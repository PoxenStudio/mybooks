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
from pathlib import Path
from gettext import gettext as _

try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False

import tornado.escape
from tornado import web

from webserver import loader, utils
from webserver.services.autofill import AutoFillService
from webserver.services.ai_fillinfo import AIFillInfoService
from webserver.services.book_search import BookSearch
from webserver.services.convert import ConvertService
from webserver.services.extract import ExtractService
from webserver.services.mail import MailService
from webserver.handlers.base import BaseHandler, ListHandler, auth, js
from webserver.models import Item, ReadingState
from webserver.plugins.meta import baike, douban, youshu, xhsd
from webserver.plugins.meta.bookbarn_tags import BookBarnTags
from webserver.plugins.parser.txt import get_content_encoding
from webserver.handlers.audio import AudioUtils
from webserver.constants import COLUMN_CATEGORY, CALIBRE_COLUMN_CATEGORY
from webserver.constants import CALIBRE_ERROR_FLAG, SUPPORTED_EBOOK_FORMATS
from webserver.constants import CALIBRE_COLUMN_BOOK_TYPE, CALIBRE_COLUMN_PHY_COUNT
from webserver.constants import BOOK_TYPE_EBOOK, BOOK_TYPE_PHYSICAL


CONF = loader.get_settings()


class Index(BaseHandler):
    def fmt(self, b):
        return utils.BookFormatter(self, b).format()

    @js
    def get(self):
        """首页显示随机书籍和最近添加的书籍"""
        setting_random_count = CONF.get("MAIN_PAGE_RANDOM_COUNT", 12)
        setting_recent_count = CONF.get("MAIN_PAGE_RECENT_COUNT", 12)
        cnt_random = min(int(self.get_argument("random", setting_random_count)), 60)
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
        new_ids = random.sample(ids[0:800], min(cnt_recent, len(ids)))
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
            return {"err": "params.book.invalid", "msg": _(u"书籍不存在")}

        # 添加当前用户的阅读状态信息
        if self.current_user:
            reading_state = self.sqlite_session.query(ReadingState).filter(
                ReadingState.book_id == book_id,
                ReadingState.reader_id == self.current_user.id
            ).first()

            # 创建阅读状态映射
            if reading_state:
                book["state"] = utils.ReadingStateFormatter.format_reading_state(reading_state)
            else:
                book["state"] = utils.ReadingStateFormatter.format_reading_state(None)
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
            "book": utils.BookFormatter(self, book).format(with_files=True, with_perms=True),
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
            return {"err": "params.book.invalid", "msg": _(u"书籍不存在")}

        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _(u"无权限")}

        isbn = book.get("isbn", "")
        title = book.get("title", "")
        authors = book.get("authors", [])
        author = authors[0] if authors else ""

        if title.startswith("百度百科"):
            return {"err": "ok", "msg": _(u"无需更新")}

        try:
            api = BookBarnTags(token=CONF.get("BOOKBARN_TOKEN", ""))
            if not api:
                return {"err": "plugin.missing", "msg": _(u"BookBarn Tags插件未安装")}
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
                    return {"err": "ok", "msg": _(u"标签更新成功")}
            return {"err": "ok", "msg": _(u"标签已是最新，无需更新")}
        except Exception as e:
            logging.error(f"Error updating tags for book {book_id}: {e}")
            return {"err": "internal", "msg": _(u"更新标签时发生错误，请稍后再试")}


class BookAIFill(BaseHandler):
    """使用 AI 同步更新单本书的分类、标签、简介和作者介绍"""
    @js
    @auth
    def post(self, id):
        book_id = int(id)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _(u"书籍不存在")}

        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _(u"无权限")}

        result = AIFillInfoService().fill_one(book_id, force=True)
        status = result.get("status", "fail")
        if status == "ok":
            return {
                "err": "ok",
                "msg": _(u"AI 更新成功"),
                "category": result.get("category", ""),
                "tags": result.get("tags", []),
            }
        return {"err": "ai.fill.failed", "msg": result.get("msg", _(u"AI 更新失败"))}


class BookUpdateTags(BaseHandler):
    """Batch update tags for all books with a specific tag"""
    @js
    @auth
    def post(self):
        if not self.is_admin():
            return {"err": "user.no_permission", "msg": _(u"无权限")}

        tag_name = self.get_argument("tag", "").strip()
        if not tag_name:
            return {"err": "params.invalid", "msg": _(u"请指定标签名称")}

        try:
            # Search books by tag
            query = f'tags:="{tag_name}"'
            book_ids = self.calibre_db_cache.search(query)

            if not book_ids:
                return {"err": "ok", "msg": _(u"未找到包含该标签的书籍"), "count": 0}

            # Convert to list to avoid "Set changed size during iteration" error
            book_ids = list(book_ids)

            # Limit to 300 books
            total_count = len(book_ids)
            if total_count > 300:
                book_ids = book_ids[:300]
                logging.info(f"Limiting tag update to first 300 books out of {total_count}")

            # Call AutoFillService to update tags in background
            AutoFillService().auto_fill_all(book_ids, only_tags=True)

            msg = _(u"已提交 %d 本书籍的标签更新任务，正在后台处理, 请稍后刷新查看结果") % len(book_ids)
            if total_count > 300:
                msg += _(u"（共找到 %d 本，仅处理前 300 本）") % total_count

            return {"err": "ok", "msg": msg, "count": len(book_ids), "total": total_count}

        except Exception as e:
            logging.error(f"Error in batch tag update for tag {tag_name}: {e}")
            return {"err": "internal", "msg": _(u"批量更新标签时发生错误")}


class BookCategory(BaseHandler):
    @js
    @auth
    def post(self, id):
        book_id = int(id)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _(u"书籍不存在")}

        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _(u"无权限")}

        data = tornado.escape.json_decode(self.request.body)
        category = data.get(COLUMN_CATEGORY, "").strip()
        if category == '清除' or category.lower() == 'clear':
            category = ''
        logging.info(f"Updating category for book {book_id}: {category}")
        try:
            # Use set_field directly on the cache to avoid Metadata object issues
            self.calibre_db_cache.set_field(CALIBRE_COLUMN_CATEGORY, {book_id: category})
            return {"err": "ok", "msg": _(u"分类更新成功")}
        except Exception as e:
            logging.error(f"Error updating category for book {book_id}: {e}")
            return {"err": "internal", "msg": _(u"更新分类失败")}


class BookCategoryBatch(BaseHandler):
    @js
    @auth
    def post(self):
        if not self.is_admin():
            return {"err": "user.no_permission", "msg": _(u"无权限")}

        data = tornado.escape.json_decode(self.request.body)
        category = data.get(COLUMN_CATEGORY, "").strip()
        author = data.get("author", "").strip()
        tag = data.get("tag", "").strip()

        if not category:
            return {"err": "params.category.empty", "msg": _(u"分类不能为空")}

        if not author and not tag:
            return {"err": "params.invalid", "msg": _(u"必须指定作者或标签")}

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
                return {"err": "internal", "msg": _(u"搜索作者书籍失败")}

        if tag:
            # Search by tag
            try:
                query = f'tags:="{tag}"'
                ids = self.calibre_db_cache.search(query)
                book_ids.update(ids)
            except Exception as e:
                logging.error(f"Error searching books by tag {tag}: {e}")
                return {"err": "internal", "msg": _(u"搜索标签书籍失败")}

        if not book_ids:
            return {"err": "ok", "msg": _(u"未找到符合条件的书籍"), "count": 0}

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

            return {"err": "ok", "msg": _(u"成功更新 %d 本书籍分类") % count, "count": count}
        except Exception as e:
            logging.error(f"Error batch updating category: {e}")
            return {"err": "internal", "msg": _(u"批量更新分类失败")}


class BookCategories(BaseHandler):
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
            return {"err": "ok", "categories": categories}
        except Exception as e:
            logging.error(f"Error fetching categories: {e}")
            return {"err": "internal", "msg": _(u"获取分类列表失败")}


