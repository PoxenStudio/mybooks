#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""POST /api/admin/settings 的入参校验，免 HTTP 栈与 calibre 依赖。

test_main.py 的 TestAdmin 走完整 HTTP 栈（需要 tests/cases 里的存量 sqlite），
那份库的 readers 表落后于 models.py，本机整类跑不起来；「网站默认访问链接」的
校验逻辑用最小 fake handler 直接打 AdminSettings.post 验证。
"""

import asyncio
import json
import unittest
from unittest import mock

from webserver.handlers import admin as admin_module
from webserver.handlers.admin import AdminSettings


class FakeHandler:
    """只提供 AdminSettings.post 与 @js/@auth 装饰器需要的那几个属性/方法。"""

    def __init__(self, payload):
        self.current_user = object()
        self.admin_user = True
        self.request = mock.Mock()
        self.request.body = json.dumps(payload).encode("utf-8")
        self.request.headers = {}
        self.written = None

    def set_header(self, *args, **kwargs):
        pass

    def write(self, rsp):
        self.written = rsp

    def finish(self):
        pass


class TestAdminSettingsPost(unittest.TestCase):

    def post(self, payload):
        captured = {}
        handler = FakeHandler(payload)

        def fake_save(self, args):
            captured.update(args)
            return {"err": "ok", "rsp": dict(args)}

        with mock.patch.object(admin_module.SettingsSaver, "save_extra_settings", fake_save):
            asyncio.run(AdminSettings.post(handler))
        return handler.written, captured

    def test_guest_download_quota_saved(self):
        rsp, saved = self.post({"ENABLE_GUEST_DOWNLOAD_QUOTA": True, "GUEST_DOWNLOAD_QUOTA": 3})
        self.assertEqual("ok", rsp["err"])
        self.assertTrue(saved["ENABLE_GUEST_DOWNLOAD_QUOTA"])
        self.assertEqual(3, saved["GUEST_DOWNLOAD_QUOTA"])

    def test_site_url_normalized(self):
        """尾部斜杠必须剥掉，否则前端会拼出 https://host//s/<token>。"""
        rsp, saved = self.post({"SITE_URL": "https://books.example.com//"})
        self.assertEqual(rsp["err"], "ok")
        self.assertEqual("https://books.example.com", saved["SITE_URL"])
        self.assertEqual("https://books.example.com", rsp["rsp"]["SITE_URL"])

    def test_site_url_invalid_rejected(self):
        for bad in ("books.example.com", "ftp://books.example.com", "https://"):
            rsp, saved = self.post({"SITE_URL": bad})
            self.assertEqual("params.site_url.invalid", rsp["err"], bad)
            self.assertNotIn("SITE_URL", saved, bad)

    def test_site_url_empty_means_not_configured(self):
        rsp, saved = self.post({"SITE_URL": "   "})
        self.assertEqual(rsp["err"], "ok")
        self.assertEqual("", saved["SITE_URL"])

    def test_site_url_absent_is_not_touched(self):
        rsp, saved = self.post({"site_title": "abc"})
        self.assertEqual(rsp["err"], "ok")
        self.assertNotIn("SITE_URL", saved)
        self.assertEqual("abc", saved["site_title"])

    def test_site_timezone_accepts_auto_and_iana_names(self):
        """合法的取值都要放行（含双斜杠/加号/短横线/点的罕见 IANA 名）。"""
        for ok in (
            "auto",
            "UTC",
            "Asia/Shanghai",
            "America/Argentina/Buenos_Aires",
            "America/Port-au-Prince",
            "Etc/GMT+8",
        ):
            rsp, saved = self.post({"site_timezone": ok})
            self.assertEqual("ok", rsp["err"], ok)
            self.assertEqual(ok, saved["site_timezone"], ok)

    def test_site_timezone_rejects_malformed_values(self):
        """形态脏值直接拦下，别落进 auto.py；名字不存在时不拦（运行时回退 + warning）。"""
        for bad in ("Asia/Shang hai", "Asia/Shanghai'", "x" * 65, "123", "Europe/柏林"):
            rsp, saved = self.post({"site_timezone": bad})
            self.assertEqual("params.site_timezone.invalid", rsp["err"], bad)
            self.assertNotIn("site_timezone", saved, bad)

    def test_site_timezone_trimmed(self):
        rsp, saved = self.post({"site_timezone": "  Asia/Shanghai  "})
        self.assertEqual("ok", rsp["err"])
        self.assertEqual("Asia/Shanghai", saved["site_timezone"])

    def test_homepage_config_syncs_legacy_flags(self):
        rsp, saved = self.post(
            {
                "HOMEPAGE_CONFIG": {
                    "hidden": ["readingStats", "index.myReading"],
                    "custom": [
                        {"id": "c1", "type": "author", "value": "刘慈欣"}
                    ],
                }
            }
        )
        self.assertEqual("ok", rsp["err"])
        self.assertFalse(saved["ENABLE_HOMEPAGE_READING_STATS"])
        self.assertFalse(saved["ENABLE_HOMEPAGE_READING_BOOKS"])
        self.assertTrue(saved["ENABLE_HOMEPAGE_BOOKLISTS"])
        self.assertNotIn("ENABLE_BOOK_RECOMMEND_TO_OTHERS", saved)
        self.assertEqual(saved["HOMEPAGE_CONFIG"]["custom"][0]["value"], "刘慈欣")

    def test_hiding_social_card_does_not_touch_global_recommend_flag(self):
        """隐藏首页"他人推荐"卡不能反写 ENABLE_BOOK_RECOMMEND_TO_OTHERS。

        该 flag 还管"评价是否计入推荐人数/详情页推荐"，一旦被卡片开关连带关掉，
        首页卡片就永远取不到数据；它在「书评与互动」里另有独立开关。
        """
        rsp, saved = self.post(
            {
                "HOMEPAGE_CONFIG": {
                    "hidden": ["index.socialRecommendation"],
                    "custom": [],
                }
            }
        )
        self.assertEqual("ok", rsp["err"])
        self.assertNotIn("ENABLE_BOOK_RECOMMEND_TO_OTHERS", saved)
        self.assertIn("index.socialRecommendation", saved["HOMEPAGE_CONFIG"]["hidden"])

    def test_homepage_random_card_keeps_count_when_visible(self):
        rsp, saved = self.post(
            {
                "HOMEPAGE_CONFIG": {"hidden": [], "custom": []},
                "MAIN_PAGE_RANDOM_COUNT": 0,
            }
        )
        self.assertEqual("ok", rsp["err"])
        self.assertEqual(saved["MAIN_PAGE_RANDOM_COUNT"], 12)

    def test_homepage_random_card_hidden_keeps_zero_count(self):
        rsp, saved = self.post(
            {
                "HOMEPAGE_CONFIG": {
                    "hidden": ["index.randomRecommendation"],
                    "custom": [],
                },
                "MAIN_PAGE_RANDOM_COUNT": 0,
            }
        )
        self.assertEqual("ok", rsp["err"])
        self.assertEqual(saved["MAIN_PAGE_RANDOM_COUNT"], 0)

    def test_recommend_flag_has_independent_setting_entry(self):
        """卡片开关之外仍可单独保存 ENABLE_BOOK_RECOMMEND_TO_OTHERS（设置页有独立项）。"""
        rsp, saved = self.post({"ENABLE_BOOK_RECOMMEND_TO_OTHERS": False})
        self.assertEqual("ok", rsp["err"])
        self.assertFalse(saved["ENABLE_BOOK_RECOMMEND_TO_OTHERS"])

    def test_opds_anonymous_key_is_backfilled(self):
        """旧版缓存页/脚本不带 OPDS_ALLOW_ANONYMOUS 时，保存不能把它从 auto.py 抹掉。"""
        rsp, saved = self.post({"site_title": "abc"})
        self.assertEqual("ok", rsp["err"])
        self.assertIn("OPDS_ALLOW_ANONYMOUS", saved)


class TestAdminSettingsGet(unittest.TestCase):
    """GET /api/admin/settings 的首页配置必须与 /api/homepage 渲染口径一致。"""

    def get(self, settings):
        handler = FakeHandler({})
        handler.site_url = "http://books.example.com"
        with mock.patch.object(admin_module, "CONF", settings), mock.patch(
            "webserver.loader.get_settings", return_value=settings
        ):
            asyncio.run(AdminSettings.get(handler))
        return handler.written

    def test_corrupted_homepage_config_falls_back_like_rendering(self):
        """auto.py 手改成字符串时，设置页不能显示"全部可见"（否则保存一次就改写首页）。"""
        rsp = self.get({"HOMEPAGE_CONFIG": "oops", "ENABLE_HOMEPAGE_BOOKLISTS": False})
        self.assertEqual("ok", rsp["err"])
        self.assertEqual(
            rsp["settings"]["HOMEPAGE_CONFIG"]["hidden"],
            ["index.booklistRecommendation"],
        )


if __name__ == "__main__":
    unittest.main()
