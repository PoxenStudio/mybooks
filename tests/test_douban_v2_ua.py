#!/usr/bin/env python3

import json
import sys
import types
import unittest
from unittest import mock

from webserver.plugins.meta.douban_v2 import api


def search_page(items):
    data = {"items": [dict(i, tpl_name="search_subject") for i in items]}
    return mock.Mock(status_code=200, text="window.__DATA__ = %s;" % json.dumps(data))


class FakeMetadata:
    def __init__(self, title):
        self.title = title


class TestUserAgent(unittest.TestCase):

    def setUp(self):
        modules = {
            "calibre": types.ModuleType("calibre"),
            "calibre.ebooks": types.ModuleType("calibre.ebooks"),
            "calibre.ebooks.metadata": types.ModuleType("calibre.ebooks.metadata"),
            "calibre.ebooks.metadata.book": types.ModuleType("calibre.ebooks.metadata.book"),
            "calibre.ebooks.metadata.book.base": types.SimpleNamespace(Metadata=FakeMetadata),
            "calibre.utils": types.ModuleType("calibre.utils"),
            "calibre.utils.date": types.SimpleNamespace(utcnow=lambda: None),
        }
        patcher = mock.patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ua_is_picked_from_list_per_search(self):
        seen = set()
        for _ in range(200):
            with mock.patch.object(api.requests, "get", return_value=search_page([])) as get:
                api.search("x")
            seen.add(get.call_args.kwargs["headers"]["User-Agent"])
        self.assertGreater(len(seen), 1)
        self.assertTrue(seen <= set(api.UA_LIST))

    def test_search_detail_and_cover_share_one_ua(self):
        item = {"title": "三体", "abstract": "刘慈欣 / 重庆出版社 / 2008-1 / 23", "url": "https://book.douban.com/subject/1/", "cover_url": "https://img/s/1.jpg"}
        with mock.patch.object(api.requests, "get", return_value=search_page([item])) as get:
            items, search_url = api.search("三体")
        agents = []

        def record(url, headers=None, **kwargs):
            agents.append(headers["User-Agent"])
            return mock.Mock(status_code=200, text="<html></html>", headers={"Content-Type": "image/jpeg"}, content=b"x", raise_for_status=lambda: None)

        session = mock.Mock()
        session.get.side_effect = record
        with mock.patch.object(api.requests, "get", side_effect=record), mock.patch.object(api.requests, "Session", return_value=session):
            api.build_metadata(items[0], search_url, copy_image=True, get_detail=True)
        self.assertEqual(len(agents), 2)
        self.assertEqual(set(agents), {get.call_args.kwargs["headers"]["User-Agent"]})

    def test_different_books_may_use_different_ua(self):
        items = [{"title": "a", "_ua": api.UA_LIST[0]}, {"title": "b", "_ua": api.UA_LIST[1]}]
        used = []
        with mock.patch.object(api, "get_book_detail", side_effect=lambda url, s, ua=None: used.append(ua)):
            for item in items:
                item["url"] = "https://book.douban.com/subject/%s/" % item["title"]
                api.build_metadata(item, "u", get_detail=True)
        self.assertEqual(used, [api.UA_LIST[0], api.UA_LIST[1]])


if __name__ == "__main__":
    unittest.main()
