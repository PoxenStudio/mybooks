#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""模块级开关（webserver/base/modules.py）的单元测试。

6 个模块互不依赖：multiuser / community / shared_reading / audio / physical / ai。
重点守：安全默认值写入、路由归属、数据/密钥不被覆盖、OPDS 匿名优先级。
"""

import unittest
from unittest import mock

from webserver.base import modules as modules_module
from webserver.base import setting_saver
from webserver.base.modules import (
    MODULE_AI,
    MODULE_AUDIO,
    MODULE_COMMUNITY,
    MODULE_MULTIUSER,
    MODULE_PHYSICAL,
    MODULE_SHARED_READING,
    MODULES,
    ModuleGateMixin,
    apply_module_switch_effects,
    is_known,
    module_disabled_error,
    module_enabled,
    opds_anonymous_allowed,
    require_login_effective,
    setting_key,
    snapshot,
)


class TestModuleEnabled(unittest.TestCase):

    def test_default_enabled_when_key_absent(self):
        for module_id in (MODULE_MULTIUSER, MODULE_COMMUNITY, MODULE_SHARED_READING, MODULE_AUDIO, MODULE_PHYSICAL, MODULE_AI):
            with self.subTest(module=module_id):
                self.assertTrue(module_enabled(module_id, settings={}))

    def test_disabled_by_setting(self):
        self.assertFalse(
            module_enabled(MODULE_COMMUNITY, settings={"ENABLE_MODULE_COMMUNITY": False})
        )
        self.assertFalse(
            module_enabled(MODULE_AUDIO, settings={"ENABLE_MODULE_AUDIO": False})
        )

    def test_truthy_values(self):
        self.assertFalse(module_enabled(MODULE_AI, settings={"ENABLE_MODULE_AI": 0}))
        self.assertTrue(module_enabled(MODULE_AI, settings={"ENABLE_MODULE_AI": 1}))

    def test_unknown_module_is_enabled(self):
        self.assertTrue(module_enabled("not_registered", settings={}))
        self.assertFalse(is_known("not_registered"))

    def test_setting_key(self):
        self.assertEqual(setting_key(MODULE_MULTIUSER), "ENABLE_MODULE_MULTIUSER")
        self.assertEqual(setting_key(MODULE_AUDIO), "ENABLE_MODULE_AUDIO")
        self.assertIsNone(setting_key("not_registered"))

    def test_modules_are_independent(self):
        settings = {
            "ENABLE_MODULE_MULTIUSER": False,
            "ENABLE_MODULE_COMMUNITY": False,
            "ENABLE_MODULE_SHARED_READING": False,
            "ENABLE_MODULE_AUDIO": False,
            "ENABLE_MODULE_PHYSICAL": True,
            "ENABLE_MODULE_AI": True,
        }
        self.assertFalse(module_enabled(MODULE_MULTIUSER, settings=settings))
        self.assertFalse(module_enabled(MODULE_COMMUNITY, settings=settings))
        self.assertFalse(module_enabled(MODULE_SHARED_READING, settings=settings))
        self.assertFalse(module_enabled(MODULE_AUDIO, settings=settings))
        self.assertTrue(module_enabled(MODULE_PHYSICAL, settings=settings))
        self.assertTrue(module_enabled(MODULE_AI, settings=settings))

    def test_require_login_effective(self):
        self.assertTrue(
            require_login_effective(
                {"ENABLE_MODULE_MULTIUSER": False, "REQUIRE_LOGIN": False}
            )
        )
        self.assertFalse(
            require_login_effective(
                {"ENABLE_MODULE_MULTIUSER": True, "REQUIRE_LOGIN": False}
            )
        )
        self.assertTrue(require_login_effective({"REQUIRE_LOGIN": True}))
        # 缺键按默认值 True 处理：新装/手工删键的站点开箱即私
        self.assertTrue(require_login_effective({}))

    def test_opds_anonymous_allowed(self):
        # 匿名开关优先：OPDS 认证项与站点级必须登录都拦不住它
        self.assertTrue(
            opds_anonymous_allowed(
                {"OPDS_ALLOW_ANONYMOUS": True, "ENABLE_OPDS_AUTH": True}
            )
        )
        self.assertTrue(
            opds_anonymous_allowed(
                {"OPDS_ALLOW_ANONYMOUS": True, "REQUIRE_LOGIN": True}
            )
        )
        self.assertFalse(opds_anonymous_allowed({"OPDS_ALLOW_ANONYMOUS": False}))


class TestSnapshot(unittest.TestCase):

    def test_snapshot_shape(self):
        self.assertEqual(
            snapshot({}),
            {
                MODULE_MULTIUSER: True,
                MODULE_COMMUNITY: True,
                MODULE_SHARED_READING: True,
                MODULE_AUDIO: True,
                MODULE_PHYSICAL: True,
                MODULE_AI: True,
            },
        )

    def test_snapshot_reflects_each_module(self):
        state = snapshot(
            {
                "ENABLE_MODULE_MULTIUSER": False,
                "ENABLE_MODULE_COMMUNITY": True,
                "ENABLE_MODULE_SHARED_READING": False,
                "ENABLE_MODULE_AUDIO": False,
                "ENABLE_MODULE_PHYSICAL": True,
                "ENABLE_MODULE_AI": False,
            }
        )
        self.assertFalse(state[MODULE_MULTIUSER])
        self.assertTrue(state[MODULE_COMMUNITY])
        self.assertFalse(state[MODULE_SHARED_READING])
        self.assertFalse(state[MODULE_AUDIO])
        self.assertTrue(state[MODULE_PHYSICAL])
        self.assertFalse(state[MODULE_AI])


class TestDisabledError(unittest.TestCase):

    def test_error_body(self):
        body = module_disabled_error(MODULE_COMMUNITY)
        self.assertEqual(body["err"], "module.disabled")
        self.assertIn("社区互动", body["msg"])


class TestApplyModuleSwitchEffects(unittest.TestCase):

    def test_multiuser_off_writes_access_defaults(self):
        args = {
            "ENABLE_MODULE_MULTIUSER": False,
            "REQUIRE_LOGIN": False,
            "ALLOW_GUEST_READ": True,
            "ALLOW_GUEST_DOWNLOAD": True,
            "ALLOW_GUEST_UPLOAD": True,
            "ALLOW_GUEST_PUSH": True,
            "ALLOW_REGISTER": True,
            "INVITE_MODE": True,
            "ENABLE_SHARE_LINK": True,
            "SOCIALS": [{"value": "github"}],
            "FRIENDS": [{"text": "x"}],
        }
        apply_module_switch_effects(
            args, {"ENABLE_MODULE_MULTIUSER": True}
        )
        self.assertTrue(args["REQUIRE_LOGIN"])
        for key in (
            "ALLOW_GUEST_READ",
            "ALLOW_GUEST_DOWNLOAD",
            "ALLOW_GUEST_UPLOAD",
            "ALLOW_GUEST_PUSH",
            "ALLOW_REGISTER",
            "INVITE_MODE",
        ):
            self.assertFalse(args[key], key)
        # 分享链接归社区互动，不随多用户关闭
        self.assertTrue(args["ENABLE_SHARE_LINK"])
        self.assertEqual(args["SOCIALS"], [{"value": "github"}])
        self.assertEqual(args["FRIENDS"], [{"text": "x"}])

    def test_multiuser_on_pins_require_login(self):
        # 重新开启多用户支持时把「必须登录」钉回 True（更安全的一侧），
        # 管理员想开访客阅读再手动取消勾选，所以它不在灰置名单里。
        args = {"ENABLE_MODULE_MULTIUSER": True, "REQUIRE_LOGIN": False}
        apply_module_switch_effects(
            args, {"ENABLE_MODULE_MULTIUSER": False, "REQUIRE_LOGIN": True}
        )
        self.assertTrue(args["REQUIRE_LOGIN"])
        # 已开启状态下不反复覆盖：管理员手动取消勾选后保存要能留住
        args = {"ENABLE_MODULE_MULTIUSER": True, "REQUIRE_LOGIN": False}
        apply_module_switch_effects(args, {"ENABLE_MODULE_MULTIUSER": True})
        self.assertFalse(args["REQUIRE_LOGIN"])

    def test_community_off_writes_feature_defaults(self):
        args = {
            "ENABLE_MODULE_COMMUNITY": False,
            "ENABLE_USER_MEMOS": True,
            "ENABLE_SHARE_LINK": True,
            "ENABLE_SHARED_NOTES": True,
            "RECOMMEND_ENABLE": True,
            "ENABLE_BOOK_REVIEW": True,
            "HOMEPAGE_CONFIG": {"order": []},
            "SIDEBAR_ITEMS": ["authors"],
        }
        apply_module_switch_effects(
            args, {"ENABLE_MODULE_COMMUNITY": True}
        )
        self.assertFalse(args["ENABLE_USER_MEMOS"])
        # 分享链接/共享笔记/推荐/书评归共享阅读，不随社区关闭
        self.assertTrue(args["ENABLE_SHARE_LINK"])
        self.assertTrue(args["ENABLE_SHARED_NOTES"])
        self.assertTrue(args["RECOMMEND_ENABLE"])
        self.assertTrue(args["ENABLE_BOOK_REVIEW"])
        self.assertEqual(args["HOMEPAGE_CONFIG"], {"order": []})
        self.assertEqual(args["SIDEBAR_ITEMS"], ["authors"])

    def test_shared_reading_off_writes_feature_defaults(self):
        args = {
            "ENABLE_MODULE_SHARED_READING": False,
            "RECOMMEND_ENABLE": True,
            "ENABLE_BOOK_REVIEW": True,
            "ENABLE_SHARE_LINK": True,
            "ENABLE_SHARED_NOTES": True,
            "ENABLE_USER_MEMOS": True,
            "HOMEPAGE_CONFIG": {"order": []},
        }
        apply_module_switch_effects(
            args, {"ENABLE_MODULE_SHARED_READING": True}
        )
        self.assertFalse(args["RECOMMEND_ENABLE"])
        self.assertFalse(args["ENABLE_BOOK_REVIEW"])
        self.assertFalse(args["ENABLE_SHARE_LINK"])
        self.assertFalse(args["ENABLE_SHARED_NOTES"])
        # 留言归社区互动，不随共享阅读关闭
        self.assertTrue(args["ENABLE_USER_MEMOS"])
        self.assertEqual(args["HOMEPAGE_CONFIG"], {"order": []})

    def test_community_on_restores_features_but_not_share_link(self):
        args = {
            "ENABLE_MODULE_COMMUNITY": True,
            "ENABLE_USER_MEMOS": False,
            "ENABLE_SHARE_LINK": False,
            "ENABLE_SHARED_NOTES": False,
        }
        apply_module_switch_effects(
            args, {"ENABLE_MODULE_COMMUNITY": False}
        )
        self.assertTrue(args["ENABLE_USER_MEMOS"])
        # 分享链接/共享笔记归共享阅读，社区重开不碰
        self.assertFalse(args["ENABLE_SHARE_LINK"])
        self.assertFalse(args["ENABLE_SHARED_NOTES"])

    def test_shared_reading_on_restores_review_and_recommend(self):
        args = {
            "ENABLE_MODULE_SHARED_READING": True,
            "RECOMMEND_ENABLE": False,
            "ENABLE_BOOK_REVIEW": False,
            "ENABLE_SHARED_NOTES": False,
            "ENABLE_SHARE_LINK": False,
        }
        apply_module_switch_effects(
            args, {"ENABLE_MODULE_SHARED_READING": False}
        )
        self.assertTrue(args["RECOMMEND_ENABLE"])
        self.assertTrue(args["ENABLE_BOOK_REVIEW"])
        self.assertTrue(args["ENABLE_SHARED_NOTES"])
        # 分享链接归共享阅读，随模块重开一起恢复
        self.assertTrue(args["ENABLE_SHARE_LINK"])

    def test_audio_off_has_no_safe_defaults(self):
        args = {"ENABLE_MODULE_AUDIO": False, "ENABLE_PODCAST_SERVICE": True}
        apply_module_switch_effects(args, {"ENABLE_MODULE_AUDIO": True})
        self.assertTrue(args["ENABLE_PODCAST_SERVICE"])

    def test_physical_and_ai_off(self):
        args = {
            "ENABLE_MODULE_PHYSICAL": False,
            "ENABLE_MODULE_AI": False,
            "AI_MCP_TOKEN": "secret",
        }
        apply_module_switch_effects(
            args,
            {"ENABLE_MODULE_PHYSICAL": True, "ENABLE_MODULE_AI": True},
        )
        self.assertFalse(args["ENABLE_PHYSICAL_BOOKS"])
        self.assertFalse(args["AI_ENABLED"])
        self.assertFalse(args["ENABLE_MYNEXUS"])
        self.assertEqual(args["AI_MCP_TOKEN"], "secret")

    def test_already_on_does_not_touch_sub_switches(self):
        args = {
            "ENABLE_MODULE_SHARED_READING": True,
            "RECOMMEND_ENABLE": False,
            "ENABLE_BOOK_REVIEW": False,
        }
        apply_module_switch_effects(
            args, {"ENABLE_MODULE_SHARED_READING": True}
        )
        self.assertFalse(args["RECOMMEND_ENABLE"])
        self.assertFalse(args["ENABLE_BOOK_REVIEW"])

    def test_install_applies_off_but_not_on(self):
        args = {
            "ENABLE_MODULE_MULTIUSER": False,
            "ENABLE_MODULE_COMMUNITY": True,
            "ENABLE_MODULE_SHARED_READING": True,
            "ENABLE_MODULE_AUDIO": True,
            "ENABLE_MODULE_PHYSICAL": False,
            "ENABLE_MODULE_AI": False,
            "RECOMMEND_ENABLE": False,
        }
        apply_module_switch_effects(args, None)
        self.assertTrue(args["REQUIRE_LOGIN"])
        self.assertFalse(args["RECOMMEND_ENABLE"])  # 安装不主动改勾选模块的主开关
        self.assertFalse(args["ENABLE_PHYSICAL_BOOKS"])
        self.assertFalse(args["AI_ENABLED"])


class _FakeBase:
    def __init__(self):
        self.prepared = False
        self.finished = None

    def prepare(self):
        self.prepared = True

    def finish(self, payload=None):
        self.finished = payload


class _JsonGated(ModuleGateMixin, _FakeBase):
    module_id = MODULE_COMMUNITY


class _FileGated(ModuleGateMixin, _FakeBase):
    module_id = MODULE_AUDIO
    module_gate_json = False


class TestModuleGateMixin(unittest.TestCase):

    def test_passes_when_enabled(self):
        handler = _JsonGated()
        with mock.patch.object(modules_module, "module_enabled", return_value=True):
            handler.prepare()
        self.assertTrue(handler.prepared)
        self.assertIsNone(handler.finished)

    def test_json_rejection(self):
        handler = _JsonGated()
        with mock.patch.object(modules_module, "module_enabled", return_value=False):
            handler.prepare()
        self.assertTrue(handler.prepared)
        self.assertEqual(handler.finished["err"], "module.disabled")

    def test_non_json_rejection_is_404(self):
        handler = _FileGated()
        with mock.patch.object(modules_module, "module_enabled", return_value=False):
            with self.assertRaises(Exception) as ctx:
                handler.prepare()
        self.assertEqual(getattr(ctx.exception, "status_code", None), 404)


class TestModuleKeysArePersistable(unittest.TestCase):

    def test_every_module_key_is_admin_setting_key(self):
        for module_id, spec in MODULES.items():
            with self.subTest(module=module_id):
                self.assertIn(spec["key"], setting_saver.ADMIN_SETTING_KEYS)

    def test_persistable_is_superset_of_admin_keys(self):
        self.assertTrue(
            set(setting_saver.ADMIN_SETTING_KEYS) <= set(setting_saver.PERSISTABLE_KEYS)
        )

    def test_opds_anonymous_key_is_persistable(self):
        self.assertIn("OPDS_ALLOW_ANONYMOUS", setting_saver.ADMIN_SETTING_KEYS)

    def test_all_effect_switch_keys_are_persistable(self):
        keys = set()
        for switches in modules_module.MODULE_OFF_SWITCHES.values():
            keys.update(switches)
        for switches in modules_module.MODULE_ON_SWITCHES.values():
            keys.update(switches)
        for key in keys:
            with self.subTest(key=key):
                self.assertIn(key, setting_saver.ADMIN_SETTING_KEYS)

    def test_default_present_in_settings_module(self):
        from webserver import settings as settings_module

        for module_id, spec in MODULES.items():
            with self.subTest(module=module_id):
                self.assertIn(spec["key"], settings_module.settings)
                self.assertEqual(settings_module.settings[spec["key"]], spec["default"])


class TestRoutesAreGated(unittest.TestCase):

    def test_audio_routes_use_audio_module(self):
        try:
            from webserver.handlers import audio
        except ImportError as exc:
            self.skipTest("audio 路由需要 calibre：%s" % exc)

        for pattern, handler in audio.routes():
            with self.subTest(route=pattern):
                self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                self.assertEqual(handler.module_id, MODULE_AUDIO, pattern)

    def test_podcast_base_gates_audio(self):
        from webserver.handlers import podcast

        for pattern, handler in podcast.routes():
            with self.subTest(route=pattern):
                self.assertTrue(issubclass(handler, podcast.PodcastBaseHandler), pattern)
        # 门禁写在基类 prepare 里，子类一旦覆写且不调 super 就会漏
        for pattern, handler in podcast.routes():
            self.assertNotIn("prepare", handler.__dict__, pattern)

    def test_audio_import_and_mimo_routes_use_audio_module(self):
        from webserver.handlers import scan

        seen = set()
        for pattern, handler in scan.routes():
            if "audio_import" in pattern:
                seen.add(pattern)
                with self.subTest(route=pattern):
                    self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                    self.assertEqual(handler.module_id, MODULE_AUDIO, pattern)
        self.assertTrue(seen)

        try:
            from webserver.handlers import toolbox
        except ImportError as exc:
            self.skipTest("toolbox 路由需要 calibre：%s" % exc)
        seen = set()
        for pattern, handler in toolbox.routes():
            if "mimo_tts" in pattern:
                seen.add(pattern)
                with self.subTest(route=pattern):
                    self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                    self.assertEqual(handler.module_id, MODULE_AUDIO, pattern)
        self.assertTrue(seen)

    def test_booklist_routes_use_shared_reading(self):
        from webserver.handlers import booklist

        for pattern, handler in booklist.routes():
            with self.subTest(route=pattern):
                self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                self.assertEqual(handler.module_id, MODULE_SHARED_READING, pattern)

    def test_book_review_routes_use_shared_reading(self):
        from webserver.handlers import book_review

        for pattern, handler in book_review.routes():
            if pattern.endswith("/social-stats"):
                self.assertFalse(issubclass(handler, ModuleGateMixin), pattern)
                continue
            with self.subTest(route=pattern):
                self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                self.assertEqual(handler.module_id, MODULE_SHARED_READING, pattern)

    def test_share_routes_use_shared_reading(self):
        from webserver.handlers import share

        for pattern, handler in share.routes():
            with self.subTest(route=pattern):
                self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                self.assertEqual(handler.module_id, MODULE_SHARED_READING, pattern)
        self.assertFalse(share.ShareInfoHandler.module_gate_json)

    def test_user_module_routes(self):
        from webserver.handlers import user

        gated = {
            "/api/user/expected": MODULE_COMMUNITY,
            "/api/user/memo": MODULE_COMMUNITY,
            "/api/user/new": MODULE_MULTIUSER,
        }
        seen = set()
        for pattern, handler in user.routes():
            if pattern in gated:
                seen.add(pattern)
                with self.subTest(route=pattern):
                    self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                    self.assertEqual(handler.module_id, gated[pattern], pattern)
        self.assertEqual(seen, set(gated))

        # 注册 POST 用方法级门禁；激活接口保持核心可用
        self.assertFalse(issubclass(user.SignUp, ModuleGateMixin))
        self.assertFalse(issubclass(user.UserActive, ModuleGateMixin))
        self.assertFalse(issubclass(user.UserSendActive, ModuleGateMixin))

    def test_core_account_routes_stay_open(self):
        from webserver.handlers import user

        core = {
            "/api/user/info",
            "/api/user/whoami",
            "/api/user/appearance",
            "/api/user/sign_in",
            "/api/user/sign_out",
            "/api/user/reset",
            "/api/user/update",
            "/api/user/avatar",
            "/api/access",
        }
        seen = set()
        for pattern, handler in user.routes():
            if pattern in core:
                seen.add(pattern)
                with self.subTest(route=pattern):
                    self.assertFalse(issubclass(handler, ModuleGateMixin), pattern)
        self.assertEqual(seen, core)

    def test_admin_routes(self):
        try:
            from webserver.handlers import admin
        except ImportError as exc:
            self.skipTest("admin 路由需要 calibre：%s" % exc)

        expected = {
            "/api/admin/users": MODULE_MULTIUSER,
            "/api/admin/book-reviews": MODULE_SHARED_READING,
        }
        seen = set()
        for pattern, handler in admin.routes():
            if pattern in expected:
                seen.add(pattern)
                with self.subTest(route=pattern):
                    self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                    self.assertEqual(handler.module_id, expected[pattern], pattern)
        self.assertEqual(seen, set(expected))

    def test_private_book_routes_are_core(self):
        try:
            from webserver.handlers import book
        except ImportError as exc:
            self.skipTest("book 路由需要 calibre：%s" % exc)

        for pattern, handler in book.routes():
            if pattern in ("/api/soledbooks", "/api/book/([0-9]+)/setsole"):
                with self.subTest(route=pattern):
                    self.assertFalse(issubclass(handler, ModuleGateMixin), pattern)

    def test_social_routes_use_multiuser(self):
        from webserver import social_routes

        for rule in social_routes.SOCIAL_AUTH_ROUTES:
            with self.subTest(route=rule.regex.pattern):
                self.assertTrue(
                    issubclass(rule.handler_class, social_routes.SocialLoginGateMixin)
                )


class TestBookSocialStatsDegrade(unittest.TestCase):
    def test_recommend_count_zero_when_community_off(self):
        import asyncio

        from webserver.handlers import book_review

        class _Fake:
            sqlite_session = object()

            def __init__(self):
                self.request = mock.Mock(headers={})
                self.written = None

            def set_header(self, *args, **kwargs):
                pass

            def write(self, value):
                self.written = value

            def finish(self):
                pass

        fake = _Fake()
        stats = {"reading_count": 1, "favorite_count": 2, "recommend_count": 3}
        with mock.patch.object(
            book_review.BookReviewService, "get_stats", return_value=stats
        ), mock.patch.object(book_review, "module_enabled", return_value=False):
            asyncio.run(book_review.BookSocialStatsHandler.get(fake, 1))
        self.assertEqual(fake.written["recommend_count"], 0)
        self.assertEqual(fake.written["reading_count"], 1)
        self.assertEqual(fake.written["favorite_count"], 2)
        self.assertEqual(stats["recommend_count"], 3)


class TestSignUpMethodGate(unittest.TestCase):
    def test_post_rejects_when_multiuser_off(self):
        import asyncio

        from webserver.handlers import user

        class _Fake:
            def __init__(self):
                self.request = mock.Mock(headers={})
                self.written = None

            def set_header(self, *args, **kwargs):
                pass

            def write(self, value):
                self.written = value

            def finish(self):
                pass

        handler = _Fake()
        with mock.patch.object(user.feature_modules, "module_enabled", return_value=False):
            asyncio.run(user.SignUp.post(handler))
        self.assertEqual(handler.written["err"], "module.disabled")


class TestOpdsAnonymousDownload(unittest.TestCase):
    def test_prepare_allows_anonymous_opds_download(self):
        try:
            from webserver.handlers.book import BookDownload
        except ImportError as exc:
            self.skipTest("book 路由需要 calibre：%s" % exc)

        from webserver.services.book_access_service import BookAccessService

        handler = object.__new__(BookDownload)
        handler.current_user = None
        handler.is_opds = True
        handler.requested_book_id = lambda: 12
        handler.login_by_download_sign = mock.Mock()
        handler.send_error_of_not_invited = mock.Mock()
        handler.redirect = mock.Mock()
        handler.sqlite_session = mock.Mock()
        handler.sqlite_session.query.return_value.filter.return_value.first.return_value = None
        with mock.patch("webserver.handlers.book.BaseHandler.prepare", return_value=None):
            with mock.patch.object(
                BookAccessService, "guest_download_allowed", return_value=False
            ):
                with mock.patch.object(
                    modules_module, "opds_anonymous_allowed", return_value=True
                ):
                    BookDownload.prepare(handler)
        handler.login_by_download_sign.assert_not_called()
        handler.send_error_of_not_invited.assert_not_called()

    def test_prepare_rejects_sole_book_for_anonymous_opds(self):
        from tornado import web

        try:
            from webserver.handlers.book import BookDownload
        except ImportError as exc:
            self.skipTest("book 路由需要 calibre：%s" % exc)

        handler = object.__new__(BookDownload)
        handler.current_user = None
        handler.is_opds = True
        handler.requested_book_id = lambda: 12
        handler.login_by_download_sign = mock.Mock()
        handler.sqlite_session = mock.Mock()
        handler.sqlite_session.query.return_value.filter.return_value.first.return_value = object()
        with mock.patch("webserver.handlers.book.BaseHandler.prepare", return_value=None), \
                mock.patch.object(modules_module, "opds_anonymous_allowed", return_value=True):
            with self.assertRaises(web.HTTPError) as ctx:
                BookDownload.prepare(handler)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_prepare_rejects_when_opds_service_off(self):
        from tornado import web

        try:
            from webserver.handlers.book import BookDownload
        except ImportError as exc:
            self.skipTest("book 路由需要 calibre：%s" % exc)

        handler = object.__new__(BookDownload)
        handler.is_opds = True
        with mock.patch("webserver.handlers.book.BaseHandler.prepare", return_value=None), \
                mock.patch.dict("webserver.handlers.book.CONF", {"ENABLE_OPDS_SERVICE": False}):
            with self.assertRaises(web.HTTPError) as ctx:
                BookDownload.prepare(handler)
        self.assertEqual(ctx.exception.status_code, 404)
