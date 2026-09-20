#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""外观设置（appearance）白名单校验与归一化的单元测试。

不需要 MyBooks 运行时 / calibre / DB —— webserver/base/appearance.py 只有纯函数。

运行：
    python -m pytest tests/test_user_appearance.py -q
    python tests/test_user_appearance.py
"""
import io
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)

from webserver.base.appearance import (  # noqa: E402
    ALLOWED_BACKGROUNDS,
    ALLOWED_RADII,
    ALLOWED_SIDEBAR_ICON_MODES,
    APPEARANCE_KEY,
    APPEARANCE_VERSION,
    MAX_APPEARANCE_BYTES,
    appearance_size,
    is_appearance_too_large,
    is_client_too_new,
    normalize_appearance,
    read_appearance,
)


class FakeUser(object):
    """只带 extra 字段的 Reader 替身（read_appearance 只用到它）。"""

    def __init__(self, extra):
        self.extra = extra


class TestNormalizeBasics(unittest.TestCase):
    def test_empty_input_returns_empty_dict(self):
        # 关键语义：没保存过就返回 {}，前端据此回退到「本地缓存 → site_theme → 内置默认」
        self.assertEqual(normalize_appearance(None), ({}, []))
        self.assertEqual(normalize_appearance({}), ({}, []))
        self.assertEqual(normalize_appearance(None, base={}), ({}, []))

    def test_non_dict_payload_is_rejected_wholesale(self):
        for payload in ("a string", 123, ["list"]):
            clean, dropped = normalize_appearance(payload, base={"darkMode": False})
            self.assertEqual(clean, {"darkMode": False})
            self.assertEqual(dropped, ["<payload>"])

    def test_server_stamps_version(self):
        clean, _ = normalize_appearance({"darkMode": False})
        self.assertEqual(clean["v"], APPEARANCE_VERSION)

    def test_client_version_is_ignored(self):
        # 客户端指定任何 v 都不该写进去；v 只由服务端盖章
        clean, _ = normalize_appearance({"v": 99, "darkMode": True})
        self.assertEqual(clean["v"], APPEARANCE_VERSION)

    def test_result_is_json_serializable_and_within_budget(self):
        clean, _ = normalize_appearance(
            {
                "darkMode": True,
                "brandColor": "#123456",
                "accent": "#ABCDEF",
                "radius": "8px",
                "background": "mesh",
                "sidebarIconMode": "custom",
                "sidebarIconColor": "#654321",
            }
        )
        self.assertLessEqual(appearance_size(clean), MAX_APPEARANCE_BYTES)
        self.assertFalse(is_appearance_too_large(clean))
        json.dumps(clean)  # 不应抛


class TestColorValidation(unittest.TestCase):
    def test_valid_hex_is_lowercased(self):
        clean, dropped = normalize_appearance({"brandColor": "#AABBCC"})
        self.assertEqual(clean["brandColor"], "#aabbcc")
        self.assertEqual(dropped, [])

    def test_invalid_colors_are_dropped(self):
        for bad in ("red", "#12345", "#1234567", "003153", "#GGGGGG", "rgb(0,0,0)", 12345, True, {}, []):
            clean, dropped = normalize_appearance({"brandColor": bad})
            self.assertNotIn("brandColor", clean, msg="accepted bad color: %r" % (bad,))
            self.assertEqual(dropped, ["brandColor"])
            self.assertEqual(clean, {})  # 只有默认/被丢弃的键时不写 v

    def test_null_and_empty_reset_color_to_default(self):
        # 显式 null/空串 = 回到内置默认品牌色，是合法输入而不是非法值
        for value in (None, ""):
            clean, dropped = normalize_appearance({"brandColor": value}, base={"brandColor": "#111111"})
            self.assertIsNone(clean["brandColor"])
            self.assertEqual(dropped, [])

    def test_oversized_string_is_dropped(self):
        clean, dropped = normalize_appearance({"accent": "#" + "a" * 5000})
        self.assertEqual(clean, {})
        self.assertEqual(dropped, ["accent"])

    def test_accent_rejects_null_and_empty(self):
        # accent（主色）没有「回到默认」这个语义：它有写死的内置默认值，前端 sanitize
        # 也只接受合法 hex。若沿用 _clean_color 把 null 存进来，user.appearance 会变成
        # 「非空」，而前端正是用「非空」判断这个账号保存过外观 —— 于是一个
        # {"accent": null} 就能让内置默认（深色）顶掉站点默认主题。
        for value in (None, ""):
            clean, dropped = normalize_appearance({"accent": value}, base={"accent": "#111111"})
            self.assertEqual(dropped, ["accent"])
            self.assertEqual(clean["accent"], "#111111")  # 保留基线值，不被 null 顶掉

    def test_brand_color_still_accepts_null(self):
        # brandColor / sidebarIconColor 的 null 是「用内置默认」，属合法输入（与前端一致）
        clean, dropped = normalize_appearance({"brandColor": None, "sidebarIconColor": ""})
        self.assertEqual(dropped, [])
        self.assertIsNone(clean["brandColor"])
        self.assertIsNone(clean["sidebarIconColor"])


class TestEnumValidation(unittest.TestCase):
    def test_all_whitelisted_values_accepted(self):
        for radius in sorted(ALLOWED_RADII):
            clean, dropped = normalize_appearance({"radius": radius})
            self.assertEqual(clean.get("radius"), radius, msg="radius=%s" % radius)
            self.assertEqual(dropped, [])
        for background in sorted(ALLOWED_BACKGROUNDS):
            clean, dropped = normalize_appearance({"background": background})
            self.assertEqual(clean.get("background"), background, msg="background=%s" % background)
            self.assertEqual(dropped, [])
        for mode in sorted(ALLOWED_SIDEBAR_ICON_MODES):
            clean, dropped = normalize_appearance({"sidebarIconMode": mode})
            self.assertEqual(clean.get("sidebarIconMode"), mode, msg="mode=%s" % mode)
            self.assertEqual(dropped, [])

    def test_whitelist_matches_frontend(self):
        # 与 app/src/components/AppearanceMenu.vue / appearance.css 保持同步的守卫
        self.assertEqual(
            ALLOWED_BACKGROUNDS,
            {
                "default",
                "cross",
                "left-diagonal",
                "right-diagonal",
                "aurora",
                "horizon",
                "glow",
                "mesh",
                "repeat-image-1",
                "repeat-image-2",
                "repeat-image-3",
                "repeat-image-4",
            },
        )
        self.assertEqual(ALLOWED_RADII, {"0px", "4px", "8px", "16px"})
        self.assertEqual(ALLOWED_SIDEBAR_ICON_MODES, {"multi", "theme", "custom"})

    def test_unknown_enum_values_are_dropped_not_coerced(self):
        for bad in ("blue", "DEFAULT", "12px", "", None, 3, ["default"]):
            clean, dropped = normalize_appearance({"background": bad})
            self.assertNotIn("background", clean)
            self.assertEqual(dropped, ["background"])


class TestBoolValidation(unittest.TestCase):
    def test_bool_passthrough(self):
        self.assertEqual(normalize_appearance({"darkMode": True})[0]["darkMode"], True)
        self.assertEqual(normalize_appearance({"darkMode": False})[0]["darkMode"], False)

    def test_string_forms_tolerated(self):
        self.assertIs(normalize_appearance({"darkMode": "true"})[0]["darkMode"], True)
        self.assertIs(normalize_appearance({"darkMode": "false"})[0]["darkMode"], False)
        self.assertIs(normalize_appearance({"darkMode": "1"})[0]["darkMode"], True)
        self.assertIs(normalize_appearance({"darkMode": "0"})[0]["darkMode"], False)
        self.assertIs(normalize_appearance({"darkMode": "TRUE"})[0]["darkMode"], True)

    def test_non_bool_is_dropped(self):
        for bad in ("yes", 2, None, {}, []):
            clean, dropped = normalize_appearance({"darkMode": bad})
            self.assertNotIn("darkMode", clean)
            self.assertEqual(dropped, ["darkMode"])


class TestPatchSemantics(unittest.TestCase):
    def test_unknown_keys_are_dropped(self):
        clean, dropped = normalize_appearance({"nope": 1, "alsoNope": {"x": 1}})
        self.assertEqual(clean, {})
        self.assertEqual(sorted(dropped), ["alsoNope", "nope"])

    def test_unknown_key_does_not_clobber_base(self):
        clean, dropped = normalize_appearance({"evil": "x"}, base={"darkMode": False})
        self.assertEqual(clean, {"darkMode": False, "v": APPEARANCE_VERSION})
        self.assertEqual(dropped, ["evil"])

    def test_invalid_value_keeps_base_value(self):
        # 非法值只丢弃该键，不能把基线里已有的合法值顶成空
        clean, dropped = normalize_appearance(
            {"brandColor": "not-a-color"},
            base={"brandColor": "#003153", "darkMode": True},
        )
        self.assertEqual(clean["brandColor"], "#003153")
        self.assertTrue(clean["darkMode"])
        self.assertEqual(dropped, ["brandColor"])

    def test_partial_patch_merges(self):
        base = {"darkMode": False, "accent": "#111111", "sidebarIconMode": "multi"}
        clean, dropped = normalize_appearance({"brandColor": "#222222"}, base=base)
        self.assertEqual(dropped, [])
        self.assertEqual(clean["brandColor"], "#222222")
        self.assertFalse(clean["darkMode"])          # 未提交的键保持原值
        self.assertEqual(clean["accent"], "#111111")
        self.assertEqual(clean["sidebarIconMode"], "multi")

    def test_base_is_not_mutated(self):
        base = {"darkMode": True}
        normalize_appearance({"radius": "8px"}, base=base)
        self.assertEqual(base, {"darkMode": True})

    def test_base_without_v_gets_stamped(self):
        # 历史数据（或迁移过来的数据）没有 v，读取时应补上
        clean, _ = normalize_appearance({"darkMode": True}, base={"darkMode": True})
        self.assertEqual(clean["v"], APPEARANCE_VERSION)

    def test_idempotent(self):
        once, _ = normalize_appearance({"darkMode": False, "background": "mesh"})
        twice, dropped = normalize_appearance(once, base=once)
        self.assertEqual(once, twice)
        self.assertEqual(dropped, [])


class TestClientVersionGuard(unittest.TestCase):
    def test_future_version_detected(self):
        self.assertTrue(is_client_too_new({"v": APPEARANCE_VERSION + 1}))
        self.assertTrue(is_client_too_new({"v": 99}))

    def test_current_or_older_version_ok(self):
        self.assertFalse(is_client_too_new({"v": APPEARANCE_VERSION}))
        self.assertFalse(is_client_too_new({"v": 0}))
        self.assertFalse(is_client_too_new({}))
        self.assertFalse(is_client_too_new(None))
        self.assertFalse(is_client_too_new({"v": "2"}))   # 字符串不算
        self.assertFalse(is_client_too_new({"v": True}))  # bool 不是版本号
        self.assertFalse(is_client_too_new("not-a-dict"))


class TestReadAppearance(unittest.TestCase):
    def test_none_user(self):
        self.assertEqual(read_appearance(None), {})

    def test_user_without_extra(self):
        self.assertEqual(read_appearance(FakeUser(None)), {})
        self.assertEqual(read_appearance(FakeUser({})), {})

    def test_user_with_stored_but_bogus_value(self):
        # 库里存了非 dict / 非法内容时，读取要静默降级而不是抛异常
        self.assertEqual(read_appearance(FakeUser({APPEARANCE_KEY: "junk"})), {})
        self.assertEqual(read_appearance(FakeUser({APPEARANCE_KEY: None})), {})
        self.assertEqual(read_appearance(FakeUser({APPEARANCE_KEY: {"bad": 1}})), {})

    def test_user_with_stored_value(self):
        stored = {"darkMode": False, "brandColor": "#123456"}
        self.assertEqual(
            read_appearance(FakeUser({APPEARANCE_KEY: stored})),
            {"darkMode": False, "brandColor": "#123456", "v": APPEARANCE_VERSION},
        )

    def test_invalid_key_inside_stored_value_is_dropped(self):
        # 手工改过库 / 旧版本残留的非法值，读取时一并清洗
        stored = {"darkMode": True, "brandColor": "red", "radius": "8px", "junk": 1}
        clean = read_appearance(FakeUser({APPEARANCE_KEY: stored}))
        self.assertEqual(clean, {"darkMode": True, "radius": "8px", "v": APPEARANCE_VERSION})


class TestDirtyBase(unittest.TestCase):
    """写入路径传进来的 base 是库里的原始值，可能是脏数据（手工改库 / 历史残留）。

    dict("junk") / dict(123) 会直接抛 ValueError/TypeError，而 /api/user/appearance
    的 POST 正是把 user.extra["appearance"] 当 base 传进来的 —— 一旦抛异常，
    handlers/base.py 的 @js 会把整个 traceback 塞进 msg 回吐给客户端。
    """

    def test_non_dict_base_is_ignored(self):
        for base in ("junk", 123, ["a"], [["a", "b"]], True):
            clean, dropped = normalize_appearance({"darkMode": False}, base=base)
            self.assertEqual(clean, {"darkMode": False, "v": APPEARANCE_VERSION}, msg=repr(base))
            self.assertEqual(dropped, [], msg=repr(base))

    def test_non_dict_base_with_non_dict_raw(self):
        clean, dropped = normalize_appearance("junk", base="junk")
        self.assertEqual(clean, {})
        self.assertEqual(dropped, ["<payload>"])

    def test_dirty_base_values_are_revalidated(self):
        # 走写入路径时 base 会先被 normalize 清洗（见 UserAppearance.post）：
        # 非法值与未知键都不该被带进下一次落库
        base = {"darkMode": True, "brandColor": "red", "radius": "8px", "junk": 1}
        cleaned_base = normalize_appearance(base)[0]
        clean, _ = normalize_appearance({"accent": "#123456"}, base=cleaned_base)
        self.assertEqual(
            clean,
            {"darkMode": True, "radius": "8px", "accent": "#123456", "v": APPEARANCE_VERSION},
        )


class TestFrontendIntegrationGuards(unittest.TestCase):
    """前后端有若干「必须保持一致」的复制品（白名单、schema 版本、对比度阈值）。

    这些地方没有编译期检查，出问题只会表现为「某个设置怎么选都不生效」这种难查的现象，
    所以在这里用最便宜的方式钉住。
    """

    @staticmethod
    def _read(relpath):
        with io.open(os.path.join(ROOT, relpath), encoding="utf-8") as fp:
            return fp.read()

    def test_app_html_background_and_radius_lists_match_backend(self):
        html = self._read("app/src/app.html")

        def js_list(name):
            match = re.search(r"var %s = \[([^\]]*)\];" % name, html)
            self.assertIsNotNone(match, msg="app/src/app.html 里找不到 %s" % name)
            return {item.strip().strip("'\"") for item in match.group(1).split(",") if item.strip()}

        self.assertEqual(js_list("BACKGROUNDS"), set(ALLOWED_BACKGROUNDS))
        self.assertEqual(js_list("RADII"), set(ALLOWED_RADII))

    def test_client_schema_version_matches_backend(self):
        utils = self._read("app/src/utils/appearance.js")
        match = re.search(r"export const SCHEMA_VERSION = (\d+);", utils)
        self.assertIsNotNone(match)
        # 客户端 v 比服务端新时会被拒绝（appearance.version.unsupported），别让两边漂移
        self.assertEqual(int(match.group(1)), APPEARANCE_VERSION)

    def test_contrast_threshold_matches_inline_script(self):
        utils = self._read("app/src/utils/appearance.js")
        html = self._read("app/src/app.html")
        # 首帧脚本里有一份同步实现，阈值必须一致，否则刷新瞬间会闪一下
        self.assertIn("0.179", utils)
        self.assertIn("0.179", html)

    def test_inline_script_uses_same_site_theme_predicate(self):
        html = self._read("app/src/app.html")
        # 「不等于 light 就算深色」——与 utils/appearance.js 的 siteThemeIsDark() 同判据
        self.assertIn("siteTheme !== 'light'", html)


class TestBackendErrorMessagesAreTranslated(unittest.TestCase):
    """新加的后端文案必须同时进 en / zh-TW 目录，否则 en 用户会看到中文报错。"""

    MESSAGES = ("外观设置版本过新，请刷新页面后重试", "外观设置过大")

    def test_catalogues_cover_appearance_errors(self):
        for name in ("en", "zh-TW"):
            with io.open(
                os.path.join(ROOT, "webserver", "i18n", "%s.json" % name), encoding="utf-8"
            ) as fp:
                catalog = json.load(fp)
            for message in self.MESSAGES:
                self.assertIn(message, catalog, msg="%s.json 缺少 %s" % (name, message))
                self.assertTrue(catalog[message].strip(), msg="%s.json 的 %s 是空翻译" % (name, message))


if __name__ == "__main__":
    unittest.main(verbosity=2)
