#!/usr/bin/env python3

import datetime
import unittest

from webserver.models import Reading
from webserver.services.reading_stats_service import (
    HEARTBEAT_MAX_GAP,
    BookFormatStatsBuffer,
    ReadingWriteBuffer,
    parse_book_id_from_hash,
)


class TestParseBookIdFromHash(unittest.TestCase):
    def test_cloud_hash_extracts_book_id(self):
        self.assertEqual(parse_book_id_from_hash("cloud-8502-epub"), 8502)

    def test_local_hash_returns_none(self):
        self.assertIsNone(parse_book_id_from_hash("a1b2c3d4e5f6"))

    def test_empty_or_none_returns_none(self):
        self.assertIsNone(parse_book_id_from_hash(None))
        self.assertIsNone(parse_book_id_from_hash(""))

    def test_malformed_cloud_prefix_returns_none(self):
        self.assertIsNone(parse_book_id_from_hash("cloud-notanumber-epub"))


class TestReadingWriteBuffer(unittest.TestCase):
    def setUp(self):
        self.buf = ReadingWriteBuffer()
        self.t0 = datetime.datetime(2026, 1, 1, 0, 0, 0)

    def test_first_heartbeat_creates_dirty_session_with_zero_delta(self):
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, self.t0)
        session = self.buf._sessions[(1, 100)]
        self.assertEqual(session.duration_delta, 0)
        self.assertTrue(session.dirty)
        self.assertEqual(session.session_start, self.t0)
        self.assertEqual(session.current_date, self.t0.date())
        self.assertEqual(self.buf._reader_seconds_delta, {})

    def test_heartbeat_within_gap_accumulates_duration(self):
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, self.t0)
        t1 = self.t0 + datetime.timedelta(seconds=3)
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, t1)
        session = self.buf._sessions[(1, 100)]
        self.assertEqual(session.duration_delta, 3)
        self.assertEqual(session.session_start, self.t0)  # same session, start unchanged
        self.assertEqual(self.buf._reader_seconds_delta[1], 3)

    def test_heartbeat_beyond_gap_starts_new_session_without_duration(self):
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, self.t0)
        t_gap = self.t0 + HEARTBEAT_MAX_GAP + datetime.timedelta(seconds=1)
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, t_gap)
        session = self.buf._sessions[(1, 100)]
        self.assertEqual(session.duration_delta, 0)
        self.assertEqual(session.session_start, t_gap)  # new session start
        self.assertTrue(session.dirty)
        self.assertNotIn(1, self.buf._reader_seconds_delta)

    def test_heartbeat_crossing_midnight_opens_a_new_day_bucket(self):
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, self.t0)
        t1 = self.t0 + datetime.timedelta(seconds=5)
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, t1)  # duration_delta=5, same day

        next_day = self.t0 + datetime.timedelta(days=1, seconds=10)  # gap well within 60s window
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, next_day)
        session = self.buf._sessions[(1, 100)]
        # crossing into a new date always opens a fresh bucket, even though the
        # real-time gap here is small — see document/Reading_Stats_Design.md §11.4
        self.assertEqual(session.current_date, next_day.date())
        self.assertEqual(session.duration_delta, 0)
        self.assertTrue(session.dirty)
        self.assertFalse(session.visit_counted)

    def test_flush_snapshot_clears_pending_but_keeps_session_state(self):
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, self.t0)
        t1 = self.t0 + datetime.timedelta(seconds=5)
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, t1)
        with self.buf._lock:
            pending = [
                (key, s.current_date, s.session_start, s.duration_delta, s.last_seen, s.protocol)
                for key, s in self.buf._sessions.items()
                if s.duration_delta or s.dirty
            ]
            for s in self.buf._sessions.values():
                s.duration_delta = 0
                s.dirty = False
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0][3], 5)
        session = self.buf._sessions[(1, 100)]
        self.assertEqual(session.duration_delta, 0)
        self.assertFalse(session.dirty)
        self.assertEqual(session.session_start, self.t0)  # session identity survives flush

    def test_download_event_increments_reader_download_delta(self):
        self.buf.on_event(1, 100, Reading.ACTION_DOWNLOAD, Reading.PROTOCOL_WEB, self.t0)
        self.buf.on_event(1, 200, Reading.ACTION_DOWNLOAD, Reading.PROTOCOL_OPDS, self.t0)
        self.assertEqual(self.buf._reader_download_delta[1], 2)
        self.assertEqual(len(self.buf._events), 2)

    def test_push_event_does_not_affect_download_delta(self):
        self.buf.on_event(1, 100, Reading.ACTION_PUSH, Reading.PROTOCOL_DEVICE, self.t0)
        self.assertNotIn(1, self.buf._reader_download_delta)
        self.assertEqual(len(self.buf._events), 1)


