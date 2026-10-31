#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""封面背景图库管理接口，仅管理员可写。"""

import asyncio

from tornado import web

from webserver.base.cover_background import CoverBackgroundError, CoverBackgroundService
from webserver.base.image_generator import ImageGenerator
from webserver.handlers.base import BaseHandler, is_admin, js
from webserver.i18n import _


def _item(name):
    return {"id": name, "url": "/api/cover_backgrounds/file/" + name}


def _payload():
    return {
        "items": [_item(name) for name in CoverBackgroundService.list_backgrounds()],
        "count": CoverBackgroundService.count(),
        "max": CoverBackgroundService.MAX_BACKGROUNDS,
    }


class CoverBackgrounds(BaseHandler):
    @js
    @is_admin
    def get(self):
        return {"err": "ok", "data": _payload()}

    @js
    @is_admin
    def post(self):
        files = self.request.files.get("file") or []
        if not files:
            return {"err": "params.invalid", "msg": _("请选择要上传的图片")}
        try:
            CoverBackgroundService.save(files[0])
        except CoverBackgroundError as err:
            return {"err": "cover_background.invalid", "msg": str(err)}
        return {"err": "ok", "msg": _("背景图已添加"), "data": _payload()}


class CoverBackgroundDelete(BaseHandler):
    @js
    @is_admin
    def post(self):
        name = self.get_argument("id", "")
        try:
            removed = CoverBackgroundService.delete(name)
        except CoverBackgroundError as err:
            return {"err": "cover_background.invalid", "msg": str(err)}
        if not removed:
            return {"err": "cover_background.not_found", "msg": _("背景图不存在")}
        return {"err": "ok", "msg": _("背景图已删除"), "data": _payload()}


class CoverBackgroundPreview(BaseHandler):
    async def get(self):
        if not self.is_admin():
            raise web.HTTPError(403, "admin only")
        title = self.get_argument("title", "")
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None, ImageGenerator.generate_cover, title or _("示例书名"), "")
        if not data:
            raise web.HTTPError(500, "generate failed")
        self.set_header("Content-Type", "image/jpeg")
        self.set_header("Cache-Control", "no-store")
        self.write(data)


class CoverBackgroundFile(BaseHandler):
    def get(self, name):
        if not self.is_admin():
            raise web.HTTPError(403, "admin only")
        data = CoverBackgroundService.read(name)
        if data is None:
            raise web.HTTPError(404, "background not found")
        self.set_header("Content-Type", "image/jpeg")
        self.set_header("Cache-Control", "private, max-age=86400")
        self.write(data)


def routes():
    return [
        (r"/api/cover_backgrounds", CoverBackgrounds),
        (r"/api/cover_backgrounds/delete", CoverBackgroundDelete),
        (r"/api/cover_backgrounds/preview", CoverBackgroundPreview),
        (r"/api/cover_backgrounds/file/([^/]+)", CoverBackgroundFile),
    ]
