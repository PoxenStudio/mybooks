#!/usr/bin/env python3

import unittest
from unittest import mock

from webserver.services.download_quota_service import DownloadQuotaService, QuotaResult

STATS = "webserver.services.reading_stats_service.ReadingStatsService.record_download"


class TestDownloadCharge(unittest.TestCase):
    def setUp(self):
        DownloadQuotaService._charged.clear()
        self.reader = mock.Mock(id=7)

    def test_repeat_within_window_charges_once(self):
        with mock.patch(STATS) as rec, mock.patch.object(
            DownloadQuotaService, "check_and_consume", return_value=QuotaResult(True, 1, 5)
        ) as consume, mock.patch.object(DownloadQuotaService, "get_usage", return_value=QuotaResult(True, 1, 5)):
            for _ in range(3):
                self.assertTrue(DownloadQuotaService.charge(self.reader, 15, "EPUB", "webdav").allowed)
            self.assertEqual(consume.call_count, 1)
            self.assertEqual(rec.call_count, 1)

    def test_different_format_or_book_charged_separately(self):
        with mock.patch(STATS) as rec, mock.patch.object(
            DownloadQuotaService, "check_and_consume", return_value=QuotaResult(True, 1, 0)
        ):
            DownloadQuotaService.charge(self.reader, 15, "epub", "web")
            DownloadQuotaService.charge(self.reader, 15, "pdf", "web")
            DownloadQuotaService.charge(self.reader, 16, "epub", "web")
            self.assertEqual(rec.call_count, 3)

    def test_denied_records_nothing_and_does_not_open_window(self):
        with mock.patch(STATS) as rec, mock.patch.object(
            DownloadQuotaService, "check_and_consume", return_value=QuotaResult(False, 5, 5)
        ) as consume:
            self.assertFalse(DownloadQuotaService.charge(self.reader, 15, "epub", "webdav").allowed)
            self.assertFalse(DownloadQuotaService.charge(self.reader, 15, "epub", "webdav").allowed)
            self.assertEqual(consume.call_count, 2)
            rec.assert_not_called()

    def test_no_quota_mode_skips_consume(self):
        with mock.patch(STATS) as rec, mock.patch.object(
            DownloadQuotaService, "check_and_consume"
        ) as consume, mock.patch.object(DownloadQuotaService, "get_usage", return_value=QuotaResult(True, 0, 5)):
            DownloadQuotaService.charge(self.reader, 15, "epub", "web", consume_quota=False)
            consume.assert_not_called()
            self.assertEqual(rec.call_count, 1)

    def test_concurrent_retries_charge_once(self):
        import threading
        import time as _t

        def slow_consume(_reader):
            _t.sleep(0.05)
            return QuotaResult(True, 1, 5)

        with mock.patch(STATS) as rec, mock.patch.object(
            DownloadQuotaService, "check_and_consume", side_effect=slow_consume
        ) as consume, mock.patch.object(DownloadQuotaService, "get_usage", return_value=QuotaResult(True, 1, 5)):
            threads = [threading.Thread(target=DownloadQuotaService.charge, args=(self.reader, 15, "epub", "web")) for _ in range(4)]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
            self.assertEqual(consume.call_count, 1)
            self.assertEqual(rec.call_count, 1)


if __name__ == "__main__":
    unittest.main()
