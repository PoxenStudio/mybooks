#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Background-refreshed TTL snapshot shared by the recommendation data sources.
@author: PoxenStudio, 2026
"""

import logging
import threading
import time
from typing import Callable, Generic, Hashable, Optional, TypeVar

T = TypeVar("T")


class BackgroundSnapshot(Generic[T]):
    """First access and expired TTL trigger a background rebuild; readers get the last snapshot meanwhile.
    With a fingerprint, an expired snapshot is only rebuilt when the fingerprint changed or it is older than max_age."""

    def __init__(
        self,
        loader: Callable[[], T],
        ttl_seconds: float,
        name: str,
        fingerprint: Optional[Callable[[], Hashable]] = None,
        max_age_seconds: float = 86400,
    ):
        self.loader = loader
        self.ttl_seconds = ttl_seconds
        self.name = name
        self.fingerprint = fingerprint
        self.max_age_seconds = max_age_seconds
        self.version = 0
        self._value: Optional[T] = None
        self._expire_at = 0.0
        self._built_at = 0.0
        self._last_fingerprint: Optional[Hashable] = None
        self._force = True
        self._lock = threading.Lock()
        self._building = False

    def snapshot(self) -> Optional[T]:
        if time.monotonic() >= self._expire_at:
            self._refresh_async()
        return self._value

    def refresh(self, force: bool = True) -> T:
        started = time.monotonic()
        fingerprint = self.fingerprint() if self.fingerprint else None
        fresh_enough = started - self._built_at < self.max_age_seconds
        if not force and self._value is not None and fingerprint is not None and fingerprint == self._last_fingerprint and fresh_enough:
            self._expire_at = time.monotonic() + self.ttl_seconds
            return self._value
        value = self.loader()
        self._value = value
        self.version += 1
        self._last_fingerprint = fingerprint
        self._built_at = started
        self._expire_at = time.monotonic() + self.ttl_seconds
        logging.info("[recommend] %s built in %d ms", self.name, int((time.monotonic() - started) * 1000))
        return value

    def invalidate(self) -> None:
        self._force = True
        self._expire_at = 0.0

    def _refresh_async(self) -> None:
        with self._lock:
            if self._building:
                return
            self._building = True
        threading.Thread(target=self._build, name="recommend-" + self.name, daemon=True).start()

    def _build(self) -> None:
        force, self._force = self._force, False
        try:
            self.refresh(force=force)
        except Exception:
            self._force = self._force or force
            self._expire_at = time.monotonic() + 60
            logging.exception("[recommend] %s build failed", self.name)
        finally:
            with self._lock:
                self._building = False
