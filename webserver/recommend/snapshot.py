#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Background-refreshed TTL snapshot shared by the recommendation data sources.
@author: PoxenStudio, 2026
"""

import logging
import threading
import time
from typing import Callable, Generic, Optional, TypeVar

T = TypeVar("T")


class BackgroundSnapshot(Generic[T]):
    """First access and expired TTL trigger a background rebuild; readers get the last snapshot meanwhile."""

    def __init__(self, loader: Callable[[], T], ttl_seconds: float, name: str):
        self.loader = loader
        self.ttl_seconds = ttl_seconds
        self.name = name
        self.version = 0
        self._value: Optional[T] = None
        self._expire_at = 0.0
        self._lock = threading.Lock()
        self._building = False

    def snapshot(self) -> Optional[T]:
        if time.monotonic() >= self._expire_at:
            self._refresh_async()
        return self._value

    def refresh(self) -> T:
        started = time.monotonic()
        value = self.loader()
        self._value = value
        self.version += 1
        self._expire_at = time.monotonic() + self.ttl_seconds
        logging.info("[recommend] %s built in %d ms", self.name, int((time.monotonic() - started) * 1000))
        return value

    def invalidate(self) -> None:
        self._expire_at = 0.0

    def _refresh_async(self) -> None:
        with self._lock:
            if self._building:
                return
            self._building = True
        threading.Thread(target=self._build, name="recommend-" + self.name, daemon=True).start()

    def _build(self) -> None:
        try:
            self.refresh()
        except Exception:
            self._expire_at = time.monotonic() + 60
            logging.exception("[recommend] %s build failed", self.name)
        finally:
            with self._lock:
                self._building = False
