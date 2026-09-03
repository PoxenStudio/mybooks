#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Read-side aggregation for the homepage reading-stats banner.

Feeds off webserver.models.Reading/Reader/ReadingState (written by
reading_stats_service.ReadingWriteBuffer). Historical (already-closed) daily
buckets are cached per-user in `<MYREADER_SYNC_PATH>/<uid>/reading.json`, and
only rewritten once a day when the cache falls behind "yesterday" — today's
data is always computed live and never persisted.

See document/Reading_Dashboard_Design.md for the full design.
"""

import datetime
import json
import logging
import os
from typing import Dict, Optional

from sqlalchemy import text

from webserver import loader
from webserver.models import Reader, Reading, ReadingState

CONF = loader.get_settings()

CACHE_VERSION = 1
CACHE_RETENTION_DAYS = 63  # 9 weeks
DISPLAY_WEEKS = 8


def _user_cache_path(uid) -> str:
    return os.path.join(
        CONF.get("MYREADER_SYNC_PATH", "/data/sync/"), str(uid), "reading.json"
    )


def _date_str(d: datetime.date) -> str:
    return d.strftime("%Y-%m-%d")


def _empty_cache() -> Dict:
    return {"version": CACHE_VERSION, "cached_through": None, "days": {}}


def _load_cache(uid) -> Dict:
    path = _user_cache_path(uid)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("days"), dict):
            raise ValueError("malformed reading.json structure")
        return data
    except FileNotFoundError:
        return _empty_cache()
    except Exception as e:
        logging.warning(
            "[reading_dashboard] failed to load %s, rebuilding from scratch: %s",
            path,
            e,
        )
        return _empty_cache()


def _save_cache(uid, cache: Dict) -> None:
    path = _user_cache_path(uid)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        os.replace(tmp_path, path)
    except Exception as e:
        logging.warning("[reading_dashboard] failed to save %s: %s", path, e)


def _query_days(
    db, reader_id: int, start: datetime.date, end: datetime.date
) -> Dict[str, Dict[str, int]]:
    """Aggregate Reading rows for reader_id within [start, end] (inclusive), bucketed by date+action."""
    rows = db.execute(
        text(
            """
            SELECT date, action, SUM(duration) AS total_duration, COUNT(*) AS cnt
            FROM readings
            WHERE reader_id = :reader_id AND date BETWEEN :start AND :end
            GROUP BY date, action
            """
        ),
        dict(reader_id=reader_id, start=start, end=end),
    ).fetchall()

    days: Dict[str, Dict[str, int]] = {}
    for row in rows:
        date_str = row.date if isinstance(row.date, str) else _date_str(row.date)
        bucket = days.setdefault(
            date_str, {"reading_seconds": 0, "download_count": 0, "push_count": 0}
        )
        if row.action == Reading.ACTION_READ:
            bucket["reading_seconds"] += int(row.total_duration or 0)
        elif row.action == Reading.ACTION_DOWNLOAD:
            bucket["download_count"] += int(row.cnt or 0)
        elif row.action == Reading.ACTION_PUSH:
            bucket["push_count"] += int(row.cnt or 0)
    return days


def _prune(days: Dict[str, Dict], today: datetime.date) -> Dict[str, Dict]:
    cutoff = today - datetime.timedelta(days=CACHE_RETENTION_DAYS)
    return {d: v for d, v in days.items() if d >= _date_str(cutoff)}


def _reconcile(db, reader_id: int, cache: Dict, today: datetime.date) -> Dict:
    """Bring the cache's closed-day coverage up to "yesterday", writing to disk only if it moved."""
    yesterday = today - datetime.timedelta(days=1)
    cached_through = cache.get("cached_through")
    cached_through_date = None
    if cached_through:
        try:
            cached_through_date = datetime.datetime.strptime(
                cached_through, "%Y-%m-%d"
            ).date()
        except ValueError:
            cached_through_date = None

    if cached_through_date is not None and cached_through_date >= yesterday:
        return cache

    start = (
        (cached_through_date + datetime.timedelta(days=1))
        if cached_through_date
        else (today - datetime.timedelta(days=CACHE_RETENTION_DAYS))
    )
    if start > yesterday:
        cache["cached_through"] = _date_str(yesterday)
        return cache

    fresh_days = _query_days(db, reader_id, start, yesterday)
    days = cache.get("days", {})
    days.update(fresh_days)
    # days with no activity at all never appear in fresh_days; that's fine, they're
    # simply absent from the cache and treated as zero when read back.
    cache["days"] = _prune(days, today)
    cache["cached_through"] = _date_str(yesterday)
    cache["version"] = CACHE_VERSION
    _save_cache(reader_id, cache)
    return cache


def _week_start(d: datetime.date) -> datetime.date:
    return d - datetime.timedelta(days=d.weekday())  # Monday


def _weekly_buckets(days: Dict[str, Dict], today: datetime.date) -> list:
    this_week_start = _week_start(today)
    week_starts = [
        this_week_start - datetime.timedelta(weeks=i)
        for i in range(DISPLAY_WEEKS - 1, -1, -1)
    ]
    weekly = []
    for ws in week_starts:
        reading_seconds = download_count = push_count = 0
        for i in range(7):
            day = ws + datetime.timedelta(days=i)
            if day > today:
                break
            bucket = days.get(_date_str(day))
            if bucket:
                reading_seconds += bucket.get("reading_seconds", 0)
                download_count += bucket.get("download_count", 0)
                push_count += bucket.get("push_count", 0)
        weekly.append(
            {
                "week_start": _date_str(ws),
                "reading_seconds": reading_seconds,
                "download_count": download_count,
                "push_count": push_count,
            }
        )
    return weekly


def _book_status(db, reader_id: int, calibre_db=None) -> Dict[str, int]:
    rows = (
        db.query(ReadingState.read_state, ReadingState.wants, ReadingState.book_id)
        .filter(ReadingState.reader_id == reader_id)
        .all()
    )
    status = {"reading": 0, "to_read": 0, "finished": 0}
    for read_state, wants, _book_id in rows:
        if calibre_db and not calibre_db.has_id(_book_id):
            continue
        if read_state == 1:
            status["reading"] += 1
        elif read_state == 2:
            status["finished"] += 1
        elif wants:
            status["to_read"] += 1
    return status


def get_stats(db, reader: Reader, calibre_db=None) -> Optional[Dict]:
    if not CONF.get("ENABLE_HOMEPAGE_READING_STATS", True):
        return None

    today = datetime.datetime.utcnow().date()
    cache = _load_cache(reader.id)
    cache = _reconcile(db, reader.id, cache, today)

    days = dict(cache.get("days", {}))
    # today is never cached, always live
    today_bucket = _query_days(db, reader.id, today, today)
    days.update(today_bucket)

    return {
        "totals": {
            "total_reading_seconds": reader.total_reading_seconds or 0,
            "download_count": reader.download_count or 0,
            "push_count": reader.push_count or 0,
        },
        "weekly": _weekly_buckets(days, today),
        "book_status": _book_status(db, reader.id, calibre_db),
    }
