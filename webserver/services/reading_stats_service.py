#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Reading/download/push activity tracking, feeding webserver.models.Reading and
the Reader.total_reading_seconds/download_count aggregates.

Writes never hit the DB synchronously — heartbeat()/record_download()/
record_push() only touch an in-process memory buffer
"""

import datetime
import logging
import re
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import tornado.ioloop
from sqlalchemy import func, text, update

from webserver import loader
from webserver.models import BookReadingStats, Item, ManualReadingLog, Reader, Reading
from webserver.services import reading_dashboard_service
from webserver.services.reader_cache import ReaderStatsCache

CONF = loader.get_settings()

HEARTBEAT_MAX_GAP = datetime.timedelta(seconds=60)

MANUAL_READING_MAX_SECONDS = 18 * 3600
FORMAT_PREFERENCE_ORDER = ("epub", "azw3", "mobi", "azw", "docx", "pdf", "txt")

# 阅读进度达到该百分比即视为"读完"，自动把 BookReadingStats.state 置为 FINISHED
# （epub 分页误差下很多书读到最后一页也算不满 100%）
FINISH_PROGRESS_THRESHOLD = 99.5

# MyBooks 云端书籍的 book_hash 形如 "cloud-8502-epub"，8502 是 book_id，"epub" 是格式；
# 不匹配这个格式的视为本地书籍，本轮不统计。
_CLOUD_BOOK_HASH_RE = re.compile(r"^cloud-(\d+)-([a-zA-Z0-9]+)$")


def parse_format_from_hash(book_hash: Optional[str]) -> Optional[str]:
    if not book_hash:
        return None
    m = _CLOUD_BOOK_HASH_RE.match(book_hash)
    if not m:
        return None
    return m.group(2).lower()


def parse_book_id_from_hash(book_hash: Optional[str]) -> Optional[int]:
    if not book_hash:
        return None
    m = _CLOUD_BOOK_HASH_RE.match(book_hash)
    if not m:
        return None
    return int(m.group(1))


@dataclass
class _PendingSession:
    """跟踪一个 (reader_id, book_id) 当前"打开中"的 Reading(action=read) 天级行。

    current_date 标识现在缓冲的是哪一天的行；日期变化（跨天）或心跳间隔超过
    HEARTBEAT_MAX_GAP 都会重置为一行新的天级记录（duration_delta 清零、dirty=True）。
    """

    current_date: datetime.date
    session_start: datetime.datetime
    last_seen: datetime.datetime
    protocol: str
    duration_delta: int = 0
    dirty: bool = False
    # 是否已经确认过 Item.count_visit 的首次阅读计数（按 current_date 这一天判定一次，
    # 跨天/新开一行时会随 current_date 一起重置为 False）
    visit_counted: bool = False


@dataclass
class _PendingEvent:
    reader_id: int
    book_id: int
    action: str
    protocol: str
    now_utc: datetime.datetime


class ReadingWriteBuffer:
    """In-memory buffer for reading heartbeats / download / push events.

    Flushed periodically (see ReadingStatsService.start()) in a single DB
    transaction, to avoid one SQLite commit per heartbeat under load.
    """

    def __init__(self):
        self._sessions: Dict[Tuple[int, int], _PendingSession] = {}
        self._events: List[_PendingEvent] = []
        self._reader_seconds_delta: Dict[int, int] = {}
        self._reader_download_delta: Dict[int, int] = {}
        self._reader_push_delta: Dict[int, int] = {}
        self._lock = threading.Lock()

    def on_heartbeat(self, reader_id: int, book_id: int, protocol: str, now_utc: datetime.datetime) -> None:
        with self._lock:
            key = (reader_id, book_id)
            session = self._sessions.get(key)
            today = now_utc.date()
            logging.debug(f"[Heartbeat] {reader_id} on {book_id}")
            # 三种情况都视为"开启一行新的天级记录"：从未见过这本书的心跳、日期跨天了、
            # 或者心跳间隔超过阈值（新的一次阅读会话）。跨天时丢弃这次心跳的 delta（最多
            # 相当于一个心跳周期的误差，可接受，见 document/Reading_Stats_Design.md §11.4）。
            is_new_bucket = session is None or session.current_date != today or (now_utc - session.last_seen) > HEARTBEAT_MAX_GAP
            if is_new_bucket:
                self._sessions[key] = _PendingSession(
                    current_date=today, session_start=now_utc, last_seen=now_utc, protocol=protocol, duration_delta=0, dirty=True
                )
                logging.debug("[Heartbeat] Found the new session!")
                return
            delta = int((now_utc - session.last_seen).total_seconds())
            session.duration_delta += delta
            session.last_seen = now_utc
            session.protocol = protocol
            if delta:
                self._reader_seconds_delta[reader_id] = self._reader_seconds_delta.get(reader_id, 0) + delta

    def on_event(self, reader_id: int, book_id: int, action: str, protocol: str, now_utc: datetime.datetime) -> None:
        with self._lock:
            self._events.append(_PendingEvent(reader_id, book_id, action, protocol, now_utc))
            if action == Reading.ACTION_DOWNLOAD:
                self._reader_download_delta[reader_id] = self._reader_download_delta.get(reader_id, 0) + 1
            elif action == Reading.ACTION_PUSH:
                self._reader_push_delta[reader_id] = self._reader_push_delta.get(reader_id, 0) + 1

    def flush(self) -> None:
        with self._lock:
            pending = []  # (reader_id, book_id, date, session_start, duration_delta, last_seen, protocol)
            visit_check_keys = []  # (reader_id, book_id, date)
            for (reader_id, book_id), s in self._sessions.items():
                if s.duration_delta or s.dirty:
                    pending.append((reader_id, book_id, s.current_date, s.session_start, s.duration_delta, s.last_seen, s.protocol))
                    if not s.visit_counted:
                        visit_check_keys.append((reader_id, book_id, s.current_date))
            for s in self._sessions.values():
                s.duration_delta = 0
                s.dirty = False
            events_snapshot, self._events = self._events, []
            seconds_delta, self._reader_seconds_delta = self._reader_seconds_delta, {}
            download_delta, self._reader_download_delta = self._reader_download_delta, {}
            push_delta, self._reader_push_delta = self._reader_push_delta, {}

        if not (pending or events_snapshot or seconds_delta or download_delta or push_delta):
            return

        db = Reading._session()
        try:
            # Item.count_visit = 唯一打开次数：这本书对这个 reader 在这一天第一次真正
            # 落库 action=read 记录时才 +1（不同天再打开也各算一次），需要在 upsert
            # 前查一次这一天的行是否已存在。
            book_visit_delta: Dict[int, int] = {}
            for reader_id, book_id, date in visit_check_keys:
                exists = (
                    db.query(Reading.id)
                    .filter(
                        Reading.reader_id == reader_id,
                        Reading.book_id == book_id,
                        Reading.action == Reading.ACTION_READ,
                        Reading.date == date,
                    )
                    .first()
                )
                if exists is None:
                    book_visit_delta[book_id] = book_visit_delta.get(book_id, 0) + 1

            for reader_id, book_id, date, session_start, duration_delta, last_seen, protocol in pending:
                db.execute(
                    text(
                        """
                        INSERT INTO readings (reader_id, book_id, action, protocol, date, start_time, duration, update_time)
                        VALUES (:reader_id, :book_id, 'read', :protocol, :date, :start_time, :duration, :update_time)
                        ON CONFLICT(reader_id, book_id, date) WHERE action='read' DO UPDATE SET
                            duration = duration + excluded.duration,
                            update_time = excluded.update_time,
                            start_time = excluded.start_time,
                            protocol = excluded.protocol
                        """
                    ),
                    dict(
                        reader_id=reader_id,
                        book_id=book_id,
                        date=date,
                        protocol=protocol,
                        start_time=session_start,
                        duration=duration_delta,
                        update_time=last_seen,
                    ),
                )

            # Item.count_download = 下载 + 推送新增的 Reading 事件行数（两者都算，见
            # document/Reading_Stats_Design.md 与后续澄清；Reader.download_count 仍只算真实下载）
            book_download_delta: Dict[int, int] = {}
            for evt in events_snapshot:
                db.add(Reading(evt.reader_id, evt.book_id, evt.action, evt.protocol, evt.now_utc))
                if evt.action in (Reading.ACTION_DOWNLOAD, Reading.ACTION_PUSH):
                    book_download_delta[evt.book_id] = book_download_delta.get(evt.book_id, 0) + 1

            for reader_id, delta in seconds_delta.items():
                db.execute(
                    update(Reader).where(Reader.id == reader_id).values(total_reading_seconds=Reader.total_reading_seconds + delta)
                )
            for reader_id, delta in download_delta.items():
                db.execute(update(Reader).where(Reader.id == reader_id).values(download_count=Reader.download_count + delta))
            for reader_id, delta in push_delta.items():
                db.execute(update(Reader).where(Reader.id == reader_id).values(push_count=Reader.push_count + delta))

            for book_id in set(book_visit_delta) | set(book_download_delta):
                item = db.query(Item).filter(Item.book_id == book_id).one_or_none()
                if item is None:
                    item = Item()
                    item.book_id = book_id
                item.count_visit += book_visit_delta.get(book_id, 0)
                item.count_download += book_download_delta.get(book_id, 0)
                db.add(item)

            db.commit()
            if visit_check_keys:
                with self._lock:
                    for reader_id, book_id, date in visit_check_keys:
                        session = self._sessions.get((reader_id, book_id))
                        # 只有 flush 期间没有再被心跳跨天/开新会话覆盖时才标记，
                        # 否则这个 date 对应的 bucket 已经不是当前打开的那个了。
                        if session is not None and session.current_date == date:
                            session.visit_counted = True
        except Exception:
            db.rollback()
            logging.error("[reading_stats] flush failed, data kept for retry on next tick", exc_info=True)
            with self._lock:
                for reader_id, book_id, date, session_start, duration_delta, last_seen, protocol in pending:
                    session = self._sessions.get((reader_id, book_id))
                    if session is not None and session.current_date == date:
                        session.duration_delta += duration_delta
                        session.dirty = True
                    # 否则这一天的 bucket 已经因为跨天/新会话被覆盖，这次失败的增量随之丢弃
                    # （见 document/Reading_Stats_Design.md §11.4，属于已知的、有界的近似误差）
                self._events = events_snapshot + self._events
                for reader_id, delta in seconds_delta.items():
                    self._reader_seconds_delta[reader_id] = self._reader_seconds_delta.get(reader_id, 0) + delta
                for reader_id, delta in download_delta.items():
                    self._reader_download_delta[reader_id] = self._reader_download_delta.get(reader_id, 0) + delta
                for reader_id, delta in push_delta.items():
                    self._reader_push_delta[reader_id] = self._reader_push_delta.get(reader_id, 0) + delta


@dataclass
class _PendingFormatState:
    """跟踪一个 (reader_id, book_id, format) 自上次 flush 以来尚未落库的心跳增量。
    """

    last_seen: datetime.datetime
    duration_delta: int = 0
    progress: Optional[Tuple[int, int]] = None
    touched: bool = False


def apply_book_format_update(
    db,
    reader_id: int,
    book_id: int,
    fmt: str,
    now_utc: datetime.datetime,
    duration_delta: int = 0,
    progress: Optional[Tuple[int, int]] = None,
    start_time: Optional[datetime.datetime] = None,
    finish_time: Optional[datetime.datetime] = None,
    state: Optional[int] = None,
) -> BookReadingStats:
    """Insert-or-update the one BookReadingStats row for (reader_id, book_id, fmt).

    Shared by BookFormatStatsBuffer.flush() (automatic heartbeats) and the
    manual POST /api/book/<id>/reading_stats endpoint (and its MCP tool
    counterpart), so both paths apply the exact same "new round"/"finished"
    rules.
    """
    row = db.query(BookReadingStats).filter_by(reader_id=reader_id, book_id=book_id, format=fmt).one_or_none()
    # 已完成状态下，只有真的又花了时间阅读（duration_delta > 0）才判定为"又开始读一轮"——
    # 单纯重复上报同样的进度（比如读完后又打开看了一眼但没翻页）不应该把 start_count 再 +1。
    is_new_round = row is None or (row.state == BookReadingStats.STATE_FINISHED and duration_delta > 0)
    if row is None:
        row = BookReadingStats(reader_id=reader_id, book_id=book_id, format=fmt, create_time=now_utc, update_time=now_utc)
        db.add(row)
    if start_time is not None:
        # 显式指定开始时间：总是视为开启新一轮，即使当前还在读（用于导入历史数据/手工纠正）
        is_new_round = True
    if is_new_round:
        row.start_time = start_time or now_utc
        row.finish_time = None
        row.state = BookReadingStats.STATE_READING
        row.start_count = (row.start_count or 0) + 1

    row.total_seconds = (row.total_seconds or 0) + max(duration_delta, 0)
    row.update_time = now_utc

    if progress is not None:
        current, total = progress
        row.progress_current = current
        row.progress_total = total
        if total:
            row.progress_percent = round(current * 100.0 / total, 2)
        if row.progress_percent is not None and row.progress_percent >= FINISH_PROGRESS_THRESHOLD:
            row.state = BookReadingStats.STATE_FINISHED
            row.finish_time = row.finish_time or now_utc

    if finish_time is not None:
        row.state = BookReadingStats.STATE_FINISHED
        row.finish_time = finish_time
    elif state is not None:
        row.state = state
        if state == BookReadingStats.STATE_FINISHED:
            row.finish_time = row.finish_time or now_utc
        else:
            row.finish_time = None

    return row


def _resolve_manual_format(db, reader_id: int, book_id: int, available_formats: Optional[List[str]]) -> Optional[str]:
    row = (
        db.query(BookReadingStats)
        .filter(BookReadingStats.reader_id == reader_id, BookReadingStats.book_id == book_id)
        .order_by(BookReadingStats.total_seconds.desc())
        .first()
    )
    if row is not None:
        return row.format
    formats = {f.lower() for f in (available_formats or [])}
    for fmt in FORMAT_PREFERENCE_ORDER:
        if fmt in formats:
            return fmt
    return next(iter(formats), None)


def _adjust_reading_bucket(db, reader_id: int, book_id: int, date: datetime.date, delta: int, now_utc: datetime.datetime) -> None:
    if not delta:
        return
    row = db.query(Reading).filter_by(reader_id=reader_id, book_id=book_id, date=date, action=Reading.ACTION_READ).one_or_none()
    if row is None:
        if delta > 0:
            db.add(
                Reading(
                    reader_id, book_id, Reading.ACTION_READ, Reading.PROTOCOL_WEB,
                    start_time=datetime.datetime.combine(date, datetime.time.min), duration=delta, update_time=now_utc, date=date
                )
            )
        return
    row.duration = max(0, (row.duration or 0) + delta)
    row.update_time = now_utc


def _adjust_book_format_total(db, reader_id: int, book_id: int, fmt: str, delta: int, now_utc: datetime.datetime) -> None:
    if not delta:
        return
    row = db.query(BookReadingStats).filter_by(reader_id=reader_id, book_id=book_id, format=fmt).one_or_none()
    if row is None:
        if delta <= 0:
            return
        row = BookReadingStats(
            reader_id=reader_id, book_id=book_id, format=fmt, state=BookReadingStats.STATE_READING,
            start_time=now_utc, start_count=1, create_time=now_utc, update_time=now_utc
        )
        db.add(row)
    row.total_seconds = max(0, (row.total_seconds or 0) + delta)
    row.update_time = now_utc


def _adjust_reader_total(db, reader_id: int, delta: int) -> None:
    if not delta:
        return
    reader = db.query(Reader).get(reader_id)
    if reader is not None:
        reader.total_reading_seconds = max(0, (reader.total_reading_seconds or 0) + delta)


class ManualReadingService:
    """管理菜单"阅读时间补录"：新增/编辑/删除都以 ManualReadingLog 这一行为准，按差值
    同步到 Reading 分桶、BookReadingStats、Reader.total_reading_seconds 三处聚合。
    """

    @classmethod
    def get_reference(cls, reader_id: int, book_id: int, date: datetime.date) -> dict:
        db = Reading._session()
        entry = db.query(ManualReadingLog).filter_by(reader_id=reader_id, book_id=book_id, date=date).one_or_none()
        reading_row = db.query(Reading).filter_by(reader_id=reader_id, book_id=book_id, date=date, action=Reading.ACTION_READ).one_or_none()
        book_total = db.query(func.sum(BookReadingStats.total_seconds)).filter_by(reader_id=reader_id, book_id=book_id).scalar()
        total_seconds = reading_row.duration if reading_row else 0
        manual_seconds = entry.duration_seconds if entry else 0
        natural_seconds = max(0, total_seconds - manual_seconds)
        logging.info(f"For book id:{book_id}, date:{date}, reading duration:{reading_row.duration if reading_row else 0}, manual:{manual_seconds}")
        return {
            "entry": entry.format_dict() if entry else None,
            "date_recorded_seconds": natural_seconds,
            "manual_recorded_seconds": manual_seconds,
            "book_total_seconds": int(book_total or 0),
        }

    @classmethod
    def upsert_entry(
        cls,
        reader_id: int,
        book_id: int,
        date: datetime.date,
        duration_seconds: int,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        available_formats: Optional[List[str]] = None,
    ) -> dict:
        duration_seconds = max(0, min(int(duration_seconds), MANUAL_READING_MAX_SECONDS))
        db = Reading._session()
        now_utc = datetime.datetime.utcnow()
        row = db.query(ManualReadingLog).filter_by(reader_id=reader_id, book_id=book_id, date=date).one_or_none()
        old_duration = row.duration_seconds if row else 0
        fmt = row.format if row else _resolve_manual_format(db, reader_id, book_id, available_formats)
        if not fmt:
            raise ValueError("no ebook format available for manual reading log")

        if row is None:
            row = ManualReadingLog(reader_id=reader_id, book_id=book_id, format=fmt, date=date, create_time=now_utc)
            db.add(row)
        row.start_time = start_time
        row.end_time = end_time
        row.duration_seconds = duration_seconds
        row.update_time = now_utc

        delta = duration_seconds - old_duration
        _adjust_reading_bucket(db, reader_id, book_id, date, delta, now_utc)
        _adjust_book_format_total(db, reader_id, book_id, fmt, delta, now_utc)
        _adjust_reader_total(db, reader_id, delta)
        db.commit()

        reading_dashboard_service.patch_cached_day(reader_id, date, delta)
        return {"entry": row.format_dict()}

    @classmethod
    def delete_entry(cls, reader_id: int, book_id: int, date: datetime.date) -> dict:
        db = Reading._session()
        now_utc = datetime.datetime.utcnow()
        row = db.query(ManualReadingLog).filter_by(reader_id=reader_id, book_id=book_id, date=date).one_or_none()
        if row is None:
            return {"deleted": False}

        delta = -row.duration_seconds
        fmt = row.format
        db.delete(row)
        _adjust_reading_bucket(db, reader_id, book_id, date, delta, now_utc)
        _adjust_book_format_total(db, reader_id, book_id, fmt, delta, now_utc)
        _adjust_reader_total(db, reader_id, delta)
        db.commit()

        reading_dashboard_service.patch_cached_day(reader_id, date, delta)
        return {"deleted": True}


class BookFormatStatsBuffer:
    """In-memory write-behind buffer for BookReadingStats heartbeats.

    Flushed on the same PeriodicCallback tick as ReadingWriteBuffer (see
    ReadingStatsService.flush_now()).
    """

    def __init__(self):
        self._states: Dict[Tuple[int, int, str], _PendingFormatState] = {}
        self._lock = threading.Lock()

    def on_heartbeat(self, reader_id: int, book_id: int, fmt: str, progress: Optional[Tuple[int, int]], now_utc: datetime.datetime) -> None:
        with self._lock:
            key = (reader_id, book_id, fmt)
            state = self._states.get(key)
            if state is None:
                self._states[key] = _PendingFormatState(last_seen=now_utc, progress=progress, touched=True)
                logging.debug(f"Found new session for {book_id} ({reader_id}), fmt:{fmt}")
                return
            gap = now_utc - state.last_seen
            if gap <= HEARTBEAT_MAX_GAP:
                state.duration_delta += int(gap.total_seconds())
            state.last_seen = now_utc
            if progress is not None:
                state.progress = progress
            state.touched = True
            logging.debug(f"[Heartbeat] update time to {state.duration_delta} for {book_id} ({reader_id}), fmt:{fmt}")

    def flush(self) -> None:
        with self._lock:
            pending = [
                (key, s.duration_delta, s.progress, s.last_seen) for key, s in self._states.items() if s.touched or s.duration_delta
            ]
            for s in self._states.values():
                s.duration_delta = 0
                s.touched = False
        if not pending:
            return

        db = Reading._session()
        try:
            for (reader_id, book_id, fmt), duration_delta, progress, last_seen in pending:
                apply_book_format_update(db, reader_id, book_id, fmt, last_seen, duration_delta=duration_delta, progress=progress)
            db.commit()
        except Exception:
            db.rollback()
            logging.error("[reading_stats] book_format flush failed, data kept for retry on next tick", exc_info=True)
            with self._lock:
                for (reader_id, book_id, fmt), duration_delta, progress, last_seen in pending:
                    state = self._states.get((reader_id, book_id, fmt))
                    if state is not None:
                        state.duration_delta += duration_delta
                        state.touched = True
                        # progress 留用内存里更新的最新值即可，不需要把旧值塞回去


class ReadingStatsService:
    """Public entry points used by sync_service/book.py/webdav/mcp."""

    _buffer = ReadingWriteBuffer()
    _format_buffer = BookFormatStatsBuffer()
    _periodic_callback: Optional[tornado.ioloop.PeriodicCallback] = None

    @classmethod
    def heartbeat(
        cls,
        reader_id: int,
        book_id: int,
        protocol: str,
        fmt: Optional[str] = None,
        progress: Optional[Tuple[int, int]] = None,
    ) -> None:
        if not ReaderStatsCache().get_allow_statistic(reader_id):
            return
        cls._buffer.on_heartbeat(reader_id, book_id, protocol, datetime.datetime.utcnow())
        if fmt:
            cls._format_buffer.on_heartbeat(reader_id, book_id, fmt.lower(), progress, datetime.datetime.utcnow())

    @classmethod
    def record_download(cls, reader_id: int, book_id: int, protocol: str) -> None:
        if not ReaderStatsCache().get_allow_statistic(reader_id):
            return
        cls._buffer.on_event(reader_id, book_id, Reading.ACTION_DOWNLOAD, protocol, datetime.datetime.utcnow())

    @classmethod
    def record_push(cls, reader_id: int, book_id: int, protocol: str) -> None:
        if not ReaderStatsCache().get_allow_statistic(reader_id):
            return
        cls._buffer.on_event(reader_id, book_id, Reading.ACTION_PUSH, protocol, datetime.datetime.utcnow())

    @classmethod
    def get_book_format_stats(cls, reader_id: int, book_id: int, fmt: Optional[str] = None) -> List[dict]:
        """所有格式（或 fmt 指定的单个格式）的统计（供 BookDetail/独立接口/MCP get_book_reading_stats 复用）。"""
        db = Reading._session()
        query = db.query(BookReadingStats).filter(
            BookReadingStats.reader_id == reader_id, BookReadingStats.book_id == book_id, BookReadingStats.total_seconds > 10
        )
        if fmt:
            query = query.filter(BookReadingStats.format == fmt.lower())
        rows = query.order_by(BookReadingStats.format).all()
        return [row.format_dict() for row in rows]

    @classmethod
    def update_book_format_stats(
        cls,
        reader_id: int,
        book_id: int,
        fmt: str,
        duration_seconds: int = 0,
        progress: Optional[Tuple[int, int]] = None,
        start_time: Optional[datetime.datetime] = None,
        finish_time: Optional[datetime.datetime] = None,
        state: Optional[int] = None,
    ) -> dict:
        """手动更新入口（POST /api/book/<id>/reading_stats 与 MCP update_book_reading_stats 共用）。

        直接写库，不进内存缓冲——请求频率低，没有节流必要，且"改了立刻能查到"更符合直觉。
        """
        fmt = fmt.lower()
        db = Reading._session()
        now_utc = datetime.datetime.utcnow()
        row = apply_book_format_update(
            db,
            reader_id,
            book_id,
            fmt,
            now_utc,
            duration_delta=max(int(duration_seconds or 0), 0),
            progress=progress,
            start_time=start_time,
            finish_time=finish_time,
            state=state,
        )
        db.commit()
        return row.format_dict()

    @classmethod
    def flush_now(cls) -> None:
        cls._buffer.flush()
        cls._format_buffer.flush()

    @classmethod
    def start(cls) -> None:
        if cls._periodic_callback is not None:
            return
        interval_ms = CONF.get("READING_STATS_FLUSH_INTERVAL_SEC", 5) * 1000
        cls._periodic_callback = tornado.ioloop.PeriodicCallback(cls.flush_now, interval_ms)
        cls._periodic_callback.start()
        logging.info("[reading_stats] ReadingStatsService started, flushing every %sms", interval_ms)

    @classmethod
    def stop(cls) -> None:
        if cls._periodic_callback is not None:
            cls._periodic_callback.stop()
            cls._periodic_callback = None
        cls.flush_now()
        logging.info("[reading_stats] ReadingStatsService stopped, final flush done")
