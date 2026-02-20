#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import logging
import time
from gettext import gettext as _

from webserver import loader
from webserver.assistant.book_ai_client import AIBookInfo, BookAIClient
from webserver.constants import CALIBRE_COLUMN_CATEGORY
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask

CONF = loader.get_settings()


class AIFillInfoService(AsyncService):
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

    def _make_client(self) -> BookAIClient:
        return BookAIClient()

    def _apply_ai_info(self, book_id: int, mi, info: AIBookInfo) -> bool:
        try:
            if info.tags:
                mi.tags = info.tags
            if info.comments:
                mi.comments = info.comments
            if info.category:
                mi.set(CALIBRE_COLUMN_CATEGORY, info.category)

            self.db.set_metadata(book_id, mi, ignore_errors=True)
            if info.category:
                try:
                    self.db.new_api.set_field(CALIBRE_COLUMN_CATEGORY, {book_id: info.category})
                except Exception as cache_err:
                    logging.warning(
                        "[AIFill] Failed to update category cache for id=%d: %s",
                        book_id,
                        cache_err,
                    )

            logging.info(
                "[AIFill] Updated book id=%d: category=%s, tags=%s",
                book_id,
                info.category,
                info.tags,
            )
            return True
        except Exception as e:
            logging.error("[AIFill] Failed to write metadata for id=%d: %s", book_id, e)
            return False

    def _should_skip(self, mi) -> bool:
        # 如果作者是空的或者为Unknown或佚名，则认为信息不完整，为避免误判跳过处理
        return not mi.authors or str(mi.authors[0]).strip() in ["", "Unknown", "佚名", "未知"]

    @AsyncService.register_function
    def fill_one(self, book_id: int, force: bool = False) -> dict:
        try:
            mi = self.db.get_metadata(book_id, index_is_id=True)
        except Exception as e:
            msg = _("读取书籍元数据失败 id=%d: %s") % (book_id, e)
            logging.error("[AIFill] %s", msg)
            return {"status": "fail", "msg": msg}

        if not force and self._should_skip(mi):
            logging.info("[AIFill] Skip book id=%d (already has complete info)", book_id)
            return {"status": "skip", "msg": _("图书已有完整信息，跳过更新")}

        try:
            client = self._make_client()
        except ValueError as e:
            return {"status": "fail", "msg": str(e)}

        authors = list(mi.authors) if mi.authors else []
        info = client.get_book_info(
            title=mi.title,
            authors=authors,
            isbn=mi.isbn or ""
        )

        if info is None or not info.is_valid():
            msg = _("AI 未能返回有效信息，book id=%d") % book_id
            logging.warning("[AIFill] %s", msg)
            return {"status": "fail", "msg": msg}

        ok = self._apply_ai_info(book_id, mi, info)
        if ok:
            return {
                "status": "ok",
                "msg": _("AI 更新成功"),
                "category": info.category,
                "tags": info.tags,
            }
        return {"status": "fail", "msg": _("写入元数据失败")}

    @AsyncService.register_service
    def fill_all(self, idlist: list, force: bool = False):
        self.is_running = True
        self.start_time = time.time()
        self.count_total = len(idlist)
        self.count_skip = 0
        self.count_done = 0
        self.count_fail = 0

        # 创建后台任务
        try:
            task = BackgroundService().update_task(
                service_type=BackgroundTask.SERVICE_TYPE_AI_FILL,
                service_item=_("AI 更新"),
                progress=0,
                progress_data={
                    "total": self.count_total,
                    "done": 0,
                    "skip": 0,
                    "fail": 0,
                },
            )
            self.task_id = task.id
        except Exception as e:
            logging.error("[AIFill] Failed to create background task: %s", e)
            self.task_id = None

        try:
            client = self._make_client()
        except ValueError as e:
            logging.error("[AIFill] Cannot start fill_all: %s", e)
            self._finish_task(failed=True, error_msg=str(e))
            return

        batch_size = 5  # 每批处理数量（AI 调用有延迟，不宜过大）

        for batch_start in range(0, len(idlist), batch_size):
            batch_ids = idlist[batch_start: batch_start + batch_size]
            pending = []
            for book_id in batch_ids:
                self.current_book_id = book_id
                try:
                    mi = self.db.get_metadata(book_id, index_is_id=True)
                    if not force and self._should_skip(mi):
                        logging.info("[AIFill] Skip book id=%d (complete info exists)", book_id)
                        self.count_skip += 1
                    else:
                        pending.append((book_id, mi))
                except Exception as e:
                    logging.error("[AIFill] Failed to read metadata id=%d: %s", book_id, e)
                    self.count_fail += 1

            updates = []
            for book_id, mi in pending:
                authors = list(mi.authors) if mi.authors else []
                try:
                    info = client.get_book_info(
                        title=mi.title,
                        authors=authors,
                        isbn=mi.isbn or ""
                    )
                    if info and info.is_valid():
                        updates.append((book_id, mi, info))
                    else:
                        logging.warning(
                            "[AIFill] AI returned no valid info for id=%d title=%s",
                            book_id,
                            mi.title,
                        )
                        self.count_fail += 1
                except Exception as e:
                    logging.error("[AIFill] AI call failed for id=%d: %s", book_id, e)
                    self.count_fail += 1

            for book_id, mi, info in updates:
                ok = self._apply_ai_info(book_id, mi, info)
                if ok:
                    self.count_done += 1
                else:
                    self.count_fail += 1
            self._update_task_progress()
        self._finish_task()

    def _update_task_progress(self):
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
                    "done": self.count_done,
                    "skip": self.count_skip,
                    "fail": self.count_fail,
                    "current_book_id": self.current_book_id,
                },
            )
        except Exception as e:
            logging.error("[AIFill] Failed to update task progress: %s", e)

    def _finish_task(self, failed: bool = False, error_msg: str = ""):
        if self.task_id:
            try:
                # complete_task 传入 error_message 时会将状态设为 FAILED
                BackgroundService().complete_task(
                    task_id=self.task_id,
                    error_message=error_msg if failed else None,
                )
            except Exception as e:
                logging.error("[AIFill] Failed to finish task: %s", e)

        self.is_running = False
        self.current_book_id = None
        self.task_id = None
