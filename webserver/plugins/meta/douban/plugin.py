#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging

from webserver import loader
from webserver.i18n import _
from webserver.constants import META_SOURCE_DOUBAN
from webserver.plugins.meta.base import MetaSourcePlugin

from .api import DoubanBookApi, KEY

CONF = loader.get_settings()


class DoubanMetaPlugin(MetaSourcePlugin):
    """豆瓣信息源插件"""

    SOURCE_KEYS = (META_SOURCE_DOUBAN,)
    PROVIDER_KEY = KEY

    def _api(self, copy_image=True):
        return DoubanBookApi(
            CONF["douban_apikey"],
            CONF["douban_baseurl"],
            copy_image=copy_image,
            manual_select=False,
            maxCount=CONF["douban_max_count"],
        )

    def search(self, title=None, isbn=None, publisher=None):
        if not title:
            return []

        api = self._api(copy_image=False)
        books = []
        try:
            books = api.search_books(title) or []
        except Exception as e:
            logging.error(_(u"豆瓣接口查询 %s 失败: %s" % (title, str(e))))

        # 如果有 ISBN 但没搜索到合适的书，则精准查询一次 ISBN
        if isbn and not has_proper_book(books, title, isbn, publisher):
            try:
                book = api.get_book_by_isbn(isbn)
                if book:
                    books = list(books)
                    books.insert(0, book)  # 总是把最佳书籍放在第一位
            except Exception as e:
                logging.error(_(u"豆瓣ISBN查询失败: %s" % str(e)))

        return [api._metadata(b) for b in books]

    def search_best(self, mi):
        title = mi.title
        try:
            api = self._api(copy_image=True)

            # 优先按 ISBN 精确查询
            book = api.get_book_by_isbn(mi.isbn)
            if book:
                book_detail_mi = api.get_book_detail(book)
                return self._fill_missing_author(book_detail_mi, mi)

            # 按标题搜索，匹配标题+出版社者优先，否则取首个结果
            books = api.search_books(title)
            if books:
                book_detail_mi = None
                for b in books:
                    if mi.title == b.get("title") and mi.publisher == b.get("publisher"):
                        book_detail_mi = api.get_book_detail(b)
                        break
                if not book_detail_mi:
                    book_detail_mi = api.get_book_detail(books[0])
                return self._fill_missing_author(book_detail_mi, mi)
        except Exception:
            logging.error(_("douban 接口查询 %s 失败"), title)
        return None

    @staticmethod
    def _fill_missing_author(book_detail_mi, mi):
        if book_detail_mi and (not book_detail_mi.authors or book_detail_mi.authors[0] in ("佚名", "")):
            book_detail_mi.authors = mi.authors
            book_detail_mi.author_sort = mi.author_sort
        return book_detail_mi

    def get_metadata_by_provider(self, provider_value, mi=None):
        mi.douban_id = provider_value
        api = self._api(copy_image=True)
        try:
            return api.get_book(mi)
        except Exception:
            raise RuntimeError({"err": "httprequest.douban.failed", "msg": _("豆瓣接口查询失败")})

    def get_cover(self, cover_url):
        return DoubanBookApi.get_cover(cover_url)

    def search_physical_by_isbn(self, isbn):
        """按 ISBN 精确查询实体书信息（用于 BookSearch.find_physical_book_by_isbn 兜底链）"""
        from .api import SimpleMetaData

        api = self._api(copy_image=True)
        return api.get_book(SimpleMetaData(isbn=isbn))


def has_proper_book(books, title, isbn, publisher=None):
    """检查搜索结果中是否包含合适的图书"""
    from webserver.plugins.meta import baike

    if not books or not isbn or isbn == baike.BAIKE_ISBN:
        return False

    for b in books:
        if isbn == b.get("isbn13", "xxx"):
            return True
        if publisher and title == b.get("title") and publisher == b.get("publisher"):
            return True
    return False
