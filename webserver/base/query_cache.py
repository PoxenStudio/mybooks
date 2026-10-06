import os
import threading
import time


def library_version(backend):
    stamps = []
    for suffix in ("", "-wal"):
        try:
            stamps.append(os.stat(backend.dbpath + suffix).st_mtime_ns)
        except OSError:
            stamps.append(0)
    return tuple(stamps)


class VersionedCache:
    def __init__(self, ttl=0, max_items=256):
        self.ttl = ttl
        self.max_items = max_items
        self._items = {}
        self._lock = threading.Lock()

    def get(self, key, version):
        with self._lock:
            entry = self._items.get(key)
        if entry is None:
            return None
        expire, cached_version, value = entry
        if cached_version != version or (self.ttl and expire < time.time()):
            return None
        return value

    def put(self, key, version, value):
        with self._lock:
            if len(self._items) >= self.max_items:
                self._items.clear()
            self._items[key] = (time.time() + self.ttl, version, value)

    def clear(self):
        with self._lock:
            self._items.clear()
