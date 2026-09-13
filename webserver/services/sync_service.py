#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Data sync storage and WS broadcast for `/api/sync` (legacy record sync).

Records are stored in the `reading_records` table (one row per (reader, book_hash,
kind, record_id)), replacing the earlier one-JSON-file-per-book-per-category
scheme. Writes go through an in-memory batch buffer (`ReadingRecordBuffer`,
flushed periodically) to keep SQLite write pressure low under the client's
3-5s polling cadence; reads are buffer-aware so a user always sees their own
just-pushed data immediately, even before the next flush.

See plan/Social_Reading_Plan.md §5.2/§7 for the full design and the legacy
(file-based) → DB migration plan implemented by `migrate_legacy_data()`.
@author: PoxenStudio, 2026-06
"""

import asyncio
import dataclasses
import datetime
import json
import logging
import os
import time
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

import tornado.ioloop

from webserver import loader
from webserver.models import ReadingRecord, Reading, Reader, parse_book_id_from_reading_record_hash
from webserver.services.reading_stats_service import ReadingStatsService, parse_book_id_from_hash, parse_format_from_hash

CONF = loader.get_settings()


@dataclasses.dataclass
class _PendingRecord:
    reader_id: int
    book_hash: str
    book_id: int
    kind: str
    record_id: str
    uid: int
    payload: dict
    updated_at: int
    deleted_at: Optional[int]


class ReadingRecordBuffer:
    """In-memory write-behind buffer for `reading_records`.

    `push()` computes the final merged value for each touched record and
    stores it here; a periodic flush (see MyReaderSyncService.start()) writes
    everything to the DB in one transaction. `pull()` overlays this buffer on
    top of DB reads so the pushing user always sees their own latest data
    immediately, regardless of whether it has been flushed yet.
    """

    def __init__(self):
        self._pending: Dict[Tuple[int, str, str, str], _PendingRecord] = {}

    def put(self, reader_id, book_hash, book_id, kind, record_id, uid, payload) -> None:
        self._pending[(reader_id, book_hash, kind, record_id)] = _PendingRecord(
            reader_id=reader_id,
            book_hash=book_hash,
            book_id=book_id,
            kind=kind,
            record_id=record_id,
            uid=uid,
            payload=payload,
            updated_at=payload.get("updated_at") or 0,
            deleted_at=payload.get("deleted_at"),
        )

    def get(self, reader_id, book_hash, kind, record_id) -> Optional[dict]:
        item = self._pending.get((reader_id, book_hash, kind, record_id))
        return item.payload if item else None

    def get_own_pending(self, reader_id: int, kind: str, book_hash: Optional[str] = None) -> Dict[Tuple[str, str], dict]:
        """{(book_hash, record_id): payload} for this reader's still-unflushed records."""
        return {
            (v.book_hash, v.record_id): v.payload
            for v in self._pending.values()
            if v.reader_id == reader_id and v.kind == kind and (book_hash is None or v.book_hash == book_hash)
        }

    def is_empty(self) -> bool:
        return not self._pending

    def flush(self) -> None:
        if not self._pending:
            return
        items = list(self._pending.values())
        keys = list(self._pending.keys())
        db = ReadingRecord._session()
        try:
            for item in items:
                row = (
                    db.query(ReadingRecord)
                    .filter_by(reader_id=item.reader_id, book_hash=item.book_hash, kind=item.kind, record_id=item.record_id)
                    .one_or_none()
                )
                if row is None:
                    row = ReadingRecord(
                        reader_id=item.reader_id,
                        book_hash=item.book_hash,
                        book_id=item.book_id,
                        kind=item.kind,
                        record_id=item.record_id,
                        uid=item.uid,
                        payload=item.payload,
                        updated_at=item.updated_at,
                        deleted_at=item.deleted_at,
                    )
                    db.add(row)
                else:
                    row.book_id = item.book_id
                    row.uid = item.uid
                    row.payload = item.payload
                    row.updated_at = item.updated_at
                    row.deleted_at = item.deleted_at
            db.commit()
            # Tornado 单线程事件循环下，flush() 全程同步执行、不 await，中途不会有其它协程
            # 插入修改 self._pending，落库后可以放心按 flush 开始时的快照 key 精确清理。
            for key in keys:
                self._pending.pop(key, None)
        except Exception:
            db.rollback()
            logging.error("[sync] reading_records flush failed, %d record(s) kept for retry", len(items), exc_info=True)


