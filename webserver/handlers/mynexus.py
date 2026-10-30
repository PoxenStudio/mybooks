import asyncio
import datetime
import json
import logging
import os
import requests
import tornado.escape
import tornado.web as web

from webserver.handlers.base import BaseHandler, auth, is_admin, js
from webserver.base import modules as feature_modules
from webserver.models import MyNexusBookAnalysis, MyNexusChatSession
from webserver.services.book_access_service import BookAccessService
from webserver.services.mynexus_service import MyNexusClient, MyNexusError, safe_json
from webserver import utils
from webserver.i18n import _


_book_locks = {}
_status_tasks = {}

ACTIVE_STATUSES = ("pending", "processing", "submitting")


def _book_lock(book_id):
    return _book_locks.setdefault(book_id, asyncio.Lock())


def _analysis_dict(analysis):
    if not analysis:
        return {
            "status": "not_started",
            "progress": 0,
            "error_msg": "",
            "reading_guide": "",
            "can_retry": False,
            "response": {},
        }
    return {
        "status": analysis.status,
        "progress": analysis.progress,
        "error_msg": analysis.error_msg,
        "reading_guide": analysis.reading_guide,
        # A failed analysis is always retryable: MyNexus can retry the failed
        # ingest/summarize task, or MyBooks re-uploads the book when the remote
        # record no longer exists.
        "can_retry": analysis.status == "failed",
        "response": safe_json(analysis.response_json),
    }


def _failed_task_id(response):
    """Return the id of the remote task that should be retried, if any."""
    for key in ("ingest_task", "summarize_task"):
        task = response.get(key) or {}
        if (
            isinstance(task, dict)
            and task.get("id")
            and task.get("status") in ("failed", "canceled")
        ):
            return task["id"]
    return None


_MAX_SELECTION_CHARS = 2000
_MAX_TITLE_CHARS = 200
_MAX_HREF_CHARS = 500
_MAX_CFI_CHARS = 500
_MAX_SNIPPET_CHARS = 50
_MAX_CONTEXT_BYTES = 8192


def _context_text(value, limit):
    if not isinstance(value, str):
        return ""
    return value[:limit]


