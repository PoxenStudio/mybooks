#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
get_sys_info 类属性缓存的离线单元测试。

get_sys_info 被 /api/user/info 心跳与首页高频调用，内部做 5 项 calibre 全库聚合
与多项 sqlite 计数，弱 CPU 设备上每次代价高；现改为 60s 类属性缓存（模式与
AdminResources 的 _cache_data/_cache_time 一致）。这里用假 handler/假数据库验证：
1. 首次调用真实计算并写缓存；
2. TTL 内再次调用直接返回缓存对象，不再触达数据库；
3. 超过 TTL 后重新计算；
4. TTL 置 0 等价于关闭缓存，每次重算。
不启动真实服务，不依赖 calibre 安装。
"""

import unittest

from webserver.handlers.base import BaseHandler


class _FakeCalibreDB:
    """记录 get_sys_info 触发的 calibre 聚合调用次数。"""

    def __init__(self):
        self.calls = 0

    def count(self):
        self.calls += 1
        return 100

    def all_tags(self):
        self.calls += 1
        return ["t"]

    def all_authors(self):
        self.calls += 1
        return ["a"]

    def all_publishers(self):
        self.calls += 1
        return ["p"]

    def all_series(self):
        self.calls += 1
        return ["s"]

    def last_modified(self):
        self.calls += 1
        import datetime

        return datetime.datetime(2026, 10, 5)


class _FakeQuery:
    def filter(self, *args, **kwargs):
        return self

    def scalar(self):
        return 3


class _FakeSession:
    def query(self, *args, **kwargs):
        return _FakeQuery()


class SysInfoCacheTest(unittest.TestCase):
    def setUp(self):
        # 跳过 RequestHandler.__init__，仅装配 get_sys_info 触及的属性
        self.handler = BaseHandler.__new__(BaseHandler)
        self.db = _FakeCalibreDB()
        self.handler.calibre_db = self.db
        self.handler.sqlite_session = _FakeSession()
        self.handler.get_audio_books_count = lambda: 1
        self.handler.get_physical_books_count = lambda: 2
        self.handler.get_custom_category_count = lambda: 3
        self.handler.get_folder_count = lambda: 4
        self.handler.need_invited = lambda: False
        self.handler._build_friends_with_favicon = lambda: []
        # 保存并清空类级缓存，避免用例间互相污染
        self._saved = (
            BaseHandler._sys_info_cache,
            BaseHandler._sys_info_cache_time,
            BaseHandler.SYS_INFO_CACHE_TIME,
        )
        BaseHandler._sys_info_cache = None
        BaseHandler._sys_info_cache_time = 0.0
        BaseHandler.SYS_INFO_CACHE_TIME = 60

    def tearDown(self):
        (
            BaseHandler._sys_info_cache,
            BaseHandler._sys_info_cache_time,
            BaseHandler.SYS_INFO_CACHE_TIME,
        ) = self._saved

    def test_first_call_computes_and_caches(self):
        result = self.handler.get_sys_info()
        self.assertEqual(result["books"], 100)
        self.assertEqual(result["users"], 3)
        # count/all_tags/all_authors/all_publishers/all_series/last_modified
        self.assertEqual(self.db.calls, 6)
        self.assertIs(BaseHandler._sys_info_cache, result)

    def test_second_call_within_ttl_uses_cache(self):
        self.handler.get_sys_info()
        calls_after_first = self.db.calls
        again = self.handler.get_sys_info()
        self.assertIs(again, BaseHandler._sys_info_cache)
        self.assertEqual(self.db.calls, calls_after_first)

    def test_expired_ttl_recomputes(self):
        self.handler.get_sys_info()
        calls_after_first = self.db.calls
        # 把缓存时间戳拨回 TTL 之前，模拟过期
        BaseHandler._sys_info_cache_time -= BaseHandler.SYS_INFO_CACHE_TIME + 1
        self.handler.get_sys_info()
        self.assertEqual(self.db.calls, calls_after_first + 6)

    def test_zero_ttl_always_recomputes(self):
        BaseHandler.SYS_INFO_CACHE_TIME = 0
        self.handler.get_sys_info()
        calls_first = self.db.calls
        self.handler.get_sys_info()
        self.assertEqual(self.db.calls, calls_first + 6)


if __name__ == "__main__":
    unittest.main()
