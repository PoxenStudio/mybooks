#!/usr/bin/env python3

import asyncio
import logging
import os
import tempfile
import time
import unittest
from unittest import mock

from webserver import perf
from webserver.handlers import base as base_module
from webserver.handlers import book as book_module
from webserver.handlers.base import BaseHandler, HeavyGate, ListHandler, throttle
from webserver.handlers.book import BookDownload, BookUpload, SearchBook


def lite(**items):
    conf = {"PERFORMANCE_MODE": "lite"}
    conf.update(items)
    return mock.patch.dict(perf.CONF, conf)


def normal():
    return mock.patch.dict(perf.CONF, {"PERFORMANCE_MODE": "normal"})


class TestFastSearch(unittest.TestCase):

    def setUp(self):
        self.handler = object.__new__(SearchBook)
        self.queries = []
        self.results = {}

        async def search(query):
            self.queries.append(query)
            return self.results.get(query, [])

        self.handler.cached_search_async = search

    def test_plain_clause_covers_only_four_fields(self):
        clause = self.handler._fast_clause(["abc"], False)
        for field in ("title", "authors", "tags", "series"):
            self.assertIn('%s:"abc"' % field, clause)
        self.assertNotIn("comments", clause)

    def test_title_clause_is_exact(self):
        self.assertEqual(self.handler._fast_clause(["a", "b"], True), "title:=a OR title:=b")

    def test_conversion_only_when_nothing_found(self):
        first = self.handler._fast_clause(["漢字"], False)
        self.results[first] = [1, 2]
        self.assertEqual(asyncio.run(self.handler._fast_search("漢字", False)), [1, 2])
        self.assertEqual(self.queries, [first])

    def test_conversion_retried_on_empty_result(self):
        asyncio.run(self.handler._fast_search("漢字", False))
        self.assertEqual(len(self.queries), 2)
        self.assertIn("汉字", self.queries[1])

    def test_no_second_query_without_variants(self):
        asyncio.run(self.handler._fast_search("abc", False))
        self.assertEqual(len(self.queries), 1)


class FakeHandler:
    def __init__(self, user=7):
        self._user = user
        self.request = mock.Mock(remote_ip="1.2.3.4")
        self.headers = {}
        self.status = None
        self.written = []

    def user_id(self):
        return self._user

    def set_status(self, code):
        self.status = code

    def set_header(self, key, value):
        self.headers[key] = value

    def write(self, data):
        self.written.append(data)


class TestThrottle(unittest.TestCase):

    def setUp(self):
        HeavyGate.inflight = 0
        HeavyGate.per_user = {}

    def run_calls(self, decorator, count, users=None):
        return asyncio.run(self._runner(decorator, count, users))

    async def _runner(self, decorator, count, users):
        release = asyncio.Event()

        async def body(handler):
            await release.wait()
            return {"err": "ok"}

        wrapped = decorator(body)
        handlers = [FakeHandler(user=(users[i] if users else i + 100)) for i in range(count)]
        tasks = [asyncio.ensure_future(wrapped(h)) for h in handlers]
        await asyncio.sleep(0.05)
        release.set()
        return handlers, await asyncio.gather(*tasks)

    def test_over_limit_gets_503_with_retry_after(self):
        with lite(LITE_THROTTLE_LIMIT=2):
            handlers, results = self.run_calls(throttle(), 4)
        self.assertEqual([r["err"] for r in results].count("ok"), 2)
        busy = [h for h in handlers if h.status == 503]
        self.assertEqual(len(busy), 2)
        self.assertEqual(busy[0].headers["Retry-After"], "2")

    def test_counters_released_after_requests(self):
        with lite(LITE_THROTTLE_LIMIT=2):
            self.run_calls(throttle(), 3)
        self.assertEqual(HeavyGate.inflight, 0)
        self.assertEqual(HeavyGate.per_user, {})

    def test_per_user_limit_of_one(self):
        with lite(LITE_THROTTLE_LIMIT=10):
            handlers, results = self.run_calls(throttle(per_user=True), 3, users=[5, 5, 6])
        self.assertEqual([h.status for h in handlers], [None, 503, None])

    def test_write_mode_writes_body_instead_of_returning(self):
        with lite(LITE_THROTTLE_LIMIT=1):
            handlers, results = self.run_calls(throttle(write=True), 2)
        self.assertIsNone(results[1])
        self.assertEqual(handlers[1].written[0]["err"], "busy")

    def test_no_throttle_in_normal_mode(self):
        with normal():
            handlers, results = self.run_calls(throttle(), 6)
        self.assertTrue(all(r["err"] == "ok" for r in results))

    def test_exceptions_release_slot(self):
        async def boom(handler):
            raise ValueError("x")

        async def main():
            await throttle()(boom)(FakeHandler())

        with lite():
            with self.assertRaises(ValueError):
                asyncio.run(main())
        self.assertEqual(HeavyGate.inflight, 0)


