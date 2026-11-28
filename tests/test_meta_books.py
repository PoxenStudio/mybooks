#!/usr/bin/env python3

import asyncio
import unittest
from unittest import mock

from webserver.handlers import meta
from webserver.handlers.meta import (
    MAX_KEYWORDS,
    KeywordBooks,
    MetaBooks,
    build_keyword_query,
    split_keywords,
)


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

    def test_new_sort(self):
        self.assertEqual(make_handler()._sorted_ids({1, 2, 3, 4}, "tag", "new"), [4, 3, 2, 1])

    def test_keyword_default_sort_is_new(self):
        self.assertEqual(make_handler()._sorted_ids({1, 2, 3, 4}, "keyword"), [4, 3, 2, 1])

    def test_title_sort(self):
        self.assertEqual(make_handler()._sorted_ids({1, 2, 3, 4}, "tag", "title"), [4, 1, 3, 2])

    def test_random_sort_keeps_all_ids(self):
        result = make_handler()._sorted_ids({1, 2, 3, 4}, "tag", "random")
        self.assertEqual(sorted(result), [1, 2, 3, 4])

    def test_invalid_rating_returns_empty_without_raising(self):
        """公开路由 /api/rating/<name>：非 1-5 整数不能让 int() 抛给 @js。"""
        handler = make_handler()
        # '²'.isdigit() 为 True 但 int() 抛 ValueError，是 isdigit() 预判漏掉的一类。
        for bad in ("abc", "0", "6", "", "4.5", "²"):
            self.assertEqual(handler._book_ids("rating", bad), set(), bad)

    def test_unicode_decimal_digit_rating_is_parsed(self):
        """'٣'（阿拉伯-印度数字 3）isdigit() 为 True 且 int() 可解析，按 3 星处理。"""
        handler = make_handler()
        handler.calibre_db_cache.backend = mock.Mock()
        handler.calibre_db_cache.backend.conn.get = mock.Mock(return_value=[])
        handler.calibre_db = mock.Mock()
        self.assertEqual(handler._book_ids("rating", "٣"), set())
        _, params = handler.calibre_db_cache.backend.conn.get.call_args.args
        self.assertEqual(params, (5, 6))

    def test_rating_reads_ratings_table_and_unions_categories(self):
        """rating 走 ratings 表的 0-10 原始分值（4 星 = 7/8），再按 item id 取书。"""
        handler = make_handler()
        handler.calibre_db_cache.backend = mock.Mock()
        handler.calibre_db_cache.backend.conn.get = mock.Mock(return_value=[(3,), (2,)])
        handler.calibre_db = mock.Mock()
        handler.calibre_db.get_books_for_category = (
            lambda category, item_id: {1, 2} if item_id == 2 else {3}
        )
        self.assertEqual(handler._book_ids("rating", "4"), {1, 2, 3})
        sql, params = handler.calibre_db_cache.backend.conn.get.call_args.args
        self.assertIn("FROM ratings", sql)
        self.assertEqual(params, (7, 8))

    def test_get_pages_ids_instead_of_loading_all_books(self):
        handler = make_handler()
        handler.get_argument = lambda name, default=None: {
            "sort": "new",
            "cover": "1",
        }.get(name, default)
        handler.run_calibre_async = mock.AsyncMock(return_value={1, 2, 3, 4})
        handler.run_calibre_read_async = mock.AsyncMock(return_value=[4, 2, 1, 3])
        handler.get_book_list = mock.AsyncMock(return_value={"err": "ok", "books": [{"id": 4}]})
        handler.request = mock.Mock()
        handler.request.headers = {}
        handler.written = None
        handler.set_header = lambda *args, **kwargs: None
        handler.write = lambda rsp: setattr(handler, "written", rsp)
        handler.finish = lambda: None
        with mock.patch.object(meta, "_", side_effect=lambda s: s):
            asyncio.run(MetaBooks.get(handler, "language", "中文"))
        self.assertEqual(handler.written, {"err": "ok", "books": [{"id": 4}]})
        handler.run_calibre_read_async.assert_awaited_once()
        sort_args = handler.run_calibre_read_async.await_args.args
        self.assertEqual(sort_args[2], "language")
        self.assertEqual(sort_args[3], "new")
        handler.get_book_list.assert_awaited_once()
        self.assertEqual(handler.get_book_list.await_args.kwargs["ids"], [4, 2, 1, 3])
        self.assertFalse(handler.get_book_list.await_args.kwargs["include_comments"])
        self.assertEqual(handler.get_book_list.await_args.args[0], [])


