#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import datetime
import json
import logging
from venv import logger
import opencc
import os
import random
import re
import shutil
import time
import traceback
import urllib
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from webserver.i18n import _

try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False

import tornado.escape
from tornado import web

from webserver import loader, utils
from webserver.base.formatter import BookFormatter, ReadingStateFormatter
from webserver.base.cover_generator import CoverGenerator
from webserver.base.image_helper import ImageHelper
from webserver.services.autofill import AutoFillService
from webserver.services.ai_fillinfo import AIFillInfoService
from webserver.services.book_search import BookSearch
from webserver.services.converter import ConverterService
from webserver.services.extract import ExtractService
from webserver.services.mail import MailService
from webserver.handlers.base import BaseHandler, ListHandler, auth, js
from webserver.models import Item, ReadingState, Reader
from webserver.plugins.meta import douban, youshu
from webserver.plugins.meta.bookbarn_tags import BookBarnTags
from webserver.plugins.parser.txt import get_content_encoding
from webserver.handlers.audio import AudioUtils
from webserver import constants
from webserver.constants import COLUMN_CATEGORY, CALIBRE_COLUMN_CATEGORY
from webserver.constants import CALIBRE_ERROR_FLAG, SUPPORTED_EBOOK_FORMATS
from webserver.constants import CALIBRE_COLUMN_BOOK_TYPE, CALIBRE_COLUMN_PHY_COUNT
from webserver.constants import BOOK_TYPE_EBOOK, BOOK_TYPE_PHYSICAL, AUTO_FILL_META
from webserver.constants import COLUMN_EXT_LINK, CALIBRE_COLUMN_EXT_LINK
from webserver.constants import CALIBRE_COLUMN_LOCATION, COLUMN_LOCATION
from webserver.constants import CALIBRE_COLUMN_DYNAMIC_COVER, COLUMN_DYNAMIC_COVER


CONF = loader.get_settings()


class Index(BaseHandler):
    def fmt(self, b):
        return BookFormatter(self, b).format()

    @js
    def get(self):
        """首页显示随机书籍和最近添加的书籍"""
        setting_random_count = CONF.get("MAIN_PAGE_RANDOM_COUNT", 12)
        setting_recent_count = CONF.get("MAIN_PAGE_RECENT_COUNT", 12)
        cnt_random = min(int(self.get_argument("random", setting_random_count)), setting_random_count)
        cnt_recent = min(int(self.get_argument("recent", setting_recent_count)), 200)

        ids = list(self.calibre_db_cache.all_book_ids())
        if not ids:
            return {
                "err": "nobooks",
                "random_books_count": 0,
                "new_books_count": 0,
                "random_books": [],
                "new_books": []
            }

        cnt_recent = min(cnt_recent, len(ids))
        cnt_random = min(cnt_random, len(ids))
        random_ids = random.sample(ids, min(cnt_random, len(ids)))
        random_books = [b for b in self.get_books(ids=random_ids)]
        random_books.sort(key=lambda x: x["id"], reverse=True)

        ids.sort(reverse=True)
        new_ids = random.sample(ids[0:600], min(cnt_recent, len(ids)))
        new_books = [b for b in self.get_books(ids=new_ids)]
        new_books.sort(key=lambda x: x["id"], reverse=True)

        return {
            "err": "ok",
            "random_books_count": len(random_books),
            "new_books_count": len(new_books),
            "random_books": [self.fmt(b) for b in random_books],
            "new_books": [self.fmt(b) for b in new_books],
        }


class BookDetail(BaseHandler):
    @js
    def get(self, bid):
        book = None
        try:
            book_id = int(bid)
            book = self.get_book(book_id, raise_exception=False)
        except Exception as e:
            logging.error("get book %s failed: %s" % (bid, e))

        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍不存在")}

        # 添加当前用户的阅读状态信息
        if self.current_user:
            reading_state = self.sqlite_session.query(ReadingState).filter(
                ReadingState.book_id == book_id,
                ReadingState.reader_id == self.current_user.id
            ).first()

            # 创建阅读状态映射
            if reading_state:
                book["state"] = ReadingStateFormatter.format_reading_state(reading_state)
            else:
                book["state"] = ReadingStateFormatter.format_reading_state(None)
        else:
            logging.info("User not logged in, skipping reading state.")

        if "state" not in book:
            book["state"] = {
                "favorite": 0,
                "favorite_date": None,
                "wants": 0,
                "wants_date": None,
                "read_state": 0,
                "read_date": None,
                "online_read": 0,
                "download": 0
            }

        self.count_increase(bid, count_visit=1)
        return {
            "err": "ok",
            "kindle_sender": CONF["smtp_username"],
            "book": BookFormatter(self, book).format(with_files=True, with_perms=True),
            "audios": AudioUtils.get_audios(bid, self.current_user.id if self.current_user else None),
        }


class BookTags(BaseHandler):
    # Update the tags by BookBarn Tags API
    @js
    @auth
    def post(self, id):
        book_id = int(id)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍不存在")}

        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _("无权限")}

        isbn = book.get("isbn", "")
        title = book.get("title", "")
        authors = book.get("authors", [])
        author = authors[0] if authors else ""

        if title.startswith("百度百科"):
            return {"err": "ok", "msg": _("无需更新")}

        try:
            api = BookBarnTags(token=CONF.get("BOOKBARN_TOKEN", ""))
            if not api:
                return {"err": "plugin.missing", "msg": _("BookBarn Tags插件未安装")}
            tags = api.get_tags(isbn=isbn, title=title, author=author)
            if not tags:
                tags = ""
            logging.info(f"BookBarn Tags for book {book_id} ({title}): {tags}")
            if len(tags) > 0:
                new_tags = tags.split(",") if tags else None
                if len(new_tags) > 0:
                    updated_tags = list(set(new_tags))
                    self.calibre_db.set_tags(book_id, updated_tags)
                    logging.info(f"Updated tags for book {book_id}: {updated_tags}")
                    return {"err": "ok", "msg": _("标签更新成功")}
            return {"err": "ok", "msg": _("标签已是最新，无需更新")}
        except Exception as e:
            logging.error(f"Error updating tags for book {book_id}: {e}")
            return {"err": "internal", "msg": _("更新标签时发生错误，请稍后再试")}


class BookAIFill(BaseHandler):
    """使用 AI 同步更新单本书的分类、标签、简介和作者介绍"""
    @js
    @auth
    def post(self, id):
        book_id = int(id)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍不存在")}

        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _("无权限")}

        result = AIFillInfoService().fill_one(book_id, force=True)
        status = result.get("status", "fail")
        if status == "ok":
            return {
                "err": "ok",
                "msg": _("AI 更新成功"),
                "category": result.get("category", ""),
                "tags": result.get("tags", []),
            }
        return {"err": "ai.fill.failed", "msg": result.get("msg", _("AI 更新失败"))}


class BookUpdateTags(BaseHandler):
    """Batch update tags for all books with a specific tag"""
    @js
    @auth
    def post(self):
        if not self.is_admin():
            return {"err": "user.no_permission", "msg": _("无权限")}

        tag_name = self.get_argument("tag", "").strip()
        if not tag_name:
            return {"err": "params.invalid", "msg": _("请指定标签名称")}

        try:
            # Search books by tag
            query = f'tags:="{tag_name}"'
            book_ids = self.calibre_db_cache.search(query)

            if not book_ids:
                return {"err": "ok", "msg": _("未找到包含该标签的书籍"), "count": 0}

            # Convert to list to avoid "Set changed size during iteration" error
            book_ids = list(book_ids)

            # Limit to 300 books
            total_count = len(book_ids)
            if total_count > 300:
                book_ids = book_ids[:300]
                logging.info(f"Limiting tag update to first 300 books out of {total_count}")

            # Call AutoFillService to update tags in background
            AutoFillService().auto_fill_all(book_ids, only_tags=True, force=True)

            msg = _("已提交 %d 本书籍的标签更新任务，正在后台处理, 请稍后刷新查看结果") % len(book_ids)
            if total_count > 300:
                msg += _("（共找到 %d 本，仅处理前 300 本）") % total_count

            return {"err": "ok", "msg": msg, "count": len(book_ids), "total": total_count}

        except Exception as e:
            logging.error(f"Error in batch tag update for tag {tag_name}: {e}")
            return {"err": "internal", "msg": _("批量更新标签时发生错误")}


class BookCategory(BaseHandler):
    @js
    @auth
    def post(self, id):
        book_id = int(id)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍不存在")}

        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _("无权限")}

        data = tornado.escape.json_decode(self.request.body)
        category = data.get(COLUMN_CATEGORY, "").strip()
        if category == '清除' or category.lower() == 'clear':
            category = ''
        logging.info(f"Updating category for book {book_id}: {category}")
        try:
            # Use set_field directly on the cache to avoid Metadata object issues
            self.calibre_db_cache.set_field(CALIBRE_COLUMN_CATEGORY, {book_id: category})
            return {"err": "ok", "msg": _("分类更新成功")}
        except Exception as e:
            logging.error(f"Error updating category for book {book_id}: {e}")
            return {"err": "internal", "msg": _("更新分类失败")}


class BookLocation(BaseHandler):
    @js
    @auth
    def post(self, id):
        book_id = int(id)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍不存在")}

        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _("无权限")}

        data = tornado.escape.json_decode(self.request.body)
        location = data.get(COLUMN_LOCATION, "").strip()
        if len(location) > 20:
            return {"err": "params.location.invalid", "msg": _("位置信息过长")}

        logging.info(f"Updating location for book {book_id}: {location}")
        try:
            self.calibre_db_cache.set_field(CALIBRE_COLUMN_LOCATION, {book_id: location})
            return {"err": "ok", "msg": _("位置更新成功")}
        except Exception as e:
            logging.error(f"Error updating location for book {book_id}: {e}")
            return {"err": "internal", "msg": _("更新位置失败")}


class BookCategoryBatch(BaseHandler):
    @js
    @auth
    def post(self):
        if not self.is_admin():
            return {"err": "user.no_permission", "msg": _("无权限")}

        data = tornado.escape.json_decode(self.request.body)
        category = data.get(COLUMN_CATEGORY, "").strip()
        author = data.get("author", "").strip()
        tag = data.get("tag", "").strip()

        if not category:
            return {"err": "params.category.empty", "msg": _("分类不能为空")}

        if not author and not tag:
            return {"err": "params.invalid", "msg": _("必须指定作者或标签")}

        # Find books
        book_ids = set()
        if author:
            # Search by author
            try:
                # Use calibre search syntax for author
                # authors:"=Author Name"
                query = f'authors:="{author}"'
                ids = self.calibre_db_cache.search(query)
                book_ids.update(ids)
            except Exception as e:
                logging.error(f"Error searching books by author {author}: {e}")
                return {"err": "internal", "msg": _("搜索作者书籍失败")}

        if tag:
            # Search by tag
            try:
                query = f'tags:="{tag}"'
                ids = self.calibre_db_cache.search(query)
                book_ids.update(ids)
            except Exception as e:
                logging.error(f"Error searching books by tag {tag}: {e}")
                return {"err": "internal", "msg": _("搜索标签书籍失败")}

        if not book_ids:
            return {"err": "ok", "msg": _("未找到符合条件的书籍"), "count": 0}

        logging.info(f"Batch updating category to '{category}' for {len(book_ids)} books (Author: {author}, Tag: {tag})")

        count = 0
        try:
            # Update category for each book
            # We use the cache's set_field which expects {book_id: value}
            # To optimize, we can construct a dict for all books if set_field supports it,
            # but usually it's one call per update or specific batch APIs.
            # Looking at existing BookCategory.post, it uses:
            # self.calibre_db_cache.set_field('#category', {book_id: category})

            # set_field can handle a dict of {id: value}
            updates = {bid: category for bid in book_ids}
            self.calibre_db_cache.set_field(CALIBRE_COLUMN_CATEGORY, updates)
            count = len(book_ids)

            return {"err": "ok", "msg": _("成功更新 %d 本书籍分类") % count, "count": count}
        except Exception as e:
            logging.error(f"Error batch updating category: {e}")
            return {"err": "internal", "msg": _("批量更新分类失败")}


class BookCategories(BaseHandler):
    def _filter_categories_by_reading_range(self, categories):
        """根据当前用户的阅读范围设置过滤分类列表，管理员和未登录用户不过滤"""
        user = self.current_user
        if not user:
            # 未登录用户只能看到未设置分类的书籍，因此只能看到一个空分类
            return []
        if not user or self.is_admin():
            return categories
        read_limit = getattr(user, 'read_limit', 0) or 0
        if read_limit == 0:
            return categories
        limit_cats = set(filter(None, (user.limit_categories or "").split(',')))
        if not limit_cats:
            return categories
        if read_limit == 1:
            return [c for c in categories if c["name"] in limit_cats]
        # read_limit == 2: 黑名单
        return [c for c in categories if c["name"] not in limit_cats]

    @js
    def get(self):
        # Find the custom column for category
        category_key = CALIBRE_COLUMN_CATEGORY
        if category_key not in self.calibre_db.field_metadata:
            return {"err": "ok", "categories": []}

        meta = self.calibre_db.field_metadata[category_key]
        table = f"custom_column_{meta['colnum']}"
        link_table = f"books_{table}_link"

        sql = f"""
            SELECT t.value, count(l.book) as count
            FROM {table} t
            JOIN {link_table} l ON t.id = l.value
            GROUP BY t.id
            ORDER BY count DESC
        """

        try:
            with self.db_lock:
                rows = self.calibre_db_cache.backend.conn.get(sql)
            categories = [{"name": row[0], "count": row[1]} for row in rows]

            if CONF.get(constants.ALLOW_READ_RANGE_SETTING, False):
                categories = self._filter_categories_by_reading_range(categories)

            return {"err": "ok", "categories": categories}
        except Exception as e:
            logging.error(f"Error fetching categories: {e}")
            return {"err": "internal", "msg": _("获取分类列表失败")}


class TagSearch(BaseHandler):
    @js
    def get(self):
        q = (self.get_argument("q", "") or "").strip()
        limit = min(50, int(self.get_argument("limit", 20)))
        sql = """SELECT tags.name, count(distinct book) as count
        FROM tags left join books_tags_link on tags.id = books_tags_link.tag
        WHERE tags.name LIKE ? ESCAPE '\\'
        GROUP BY tags.id ORDER BY count DESC LIMIT ?"""
        try:
            with self.db_lock:
                rows = self.calibre_db_cache.backend.conn.get(sql, (q + "%", limit))
            tags = [{"name": r[0], "count": r[1]} for r in rows]
            return {"err": "ok", "tags": tags}
        except Exception as e:
            logging.error(f"Error searching tags: {e}")
            return {"err": "internal", "msg": _("获取标签列表失败")}


class BookConverter(BaseHandler):
    @js
    @auth
    def post(self, id):
        book_id = int(id)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍不存在")}

        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _("无权限")}

        fmts = []
        paths = []
        for fmt in constants.SUPPORTED_EBOOK_FORMATS:
            book_path = book.get("fmt_%s" % fmt, None)
            if book_path:
                fmts.append(fmt)
                paths.append(book_path)

        if ('epub' in fmts) and ('azw3' in fmts):
            return {"err": "params.book.invalid", "msg": _("本书已有EPUB及Kindle版本, 不需要转换")}

        if fmts[0] == "epub":
            fmt = "azw3"
        elif fmts[0] == "pdf":
            fmt = "epub"
        else:
            fmt = "epub"

        if 'docx' in fmts:
            # docx is preferred than pdf
            fpath = paths[fmts.index('docx')]
        else:
            fpath = paths[0]

        service = ConverterService()
        if service.is_book_converting(book):
            return {"err": "params.book.converting", "msg": _("本书正在转换中，请稍后再试")}
        logging.info(f"Start converting book {book_id} from {fmts[0]} to {fmt}, title:{book.get('title', '')}")
        service.convert_and_save(self.user_id(), book, fpath, fmt)
        return {"err": "ok", "content": "%s" % _("转换成功，请稍后刷新页面查看")}


