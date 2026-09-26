#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
SQLAlchemy data sources for crowd statistics and reader profiles.
@author: PoxenStudio, 2026
"""

import datetime
from typing import Dict, Hashable, List, Tuple

from sqlalchemy import func, or_

from webserver.models import BookReadingStats, BookReview, Item, Reader, Reading, ReadingState
from webserver.recommend.config import RecommendConfig
from webserver.recommend.crowd import CrowdData, Engagement
from webserver.recommend.profile import BookSignal


LEGACY_HISTORY_KEYS = ("read_history", "push_history")


class SqlCrowdSource:
    def __init__(self, scoped_session):
        self.make_session = scoped_session.session_factory

    def fingerprint(self) -> Hashable:
        session = self.make_session()
        try:
            return (
                session.query(func.count(Reading.id), func.max(Reading.update_time), func.sum(Reading.duration)).one(),
                session.query(func.count(ReadingState.book_id), func.max(ReadingState.favorite_date), func.max(ReadingState.read_date)).one(),
                session.query(func.count(BookReview.id), func.max(BookReview.update_time)).one(),
                session.query(func.count(Reader.id), func.sum(Reader.id)).filter(Reader.allow_statistic.is_(True)).one(),
                session.query(func.sum(Item.count_visit + Item.count_download)).scalar(),
            )
        finally:
            session.close()

    def load(self, config: RecommendConfig) -> CrowdData:
        session = self.make_session()
        try:
            return CrowdData(
                engagements=list(self._engagements(session, config).values()),
                reviews=self._reviews(session) if config.use_reviews else {},
                item_counts=self._item_counts(session),
            )
        finally:
            session.close()

    def _engagements(self, session, config: RecommendConfig) -> Dict[Tuple[int, int], Engagement]:
        eligible = {rid for (rid,) in session.query(Reader.id).filter(Reader.allow_statistic.is_(True))}
        eligible -= set(config.crowd_exclude_readers)
        result: Dict[Tuple[int, int], Engagement] = {}

        def get(reader_id, book_id):
            key = (reader_id, book_id)
            if key not in result:
                result[key] = Engagement(reader_id=reader_id, book_id=book_id)
            return result[key]

        rows = session.query(Reading.reader_id, Reading.book_id, Reading.action, func.sum(Reading.duration), func.max(Reading.update_time))
        if config.crowd_ignore_protocols:
            rows = rows.filter(or_(Reading.action == Reading.ACTION_READ, Reading.protocol.notin_(config.crowd_ignore_protocols)))
        for reader_id, book_id, action, secs, last in rows.group_by(Reading.reader_id, Reading.book_id, Reading.action):
            if reader_id not in eligible:
                continue
            e = get(reader_id, book_id)
            if action == "read":
                e.read_secs += int(secs or 0)
            else:
                e.downloaded = True
            e.last_active = max(filter(None, (e.last_active, last)), default=None)

        states = session.query(
            ReadingState.reader_id, ReadingState.book_id, ReadingState.favorite, ReadingState.favorite_date, ReadingState.read_state, ReadingState.read_date
        ).filter(or_(ReadingState.favorite == 1, ReadingState.read_state > 0))
        for reader_id, book_id, favorite, favorite_date, read_state, read_date in states:
            if reader_id not in eligible:
                continue
            e = get(reader_id, book_id)
            e.favorite = favorite == 1
            e.finished = read_state == 2
            e.started = read_state > 0
            e.last_active = max(filter(None, (e.last_active, favorite_date if e.favorite else None, read_date)), default=None)

        if config.use_legacy_history:
            self._add_legacy_history(session, eligible, result)

        own_ratings = session.query(BookReview.reader_id, BookReview.book_id, BookReview.rating).filter(BookReview.deleted_at.is_(None))
        for reader_id, book_id, rating in own_ratings:
            if (reader_id, book_id) in result:
                result[(reader_id, book_id)].rating = rating
        return result

    @staticmethod
    def _add_legacy_history(session, eligible, result: Dict[Tuple[int, int], Engagement]) -> None:
        """Pre-Reading-table history in Reader.extra, counted like a download and never overriding real records."""
        for reader_id, extra in session.query(Reader.id, Reader.extra).filter(Reader.id.in_(eligible)):
            for key in LEGACY_HISTORY_KEYS:
                for entry in (extra or {}).get(key) or []:
                    book_id, ts = entry.get("id"), entry.get("timestamp")
                    if not isinstance(book_id, int) or (reader_id, book_id) in result:
                        continue
                    last = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).replace(tzinfo=None) if ts else None
                    result[(reader_id, book_id)] = Engagement(reader_id=reader_id, book_id=book_id, downloaded=True, last_active=last)

    def _reviews(self, session) -> Dict[int, Tuple[int, int]]:
        rows = session.query(BookReview.book_id, func.count(BookReview.id), func.sum(BookReview.rating)).filter(
            BookReview.status == BookReview.STATUS_APPROVED, BookReview.deleted_at.is_(None)
        ).group_by(BookReview.book_id)
        return {book_id: (int(n), int(total or 0)) for book_id, n, total in rows}

    def _item_counts(self, session) -> Dict[int, int]:
        rows = session.query(Item.book_id, Item.count_visit + Item.count_download).filter(Item.count_visit + Item.count_download > 0)
        return {book_id: int(count) for book_id, count in rows}


class SqlProfileSource:
    def __init__(self, scoped_session):
        self.make_session = scoped_session.session_factory

    def load(self, reader_id: int) -> List[BookSignal]:
        session = self.make_session()
        try:
            return list(self._signals(session, reader_id).values())
        finally:
            session.close()

    def _signals(self, session, reader_id: int) -> Dict[int, BookSignal]:
        result: Dict[int, BookSignal] = {}

        def get(book_id):
            if book_id not in result:
                result[book_id] = BookSignal(book_id=book_id)
            return result[book_id]

        def touch(signal, *times):
            signal.last_active = max(filter(None, (signal.last_active, *times)), default=None)

        for row in session.query(ReadingState).filter(ReadingState.reader_id == reader_id):
            if not (row.favorite or row.wants or row.read_state):
                continue
            signal = get(row.book_id)
            signal.favorite, signal.wants, signal.read_state = row.favorite == 1, row.wants == 1, row.read_state
            touch(signal, row.favorite_date if row.favorite else None, row.wants_date if row.wants else None, row.read_date if row.read_state else None)

        allow_statistic = session.query(Reader.allow_statistic).filter(Reader.id == reader_id).scalar()
        if allow_statistic:
            rows = session.query(Reading.book_id, Reading.action, func.sum(Reading.duration), func.max(Reading.update_time)).filter(Reading.reader_id == reader_id)
            for book_id, action, secs, last in rows.group_by(Reading.book_id, Reading.action):
                signal = get(book_id)
                if action == "read":
                    signal.read_secs = max(signal.read_secs, int(secs or 0))
                else:
                    signal.downloaded = True
                touch(signal, last)
            stats = session.query(BookReadingStats.book_id, func.sum(BookReadingStats.total_seconds)).filter(BookReadingStats.reader_id == reader_id)
            for book_id, secs in stats.group_by(BookReadingStats.book_id):
                signal = get(book_id)
                signal.read_secs = max(signal.read_secs, int(secs or 0))

        reviews = session.query(BookReview.book_id, BookReview.rating, BookReview.update_time).filter(BookReview.reader_id == reader_id, BookReview.deleted_at.is_(None))
        for book_id, rating, updated in reviews:
            signal = get(book_id)
            signal.rating = rating
            touch(signal, updated)
        return result