class TestKeywordBooks(unittest.TestCase):

    def test_split_keywords_separators_and_quotes(self):
        self.assertEqual(
            split_keywords('三体,黑暗、 森林;"Harry Potter" 魔法'),
            ["三体", "黑暗", "森林", "Harry Potter", "魔法"],
        )

    def test_split_keywords_dedup_and_cap(self):
        words = split_keywords(" ".join("k%d" % i for i in range(MAX_KEYWORDS + 3)))
        self.assertEqual(len(words), MAX_KEYWORDS)
        self.assertEqual(split_keywords("三体 三体 三體"), ["三体", "三體"])

    def test_split_keywords_drops_punctuation_only_words(self):
        """纯标点词在 Calibre 的标题包含匹配里会退化成空查询命中整库，必须丢弃。"""
        self.assertEqual(split_keywords("- ... ?? 三体"), ["三体"])
        self.assertEqual(split_keywords("--- ..."), [])
        self.assertEqual(split_keywords('"..." "Harry Potter"'), ["Harry Potter"])

    def test_split_keywords_keeps_cjk_digits_and_underscore_lead(self):
        """isalnum 判定：CJK/英文/数字/带下划线的词都保留，纯下划线/空白/emoji 丢弃。"""
        self.assertEqual(split_keywords("三体 2024 _temp _ 😀"), ["三体", "2024", "_temp"])
        self.assertEqual(split_keywords("  \u3000  "), [])

    def test_build_keyword_query_forces_literal_contains(self):
        """首字符 = ~ ^ \\ 在 Calibre 里是精确/正则等特殊语义，必须强制按字面包含。"""
        with mock.patch.object(meta.utils, "get_opencc", side_effect=lambda p: mock.Mock(convert=lambda v: v)):
            self.assertEqual(
                build_keyword_query("~三体 =GAMERS ^x"),
                '(title:"\\\\~三体") OR (title:"\\\\=GAMERS") OR (title:"\\\\^x")',
            )
        self.assertEqual(build_keyword_query("-"), "")

    def test_build_keyword_query_any_and_traditional_variant(self):
        def fake_opencc(profile):
            mapping = {"三体": "三體"} if profile == "s2t" else {}
            return mock.Mock(convert=lambda value: mapping.get(value, value))

        with mock.patch.object(meta.utils, "get_opencc", side_effect=fake_opencc):
            query = build_keyword_query("三体 黑暗", "any")
        self.assertEqual(query, '(title:"三体" OR title:"三體") OR (title:"黑暗")')

    def test_build_keyword_query_all(self):
        with mock.patch.object(meta.utils, "get_opencc", side_effect=lambda p: mock.Mock(convert=lambda v: v)):
            query = build_keyword_query("三体 黑暗", "all")
        self.assertEqual(query, '(title:"三体") AND (title:"黑暗")')

    def test_build_keyword_query_escapes_quotes_and_backslashes(self):
        with mock.patch.object(meta.utils, "get_opencc", side_effect=lambda p: mock.Mock(convert=lambda v: v)):
            query = build_keyword_query('a"b\\c')
        self.assertEqual(query, '(title:"a\\"b\\\\c")')

    def test_keyword_get_uses_match_sort_and_cover(self):
        handler = make_keyword_handler({"match": "ALL", "sort": "title", "cover": "1"})
        with mock.patch.object(meta, "_", side_effect=lambda s: s), mock.patch.object(
            meta, "build_keyword_query", return_value='(title:"三体")'
        ) as build:
            asyncio.run(KeywordBooks.get(handler, " 三体 "))
        build.assert_called_once_with("三体", "all")
        handler.cached_search_async.assert_awaited_once_with('(title:"三体")')
        handler.run_calibre_read_async.assert_awaited_once()
        self.assertEqual(handler.run_calibre_read_async.await_args.args[2], "title")
        handler.get_book_list.assert_awaited_once()
        self.assertEqual(handler.get_book_list.await_args.kwargs["ids"], [3, 2, 1])
        self.assertFalse(handler.get_book_list.await_args.kwargs["include_comments"])
        self.assertEqual(handler.written, {"err": "ok", "books": [{"id": 3}]})

    def test_keyword_get_rejects_unknown_match_and_sort(self):
        handler = make_keyword_handler({"match": "regex", "sort": "series"})
        with mock.patch.object(meta, "_", side_effect=lambda s: s), mock.patch.object(
            meta, "build_keyword_query", return_value='(title:"三体")'
        ) as build:
            asyncio.run(KeywordBooks.get(handler, "三体"))
        build.assert_called_once_with("三体", "any")
        self.assertEqual(handler.run_calibre_read_async.await_args.args[2], "new")

    def test_keyword_get_empty_value_skips_search(self):
        handler = make_keyword_handler({})
        with mock.patch.object(meta, "_", side_effect=lambda s: s), mock.patch.object(
            meta, "build_keyword_query", return_value=""
        ):
            asyncio.run(KeywordBooks.get(handler, "   "))
        handler.cached_search_async.assert_not_awaited()
        self.assertEqual(handler.written, {"err": "ok", "books": [{"id": 3}]})

    def test_keyword_get_search_failure_returns_empty_page(self):
        handler = make_keyword_handler({})
        handler.cached_search_async = mock.AsyncMock(side_effect=RuntimeError("boom"))
        with mock.patch.object(meta, "_", side_effect=lambda s: s), mock.patch.object(
            meta, "build_keyword_query", return_value='(title:"三体")'
        ):
            asyncio.run(KeywordBooks.get(handler, "三体"))
        # 搜索失败只降级为空结果，排序列不应拿到任何 id
        self.assertEqual(handler.run_calibre_read_async.await_args.args[1], [])
        handler.get_book_list.assert_awaited_once()
        self.assertEqual(handler.written, {"err": "ok", "books": [{"id": 3}]})

    def test_keyword_route_registered(self):
        paths = [rule[0] for rule in meta.routes()]
        self.assertIn(r"/api/keyword/(.*)", paths)


def make_keyword_handler(args):
    handler = KeywordBooks.__new__(KeywordBooks)
    handler.get_argument = lambda name, default=None: args.get(name, default)
    handler.cached_search_async = mock.AsyncMock(return_value={1, 2, 3})
    handler.run_calibre_read_async = mock.AsyncMock(return_value=[3, 2, 1])
    handler.get_book_list = mock.AsyncMock(
        return_value={"err": "ok", "books": [{"id": 3}]}
    )
    handler.request = mock.Mock()
    handler.request.headers = {}
    handler.written = None
    handler.set_header = lambda *args, **kwargs: None
    handler.write = lambda rsp: setattr(handler, "written", rsp)
    handler.finish = lambda: None
    return handler


if __name__ == "__main__":
    unittest.main()
