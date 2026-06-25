#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Data sync storage and WS broadcast for `/api/sync` (legacy record sync).
@author: PoxenStudio, 2026-06

Records are stored one JSON file per book per category, under
`<MYREADER_SYNC_PATH>/<uid>/<book_hash>/{books,configs,notes}.json`, so no
single file grows with the user's whole library:

- `books.json` / `configs.json`: at most one record per (user, book), stored
  as a single plain JSON object (the key is already the directory name).
- `notes.json`: a book can have many notes, stored as a JSON object keyed by
  note `id`.
"""

import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from typing import Dict, Optional, Set

from webserver import loader

CONF = loader.get_settings()


class MyReaderSyncService:
    """All storage/merge logic and the WS connection registry for `/api/sync`."""

    KINDS = ("books", "configs", "notes")
    # kinds whose per-book JSON file holds multiple records keyed by `id`;
    # the rest hold a single record per book (one book/config record per user+book_hash)
    _MULTI_RECORD_KINDS = {"notes"}

    # shared, process-wide state (single-instance deployment, see plan §6/§7)
    _locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
    connections: Dict[int, Set] = defaultdict(set)

    @staticmethod
    def is_enabled() -> bool:
        return CONF.get("ENABLE_DATA_SYNC", True)

    @staticmethod
    def _user_dir(uid) -> str:
        return os.path.join(CONF.get("MYREADER_SYNC_PATH", "/data/sync/"), str(uid))

    @classmethod
    def _book_dir(cls, uid, book_hash: str) -> str:
        return os.path.join(cls._user_dir(uid), book_hash)

    @classmethod
    def _file_path(cls, uid, book_hash: str, kind: str) -> str:
        return os.path.join(cls._book_dir(uid, book_hash), f"{kind}.json")

    @classmethod
    def _list_book_hashes(cls, uid):
        user_dir = cls._user_dir(uid)
        if not os.path.isdir(user_dir):
            return []
        return [name for name in os.listdir(user_dir) if os.path.isdir(os.path.join(user_dir, name))]

    @staticmethod
    def _load_json(path: str, default):
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            logging.error("[sync] failed to read %s, treating as empty", path, exc_info=True)
            return default

    @staticmethod
    def _save_json(path: str, data) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)

    @classmethod
    def _load_record(cls, uid, book_hash: str, kind: str) -> Optional[dict]:
        """books/configs: at most one record per (user, book)."""
        return cls._load_json(cls._file_path(uid, book_hash, kind), None)

    @classmethod
    def _save_record(cls, uid, book_hash: str, kind: str, record: dict) -> None:
        cls._save_json(cls._file_path(uid, book_hash, kind), record)

    @classmethod
    def _load_note_store(cls, uid, book_hash: str) -> dict:
        """notes: a book can have many notes, keyed by id."""
        return cls._load_json(cls._file_path(uid, book_hash, "notes"), {})

    @classmethod
    def _save_note_store(cls, uid, book_hash: str, store: dict) -> None:
        cls._save_json(cls._file_path(uid, book_hash, "notes"), store)

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
    def pull(cls, uid, since: int, type_: Optional[str] = None, book_hash: Optional[str] = None) -> dict:
        result = {"books": None, "notes": None, "configs": None}
        kinds = (type_,) if type_ else cls.KINDS
        book_hashes = (book_hash,) if book_hash else cls._list_book_hashes(uid)
        for kind in kinds:
            items = []
            for bh in book_hashes:
                if kind in cls._MULTI_RECORD_KINDS:
                    store = cls._load_note_store(uid, bh)
                    items.extend(record for record in store.values() if cls._changed_since(record, since))
                else:
                    record = cls._load_record(uid, bh, kind)
                    if record and cls._changed_since(record, since):
                        items.append(record)
            result[kind] = items
        return result

    @classmethod
    def _get_lock(cls, uid) -> asyncio.Lock:
        return cls._locks[uid]

    @classmethod
    def _push_book_records(cls, uid, book_hash: str, kind: str, incoming_records: list):
        """Merge incoming records for one (book_hash, kind) into its on-disk store.

        Returns (merged_records_for_response, was_applied).
        """
        if kind in cls._MULTI_RECORD_KINDS:
            store = cls._load_note_store(uid, book_hash)
            merged_list = []
            applied_any = False
            for incoming in incoming_records:
                key = incoming.get("id")
                if not key:
                    logging.debug("[sync] note record without id for user %s, book %s", uid, book_hash)
                    continue
                merged, applied = cls._merge_one(store.get(key), incoming)
                store[key] = merged
                merged_list.append(merged)
                applied_any = applied_any or applied
            if applied_any:
                cls._save_note_store(uid, book_hash, store)
            return merged_list, applied_any

        existing = cls._load_record(uid, book_hash, kind)
        merged = existing
        applied_any = False
        for incoming in incoming_records:
            merged, applied = cls._merge_one(merged, incoming)
            applied_any = applied_any or applied
        if applied_any:
            cls._save_record(uid, book_hash, kind, merged)
        return ([merged] if merged is not None else []), applied_any

    @classmethod
    async def push(cls, uid, payload: dict) -> dict:
        result = {}
        changed_scopes = set()
        async with cls._get_lock(uid):
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
                    book_merged, applied = cls._push_book_records(uid, book_hash, kind, incoming_records)
                    merged_list.extend(book_merged)
                    if applied:
                        changed_scopes.add((kind, book_hash))
                if merged_list:
                    result[kind] = merged_list
        for scope, book_hash in changed_scopes:
            cls.broadcast_changed(uid, scope, book_hash)
        return result

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
