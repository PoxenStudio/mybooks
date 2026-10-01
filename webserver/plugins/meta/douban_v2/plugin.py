#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
# @author: PoxenStudio, 2026-06

import logging
import traceback

from webserver import loader
from webserver.i18n import _
from webserver.constants import META_SOURCE_DOUBAN_V2
from webserver.plugins.meta.base import MetaSourcePlugin

from . import api
from .api import KEY

CONF = loader.get_settings()


def _max_count():
    return max(1, min(int(CONF.get("douban_max_count", 2)), 5))


class DoubanV2MetaPlugin(MetaSourcePlugin):
    """豆瓣(V2)信息源插件 —— 仅使用 subject_search 接口，不发二次详情请求。"""

    SOURCE_KEYS: tuple = (META_SOURCE_DOUBAN_V2, )
    PROVIDER_KEY = KEY

    def search(self, title=None, isbn=None, publisher=None):
        query = isbn or title
        if not query:
            return []
        items, search_url = api.search(query, max_count=_max_count())
        return api.build_metadata_batch(items, search_url, isbn=isbn, copy_image=False, get_detail=True)

    def search_best(self, mi):
        query = mi.isbn or mi.title
        if not query:
            return None
        items, search_url = api.search(query, max_count=_max_count(), skip_error=True)
        if not items:
            return None
        if items[0].get("title", "") == "BLOCKED":
            return None
        # 优先取标题完全匹配的，否则取首个结果
        best = next((i for i in items if i.get("title") == mi.title), items[0])
        try:
            return api.build_metadata(best, search_url, isbn=getattr(mi, "isbn", None), copy_image=True, get_detail=True)
        except Exception:
            logging.error(_("[DoubanV2]查询 %s 失败"), query)
            return None

    def get_metadata_by_provider(self, provider_value, item=None):
        # 按标题重新搜索，找到 provider_value 匹配的条目后下载封面
        if not item:
            return None
        try:
            return api.build_metadata(
                item, "https://book.douban.com",
                isbn=None,
                copy_image=True,
                get_detail=True
            )
        except Exception as e:
            logging.error("[DoubanV2]获取详情失败，provider_value=%s", provider_value)
            logging.error(f"[DoubanV2] Exception {e}")
            logging.error(f"[DoubanV2] {traceback.format_exc()}")

        return None

    def get_cover(self, cover_url):
        return api.get_cover(cover_url)

    def search_physical_by_isbn(self, isbn):
        """按 ISBN 精确查询实体书信息（用于 BookSearch.find_physical_book_by_isbn 兜底链）"""
        if not isbn:
            return None
        items, search_url = api.search(isbn, max_count=1)
        if not items:
            return None
        try:
            return api.build_metadata(items[0], search_url, isbn=isbn, copy_image=True)
        except Exception:
            logging.error("[DoubanV2] ISBN查询 %s 失败", isbn)
            return None
