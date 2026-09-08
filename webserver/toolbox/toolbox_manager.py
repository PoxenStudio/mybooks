"""
Toolbox 工具生命周期管理 —— toolbox_manager

对应 document/Toolbox_Dynamic_Design.md 第三节。M1 阶段只实现"开发者模式"这一条安装/更新
路径（本地 zip 上传，见 3.5 节），商店安装（3.4 节）留给 M5。

术语：MyBooks 里统一用"工具"（tool）指代 Toolbox 里的功能单元，不用"插件"（plugin）这个
词——`type=builtin` 是随仓库自带的工具，`type=tool` 是通过 zip 安装的非内置工具（无论
来源是商店下载还是开发者模式本地上传）。

核心模型：
- 每个工具（无论 `builtin` 还是 `tool`）在 `InstalledTool` 表里有且只有一条记录。
- `<TOOL_ROOT>/<tool_id>/` 存在与否决定这个 tool_id 是否有"覆盖产物"：
    - `type=tool` 的工具：这就是它的全部代码所在。
    - `type=builtin` 的工具：目录不存在时用仓库自带实现（`webserver/toolbox/<tool_id>.py`，
      随 `ToolSet.collect_tools()` 静态注册）；目录存在时说明被"更新"过，动态加载目录里的
      版本，优先于仓库自带实现（见 3.3 节"内置工具的更新机制"）。
- 动态 import（`importlib`）与 Tornado 路由挂载只在进程启动时的 `load_all()` 里发生一次，
  这是本文档确认的"重启生效"模型；`install_from_zip` / `enable_tool` / `disable_tool` /
  `uninstall_tool` 只改文件和 `InstalledTool` 记录，不做任何动态 import。
"""
import datetime
import importlib.util
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import zipfile
from typing import Dict, List, Optional, Set, Type

from webserver.i18n import _
from webserver.loader import get_settings
from webserver.models import InstalledTool
from webserver.toolbox.base_tool import BaseTool
from webserver.toolbox.toolset import ToolSet

CONF = get_settings()

MANIFEST_FILENAME = "manifest.json"

REQUIRED_MANIFEST_FIELDS = (
    "tool_id", "name", "description", "revision", "author",
    "core_api_version", "entry_backend", "repo_url",
)

