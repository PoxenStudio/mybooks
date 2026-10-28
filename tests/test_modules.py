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
        self.assertEqual(snapshot({}), {MODULE_AUDIO: True})
        self.assertEqual(
            snapshot({"ENABLE_MODULE_AUDIO": False}), {MODULE_AUDIO: False}
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

        self.assertTrue(settings_module.settings["ENABLE_MODULE_AUDIO"])


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


if __name__ == "__main__":
    unittest.main()
