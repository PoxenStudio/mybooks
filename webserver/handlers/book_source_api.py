#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""书源引擎 API — MyBooks Toolbox「书源管理」路由。

对应前端页面 app/pages/toolbox/book_source.vue。
所有响应遵循 MyBooks 约定：{"err": "ok", ...}，错误时 {"err": "...", "msg": "..."}。
"""
import os
import re
import tempfile
import tornado

from urllib.parse import quote

from webserver.i18n import _
from webserver.handlers.base import BaseHandler, js, is_admin
from webserver.toolbox.book_source_tool import BookSourceTool
from webserver.services.background_service import BackgroundService, BackgroundTask


class AdminBookSourceList(BaseHandler):
    @js
    @is_admin
    def get(self):
        return {"err": "ok", "data": BookSourceTool().list_sources()}


class AdminBookSourceSave(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        raw = data.get("raw")
        if not isinstance(raw, dict) or not (raw.get("bookSourceName") or "").strip():
            return {"err": "params.missing", "msg": _("请提供书源 JSON（含 bookSourceName）")}
        try:
            result = BookSourceTool().add_source(raw)
        except ValueError as err:
            return {"err": "book_source.invalid", "msg": str(err)}
        return {"err": "ok", "data": result}


class AdminBookSourceToggle(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        name = (data.get("name") or "").strip()
        if not name:
            return {"err": "params.missing", "msg": _("请提供书源名称")}
        result = BookSourceTool().toggle_source(name)
        if result.get("status") == "not_found":
            return {"err": "book_source.not_found", "msg": _("书源不存在: %s") % name}
        return {"err": "ok", "data": result}


class AdminBookSourceDelete(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        name = (data.get("name") or "").strip()
        if not name:
            return {"err": "params.missing", "msg": _("请提供书源名称")}
        result = BookSourceTool().delete_source(name)
        if result.get("status") == "not_found":
            return {"err": "book_source.not_found", "msg": _("书源不存在: %s") % name}
        return {"err": "ok", "data": result}


class AdminBookSourceSearchAsync(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        keyword = (data.get("keyword") or "").strip()
        if not keyword:
            return {"err": "params.missing", "msg": _("请提供搜索关键词")}
        source_names = data.get("source_names")
        result = BookSourceTool().search_async(keyword, source_names)
        return {"err": "ok", "data": result}


class AdminBookSourceSearchStatus(BaseHandler):
    @js
    @is_admin
    def get(self):
        task_id = self.get_argument("task_id", "")
        if not task_id:
            return {"err": "params.missing", "msg": _("缺少 task_id")}
        status = BookSourceTool().get_search_status(task_id)
        if status is None:
            return {"err": "task.not_found", "msg": _("搜索任务不存在或已过期")}
        return {"err": "ok", "data": status}


class AdminBookSourceTest(BaseHandler):
    @js
    @is_admin
    def get(self):
        name = self.get_argument("source", "")
        if not name:
            return {"err": "params.missing", "msg": _("请提供书源名称")}
        try:
            result = BookSourceTool().test_source(name)
        except ValueError as err:
            return {"err": "book_source.invalid", "msg": str(err)}
        return {"err": "ok", "data": result}


class AdminBookSourceDownload(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        source = (data.get("source") or "").strip()
        book_url = (data.get("bookUrl") or "").strip()
        if not source or not book_url:
            return {"err": "params.missing", "msg": _("请提供书源与书籍地址")}
        try:
            max_chapters = max(1, min(int(data.get("maxChapters", 9999)), 9999))
        except (TypeError, ValueError):
            max_chapters = 9999
        BookSourceTool().download_book(
            source_name=source,
            book_url=book_url,
            book_title=data.get("bookTitle", ""),
            max_chapters=max_chapters,
            user_id=self.user_id(),
        )
        return {"err": "ok", "msg": _("下载任务已启动，右上角可以查看进度")}


class AdminBookSourceGenerateEpub(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        source = (data.get("source") or "").strip()
        book_url = (data.get("bookUrl") or "").strip()
        if not source or not book_url:
            return {"err": "params.missing", "msg": _("请提供书源与书籍地址")}
        try:
            max_chapters = max(1, min(int(data.get("maxChapters", 9999)), 9999))
        except (TypeError, ValueError):
            max_chapters = 9999
        BookSourceTool().generate_epub_task(
            source_name=source,
            book_url=book_url,
            book_title=data.get("bookTitle", ""),
            max_chapters=max_chapters,
            user_id=self.user_id(),
        )
        return {"err": "ok", "msg": _("EPUB 生成任务已启动，右上角可以查看进度")}


class AdminBookSourceCancel(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        task_id = data.get("task_id")
        if not task_id:
            return {"err": "params.missing", "msg": _("缺少 task_id")}
        ok = BackgroundService().cancel_task(int(task_id))
        if not ok:
            return {"err": "task.not_found", "msg": _("任务不存在或已结束")}
        return {"err": "ok", "msg": _("任务已取消")}


class AdminBookSourceProgress(BaseHandler):
    @js
    @is_admin
    def get(self):
        task = BookSourceTool.get_last_task(self.user_id())
        if not task:
            return {"err": "ok", "data": None}
        progress_data = task.get("progress_data") or {}
        return {
            "err": "ok",
            "data": {
                "task_id": task.get("id"),
                "progress": task.get("progress", 0),
                "status": task.get("status"),
                "progress_data": progress_data,
            },
        }


class AdminBookSourceImportZip(BaseHandler):
    @js
    @is_admin
    def post(self):
        if not self.request.files or 'file' not in self.request.files:
            return {"err": "params.missing", "msg": _("未上传文件")}

        file_meta = self.request.files['file'][0]
        suffix = os.path.splitext(file_meta['filename'])[1] or ".zip"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(file_meta['body'])
            tmp_path = f.name
        try:
            result = BookSourceTool().import_sources_from_zip(tmp_path)
        except (ValueError, RuntimeError) as err:
            return {"err": "book_source.import_failed", "msg": str(err)}
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        if result.get("status") == "ok" or result.get("added", 0) > 0:
            return {"err": "ok", "msg": _("导入成功，新增 %s 个书源") % result.get("added", 0), "data": result}
        return {"err": "book_source.import_failed", "msg": result.get("message", _("导入失败")), "data": result}


class AdminBookSourceImportUrl(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        url = (data.get("url") or "").strip()
        if not url:
            return {"err": "params.missing", "msg": _("网址不能为空")}
        try:
            result = BookSourceTool().import_sources_from_url(url)
        except (ValueError, RuntimeError) as err:
            return {"err": "book_source.import_failed", "msg": str(err)}
        if result.get("status") == "ok" or result.get("added", 0) > 0:
            return {"err": "ok", "msg": _("导入成功，新增 %s 个书源") % result.get("added", 0), "data": result}
        return {"err": "book_source.import_failed", "msg": result.get("message", _("导入失败")), "data": result}


class AdminBookSourceDownloadEpub(BaseHandler):
    @is_admin
    def get(self):
        epub_path = BookSourceTool().get_last_epub_path(self.user_id())
        if not epub_path or not os.path.exists(epub_path):
            self.set_status(404)
            self.write("EPUB not found")
            return

        filename = os.path.basename(epub_path)
        ascii_name = re.sub(r'[^\x00-\x7f]', '_', filename) or "book.epub"
        encoded_name = quote(filename)
        self.set_header('Content-Type', 'application/epub+zip')
        self.set_header('Content-Disposition',
                        f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}')
        with open(epub_path, 'rb') as f:
            self.write(f.read())


BOOK_SOURCE_ROUTES = [
    (r"/api/toolbox/book_source/list", AdminBookSourceList),
    (r"/api/toolbox/book_source/save", AdminBookSourceSave),
    (r"/api/toolbox/book_source/toggle", AdminBookSourceToggle),
    (r"/api/toolbox/book_source/delete", AdminBookSourceDelete),
    (r"/api/toolbox/book_source/search_async", AdminBookSourceSearchAsync),
    (r"/api/toolbox/book_source/search_status", AdminBookSourceSearchStatus),
    (r"/api/toolbox/book_source/test", AdminBookSourceTest),
    (r"/api/toolbox/book_source/download", AdminBookSourceDownload),
    (r"/api/toolbox/book_source/generate_epub", AdminBookSourceGenerateEpub),
    (r"/api/toolbox/book_source/cancel", AdminBookSourceCancel),
    (r"/api/toolbox/book_source/progress", AdminBookSourceProgress),
    (r"/api/toolbox/book_source/import_zip", AdminBookSourceImportZip),
    (r"/api/toolbox/book_source/import_url", AdminBookSourceImportUrl),
    (r"/api/toolbox/book_source/download_epub", AdminBookSourceDownloadEpub),
]
