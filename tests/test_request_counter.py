#!/usr/bin/env python3

import unittest
from unittest import mock

from webserver.base import request_counter
from webserver.base.request_counter import RequestCounter


class FakeClock:

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TestRequestCounter(unittest.TestCase):

    def setUp(self):
        self.clock = FakeClock()
        patcher = mock.patch.object(request_counter.time, "monotonic", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def burst(self, counter):
        n = 0
        while not counter.is_exceeded():
            counter.record()
            n += 1
        return n

    def test_plan_window(self):
        cases = {180: (60, 3), 90: (120, 3), 100: (180, 5), 7: (300, 1), 60: (60, 1), 1000: (180, 50)}
        for max_per_hour, (seconds, limit) in cases.items():
            c = RequestCounter(max_per_hour)
            self.assertEqual((c.window_seconds, c.limit), (seconds, limit), max_per_hour)

    def test_window_never_exceeds_five_minutes(self):
        for max_per_hour in range(1, 400):
            self.assertLessEqual(RequestCounter(max_per_hour).window_seconds, 300)
            self.assertGreaterEqual(RequestCounter(max_per_hour).limit, 1)

    def test_allows_double_limit_in_window(self):
        c = RequestCounter(180)
        self.assertEqual(self.burst(c), 6)
        self.assertTrue(c.is_exceeded())

    def test_borrowed_window_blocks_next_window(self):
        c = RequestCounter(180)
        self.assertEqual(self.burst(c), 6)
        self.clock.advance(60)
        self.assertEqual(self.burst(c), 0)
        self.clock.advance(60)
        self.assertEqual(self.burst(c), 6)
        self.clock.advance(60)
        self.assertEqual(self.burst(c), 0)

    def test_blocked_window_stays_blocked_until_it_ends(self):
        c = RequestCounter(180)
        self.burst(c)
        self.clock.advance(60)
        self.clock.advance(59)
        self.assertTrue(c.is_exceeded())
        self.clock.advance(1)
        self.assertFalse(c.is_exceeded())

    def test_within_limit_does_not_block_next_window(self):
        c = RequestCounter(180)
        for _ in range(3):
            c.record()
        self.assertFalse(c.is_exceeded())
        self.clock.advance(60)
        self.assertEqual(self.burst(c), 6)

    def test_one_over_limit_still_blocks_next_window(self):
        c = RequestCounter(180)
        for _ in range(4):
            c.record()
        self.clock.advance(60)
        self.assertTrue(c.is_exceeded())

    def test_idle_for_multiple_windows_resets(self):
        c = RequestCounter(180)
        self.burst(c)
        self.clock.advance(120)
        self.assertEqual(self.burst(c), 6)

    def test_small_hourly_limit_uses_five_minute_window(self):
        c = RequestCounter(7)
        self.assertEqual(self.burst(c), 2)
        self.clock.advance(300)
        self.assertEqual(self.burst(c), 0)
        self.clock.advance(300)
        self.assertEqual(self.burst(c), 2)


class TestDoubanV2RateLimit(unittest.TestCase):

    def setUp(self):
        from webserver.plugins.meta.douban_v2 import plugin as douban_plugin
        self.module = douban_plugin
        self.cls = douban_plugin.DoubanV2MetaPlugin
        self.plugin = self.cls()
        exhausted = mock.Mock()
        exhausted.is_exceeded.return_value = True
        exhausted.window_seconds = 60
        exhausted.limit = 3
        self.exhausted = exhausted

    def test_limit_configured(self):
        self.assertEqual(self.cls.MAX_REQUESTS_PER_HOUR, 180)
        self.assertEqual(self.cls._counter.limit, 3)

    def test_exceeded_short_circuits_all_four_methods(self):
        mi = mock.Mock(isbn="9787220105203", title="t")
        with mock.patch.object(self.cls, "_counter", self.exhausted), mock.patch.object(self.module.api, "search") as search:
            self.assertEqual(self.plugin.search(title="t"), [])
            self.assertIsNone(self.plugin.search_best(mi))
            self.assertIsNone(self.plugin.get_metadata_by_provider("1", item={"title": "t"}))
            self.assertIsNone(self.plugin.search_physical_by_isbn("9787220105203"))
            search.assert_not_called()
        self.exhausted.record.assert_not_called()

    def test_each_method_records_one_request(self):
        counter = mock.Mock()
        counter.is_exceeded.return_value = False
        mi = mock.Mock(isbn="9787220105203", title="t")
        with mock.patch.object(self.cls, "_counter", counter), \
                mock.patch.object(self.module.api, "search", return_value=([], "u")), \
                mock.patch.object(self.module.api, "build_metadata_batch", return_value=[]), \
                mock.patch.object(self.module.api, "build_metadata", return_value=None):
            self.plugin.search(title="t")
            self.plugin.search_best(mi)
            self.plugin.get_metadata_by_provider("1", item={"title": "t"})
            self.plugin.search_physical_by_isbn("9787220105203")
        self.assertEqual(counter.record.call_count, 4)


if __name__ == "__main__":
    unittest.main()
