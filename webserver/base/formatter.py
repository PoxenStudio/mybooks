#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import datetime
from webserver.i18n import _
from webserver.constants import CALIBRE_COLUMN_BOOK_TYPE, CALIBRE_COLUMN_PHY_COUNT
from webserver.constants import CALIBRE_COLUMN_EXT_LINK, CALIBRE_COLUMN_CATEGORY
from webserver.constants import BOOK_TYPE_EBOOK, CALIBRE_COLUMN_DYNAMIC_COVER
from webserver.constants import CALIBRE_COLUMN_LOCATION, BOOK_TYPE_PHYSICAL


class SimpleBookFormatter:
    """格式化calibre book的字段"""

    def __init__(self, calibre_book_item, cdn_url):
        self.cdn_url = cdn_url
        self.book = calibre_book_item

    def get_collector(self):
        collector = self.book.get("collector", None)
        if isinstance(collector, dict):
            collector = collector.get("username", None)
        elif collector:
            collector = collector.username
        return collector

    def val(self, k, default_value=_("Unknown")):
        v = self.book.get(k, None)
        if not v:
            v = default_value
        if isinstance(v, datetime.datetime):
            return f'{v.year:04}-{v.month:02}-{v.day:02}'
        return v

    def get_files(self):
        files = []
        for fmt in self.book.get("available_formats", []):
            item = {
                "format": fmt,
                "size": 0
            }
            files.append(item)
        return files

    def format(self, include_comments=True, strip_comments=False):
        b = self.book
        b["ts"] = int(b["timestamp"].timestamp())
        category = self.val(CALIBRE_COLUMN_CATEGORY, '').strip()
        book_type = self.val(CALIBRE_COLUMN_BOOK_TYPE, self.book.get("book_type", BOOK_TYPE_EBOOK))
        book_count = self.val(CALIBRE_COLUMN_PHY_COUNT, self.book.get("book_count", 1))
        ext_link = self.val(CALIBRE_COLUMN_EXT_LINK, '').strip()
        location = self.val(CALIBRE_COLUMN_LOCATION, '').strip() if book_type == BOOK_TYPE_PHYSICAL else ""
        dynamic_cover = self.book.get(CALIBRE_COLUMN_DYNAMIC_COVER, 0)
        comments = self.val("comments", _(u"暂无简介")) if include_comments else ""
        if strip_comments and comments:
            comments = comments[:120] + "..." if len(comments) > 120 else comments
        return {
            "id": b["id"],
            "title": b["title"],
            "rating": b["rating"],
            "timestamp": self.val("timestamp"),
            "pubdate": self.val("pubdate"),
            "author": ", ".join(b["authors"]),
            "authors": b["authors"],
            "author_sort": self.val("author_sort"),
            "tag": " / ".join(b["tags"]),
            "tags": b["tags"],
            "publisher": self.val("publisher"),
            "comments": comments,
            "series": self.val("series", None),
            "series_index": self.val("series_index", None),
            "languages": self.val("languages", None),
            "isbn": self.val("isbn", None),
            "img": self.cdn_url + "/get/cover/%(id)s.jpg?t=%(ts)s" % b,
            "thumb": self.cdn_url + "/get/thumb_240_320/%(id)s.jpg?t=%(ts)s&size=240x320" % b,
            # 额外填充的字段
            "collector": self.get_collector(),
            "count_visit": self.val("count_visit", 0),
            "count_download": self.val("count_download", 0),
            "sole": self.val("sole", False),
            "has_audio": self.val("has_audio", 0),
            "book_type": self.book.get("book_type", book_type),
            "book_count": self.book.get("book_count", book_count),
            "state": self.book.get("state", {}),
            'category': category,
            'ext_link': ext_link,
            'files': self.get_files(),
            'dynamic_cover': dynamic_cover,
            'location': location,
        }


