#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import asyncio
import contextlib
import logging
import threading
import time

import tornado.httpserver
import tornado.ioloop
import tornado.netutil
from tornado import web

UPGRADE_STEPS = ("db_items", "db_readers", "db_scanfiles", "db_readings")
PENDING, RUNNING, DONE, FAILED = "pending", "running", "done", "failed"


class StartupState:
    lock = threading.Lock()
    running = False
    steps = {}
    began = {}
    costs = []
    t0 = time.perf_counter()

    @classmethod
    def plan(cls, names):
        with cls.lock:
            cls.running = True
            cls.steps = {name: PENDING for name in names}

    @classmethod
    def _record(cls, name, status):
        cost = (time.perf_counter() - cls.began.pop(name)) * 1000 if name in cls.began else 0
        cls.costs.append((name, cost))
        logging.info("[STARTUP-TIMING] step=%s status=%s cost_ms=%.0f", name, status, cost)

    @classmethod
    def _close_running(cls):
        for name, status in cls.steps.items():
            if status == RUNNING:
                cls.steps[name] = DONE
                cls._record(name, DONE)

    @classmethod
    def enter(cls, name):
        """顺序阶段：结束当前阶段并进入下一个。"""
        with cls.lock:
            cls._close_running()
            cls.steps[name] = RUNNING
            cls.began[name] = time.perf_counter()

    @classmethod
    def set_step(cls, name, status):
        with cls.lock:
            if cls.steps.get(name) == RUNNING or name in cls.began:
                cls._record(name, status)
            cls.steps[name] = status

    @classmethod
    def finish(cls):
        with cls.lock:
            cls._close_running()
            cls.running = False
            total = (time.perf_counter() - cls.t0) * 1000
            detail = " ".join("%s=%.0f" % item for item in cls.costs)
            logging.info("[STARTUP-TIMING] total_ms=%.0f %s", total, detail)

    @classmethod
    def snapshot(cls):
        with cls.lock:
            steps = [{"name": name, "status": status} for name, status in cls.steps.items()]
            current = next((s["name"] for s in steps if s["status"] == RUNNING), "")
            return {"starting": cls.running, "upgrading": current in UPGRADE_STEPS, "current": current, "steps": steps}


@contextlib.contextmanager
def substep(name):
    start = time.perf_counter()
    try:
        yield
    finally:
        logging.info("[STARTUP-TIMING] sub=%s cost_ms=%.0f", name, (time.perf_counter() - start) * 1000)


@contextlib.contextmanager
def upgrade_step(name):
    StartupState.enter(name)
    try:
        yield
    except Exception:
        StartupState.set_step(name, FAILED)
        raise
    StartupState.set_step(name, DONE)


class StartupStatusHandler(web.RequestHandler):
    def get(self):
        self.set_header("Cache-Control", "no-cache")
        self.write(dict(err="ok", **StartupState.snapshot()))


class _StartingApiHandler(web.RequestHandler):
    def _reply(self, *args):
        self.set_header("Cache-Control", "no-cache")
        self.write(dict(err="server_starting", msg="Service is starting, please wait", **StartupState.snapshot()))

    get = post = put = delete = patch = _reply


_FALLBACK_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="5">
<title>MyBooks</title></head><body style="font-family:sans-serif;text-align:center;padding-top:20vh">
<h2>系统启动中，请稍候；数据库升级期间请不要重启服务</h2><p>Service is starting, please wait. Do not restart during database upgrade.</p>
</body></html>"""


class _StartingPageHandler(web.RequestHandler):
    def _reply(self, *args):
        self.set_status(503)
        self.set_header("Retry-After", "5")
        self.set_header("Cache-Control", "no-cache")
        self.write(_FALLBACK_PAGE)

    get = post = put = delete = patch = _reply


def bind_service_sockets(port, host=""):
    """提前绑定服务端口；临时服务与正式服务共用这组监听 socket，交接期间新连接在内核队列排队。"""
    try:
        return tornado.netutil.bind_sockets(port, address=host or None)
    except Exception as err:
        logging.warning("[STARTUP] Failed to bind %s:%s early: %s", host, port, err)
        return None


class StartupStatusServer:
    """启动期间用 dup 出的监听 socket 应答进度，停止时只关闭副本，原 socket 留给正式服务。"""

    def __init__(self, sockets):
        self.sockets = sockets
        self._loop = None
        self._server = None
        self._thread = None
        self._ready = threading.Event()

    def _run(self):
        asyncio.set_event_loop(asyncio.new_event_loop())
        self._loop = tornado.ioloop.IOLoop.current()
        app = web.Application([
            (r"/api/.*", _StartingApiHandler),
            (r"/.*", _StartingPageHandler),
        ])
        try:
            self._server = tornado.httpserver.HTTPServer(app, xheaders=True)
            self._server.add_sockets([sock.dup() for sock in self.sockets])
        except Exception as err:
            logging.warning("[STARTUP] Status server failed to start: %s", err)
            self._server = None
            self._ready.set()
            self._loop.close(all_fds=True)
            return
        logging.info("[STARTUP] Status server started")
        self._ready.set()
        self._loop.start()
        self._loop.close(all_fds=True)

    def start(self):
        self._thread = threading.Thread(target=self._run, name="startup-status", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def stop(self):
        if not self._thread:
            return
        if self._server and self._loop:
            def _shutdown():
                self._server.stop()
                self._loop.stop()
            self._loop.add_callback(_shutdown)
        self._thread.join(10)
        self._thread = None
        logging.info("[STARTUP] Status server stopped")


def routes():
    return [(r"/api/startup/status", StartupStatusHandler)]