class BookConverter(BaseHandler):
    @js
    @auth
    def post(self, id):
        book_id = int(id)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _(u"书籍不存在")}

        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _(u"无权限")}

        fmts = []
        paths = []
        for fmt in ["epub", "azw3", "mobi", "azw", "txt"]:
            book_path = book.get("fmt_%s" % fmt, None)
            if book_path:
                fmts.append(fmt)
                paths.append(book_path)

        if len(fmts) == 0:
            return {"err": "params.book.invalid", "msg": _(u"本书不支持转换，仅支持EPUB,TXT以及Kindle使用的格式")}
        if ('epub' in fmts) and ('azw3' in fmts):
            return {"err": "params.book.invalid", "msg": _(u"本书已有EPUB和Kindle版本, 不需要转换")}

        if fmts[0] == "epub":
            fmt = "azw3"
        else:
            fmt = "epub"
        fpath = paths[0]

        service = ConvertService()
        if service.is_book_converting(book):
            return {"err": "params.book.converting", "msg": _(u"本书正在转换中，请稍后再试")}
        service.convert_and_save(self.user_id(), book, fpath, fmt)
        return {"err": "ok", "content": "%s" % _(u"转换成功，请稍后刷新页面查看")}


class BookToPDF(BaseHandler):
    @js
    @auth
    def post(self, id):
        book_id = int(id)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _(u"书籍不存在")}

        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _(u"无权限")}

        fmts = []
        paths = []
        has_pdf = False
        for fmt in ["epub", "azw3", "mobi", "azw", "pdf"]:
            book_path = book.get("fmt_%s" % fmt, None)
            if not book_path:
                continue
            if fmt == "pdf":
                has_pdf = True
                continue
            fmts.append(fmt)
            paths.append(book_path)

        if has_pdf:
            return {"err": "params.book.invalid", "msg": _(u"本书已有PDF版本, 不需要转换")}
        if len(fmts) == 0:
            return {"err": "params.book.invalid", "msg": _(u"本书不支持转换，仅支持EPUB及Kindle使用的格式转换为PDF")}

        fpath = paths[0]
        service = ConvertService()
        if service.is_book_converting(book):
            return {"err": "params.book.converting", "msg": _(u"本书正在转换中，请稍后再试")}
        service.convert_and_save(self.user_id(), book, fpath, "pdf")
        return {"err": "ok", "content": "%s" % _(u"转换成功，请稍后刷新页面查看")}


class BookSetSole(BaseHandler):
    @js
    @auth
    def post(self, bid):
        book = self.get_book(bid, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _(u"书籍已不存在")}
        bid = book["id"]
        if isinstance(book["collector"], dict):
            cid = book["collector"]["id"]
        else:
            cid = book["collector"].id
        if not self.current_user.can_edit() or not (self.is_admin() or self.is_book_owner(bid, cid)):
            return {"err": "permission", "msg": _(u"无权操作")}

        if not self.current_user.can_delete() or not (self.is_admin() or self.is_book_owner(bid, cid)):
            return {"err": "permission", "msg": _(u"无权操作")}

        succeed = False
        try:
            self.sqlite_session.query(Item).filter(Item.book_id == bid).update({"sole": not book["sole"]})
            self.sqlite_session.commit()
            succeed = True
        except Exception as e:
            self.sqlite_session.rollback()
            logging.error("set book %d sole failed: %s" % (bid, e))

        if succeed:
            return {"err": "ok", "msg": _(u"更新成功")}
        else:
            return {"err": "db.update.failed", "msg": _(u"更新失败，请稍后再试")}


class BookRefer(BaseHandler):
    def plugin_get_book_meta(self, provider_key, provider_value, mi):
        if provider_key == baike.KEY:
            title = re.sub(u"[(（].*", "", mi.title)
            api = baike.BaiduBaikeApi(copy_image=True)
            try:
                return api.get_book(title)
            except:
                raise RuntimeError({"err": "httprequest.baidubaike.failed", "msg": _(u"百度百科查询失败")})

        if provider_key == douban.KEY:
            mi.douban_id = provider_value
            api = douban.DoubanBookApi(
                CONF["douban_apikey"],
                CONF["douban_baseurl"],
                copy_image=True,
                maxCount=CONF["douban_max_count"],
            )
            try:
                return api.get_book(mi)
            except:
                raise RuntimeError({"err": "httprequest.douban.failed", "msg": _(u"豆瓣接口查询失败")})

        if provider_key == youshu.KEY:
            title = re.sub(u"[(（].*", "", mi.title)
            api = youshu.YoushuApi(copy_image=True)
            try:
                return api.get_book(title)
            except:
                raise RuntimeError({"err": "httprequest.youshu.failed", "msg": _(u"优书网查询失败")})
        raise RuntimeError({"err": "params.provider_key.not_support", "msg": _(u"不支持该provider_key")})

    def reset_book_meta(self, book_id):
        book = self.get_book(book_id)
        for fmt in ["epub", "mobi", "azw", "azw3", "txt", "pdf"]:
            book_path = book.get("fmt_%s" % fmt, None)
            if book_path:
                break
        if not book_path:
            return {"err": "params.book.invalid", "msg": _(u"书籍不存在")}
        logging.info("[RESET]reset book meta for %d, path=%s" % (book_id, book_path))

        from calibre.ebooks.metadata.meta import get_metadata
        from calibre.utils.date import now as nowf
        book_name = os.path.basename(book_path)
        logging.error("[RESET]book name = " + repr(book_name))
        fmt = os.path.splitext(book_name)[1]
        fmt = fmt[1:] if fmt else None
        if not fmt:
            return {"err": "params.filename", "msg": _(u"文件名不合法")}
        fmt = fmt.lower()

        # read ebook meta
        with open(book_path, "rb") as stream:
            org_mi = get_metadata(stream, stream_type=fmt, use_libprs_metadata=True)
            org_mi.title = utils.super_strip(org_mi.title)
            org_mi.authors = [utils.super_strip(org_mi.author_sort)]
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
        if org_mi.title and org_mi.title == CALIBRE_ERROR_FLAG:
            return {"err": "book.invalid", "msg": _(u"此书籍文件无法识别, 或者受DRM保护无法处理")}

        if fmt in ["txt", "pdf"]:
            org_mi.title = book_name.replace("." + fmt, "")
            org_mi.authors = [_(u"佚名")]

        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _(u"无权限")}

        org_mi.set("comments", _(u""))
        if org_mi.get("comments", "") == "":
            org_mi.set("comments", _(u"无详细介绍"))
        org_mi.timestamp = nowf()
        self.calibre_db.set_metadata(book_id, org_mi, force_changes=True)
        self.calibre_db_cache.set_field(CALIBRE_COLUMN_CATEGORY, {book_id: ""})
        logging.info("[RESET]reset meta data for %d" % book_id)
        return {"err": "ok", "book_id": book_id}

    @js
    @auth
    def get(self, id):
        book_id = int(id)
        mi = self.calibre_db.get_metadata(book_id, index_is_id=True)
        books = BookSearch.plugin_search_books(
            title=mi.title,
            isbn=mi.isbn,
            publisher=mi.publisher
        )
        keys = [
            "cover_url",
            "source",
            "website",
            "title",
            "author_sort",
            "publisher",
            "isbn",
            "comments",
            "provider_key",
            "provider_value",
        ]
        rsp = []

        for b in books:
            try:
                d = dict((k, b.get(k, "")) for k in keys)
                pubdate = b.get("pubdate")
                d["pubyear"] = pubdate.strftime("%Y") if pubdate else ""
                if not d["comments"]:
                    d["comments"] = _(u"无详细介绍")
                rsp.append(d)
            except Exception as e:
                logging.error("get book meta error: %s" % e)

        return {"err": "ok", "books": rsp}

    @js
    @auth
    def post(self, id):
        from calibre.utils.date import now as nowf
        should_reset = self.get_argument("reset", "no")
        provider_key = self.get_argument("provider_key", "error")
        provider_value = self.get_argument("provider_value", "")
        only_meta = self.get_argument("only_meta", "")
        only_cover = self.get_argument("only_cover", "")
        book_id = int(id)
        mi = self.calibre_db.get_metadata(book_id, index_is_id=True)
        if not mi:
            return {"err": "params.book.invalid", "msg": _(u"书籍不存在")}
        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _(u"无权限")}

        if should_reset == "yes":
            return self.reset_book_meta(book_id)

        if not provider_key:
            return {"err": "params.provider_key.invalid", "msg": _(u"请求参数错误")}
        if not provider_value:
            return {"err": "params.provider_key.invalid", "msg": _(u"请求参数错误")}
        if only_meta == "yes" and only_cover == "yes":
            return {"err": "params.conflict", "msg": _(u"参数冲突")}

        try:
            refer_mi = self.plugin_get_book_meta(provider_key, provider_value, mi)
        except RuntimeError as e:
            return e.args[0]

        if not refer_mi:
            return {"err": "plugin.fail", "msg": _(u"拉取图书信息异常，请重试")}

        if only_cover == "yes":
            # just set cover
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
        self.calibre_db.set_metadata(book_id, mi)
        return {"err": "ok"}