class BookToPDF(BaseHandler):
    @js
    @auth
    def post(self, id):
        book_id = int(id)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍不存在")}

        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _("无权限")}

        fmts = []
        paths = []
        has_pdf = False
        for fmt in ["epub", "azw3", "mobi", "azw", "pdf", "docx"]:
            book_path = book.get("fmt_%s" % fmt, None)
            if not book_path:
                continue
            if fmt == "pdf":
                has_pdf = True
                continue
            fmts.append(fmt)
            paths.append(book_path)

        if has_pdf:
            return {"err": "params.book.invalid", "msg": _("本书已有PDF版本, 不需要转换")}
        if len(fmts) == 0:
            return {"err": "params.book.invalid", "msg": _("本书不支持转换，仅支持EPUB及Kindle使用的格式转换为PDF")}

        fpath = paths[0]
        service = ConverterService()
        if service.is_book_converting(book):
            return {"err": "params.book.converting", "msg": _("本书正在转换中，请稍后再试")}
        service.convert_and_save(self.user_id(), book, fpath, "pdf")
        return {"err": "ok", "content": "%s" % _("转换成功，请稍后刷新页面查看")}


class BookToTxtZ(BaseHandler):
    @js
    @auth
    def post(self, id):
        book_id = int(id)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍不存在")}

        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _("无权限")}

        fmts = []
        paths = []
        has_txtz = False
        for fmt in ["txt", "txtz"]:
            book_path = book.get("fmt_%s" % fmt, None)
            if not book_path:
                continue
            if fmt == "txtz":
                has_txtz = True
                continue
            fmts.append(fmt)
            paths.append(book_path)

        if has_txtz:
            return {"err": "params.book.invalid", "msg": _("本书已有TXTZ版本, 不需要转换")}
        if len(fmts) == 0:
            return {"err": "params.book.invalid", "msg": _("本书不支持转换，仅支持TXT格式转换为TXTZ")}

        fpath = paths[0]
        service = ConverterService()
        if service.is_book_converting(book):
            return {"err": "params.book.converting", "msg": _("本书正在转换中，请稍后再试")}
        service.convert_and_save(self.user_id(), book, fpath, "txtz")
        return {"err": "ok", "content": "%s" % _("转换成功，请稍后刷新页面查看")}


class BookSetSole(BaseHandler):
    @js
    @auth
    def post(self, bid):
        book = self.get_book(bid, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍已不存在")}
        bid = book["id"]
        if isinstance(book["collector"], dict):
            cid = book["collector"]["id"]
        else:
            cid = book["collector"].id
        if not self.current_user.can_edit() or not (self.is_admin() or self.is_book_owner(bid, cid)):
            return {"err": "permission", "msg": _("无权操作")}

        succeed = False
        try:
            self.sqlite_session.query(Item).filter(Item.book_id == bid).update({"sole": not book["sole"]})
            self.sqlite_session.commit()
            succeed = True
        except Exception as e:
            self.sqlite_session.rollback()
            logging.error("set book %d sole failed: %s" % (bid, e))

        if succeed:
            return {"err": "ok", "msg": _("更新成功")}
        else:
            return {"err": "db.update.failed", "msg": _("更新失败，请稍后再试")}


class BookRefer(BaseHandler):
    _search_executor = ThreadPoolExecutor(max_workers=int(CONF.get("REFER_SEARCH_MAX_WORKERS", 6)))
    _search_cache_ttl = int(CONF.get("REFER_SEARCH_CACHE_TTL", 180))
    _search_max_concurrency = int(CONF.get("REFER_SEARCH_MAX_CONCURRENCY", 16))
    _search_cache = {}
    _search_inflight = {}
    _search_state_lock = threading.Lock()
    _search_semaphore = None

    meta_keys = [
        "cover_url",
        "source",
        "website",
        "title",
        "authors",
        "author_sort",
        "publisher",
        "comments",
        "provider_key",
        "provider_value",
        "isbn",
        "isbn13",
        "language",
        "identifiers",
        "tags",
        "series"
    ]

    @classmethod
    def _get_search_semaphore(cls):
        if cls._search_semaphore is None:
            cls._search_semaphore = asyncio.Semaphore(cls._search_max_concurrency)
        return cls._search_semaphore

    @staticmethod
    def _build_search_key(title, isbn, publisher):
        return "|".join([(title or "").strip(), (isbn or "").strip(), (publisher or "").strip()])

    @classmethod
    def _get_cached_books(cls, key):
        now = time.time()
        with cls._search_state_lock:
            entry = cls._search_cache.get(key)
            if not entry:
                return None
            expires_at, books = entry
            if now >= expires_at:
                cls._search_cache.pop(key, None)
                return None
            return books

    @classmethod
    def _set_cached_books(cls, key, books):
        with cls._search_state_lock:
            cls._search_cache[key] = (time.time() + cls._search_cache_ttl, books)

    @classmethod
    def _cleanup_inflight(cls, key, fut):
        with cls._search_state_lock:
            current = cls._search_inflight.get(key)
            if current is fut:
                cls._search_inflight.pop(key, None)

    def _format_refer_books(self, books):
        rsp = []
        for b in books:
            try:
                d = dict((k, b.get(k, None)) for k in self.meta_keys)
                # Remoe the key with empty values
                d = {k: v for k, v in d.items() if v}
                pubdate = b.get("pubdate")
                if b.rating:
                    d["rating"] = round(b.rating, 1)
                d["pubyear"] = pubdate.strftime("%Y") if pubdate else ""
                d["pubdate"] = pubdate.strftime("%Y-%m-%d") if pubdate else ""
                if not d.get("comments", ""):
                    d["comments"] = _("无详细介绍")
                rsp.append(d)
            except Exception as e:
                logging.error("get book meta error: %s" % e)
                logging.error(traceback.format_exc())
        return rsp

    def _convert_to_metadata(self, metadata):
        from calibre.ebooks.metadata.book.base import Metadata
        mi = Metadata(metadata.get("title", ""))
        mi.publisher = metadata.get("publisher", None)
        mi.authors = metadata.get("authors", [])
        mi.author_sort = metadata.get("author_sort", None)
        mi.isbn = metadata.get("isbn", "")
        mi.isbn13 = metadata.get("isbn13", None)
        mi.language = metadata.get("language", "zho")
        mi.identifiers = metadata.get("identifiers", None)
        mi.comments = metadata.get("comments", None)
        mi.website = metadata.get("website", None)
        mi.source = metadata.get("source", None)
        mi.provider_key = metadata.get("provider_key", None)
        mi.provider_value = metadata.get("provider_value", None)
        mi.cover_url = metadata.get("cover_url", None)
        mi.rating = metadata.get("rating", 0)
        mi.series = metadata.get("series", None)
        mi.tags = metadata.get("tags", [])
        if "pubdate" in metadata:
            mi.pubdate = utils.parse_date(metadata["pubdate"])
        return mi

    def plugin_fill_book_cover(self, provider_key, cover_url):
        return BookSearch.get_cover(provider_key, cover_url)

    def plugin_get_book_meta(self, provider_key, provider_value, mi):
        return BookSearch.get_metadata_by_provider(provider_key, provider_value, mi)

    def reset_book_meta(self, book_id):
        book = self.get_book(book_id)
        for fmt in ["epub", "mobi", "azw", "azw3", "txt", "pdf"]:
            book_path = book.get("fmt_%s" % fmt, None)
            if book_path:
                break
        if not book_path:
            return {"err": "params.book.invalid", "msg": _("书籍不存在")}
        logging.info("[RESET]reset book meta for %d, path=%s" % (book_id, book_path))

        from calibre.ebooks.metadata.meta import get_metadata
        from calibre.utils.date import now as nowf
        book_name = os.path.basename(book_path)
        logging.info("[RESET]book name = " + repr(book_name))
        fmt = os.path.splitext(book_name)[1]
        fmt = fmt[1:] if fmt else None
        if not fmt:
            return {"err": "params.filename", "msg": _("文件名不合法")}
        fmt = fmt.lower()

        # read ebook meta
        with open(book_path, "rb") as stream:
            org_mi = get_metadata(stream, stream_type=fmt, use_libprs_metadata=True)
            org_mi.title = utils.super_strip(org_mi.title)
            org_mi.authors = [utils.super_strip(org_mi.author_sort)]
            logging.info(f"[RESET] get the book title from book file: {org_mi.title}")
            if org_mi.isbn:
                org_mi.set("isbn", utils.super_strip(org_mi.isbn))
            else:
                org_mi.set("isbn", "")
            if org_mi.publisher:
                org_mi.set("publisher", utils.super_strip(org_mi.publisher))
            else:
                org_mi.set("publisher", "")
            if org_mi.tags:
                org_mi.set("tags", [utils.super_strip(t) for t in org_mi.tags])
            else:
                org_mi.set("tags", [])
            if org_mi.series:
                org_mi.set("series", utils.super_strip(org_mi.series))
            else:
                org_mi.set("series", "")
            if org_mi.series_index:
                try:
                    org_mi.set("series_index", float(org_mi.series_index))
                except Exception:
                    org_mi.set("series_index", 1.0)
        if org_mi.title and org_mi.title == CALIBRE_ERROR_FLAG:
            return {"err": "book.invalid", "msg": _("此书籍文件无法识别, 或者受DRM保护无法处理")}

        if fmt == "txt":
            org_mi.title = book.get("title", book_name[:-4])
            org_mi.authors = [_("佚名")]
        elif fmt == "pdf":
            org_mi.title = book.get("title", org_mi.title)
            org_mi.authors = [_("佚名")]

        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _("无权限")}

        org_mi.set("comments", _(""))
        if org_mi.get("comments", "") == "":
            org_mi.set("comments", _("无详细介绍"))
        dynamic_cover = False
        if CONF.get("USE_DYNAMIC_COVER", False) and org_mi.cover_data is not None:
            (data, mime) = org_mi.cover_data
            if data is None and mime is None:
                author = org_mi.authors[0] if org_mi.authors else _("佚名")
                data = CoverGenerator.generate_cover(org_mi.title, author)
                if data:
                    org_mi.cover_data = ("jpeg", data)
                    dynamic_cover = True
        org_mi.timestamp = nowf()
        self.calibre_db.set_metadata(book_id, org_mi, force_changes=True)
        self.calibre_db_cache.set_field(CALIBRE_COLUMN_CATEGORY, {book_id: ""})
        self.calibre_db_cache.set_field(CALIBRE_COLUMN_DYNAMIC_COVER, {book_id: 1 if dynamic_cover else 0})

        return {"err": "ok", "book_id": book_id}

    @js
    @auth
    async def get(self, id):
        book_id = int(id)
        # 优先使用URL参数中的书籍信息，避免查询数据库
        title = self.get_argument('title', "")
        isbn = self.get_argument('isbn', "")
        publisher = self.get_argument('publisher', "")

        # 如果参数不完整，则查询数据库获取（保持向后兼容）
        if not title and not isbn:
            mi = self.calibre_db.get_metadata(book_id, index_is_id=True)
            title = title or mi.title
            isbn = isbn or mi.isbn
            publisher = publisher or mi.publisher

        logging.info(f"BookRefer: Searching for book meta with title='{title}', isbn='{isbn}', publisher='{publisher}'")
        key = self._build_search_key(title, isbn, publisher)
        cached_books = self._get_cached_books(key)
        if cached_books is not None:
            return {"err": "ok", "books": self._format_refer_books(cached_books, ), "cached": True}

        semaphore = self._get_search_semaphore()
        loop = asyncio.get_running_loop()

        async with semaphore:
            created = False
            with self._search_state_lock:
                fut = self._search_inflight.get(key)
                if fut is None:
                    fut = loop.run_in_executor(
                        self._search_executor,
                        BookSearch.search_books,
                        title,
                        isbn,
                        publisher,
                    )
                    self._search_inflight[key] = fut
                    created = True

            if created:
                fut.add_done_callback(lambda f, _key=key: self._cleanup_inflight(_key, f))

            search_timeout = float(CONF.get("REFER_SEARCH_TIMEOUT", 60))
            try:
                books = await asyncio.wait_for(asyncio.shield(fut), timeout=search_timeout)
            except asyncio.TimeoutError:
                logging.warning("BookRefer search timeout: key=%s", key)
                fallback = self._get_cached_books(key) or []
                return {"err": "timeout", "books": self._format_refer_books(fallback), "msg": _("查询超时，请稍后重试")}
            except Exception as e:
                logging.error("BookRefer search failed: %s", e)
                fallback = self._get_cached_books(key) or []
                return {"err": "search.failed", "books": self._format_refer_books(fallback), "msg": _("查询失败，请稍后重试")}

        books = books or []
        if books:
            self._set_cached_books(key, books)
        return {"err": "ok", "books": self._format_refer_books(books)}

    @js
    @auth
    def post(self, id):
        from calibre.utils.date import now as nowf
        should_reset = self.get_argument("reset", "no")
        provider_key = self.get_argument("provider_key", "error")
        provider_value = self.get_argument("provider_value", "")
        only_meta = self.get_argument("only_meta", "")
        only_cover = self.get_argument("only_cover", "")
        metadata = self.get_argument("metadata", "")
        if metadata:
            try:
                metadata = json.loads(metadata)
            except Exception as e:
                logging.error(f"Error parsing metadata JSON: {e}")
                return {"err": "params.invalid", "msg": _("无效的metadata参数")}
        if not self.current_user.can_edit():
            return {"err": "permission", "msg": _("无权操作")}

        book_id = int(id)
        mi = self.calibre_db.get_metadata(book_id, index_is_id=True)
        if not mi:
            return {"err": "params.book.invalid", "msg": _("书籍不存在")}
        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _("无权限")}

        if should_reset == "yes":
            return self.reset_book_meta(book_id)

        if not provider_key:
            return {"err": "params.provider_key.invalid", "msg": _("请求参数错误")}
        if not provider_value:
            return {"err": "params.provider_key.invalid", "msg": _("请求参数错误")}
        if only_meta == "yes" and only_cover == "yes":
            return {"err": "params.conflict", "msg": _("参数冲突")}

        if provider_key in (douban.KEY, youshu.KEY):
            try:
                refer_mi = self.plugin_get_book_meta(provider_key, provider_value, mi)
                if not refer_mi:
                    return {"err": "plugin.no_result", "msg": _("未找到相关信息或被限制访问，频繁出现请稍后再试，或查看日志确认原因")}
                # Correct the author if douban detail not return authors
                if not refer_mi.authors or (len(refer_mi.authors) == 1 and refer_mi.authors[0] in ("佚名", "")):
                    refer_mi.author_sort = metadata.get("author_sort", None) if metadata else mi.author_sort
                    refer_mi.authors = metadata.get("authors", []) if metadata else mi.authors
            except Exception as e:
                logging.error(f"Error fetching book meta from plugin {provider_key}: {e}")
                return {"err": "plugin.no_result", "msg": _("未找到相关信息或被限制访问，频繁出现请稍后再试，或查看日志确认原因")}
        else:
            refer_mi = self._convert_to_metadata(metadata) if metadata else mi
            if only_meta != "yes":
                try:
                    cover_url = metadata.get("cover_url") if metadata else None
                    refer_mi.cover_data = self.plugin_fill_book_cover(provider_key, cover_url)
                except Exception as e:
                    logging.error(f"Error filling book metadata from plugin {provider_key}: {e}")

        if not refer_mi:
            return {"err": "plugin.fail", "msg": _("拉取图书信息异常，请重试")}

        if only_cover == "yes":
            # just set cover
            if not refer_mi.cover_data:
                return {"err": "plugin.no_cover", "msg": _("未找到封面信息")}
            mi.cover_data = refer_mi.cover_data
        else:
            if only_meta == "yes":
                refer_mi.cover_data = None
            if len(refer_mi.tags) == 0 and len(mi.tags) == 0:
                ts = []
                for tag in CONF['BOOK_NAV'].replace("=", "/").replace("\n", "/").split("/"):
                    if tag in refer_mi.title or tag in refer_mi.comments:
                        ts.append(tag)
                    elif tag in refer_mi.authors:
                        ts.append(tag)
                if len(ts) > 0:
                    mi.tags += ts[:8]
                    logging.info("tags are %s" % ','.join(mi.tags))
                    self.calibre_db.set_tags(book_id, mi.tags)
            mi.smart_update(refer_mi, replace_metadata=True)

        mi.timestamp = nowf()
        self.calibre_db.set_metadata(book_id, mi, force_changes=True)
        return {"err": "ok"}


