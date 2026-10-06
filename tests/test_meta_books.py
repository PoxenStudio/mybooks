#!/usr/bin/env python3

import asyncio
import unittest
from unittest import mock

from webserver.handlers import meta
from webserver.handlers.meta import MetaBooks


class FakeCache:
    FIELDS = {
        "rating": {1: 4, 2: 8, 3: None, 4: 8},
        "series_index": {1: 2.0, 2: 1.0, 3: None, 4: 1.0},
        "sort": {1: "b", 2: "z", 3: "c", 4: "a"},
    }

    def all_field_for(self, field, ids, default):
        return {i: self.FIELDS[field].get(i, default) for i in ids}


def make_handler():
    handler = MetaBooks.__new__(MetaBooks)
    handler.calibre_db_cache = FakeCache()
    return handler


class TestMetaBooks(unittest.TestCase):

    def test_rating_sort_matches_rating_desc_then_id_desc(self):
        self.assertEqual(make_handler()._sorted_ids({1, 2, 3, 4}, "tag"), [4, 2, 1, 3])

    def test_series_sort_by_index_then_sort_key(self):
        self.assertEqual(make_handler()._sorted_ids({1, 2, 3, 4}, "series"), [3, 4, 2, 1])

    def test_get_pages_ids_instead_of_loading_all_books(self):
        handler = make_handler()
        handler.run_calibre_async = mock.AsyncMock(return_value={1, 2, 3, 4})
        handler.run_calibre_read_async = mock.AsyncMock(return_value=[4, 2, 1, 3])
        handler.render_book_list = mock.AsyncMock(return_value="rendered")
        with mock.patch.object(meta, "_", side_effect=lambda s: s):
            result = asyncio.run(handler.get("language", "中文"))
        self.assertEqual(result, "rendered")
        handler.render_book_list.assert_awaited_once()
        self.assertEqual(handler.render_book_list.await_args.kwargs["ids"], [4, 2, 1, 3])
        self.assertEqual(handler.render_book_list.await_args.args[0], [])


if __name__ == "__main__":
    unittest.main()
