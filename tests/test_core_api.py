# -*- coding: utf-8 -*-
"""CoreAPI 单元测试（不依赖真实 Calibre/DB，用轻量 fake owner 验证命名空间转发逻辑）。

覆盖 document/Toolbox_Dynamic_Design.md 第二节描述的 M0 交付物：
- CoreAPI.calibre / .db / .tasks / .messages / .storage / .settings / .utils
  七个命名空间存在且可用
- 已有 BaseTool 方法（import_file / merge_book_formats / delete_book_by_id /
  create_task / ...）的 CoreAPI 封装原样转发，不改变行为
- CoreAPI.storage 的 get_config/set_config 新增能力
- CoreAPI.settings 的白名单只读语义：白名单内的 key 转发到 CONF，白名单外的 key
  一律返回 default，不触碰真实 CONF
- CoreAPI.utils 转发 `webserver/utils.py` 里的 strip/get_title_sort/
  guess_title_author_from_filename/parse_date，不改变行为
- CoreAPI.calibre.new_metadata 构造 BookMetadata（Protocol 本身不能被实例化，真正的
  构造逻辑转发给 calibre.ebooks.metadata.book.base.Metadata），调用方不需要 import calibre
"""
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

from webserver.toolbox.core_api import CORE_API_VERSION, CoreAPI


class FakeOwner:
    """模拟一个 BaseTool 实例：只提供 CoreAPI 命名空间会用到的属性/方法。"""

    TOOL_DATA_ROOT = None  # 测试时指向临时目录
    _tool_id = "fake_tool"

    def __init__(self):
        self.db = MagicMock()
        self.session = MagicMock()
        # BaseTool 上已有的方法，CoreAPI 应该原样转发调用，不重新实现
        self.import_file = MagicMock(return_value=123)
        self.merge_book_formats = MagicMock(return_value=["MOBI"])
        self.delete_book_by_id = MagicMock()
        self.get_all_book_ids = MagicMock(return_value=[1, 2, 3])
        self.get_book_metadata = MagicMock(return_value="metadata-obj")
        self.set_book_language = MagicMock()
        self.get_work_dir = MagicMock(return_value="/tmp/fake_tool/work")
        self.cleanup_work_dir = MagicMock()
        self.create_task = MagicMock(return_value=42)
        self.update_task_progress = MagicMock()
        self.complete_task = MagicMock()
        self.make_progress_callback = MagicMock(return_value=lambda p: None)

    def tool_id(self):
        return self._tool_id