class BookCover(BaseHandler):
    @js
    @auth
    def post(self, id):
        from calibre.utils.date import now as nowf
        book_id = int(id)
        mi = self.calibre_db.get_metadata(book_id, index_is_id=True)
        if not mi:
            return {"err": "params.book.invalid", "msg": _(u"书籍不存在")}

        fileinfo = self.request.files.get('cover_data')
        if not fileinfo:
            return {"err": "params.invalid", "msg": _(u"未上传封面文件")}
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
        return {"err": "ok"}


class BookFavorite(BaseHandler):
    @js
    @auth
    def post(self, id):
        """设置或取消收藏某本书"""
        book_id = int(id)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _(u"书籍已不存在")}

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
        return {"err": "ok", "msg": _(u"%s成功") % action}

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
            book_data = utils.BookFormatter(self, book).format()
            book_data["state"] = utils.ReadingStateFormatter.format_reading_state(state_dict[book_id])
            favorite_books.append(book_data)

        return {"err": "ok",
                "title": _(u"我的收藏"),
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
            return {"err": "params.book.invalid", "msg": _(u"书籍已不存在")}

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
        return {"err": "ok", "msg": _(u"%s成功") % action}

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
            book_data = utils.BookFormatter(self, book).format()
            book_data["state"] = utils.ReadingStateFormatter.format_reading_state(state_dict[book_id])
            favorite_books.append(book_data)

        return {"err": "ok",
                "title": _(u"待读清单"),
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
            book_data = utils.BookFormatter(self, book).format()
            book_data["state"] = utils.ReadingStateFormatter.format_reading_state(state_dict[book_id])
            reading_books.append(book_data)

        return {"err": "ok",
                "title": _(u"在读书籍"),
                "total": len(reading_books),
                "books": reading_books}


class PrintBooks(BaseHandler):
    @js
    def get(self):
        title = _(u"实体书")

        # 查询所有实体书，按添加时间倒序排列
        db_items = self.sqlite_session.query(Item).filter(
            Item.book_type == BOOK_TYPE_PHYSICAL
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
                    Item.book_type == BOOK_TYPE_PHYSICAL
                ).count()
            books = self.get_books(ids=ids)
            books.sort(key=lambda x: x["id"], reverse=True)

            books_result = []
            for book in books:
                book_data = utils.BookFormatter(self, book).format()
                books_result.append(book_data)

            return {"err": "ok",
                    "title": title,
                    "total": total_items,
                    "books": books_result}
        except Exception as e:
            import traceback
            traceback.print_exc()
            logging.error("Failed to get print books: %s", e)
            return {"err": "internal", "msg": _(u"获取实体书失败")}


class BookSoled(BaseHandler):
    @js
    @auth
    def get(self):
        """获取当前用户设为soled的所有图书信息"""
        user_id = self.user_id()
        title = _(u"私有书籍")

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
                book_data = utils.BookFormatter(self, book).format()
                books_result.append(book_data)

            return {"err": "ok",
                    "title": title,
                    "total": total_items,
                    "books": books_result}
        except Exception as e:
            import traceback
            traceback.print_exc()
            logging.error("Failed to get soled books: %s", e)
            return {"err": "internal", "msg": _(u"获取私有书籍失败")}


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
            book_data = utils.BookFormatter(self, book).format()
            book_data["state"] = utils.ReadingStateFormatter.format_reading_state(state_dict[book_id])
            read_done_books.append(book_data)

        return {"err": "ok",
                "title": _(u"已读完书籍"),
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
            book_data = utils.BookFormatter(self, book).format()
            book_data["state"] = utils.ReadingStateFormatter.format_reading_state(state)
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
            book_data = utils.BookFormatter(self, book).format()
            book_data["state"] = utils.ReadingStateFormatter.format_reading_state(state)
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


class LibraryStats(BaseHandler):
    _cache_data = None
    _cache_time = 0

    def _get_stats(self):
        import datetime
        from sqlalchemy import func, extract
        from ..models import Item

        # 获取当前月份和年份
        now = datetime.datetime.now()
        current_year = now.year
        current_month = now.month

        # 查询所有书籍ID
        all_book_ids = list(self.calibre_db_cache.all_book_ids())
        total_books = len(all_book_ids)

        # 从items表统计书籍类型
        ebook_count = 0
        physical_count = 0
        month_ebook_count = 0
        month_physical_count = 0

        if all_book_ids:
            # 统计实体书数量 (book_type = 1, 需要加总book_count)
            physical_books = self.sqlite_session.query(func.sum(Item.book_count)).filter(
                Item.book_id.in_(all_book_ids),
                Item.book_type == 1
            ).scalar()
            physical_count = physical_books if physical_books else 0

            # 统计电子书数量 (book_type = 0)
            ebook_count = total_books - physical_count

            # 本月新增电子书数量
            month_ebook_count = self.sqlite_session.query(Item).filter(
                Item.book_id.in_(all_book_ids),
                Item.book_type == 0,
                extract('year', Item.create_time) == current_year,
                extract('month', Item.create_time) == current_month
            ).count()

            # 本月新增实体书数量 (加总book_count)
            month_physical_books = self.sqlite_session.query(func.sum(Item.book_count)).filter(
                Item.book_id.in_(all_book_ids),
                Item.book_type == 1,
                extract('year', Item.create_time) == current_year,
                extract('month', Item.create_time) == current_month
            ).scalar()
            month_physical_count = month_physical_books if month_physical_books else 0

        return {
            "total_books": total_books,
            "ebook_count": ebook_count,
            "physical_count": physical_count,
            "month_ebook_count": month_ebook_count,
            "month_physical_count": month_physical_count,
        }

    @js
    def get(self):
        """获取书库统计信息"""
        import datetime
        now = datetime.datetime.now()
        current_year = now.year
        current_month = now.month

        stats = None
        # check cache
        if time.time() - LibraryStats._cache_time < 30 and LibraryStats._cache_data:
            stats = LibraryStats._cache_data
        else:
            try:
                stats = self._get_stats()
                LibraryStats._cache_data = stats
                LibraryStats._cache_time = time.time()
            except Exception as e:
                logging.error("Failed to get library stats: %s", e)
                if LibraryStats._cache_data:
                    stats = LibraryStats._cache_data
                else:
                    # fallback to empty stats
                    stats = {
                        "total_books": 0,
                        "ebook_count": 0,
                        "physical_count": 0,
                        "month_ebook_count": 0,
                        "month_physical_count": 0,
                    }

        stats["current_year"] = current_year
        stats["current_month"] = current_month
        return {"err": "ok", "stats": stats}


class BookReadingState(BaseHandler):
    @js
    @auth
    def post(self, id):
        """设置某本书的阅读状态"""
        book_id = int(id)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _(u"书籍已不存在")}

        user_id = self.user_id()
        data = tornado.escape.json_decode(self.request.body)
        read_state = data.get("read_state", 0)

        # 验证阅读状态值
        if read_state not in [0, 1, 2]:
            return {"err": "params.invalid", "msg": _(u"阅读状态参数错误")}

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
        return {"err": "ok", "msg": _(u"阅读状态已设置为：%s") % state_names[read_state]}

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

        return utils.ReadingStateFormatter.format_reading_state_with_api_format(reading_state)


class BookEdit(BaseHandler):
    def edit_book(self, bid, data):
        from calibre.utils.date import now as nowf
        mi = self.calibre_db.get_metadata(bid, index_is_id=True)
        KEYS = [
            "authors",
            "title",
            "comments",
            "tags",
            "publisher",
            "isbn",
            "series",
            "rating",
            "languages"
        ]
        for key, val in data.items():
            if key not in KEYS:
                continue
            mi.set(key, val)

        if data.get("pubdate", None):
            content = douban.str2date(data["pubdate"])
            if content is None:
                return {"err": "params.pudate.invalid", "msg": _(u"出版日期参数错误，格式应为 2026-05-10或2026-05或2026年或2026")}
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
        mi.timestamp = nowf()
        self.calibre_db.set_metadata(bid, mi, force_changes=True)
        return True

    @js
    @auth
    def post(self, bid):
        book = self.get_book(bid, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _(u"书籍已不存在")}
        bid = book["id"]
        update_books = []
        if isinstance(book["collector"], dict):
            cid = book["collector"]["id"]
        else:
            cid = book["collector"].id
        if not self.current_user.can_edit() or not (self.is_admin() or self.is_book_owner(bid, cid)):
            return {"err": "permission", "msg": _(u"无权操作")}

        data = tornado.escape.json_decode(self.request.body)
        # output data
        logging.info(f"Book edit data: {data}")
        id_list = data.get("ids", None)
        if id_list and bid in id_list:
            # 仅当有列表，且当前书籍在列表中时，才进行批量更新
            for bid in id_list:
                self.edit_book(bid, data)
                update_books.append(bid)
            return {"err": "ok", "msg": _(u"更新成功"), "books": update_books}
        else:
            self.edit_book(bid, data)
            update_books = [bid]
        return {"err": "ok", "msg": _(u"更新成功"), "books": update_books}


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
            return {"err": "permission", "msg": _(u"无权操作")}

        if not self.current_user.can_delete() or not (self.is_admin() or self.is_book_owner(bid, cid)):
            return {"err": "permission", "msg": _(u"无权操作")}

        # 删除整本书
        AudioUtils.clear_audio(bid)

        # 对应删除Item
        try:
            item = self.sqlite_session.query(Item).filter(Item.book_id == bid).first()
            if item:
                self.sqlite_session.delete(item)
                self.sqlite_session.commit()
        except Exception as e:
            logging.error(f"删除书籍《{book['title']}》的Item记录失败: {e}")

        try:
            self.calibre_db.delete_book(bid)
            self.add_msg("success", _(u"删除书籍《%s》") % book["title"])
            return {"err": "ok", "msg": _(u"删除成功")}
        except Exception as e:
            logging.error(f"删除书籍《{book['title']}》失败: {e}")
            return {"err": "fail", "msg": _(u"删除失败, 请查看日志。如果一直出错，请联系管理员。")}


class BookDeleteFormat(BaseHandler):
    @js
    @auth
    def post(self, bid):
        book = self.get_book(bid, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _(u"书籍已不存在")}
        bid = book["id"]

        if isinstance(book["collector"], dict):
            cid = book["collector"]["id"]
        else:
            cid = book["collector"].id
        if not self.current_user.can_edit() or not (self.is_admin() or self.is_book_owner(bid, cid)):
            return {"err": "permission", "msg": _(u"无权操作")}

        if not self.current_user.can_delete() or not (self.is_admin() or self.is_book_owner(bid, cid)):
            return {"err": "permission", "msg": _(u"无权操作")}

        try:
            data = tornado.escape.json_decode(self.request.body)
            fmt = data.get("format", "").strip().lower()
        except:
            return {"err": "params.invalid", "msg": _(u"请求参数格式错误")}

        if not fmt:
            return {"err": "params.missing", "msg": _(u"格式参数不能为空")}

        fmt_key = "fmt_%s" % fmt
        if fmt_key not in book:
            return {"err": "format.not_found", "msg": _(u"书籍不包含 %s 格式") % fmt.upper()}

        # 检查书籍是否只有一个格式
        available_formats = book.get("available_formats", "")
        available_formats = [f.strip() for f in available_formats if f.strip()]
        if len(available_formats) <= 1:
            return {"err": "last.format", "msg": _(u"书籍只有一个格式，无法刪除")}

        try:
            self.calibre_db_cache.remove_formats({bid: [fmt.upper()]})
            self.add_msg("success", _(u"删除书籍《%s》的%s格式") % (book["title"], fmt))
            return {"err": "ok", "msg": _(u"删除%s格式成功" % fmt)}
        except Exception as e:
            logging.error(f"删除书籍《{book['title']}》的{fmt}格式失败: {e}")
            return {"err": "fail", "msg": _(u"删除%s格式失败, 请查看日志。如果一直出错，请联系管理员。" % fmt)}


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
                    raise web.HTTPError(403, reason=_(u"无权操作，请先登录注册邮箱激活账号。"))
            else:
                raise web.HTTPError(403, reason=_(u"无权操作"))

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
            raise web.HTTPError(404, reason=_(u"%s格式无法下载" % fmt))

        path = book["fmt_%s" % fmt]
        book["fmt"] = fmt
        book["title"] = urllib.parse.quote_plus(book["title"])
        fname = "%(id)d-%(title)s.%(fmt)s" % book
        att = u"attachment; filename=\"%s\"; filename*=UTF-8''%s" % (fname, fname)
        if self.is_opds:
            att = u'attachment; filename="%(id)d.%(fmt)s"' % book

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
        title = _(u"新书推荐")
        ids = self.books_by_id()
        return self.render_book_list([], ids=ids, title=title, sort_fields="id")


class SearchBook(ListHandler):
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
        logging.debug(f"[TRACE]Word segmentation search took {time.time() - start:.2f} seconds.")
        return or_query

    def get(self):
        name = self.get_argument("name", "").strip()
        book_title = self.get_argument("title", "").strip()  # 传入此参数代表只按名称搜索
        exclude_id = int(self.get_argument("exclude", "0").strip())
        seg = int(self.get_argument("seg", "0").strip())  # 是否进行分词查询
        order_by = self.get_argument("order", "").strip()

        if not name and not book_title:
            return self.write({"err": "params.invalid", "msg": _(u"请输入搜索关键字")})

        title_search = len(book_title) > 0
        if title_search:
            name = book_title

        title = _(u"搜索：%(name)s") % {"name": name}
        ids = []
        seen = set()

        seg_or_query = None
        # 只有当 seg=1 时才进行分词搜索
        if seg == 1 and title_search:
            # 分词搜索：当name长度在2-10之间且jieba可用时
            seg_or_query = self._search_by_segmentation(name, ids, seen)

        # 简繁体转换搜索（合并为一次查询）
        start = time.time()
        converted_names = [name]
        for profile in ['s2t', 't2s']:
            converted_name = opencc.OpenCC(profile).convert(name)
            if converted_name != name:
                converted_names.append(converted_name)
        if converted_names:
            try:
                if title_search:
                    # 对于精确标题搜索，构建OR查询
                    query = " OR ".join([f'title:={cn}' for cn in converted_names])
                else:
                    # 主要是comments字段的搜索比较耗时
                    query = " OR ".join(converted_names)
                if seg_or_query:
                    query = f"({query}) OR ({seg_or_query})"
                logging.debug(f"Searching books with query: {query}")
                ids2 = self.calibre_db_cache.search(query)
                if ids2:
                    self._add_books(ids2, ids, seen)
            except Exception as e:
                logging.error("Search book failed: %s" % e)
        logging.debug(f"[TRACE] search took {time.time() - start:.2f} seconds.")

        if exclude_id > 0 and exclude_id in seen:
            if exclude_id in ids:
                ids.remove(exclude_id)

        # 查询被别的用户标记为sole的图书ID，并将ids中对应的ID去除
        sole_book_ids = set(item.book_id for item in self.sqlite_session.query(Item).filter(Item.sole == 1, Item.collector_id != self.user_id()).all())
        ids = [book_id for book_id in ids if book_id not in sole_book_ids]

        return self.render_book_list([], ids=ids, title=title, sort_fields=order_by)


class HotBook(ListHandler):
    def get(self):
        title = _(u"热度榜单")
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
            return {"err": "permission", "msg": _(u"无权操作")}
        data = tornado.escape.json_decode(self.request.body)
        isbn = data.get("isbn", "").strip()
        if not isbn:
            return {"err": "params.invalid", "msg": _(u"请输入ISBN号")}

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
            self.calibre_db_cache.set_field(CALIBRE_COLUMN_PHY_COUNT, {book_id: book_count})
            self.calibre_db_cache.set_field(CALIBRE_COLUMN_BOOK_TYPE, {book_id: BOOK_TYPE_PHYSICAL})
            return {"err": "ok", "msg": _(u"实体书数量已更新，当前数量：%d") % book_count, "book_id": book_id}

        logging.info("Adding new book by ISBN: %s" % isbn)
        # 通过Douban API查询ISBN的图书信息
        douban_api = douban.DoubanBookApi(
            CONF["douban_apikey"],
            CONF["douban_baseurl"],
            copy_image=True,
            maxCount=1
        )
        try:
            try:
                md = douban.SimpleMetaData(isbn=isbn)
                book_data = douban_api.get_book(md)
            except Exception as e:
                logging.error(f"Douban API error for ISBN {isbn}: {e}")
                book_data = None

            if not book_data:
                # 尝试使用XhsdBookApi
                try:
                    logging.info(f"Trying Xhsd API for ISBN {isbn}")
                    xhsd_api = xhsd.XhsdBookApi()
                    book_data = xhsd_api.get_book_by_isbn(isbn)
                except Exception as e:
                    logging.error(f"Xhsd API error for ISBN {isbn}: {e}")
                    book_data = None

            if not book_data:
                return {"err": "book.notfound", "msg": _(u"未找到该ISBN号对应的图书")}

            # 通过上面返回的book metadata, 添加图书到calibre中（不需要文件，仅metadata）
            book_id = self.calibre_db.create_book_entry(book_data)
            if book_id is None:
                return {"err": "book.duplicate", "msg": _(u"该图书已存在或创建失败")}

            try:
                self.calibre_db_cache.set_field(CALIBRE_COLUMN_BOOK_TYPE, {book_id: BOOK_TYPE_PHYSICAL})
                self.calibre_db_cache.set_field(CALIBRE_COLUMN_PHY_COUNT, {book_id: 1})
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
            return {"err": "ok", "msg": _(u"图书添加成功"), "book_id": book_id}
        except Exception as e:
            logging.error("Failed to add book by ISBN: %s", e)
            return {"err": "internal", "msg": _(u"查询ISBN失败，请在系统设置中配置互联网信息源中插件地址。如http://douban-rs-api:80/。")}


class BookUpload(BaseHandler):
    @classmethod
    def convert(cls, s):
        try:
            return s.group(0).encode("latin1").decode("utf8")
        except:
            return s.group(0)

    def _add_new_book(self, mi, fpaths):
        book_id = self.calibre_db.import_book(mi, fpaths)
        self.increase_history_count("upload_history")
        item = Item()
        item.book_id = book_id
        item.collector_id = self.user_id()
        self.sqlite_session.add(item)
        self.sqlite_session.commit()
        AutoFillService().auto_fill(book_id)
        return book_id

    def get_upload_file(self):
        # for unittest mock
        if "ebook" not in self.request.files:
            return None, None
        p = self.request.files["ebook"][0]
        return (p["filename"], p["body"])

    @js
    def post(self):
        from calibre.ebooks.metadata.meta import get_metadata

        if CONF["ALLOW_GUEST_UPLOAD"] is False:
            if self.is_guest():
                return {"err": "permission", "msg": _(u"无权操作，请先登录")}
            if not self.current_user.can_upload():
                return {"err": "permission", "msg": _(u"无权操作")}

        name, data = self.get_upload_file()
        if name is None:
            return {"err": "params.filename", "msg": _(u"文件不存在或未选择文件")}

        name = re.sub(r"[\x80-\xFF]+", BookUpload.convert, name)
        logging.error("upload book name = " + repr(name))
        fmt = os.path.splitext(name)[1]
        fmt = fmt[1:] if fmt else None
        if not fmt:
            return {"err": "params.filename", "msg": _(u"文件名不合法, 没有扩展名")}
        fmt = fmt.lower()
        if fmt not in SUPPORTED_EBOOK_FORMATS:
            return {"err": "params.format.unsupported", "msg": _(u"不支持的书籍格式: %s" % fmt)}

        # save file
        fpath = os.path.join(CONF["upload_path"], name)
        with open(fpath, "wb") as f:
            f.write(data)
        logging.debug("save upload file into [%s]", fpath)

        # read ebook meta
        failed = False
        with open(fpath, "rb") as stream:
            mi = get_metadata(stream, stream_type=fmt, use_libprs_metadata=True)
            if mi.title and mi.title == CALIBRE_ERROR_FLAG:
                logger.error("Failed to get metadata for %s, reason:%s", fpath, mi.comments)
                failed = True
            mi.title = utils.super_strip(mi.title)
            if mi.author_sort == "Unknown" and mi.authors and len(mi.authors) > 0:
                mi.authors = [utils.super_strip(a) for a in mi.authors]
            else:
                mi.authors = [utils.super_strip(mi.author_sort)]

        if failed:
            Path(fpath).unlink(missing_ok=True)
            return {"err": "book.invalid", "msg": _(u"此书籍文件无法识别, 或者受DRM保护无法导入")}

        # 非结构化的格式，calibre无法识别准确的信息，直接从文件名提取
        if fmt == "txt":
            mi.title = utils.remove_zlibrary_suffix(name.replace("." + fmt, ""))
            mi.authors = [_(u"佚名")]

        if fmt == "pdf":
            if mi.title is None or mi.title.strip() == "":
                mi.title = utils.remove_zlibrary_suffix(name.replace("." + fmt, ""))
            if mi.authors is None or len(mi.authors) == 0 or mi.authors[0].lower() == "unknown":
                mi.authors = [_(u"佚名")]

        logging.info("upload mi.title = " + repr(mi.title))
        books = self.calibre_db.books_with_same_title(mi)
        if books:
            book_id = None
            for id in books:
                b = self.calibre_db.get_metadata(id, index_is_id=True)
                logging.debug(f"book id:{id}, book_type:{b.get(CALIBRE_COLUMN_BOOK_TYPE, BOOK_TYPE_EBOOK)}")
                logging.debug(f"  existed formats: {b.formats}")
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
                        "msg": _(u"同名书籍《%s》已存在这一图书格式 %s") % (mi.title, fmt),
                        "book_id": b.get("id")
                    }
            logging.debug("import [%s] from %s with format %s", repr(mi.title), fpath, fmt)
            if book_id is None:
                # New EBOOK
                book_id = self._add_new_book(mi, [fpath])
            else:
                self.calibre_db.add_format(book_id, fmt.upper(), fpath, True)
        else:
            fpaths = [fpath]
            book_id = self._add_new_book(mi, fpaths)
        self.add_msg("success", _(u"导入书籍成功！"))
        return {"err": "ok", "book_id": book_id}


class BookUploadChunk(BaseHandler):
    """Handler for chunked file upload"""

    def _add_new_book(self, mi, fpaths):
        book_id = self.calibre_db.import_book(mi, fpaths)
        self.increase_history_count("upload_history")
        item = Item()
        item.book_id = book_id
        item.collector_id = self.user_id()
        self.sqlite_session.add(item)
        self.sqlite_session.commit()
        AutoFillService().auto_fill(book_id)
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
                return {"err": "permission", "msg": _(u"无权操作，请先登录")}
            if not self.current_user.can_upload():
                return {"err": "permission", "msg": _(u"无权操作")}

        # Get parameters from form data
        filename = self.get_argument("filename", "")
        chunk_index = int(self.get_argument("chunk_index", 0))
        total_chunks = int(self.get_argument("total_chunks", 1))
        file_hash = self.get_argument("file_hash", "")

        if not filename:
            return {"err": "params.filename", "msg": _(u"文件名不能为空")}
        filename = re.sub(r"[\x80-\xFF]+", BookUpload.convert, filename)
        logging.error("upload book name = " + repr(filename))
        fmt = os.path.splitext(filename)[1]
        fmt = fmt[1:] if fmt else None
        if not fmt:
            return {"err": "params.filename", "msg": _(u"文件名不合法，没有包含扩展名")}
        fmt = fmt.lower()
        if fmt not in SUPPORTED_EBOOK_FORMATS:
            return {"err": "params.format.unsupported", "msg": _(u"不支持的书籍格式: %s" % fmt)}

        if not file_hash:
            return {"err": "params.hash", "msg": _(u"文件hash不能为空")}

        # Get the chunk data
        if "chunk" not in self.request.files:
            return {"err": "params.chunk", "msg": _(u"未找到文件块数据")}

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
                "msg": _(u"块上传成功"),
                "received_chunks": len(received_chunks),
                "total_chunks": total_chunks
            }

    def _merge_chunks_and_import(self, filename, file_hash, total_chunks, temp_dir):
        """Merge all chunks and import the book"""
        from calibre.ebooks.metadata.meta import get_metadata

        try:
            # Clean filename
            filename = re.sub(r"[\x80-\xFF]+", BookUpload.convert, filename)
            fmt = os.path.splitext(filename)[1]
            fmt = fmt[1:] if fmt else None
            if not fmt:
                return {"err": "params.filename", "msg": _(u"文件名不合法")}
            fmt = fmt.lower()

            # Merge chunks into final file
            final_path = os.path.join(CONF["upload_path"], filename)
            with open(final_path, "wb") as outfile:
                for i in range(total_chunks):
                    chunk_path = os.path.join(temp_dir, f"chunk_{i}")
                    with open(chunk_path, "rb") as chunk_file:
                        outfile.write(chunk_file.read())

            # Clean up temporary chunks
            import shutil
            shutil.rmtree(temp_dir)

            logging.debug("Merged chunked upload file into [%s]", final_path)

            # Read ebook metadata (same logic as BookUpload)
            failed = False
            with open(final_path, "rb") as stream:
                mi = get_metadata(stream, stream_type=fmt, use_libprs_metadata=True)
                if mi.title and mi.title == CALIBRE_ERROR_FLAG:
                    logger.error("Failed to get metadata for %s, reason:%s", final_path, mi.comments)
                    failed = True
                mi.title = utils.super_strip(mi.title)
                if mi.author_sort == "Unknown" and mi.authors and len(mi.authors) > 0:
                    mi.authors = [utils.super_strip(a) for a in mi.authors]
                else:
                    mi.authors = [utils.super_strip(mi.author_sort)]
            if failed:
                Path(final_path).unlink(missing_ok=True)
                return {"err": "book.invalid", "msg": _(u"此书籍文件无法识别, 或者受DRM保护无法导入")}

            # Handle special formats like txt and pdf
            if fmt in ["txt", "pdf"]:
                mi.title = utils.remove_zlibrary_suffix(filename.replace("." + fmt, ""))
                mi.authors = [_(u"佚名")]

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
                            "msg": _(u"同名书籍《%s》已存在这一图书格式 %s") % (mi.title, fmt),
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

            self.add_msg("success", _(u"导入书籍成功！"))
            return {"err": "ok", "book_id": book_id}

        except Exception as e:
            logging.error("Error in chunked upload: %s", str(e))
            # Clean up on error
            if os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)
            return {"err": "upload_error", "msg": _(u"文件上传处理失败：%s") % str(e)}


