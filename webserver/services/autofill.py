#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging
import time
from webserver.i18n import _

from webserver import loader, utils
from webserver.base.meta_helper import guess_authors
from webserver.plugins.meta.bookbarn_tags import BookBarnTags
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver.services.book_search import BookSearch
from webserver.constants import AUTO_FILL_META, CALIBRE_COLUMN_TRANSLATORS

CONF = loader.get_settings()

# 限流暂停切片与上限：RequestCounter 窗口最长 5 分钟，正常一轮暂停远小于上限；
# 连续暂停超过 PAUSE_MAX_ROUNDS 轮（约 2 小时）视为源持续不可用，中止本轮。
PAUSE_SLICE_SECONDS = 5
PAUSE_MAX_SECONDS = 30 * 60
PAUSE_MAX_ROUNDS = 24


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
        self.cancel_requested = False
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

    def cancel(self):
        """请求中断当前刮削任务。"""
        if not self.is_running:
            return False
        self.cancel_requested = True
        return True

    @AsyncService.register_service
    def auto_fill_all(self, idlist: list, only_tags=False, force=False, qpm=None):
        if not CONF.get(AUTO_FILL_META, False) and not force:
            logging.info("Auto-fill meta is disabled in settings, skipping auto_fill_all.")
            return

        # 根据qpm，计算更新的间隔，避免刷爆豆瓣等服务；qpm 未显式给定时读设置
        if not qpm:
            qpm = max(1, int(CONF.get("auto_fill_qpm", 60) or 60))
        sleep_seconds = 60.0 / qpm
        batch_size = 10  # 每批处理的书籍数量
        pause_on_throttle = bool(CONF.get("auto_fill_pause_on_throttle", True))

        # 设置运行状态
        self.is_running = True
        self.cancel_requested = False
        self.start_time = time.time()
        self.count_total = len(idlist)
        self.count_skip = 0
        self.count_done = 0
        self.count_fail = 0
        self._throttle_pause_rounds = 0

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
        throttle_aborted = False
        for batch_start in range(0, len(idlist), batch_size):
            if throttle_aborted or self.cancel_requested:
                break
            batch_end = min(batch_start + batch_size, len(idlist))
            batch_ids = idlist[batch_start:batch_end]

            # 第一阶段：批量读取元数据（持有锁的时间短）
            books_to_update = []
            for book_id in batch_ids:
                if self.cancel_requested:
                    break
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
                if self.cancel_requested:
                    break
                time.sleep(sleep_seconds)
                if self.cancel_requested:
                    break
                try:
                    refer_mi = self._fetch_refer(mi, only_tags)
                    if refer_mi is None and pause_on_throttle and BookSearch.throttle_wait_seconds():
                        # 落空且恰有限流源预算耗尽：大概率本次请求被限流源静默
                        # 跳过（排在它前面的后备源未命中才会轮到它）。等预算
                        # 恢复后重试一次——否则每个限流窗口边界都白丢一本书的
                        # 元数据。后备源仍健康的场景不会走到这里（取到了就不
                        # 检查），不与限流源无关的正常无结果冲突。
                        logging.warning(_("书籍 id=%d 获取信息落空且限流源预算耗尽，暂停等待预算恢复后重试"), book_id)
                        if not self._throttle_pause():
                            if self.cancel_requested:
                                break
                            logging.error(_("元数据源限流暂停超过上限，中止本轮自动填充，剩余书目下轮重扫或手动触发"))
                            self._restore_progress()
                            throttle_aborted = True
                            break
                        if self.cancel_requested:
                            break
                        time.sleep(sleep_seconds)
                        refer_mi = self._fetch_refer(mi, only_tags)

                    if refer_mi and refer_mi.cover_data is not None and refer_mi.title and refer_mi.title != "验证":
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
                    _authors, _translators = guess_authors(mi.authors)
                    mi.authors = _authors
                    mi.title_sort = utils.get_title_sort(mi.title)
                    self.db.set_metadata(book_id, mi, ignore_errors=True)
                    if _translators:
                        translators = ",".join(_translators)
                        self.db.new_api.set_field(CALIBRE_COLUMN_TRANSLATORS, {book_id: translators})
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
                if self.cancel_requested:
                    BackgroundService().cancel_task(task_id=self.task_id)
                else:
                    BackgroundService().complete_task(task_id=self.task_id)
            except Exception as e:
                logging.error(f"Failed to complete task: {e}")

        # 重置运行状态
        self.is_running = False
        self.current_book_id = None
        self.task_id = None

    def _fetch_refer(self, mi, only_tags):
        """单次元数据网络获取（only_tags 路径无网络请求，直接用本地 mi）。"""
        if only_tags:
            return mi
        return BookSearch.search_best_book(mi)

    def _throttle_pause(self):
        """元数据源（豆瓣 v2 等）预算耗尽时暂停批任务，定时自动续跑。

        暂停态注册到右上角任务指示器：progress_data.stage=paused + resume_at
        （epoch 秒）+ pause_reason，前端据此渲染“已限流暂停，HH:MM 自动继续”。
        切片睡眠并复查预算（突发耗尽后的整窗拒绝也能等到恢复）。返回 False
        表示应中止本轮：单次等待超 PAUSE_MAX_SECONDS 或连续暂停轮数超
        PAUSE_MAX_ROUNDS——源持续不可用时不再无限空转。
        """
        while True:
            if self.cancel_requested:
                return False
            wait = BookSearch.throttle_wait_seconds()
            if not wait:
                # 预算恢复：连续不可用计数清零（保险丝只拦"持续不可用"，
                # 间歇性正常限流不累计）
                self._throttle_pause_rounds = 0
                return True
            wait = int(wait)
            if wait > PAUSE_MAX_SECONDS or self._throttle_pause_rounds >= PAUSE_MAX_ROUNDS:
                return False
            self._throttle_pause_rounds += 1
            resume_at = int(time.time() + wait)
            logging.warning(_("元数据源请求频率已达上限，暂停 %d 秒后自动继续"), wait)
            self._update_paused_progress(resume_at, wait)
            deadline = time.time() + wait
            while time.time() < deadline:
                if self.cancel_requested:
                    return False
                time.sleep(min(PAUSE_SLICE_SECONDS, max(0.05, deadline - time.time())))
            self._restore_progress()

    def _update_paused_progress(self, resume_at, wait_seconds):
        if not self.task_id:
            return
        try:
            BackgroundService().update_progress(
                task_id=self.task_id,
                progress=self._current_progress(),
                progress_data={
                    "total": self.count_total,
                    "done": self.count_done,
                    "skip": self.count_skip,
                    "fail": self.count_fail,
                    "stage": "paused",
                    "pause_reason": "douban_v2_rate_limit",
                    "resume_at": resume_at,
                    "wait_seconds": int(wait_seconds),
                },
            )
        except Exception as e:
            logging.error(f"Failed to update paused progress: {e}")

    def _restore_progress(self):
        if not self.task_id:
            return
        try:
            BackgroundService().update_progress(
                task_id=self.task_id,
                progress=self._current_progress(),
                progress_data={
                    "total": self.count_total,
                    "done": self.count_done,
                    "skip": self.count_skip,
                    "fail": self.count_fail,
                    "stage": "importing",
                    "current_book_id": self.current_book_id,
                },
            )
        except Exception as e:
            logging.error(f"Failed to restore progress: {e}")

    def _current_progress(self):
        if not self.count_total:
            return 0
        return int((self.count_done + self.count_skip + self.count_fail) * 100 / self.count_total)

    @AsyncService.register_function
    def auto_fill(self, book_id, only_tags=False, force_update=False):
        mi = self.db.get_metadata(book_id, index_is_id=True)
        if not force_update and (not CONF.get(AUTO_FILL_META, False) or only_tags):
            self.do_fill_tags(book_id, mi, need_commit=True)
            return True
        return self.do_fill_metadata(book_id, mi)

    @AsyncService.register_service
    def auto_fill_async(self, book_id):
        if not self.db.new_api.has_id(book_id):
            logging.info("[AutoFill] book %s no longer exists, skip", book_id)
            return
        self.auto_fill(book_id)

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

        if refer_mi.isbn and refer_mi.title == "验证":
            logging.info(_("忽略更新书籍 id=%d : 无效信息"), book_id)
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

        _authors, _translators = guess_authors(refer_mi.authors)
        mi.smart_update(refer_mi, replace_metadata=True)
        mi.authors = _authors
        self.db.set_metadata(book_id, mi, ignore_errors=True)
        if _translators:
            translators = ",".join(_translators)
            self.db.new_api.set_field(CALIBRE_COLUMN_TRANSLATORS, {book_id: translators})
        # Try to update author info auto
        if mi.authors and mi.authors[0] not in (u"佚名", u"未知", u"Unknown"):
            from webserver.services.book_barn import BookBarnService
            BookBarnService().update_author_async(mi.authors[0], force=False)
        logging.info(_("自动更新书籍 id=[%d] 的信息，title=%s"), book_id, mi.title)
        return True

    def should_update(self, mi):
        if not mi.comments or not mi.has_cover or not mi.authors or mi.authors[0] in (u"佚名", u"未知", u"Unknown"):
            return True
        return False

    def guess_tags(self, refer_mi, max_count=8):
        ts = []
        for tag in CONF["BOOK_NAV"].replace("=", "/").replace("\n", "/").split("/"):
            if (refer_mi.title and tag in refer_mi.title) or \
               (refer_mi.comments and tag in refer_mi.comments) or \
               (refer_mi.authors and tag in refer_mi.authors):
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

        if mi.title and mi.title == "验证":
            return None

        api = BookBarnTags(token=CONF.get("BOOKBARN_TOKEN", ""))
        try:
            author = mi.authors[0] if mi.authors else ""
            logging.info(_("调用 bookbarn_tags 接口查询 %s, %s, %s"), mi.title, author, mi.isbn)
            tags = api.get_tags(mi.isbn, mi.title, author)
            logging.info(f"bookbarn_tags 返回标签: {tags}")
            return tags.split(",") if tags else None
        except Exception:
            logging.error(_("bookbarn_tags 接口查询 %s 失败"), mi.title)
        return None
