#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import io
import json
import os
import unittest

from webserver import i18n

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# OPDS 一级目录会显示的固定文案 + calibre 内置分类名
OPDS_KEYS = (
    "Library",
    "Books in your library",
    "Newest",
    "Title",
    "Date",
    "By {0}",
    "By {0} :: {1}",
    "Books sorted by {0}",
    "Authors",
    "Series",
    "Publisher",
    "Tags",
    "Rating",
    "Languages",
    "Published",
    "Comments",
    "News",
    "Book Category",
    "Book Folder",
    "Translator",
    "Location",
)


class TestOpdsTranslations(unittest.TestCase):
    def setUp(self):
        self._original_language = i18n.get_language()

    def tearDown(self):
        i18n.set_language(self._original_language)

    def test_catalogs_cover_opds_top_level(self):
        for name in ("zh", "zh-TW", "en"):
            with io.open(os.path.join(ROOT, "webserver", "i18n", "%s.json" % name), encoding="utf-8") as fp:
                catalog = json.load(fp)
            for key in OPDS_KEYS:
                self.assertIn(key, catalog, msg="%s.json 缺少 %s" % (name, key))
                self.assertTrue(catalog[key].strip(), msg="%s.json 的 %s 是空翻译" % (name, key))

    def test_site_language_translates_top_level(self):
        cases = {
            "zh": ("书库", "按最新", "按评分"),
            "zh-TW": ("書庫", "依最新", "依評分"),
            "en": ("Library", "By Newest", "By Rating"),
        }
        columns = {
            "zh": ("分类", "目录", "译者", "所在位置"),
            "zh-TW": ("分類", "目錄", "譯者", "所在位置"),
            "en": ("Book Category", "Book Folder", "Translator", "Location"),
        }
        for language, (library, newest, rating) in cases.items():
            i18n.set_language(language)
            self.assertEqual(i18n._("Library"), library)
            self.assertEqual(i18n._("By {0}").format(i18n._("Newest")), newest)
            self.assertEqual(i18n._("By {0}").format(i18n._("Rating")), rating)
            self.assertEqual(
                tuple(i18n._(key) for key in ("Book Category", "Book Folder", "Translator", "Location")),
                columns[language],
            )

    def test_unknown_message_falls_back_to_source(self):
        for language in ("zh", "zh-TW", "en"):
            i18n.set_language(language)
            self.assertEqual(i18n._("不存在的测试文案"), "不存在的测试文案")


if __name__ == "__main__":
    unittest.main()