class BookRead(BaseHandler):
    def get(self, id):
        if not CONF["ALLOW_GUEST_READ"] and not self.current_user:
            return self.redirect("/login")

        if self.current_user:
            if self.current_user.can_read():
                if not self.current_user.is_active():
                    raise web.HTTPError(403, reason=_(u"无权在线阅读，请先登录注册邮箱激活账号。"))
            else:
                raise web.HTTPError(403, reason=_(u"无权在线阅读"))

        book = self.get_book(id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _(u"书籍已不存在")}
        book_id = book["id"]
        self.user_history("read_history", book)
        self.count_increase(book_id, count_download=1)

        # 优先阅读epub/azw3/mobi/txt格式
        for fmt in ["epub", "mobi", "azw", "azw3", "txt"]:
            fpath = book.get("fmt_%s" % fmt, None)
            if not fpath:
                continue

            if fmt != 'epub':
                ConvertService().convert_and_save(self.user_id(), book, fpath, "epub")

            # epub_dir is for javascript
            epub_dir = "/get/extract/%s" % book["id"]
            return self.html_page("book/" + CONF["EPUB_VIEWER"], {
                "book": book,
                "epub_dir": epub_dir,
                "is_ready": (fmt == 'epub'),
                "CANDLE_READER_SERVER": CONF["CANDLE_READER_SERVER"],
            })

        if "fmt_pdf" in book:
            # PDF类书籍需要检查下载权限。
            if not CONF["ALLOW_GUEST_DOWNLOAD"] and not self.current_user:
                return self.redirect("/login")

            if self.current_user and not self.current_user.can_save():
                raise web.HTTPError(403, reason=_(u"无权在线阅读PDF类书籍"))

            pdf_url = urllib.parse.quote_plus(self.api_url + "/api/book/%(id)d.PDF" % book)
            pdf_reader_url = CONF["PDF_VIEWER"] % {"pdf_url": pdf_url}
            return self.redirect(pdf_reader_url)

        if 'fmt_txt' in book:
            # TXT有专门的阅读器
            txt_reader_url = f'/book/{book_id}/readtxt'
            return self.redirect(txt_reader_url)

        raise web.HTTPError(404, reason=_(u"抱歉，在线阅读器暂不支持该格式的书籍"))


