#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""系统模式配置的规范化与下发契约。"""

import unittest

from webserver.base import system_mode


class TestNormalizeConfig(unittest.TestCase):
    def test_invalid_mode_falls_back_to_pro(self):
        cfg = system_mode.normalize_config({"mode": "unknown"})
        self.assertEqual(cfg["mode"], "pro")
        self.assertEqual(cfg["version"], system_mode.CONFIG_VERSION)

    def test_invalid_overrides_are_dropped(self):
        cfg = system_mode.normalize_config(
            {
                "mode": "personal",
                "overrides": {
                    "reading_sync": False,
                    "audio": True,
                    "bad-id": False,
                    "bad_value": "yes",
                },
            }
        )
        self.assertEqual(cfg["overrides"], {"reading_sync": False, "audio": True})

    def test_pro_clears_overrides(self):
        cfg = system_mode.normalize_config(
            {"mode": "pro", "overrides": {"reading_sync": False}}
        )
        self.assertEqual(cfg["overrides"], {})

    def test_missing_config_means_pro(self):
        self.assertEqual(system_mode.read_config({})["mode"], "pro")

    def test_build_config_sets_timestamp(self):
        cfg = system_mode.build_config("standard", {"audio": False})
        self.assertEqual(cfg["mode"], "standard")
        self.assertEqual(cfg["overrides"], {"audio": False})
        self.assertTrue(cfg["updated_at"])

    def test_sys_payload_shape(self):
        payload = system_mode.sys_payload(
            {
                "SYSTEM_MODE_CONFIG": {
                    "mode": "personal",
                    "overrides": {"book_review": True},
                }
            }
        )
        self.assertEqual(payload["systemMode"], "personal")
        self.assertEqual(payload["featureOverrides"], {"book_review": True})
        self.assertEqual(payload["featureConfigVersion"], system_mode.CONFIG_VERSION)


if __name__ == "__main__":
    unittest.main()
