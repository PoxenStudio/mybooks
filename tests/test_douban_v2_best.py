#!/usr/bin/env python3

import unittest
from unittest import mock

from webserver.plugins.meta.douban_v2 import plugin as plugin_module
from webserver.plugins.meta.douban_v2.plugin import DoubanV2MetaPlugin


class TestSearchBest(unittest.TestCase):

    def setUp(self):
        self.mi = mock.Mock(isbn=None, title="三体")
        patcher = mock.patch.object(DoubanV2MetaPlugin, "_acquire", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_error_response_returns_none_instead_of_raising(self):
        with mock.patch.object(plugin_module.api, "search", return_value=None):
            self.assertIsNone(DoubanV2MetaPlugin().search_best(self.mi))

    def test_exact_title_preferred(self):
        items = [{"title": "三体2"}, {"title": "三体"}]
        with mock.patch.object(plugin_module.api, "search", return_value=(items, "u")), \
                mock.patch.object(plugin_module.api, "build_metadata", side_effect=lambda best, *a, **k: best) as build:
            self.assertEqual(DoubanV2MetaPlugin().search_best(self.mi), {"title": "三体"})
        self.assertEqual(build.call_args[0][0], {"title": "三体"})

    def test_rate_limited_returns_none(self):
        with mock.patch.object(DoubanV2MetaPlugin, "_acquire", return_value=False):
            self.assertIsNone(DoubanV2MetaPlugin().search_best(self.mi))


if __name__ == "__main__":
    unittest.main()