class TxtRead(BaseHandler):
    @js
    @auth
    def get(self):
        bid = self.get_argument("id", "")
        book = self.get_book(bid)
        start = int(self.get_argument("start", "0"))
        end = int(self.get_argument("end", "-1"))
        logging.info(book)
        fpath = book.get("fmt_txt", None)
        if not fpath:
            return {"err": "format error", "msg": "非txt书籍"}
        with open(fpath, mode='rb') as file:
            # 移动文件指针到起始位置
            file.seek(start)
            if end == -1:
                content = file.read()
            else:
                # 读取从起始位置到结束位置的内容
                content = file.read(end - start)
        if not content:
            return {"err": "format error", "msg": "空文件"}
        encode = get_content_encoding(content)
        content = content.decode(encoding=encode, errors='ignore').replace("\r", "").replace("\n", "<br>")
        return {"err": "ok", "content": content}


class BookTxtInit(BaseHandler):
    @js
    def get(self):
        bid = self.get_argument("id", "")
        test_ready = self.get_argument("test", "")
        book = self.get_book(bid)
        fpath = book.get("fmt_txt", None)
        if not fpath:
            return {"err": "format error", "msg": "非txt书籍"}
        # 解压后的目录
        fdir = os.path.join(CONF["extract_path"], str(book["id"]))
        # txt 解析出的目录文件
        content_path = fdir + "/content.json"
        is_ready = os.path.isfile(content_path)
        if is_ready:
            with open(content_path, 'r', encoding='utf8') as f:
                meta = json.loads(f.read())
            return {"err": "ok", "msg": "已解析", "data": {
                "content": meta['toc'],
                "encoding": meta['encoding'],
                "name": book["title"]
            }}
        if test_ready != "0":
            return {"err": "ok", "msg": "未解析完成"}

        # 若未解析则计算预计等待时间，至少2分钟
        wait = min(120, os.path.getsize(fpath) / (1024 * 1024) * 15)
        ExtractService().parse_txt_content(bid, fpath)
        que_len = ExtractService().get_queue('parse_txt_content').qsize()
        return {"err": "ok", "msg": "已加入队列", "data": {
            "wait": wait,
            "name": book["title"],
            "path": content_path,
            "que": que_len
        }}


