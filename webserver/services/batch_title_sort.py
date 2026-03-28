#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import logging
import time
from gettext import gettext as _

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

    def _collect_books_to_update(self, idlist: list) -> list:
        """收集需要更新title_sort的书籍列表"""
        books_to_update = []

        if not idlist:
            all_book_ids = list(self.db.all_book_ids())
            logging.info("[BatchTitleSort] Scanning all %d books", len(all_book_ids))
        else:
            all_book_ids = idlist
            logging.info("[BatchTitleSort] Scanning %d specified books", len(all_book_ids))

        for book_id in all_book_ids:
            try:
                mi = self.db.get_metadata(book_id, index_is_id=True)
                if not mi:
                    continue
                title = mi.title
                if not title:
                    continue
                books_to_update.append((book_id, title))
            except Exception as e:
                logging.error("[BatchTitleSort] Failed to check book id=%d: %s", book_id, e)

        logging.info("[BatchTitleSort] Found %d books needing title_sort update", len(books_to_update))
        return books_to_update

    def _update_one_book(self, book_id: int, title: str) -> bool:
        try:
            new_sort = utils.get_title_sort(title)
            mi = self.db.get_metadata(book_id, index_is_id=True)
            if not mi:
                return False
            mi.title_sort = new_sort
            self.db.set_metadata(book_id, mi, commit=True)
            logging.info("[BatchTitleSort] Updated book id=%d title_sort: %r -> %r", book_id, title, new_sort)
            return True
        except Exception as e:
            logging.error("[BatchTitleSort] Failed to update book id=%d: %s", book_id, e)
            return False

    @AsyncService.register_service
    def update_all(self, user_id, idlist: list):
        self.is_running = True
        self.start_time = time.time()
        self.count_skip = 0
        self.count_done = 0
        self.count_fail = 0

        logging.info("[BatchTitleSort] Starting batch title_sort update task")
        self.add_msg(user_id, "success", _(u"更新书名信息任务已启动"))
        books_to_update = self._collect_books_to_update(idlist)
        self.count_total = len(books_to_update)

        if self.count_total == 0:
            logging.info("[BatchTitleSort] No books need title_sort update")
            self.is_running = False
            self.add_msg(user_id, "success", _(u"更新书名信息任务已结束，未找到需要更新的书籍"))
            return

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
            logging.error("[BatchTitleSort] Failed to create background task: %s", e)
            self.task_id = None

        for book_id, title in books_to_update:
            self.current_book_id = book_id
            ok = self._update_one_book(book_id, title)
            if ok:
                self.count_done += 1
            else:
                self.count_fail += 1
            self._update_task_progress()

        self._finish_task()
        msg = _(u"更新书名信息任务已完成，成功更新%d本书，%d本书更新失败" % (self.count_done, self.count_fail))
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
            logging.error("[BatchTitleSort] Failed to update task progress: %s", e)

    def _finish_task(self, failed: bool = False, error_msg: str = ""):
        if not self.task_id:
            return
        try:
            BackgroundService().complete_task(
                task_id=self.task_id,
                error_message=error_msg if failed else None,
            )
        except Exception as e:
            logging.error("[BatchTitleSort] Failed to finish task: %s", e)
