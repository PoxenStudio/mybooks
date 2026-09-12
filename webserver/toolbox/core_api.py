"""
Toolbox Core API 层
@author: PoxenStudio, 2026-8

给工具（无论是内置工具还是未来的外部插件）提供一份版本化、语义化的接口，把工具代码与
Calibre / SQLAlchemy 的内部实现细节解耦。设计背景见
`document/Toolbox_Dynamic_Design.md` 第二节。

`CoreAPI` 挂在 `BaseTool.api` 上（`BaseTool.__init__` 里构造），按命名空间划分：

- `CoreAPI.calibre`  —— Calibre 书库读写
- `CoreAPI.db`        —— 应用 SQLAlchemy 模型读写（Reader / Item）
- `CoreAPI.tasks`     —— 后台任务生命周期
- `CoreAPI.messages`  —— 站内消息
- `CoreAPI.storage`   —— 工具专属数据目录 + 持久配置
- `CoreAPI.settings`  —— 系统配置只读白名单（`SettingsAPI.ALLOWED_KEYS`）

M0 阶段只做接口收敛，不改变现有 14 个内置工具的行为：凡是 `BaseTool` 已有对应方法
的（`import_file`、`merge_book_formats`、`delete_book_by_id`、`get_all_book_ids`、
`get_book_metadata`、`set_book_language`、`get_work_dir`、`cleanup_work_dir`、
`create_task`、`update_task_progress`、`complete_task`、`make_progress_callback`），
`CoreAPI` 里对应的方法只是薄封装、原样转发给 `BaseTool` 的实现，单一实现来源仍在
`base_tool.py`，避免出现两份逻辑分叉。`BaseTool` 目前没有的能力
（`search_books`/`search_ids`、`set_metadata`、`add_format`、`format_abspath`、
`get_data_as_dict`、`cover`、`import_book`、`get_custom`/`set_custom`、`remove_formats`、
应用数据库的 `get_item_by_book_id`/`create_item`/`delete_item_by_book_id`/`get_reader`、
站内消息、持久配置）在这里给出新实现——其中 `get_data_as_dict`/`cover`/`import_book`/
`get_custom`/`set_custom`/`remove_formats` 是 M4（迁移剩余内置工具）阶段按各工具的实际
用法补齐的，直接转发给 Calibre `legacy` DB / `new_api`，不经过 `BaseTool`。

`base_tool.py` 与本文件是 Core API 的唯一实现来源，允许直接访问 `owner.db`/
`owner.session`；`webserver/toolbox/` 下的其余文件（各工具类、`book_utils.py` 等）一律
通过 `self.api.*`／`tool.api.*` 访问，不直接触碰 `self.db`/`self.session`
（`document/Toolbox_Dynamic_Design.md` 第八节 M4 的验收标准）。
"""
import json
import logging
import os
from typing import Callable, List, Optional

from webserver import loader
from webserver.base.formatter import SimpleBookFormatter
from webserver.base.global_state import get_global_state
from webserver.i18n import _

# Core API 的语义化版本号，工具 manifest.json 里的 core_api_version 据此做兼容性检查
# （见 document/Toolbox_Dynamic_Design.md 2.3 节）。新增向后兼容的能力（如新命名空间/新方法）
# bump 次版本号；破坏兼容性的改动 bump 主版本号。1.1.0：新增 CoreAPI.settings 命名空间。
CORE_API_VERSION = "1.1.0"


class _NamespaceBase:
    """各命名空间的公共基类：持有对宿主 BaseTool 实例的引用。

    不在 __init__ 时缓存 owner.db / owner.session ——它们是在每次
    `@AsyncService.register_service` 调用时才被重新赋值的（见
    `webserver/services/async_service.py` 的 `register_service`），所以这里的方法都要
    在被调用的那一刻才去读 `self._owner.db` / `self._owner.session`，不能提前缓存。
    """

    def __init__(self, owner):
        self._owner = owner


