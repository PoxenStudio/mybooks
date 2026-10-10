#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
`/api/booklists/*`, `/api/booklist/*`, `/api/book/:id/booklists` -- user
booklists (书单). See document/BookList_Design.md for the full design.
Business logic (pure CRUD on booklist_* tables) lives in
webserver/services/booklist_service.py; Calibre book-metadata lookups
(title/cover/existence) stay here, same split as book_review.py.
"""

import logging

import tornado.escape

from webserver import loader
from webserver.handlers.base import BaseHandler, auth, is_admin, js
from webserver.i18n import _
from webserver.models import BookList, Reader
from webserver.services.booklist_service import BookListLimitExceeded, BookListService

CONF = loader.get_settings()

MAX_COVER_BOOKS = 12


def _reader_avatar_url(site_url: str, reader) -> str:
    """同 book_review.py::_reader_avatar_url，拼成基于 host 的绝对路径。"""
    if not reader or not reader.avatar:
        return ""
    if reader.avatar.startswith("http"):
        gravatar_url = "https://www.gravatar.com"
        return reader.avatar.replace("http://", "https://").replace(gravatar_url, CONF.get("avatar_service", ""))
    return site_url + "/avatar/%s" % reader.avatar


class BookListHandlerMixin:
    """给几个 handler 复用的序列化/校验小工具。"""

    def _owner_dict(self, reader):
        if not reader:
            return None
        return {
            "id": reader.id,
            "username": getattr(reader, "name", None) or getattr(reader, "username", None) or "",
            "avatar": _reader_avatar_url(self.site_url, reader),
        }

    def _book_covers(self, book_ids):
        """构造封面卡片列表，做法同 user.py::UserReadingBooks（img/thumb/href 拼接）。"""
        if not book_ids:
            return []
        books_by_id = {b["id"]: b for b in self.calibre_db.get_data_as_dict(ids=book_ids)}
        result = []
        for book_id in book_ids:
            b = books_by_id.get(book_id)
            if not b:
                continue
            result.append({
                "book_id": b["id"],
                "title": b.get("title", ""),
                "img": self.cdn_url + "/get/cover/%(id)s.jpg" % b,
                "thumb": self.cdn_url + "/get/thumb_240_320/%(id)s.jpg?size=240x320" % b,
                "href": "/book/%(id)s" % b,
            })
        return result

    def _serialize(self, row: BookList, viewer_id=None, liked_ids=None, with_covers=True):
        if liked_ids is not None:
            liked_by_me = row.id in liked_ids
        elif viewer_id:
            liked_by_me = BookListService.is_liked(self.sqlite_session, row.id, viewer_id)
        else:
            liked_by_me = False
        data = {
            "id": row.id,
            "name": row.name,
            "description": row.description or "",
            "color": row.color,
            "is_public": row.is_public,
            "is_sticky": row.is_sticky,
            "guest_read": bool(row.guest_read),
            "view_count": row.view_count,
            "like_count": row.like_count,
            "book_count": row.book_count,
            "create_time": row.create_time.isoformat() if row.create_time else None,
            "update_time": row.update_time.isoformat() if row.update_time else None,
            "owner": self._owner_dict(row.reader),
            "is_owner": viewer_id is not None and row.reader_id == viewer_id,
            "liked_by_me": liked_by_me,
        }
        if with_covers:
            book_ids = BookListService.list_book_ids(self.sqlite_session, row.id, order="desc")[:MAX_COVER_BOOKS]
            data["cover_books"] = self._book_covers(book_ids)
        return data

    def _serialize_many(self, rows, viewer_id=None):
        liked_ids = set()
        if viewer_id and rows:
            from webserver.models import BookListLike
            liked_ids = {
                r[0]
                for r in self.sqlite_session.query(BookListLike.booklist_id).filter(
                    BookListLike.reader_id == viewer_id,
                    BookListLike.booklist_id.in_([row.id for row in rows]),
                ).all()
            }
        return [self._serialize(row, viewer_id=viewer_id, liked_ids=liked_ids) for row in rows]

    def _get_owned_or_none(self, booklist_id):
        row = BookListService.get(self.sqlite_session, booklist_id)
        if row is None:
            return None, {"err": "booklist.not_found", "msg": _("书单不存在")}
        if row.reader_id != self.user_id() and not self.is_admin():
            return None, {"err": "permission.denied", "msg": _("没有权限操作这个书单")}
        return row, None


class BookListMineHandler(BaseHandler, BookListHandlerMixin):
    @js
    @auth
    def get(self):
        rows = BookListService.list_mine(self.sqlite_session, self.user_id())
        return {"err": "ok", "booklists": self._serialize_many(rows, viewer_id=self.user_id())}


class BookListPublicHandler(BaseHandler, BookListHandlerMixin):
    @js
    def get(self):
        page = int(self.get_argument("page", "1"))
        page_size = min(int(self.get_argument("page_size", "20")), 50)
        viewer_id = self.current_user.id if self.current_user else None
        rows, total = BookListService.list_public(self.sqlite_session, page=page, page_size=page_size)
        return {"err": "ok", "total": total, "page": page, "page_size": page_size, "booklists": self._serialize_many(rows, viewer_id=viewer_id)}


class BookListLikedHandler(BaseHandler, BookListHandlerMixin):
    @js
    @auth
    def get(self):
        rows = BookListService.list_liked(self.sqlite_session, self.user_id())
        return {"err": "ok", "booklists": self._serialize_many(rows, viewer_id=self.user_id())}


class BookListHomepageHandler(BaseHandler, BookListHandlerMixin):
    @js
    def get(self):
        if not CONF.get("ENABLE_HOMEPAGE_BOOKLISTS", True):
            return {"err": "ok", "booklists": []}
        viewer_id = self.current_user.id if self.current_user else None
        rows = BookListService.list_for_homepage(self.sqlite_session, viewer_id, limit=2)
        return {"err": "ok", "booklists": self._serialize_many(rows, viewer_id=viewer_id)}


class BookListCreateHandler(BaseHandler, BookListHandlerMixin):
    @js
    @auth
    def post(self):
        try:
            data = tornado.escape.json_decode(self.request.body or b"{}")
        except ValueError:
            return {"err": "params.invalid", "msg": _("请求体不是合法的 JSON")}
        name = (data.get("name") or "").strip()
        if not name:
            return {"err": "params.invalid", "msg": _("书单名称不能为空")}
        description = (data.get("description") or "").strip()[:500]
        color = data.get("color")
        is_public = bool(data.get("is_public", False))
        guest_read = bool(data.get("guest_read", False)) and self.is_admin()
        if guest_read and not is_public:
            return {"err": "params.invalid", "msg": _("仅公开书单可以开启访客阅读")}
        try:
            row = BookListService.create(self.sqlite_session, self.user_id(), name, description, color, is_public)
            if guest_read:
                row = BookListService.update(self.sqlite_session, row, guest_read=True)
        except BookListLimitExceeded:
            return {"err": "booklist.limit_exceeded", "msg": _("最多只能创建 %(limit)s 个书单") % {"limit": BookList.MAX_PER_USER}}
        logging.info("[booklist] user %s created booklist %s", self.user_id(), row.id)
        return {"err": "ok", "booklist": self._serialize(row, viewer_id=self.user_id()), "msg": _("创建成功")}


class BookListDetailHandler(BaseHandler, BookListHandlerMixin):
    @js
    def get(self, id):
        booklist_id = int(id)
        row = BookListService.get(self.sqlite_session, booklist_id)
        if row is None:
            return {"err": "booklist.not_found", "msg": _("书单不存在")}
        viewer_id = self.current_user.id if self.current_user else None
        if not row.is_public and row.reader_id != viewer_id and not self.is_admin():
            return {"err": "permission.denied", "msg": _("这是一个私有书单")}

        order = self.get_argument("order", "desc")
        page = int(self.get_argument("page", "1"))
        page_size = min(int(self.get_argument("page_size", "24")), 60)
        book_ids = BookListService.list_book_ids(self.sqlite_session, booklist_id, order=order)
        total = len(book_ids)
        page_ids = book_ids[(page - 1) * page_size: page * page_size]

        data = self._serialize(row, viewer_id=viewer_id, with_covers=False)
        data["books"] = self._book_covers(page_ids)
        data["books_total"] = total
        data["page"] = page
        data["page_size"] = page_size
        return {"err": "ok", "booklist": data}

    @js
    @auth
    def post(self, id):
        row, err = self._get_owned_or_none(int(id))
        if err:
            return err
        try:
            data = tornado.escape.json_decode(self.request.body or b"{}")
        except ValueError:
            return {"err": "params.invalid", "msg": _("请求体不是合法的 JSON")}
        name = data.get("name")
        if name is not None:
            name = name.strip()
            if not name:
                return {"err": "params.invalid", "msg": _("书单名称不能为空")}
        description = data.get("description")
        if description is not None:
            description = description.strip()[:500]
        color = data.get("color")
        is_public = data.get("is_public")
        guest_read = bool(data["guest_read"]) if self.is_admin() and "guest_read" in data else None
        if guest_read and not (row.is_public if is_public is None else is_public):
            return {"err": "params.invalid", "msg": _("仅公开书单可以开启访客阅读")}
        row = BookListService.update(self.sqlite_session, row, name=name, description=description, color=color, is_public=is_public, guest_read=guest_read)
        return {"err": "ok", "booklist": self._serialize(row, viewer_id=self.user_id()), "msg": _("已更新")}


class BookListDeleteHandler(BaseHandler, BookListHandlerMixin):
    @js
    @auth
    def post(self, id):
        row, err = self._get_owned_or_none(int(id))
        if err:
            return err
        BookListService.delete(self.sqlite_session, row)
        logging.info("[booklist] user %s deleted booklist %s", self.user_id(), id)
        return {"err": "ok", "msg": _("已删除")}


class BookListStickyHandler(BaseHandler, BookListHandlerMixin):
    @js
    @is_admin
    def post(self, id):
        row = BookListService.get(self.sqlite_session, int(id))
        if row is None:
            return {"err": "booklist.not_found", "msg": _("书单不存在")}
        try:
            data = tornado.escape.json_decode(self.request.body or b"{}")
        except ValueError:
            data = {}
        is_sticky = bool(data.get("is_sticky", not row.is_sticky))
        sticky_order = data.get("sticky_order")
        row = BookListService.set_sticky(self.sqlite_session, row, is_sticky, sticky_order)
        return {"err": "ok", "booklist": self._serialize(row, viewer_id=self.user_id()), "msg": _("已更新")}


class BookListLikeHandler(BaseHandler, BookListHandlerMixin):
    @js
    @auth
    def post(self, id):
        row = BookListService.get(self.sqlite_session, int(id))
        if row is None:
            return {"err": "booklist.not_found", "msg": _("书单不存在")}
        if not row.is_public and row.reader_id != self.user_id():
            return {"err": "permission.denied", "msg": _("私有书单不能点赞")}
        liked = BookListService.toggle_like(self.sqlite_session, row.id, self.user_id())
        return {"err": "ok", "liked": liked}


class BookListViewHandler(BaseHandler, BookListHandlerMixin):
    @js
    def post(self, id):
        row = BookListService.get(self.sqlite_session, int(id))
        if row is None:
            return {"err": "booklist.not_found", "msg": _("书单不存在")}
        viewer_id = self.current_user.id if self.current_user else None
        if not row.is_public and row.reader_id != viewer_id and not self.is_admin():
            return {"err": "permission.denied", "msg": _("这是一个私有书单")}
        BookListService.bump_view(self.sqlite_session, row.id)
        return {"err": "ok"}


class BookListBooksAddHandler(BaseHandler, BookListHandlerMixin):
    @js
    @auth
    def post(self, id):
        row, err = self._get_owned_or_none(int(id))
        if err:
            return err
        try:
            data = tornado.escape.json_decode(self.request.body or b"{}")
        except ValueError:
            return {"err": "params.invalid", "msg": _("请求体不是合法的 JSON")}
        book_ids = data.get("book_ids")
        if book_ids is None and data.get("book_id") is not None:
            book_ids = [data.get("book_id")]
        if not isinstance(book_ids, list) or not book_ids:
            return {"err": "params.invalid", "msg": _("请指定要加入的书籍")}
        try:
            book_ids = [int(b) for b in book_ids]
        except (TypeError, ValueError):
            return {"err": "params.invalid", "msg": _("书籍 ID 不合法")}

        # 只加入真实存在的书籍
        existing_ids = {b["id"] for b in self.calibre_db.get_data_as_dict(ids=book_ids)}
        valid_ids = [b for b in book_ids if b in existing_ids]
        if not valid_ids:
            return {"err": "params.book.invalid", "msg": _("书籍不存在")}

        added = BookListService.add_books(self.sqlite_session, row, valid_ids)
        return {"err": "ok", "added": added, "book_count": row.book_count, "msg": _("已加入书单")}


class BookListBooksRemoveHandler(BaseHandler, BookListHandlerMixin):
    @js
    @auth
    def post(self, id):
        row, err = self._get_owned_or_none(int(id))
        if err:
            return err
        try:
            data = tornado.escape.json_decode(self.request.body or b"{}")
        except ValueError:
            return {"err": "params.invalid", "msg": _("请求体不是合法的 JSON")}
        book_id = data.get("book_id")
        if book_id is None:
            return {"err": "params.invalid", "msg": _("请指定要移出的书籍")}
        ok = BookListService.remove_book(self.sqlite_session, row, int(book_id))
        if not ok:
            return {"err": "params.invalid", "msg": _("这本书不在书单中")}
        return {"err": "ok", "book_count": row.book_count, "msg": _("已从书单移出")}


class BookBookListsHandler(BaseHandler, BookListHandlerMixin):
    """供书籍详情页"快速加入书单"面板用：当前用户的书单列表 + 该书已在哪些书单中。"""

    @js
    @auth
    def get(self, id):
        book_id = int(id)
        rows = BookListService.list_mine(self.sqlite_session, self.user_id())
        contained = BookListService.booklists_containing_book(self.sqlite_session, self.user_id(), book_id)
        booklists = [{
            "id": row.id,
            "name": row.name,
            "color": row.color,
            "is_public": row.is_public,
            "contains_book": row.id in contained,
        } for row in rows]
        return {"err": "ok", "booklists": booklists}


def routes():
    return [
        (r"/api/booklists/mine", BookListMineHandler),
        (r"/api/booklists/public", BookListPublicHandler),
        (r"/api/booklists/liked", BookListLikedHandler),
        (r"/api/booklists/homepage", BookListHomepageHandler),
        (r"/api/booklist/create", BookListCreateHandler),
        (r"/api/booklist/([0-9]+)", BookListDetailHandler),
        (r"/api/booklist/([0-9]+)/update", BookListDetailHandler),
        (r"/api/booklist/([0-9]+)/delete", BookListDeleteHandler),
        (r"/api/booklist/([0-9]+)/sticky", BookListStickyHandler),
        (r"/api/booklist/([0-9]+)/like", BookListLikeHandler),
        (r"/api/booklist/([0-9]+)/view", BookListViewHandler),
        (r"/api/booklist/([0-9]+)/books/add", BookListBooksAddHandler),
        (r"/api/booklist/([0-9]+)/books/remove", BookListBooksRemoveHandler),
        (r"/api/book/([0-9]+)/booklists", BookBookListsHandler),
    ]