class BookSuggestion(ListHandler):
    @js
    def get(self, id):
        book = self.get_book(id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _(u"书籍已不存在")}

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
            "msg": _(u"推荐成功"),
            "books": [self.fmt(b) for b in similar_books]
        }


class BookSendToDevice(BaseHandler):
    @js
    def post(self, bid):
        """发送书籍到指定设备"""
        book_id = int(bid)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "book.not_found", "msg": _(u"书籍已不存在")}

        # 检查用户权限
        if not CONF["ALLOW_GUEST_PUSH"]:
            if not self.current_user:
                return {"err": "user.need_login", "msg": _(u"请先登录")}
            else:
                if not self.current_user.can_push():
                    return {"err": "permission", "msg": _(u"无权操作")}
                elif not self.current_user.is_active():
                    return {"err": "permission", "msg": _(u"无权操作，请先激活账号。")}

        # 解析请求参数
        try:
            data = tornado.escape.json_decode(self.request.body)
            device_type = data.get("device_type", "").lower()
            device_url = data.get("device_url", "")
            mailbox = data.get("mailbox", "")
        except:
            return {"err": "params.invalid", "msg": _(u"请求参数格式错误")}

        # Kindle设备使用邮箱地址，其他设备使用device_url
        if device_type == "kindle":
            if not mailbox:
                return {"err": "params.missing", "msg": _(u"Kindle设备需要提供邮箱地址")}
        else:
            if not device_type or not device_url:
                return {"err": "params.missing", "msg": _(u"设备类型和设备地址不能为空")}

        # 支持的设备类型
        supported_types = ["duokan", "ireader", "hanwang", "boox", "dangdang", "kindle"]
        if device_type not in supported_types:
            return {"err": "device.unsupported", "msg": _(u"不支持的设备类型: %s") % device_type}

        # Kindle设备通过邮件发送
        if device_type == "kindle":
            return self._send_to_kindle(book, book_id, mailbox)
        else:
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
                    _(u"服务器正在推送《%(title)s》到%(email)s") % {"title": book["title"], "email": mail_to},
                )
                return {"err": "ok", "msg": _(u"服务器后台正在推送。您可关闭此窗口，继续浏览其他书籍。")}

        # 如果没有可直接发送的格式，检查是否有azw3或mobi格式需要转换
        if "fmt_azw3" in book or "fmt_mobi" in book:
            fmt = "azw3" if "fmt_azw3" in book else "mobi"
            logging.info(f"[SEND_TO_KINDLE] 找到{fmt}格式，需要转换为epub后发送")
            ConvertService().convert_and_send(self.user_id(), self.site_url, book, mail_to)
            self.add_msg(
                "success",
                _(u"服务器正在推送《%(title)s》到%(email)s") % {"title": book["title"], "email": mail_to},
            )
            return {"err": "ok", "msg": _(u"服务器正在转换格式，稍后将自动推送。您可关闭此窗口，继续浏览其他书籍。")}

        # 没有Kindle支持的格式
        return {
            "err": "format.not_supported",
            "msg": _(u"书籍没有Kindle支持的格式!")
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
            return {"err": "file.not_found", "msg": _(u"书籍没有支持的文件格式（epub/azw3/pdf/txt）")}

        # 检查文件是否存在
        if not os.path.exists(file_path):
            return {"err": "file.missing", "msg": _(u"书籍文件不存在: %s") % file_path}

        # 导入对应的上传器
        try:
            from webserver.plugins.sending.uploader import DuokanUploader, IReaderUploader, HanwangUploader
            from webserver.plugins.sending.uploader import BooxUploader, DangdangUploader

            uploader_map = {
                "duokan": DuokanUploader,
                "ireader": IReaderUploader,
                "hanwang": HanwangUploader,
                "boox": BooxUploader,
                "dangdang": DangdangUploader,
            }

            uploader_class = uploader_map.get(device_type)
            if not uploader_class:
                return {"err": "uploader.not_found", "msg": _(u"找不到对应的上传器: %s") % device_type}

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
                return {"err": "ok", "msg": _(u"书籍发送成功")}
            else:
                error_type = result.get('error_type', 'unknown')
                error_msg = result.get('message', '发送失败')

                if error_type == 'connection':
                    return {"err": "connection.failed", "msg": _(u"无法连接到设备。请确认IP地址正确，且设备已开启WiFi上传功能")}
                elif error_type == 'timeout':
                    return {"err": "upload.timeout", "msg": _(u"上传超时。请检查网络连接和设备状态")}
                elif error_type == 'http':
                    status_code = result.get('status_code', 0)
                    return {"err": "upload.failed", "msg": _(u"上传失败 (HTTP %d)。请查看日志获取详细信息") % status_code}
                else:
                    return {"err": "upload.error", "msg": _(u"上传过程出错: %s。请查看日志获取详细信息") % error_msg}

        except ImportError as e:
            logging.error(f"[SEND_TO_DEVICE] 导入上传器失败: {e}")
            return {"err": "uploader.import_error", "msg": _(u"设备上传功能不可用")}
        except Exception as e:
            logging.error(f"[SEND_TO_DEVICE] 发送失败: {e}")
            return {"err": "upload.error", "msg": _(u"发送过程出错，请查看日志获取详细信息")}


class BookSendToMail(BaseHandler):
    @js
    def post(self, bid):
        """发送书籍到指定邮箱"""
        book_id = int(bid)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "book.not_found", "msg": _(u"书籍已不存在")}

        if not CONF["ALLOW_GUEST_PUSH"]:
            if not self.current_user:
                return {"err": "user.need_login", "msg": _(u"请先登录")}
            else:
                if not self.current_user.can_push():
                    return {"err": "permission", "msg": _(u"无权限进行推送，请联系管理员检查权限")}
                elif not self.current_user.is_active():
                    return {"err": "permission", "msg": _(u"无权限进行操作，请先激活账号。")}

        # 解析请求参数
        try:
            data = tornado.escape.json_decode(self.request.body)
            mail_to = data.get("email", "").strip()
        except:
            return {"err": "params.invalid", "msg": _(u"没有指定邮箱地址")}

        if not mail_to:
            return {"err": "params.missing", "msg": _(u"邮箱地址不能为空")}

        # 验证邮箱地址格式
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, mail_to):
            return {"err": "email.invalid", "msg": _(u"邮箱地址格式不正确")}

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
            return {"err": "format.not_found", "msg": _(u"书籍没有支持的文件格式（EPUB/AZW3/PDF/MOBI/TXT）")}

        # 检查文件是否存在
        if not os.path.exists(file_path):
            return {"err": "file.missing", "msg": _(u"书籍文件不存在")}

        # 检查文件大小（50MB = 52428800 bytes）
        file_size = os.path.getsize(file_path)
        max_size = 50 * 1024 * 1024  # 50MB
        if file_size > max_size:
            size_mb = file_size / (1024 * 1024)
            return {
                "err": "file.too_large",
                "msg": _(u"附件过大（%.1fMB），邮件附件大小不能超过50MB") % size_mb
            }

        # 记录推送历史和增加统计
        self.user_history("push_history", book)
        self.count_increase(book_id, count_download=1, count_visit=1)
        logging.info(f"[SEND_TO_MAIL] 发送书籍 {book_id} ({file_format}, {file_size} bytes) 到邮箱 {mail_to}")
        MailService().send_book(self.user_id(), self.site_url, book, mail_to, file_format, file_path)

        self.add_msg(
            "success",
            _(u"已开始推送《%(title)s》到%(email)s") % {"title": book["title"], "email": mail_to},
        )

        return {"err": "ok", "msg": _(u"后台正在推送，稍后可以刷新页面，在通知消息中查看结果。")}


