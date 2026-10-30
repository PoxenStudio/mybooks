#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
匿名（游客）访问书籍内容的统一判定入口，设计见 document/Share_Visits_GuestBooklist_Design.md。

book_id 为 None 表示不针对具体书籍的通用检查（如阅读器的词典、朗读接口）。
"""

from typing import Optional

from webserver import loader
from webserver.base import modules as feature_modules
from webserver.models import BookList, BookListBook
from webserver.services.book_share_service import BookShareService

CONF = loader.get_settings()


class BookAccessService:

    @staticmethod
    def guest_read_allowed(handler, book_id: Optional[int] = None) -> bool:
        return BookAccessService.guest_read_source(handler, book_id) is not None

    @staticmethod
    def guest_read_source(handler, book_id: Optional[int] = None) -> Optional[str]:
        # 分享链接优先于 REQUIRE_LOGIN：持有效分享授权即可读，不受"必须登录"影响。
        if BookAccessService._share_allows(handler, book_id, "allow_read"):
            return "share"
        # REQUIRE_LOGIN（必须登录才能访问）是"整站关闸"：全站访客可读、公开书单的
        # guest_read 一律失效。分享链接已在上面单独放行，不受此门影响。
        if CONF.get("REQUIRE_LOGIN", False):
            return None
        if CONF.get("ALLOW_GUEST_READ", False):
            return "global"
        if BookAccessService._booklist_allows_read(book_id):
            return "booklist"
        return None

    @staticmethod
    def share_link_enabled() -> bool:
        """分享链接功能总开关；与 sys.allow.share_link 一致，不受 REQUIRE_LOGIN 影响。"""
        return bool(CONF.get("ENABLE_SHARE_LINK", True))

    @staticmethod
    def _share_allows(handler, book_id: Optional[int], permission: str) -> bool:
        # 总开关关闭后，已发出的分享链接与已授予的 cookie 一并失效，避免旧授权继续放行
        if not BookAccessService.share_link_enabled():
            return False
        if book_id is None:
            return BookShareService.any_grant(handler)
        share = BookShareService.granted_share(handler, book_id)
        return share is not None and bool(getattr(share, permission))

    @staticmethod
    def share_read_granted(handler, book_id) -> bool:
        # 分享链接优先于 REQUIRE_LOGIN；持有有效授权时也不再受账号阅读权限约束。
        return book_id is not None and BookAccessService._share_allows(handler, book_id, "allow_read")

    @staticmethod
    def share_any_read_granted(handler) -> bool:
        """当前浏览器是否持有任意一本有效分享的阅读授权。

        给「不针对具体书籍」的阅读附属接口用（词典、朗读）：这些接口没有 book_id 可校验，
        语义与 guest_read_allowed(handler, None) 一致——只要手里有一份有效分享，就算"在读"。
        """
        return BookAccessService._share_allows(handler, None, "allow_read")

    @staticmethod
    def share_download_granted(handler, book_id) -> bool:
        return book_id is not None and BookAccessService._share_allows(handler, book_id, "allow_download")

    @staticmethod
    def _booklist_allows_read(book_id: Optional[int]) -> bool:
        # 公开书单的 guest_read 是书单能力的延伸：社区互动模块关闭后书单入口与接口
        # 都已下线，这份授权必须一并失效，否则会留下「书单页面没了、访客照样能读」
        # 的暗门。只影响判定，不改动书单数据，重新打开模块即恢复。
        if not feature_modules.module_enabled(feature_modules.MODULE_COMMUNITY):
            return False
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
        # 分享授权优先于 REQUIRE_LOGIN，其次才是全局"访客可下载"开关
        if BookAccessService._share_allows(handler, book_id, "allow_download"):
            return True
        if CONF.get("REQUIRE_LOGIN", False):
            return False
        return bool(CONF.get("ALLOW_GUEST_DOWNLOAD", False))

    @staticmethod
    def guest_upload_allowed() -> bool:
        """访客上传的总开关（REQUIRE_LOGIN 下恒 False）。

        handlers 里"ALLOW_GUEST_UPLOAD 为真就跳过 can_upload() 检查"的分支必须读这里，
        否则开了必须登录、但遗留 ALLOW_GUEST_UPLOAD=True 时，登录用户即使没有上传权限
        也能上传。
        """
        if CONF.get("REQUIRE_LOGIN", False):
            return False
        return bool(CONF.get("ALLOW_GUEST_UPLOAD", False))

    @staticmethod
    def guest_push_allowed() -> bool:
        """访客推送的总开关（REQUIRE_LOGIN 下恒 False），语义同 guest_upload_allowed。"""
        if CONF.get("REQUIRE_LOGIN", False):
            return False
        return bool(CONF.get("ALLOW_GUEST_PUSH", False))
