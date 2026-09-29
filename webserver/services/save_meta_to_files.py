#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

"""
(PoxenStudio)批量将metadata保存到文件中，供外部程序使用
"""


import logging
import os
import time
import traceback
from webserver.i18n import _

from webserver import loader, utils
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask

CONF = loader.get_settings()


class SaveMetaToFilesService(AsyncService):

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
            logging.error("[MetaDataSave] Failed to update task progress: %s", e)

    def _get_book(self, book_id):
        books = self.db.get_data_as_dict(ids=[int(book_id)])
        if not books:
            return None
        return books[0]

    def _save_book_meta(self, book_id):
        book = self._get_book(book_id)
        if not book:
            return False

        logging.info(f"[MetaDataSave] save meta for book id:{book_id}, title:{book.get('title', '')}")

        supported_formats = []
        for f in utils.meta_writable_formats():
            fmt_key = f"fmt_{f}"
            if fmt_key in book:
                supported_formats.append((f, book[fmt_key]))

        if not supported_formats:
            logging.warning(f"[MetaDataSave] No supported formats found for book id:{book_id}, title:{book.get('title', '')}")
            return False

        result = False
        try:
            from calibre.ebooks.metadata.meta import set_metadata
            # 获取当前书籍的元数据
            mi = self.db.get_metadata(book_id, index_is_id=True)
            if not mi:
                return False

            success_formats = []
            failed_formats = []

            for f, file_path in supported_formats:
                try:
                    if not os.path.exists(file_path):
                        logging.warning(f"[SAVE_META] File not found: {file_path}")
                        failed_formats.append(f.upper())
                        continue

                    if mi.title:
                        mi.title_sort = utils.super_strip(mi.title)
                    if mi.authors:
                        mi.author_sort = utils.super_strip(mi.authors[0])
                    if not mi.comments:
                        mi.comments = "<>"
                    # 获取封面数据（cover 方法直接返回字节数据）
                    cover_data = self.db.cover(book_id, index_is_id=True)
                    if cover_data:
                        mi.cover_data = ("jpeg", cover_data)
                        logging.info(f"[MetaDataSave] Cover data added for {f.upper()}, size: {len(cover_data)} bytes")

                    # 将元数据写入文件（包含封面）
                    with open(file_path, "rb+") as stream:
                        set_metadata(stream, mi, stream_type=f)

                    logging.info(f"[SAVE_META] Successfully saved metadata to {f.upper()} file for book {book_id}")
                    success_formats.append(f.upper())
                except Exception as e:
                    logging.error(f"[SAVE_META] Failed to save metadata to {f.upper()} file for book {book_id}: {e}")
                    logging.error(traceback.format_exc())
                    failed_formats.append(f.upper())

            if success_formats:
                logging.info(f"[SAVE_META] Metadata saved for book {book_id} in formats: {', '.join(success_formats)}")
                self.count_done += 1
                result = True
            else:
                logging.error(f"[SAVE_META] Failed to save metadata for book {book_id} in formats: {', '.join(f.upper() for f, _ in failed_formats)}")
                self.count_fail += 1
                result = False

        except Exception as e:
            logging.error(f"[SAVE_META] Error saving metadata for book {book_id}: {e}")
            logging.error(traceback.format_exc())
            result = False
        return result

    @AsyncService.register_service
    def save_metadata(self, uid, idlist: list = None):
        self.is_running = True
        self.start_time = time.time()
        self.count_done = 0
        self.count_fail = 0

        books_to_update = idlist
        if not books_to_update:
            logging.info("[MetaDataSave] No books to update, exiting")
            return

        self.count_total = len(books_to_update)
        logging.info("[MetaDataSave] Starting metadata update for %d books", self.count_total)

        try:
            task = BackgroundService().update_task(
                service_type=BackgroundTask.SERVICE_TYPE_SAVE_META,
                service_item=_("同步图书元数据到文件"),
                progress=0,
                progress_data={
                    "total": self.count_total,
                    "done": 0,
                    "fail": 0,
                },
            )
            self.task_id = task.id
        except Exception as e:
            logging.error("[MetaDataSave] Failed to create background task: %s", e)
            self.task_id = None

        for index, book_id in enumerate(books_to_update):
            self.current_book_id = book_id
            self._save_book_meta(book_id)
            if (index + 1) % 100 == 0:
                self._update_task_progress()

        self._update_task_progress()

        if self.task_id:
            try:
                BackgroundService().complete_task(task_id=self.task_id)
            except Exception as e:
                logging.error("[MetaDataSave] Failed to complete task: %s", e)

        logging.info(
            "[MetaDataSave] Completed: total=%d, done=%d, fail=%d, elapsed=%.1fs",
            self.count_total, self.count_done, self.count_fail, time.time() - self.start_time,
        )

        # 发送消息通知用户更新完成
        self.add_msg(
            user_id=uid,
            status="success",
            msg=_("图书元数据保存已完成: 共%d本，成功%d本，失败%d本, 跳过%d本") % (self.count_total, self.count_done, self.count_fail, self.count_total - self.count_done - self.count_fail),
        )

        self.is_running = False
        self.current_book_id = None
        self.task_id = None
