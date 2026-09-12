# -*- coding: utf-8 -*-
"""toolbox_manager 集成测试（M1 验收标准的自动化版本）。

覆盖 document/Toolbox_Dynamic_Design.md 第三节 + 第八节 M1 milestone 描述的整条链路：

    打包 zip -> 开发者模式安装 -> "重启"(重新调用 load_all()) 生效 -> 出现在 ToolSet /
    service_type 带 tool:<tool_id> 前缀 -> 禁用立即生效（不需要重启）-> 卸载后重启彻底清除

以及 builtin 工具的"更新覆盖"路径（3.3 节）。

用轻量内存 SQLite（与 tests/test_reading_stats_flush.py 同一模式）+ 临时目录当
TOOL_ROOT，不依赖 tests/test_main.py 里那套完整的 Calibre 测试库 fixture。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import models
from webserver.loader import get_settings
from webserver.models import InstalledTool
from webserver.toolbox import toolbox_manager
from webserver.toolbox.toolset import ToolSet

CONF = get_settings()

# ToolSet.collect_tools() 会真的 import 全部 14 个内置工具模块，其中几个（text_replace /
# book_utils 等）顶层 import calibre.ebooks.*，需要 webserver.main.init_calibre() 先把真实
# Calibre 安装路径塞进 sys.path 才能用（见 webserver/main.py）。这不是 toolbox_manager 自身
# 的逻辑，本测试文件只关心 toolbox_manager 对"已注册工具"的处理是否正确，所以把
# ToolSet.collect_tools() 替换成注册两个假 builtin 工具，绕开真实 Calibre 依赖 —— 与
# tests/test_text_replace_core.py 对 webserver 依赖的 stub 思路一致。
_FAKE_BUILTIN_TOOLS = (
    {
        "tool_id": "merge_formats_tool", "name": "格式合并", "description": "...",
        "revision": "0.1.0", "author": "PoxenStudio",
    },
    {
        "tool_id": "rare_book_downloader", "name": "古书下载器", "description": "...",
        "revision": "0.1.0", "author": "PoxenStudio",
    },
)


def _fake_collect_tools():
    for info in _FAKE_BUILTIN_TOOLS:
        ToolSet.register(info)


DEMO_BACKEND_SRC = '''
from webserver.toolbox.base_tool import BaseTool
from webserver.services import AsyncService
from webserver.handlers.base import BaseHandler, js


class DemoTool(BaseTool):
    service_item_name = "Demo Tool Task"

    @staticmethod
    def info():
        return {{
            "tool_id": "{tool_id}",
            "name": "Demo Tool",
            "description": "A demo external tool for tests",
            "revision": "{revision}",
            "author": "Tester",
            "publish_date": "2026-01-01",
            "repo_url": "https://example.com/{tool_id}",
        }}

    @AsyncService.register_function
    def ping(self):
        task_id = self.api.tasks.create_task(progress_data={{"stage": "ping"}})
        self.api.tasks.complete_task(task_id)
        return "pong"


# manifest 里 api_routes 声明的自定义 handler，和上面的工具类同在一个文件里——这是工具作者
# 最自然的写法，也是曾经触发过"两次 import 出两个不同类对象"这个 bug 的具体场景，见
# test_collect_tool_routes_shares_module_with_entry_backend()。
class PingHandler(BaseHandler):
    @js
    def get(self):
        return {{"err": "ok", "msg": DemoTool().ping()}}
'''


def _build_demo_tool_src(tool_id="demo_tool", revision="1.0.0", entry_backend="tool.DemoTool", extra_manifest=None):
    """在临时目录里搭建一个符合 3.1 节结构的工具源码树，返回源码目录路径（调用方负责打包）。"""
    src_dir = tempfile.mkdtemp(prefix="mybooks_demo_tool_src_")
    manifest = {
        "tool_id": tool_id,
        "name": "Demo Tool",
        "description": "A demo external tool for tests",
        "revision": revision,
        "author": "Tester",
        "publish_date": "2026-01-01",
        "core_api_version": "1.0.0",
        "entry_backend": entry_backend,
        "entry_frontend": "index.html",
        "page": tool_id,
        "repo_url": f"https://example.com/{tool_id}",
    }
    if extra_manifest:
        manifest.update(extra_manifest)

    with open(os.path.join(src_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)

    backend_dir = os.path.join(src_dir, "backend")
    os.makedirs(backend_dir, exist_ok=True)
    open(os.path.join(backend_dir, "__init__.py"), "w").close()
    with open(os.path.join(backend_dir, "tool.py"), "w", encoding="utf-8") as f:
        class_name = entry_backend.rsplit(".", 1)[-1]
        code = DEMO_BACKEND_SRC.format(tool_id=tool_id, revision=revision)
        # 连带 PingHandler 里 `DemoTool()` 的引用一起改名，保持类名 <-> 引用一致
        code = code.replace("DemoTool", class_name)
        f.write(code)

    frontend_dir = os.path.join(src_dir, "frontend")
    os.makedirs(frontend_dir, exist_ok=True)
    with open(os.path.join(frontend_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write("<html><body>demo</body></html>")

    return src_dir


def _write_demo_tool(tool_id="demo_tool", revision="1.0.0", entry_backend="tool.DemoTool", extra_manifest=None):
    """搭建一个符合 3.1 节结构的工具源码树，打成 zip，返回 zip 路径。"""
    src_dir = _build_demo_tool_src(tool_id, revision, entry_backend, extra_manifest)
    zip_path = os.path.join(tempfile.mkdtemp(prefix="mybooks_demo_tool_zip_"), f"{tool_id}-{revision}.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        for root, _dirs, files in os.walk(src_dir):
            for name in files:
                abs_path = os.path.join(root, name)
                rel_path = os.path.relpath(abs_path, src_dir)
                zf.write(abs_path, rel_path)

    shutil.rmtree(src_dir, ignore_errors=True)
    return zip_path


def _write_demo_tool_7z(tool_id="demo_tool", revision="1.0.0", entry_backend="tool.DemoTool", extra_manifest=None):
    """搭建同样的工具源码树，打成 7z（覆盖 `_extract_archive` 的 7z 分支），返回 7z 路径。"""
    import py7zr  # 惰性 import：只有这个测试需要，py7zr 不是必装依赖时其它测试不受影响

    src_dir = _build_demo_tool_src(tool_id, revision, entry_backend, extra_manifest)
    archive_path = os.path.join(tempfile.mkdtemp(prefix="mybooks_demo_tool_7z_"), f"{tool_id}-{revision}.7z")
    with py7zr.SevenZipFile(archive_path, "w") as archive:
        for root, _dirs, files in os.walk(src_dir):
            for name in files:
                abs_path = os.path.join(root, name)
                rel_path = os.path.relpath(abs_path, src_dir)
                archive.write(abs_path, rel_path)

    shutil.rmtree(src_dir, ignore_errors=True)
    return archive_path


class TestToolboxManager(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)

        self._tool_root = tempfile.mkdtemp(prefix="mybooks_tool_root_")
        self._orig_tool_root = CONF.get("TOOL_ROOT")
        CONF["TOOL_ROOT"] = self._tool_root

        # 模块级状态，测试间要重置，避免互相污染
        ToolSet._tool_set.clear()
        toolbox_manager._loaded_classes.clear()
        toolbox_manager._loaded_at_startup.clear()

        self._collect_tools_patcher = patch.object(ToolSet, "collect_tools", side_effect=_fake_collect_tools)
        self._collect_tools_patcher.start()

        self._tmp_files = []

    def tearDown(self):
        self._collect_tools_patcher.stop()
        self.session.remove()
        shutil.rmtree(self._tool_root, ignore_errors=True)
        if self._orig_tool_root is not None:
            CONF["TOOL_ROOT"] = self._orig_tool_root
        for path in self._tmp_files:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)
        ToolSet._tool_set.clear()
        toolbox_manager._loaded_classes.clear()
        toolbox_manager._loaded_at_startup.clear()

    def _install(self, **kwargs):
        zip_path = _write_demo_tool(**kwargs)
        self._tmp_files.append(zip_path)
        return zip_path

    # ---- 安装（全新外部工具）----

    def test_install_new_tool_creates_record_and_dir(self):
        zip_path = self._install(tool_id="demo_tool")
        record = toolbox_manager.install_from_zip(zip_path, is_update=False, installed_by=1)

        self.assertEqual(record.type, InstalledTool.TYPE_TOOL)
        self.assertEqual(record.source, InstalledTool.SOURCE_DEV)
        self.assertEqual(record.installed_revision, "1.0.0")
        self.assertTrue(record.enabled)
        self.assertTrue(os.path.isdir(toolbox_manager._tool_dir("demo_tool")))
        self.assertIsNotNone(InstalledTool.get("demo_tool"))

    def test_install_new_tool_from_7z_package(self):
        """商店/开发者模式下，7z 包（按文件头识别，不看文件名后缀）应该和 zip 包一样能装成功。"""
        try:
            import py7zr  # noqa: F401
        except ImportError:
            self.skipTest("py7zr 未安装，跳过 7z 安装包测试")

        archive_path = _write_demo_tool_7z(tool_id="demo_tool_7z")
        self._tmp_files.append(archive_path)
        record = toolbox_manager.install_from_zip(archive_path, is_update=False, installed_by=1)

        self.assertEqual(record.type, InstalledTool.TYPE_TOOL)
        self.assertEqual(record.installed_revision, "1.0.0")
        self.assertTrue(os.path.isdir(toolbox_manager._tool_dir("demo_tool_7z")))
        self.assertIsNotNone(InstalledTool.get("demo_tool_7z"))

    def test_install_rejects_unknown_archive_format(self):
        garbage_path = os.path.join(tempfile.mkdtemp(prefix="mybooks_garbage_"), "not_an_archive.zip")
        with open(garbage_path, "wb") as f:
            f.write(b"this is not a zip or 7z file")
        self._tmp_files.append(garbage_path)

        with self.assertRaises(toolbox_manager.ToolValidationError):
            toolbox_manager.install_from_zip(garbage_path, is_update=False)

    def test_install_duplicate_tool_id_rejected(self):
        zip_path = self._install(tool_id="demo_tool")
        toolbox_manager.install_from_zip(zip_path, is_update=False)
        with self.assertRaises(toolbox_manager.ToolStateError):
            toolbox_manager.install_from_zip(zip_path, is_update=False)

    def test_update_nonexistent_tool_rejected(self):
        zip_path = self._install(tool_id="never_installed")
        with self.assertRaises(toolbox_manager.ToolStateError):
            toolbox_manager.install_from_zip(zip_path, is_update=True, expected_tool_id="never_installed")

    def test_update_tool_id_mismatch_rejected(self):
        zip_path = self._install(tool_id="demo_tool")
        toolbox_manager.install_from_zip(zip_path, is_update=False)
        with self.assertRaises(toolbox_manager.ToolValidationError):
            toolbox_manager.install_from_zip(zip_path, is_update=True, expected_tool_id="some_other_tool")

    def test_validate_manifest_missing_fields(self):
        with self.assertRaises(toolbox_manager.ToolValidationError):
            toolbox_manager.validate_manifest({"tool_id": "x"})

    def test_zip_slip_is_rejected(self):
        # 构造一个内含路径穿越条目的恶意 zip
        evil_zip = os.path.join(tempfile.mkdtemp(prefix="mybooks_evil_zip_"), "evil.zip")
        with zipfile.ZipFile(evil_zip, "w") as zf:
            zf.writestr("../../etc/evil.txt", "pwned")
        self._tmp_files.append(evil_zip)
        with self.assertRaises(toolbox_manager.ToolValidationError):
            toolbox_manager.install_from_zip(evil_zip, is_update=False)

    # ---- 重启生效：load_all() ----

    def test_load_all_registers_tool_with_service_type_prefix(self):
        zip_path = self._install(tool_id="demo_tool")
        toolbox_manager.install_from_zip(zip_path, is_update=False)

        # 模拟进程重启：重新调用 load_all()
        toolbox_manager.load_all()

        tool = ToolSet.get_tool("demo_tool")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.name, "Demo Tool")

        cls = toolbox_manager.get_tool_class("demo_tool")
        self.assertIsNotNone(cls)
        self.assertEqual(cls.TOOL_SERVICE_TYPE, "tool:demo_tool")

        # 回归测试：真实容器里用 tool_builder 生成的包做验证时发现的 bug —— manifest.json
        # 里的 page 字段（DEMO_BACKEND_SRC 的 info() 故意没有返回它，模拟大多数工具作者会
        # 忘记在两处重复同一个字段的情况）之前会被 cls.info() 的返回值直接覆盖掉，
        # ToolSet 里最终拿到空字符串。load_all() 现在会用 manifest.json 兜底补上。
        self.assertEqual(tool.page, "demo_tool")

        state = toolbox_manager.tool_state("demo_tool")
        self.assertEqual(state["type"], "tool")
        self.assertEqual(state["status"], "enabled")
        self.assertFalse(state["pending_restart"])

    def test_collect_tool_routes_shares_module_with_entry_backend(self):
        # 回归测试：曾经真实发生过的 bug——entry_backend 和 manifest 里 api_routes 声明的
        # handler 同在一个 backend/tool.py 文件里时，如果各自单独 import 了一次，会得到两个
        # 不同的模块对象、两份不同的 DemoTool 类定义，handler 里 `DemoTool()` 实例化出来的
        # 对象读不到 load_all() 设在"另一份" DemoTool 类上的 TOOL_SERVICE_TYPE，
        # 表现为后台任务面板的 service_type 悄悄退回 "other"。在真实容器里用一个带自定义
        # api_routes 的 demo 工具手工验证时发现的，见对话记录。
        zip_path = self._install(
            tool_id="demo_tool",
            extra_manifest={"api_routes": [{"path": "ping", "handler": "tool.PingHandler"}]},
        )
        toolbox_manager.install_from_zip(zip_path, is_update=False)
        toolbox_manager.load_all()

        routes = toolbox_manager.collect_tool_routes()
        self.assertEqual(len(routes), 1)
        route_path, wrapped_handler_cls = routes[0]
        self.assertEqual(route_path, "/api/toolbox/tool/demo_tool/ping")

        real_handler_cls = wrapped_handler_cls.__bases__[0]
        handler_module = sys.modules[real_handler_cls.__module__]
        tool_cls_seen_by_handler = getattr(handler_module, "DemoTool")

        entry_cls = toolbox_manager.get_tool_class("demo_tool")
        self.assertIs(
            tool_cls_seen_by_handler, entry_cls,
            "handler 模块里的 DemoTool 必须和 entry_backend 解析出来的是同一个类对象，"
            "否则 TOOL_SERVICE_TYPE 对 handler 不可见",
        )
        self.assertEqual(entry_cls.TOOL_SERVICE_TYPE, "tool:demo_tool")

    def test_pending_restart_before_next_load_all(self):
        zip_path = self._install(tool_id="demo_tool")
        toolbox_manager.install_from_zip(zip_path, is_update=False)
        # 还没有"重启"（没有调用 load_all()）：装了但还没生效
        self.assertTrue(toolbox_manager.is_pending_restart("demo_tool"))

        toolbox_manager.load_all()
        self.assertFalse(toolbox_manager.is_pending_restart("demo_tool"))

    # ---- 启用 / 禁用：立即生效，不需要重启 ----

    def test_disable_takes_effect_without_reload(self):
        zip_path = self._install(tool_id="demo_tool")
        toolbox_manager.install_from_zip(zip_path, is_update=False)
        toolbox_manager.load_all()

        toolbox_manager.disable_tool("demo_tool")
        self.assertFalse(toolbox_manager.is_tool_enabled("demo_tool"))
        self.assertEqual(toolbox_manager.tool_state("demo_tool")["status"], "disabled")

        toolbox_manager.enable_tool("demo_tool")
        self.assertTrue(toolbox_manager.is_tool_enabled("demo_tool"))

    def test_disable_enable_rejected_for_builtin(self):
        toolbox_manager.sync_builtin_records()
        builtin_id = ToolSet.all_tools()[0].id
        with self.assertRaises(toolbox_manager.ToolPermissionError):
            toolbox_manager.disable_tool(builtin_id)
        with self.assertRaises(toolbox_manager.ToolPermissionError):
            toolbox_manager.enable_tool(builtin_id)

    # ---- 卸载：仅 type=tool，重启后彻底清除 ----

    def test_uninstall_removes_dir_and_record(self):
        zip_path = self._install(tool_id="demo_tool")
        toolbox_manager.install_from_zip(zip_path, is_update=False)
        toolbox_manager.load_all()

        toolbox_manager.uninstall_tool("demo_tool")
        self.assertIsNone(InstalledTool.get("demo_tool"))
        self.assertFalse(os.path.isdir(toolbox_manager._tool_dir("demo_tool")))

        # 卸载后重新"重启"：ToolSet 里也不再有它
        toolbox_manager.load_all()
        self.assertIsNone(ToolSet.get_tool("demo_tool"))

    def test_tool_state_none_after_uninstall_before_restart(self):
        # 回归测试：真实容器里手工验证时发现的 bug——卸载后、重启前这段空档期，
        # tool_state() 之前会兜底回退成 type=builtin/source=bundled，AdminToolList 因此会
        # 展示一条来源被错误标注的记录，而不是按 3.3.1 节要求的"立即从列表消失"。
        zip_path = self._install(tool_id="demo_tool")
        toolbox_manager.install_from_zip(zip_path, is_update=False)
        toolbox_manager.load_all()

        toolbox_manager.uninstall_tool("demo_tool")
        # ToolSet 里的静态注册还在（要等下次 load_all()/"重启"才清掉），
        # 但 InstalledTool 记录已经没了，tool_state() 必须能表达"应该被隐藏"
        self.assertIsNotNone(ToolSet.get_tool("demo_tool"))
        self.assertIsNone(toolbox_manager.tool_state("demo_tool"))

    def test_uninstall_rejected_for_builtin(self):
        toolbox_manager.sync_builtin_records()
        builtin_id = ToolSet.all_tools()[0].id
        with self.assertRaises(toolbox_manager.ToolPermissionError):
            toolbox_manager.uninstall_tool(builtin_id)

    # ---- builtin 工具的更新覆盖机制（3.3 节）----

    def test_builtin_update_overrides_repo_implementation(self):
        toolbox_manager.sync_builtin_records()
        builtin_id = "merge_formats_tool"
        self.assertIsNotNone(InstalledTool.get(builtin_id))
        self.assertEqual(InstalledTool.get(builtin_id).type, InstalledTool.TYPE_BUILTIN)

        zip_path = self._install(
            tool_id=builtin_id, revision="9.9.9", entry_backend="tool.MergeFormatsOverride"
        )
        record = toolbox_manager.install_from_zip(zip_path, is_update=True, expected_tool_id=builtin_id)
        self.assertEqual(record.type, InstalledTool.TYPE_BUILTIN)  # type 不因为走了 update 而改变
        self.assertEqual(record.source, InstalledTool.SOURCE_DEV)
        self.assertEqual(record.installed_revision, "9.9.9")

        toolbox_manager.load_all()

        cls = toolbox_manager.get_tool_class(builtin_id)
        self.assertIsNotNone(cls)
        self.assertEqual(cls.__name__, "MergeFormatsOverride")
        # builtin 即使被更新覆盖，也不使用 tool: 前缀（2.2 节决策，只有 type=tool 才前缀）
        self.assertIsNone(cls.TOOL_SERVICE_TYPE)

        tool = ToolSet.get_tool(builtin_id)
        self.assertEqual(tool.revision, "9.9.9")

    def test_builtin_records_synced_on_first_load(self):
        toolbox_manager.load_all()
        installed = {r.tool_id: r for r in InstalledTool.all()}
        # 至少覆盖几个已知的内置工具，全部 14 个逐一断言太啰嗦
        for tool_id in ("merge_formats_tool", "rare_book_downloader"):
            self.assertIn(tool_id, installed)
            self.assertEqual(installed[tool_id].type, InstalledTool.TYPE_BUILTIN)
            self.assertEqual(installed[tool_id].source, InstalledTool.SOURCE_BUNDLED)
            self.assertTrue(installed[tool_id].enabled)


if __name__ == "__main__":
    unittest.main()
