#!/usr/bin/env python3

import time
import unittest
from unittest import mock

from webserver.handlers.base import BaseHandler
from webserver.handlers.book import BookDownloadSign, routes


def make_handler():
    handler = object.__new__(BaseHandler)
    handler.application = mock.Mock()
    handler.application.settings = {"cookie_secret": "secret"}
    return handler


class TestDownloadSign(unittest.TestCase):

    def test_roundtrip_binds_user_book_and_format(self):
        handler = make_handler()
        sign = handler.make_download_sign(7, "15", "EPUB")
        self.assertEqual(handler.parse_download_sign(sign, "15", "epub"), 7)
        self.assertIsNone(handler.parse_download_sign(sign, "16", "epub"))
        self.assertIsNone(handler.parse_download_sign(sign, "15", "mobi"))

    def test_sign_expires_after_max_age_from_creation(self):
        handler = make_handler()
        now = time.time()
        ttl = handler.DOWNLOAD_SIGN_MAX_AGE_SECONDS
        with mock.patch("webserver.handlers.base.time.time", return_value=now):
            sign = handler.make_download_sign(7, "15", "epub")
        with mock.patch("webserver.handlers.base.time.time", return_value=now + ttl - 1):
            self.assertEqual(handler.parse_download_sign(sign, "15", "epub"), 7)
        with mock.patch("webserver.handlers.base.time.time", return_value=now + ttl + 1):
            self.assertIsNone(handler.parse_download_sign(sign, "15", "epub"))

    def test_route_registered_before_download_pattern(self):
        patterns = [r[0] for r in routes()]
        self.assertLess(patterns.index(r"/api/book/([0-9]+)/download_sign"), patterns.index(r"/api/book/([0-9]+\..+)"))
        self.assertTrue(any(r[1] is BookDownloadSign for r in routes() if r[0].endswith("download_sign")))


if __name__ == "__main__":
    unittest.main()
