#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Read/delete helpers for a user's online reading history.

History rows are daily buckets keyed by (reader_id, book_id, date), so deleting a
"record" removes one day for one book, not an individual reading session.
"""

import datetime

from sqlalchemy import exists, func

from webserver import site_time
from webserver.models import ManualReadingLog, Reader, Reading
from webserver.services import reading_dashboard_service, reading_stats_service


def _iso_date(value):
    if value is None:
        return None
    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(value)


def _iso_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    return str(value)


class ReadingHistoryService:
    @classmethod
    def summary(cls, reader_id):
        db = Reading._session()
        records, books, total_seconds, first_date, last_date = (
            db.query(
                func.count(Reading.id),
                func.count(func.distinct(Reading.book_id)),
                func.coalesce(func.sum(Reading.duration), 0),
                func.min(Reading.date),
                func.max(Reading.date),
            )
            .filter(Reading.reader_id == reader_id, Reading.action == Reading.ACTION_READ)
            .one()
        )
        # Zero-duration manual entries can exist without a Reading row. Count those
        # separately so the manager can still expose clear-all for them.
        missing_reading = ~exists().where(
            Reading.reader_id == ManualReadingLog.reader_id,
            Reading.book_id == ManualReadingLog.book_id,
            Reading.date == ManualReadingLog.date,
            Reading.action == Reading.ACTION_READ,
        )
        manual_records = (
            db.query(func.count(ManualReadingLog.id))
            .filter(ManualReadingLog.reader_id == reader_id, missing_reading)
            .scalar()
        )
        return {
            "records": int(records or 0),
            "books": int(books or 0),
            "total_seconds": int(total_seconds or 0),
            "first_date": _iso_date(first_date),
            "last_date": _iso_date(last_date),
            "manual_records": int(manual_records or 0),
        }

    @classmethod
    def book_summaries(cls, reader_id):
        db = Reading._session()
        rows = (
            db.query(
                Reading.book_id,
                func.count(Reading.id),
                func.coalesce(func.sum(Reading.duration), 0),
                func.min(Reading.date),
                func.max(Reading.date),
                func.max(Reading.update_time),
            )
            .filter(Reading.reader_id == reader_id, Reading.action == Reading.ACTION_READ)
            .group_by(Reading.book_id)
            .order_by(func.max(Reading.update_time).desc())
            .all()
        )
        return [
            {
                "book_id": int(row[0]),
                "records": int(row[1] or 0),
                "total_seconds": int(row[2] or 0),
                "first_date": _iso_date(row[3]),
                "last_date": _iso_date(row[4]),
                "last_read": _iso_datetime(row[5]),
            }
            for row in rows
        ]

    @classmethod
    def book_records(cls, reader_id, book_id):
        db = Reading._session()
        rows = (
            db.query(Reading)
            .filter(
                Reading.reader_id == reader_id,
                Reading.book_id == book_id,
                Reading.action == Reading.ACTION_READ,
            )
            .order_by(Reading.date.desc())
            .all()
        )
        return [
            {
                "date": _iso_date(row.date),
                "duration": int(row.duration or 0),
                "protocol": row.protocol,
                "start_time": _iso_datetime(row.start_time),
                "update_time": _iso_datetime(row.update_time),
            }
            for row in rows
        ]

    @classmethod
    def delete(cls, reader_id, book_id=None, date=None):
        # Flush pending heartbeats first: otherwise a buffered delta can recreate
        # a row seconds after the user deleted it. A failed flush requeues data, so
        # abort instead of deleting and letting the next tick recreate it.
        if not reading_stats_service.ReadingStatsService.flush_now():
            raise RuntimeError("reading stats flush failed, abort history deletion")

        db = Reading._session()
        reading_filters = [
            Reading.reader_id == reader_id,
            Reading.action == Reading.ACTION_READ,
        ]
        manual_filters = [ManualReadingLog.reader_id == reader_id]
        if book_id is not None:
            reading_filters.append(Reading.book_id == book_id)
            manual_filters.append(ManualReadingLog.book_id == book_id)
        if date is not None:
            reading_filters.append(Reading.date == date)
            manual_filters.append(ManualReadingLog.date == date)

        try:
            records, books, total_seconds, first_date, last_date = (
                db.query(
                    func.count(Reading.id),
                    func.count(func.distinct(Reading.book_id)),
                    func.coalesce(func.sum(Reading.duration), 0),
                    func.min(Reading.date),
                    func.max(Reading.date),
                )
                .filter(*reading_filters)
                .one()
            )
            manual_records = (
                db.query(ManualReadingLog)
                .filter(*manual_filters)
                .delete(synchronize_session=False)
            )
            db.query(Reading).filter(*reading_filters).delete(synchronize_session=False)

            # populate_existing: the heartbeat flush above may have advanced the
            # reader total via a Core UPDATE, leaving the identity-map instance stale.
            reader = db.get(Reader, reader_id, populate_existing=True)
            if reader is not None:
                if book_id is None and date is None:
                    reader.total_reading_seconds = 0
                else:
                    reader.total_reading_seconds = max(
                        0, (reader.total_reading_seconds or 0) - int(total_seconds or 0)
                    )
            db.commit()
        except Exception:
            db.rollback()
            raise

        deleted = {
            "records": int(records or 0),
            "books": int(books or 0),
            "total_seconds": int(total_seconds or 0),
            "first_date": _iso_date(first_date),
            "last_date": _iso_date(last_date),
            "manual_records": int(manual_records or 0),
        }
        if deleted["records"] and (date is None or date == site_time.site_today()):
            reading_stats_service.ReadingStatsService.reset_sessions(reader_id, book_id)
        if deleted["records"] or deleted["manual_records"]:
            reading_dashboard_service.invalidate_cache(reader_id)
        return deleted
