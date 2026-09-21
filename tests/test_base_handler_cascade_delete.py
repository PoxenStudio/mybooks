#!/usr/bin/env python3

import datetime
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import models
from webserver.handlers.base import BaseHandler
from webserver.models import BookReadingStats, BookReview, Item, ManualReadingLog, Reader, Reading, ReadingRecord, ReadingState


class TestCascadeDeleteBookData(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)

        reader = Reader()
        reader.id, reader.username = 1, "u1"
        self.session.add(reader)

        now = datetime.datetime.now()
        item = Item()
        item.book_id = 100
        self.session.add(item)
        self.session.add(BookReview(reader_id=1, book_id=100, rating=8, create_time=now, update_time=now))
        self.session.add(ReadingRecord(
            reader_id=1, book_hash="cloud-100-epub", book_id=100, kind=ReadingRecord.KIND_BOOKS,
            record_id="cloud-100-epub", uid=1, payload={}, updated_at=int(now.timestamp() * 1000),
        ))
        self.session.add(ReadingState(book_id=100, reader_id=1))
        self.session.add(ManualReadingLog(
            reader_id=1, book_id=100, format="epub", date=now.date(), duration_seconds=600,
            create_time=now, update_time=now,
        ))
        self.session.add(Reading(1, 100, Reading.ACTION_READ, Reading.PROTOCOL_APP, start_time=now, duration=300, date=now.date()))
        self.session.add(BookReadingStats(reader_id=1, book_id=100, format="epub", total_seconds=900, create_time=now, update_time=now))
        self.session.commit()

    def tearDown(self):
        self.session.remove()

    def test_removes_all_book_scoped_tables(self):
        BaseHandler.cascade_delete_book_data(self.session, 100)

        self.assertEqual(self.session.query(Item).filter_by(book_id=100).count(), 0)
        self.assertEqual(self.session.query(BookReview).filter_by(book_id=100).count(), 0)
        self.assertEqual(self.session.query(ReadingRecord).filter_by(book_id=100).count(), 0)
        self.assertEqual(self.session.query(ReadingState).filter_by(book_id=100).count(), 0)
        self.assertEqual(self.session.query(ManualReadingLog).filter_by(book_id=100).count(), 0)
        self.assertEqual(self.session.query(Reading).filter_by(book_id=100).count(), 0)
        self.assertEqual(self.session.query(BookReadingStats).filter_by(book_id=100).count(), 0)

    def test_commit_false_lets_caller_control_the_transaction(self):
        BaseHandler.cascade_delete_book_data(self.session, 100, commit=False)
        self.assertEqual(self.session.query(BookReview).filter_by(book_id=100).count(), 0)
        self.session.rollback()
        self.assertEqual(self.session.query(BookReview).filter_by(book_id=100).count(), 1)

    def test_leaves_other_books_untouched(self):
        now = datetime.datetime.now()
        self.session.add(BookReview(reader_id=1, book_id=200, rating=5, create_time=now, update_time=now))
        self.session.commit()

        BaseHandler.cascade_delete_book_data(self.session, 100)

        self.assertEqual(self.session.query(BookReview).filter_by(book_id=200).count(), 1)
