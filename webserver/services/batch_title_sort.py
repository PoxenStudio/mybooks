#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import logging
import time
from webserver.i18n import _

from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver import utils


class BatchTitleSortUpdateService(AsyncService):
    """批量更新title_sort为拼音排序的服务"""

    def __init__(self):
        self.count_total = 0
        self.count_skip = 0
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
            "count_skip": self.count_skip,
            "count_done": self.count_done,
            "count_fail": self.count_fail,
            "task_id": self.task_id,
        }

    def _update_one_book(self, book_id: int):
        logging.debug("[TitleSort] Updating book id=%d", book_id)
        try:
            mi = self.db.get_metadata(book_id, index_is_id=True)
            if not mi:
                self.count_skip += 1
                logging.debug("[TitleSort] Book id=%d not found, skipping", book_id)
                return

            logging.debug("[TitleSort] Current title: '%s', current title_sort: '%s'", mi.title, mi.title_sort)
            title = mi.title
            new_sort = utils.get_title_sort(title)
            if new_sort == mi.title_sort:
                self.count_skip += 1
                logging.debug("[TitleSort] Book id=%d title_sort is already up-to-date, skipping", book_id)
                return

            logging.debug("[TitleSort] [%d] New title_sort: '%s'", book_id, new_sort)
            mi.title_sort = new_sort
            self.db.set_metadata(book_id, mi, commit=True)
            self.count_done += 1
            logging.debug("[TitleSort] Updated book id=%d", book_id)
        except Exception as e:
            logging.error("[TitleSort] Failed to update book id=%d: %s", book_id, e)
            self.count_fail += 1

    @AsyncService.register_service
    def update_all(self, user_id, idlist: list):
        self.is_running = True
        self.start_time = time.time()
        self.count_skip = 0
        self.count_done = 0
        self.count_fail = 0

        logging.info("[TitleSort] Starting batch title_sort update task")
        self.add_msg(user_id, "success", _(u"更新书名信息任务已启动"))
        books_to_update = idlist if idlist else list(self.db.all_book_ids())
        self.count_total = len(books_to_update)
        logging.info("[TitleSort] Total books to process: %d", self.count_total)

        try:
            task = BackgroundService().update_task(
                service_type=BackgroundTask.SERVICE_TYPE_TITLE_SORT_UPDATE,
                service_item=_("更新书名信息"),
                progress=0,
                progress_data={
                    "total": self.count_total,
                    "done": 0,
                    "fail": 0,
                },
            )
            self.task_id = task.id
        except Exception as e:
            logging.error("[TitleSort] Failed to create background task: %s", e)
            self.task_id = None

        index = 0
        for book_id in books_to_update:
            logging.debug("[TitleSort] Processing book id=%d (%d/%d)", book_id, index + 1, self.count_total)
            self.current_book_id = book_id
            self._update_one_book(book_id)
            if index % 10 == 0:
                self._update_task_progress()
            index += 1
        logging.debug("[TitleSort] All books processed, succeed:%d, skipped:%d, failed:%d", self.count_done, self.count_skip, self.count_fail)

        self._update_task_progress()
        self._finish_task()
        msg = _(u"更新书名信息任务已完成，成功更新%d本书，%d本书更新失败, %d本书被跳过" % (self.count_done, self.count_fail, self.count_skip))
        if self.count_fail > 0:
            self.add_msg(user_id, "warning", msg)
        else:
            self.add_msg(user_id, "success", msg)

        self.is_running = False
        self.current_book_id = None
        self.task_id = None

    def _update_task_progress(self):
        """更新后台任务进度"""
        if not self.task_id:
            return
        try:
            processed = self.count_done + self.count_skip + self.count_fail
            progress = int(processed * 100 / self.count_total) if self.count_total else 100
            BackgroundService().update_progress(
                task_id=self.task_id,
                progress=progress,
                progress_data={
                    "total": self.count_total,
                    "done": self.count_done + self.count_skip,
                    "fail": self.count_fail,
                    "current_book_id": self.current_book_id,
                },
            )
        except Exception as e:
            logging.error("[TitleSort] Failed to update task progress: %s", e)

    def _finish_task(self, failed: bool = False, error_msg: str = ""):
        if not self.task_id:
            return
        try:
            BackgroundService().complete_task(
                task_id=self.task_id,
                error_message=error_msg if failed else None,
            )
        except Exception as e:
            logging.error("[TitleSort] Failed to finish task: %s", e)