def _context_int(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def _context_fraction(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return min(1.0, max(0.0, float(value)))


def _normalize_context(raw):
    """Drop malformed fields and enforce the wire limits shared with MyReader."""
    if not isinstance(raw, dict):
        return None
    reading = raw.get("reading")
    selection = raw.get("selection")
    out = {}
    if isinstance(reading, dict):
        out["reading"] = {
            "book_title": _context_text(reading.get("book_title"), _MAX_TITLE_CHARS),
            "chapter_title": _context_text(reading.get("chapter_title"), _MAX_TITLE_CHARS),
            "chapter_href": _context_text(reading.get("chapter_href"), _MAX_HREF_CHARS),
            "section_index": _context_int(reading.get("section_index")),
            "progress_fraction": _context_fraction(reading.get("progress_fraction")),
            "page": _context_int(reading.get("page")),
            "cfi": _context_text(reading.get("cfi"), _MAX_CFI_CHARS),
            "snippet": _context_text(reading.get("snippet"), _MAX_SNIPPET_CHARS),
        }
    if isinstance(selection, dict):
        text = _context_text(selection.get("text"), _MAX_SELECTION_CHARS)
        if text:
            out["selection"] = {
                "text": text,
                "chapter_title": _context_text(selection.get("chapter_title"), _MAX_TITLE_CHARS),
                "chapter_href": _context_text(selection.get("chapter_href"), _MAX_HREF_CHARS),
                "section_index": _context_int(selection.get("section_index")),
                "page": _context_int(selection.get("page")),
                "progress_fraction": _context_fraction(selection.get("progress_fraction")),
                "cfi": _context_text(selection.get("cfi"), _MAX_CFI_CHARS),
            }
    if not out:
        return None
    if len(json.dumps(out, ensure_ascii=False).encode("utf-8")) > _MAX_CONTEXT_BYTES:
        out.pop("selection", None)
        if not out or len(json.dumps(out, ensure_ascii=False).encode("utf-8")) > _MAX_CONTEXT_BYTES:
            return None
    return out


def _update_analysis(session, analysis, response):
    status = response.get("analysis_status") or "processing"
    ingest = response.get("ingest_task") or {}
    summarize = response.get("summarize_task") or {}
    current_task = summarize if ingest.get("status") == "completed" else ingest
    progress = 100 if status == "completed" else int(current_task.get("progress") or 0)
    analysis.remote_book_id = response.get("book_id") or analysis.remote_book_id
    analysis.status = status
    analysis.progress = max(0, min(100, progress))
    analysis.error_msg = response.get("error_msg") or current_task.get("error_msg") or ""
    analysis.reading_guide = response.get("reading_guide") or ""
    analysis.response_json = json.dumps(response, ensure_ascii=False)
    analysis.update_time = datetime.datetime.now()
    session.commit()


def _mark_analysis_failed(session, analysis, message, clear_remote=False):
    analysis.status = "failed"
    analysis.error_msg = message
    if clear_remote:
        analysis.remote_book_id = ""
    analysis.update_time = datetime.datetime.now()
    session.commit()


def _persist_status(scoped_session, book_id, response):
    session = scoped_session()
    try:
        analysis = session.get(MyNexusBookAnalysis, book_id)
        if not analysis:
            return None
        _update_analysis(session, analysis, response)
        return analysis.status
    finally:
        session.close()
        scoped_session.remove()


REMOTE_MISSING_ERROR = "MyNexus has no book matching this MyBooks ID"


async def _refresh_remote_analysis(session, analysis, book_id):
    """Mirror the MyNexus analysis status of a book into our local record.

    Returns ``(state, error)`` where ``state`` is ``"completed"``,
    ``"not_ready"`` or ``"missing"``. ``error`` is a ``MyNexusError`` when
    MyNexus itself could not be reached, so callers can surface the transport
    failure instead of treating the book as deleted.
    """
    try:
        client = MyNexusClient()
        response = await utils.run_in_threadpool(client.analysis_status, book_id)
    except MyNexusError as exc:
        if exc.status_code == 404:
            # The remote book (and therefore its AI analysis) no longer exists.
            _mark_analysis_failed(session, analysis, REMOTE_MISSING_ERROR, clear_remote=True)
            return "missing", None
        return None, exc
    _update_analysis(session, analysis, response)
    if analysis.status == "completed":
        return "completed", None
    return "not_ready", None


def _persist_failure(scoped_session, book_id, message):
    session = scoped_session()
    try:
        analysis = session.get(MyNexusBookAnalysis, book_id)
        if analysis:
            _mark_analysis_failed(session, analysis, message, clear_remote=True)
    finally:
        session.close()
        scoped_session.remove()


async def _poll_analysis(book_id, scoped_session):
    try:
        client = MyNexusClient()
    except MyNexusError:
        return
    for _ in range(720):
        await asyncio.sleep(5)
        try:
            response = await utils.run_in_threadpool(client.analysis_status, book_id)
        except MyNexusError as exc:
            if exc.status_code == 404:
                await asyncio.get_running_loop().run_in_executor(
                    None, _persist_failure, scoped_session, book_id,
                    "MyNexus has no book matching this MyBooks ID",
                )
                return
            logging.error("MyNexus background status lookup for book %s failed: %s", book_id, exc.message)
            continue
        status = await asyncio.get_running_loop().run_in_executor(
            None, _persist_status, scoped_session, book_id, response
        )
        if status not in ACTIVE_STATUSES:
            return


def _ensure_status_poll(book_id, scoped_session):
    task = _status_tasks.get(book_id)
    if task is None or task.done():
        _status_tasks[book_id] = asyncio.create_task(_poll_analysis(book_id, scoped_session))


class MyNexusBookHandler(feature_modules.ModuleGateMixin, BaseHandler):
    module_id = feature_modules.MODULE_AI

    async def _book(self, raw_id):
        try:
            book_id = int(raw_id)
        except (TypeError, ValueError):
            return None, None
        book = await self.get_book_async(book_id, raise_exception=False)
        if not book:
            return book_id, None
        if not self.current_user and not BookAccessService.guest_read_allowed(self, book_id):
            return book_id, None
        return book_id, book

    async def _retry_remote_analysis(self, client, book_id, analysis):
        """Retry the failed remote task, reusing the book already on MyNexus."""
        response = await utils.run_in_threadpool(client.analysis_status, book_id)
        if response.get("analysis_status") != "failed":
            # The remote side may have moved on (still running or completed).
            _update_analysis(self.sqlite_session, analysis, response)
            if analysis.status in ACTIVE_STATUSES:
                _ensure_status_poll(book_id, self.settings["ScopedSession"])
            return True
        task_id = _failed_task_id(response)
        if not task_id:
            return False
        await utils.run_in_threadpool(client.retry_task, task_id)
        analysis.status = "pending"
        analysis.progress = 0
        analysis.error_msg = ""
        analysis.update_time = datetime.datetime.now()
        self.sqlite_session.commit()
        _ensure_status_poll(book_id, self.settings["ScopedSession"])
        return True

    @js
    @is_admin
    async def post(self, raw_id):
        book_id, book = await self._book(raw_id)
        if not book:
            return {"err": "not_found", "msg": _("未找到该图书或无权访问")}
        async with _book_lock(book_id):
            analysis = self.sqlite_session.get(MyNexusBookAnalysis, book_id)
            if analysis and analysis.status in ACTIVE_STATUSES + ("completed",):
                return {"err": "ok", "analysis": _analysis_dict(analysis)}
            try:
                client = MyNexusClient()
            except MyNexusError as exc:
                return {"err": "mynexus.error", "msg": exc.message}
            if analysis and analysis.status == "failed" and analysis.remote_book_id:
                try:
                    if await self._retry_remote_analysis(client, book_id, analysis):
                        return {"err": "ok", "analysis": _analysis_dict(analysis)}
                except MyNexusError as exc:
                    if exc.status_code != 404:
                        _mark_analysis_failed(self.sqlite_session, analysis, exc.message)
                        return {"err": "mynexus.error", "msg": exc.message}
                    # The remote book no longer exists; upload it again.
                    analysis.remote_book_id = ""
                    self.sqlite_session.commit()
            try:
                formats = {
                    str(fmt).lower()
                    for fmt in await self.run_calibre_read_async(self.calibre_db_cache.formats, book_id)
                }
                file_format = "epub" if "epub" in formats else "txt" if "txt" in formats else None
                if not file_format:
                    return {"err": "unsupported_format", "msg": _("需要 EPUB 或 TXT 格式")}
                file_path = await self.run_calibre_async(
                    self.calibre_db.format_abspath, book_id, file_format.upper(), index_is_id=True
                )
                if not file_path or not os.path.isfile(file_path):
                    return {"err": "book_file_missing", "msg": _("所选图书文件不可用")}
                if analysis is None:
                    analysis = MyNexusBookAnalysis(book_id, status="submitting")
                    self.sqlite_session.add(analysis)
                else:
                    analysis.status = "submitting"
                    analysis.error_msg = ""
                self.sqlite_session.commit()
                try:
                    response = await utils.run_in_threadpool(
                        client.upload_book, book_id, file_path
                    )
                except MyNexusError as exc:
                    logging.error(f"[MyNexus] Exception:{exc}")
                    if exc.status_code != 502:
                        raise
                    try:
                        response = await utils.run_in_threadpool(client.analysis_status, book_id)
                    except MyNexusError:
                        raise exc
                _update_analysis(self.sqlite_session, analysis, response)
                if analysis.status in ACTIVE_STATUSES:
                    _ensure_status_poll(book_id, self.settings["ScopedSession"])
                return {"err": "ok", "analysis": _analysis_dict(analysis)}
            except MyNexusError as exc:
                if analysis:
                    _mark_analysis_failed(self.sqlite_session, analysis, exc.message)
                return {"err": "mynexus.error", "msg": exc.message}

    @js
    @is_admin
    async def get(self, raw_id):
        book_id, book = await self._book(raw_id)
        if not book:
            return {"err": "not_found", "msg": _("未找到该图书或无权访问")}
        analysis = self.sqlite_session.get(MyNexusBookAnalysis, book_id)
        if not analysis:
            return {"err": "ok", "analysis": _analysis_dict(None)}
        if analysis.status in ACTIVE_STATUSES:
            try:
                response = await utils.run_in_threadpool(MyNexusClient().analysis_status, book_id)
                _update_analysis(self.sqlite_session, analysis, response)
            except MyNexusError as exc:
                if exc.status_code == 404:
                    _mark_analysis_failed(
                        self.sqlite_session, analysis,
                        "MyNexus has no book matching this MyBooks ID",
                        clear_remote=True,
                    )
                elif exc.status_code != 404:
                    logging.error("MyNexus status lookup for book %s failed: %s", book_id, exc.message)
        return {"err": "ok", "analysis": _analysis_dict(analysis)}


class MyNexusSessionHandler(feature_modules.ModuleGateMixin, BaseHandler):
    module_id = feature_modules.MODULE_AI

    async def _ready_book(self, raw_id):
        try:
            book_id = int(raw_id)
        except (TypeError, ValueError):
            return None
        if not self.current_user or not await self.get_book_async(book_id, raise_exception=False):
            return None
        analysis = self.sqlite_session.get(MyNexusBookAnalysis, book_id)
        if not analysis or analysis.status != "completed" or not analysis.remote_book_id:
            return None
        return book_id, analysis

    @js
    @auth
    async def get(self, raw_id):
        ready = await self._ready_book(raw_id)
        if not ready:
            return {"err": "not_found", "msg": _("AI 助手暂不可用")}
        book_id, analysis = ready
        # Confirm with MyNexus that the book still exists and is ready before
        # opening a session: the local record can be stale when the book was
        # deleted from MyNexus.
        state, error = await _refresh_remote_analysis(self.sqlite_session, analysis, book_id)
        if error:
            return {"err": "mynexus.error", "msg": error.message}
        if state == "missing":
            return {"err": "mynexus.missing", "msg": _("AI解析结果已不存在")}
        if state != "completed":
            return {"err": "mynexus.not_ready", "msg": _("AI解析尚未完成")}
        mapping = self.sqlite_session.get(MyNexusChatSession, (self.current_user.id, book_id))
        if not mapping:
            return {"err": "ok", "session_id": None, "messages": []}
        try:
            client = MyNexusClient()
            detail = await utils.run_in_threadpool(
                client.session_detail, mapping.remote_session_id, self.current_user.id
            )
        except MyNexusError as exc:
            if exc.status_code == 404:
                # The remote chat session was removed; start a new one lazily.
                self.sqlite_session.delete(mapping)
                self.sqlite_session.commit()
                return {"err": "ok", "session_id": None, "messages": []}
            return {"err": "mynexus.error", "msg": exc.message}
        mapping.update_time = datetime.datetime.now()
        self.sqlite_session.commit()
        return {
            "err": "ok",
            "session_id": mapping.remote_session_id,
            "messages": detail.get("messages") or [],
        }

    async def post(self, raw_id):
        if not self.current_user:
            self.set_status(401)
            self.finish({"err": "user.need_login", "msg": _("请先登录")})
            return
        ready = await self._ready_book(raw_id)
        if not ready:
            self.set_status(404)
            self.finish({"err": "not_found", "msg": _("AI 助手暂不可用")})
            return
        book_id, analysis = ready
        try:
            data = tornado.escape.json_decode(self.request.body)
        except (ValueError, TypeError):
            self.set_status(400)
            self.finish({"err": "params.invalid", "msg": _("JSON 请求格式无效")})
            return
        if not isinstance(data, dict):
            self.set_status(400)
            self.finish({"err": "params.invalid", "msg": _("请求内容无效")})
            return
        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            self.set_status(400)
            self.finish({"err": "params.invalid", "msg": _("至少需要一条消息")})
            return
        normalized = []
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in ("user", "assistant") or not isinstance(message.get("content"), str):
                self.set_status(400)
                self.finish({"err": "params.invalid", "msg": _("消息必须包含用户或助手角色及文本内容")})
                return
            normalized.append({"role": message["role"], "content": message["content"]})
            context = _normalize_context(message.get("context"))
            if context:
                normalized[-1]["context"] = context
        if normalized[-1]["role"] != "user":
            self.set_status(400)
            self.finish({"err": "params.invalid", "msg": _("最后一条消息必须来自用户")})
            return
        mapping = self.sqlite_session.get(MyNexusChatSession, (self.current_user.id, book_id))
        reader_id = self.current_user.id
        payload = {
            "session_id": mapping.remote_session_id if mapping else "",
            "messages": normalized,
            "book_ids": [analysis.remote_book_id],
            "stream": True,
        }
        sent_context = normalized[-1].get("context") or {}
        sent_reading = sent_context.get("reading") or {}
        sent_selection = sent_context.get("selection") or {}
        logging.info(
            "[MyNexus] chat context book=%s chapter=%s section=%s snippet_len=%d selection_len=%d",
            book_id, sent_reading.get("chapter_title", ""), sent_reading.get("section_index"),
            len(sent_reading.get("snippet", "")), len(sent_selection.get("text", "")),
        )
        try:
            client = MyNexusClient()
        except MyNexusError as exc:
            self.set_status(exc.status_code)
            self.finish({"err": "mynexus.error", "msg": exc.message})
            return

        loop = asyncio.get_running_loop()
        headers_future = loop.create_future()
        chunks = asyncio.Queue()

        def set_headers(value):
            if not headers_future.done():
                headers_future.set_result(value)

        def push_chunk(value):
            chunks.put_nowait(value)

        def stream_request():
            try:
                with requests.post(
                    client.chat_url(),
                    headers=client.chat_headers(reader_id),
                    json=payload,
                    stream=True,
                    timeout=(10, 300),
                ) as response:
                    loop.call_soon_threadsafe(set_headers, {
                        "status": response.status_code,
                        "session_id": response.headers.get("X-Session-Id", ""),
                        "body": response.text[:2000] if not response.ok else "",
                    })
                    if response.ok:
                        for chunk in response.iter_content(chunk_size=1024):
                            if chunk:
                                loop.call_soon_threadsafe(push_chunk, chunk)
            except requests.RequestException as exc:
                logging.error("MyNexus chat stream for book %s failed: %s", book_id, exc)
                message = _("无法连接到 MyNexus 服务，请检查服务状态或网络设置")
                loop.call_soon_threadsafe(set_headers, {"status": 502, "error": message})
                loop.call_soon_threadsafe(push_chunk, {"error": message})
            finally:
                loop.call_soon_threadsafe(push_chunk, None)

        stream_future = loop.run_in_executor(None, stream_request)
        response_info = await headers_future
        status = response_info["status"]
        if status < 200 or status >= 300:
            await stream_future
            self.set_status(status)
            self.set_header("Content-Type", "application/json; charset=utf-8")
            self.finish(json.dumps({
                "err": "mynexus.error",
                "msg": response_info.get("body") or response_info.get("error") or _("MyNexus 会话失败"),
            }))
            return
        remote_session_id = response_info.get("session_id")
        if not remote_session_id:
            await stream_future
            self.set_status(502)
            self.finish({"err": "mynexus.error", "msg": _("MyNexus 未返回会话 ID")})
            return
        if mapping is None:
            mapping = MyNexusChatSession(self.current_user.id, book_id, remote_session_id)
            self.sqlite_session.add(mapping)
        else:
            mapping.remote_session_id = remote_session_id
            mapping.update_time = datetime.datetime.now()
        self.sqlite_session.commit()
        self.set_header("Content-Type", "text/event-stream; charset=utf-8")
        self.set_header("Cache-Control", "no-cache")
        self.set_header("Connection", "keep-alive")
        self.set_header("X-Accel-Buffering", "no")
        self.set_status(200)
        await self.flush()
        while True:
            chunk = await chunks.get()
            if chunk is None:
                break
            if isinstance(chunk, dict):
                logging.error("MyNexus chat stream for book %s interrupted: %s", book_id, chunk["error"])
                self.write("data: %s\n\n" % json.dumps({"error": chunk["error"]}))
                await self.flush()
                continue
            self.write(chunk)
            await self.flush()
        await stream_future
        self.finish()


class MyNexusAvailabilityHandler(MyNexusBookHandler):
    @js
    @auth
    async def get(self, raw_id):
        book_id, book = await self._book(raw_id)
        if not book:
            return {"err": "not_found", "msg": _("没有找到书籍")}
        analysis = self.sqlite_session.get(MyNexusBookAnalysis, book_id)
        # ``verify=1`` asks MyNexus directly, which is used right before
        # opening an AI companion session so a book removed from MyNexus is
        # detected even though the local analysis record still says completed.
        verify = self.get_argument("verify", "0").lower() in ("1", "true", "yes")
        if analysis and (verify or analysis.status in ACTIVE_STATUSES):
            state, error = await _refresh_remote_analysis(self.sqlite_session, analysis, book_id)
            if error:
                if verify:
                    return {"err": "mynexus.error", "msg": error.message}
                logging.error("MyNexus public status lookup for book %s failed: %s", book_id, error.message)
        available = bool(analysis and analysis.status == "completed")
        reason = ""
        if not available:
            if not analysis or not analysis.remote_book_id:
                reason = "missing"
            elif analysis.status == "failed":
                reason = "failed"
            else:
                reason = "not_ready"
        return {
            "err": "ok",
            "available": available,
            "reason": reason,
            "status": analysis.status if analysis else "not_started",
            "reading_guide": analysis.reading_guide if available else "",
        }

    def post(self, raw_id):
        raise web.HTTPError(405)


class MyNexusTestConnectionHandler(feature_modules.ModuleGateMixin, BaseHandler):
    module_id = feature_modules.MODULE_AI

    @js
    @is_admin
    async def post(self):
        try:
            data = tornado.escape.json_decode(self.request.body)
        except (ValueError, TypeError):
            return {"err": "params.invalid", "msg": _("请求内容无效")}
        if not isinstance(data, dict):
            return {"err": "params.invalid", "msg": _("请求内容无效")}
        try:
            client = MyNexusClient(data.get("url"), data.get("token") or None)
            await utils.run_in_threadpool(client.test_connection)
        except MyNexusError as exc:
            logging.error(f"MyNexus test connection failed: {exc}")
            return {"err": "mynexus.error"}
        return {"err": "ok", "msg": _("MyNexus连接成功")}


def routes():
    return [
        (r"/api/admin/mynexus/test", MyNexusTestConnectionHandler),
        (r"/api/book/([0-9]+)/mynexus/analysis", MyNexusBookHandler),
        (r"/api/book/([0-9]+)/mynexus/availability", MyNexusAvailabilityHandler),
        (r"/api/book/([0-9]+)/mynexus/session", MyNexusSessionHandler),
        (r"/api/book/([0-9]+)/mynexus/chat", MyNexusSessionHandler),
    ]
