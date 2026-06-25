#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
`/api/sync` — legacy record sync (books/notes/configs) and the matching
`/api/sync/events` WS change-notification channel. See
document/Sync_IMPLEMENT_PLAN.md for the full protocol/design.

All storage and merge logic lives in webserver/services/sync_service.py;
this module only does auth/feature-gate checks and request/response shaping.
@author: PoxenStudio, 2026-06
"""

import logging

import tornado.escape
import tornado.websocket

from webserver.handlers.base import BaseHandler, auth, js
from webserver.i18n import _
from webserver.services import sync_service


class SyncHandler(BaseHandler):
    @js
    @auth
    def get(self):
        if not sync_service.is_enabled():
            return {"err": "sync.disabled", "msg": _("数据同步功能未启用")}

        since = self.get_argument("since", None)
        if since is None or not since.lstrip("-").isdigit():
            return {"err": "params.invalid", "msg": _("缺少或非法的 since 参数")}
        type_ = self.get_argument("type", None)
        if type_ and type_ not in sync_service.KEY_FIELDS:
            return {"err": "params.invalid", "msg": _("非法的 type 参数")}
        book_hash = self.get_argument("book", None)

        return sync_service.pull(self.current_user.id, int(since), type_, book_hash)

    @js
    @auth
    async def post(self):
        if not sync_service.is_enabled():
            return {"err": "sync.disabled", "msg": _("数据同步功能未启用")}
        logging.debug("[sync] push request from user %s: %s", self.current_user.id, self.request.body)
        try:
            payload = tornado.escape.json_decode(self.request.body or b"{}")
        except ValueError:
            logging.error("[sync] invalid JSON payload from user %s: %s", self.current_user.id, self.request.body)
            return {"err": "params.invalid", "msg": _("请求体不是合法的 JSON")}
        if not isinstance(payload, dict):
            logging.error("[sync] invalid payload type from user %s: %s", self.current_user.id, type(payload))
            return {"err": "params.invalid", "msg": _("请求体格式错误")}

        return await sync_service.push(self.current_user.id, payload)


class SyncWebSocketHandler(tornado.websocket.WebSocketHandler):
    def get_current_user(self):
        user_id = self.get_secure_cookie("user_id")
        if not user_id:
            return None
        return user_id

    def check_origin(self, origin):
        return True

    async def open(self):
        if not sync_service.is_enabled():
            self.close(code=4004, reason="Sync service disabled")
            return
        user_id = self.get_current_user()
        if not user_id:
            logging.warning("[sync] WebSocket connection attempt without login.")
            self.close(code=4003, reason="Authentication required")
            return
        self.uid = int(user_id)
        sync_service.register_connection(self.uid, self)

    def on_message(self, message):
        try:
            data = tornado.escape.json_decode(message)
        except ValueError:
            return
        msg_type = data.get("type")
        if msg_type == "ping":
            self.write_message(tornado.escape.json_encode({"type": "pong"}))
        # `hello` is accepted but ignored in this first version (see plan §11.8).

    def on_close(self):
        if hasattr(self, "uid"):
            sync_service.unregister_connection(self.uid, self)


def routes():
    return [
        (r"/api/sync", SyncHandler),
        (r"/api/sync/events", SyncWebSocketHandler),
    ]
