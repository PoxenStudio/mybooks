#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
# @author: PoxenStudio, 2026-08

import logging

from webserver import loader
from webserver.constants import META_SOURCE_UJXSW
from webserver.plugins.meta.base import MetaSourcePlugin

from . import api
from .api import KEY

CONF = loader.get_settings()


def _max_count():
    return max(1, min(int(CONF.get("ujxsw_max_count", 2)), 5))


class UjxswMetaPlugin(MetaSourcePlugin):
    """悠久小说网(wap.ujxsw.org)信息源插件 —— 通过手机站搜索接口查询网络小说信息。"""

    SOURCE_KEYS: tuple = (META_SOURCE_UJXSW, )
    PROVIDER_KEY = KEY

    def search(self, title=None, isbn=None, publisher=None):
        if not title:
            return []
        items = api.search(title, max_count=_max_count())
        return api.build_metadata_batch(items, isbn=isbn, copy_image=False)

    def search_best(self, mi):
        title = mi.title
        if not title:
            return None
        items = api.search(title, max_count=_max_count())
        if not items:
            return None
        # 优先取标题完全匹配的，否则取首个结果
        best = next((i for i in items if i.get("title") == title), items[0])
        try:
            return api.build_metadata(best, isbn=getattr(mi, "isbn", None), copy_image=True)
        except Exception:
            logging.error("[Ujxsw]查询 %s 失败", title)
            return None

    def get_metadata_by_provider(self, provider_value, mi=None):
        cover_url = getattr(mi, "cover_url", None)
        if mi and cover_url:
            cover_data = api.get_cover(cover_url)
            if cover_data:
                mi.cover_data = cover_data
        return mi

    def get_cover(self, cover_url):
        return api.get_cover(cover_url)