class CalibreAPI(_NamespaceBase):
    """Calibre 书库访问。"""

    def search_books(self, query: str, max_results: int = 20, include_comments: bool = False) -> List[dict]:
        """按 Calibre 搜索语法查询书籍，返回 dict 列表（含 id/title/authors/formats 等字段）。"""
        ids = list(self._owner.db.new_api.search(query))[:max_results]
        if not ids:
            return []
        books = self._owner.db.get_data_as_dict(ids=ids)
        cdn_url = get_global_state().cdn_url
        return [SimpleBookFormatter(b, cdn_url).format(include_comments) for b in books]

    def get_metadata(self, book_id: int, get_cover: bool = False, cover_as_data: bool = False):
        """返回指定书籍的 Calibre Metadata 对象；`get_cover`/`cover_as_data` 透传给 Calibre。"""
        if not get_cover and not cover_as_data:
            return self._owner.get_book_metadata(book_id)
        return self._owner.db.get_metadata(
            book_id, index_is_id=True, get_cover=get_cover, cover_as_data=cover_as_data
        )

    def set_metadata(self, book_id: int, mi, force_changes: bool = True) -> None:
        """写回书籍元数据。"""
        self._owner.db.set_metadata(book_id, mi, force_changes=force_changes)

    def get_data_as_dict(self, ids: List[int]) -> List[dict]:
        """按 book_id 列表批量返回书籍 dict（含 available_formats/title 等字段）。"""
        return self._owner.db.get_data_as_dict(ids=ids)

    def cover(self, book_id: int) -> Optional[bytes]:
        """返回书籍封面的原始字节，没有封面时返回 None。"""
        return self._owner.db.cover(book_id, index_is_id=True)

    def set_cover(self, book_id: int, cover: bytes) -> None:
        """设置书籍封面。"""
        self._owner.db.set_cover(book_id, cover)

    def import_book(self, mi, formats: List[str]) -> Optional[int]:
        """将本地格式文件与给定元数据一并入库，返回新书的 book_id。"""
        return self._owner.db.import_book(mi, formats)

    def search_ids(self, query: str) -> List[int]:
        """按 Calibre 搜索语法查询书籍，返回排序后的 book_id 列表（不取详情）。"""
        return sorted(self._owner.db.new_api.search(query))

    def get_custom(self, book_id: int, label: str):
        """读取自定义列的值。"""
        return self._owner.db.get_custom(book_id, label=label, index_is_id=True)

    def set_custom(self, label: str, values: dict) -> None:
        """批量写入自定义列的值，`values` 为 `{book_id: value}`。"""
        self._owner.db.new_api.set_field(label, values)

    def remove_formats(self, values: dict) -> None:
        """批量删除格式文件，`values` 为 `{book_id: [fmt, ...]}`。"""
        self._owner.db.new_api.remove_formats(values)

    def set_language(self, book_id: int, language: str) -> None:
        self._owner.set_book_language(book_id, language)

    def all_book_ids(self) -> List[int]:
        return self._owner.get_all_book_ids()

    def import_file(
        self,
        user_id: int,
        file_path: str,
        title: str,
        authors: List[str],
        *,
        delete_after_import: bool = True,
    ) -> int:
        return self._owner.import_file(
            user_id, file_path, title, authors, delete_after_import=delete_after_import
        )

    def merge_formats(self, source_book_id: int, target_book_id: int) -> list:
        return self._owner.merge_book_formats(source_book_id, target_book_id)

    def add_format(self, book_id: int, fmt: str, file_path: str) -> None:
        self._owner.db.add_format(book_id, fmt, file_path, index_is_id=True)

    def format_abspath(self, book_id: int, fmt: str) -> Optional[str]:
        return self._owner.db.format_abspath(book_id, fmt, index_is_id=True)

    def delete_book(self, book_id: int) -> None:
        self._owner.delete_book_by_id(book_id)


class AppDBAPI(_NamespaceBase):
    """应用数据库访问（Reader / Item），不暴露裸的 SQLAlchemy Session。"""

    def get_item_by_book_id(self, book_id: int) -> Optional[dict]:
        from webserver.models import Item

        item = self._owner.session.query(Item).filter(Item.book_id == book_id).first()
        if not item:
            return None
        return {
            "id": item.id,
            "book_id": item.book_id,
            "collector_id": item.collector_id,
        }

    def create_item(self, book_id: int, collector_id: int) -> dict:
        from webserver.models import Item

        item = Item()
        item.book_id = book_id
        item.collector_id = collector_id
        item.save()
        return {"id": item.id, "book_id": item.book_id, "collector_id": item.collector_id}

    def delete_item_by_book_id(self, book_id: int) -> None:
        from webserver.models import Item

        item = self._owner.session.query(Item).filter(Item.book_id == book_id).first()
        if item:
            self._owner.session.delete(item)
            self._owner.session.commit()

    def get_reader(self, user_id: int) -> Optional[dict]:
        from webserver.models import Reader

        reader = self._owner.session.query(Reader).filter(Reader.id == user_id).first()
        if not reader:
            return None
        return {
            "id": reader.id,
            "username": reader.username,
            "name": reader.name,
            "admin": reader.admin,
        }


