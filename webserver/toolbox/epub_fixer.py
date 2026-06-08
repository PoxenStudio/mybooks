"""
EPUB 修复工具

对指定书籍进行 epub→epub 强制转换，重新生成规范的 EPUB 文件并覆盖原文件，
以修复格式损坏或结构不规范的 EPUB。

@author: PoxenStudio, 2026
"""
import logging
import os
import shutil
import threading
import traceback

from webserver.i18n import _
from webserver.services import AsyncService
from webserver.toolbox.base_tool import BaseTool


class EpubFixerTool(BaseTool):
    """对指定书籍执行 epub→epub 转换以修复文件。"""

    service_item_name = "EPUB修复"

    _fix_lock = threading.Lock()

    @classmethod
    def is_running(cls) -> bool:
        acquired = cls._fix_lock.acquire(blocking=False)
        if acquired:
            cls._fix_lock.release()
            return False
        return True

    @staticmethod
    def info() -> dict:
        return {
            "tool_id": "epub_fixer",
            "name": "EPUB修复",
            "description": "对指定书籍执行 epub→epub 格式转换，重建规范的 EPUB 结构，修复损坏或格式不规范的文件",
            "revision": "0.1.0",
            "author": "MyBooks",
            "publish_date": "2026-06-09",
        }

    @AsyncService.register_service
    def fix(self, book_id: int, backup: bool, user_id: int) -> None:
        """执行 epub→epub 修复转换，通过 register_service 在后台线程中运行。

        :param book_id: Calibre 书籍 ID。
        :param backup:  是否在转换前备份原始 EPUB 文件。
        :param user_id: 操作用户 ID（记录日志用）。
        """
        if not EpubFixerTool._fix_lock.acquire(blocking=False):
            logging.warning("[EpubFixerTool] Already running, skipping fix for book_id=%d [uid:%d]", book_id, user_id)
            return

        try:
            books = self.db.get_data_as_dict(ids=[book_id])
            if not books:
                logging.error("[EpubFixerTool] Book not found: ID=%d [uid:%d]", book_id, user_id)
                return

            book = books[0]
            fmts = [f.upper() for f in (book.get("available_formats") or [])]
            if "EPUB" not in fmts:
                logging.error("[EpubFixerTool] No EPUB format for book_id=%d [uid:%d]", book_id, user_id)
                return

            epub_path = self.db.format_abspath(book_id, "EPUB", index_is_id=True)
            if not epub_path or not os.path.exists(epub_path):
                logging.error("[EpubFixerTool] EPUB file missing for book_id=%d [uid:%d]", book_id, user_id)
                return

            work_dir = self.get_work_dir(str(book_id))

            if backup:
                backup_path = os.path.join(work_dir, os.path.basename(epub_path))
                shutil.copy2(epub_path, backup_path)
                logging.info("[EpubFixerTool] Backed up epub to %s [uid:%d]", backup_path, user_id)

            fixed_path = os.path.join(work_dir, "fixed.epub")
            log_path = os.path.join(work_dir, "convert.log")

            from webserver.services.converter import ConverterService
            converter = ConverterService()
            logging.info("[EpubFixerTool] Starting epub→epub fix for book_id=%d [uid:%d]", book_id, user_id)
            ok = converter.do_ebook_convert(epub_path, fixed_path, log_path)

            if not ok:
                logging.error("[EpubFixerTool] Conversion failed for book_id=%d, log: %s", book_id, log_path)
                return

            with open(fixed_path, "rb") as f:
                self.db.add_format(book_id, "EPUB", f, index_is_id=True)
            logging.info("[EpubFixerTool] Replaced EPUB for book_id=%d [uid:%d]", book_id, user_id)

            try:
                os.remove(fixed_path)
            except Exception as err:
                logging.warning("[EpubFixerTool] Failed to remove temp file %s: %s", fixed_path, err)

            self.add_msg(user_id, "success", _(u"书籍 [%s] EPUB 修复成功！") % book.get("title", "Unknown"))
        except Exception as err:
            self.add_msg(user_id, "danger", _(u"书籍 [%s] EPUB 修复失败！") % book.get("title", "Unknown"))
            logging.error("[EpubFixerTool] Unexpected error for book_id=%d: %s", book_id, err)
            logging.error(traceback.format_exc())
        finally:
            EpubFixerTool._fix_lock.release()