class TestBookList(unittest.TestCase):

    def make(self, size="0"):
        handler = object.__new__(ListHandler)
        args = {"size": size}
        handler.get_argument = lambda name, default=None: args.get(name, default)
        handler.get_argument_start = lambda: 0
        self.fmt_calls = []

        async def books(ids, **kw):
            return [{"id": i} for i in ids]

        handler.get_books_for_list_async = mock.Mock(side_effect=lambda ids: books(ids))
        handler.fmt = lambda b, **kw: self.fmt_calls.append(kw) or b
        return handler

    def test_lite_caps_page_size_and_drops_comments(self):
        handler = self.make("200")
        with lite():
            result = asyncio.run(handler.get_book_list([], ids=list(range(300)), sort_fields=""))
        self.assertEqual(len(result["books"]), 60)
        self.assertTrue(all(kw["include_comments"] is False for kw in self.fmt_calls))

    def test_normal_keeps_comments_and_size(self):
        handler = self.make("200")
        with normal():
            result = asyncio.run(handler.get_book_list([], ids=list(range(300)), sort_fields=""))
        self.assertEqual(len(result["books"]), 200)
        self.assertTrue(all(kw["include_comments"] is True for kw in self.fmt_calls))

    def test_group_switch_off_restores_normal_behavior(self):
        handler = self.make("200")
        with lite(LITE_GROUP_LISTING=False):
            result = asyncio.run(handler.get_book_list([], ids=list(range(300)), sort_fields=""))
        self.assertEqual(len(result["books"]), 200)
        self.assertTrue(self.fmt_calls[0]["include_comments"])


class TestSearchCacheChoice(unittest.TestCase):

    def test_lite_uses_longer_ttl_cache(self):
        with lite():
            self.assertIs(BaseHandler.search_cache(), BaseHandler._search_cache_lite)
        with normal():
            self.assertIs(BaseHandler.search_cache(), BaseHandler._search_cache)
        with lite(LITE_GROUP_LISTING=False):
            self.assertIs(BaseHandler.search_cache(), BaseHandler._search_cache)


class TestUpload(unittest.TestCase):

    def test_after_import_skipped_in_lite(self):
        handler = object.__new__(BookUpload)
        handler.increase_history_count = mock.Mock()
        handler.user_id = lambda: 1
        handler.sqlite_session = mock.Mock()
        with lite(), mock.patch.object(book_module, "AutoFillService") as autofill, \
                mock.patch.object(book_module, "CatalogExtractService") as catalog:
            self.assertEqual(handler._after_import(mock.Mock(title="t"), 5), 5)
        autofill.assert_not_called()
        catalog.assert_not_called()
        handler.sqlite_session.commit.assert_called_once()

    def test_after_import_runs_extras_in_normal_mode(self):
        handler = object.__new__(BookUpload)
        handler.increase_history_count = mock.Mock()
        handler.user_id = lambda: 1
        handler.sqlite_session = mock.Mock()
        with normal(), mock.patch.object(book_module, "AutoFillService"), mock.patch.object(book_module, "CatalogExtractService") as catalog:
            handler._after_import(mock.Mock(title="t"), 5)
        catalog.return_value.extract_one_async.assert_called_once_with(5)

    def test_staged_file_removed_even_if_kept_in_lite(self):
        for mode, expected in ((lite(KEEP_UPLOAD_SOURCE_FILE=True), False), (normal(), True)):
            fd, path = tempfile.mkstemp()
            os.close(fd)
            with mode, mock.patch.dict(book_module.CONF, {"KEEP_UPLOAD_SOURCE_FILE": True}):
                BookUpload._remove_staged_file(path)
            self.assertEqual(os.path.exists(path), expected)
            if os.path.exists(path):
                os.remove(path)


class TestDownloadTtl(unittest.TestCase):

    def run_download(self):
        BookDownload._download_cache.clear()
        handler = object.__new__(BookDownload)
        handler.is_opds = False
        handler.current_user = mock.Mock(id=1)
        handler.set_header = mock.Mock()
        fd, path = tempfile.mkstemp()
        os.close(fd)
        self.addCleanup(os.remove, path)
        handler.get_book = mock.Mock(return_value={"id": 5, "title": "t", "fmt_epub": path})
        with mock.patch.object(book_module.DownloadQuotaService, "check_and_consume", return_value=mock.Mock(allowed=True)), \
                mock.patch.object(book_module.ReadingStatsService, "record_download"):
            handler.parse_url_path("/x/5.epub")
        return next(iter(BookDownload._download_cache.values()))[0] - time.time()

    def test_ttl_longer_in_lite(self):
        with normal():
            self.assertLess(self.run_download(), 61)
        with lite():
            self.assertGreater(self.run_download(), 500)


class TestLogLevel(unittest.TestCase):

    def test_toggle_restores_previous_level(self):
        root = logging.getLogger()
        original = root.level
        self.addCleanup(root.setLevel, original)
        root.setLevel(logging.INFO)
        perf._saved_level = None
        with lite():
            perf.apply_logging()
            self.assertEqual(root.level, logging.WARNING)
        with normal():
            perf.apply_logging()
            self.assertEqual(root.level, logging.INFO)
        self.assertIsNone(perf._saved_level)


class TestBaseModuleExports(unittest.TestCase):

    def test_throttle_exported(self):
        self.assertTrue(callable(base_module.throttle))


if __name__ == "__main__":
    unittest.main()
