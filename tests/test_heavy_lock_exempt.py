#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""极速模式单一大任务锁（LITE_ONE_HEAVY_TASK）的常驻服务豁免测试。

极速模式下所有注册的后台服务任务共用 heavy_task_lock 串行执行；常驻型服务
（函数永不返回）不能参与该锁——它启动后永久持锁，邮件推送、格式转换等其它
后台任务会全部饿死（容器实测：推送只入队、永不发送）。用"挂住的长任务 +
heavy=False 注册的常驻服务"钉住两点：常驻服务不被锁阻塞、普通服务仍排队。
"""

import threading
import unittest
from unittest import mock

from webserver import perf
from webserver.services.async_service import AsyncService

BOOKBARN_DAILY_CHECK = "webserver.services.book_barn.BookBarnService.get_daily_books"
BOOKBARN_AUTHOR_SYNC = "webserver.services.book_barn.BookBarnService.sync_author_list"


def stub_hung_task(ins, started, release):
    """模拟占住大任务锁的长任务：进入（已持锁）后等 release 才结束"""
    started.set()
    release.wait(10)


def stub_normal_task(ins, done):
    done.set()


def stub_daemon_task(ins, done):
    done.set()


class _StubScopedSession:
    """scoped_session 拟件：loop 既调用它取 session（用 hash_key），也直接取 .remove()"""

    class _Session:
        hash_key = 0

    def __call__(self):
        return self._Session()

    def remove(self):
        pass


class TestHeavyLockExempt(unittest.TestCase):
    def setUp(self):
        AsyncService.running = {}
        # loop 尾部会调用 self.scoped_session.remove()，而任务线程可能在测试结束后才
        # 执行到这里：用带 hash_key/remove() 的拟件替换默认 lambda，且不还原
        AsyncService().scoped_session = _StubScopedSession()
        self.original_exempt = set(AsyncService.heavy_lock_exempt)
        # 走真实装饰器登记豁免名单（幂等）
        AsyncService.register_service(stub_daemon_task, heavy=False)

    def tearDown(self):
        AsyncService.heavy_lock_exempt.clear()
        AsyncService.heavy_lock_exempt.update(self.original_exempt)

    def _enqueue(self, func, *args):
        """与 register_service 包装器等价的投递：取服务队列放入一个任务"""
        queue = AsyncService().start_service(func)
        queue.put((args, {}))

    def test_daemon_runs_while_heavy_lock_held(self):
        started, release, daemon_done = threading.Event(), threading.Event(), threading.Event()
        try:
            with mock.patch.dict(perf.CONF, {"PERFORMANCE_MODE": "lite"}):
                self._enqueue(stub_hung_task, started, release)
                self.assertTrue(started.wait(5), "长任务未能在 5s 内启动并持锁")
                self._enqueue(stub_daemon_task, daemon_done)
                self.assertTrue(daemon_done.wait(5), "常驻服务被大任务锁挡住——heavy=False 豁免失效")
        finally:
            release.set()

    def test_normal_task_still_waits_for_heavy_lock(self):
        started, release, normal_done = threading.Event(), threading.Event(), threading.Event()
        try:
            with mock.patch.dict(perf.CONF, {"PERFORMANCE_MODE": "lite"}):
                self._enqueue(stub_hung_task, started, release)
                self.assertTrue(started.wait(5), "长任务未能在 5s 内启动并持锁")
                self._enqueue(stub_normal_task, normal_done)
                self.assertFalse(normal_done.wait(0.5), "普通服务不应绕过单一大任务锁")
                release.set()
                self.assertTrue(normal_done.wait(5), "锁释放后普通服务应能继续执行")
        finally:
            release.set()


class TestBookBarnRegistration(unittest.TestCase):
    def test_daily_check_is_heavy_lock_exempt(self):
        # import 即触发 BookBarnService 方法上的装饰器登记
        from webserver.services import book_barn  # noqa: F401

        self.assertIn(BOOKBARN_DAILY_CHECK, AsyncService.heavy_lock_exempt)

    def test_author_sync_is_exempt_too(self):
        from webserver.services import book_barn  # noqa: F401

        self.assertIn(BOOKBARN_AUTHOR_SYNC, AsyncService.heavy_lock_exempt)

    def test_single_author_update_keeps_default_serialization(self):
        from webserver.services import book_barn  # noqa: F401

        self.assertNotIn("webserver.services.book_barn.BookBarnService.update_author_async", AsyncService.heavy_lock_exempt)
