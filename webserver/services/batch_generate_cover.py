#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

"""
(PoxenStudio)Dynamic Cover更新处理
"""

import logging
import os
import time
from webserver.i18n import _

from webserver import loader
from webserver.base.cover_generator import CoverGenerator
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver.constants import COLUMN_DYNAMIC_COVER

CONF = loader.get_settings()


class DynamicCoverUpdateService(AsyncService):

    def __init__(self):
        self.count_total = 0
        self.count_done = 0
        self.count_fail = 0
        self.is_running = False
        self.current_book_id = None
        self.start_time = None
        self.task_id = None
        AsyncService.__init__(self)

    def status(self):
        return {
            "is_running": self.is_running,
            "current_book_id": self.current_book_id,
            "start_time": self.start_time,
            "count_total": self.count_total,
            "count_done": self.count_done,
            "count_fail": self.count_fail,
            "task_id": self.task_id,
        }

    def _update_task_progress(self):
        if not self.task_id:
            return
        try:
            processed = self.count_done + self.count_fail
            progress = int(processed * 100 / self.count_total) if self.count_total else 100
            BackgroundService().update_progress(
                task_id=self.task_id,
                progress=progress,
                progress_data={
                    "total": self.count_total,
                    "done": self.count_done,
                    "fail": self.count_fail,
                    "current_book_id": self.current_book_id,
                },
            )
        except Exception as e:
            logging.error("[DynamicCover] Failed to update task progress: %s", e)

    def _generate_dynamic_cover(self, book_id, mi):
        """使用 CoverGenerator 为书籍生成动态封面"""
        author = mi.author_sort[0] if mi.author_sort else _("佚名")
        data = CoverGenerator.generate_cover(mi.title, author)
        if data:
            mi.cover_data = ("jpeg", data)
            self.db.set_metadata(book_id, mi, commit=True)
            self.db.set_custom(book_id, 1, COLUMN_DYNAMIC_COVER)
            logging.debug(f"[DynamicCover] Generated dynamic cover for book id={book_id}")
            return True
        return False

    def _extract_file_cover(self, book_id, mi):
        """从书籍文件中提取内置封面"""
        from calibre.ebooks.metadata.meta import get_metadata

        books = self.db.get_data_as_dict(ids=[book_id])
        if not books:
            logging.warning(f"[DynamicCover] Book id={book_id} not found in db")
            return False
        book = books[0]

        book_path = None
        for fmt in ["epub", "mobi", "azw", "azw3", "pdf"]:
            book_path = book.get(f"fmt_{fmt}", None)
            if book_path:
                break

        if not book_path:
            logging.warning(f"[DynamicCover] No supported book file found for book id={book_id}")
            return False

        book_name = os.path.basename(book_path)
        ext = os.path.splitext(book_name)[1]
        file_fmt = ext[1:].lower() if ext else None
        if not file_fmt:
            return False

        try:
            with open(book_path, "rb") as stream:
                file_mi = get_metadata(stream, stream_type=file_fmt, use_libprs_metadata=True)
            if file_mi.cover_data:
                cover_fmt, cover_data = file_mi.cover_data
                if cover_data:
                    mi.cover_data = (cover_fmt or "jpeg", cover_data)
                    self.db.set_metadata(book_id, mi, commit=True)
                    self.db.set_custom(book_id, 0, COLUMN_DYNAMIC_COVER)
                    logging.debug(f"[DynamicCover] Extracted file cover for book id={book_id}")
                    return True
        except Exception as e:
            logging.error(f"[DynamicCover] Failed to extract file cover for book id={book_id}: {e}")

        return False

    @AsyncService.register_service
    def update_cover(self, uid, idlist: list = None, dynamic_cover=True):
        self.is_running = True
        self.start_time = time.time()
        self.count_done = 0
        self.count_fail = 0

        books_to_update = idlist
        if not books_to_update:
            logging.info("[DynamicCover] No books to update, exiting")
            return

        self.count_total = len(books_to_update)
        logging.info("[DynamicCover] Starting cover update for %d books，dynamic_cover=%s", self.count_total, dynamic_cover)

        try:
            task = BackgroundService().update_task(
                service_type=BackgroundTask.SERVICE_TYPE_COVER_UPDATE,
                service_item="更新图书封面",
                progress=0,
                progress_data={
                    "total": self.count_total,
                    "done": 0,
                    "fail": 0,
                },
            )
            self.task_id = task.id
        except Exception as e:
            logging.error("[DynamicCover] Failed to create background task: %s", e)
            self.task_id = None

        for index, book_id in enumerate(books_to_update):
            self.current_book_id = book_id
            try:
                mi = self.db.get_metadata(book_id, index_is_id=True, get_cover=True)
                self.count_done += 1
                if mi is None:
                    continue
                if mi.cover:
                    dynamic_cover_flag = False
                    custom_data = self.db.get_custom(book_id, label=COLUMN_DYNAMIC_COVER, index_is_id=True)
                    dynamic_cover_flag = custom_data == 1
                    logging.info(f"[DynamicCover] Book id={book_id} already has cover data, dynamic_cover_flag={dynamic_cover_flag}")
                    if dynamic_cover and not dynamic_cover_flag:
                        continue
                if dynamic_cover:
                    self._generate_dynamic_cover(book_id, mi)
                else:
                    self._extract_file_cover(book_id, mi)
                logging.debug("[DynamicCover] Updated book id=%d (%d/%d)", book_id, index + 1, self.count_total)
            except Exception as e:
                self.count_fail += 1
                logging.error("[DynamicCover] Failed to update book id=%d: %s", book_id, e)

            if (index + 1) % 100 == 0:
                self._update_task_progress()

        self._update_task_progress()

        if self.task_id:
            try:
                BackgroundService().complete_task(task_id=self.task_id)
                self.add_msg(
                    user_id=uid,
                    status="success",
                    msg=_("图书封面更新完成: 共%d本，成功%d本)") % (self.count_total, self.count_done))
            except Exception as e:
                logging.error("[DynamicCover] Failed to complete task: %s", e)

        logging.info(
            "[DynamicCover] Completed: total=%d, done=%d, fail=%d, elapsed=%.1fs",
            self.count_total, self.count_done, self.count_fail, time.time() - self.start_time,
        )

        # 发送消息通知用户更新完成
        self.add_msg(
            user_id=uid,
            status="success",
            msg=_("图书封面更新完成: 共%d本，成功%d本，失败%d本") % (self.count_total, self.count_done, self.count_fail),
        )

        self.is_running = False
        self.current_book_id = None
        self.task_id = None
