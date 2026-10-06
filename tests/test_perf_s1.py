#!/usr/bin/env python3

import os
import tempfile
import time
import unittest
from unittest import mock

from webserver import utils
from webserver.handlers import book as book_module
from webserver.handlers.base import BaseHandler
from webserver.handlers.book import BookDownload


class TestOpenccCache(unittest.TestCase):

    def test_converter_is_reused(self):
        self.assertIs(utils.get_opencc("t2s"), utils.get_opencc("t2s"))
        self.assertEqual(utils.get_opencc("t2s").convert("漢字"), "汉字")


class FakeUser:
    id = 7


class TestDownloadCache(unittest.TestCase):

    def setUp(self):
        BookDownload._download_cache.clear()
        BookDownload._charged.clear()
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        self.addCleanup(os.remove, self.path)
        self.handler = object.__new__(BookDownload)
        self.handler.is_opds = False
        self.handler.current_user = FakeUser()
        self.handler.set_header = mock.Mock()
        self.handler.request = mock.Mock(method="GET")
        self.book = {"id": 5, "title": "t", "fmt_epub": self.path}
        self.handler.get_book = mock.Mock(return_value=self.book)

    def run_download(self):
        with mock.patch.object(book_module.DownloadQuotaService, "check_and_consume") as quota, \
                mock.patch.object(book_module.ReadingStatsService, "record_download") as record:
            quota.return_value = mock.Mock(allowed=True)
            path = self.handler.parse_url_path("/book/5.epub")
        return path, quota, record

    def test_quota_consumed_once_for_segments(self):
        total = 0
        for _ in range(7):
            path, quota, record = self.run_download()
            self.assertEqual(path, self.path)
            total += quota.call_count
        self.assertEqual(total, 1)
        self.assertEqual(self.handler.get_book.call_count, 1)

    def test_path_cache_expiry_within_window_does_not_charge_again(self):
        self.run_download()
        for key, value in list(BookDownload._download_cache.items()):
            BookDownload._download_cache[key] = (time.time() - 1, value[1], value[2])
        _, quota, _ = self.run_download()
        self.assertEqual(quota.call_count, 0)

    def test_charged_again_after_window(self):
        self.run_download()
        for key in list(BookDownload._charged):
            BookDownload._charged[key] = time.time() - 1
        _, quota, _ = self.run_download()
        self.assertEqual(quota.call_count, 1)

    def test_head_never_charges(self):
        self.handler.request = mock.Mock(method="HEAD")
        _, quota, record = self.run_download()
        self.assertEqual((quota.call_count, record.call_count), (0, 0))
        self.handler.request = mock.Mock(method="GET")
        _, quota, _ = self.run_download()
        self.assertEqual(quota.call_count, 1)

    def test_missing_format_does_not_charge(self):
        del self.book["fmt_epub"]
        with self.assertRaises(book_module.web.HTTPError):
            self.run_download()
        self.assertEqual(BookDownload._charged, {})

    def test_quota_exceeded_blocks_new_but_not_continuation(self):
        self.run_download()
        with mock.patch.object(book_module.DownloadQuotaService, "check_and_consume") as quota:
            quota.return_value = mock.Mock(allowed=False, used=3, quota=3)
            self.handler.parse_url_path("/book/5.epub")
            BookDownload._charged.clear()
            BookDownload._download_cache.clear()
            with self.assertRaises(book_module.web.HTTPError) as ctx:
                self.handler.parse_url_path("/book/5.epub")
        self.assertEqual(ctx.exception.status_code, 429)

    def test_cache_is_per_user(self):
        self.run_download()
        self.handler.current_user = type("U", (), {"id": 8})()
        _, quota, _ = self.run_download()
        self.assertEqual(quota.call_count, 1)

    def test_missing_file_falls_back(self):
        self.run_download()
        os.remove(self.path)
        self.run_download()
        self.assertEqual(self.handler.get_book.call_count, 2)
        open(self.path, "w").close()


class TestTokenThrottle(unittest.TestCase):

    def test_second_token_login_does_not_persist(self):
        BaseHandler._token_login_at.clear()
        handler = object.__new__(BaseHandler)
        user = mock.Mock(id=3)
        query = mock.Mock()
        query.filter.return_value.first.return_value = user
        handler.sqlite_session = mock.Mock()
        handler.sqlite_session.query.return_value = query
        handler.get_argument = mock.Mock(return_value="tok")
        handler.request = mock.Mock(headers={})
        handler.login_user = mock.Mock()
        handler.process_auth_token()
        handler.process_auth_token()
        self.assertEqual([c.kwargs["persist"] for c in handler.login_user.call_args_list], [True, False])


if __name__ == "__main__":
    unittest.main()