class BookCover(BaseHandler):
    def generate_default_cover(self, book_id, mi):
        from calibre.utils.date import now as nowf
        title = mi.title if mi.title else _("未知书籍")
        author = mi.authors[0] if mi.authors else _("佚名")
        cover_data = CoverGenerator.generate_cover(title, author)
        if cover_data:
            mi.cover_data = ("jpeg", cover_data)
            mi.timestamp = nowf()
            self.calibre_db.set_metadata(book_id, mi)
            self.calibre_db_cache.set_field(CALIBRE_COLUMN_DYNAMIC_COVER, {book_id: 1})
            return {"err": "ok", "msg": _("已生成默认封面")}
        else:
            return {"err": "cover.generate_failed", "msg": _("生成封面失败")}

    @js
    @auth
    def post(self, id):
        from calibre.utils.date import now as nowf
        book_id = int(id)
        mi = self.calibre_db.get_metadata(book_id, index_is_id=True)
        if not mi:
            return {"err": "params.book.invalid", "msg": _("书籍不存在")}

        fileinfo = self.request.files.get('cover_data')
        if not fileinfo:
            # 生成默认封面
            return self.generate_default_cover(book_id, mi)

        fileinfo = fileinfo[0]
        # Prepare cover data as (format, bytes) tuple for Calibre API
        img_data = fileinfo['body']
        # Determine image format from filename or content_type
        ext = os.path.splitext(fileinfo['filename'])[1].lower().lstrip('.')
        if not ext and 'content_type' in fileinfo:
            ext = fileinfo['content_type'].split('/')[-1]
        mi.cover_data = (ext or None, img_data)
        mi.timestamp = nowf()

        self.calibre_db.set_metadata(book_id, mi)
        self.calibre_db_cache.set_field(CALIBRE_COLUMN_DYNAMIC_COVER, {book_id: 0})
        return {"err": "ok"}


class BookCropCover(BaseHandler):
    @js
    @auth
    def post(self):
        from calibre.utils.date import now as nowf
        data = tornado.escape.json_decode(self.request.body) if self.request.body else {}
        book_ids = []
        if "id" in data:
            book_ids.append(int(data["id"]))
        elif "ids" in data:
            book_ids.extend([int(x) for x in data["ids"]])
        else:
            req_id = self.get_argument("id", None)
            if req_id:
                book_ids.append(int(req_id))
            else:
                req_ids = self.get_arguments("ids")
                if req_ids:
                    book_ids.extend([int(x) for x in req_ids])

        if not book_ids:
            return {"err": "params.invalid", "msg": _("请指定书籍ID")}

        updated_count = 0
        failed_count = 0

        for book_id in book_ids:
            if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
                failed_count += 1
                continue
            try:
                # 获取当前封面
                cover_data = self.calibre_db.cover(book_id, index_is_id=True)
                if not cover_data:
                    logging.info("Book %d cover data is empty, skipped cropping." % book_id)
                    failed_count += 1
                    continue

                new_cover_bytes = ImageHelper.crop_white_borders(cover_data)
                if new_cover_bytes:
                    mi = self.calibre_db.get_metadata(book_id, index_is_id=True)
                    if mi:
                        mi.cover_data = ("jpeg", new_cover_bytes)
                        mi.timestamp = nowf()
                        self.calibre_db.set_metadata(book_id, mi)
                        self.calibre_db_cache.set_field(CALIBRE_COLUMN_DYNAMIC_COVER, {book_id: 0})
                        updated_count += 1
            except Exception as e:
                logging.error(f"Error cropping cover for book {book_id}: {e}")
                logging.error(traceback.format_exc())
                failed_count += 1

        return {
            "err": "ok",
            "msg": _("处理完成，成功更新 %d 本，跳过/失败 %d 本。") % (updated_count, len(book_ids) - updated_count),
            "data": {
                "updated": updated_count,
                "failed": len(book_ids) - updated_count
            }
        }


class BookFavorite(BaseHandler):
    @js
    @auth
    def post(self, id):
        """设置或取消收藏某本书"""
        book_id = int(id)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍已不存在")}

        user_id = self.user_id()
        data = tornado.escape.json_decode(self.request.body)
        favorite_status = data.get("favorite", False)

        # 查找或创建阅读状态记录
        reading_state = self.sqlite_session.query(ReadingState).filter(
            ReadingState.book_id == book_id,
            ReadingState.reader_id == user_id
        ).first()

        if not reading_state:
            reading_state = ReadingState(book_id, user_id)
            self.sqlite_session.add(reading_state)

        # 设置收藏状态
        reading_state.set_favorite(favorite_status)
        reading_state.save()

        action = "收藏" if favorite_status else "取消收藏"
        return {"err": "ok", "msg": _("%s成功") % action}

    @js
    @auth
    def get(self):
        """获取当前用户的收藏"""
        user_id = self.user_id()
        logging.info("User %d is fetching favorite books." % user_id)
        # 列出所有收藏书籍
        reading_states = self.sqlite_session.query(ReadingState).filter(
            ReadingState.reader_id == user_id,
            ReadingState.favorite == 1
        ).order_by(ReadingState.favorite_date.desc()).all()

        # 批量获取所有书籍
        book_ids = [state.book_id for state in reading_states]
        books_dict = {book['id']: book for book in self.get_books(ids=book_ids)}

        # 构建书籍状态字典
        state_dict = {state.book_id: state for state in reading_states}

        favorite_books = []
        for book_id in book_ids:
            book = books_dict.get(book_id)
            if not book:
                continue
            book_data = BookFormatter(self, book).format()
            book_data["state"] = ReadingStateFormatter.format_reading_state(state_dict[book_id])
            favorite_books.append(book_data)

        return {"err": "ok",
                "title": _("我的收藏"),
                "total": len(favorite_books),
                "books": favorite_books}


class BookWantToRead(BaseHandler):
    @js
    @auth
    def post(self, id):
        """设置或取消待读某本书"""
        book_id = int(id)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍已不存在")}

        user_id = self.user_id()
        data = tornado.escape.json_decode(self.request.body)
        wants_status = data.get("wants", False)

        # 查找或创建阅读状态记录
        reading_state = self.sqlite_session.query(ReadingState).filter(
            ReadingState.book_id == book_id,
            ReadingState.reader_id == user_id
        ).first()

        if not reading_state:
            reading_state = ReadingState(book_id, user_id)
            self.sqlite_session.add(reading_state)

        # 设置待读状态
        reading_state.set_wants(wants_status)
        reading_state.save()

        action = "标记为待读" if wants_status else "取消待读"
        return {"err": "ok", "msg": _("%s成功") % action}

    @js
    @auth
    def get(self):
        """获取当前用户对某本书的待读状态"""
        user_id = self.user_id()
        logging.info("User %d is fetching favorite books." % user_id)
        reading_states = self.sqlite_session.query(ReadingState).filter(
            ReadingState.reader_id == user_id,
            ReadingState.wants == 1
        ).order_by(ReadingState.wants_date.desc()).all()

        # 批量获取所有书籍
        book_ids = [state.book_id for state in reading_states]
        books_dict = {book['id']: book for book in self.get_books(ids=book_ids)}

        # 构建书籍状态字典
        state_dict = {state.book_id: state for state in reading_states}

        favorite_books = []
        for book_id in book_ids:
            book = books_dict.get(book_id)
            if not book:
                continue
            book_data = BookFormatter(self, book).format()
            book_data["state"] = ReadingStateFormatter.format_reading_state(state_dict[book_id])
            favorite_books.append(book_data)

        return {"err": "ok",
                "title": _("待读清单"),
                "total": len(favorite_books),
                "books": favorite_books}


class BookReading(BaseHandler):
    @js
    @auth
    def get(self):
        """获取当前用户的在读书籍"""
        user_id = self.user_id()
        logging.info("User %d is fetching reading books." % user_id)
        reading_states = self.sqlite_session.query(ReadingState).filter(
            ReadingState.reader_id == user_id,
            ReadingState.read_state == 1  # 在读状态
        ).order_by(ReadingState.read_date.desc()).all()

        # 批量获取所有书籍
        book_ids = [state.book_id for state in reading_states]
        books_dict = {book['id']: book for book in self.get_books(ids=book_ids)}

        # 构建书籍状态字典
        state_dict = {state.book_id: state for state in reading_states}

        reading_books = []
        for book_id in book_ids:
            book = books_dict.get(book_id)
            if not book:
                continue
            book_data = BookFormatter(self, book).format()
            book_data["state"] = ReadingStateFormatter.format_reading_state(state_dict[book_id])
            reading_books.append(book_data)

        return {"err": "ok",
                "title": _("在读书籍"),
                "total": len(reading_books),
                "books": reading_books}


class PrintBooks(BaseHandler):
    @js
    def get(self):
        title = _("实体书")

        # 查询所有实体书，按添加时间倒序排列
        db_items = self.sqlite_session.query(Item).filter(
            Item.book_type == BOOK_TYPE_PHYSICAL
        ).order_by(Item.create_time.desc())
        total_cnt = db_items.count()

        try:
            start = self.get_argument_start()
            delta = CONF.get("DEFAULT_PAGE_SIZE", 60)
            items = db_items.limit(delta).offset(start).all()
            ids = [item.book_id for item in items]
            books = self.get_books(ids=ids)
            books.sort(key=lambda x: x["id"], reverse=True)

            books_result = []
            for book in books:
                book_data = BookFormatter(self, book).format()
                books_result.append(book_data)

            return {"err": "ok",
                    "title": title,
                    "total": total_cnt,
                    "books": books_result}
        except Exception as e:
            traceback.print_exc()
            logging.error("Failed to get print books: %s", e)
            return {"err": "internal", "msg": _("获取实体书失败")}


class BookSoled(BaseHandler):
    @js
    @auth
    def get(self):
        """获取当前用户设为soled的所有图书信息"""
        user_id = self.user_id()
        title = _("私有书籍")

        # 查询当前用户设为sole的所有图书，按添加时间倒序排列
        db_items = self.sqlite_session.query(Item).filter(
            Item.collector_id == user_id,
            Item.sole == 1
        ).order_by(Item.create_time.desc())

        try:
            start = self.get_argument_start()
            delta = 60
            items = db_items.limit(delta).offset(start).all()
            ids = [item.book_id for item in items]
            total_items = 0

            if len(ids) > 0:
                # 获取总数用于分页
                total_items = self.sqlite_session.query(Item).filter(
                    Item.collector_id == user_id,
                    Item.sole == 1
                ).count()

            books = self.get_books(ids=ids)
            books.sort(key=lambda x: x["id"], reverse=True)

            books_result = []
            for book in books:
                book_data = BookFormatter(self, book).format()
                books_result.append(book_data)

            return {"err": "ok",
                    "title": title,
                    "total": total_items,
                    "books": books_result}
        except Exception as e:
            import traceback
            traceback.print_exc()
            logging.error("Failed to get soled books: %s", e)
            return {"err": "internal", "msg": _("获取私有书籍失败")}


class BookReadDone(BaseHandler):
    @js
    @auth
    def get(self):
        """获取当前用户的已读完书籍"""
        user_id = self.user_id()
        logging.info("User %d is fetching read done books." % user_id)
        reading_states = self.sqlite_session.query(ReadingState).filter(
            ReadingState.reader_id == user_id,
            ReadingState.read_state == 2  # 已读完状态
        ).order_by(ReadingState.read_date.desc()).all()

        # 批量获取所有书籍
        book_ids = [state.book_id for state in reading_states]
        books_dict = {book['id']: book for book in self.get_books(ids=book_ids)}

        # 构建书籍状态字典
        state_dict = {state.book_id: state for state in reading_states}

        read_done_books = []
        for book_id in book_ids:
            book = books_dict.get(book_id)
            if not book:
                continue
            book_data = BookFormatter(self, book).format()
            book_data["state"] = ReadingStateFormatter.format_reading_state(state_dict[book_id])
            read_done_books.append(book_data)

        return {"err": "ok",
                "title": _("已读完书籍"),
                "total": len(read_done_books),
                "books": read_done_books}


class BookReadingStats(BaseHandler):
    @js
    @auth
    def get(self):
        """获取当前用户的阅读统计信息"""
        import datetime
        from sqlalchemy import extract

        user_id = self.user_id()
        logging.info("User %d is fetching reading statistics." % user_id)

        # 获取当前月份和年份
        now = datetime.datetime.now()
        current_year = now.year
        current_month = now.month

        # 总体统计
        total_reading = self.sqlite_session.query(ReadingState).filter(
            ReadingState.reader_id == user_id,
            ReadingState.read_state == 1  # 在读
        ).count()

        total_read_done = self.sqlite_session.query(ReadingState).filter(
            ReadingState.reader_id == user_id,
            ReadingState.read_state == 2  # 已读完
        ).count()

        # 本月统计 - 在读（本月设置为在读状态的书籍）
        month_reading = self.sqlite_session.query(ReadingState).filter(
            ReadingState.reader_id == user_id,
            ReadingState.read_state == 1,
            extract('year', ReadingState.read_date) == current_year,
            extract('month', ReadingState.read_date) == current_month
        ).count()

        # 本月统计 - 已读完（本月读完的书籍）
        month_read_done = self.sqlite_session.query(ReadingState).filter(
            ReadingState.reader_id == user_id,
            ReadingState.read_state == 2,
            extract('year', ReadingState.read_date) == current_year,
            extract('month', ReadingState.read_date) == current_month
        ).count()

        # 本月读完的书籍列表
        month_read_done_states = self.sqlite_session.query(ReadingState).filter(
            ReadingState.reader_id == user_id,
            ReadingState.read_state == 2,
            extract('year', ReadingState.read_date) == current_year,
            extract('month', ReadingState.read_date) == current_month
        ).order_by(ReadingState.read_date.desc()).limit(12).all()

        month_read_done_books = []
        for state in month_read_done_states:
            book = self.get_book(state.book_id, raise_exception=False)
            if not book:
                continue
            book_data = BookFormatter(self, book).format()
            book_data["state"] = ReadingStateFormatter.format_reading_state(state)
            month_read_done_books.append(book_data)

        # 当前在读的书籍列表
        current_reading_states = self.sqlite_session.query(ReadingState).filter(
            ReadingState.reader_id == user_id,
            ReadingState.read_state == 1
        ).order_by(ReadingState.read_date.desc()).limit(12).all()

        current_reading_books = []
        for state in current_reading_states:
            book = self.get_book(state.book_id, raise_exception=False)
            if not book:
                continue
            book_data = BookFormatter(self, book).format()
            book_data["state"] = ReadingStateFormatter.format_reading_state(state)
            current_reading_books.append(book_data)

        return {
            "err": "ok",
            "stats": {
                "total_reading": total_reading,
                "total_read_done": total_read_done,
                "month_reading": month_reading,
                "month_read_done": month_read_done,
                "current_year": current_year,
                "current_month": current_month
            },
            "month_read_done_books": month_read_done_books,
            "current_reading_books": current_reading_books
        }


