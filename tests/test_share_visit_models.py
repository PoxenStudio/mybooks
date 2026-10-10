#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import datetime
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import models
from webserver.models import BookList, BookShare, BookVisit, Reader
from webserver.services.async_service import AsyncService


class TestShareVisitModels(unittest.TestCase):

    def setUp(self):
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.Base.metadata.create_all(engine)
        reader = Reader()
        reader.id, reader.username, reader.name = 1, "u1", "Alice"
        self.session.add(reader)
        self.session.commit()

    def tearDown(self):
        self.session.remove()

    def test_visit_primary_key_is_unique_per_reader_book(self):
        self.session.add(BookVisit(1, 10))
        self.session.commit()
        self.session.add(BookVisit(1, 10))
        with self.assertRaises(IntegrityError):
            self.session.commit()

    def test_share_defaults_and_validity(self):
        share = BookShare(book_id=5, token="tok", creator_id=1)
        self.session.add(share)
        self.session.commit()
        self.assertTrue(share.allow_read)
        self.assertFalse(share.allow_download)
        self.assertEqual(share.view_count, 0)
        self.assertTrue(share.is_valid())

    def test_share_invalid_when_cancelled_expired_or_exhausted(self):
        now = datetime.datetime.now()
        share = BookShare(book_id=5, token="tok", creator_id=1, max_views=2)
        share.view_count = 2
        self.assertTrue(share.is_exhausted())
        self.assertFalse(share.is_valid())
        share.view_count = 0
        share.expire_time = now - datetime.timedelta(seconds=1)
        self.assertFalse(share.is_valid())
        share.expire_time = now + datetime.timedelta(days=1)
        self.assertTrue(share.is_valid())
        share.status = BookShare.STATUS_CANCELLED
        self.assertFalse(share.is_valid())

    def test_share_book_id_and_token_unique(self):
        self.session.add(BookShare(book_id=5, token="a", creator_id=1))
        self.session.commit()
        self.session.add(BookShare(book_id=5, token="b", creator_id=1))
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()
        self.session.add(BookShare(book_id=6, token="a", creator_id=1))
        with self.assertRaises(IntegrityError):
            self.session.commit()

    def test_booklist_guest_read_defaults_false(self):
        row = BookList(reader_id=1, name="n")
        self.session.add(row)
        self.session.commit()
        self.assertFalse(row.guest_read)

    def test_adjust_booklist_table_adds_missing_column(self):
        engine = create_engine("sqlite://")
        session = scoped_session(sessionmaker(bind=engine))
        session.execute(text("CREATE TABLE booklists (id INTEGER PRIMARY KEY, name VARCHAR(100))"))
        session.execute(text("INSERT INTO booklists (id, name) VALUES (1, 'old')"))
        service = AsyncService()
        service.session = session
        service.adjust_booklist_table()
        service.adjust_booklist_table()
        row = session.execute(text("SELECT guest_read FROM booklists WHERE id=1")).fetchone()
        self.assertEqual(row[0], 0)
        session.remove()


if __name__ == "__main__":
    unittest.main()
