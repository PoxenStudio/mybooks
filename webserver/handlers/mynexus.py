import asyncio
import datetime
import json
import logging
import os
import requests
import tornado.escape
import tornado.web as web

from webserver.handlers.base import BaseHandler, auth, is_admin, js
from webserver.models import MyNexusBookAnalysis, MyNexusChatSession
from webserver.services.book_access_service import BookAccessService
from webserver.services.mynexus_service import MyNexusClient, MyNexusError, safe_json
from webserver import utils


_book_locks = {}
_status_tasks = {}


def _book_lock(book_id):
    return _book_locks.setdefault(book_id, asyncio.Lock())


def _analysis_dict(analysis):
    if not analysis:
        return {
            "status": "not_started",
            "progress": 0,
            "error_msg": "",
            "reading_guide": "",
            "response": {},
        }
    return {
        "status": analysis.status,
        "progress": analysis.progress,
        "error_msg": analysis.error_msg,
        "reading_guide": analysis.reading_guide,
        "can_retry": analysis.status == "failed" and not analysis.remote_book_id,
        "response": safe_json(analysis.response_json),
    }


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


def _mark_analysis_failed(session, analysis, message):
    analysis.status = "failed"
    analysis.error_msg = message
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


def _persist_failure(scoped_session, book_id, message):
    session = scoped_session()
    try:
        analysis = session.get(MyNexusBookAnalysis, book_id)
        if analysis:
            _mark_analysis_failed(session, analysis, message)
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
        if status not in ("pending", "processing", "submitting"):
            return


def _ensure_status_poll(book_id, scoped_session):
    task = _status_tasks.get(book_id)
    if task is None or task.done():
        _status_tasks[book_id] = asyncio.create_task(_poll_analysis(book_id, scoped_session))


class MyNexusBookHandler(BaseHandler):
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

    @js
    @is_admin
    async def post(self, raw_id):
        book_id, book = await self._book(raw_id)
        if not book:
            return {"err": "not_found", "msg": "Book not found or not accessible"}
        async with _book_lock(book_id):
            analysis = self.sqlite_session.get(MyNexusBookAnalysis, book_id)
            if analysis and analysis.status in ("pending", "processing", "completed", "submitting"):
                return {"err": "ok", "analysis": _analysis_dict(analysis)}
            if analysis and analysis.status == "failed" and analysis.remote_book_id:
                return {"err": "analysis.failed", "msg": analysis.error_msg, "analysis": _analysis_dict(analysis)}
            try:
                client = MyNexusClient()
                formats = {
                    str(fmt).lower()
                    for fmt in await self.run_calibre_read_async(self.calibre_db_cache.formats, book_id)
                }
                file_format = "epub" if "epub" in formats else "txt" if "txt" in formats else None
                if not file_format:
                    return {"err": "unsupported_format", "msg": "EPUB or TXT format is required"}
                file_path = await self.run_calibre_async(
                    self.calibre_db.format_abspath, book_id, file_format.upper(), index_is_id=True
                )
                if not file_path or not os.path.isfile(file_path):
                    return {"err": "book_file_missing", "msg": "The selected book file is unavailable"}
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
                    if exc.status_code != 502:
                        raise
                    try:
                        response = await utils.run_in_threadpool(client.analysis_status, book_id)
                    except MyNexusError:
                        raise exc
                _update_analysis(self.sqlite_session, analysis, response)
                if analysis.status in ("pending", "processing", "submitting"):
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
            return {"err": "not_found", "msg": "Book not found or not accessible"}
        analysis = self.sqlite_session.get(MyNexusBookAnalysis, book_id)
        if not analysis:
            return {"err": "ok", "analysis": _analysis_dict(None)}
        if analysis.status in ("pending", "processing", "submitting"):
            try:
                response = await utils.run_in_threadpool(MyNexusClient().analysis_status, book_id)
                _update_analysis(self.sqlite_session, analysis, response)
            except MyNexusError as exc:
                if exc.status_code == 404:
                    _mark_analysis_failed(
                        self.sqlite_session, analysis, "MyNexus has no book matching this MyBooks ID"
                    )
                elif exc.status_code != 404:
                    logging.error("MyNexus status lookup for book %s failed: %s", book_id, exc.message)
        return {"err": "ok", "analysis": _analysis_dict(analysis)}