class BookReadingState(BaseHandler):
    @js
    @auth
    def post(self, id):
        """设置某本书的阅读状态"""
        book_id = int(id)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍已不存在")}

        user_id = self.user_id()
        data = tornado.escape.json_decode(self.request.body)
        read_state = data.get("read_state", 0)

        # 验证阅读状态值
        if read_state not in [0, 1, 2]:
            return {"err": "params.invalid", "msg": _("阅读状态参数错误")}

        # 查找或创建阅读状态记录
        reading_state = self.sqlite_session.query(ReadingState).filter(
            ReadingState.book_id == book_id,
            ReadingState.reader_id == user_id
        ).first()

        if not reading_state:
            reading_state = ReadingState(book_id, user_id)
            self.sqlite_session.add(reading_state)

        # 设置阅读状态
        reading_state.set_read_state(read_state)

        # 如果是在线阅读或下载操作，同时更新相应状态
        if data.get("online_read") is not None:
            reading_state.set_online_read(data["online_read"])
        if data.get("download") is not None:
            reading_state.set_download(data["download"])

        reading_state.save()

        state_names = {0: "未读", 1: "在读", 2: "已读完"}
        return {"err": "ok", "msg": _("阅读状态已设置为：%s") % state_names[read_state]}

    @js
    @auth
    def get(self, id):
        """获取当前用户对某本书的阅读状态"""
        book_id = int(id)
        user_id = self.user_id()

        reading_state = self.sqlite_session.query(ReadingState).filter(
            ReadingState.book_id == book_id,
            ReadingState.reader_id == user_id
        ).first()

        return ReadingStateFormatter.format_reading_state_with_api_format(reading_state)