_TOOL_ID_RE = re.compile(r"^[a-z0-9_]+$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

# tool_id -> 动态加载得到的 BaseTool 子类（外部工具，或被更新覆盖过的内置工具）
_loaded_classes: Dict[str, Type[BaseTool]] = {}
# 进程启动这次 load_all() 时，实际成功加载了覆盖产物的 tool_id 集合，用于计算 pending_restart
_loaded_at_startup: Set[str] = set()


class ToolValidationError(ValueError):
    """manifest.json / zip 包结构不合法。"""


class ToolStateError(ValueError):
    """安装/更新/启用/禁用/卸载时，当前状态不允许该操作（例如重复安装、更新不存在的工具）。"""


class ToolPermissionError(PermissionError):
    """对 builtin 工具做了只允许 tool 类型的操作（如卸载）。"""


def tool_root() -> str:
    root = CONF.get("TOOL_ROOT") or "/data/books/tools/"
    os.makedirs(root, exist_ok=True)
    return root


def _tool_dir(tool_id: str) -> str:
    return os.path.join(tool_root(), tool_id)


def has_override(tool_id: str) -> bool:
    """该 tool_id 是否在 TOOL_ROOT 下有覆盖产物（外部工具的全部代码，或内置工具的更新覆盖）。"""
    return os.path.isdir(_tool_dir(tool_id))


def _read_manifest(tool_dir: str) -> dict:
    path = os.path.join(tool_dir, MANIFEST_FILENAME)
    if not os.path.exists(path):
        raise ToolValidationError(_("zip 包缺少 manifest.json"))
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as err:
        raise ToolValidationError(_("manifest.json 不是合法的 JSON: %s") % err) from err


def validate_manifest(manifest: dict) -> None:
    """校验 manifest.json 字段，见 document/Toolbox_Dynamic_Design.md 3.2 节。"""
    missing = [f for f in REQUIRED_MANIFEST_FIELDS if not manifest.get(f)]
    if missing:
        raise ToolValidationError(_("manifest.json 缺少必填字段：%s") % "、".join(missing))

    tool_id = manifest["tool_id"]
    if not _TOOL_ID_RE.match(tool_id):
        raise ToolValidationError(_("tool_id 格式不合法：只允许小写字母、数字、下划线"))

    for field in ("revision", "core_api_version"):
        if not _SEMVER_RE.match(manifest[field]):
            raise ToolValidationError(_("%s 不是合法的语义化版本号（x.y.z）") % field)

    entry_backend = manifest["entry_backend"]
    if "." not in entry_backend:
        raise ToolValidationError(_("entry_backend 格式应为 <module>.<ClassName>"))


def _module_file_for(tool_dir: str, module_rel: str) -> str:
    return os.path.join(tool_dir, "backend", *module_rel.split(".")) + ".py"


def _semver_tuple(v: str):
    return tuple(int(p) for p in v.split("."))


def _safe_extract(zf: zipfile.ZipFile, dest_dir: str) -> None:
    """解压前校验成员路径，避免 zip slip（路径穿越）。"""
    dest_abs = os.path.abspath(dest_dir)
    for member in zf.infolist():
        member_path = os.path.abspath(os.path.join(dest_dir, member.filename))
        if not member_path.startswith(dest_abs + os.sep) and member_path != dest_abs:
            raise ToolValidationError(_("zip 包内包含非法路径：%s") % member.filename)
    zf.extractall(dest_dir)


# ---------------------------------------------------------------------------
# 安装 / 更新（3.3 / 3.5 节，M1 只支持开发者模式来源）
# ---------------------------------------------------------------------------

def install_from_zip(
    zip_path: str,
    *,
    is_update: bool,
    expected_tool_id: Optional[str] = None,
    installed_by: Optional[int] = None,
    source: str = InstalledTool.SOURCE_DEV,
) -> InstalledTool:
    """校验并把 zip 解压落盘到 TOOL_ROOT/<tool_id>/，写入/更新 InstalledTool 记录。

    只做文件系统 + 数据库操作，不做任何动态 import / 路由注册 —— 那些只在下次进程启动、
    `load_all()` 运行时才会发生（"重启生效"模型，见 3.3.1 节）。

    :param is_update: True 表示走"更新"语义（tool_id 必须已安装，builtin/tool 均可）；
                       False 表示走"安装"语义（tool_id 必须尚未安装，只能是全新的外部工具）。
    :param expected_tool_id: 更新时用于校验 manifest 里的 tool_id 与目标一致（防止传错文件）。
    :param source: 记录到 InstalledTool.source；M1 只会用到 SOURCE_DEV。
    """
    tmp_dir = tempfile.mkdtemp(prefix="mybooks_tool_install_")
    moved = False
    try:
        try:
            with zipfile.ZipFile(zip_path) as zf:
                _safe_extract(zf, tmp_dir)
        except zipfile.BadZipFile as err:
            raise ToolValidationError(_("不是合法的 zip 文件: %s") % err) from err

        manifest = _read_manifest(tmp_dir)
        validate_manifest(manifest)
        tool_id = manifest["tool_id"]

        if expected_tool_id and tool_id != expected_tool_id:
            raise ToolValidationError(
                _("manifest.json 中的 tool_id(%s) 与目标工具(%s) 不一致") % (tool_id, expected_tool_id)
            )

        module_rel, _cls_name = manifest["entry_backend"].rsplit(".", 1)
        module_file = _module_file_for(tmp_dir, module_rel)
        if not os.path.exists(module_file):
            raise ToolValidationError(_("找不到 entry_backend 指向的模块文件：backend/%s.py") % module_rel.replace(".", "/"))

        entry_frontend = manifest.get("entry_frontend")
        if entry_frontend and not os.path.exists(os.path.join(tmp_dir, "frontend", entry_frontend)):
            raise ToolValidationError(_("找不到 entry_frontend 指向的文件：frontend/%s") % entry_frontend)

        existing = InstalledTool.get(tool_id)

        if is_update:
            if not existing:
                raise ToolStateError(_("工具「%s」尚未安装，无法更新，请先安装") % tool_id)
            tool_type = existing.type
            # 开发者模式不做版本单调递增限制（3.2 节决策），商店路径的限制留给 M5。
        else:
            if existing:
                raise ToolStateError(_("工具「%s」已安装，请使用更新而不是重复安装") % tool_id)
            # 通过 install 接口新增的一律是外部工具；builtin 只能通过"更新"获得覆盖版本，
            # 不能凭空通过 install 创建（builtin 记录只在 sync_builtin_records() 里生成）。
            tool_type = InstalledTool.TYPE_TOOL

        target_dir = _tool_dir(tool_id)
        if os.path.isdir(target_dir):
            shutil.rmtree(target_dir)
        shutil.move(tmp_dir, target_dir)
        moved = True

        now = datetime.datetime.now()
        if existing:
            existing.installed_revision = manifest["revision"]
            existing.source = source
            existing.update_time = now
            existing.installed_by = installed_by
            existing.save()
            record = existing
        else:
            record = InstalledTool(
                tool_id, tool_type, source,
                installed_revision=manifest["revision"],
                enabled=True,
                installed_by=installed_by,
            )
            record.save()

        logging.info(
            "[toolbox_manager] %s tool=%s revision=%s source=%s (等待重启生效)",
            "更新" if is_update else "安装", tool_id, manifest["revision"], source,
        )
        return record
    finally:
        if not moved and os.path.isdir(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)


def enable_tool(tool_id: str) -> InstalledTool:
    record = _require_installed(tool_id)
    if record.type != InstalledTool.TYPE_TOOL:
        raise ToolPermissionError(_("内置工具不支持启用/禁用"))
    record.enabled = True
    record.update_time = datetime.datetime.now()
    record.save()
    return record


def disable_tool(tool_id: str) -> InstalledTool:
    record = _require_installed(tool_id)
    if record.type != InstalledTool.TYPE_TOOL:
        raise ToolPermissionError(_("内置工具不支持启用/禁用"))
    record.enabled = False
    record.update_time = datetime.datetime.now()
    record.save()
    return record


def uninstall_tool(tool_id: str) -> InstalledTool:
    """删除工具目录与安装记录；不清理 TOOLBOX_DATA_ROOT 下的历史数据（3.3.1 节）。
    仅允许对 type=tool 操作，builtin 抛 ToolPermissionError。"""
    record = _require_installed(tool_id)
    if record.type != InstalledTool.TYPE_TOOL:
        raise ToolPermissionError(_("内置工具不可卸载"))

    shutil.rmtree(_tool_dir(tool_id), ignore_errors=True)
    record.delete()
    logging.info("[toolbox_manager] 已卸载工具 %s（重启后彻底生效）", tool_id)
    return record


def _require_installed(tool_id: str) -> InstalledTool:
    record = InstalledTool.get(tool_id)
    if not record:
        raise ToolStateError(_("工具「%s」未安装") % tool_id)
    return record


# ---------------------------------------------------------------------------
# 启动加载（"重启生效"：动态 import + 路由挂载只在这里发生一次）
# ---------------------------------------------------------------------------

# (tool_id, module_rel) -> 已 import 的模块对象。entry_backend 和 manifest 里
# api_routes 声明的 handler 很可能落在同一个 backend/tool.py 文件里（如
# `tool.DemoTool` + `tool.SearchHandler`），如果各自单独调一次
# importlib.util.spec_from_file_location，会把同一份源码 import 成两个不同的模块对象、
# 两份不同的类定义——DemoTool 类上设置的 TOOL_SERVICE_TYPE 只会出现在 _load_tool_class()
# 这一份上，Handler 里 `from tool import DemoTool` 拿到的却是另一份，TOOL_SERVICE_TYPE
# 读回来是 None，后台任务的 service_type 就悄悄退回 SERVICE_TYPE_OTHER——这是曾经真实
# 出现过的 bug，用这个缓存保证同一个 (tool_id, module_rel) 在一次 load_all() 里只 import
# 一次、处处拿到同一个模块/同一份类对象。
_module_cache: Dict[tuple, "object"] = {}

# tool_id -> 该工具 backend/ 目录对应的 package 名（没有 backend/__init__.py 的旧工具是
# None，见 _ensure_backend_package()）。和 _module_cache 一样，只在一次 load_all() 内有效，
# 由 load_all() 负责清空。
_package_cache: Dict[str, Optional[str]] = {}


def _ensure_backend_package(tool_id: str, tool_dir: str) -> Optional[str]:
    """把工具的 backend/ 目录注册成一个真正的 Python package（sys.modules 里有对应条目、
    __path__ 指向 backend/），这样 backend/ 下多个文件之间才能用相对 import
    （`from . import job_store` / `from .job_store import JobStore`）互相引用——3.1 节的
    目录结构里 backend/ 本就带了 __init__.py，暗示了这个预期，但如果只用
    importlib.util.spec_from_file_location 单独加载 entry_backend 指向的那一个文件，
    Python 并不知道它属于哪个 package，相对 import 会直接报
    "attempted relative import with no known parent package"。

    没有 backend/__init__.py 的旧工具包（打包时没跟上这个约定）：退回成不带 package 的
    加载方式，行为和这个函数出现之前完全一致，只是不支持 backend/ 内的相对 import。
    """
    if tool_id in _package_cache:
        return _package_cache[tool_id]

    backend_dir = os.path.join(tool_dir, "backend")
    init_file = os.path.join(backend_dir, "__init__.py")
    if not os.path.exists(init_file):
        _package_cache[tool_id] = None
        return None

    package_name = f"mybooks_tool_{tool_id}_backend"
    spec = importlib.util.spec_from_file_location(
        package_name, init_file, submodule_search_locations=[backend_dir],
    )
    if spec is None or spec.loader is None:
        raise ToolValidationError(_("无法加载模块文件：%s") % init_file)
    package = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = package
    spec.loader.exec_module(package)

    _package_cache[tool_id] = package_name
    return package_name


def _import_backend_module(tool_id: str, tool_dir: str, module_rel: str):
    cache_key = (tool_id, module_rel)
    if cache_key in _module_cache:
        return _module_cache[cache_key]

    module_file = _module_file_for(tool_dir, module_rel)
    package_name = _ensure_backend_package(tool_id, tool_dir)
    module_name = (
        f"{package_name}.{module_rel}" if package_name
        else f"mybooks_tool_{tool_id}_{module_rel.replace('.', '_')}"
    )

    spec = importlib.util.spec_from_file_location(module_name, module_file)
    if spec is None or spec.loader is None:
        raise ToolValidationError(_("无法加载模块文件：%s") % module_file)
    module = importlib.util.module_from_spec(spec)
    if package_name:
        module.__package__ = package_name
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    _module_cache[cache_key] = module
    return module


def _load_tool_class(tool_id: str, tool_dir: str) -> Type[BaseTool]:
    manifest = _read_manifest(tool_dir)
    module_rel, class_name = manifest["entry_backend"].rsplit(".", 1)
    module = _import_backend_module(tool_id, tool_dir, module_rel)

    cls = getattr(module, class_name, None)
    if cls is None or not (isinstance(cls, type) and issubclass(cls, BaseTool)):
        raise ToolValidationError(_("entry_backend 指向的 %s 不是 BaseTool 的子类") % class_name)
    return cls


def sync_builtin_records() -> None:
    """确保 14 个内置工具在 InstalledTool 表里都有记录（首次启动时自动补，3.3.2 节）。"""
    ToolSet.collect_tools()
    now = datetime.datetime.now()
    for tool in ToolSet.all_tools():
        if InstalledTool.get(tool.id):
            continue
        record = InstalledTool(
            tool.id, InstalledTool.TYPE_BUILTIN, InstalledTool.SOURCE_BUNDLED,
            installed_revision=tool.revision, enabled=True,
        )
        record.install_time = now
        record.update_time = now
        record.save()


def load_all() -> None:
    """进程启动时调用一次：同步内置工具记录 + 动态加载所有有覆盖产物的工具
    （外部工具 + 被更新过的内置工具），刷新它们在 ToolSet 里的元数据。

    正常的"重启生效"模型下这个函数一个进程生命周期只跑一次，`ToolSet` 从空字典开始，不存在
    残留问题；但为了在同一进程内重复调用也是安全的（例如测试、未来可能出现的重载路径），先把
    上一次 load_all() 注册过的 tool_id 从 ToolSet 里撤销，再重新走一遍——这样如果某个工具在
    两次调用之间被卸载了，它就不会继续残留在 ToolSet 里。
    """
    for tool_id in _loaded_at_startup:
        ToolSet.unregister(tool_id)

    _loaded_classes.clear()
    _loaded_at_startup.clear()
    _module_cache.clear()
    _package_cache.clear()
    sync_builtin_records()

    for record in InstalledTool.all():
        if record.type == InstalledTool.TYPE_TOOL and not record.enabled:
            continue  # 禁用的外部工具：保留安装记录，但不加载代码、不挂路由

        tool_dir = _tool_dir(record.tool_id)
        if not os.path.isdir(tool_dir):
            if record.type == InstalledTool.TYPE_TOOL:
                logging.warning(
                    "[toolbox_manager] 已安装的工具 %s 缺少目录 %s，跳过加载", record.tool_id, tool_dir
                )
            continue  # builtin 且没有覆盖目录：沿用仓库自带实现，ToolSet 里已经有静态注册

        try:
            cls = _load_tool_class(record.tool_id, tool_dir)
        except Exception as err:
            logging.error("[toolbox_manager] 加载工具 %s 失败，跳过: %s", record.tool_id, err)
            continue

        if record.type == InstalledTool.TYPE_TOOL:
            cls.TOOL_SERVICE_TYPE = f"tool:{record.tool_id}"

        # ToolSet 的元数据来自 cls.info()（BaseTool 子类必须实现的 staticmethod），但
        # manifest.json 里 page/repo_url 这两个"打包描述"字段不要求工具作者在 info() 里
        # 重复一遍——那样两处容易改一处漏一处（tool_builder 生成的模板都会填，但手写的
        # manifest.json 未必会记得同步）。这里把 manifest.json 当兜底：只在 info() 没给出
        # 时才用 manifest 里的值补上，不覆盖 info() 已经给出的值。
        try:
            manifest = _read_manifest(tool_dir)
        except ToolValidationError:
            manifest = {}
        info = cls.info()
        for field in ("page", "repo_url"):
            if not info.get(field) and manifest.get(field):
                info[field] = manifest[field]

        ToolSet.register(info)
        _loaded_classes[record.tool_id] = cls
        _loaded_at_startup.add(record.tool_id)

    logging.info(
        "[toolbox_manager] load_all() 完成：%d 个工具带覆盖产物被加载 (%s)",
        len(_loaded_at_startup), ", ".join(sorted(_loaded_at_startup)) or "无",
    )


def get_tool_class(tool_id: str) -> Optional[Type[BaseTool]]:
    """返回动态加载得到的 BaseTool 子类（仅对有覆盖产物的工具有效）。"""
    return _loaded_classes.get(tool_id)


def is_tool_enabled(tool_id: str) -> bool:
    record = InstalledTool.get(tool_id)
    return bool(record and record.enabled)


def is_pending_restart(tool_id: str) -> bool:
    """磁盘上有覆盖产物、但进程这次启动时没有加载它 —— 说明是安装/更新/卸载发生在本次
    进程启动之后，需要重启才能生效。"""
    return has_override(tool_id) and tool_id not in _loaded_at_startup


def tool_state(tool_id: str) -> Optional[dict]:
    """供 /api/toolbox/list 拼接 type/source/status/pending_restart 字段，见 3.3.1 节。

    返回 None 表示这个 tool_id 已经没有 InstalledTool 记录——只会发生在"外部工具被卸载，
    但进程还没有重启、ToolSet 里的静态注册还没清掉"这个空档期，调用方（AdminToolList）应该
    把这种工具从列表里剔除，而不是回退展示成 builtin：3.3.1 节明确要求"工具已经从
    /api/toolbox/list 消失"，展示成来源错误的 builtin 元数据比直接不显示更容易误导管理员。
    builtin 工具不会走到这个分支——sync_builtin_records() 在 load_all() 里已经保证它们
    都有记录。
    """
    record = InstalledTool.get(tool_id)
    if not record:
        return None
    return {
        "type": record.type,
        "source": record.source,
        "status": "enabled" if record.enabled else "disabled",
        "pending_restart": is_pending_restart(tool_id),
    }


# ---------------------------------------------------------------------------
# 自定义路由（3.6 节）
# ---------------------------------------------------------------------------

def _wrap_with_enabled_check(handler_cls, tool_id: str):
    """包一层 prepare()，请求到达时检查该工具是否仍处于启用状态（禁用立即生效，3.3.1 节）。"""

    def prepare(self):
        if not is_tool_enabled(tool_id):
            self.set_status(404)
            self.finish({"err": "tool.disabled", "msg": _("工具未启用或不存在")})
            return
        super(wrapped, self).prepare()

    wrapped = type(f"{handler_cls.__name__}_{tool_id}", (handler_cls,), {"prepare": prepare})
    return wrapped


def collect_tool_routes() -> List[tuple]:
    """从每个已加载工具的 manifest.json 里读取可选的 api_routes 声明，动态挂载路由。
    只在 load_all() 之后调用一次（main.py 启动时的路由拼接阶段），见 3.6 节。"""
    routes = []
    for tool_id, _cls in _loaded_classes.items():
        tool_dir = _tool_dir(tool_id)
        try:
            manifest = _read_manifest(tool_dir)
        except ToolValidationError:
            continue

        for entry in manifest.get("api_routes", []):
            path = entry.get("path")
            handler_name = entry.get("handler")
            if not path or not handler_name:
                logging.warning("[toolbox_manager] %s 的 api_routes 声明不完整，跳过：%s", tool_id, entry)
                continue
            module_rel, handler_cls_name = handler_name.rsplit(".", 1)
            try:
                # 复用 _import_backend_module() 的缓存：handler 常常和 entry_backend 同在
                # 一个模块文件里（如 tool.DemoTool + tool.PingHandler），必须拿到同一个模块
                # 对象、同一份类定义，否则 entry_backend 类上设置的 TOOL_SERVICE_TYPE 类
                # 属性对 handler 里实例化出来的对象不可见（曾经真实触发过的 bug）。
                module = _import_backend_module(tool_id, tool_dir, module_rel)
                handler_cls = getattr(module, handler_cls_name)
            except Exception as err:
                logging.error("[toolbox_manager] 加载 %s 的自定义路由 handler 失败: %s", tool_id, err)
                continue

            wrapped = _wrap_with_enabled_check(handler_cls, tool_id)
            route_path = rf"/api/toolbox/tool/{re.escape(tool_id)}/{path.lstrip('/')}"
            routes.append((route_path, wrapped))

    return routes
