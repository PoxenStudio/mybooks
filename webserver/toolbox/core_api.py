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
- `CoreAPI.utils`     —— 通用文本/日期处理，转发 `webserver/utils.py` 里的纯函数

`BookMetadata`（本文件顶部）是 `CoreAPI.calibre.get_metadata`/`set_metadata`/`import_book`
用到的"书籍元数据"类型契约——一份结构化子类型（`typing.Protocol`）声明，不是重新实现的
类：运行时仍是原生 Calibre `Metadata` 实例，工具作者只需要
`from webserver.toolbox.core_api import BookMetadata` 做类型标注，不需要
`import calibre`。详见该类的 docstring。
"""
import json
import logging
import os
import datetime
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

from webserver import loader
from webserver.base.formatter import SimpleBookFormatter
from webserver.base.global_state import get_global_state
from webserver.i18n import _

# Core API 的语义化版本号，工具 manifest.json 里的 core_api_version 据此做兼容性检查
CORE_API_VERSION = "1.3.0"


class _NamespaceBase:
    """各命名空间的公共基类：持有对宿主 BaseTool 实例的引用。

    不在 __init__ 时缓存 owner.db / owner.session ——它们是在每次
    `@AsyncService.register_service` 调用时才被重新赋值的（见
    `webserver/services/async_service.py` 的 `register_service`），所以这里的方法都要
    在被调用的那一刻才去读 `self._owner.db` / `self._owner.session`，不能提前缓存。
    """

    def __init__(self, owner):
        self._owner = owner


@runtime_checkable
class BookMetadata(Protocol):
    """`CoreAPI.calibre` 里"书籍元数据"这个概念的类型契约，结构对齐
    `calibre.ebooks.metadata.book.base.Metadata`，但只是一份 :pep:`544` 结构化子类型
    （`typing.Protocol`）声明，不是一个真正的实现类：

    - 运行时该方法实际传递/返回的**仍然是原本那个 Calibre `Metadata` 实例**，没有做任何
      字段搬运/复制/转换——这里只是给它一个不挂 `calibre.*` 模块路径的类型名，工具作者
      写 `from webserver.toolbox.core_api import BookMetadata` 做类型标注/IDE 补全即可，
      不需要（也不应该）直接 `import calibre`。
    - 之所以不用一个全新的 dataclass/普通类重新定义再互相转换：Calibre `Metadata` 本身是
      一个通过 `__getattr__`/`__setattr__` 代理到内部 `_data` 字典的动态对象（支持任意
      `#custom_column` 键、`is_null()`/`deepcopy()` 等一整套语义），重新定义一份等价类会
      需要在两边手动同步字段列表、还要写一次容易出 bug 的双向转换，维护成本远高于这里
      "只声明用得到的结构子集"的做法；Protocol 是纯静态类型层面的东西，没有任何运行时
      开销，也不会在 `isinstance()` 时误判（`@runtime_checkable` 只检查方法/属性是否存在，
      不检查类型）。
    - 只列出 Core API 实际用得到、值得对外承诺的字段；不在这份列表里的字段/自定义列，
      仍然可以通过下面的 `get(field, default)` 读到——这也是真实 `Metadata.get()` 的原样
      转发，行为与直接用 Calibre 的 `Metadata` 一致。
    """

    title: str
    title_sort: str
    authors: List[str]
    author_sort: str
    tags: List[str]
    comments: Optional[str]
    series: Optional[str]
    series_index: Optional[float]
    publisher: Optional[str]
    pubdate: Optional[datetime.datetime]
    languages: List[str]
    identifiers: Dict[str, str]
    rating: Optional[float]
    uuid: str

    def get(self, field: str, default: Any = None) -> Any:
        """读取任意字段（包括不在上面列表里的自定义列，如 `#mytags`），不存在时返回 default。"""
        ...

    def set(self, field: str, val: Any, extra: Any = None) -> None:
        """写入任意字段，`extra` 语义与 Calibre 原生 `Metadata.set()` 一致（如系列索引）。"""
        ...

    def is_null(self, field: str) -> bool:
        """判断某字段是否为"空值"（Calibre 对不同字段类型有各自的空值约定）。"""
        ...


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

    def new_metadata(self, title: str, authors: Optional[List[str]] = None) -> BookMetadata:
        """构造一个新的元数据对象（常见于"生成新书"场景，配合 `import_book` 使用）。

        `BookMetadata` 只是类型契约，Protocol 本身不能被实例化——这个方法把真正的构造逻辑
        （即 `calibre.ebooks.metadata.book.base.Metadata(title, authors)`）收在这里，
        调用方因此不需要自己 `import calibre`。
        """
        from calibre.ebooks.metadata.book.base import Metadata
        return Metadata(title, authors or [_("未知作者")])

    def get_metadata(self, book_id: int, get_cover: bool = False, cover_as_data: bool = False) -> BookMetadata:
        """返回指定书籍的元数据对象（类型见 `BookMetadata`）；`get_cover`/`cover_as_data` 透传给 Calibre。"""
        if not get_cover and not cover_as_data:
            return self._owner.get_book_metadata(book_id)
        return self._owner.db.get_metadata(
            book_id, index_is_id=True, get_cover=get_cover, cover_as_data=cover_as_data
        )

    def set_metadata(self, book_id: int, mi: BookMetadata, force_changes: bool = True) -> None:
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

    def import_book(self, mi: BookMetadata, formats: List[str]) -> Optional[int]:
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


class UtilsAPI(_NamespaceBase):
    """通用文本/日期处理，纯函数转发给 `webserver/utils.py`，不依赖宿主 `BaseTool` 的状态。"""

    def strip(self, s: str) -> str:
        """去除首尾空白，并过滤掉其余不可打印字符，转发 `webserver.utils.super_strip`。"""
        from webserver.utils import super_strip
        return super_strip(s)

    def get_title_sort(self, title: str) -> str:
        """把书名转成用于排序的 ASCII 小写形式，转发 `webserver.utils.get_title_sort`。"""
        from webserver.utils import get_title_sort
        return get_title_sort(title)

    def guess_title_author_from_filename(self, name: str):
        """从"《书名》作者：xxx"这类文件名里拆出 `(title, author)`。"""
        from webserver.utils import guess_title_author_from_filename
        return guess_title_author_from_filename(name)

    def parse_date(self, date_str: str):
        """按常见格式（含中文"年月日"）解析日期字符串，失败返回 `None`。"""
        from webserver.utils import parse_date
        return parse_date(date_str)


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
        self.utils = UtilsAPI(owner)