class BookSperate(BaseHandler):
    @js
    @auth
    def post(self, bid):
        """将指定格式从书籍中分离并创建为新的独立书籍"""
        from calibre.ebooks.metadata.meta import get_metadata

        book_id = int(bid)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _(u"书籍已不存在")}

        if isinstance(book["collector"], dict):
            cid = book["collector"]["id"]
        else:
            cid = book["collector"].id
        if not self.current_user.can_edit() or not (self.is_admin() or self.is_book_owner(book_id, cid)):
            return {"err": "permission", "msg": _(u"无权操作")}

        try:
            data = tornado.escape.json_decode(self.request.body)
            fmt = data.get("format", "").strip().lower()
        except:
            return {"err": "params.invalid", "msg": _(u"请求参数格式错误")}

        if not fmt:
            return {"err": "params.missing", "msg": _(u"格式参数不能为空")}

        fmt_key = "fmt_%s" % fmt
        if fmt_key not in book:
            return {"err": "format.not_found", "msg": _(u"书籍不包含 %s 格式") % fmt.upper()}

        original_path = book[fmt_key]
        if not os.path.exists(original_path):
            return {"err": "file.missing", "msg": _(u"格式文件不存在: %s") % original_path}

        # 检查书籍是否只有一个格式
        available_formats = book.get("available_formats", "")
        available_formats = [f.strip() for f in available_formats if f.strip()]
        if len(available_formats) <= 1:
            return {"err": "last.format", "msg": _(u"书籍只有一个格式，无法分离")}

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
                return {"err": "book.invalid", "msg": _(u"此书籍文件无法识别, 或者受DRM保护无法处理")}

            # 对于txt和pdf格式，从文件名提取信息
            if fmt in ["txt", "pdf"]:
                mi.title = utils.remove_zlibrary_suffix(filename.replace("." + fmt, ""))
                mi.authors = [_(u"佚名")]

            # 创建新书籍
            fpaths = [upload_path]
            new_book_id = self.calibre_db.import_book(mi, fpaths)

            if new_book_id is None:
                # 清理临时文件
                if os.path.exists(upload_path):
                    os.remove(upload_path)
                return {"err": "book.create.failed", "msg": _(u"创建新书籍失败")}

            # 创建Item记录
            item = Item()
            item.book_id = new_book_id
            item.collector_id = self.user_id()
            self.sqlite_session.add(item)
            self.sqlite_session.commit()

            # 从原书籍中删除该格式
            self.calibre_db_cache.remove_formats({book_id: [fmt.upper()]})

            logging.info(f"[SEPARATE] Successfully separated format {fmt} from book {book_id} to new book {new_book_id}")
            self.add_msg("success", _(u"成功将 %s 格式分离为新书籍") % fmt.upper())
            return {
                "err": "ok",
                "msg": _(u"格式分离成功"),
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
                except:
                    pass
            return {"err": "internal", "msg": _(u"分离格式时发生错误: %s") % str(e)}


class BookSaveMeta(BaseHandler):
    @js
    @auth
    def post(self, bid):
        """将书籍的元数据保存到文件中（仅支持 epub 和 azw3）"""
        book_id = int(bid)
        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "book.not_found", "msg": _(u"书籍不存在")}

        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _(u"无权限")}

        # 检查是否有支持的格式
        supported_formats = []
        for fmt in ["epub", "azw3"]:
            fmt_key = f"fmt_{fmt}"
            if fmt_key in book:
                supported_formats.append((fmt, book[fmt_key]))

        if not supported_formats:
            return {"err": "format.not_supported", "msg": _(u"书籍没有支持的格式（需要 EPUB 或 AZW3）")}

        try:
            from calibre.ebooks.metadata.meta import set_metadata

            # 获取当前书籍的元数据
            mi = self.calibre_db.get_metadata(book_id, index_is_id=True)
            if not mi:
                return {"err": "book.meta.not_found", "msg": _(u"无法获取书籍元数据")}

            success_formats = []
            failed_formats = []

            for fmt, file_path in supported_formats:
                try:
                    if not os.path.exists(file_path):
                        logging.warning(f"[SAVE_META] File not found: {file_path}")
                        failed_formats.append(fmt.upper())
                        continue

                    # 获取封面数据（cover方法直接返回字节数据）
                    cover_data = self.calibre_db.cover(book_id, index_is_id=True)
                    if cover_data:
                        # cover_data 已经是字节数据，设置封面数据，格式为 (扩展名, 字节数据)
                        mi.cover_data = ('jpeg', cover_data)
                        logging.info(f"[SAVE_META] Cover data added for {fmt.upper()}, size: {len(cover_data)} bytes")

                    # 将元数据写入文件（包含封面）
                    with open(file_path, "r+b") as stream:
                        set_metadata(stream, mi, stream_type=fmt)

                    logging.info(f"[SAVE_META] Successfully saved metadata to {fmt.upper()} file for book {book_id}")
                    success_formats.append(fmt.upper())
                except Exception as e:
                    logging.error(f"[SAVE_META] Failed to save metadata to {fmt.upper()} file for book {book_id}: {e}")
                    failed_formats.append(fmt.upper())

            if success_formats:
                msg = _(u"成功将元数据同步到文件：%s") % ", ".join(success_formats)
                if failed_formats:
                    msg += _(u"；失败：%s") % ", ".join(failed_formats)
                return {"err": "ok", "msg": msg}
            else:
                return {"err": "save.failed", "msg": _(u"同步元数据失败：%s") % ", ".join(failed_formats)}

        except Exception as e:
            logging.error(f"[SAVE_META] Error saving metadata for book {book_id}: {e}")
            traceback.print_exc()
            return {"err": "internal", "msg": _(u"同步元数据时发生错误: %s") % str(e)}