class BookEdit(BaseHandler):
    KEYS = [
        "authors",
        "title",
        "comments",
        "tags",
        "publisher",
        "isbn",
        "series",
        "series_index",
        "rating",
        "languages",
    ]

    def _is_html_content(self, content: str) -> bool:
        if not content:
            return False
        html_pattern = re.compile(r'<[^>]+>')
        return bool(html_pattern.search(content))

    def edit_book(self, bid, data):
        from calibre.utils.date import now as nowf
        mi = self.calibre_db.get_metadata(bid, index_is_id=True, get_cover=True)
        need_update_cover = False
        if CONF.get("USE_DYNAMIC_COVER", False) and data.get("title", None) and data["title"] != mi.title:
            fmt, cover_data = mi.cover_data if mi.cover_data else (None, None)
            if cover_data is not None or mi.cover:
                dynamic_cover_flag = self.calibre_db.get_custom(bid, label=COLUMN_DYNAMIC_COVER, index_is_id=True)
                need_update_cover = dynamic_cover_flag == 1
            else:
                need_update_cover = True

        for key, val in data.items():
            if key not in self.KEYS:
                continue
            if key == "comments" and not self._is_html_content(val):
                # replace the line break with <br/> to avoid losing line break when display in web
                val = val.replace("\n", "<br/>")
            mi.set(key, val)

        if data.get("pubdate", None):
            content = douban.str2date(data["pubdate"])
            if content is None:
                return {"err": "params.pudate.invalid", "msg": _("出版日期参数错误，格式应为 2026-05-10或2026-05或2026年或2026")}
            mi.set("pubdate", content)

        if data.get("book_count", None):
            book_cnt = data.get("book_count", 0)
            if data.get("book_type", BOOK_TYPE_EBOOK) == BOOK_TYPE_PHYSICAL:
                mi.set(CALIBRE_COLUMN_PHY_COUNT, book_cnt)
                mi.set(CALIBRE_COLUMN_BOOK_TYPE, BOOK_TYPE_PHYSICAL)
            else:
                mi.set(CALIBRE_COLUMN_PHY_COUNT, 0)
                mi.set(CALIBRE_COLUMN_BOOK_TYPE, BOOK_TYPE_EBOOK)
            # Need to update the item too
            existing_item = self.sqlite_session.query(Item).filter(Item.book_id == bid).first()
            if existing_item:
                existing_item.book_count = book_cnt
                self.sqlite_session.add(existing_item)
                self.sqlite_session.commit()
            else:
                item = Item()
                item.book_id = bid
                item.collector_id = self.user_id()
                item.book_type = data.get("book_type", BOOK_TYPE_EBOOK)
                item.book_count = book_cnt
                self.sqlite_session.add(item)
                self.sqlite_session.commit()

        if "tags" in data and not data["tags"]:
            self.calibre_db.set_tags(bid, [])

        if COLUMN_CATEGORY in data:
            category = data[COLUMN_CATEGORY].strip()
            if len(category) < 80:
                if category == '清除' or category.lower() == 'clear':
                    category = ''
                mi.set(CALIBRE_COLUMN_CATEGORY, category)
                self.calibre_db_cache.set_field(CALIBRE_COLUMN_CATEGORY, {bid: category})
            else:
                logging.error("Too many characters in the category, ignore it!")
        if COLUMN_EXT_LINK in data:
            ext_link = data[COLUMN_EXT_LINK].strip()
            if len(ext_link) < 500 and (ext_link.startswith('http://') or ext_link.startswith('https://') or ext_link == ''):
                mi.set(CALIBRE_COLUMN_EXT_LINK, ext_link)
                self.calibre_db_cache.set_field(CALIBRE_COLUMN_EXT_LINK, {bid: ext_link})
            else:
                logging.error("Too many characters in the external link, ignore it!")
        if COLUMN_LOCATION in data:
            location = data[COLUMN_LOCATION].strip()
            if len(location) < 64:
                mi.set(CALIBRE_COLUMN_LOCATION, location)
                self.calibre_db_cache.set_field(CALIBRE_COLUMN_LOCATION, {bid: location})
            else:
                logging.error("Too many characters in the location, ignore it!")

        if mi.authors:
            # authors中如果有.,则替换为·
            mi.authors = [a.replace(".", "·") for a in mi.authors]
        mi.timestamp = nowf()
        mi.title_sort = utils.get_title_sort(mi.title)
        # If the existing cover is dynamic generated, and the new title or author may cause the cover to be no longer suitable, we need to regenerate it
        if CONF.get("USE_DYNAMIC_COVER", False) and need_update_cover:
            author = mi.authors[0] if mi.authors else _("佚名")
            cover_data = CoverGenerator.generate_cover(mi.title, author)
            if cover_data:
                mi.cover_data = ("jpeg", cover_data)
        self.calibre_db.set_metadata(bid, mi, force_changes=True)
        return True

    @js
    @auth
    def post(self, bid):
        book = self.get_book(bid, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍已不存在")}
        bid = book["id"]
        update_books = []
        if isinstance(book["collector"], dict):
            cid = book["collector"]["id"]
        else:
            cid = book["collector"].id
        if not self.current_user.can_edit() or not (self.is_admin() or self.is_book_owner(bid, cid)):
            return {"err": "permission", "msg": _("无权操作")}

        data = tornado.escape.json_decode(self.request.body)
        logging.debug(f"Book edit data: {data}")
        id_list = data.get("ids", None)
        if id_list and bid in id_list:
            # 仅当有列表，且当前书籍在列表中时，才进行批量更新
            for bid in id_list:
                self.edit_book(bid, data)
                update_books.append(bid)
            return {"err": "ok", "msg": _("更新成功"), "books": update_books}
        else:
            self.edit_book(bid, data)
            update_books = [bid]
        return {"err": "ok", "msg": _("更新成功"), "books": update_books}


class BookDelete(BaseHandler):
    @js
    @auth
    def post(self, bid):
        book = self.get_book(bid)
        bid = book["id"]

        if isinstance(book["collector"], dict):
            cid = book["collector"]["id"]
        else:
            cid = book["collector"].id
        if not self.current_user.can_edit() or not (self.is_admin() or self.is_book_owner(bid, cid)):
            return {"err": "permission", "msg": _("无权操作")}

        if not self.current_user.can_delete() or not (self.is_admin() or self.is_book_owner(bid, cid)):
            return {"err": "permission", "msg": _("无权操作")}

        # 删除整本书
        AudioUtils.clear_audio(bid)
        if self.delete_book(bid, book.get("title", "")):
            return {"err": "ok", "msg": _("删除成功")}
        return {"err": "fail", "msg": _("删除失败, 请查看日志。如果一直出错，请联系管理员。")}


class BookDeleteFormat(BaseHandler):
    @js
    @auth
    def post(self, bid):
        book = self.get_book(bid, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍已不存在")}
        bid = book["id"]

        if isinstance(book["collector"], dict):
            cid = book["collector"]["id"]
        else:
            cid = book["collector"].id
        if not self.current_user.can_edit() or not (self.is_admin() or self.is_book_owner(bid, cid)):
            return {"err": "permission", "msg": _("无权操作")}

        if not self.current_user.can_delete() or not (self.is_admin() or self.is_book_owner(bid, cid)):
            return {"err": "permission", "msg": _("无权操作")}

        try:
            data = tornado.escape.json_decode(self.request.body)
            fmt = data.get("format", "").strip().lower()
        except:
            return {"err": "params.invalid", "msg": _("请求参数格式错误")}

        if not fmt:
            return {"err": "params.missing", "msg": _("格式参数不能为空")}

        fmt_key = "fmt_%s" % fmt
        if fmt_key not in book:
            return {"err": "format.not_found", "msg": _("书籍不包含 %s 格式") % fmt.upper()}

        # 检查书籍是否只有一个格式
        available_formats = book.get("available_formats", "")
        available_formats = [f.strip() for f in available_formats if f.strip()]
        if len(available_formats) <= 1:
            return {"err": "last.format", "msg": _("书籍只有一个格式，无法刪除")}

        try:
            self.calibre_db_cache.remove_formats({bid: [fmt.upper()]})
            self.add_msg("success", _("删除书籍《%s》的%s格式") % (book["title"], fmt))
            return {"err": "ok", "msg": _("删除%s格式成功" % fmt)}
        except Exception as e:
            logging.error(f"删除书籍《{book['title']}》的{fmt}格式失败: {e}")
            return {"err": "fail", "msg": _("删除%s格式失败, 请查看日志。如果一直出错，请联系管理员。" % fmt)}


class BookDownload(BaseHandler, web.StaticFileHandler):
    def send_error_of_not_invited(self):
        self.set_header("WWW-Authenticate", "Basic")
        self.set_status(401)
        raise web.Finish()

    def initialize(self):
        self.root = "/"
        self.default_filename = None
        self.is_opds = self.get_argument("from", "") == "opds"
        BaseHandler.initialize(self)

    def prepare(self):
        BaseHandler.prepare(self)
        if not CONF["ALLOW_GUEST_DOWNLOAD"] and not self.current_user:
            if self.is_opds:
                return self.send_error_of_not_invited()
            else:
                return self.redirect("/login")

        if self.current_user:
            if self.current_user.can_save():
                if not self.current_user.is_active():
                    raise web.HTTPError(403, reason=_("无权操作，请先登录注册邮箱激活账号。"))
            else:
                raise web.HTTPError(403, reason=_("无权操作"))

    def parse_url_path(self, url_path: str) -> str:
        filename = url_path.split("/")[-1]
        bid, fmt = filename.split(".")
        fmt = fmt.lower()
        logging.error("download %s bid=%s, fmt=%s" % (filename, bid, fmt))
        book = self.get_book(bid)
        book_id = book["id"]
        self.increase_history_count("download_history")
        self.count_increase(book_id, count_download=1)
        if "fmt_%s" % fmt not in book:
            raise web.HTTPError(404, reason=_("%s格式无法下载" % fmt))

        path = book["fmt_%s" % fmt]
        book["fmt"] = fmt
        book["title"] = urllib.parse.quote_plus(book["title"][:128])
        fname = "%(id)d-%(title)s.%(fmt)s" % book
        att = "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (fname, fname)
        if self.is_opds:
            att = 'attachment; filename="%(id)d.%(fmt)s"' % book

        self.set_header("Content-Disposition", att.encode("UTF-8"))
        self.set_header("Content-Type", "application/octet-stream")
        return path

    @classmethod
    def get_absolute_path(cls, root: str, path: str) -> str:
        return path


class BookNav(ListHandler):
    @js
    def get(self):
        tagmap = self.all_tags_with_count()
        navs = []
        done = set()
        for line in CONF['BOOK_NAV'].split("\n"):
            line = utils.super_strip(line)
            p = line.split("=")
            if len(p) != 2:
                continue
            h1, tags = p
            tags = [v.strip() for v in tags.split("/")]
            done.update(tags)
            tag_items = [{"name": v, "count": tagmap.get(v, 0)} for v in tags if tagmap.get(v, 0) > 0]
            if tag_items:
                navs.append({"legend": h1, "tags": tag_items})

        tag_items = [{"name": tag, "count": cnt} for tag, cnt in tagmap.items() if tag not in done]
        navs.append({"legend": _("其他"), "tags": tag_items})

        return {"err": "ok", "navs": navs}


class RecentBook(ListHandler):
    def get(self):
        title = _("新书推荐")
        ids = self.books_by_id()
        return self.render_book_list([], ids=ids, title=title, sort_fields="id")


class SearchBook(ListHandler):
    CALIBRE_KEYS = ("title:", "authors:", "comments:", "publisher:", "isbn:", "publisher:", "series:", "tags:", "author:", "py:")

    def _clear(self, text):
        # 去除字串中的括号及其内容，以免影响查询
        if not text:
            return text
        text = re.sub(r"\([^)]*\)|（[^）]*）", " ", text)
        text = text.replace("(", " ").replace(")", " ")
        return text.strip()

    def _add_books(self, result_ids, ids, seen):
        if not result_ids:
            return
        for bid in result_ids:
            if bid not in seen:
                ids.append(bid)
                seen.add(bid)

    def _search_by_segmentation(self, name, ids, seen):
        if not JIEBA_AVAILABLE or not (2 < len(name) < 10):
            return None

        start = time.time()
        or_query = None

        try:
            # 对name进行分词
            words = jieba.cut(name)
            # 过滤分词结果：排除等于name本身的词和长度为1的词，并去重
            filtered_words = list({w for w in words if w != name and len(w) > 1})

            if filtered_words and len(filtered_words) > 1:
                logging.info(f"Word segmentation for '{name}': {filtered_words}")
                # 1. 先查所有分词都包含的书（AND查询）
                try:
                    and_query = " AND ".join([f'title:"{word}"' for word in filtered_words])
                    and_ids = self.calibre_db_cache.search(and_query)
                    if and_ids:
                        self._add_books(and_ids, ids, seen)
                        logging.info(f"Found {len(and_ids)} books for AND of segmented words: {filtered_words}")
                except Exception as e:
                    logging.error("Search book by AND segmented words failed: %s" % e)

                # OR查询放到后面与其他查询合并
                or_query = " OR ".join([f'title:"{word}"' for word in filtered_words])
        except Exception as e:
            logging.error(f"Word segmentation failed for '{name}': %s" % e)
        logging.info(f"[TRACE]Word segmentation search took {time.time() - start:.2f} seconds.")
        return or_query

    def get(self):
        name = self.get_argument("name", "").strip()
        book_title = self.get_argument("title", "").strip()  # 传入此参数代表只按名称搜索
        exclude_id = int(self.get_argument("exclude", "0").strip())
        seg = int(self.get_argument("seg", "0").strip())  # 是否进行分词查询
        order_by = self.get_argument("order", "").strip()

        if not name and not book_title:
            return self.write({"err": "params.invalid", "msg": _("请输入搜索关键字")})

        title_search = len(book_title) > 0
        if title_search:
            name = book_title
        calibre_query = False
        for key in self.CALIBRE_KEYS:
            if name.startswith(key):
                calibre_query = True
                title_search = False
                name = name.replace("py:", "title_sort:")
                break

        title = _("搜索：%(name)s") % {"name": name}
        ids = []
        seen = set()
        seg_or_query = None

        if not calibre_query:
            book_title = self._clear(book_title)
            name = self._clear(name)

        # 只有当 seg=1 时才进行分词搜索
        if seg == 1 and title_search and not calibre_query:
            # 分词搜索：当name长度在2-10之间且jieba可用时
            seg_or_query = self._search_by_segmentation(name, ids, seen)

        # 简繁体转换搜索（合并为一次查询）
        start = time.time()

        if calibre_query:
            converted_names = ["( " + name + " )"]
        else:
            converted_names = [name]
        for profile in ['s2t', 't2s']:
            converted_name = opencc.OpenCC(profile).convert(name)
            if converted_name != name:
                if calibre_query:
                    converted_names.append("( " + converted_name + " )")
                else:
                    converted_names.append(converted_name)
        if converted_names:
            try:
                if seg == 1:
                    query = seg_or_query
                else:
                    if title_search:
                        # 对于精确标题搜索，构建OR查询
                        query = " OR ".join([f'title:={cn}' for cn in converted_names])
                    else:
                        # 主要是comments字段的搜索比较耗时
                        query = " OR ".join(converted_names)
                    if seg_or_query:
                        query = f"({query}) OR ({seg_or_query})"
                logging.info(f"Searching books with query: {query}")
                ids2 = None
                if query:
                    ids2 = self.calibre_db_cache.search(query)
                if ids2:
                    self._add_books(ids2, ids, seen)
            except Exception as e:
                logging.error("Search book failed: %s" % e)
                logging.error(traceback.format_exc())
        logging.info(f"[TRACE] search took {time.time() - start:.2f} seconds.")

        if exclude_id > 0 and exclude_id in seen:
            if exclude_id in ids:
                ids.remove(exclude_id)

        # 查询被别的用户标记为sole的图书ID，并将ids中对应的ID去除
        sole_book_ids = set(item.book_id for item in self.sqlite_session.query(Item).filter(Item.sole == 1, Item.collector_id != self.user_id()).all())
        ids = [book_id for book_id in ids if book_id not in sole_book_ids]

        return self.render_book_list([], ids=ids, title=title, sort_fields=order_by)


class HotBook(ListHandler):
    def get(self):
        title = _("热度榜单")
        db_items = self.sqlite_session.query(Item).filter(Item.count_visit > 1).order_by(Item.count_visit.desc())
        start = self.get_argument_start()
        delta = 60
        items = db_items.limit(delta).offset(start).all()
        ids = [item.book_id for item in items]
        return self.render_book_list([], ids=ids, title=title)


# 通ISBN添加实体图书
class BookAddByISBN(BaseHandler):
    @js
    @auth
    def post(self):
        if not self.current_user.can_upload():
            return {"err": "permission", "msg": _("无权操作")}
        data = tornado.escape.json_decode(self.request.body)
        isbn = data.get("isbn", "").strip()
        if not isbn:
            return {"err": "params.invalid", "msg": _("请输入ISBN号")}

        # 使用基类方法查找已存在的ISBN实体书
        existing_books = self.find_phy_books_by_isbn(isbn)

        # 如果已存在该ISBN的图书，更新相关计数
        if existing_books:
            book_id = list(existing_books)[0]  # 取第一个匹配的图书ID
            # 检查当前用户是否已经有该图书的Item记录
            existing_item = self.sqlite_session.query(Item).filter(
                Item.book_id == book_id
            ).first()

            book_count = 1
            if existing_item:
                book_count = (existing_item.book_count or 0) + 1
                existing_item.book_count = book_count
                self.sqlite_session.add(existing_item)
                self.sqlite_session.commit()
            else:
                item = Item()
                item.book_id = book_id
                item.collector_id = self.user_id()
                item.book_type = BOOK_TYPE_PHYSICAL
                item.book_count = book_count
                self.sqlite_session.add(item)
                self.sqlite_session.commit()

            # 更新calibre custom data
            try:
                self.calibre_db_cache.set_field(CALIBRE_COLUMN_BOOK_TYPE, {book_id: BOOK_TYPE_PHYSICAL})
                self.calibre_db_cache.set_field(CALIBRE_COLUMN_PHY_COUNT, {book_id: book_count})
            except Exception as e:
                logging.error(f"Failed to set custom fields for book ID {book_id}: {e}")

            return {"err": "ok", "msg": _("实体书数量已更新，当前数量：%d") % book_count, "book_id": book_id}

        logging.info("Adding new book by ISBN: %s" % isbn)
        try:
            # 通过 BookSearch 查询ISBN的图书信息（依次尝试豆瓣、新华书店兜底）
            book_data = BookSearch.find_physical_book_by_isbn(isbn)
            if not book_data:
                return {"err": "book.notfound", "msg": _("未找到该ISBN号对应的图书")}

            # 通过上面返回的book metadata, 添加图书到calibre中（不需要文件，仅metadata）
            book_data.title_sort = utils.get_title_sort(book_data.title)
            book_id = self.calibre_db.create_book_entry(book_data)
            if book_id is None:
                return {"err": "book.duplicate", "msg": _("该图书已存在或创建失败")}

            try:
                self.calibre_db_cache.set_field(CALIBRE_COLUMN_BOOK_TYPE, {book_id: BOOK_TYPE_PHYSICAL})
                self.calibre_db_cache.set_field(CALIBRE_COLUMN_PHY_COUNT, {book_id: 1})
                BaseHandler._physical_books_count_cache_time = 0
            except Exception as e:
                logging.error(f"Failed to set custom fields for book ID {book_id}: {e}")

            # 创建Item记录
            item = Item()
            item.book_id = book_id
            item.collector_id = self.user_id()
            item.book_type = BOOK_TYPE_PHYSICAL
            item.book_count = 1
            self.sqlite_session.add(item)
            self.sqlite_session.commit()
            return {"err": "ok", "msg": _("图书添加成功"), "book_id": book_id}
        except Exception as e:
            logging.error("Failed to add book by ISBN: %s", e)
            return {"err": "internal", "msg": _("查询ISBN失败，请在系统设置中配置互联网信息源中插件地址。如http://douban-rs-api:80/。")}


class BookUpload(BaseHandler):
    @classmethod
    def convert(cls, s):
        try:
            return s.group(0).encode("latin1").decode("utf8")
        except Exception:
            return s.group(0)

    def _add_new_book(self, mi, fpaths):
        dynamic_cover = False
        mi.title_sort = utils.get_title_sort(mi.title)
        if utils.is_traditional_chinese(mi.title):
            mi.languages = constants.TRADITIONAL_CHINESE_CODE
        if not mi.languages:
            mi.languages = CONF.get("DEFAULT_LANGUAGE", constants.DEFAULT_LANGUAGE_CODE)

        if CONF.get("USE_DYNAMIC_COVER", False):
            fmt, cover_data = mi.cover_data
            if fmt is None or cover_data is None:
                author = mi.authors[0] if mi.authors else _("佚名")
                data = CoverGenerator.generate_cover(mi.title, author)
                if data:
                    mi.cover_data = ("jpeg", data)
                    dynamic_cover = True
        book_id = self.calibre_db.import_book(mi, fpaths)
        if book_id is not None and dynamic_cover:
            try:
                self.calibre_db_cache.set_field(CALIBRE_COLUMN_DYNAMIC_COVER, {book_id: 1})
            except Exception as e:
                logging.error(f"Failed to set dynamic cover field for book ID {book_id}: {e}")
        self.increase_history_count("upload_history")
        item = Item()
        item.book_id = book_id
        item.collector_id = self.user_id()
        self.sqlite_session.add(item)
        self.sqlite_session.commit()
        if CONF.get(AUTO_FILL_META, False):
            AutoFillService().auto_fill(book_id)

        if CONF.get("SEND_MAIL_FOR_NEW_BOOKS", False) and mi.title:
            try:
                emails = []
                readers = self.sqlite_session.query(Reader).filter(Reader.active.is_(1)).all()
                for r in readers:
                    if not r.email or not r.active:
                        continue
                    if r.extra and r.extra.get("allow_sending_mail", True) is True:
                        emails.append(r.email)
                if emails:
                    site_url = self.site_url
                    if not site_url:
                        referer = self.request.headers.get("Referer", "")
                        parsed = urllib.parse.urlsplit(referer)
                        if parsed.scheme and parsed.netloc:
                            site_url = f"{parsed.scheme}://{parsed.netloc}"
                    MailService().send_new_book_notification(emails, [mi.title], site_url=site_url)
                else:
                    logging.info("No active readers with email found for new book notification.")
            except Exception as e:
                logging.error("Failed to trigger new book notification: %s", e)

        return book_id

    def get_upload_file(self):
        # for unittest mock
        if "ebook" not in self.request.files:
            return None, None
        p = self.request.files["ebook"][0]
        return (p["filename"], p["body"])

    def _add_format_to_existing_book(self, book_id):
        """向已存在的书籍添加新格式文件"""
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "book.not_found", "msg": _("书籍不存在")}

        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _("无权限")}

        name, data = self.get_upload_file()
        if name is None:
            return {"err": "params.filename", "msg": _("文件不存在或未选择文件")}

        name = re.sub(r"[\x80-\xFF]+", BookUpload.convert, name)
        name = self._sanitize_uploaded_filename(name)
        if not name:
            return {"err": "params.filename", "msg": _("文件名不合法")}
        logging.info(f"Adding format to book {book_id}, file name = {repr(name)}")

        fmt = os.path.splitext(name)[1]
        fmt = fmt[1:] if fmt else None
        if not fmt:
            return {"err": "params.filename", "msg": _("文件名不合法, 没有扩展名")}
        fmt = fmt.lower()

        if fmt not in SUPPORTED_EBOOK_FORMATS:
            return {"err": "params.format.unsupported", "msg": _("不支持的书籍格式: %s" % fmt)}

        if f"fmt_{fmt}" in book:
            return {
                "err": "format.already_exists",
                "msg": _("书籍已存在 %s 格式") % fmt.upper(),
                "book_id": book_id
            }

        try:
            fpath = self._safe_upload_path(name)
        except ValueError:
            return {"err": "params.filename", "msg": _("文件名不合法")}
        with open(fpath, "wb") as f:
            f.write(data)
        logging.info(f"Save format file to [{fpath}]")

        try:
            self.calibre_db.add_format(book_id, fmt.upper(), fpath, True)
            logging.info(f"Successfully added {fmt.upper()} format to book {book_id}")

            try:
                self.save_book_meta(book_id, fmt=fmt)
                logging.info(f"Metadata written to new format {fmt.upper()} for book {book_id}")
            except Exception as e:
                logging.warning(f"Failed to write metadata to new format: {e}")

            self.add_msg("success", _("格式添加成功！"))
            return {"err": "ok", "book_id": book_id, "msg": _("成功添加 %s 格式") % fmt.upper()}
        except Exception as e:
            logging.error(f"Failed to add format to book {book_id}: {e}")
            return {"err": "internal", "msg": _("添加格式失败: %s") % str(e)}
        finally:
            # 清理临时文件
            if os.path.exists(fpath):
                os.remove(fpath)

    @js
    def post(self):
        from calibre.ebooks.metadata.meta import get_metadata

        if CONF["ALLOW_GUEST_UPLOAD"] is False:
            if self.is_guest():
                return {"err": "permission", "msg": _("无权操作，请先登录")}
            if not self.current_user.can_upload():
                return {"err": "permission", "msg": _("无权操作")}

        # 检查是否为添加格式到已有书籍
        target_book_id = self.get_argument("bid", None)
        if target_book_id:
            return self._add_format_to_existing_book(int(target_book_id))

        name, data = self.get_upload_file()
        if name is None:
            return {"err": "params.filename", "msg": _("文件不存在或未选择文件")}

        name = re.sub(r"[\x80-\xFF]+", BookUpload.convert, name)
        name = self._sanitize_uploaded_filename(name)
        if not name:
            return {"err": "params.filename", "msg": _("文件名不合法")}
        logging.info("upload book name = " + repr(name))
        fmt = os.path.splitext(name)[1]
        fmt = fmt[1:] if fmt else None
        if not fmt:
            return {"err": "params.filename", "msg": _("文件名不合法, 没有扩展名")}
        fmt = fmt.lower()
        if fmt not in SUPPORTED_EBOOK_FORMATS:
            return {"err": "params.format.unsupported", "msg": _("不支持的书籍格式: %s" % fmt)}

        # save file
        try:
            fpath = self._safe_upload_path(name)
        except ValueError:
            return {"err": "params.filename", "msg": _("文件名不合法")}
        with open(fpath, "wb") as f:
            f.write(data)
        logging.info("save upload file into [%s]", fpath)

        # read ebook meta
        failed = False
        with open(fpath, "rb") as stream:
            mi = get_metadata(stream, stream_type=fmt, use_libprs_metadata=True)
            if mi.title and mi.title == CALIBRE_ERROR_FLAG:
                if fmt == "pdf":
                    mi.title = utils.remove_zlibrary_suffix(name.replace("." + fmt, ""))
                else:
                    logging.error("Failed to get metadata for %s, reason:%s", fpath, mi.comments)
                    failed = True
            mi.title = utils.super_strip(mi.title)
            if mi.author_sort == "Unknown" and mi.authors and len(mi.authors) > 0:
                mi.authors = [utils.super_strip(a) for a in mi.authors]
            else:
                mi.authors = [utils.super_strip(mi.author_sort)]

        if failed:
            Path(fpath).unlink(missing_ok=True)
            return {"err": "book.invalid", "msg": _("此书籍文件无法识别, 或者受DRM保护无法导入")}

        # 非结构化的格式，calibre无法识别准确的信息，直接从文件名提取
        name = name[:-len(fmt) - 1]
        if fmt == "txt":
            mi.title = utils.remove_zlibrary_suffix(name)
            title, author = utils.guess_title_author_from_filename(mi.title)
            mi.title = title if title else mi.title
            mi.authors = [author] if author else [_("佚名")]
        elif fmt == "pdf":
            if CONF["PDF_TILE_WITH_FILE_NAME"]:
                mi.title = utils.remove_zlibrary_suffix(name)
            else:
                title = mi.title.strip() if mi.title else ""
                if not title or title.find(_("下载工具")) >= 0 or title == "SSReader Print.":
                    mi.title = utils.remove_zlibrary_suffix(name)
                else:
                    mi.title = utils.remove_zlibrary_suffix(title)
            if mi.authors is None or len(mi.authors) == 0 or mi.authors[0].lower() == "unknown":
                mi.authors = [_("佚名")]

        logging.info("upload mi.title = " + repr(mi.title))
        books = self.calibre_db.books_with_same_title(mi)
        if books:
            book_id = None
            for id in books:
                b = self.calibre_db.get_metadata(id, index_is_id=True, get_user_categories=False)
                logging.info(f"book id:{id}, book_type:{b.get(CALIBRE_COLUMN_BOOK_TYPE, BOOK_TYPE_EBOOK)}")
                logging.info(f"  existed formats: {b.formats}")
                # 如果是实体书，则跳过
                if b.get(CALIBRE_COLUMN_BOOK_TYPE, BOOK_TYPE_EBOOK) == BOOK_TYPE_PHYSICAL:
                    continue
                if book_id is None:
                    book_id = b.get("id")
                if b.get("authors", "") != mi.authors:
                    continue
                if fmt.upper() in b.formats:
                    return {
                        "err": "samebook",
                        "msg": _("同名书籍《%s》已存在这一图书格式 %s") % (mi.title, fmt),
                        "book_id": b.get("id")
                    }
            logging.info("import [%s] from %s with format %s", repr(mi.title), fpath, fmt)
            if book_id is None:
                # New EBOOK
                book_id = self._add_new_book(mi, [fpath])
            else:
                self.calibre_db.add_format(book_id, fmt.upper(), fpath, True)
        else:
            fpaths = [fpath]
            book_id = self._add_new_book(mi, fpaths)
        self.add_msg("success", _("导入书籍成功！"))
        return {"err": "ok", "book_id": book_id}


