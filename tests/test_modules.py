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
    MODULE_AUDIO,
    MODULE_COMMUNITY,
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
        self.assertEqual(snapshot({}), {MODULE_AUDIO: True, MODULE_COMMUNITY: True})
        self.assertEqual(
            snapshot({"ENABLE_MODULE_AUDIO": False, "ENABLE_MODULE_COMMUNITY": False}),
            {MODULE_AUDIO: False, MODULE_COMMUNITY: False},
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
    def test_sole_rejected_when_community_off(self):
        import asyncio
        import json

        from webserver.handlers import scan

        class _Fake:
            def __init__(self):
                self.request = mock.Mock(
                    headers={}, body=json.dumps({"filelist": "all", "sole": True}).encode()
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

        handler = _Fake()
        with mock.patch.object(scan, "module_enabled", return_value=False):
            asyncio.run(scan.ImportRun.post(handler))
        self.assertEqual(handler.written["err"], "module.disabled")


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
        with mock.patch.object(admin_module, "get_homepage_config", return_value=config) as get_config, \
                mock.patch.object(admin_module.BookSearch, "all_sources", return_value=[]):
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

        with mock.patch.object(modules_module, "module_enabled", return_value=True):
            flags = BaseHandler.allow_flags(_Fake())
        self.assertTrue(flags["user_memos"])


if __name__ == "__main__":
    unittest.main()
