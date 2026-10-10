#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
`/api/admin/share*`（管理员维护分享链接）与 `/api/share/<token>*`（匿名访问）。
设计见 document/Share_Visits_GuestBooklist_Design.md。
"""

import logging

import tornado.escape

from webserver import loader
from webserver.base.formatter import BookFormatter
from webserver.handlers.base import BaseHandler, is_admin, js
from webserver.i18n import _
from webserver.models import BookShare
from webserver.services.book_share_service import RESULT_BAD_PASSWORD, RESULT_LOCKED, RESULT_OK, BookShareService, ShareParamError

CONF = loader.get_settings()

MAX_PAGE_SIZE = 100


def _invalid():
    return {"err": "share.invalid", "msg": _("链接无效或已失效")}


class ShareHandlerMixin:

    def _share_dict(self, share, title=None):
        data = {
            "id": share.id,
            "book_id": share.book_id,
            "token": share.token,
            "path": "/s/" + share.token,
            "password": share.password,
            "allow_read": bool(share.allow_read),
            "allow_download": bool(share.allow_download),
            "expire_time": share.expire_time.isoformat() if share.expire_time else None,
            "max_views": share.max_views,
            "view_count": share.view_count,
            "status": share.status,
            "state": BookShareService.state_of(share),
            "create_time": share.create_time.isoformat() if share.create_time else None,
            "update_time": share.update_time.isoformat() if share.update_time else None,
        }
        if title is not None:
            data["title"] = title
            data["thumb"] = self.cdn_url + "/get/thumb_240_320/%d.jpg?size=240x320" % share.book_id
        return data

    def _json_body(self):
        try:
            data = tornado.escape.json_decode(self.request.body or b"{}")
        except ValueError:
            return None
        return data if isinstance(data, dict) else None


class AdminBookShareHandler(BaseHandler, ShareHandlerMixin):

    @js
    @is_admin
    def get(self, bid):
        share = BookShareService.get_by_book(int(bid))
        return {"err": "ok", "share": self._share_dict(share) if share else None}

    @js
    @is_admin
    def post(self, bid):
        book_id = int(bid)
        data = self._json_body()
        if data is None:
            return {"err": "params.invalid", "msg": _("请求体不是合法的 JSON")}
        if not self.get_book(book_id, raise_exception=False):
            return {"err": "params.book.invalid", "msg": _("书籍已不存在")}
        try:
            share = BookShareService.create_or_update(
                book_id,
                self.user_id(),
                bool(data.get("allow_read", True)),
                bool(data.get("allow_download", False)),
                int(data.get("expire_days", 0)),
                int(data.get("max_views", 0)),
                data.get("password"),
            )
        except (ShareParamError, TypeError, ValueError) as e:
            logging.info("[share] invalid params: %s", e)
            return {"err": "params.invalid", "msg": _("分享参数不正确")}
        logging.info("[share] admin %s saved share %s for book %s", self.user_id(), share.id, book_id)
        return {"err": "ok", "share": self._share_dict(share), "msg": _("分享已保存")}


class AdminShareCancelHandler(BaseHandler, ShareHandlerMixin):

    @js
    @is_admin
    def post(self, share_id):
        if not BookShareService.cancel(int(share_id)):
            return {"err": "share.not_found", "msg": _("分享不存在")}
        return {"err": "ok", "msg": _("分享已取消")}


class AdminShareDeleteHandler(BaseHandler, ShareHandlerMixin):

    @js
    @is_admin
    def post(self, share_id):
        if not BookShareService.delete(int(share_id)):
            return {"err": "share.not_found", "msg": _("分享不存在")}
        return {"err": "ok", "msg": _("分享已删除")}


class AdminShareListHandler(BaseHandler, ShareHandlerMixin):

    @js
    @is_admin
    def get(self):
        start = self.get_argument_start()
        try:
            limit = max(1, min(int(self.get_argument("limit", "10")), MAX_PAGE_SIZE))
        except ValueError:
            limit = 10
        rows, total = BookShareService.list_page(start, limit)
        titles = self.calibre_db_cache.all_field_for("title", {row.book_id for row in rows}, "") if rows else {}
        return {"err": "ok", "total": total, "shares": [self._share_dict(row, titles.get(row.book_id, "")) for row in rows]}


class ShareInfoHandler(BaseHandler, ShareHandlerMixin):

    def _payload(self, share, granted):
        book = self.get_book(share.book_id, raise_exception=False)
        if not book:
            return None
        info = BookFormatter(self, book).format(with_files=True)
        data = {
            "err": "ok",
            "title": info["title"],
            "author": info["author"],
            "comments": info["comments"],
            "img": info["img"],
            "thumb": info["thumb"],
            "allow_read": bool(share.allow_read),
            "allow_download": bool(share.allow_download),
            "need_password": bool(share.password),
            "granted": granted,
            "expire_time": share.expire_time.isoformat() if share.expire_time else None,
        }
        if granted:
            data["book_id"] = share.book_id
            data["files"] = info["files"] if share.allow_download else []
        return data

    def _usable(self, share, granted):
        if share is None or share.status != BookShare.STATUS_ACTIVE or share.is_expired():
            return False
        return granted or not share.is_exhausted()

    @js
    def get(self, token):
        share = BookShareService.get_by_token(token)
        granted = share is not None and BookShareService.has_grant(self, share)
        if not self._usable(share, granted):
            return _invalid()
        return self._payload(share, granted) or _invalid()


class ShareVerifyHandler(ShareInfoHandler):

    @js
    def post(self, token):
        share = BookShareService.get_by_token(token)
        granted = share is not None and BookShareService.has_grant(self, share)
        if not self._usable(share, granted):
            return _invalid()
        if not granted:
            data = self._json_body() or {}
            result = BookShareService.verify(share, str(data.get("password", "")), self.request.remote_ip)
            if result == RESULT_LOCKED:
                return {"err": "share.locked", "msg": _("尝试次数过多，请稍后再试")}
            if result == RESULT_BAD_PASSWORD:
                return {"err": "share.bad_password", "msg": _("提取码不正确")}
            if result != RESULT_OK:
                return _invalid()
            BookShareService.issue_grant(self, share)
        return self._payload(share, True) or _invalid()


def routes():
    return [
        (r"/api/admin/share/book/([0-9]+)", AdminBookShareHandler),
        (r"/api/admin/share/([0-9]+)/cancel", AdminShareCancelHandler),
        (r"/api/admin/share/([0-9]+)/delete", AdminShareDeleteHandler),
        (r"/api/admin/shares", AdminShareListHandler),
        (r"/api/share/([A-Za-z0-9_-]{1,64})", ShareInfoHandler),
        (r"/api/share/([A-Za-z0-9_-]{1,64})/verify", ShareVerifyHandler),
    ]
