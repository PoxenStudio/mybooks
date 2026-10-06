import collections
import threading


def clone_row(row):
    out = dict(row)
    for key, value in out.items():
        if isinstance(value, list):
            out[key] = list(value)
        elif isinstance(value, dict):
            out[key] = dict(value)
        elif isinstance(value, set):
            out[key] = set(value)
    return out


def estimate_size(row):
    size = 1024
    for value in row.values():
        if isinstance(value, str):
            size += len(value)
        elif isinstance(value, (list, tuple)):
            size += 64 * len(value) + sum(len(v) for v in value if isinstance(v, str))
        elif isinstance(value, dict):
            size += 96 * len(value)
        else:
            size += 32
    return size


class BookRowCache:
    def __init__(self):
        self._items = collections.OrderedDict()
        self._lock = threading.Lock()
        self._bytes = 0
        self.hits = 0
        self.misses = 0

    def get(self, key):
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                self.misses += 1
                return None
            self._items.move_to_end(key)
            self.hits += 1
            row = entry[0]
        return clone_row(row)

    def put(self, key, row, max_items, max_bytes):
        stored = clone_row(row)
        size = estimate_size(stored)
        if size > max_bytes:
            return
        with self._lock:
            old = self._items.pop(key, None)
            if old is not None:
                self._bytes -= old[1]
            self._items[key] = (stored, size)
            self._bytes += size
            while self._items and (len(self._items) > max_items or self._bytes > max_bytes):
                _key, (_row, dropped) = self._items.popitem(last=False)
                self._bytes -= dropped

    def clear(self):
        with self._lock:
            self._items.clear()
            self._bytes = 0

    def stats(self):
        with self._lock:
            return {"entries": len(self._items), "bytes": self._bytes, "hits": self.hits, "misses": self.misses}
