#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging
import time
from webserver.i18n import _

from webserver import loader, utils
from webserver.plugins.meta.bookbarn_tags import BookBarnTags
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver.services.book_search import BookSearch
from webserver.constants import AUTO_FILL_META

CONF = loader.get_settings()


class AutoFillService(AsyncService):
    """自动从网上拉取书籍信息，填充到DB中"""
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
        """获取运行状态及处理的进度信息"""
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

    @AsyncService.register_service
    def auto_fill_all(self, idlist: list, only_tags=False, force=False, qpm=60):
        if not CONF.get(AUTO_FILL_META, False) and not force:
            logging.info("Auto-fill meta is disabled in settings, skipping auto_fill_all.")
            return

        # 根据qpm，计算更新的间隔，避免刷爆豆瓣等服务
        sleep_seconds = 60.0 / qpm
        batch_size = 10  # 每批处理的书籍数量

        # 设置运行状态
        self.is_running = True
        self.start_time = time.time()
        self.count_total = len(idlist)
        self.count_skip = 0
        self.count_done = 0
        self.count_fail = 0

        # 创建后台任务
        try:
            service_item = _("图书信息刮削")
            task = BackgroundService().update_task(
                service_type=BackgroundTask.SERVICE_TYPE_AUTOFILL,
                service_item=service_item,
                progress=0,
                progress_data={
                    "total": self.count_total,
                    "done": 0,
                    "skip": 0,
                    "fail": 0
                }
            )
            self.task_id = task.id
        except Exception as e:
            logging.error(f"Failed to create background task: {e}")
            self.task_id = None

        # 分批处理，减少长时间持有数据库锁
        for batch_start in range(0, len(idlist), batch_size):
            batch_end = min(batch_start + batch_size, len(idlist))
            batch_ids = idlist[batch_start:batch_end]

            # 第一阶段：批量读取元数据（持有锁的时间短）
            books_to_update = []
            for book_id in batch_ids:
                self.current_book_id = book_id
                try:
                    mi = self.db.get_metadata(book_id, index_is_id=True)
                    if self.should_update(mi) or only_tags:
                        books_to_update.append((book_id, mi))
                    else:
                        logging.info(_("忽略更新书籍 id=%d : 无需更新"), book_id)
                        self.count_skip += 1
                except Exception as err:
                    logging.error(_("读取书籍元数据失败 id=%d: %s"), book_id, err)
                    self.count_fail += 1

            # 第二阶段：网络请求获取信息（不持有数据库锁）
            updates = []
            for book_id, mi in books_to_update:
                time.sleep(sleep_seconds)
                try:
                    if only_tags:
                        refer_mi = mi
                    else:
                        refer_mi = BookSearch.search_best_book(mi)

                    if refer_mi and refer_mi.cover_data is not None:
                        # 准备更新数据
                        self.do_fill_tags(book_id, refer_mi, need_commit=False)
                        if len(refer_mi.tags) == 0 and len(mi.tags) == 0:
                            refer_mi.tags = self.guess_tags(refer_mi)
                        # 保留书名不修改
                        refer_mi.title = utils.remove_zlibrary_suffix(mi.title)
                        mi.smart_update(refer_mi, replace_metadata=True)
                        updates.append((book_id, mi))
                    else:
                        self.count_fail += 1
                        if not refer_mi:
                            logging.info(_("忽略更新书籍 id=%d : 无法获取信息"), book_id)
                        else:
                            logging.info(_("忽略更新书籍 id=%d : 无法获取封面"), book_id)
                except Exception as err:
                    self.count_fail += 1
                    logging.error(_("获取书籍信息失败 id=%d: %s"), book_id, err if err else "Not found!")

            # 第三阶段：批量写入更新（减少数据库锁持有次数）
            for book_id, mi in updates:
                try:
                    mi.title_sort = utils.get_title_sort(mi.title)
                    self.db.set_metadata(book_id, mi, ignore_errors=True)
                    logging.info(_("自动更新书籍 id=[%d] 的信息，title=%s"), book_id, mi.title)
                    self.count_done += 1
                except Exception as err:
                    self.count_fail += 1
                    logging.error(_("更新书籍元数据失败 id=%d: %s"), book_id, err)

            # 更新任务进度
            if self.task_id:
                try:
                    progress = int((self.count_done + self.count_skip + self.count_fail) * 100 / self.count_total)
                    BackgroundService().update_progress(
                        task_id=self.task_id,
                        progress=progress,
                        progress_data={
                            "total": self.count_total,
                            "done": self.count_done,
                            "skip": self.count_skip,
                            "fail": self.count_fail,
                            "current_book_id": self.current_book_id
                        }
                    )
                except Exception as e:
                    logging.error(f"Failed to update task progress: {e}")

        # 完成任务
        if self.task_id:
            try:
                BackgroundService().complete_task(task_id=self.task_id)
            except Exception as e:
                logging.error(f"Failed to complete task: {e}")

        # 重置运行状态
        self.is_running = False
        self.current_book_id = None
        self.task_id = None

    @AsyncService.register_function
    def auto_fill(self, book_id, only_tags=False, force_update=False):
        mi = self.db.get_metadata(book_id, index_is_id=True)
        if not force_update and (not CONF.get(AUTO_FILL_META, False) or only_tags):
            self.do_fill_tags(book_id, mi, need_commit=True)
            return True
        return self.do_fill_metadata(book_id, mi)

    def do_fill_metadata(self, book_id, mi):
        refer_mi = None

        logging.info(_("开始自动填充书籍 id=%d 的元数据，title=%s"), book_id, mi.title)
        try:
            refer_mi = BookSearch.search_best_book(mi)
        except Exception as e:
            logging.error(_("自动填充元数据时出错 id=%d: %s"), book_id, e)
            return False

        if not refer_mi:
            logging.info(_("忽略更新书籍 id=%d : 无法获取信息"), book_id)
            return False

        if refer_mi.cover_data is None:
            logging.info(_("忽略更新书籍 id=%d : 无法获取封面"), book_id)
            return False

        # 自动填充tag
        self.do_fill_tags(book_id, refer_mi, need_commit=False)
        if len(refer_mi.tags) == 0 and len(mi.tags) == 0:
            mi.tags = self.guess_tags(refer_mi)

        # 保留书名不修改（万一出BUG，还能抢救一下）
        title = utils.remove_zlibrary_suffix(mi.title)
        refer_mi.title = title
        refer_mi.title_sort = utils.get_title_sort(refer_mi.title)

        mi.smart_update(refer_mi, replace_metadata=True)
        self.db.set_metadata(book_id, mi, ignore_errors=True)
        logging.info(_("自动更新书籍 id=[%d] 的信息，title=%s"), book_id, mi.title)
        return True

    def should_update(self, mi):
        if not mi.comments or not mi.has_cover or not mi.authors or mi.authors[0] in (u"佚名", u"未知", u"Unknown"):
            return True
        return False

    def guess_tags(self, refer_mi, max_count=8):
        ts = []
        for tag in CONF["BOOK_NAV"].replace("=", "/").replace("\n", "/").split("/"):
            if tag in refer_mi.title or tag in refer_mi.comments:
                ts.append(tag)
            elif tag in refer_mi.authors:
                ts.append(tag)
            if len(ts) > max_count:
                break
        return ts

    def do_fill_tags(self, book_id, mi, need_commit=False):
        try:
            tags = self.plugin_search_book_tag(mi)
            if tags:
                mi.tags = tags
                if need_commit:
                    self.db.set_metadata(book_id, mi, ignore_errors=True)
                logging.info(_("自动更新书籍 id=[%d] 的标签，title=%s"), book_id, mi.title)
                return True
            else:
                logging.info(_("忽略更新书籍 id=%d : 无法获取标签, title=%s"), book_id, mi.title)
        except Exception as e:
            logging.error(_("bookbarn_tags 接口查询 %s 失败: %s"), mi.title, e)
        return False

    def plugin_search_book_tag(self, mi):
        if not mi.isbn and not mi.title and not mi.author:
            logging.info(_("忽略获取标签书籍 id=%d : 无有效数据"), mi.id)
            return None

        api = BookBarnTags(token=CONF.get("BOOKBARN_TOKEN", ""))
        try:
            author = mi.authors[0] if mi.authors else ""
            logging.info(_("调用 bookbarn_tags 接口查询 %s, %s, %s"), mi.title, author, mi.isbn)
            tags = api.get_tags(mi.isbn, mi.title, author)
            logging.info(f"bookbarn_tags 返回标签: {tags}")
            return tags.split(",") if tags else None
        except:
            logging.error(_("bookbarn_tags 接口查询 %s 失败"), mi.title)
        return None
