#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
`/api/book/:id/review`, `/api/book/:id/reviews`, `/api/book/:id/social-stats`
-- user ratings/reviews ("共读" 评价 = 推荐). Business logic lives in
webserver/services/book_review_service.py; see plan/Social_Reading_Plan.md
§2.4/§5.1. Admin moderation endpoints are in webserver/handlers/admin.py.
"""

import logging

import tornado.escape

from webserver import loader
from webserver.handlers.base import BaseHandler, auth, js
from webserver.i18n import _
from webserver.models import BookReview, Reader
from webserver.services.book_review_service import BookReviewService

CONF = loader.get_settings()


def _reader_avatar_url(site_url: str, reader) -> str:
    """同 webserver/handlers/book.py 的 Index._reader_avatar_url：拼成基于 host 的绝对路径，
    避免前端按当前页面路径（如 /book/xxx）相对解析成 /book/avatar/1.png。"""
    if not reader or not reader.avatar:
        return ""
    if reader.avatar.startswith("http"):
        gravatar_url = "https://www.gravatar.com"
        return reader.avatar.replace("http://", "https://").replace(gravatar_url, CONF.get("avatar_service", ""))
    return site_url + "/avatar/%s" % reader.avatar


def _serialize_review(site_url: str, row: BookReview, reader, viewer_reader_id=None) -> dict:
    return {
        "id": row.id,
        "book_id": row.book_id,
        "reader_id": row.reader_id,
        "nickname": (getattr(reader, "name", None) or getattr(reader, "username", None) or "") if reader else "",
        "avatar": _reader_avatar_url(site_url, reader),
        "rating": row.rating,
        "comment": row.comment or "",
        "status": row.status,
        "update_time": row.update_time.isoformat() if row.update_time else None,
        # 前端目前没有拿到当前用户数字 id 的稳定途径，由后端直接判断是否为"我的评价"，
        # 用于列表里展示编辑图标（见 app/src/components/BookReviewList.vue）
        "is_own": viewer_reader_id is not None and row.reader_id == viewer_reader_id,
    }


class BookSocialStatsHandler(BaseHandler):
    @js
    def get(self, id):
        """在读/收藏/推荐人数，见 plan §2.4a。不要求登录（游客也能看）。"""
        book_id = int(id)
        stats = BookReviewService.get_stats(self.sqlite_session, book_id)
        return {"err": "ok", **stats}


class BookReviewHandler(BaseHandler):
    @js
    @auth
    def get(self, id):
        """取当前用户对该书的评价，用于评价对话框预填充/判断编辑态。"""
        row = BookReviewService.get_own(self.sqlite_session, int(id), self.user_id())
        if row is None:
            return {"err": "ok", "review": None}
        return {"err": "ok", "review": _serialize_review(self.site_url, row, self.current_user)}

    @js
    @auth
    def post(self, id):
        if not BookReviewService.is_enabled():
            return {"err": "review.disabled", "msg": _("评论功能未启用")}
        if not getattr(self.current_user, "allow_review", True):
            return {"err": "review.banned", "msg": _("你已被禁止发表评论")}
        book = self.get_book(int(id), raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍已不存在")}

        try:
            data = tornado.escape.json_decode(self.request.body or b"{}")
        except ValueError:
            return {"err": "params.invalid", "msg": _("请求体不是合法的 JSON")}
        rating = data.get("rating")
        if not isinstance(rating, int) or not (0 <= rating <= 10):
            return {"err": "params.invalid", "msg": _("评分不合法")}
        comment = (data.get("comment") or "").strip()

        row = BookReviewService.upsert(self.sqlite_session, int(id), self.user_id(), rating, comment)
        self.invalidate_recommendation()
        logging.info("[book_review] user %s reviewed book %s: rating=%s", self.user_id(), id, rating)
        return {"err": "ok", "review": _serialize_review(self.site_url, row, self.current_user), "msg": _("评价已提交")}

    @js
    @auth
    def delete(self, id):
        ok = BookReviewService.soft_delete(self.sqlite_session, int(id), self.user_id())
        self.invalidate_recommendation()
        if not ok:
            return {"err": "params.invalid", "msg": _("没有可删除的评价")}
        return {"err": "ok", "msg": _("已删除")}


class BookReviewListHandler(BaseHandler):
    @js
    def get(self, id):
        """评论卡片列表，见 plan §2.4c：不做日期筛选/分页，只取最近更新的最多 50 条，当前用户置顶。"""
        book_id = int(id)
        viewer_id = self.current_user.id if self.current_user else None
        rows, total = BookReviewService.list_for_book(self.sqlite_session, book_id, viewer_reader_id=viewer_id)
        readers = {}
        if rows:
            reader_ids = {r.reader_id for r in rows}
            for reader in self.sqlite_session.query(Reader).filter(Reader.id.in_(reader_ids)).all():
                readers[reader.id] = reader
        reviews = [_serialize_review(self.site_url, r, readers.get(r.reader_id), viewer_id) for r in rows]
        return {"err": "ok", "total": total, "reviews": reviews}


def routes():
    return [
        (r"/api/book/([0-9]+)/social-stats", BookSocialStatsHandler),
        (r"/api/book/([0-9]+)/review", BookReviewHandler),
        (r"/api/book/([0-9]+)/reviews", BookReviewListHandler),
    ]
