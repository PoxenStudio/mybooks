#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
匿名（游客）访问书籍内容的统一判定入口，设计见 document/Share_Visits_GuestBooklist_Design.md。

book_id 为 None 表示不针对具体书籍的通用检查（如阅读器的词典、朗读接口）。
"""

from typing import Optional

from webserver import loader
from webserver.models import BookList, BookListBook
from webserver.services.book_share_service import BookShareService

CONF = loader.get_settings()


class BookAccessService:

    @staticmethod
    def guest_read_allowed(handler, book_id: Optional[int] = None) -> bool:
        return BookAccessService.guest_read_source(handler, book_id) is not None

    @staticmethod
    def guest_read_source(handler, book_id: Optional[int] = None) -> Optional[str]:
        if CONF.get("ALLOW_GUEST_READ", False):
            return "global"
        if BookAccessService._share_allows(handler, book_id, "allow_read"):
            return "share"
        if BookAccessService._booklist_allows_read(book_id):
            return "booklist"
        return None

    @staticmethod
    def _share_allows(handler, book_id: Optional[int], permission: str) -> bool:
        if book_id is None:
            return BookShareService.any_grant(handler)
        share = BookShareService.granted_share(handler, book_id)
        return share is not None and bool(getattr(share, permission))

    @staticmethod
    def share_read_granted(handler, book_id) -> bool:
        return book_id is not None and BookAccessService._share_allows(handler, book_id, "allow_read")

    @staticmethod
    def share_download_granted(handler, book_id) -> bool:
        return book_id is not None and BookAccessService._share_allows(handler, book_id, "allow_download")

    @staticmethod
    def _booklist_allows_read(book_id: Optional[int]) -> bool:
        db = BookList._session()
        ids = [row[0] for row in db.query(BookList.id).filter(BookList.is_public.is_(True), BookList.guest_read.is_(True)).all()]
        if not ids or book_id is None:
            return bool(ids)
        try:
            book_id = int(book_id)
        except (TypeError, ValueError):
            return False
        return db.query(BookListBook.id).filter(BookListBook.booklist_id.in_(ids), BookListBook.book_id == book_id).first() is not None

    @staticmethod
    def guest_download_allowed(handler, book_id: Optional[int] = None) -> bool:
        if CONF.get("ALLOW_GUEST_DOWNLOAD", False):
            return True
        return BookAccessService._share_allows(handler, book_id, "allow_download")