class BookUploadChunk(BaseHandler):
    """Handler for chunked file upload"""

    def _add_new_book(self, mi, fpaths):
        dynamic_cover = False
        mi.title_sort = utils.get_title_sort(mi.title)
        if utils.is_traditional_chinese(mi.title):
            mi.languages = constants.TRADITIONAL_CHINESE_CODE
        if not mi.languages:
            mi.languages = CONF.get("DEFAULT_LANGUAGE", constants.DEFAULT_LANGUAGE_CODE)

        if CONF.get("USE_DYNAMIC_COVER", False):
            fmt, cover_data = mi.cover_data
            if fmt is None and cover_data is not None:
                author = mi.authors[0] if mi.authors else _("佚名")
                data = CoverGenerator.generate_cover(mi.title, author)
                if data:
                    mi.cover_data = ("jpeg", data)
                    dynamic_cover = True
        book_id = self.calibre_db.import_book(mi, fpaths)
        if book_id is not None and dynamic_cover:
            try:
                self.calibre_db_cache.set_field(CALIBRE_COLUMN_DYNAMIC_COVER, {book_id: 1})
            except Exception as e:
                logging.error(f"Failed to set dynamic cover field for book ID {book_id}: {e}")
        self.increase_history_count("upload_history")
        item = Item()
        item.book_id = book_id
        item.collector_id = self.user_id()
        self.sqlite_session.add(item)
        self.sqlite_session.commit()
        if CONF.get(AUTO_FILL_META, False):
            AutoFillService().auto_fill(book_id)

        if CONF.get("SEND_MAIL_FOR_NEW_BOOKS", False) and mi.title:
            try:
                emails = []
                readers = self.sqlite_session.query(Reader).filter(Reader.active.is_(1)).all()
                for r in readers:
                    if not r.email:
                        continue
                    if r.extra and r.extra.get("allow_sending_mail", True) is True:
                        emails.append(r.email)
                if emails:
                    site_url = self.site_url
                    if not site_url:
                        referer = self.request.headers.get("Referer", "")
                        parsed = urllib.parse.urlsplit(referer)
                        if parsed.scheme and parsed.netloc:
                            site_url = f"{parsed.scheme}://{parsed.netloc}"
                    MailService().send_new_book_notification(emails, [mi.title], site_url=site_url)
                else:
                    logging.info("No active readers with email found for new book notification.")
            except Exception as e:
                logging.error("Failed to trigger new book notification: %s", e)
        return book_id

    @staticmethod
    def get_chunk_size():
        """Get the configured chunk upload threshold size in bytes"""
        size_str = CONF.get("CHUNK_UPLOAD_SIZE", "0MB").lower().strip()
        if size_str == "0" or size_str == "0mb" or size_str == "0kb":
            return 0

        if size_str.endswith("mb"):
            return int(size_str[:-2]) * 1024 * 1024
        elif size_str.endswith("kb"):
            return int(size_str[:-2]) * 1024
        else:
            return int(size_str)

    @js
    def post(self):
        """Handle chunked upload POST requests"""
        if CONF["ALLOW_GUEST_UPLOAD"] is False:
            if self.is_guest():
                return {"err": "permission", "msg": _("无权操作，请先登录")}
            if not self.current_user.can_upload():
                return {"err": "permission", "msg": _("无权操作")}

        # Get parameters from form data
        filename = self.get_argument("filename", "")
        chunk_index = int(self.get_argument("chunk_index", 0))
        total_chunks = int(self.get_argument("total_chunks", 1))
        file_hash = self.get_argument("file_hash", "")

        if not filename:
            return {"err": "params.filename", "msg": _("文件名不能为空")}
        filename = re.sub(r"[\x80-\xFF]+", BookUpload.convert, filename)
        filename = self._sanitize_uploaded_filename(filename)
        if not filename:
            return {"err": "params.filename", "msg": _("文件名不合法")}
        logging.info("upload book name = " + repr(filename))
        fmt = os.path.splitext(filename)[1]
        fmt = fmt[1:] if fmt else None
        if not fmt:
            return {"err": "params.filename", "msg": _("文件名不合法，没有包含扩展名")}
        fmt = fmt.lower()
        if fmt not in SUPPORTED_EBOOK_FORMATS:
            return {"err": "params.format.unsupported", "msg": _("不支持的书籍格式: %s" % fmt)}

        if not file_hash:
            return {"err": "params.hash", "msg": _("文件hash不能为空")}
        if not re.fullmatch(r"[a-fA-F0-9]{8,128}", file_hash):
            return {"err": "params.hash", "msg": _("文件hash不合法")}

        # Get the chunk data
        if "chunk" not in self.request.files:
            return {"err": "params.chunk", "msg": _("未找到文件块数据")}

        chunk_file = self.request.files["chunk"][0]
        chunk_data = chunk_file["body"]

        # Create temporary directory for chunks
        temp_dir = os.path.join(CONF["upload_path"], "temp_chunks", file_hash)
        os.makedirs(temp_dir, exist_ok=True)

        # Save current chunk
        chunk_path = os.path.join(temp_dir, f"chunk_{chunk_index}")
        with open(chunk_path, "wb") as f:
            f.write(chunk_data)

        # Check if all chunks are received
        received_chunks = []
        for i in range(total_chunks):
            chunk_file_path = os.path.join(temp_dir, f"chunk_{i}")
            if os.path.exists(chunk_file_path):
                received_chunks.append(i)

        if len(received_chunks) == total_chunks:
            # All chunks received, merge them
            return self._merge_chunks_and_import(filename, file_hash, total_chunks, temp_dir)
        else:
            # Still waiting for more chunks
            return {
                "err": "ok",
                "msg": _("分块上传成功"),
                "received_chunks": len(received_chunks),
                "total_chunks": total_chunks
            }

    def _merge_chunks_and_import(self, filename, file_hash, total_chunks, temp_dir):
        """Merge all chunks and import the book"""
        from calibre.ebooks.metadata.meta import get_metadata

        try:
            # Clean filename
            filename = re.sub(r"[\x80-\xFF]+", BookUpload.convert, filename)
            filename = self._sanitize_uploaded_filename(filename)
            if not filename:
                return {"err": "params.filename", "msg": _("文件名不合法")}
            fmt = os.path.splitext(filename)[1]
            fmt = fmt[1:] if fmt else None
            if not fmt:
                return {"err": "params.filename", "msg": _("文件名不合法")}
            fmt = fmt.lower()

            # Merge chunks into final file
            try:
                final_path = self._safe_upload_path(filename)
            except ValueError:
                return {"err": "params.filename", "msg": _("文件名不合法")}
            with open(final_path, "wb") as outfile:
                for i in range(total_chunks):
                    chunk_path = os.path.join(temp_dir, f"chunk_{i}")
                    with open(chunk_path, "rb") as chunk_file:
                        outfile.write(chunk_file.read())

            # Clean up temporary chunks
            import shutil
            shutil.rmtree(temp_dir)

            logging.info("Merged chunked upload file into [%s]", final_path)

            # Read ebook metadata (same logic as BookUpload)
            failed = False
            with open(final_path, "rb") as stream:
                mi = get_metadata(stream, stream_type=fmt, use_libprs_metadata=True)
                if mi.title and mi.title == CALIBRE_ERROR_FLAG:
                    if fmt == "pdf":
                        mi.title = utils.remove_zlibrary_suffix(filename.replace("." + fmt, ""))
                    else:
                        logger.error("Failed to get metadata for %s, reason:%s", final_path, mi.comments)
                        failed = True
                mi.title = utils.super_strip(mi.title)
                if mi.author_sort == "Unknown" and mi.authors and len(mi.authors) > 0:
                    mi.authors = [utils.super_strip(a) for a in mi.authors]
                else:
                    mi.authors = [utils.super_strip(mi.author_sort)]
            if failed:
                Path(final_path).unlink(missing_ok=True)
                return {"err": "book.invalid", "msg": _("此书籍文件无法识别, 或者受DRM保护无法导入")}

            # Handle special formats like txt and pdf
            if fmt in ["txt", "pdf"]:
                mi.title = utils.remove_zlibrary_suffix(filename.replace("." + fmt, ""))
                mi.authors = [_("佚名")]

            logging.info("chunked upload mi.title = " + repr(mi.title))

            # Check for existing books
            books = self.calibre_db.books_with_same_title(mi)
            if books:
                book_id = None
                for id in books:
                    b = self.calibre_db.get_metadata(id, index_is_id=True)
                    # 如果是实体书，则跳过
                    if b.get(CALIBRE_COLUMN_BOOK_TYPE, BOOK_TYPE_EBOOK) == BOOK_TYPE_PHYSICAL:
                        continue
                    if book_id is None:
                        book_id = b.get("id")
                    if b.get("authors", "") != mi.authors:
                        continue
                    if fmt.upper() in b.formats:
                        return {
                            "err": "samebook",
                            "msg": _("同名书籍《%s》已存在这一图书格式 %s") % (mi.title, fmt),
                            "book_id": b.get("id")
                        }
                logging.info("import [%s] from %s with format %s", repr(mi.title), final_path, fmt)
                if book_id is None:
                    # New EBOOK
                    book_id = self._add_new_book(mi, [final_path])
                else:
                    self.calibre_db.add_format(book_id, fmt.upper(), final_path, True)
            else:
                book_id = self._add_new_book(mi, [final_path])

            self.add_msg("success", _("导入书籍成功！"))
            return {"err": "ok", "book_id": book_id}

        except Exception as e:
            logging.error("Error in chunked upload: %s", str(e))
            # Clean up on error
            if os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)
            return {"err": "upload_error", "msg": _("文件上传处理失败：%s") % str(e)}


