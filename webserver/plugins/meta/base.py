#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

"""图书元数据信息源插件的统一基类。

每个信息源（豆瓣、百度百科、优书网、Calibre Google/Amazon ...）都应实现一个
MetaSourcePlugin 子类，把"是否参与本次检索"（由 META_SELECTED_SOURCES 决定）
封装到插件内部，并对外暴露统一的检索接口，方便 BookSearch 统一调度、并行执行。
"""

from abc import ABC

from webserver import loader
from webserver.constants import META_SELECTED_SOURCES

CONF = loader.get_settings()


class MetaSourcePlugin(ABC):
    """图书元数据信息源插件基类"""

    # 本插件关联的 META_SELECTED_SOURCES 取值（保持声明顺序，用于汇总全部可选信息源）
    # （大多数插件只对应一个值，Calibre 插件同时覆盖 google 与 amazon）
    SOURCE_KEYS = ()

    def is_enabled(self, sources=None):
        """该插件是否应参与本次检索（由 META_SELECTED_SOURCES 配置决定）"""
        if sources is None:
            sources = CONF.get(META_SELECTED_SOURCES, [])
        return bool(set(self.SOURCE_KEYS) & set(sources))

    def search(self, title=None, isbn=None, publisher=None):
        """多结果聚合搜索，用于候选列表展示。返回 list[Metadata]，找不到时返回 []"""
        return []

    def search_best(self, mi):
        """按本插件规则返回单一最佳匹配的 Metadata，找不到时返回 None。

        默认退化为 search() 的首个结果；子类可覆盖以实现更精细的匹配规则
        （如优先按 ISBN 精确查询，找不到再按标题搜索）。
        """
        books = self.search(title=mi.title, isbn=mi.isbn, publisher=mi.publisher)
        return books[0] if books else None

    def get_metadata_by_provider(self, provider_value, mi=None):
        """依据本插件的 provider_value 拉取完整详情，找不到/不支持时返回 None"""
        return None

    def get_cover(self, cover_url):
        """按封面 URL 拉取封面数据，找不到/不支持时返回 None"""
        return None

    @property
    def name(self):
        return type(self).__name__
