#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

from webserver.constants import META_SOURCE_XHSD
from webserver.plugins.meta.base import MetaSourcePlugin

from .api import XhsdBookApi, KEY


class XhsdMetaPlugin(MetaSourcePlugin):
    """新华书店信息源插件

    当前仅作为 ISBN 实体书添加的兜底数据源使用（见 BookSearch.find_physical_book_by_isbn），
    不参与聚合搜索 / 自动刮削，也不受 META_SELECTED_SOURCES 限制——这与改造前的行为保持一致。
    """

    SOURCE_KEYS = (META_SOURCE_XHSD,)
    PROVIDER_KEY = KEY

    def search_by_isbn(self, isbn):
        if not isbn:
            return None
        return XhsdBookApi().get_book_by_isbn(isbn)
