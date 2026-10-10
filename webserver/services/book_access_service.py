#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
匿名（游客）访问书籍内容的统一判定入口，设计见 document/Share_Visits_GuestBooklist_Design.md。

book_id 为 None 表示不针对具体书籍的通用检查（如阅读器的词典、朗读接口）。
"""

from typing import Optional

from webserver import loader

CONF = loader.get_settings()


class BookAccessService:

    @staticmethod
    def guest_read_allowed(handler, book_id: Optional[int] = None) -> bool:
        return bool(CONF.get("ALLOW_GUEST_READ", False))

    @staticmethod
    def guest_download_allowed(handler, book_id: Optional[int] = None) -> bool:
        return bool(CONF.get("ALLOW_GUEST_DOWNLOAD", False))