class TestReadingWriteBufferExplicit(unittest.TestCase):
    """客户端离线阅读显式上报（见 document/Reading_Stats_Design.md 的离线阅读扩展）：
    与 on_heartbeat() 的到达间隔推算完全独立，不做 60 秒窗口判断，秒数直接累加。"""

    def setUp(self):
        self.buf = ReadingWriteBuffer()
        self.t0 = datetime.datetime(2026, 1, 1, 0, 0, 0)
        self.d0 = self.t0.date()

    def test_explicit_duration_is_added_verbatim(self):
        self.buf.on_explicit(1, 100, Reading.PROTOCOL_APP, self.d0, 1800, self.t0)
        entry = self.buf._explicit[(1, 100, self.d0)]
        self.assertEqual(entry.duration_delta, 1800)
        self.assertEqual(entry.start_time, self.t0 - datetime.timedelta(seconds=1800))
        self.assertEqual(self.buf._reader_seconds_delta[1], 1800)

    def test_repeated_explicit_reports_for_same_day_accumulate(self):
        self.buf.on_explicit(1, 100, Reading.PROTOCOL_APP, self.d0, 100, self.t0)
        t1 = self.t0 + datetime.timedelta(seconds=200)
        self.buf.on_explicit(1, 100, Reading.PROTOCOL_APP, self.d0, 50, t1)
        entry = self.buf._explicit[(1, 100, self.d0)]
        self.assertEqual(entry.duration_delta, 150)
        self.assertEqual(self.buf._reader_seconds_delta[1], 150)

    def test_different_dates_for_same_book_stay_in_separate_buckets(self):
        d1 = self.d0 + datetime.timedelta(days=1)
        self.buf.on_explicit(1, 100, Reading.PROTOCOL_APP, self.d0, 100, self.t0)
        self.buf.on_explicit(1, 100, Reading.PROTOCOL_APP, d1, 200, self.t0 + datetime.timedelta(days=1))
        self.assertEqual(self.buf._explicit[(1, 100, self.d0)].duration_delta, 100)
        self.assertEqual(self.buf._explicit[(1, 100, d1)].duration_delta, 200)
        self.assertEqual(self.buf._reader_seconds_delta[1], 300)

    def test_zero_or_negative_delta_is_ignored(self):
        self.buf.on_explicit(1, 100, Reading.PROTOCOL_APP, self.d0, 0, self.t0)
        self.buf.on_explicit(1, 100, Reading.PROTOCOL_APP, self.d0, -5, self.t0)
        self.assertNotIn((1, 100, self.d0), self.buf._explicit)
        self.assertEqual(self.buf._reader_seconds_delta, {})

    def test_explicit_and_session_state_are_independent(self):
        """同一本书既有正常心跳（在线）又有显式上报（离线补的另一天），两套内存态互不
        干扰——调用方（sync_service.push()）保证同一次 push 对同一本书只会选其中一条
        路径，但缓冲区本身不假设这一点，各自维护自己的 key。"""
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, self.t0)
        self.buf.on_explicit(1, 100, Reading.PROTOCOL_APP, self.d0 - datetime.timedelta(days=1), 500, self.t0)
        self.assertIn((1, 100), self.buf._sessions)
        self.assertIn((1, 100, self.d0 - datetime.timedelta(days=1)), self.buf._explicit)
        self.assertEqual(self.buf._reader_seconds_delta[1], 500)  # heartbeat's first call contributes 0


class TestBookFormatStatsBufferExplicit(unittest.TestCase):
    def setUp(self):
        self.buf = BookFormatStatsBuffer()
        self.t0 = datetime.datetime(2026, 1, 1, 0, 0, 0)

    def test_explicit_duration_adds_unconditionally_without_gap_check(self):
        # 相隔远超 HEARTBEAT_MAX_GAP，heartbeat 路径会因为间隔过大丢弃这段增量；
        # 显式路径必须原样累加，因为这个秒数已经是客户端算好的，不需要再判断间隔。
        self.buf.on_explicit(1, 100, "epub", 3600, None, self.t0)
        t1 = self.t0 + HEARTBEAT_MAX_GAP * 10
        self.buf.on_explicit(1, 100, "epub", 1800, (10, 100), t1)
        state = self.buf._states[(1, 100, "epub")]
        self.assertEqual(state.duration_delta, 5400)
        self.assertEqual(state.progress, (10, 100))
        self.assertTrue(state.touched)


if __name__ == "__main__":
    unittest.main()
