#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging
import traceback

from webserver.i18n import _
from webserver.constants import META_SOURCE_GOOGLE, META_SOURCE_AMAZON
from webserver.plugins.meta.base import MetaSourcePlugin

from .api import CalibreMetadataApi, KEY


class CalibreMetaPlugin(MetaSourcePlugin):
    """基于 Calibre 内置 Google Books / Amazon.com 插件的信息源

    Google 与 Amazon 共享同一套 Calibre identify 调用机制，且自动刮削时两者之间存在
    "未选 Amazon 时才用 Google 查 ISBN，否则统一走 Amazon 标题搜索" 的优先级耦合，
    因此沿用改造前的做法，把两个来源放在同一个插件里统一处理（也减少了并行 worker 数量）。
    """

    SOURCE_KEYS = (META_SOURCE_GOOGLE, META_SOURCE_AMAZON)
    PROVIDER_KEY = KEY

    def _selected_sources(self, sources=None):
        if sources is None:
            from webserver import loader
            from webserver.constants import META_SELECTED_SOURCES
            sources = loader.get_settings().get(META_SELECTED_SOURCES, [])
        return [s for s in sources if s in self.SOURCE_KEYS]

    def search(self, title=None, isbn=None, publisher=None):
        sources = self._selected_sources()
        books = []
        try:
            if isbn:
                calibre_books = CalibreMetadataApi.get_book_by_isbn(isbn, sources)
                if calibre_books:
                    books.extend(calibre_books)
            if title:
                calibre_books = CalibreMetadataApi.get_book_by_title(title=title, sources=sources, timeout=10)
                if calibre_books:
                    books.extend(calibre_books)
        except Exception as e:
            logging.error("Calibre Metadata API查询失败: %s" % str(e))
        return books

    def search_best(self, mi):
        title = mi.title
        sources = self._selected_sources()
        try:
            if META_SOURCE_AMAZON not in sources:
                # 只有在没有 amazon 时才使用 google 查询
                try:
                    results = CalibreMetadataApi.get_book_by_isbn(mi.isbn, sources=sources)
                    if results:
                        return results[0]
                except Exception:
                    logging.error(_("calibre 插件 ISBN 查询 %s 失败"), title)

            results = CalibreMetadataApi.get_book_by_title(title, authors=mi.authors, sources=sources)
            if results:
                result = results[0]
                result.cover_data = CalibreMetadataApi.get_cover(result.cover_url) if result.cover_url else None
                return result
        except Exception as e:
            logging.error(_("calibre 插件书名查询 %s 失败: %s"), title, e)
            logging.error(traceback.format_exc())
        return None

    def get_cover(self, cover_url):
        return CalibreMetadataApi.get_cover(cover_url)
