#!/usr/bin/env python3

import unittest
from unittest import mock

from webserver import perf
from webserver.base import setting_saver
from webserver.base.setting_saver import ADMIN_SETTING_KEYS, PERSISTABLE_KEYS, SettingsSaver


class TestPersistableKeys(unittest.TestCase):

    def test_every_admin_key_is_persistable(self):
        self.assertTrue(set(ADMIN_SETTING_KEYS) <= PERSISTABLE_KEYS)

    def test_perf_keys_are_saved_by_admin_page(self):
        for key in perf.setting_keys():
            self.assertIn(key, ADMIN_SETTING_KEYS)

    def test_no_duplicate_admin_keys(self):
        self.assertEqual(len(ADMIN_SETTING_KEYS), len(set(ADMIN_SETTING_KEYS)))


class TestSavePartial(unittest.TestCase):

    def run_partial(self, conf, overrides):
        captured = {}

        def fake_save(self, args):
            captured.update(args)
            return {"err": "ok"}

        with mock.patch.dict(setting_saver.CONF, conf, clear=False), mock.patch.object(SettingsSaver, "save_extra_settings", fake_save):
            SettingsSaver().save_partial(overrides)
        return captured

    def test_keeps_settings_that_default_to_false(self):
        saved = self.run_partial(
            {"ENABLE_HOMEPAGE_BOOKLISTS": True, "ENABLE_FOLDER_BROWSE": True, "ENABLE_DOWNLOAD_QUOTA": True, "KEEP_UPLOAD_SOURCE_FILE": True},
            {"SYNC_LEGACY_MIGRATION_DONE": True},
        )
        for key in ("ENABLE_HOMEPAGE_BOOKLISTS", "ENABLE_FOLDER_BROWSE", "ENABLE_DOWNLOAD_QUOTA", "KEEP_UPLOAD_SOURCE_FILE"):
            self.assertIs(saved[key], True, key)
        self.assertTrue(saved["SYNC_LEGACY_MIGRATION_DONE"])

    def test_keeps_performance_settings(self):
        saved = self.run_partial({"PERFORMANCE_MODE": "lite", "LITE_GROUP_FILES": False}, {"BOOKBARN_TOKEN": "t"})
        self.assertEqual(saved["PERFORMANCE_MODE"], "lite")
        self.assertIs(saved["LITE_GROUP_FILES"], False)

    def test_computed_settings_are_not_persisted(self):
        saved = self.run_partial({"html_path": "/x", "installed_version": "v"}, {"BOOKBARN_TOKEN": "t"})
        self.assertNotIn("html_path", saved)

    def test_every_admin_key_present_in_conf_survives(self):
        conf = {key: "marker" for key in ADMIN_SETTING_KEYS}
        saved = self.run_partial(conf, {"BOOKBARN_TOKEN": "t"})
        for key in ADMIN_SETTING_KEYS:
            if key != "BOOKBARN_TOKEN":
                self.assertEqual(saved[key], "marker", key)


if __name__ == "__main__":
    unittest.main()
