import io
import logging
import os
import threading
import time

from PIL import Image

DEFAULT_SIZES = ((60, 80), (120, 200), (240, 320), (480, 640))


def nearest_size(width, height, sizes=DEFAULT_SIZES):
    ordered = sorted(sizes, key=lambda s: s[0] * s[1])
    for w, h in ordered:
        if w >= width and h >= height:
            return w, h
    return ordered[-1]


def scale_cover(data, width, height, quality=81):
    im = Image.open(io.BytesIO(data))
    if im.format == "JPEG":
        im.draft("RGB", (width * 2, height * 2))
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        base = Image.new("RGB", im.size, (255, 255, 255))
        base.paste(im, mask=im.getchannel("A"))
        im = base
    elif im.mode != "RGB":
        im = im.convert("RGB")
    im.thumbnail((width, height), Image.BILINEAR, reducing_gap=2.0)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=quality)
    return out.getvalue()


class ThumbCache:
    def __init__(self, root, max_bytes):
        self.root = root
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._size = None
        self._cleaning = False
        self.hits = 0
        self.misses = 0

    def path_for(self, book_id, stamp, width, height):
        return os.path.join(self.root, "thumb", "%dx%d" % (width, height), "%d-%d.jpg" % (book_id, stamp))

    def get(self, path):
        try:
            st = os.stat(path)
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            self.misses += 1
            return None
        self.hits += 1
        if time.time() - st.st_mtime > 3600:
            try:
                os.utime(path)
            except OSError:
                pass
        return data

    def put(self, path, data):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = "%s.%d.tmp" % (path, threading.get_ident())
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except OSError as e:
            logging.warning("thumb cache write failed: %s", e)
            return
        with self._lock:
            if self._size is None:
                self._size = self._scan()
            else:
                self._size += len(data)
            over = self._size > self.max_bytes * 0.9
        if over:
            self.cleanup()

    def remove_book(self, book_id):
        base = os.path.join(self.root, "thumb")
        prefix = "%d-" % book_id
        freed = 0
        try:
            dirs = os.listdir(base)
        except OSError:
            return 0
        for d in dirs:
            folder = os.path.join(base, d)
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            for name in names:
                if not (name.startswith(prefix) and name.endswith((".jpg", ".webp"))):
                    continue
                full = os.path.join(folder, name)
                try:
                    size = os.stat(full).st_size
                    os.remove(full)
                    freed += size
                except OSError:
                    continue
        with self._lock:
            if self._size is not None:
                self._size = max(0, self._size - freed)
        return freed

    def _files(self):
        base = os.path.join(self.root, "thumb")
        for dirpath, _dirs, names in os.walk(base):
            for name in names:
                full = os.path.join(dirpath, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                yield full, st.st_mtime, st.st_size

    def _scan(self):
        return sum(size for _p, _m, size in self._files())

    def cleanup(self):
        with self._lock:
            if self._cleaning:
                return
            self._cleaning = True
        try:
            files = sorted(self._files(), key=lambda f: f[1])
            total = sum(f[2] for f in files)
            target = self.max_bytes * 0.7
            for full, _mtime, size in files:
                if total <= target:
                    break
                try:
                    os.remove(full)
                    total -= size
                except OSError:
                    continue
            with self._lock:
                self._size = total
        finally:
            self._cleaning = False

    def stats(self):
        with self._lock:
            size = self._size
        return {"bytes": size, "max_bytes": self.max_bytes, "hits": self.hits, "misses": self.misses}
