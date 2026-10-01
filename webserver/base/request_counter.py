#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
请求次数统计工具，用于限制对外部信息源的访问频率

调用者给出每小时最大请求次数，内部换算成 1~5 分钟的固定窗口，让请求均匀分布而不是在小时内集中爆发：
优先取能让 max_per_hour * 窗口分钟数 / 60 恰好整除的最短窗口（180/小时 -> 每分钟 3 次）；
1~5 分钟都除不尽时用 5 分钟窗口，窗口内上限向下取整（至少 1 次）。
为容纳短时间内的少量突发，每个窗口最多放行 2 倍上限；一旦用到了超出部分，紧接着的下一个窗口整体拒绝请求。
"""
import threading
import time

MAX_WINDOW_MINUTES = 5


def _plan_window(max_per_hour):
    for minutes in range(1, MAX_WINDOW_MINUTES + 1):
        if (max_per_hour * minutes) % 60 == 0:
            return minutes, max_per_hour * minutes // 60
    return MAX_WINDOW_MINUTES, max(1, max_per_hour * MAX_WINDOW_MINUTES // 60)


class RequestCounter:

    def __init__(self, max_per_hour):
        self.max_per_hour = max_per_hour
        minutes, self.limit = _plan_window(max_per_hour)
        self.window_seconds = minutes * 60
        self._start = time.monotonic()
        self._count = 0
        self._blocked = False
        self._lock = threading.Lock()

    def _roll(self, now):
        windows = int((now - self._start) // self.window_seconds)
        if windows < 1:
            return
        self._blocked = windows == 1 and not self._blocked and self._count > self.limit
        self._start += windows * self.window_seconds
        self._count = 0

    def record(self):
        with self._lock:
            self._roll(time.monotonic())
            self._count += 1

    def is_exceeded(self):
        with self._lock:
            self._roll(time.monotonic())
            return self._blocked or self._count >= self.limit * 2
