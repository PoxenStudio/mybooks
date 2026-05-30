"""
工具类基类 — BaseTool

所有 Toolbox 工具都应继承此类，以复用后台任务管理、文件入库、
工作目录管理等通用基础设施，让子类只需关注自身的业务逻辑。

子类必须提供：
    service_item_name (str)  : 后台任务面板中显示的任务名称
    info()           (static): 返回工具元数据 dict，格式见 BaseTool.info()
"""
import hashlib
import logging
import os
import shutil
from typing import Callable, List, Optional

from webserver.i18n import _
from webserver.models import Item
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask


class BaseTool(AsyncService):
    """Toolbox 工具基类。"""

    # 子类必须覆盖：后台任务面板中显示的任务名称（会经过 i18n 处理）
    service_item_name: str = ""

    # 工具数据根目录；子类可覆盖
    TOOL_DATA_ROOT: str = "/data/toolbox"

    # 支持的入库文件格式
    SUPPORTED_FORMATS = {"epub", "pdf", "azw3", "mobi", "txt"}

    @staticmethod
    def info() -> dict:
        """返回工具元数据，子类必须实现。
        返回示例::

            {
                "tool_id":      "my_tool",
                "name":         "My Tool",
                "description":  "...",
                "revision":     "1.0.0",
                "author":       "Author",
                "publish_date": "2025-01-01",
            }
        """
        raise NotImplementedError("Subclass must implement info()")

    @classmethod
    def tool_id(cls) -> str:
        """从 info() 中读取工具唯一标识符。"""
        return cls.info()["tool_id"]

    # 工作目录

    def get_work_dir(self, unique_key: str) -> str:
        """返回并创建该任务专属的工作目录。

        路径规则：``TOOL_DATA_ROOT/<tool_id>/<md5(unique_key)[:16]>``

        :param unique_key: 任意字符串（URL、任务参数等），用于生成唯一子目录。
        """
        if unique_key:
            key_hash = hashlib.md5(unique_key.encode()).hexdigest()[:16]
            work_dir = os.path.join(self.TOOL_DATA_ROOT, self.tool_id(), key_hash)
        else:
            work_dir = os.path.join(self.TOOL_DATA_ROOT, self.tool_id())
        os.makedirs(work_dir, exist_ok=True)
        return work_dir

    def cleanup_work_dir(self, work_dir: str) -> None:
        """递归删除工作目录，失败时仅记录警告，不向上抛出异常。"""
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
            logging.info("[%s] Removed work dir: %s", self.__class__.__name__, work_dir)
        except Exception as err:
            logging.warning(
                "[%s] Failed to remove work dir %s: %s",
                self.__class__.__name__, work_dir, err,
            )

    # 后台任务生命周期

    def create_task(self, progress_data: Optional[dict] = None) -> int:
        """创建一个新的后台任务并返回 task_id。

        任务名称取自 :attr:`service_item_name`，子类未设置时抛出 ``NotImplementedError``。
        """
        if not self.service_item_name:
            raise NotImplementedError(
                f"{self.__class__.__name__} must define service_item_name"
            )
        task = BackgroundService().update_task(
            service_type=BackgroundTask.SERVICE_TYPE_OTHER,
            service_item=_(self.service_item_name),
            progress=0,
            progress_data=progress_data or {},
        )
        return task.id

    def update_task_progress(
        self,
        task_id: int,
        progress: int,
        progress_data: Optional[dict] = None,
    ) -> None:
        """更新后台任务进度（0-100）。"""
        BackgroundService().update_progress(
            task_id=task_id,
            progress=progress,
            progress_data=progress_data or {},
        )

    def complete_task(
        self, task_id: int, error_message: Optional[str] = None
    ) -> None:
        """将后台任务标记为完成或失败。

        :param error_message: 非 None 时任务被标记为失败，并附带错误描述。
        """
        BackgroundService().complete_task(task_id, error_message=error_message)

    def make_progress_callback(
        self,
        task_id: int,
        progress_data_factory: Optional[Callable[[int], dict]] = None,
        outer_callback: Optional[Callable[[int], None]] = None,
    ) -> Callable[[int], None]:
        """构造标准进度回调函数，消除子类中重复的样板代码。

        :param task_id:               后台任务 ID。
        :param progress_data_factory: 可选工厂函数，接收 progress(int) 返回 dict。
        :param outer_callback:        可选，外层调用者的额外回调。
        :return: ``(progress: int) -> None`` 的回调函数。
        """
        def _callback(progress: int) -> None:
            data = progress_data_factory(progress) if progress_data_factory else {}
            self.update_task_progress(task_id, progress, data)
            if outer_callback:
                outer_callback(progress)

        return _callback

    # 文件入库

    def import_file(
        self,
        user_id: int,
        file_path: str,
        title: str,
        authors: List[str],
        *,
        delete_after_import: bool = True,
    ) -> int:
        """将本地文件导入 Calibre 书库，并创建对应的 Item 记录。

        :param user_id:             入库操作关联的用户 ID。
        :param file_path:           待入库文件的绝对路径。
        :param title:               书名（将被自动 strip 处理）。
        :param authors:             作者列表（每项将被自动 strip 处理）。
        :param delete_after_import: 入库成功后是否删除源文件，默认 True。
        :return:                    Calibre book_id。
        :raises RuntimeError:       格式不支持、Calibre 入库失败等。
        """
        from calibre.ebooks.metadata.meta import get_metadata
        from calibre.ebooks.metadata.book.base import Metadata
        from webserver import utils

        fmt = file_path.rsplit(".", 1)[-1].lower()
        if fmt not in self.SUPPORTED_FORMATS:
            raise RuntimeError(_("不支持的文件格式：%s") % fmt)

        clean_title = utils.super_strip(title)
        clean_authors = [utils.super_strip(a) for a in authors]

        try:
            with open(file_path, "rb") as stream:
                mi = get_metadata(stream, stream_type=fmt, use_libprs_metadata=True)
            mi.title = clean_title or utils.super_strip(mi.title)
            mi.authors = clean_authors or [utils.super_strip(a) for a in mi.authors]
        except Exception as err:
            logging.warning(
                "[%s] Failed to read metadata from %s: %s",
                self.__class__.__name__, file_path, err,
            )
            mi = Metadata(clean_title, clean_authors)

        mi.title_sort = utils.get_title_sort(mi.title)

        logging.info("[%s] Importing file: %s", self.__class__.__name__, file_path)
        try:
            book_id = self.db.import_book(mi, [file_path])
        except Exception as err:
            logging.error(
                "[%s] import_book failed for %s: %s",
                self.__class__.__name__, file_path, err,
            )
            raise RuntimeError(_("导入文件失败")) from err

        if book_id is None:
            raise RuntimeError(_("导入文件失败，Calibre未返回书籍ID"))

        try:
            item = Item()
            item.book_id = book_id
            item.collector_id = user_id
            item.save()
        except Exception as err:
            logging.error(
                "[%s] Failed to create Item record for book_id=%s: %s",
                self.__class__.__name__, book_id, err,
            )

        if delete_after_import:
            try:
                os.remove(file_path)
                logging.info("[%s] Deleted source file: %s", self.__class__.__name__, file_path)
            except Exception as err:
                logging.warning(
                    "[%s] Failed to delete source file %s: %s",
                    self.__class__.__name__, file_path, err,
                )
        return book_id

    def merge_book_formats(self, source_book_id: int, target_book_id: int) -> list:
        """将 source 书籍的所有格式文件复制到 target 书籍，返回新增的格式列表。

        仅复制 target 书籍中尚不存在的格式，不覆盖已有格式。

        :param source_book_id: 格式来源书籍 ID（合并后将被删除）。
        :param target_book_id: 格式目标书籍 ID（保留）。
        :return:               成功添加的格式名称列表（大写），例如 ``["MOBI", "AZW3"]``。
        :raises RuntimeError:  书籍不存在或没有可合并的新格式时抛出。
        """
        src_books = self.db.get_data_as_dict(ids=[source_book_id])
        tgt_books = self.db.get_data_as_dict(ids=[target_book_id])
        if not src_books:
            raise RuntimeError(_("来源书籍不存在: ID=%d") % source_book_id)
        if not tgt_books:
            raise RuntimeError(_("目标书籍不存在: ID=%d") % target_book_id)

        src_book = src_books[0]
        tgt_book = tgt_books[0]

        src_fmts = set(f.upper() for f in (src_book.get("available_formats") or []))
        tgt_fmts = set(f.upper() for f in (tgt_book.get("available_formats") or []))
        new_fmts = src_fmts - tgt_fmts

        if not new_fmts:
            raise RuntimeError(_("来源书籍没有目标书籍中缺少的格式，无需合并"))

        added = []
        for fmt in new_fmts:
            fpath = self.db.format_abspath(source_book_id, fmt, index_is_id=True)
            if not fpath or not os.path.exists(fpath):
                logging.warning(
                    "[%s] format file not found: book_id=%d fmt=%s",
                    self.__class__.__name__, source_book_id, fmt,
                )
                continue
            try:
                self.db.add_format(target_book_id, fmt, fpath, index_is_id=True)
                added.append(fmt)
                logging.info(
                    "[%s] Copied format %s from book %d to %d",
                    self.__class__.__name__, fmt, source_book_id, target_book_id,
                )
            except Exception as err:
                logging.error(
                    "[%s] Failed to add format %s to book %d: %s",
                    self.__class__.__name__, fmt, target_book_id, err,
                )

        return added

    def delete_book_by_id(self, book_id: int) -> None:
        """从 Calibre 书库及 Item 表中删除指定书籍。

        :param book_id: 要删除的书籍 ID。
        :raises RuntimeError: 删除失败时抛出。
        """
        try:
            item = self.session.query(Item).filter(Item.book_id == book_id).first()
            if item:
                self.session.delete(item)
                self.session.commit()
        except Exception as err:
            logging.warning(
                "[%s] Failed to delete Item for book_id=%d: %s",
                self.__class__.__name__, book_id, err,
            )
        try:
            self.db.delete_book(book_id)
            logging.info("[%s] Deleted book_id=%d", self.__class__.__name__, book_id)
        except Exception as err:
            logging.error(
                "[%s] Failed to delete book_id=%d from Calibre: %s",
                self.__class__.__name__, book_id, err,
            )
            raise RuntimeError(_("删除书籍失败: %s") % str(err)) from err

    # 遍历书籍相关操作

    def get_all_book_ids(self) -> List[int]:
        """返回书库中所有书籍的 ID 列表（已排序）。"""
        ids = list(self.db.new_api.all_book_ids())
        ids.sort()
        return ids

    def get_book_metadata(self, book_id: int):
        """返回指定书籍的 Calibre Metadata 对象。

        :param book_id: Calibre 书籍 ID。
        :return: calibre.ebooks.metadata.book.base.Metadata 对象。
        """
        return self.db.get_metadata(book_id, index_is_id=True)

    def set_book_language(self, book_id: int, language: str) -> None:
        """将指定书籍的语言字段更新为给定语言代码。

        :param book_id:  Calibre 书籍 ID。
        :param language: 语言代码（例如 "zha"、"zh"、"en"）。
        """
        mi = self.get_book_metadata(book_id)
        mi.languages = language
        self.db.set_metadata(book_id, mi, force_changes=True)
        logging.info(
            "[%s] Set language of book_id=%d to %s",
            self.__class__.__name__, book_id, language,
        )
