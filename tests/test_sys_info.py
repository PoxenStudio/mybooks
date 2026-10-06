#!/usr/bin/env python3

import asyncio
import datetime
import unittest
from unittest import mock

from webserver.handlers.base import BaseHandler


class TestSysInfo(unittest.TestCase):

    def setUp(self):
        BaseHandler._stats_cache.clear()
        handler = object.__new__(BaseHandler)
        handler.library_version = mock.Mock(return_value=(1, 0))
        handler.calibre_db = mock.Mock()
        handler.calibre_db.count.return_value = 5
        handler.calibre_db.all_tags.return_value = ["a", "b"]
        handler.calibre_db.all_authors.return_value = ["x"]
        handler.calibre_db.all_publishers.return_value = []
        handler.calibre_db.all_series.return_value = []
        handler.calibre_db.last_modified.return_value = datetime.datetime(2026, 1, 2)
        handler.get_audio_books_count = mock.Mock(return_value=1)
        handler.get_custom_category_count = mock.Mock(return_value=2)
        handler.get_folder_count = mock.Mock(return_value=3)
        handler.get_physical_books_count = mock.Mock(return_value=4)
        handler._build_friends_with_favicon = mock.Mock(return_value=[])
        handler.need_invited = mock.Mock(return_value=False)
        handler.sqlite_session = mock.Mock()
        handler.sqlite_session.query.return_value.scalar.return_value = 7
        handler.sqlite_session.query.return_value.filter.return_value.scalar.return_value = 3

        async def run_calibre(func, *a, **kw):
            return func(*a, **kw)

        handler.run_calibre_async = run_calibre
        self.handler = handler

    def test_sync_and_async_have_same_keys(self):
        sync_info = self.handler.get_sys_info()
        async_info = asyncio.run(self.handler.get_sys_info_async())
        self.assertEqual(set(sync_info), set(async_info))
        for key in ("books", "tags", "authors", "audiobooks", "publishers", "series", "categories", "folders", "physicals", "mtime", "users", "active", "version", "title", "allow", "installed"):
            self.assertIn(key, async_info)
        self.assertEqual(async_info["tags"], 2)
        self.assertEqual(async_info["users"], 7)

    def test_lite_flags_follow_mode_and_group(self):
        from webserver import perf

        for conf, expected in (({"PERFORMANCE_MODE": "lite", "LITE_GROUP_RECOMMEND": True}, True), ({"PERFORMANCE_MODE": "lite", "LITE_GROUP_RECOMMEND": False}, False), ({"PERFORMANCE_MODE": "normal"}, False)):
            with mock.patch.dict(perf.CONF, conf):
                info = asyncio.run(self.handler.get_sys_info_async())
            self.assertEqual(info["lite"], {"homeCollapse": expected})
            self.assertEqual(info["performanceMode"], conf["PERFORMANCE_MODE"])

    def test_library_part_cached_user_counts_live(self):
        asyncio.run(self.handler.get_sys_info_async())
        self.handler.sqlite_session.query.return_value.scalar.return_value = 8
        info = asyncio.run(self.handler.get_sys_info_async())
        self.assertEqual(self.handler.calibre_db.all_tags.call_count, 1)
        self.assertEqual(info["users"], 8)

    def test_invalidated_by_library_version(self):
        asyncio.run(self.handler.get_sys_info_async())
        self.handler.library_version.return_value = (2, 0)
        asyncio.run(self.handler.get_sys_info_async())
        self.assertEqual(self.handler.calibre_db.all_tags.call_count, 2)


if __name__ == "__main__":
    unittest.main()
