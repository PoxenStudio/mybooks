#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging

from webserver.i18n import _
from webserver.constants import META_SOURCE_BAIDU
from webserver.plugins.meta.base import MetaSourcePlugin

from .api import BaiduBaikeApi, KEY


class BaikeMetaPlugin(MetaSourcePlugin):
    """百度百科信息源插件"""

    SOURCE_KEYS = (META_SOURCE_BAIDU,)
    PROVIDER_KEY = KEY

    def search(self, title=None, isbn=None, publisher=None):
        if not title:
            return []
        api = BaiduBaikeApi(copy_image=False)
        try:
            book = api.get_book(title)
            return [book] if book else []
        except Exception as e:
            logging.error(_(u"百度百科查询失败: %s" % str(e)))
            return []

    def search_best(self, mi):
        api = BaiduBaikeApi(copy_image=True)
        try:
            return api.get_book(mi.title)
        except Exception:
            logging.error(_("baidu 接口查询 %s 失败"), mi.title)
            return None

    def get_cover(self, cover_url):
        return BaiduBaikeApi.get_cover(cover_url)
