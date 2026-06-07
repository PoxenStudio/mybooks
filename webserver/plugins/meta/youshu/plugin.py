#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging
import re

from webserver.i18n import _
from webserver.constants import META_SOURCE_YOUSHU
from webserver.plugins.meta.base import MetaSourcePlugin

from .api import YoushuApi, KEY


class YoushuMetaPlugin(MetaSourcePlugin):
    """优书网信息源插件"""

    SOURCE_KEYS = (META_SOURCE_YOUSHU,)
    PROVIDER_KEY = KEY

    def search(self, title=None, isbn=None, publisher=None):
        if not title:
            return []
        api = YoushuApi(copy_image=True)
        try:
            book = api.get_book(title)
            return [book] if book else []
        except Exception as e:
            logging.error("优书网查询失败: %s" % str(e))
            return []

    def search_best(self, mi):
        title = mi.title
        logging.info("尝试使用 youshu 插件查询 %s", title)
        api = YoushuApi(copy_image=True)
        try:
            return api.get_book(title)
        except Exception:
            logging.error(_("youshu 接口查询 %s 失败"), title)
            return None

    def get_metadata_by_provider(self, provider_value, mi=None):
        title = re.sub(u"[(（].*", "", mi.title)
        api = YoushuApi(copy_image=True)
        try:
            return api.get_book(title)
        except Exception:
            raise RuntimeError({"err": "httprequest.youshu.failed", "msg": _("优书网查询失败")})

    def get_cover(self, cover_url):
        return YoushuApi.get_cover(cover_url)
