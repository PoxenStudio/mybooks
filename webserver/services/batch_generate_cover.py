#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

"""
(PoxenStudio)Dynamic Cover更新处理
"""

import logging
import time
from webserver.i18n import _

from webserver import loader
from webserver.base.cover_generator import CoverGenerator
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver.constants import CALIBRE_COLUMN_DYNAMIC_COVER, COLUMN_DYNAMIC_COVER

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

    @AsyncService.register_service
    def update_cover(self, uid, idlist: list = None):
        self.is_running = True
        self.start_time = time.time()
        self.count_done = 0
        self.count_fail = 0

        books_to_update = idlist
        if not books_to_update:
            logging.info("[DynamicCover] No books to update, exiting")
            return

        self.count_total = len(books_to_update)
        logging.info("[DynamicCover] Starting cover update for %d books", self.count_total)

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
                if mi.cover_data:
                    fmt, data = mi.cover_data
                    dynamic_cover_flag = False
                    if data:
                        custom_data = self.db.get_custom_book_data(CALIBRE_COLUMN_DYNAMIC_COVER, book_id, 0)
                        dynamic_cover_flag = int(custom_data) == 1
                        logging.info(f"[DynamicCover] Book id={book_id} already has cover data, dynamic_cover_flag={dynamic_cover_flag}")
                    if not dynamic_cover_flag and data is not None:
                        continue
                    author = mi.author_sort[0] if mi.author_sort else _("佚名")
                    data = CoverGenerator.generate_cover(mi.title, author)
                    if data:
                        mi.cover_data = ("jpeg", data)
                        logging.debug(f"[DynamicCover] Generated cover for book id={book_id}")
                        self.db.set_metadata(book_id, mi, commit=True)
                        self.db.set_custom(book_id, 1, COLUMN_DYNAMIC_COVER)
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