class TestCoreAPINamespaces(unittest.TestCase):
    def setUp(self):
        self.owner = FakeOwner()
        self.api = CoreAPI(self.owner)

    def test_version_constant(self):
        self.assertEqual(CoreAPI.VERSION, CORE_API_VERSION)
        self.assertRegex(CORE_API_VERSION, r"^\d+\.\d+\.\d+$")

    def test_namespaces_exist(self):
        for ns in ("calibre", "db", "tasks", "messages", "storage", "settings", "utils"):
            self.assertTrue(hasattr(self.api, ns), f"CoreAPI 缺少命名空间 {ns}")

    # --- CoreAPI.calibre：转发到 owner 已有方法，行为不变 ---

    def test_calibre_import_file_forwards(self):
        book_id = self.api.calibre.import_file(1, "/tmp/x.epub", "Title", ["Author"])
        self.assertEqual(book_id, 123)
        self.owner.import_file.assert_called_once_with(
            1, "/tmp/x.epub", "Title", ["Author"], delete_after_import=True
        )

    def test_calibre_merge_formats_forwards(self):
        added = self.api.calibre.merge_formats(10, 20)
        self.assertEqual(added, ["MOBI"])
        self.owner.merge_book_formats.assert_called_once_with(10, 20)

    def test_calibre_delete_book_forwards(self):
        self.api.calibre.delete_book(99)
        self.owner.delete_book_by_id.assert_called_once_with(99)

    def test_calibre_all_book_ids_forwards(self):
        self.assertEqual(self.api.calibre.all_book_ids(), [1, 2, 3])
        self.owner.get_all_book_ids.assert_called_once()

    def test_calibre_set_language_forwards(self):
        self.api.calibre.set_language(5, "zh")
        self.owner.set_book_language.assert_called_once_with(5, "zh")

    def test_calibre_search_books_uses_new_api_search(self):
        self.owner.db.new_api.search.return_value = [1, 2]
        self.owner.db.get_data_as_dict.return_value = [{"id": 1}, {"id": 2}]
        result = self.api.calibre.search_books("title:foo", max_results=5)
        self.owner.db.new_api.search.assert_called_once_with("title:foo")
        self.owner.db.get_data_as_dict.assert_called_once_with(ids=[1, 2])
        self.assertEqual(result, [{"id": 1}, {"id": 2}])

    def test_calibre_search_books_empty(self):
        self.owner.db.new_api.search.return_value = []
        self.assertEqual(self.api.calibre.search_books("nomatch"), [])
        self.owner.db.get_data_as_dict.assert_not_called()

    def test_calibre_add_format_and_format_abspath(self):
        self.api.calibre.add_format(1, "PDF", "/tmp/a.pdf")
        self.owner.db.add_format.assert_called_once_with(1, "PDF", "/tmp/a.pdf", index_is_id=True)

        self.owner.db.format_abspath.return_value = "/tmp/a.pdf"
        path = self.api.calibre.format_abspath(1, "PDF")
        self.assertEqual(path, "/tmp/a.pdf")
        self.owner.db.format_abspath.assert_called_once_with(1, "PDF", index_is_id=True)

    # --- CoreAPI.tasks：转发到 owner 已有方法，行为不变 ---

    def test_tasks_create_update_complete(self):
        task_id = self.api.tasks.create_task(progress_data={"a": 1})
        self.assertEqual(task_id, 42)
        self.owner.create_task.assert_called_once_with(progress_data={"a": 1})

        self.api.tasks.update_progress(42, 50, progress_data={"b": 2})
        self.owner.update_task_progress.assert_called_once_with(42, 50, progress_data={"b": 2})

        self.api.tasks.complete_task(42, error_message="boom")
        self.owner.complete_task.assert_called_once_with(42, error_message="boom")

    def test_tasks_make_progress_callback_forwards(self):
        cb = self.api.tasks.make_progress_callback(42)
        self.owner.make_progress_callback.assert_called_once_with(
            42, progress_data_factory=None, outer_callback=None
        )
        self.assertTrue(callable(cb))

    # --- CoreAPI.storage：get_work_dir/cleanup_work_dir 转发；get_config/set_config 新增 ---

    def test_storage_work_dir_forwards(self):
        self.assertEqual(self.api.storage.get_work_dir("key"), "/tmp/fake_tool/work")
        self.owner.get_work_dir.assert_called_once_with("key")

        self.api.storage.cleanup_work_dir("/tmp/fake_tool/work")
        self.owner.cleanup_work_dir.assert_called_once_with("/tmp/fake_tool/work")

    def test_storage_config_roundtrip(self):
        tmp_root = tempfile.mkdtemp(prefix="mybooks_toolbox_test_")
        try:
            self.owner.TOOL_DATA_ROOT = tmp_root
            self.assertEqual(self.api.storage.get_config(), {})

            self.api.storage.set_config({"api_key": "secret", "n": 3})
            self.assertEqual(
                self.api.storage.get_config(), {"api_key": "secret", "n": 3}
            )

            config_path = os.path.join(tmp_root, "fake_tool", "config.json")
            self.assertTrue(os.path.exists(config_path))
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    def test_storage_get_config_survives_corrupt_file(self):
        tmp_root = tempfile.mkdtemp(prefix="mybooks_toolbox_test_")
        try:
            self.owner.TOOL_DATA_ROOT = tmp_root
            tool_dir = os.path.join(tmp_root, "fake_tool")
            os.makedirs(tool_dir, exist_ok=True)
            with open(os.path.join(tool_dir, "config.json"), "w") as f:
                f.write("{not valid json")
            self.assertEqual(self.api.storage.get_config(), {})
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    # --- CoreAPI.db：应用数据库（Reader/Item），全新实现，绕过裸 Session 长期持有 ---

    def test_db_get_item_by_book_id_none(self):
        self.owner.session.query.return_value.filter.return_value.first.return_value = None
        self.assertIsNone(self.api.db.get_item_by_book_id(1))

    def test_db_get_item_by_book_id_found(self):
        fake_item = MagicMock(id=7, book_id=1, collector_id=2)
        self.owner.session.query.return_value.filter.return_value.first.return_value = fake_item
        result = self.api.db.get_item_by_book_id(1)
        self.assertEqual(result, {"id": 7, "book_id": 1, "collector_id": 2})

    def test_db_delete_item_by_book_id_noop_when_missing(self):
        self.owner.session.query.return_value.filter.return_value.first.return_value = None
        self.api.db.delete_item_by_book_id(1)
        self.owner.session.delete.assert_not_called()

    # --- CoreAPI.messages：新增能力，user_id 为空时是安全的 no-op ---

    def test_messages_send_message_noop_without_user_id(self):
        # 不应该抛异常，也不应该触及 session
        self.api.messages.send_message(0, "hello")
        self.api.messages.send_message(None, "hello")

    # --- CoreAPI.settings：白名单只读，不在名单内的 key 一律返回 default ---

    @patch("webserver.toolbox.core_api.loader.get_settings")
    def test_settings_get_allowed_key_reads_conf(self, mock_get_settings):
        mock_get_settings.return_value = {"auto_fill_meta": True}
        self.assertTrue(self.api.settings.get("auto_fill_meta", False))

    @patch("webserver.toolbox.core_api.loader.get_settings")
    def test_settings_get_allowed_key_missing_from_conf_uses_default(self, mock_get_settings):
        mock_get_settings.return_value = {}
        self.assertEqual(self.api.settings.get("audio_output_folder", "/fallback/"), "/fallback/")

    @patch("webserver.toolbox.core_api.loader.get_settings")
    def test_settings_get_rejects_key_outside_whitelist(self, mock_get_settings):
        # 即便 CONF 里真的有这个敏感 key，不在白名单里也不能读出来
        mock_get_settings.return_value = {"BOOKBARN_TOKEN": "super-secret"}
        self.assertEqual(self.api.settings.get("BOOKBARN_TOKEN", None), None)
        mock_get_settings.assert_not_called()


