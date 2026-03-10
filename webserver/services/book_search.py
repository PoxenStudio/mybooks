#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging
import re
from gettext import gettext as _

from webserver import loader
from webserver.plugins.meta import baike, douban
from webserver.constants import META_SELECTED_SOURCES, META_SOURCE_DOUBAN, META_SOURCE_BAIDU
from webserver.constants import META_SOURCE_GOOGLE, META_SOURCE_AMAZON

CONF = loader.get_settings()


class BookSearch:
    """图书搜索工具类，用于从多个来源搜索图书元数据"""

    @staticmethod
    def has_proper_book(books, title, isbn, publisher=None):
        """
        检查搜索结果中是否包含合适的图书

        Args:
            books: 搜索结果列表
            title: 图书标题
            isbn: ISBN号
            publisher: 出版社（可选）

        Returns:
            bool: 如果找到合适的图书返回True，否则返回False
        """
        if not books or not isbn or isbn == baike.BAIKE_ISBN:
            return False

        for b in books:
            if isbn == b.get("isbn13", "xxx"):
                return True
            if publisher and title == b.get("title") and publisher == b.get("publisher"):
                return True
        return False

    @staticmethod
    def plugin_search_books(title=None, isbn=None, publisher=None):
        """
        从多个插件源搜索图书信息

        Args:
            title: 图书标题（可选）
            isbn: ISBN号（可选）
            publisher: 出版社（可选）
            * title & isbn 至少有一个
        Returns:
            list: 搜索到的图书元数据列表
        """
        sources = CONF.get(META_SELECTED_SOURCES, [])
        if not sources:
            return []

        if not title and not isbn:
            return []

        logging.info(_("开始搜索图书，title: %s, isbn: %s, publisher: %s, sources: %s") % (title, isbn, publisher, sources))

        # 清理标题，移除括号及其内容（含括号本身）
        if title:
            clean_title = re.sub(r'\([^)]*\)|\[[^\]]*\]|（[^）]*）|【[^】]*】', '', title).strip()
        else:
            clean_title = ""

        books = []

        # 豆瓣搜索
        if META_SOURCE_DOUBAN in sources:
            douban_api = douban.DoubanBookApi(
                CONF["douban_apikey"],
                CONF["douban_baseurl"],
                copy_image=False,
                manual_select=False,
                maxCount=CONF["douban_max_count"],
            )
            if clean_title:
                try:
                    books = douban_api.search_books(clean_title) or []
                except Exception as e:
                    logging.error(_(u"豆瓣接口查询 %s 失败: %s" % (clean_title, str(e))))

            # 如果有ISBN号但没搜索到合适的书，则精准查询一次ISBN
            if isbn and not BookSearch.has_proper_book(books, clean_title, isbn, publisher):
                try:
                    book = douban_api.get_book_by_isbn(isbn)
                    if book:
                        books = list(books)
                        books.insert(0, book)  # 总是把最佳书籍放在第一位
                except Exception as e:
                    logging.error(_(u"豆瓣ISBN查询失败: %s" % str(e)))

            # 转换为元数据格式
            books = [douban_api._metadata(b) for b in books]

        # 百度百科搜索
        if META_SOURCE_BAIDU in sources:
            baike_api = baike.BaiduBaikeApi(copy_image=False)
            try:
                book = baike_api.get_book(clean_title)
                if book:
                    books.append(book)
            except Exception as e:
                logging.error(_(u"百度百科查询失败: %s" % str(e)))

        # Google & Amazon 搜索（使用 Calibre Metadata API）
        if any(s in sources for s in [META_SOURCE_GOOGLE, META_SOURCE_AMAZON]):
            logging.info(_("使用 Calibre Metadata API 搜索图书，title: %s, isbn: %s, sources: %s") % (clean_title, isbn, sources))
            try:
                from webserver.plugins.meta.calibre import CalibreMetadataApi
                calibre_books = CalibreMetadataApi.get_book_by_isbn(isbn, sources) if isbn else None
                if calibre_books:
                    books.extend(calibre_books)
                calibre_books = CalibreMetadataApi.get_book_by_title(title=clean_title, sources=sources, timeout=10) if clean_title else None
                if calibre_books:
                    books.extend(calibre_books)
            except Exception as e:
                logging.error(_(u"Calibre Metadata API查询失败: %s" % str(e)))
        else:
            logging.info(_("未启用 Calibre Metadata API 搜索，跳过 Google 和 Amazon 搜索"))
        logging.info(_("搜索完成，找到 %d 本书") % len(books))
        return books