class MCPBookFormatter:
    """格式化calibre book的字段"""

    def __init__(self, calibre_book_item, cdn_url):
        self.cdn_url = cdn_url
        self.book = calibre_book_item

    def val(self, k, default_value=_("Unknown")):
        v = self.book.get(k, None)
        if not v:
            v = default_value
        if isinstance(v, datetime.datetime):
            return f'{v.year:04}-{v.month:02}-{v.day:02}'
        return v

    def format(self, include_comments=True):
        b = self.book
        b["ts"] = b["timestamp"].strftime("%s")
        return {
            "id": b["id"],
            "title": b["title"],
            "rating": b["rating"],
            "pubdate": self.val("pubdate"),
            "author": ", ".join(b["authors"]),
            "tag": " / ".join(b["tags"]),
            "publisher": self.val("publisher"),
            "comments": self.val("comments", _(u"暂无简介")) if include_comments else "",
            "languages": self.val("languages", None),
            "isbn": self.val("isbn", None),
            'category': self.val('#category', ''),
        }


class BookFormatter:
    def __init__(self, tornado_handler, calibre_book_item):
        self.db = tornado_handler.calibre_db
        self.book = calibre_book_item
        self.cdn_url = tornado_handler.cdn_url
        self.api_url = tornado_handler.api_url
        self.handler = tornado_handler

    def get_files(self):
        files = []
        book_id = self.book["id"]
        for fmt in self.book.get("available_formats", []):
            try:
                filesize = self.db.sizeof_format(book_id, fmt, index_is_id=True)
            except:
                continue
            item = {
                "format": fmt,
                "size": filesize,
                "href": self.cdn_url + "/api/book/%s.%s" % (book_id, fmt),
            }
            files.append(item)
        return files

    def get_permissions(self):
        h = self.handler
        return {
            # 图书权限数据
            "is_public": True,
            "is_owner": h.is_admin() or h.is_book_owner(self.book["id"], h.user_id()),
        }

    def format(self, with_files=False, with_perms=False, include_comments=True, strip_comments=False):
        f = SimpleBookFormatter(self.book, self.cdn_url)
        data = f.format(include_comments=include_comments, strip_comments=strip_comments)
        data.update(
            {
                "author_url": self.api_url + "/author/" + f.val("author_sort"),
                "publisher_url": self.api_url + "/publisher/" + f.val("publisher"),
            }
        )
        if with_files:
            data["files"] = self.get_files()
        if with_perms:
            data.update(self.get_permissions())
        return data


class ReadingStateFormatter:
    """处理阅读状态数据格式化的工具类"""

    @staticmethod
    def format_reading_state(reading_state):
        """
        将ReadingState对象转换为字典格式

        Args:
            reading_state: ReadingState对象

        Returns:
            dict: 格式化的状态数据
        """
        if not reading_state:
            return {
                "favorite": 0,
                "favorite_date": None,
                "wants": 0,
                "wants_date": None,
                "read_state": 0,
                "read_date": None,
                "online_read": 0,
                "download": 0
            }

        return {
            "favorite": reading_state.favorite,
            "favorite_date": reading_state.favorite_date.isoformat() if reading_state.favorite_date else None,
            "wants": reading_state.wants,
            "wants_date": reading_state.wants_date.isoformat() if reading_state.wants_date else None,
            "read_state": reading_state.read_state,
            "read_date": reading_state.read_date.isoformat() if reading_state.read_date else None,
            "online_read": reading_state.online_read or 0,
            "download": reading_state.download or 0
        }

    @staticmethod
    def format_reading_state_with_api_format(reading_state):
        """
        将ReadingState对象转换为API返回格式的字典
        用于单个书籍状态查询的场景

        Args:
            reading_state: ReadingState对象

        Returns:
            dict: 格式化的状态数据（包含err字段）
        """
        if reading_state:
            return {
                "err": "ok",
                "read_state": reading_state.get_read_state(),
                "favorite": reading_state.is_favorite(),
                "wants": reading_state.is_wants(),
                "online_read": reading_state.online_read or 0,
                "download": reading_state.download or 0,
                "read_date": reading_state.read_date.isoformat() if reading_state.read_date else None,
                "favorite_date": reading_state.favorite_date.isoformat() if reading_state.favorite_date else None,
                "wants_date": reading_state.wants_date.isoformat() if reading_state.wants_date else None
            }
        else:
            return {
                "err": "ok",
                "read_state": 0,
                "favorite": False,
                "wants": False,
                "online_read": 0,
                "download": 0,
                "read_date": None,
                "favorite_date": None,
                "wants_date": None
            }
