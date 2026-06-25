#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Data sync storage and WS broadcast for `/api/sync` (legacy record sync).
@author: PoxenStudio, 2026-06
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

# kind -> the field used as the JSON file's object key for that kind
KEY_FIELDS = {
    "books": "book_hash",
    "configs": "book_hash",
    "notes": "id",
}

_locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
connections: Dict[int, Set] = defaultdict(set)


def is_enabled() -> bool:
    return CONF.get("ENABLE_DATA_SYNC", True)


def _user_dir(uid) -> str:
    return os.path.join(CONF.get("MYREADER_SYNC_PATH", "/data/sync/"), str(uid))


def _file_path(uid, kind: str) -> str:
    return os.path.join(_user_dir(uid), f"{kind}.json")


def _load(uid, kind: str) -> dict:
    path = _file_path(uid, kind)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        logging.error("[sync] failed to read %s, treating as empty", path, exc_info=True)
        return {}


def _save(uid, kind: str, data: dict) -> None:
    path = _file_path(uid, kind)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


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


def pull(uid, since: int, type_: Optional[str] = None, book_hash: Optional[str] = None) -> dict:
    result = {"books": None, "notes": None, "configs": None}
    for kind in KEY_FIELDS:
        if type_ and kind != type_:
            continue
        store = _load(uid, kind)
        items = []
        for record in store.values():
            updated_at = record.get("updated_at")
            deleted_at = record.get("deleted_at")
            changed = (updated_at is not None and updated_at > since) or (
                deleted_at is not None and deleted_at > since
            )
            if not changed:
                continue
            if book_hash and record.get("book_hash") != book_hash:
                continue
            items.append(record)
        result[kind] = items
    return result


def _get_lock(uid) -> asyncio.Lock:
    return _locks[uid]


async def push(uid, payload: dict) -> dict:
    result = {}
    changed_scopes = set()
    async with _get_lock(uid):
        for kind, key_field in KEY_FIELDS.items():
            records = payload.get(kind) or []
            if not records:
                continue
            store = _load(uid, kind)
            merged_list = []
            for incoming in records:
                key = incoming.get(key_field)
                if not key:
                    continue
                existing = store.get(key)
                merged, applied = _merge_one(existing, incoming)
                store[key] = merged
                merged_list.append(merged)
                if applied:
                    changed_scopes.add((kind, merged.get("book_hash")))
            if merged_list:
                _save(uid, kind, store)
                result[kind] = merged_list
    for scope, book_hash in changed_scopes:
        broadcast_changed(uid, scope, book_hash)
    return result


def register_connection(uid, ws) -> None:
    connections[uid].add(ws)


def unregister_connection(uid, ws) -> None:
    connections[uid].discard(ws)


def broadcast_changed(uid, scope: str, book_hash: Optional[str], exclude=None) -> None:
    message = json.dumps({
        "type": "changed",
        "scope": scope,
        "bookHash": book_hash,
        "ts": int(time.time() * 1000),
    })
    for ws in list(connections.get(uid, ())):
        if ws is exclude:
            continue
        try:
            ws.write_message(message)
        except Exception:
            logging.warning("[sync] ws broadcast failed, connection will be cleaned up on disconnect", exc_info=True)