class TestUtilsAPI(unittest.TestCase):
    """CoreAPI.utils：转发 `webserver/utils.py` 的纯函数，不依赖 owner 状态。"""

    def setUp(self):
        self.owner = FakeOwner()
        self.api = CoreAPI(self.owner)

    def test_strip_trims_and_drops_unprintable(self):
        self.assertEqual(self.api.utils.strip("  hi\x00there  "), "hithere")

    @patch("webserver.utils.get_title_sort")
    def test_get_title_sort_forwards(self, mock_get_title_sort):
        mock_get_title_sort.return_value = "the matrix"
        self.assertEqual(self.api.utils.get_title_sort("The Matrix"), "the matrix")
        mock_get_title_sort.assert_called_once_with("The Matrix")

    def test_guess_title_author_from_filename_forwards(self):
        title, author = self.api.utils.guess_title_author_from_filename("《三体》作者：刘慈欣")
        self.assertEqual(title, "三体")
        self.assertEqual(author, "刘慈欣")

    def test_parse_date_forwards(self):
        result = self.api.utils.parse_date("2024-05-01")
        self.assertIsNotNone(result)
        self.assertEqual((result.year, result.month, result.day), (2024, 5, 1))
        self.assertIsNone(self.api.utils.parse_date(""))


def _install_fake_calibre_metadata_module():
    """往 sys.modules 里塞一份假的 calibre.ebooks.metadata.book.base，让
    `from calibre.ebooks.metadata.book.base import Metadata` 在没有真实 Calibre 的
    环境下也能导入——`FakeMetadata` 只记录构造参数，足够验证 `new_metadata` 的转发逻辑。
    """
    class FakeMetadata:
        def __init__(self, title, authors):
            self.title = title
            self.authors = authors

    base = types.ModuleType("calibre.ebooks.metadata.book.base")
    base.Metadata = FakeMetadata
    modules = {
        "calibre": types.ModuleType("calibre"),
        "calibre.ebooks": types.ModuleType("calibre.ebooks"),
        "calibre.ebooks.metadata": types.ModuleType("calibre.ebooks.metadata"),
        "calibre.ebooks.metadata.book": types.ModuleType("calibre.ebooks.metadata.book"),
        "calibre.ebooks.metadata.book.base": base,
    }
    return modules


class TestCalibreNewMetadata(unittest.TestCase):
    """CoreAPI.calibre.new_metadata：BookMetadata 是 Protocol，不能被实例化，真正的构造
    转发给 calibre 的 Metadata，调用方不需要自己 import calibre。"""

    def setUp(self):
        self.owner = FakeOwner()
        self.api = CoreAPI(self.owner)

    def test_new_metadata_forwards_to_calibre(self):
        with patch.dict(sys.modules, _install_fake_calibre_metadata_module()):
            mi = self.api.calibre.new_metadata("Title", ["Author A"])
        self.assertEqual(mi.title, "Title")
        self.assertEqual(mi.authors, ["Author A"])

    def test_new_metadata_defaults_authors_when_empty(self):
        with patch.dict(sys.modules, _install_fake_calibre_metadata_module()):
            mi = self.api.calibre.new_metadata("Title")
        self.assertEqual(len(mi.authors), 1)


if __name__ == "__main__":
    unittest.main()
