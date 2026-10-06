#!/usr/bin/env python3

import json
import os
import unittest
from unittest import mock

from webserver import perf

ROOT = os.path.dirname(os.path.dirname(__file__))
LOCALES = ("zh", "zh-TW", "en")


def load_locale(name):
    with open(os.path.join(ROOT, "app", "locales", name + ".json"), encoding="utf-8") as f:
        return json.load(f)


class TestModeSwitches(unittest.TestCase):

    def test_normal_mode_disables_every_item(self):
        with mock.patch.dict(perf.CONF, {"PERFORMANCE_MODE": "normal"}):
            self.assertFalse(perf.is_lite())
            for item in perf.ITEM_GROUP:
                self.assertFalse(perf.lite_on(item))

    def test_lite_mode_enables_items_by_default(self):
        with mock.patch.dict(perf.CONF, {"PERFORMANCE_MODE": "lite"}):
            for group in perf.LITE_GROUPS:
                perf.CONF.pop(group, None)
            for item in perf.ITEM_GROUP:
                self.assertTrue(perf.lite_on(item), item)

    def test_group_switch_turns_off_all_its_items(self):
        with mock.patch.dict(perf.CONF, {"PERFORMANCE_MODE": "lite", "LITE_GROUP_LISTING": False}):
            for item in perf.LITE_GROUPS["LITE_GROUP_LISTING"]:
                self.assertFalse(perf.lite_on(item), item)
            self.assertTrue(perf.lite_on("LITE_THROTTLE"))

    def test_every_item_belongs_to_exactly_one_group(self):
        items = [item for items in perf.LITE_GROUPS.values() for item in items]
        self.assertEqual(len(items), len(set(items)))
        self.assertEqual(set(items), set(perf.ITEM_GROUP))

    def test_setting_keys_cover_mode_and_groups(self):
        self.assertEqual(perf.setting_keys()[0], "PERFORMANCE_MODE")
        self.assertEqual(set(perf.setting_keys()[1:]), set(perf.LITE_GROUPS))


class TestSanitize(unittest.TestCase):

    def test_invalid_mode_falls_back_to_normal(self):
        self.assertEqual(perf.sanitize({"PERFORMANCE_MODE": "turbo"}, {})["PERFORMANCE_MODE"], "normal")

    def test_missing_values_keep_current(self):
        args = perf.sanitize({}, {"PERFORMANCE_MODE": "lite", "LITE_GROUP_FILES": False})
        self.assertEqual(args["PERFORMANCE_MODE"], "lite")
        self.assertFalse(args["LITE_GROUP_FILES"])

    def test_defaults_when_nothing_saved(self):
        args = perf.sanitize({}, {})
        self.assertEqual(args["PERFORMANCE_MODE"], "normal")
        self.assertTrue(all(args[group] is True for group in perf.LITE_GROUPS))

    def test_groups_coerced_to_bool(self):
        self.assertIs(perf.sanitize({"LITE_GROUP_FILES": 0}, {})["LITE_GROUP_FILES"], False)


class TestFrontendConsistency(unittest.TestCase):

    def test_every_group_is_in_settings_page(self):
        with open(os.path.join(ROOT, "app", "src", "pages", "admin", "settings.vue"), encoding="utf-8") as f:
            page = f.read()
        for key in perf.setting_keys():
            self.assertIn('"%s"' % key, page)

    def test_every_group_has_text_in_all_locales(self):
        for name in LOCALES:
            settings = load_locale(name)["settings"]
            for key in ("perf_mode_lite", "perf_mode_hint"):
                self.assertTrue(settings.get(key), "%s missing settings.%s" % (name, key))
            for group in perf.LITE_GROUPS:
                text = group.lower()
                self.assertTrue(settings.get(text), "%s missing settings.%s" % (name, text))
                self.assertTrue(settings.get(text + "_hint"), "%s missing settings.%s_hint" % (name, text))

    def test_header_texts_in_all_locales(self):
        for name in LOCALES:
            header = load_locale(name)["appHeader"]
            self.assertTrue(header.get("lite_mode"))
            self.assertTrue(header.get("lite_mode_tip"))

    def test_locale_key_sets_match_for_perf_texts(self):
        def perf_keys(name):
            data = load_locale(name)
            return {k for k in data["settings"] if k.startswith(("perf_", "lite_"))} | {"h." + k for k in data["appHeader"] if k.startswith("lite_")}

        base = perf_keys("zh")
        for name in LOCALES[1:]:
            self.assertEqual(base, perf_keys(name))


if __name__ == "__main__":
    unittest.main()
