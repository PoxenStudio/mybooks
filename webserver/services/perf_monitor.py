#!/usr/bin/env python3
import collections
import logging
import os
import re
import sys
import threading
import time
import traceback

import tornado.ioloop

HEARTBEAT_MS = 100
WATCHDOG_INTERVAL_S = 0.2
DEFAULT_STALL_MS = 500
MAX_STALLS = 50
MAX_SAMPLES = 300
MAX_ROUTES = 300
_ID_RE = re.compile(r"\d+")


def _percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * pct))]


def _summary(samples):
    values = list(samples)
    return {
        "count": len(values),
        "p50": round(_percentile(values, 0.5), 1),
        "p95": round(_percentile(values, 0.95), 1),
        "max": round(max(values), 1) if values else 0.0,
    }


class PerfMonitor:
    """ioloop 滞后看门狗 + 分路由耗时 + calibre 池排队统计，用于定位全站卡顿的元凶。

    心跳由 ioloop 周期回调刷新；看门狗线程发现心跳停滞超过阈值时，抓取主线程当前
    调用栈——栈顶即正在占住 ioloop 的同步代码。
    """

    _instance = None

    def __init__(self, stall_ms=DEFAULT_STALL_MS):
        self.stall_ms = stall_ms
        self._lock = threading.Lock()
        self._heartbeat = time.monotonic()
        self._expected = None
        self._main_ident = None
        self._stalls = collections.deque(maxlen=MAX_STALLS)
        self._stall_total = 0
        self._lag_samples = collections.deque(maxlen=MAX_SAMPLES * 4)
        self._routes = {}
        self._calibre = {}
        self._started_at = time.time()
        self._callback = None
        self._watchdog = None
        self._running = False

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self, stall_ms=None):
        if self._running:
            return
        if stall_ms:
            self.stall_ms = stall_ms
        self._running = True
        self._main_ident = threading.get_ident()
        self._heartbeat = time.monotonic()
        self._expected = self._heartbeat + HEARTBEAT_MS / 1000.0
        self._callback = tornado.ioloop.PeriodicCallback(self._beat, HEARTBEAT_MS)
        self._callback.start()
        self._watchdog = threading.Thread(target=self._watch, name="PerfMonitor.watchdog", daemon=True)
        self._watchdog.start()
        logging.info("[perf] monitor started, stall threshold=%dms", self.stall_ms)

    def _beat(self):
        now = time.monotonic()
        lag_ms = max(0.0, (now - self._expected) * 1000.0)
        self._lag_samples.append(lag_ms)
        self._heartbeat = now
        self._expected = now + HEARTBEAT_MS / 1000.0

    def _watch(self):
        reported_for = None
        while self._running:
            time.sleep(WATCHDOG_INTERVAL_S)
            beat = self._heartbeat
            stalled_ms = (time.monotonic() - beat) * 1000.0
            if stalled_ms < self.stall_ms:
                reported_for = None
                continue
            if reported_for == beat:
                continue
            reported_for = beat
            frame = sys._current_frames().get(self._main_ident)
            stack = "".join(traceback.format_stack(frame, limit=12)) if frame else ""
            self._record_stall(stalled_ms, stack)

    def _record_stall(self, stalled_ms, stack):
        entry = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "stalled_ms": round(stalled_ms),
            "stack": stack,
        }
        with self._lock:
            self._stalls.append(entry)
            self._stall_total += 1
        logging.warning("[perf] ioloop stalled >= %dms, main thread stack:\n%s", stalled_ms, stack)

    def record_request(self, method, path, cost_ms):
        key = "%s %s" % (method, _ID_RE.sub("N", path))
        with self._lock:
            samples = self._routes.get(key)
            if samples is None:
                if len(self._routes) >= MAX_ROUTES:
                    return
                samples = self._routes[key] = collections.deque(maxlen=MAX_SAMPLES)
            samples.append(cost_ms)

    def record_calibre(self, name, wait_ms, run_ms):
        with self._lock:
            entry = self._calibre.get(name)
            if entry is None:
                entry = self._calibre[name] = {
                    "wait": collections.deque(maxlen=MAX_SAMPLES),
                    "run": collections.deque(maxlen=MAX_SAMPLES),
                }
            entry["wait"].append(wait_ms)
            entry["run"].append(run_ms)
        if wait_ms > 1000:
            logging.warning("[perf] calibre call %s waited %.0fms for pool/db_lock (run %.0fms)", name, wait_ms, run_ms)

    def snapshot(self):
        with self._lock:
            routes = {k: _summary(v) for k, v in self._routes.items()}
            calibre = {k: {"wait": _summary(v["wait"]), "run": _summary(v["run"])} for k, v in self._calibre.items()}
            stalls = list(self._stalls)
            stall_total = self._stall_total
        slowest = sorted(routes.items(), key=lambda kv: kv[1]["p95"] * kv[1]["count"], reverse=True)
        return {
            "running": self._running,
            "uptime_s": round(time.time() - self._started_at),
            "stall_threshold_ms": self.stall_ms,
            "loop_lag_ms": _summary(self._lag_samples),
            "stall_total": stall_total,
            "stalls": stalls[-20:],
            "calibre": calibre,
            "routes": dict(slowest[:40]),
            "system": self._system(),
        }

    @staticmethod
    def _system():
        info = {"threads": threading.active_count(), "cpu_count": os.cpu_count()}
        try:
            info["loadavg"] = [round(x, 2) for x in os.getloadavg()]
        except OSError:
            pass
        try:
            import resource

            usage = resource.getrusage(resource.RUSAGE_SELF)
            info["cpu_user_s"] = round(usage.ru_utime, 1)
            info["cpu_sys_s"] = round(usage.ru_stime, 1)
            info["max_rss_kb"] = usage.ru_maxrss
        except ImportError:
            pass
        return info

    def reset(self):
        with self._lock:
            self._stalls.clear()
            self._stall_total = 0
            self._routes.clear()
            self._calibre.clear()
        self._lag_samples.clear()
