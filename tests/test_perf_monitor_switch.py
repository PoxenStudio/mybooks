#!/usr/bin/env python3

import unittest
from unittest import mock

from webserver import loader
from webserver.services.perf_monitor import PerfMonitor


class TestMonitorSwitch(unittest.TestCase):

    def setUp(self):
        self.monitor = PerfMonitor()
        self.configured = self.monitor.enabled

    def test_default_is_off_in_settings(self):
        self.assertFalse(loader.get_settings().get("PERF_MONITOR"))
        self.assertFalse(loader.get_settings().get("LOG_LEVEL_DEBUG"))

    def test_disabled_monitor_records_nothing(self):
        self.monitor.enabled = False
        self.monitor.record_request("GET", "/api/x", 5.0)
        self.monitor.record_calibre("search", 1.0, 2.0)
        self.monitor.record_stage("fast.fields", 3.0)
        with self.monitor.stage("list.items_fetch"):
            pass
        snap = self.monitor.snapshot()
        self.assertEqual((snap["routes"], snap["calibre"], snap["stages"]), ({}, {}, {}))
        self.assertFalse(snap["running"])

    def test_enabled_follows_setting_from_creation(self):
        self.assertEqual(self.configured, bool(loader.get_settings().get("PERF_MONITOR")))
        with mock.patch.dict(loader.get_settings(), {"PERF_MONITOR": True}):
            self.assertTrue(PerfMonitor().enabled)

    def test_enabled_monitor_records(self):
        self.monitor.enabled = True
        self.monitor.record_stage("fast.fields", 3.0)
        self.assertIn("fast.fields", self.monitor.snapshot()["stages"])


if __name__ == "__main__":
    unittest.main()
