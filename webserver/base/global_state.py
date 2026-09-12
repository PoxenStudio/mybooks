#!/usr/bin/env python3

"""
进程内全局状态
"""

import threading


class GlobalState:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(GlobalState, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._state_lock = threading.Lock()
            self.cdn_url = ""
            self.api_url = ""
            self._initialized = True

    def update(self, **kwargs):
        """批量更新，未知 key 一律忽略（避免笔误悄悄新建属性）。"""
        with self._state_lock:
            for key, value in kwargs.items():
                if hasattr(self, key):
                    setattr(self, key, value)


# 全局实例
_global_state = GlobalState()


def get_global_state() -> GlobalState:
    return _global_state
