#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""模块级开关（webserver/base/modules.py）的单元测试。

重点守两类回归：

1. 模块开关的默认值与未登记模块的兜底（不能让新模块漏登记就整块消失）；
2. **配置键必须进 PERSISTABLE_KEYS / ADMIN_SETTING_KEYS**——漏了会在设置页
   保存时被 dumpfile() 整份覆盖回默认值，属于静默失效，最难靠肉眼发现。
"""

import unittest
from unittest import mock

from webserver.base import modules as modules_module
from webserver.base import setting_saver
from webserver.base.modules import (
    MODULE_AI,
    MODULE_AUDIO,
    MODULE_COMMUNITY,
    MODULE_PHYSICAL,
    MODULE_USERS,
    MODULES,
    ModuleGateMixin,
    is_known,
    module_disabled_error,
    module_enabled,
    setting_key,
    snapshot,
)


class TestModuleEnabled(unittest.TestCase):

    def test_default_enabled_when_key_absent(self):
        # 老实例升级：auto.py 里没有新键时必须按开启处理，行为零变化
        self.assertTrue(module_enabled(MODULE_AUDIO, settings={}))

    def test_disabled_by_setting(self):
        self.assertFalse(
            module_enabled(MODULE_AUDIO, settings={"ENABLE_MODULE_AUDIO": False})
        )

    def test_truthy_values(self):
        # 手工把 auto.py 改成 0 / 空串也应视为关闭
        self.assertFalse(module_enabled(MODULE_AUDIO, settings={"ENABLE_MODULE_AUDIO": 0}))
        self.assertTrue(module_enabled(MODULE_AUDIO, settings={"ENABLE_MODULE_AUDIO": 1}))

    def test_unknown_module_is_enabled(self):
        # 未登记的模块一律视为开启：宁可多显示，也不要让整块功能凭空消失
        self.assertTrue(module_enabled("not_registered", settings={}))
        self.assertFalse(is_known("not_registered"))

    def test_setting_key(self):
        self.assertEqual(setting_key(MODULE_AUDIO), "ENABLE_MODULE_AUDIO")
        self.assertIsNone(setting_key("not_registered"))


class TestSnapshot(unittest.TestCase):

    def test_snapshot_shape(self):
        self.assertEqual(
            snapshot({}),
            {
                MODULE_AUDIO: True,
                MODULE_COMMUNITY: True,
                MODULE_PHYSICAL: True,
                MODULE_AI: True,
                MODULE_USERS: True,
            },
        )
        self.assertEqual(
            snapshot({
                "ENABLE_MODULE_AUDIO": False,
                "ENABLE_MODULE_COMMUNITY": False,
                "ENABLE_MODULE_PHYSICAL": False,
                "ENABLE_MODULE_AI": False,
                "ENABLE_MODULE_USERS": False,
            }),
            {
                MODULE_AUDIO: False,
                MODULE_COMMUNITY: False,
                MODULE_PHYSICAL: False,
                MODULE_AI: False,
                MODULE_USERS: False,
            },
        )


class TestDisabledError(unittest.TestCase):

    def test_error_body(self):
        body = module_disabled_error(MODULE_AUDIO)
        self.assertEqual(body["err"], "module.disabled")
        self.assertIn("有声书", body["msg"])


class _FakeBase:
    """冒充 BaseHandler：只要 prepare 被先调用、finish 收得到 body 就够了。"""

    def __init__(self):
        self.prepared = False
        self.finished = None

    def prepare(self):
        self.prepared = True

    def finish(self, payload=None):
        self.finished = payload


class _JsonGated(ModuleGateMixin, _FakeBase):
    module_id = MODULE_AUDIO


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
        self.assertTrue(handler.prepared)  # 先走原有登录/邀请闸，再判模块
        self.assertEqual(handler.finished["err"], "module.disabled")

    def test_non_json_rejection_is_404(self):
        handler = _FileGated()
        with mock.patch.object(modules_module, "module_enabled", return_value=False):
            with self.assertRaises(Exception) as ctx:
                handler.prepare()
        self.assertEqual(getattr(ctx.exception, "status_code", None), 404)


class TestModuleKeysArePersistable(unittest.TestCase):
    """模块键必须进 ADMIN_SETTING_KEYS（设置接口按它过滤请求体）。

    PERSISTABLE_KEYS 是 ADMIN_SETTING_KEYS 的超集，键进了前者必然在后者里，
    所以只断言 ADMIN_SETTING_KEYS 就够了，另加一条超集断言防止将来拆开。
    """

    def test_every_module_key_is_admin_setting_key(self):
        for module_id, spec in MODULES.items():
            with self.subTest(module=module_id):
                self.assertIn(spec["key"], setting_saver.ADMIN_SETTING_KEYS)

    def test_persistable_is_superset_of_admin_keys(self):
        # 两者一旦被拆成互不相交的清单，模块键就可能在保存时被静默丢掉
        self.assertTrue(
            set(setting_saver.ADMIN_SETTING_KEYS) <= set(setting_saver.PERSISTABLE_KEYS)
        )

    def test_default_present_in_settings_module(self):
        from webserver import settings as settings_module

        # 每个登记过的模块都要有出厂默认值且与模块表一致（不能只断言 True：
        # 将来允许默认关闭的模块时，这里不应该拦）
        for module_id, spec in MODULES.items():
            with self.subTest(module=module_id):
                self.assertIn(spec["key"], settings_module.settings)
                self.assertEqual(settings_module.settings[spec["key"]], spec["default"])


class TestRoutesAreGated(unittest.TestCase):
    """逐个路由反射：挂了 Mixin 却漏写 module_id 是这套机制最容易犯的错。

    mock module_enabled 测不到「哪条路由忘了挂」，只有遍历 routes() 才守得住。
    """

    def test_every_audio_route_is_gated(self):
        from webserver.handlers import audio

        for pattern, handler in audio.routes():
            with self.subTest(route=pattern):
                self.assertTrue(
                    issubclass(handler, ModuleGateMixin),
                    "%s 未挂 ModuleGateMixin" % pattern,
                )
                self.assertEqual(handler.module_id, MODULE_AUDIO, pattern)

    def test_audio_stream_routes_are_not_json(self):
        from webserver.handlers import audio

        # 文件流用 404，别把 JSON 错误体塞给播放器
        self.assertFalse(audio.AudioFile.module_gate_json)
        self.assertFalse(audio.AudioCollectionDownloadFile.module_gate_json)

    def test_podcast_routes_share_gated_base(self):
        from webserver.handlers import podcast

        for pattern, handler in podcast.routes():
            with self.subTest(route=pattern):
                self.assertTrue(
                    issubclass(handler, podcast.PodcastBaseHandler),
                    "%s 未继承 PodcastBaseHandler" % pattern,
                )
        # 门禁写在基类 prepare 里，子类一旦覆写且不调 super 就会漏
        for pattern, handler in podcast.routes():
            self.assertNotIn("prepare", handler.__dict__, pattern)

    def test_audio_import_routes_are_gated(self):
        from webserver.handlers import scan

        for pattern, handler in scan.routes():
            if "audio_import" not in pattern:
                continue
            with self.subTest(route=pattern):
                self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                self.assertEqual(handler.module_id, MODULE_AUDIO, pattern)

    def test_mimo_tts_effectful_routes_are_gated(self):
        try:
            from webserver.handlers import toolbox
        except ImportError as exc:
            # toolbox 依赖 calibre；没装 calibre 的环境跳过，别把环境问题当成回归
            self.skipTest("toolbox 路由需要 calibre：%s" % exc)

        # 会写音频目录 / 读音频流的 4 条必须挂门禁；纯配置类接口不强制
        effectful = (
            "/api/toolbox/mimo_tts/convert",
            "/api/toolbox/mimo_tts/progress",
            "/api/toolbox/mimo_tts/test",
            "/api/toolbox/mimo_tts/clone/audio",
        )
        seen = set()
        for pattern, handler in toolbox.routes():
            if pattern in effectful:
                seen.add(pattern)
                with self.subTest(route=pattern):
                    self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                    self.assertEqual(handler.module_id, MODULE_AUDIO, pattern)
        self.assertEqual(seen, set(effectful))


class TestCommunityRoutesAreGated(unittest.TestCase):
    """社区互动模块：留言/缺书/书单/私藏五组接口逐条反射。"""

    def test_user_community_routes_are_gated(self):
        from webserver.handlers import user

        gated = {"/api/user/expected", "/api/user/memo"}
        seen = set()
        for pattern, handler in user.routes():
            if pattern in gated:
                seen.add(pattern)
                with self.subTest(route=pattern):
                    self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                    self.assertEqual(handler.module_id, MODULE_COMMUNITY, pattern)
        self.assertEqual(seen, gated)

    def test_booklist_routes_are_gated(self):
        from webserver.handlers import booklist

        # /api/booklists/homepage 例外：首页按 err=="ok" 读，模块关闭时必须
        # 返回空列表而不是 module.disabled（见下面 TestBookListHomepageHandler）
        for pattern, handler in booklist.routes():
            if pattern == "/api/booklists/homepage":
                self.assertFalse(issubclass(handler, ModuleGateMixin), pattern)
                continue
            with self.subTest(route=pattern):
                self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                self.assertEqual(handler.module_id, MODULE_COMMUNITY, pattern)

    def test_booklist_homepage_routes_exist(self):
        from webserver.handlers import booklist

        patterns = [pattern for pattern, _ in booklist.routes()]
        self.assertIn("/api/booklists/homepage", patterns)

    def test_sole_routes_are_gated(self):
        try:
            from webserver.handlers import book
        except ImportError as exc:
            # book.py 依赖 calibre；没装 calibre 的环境跳过
            self.skipTest("book 路由需要 calibre：%s" % exc)

        gated = {"/api/soledbooks", "/api/book/([0-9]+)/setsole"}
        seen = set()
        for pattern, handler in book.routes():
            if pattern in gated:
                seen.add(pattern)
                with self.subTest(route=pattern):
                    self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                    self.assertEqual(handler.module_id, MODULE_COMMUNITY, pattern)
        self.assertEqual(seen, gated)


class TestPhysicalRoutesAreGated(unittest.TestCase):
    """实体书模块：登记、互转、实体书列表逐条反射。"""

    def test_physical_routes_are_gated(self):
        try:
            from webserver.handlers import book
        except ImportError as exc:
            self.skipTest("book 路由需要 calibre：%s" % exc)

        gated = {
            "/api/printbooks",
            "/api/book/add",
            "/api/book/add/manual",
            "/api/book/exchange_type",
            "/api/book/([0-9]+)/location",
        }
        seen = set()
        for pattern, handler in book.routes():
            if pattern in gated:
                seen.add(pattern)
                with self.subTest(route=pattern):
                    self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                    self.assertEqual(handler.module_id, MODULE_PHYSICAL, pattern)
        self.assertEqual(seen, gated)

    def test_physical_batch_add_routes_are_gated(self):
        from webserver.handlers import scan

        gated = {"/api/admin/batch_add/run", "/api/admin/batch_add/status"}
        seen = set()
        for pattern, handler in scan.routes():
            if pattern in gated:
                seen.add(pattern)
                with self.subTest(route=pattern):
                    self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                    self.assertEqual(handler.module_id, MODULE_PHYSICAL, pattern)
        self.assertEqual(seen, gated)

    def test_stamp_stays_independent(self):
        try:
            from webserver.handlers import book
        except ImportError as exc:
            self.skipTest("book 路由需要 calibre：%s" % exc)

        # 封面图章作用于电子书封面（2026-10-19 设计），不属于实体书模块
        self.assertFalse(issubclass(book.BookAddStamp, ModuleGateMixin))


class TestAIRoutesAreGated(unittest.TestCase):
    """AI 模块：单书/批量 AI 更新、MyNexus、MCP、助手 WebSocket。"""

    def test_book_and_admin_ai_routes_are_gated(self):
        try:
            from webserver.handlers import admin, book
        except ImportError as exc:
            self.skipTest("book/admin 路由需要 calibre：%s" % exc)

        book_gated = {"/api/book/([0-9]+)/aifill"}
        seen = set()
        for pattern, handler in book.routes():
            if pattern in book_gated:
                seen.add(pattern)
                with self.subTest(route=pattern):
                    self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                    self.assertEqual(handler.module_id, MODULE_AI, pattern)
        self.assertEqual(seen, book_gated)

        admin_gated = {"/api/admin/book/aifill", "/api/admin/ai/test"}
        seen = set()
        for pattern, handler in admin.routes():
            if pattern in admin_gated:
                seen.add(pattern)
                with self.subTest(route=pattern):
                    self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                    self.assertEqual(handler.module_id, MODULE_AI, pattern)
        self.assertEqual(seen, admin_gated)

    def test_mynexus_routes_are_gated(self):
        from webserver.handlers import mynexus

        for pattern, handler in mynexus.routes():
            with self.subTest(route=pattern):
                self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                self.assertEqual(handler.module_id, MODULE_AI, pattern)

    def test_mcp_routes_are_gated(self):
        from webserver.handlers import mcp

        for pattern, handler in mcp.routes():
            with self.subTest(route=pattern):
                self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                self.assertEqual(handler.module_id, MODULE_AI, pattern)

    def test_assistant_websocket_closes_when_module_off(self):
        import asyncio

        from webserver.handlers.assistant import AssistantWebSocketHandler

        class _Fake:
            def __init__(self):
                self.closed = None

            def get_current_user(self):
                return b"1"

            def close(self, code=None, reason=None):
                self.closed = (code, reason)

        handler = _Fake()
        with mock.patch("webserver.handlers.assistant.module_enabled", return_value=False):
            asyncio.run(AssistantWebSocketHandler.open(handler))
        self.assertEqual(handler.closed[0], 4004)

    def test_assistant_rejects_message_when_module_off(self):
        """已建立的连接也要复查，避免关闭模块后旧会话继续调用 AI。"""
        import asyncio

        from webserver.handlers.assistant import AssistantWebSocketHandler

        class _Fake:
            def __init__(self):
                self.closed = None

            def close(self, code=None, reason=None):
                self.closed = (code, reason)

        handler = _Fake()
        with mock.patch("webserver.handlers.assistant.module_enabled", return_value=False):
            asyncio.run(AssistantWebSocketHandler.on_message(handler, '{"content": "hi"}'))
        self.assertEqual(handler.closed[0], 4004)


class TestMCPPhysicalFieldGuard(unittest.TestCase):
    def test_edit_book_rejects_physical_fields_when_module_off(self):
        import asyncio

        from webserver.mcp import api_tools

        async def call(*args, **kwargs):
            return {"err": "ok"}

        with mock.patch.object(modules_module, "module_enabled", return_value=False):
            result = asyncio.run(api_tools.edit_book(call, {"book_id": 1, "book_count": 2}))
        self.assertEqual(result["status"], "error")

        with mock.patch.object(modules_module, "module_enabled", return_value=True):
            result = asyncio.run(api_tools.edit_book(call, {"book_id": 1, "book_count": 2}))
        self.assertEqual(result["err"], "ok")


class TestOpdsModuleVisibility(unittest.TestCase):
    def test_location_category_hidden_with_module(self):
        try:
            from webserver.constants import CALIBRE_COLUMN_LOCATION
            from webserver.handlers import opds
        except ImportError as exc:
            self.skipTest("opds 路由需要 calibre：%s" % exc)

        with mock.patch.object(modules_module, "module_enabled", return_value=False):
            self.assertTrue(opds.OpdsHandler._physical_category_hidden(None, CALIBRE_COLUMN_LOCATION))
        with mock.patch.object(modules_module, "module_enabled", return_value=True):
            self.assertFalse(opds.OpdsHandler._physical_category_hidden(None, CALIBRE_COLUMN_LOCATION))
        # 其它分类不受影响
        self.assertFalse(opds.OpdsHandler._physical_category_hidden(None, "tags"))


class TestUsersModuleRoutes(unittest.TestCase):
    """用户与账号：用户管理、注册/激活、社交登录门禁；登录等核心能力保持开放。"""

    def test_signup_routes_are_gated(self):
        from webserver.handlers import user

        user_gated = {
            "/api/user/sign_up",
            "/api/user/new",
            "/api/user/active/send",
            "/api/active/(.*)/(.*)",
        }
        seen = set()
        for pattern, handler in user.routes():
            if pattern in user_gated:
                seen.add(pattern)
                with self.subTest(route=pattern):
                    self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                    self.assertEqual(handler.module_id, MODULE_USERS, pattern)
        self.assertEqual(seen, user_gated)

    def test_admin_user_routes_are_gated(self):
        try:
            from webserver.handlers import admin
        except ImportError as exc:
            self.skipTest("admin 路由需要 calibre：%s" % exc)

        admin_gated = {"/api/admin/users"}
        seen = set()
        for pattern, handler in admin.routes():
            if pattern in admin_gated:
                seen.add(pattern)
                with self.subTest(route=pattern):
                    self.assertTrue(issubclass(handler, ModuleGateMixin), pattern)
                    self.assertEqual(handler.module_id, MODULE_USERS, pattern)
        self.assertEqual(seen, admin_gated)

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

    def test_social_routes_are_gated(self):
        from webserver import social_routes

        for rule in social_routes.SOCIAL_AUTH_ROUTES:
            with self.subTest(route=rule.regex.pattern):
                self.assertTrue(
                    issubclass(rule.handler_class, social_routes.SocialLoginGateMixin)
                )

    def test_social_gate_blocks_when_users_off(self):
        from webserver import social_routes

        class _Base:
            def __init__(self):
                self.prepared = False

            def prepare(self):
                self.prepared = True

        class _Gated(social_routes.SocialLoginGateMixin, _Base):
            pass

        handler = _Gated()
        with mock.patch.object(
            social_routes, "module_enabled", side_effect=lambda mid: mid != MODULE_USERS
        ):
            with self.assertRaises(Exception) as ctx:
                handler.prepare()
        self.assertEqual(getattr(ctx.exception, "status_code", None), 404)
        self.assertFalse(handler.prepared)

        with mock.patch.object(social_routes, "module_enabled", return_value=True):
            handler.prepare()
        self.assertTrue(handler.prepared)


class TestBookListHomepageHandler(unittest.TestCase):
    def _handler(self):
        class _Fake:
            def __init__(self):
                self.request = mock.Mock(headers={})
                self.written = None
                self.current_user = None
                self.sqlite_session = mock.Mock()

            def set_header(self, *args, **kwargs):
                pass

            def write(self, value):
                self.written = value

            def finish(self):
                pass

        return _Fake()

    def test_returns_empty_when_community_off(self):
        import asyncio

        from webserver.handlers.booklist import BookListHomepageHandler

        handler = self._handler()
        with mock.patch.object(modules_module, "module_enabled", return_value=False):
            asyncio.run(BookListHomepageHandler.get(handler))
        # 首页拿的是 err=="ok" 的正常空列表，不是 module.disabled 错误体
        self.assertEqual(handler.written, {"err": "ok", "booklists": []})

    def test_returns_booklists_when_community_on(self):
        import asyncio

        from webserver.handlers import booklist

        handler = self._handler()
        handler.current_user = None
        handler._serialize_many = lambda rows, viewer_id=None: ["x"]
        with mock.patch.object(modules_module, "module_enabled", return_value=True), \
                mock.patch.dict(booklist.CONF, {"ENABLE_HOMEPAGE_BOOKLISTS": True}), \
                mock.patch.object(booklist.BookListService, "list_for_homepage", return_value=[object()]):
            asyncio.run(booklist.BookListHomepageHandler.get(handler))
        self.assertEqual(handler.written, {"err": "ok", "booklists": ["x"]})


class TestImportRunSoleGate(unittest.TestCase):
    """导入本身是核心能力，模块关闭只丢弃 sole 标记，不阻断导入。"""

    def _run(self, sole, community_on):
        import asyncio
        import json

        from webserver.handlers import scan

        class _Fake:
            def __init__(self):
                self.request = mock.Mock(
                    headers={},
                    body=json.dumps({"filelist": "all", "sole": sole}).encode(),
                )
                self.written = None
                self.current_user = object()
                self.admin_user = object()

            def set_header(self, *args, **kwargs):
                pass

            def write(self, value):
                self.written = value

            def finish(self):
                pass

            def user_id(self):
                return 1

        handler = _Fake()
        captured = {}

        def fake_do_import(_svc, paths, user_id, options=None):
            captured["options"] = options

        with mock.patch.object(scan, "module_enabled", return_value=community_on), \
                mock.patch.object(scan.ScanService, "is_importing", return_value=False), \
                mock.patch.object(scan.ScanService, "is_bulk_deleting", return_value=False), \
                mock.patch.object(scan.ScanService, "do_import", new=fake_do_import):
            asyncio.run(scan.ImportRun.post(handler))
        return handler.written, captured.get("options")

    def test_sole_dropped_when_community_off(self):
        written, options = self._run(sole=True, community_on=False)
        self.assertEqual(written["err"], "ok")
        self.assertFalse(options.sole)

    def test_import_still_runs_without_sole_when_community_off(self):
        written, options = self._run(sole=False, community_on=False)
        self.assertEqual(written["err"], "ok")
        self.assertFalse(options.sole)

    def test_sole_passes_through_when_community_on(self):
        written, options = self._run(sole=True, community_on=True)
        self.assertEqual(written["err"], "ok")
        self.assertTrue(options.sole)


class TestHomepageCardVisibility(unittest.TestCase):
    """模块关闭只强制隐藏卡片，不写回用户配置；设置页取的是原样配置。"""

    def _config(self):
        from webserver.base.homepage import default_homepage

        return default_homepage()

    def test_forces_booklist_card_hidden(self):
        from webserver.base.homepage import apply_module_visibility

        config = self._config()
        with mock.patch.object(modules_module, "module_enabled", return_value=False):
            result = apply_module_visibility(config)
        self.assertIn("index.booklistRecommendation", result["hidden"])
        # 不改原对象：调用方拿到的可能是同一份 CONF 数据
        self.assertNotIn("index.booklistRecommendation", config["hidden"])

    def test_noop_when_module_on(self):
        from webserver.base.homepage import apply_module_visibility

        config = self._config()
        with mock.patch.object(modules_module, "module_enabled", return_value=True):
            result = apply_module_visibility(config)
        self.assertIs(result, config)

    def test_settings_page_uses_unforced_config(self):
        from webserver.base import homepage as homepage_module

        config = self._config()
        with mock.patch.object(modules_module, "module_enabled", return_value=False):
            with mock.patch("webserver.loader.get_settings",
                            return_value={"HOMEPAGE_CONFIG": config}):
                runtime = homepage_module.get_homepage_config()
                settings_view = homepage_module.get_homepage_config(apply_modules=False)
        self.assertIn("index.booklistRecommendation", runtime["hidden"])
        self.assertNotIn("index.booklistRecommendation", settings_view["hidden"])

    def test_admin_settings_reads_unforced_config(self):
        """守住真正的调用点：设置页必须用 apply_modules=False 取配置。"""
        import asyncio

        try:
            from webserver.handlers import admin as admin_module
        except ImportError as exc:
            self.skipTest("admin 路由需要 calibre：%s" % exc)

        class _Fake:
            def __init__(self):
                self.request = mock.Mock(headers={})
                self.written = None
                self.current_user = object()
                self.admin_user = object()
                self.site_url = "http://example.test"

            def set_header(self, *args, **kwargs):
                pass

            def write(self, value):
                self.written = value

            def finish(self):
                pass

        handler = _Fake()
        config = self._config()
        # AdminSettings.get 会原地补写一些键，patch.dict 在退出时整份恢复，避免污染后续用例
        with mock.patch.object(admin_module, "get_homepage_config", return_value=config) as get_config, \
                mock.patch.object(admin_module.BookSearch, "all_sources", return_value=[]), \
                mock.patch.dict(admin_module.CONF, {}):
            asyncio.run(admin_module.AdminSettings.get(handler))
        get_config.assert_called_once_with(apply_modules=False)
        self.assertEqual(handler.written.get("err"), "ok")


class TestSysDowngrade(unittest.TestCase):
    """模块关闭时 sys 下发要降级：友情链接为空、留言开关为假。"""

    def test_friends_empty_when_community_off(self):
        from webserver.handlers.base import BaseHandler

        with mock.patch.object(modules_module, "module_enabled", return_value=False):
            self.assertEqual(BaseHandler._build_friends_with_favicon(mock.Mock()), [])

    def test_user_memos_flag_follows_module(self):
        from webserver.handlers.base import BaseHandler

        class _Fake:
            def require_login_enabled(self):
                return False

        with mock.patch.object(modules_module, "module_enabled", return_value=False):
            flags = BaseHandler.allow_flags(_Fake())
        self.assertFalse(flags["user_memos"])
        self.assertFalse(flags["physical_books"])

        with mock.patch.object(modules_module, "module_enabled", return_value=True):
            flags = BaseHandler.allow_flags(_Fake())
        self.assertTrue(flags["user_memos"])
        self.assertTrue(flags["physical_books"])

    def test_sys_info_ai_flags_follow_module(self):
        from webserver.handlers import base as base_module

        class _Fake:
            def __init__(self):
                self.sqlite_session = mock.MagicMock()

            def _build_friends_with_favicon(self):
                return []

            def allow_flags(self):
                return {}

            def need_invited(self):
                return False

        fake = _Fake()
        conf = {
            "AI_ENABLED": True,
            "ENABLE_MYNEXUS": True,
            "SOCIALS": [{"value": "github", "text": "Github"}],
        }
        with mock.patch.dict(base_module.CONF, conf):
            with mock.patch.object(
                modules_module, "module_enabled", side_effect=lambda mid: mid != MODULE_AI
            ):
                info = base_module.BaseHandler._sys_info_with(fake, {})
            self.assertFalse(info["aiEnabled"])
            self.assertFalse(info["mynexus_enabled"])
            self.assertEqual(info["socials"], conf["SOCIALS"])

            with mock.patch.object(
                modules_module, "module_enabled", side_effect=lambda mid: mid != MODULE_USERS
            ):
                info = base_module.BaseHandler._sys_info_with(fake, {})
            self.assertTrue(info["aiEnabled"])
            self.assertTrue(info["mynexus_enabled"])
            self.assertEqual(info["socials"], [])

            with mock.patch.object(modules_module, "module_enabled", return_value=True):
                info = base_module.BaseHandler._sys_info_with(fake, {})
            self.assertTrue(info["aiEnabled"])
            self.assertTrue(info["mynexus_enabled"])
            self.assertEqual(info["socials"], conf["SOCIALS"])

    def test_register_flag_follows_users_module(self):
        from webserver.handlers import base as base_module

        class _Fake:
            def require_login_enabled(self):
                return False

        with mock.patch.dict(base_module.CONF, {"ALLOW_REGISTER": True}):
            with mock.patch.object(
                modules_module, "module_enabled", side_effect=lambda mid: mid != MODULE_USERS
            ):
                flags = base_module.BaseHandler.allow_flags(_Fake())
            self.assertFalse(flags["register"])

            with mock.patch.object(modules_module, "module_enabled", return_value=True):
                flags = base_module.BaseHandler.allow_flags(_Fake())
            self.assertTrue(flags["register"])


if __name__ == "__main__":
    unittest.main()
