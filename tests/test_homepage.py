#!/usr/bin/env python3

import unittest
from unittest import mock

from webserver.base import homepage as homepage_module
from webserver.base.homepage import (
    BUILTIN_SECTIONS,
    MAX_CUSTOM_CARDS,
    default_homepage,
    homepage_from_legacy,
    normalize_homepage,
)


class TestHomepageConfig(unittest.TestCase):

    def test_default(self):
        config = normalize_homepage({})
        self.assertEqual(config["version"], 1)
        self.assertEqual(config["order"], list(BUILTIN_SECTIONS))
        self.assertEqual(config["hidden"], [])
        self.assertEqual(config["custom"], [])

    def test_unknown_sections_are_dropped_and_missing_appended(self):
        config = normalize_homepage(
            {
                "order": ["unknown", "index.myReading", "custom:c1", "index.myReading"],
                "hidden": ["unknown", "index.myReading"],
                "custom": [{"id": "c1", "type": "author", "value": "刘慈欣"}],
            }
        )
        self.assertEqual(
            config["order"],
            [
                "index.myReading",
                "custom:c1",
                "libraryStats",
                "readingStats",
                "index.socialRecommendation",
                "index.booklistRecommendation",
                "index.randomRecommendation",
                "index.newRecommendation",
            ],
        )
        self.assertEqual(config["order"].count("index.myReading"), 1)
        self.assertNotIn("unknown", config["order"])
        self.assertEqual(config["hidden"], ["index.myReading"])
        self.assertEqual(set(config["order"]), set(BUILTIN_SECTIONS) | {"custom:c1"})

    def test_custom_card_normalization(self):
        config = normalize_homepage(
            {
                "custom": [
                    {
                        "id": "bad id",
                        "type": "series",
                        "value": "  三体  ",
                        "sort": "bad",
                        "limit": 999,
                    },
                    {"id": "dup", "type": "tag", "value": "科幻"},
                    {"id": "dup", "type": "tag", "value": "奇幻"},
                ]
            }
        )
        cards = config["custom"]
        self.assertEqual(cards[0]["id"], "c1")
        self.assertEqual(cards[0]["value"], "三体")
        self.assertNotIn("title", cards[0])
        self.assertEqual(cards[0]["sort"], "series")
        self.assertEqual(cards[0]["limit"], 12)
        self.assertEqual(cards[1]["id"], "dup")
        self.assertNotEqual(cards[2]["id"], "dup")

    def test_unknown_type_skipped_empty_value_kept(self):
        config = normalize_homepage(
            {
                "custom": [
                    {"type": "unknown", "value": "x"},
                    {"type": "author", "value": "   "},
                    {"type": "author", "value": "OK", "limit": 24},
                    {"type": "tag", "value": {"bad": 1}},
                ]
            }
        )
        self.assertEqual(len(config["custom"]), 3)
        self.assertEqual(config["custom"][0]["value"], "")
        self.assertEqual(config["custom"][1]["value"], "OK")
        self.assertEqual(config["custom"][1]["limit"], 24)
        self.assertEqual(config["custom"][2]["value"], "")

    def test_custom_card_limit(self):
        cards = [
            {"id": "c%d" % i, "type": "author", "value": "a%d" % i}
            for i in range(MAX_CUSTOM_CARDS + 10)
        ]
        config = normalize_homepage({"custom": cards})
        self.assertEqual(len(config["custom"]), MAX_CUSTOM_CARDS)

    def test_bad_root_returns_default(self):
        self.assertEqual(normalize_homepage(None), default_homepage())
        self.assertEqual(normalize_homepage([]), default_homepage())

    def test_legacy_flags_become_hidden_sections(self):
        config = homepage_from_legacy(
            {
                "ENABLE_HOMEPAGE_READING_STATS": False,
                "ENABLE_HOMEPAGE_READING_BOOKS": False,
                "ENABLE_HOMEPAGE_BOOKLISTS": False,
                "ENABLE_BOOK_RECOMMEND_TO_OTHERS": False,
                "MAIN_PAGE_RANDOM_COUNT": 0,
            }
        )
        self.assertEqual(
            set(config["hidden"]),
            {
                "readingStats",
                "index.myReading",
                "index.booklistRecommendation",
                "index.socialRecommendation",
                "index.randomRecommendation",
            },
        )

    def test_legacy_defaults_hide_booklists(self):
        config = homepage_from_legacy({})
        self.assertEqual(config["hidden"], ["index.booklistRecommendation"])