class ClearRareTags(ListHandler):
    @js
    @auth
    def post(self):
        """清理稀少标签, 对少于3本书的标签所对应的书籍重新更新标签"""
        if not self.is_admin():
            return {"err": "user.not_admin", "msg": _(u"无权限")}

        ids = list(self.calibre_db_cache.all_book_ids())
        if not ids or len(ids) < 100:
            return {"err": "ok", "msg": _(u"书籍数量较少，无需清理标签")}

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
                return {"err": "ok", "msg": _(u"没有找到稀少标签对应的书籍")}

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
                return {"err": "ok", "msg": _(u"没有找到需要更新的书籍")}

            # 调用自动填充服务，只更新标签
            service = AutoFillService()
            service.auto_fill_all(book_ids, only_tags=True)

            return {
                "err": "ok",
                "msg": _(u"开始更新 %d 本书的标签，涉及 %d 个稀少标签") % (len(book_ids), rare_tag_count),
                "book_count": len(book_ids),
                "tag_count": rare_tag_count
            }

        except Exception as e:
            logging.error(f"Clear rare tags error: {e}")
            return {"err": "error", "msg": _(u"处理失败：%s") % str(e)}


class BookExchangeType(BaseHandler):
    @js
    @auth
    def post(self):
        """批量转换书籍类型, 电子书与实体书互转"""
        if not self.is_admin():
            return {"err": "user.no_permission", "msg": _(u"无权限")}

        data = tornado.escape.json_decode(self.request.body)
        idlist = data.get("idlist", [])

        if not idlist:
            return {"err": "params.invalid", "msg": _(u"请提供书籍ID列表")}

        success_count = 0
        skip_count = 0
        results = []

        for book_id in idlist:
            try:
                book = self.get_book(book_id, raise_exception=False)
                if not book:
                    results.append({"book_id": book_id, "status": "not_found", "msg": _(u"书籍已不存在")})
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
                        results.append({"book_id": book_id, "status": "skip", "msg": _(u"无ISBN，跳过")})
                        skip_count += 1
                        continue

                    # 检查是否有任何电子书格式
                    has_formats = False
                    for fmt in ["epub", "mobi", "azw", "azw3", "txt", "pdf"]:
                        if book.get("fmt_%s" % fmt):
                            has_formats = True
                            break

                    if has_formats:
                        results.append({"book_id": book_id, "status": "skip", "msg": _(u"已有电子书格式，跳过")})
                        skip_count += 1
                        continue

                    # 转换为实体书
                    item.book_type = BOOK_TYPE_PHYSICAL
                    item.book_count = 1
                    results.append({"book_id": book_id, "status": "success", "msg": _(u"已转为实体书")})
                    success_count += 1

                # 如果是实体书，转为电子书
                elif current_type == BOOK_TYPE_PHYSICAL:
                    item.book_type = BOOK_TYPE_EBOOK
                    item.book_count = 1
                    results.append({"book_id": book_id, "status": "success", "msg": _(u"已转为电子书")})
                    success_count += 1

                else:
                    results.append({"book_id": book_id, "status": "skip", "msg": _(u"未知类型")})
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
            return {"err": "db.error", "msg": _(u"数据库错误：%s") % str(e)}

        return {
            "err": "ok",
            "msg": _(u"处理完成：成功 %d 本，跳过 %d 本") % (success_count, skip_count),
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
        (r"/api/read/txt", TxtRead),
        (r"/api/book/txt/init", BookTxtInit),
        (r"/api/book/([0-9]+)/convert", BookConverter),
        (r"/api/book/([0-9]+)/topdf", BookToPDF),
        (r"/api/book/([0-9]+)/setsole", BookSetSole),
        (r"/api/book/([0-9]+)/cover", BookCover),
        (r"/api/book/([0-9]+)/favorite", BookFavorite),
        (r"/api/book/([0-9]+)/wants", BookWantToRead),
        (r"/api/book/([0-9]+)/readstate", BookReadingState),
        (r"/api/favorites", BookFavorite),
        (r"/api/wants", BookWantToRead),
        (r"/api/reading", BookReading),
        (r"/api/read-done", BookReadDone),
        (r"/api/reading/stats", BookReadingStats),
        (r"/api/library/stats", LibraryStats),
        (r"/api/book/([0-9]+)/tags", BookTags),
        (r"/api/book/([0-9]+)/aifill", BookAIFill),
        (r"/api/book/update_tags", BookUpdateTags),
        (r"/api/book/category", BookCategoryBatch),
        (r"/api/book/([0-9]+)/category", BookCategory),
        (r"/api/categories", BookCategories),
        (r"/api/book/([0-9]+)/suggestion", BookSuggestion),
        (r"/api/book/([0-9]+)/separate", BookSperate),
        (r"/api/book/([0-9]+)/savemeta", BookSaveMeta),
        (r"/api/book/exchange_type", BookExchangeType),
        (r"/api/clear_rare_tags", ClearRareTags),
    ]
