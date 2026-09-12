# -*- coding: utf-8 -*-
"""ToolboxStoreClient 单元测试（M5 milestone）。

覆盖 document/Toolbox_Dynamic_Design.md 3.4 / 3.4.1 节：
- `ENABLE_TOOLBOX_STORE=False`（默认）时 get_index() 不发起任何网络请求，直接返回空结果；
  download() 直接拒绝。
- 开启后走真实请求路径（用 mock 替身，不打真实网络，请求的是 mybooks.top/toolbox/ 静态文件服务
  的 fulllist.json），并且 sha256 校验失败时拒绝安装。
"""
import hashlib
import unittest
from unittest.mock import MagicMock, patch

from webserver.loader import get_settings
from webserver.services import toolbox_store
from webserver.services.toolbox_store import ToolboxStoreClient, ToolboxStoreError

CONF = get_settings()


class TestStoreDisabled(unittest.TestCase):
    """ENABLE_TOOLBOX_STORE=False（默认）：不发网络请求，直接返回空结果。"""

    def setUp(self):
        CONF["ENABLE_TOOLBOX_STORE"] = False

    @patch("requests.get")
    def test_get_index_returns_empty_without_request(self, mock_get):
        self.assertEqual(ToolboxStoreClient().get_index(), [])
        mock_get.assert_not_called()

    def test_download_raises_without_request(self):
        with self.assertRaises(ToolboxStoreError):
            ToolboxStoreClient().download("https://mybooks.top/toolbox/files/favorite/demo.zip", "deadbeef")


class TestStoreEnabled(unittest.TestCase):
    """ENABLE_TOOLBOX_STORE=True：走真实请求路径（mock 掉 requests）。"""

    def setUp(self):
        CONF["ENABLE_TOOLBOX_STORE"] = True

    def tearDown(self):
        CONF["ENABLE_TOOLBOX_STORE"] = False

    VALID_ENTRY = {
        "tool_id": "demo_tool",
        "latest_revision": "0.2.0",
        "icon_url": "https://mybooks.top/toolbox/logos/demo_tool.png",
        "download_url": "https://mybooks.top/toolbox/files/favorite/demo_tool-0.2.0.zip",
    }

    @patch("requests.get")
    def test_get_index_returns_tools_list(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"tools": [self.VALID_ENTRY]}
        mock_get.return_value = mock_resp

        tools = ToolboxStoreClient().get_index()
        self.assertEqual(tools, [self.VALID_ENTRY])
        mock_get.assert_called_once()
        self.assertEqual(mock_get.call_args.args[0], ToolboxStoreClient.INDEX_URL)

    @patch("requests.get")
    def test_get_index_returns_empty_on_error(self, mock_get):
        mock_get.side_effect = Exception("network down")
        self.assertEqual(ToolboxStoreClient().get_index(), [])

    @patch("requests.get")
    def test_get_index_drops_entries_with_untrusted_host(self, mock_get):
        untrusted = dict(self.VALID_ENTRY, download_url="https://evil.example.com/demo_tool.zip")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"tools": [untrusted, self.VALID_ENTRY]}
        mock_get.return_value = mock_resp

        tools = ToolboxStoreClient().get_index()
        self.assertEqual(tools, [self.VALID_ENTRY])

    @patch("requests.get")
    def test_get_index_drops_entries_with_untrusted_icon_host(self, mock_get):
        untrusted = dict(self.VALID_ENTRY, icon_url="https://evil.example.com/demo_tool.png")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"tools": [untrusted]}
        mock_get.return_value = mock_resp

        self.assertEqual(ToolboxStoreClient().get_index(), [])

    def test_download_requires_sha256(self):
        with self.assertRaises(ToolboxStoreError):
            ToolboxStoreClient().download("https://mybooks.top/toolbox/files/favorite/demo.zip", "")

    def test_download_rejects_untrusted_host(self):
        with self.assertRaises(ToolboxStoreError):
            ToolboxStoreClient().download("https://evil.example.com/demo.zip", "0" * 64)

    @patch("requests.get")
    def test_download_verifies_sha256_and_returns_path(self, mock_get):
        content = b"fake zip bytes"
        expected_sha256 = hashlib.sha256(content).hexdigest()

        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [content]
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        mock_get.return_value = mock_resp

        path = ToolboxStoreClient().download("https://mybooks.top/toolbox/files/favorite/demo.zip", expected_sha256)
        try:
            with open(path, "rb") as f:
                self.assertEqual(f.read(), content)
        finally:
            import os
            if os.path.exists(path):
                os.remove(path)

    @patch("requests.get")
    def test_download_rejects_sha256_mismatch(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"fake zip bytes"]
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        mock_get.return_value = mock_resp

        with self.assertRaises(ToolboxStoreError):
            ToolboxStoreClient().download("https://mybooks.top/toolbox/files/favorite/demo.zip", "0" * 64)


class TestIndexCache(unittest.TestCase):
    """get_cached_index() / find_in_index() 的 TTL 缓存。"""

    def setUp(self):
        CONF["ENABLE_TOOLBOX_STORE"] = True
        toolbox_store._index_cache = {"tools": [], "ts": 0.0}

    def tearDown(self):
        CONF["ENABLE_TOOLBOX_STORE"] = False
        toolbox_store._index_cache = {"tools": [], "ts": 0.0}

    @patch.object(ToolboxStoreClient, "get_index")
    def test_cache_reused_within_ttl(self, mock_get_index):
        mock_get_index.return_value = [{"tool_id": "demo_tool"}]

        first = toolbox_store.get_cached_index()
        second = toolbox_store.get_cached_index()

        self.assertEqual(first, [{"tool_id": "demo_tool"}])
        self.assertEqual(second, first)
        mock_get_index.assert_called_once()

    @patch.object(ToolboxStoreClient, "get_index")
    def test_force_refresh_bypasses_cache(self, mock_get_index):
        mock_get_index.return_value = [{"tool_id": "demo_tool"}]
        toolbox_store.get_cached_index()
        toolbox_store.get_cached_index(force=True)
        self.assertEqual(mock_get_index.call_count, 2)

    @patch.object(ToolboxStoreClient, "get_index")
    def test_find_in_index_matches_tool_id(self, mock_get_index):
        mock_get_index.return_value = [
            {"tool_id": "demo_tool", "download_url": "https://x/demo.zip"},
            {"tool_id": "other_tool"},
        ]
        entry = toolbox_store.find_in_index("demo_tool")
        self.assertEqual(entry["download_url"], "https://x/demo.zip")
        self.assertEqual(toolbox_store.find_in_index("missing"), {})


if __name__ == "__main__":
    unittest.main()