class TestGetHomepageConfig(unittest.TestCase):
    """接线层：get_homepage_config 的两条分支（磁盘配置优先 / 无配置回退旧开关）。"""

    def test_stored_config_wins(self):
        stored = {"order": ["index.myReading"], "hidden": ["index.myReading"], "custom": []}
        with mock.patch(
            "webserver.loader.get_settings", return_value={"HOMEPAGE_CONFIG": stored}
        ):
            config = homepage_module.get_homepage_config()
        self.assertEqual(config["order"][0], "index.myReading")
        self.assertEqual(config["hidden"], ["index.myReading"])

    def test_falls_back_to_legacy_when_missing(self):
        settings = {
            "ENABLE_HOMEPAGE_READING_STATS": False,
            "ENABLE_HOMEPAGE_BOOKLISTS": True,
        }
        with mock.patch("webserver.loader.get_settings", return_value=settings):
            config = homepage_module.get_homepage_config()
        self.assertEqual(config["hidden"], ["readingStats"])

    def test_non_dict_stored_config_falls_back_to_legacy(self):
        """auto.py 被手改成字符串/列表时不能当作"全部可见"。"""
        settings = {"HOMEPAGE_CONFIG": "oops", "ENABLE_HOMEPAGE_BOOKLISTS": False}
        with mock.patch("webserver.loader.get_settings", return_value=settings):
            config = homepage_module.get_homepage_config()
        self.assertEqual(config["hidden"], ["index.booklistRecommendation"])

    def test_homepage_route_is_registered(self):
        from webserver.handlers import book as book_module

        paths = [rule[0] for rule in book_module.routes()]
        self.assertIn(r"/api/homepage", paths)
        self.assertIn(r"/api/index", paths)
        self.assertIn(r"/api/index/random", paths)
        self.assertIn(r"/api/index/new", paths)
        self.assertIn(r"/api/index/social", paths)


class TestLegacyHomeIds(unittest.TestCase):
    """legacy 选书对 avoid_ids 的避让语义与条数补齐（换一批把屏幕上的书传进 exclude）。

    纯函数测试：_legacy_home_ids 不用 self，传 None 调用。"""

    def pick(self, ids, cnt_random, cnt_recent, avoid=frozenset()):
        from webserver.handlers import book as book_module

        return book_module.Index._legacy_home_ids(None, ids, cnt_random, cnt_recent, avoid)

    def test_avoids_shown_ids(self):
        ids = list(range(1, 41))
        avoid = frozenset(range(1, 21))
        random_ids, new_ids = self.pick(ids, 12, 12, avoid)
        self.assertFalse(set(random_ids) & avoid)
        self.assertFalse(set(new_ids) & avoid)
        self.assertEqual(len(random_ids), 12)
        self.assertEqual(len(new_ids), 12)

    def test_fills_count_when_pool_is_partial(self):
        """池子还有书但不够 cnt：先挑光池子，再从避让集合补齐条数。

        回归：只 sample 池子（min(cnt, len(pool)) 不补）会让「换一批」把
        随便看看越换越短——20 本库首屏 8 张、刷新后 3 张。"""
        ids = list(range(1, 21))
        avoid = frozenset(range(1, 13))  # 剩 8 本没在屏幕上
        pool = set(ids) - avoid
        random_ids, new_ids = self.pick(ids, 12, 12, avoid)
        for picked in (random_ids, new_ids):
            self.assertEqual(len(picked), 12)
            self.assertTrue(set(picked) <= set(ids))
            # 避让后的池子必须被用完，重复只允许出现在补齐的那部分
            self.assertTrue(pool <= set(picked), picked)

    def test_falls_back_when_pool_too_small(self):
        ids = list(range(1, 41))
        # 全部排除：宁可重复也不开天窗
        random_ids, new_ids = self.pick(ids, 12, 12, frozenset(ids))
        self.assertEqual(len(random_ids), 12)
        self.assertEqual(len(new_ids), 12)
        self.assertTrue(set(random_ids) <= set(ids))
        self.assertTrue(set(new_ids) <= set(ids))

    def test_new_ids_stay_in_newest_window(self):
        """补足只从「全库最新 600 本」里取，不会把 600 窗口外的老书当新书推。

        补 40 本是为了让断言确定：若放开窗口，40 本全落在窗口内的概率可忽略。"""
        ids = list(range(1, 1001))
        avoid = frozenset(range(1, 981))  # 池子只剩 981..1000
        random_ids, new_ids = self.pick(ids, 12, 60, avoid)
        self.assertEqual((len(random_ids), len(new_ids)), (12, 60))
        self.assertGreaterEqual(min(new_ids), 401, new_ids)  # 全库 top-600 的下界

    def test_count_is_independent_of_avoid_set(self):
        """条数只由书库大小决定，不随 exclude 缩水（0..全部 都扫一遍）。"""
        for size in (3, 12, 20, 24, 40):
            ids = list(range(1, size + 1))
            expected = min(12, size)
            for avoid_size in range(0, size + 1, 4):
                avoid = frozenset(range(1, avoid_size + 1))
                random_ids, new_ids = self.pick(ids, 12, 12, avoid)
                self.assertEqual(
                    (len(random_ids), len(new_ids)), (expected, expected),
                    "size=%d avoid=%d" % (size, avoid_size),
                )


if __name__ == "__main__":
    unittest.main()
