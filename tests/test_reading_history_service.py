#!/usr/bin/env python3

import datetime
import json
import os
import shutil
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import loader, models
from webserver.models import BookReadingStats, ManualReadingLog, Reader, Reading, ReadingState
from webserver.services.reading_history_service import ReadingHistoryService


def _dt(day, hour=8):
    return datetime.datetime(2026, 10, day, hour, 0, 0)


class TestReadingHistoryService(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.conf = loader.get_settings()
        self._orig_sync_path = self.conf.get("MYREADER_SYNC_PATH")
        self.conf["MYREADER_SYNC_PATH"] = self.tmp_dir

        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)

        self.reader = Reader()
        self.reader.id = 1
        self.reader.username = "u1"
        self.reader.total_reading_seconds = 7200
        self.other_reader = Reader()
        self.other_reader.id = 2
        self.other_reader.username = "u2"
        self.other_reader.total_reading_seconds = 999
        self.session.add_all([self.reader, self.other_reader])
        self.session.commit()

        self.session.add_all(
            [
                Reading(1, 100, Reading.ACTION_READ, Reading.PROTOCOL_WEB, _dt(1, 8), duration=60, date=datetime.date(2026, 10, 1)),
                Reading(1, 100, Reading.ACTION_READ, Reading.PROTOCOL_APP, _dt(2, 9), duration=120, date=datetime.date(2026, 10, 2)),
                Reading(1, 200, Reading.ACTION_READ, Reading.PROTOCOL_KOREADER, _dt(1, 10), duration=30, date=datetime.date(2026, 10, 1)),
                Reading(1, 100, Reading.ACTION_DOWNLOAD, Reading.PROTOCOL_OPDS, _dt(1, 11), duration=0, date=datetime.date(2026, 10, 1)),
                Reading(2, 100, Reading.ACTION_READ, Reading.PROTOCOL_WEB, _dt(1, 12), duration=999, date=datetime.date(2026, 10, 1)),
            ]
        )
        self.session.add_all(
            [
                ManualReadingLog(
                    reader_id=1, book_id=100, format="epub", date=datetime.date(2026, 10, 1),
                    duration_seconds=60, create_time=_dt(1), update_time=_dt(1),
                ),
                ManualReadingLog(
                    reader_id=1, book_id=200, format="epub", date=datetime.date(2026, 10, 1),
                    duration_seconds=30, create_time=_dt(1), update_time=_dt(1),
                ),
                ManualReadingLog(
                    reader_id=2, book_id=100, format="epub", date=datetime.date(2026, 10, 1),
                    duration_seconds=999, create_time=_dt(1), update_time=_dt(1),
                ),
                BookReadingStats(
                    reader_id=1, book_id=100, format="epub", state=BookReadingStats.STATE_READING,
                    total_seconds=180, create_time=_dt(1), update_time=_dt(2),
                ),
            ]
        )
        self.session.add(ReadingState(100, 1))
        self.session.commit()
        self._write_cache(1)

    def tearDown(self):
        self.session.remove()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        if self._orig_sync_path is None:
            self.conf.pop("MYREADER_SYNC_PATH", None)
        else:
            self.conf["MYREADER_SYNC_PATH"] = self._orig_sync_path

    def _cache_path(self, uid):
        return os.path.join(self.tmp_dir, str(uid), "reading.json")

    def _write_cache(self, uid):
        path = self._cache_path(uid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fp:
            json.dump({"version": 1, "cached_through": "2026-10-01", "days": {}}, fp)

    def _read_rows(self, reader_id=1, action=Reading.ACTION_READ):
        return self.session.query(Reading).filter_by(reader_id=reader_id, action=action).all()

    def test_summary_counts_only_read_rows(self):
        summary = ReadingHistoryService.summary(1)
        self.assertEqual(
            summary,
            {
                "records": 3,
                "books": 2,
                "total_seconds": 210,
                "first_date": "2026-10-01",
                "last_date": "2026-10-02",
            },
        )

    def test_book_summaries_group_by_book(self):
        rows = {row["book_id"]: row for row in ReadingHistoryService.book_summaries(1)}
        self.assertEqual(rows[100]["records"], 2)
        self.assertEqual(rows[100]["total_seconds"], 180)
        self.assertEqual(rows[100]["first_date"], "2026-10-01")
        self.assertEqual(rows[100]["last_date"], "2026-10-02")
        self.assertEqual(rows[200]["records"], 1)
        self.assertEqual(rows[200]["total_seconds"], 30)

    def test_book_records_are_descending_and_scoped(self):
        rows = ReadingHistoryService.book_records(1, 100)
        self.assertEqual([row["date"] for row in rows], ["2026-10-02", "2026-10-01"])
        self.assertEqual([row["duration"] for row in rows], [120, 60])
        self.assertTrue(all(row["protocol"] for row in rows))

    def test_delete_one_day(self):
        deleted = ReadingHistoryService.delete(1, book_id=100, date=datetime.date(2026, 10, 1))
        self.assertEqual(deleted["records"], 1)
        self.assertEqual(deleted["total_seconds"], 60)
        self.assertEqual(deleted["manual_records"], 1)

        dates = {row.date for row in self.session.query(Reading).filter_by(reader_id=1, book_id=100, action="read")}
        self.assertEqual(dates, {datetime.date(2026, 10, 2)})
        self.assertEqual(self._read_rows(2)[0].duration, 999)
        self.assertEqual(self._read_rows(action=Reading.ACTION_DOWNLOAD)[0].book_id, 100)
        self.session.expire_all()
        self.assertEqual(self.session.get(Reader, 1).total_reading_seconds, 7140)
        self.assertEqual(
            self.session.query(ManualReadingLog).filter_by(reader_id=1, book_id=100).one_or_none(),
            None,
        )
        self.assertIsNotNone(
            self.session.query(ManualReadingLog).filter_by(reader_id=1, book_id=200).one_or_none()
        )
        self.assertFalse(os.path.exists(self._cache_path(1)))

    def test_delete_book_removes_all_days_and_manual_logs(self):
        deleted = ReadingHistoryService.delete(1, book_id=100)
        self.assertEqual(deleted["records"], 2)
        self.assertEqual(deleted["total_seconds"], 180)
        self.assertEqual(deleted["manual_records"], 1)

        remaining = self.session.query(Reading).filter_by(reader_id=1, action="read").all()
        self.assertEqual([row.book_id for row in remaining], [200])
        self.session.expire_all()
        self.assertEqual(self.session.get(Reader, 1).total_reading_seconds, 7020)
        self.assertEqual(
            self.session.query(ManualReadingLog).filter_by(reader_id=1, book_id=100).one_or_none(),
            None,
        )
        self.assertFalse(os.path.exists(self._cache_path(1)))

    def test_clear_all_keeps_other_actions_and_other_users(self):
        deleted = ReadingHistoryService.delete(1)
        self.assertEqual(deleted["records"], 3)
        self.assertEqual(deleted["books"], 2)
        self.assertEqual(deleted["total_seconds"], 210)
        self.assertEqual(deleted["manual_records"], 2)

        self.assertEqual(self._read_rows(1), [])
        self.assertEqual(len(self._read_rows(action=Reading.ACTION_DOWNLOAD)), 1)
        self.assertEqual(len(self._read_rows(2)), 1)
        self.session.expire_all()
        self.assertEqual(self.session.get(Reader, 1).total_reading_seconds, 0)
        self.assertEqual(
            self.session.get(Reader, 2).total_reading_seconds, 999
        )
        self.assertEqual(
            self.session.query(ManualReadingLog).filter_by(reader_id=1).count(), 0
        )
        self.assertEqual(
            self.session.query(ManualReadingLog).filter_by(reader_id=2).count(), 1
        )
        self.assertEqual(
            self.session.query(BookReadingStats).filter_by(reader_id=1).count(), 1
        )
        self.assertEqual(
            self.session.query(ReadingState).filter_by(reader_id=1).count(), 1
        )
        self.assertFalse(os.path.exists(self._cache_path(1)))

    def test_delete_empty_scope_keeps_cache(self):
        deleted = ReadingHistoryService.delete(1, book_id=999)
        self.assertEqual(deleted["records"], 0)
        self.assertEqual(deleted["manual_records"], 0)
        self.assertTrue(os.path.exists(self._cache_path(1)))


if __name__ == "__main__":
    unittest.main()