class TasksAPI(_NamespaceBase):
    """后台任务生命周期，转发给 `BaseTool` 现有实现（不改变行为）。"""

    def create_task(self, progress_data: Optional[dict] = None) -> int:
        return self._owner.create_task(progress_data=progress_data)

    def update_progress(
        self, task_id: int, progress: int, progress_data: Optional[dict] = None
    ) -> None:
        self._owner.update_task_progress(task_id, progress, progress_data=progress_data)

    def complete_task(self, task_id: int, error_message: Optional[str] = None) -> None:
        self._owner.complete_task(task_id, error_message=error_message)

    def make_progress_callback(
        self,
        task_id: int,
        progress_data_factory: Optional[Callable[[int], dict]] = None,
        outer_callback: Optional[Callable[[int], None]] = None,
    ) -> Callable[[int], None]:
        return self._owner.make_progress_callback(
            task_id,
            progress_data_factory=progress_data_factory,
            outer_callback=outer_callback,
        )


class MessagesAPI(_NamespaceBase):
    """站内消息（`Message` 模型封装），供工具在后台任务之外再发一条持久化通知。"""

    def send_message(self, user_id: int, msg: str, status: str = "info") -> None:
        """给用户发一条站内信，等同于 `AsyncService.add_msg` 的逻辑。"""
        from webserver.models import Message

        if not user_id:
            return
        Message.cleanup_messages(user_id, msg)
        m = Message(user_id, status, msg)
        m.save()

    def cleanup_messages(self, user_id: int, msg_content: str, days: int = 31) -> int:
        from webserver.models import Message

        return Message.cleanup_messages(user_id, msg_content, days=days)


class StorageAPI(_NamespaceBase):
    """工具专属数据目录 + 持久配置。"""

    CONFIG_FILENAME = "config.json"

    def get_work_dir(self, unique_key: Optional[str] = None) -> str:
        return self._owner.get_work_dir(unique_key)

    def cleanup_work_dir(self, work_dir: str) -> None:
        self._owner.cleanup_work_dir(work_dir)

    def _config_path(self) -> str:
        tool_dir = os.path.join(self._owner.TOOL_DATA_ROOT, self._owner.tool_id())
        os.makedirs(tool_dir, exist_ok=True)
        return os.path.join(tool_dir, self.CONFIG_FILENAME)

    def get_config(self) -> dict:
        path = self._config_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as err:
            logging.warning("[CoreAPI.storage] Failed to read config %s: %s", path, err)
            return {}

    def set_config(self, data: dict) -> None:
        path = self._config_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as err:
            logging.error("[CoreAPI.storage] Failed to write config %s: %s", path, err)
            raise RuntimeError(_("保存工具配置失败")) from err


class SettingsAPI(_NamespaceBase):
    """系统配置只读访问，White-list 制——`webserver.settings`/`auto.py`/`manual.py`
    合并后的 `CONF` 里混有数据库连接串、各种第三方 API key/token 等敏感项，不能整份透出
    给工具（尤其是未来的外部工具），所以这里只允许读 `ALLOWED_KEYS` 里显式登记过的
    非敏感只读配置项，不在名单里的 key 一律返回调用方传入的 `default`。

    需要新增可读配置项时，把 key 加进 `ALLOWED_KEYS` 并在后面的注释里写清楚这一项
    为什么可以放行；不要为了方便某个工具就放开整份 `CONF`。
    """

    # key -> 一句话说明为什么这项配置可以只读透出给工具
    ALLOWED_KEYS = {
        "auto_fill_meta": "是否自动补全导入书籍的元数据，纯行为开关，不含敏感信息",
        "audio_output_folder": "音频类工具的输出目录路径，本地文件系统路径，不含敏感信息",
        "DEFAULT_LANGUAGE": "站点默认语言，用于工具自行做多语言展示的兜底",
    }

    def get(self, key: str, default=None):
        """读取一项白名单内的系统配置；不在白名单内的 key 直接返回 default，不抛异常。"""
        if key not in self.ALLOWED_KEYS:
            logging.warning("[CoreAPI.settings] Key %r not in ALLOWED_KEYS, returning default", key)
            return default
        return loader.get_settings().get(key, default)


class CoreAPI:
    """按命名空间聚合的 Core API 入口，`BaseTool.__init__` 里构造一次并挂在 `self.api`。"""

    VERSION = CORE_API_VERSION

    def __init__(self, owner):
        self.calibre = CalibreAPI(owner)
        self.db = AppDBAPI(owner)
        self.tasks = TasksAPI(owner)
        self.messages = MessagesAPI(owner)
        self.storage = StorageAPI(owner)
        self.settings = SettingsAPI(owner)
