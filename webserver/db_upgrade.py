#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import asyncio
import contextlib
import logging
import threading

import tornado.httpserver
import tornado.ioloop
import tornado.netutil
from tornado import web

STEPS = ("items", "readers", "scanfiles", "readings")
PENDING, RUNNING, DONE, FAILED = "pending", "running", "done", "failed"


class DbUpgradeState:
    lock = threading.Lock()
    running = False
    steps = {name: PENDING for name in STEPS}

    @classmethod
    def begin(cls):
        with cls.lock:
            cls.running = True
            cls.steps = {name: PENDING for name in STEPS}

    @classmethod
    def finish(cls):
        with cls.lock:
            cls.running = False

    @classmethod
    def set_step(cls, name, status):
        with cls.lock:
            cls.steps[name] = status

    @classmethod
    def snapshot(cls):
        with cls.lock:
            steps = [{"name": name, "status": cls.steps.get(name, PENDING)} for name in STEPS]
            current = next((s["name"] for s in steps if s["status"] == RUNNING), "")
            return {"upgrading": cls.running, "current": current, "steps": steps}


@contextlib.contextmanager
def step(name):
    DbUpgradeState.set_step(name, RUNNING)
    try:
        yield
    except Exception:
        DbUpgradeState.set_step(name, FAILED)
        raise
    DbUpgradeState.set_step(name, DONE)


class DbUpgradeStatusHandler(web.RequestHandler):
    def get(self):
        self.set_header("Cache-Control", "no-cache")
        self.write(dict(err="ok", **DbUpgradeState.snapshot()))


class _UpgradingApiHandler(web.RequestHandler):
    def _reply(self, *args):
        self.set_header("Cache-Control", "no-cache")
        self.write(dict(err="db_upgrading", msg="Database upgrading, please do not restart the service", **DbUpgradeState.snapshot()))

    get = post = put = delete = patch = _reply


_FALLBACK_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="5">
<title>MyBooks</title></head><body style="font-family:sans-serif;text-align:center;padding-top:20vh">
<h2>数据库升级中，请不要重启服务，等待任务完成</h2><p>Database upgrading, please do not restart the service.</p>
</body></html>"""


class _UpgradingPageHandler(web.RequestHandler):
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
        logging.warning("[DB-UPGRADE] Failed to bind %s:%s early: %s", host, port, err)
        return None


class UpgradeStatusServer:
    """数据库升级期间用 dup 出的监听 socket 应答进度，停止时只关闭副本，原 socket 留给正式服务。"""

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
            (r"/api/.*", _UpgradingApiHandler),
            (r"/.*", _UpgradingPageHandler),
        ])
        try:
            self._server = tornado.httpserver.HTTPServer(app, xheaders=True)
            self._server.add_sockets([sock.dup() for sock in self.sockets])
        except Exception as err:
            logging.warning("[DB-UPGRADE] Status server failed to start: %s", err)
            self._server = None
            self._ready.set()
            self._loop.close(all_fds=True)
            return
        logging.info("[DB-UPGRADE] Status server started")
        self._ready.set()
        self._loop.start()
        self._loop.close(all_fds=True)

    def start(self):
        self._thread = threading.Thread(target=self._run, name="db-upgrade-status", daemon=True)
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
        logging.info("[DB-UPGRADE] Status server stopped")


def routes():
    return [(r"/api/upgrade/status", DbUpgradeStatusHandler)]
