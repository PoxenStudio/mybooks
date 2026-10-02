#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Unit tests for ioloop offloading helpers — utils.run_in_threadpool and
BaseHandler.run_calibre_async/get_book_async.

导入/刮削等后台任务持有 calibre 独占写锁期间，ioloop 线程上的同步 calibre 调用会
连带冻住全站请求（Tornado 单线程事件循环）。这里用假 handler/假数据库验证：
1. run_in_threadpool 确实把调用送到共享线程池并透传参数/结果/异常；
2. get_book_async 的 calibre 段在工作线程执行、sqlite 合并段留在调用线程，
   且与同步 get_book 的合并结果一致（拆分无行为回归）。
不启动真实服务，不依赖 calibre 安装。
"""

import asyncio
import threading
import unittest

from tornado import web

from webserver.handlers.base import BaseHandler
from webserver.models import Item, Reader
from webserver.utils import blocking_pool, calibre_pool, run_in_threadpool


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def order_by(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeCollector:
    def __init__(self, name="alice"):
        self._name = name

    def to_dict(self):
        return {"name": self._name}


class _FakeItemRow:
    def __init__(self, book_id, sole=False, collector_id=1):
        self.book_id = book_id
        self.sole = sole
        self.collector_id = collector_id
        self.collector = _FakeCollector()

    def to_dict(self):
        return {
            "book_id": self.book_id,
            "sole": self.sole,
            "collector_id": self.collector_id,
        }


class _FakeSession:
    def __init__(self, readers=(), items=()):
        self._readers = list(readers)
        self._items = list(items)

    def query(self, model):
        if model is Reader:
            return _FakeQuery(self._readers)
        if model is Item:
            return _FakeQuery(self._items)
        raise AssertionError("unexpected model %r" % model)


class _FakeCalibreDB:
    """get_data_as_dict 的假实现：记录执行线程并返回固定书目。"""

    field_metadata = {}

    def __init__(self, books):
        self._books = books
        self.calls = []
        self.thread_names = []

    def get_data_as_dict(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        self.thread_names.append(threading.current_thread().name)
        return list(self._books)


def _make_handler(books, items=()):
    # 跳过 RequestHandler.__init__（需要 application/db），只装配被测路径触及的属性
    handler = BaseHandler.__new__(BaseHandler)
    handler.request = None
    handler.calibre_db = _FakeCalibreDB(books)
    handler.db_lock = threading.RLock()
    handler.sqlite_session = _FakeSession(items=items)
    handler.write = lambda chunk: None
    handler.set_status = lambda status, reason=None: None
    handler.user_id = lambda: 1
    return handler


class TestRunInThreadpool(unittest.TestCase):
    def test_returns_result_with_args_and_kwargs(self):
        def work(a, b, scale=1):
            return (a + b) * scale

        self.assertEqual(
            asyncio.run(run_in_threadpool(work, 2, 3, scale=10)),
            50,
        )

    def test_runs_on_shared_pool_thread(self):
        observed = {}

        def work():
            observed["thread"] = threading.current_thread().name

        asyncio.run(run_in_threadpool(work))
        self.assertTrue(
            observed["thread"].startswith("mybooks-blocking"),
            "expected work on shared blocking pool, got %r" % observed["thread"],
        )

    def test_propagates_exception(self):
        def work():
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            asyncio.run(run_in_threadpool(work))


class TestPoolIsolation(unittest.TestCase):
    def test_calibre_pool_separate_from_network_pool(self):
        # 联网长任务（单次可达分钟级）打满 blocking_pool 时，阅读链路的毫秒级
        # calibre 查询不能跟着排队——两池必须隔离
        self.assertIsNot(calibre_pool, blocking_pool)
        self.assertNotEqual(calibre_pool._thread_name_prefix, blocking_pool._thread_name_prefix)


class TestGetBookAsync(unittest.TestCase):
    BOOKS = [{"id": 7, "title": "Book Seven", "colnum": "v"}]

    def setUp(self):
        # _merge_books_full 会读 CONF 的阅读范围开关，保持默认关闭即可
        self.handler = _make_handler(
            self.BOOKS,
            items=[_FakeItemRow(7, sole=False, collector_id=3)],
        )

    def test_calibre_call_runs_off_ioloop(self):
        main_thread = threading.current_thread().name
        book = asyncio.run(self.handler.get_book_async(7))
        self.assertIsNotNone(book)
        self.assertEqual(book["title"], "Book Seven")
        # calibre 查询必须发生在专用池线程而非 ioloop（这是本次修复的核心契约）
        for name in self.handler.calibre_db.thread_names:
            self.assertNotEqual(name, main_thread)
            self.assertTrue(name.startswith("mybooks-calibre"))

    def test_merges_sqlite_item_data(self):
        book = asyncio.run(self.handler.get_book_async(7))
        # _merge_books_simple 把 Item/collector 信息并入 calibre 元数据
        self.assertEqual(book["collector_id"], 3)
        self.assertEqual(book["collector"]["name"], "alice")

    def test_missing_book_returns_none(self):
        self.handler.calibre_db = _FakeCalibreDB([])
        self.assertIsNone(
            asyncio.run(self.handler.get_book_async(999, raise_exception=False))
        )

    def test_missing_book_raises_finish_when_requested(self):
        self.handler.calibre_db = _FakeCalibreDB([])
        with self.assertRaises(web.Finish):
            asyncio.run(self.handler.get_book_async(999, raise_exception=True))

    def test_matches_sync_get_book_result(self):
        # 拆分回归保障：同步路径与异步路径产出的合并结果一致
        sync_book = self.handler.get_book(7, fully=False, raise_exception=False)
        async_book = asyncio.run(self.handler.get_book_async(7, fully=False))
        self.assertEqual(sync_book, async_book)


if __name__ == "__main__":
    unittest.main()
