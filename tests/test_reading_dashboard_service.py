#!/usr/bin/env python3

import datetime
import json
import os
import shutil
import tempfile
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import loader, models
from webserver.models import Reader, Reading, ReadingState
from webserver.services import reading_dashboard_service as svc


class TestReadingDashboardService(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.conf = loader.get_settings()
        self._orig_sync_path = self.conf.get("MYREADER_SYNC_PATH")
        self.conf["MYREADER_SYNC_PATH"] = self.tmp_dir

        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)
        self.session.execute(
            text("CREATE UNIQUE INDEX ux_readings_read ON readings (reader_id, book_id, date) WHERE action='read'")
        )

        self.reader = Reader()
        self.reader.id = 1
        self.reader.username = "u1"
        self.reader.total_reading_seconds = 100
        self.reader.download_count = 3
        self.reader.push_count = 2
        self.session.add(self.reader)
        self.session.commit()

    def tearDown(self):
        self.session.remove()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        if self._orig_sync_path is None:
            self.conf.pop("MYREADER_SYNC_PATH", None)
        else:
            self.conf["MYREADER_SYNC_PATH"] = self._orig_sync_path

    def _add_reading(self, date, duration=0, action=Reading.ACTION_READ, book_id=100):
        row = Reading(1, book_id, action, Reading.PROTOCOL_APP, datetime.datetime.combine(date, datetime.time()), duration=duration)
        self.session.add(row)
        self.session.commit()

    def test_disabled_returns_none(self):
        self.conf["ENABLE_HOMEPAGE_READING_STATS"] = False
        try:
            self.assertIsNone(svc.get_stats(self.session, self.reader))
        finally:
            self.conf["ENABLE_HOMEPAGE_READING_STATS"] = True

    def test_totals_come_from_reader_columns(self):
        stats = svc.get_stats(self.session, self.reader)
        self.assertEqual(stats["totals"], {"total_reading_seconds": 100, "download_count": 3, "push_count": 2})

    def test_missing_cache_file_recomputes_from_db(self):
        today = datetime.datetime.utcnow().date()
        yesterday = today - datetime.timedelta(days=1)
        self._add_reading(yesterday, duration=600)
        self._add_reading(today, duration=120)

        stats = svc.get_stats(self.session, self.reader)
        weekly = stats["weekly"]
        self.assertEqual(len(weekly), 8)
        total_seconds = sum(w["reading_seconds"] for w in weekly)
        self.assertEqual(total_seconds, 720)

        # cache file should now exist with yesterday folded in
        cache_path = svc._user_cache_path(1)
        self.assertTrue(os.path.exists(cache_path))
        with open(cache_path) as f:
            cache = json.load(f)
        self.assertEqual(cache["cached_through"], svc._date_str(yesterday))
        self.assertIn(svc._date_str(yesterday), cache["days"])
        self.assertNotIn(svc._date_str(today), cache["days"])  # today never persisted

    def test_corrupt_cache_file_falls_back_to_recompute(self):
        os.makedirs(os.path.dirname(svc._user_cache_path(1)), exist_ok=True)
        with open(svc._user_cache_path(1), "w") as f:
            f.write("{not valid json")

        today = datetime.datetime.utcnow().date()
        yesterday = today - datetime.timedelta(days=1)
        self._add_reading(yesterday, duration=42)

        stats = svc.get_stats(self.session, self.reader)
        self.assertEqual(sum(w["reading_seconds"] for w in stats["weekly"]), 42)

    def test_second_call_same_day_does_not_rewrite_cache(self):
        today = datetime.datetime.utcnow().date()
        yesterday = today - datetime.timedelta(days=1)
        self._add_reading(yesterday, duration=10)
        svc.get_stats(self.session, self.reader)

        cache_path = svc._user_cache_path(1)
        mtime1 = os.path.getmtime(cache_path)

        # more "today" activity shouldn't touch the cache file
        self._add_reading(today, duration=5)
        svc.get_stats(self.session, self.reader)
        mtime2 = os.path.getmtime(cache_path)
        self.assertEqual(mtime1, mtime2)

    def test_book_status_categorizes_reading_to_read_finished(self):
        s1 = ReadingState(101, 1)
        s1.read_state = 1
        s2 = ReadingState(102, 1)
        s2.read_state = 2
        s3 = ReadingState(103, 1)
        s3.wants = 1
        s3.read_state = 0
        self.session.add_all([s1, s2, s3])
        self.session.commit()

        stats = svc.get_stats(self.session, self.reader)
        self.assertEqual(stats["book_status"], {"reading": 1, "finished": 1, "to_read": 1})

    def test_weekly_buckets_use_monday_start_and_cover_8_weeks(self):
        stats = svc.get_stats(self.session, self.reader)
        weekly = stats["weekly"]
        self.assertEqual(len(weekly), 8)
        today = datetime.datetime.utcnow().date()
        self.assertEqual(weekly[-1]["week_start"], svc._date_str(svc._week_start(today)))
        for w in weekly:
            d = datetime.datetime.strptime(w["week_start"], "%Y-%m-%d").date()
            self.assertEqual(d.weekday(), 0)  # Monday

    def test_heatmap_covers_13_weeks_starting_on_monday_through_today(self):
        today = datetime.datetime.utcnow().date()
        yesterday = today - datetime.timedelta(days=1)
        self._add_reading(yesterday, duration=1800)

        stats = svc.get_stats(self.session, self.reader)
        heatmap = stats["heatmap"]
        self.assertEqual(heatmap["weeks"], svc.HEATMAP_WEEKS)
        days = heatmap["days"]

        expected_start = svc._week_start(today) - datetime.timedelta(weeks=svc.HEATMAP_WEEKS - 1)
        self.assertEqual(days[0]["date"], svc._date_str(expected_start))
        self.assertEqual(days[-1]["date"], svc._date_str(today))
        # no future dates beyond today
        self.assertEqual(len(days), (today - expected_start).days + 1)

        by_date = {d["date"]: d["reading_seconds"] for d in days}
        self.assertEqual(by_date[svc._date_str(yesterday)], 1800)
        self.assertEqual(by_date[svc._date_str(today)], 0)

    def test_heatmap_uses_live_today_value_not_stale_cache(self):
        today = datetime.datetime.utcnow().date()
        self._add_reading(today, duration=300)
        stats = svc.get_stats(self.session, self.reader)
        days = stats["heatmap"]["days"]
        self.assertEqual(days[-1]["date"], svc._date_str(today))
        self.assertEqual(days[-1]["reading_seconds"], 300)


if __name__ == "__main__":
    unittest.main()
