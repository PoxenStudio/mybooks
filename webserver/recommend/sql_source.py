#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

from typing import Dict, Tuple

from sqlalchemy import func, or_

from webserver.models import BookReview, Item, Reader, Reading, ReadingState
from webserver.recommend.config import RecommendConfig
from webserver.recommend.crowd import CrowdData, Engagement


class SqlCrowdSource:
    def __init__(self, scoped_session):
        self.make_session = scoped_session.session_factory

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
        return result

    def _reviews(self, session) -> Dict[int, Tuple[int, int]]:
        rows = session.query(BookReview.book_id, func.count(BookReview.id), func.sum(BookReview.rating)).filter(
            BookReview.status == BookReview.STATUS_APPROVED, BookReview.deleted_at.is_(None)
        ).group_by(BookReview.book_id)
        return {book_id: (int(n), int(total or 0)) for book_id, n, total in rows}

    def _item_counts(self, session) -> Dict[int, int]:
        rows = session.query(Item.book_id, Item.count_visit + Item.count_download).filter(Item.count_visit + Item.count_download > 0)
        return {book_id: int(count) for book_id, count in rows}
