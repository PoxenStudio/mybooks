#!/usr/bin/env python3

import asyncio
import os
import tempfile
import time
import unittest
from unittest import mock

from webserver.base.query_cache import VersionedCache, library_version
from webserver.handlers.base import BaseHandler, ListHandler


class TestVersionedCache(unittest.TestCase):

    def test_hit_and_version_miss(self):
        cache = VersionedCache()
        cache.put("k", 1, "v")
        self.assertEqual(cache.get("k", 1), "v")
        self.assertIsNone(cache.get("k", 2))

    def test_ttl(self):
        cache = VersionedCache(ttl=10)
        cache.put("k", 1, "v")
        with mock.patch("webserver.base.query_cache.time.time", return_value=time.time() + 11):
            self.assertIsNone(cache.get("k", 1))

    def test_max_items_clears(self):
        cache = VersionedCache(max_items=2)
        for i in range(3):
            cache.put(i, 1, i)
        self.assertIsNone(cache.get(0, 1))
        self.assertEqual(cache.get(2, 1), 2)

    def test_library_version_follows_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "metadata.db")
            open(db, "w").close()
            backend = mock.Mock(dbpath=db)
            first = library_version(backend)
            open(db + "-wal", "w").close()
            self.assertNotEqual(library_version(backend), first)
            os.utime(db, ns=(1, 1))
            self.assertEqual(library_version(backend)[0], 1)


class TestHandlerCaches(unittest.TestCase):

    def setUp(self):
        BaseHandler._catalog_cache.clear()
        BaseHandler._search_cache.clear()
        self.handler = object.__new__(BaseHandler)
        self.handler.library_version = mock.Mock(return_value=(1, 0))
        self.handler.calibre_db_cache = mock.Mock()
        self.handler.calibre_db_cache.search.return_value = {3, 1, 2}
        self.handler.db_lock = mock.MagicMock()
        self.handler.calibre_db_cache.backend.conn.get.return_value = [(9,), (5,)]

    def test_search_cached_and_invalidated(self):
        self.assertEqual(sorted(self.handler.cached_search("q")), [1, 2, 3])
        self.handler.cached_search("q")
        self.assertEqual(self.handler.calibre_db_cache.search.call_count, 1)
        self.handler.library_version.return_value = (2, 0)
        self.handler.cached_search("q")
        self.assertEqual(self.handler.calibre_db_cache.search.call_count, 2)

    def test_search_result_is_a_copy(self):
        first = self.handler.cached_search("q")
        first.append(99)
        self.assertNotIn(99, self.handler.cached_search("q"))

    def test_books_by_id_cached(self):
        self.assertEqual(self.handler.books_by_id(), [9, 5])
        self.handler.books_by_id().append(1)
        self.assertEqual(self.handler.books_by_id(), [9, 5])
        self.assertEqual(self.handler.calibre_db_cache.backend.conn.get.call_count, 1)


class TestBookList(unittest.TestCase):

    def make(self, size, sort_values):
        handler = object.__new__(ListHandler)
        args = {"size": str(size)}
        handler.get_argument = lambda name, default=None: args.get(name, default)
        handler.get_argument_start = lambda: 0
        handler.calibre_db_cache = mock.Mock()
        handler.calibre_db_cache.all_field_for.side_effect = lambda field, ids, default: {i: sort_values[i] for i in ids}

        async def run_calibre(func, *a, **kw):
            return func(*a, **kw)

        async def books(ids, **kw):
            return [{"id": i} for i in ids]

        handler.run_calibre_async = run_calibre
        handler.get_books_for_list_async = mock.Mock(side_effect=lambda ids: books(ids))
        handler.fmt = lambda b, **kw: b
        return handler

    def test_size_is_capped(self):
        handler = self.make(1000, {})
        ids = list(range(500, 0, -1))
        result = asyncio.run(handler.get_book_list([], ids=ids, sort_fields="id"))
        self.assertEqual(len(result["books"]), 200)
        self.assertEqual(result["total"], 500)

    def test_title_sort_fetches_only_page(self):
        values = {i: "%03d" % (100 - i) for i in range(1, 101)}
        handler = self.make(40, values)
        ids = list(range(1, 101))
        result = asyncio.run(handler.get_book_list([], ids=ids, sort_fields="title"))
        self.assertEqual([b["id"] for b in result["books"]], list(range(100, 60, -1)))
        self.assertEqual(len(handler.get_books_for_list_async.call_args.kwargs["ids"]), 40)

    def test_input_order_kept_without_sort(self):
        handler = self.make(3, {})
        ids = [9, 4, 7, 1]
        result = asyncio.run(handler.get_book_list([], ids=ids, sort_fields=""))
        self.assertEqual([b["id"] for b in result["books"]], [9, 4, 7])


class TestAsyncHelpers(unittest.TestCase):

    def setUp(self):
        BaseHandler._catalog_cache.clear()
        BaseHandler._search_cache.clear()
        self.handler = object.__new__(BaseHandler)
        self.handler.library_version = mock.Mock(return_value=(1, 0))
        self.handler.calibre_db_cache = mock.Mock()
        self.handler.calibre_db_cache.search.return_value = {3, 1}
        self.handler.db_lock = mock.MagicMock()
        self.handler.calibre_db_cache.backend.conn.get.return_value = [(9,), (5,)]

        async def run_calibre(func, *a, **kw):
            return func(*a, **kw)

        self.handler.run_calibre_async = run_calibre

    def test_cached_search_async(self):
        self.assertEqual(sorted(asyncio.run(self.handler.cached_search_async("q"))), [1, 3])
        asyncio.run(self.handler.cached_search_async("q"))
        self.assertEqual(self.handler.calibre_db_cache.search.call_count, 1)

    def test_books_by_id_async_shares_cache_with_sync(self):
        self.assertEqual(asyncio.run(self.handler.books_by_id_async()), [9, 5])
        self.assertEqual(self.handler.books_by_id(), [9, 5])
        self.assertEqual(self.handler.calibre_db_cache.backend.conn.get.call_count, 1)

    def test_get_books_for_list_async_merges_on_loop(self):
        self.handler.calibre_db = mock.Mock()
        self.handler.calibre_db.get_data_as_dict.return_value = [{"id": 1}]
        self.handler._merge_books_full = mock.Mock(side_effect=lambda books, ts, item_maps: books)
        self.handler._item_maps_async = mock.AsyncMock(return_value=({}, {}))
        result = asyncio.run(self.handler.get_books_for_list_async(ids=[1]))
        self.assertEqual(result, [{"id": 1}])
        self.handler.calibre_db.get_data_as_dict.assert_called_once()


if __name__ == "__main__":
    unittest.main()