class ShareAnnotationsCache:
    _disabled_uids: Optional[Set[int]] = None
    _loaded_at: float = 0.0
    _REFRESH_INTERVAL_SEC = 600

    @classmethod
    def _load(cls, db) -> Set[int]:
        disabled = set()
        for reader_id, extra in db.query(Reader.id, Reader.extra).all():
            if extra and extra.get("share_annotations") is False:
                disabled.add(reader_id)
        return disabled

    @classmethod
    def is_disabled(cls, db, uid: int) -> bool:
        now = time.time()
        if cls._disabled_uids is None or now - cls._loaded_at > cls._REFRESH_INTERVAL_SEC:
            cls._disabled_uids = cls._load(db)
            cls._loaded_at = now
        return uid in cls._disabled_uids

    @classmethod
    def set(cls, uid: int, shared: bool) -> None:
        """Called right after a reader saves their `share_annotations` preference."""
        if cls._disabled_uids is None:
            return
        if shared:
            cls._disabled_uids.discard(uid)
        else:
            cls._disabled_uids.add(uid)


class MyReaderSyncService:
    """All storage/merge logic and the WS connection registry for `/api/sync`."""

    KINDS = ("books", "configs", "notes")
    # kinds whose per-book store holds multiple records keyed by `id`;
    # the rest hold a single record per (reader, book_hash)
    _MULTI_RECORD_KINDS = {"notes"}

    # shared, process-wide state (single-instance deployment, see plan §4/§7)
    _locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
    connections: Dict[int, Set] = defaultdict(set)
    _buffer = ReadingRecordBuffer()
    _periodic_callback: Optional[tornado.ioloop.PeriodicCallback] = None
    _purge_periodic_callback: Optional[tornado.ioloop.PeriodicCallback] = None
    _PURGE_INTERVAL_MS = 24 * 3600 * 1000  # 每天清理一次软删除记录

    @staticmethod
    def is_enabled() -> bool:
        return CONF.get("ENABLE_DATA_SYNC", True)

    @staticmethod
    def set_share_annotations(uid: int, shared: bool) -> None:
        """Called by the user-settings handler right after saving
        `share_annotations`, so `_shared_notes()` picks up the change without
        waiting for `ShareAnnotationsCache`'s periodic reload."""
        ShareAnnotationsCache.set(uid, shared)

    # ---------------------------------------------------------------- pull

    @classmethod
    def _effective_records(cls, db, uid, kind, book_hash=None) -> Dict[Tuple[str, str], dict]:
        """{(book_hash, record_id): payload} for `uid`'s own records, DB rows
        overlaid by any not-yet-flushed buffer entries (buffer wins)."""
        q = db.query(ReadingRecord).filter(ReadingRecord.reader_id == uid, ReadingRecord.kind == kind)
        if book_hash:
            q = q.filter(ReadingRecord.book_hash == book_hash)
        out = {(row.book_hash, row.record_id): row.payload for row in q.all()}
        out.update(cls._buffer.get_own_pending(uid, kind, book_hash))
        return out

    @classmethod
    def _shared_notes(cls, db, uid, book_hash, since) -> List[dict]:
        """Other users' `notes` for the same book (by book_id), for `own=0` pulls.

        Only exercised when the caller scopes the pull to a single `book_hash`
        (the common "viewing this book" case) — see plan §5.2/§7.2. Reads
        straight from the DB (not buffer-overlaid), so other users' very
        latest edits may lag by up to SYNC_DB_FLUSH_INTERVAL_SEC, which is an
        accepted tradeoff (see plan §4.3).
        """
        if not CONF.get("ENABLE_SHARED_NOTES", True):
            return []
        book_id = parse_book_id_from_reading_record_hash(book_hash)
        if book_id is None or book_id <= 0:
            return []  # local/unrecognized book_hash, no cross-user notes to show
        max_users = CONF.get("SYNC_SHARED_NOTES_MAX_USERS", 20)
        rows = (
            db.query(ReadingRecord)
            .filter(ReadingRecord.kind == "notes", ReadingRecord.book_id == book_id, ReadingRecord.reader_id != uid)
            .order_by(ReadingRecord.updated_at.desc())
            .all()
        )
        allowed_uids: Set[int] = set()
        for row in rows:
            if row.uid in allowed_uids or len(allowed_uids) >= max_users:
                continue
            if ShareAnnotationsCache.is_disabled(db, row.uid):
                continue  # 该用户关闭了「分享我的阅读笔记和批注」，不参与合并
            allowed_uids.add(row.uid)
        authors = cls._authors_by_id(db, allowed_uids)
        result = []
        for row in rows:
            if row.uid not in allowed_uids or not cls._changed_since(row.payload, since):
                continue
            payload = dict(row.payload)
            author = authors.get(row.uid)
            if author:
                payload["author"] = author
            result.append(payload)
        return result

    @classmethod
    def _authors_by_id(cls, db, uids: Set[int]) -> Dict[int, dict]:
        """{uid: {"nickname", "avatar"}} for the given reader ids — attached to
        cross-user notes so myreader can show who wrote them (see
        plan/Social_Reading_Plan.md §2.2 实施调整). Avatar URL built the same
        way as UserInfo handler (webserver/handlers/user.py), but from CONF's
        `site_url` since this isn't a request handler."""
        if not uids:
            return {}
        readers = db.query(Reader).filter(Reader.id.in_(uids)).all()
        out = {}
        for reader in readers:
            avatar = ""
            if reader.avatar:
                if reader.avatar.startswith("http"):
                    gravatar_url = "https://www.gravatar.com"
                    avatar = reader.avatar.replace("http://", "https://").replace(gravatar_url, CONF.get("avatar_service", ""))
                else:
                    avatar = CONF.get("site_url", "") + "/avatar/%s" % reader.avatar
            out[reader.id] = {"nickname": reader.name or "", "avatar": avatar}
        return out

    @classmethod
    def pull(cls, uid, since: int, type_: Optional[str] = None, book_hash: Optional[str] = None, own: int = 1) -> dict:
        result = {"books": None, "notes": None, "configs": None}
        kinds = (type_,) if type_ else cls.KINDS
        db = ReadingRecord._session()
        for kind in kinds:
            own_map = cls._effective_records(db, uid, kind, book_hash)
            items = [payload for payload in own_map.values() if cls._changed_since(payload, since)]
            if kind == "notes" and int(own) == 0 and book_hash:
                items.extend(cls._shared_notes(db, uid, book_hash, since))
            result[kind] = items
        return result

    # ---------------------------------------------------------------- merge

    @staticmethod
    def _merge_one(existing: Optional[dict], incoming: dict):
        """Last-write-wins merge. Returns (merged_record, was_applied)."""
        if existing is None:
            return incoming, True
        old_ts = existing.get("updated_at")
        new_ts = incoming.get("updated_at")
        if new_ts is not None and (old_ts is None or new_ts >= old_ts):
            merged = dict(existing)
            merged.update(incoming)
            return merged, True
        return existing, False

    @staticmethod
    def _changed_since(record: dict, since: int) -> bool:
        updated_at = record.get("updated_at")
        deleted_at = record.get("deleted_at")
        return (updated_at is not None and updated_at > since) or (deleted_at is not None and deleted_at > since)

    @classmethod
    def _get_lock(cls, uid) -> asyncio.Lock:
        return cls._locks[uid]

    @classmethod
    def _stage(cls, uid, book_hash, kind, record_id, payload) -> None:
        book_id = parse_book_id_from_reading_record_hash(book_hash)
        cls._buffer.put(uid, book_hash, book_id, kind, record_id, uid, payload)

    @classmethod
    def _push_book_records(cls, db, uid, book_hash: str, kind: str, incoming_records: list):
        """Merge incoming records for one (book_hash, kind) into the effective
        (buffer-overlaid DB) state. Returns (merged_records_for_response, was_applied)."""
        if kind in cls._MULTI_RECORD_KINDS:
            store = cls._effective_records(db, uid, kind, book_hash)  # {(book_hash, id): payload}
            merged_list = []
            applied_any = False
            for incoming in incoming_records:
                key = incoming.get("id")
                if not key:
                    logging.debug("[sync] note record without id for user %s, book %s", uid, book_hash)
                    continue
                incoming_uid = incoming.get("uid")
                if incoming_uid and incoming_uid != uid:
                    # own=0 拉取会把其他用户的共读 notes 一并混入客户端本地数据，客户端保存/推送时
                    # 有概率把这些别人的条目原样带回来；这里按 uid 过滤掉，避免把别人的 note 误存成
                    # 当前用户自己的一条记录（reader_id 仍是 uid，但 payload.uid 会挂着别人的身份）。
                    logging.debug(
                        "[sync] drop note %s for user %s book %s: belongs to uid %s", key, uid, book_hash, incoming_uid
                    )
                    continue
                if not incoming_uid:
                    # 需求要求 notes 内每一项数据都带 uid，标注是谁做的；调用方没传时兜底补当前用户
                    incoming = dict(incoming)
                    incoming["uid"] = uid
                merged, applied = cls._merge_one(store.get((book_hash, key)), incoming)
                store[(book_hash, key)] = merged
                merged_list.append(merged)
                if applied:
                    cls._stage(uid, book_hash, kind, key, merged)
                    applied_any = True
            return merged_list, applied_any

        store = cls._effective_records(db, uid, kind, book_hash)
        existing = store.get((book_hash, book_hash))  # books/configs: 一个 (reader, book_hash) 只有一条，record_id 复用 book_hash
        merged = existing
        applied_any = False
        for incoming in incoming_records:
            merged, applied = cls._merge_one(merged, incoming)
            applied_any = applied_any or applied
        if applied_any:
            cls._stage(uid, book_hash, kind, book_hash, merged)
        return ([merged] if merged is not None else []), applied_any

    @staticmethod
    def _extract_progress(book_merged: list) -> Optional[Tuple[int, int]]:
        if not book_merged:
            return None
        raw_progress = book_merged[-1].get("progress")
        if not (isinstance(raw_progress, (list, tuple)) and len(raw_progress) == 2):
            return None
        try:
            current, total = int(raw_progress[0]), int(raw_progress[1])
        except (TypeError, ValueError):
            return None
        return (current, total) if total > 0 else None

    @staticmethod
    def _parse_reading_seconds(raw) -> Dict[str, List[Tuple["datetime.date", int]]]:
        """客户端离线阅读显式上报（见 document/Reading_Stats_Design.md 的离线阅读扩展）：
        [{"book_hash": ..., "date": "YYYY-MM-DD", "seconds": N}, ...]，一本书一次 push
        里可以带多天（跨天离线场景）。日期由客户端上报前转换成 UTC，这里不再转换，只
        做格式/范围校验。"""
        result: Dict[str, List[Tuple[datetime.date, int]]] = defaultdict(list)
        for entry in raw or []:
            if not isinstance(entry, dict):
                continue
            book_hash = entry.get("book_hash")
            date_str = entry.get("date")
            if not book_hash or not date_str:
                continue
            try:
                date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                seconds = int(entry.get("seconds"))
            except (TypeError, ValueError):
                logging.warning("[sync] drop malformed reading_seconds entry: %r", entry)
                continue
            if seconds <= 0:
                continue
            result[book_hash].append((date, seconds))
        return result

    @classmethod
    async def push(cls, uid, payload: dict) -> dict:
        result = {}
        changed_scopes = set()
        reading_seconds_by_book = cls._parse_reading_seconds(payload.get("reading_seconds"))
        async with cls._get_lock(uid):
            db = ReadingRecord._session()
            configs_progress_by_book: Dict[str, Optional[Tuple[int, int]]] = {}
            for kind in cls.KINDS:
                records = payload.get(kind) or []
                if not records:
                    continue
                by_book = defaultdict(list)
                for incoming in records:
                    book_hash = incoming.get("book_hash")
                    if not book_hash:
                        continue
                    by_book[book_hash].append(incoming)
                merged_list = []
                for book_hash, incoming_records in by_book.items():
                    book_merged, applied = cls._push_book_records(db, uid, book_hash, kind, incoming_records)
                    merged_list.extend(book_merged)
                    if applied:
                        changed_scopes.add((kind, book_hash))
                    if kind == "configs":
                        # configs 记录（阅读进度/位置）是"仍在阅读"的信号，见
                        # document/Reading_Stats_Design.md §3.1；books/notes 的 push 不触发。
                        progress = cls._extract_progress(book_merged)
                        configs_progress_by_book[book_hash] = progress
                        # 这次 push 带了这本书的显式时长时，交给下面统一处理，不在这里再
                        # 走心跳到达间隔推算——否则同一段时间会被两条路径各计一次。
                        if applied and book_hash not in reading_seconds_by_book:
                            book_id = parse_book_id_from_hash(book_hash)
                            if book_id is not None:
                                fmt = parse_format_from_hash(book_hash)
                                ReadingStatsService.heartbeat(uid, book_id, Reading.PROTOCOL_APP, fmt=fmt, progress=progress)
                if merged_list:
                    result[kind] = merged_list

            # 离线阅读显式上报：与上面的心跳路径互斥（见 _parse_reading_seconds 用法处的
            # 注释），不依赖这次 push 里 configs 是否有实际变化——用户可能全程停在同一页，
            # 但确实读了这么久。
            for book_hash, entries in reading_seconds_by_book.items():
                book_id = parse_book_id_from_hash(book_hash)
                if book_id is None:
                    continue
                fmt = parse_format_from_hash(book_hash)
                progress = configs_progress_by_book.get(book_hash)
                for date, seconds in entries:
                    ReadingStatsService.report_duration(uid, book_id, Reading.PROTOCOL_APP, date, seconds, fmt=fmt, progress=progress)
        for scope, book_hash in changed_scopes:
            cls.broadcast_changed(uid, scope, book_hash)
        return result

    # -------------------------------------------------------- legacy migration

    @classmethod
    def migrate_legacy_data(cls) -> None:
        """Scan `MYREADER_SYNC_PATH` for legacy `<uid>/<book_hash>/{kind}.json`
        files and import them into `reading_records`, deleting each directory
        as it's fully migrated. Safe to call repeatedly (idempotent, resumable
        after a crash) and safe to run while the service is live-serving
        push/pull (per-uid lock shared with push()). See plan §7.1."""
        root = CONF.get("MYREADER_SYNC_PATH", "/data/sync/")
        if not os.path.isdir(root):
            cls._mark_migration_done()
            return

        uid_dirs = [name for name in os.listdir(root) if os.path.isdir(os.path.join(root, name))]
        if not uid_dirs:
            cls._mark_migration_done()
            return

        loop = asyncio.new_event_loop()
        try:
            for name in uid_dirs:
                try:
                    uid = int(name)
                except ValueError:
                    logging.warning("[sync] skip non-numeric sync dir during migration: %s", name)
                    continue
                try:
                    loop.run_until_complete(cls._migrate_user(uid, os.path.join(root, name)))
                except Exception:
                    logging.error("[sync] migration failed for user %s, will retry next startup", uid, exc_info=True)
        finally:
            loop.close()

        if not any(os.path.isdir(os.path.join(root, name)) for name in os.listdir(root)):
            cls._mark_migration_done()

    @classmethod
    def _mark_migration_done(cls) -> None:
        if CONF.get("SYNC_LEGACY_MIGRATION_DONE", False):
            return
        CONF["SYNC_LEGACY_MIGRATION_DONE"] = True
        try:
            from webserver.base.setting_saver import SettingsSaver
            SettingsSaver().save_partial({"SYNC_LEGACY_MIGRATION_DONE": True})
        except Exception:
            logging.error("[sync] failed to persist SYNC_LEGACY_MIGRATION_DONE, will re-scan next startup", exc_info=True)
        logging.info("[sync] legacy file-based sync data fully migrated to reading_records")

    @classmethod
    async def _migrate_user(cls, uid: int, user_dir: str) -> None:
        async with cls._get_lock(uid):
            db = ReadingRecord._session()
            for book_hash in [n for n in os.listdir(user_dir) if os.path.isdir(os.path.join(user_dir, n))]:
                book_dir = os.path.join(user_dir, book_hash)
                book_id = parse_book_id_from_reading_record_hash(book_hash)
                try:
                    for kind in cls.KINDS:
                        path = os.path.join(book_dir, f"{kind}.json")
                        if not os.path.exists(path):
                            continue
                        data = cls._load_legacy_json(path)
                        if data is None:
                            continue
                        if kind in cls._MULTI_RECORD_KINDS:
                            for record_id, record in data.items():
                                if not isinstance(record, dict):
                                    continue
                                if not record.get("uid"):
                                    record = dict(record)
                                    record["uid"] = uid
                                cls._migrate_upsert(db, uid, book_hash, book_id, kind, record_id, record)
                        elif isinstance(data, dict):
                            cls._migrate_upsert(db, uid, book_hash, book_id, kind, book_hash, data)
                    db.commit()
                except Exception:
                    db.rollback()
                    logging.error("[sync] migration failed for user %s book %s, directory kept for retry", uid, book_hash, exc_info=True)
                    continue
                # 三个文件都已成功落库（或本来就不存在），删除该书目录
                import shutil
                shutil.rmtree(book_dir, ignore_errors=True)
            # 该用户所有 book_hash 子目录都处理完（已清空）才删除用户目录
            if not os.listdir(user_dir):
                try:
                    os.rmdir(user_dir)
                except OSError:
                    pass

    @staticmethod
    def _load_legacy_json(path: str):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            logging.error("[sync] failed to read legacy sync file %s during migration, skipping", path, exc_info=True)
            return None

    @staticmethod
    def _migrate_upsert(db, uid, book_hash, book_id, kind, record_id, payload) -> None:
        """Last-write-wins upsert straight to DB (bypasses the write buffer —
        migration runs once at startup, not on the request hot path)."""
        row = db.query(ReadingRecord).filter_by(reader_id=uid, book_hash=book_hash, kind=kind, record_id=record_id).one_or_none()
        existing_payload = row.payload if row else None
        merged, applied = MyReaderSyncService._merge_one(existing_payload, payload)
        if not applied:
            return
        if row is None:
            row = ReadingRecord(
                reader_id=uid, book_hash=book_hash, book_id=book_id, kind=kind, record_id=record_id,
                uid=uid, payload=merged, updated_at=merged.get("updated_at") or 0, deleted_at=merged.get("deleted_at"),
            )
            db.add(row)
        else:
            row.book_id = book_id
            row.uid = uid
            row.payload = merged
            row.updated_at = merged.get("updated_at") or 0
            row.deleted_at = merged.get("deleted_at")

    # --------------------------------------------------------- periodic flush

    @classmethod
    def flush_now(cls) -> None:
        cls._buffer.flush()

    @classmethod
    def purge_soft_deleted(cls) -> None:
        """Physically delete `reading_records` rows soft-deleted (`deleted_at`
        set) longer than `SYNC_SOFT_DELETE_RETENTION_DAYS` ago.

        Only `notes` genuinely accumulates one row per record (books/configs
        are single-row-per-book, always overwritten in place — see
        `_push_book_records`), and soft-deleted notes were otherwise kept
        forever, so this is the only thing standing between "delete a note"
        and unbounded table growth.
        """
        retention_days = CONF.get("SYNC_SOFT_DELETE_RETENTION_DAYS", 7)
        if retention_days <= 0:
            return
        cutoff_ms = int(time.time() * 1000) - retention_days * 24 * 3600 * 1000
        db = ReadingRecord._session()
        try:
            deleted = (
                db.query(ReadingRecord)
                .filter(ReadingRecord.deleted_at.isnot(None), ReadingRecord.deleted_at < cutoff_ms)
                .delete(synchronize_session=False)
            )
            db.commit()
            if deleted:
                logging.info("[sync] purged %d soft-deleted reading_records row(s) older than %d day(s)", deleted, retention_days)
        except Exception:
            db.rollback()
            logging.error("[sync] purge_soft_deleted failed, will retry next cycle", exc_info=True)

    @classmethod
    def start(cls) -> None:
        if cls._periodic_callback is None:
            interval_ms = CONF.get("SYNC_DB_FLUSH_INTERVAL_SEC", 5) * 1000
            cls._periodic_callback = tornado.ioloop.PeriodicCallback(cls.flush_now, interval_ms)
            cls._periodic_callback.start()
            logging.info("[sync] reading_records write buffer started, flushing every %sms", interval_ms)
        if cls._purge_periodic_callback is None:
            cls._purge_periodic_callback = tornado.ioloop.PeriodicCallback(cls.purge_soft_deleted, cls._PURGE_INTERVAL_MS)
            cls._purge_periodic_callback.start()
            tornado.ioloop.IOLoop.current().call_later(0, cls.purge_soft_deleted)  # 启动时先跑一次，之后每天一次
            logging.info("[sync] reading_records soft-delete purge started, running every %sms", cls._PURGE_INTERVAL_MS)

    @classmethod
    def stop(cls) -> None:
        if cls._periodic_callback is not None:
            cls._periodic_callback.stop()
            cls._periodic_callback = None
        if cls._purge_periodic_callback is not None:
            cls._purge_periodic_callback.stop()
            cls._purge_periodic_callback = None
        cls.flush_now()
        logging.info("[sync] reading_records write buffer stopped, final flush done")

    # ------------------------------------------------------------------- WS

    @classmethod
    def register_connection(cls, uid, ws) -> None:
        cls.connections[uid].add(ws)

    @classmethod
    def unregister_connection(cls, uid, ws) -> None:
        cls.connections[uid].discard(ws)

    @classmethod
    def broadcast_changed(cls, uid, scope: str, book_hash: Optional[str], exclude=None) -> None:
        message = json.dumps({
            "type": "changed",
            "scope": scope,
            "bookHash": book_hash,
            "ts": int(time.time() * 1000),
        })
        for ws in list(cls.connections.get(uid, ())):
            if ws is exclude:
                continue
            try:
                ws.write_message(message)
            except Exception:
                logging.warning("[sync] ws broadcast failed, connection will be cleaned up on disconnect", exc_info=True)
