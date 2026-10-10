#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
用户浏览记录（详情页访问），设计见 document/Share_Visits_GuestBooklist_Design.md。

访问先进入进程内缓存，由定时任务或缓存条数阈值触发批量落库；
VISIT_FLUSH_INTERVAL 为 0 时每次访问同步写库。
"""

import datetime
import logging
import threading
from typing import Dict, List, Optional, Tuple

import tornado.ioloop

from webserver import loader
from webserver.models import BookVisit

CONF = loader.get_settings()


class BookVisitService:
    _pending: Dict[Tuple[int, int], datetime.datetime] = {}
    _lock = threading.Lock()
    _flush_lock = threading.RLock()
    _periodic_callback: Optional[tornado.ioloop.PeriodicCallback] = None

    @classmethod
    def _interval(cls) -> int:
        return int(CONF.get("VISIT_FLUSH_INTERVAL", 30))

    @classmethod
    def _threshold(cls) -> int:
        return int(CONF.get("VISIT_FLUSH_THRESHOLD", 200))

    @classmethod
    def record(cls, reader_id: int, book_id: int) -> None:
        now = datetime.datetime.now()
        if cls._interval() <= 0:
            with cls._flush_lock:
                cls._write({(reader_id, book_id): now})
            return
        with cls._lock:
            cls._pending[(reader_id, book_id)] = now
            full = len(cls._pending) >= cls._threshold()
        if full:
            cls.flush_now()

    @classmethod
    def flush_now(cls) -> None:
        with cls._flush_lock:
            with cls._lock:
                batch = dict(cls._pending)
                cls._pending.clear()
            if not batch:
                return
            try:
                cls._write(batch)
            except Exception:
                logging.error("[book_visit] flush failed, data kept for retry on next tick", exc_info=True)
                with cls._lock:
                    for key, value in batch.items():
                        if key not in cls._pending or cls._pending[key] < value:
                            cls._pending[key] = value

    @classmethod
    def _write(cls, batch: Dict[Tuple[int, int], datetime.datetime]) -> None:
        db = BookVisit._session()
        try:
            for (reader_id, book_id), visit_time in batch.items():
                row = db.query(BookVisit).filter_by(reader_id=reader_id, book_id=book_id).one_or_none()
                if row is None:
                    db.add(BookVisit(reader_id, book_id, visit_time))
                elif row.visit_time < visit_time:
                    row.visit_time = visit_time
            db.flush()
            for reader_id in {key[0] for key in batch}:
                cls._prune(db, reader_id)
            db.commit()
        except Exception:
            db.rollback()
            raise

    @classmethod
    def _prune(cls, db, reader_id: int) -> None:
        limit = BookVisit.MAX_PER_USER
        if db.query(BookVisit).filter_by(reader_id=reader_id).count() <= limit:
            return
        keep = [
            row[0]
            for row in db.query(BookVisit.book_id).filter_by(reader_id=reader_id).order_by(BookVisit.visit_time.desc(), BookVisit.book_id.desc()).limit(limit).all()
        ]
        db.query(BookVisit).filter(BookVisit.reader_id == reader_id, BookVisit.book_id.notin_(keep)).delete(synchronize_session=False)

    @classmethod
    def list(cls, reader_id: int, start: int = 0, limit: int = 60) -> Tuple[List[Tuple[int, datetime.datetime]], int]:
        db = BookVisit._session()
        merged = {row.book_id: row.visit_time for row in db.query(BookVisit).filter_by(reader_id=reader_id).all()}
        with cls._lock:
            for (rid, book_id), visit_time in cls._pending.items():
                if rid == reader_id and (book_id not in merged or merged[book_id] < visit_time):
                    merged[book_id] = visit_time
        ordered = sorted(merged.items(), key=lambda item: (item[1], item[0]), reverse=True)[:BookVisit.MAX_PER_USER]
        return ordered[start:start + limit], len(ordered)

    @classmethod
    def clear(cls, reader_id: int) -> None:
        with cls._flush_lock:
            with cls._lock:
                for key in [k for k in cls._pending if k[0] == reader_id]:
                    del cls._pending[key]
            db = BookVisit._session()
            try:
                db.query(BookVisit).filter_by(reader_id=reader_id).delete(synchronize_session=False)
                db.commit()
            except Exception:
                db.rollback()
                raise

    @classmethod
    def start(cls) -> None:
        interval = cls._interval()
        if cls._periodic_callback is not None or interval <= 0:
            return
        cls._periodic_callback = tornado.ioloop.PeriodicCallback(cls.flush_now, interval * 1000)
        cls._periodic_callback.start()
        logging.info("[book_visit] BookVisitService started, flushing every %ss", interval)

    @classmethod
    def stop(cls) -> None:
        if cls._periodic_callback is not None:
            cls._periodic_callback.stop()
            cls._periodic_callback = None
        cls.flush_now()