class MyNexusSessionHandler(BaseHandler):
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
            return {"err": "not_found", "msg": "AI companion is unavailable"}
        book_id, _ = ready
        mapping = self.sqlite_session.get(MyNexusChatSession, (self.current_user.id, book_id))
        if not mapping:
            return {"err": "ok", "session_id": None, "messages": []}
        try:
            client = MyNexusClient()
            detail = await utils.run_in_threadpool(
                client.session_detail, mapping.remote_session_id, self.current_user.id
            )
        except MyNexusError as exc:
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
            self.finish({"err": "user.need_login", "msg": "Please sign in"})
            return
        ready = await self._ready_book(raw_id)
        if not ready:
            self.set_status(404)
            self.finish({"err": "not_found", "msg": "AI companion is unavailable"})
            return
        book_id, analysis = ready
        try:
            data = tornado.escape.json_decode(self.request.body)
        except (ValueError, TypeError):
            self.set_status(400)
            self.finish({"err": "params.invalid", "msg": "Invalid JSON request"})
            return
        if not isinstance(data, dict):
            self.set_status(400)
            self.finish({"err": "params.invalid", "msg": "Invalid request body"})
            return
        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            self.set_status(400)
            self.finish({"err": "params.invalid", "msg": "At least one message is required"})
            return
        normalized = []
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in ("user", "assistant") or not isinstance(message.get("content"), str):
                self.set_status(400)
                self.finish({"err": "params.invalid", "msg": "Messages must contain user or assistant text"})
                return
            normalized.append({"role": message["role"], "content": message["content"]})
        if normalized[-1]["role"] != "user":
            self.set_status(400)
            self.finish({"err": "params.invalid", "msg": "The last message must be from the user"})
            return
        mapping = self.sqlite_session.get(MyNexusChatSession, (self.current_user.id, book_id))
        reader_id = self.current_user.id
        payload = {
            "session_id": mapping.remote_session_id if mapping else "",
            "messages": normalized,
            "book_ids": [analysis.remote_book_id],
            "stream": True,
        }
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
                loop.call_soon_threadsafe(set_headers, {"status": 502, "error": str(exc)})
                loop.call_soon_threadsafe(push_chunk, {"error": str(exc)})
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
                "msg": response_info.get("body") or response_info.get("error") or "MyNexus chat request failed",
            }))
            return
        remote_session_id = response_info.get("session_id")
        if not remote_session_id:
            await stream_future
            self.set_status(502)
            self.finish({"err": "mynexus.error", "msg": "MyNexus did not return a session ID"})
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
                logging.error("MyNexus chat stream for book %s failed: %s", book_id, chunk["error"])
                self.write("data: %s\n\n" % json.dumps({"error": "MyNexus chat stream was interrupted"}))
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
            return {"err": "not_found", "msg": "Book not found or not accessible"}
        analysis = self.sqlite_session.get(MyNexusBookAnalysis, book_id)
        if analysis and analysis.status in ("pending", "processing", "submitting"):
            try:
                response = await utils.run_in_threadpool(MyNexusClient().analysis_status, book_id)
                _update_analysis(self.sqlite_session, analysis, response)
            except MyNexusError as exc:
                if exc.status_code == 404:
                    _mark_analysis_failed(
                        self.sqlite_session, analysis, "MyNexus has no book matching this MyBooks ID"
                    )
                elif exc.status_code != 404:
                    logging.error("MyNexus public status lookup for book %s failed: %s", book_id, exc.message)
        available = bool(analysis and analysis.status == "completed")
        return {
            "err": "ok",
            "available": available,
            "reading_guide": analysis.reading_guide if available else "",
        }

    def post(self, raw_id):
        raise web.HTTPError(405)


class MyNexusTestConnectionHandler(BaseHandler):
    @js
    @is_admin
    async def post(self):
        try:
            data = tornado.escape.json_decode(self.request.body)
        except (ValueError, TypeError):
            return {"err": "params.invalid", "msg": "Invalid request body"}
        if not isinstance(data, dict):
            return {"err": "params.invalid", "msg": "Invalid request body"}
        try:
            client = MyNexusClient(data.get("url"), data.get("token") or None)
            await utils.run_in_threadpool(client.test_connection)
        except MyNexusError as exc:
            return {"err": "mynexus.error", "msg": exc.message}
        return {"err": "ok", "msg": "MyNexus connection successful"}


def routes():
    return [
        (r"/api/admin/mynexus/test", MyNexusTestConnectionHandler),
        (r"/api/book/([0-9]+)/mynexus/analysis", MyNexusBookHandler),
        (r"/api/book/([0-9]+)/mynexus/availability", MyNexusAvailabilityHandler),
        (r"/api/book/([0-9]+)/mynexus/session", MyNexusSessionHandler),
        (r"/api/book/([0-9]+)/mynexus/chat", MyNexusSessionHandler),
    ]