class BookRead(BaseHandler):
    def get(self, bid):
        if not CONF["ALLOW_GUEST_READ"] and not self.current_user:
            return self.redirect("/login")

        if self.current_user:
            if self.current_user.can_read():
                if not self.current_user.is_active():
                    raise web.HTTPError(403, reason=_("无权在线阅读，请先登录注册邮箱激活账号。"))
            else:
                raise web.HTTPError(403, reason=_("无权在线阅读"))

        book = self.get_book(bid, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍已不存在")}
        book_id = book["id"]
        self.user_history("read_history", book)
        self.count_increase(book_id, count_download=1)

        # 若指定了格式且书籍存在该格式，优先按指定格式处理
        fmt_arg = self.get_argument("format", "").lower()
        fpath_arg = book.get("fmt_%s" % fmt_arg, None) if fmt_arg else None
        if fpath_arg:
            if fmt_arg == "txt":
                return self.redirect(f'/read/txt/{book_id}')

            if fmt_arg == "pdf":
                if not CONF["ALLOW_GUEST_DOWNLOAD"] and not self.current_user:
                    return self.redirect("/login")

                if self.current_user and not self.current_user.can_save():
                    raise web.HTTPError(403, reason=_("无权在线阅读"))

                pdf_url = urllib.parse.quote_plus(self.api_url + "/api/book/%(id)d.pdf" % book)
                pdf_reader_url = CONF["PDF_VIEWER"] % {"pdf_url": pdf_url}
                return self.redirect(pdf_reader_url)

            if fmt_arg in ("epub", "mobi", "azw", "azw3"):
                if fmt_arg != 'epub':
                    service = ConverterService()
                    if not service.is_book_converting(book):
                        service.convert_and_save(self.user_id(), book, fpath_arg, "epub")

                epub_dir = "/get/extract/%s" % book["id"]
                return self.html_page("book/" + CONF["EPUB_VIEWER"], {
                    "book": book,
                    "epub_dir": epub_dir,
                    "is_ready": (fmt_arg == 'epub'),
                    "CANDLE_READER_SERVER": CONF["CANDLE_READER_SERVER"],
                })

        # 优先阅读epub/azw3/mobi/txt格式
        for fmt in ["epub", "mobi", "azw", "azw3", "txt"]:
            fpath = book.get("fmt_%s" % fmt, None)
            if not fpath:
                continue

            if fmt != 'epub':
                service = ConverterService()
                if not service.is_book_converting(book):
                    logging.info(f"[READ]Convert book {bid} to epub format, {fpath}")
                    service.convert_and_save(self.user_id(), book, fpath, "epub")

            # epub_dir is for javascript
            epub_dir = "/get/extract/%s" % book["id"]
            return self.html_page("book/" + CONF["EPUB_VIEWER"], {
                "book": book,
                "epub_dir": epub_dir,
                "is_ready": (fmt == 'epub'),
                "CANDLE_READER_SERVER": CONF["CANDLE_READER_SERVER"],
            })

        has_converted_pdf = False
        if 'fmt_docx' in book and 'fmt_pdf' not in book:
            fpath = book.get("fmt_docx", None)
            if fpath:
                service = ConverterService()
                if not service.is_book_converting(book):
                    service.convert_and_save(self.user_id(), book, fpath, "pdf")
                has_converted_pdf = True

        if "fmt_pdf" in book or has_converted_pdf:
            # PDF类书籍需要检查下载权限。
            if not CONF["ALLOW_GUEST_DOWNLOAD"] and not self.current_user:
                return self.redirect("/login")

            if self.current_user and not self.current_user.can_save():
                raise web.HTTPError(403, reason=_("无权在线阅读PDF类书籍"))

            pdf_url = urllib.parse.quote_plus(self.api_url + "/api/book/%(id)d.PDF" % book)
            pdf_reader_url = CONF["PDF_VIEWER"] % {"pdf_url": pdf_url}
            return self.redirect(pdf_reader_url)

        if 'fmt_txt' in book:
            # TXT有专门的阅读器
            txt_reader_url = f'/read/txt/{book_id}'
            return self.redirect(txt_reader_url)

        raise web.HTTPError(404, reason=_("抱歉，在线阅读器暂不支持该格式的书籍，可以转为epub或者pdf后阅读"))

    def _epub_conversion_source(self, book, fmt_arg=""):
        """返回需要转换为epub的源文件路径；如果无需转换（已就绪或该格式不需要转换）则返回None"""
        if fmt_arg and fmt_arg not in ("epub"):
            return None

        for fmt in ["epub", "txt", "mobi", "azw", "azw3"]:
            fpath = book.get("fmt_%s" % fmt, None)
            if not fpath:
                continue
            if fmt in ("epub"):
                return None
            return None if book.get("fmt_epub") else fpath
        return None

    @js
    def post(self, bid):
        """检测目标阅读格式是否就绪，如未就绪则按需启动转换任务"""
        if not CONF["ALLOW_GUEST_READ"] and not self.current_user:
            return {"err": "user.need_login", "msg": _("请先登录")}

        if self.current_user:
            if self.current_user.can_read():
                if not self.current_user.is_active():
                    return {"err": "user.no_permission", "msg": _("无权在线阅读，请先登录注册邮箱激活账号。")}
            else:
                return {"err": "user.no_permission", "msg": _("无权在线阅读")}

        book = self.get_book(bid, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍已不存在")}

        data = {}
        if self.request.body:
            try:
                data = tornado.escape.json_decode(self.request.body)
            except (ValueError, json.JSONDecodeError):
                data = {}
        fmt_arg = str(data.get("format") or self.get_argument("format", "")).lower()

        fpath = self._epub_conversion_source(book, fmt_arg)
        if not fpath:
            return {"err": "ok", "msg": _("可以直接打开"), "data": {"status": "ready", "path": fpath}}

        service = ConverterService()
        if not service.is_book_converting(book):
            logging.info(f"[READ]Convert book {bid} to epub format, {fpath}")
            service.convert_and_save(self.user_id(), book, fpath, "epub")
        else:
            logging.info("[READ]One converting task is running.")

        return {"err": "ok", "msg": _("正在执行转换任务，请稍候..."), "data": {"status": "converting"}}


class TxtRead(BaseHandler):
    @js
    @auth
    def get(self, bid):
        book = self.get_book(bid, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍已不存在")}
        start = int(self.get_argument("start", "0"))
        end = int(self.get_argument("end", "-1"))
        fpath = book.get("fmt_txt", None)
        if not fpath:
            return {"err": "format error", "msg": _("非txt书籍")}
        if not CONF["ALLOW_GUEST_READ"] and not self.current_user:
            return {"err": "user.need_login", "msg": _("请先登录")}
        if self.current_user:
            if self.current_user.can_read():
                if not self.current_user.is_active():
                    return {"err": "user.no_permission", "msg": _("无权在线阅读，请先登录注册邮箱激活账号。")}
            else:
                return {"err": "user.no_permission", "msg": _("无权在线阅读")}
        with open(fpath, mode='rb') as file:
            file.seek(start)
            if end == -1:
                content = file.read()
            else:
                # 读取从起始位置到结束位置的内容
                content = file.read(end - start)
        if not content:
            return {"err": "format error", "msg": _("空文件")}
        encode = get_content_encoding(content)
        content = content.decode(encoding=encode, errors='ignore').replace("\r", "").replace("\n", "<br>")
        return {"err": "ok", "content": content}


class BookTxtParser(BaseHandler):
    @js
    def get(self):
        bid = self.get_argument("id", "")
        test_ready = self.get_argument("test", "")
        book = self.get_book(bid)
        fpath = book.get("fmt_txt", None)
        if not fpath:
            return {"err": "format error", "msg": _("非text书籍")}
        if not CONF["ALLOW_GUEST_READ"] and not self.current_user:
            return {"err": "user.need_login", "msg": _("请先登录")}
        if self.current_user:
            if self.current_user.can_read():
                if not self.current_user.is_active():
                    return {"err": "user.no_permission", "msg": _("无权在线阅读，请先登录注册邮箱激活账号。")}
            else:
                return {"err": "user.no_permission", "msg": _("无权在线阅读")}
        # 解压后的目录
        fdir = os.path.join(CONF["extract_path"], str(book["id"]))
        # txt 解析出的目录文件
        content_path = fdir + "/content.json"
        is_ready = os.path.isfile(content_path)
        if is_ready:
            with open(content_path, 'r', encoding='utf8') as f:
                meta = json.loads(f.read())
            return {"err": "ok", "msg": _("parsed"), "data": {
                "content": meta['toc'],
                "encoding": meta['encoding'],
                "name": book["title"]
            }}
        if test_ready != "0":
            return {"err": "ok", "msg": _("not parsed")}

        # 若未解析则计算预计等待时间，至少2分钟
        wait = min(120, os.path.getsize(fpath) / (1024 * 1024) * 15)
        ExtractService().parse_txt_content(bid, fpath)
        que_len = ExtractService().get_queue('parse_txt_content').qsize()
        return {
            "err": "ok",
            "msg": _("已加入队列"),
            "data": {
                "wait": wait,
                "name": book["title"],
                "path": content_path,
                "que": que_len,
            },
        }


class BookSuggestion(ListHandler):
    @js
    def get(self, id):
        book = self.get_book(id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍已不存在")}

        tags = book.get("tags", [])
        similar_books = []

        if tags:
            random_tag = random.choice(tags)
            similar_books = self.get_item_books("tags", random_tag, max_count=12)

        if not similar_books:
            # 如果没有标签或没有找到匹配的书籍，则使用作者查询
            authors = book.get("authors", [])
            if authors and authors[0] not in ("佚名", "Unknown"):
                similar_books = self.get_item_books("authors", authors[0], max_count=12)
        # 移除结果中的当前书籍
        similar_books = [b for b in similar_books if b["id"] != book["id"]]
        return {
            "err": "ok",
            "msg": _("推荐成功"),
            "books": [self.fmt(b) for b in similar_books]
        }


class BookSendToDevice(BaseHandler):
    def _blocked_local_ip(self, device_url):
        if not device_url:
            return False
        if device_url.startswith("127."):
            return True
        if device_url.lower().startswith("http://127.") or device_url.lower().startswith("https://127."):
            return True
        return False

    @js
    def post(self, bid):
        """发送书籍到指定设备"""
        book_id = int(bid)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "book.not_found", "msg": _("书籍已不存在")}

        # 检查用户权限
        if not CONF["ALLOW_GUEST_PUSH"]:
            if not self.current_user:
                return {"err": "user.need_login", "msg": _("请先登录")}
            else:
                if not self.current_user.can_push():
                    return {"err": "permission", "msg": _("无权操作")}
                elif not self.current_user.is_active():
                    return {"err": "permission", "msg": _("无权操作，请先激活账号。")}

        # 解析请求参数
        try:
            data = tornado.escape.json_decode(self.request.body)
            device_type = data.get("device_type", "").lower()
            device_url = data.get("device_url", "")
            mailbox = data.get("mailbox", "")
            ftp_username = data.get("ftp_username", "")
            ftp_password = data.get("ftp_password", "")
            ftp_path = data.get("ftp_path", "")
        except Exception:
            return {"err": "params.invalid", "msg": _("请求参数格式错误")}

        # 支持的设备类型
        supported_types = ["duokan", "ireader", "hanwang", "boox", "dangdang", "kindle", "purelibro", "ftp"]
        if device_type not in supported_types:
            return {"err": "device.unsupported", "msg": _("不支持的设备类型: %s") % device_type}

        # 各设备类型参数校验
        if device_type == "kindle":
            if not mailbox:
                return {"err": "params.missing", "msg": _("Kindle设备需要提供邮箱地址")}
        elif device_type == "ftp":
            if not device_url:
                return {"err": "params.missing", "msg": _("设备类型和设备地址不能为空")}
            if not ftp_path:
                return {"err": "params.missing", "msg": _("FTP路径不能为空")}
        else:
            if not device_type or not device_url:
                return {"err": "params.missing", "msg": _("设备类型和设备地址不能为空")}

        if device_type == "kindle":
            return self._send_to_kindle(book, book_id, mailbox)
        elif device_type == "ftp":
            if self._blocked_local_ip(device_url):
                return {"err": "params.invalid", "msg": _("不允许直接发送到本机")}
            return self._send_to_ftp(book, book_id, device_url, ftp_username, ftp_password, ftp_path)
        else:
            if self._blocked_local_ip(device_url):
                return {"err": "params.invalid", "msg": _("不允许直接发送到本机")}
            return self._send_to_other_device(book, book_id, device_type, device_url)

    def _send_to_kindle(self, book, book_id, mail_to):
        """通过邮件发送书籍到Kindle设备"""
        self.user_history("push_history", book)
        self.count_increase(book_id, count_download=1, count_visit=1)

        # epub、pdf、txt格式可以直接发送，不需要转换
        for fmt in ["epub", "pdf", "txt"]:
            fmt_key = "fmt_%s" % fmt
            if fmt_key in book:
                fpath = book[fmt_key]
                logging.info(f"[SEND_TO_KINDLE] 找到可直接发送的格式: {fmt}, 路径: {fpath}")
                MailService().send_book(self.user_id(), self.site_url, book, mail_to, fmt, fpath)
                self.add_msg(
                    "success",
                    _("服务器正在推送《%(title)s》到%(email)s") % {"title": book["title"], "email": mail_to},
                )
                return {"err": "ok", "msg": _("服务器后台正在推送。您可关闭此窗口，继续浏览其他书籍。")}

        # 如果没有可直接发送的格式，检查是否有azw3或mobi格式需要转换
        if "fmt_azw3" in book or "fmt_mobi" in book:
            fmt = "azw3" if "fmt_azw3" in book else "mobi"
            logging.info(f"[SEND_TO_KINDLE] 找到{fmt}格式，需要转换为epub后发送")
            ConverterService().convert_and_send(self.user_id(), self.site_url, book, mail_to)
            self.add_msg(
                "success",
                _("服务器正在推送《%(title)s》到%(email)s") % {"title": book["title"], "email": mail_to},
            )
            return {"err": "ok", "msg": _("服务器正在转换格式，稍后将自动推送。您可关闭此窗口，继续浏览其他书籍。")}

        # 没有Kindle支持的格式
        return {
            "err": "format.not_supported",
            "msg": _("书籍没有Kindle支持的格式!")
        }

    def _send_to_other_device(self, book, book_id, device_type, device_url):
        """通过WiFi上传发送书籍到其他设备"""

        # 查找合适的文件格式（优先级：epub > azw3 > pdf > txt）
        file_path = None
        file_format = None
        format_priority = ["epub", "azw3", "pdf", "txt"]
        for fmt in format_priority:
            fmt_key = "fmt_%s" % fmt
            if fmt_key in book:
                file_path = book[fmt_key]
                file_format = fmt
                break

        if not file_path:
            return {"err": "file.not_found", "msg": _("书籍没有支持的文件格式（epub/azw3/pdf/txt）")}

        # 检查文件是否存在
        if not os.path.exists(file_path):
            return {"err": "file.missing", "msg": _("书籍文件不存在: %s") % file_path}

        # 导入对应的上传器
        try:
            from webserver.plugins.sending.uploader import DuokanUploader, IReaderUploader, HanwangUploader
            from webserver.plugins.sending.uploader import BooxUploader, DangdangUploader, PureLibroUploader

            uploader_map = {
                "duokan": DuokanUploader,
                "ireader": IReaderUploader,
                "hanwang": HanwangUploader,
                "boox": BooxUploader,
                "dangdang": DangdangUploader,
                "purelibro": PureLibroUploader,
            }

            uploader_class = uploader_map.get(device_type)
            if not uploader_class:
                return {"err": "uploader.not_found", "msg": _("找不到对应的上传器: %s") % device_type}

            # 创建上传器实例
            book_name = book.get("title", "")
            if len(book_name) > 120:
                book_name = ""
            if not book_name:
                book_name = None
            else:
                book_name += os.path.splitext(file_path)[-1]
            uploader = uploader_class(file_path, file_name=book_name)

            # 构建设备上传URL
            if not device_url.startswith(('http://', 'https://')):
                device_url = 'http://' + device_url

            # 使用uploader的get_upload_url方法构建完整URL
            upload_url = uploader.get_upload_url(device_url)

            # 执行上传
            logging.info(f"[SEND_TO_DEVICE] 开始发送书籍 {book_id} ({file_format}) 到设备 {device_type}: {upload_url}")
            result = uploader.upload(device_url)

            if result.get('success'):
                logging.info(f"[SEND_TO_DEVICE] 发送成功: {book_id} -> {device_type}")
                return {"err": "ok", "msg": _("书籍发送成功")}
            else:
                error_type = result.get('error_type', 'unknown')
                error_msg = result.get('message', '发送失败')

                if error_type == 'connection':
                    return {"err": "connection.failed", "msg": _("无法连接到设备。请确认IP地址正确，且设备已开启WiFi上传功能")}
                elif error_type == 'timeout':
                    return {"err": "upload.timeout", "msg": _("上传超时。请检查网络连接和设备状态")}
                elif error_type == 'http':
                    status_code = result.get('status_code', 0)
                    return {"err": "upload.failed", "msg": _("上传失败 (HTTP %d)。请查看日志获取详细信息") % status_code}
                else:
                    return {"err": "upload.error", "msg": _("上传过程出错: %s。请查看日志获取详细信息") % error_msg}

        except ImportError as e:
            logging.error(f"[SEND_TO_DEVICE] 导入上传器失败: {e}")
            return {"err": "uploader.import_error", "msg": _("设备上传功能不可用")}
        except Exception as e:
            logging.error(f"[SEND_TO_DEVICE] 发送失败: {e}")
            return {"err": "upload.error", "msg": _("发送过程出错，请查看日志获取详细信息")}

    def _send_to_ftp(self, book, book_id, device_url, ftp_username, ftp_password, ftp_path):
        """通过FTP上传发送书籍。每次调用创建独立FTP连接，多个并发请求互不影响。"""
        # 查找合适的文件格式（优先级：epub > azw3 > pdf > txt）
        file_path = None
        file_format = None
        for fmt in ["epub", "azw3", "pdf", "txt"]:
            fmt_key = "fmt_%s" % fmt
            if fmt_key in book:
                file_path = book[fmt_key]
                file_format = fmt
                break

        if not file_path:
            return {"err": "file.not_found", "msg": _("书籍没有支持的文件格式（epub/azw3/pdf/txt）")}

        if not os.path.exists(file_path):
            return {"err": "file.missing", "msg": _("书籍文件不存在: %s") % file_path}

        try:
            from webserver.plugins.sending.uploader import FtpUploader

            # 优先使用 title_sort（已转为拼音，无中文兼容问题）
            book_name = book.get("sort", "") or book.get("title", "")
            if book_name:
                book_name = book_name.replace(" ", "_")
            if len(book_name) > 120:
                book_name = f"{book_id}"
            else:
                book_name = f"{book_id}_{book_name}"
            if book_name:
                book_name += os.path.splitext(file_path)[-1]
            else:
                book_name = None

            # 每次实例化都创建独立连接对象，并发请求之间无共享状态
            uploader = FtpUploader(
                file_path,
                file_name=book_name,
                username=ftp_username,
                password=ftp_password,
                path=ftp_path,
            )

            logging.info(
                "[SEND_TO_FTP] 开始发送书籍 %s (%s) 到 %s%s",
                book_id, file_format, device_url, ftp_path,
            )
            result = uploader.upload(device_url)

            if result.get("success"):
                logging.info("[SEND_TO_FTP] 发送成功: %s -> %s", book_id, device_url)
                return {"err": "ok", "msg": _("书籍发送成功")}

            error_type = result.get("error_type", "other")
            error_msg = result.get("message", "发送失败")
            logging.warning("[SEND_TO_FTP] 发送失败 book=%s error_type=%s msg=%s", book_id, error_type, error_msg)

            if error_type == "auth":
                return {"err": "ftp.auth_failed", "msg": _("FTP认证失败")}
            if error_type == "ftp_perm":
                return {"err": "ftp.path_not_found", "msg": _("FTP路径不存在: %s") % ftp_path}
            if error_type == "connection":
                return {"err": "connection.failed", "msg": _("FTP连接失败: %s") % device_url}
            if error_type == "timeout":
                return {"err": "upload.timeout", "msg": _("上传超时。请检查网络连接和设备状态")}
            return {"err": "ftp.upload_failed", "msg": _("FTP上传失败: %s") % error_msg}

        except ImportError as e:
            logging.error("[SEND_TO_FTP] 导入FTP上传器失败: %s", e)
            return {"err": "uploader.import_error", "msg": _("设备上传功能不可用")}
        except Exception as e:
            logging.error("[SEND_TO_FTP] 发送失败: %s", e)
            return {"err": "ftp.upload_failed", "msg": _("FTP上传失败: %s") % str(e)}


class BookSendToMail(BaseHandler):
    @js
    def post(self, bid):
        """发送书籍到指定邮箱"""
        book_id = int(bid)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "book.not_found", "msg": _("书籍已不存在")}

        if not CONF["ALLOW_GUEST_PUSH"]:
            if not self.current_user:
                return {"err": "user.need_login", "msg": _("请先登录")}
            else:
                if not self.current_user.can_push():
                    return {"err": "permission", "msg": _("无权限进行推送，请联系管理员检查权限")}
                elif not self.current_user.is_active():
                    return {"err": "permission", "msg": _("无权限进行操作，请先激活账号。")}

        # 解析请求参数
        try:
            data = tornado.escape.json_decode(self.request.body)
            mail_to = data.get("email", "").strip()
        except:
            return {"err": "params.invalid", "msg": _("没有指定邮箱地址")}

        if not mail_to:
            return {"err": "params.missing", "msg": _("邮箱地址不能为空")}

        # 验证邮箱地址格式
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, mail_to):
            return {"err": "email.invalid", "msg": _("邮箱地址格式不正确")}

        # 按优先级查找可用格式: EPUB > AZW3 > PDF > MOBI > TXT
        format_priority = ["epub", "azw3", "pdf", "mobi", "txt"]
        file_path = None
        file_format = None

        for fmt in format_priority:
            fmt_key = "fmt_%s" % fmt
            if fmt_key in book:
                file_path = book[fmt_key]
                file_format = fmt
                break

        if not file_path:
            return {"err": "format.not_found", "msg": _("书籍没有支持的文件格式（EPUB/AZW3/PDF/MOBI/TXT）")}

        # 检查文件是否存在
        if not os.path.exists(file_path):
            return {"err": "file.missing", "msg": _("书籍文件不存在")}

        # 检查文件大小（50MB = 52428800 bytes）
        file_size = os.path.getsize(file_path)
        max_size = 50 * 1024 * 1024  # 50MB
        if file_size > max_size:
            size_mb = file_size / (1024 * 1024)
            return {
                "err": "file.too_large",
                "msg": _("附件过大（%.1fMB），邮件附件大小不能超过50MB") % size_mb
            }

        # 记录推送历史和增加统计
        self.user_history("push_history", book)
        self.count_increase(book_id, count_download=1, count_visit=1)
        logging.info(f"[SEND_TO_MAIL] 发送书籍 {book_id} ({file_format}, {file_size} bytes) 到邮箱 {mail_to}")
        MailService().send_book(self.user_id(), self.site_url, book, mail_to, file_format, file_path)

        self.add_msg(
            "success",
            _("已开始推送《%(title)s》到%(email)s") % {"title": book["title"], "email": mail_to},
        )

        return {"err": "ok", "msg": _("后台正在推送，稍后可以刷新页面，在通知消息中查看结果。")}


class BookSperate(BaseHandler):
    @js
    @auth
    def post(self, bid):
        """将指定格式从书籍中分离并创建为新的独立书籍"""
        from calibre.ebooks.metadata.meta import get_metadata

        book_id = int(bid)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍已不存在")}

        if isinstance(book["collector"], dict):
            cid = book["collector"]["id"]
        else:
            cid = book["collector"].id
        if not self.current_user.can_edit() or not (self.is_admin() or self.is_book_owner(book_id, cid)):
            return {"err": "permission", "msg": _("无权操作")}

        try:
            data = tornado.escape.json_decode(self.request.body)
            fmt = data.get("format", "").strip().lower()
        except Exception:
            return {"err": "params.invalid", "msg": _("请求参数格式错误")}

        if not fmt:
            return {"err": "params.missing", "msg": _("格式参数不能为空")}

        fmt_key = "fmt_%s" % fmt
        if fmt_key not in book:
            return {"err": "format.not_found", "msg": _("书籍不包含 %s 格式") % fmt.upper()}

        original_path = book[fmt_key]
        if not os.path.exists(original_path):
            return {"err": "file.missing", "msg": _("格式文件不存在: %s") % original_path}

        # 检查书籍是否只有一个格式
        available_formats = book.get("available_formats", "")
        available_formats = [f.strip() for f in available_formats if f.strip()]
        if len(available_formats) <= 1:
            return {"err": "last.format", "msg": _("书籍只有一个格式，无法分离")}

        try:
            # 复制文件到上传目录
            filename = os.path.basename(original_path)
            upload_path = os.path.join(CONF["upload_path"], filename)

            # 如果目标文件已存在，添加时间戳避免冲突
            if os.path.exists(upload_path):
                timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                name, ext = os.path.splitext(filename)
                upload_path = os.path.join(CONF["upload_path"], f"{name}_{timestamp}{ext}")

            shutil.copy2(original_path, upload_path)
            logging.info(f"[SEPARATE] Copied format file from {original_path} to {upload_path}")

            # 读取元数据
            failed = False
            with open(upload_path, "rb") as stream:
                mi = get_metadata(stream, stream_type=fmt, use_libprs_metadata=True)
                if mi.title and mi.title == CALIBRE_ERROR_FLAG:
                    logger.error("Failed to get metadata for %s, reason:%s", upload_path, mi.comments)
                    failed = True
                mi.title = utils.super_strip(mi.title)
                if mi.author_sort == "Unknown" and mi.authors and len(mi.authors) > 0:
                    mi.authors = [utils.super_strip(a) for a in mi.authors]
                else:
                    mi.authors = [utils.super_strip(mi.author_sort)]

            if failed:
                return {"err": "book.invalid", "msg": _("此书籍文件无法识别, 或者受DRM保护无法处理")}

            # 对于txt和pdf格式，从文件名提取信息
            if fmt in ["txt", "pdf"]:
                mi.title = utils.remove_zlibrary_suffix(filename.replace("." + fmt, ""))
                mi.authors = [_("佚名")]

            # 创建新书籍
            fpaths = [upload_path]
            mi.title_sort = utils.get_title_sort(mi.title)
            new_book_id = self.calibre_db.import_book(mi, fpaths)

            if new_book_id is None:
                # 清理临时文件
                if os.path.exists(upload_path):
                    os.remove(upload_path)
                return {"err": "book.create.failed", "msg": _("创建新书籍失败")}

            # 创建Item记录
            item = Item()
            item.book_id = new_book_id
            item.collector_id = self.user_id()
            self.sqlite_session.add(item)
            self.sqlite_session.commit()

            # 从原书籍中删除该格式
            self.calibre_db_cache.remove_formats({book_id: [fmt.upper()]})

            logging.info(f"[SEPARATE] Successfully separated format {fmt} from book {book_id} to new book {new_book_id}")
            self.add_msg("success", _("成功将 %s 格式分离为新书籍") % fmt.upper())
            return {
                "err": "ok",
                "msg": _("格式分离成功"),
                "original_book_id": book_id,
                "new_book_id": new_book_id
            }

        except Exception as e:
            logging.error(f"[SEPARATE] Failed to separate format {fmt} from book {book_id}: {e}")
            traceback.print_exc()
            # 清理可能存在的临时文件
            if 'upload_path' in locals() and os.path.exists(upload_path):
                try:
                    os.remove(upload_path)
                except Exception as err:
                    logging.error(f"[SEPARATE] Failed to clean up temporary file {upload_path}: {err}")

            return {"err": "internal", "msg": _("分离格式时发生错误: %s") % str(e)}


class BookSaveMeta(BaseHandler):
    @js
    @auth
    def post(self, bid):
        """将书籍的元数据保存到文件中（仅支持 epub/azw3/pdf）"""
        book_id = int(bid)
        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _("无权限，非管理员或书籍所有者无法操作")}

        fmt = self.get_argument("fmt", None)
        return self.save_book_meta(book_id, fmt=fmt)


