#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import datetime
import time
import unittest
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import models
from webserver.models import BookVisit, Reader
from webserver.services import book_visit_service
from webserver.services.book_visit_service import BookVisitService


class TestBookVisitService(unittest.TestCase):

    def setUp(self):
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)
        for rid in (1, 2):
            reader = Reader()
            reader.id, reader.username, reader.name = rid, "u%d" % rid, "U%d" % rid
            self.session.add(reader)
        self.session.commit()
        BookVisitService._pending.clear()
        patcher = mock.patch.dict(book_visit_service.CONF, {"VISIT_FLUSH_INTERVAL": 30, "VISIT_FLUSH_THRESHOLD": 200}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        BookVisitService._pending.clear()
        self.session.remove()

    def ids(self, reader_id=1):
        rows, _total = BookVisitService.list(reader_id, 0, 200)
        return [book_id for book_id, _time in rows]

    def db_count(self, reader_id=1):
        return self.session.query(BookVisit).filter_by(reader_id=reader_id).count()

    def test_list_merges_unflushed_cache(self):
        BookVisitService.record(1, 10)
        self.assertEqual(self.db_count(), 0)
        self.assertEqual(self.ids(), [10])

    def test_repeated_visits_merge_and_reorder(self):
        BookVisitService.record(1, 10)
        time.sleep(0.01)
        BookVisitService.record(1, 11)
        time.sleep(0.01)
        BookVisitService.record(1, 10)
        BookVisitService.flush_now()
        self.assertEqual(self.db_count(), 2)
        self.assertEqual(self.ids(), [10, 11])

    def test_flush_keeps_newest_visit_time(self):
        old = datetime.datetime.now() - datetime.timedelta(days=1)
        self.session.add(BookVisit(1, 10, old))
        self.session.commit()
        BookVisitService.record(1, 10)
        BookVisitService.flush_now()
        row = self.session.query(BookVisit).filter_by(reader_id=1, book_id=10).one()
        self.assertGreater(row.visit_time, old)

    def test_prune_keeps_latest_limit(self):
        base = datetime.datetime.now() - datetime.timedelta(hours=1)
        for i in range(BookVisit.MAX_PER_USER):
            self.session.add(BookVisit(1, i, base + datetime.timedelta(seconds=i)))
        self.session.commit()
        BookVisitService.record(1, 1000)
        BookVisitService.flush_now()
        self.assertEqual(self.db_count(), BookVisit.MAX_PER_USER)
        ids = self.ids()
        self.assertEqual(ids[0], 1000)
        self.assertNotIn(0, ids)

    def test_readers_are_isolated(self):
        BookVisitService.record(1, 10)
        BookVisitService.record(2, 20)
        BookVisitService.flush_now()
        self.assertEqual(self.ids(1), [10])
        self.assertEqual(self.ids(2), [20])

    def test_clear_removes_cache_and_db_without_write_back(self):
        BookVisitService.record(1, 10)
        BookVisitService.flush_now()
        BookVisitService.record(1, 11)
        BookVisitService.clear(1)
        BookVisitService.flush_now()
        self.assertEqual(self.ids(), [])
        self.assertEqual(self.db_count(), 0)

    def test_threshold_triggers_flush(self):
        with mock.patch.dict(book_visit_service.CONF, {"VISIT_FLUSH_THRESHOLD": 3}):
            BookVisitService.record(1, 1)
            BookVisitService.record(1, 2)
            self.assertEqual(self.db_count(), 0)
            BookVisitService.record(1, 3)
        self.assertEqual(self.db_count(), 3)
        self.assertEqual(BookVisitService._pending, {})

    def test_interval_zero_writes_synchronously(self):
        with mock.patch.dict(book_visit_service.CONF, {"VISIT_FLUSH_INTERVAL": 0}):
            BookVisitService.record(1, 10)
        self.assertEqual(self.db_count(), 1)

    def test_flush_failure_keeps_data_for_retry(self):
        BookVisitService.record(1, 10)
        with mock.patch.object(BookVisitService, "_write", side_effect=RuntimeError("boom")):
            BookVisitService.flush_now()
        self.assertEqual(self.db_count(), 0)
        self.assertEqual(self.ids(), [10])
        BookVisitService.flush_now()
        self.assertEqual(self.db_count(), 1)

    def test_stop_flushes_pending(self):
        BookVisitService.record(1, 10)
        BookVisitService.stop()
        self.assertEqual(self.db_count(), 1)

    def test_list_pagination(self):
        for i in range(5):
            BookVisitService.record(1, i)
        rows, total = BookVisitService.list(1, 1, 2)
        self.assertEqual(total, 5)
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
