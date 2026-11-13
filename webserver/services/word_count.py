#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""按需统计书籍字数。

与目录提取解耦：详情页按钮触发一次解析，结果写入 calibre 自定义列
``#word_count``，之后详情页只读缓存值。入口只接受 EPUB/TXT，其它格式
（PDF/MOBI/AZW3/扫描版）直接返回不支持。
"""

import json
import logging
import os
import subprocess
import sys

from webserver.constants import CALIBRE_COLUMN_WORD_COUNT
from webserver.i18n import _
from webserver.plugins.parser.txt import TxtParser, count_words
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver.services.extract import ExtractService

COUNTABLE_FORMATS = ("EPUB", "TXT")
TXT_PARSER_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "plugins", "parser", "txt.py",
)


class WordCountService(AsyncService):
    def __init__(self):
        AsyncService.__init__(self)
        self.is_running = False
        self.task_id = None
        self.current_book_id = None
        self.count_total = 0
        self.count_done = 0
        self.count_fail = 0
        self.count_skip = 0

    @AsyncService.register_function
    def count_one(self, book_id):
        """单本入口：同步统计并写入 #word_count，供详情页按钮调用。"""
        return self.count_book(book_id, self.db.new_api, force=True)

    @AsyncService.register_service
    def count_batch(self, uid, book_ids, force=False):
        """批量统计，后台线程执行；force=False 时跳过已有字数的书。"""
        self.is_running = True
        self.count_total = len(book_ids)
        self.count_done = 0
        self.count_fail = 0
        self.count_skip = 0
        self.current_book_id = None
        self.task_id = None

        if not book_ids:
            self.is_running = False
            return

        try:
            task = BackgroundService().update_task(
                service_type=BackgroundTask.SERVICE_TYPE_WORD_COUNT,
                service_item="统计图书字数",
                progress=0,
                progress_data={
                    "total": self.count_total,
                    "done": 0,
                    "fail": 0,
                    "skip": 0,
                    "current_book_id": 0,
                },
            )
            self.task_id = task.id
        except Exception as e:
            logging.error("[WordCount] Failed to create background task: %s", e)

        try:
            for index, book_id in enumerate(book_ids):
                self.current_book_id = book_id
                try:
                    ret = self.count_book(book_id, self.db.new_api, force=force)
                except Exception as e:
                    logging.error("[WordCount] batch error book=%s: %s", book_id, e)
                    ret = {"err": "internal"}

                if ret.get("skipped") or ret.get("err") == "word_count.unsupported":
                    self.count_skip += 1
                elif ret.get("err") != "ok":
                    self.count_fail += 1
                else:
                    self.count_done += 1

                if (index + 1) % 10 == 0:
                    self._update_batch_progress()
        finally:
            self._update_batch_progress()
            if self.task_id:
                try:
                    BackgroundService().complete_task(task_id=self.task_id)
                except Exception as e:
                    logging.error("[WordCount] Failed to complete task: %s", e)
            self.is_running = False
            self.current_book_id = None
            self.add_msg(
                user_id=uid,
                status="success",
                msg=_("字数统计完成：共%d本，成功%d，跳过%d，失败%d") % (
                    self.count_total, self.count_done, self.count_skip, self.count_fail),
            )

    def _update_batch_progress(self):
        if not self.task_id:
            return
        try:
            processed = self.count_done + self.count_fail + self.count_skip
            progress = int(processed * 100 / self.count_total) if self.count_total else 100
            BackgroundService().update_progress(
                task_id=self.task_id,
                progress=progress,
                progress_data={
                    "total": self.count_total,
                    "done": self.count_done,
                    "fail": self.count_fail,
                    "skip": self.count_skip,
                    "current_book_id": self.current_book_id or 0,
                },
            )
        except Exception as e:
            logging.error("[WordCount] Failed to update task progress: %s", e)

    @staticmethod
    def count_book(book_id, db, force=True):
        if not force:
            try:
                existing = db.field_for(CALIBRE_COLUMN_WORD_COUNT, book_id)
            except Exception:
                existing = None
            if existing is not None:
                return {
                    "err": "ok",
                    "skipped": True,
                    "word_count": int(existing),
                    "msg": _("已有字数，跳过"),
                }

        source = WordCountService._pick_source(db, book_id)
        if source is None:
            return {
                "err": "word_count.unsupported",
                "msg": _("书籍不包含可统计字数的格式（EPUB/TXT）"),
            }
        fmt, path = source
        try:
            if fmt == "EPUB":
                word_count = WordCountService._count_epub(path)
            else:
                word_count = WordCountService._count_txt(path)
        except subprocess.TimeoutExpired:
            logging.warning("[WordCount] txt parse timeout book=%s", book_id)
            return {"err": "word_count.timeout", "msg": _("字数统计超时")}
        except Exception as e:
            logging.warning("[WordCount] count failed book=%s fmt=%s: %s", book_id, fmt, e)
            logging.debug("word count traceback", exc_info=True)
            return {"err": "word_count.failed", "msg": _("字数统计失败")}

        try:
            db.set_field(CALIBRE_COLUMN_WORD_COUNT, {book_id: int(word_count)})
        except Exception as e:
            logging.warning("[WordCount] save failed book=%s: %s", book_id, e)
            return {"err": "word_count.save_failed", "msg": _("字数保存失败")}

        return {
            "err": "ok",
            "word_count": int(word_count),
            "format": fmt,
            "msg": _("字数统计成功"),
        }

    @staticmethod
    def _pick_source(db, book_id):
        try:
            available = set(db.formats(book_id, verify_formats=False) or ())
        except Exception:
            return None
        for fmt in COUNTABLE_FORMATS:
            if fmt not in available:
                continue
            try:
                path = db.format_abspath(book_id, fmt)
            except Exception:
                path = None
            if path and os.path.isfile(path):
                return fmt, path
        return None

    @staticmethod
    def _count_txt(path):
        """TXT 整本扫描放子进程，避免大文件统计时和 Tornado 抢 GIL。"""
        if sys.executable and not getattr(sys, "frozen", False) and os.path.isfile(TXT_PARSER_SCRIPT):
            timeout = ExtractService().txt_parse_timeout(path)
            proc = subprocess.run(
                [sys.executable, TXT_PARSER_SCRIPT, "--count", path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                timeout=timeout,
            )
            if proc.returncode == 0:
                try:
                    result = json.loads(proc.stdout.decode("utf-8"))
                    return int(result["word_count"])
                except (ValueError, KeyError, TypeError) as e:
                    logging.warning("[WordCount] invalid txt count output: %s", e)
            else:
                logging.warning(
                    "[WordCount] txt count subprocess exit=%s: %s",
                    proc.returncode, proc.stderr.decode("utf-8", "replace")[-500:],
                )
        return int(TxtParser().count_file(path)["word_count"])

    @staticmethod
    def _count_epub(path):
        import ebooklib
        from ebooklib import epub
        from lxml import html as lxml_html

        book = epub.read_epub(path, {"ignore_ncx": True})
        total = 0
        seen = set()
        spine = getattr(book, "spine", None) or []
        for entry in spine:
            idref = entry[0] if isinstance(entry, (tuple, list)) else entry
            if idref in seen:
                continue
            seen.add(idref)
            item = book.get_item_with_id(idref)
            if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue
            total += WordCountService._html_word_count(item.get_content(), lxml_html)
        if not seen:
            for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                total += WordCountService._html_word_count(item.get_content(), lxml_html)
        return total

    @staticmethod
    def _html_word_count(content, lxml_html):
        try:
            root = lxml_html.fromstring(content)
            for bad in root.xpath("//script|//style|//head"):
                bad.drop_tree()
            return count_words(root.text_content())
        except Exception as e:
            logging.debug("[WordCount] skip bad epub document: %s", e)
            return 0