class BookAddStamp(BaseHandler):
    @js
    @auth
    def post(self, bid):
        """为书籍封面加盖图章"""
        book_id = int(bid)
        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _("无权限，非管理员或书籍所有者无法操作")}

        # 检查功能是否启用
        if not CONF.get("ENABLE_STAMP_FEATURE", False):
            return {"err": "feature.disabled", "msg": _("图章功能未启用")}

        # 检查图章文件是否存在
        stamp_path = os.path.join(CONF["static_path"], "logo", "stamp.png")
        if not os.path.exists(stamp_path):
            return {"err": "stamp.not_found", "msg": _("图章文件不存在，请先在设置中上传图章图片")}

        # 获取书籍信息
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "book.not_found", "msg": _("书籍不存在")}

        # 检查是否有支持的格式
        supported_formats = []
        for f in ["epub", "azw3", "pdf"]:
            fmt_key = f"fmt_{f}"
            if fmt_key in book:
                supported_formats.append(f)

        if not supported_formats:
            return {
                "err": "format.not_supported",
                "msg": _("书籍没有支持的格式（需要 EPUB、AZW3 或 PDF）"),
            }

        try:
            # 获取当前封面
            cover_data = self.calibre_db.cover(book_id, index_is_id=True)
            if not cover_data:
                return {"err": "cover.not_found", "msg": _("书籍没有封面")}

            # 获取图章位置（从请求参数或配置中获取）
            args = tornado.escape.json_decode(self.request.body)
            stamp_position = args.get("position", CONF.get("STAMP_POSITION", "bottom-right"))

            new_cover_data = ImageHelper().add_stamp_to_image(cover_data, stamp_path, stamp_position)
            if not new_cover_data:
                return {"err": "stamp.failed", "msg": _("添加图章失败")}

            # 更新元数据到文件
            result = self.save_book_meta(book_id, fmt=None, cover=new_cover_data)
            if result.get("err") != "ok":
                # 即使保存到文件失败，封面已经更新到数据库
                logging.warning(f"Failed to save metadata to file: {result.get('msg')}")
                return {
                    "err": "ok",
                    "msg": _("图章已添加到封面，但保存到文件时部分失败: %s") % result.get("msg", ""),
                }

            return {"err": "ok", "msg": _("图章已成功添加到封面")}

        except Exception as e:
            logging.error(f"Error adding stamp to cover: {e}")
            logging.error(traceback.format_exc())
            return {"err": "error", "msg": _("添加图章时发生错误: %s") % str(e)}


class ClearRareTags(ListHandler):
    @js
    @auth
    def post(self):
        """清理稀少标签, 对少于3本书的标签所对应的书籍重新更新标签"""
        if not self.is_admin():
            return {"err": "user.not_admin", "msg": _("无权限")}

        ids = list(self.calibre_db_cache.all_book_ids())
        if not ids or len(ids) < 100:
            return {"err": "ok", "msg": _("书籍数量较少，无需清理标签")}

        try:
            # 使用SQL直接批量查询：找出所有count < 3的tag对应的所有书籍ID
            sql = """
                SELECT DISTINCT l.book
                FROM books_tags_link l
                INNER JOIN (
                    SELECT A.id, COUNT(DISTINCT B.book) as book_count
                    FROM tags A
                    LEFT JOIN books_tags_link B ON A.id = B.tag
                    GROUP BY A.id
                    HAVING COUNT(DISTINCT B.book) < 3 AND COUNT(DISTINCT B.book) > 0
                ) rare_tag_ids ON l.tag = rare_tag_ids.id
            """

            with self.db_lock:
                rows = self.calibre_db_cache.backend.conn.get(sql)

            if not rows:
                return {"err": "ok", "msg": _("没有找到稀少标签对应的书籍")}

            book_ids = [row[0] for row in rows]

            # 同时获取稀少标签的数量用于返回信息
            count_sql = """
                SELECT COUNT(*)
                FROM (
                    SELECT A.id
                    FROM tags A
                    LEFT JOIN books_tags_link B ON A.id = B.tag
                    GROUP BY A.id
                    HAVING COUNT(DISTINCT B.book) < 3 AND COUNT(DISTINCT B.book) > 0
                )
            """
            with self.db_lock:
                tag_count_rows = self.calibre_db_cache.backend.conn.get(count_sql)
            rare_tag_count = tag_count_rows[0][0] if tag_count_rows else 0

            if not book_ids:
                return {"err": "ok", "msg": _("没有找到需要更新的书籍")}

            # 调用自动填充服务，只更新标签
            service = AutoFillService()
            service.auto_fill_all(book_ids, only_tags=True)

            return {
                "err": "ok",
                "msg": _("开始更新 %d 本书的标签，涉及 %d 个稀少标签") % (len(book_ids), rare_tag_count),
                "book_count": len(book_ids),
                "tag_count": rare_tag_count
            }

        except Exception as e:
            logging.error(f"Clear rare tags error: {e}")
            return {"err": "error", "msg": _("处理失败：%s") % str(e)}


class BookExchangeType(BaseHandler):
    @js
    @auth
    def post(self):
        """批量转换书籍类型, 电子书与实体书互转"""
        if not self.is_admin():
            return {"err": "user.no_permission", "msg": _("无权限")}

        data = tornado.escape.json_decode(self.request.body)
        idlist = data.get("idlist", [])

        if not idlist:
            return {"err": "params.invalid", "msg": _("请提供书籍ID列表")}

        success_count = 0
        skip_count = 0
        results = []

        for book_id in idlist:
            try:
                book = self.get_book(book_id, raise_exception=False)
                if not book:
                    results.append({"book_id": book_id, "status": "not_found", "msg": _("书籍已不存在")})
                    skip_count += 1
                    continue

                # 获取或创建Item记录
                item = self.sqlite_session.query(Item).filter(Item.book_id == book_id).first()
                if not item:
                    item = Item()
                    item.book_id = book_id
                    item.collector_id = self.user_id()
                    self.sqlite_session.add(item)

                current_type = item.book_type

                # 如果是电子书，转为实体书
                if current_type == BOOK_TYPE_EBOOK:
                    # 检查是否有ISBN
                    isbn = book.get("isbn", "")
                    if not isbn:
                        results.append({"book_id": book_id, "status": "skip", "msg": _("无ISBN，跳过")})
                        skip_count += 1
                        continue

                    # 检查是否有任何电子书格式
                    has_formats = False
                    for fmt in ["epub", "mobi", "azw", "azw3", "txt", "pdf"]:
                        if book.get("fmt_%s" % fmt):
                            has_formats = True
                            break

                    if has_formats:
                        results.append({"book_id": book_id, "status": "skip", "msg": _("已有电子书格式，跳过")})
                        skip_count += 1
                        continue

                    # 转换为实体书
                    item.book_type = BOOK_TYPE_PHYSICAL
                    item.book_count = 1
                    results.append({"book_id": book_id, "status": "success", "msg": _("已转为实体书")})
                    success_count += 1

                # 如果是实体书，转为电子书
                elif current_type == BOOK_TYPE_PHYSICAL:
                    item.book_type = BOOK_TYPE_EBOOK
                    item.book_count = 1
                    results.append({"book_id": book_id, "status": "success", "msg": _("已转为电子书")})
                    success_count += 1

                else:
                    results.append({"book_id": book_id, "status": "skip", "msg": _("未知类型")})
                    skip_count += 1

            except Exception as e:
                logging.error(f"Exchange type error for book {book_id}: {e}")
                results.append({"book_id": book_id, "status": "error", "msg": str(e)})
                skip_count += 1

        # 提交所有更改
        try:
            self.sqlite_session.commit()
        except Exception as e:
            self.sqlite_session.rollback()
            return {"err": "db.error", "msg": _("数据库错误：%s") % str(e)}

        return {
            "err": "ok",
            "msg": _("处理完成：成功 %d 本，跳过 %d 本") % (success_count, skip_count),
            "success_count": success_count,
            "skip_count": skip_count,
            "results": results
        }


def routes():
    return [
        (r"/api/index", Index),
        (r"/api/search", SearchBook),
        (r"/api/recent", RecentBook),
        (r"/api/all", RecentBook),
        (r"/api/hot", HotBook),
        (r"/api/printbooks", PrintBooks),
        (r"/api/soledbooks", BookSoled),
        (r"/api/book/nav", BookNav),
        (r"/api/book/add", BookAddByISBN),
        (r"/api/book/upload", BookUpload),
        (r"/api/book/upload/chunk", BookUploadChunk),
        (r"/api/book/([0-9]+)", BookDetail),
        (r"/api/book/([0-9]+)/delete", BookDelete),
        (r"/api/book/([0-9]+)/delete_format", BookDeleteFormat),
        (r"/api/book/([0-9]+)/edit", BookEdit),
        (r"/api/book/([0-9]+\..+)", BookDownload),
        (r"/api/book/([0-9]+)/refer", BookRefer),
        (r"/api/book/([0-9]+)/send_to_device", BookSendToDevice),
        (r"/api/book/([0-9]+)/mailto", BookSendToMail),
        (r"/read/([0-9]+)", BookRead),
        (r"/api/book/([0-9]+)/read", BookRead),
        (r"/api/read/txt/([0-9]+)", TxtRead),
        (r"/api/book/txt/parser", BookTxtParser),
        (r"/api/book/([0-9]+)/convert", BookConverter),
        (r"/api/book/([0-9]+)/topdf", BookToPDF),
        (r"/api/book/([0-9]+)/totxtz", BookToTxtZ),
        (r"/api/book/([0-9]+)/setsole", BookSetSole),
        (r"/api/book/([0-9]+)/cover", BookCover),
        (r"/api/book/crop_cover", BookCropCover),
        (r"/api/book/([0-9]+)/favorite", BookFavorite),
        (r"/api/book/([0-9]+)/wants", BookWantToRead),
        (r"/api/book/([0-9]+)/readstate", BookReadingState),
        (r"/api/favorites", BookFavorite),
        (r"/api/wants", BookWantToRead),
        (r"/api/reading", BookReading),
        (r"/api/read-done", BookReadDone),
        (r"/api/reading/stats", BookReadingStats),
        (r"/api/book/([0-9]+)/tags", BookTags),
        (r"/api/book/([0-9]+)/aifill", BookAIFill),
        (r"/api/book/update_tags", BookUpdateTags),
        (r"/api/book/category", BookCategoryBatch),
        (r"/api/book/([0-9]+)/category", BookCategory),
        (r"/api/book/([0-9]+)/location", BookLocation),
        (r"/api/categories", BookCategories),
        (r"/api/tags/search", TagSearch),
        (r"/api/book/([0-9]+)/suggestion", BookSuggestion),
        (r"/api/book/([0-9]+)/separate", BookSperate),
        (r"/api/book/([0-9]+)/savemeta", BookSaveMeta),
        (r"/api/book/([0-9]+)/addstamp", BookAddStamp),
        (r"/api/book/exchange_type", BookExchangeType),
        (r"/api/clear_rare_tags", ClearRareTags),
    ]
