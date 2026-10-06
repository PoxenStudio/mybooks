#!/usr/bin/env python3

import asyncio
import io
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from PIL import Image
from tornado import web

from webserver.base import accel
from webserver.base.thumbnail import ThumbCache, nearest_size, scale_cover
from webserver.handlers import static_files
from webserver.handlers.book import BookDownload
from webserver.handlers.static_files import ImageHandler


def jpeg(width, height, mode="RGB"):
    out = io.BytesIO()
    Image.new(mode, (width, height), "red").save(out, "JPEG")
    return out.getvalue()


class TestScale(unittest.TestCase):

    def test_nearest_size(self):
        self.assertEqual(nearest_size(240, 320), (240, 320))
        self.assertEqual(nearest_size(100, 150), (120, 200))
        self.assertEqual(nearest_size(1000, 1000), (480, 640))
        self.assertEqual(nearest_size(10, 10), (60, 80))

    def test_scale_down_keeps_aspect(self):
        im = Image.open(io.BytesIO(scale_cover(jpeg(1600, 2400), 240, 320)))
        self.assertLessEqual(im.width, 240)
        self.assertLessEqual(im.height, 320)
        self.assertAlmostEqual(im.width / im.height, 1600 / 2400, delta=0.02)

    def test_small_image_not_upscaled(self):
        im = Image.open(io.BytesIO(scale_cover(jpeg(50, 60), 240, 320)))
        self.assertEqual(im.size, (50, 60))

    def test_png_with_alpha_composited_on_white(self):
        out = io.BytesIO()
        Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(out, "PNG")
        im = Image.open(io.BytesIO(scale_cover(out.getvalue(), 60, 80)))
        self.assertEqual(im.mode, "RGB")
        self.assertGreater(min(im.getpixel((5, 5))), 240)


class TestThumbCache(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_put_get(self):
        cache = ThumbCache(self.tmp.name, 10 ** 6)
        path = cache.path_for(1, 123, 240, 320)
        self.assertIsNone(cache.get(path))
        cache.put(path, b"x" * 10)
        self.assertEqual(cache.get(path), b"x" * 10)
        self.assertEqual((cache.hits, cache.misses), (1, 1))

    def test_remove_book(self):
        cache = ThumbCache(self.tmp.name, 10 ** 6)
        mine = [cache.path_for(1, 5, 60, 80), cache.path_for(1, 5, 240, 320)]
        other = [cache.path_for(11, 5, 60, 80), cache.path_for(2, 5, 60, 80)]
        for path in mine + other:
            cache.put(path, b"x" * 10)
        self.assertEqual(cache.remove_book(1), 20)
        self.assertFalse(any(os.path.exists(p) for p in mine))
        self.assertTrue(all(os.path.exists(p) for p in other))
        self.assertEqual(cache._size, 20)
        self.assertEqual(ThumbCache(os.path.join(self.tmp.name, "none"), 1).remove_book(1), 0)

    def test_eviction_removes_oldest(self):
        cache = ThumbCache(self.tmp.name, 1000)
        paths = []
        for i in range(10):
            path = cache.path_for(i, 1, 60, 80)
            cache.put(path, b"x" * 100)
            os.utime(path, (time.time() - 1000 + i, time.time() - 1000 + i))
            paths.append(path)
        cache.put(cache.path_for(99, 1, 60, 80), b"x" * 100)
        self.assertFalse(os.path.exists(paths[0]))
        self.assertTrue(os.path.exists(cache.path_for(99, 1, 60, 80)))
        self.assertLessEqual(cache._scan(), 1000)

    def test_tmp_files_not_left(self):
        cache = ThumbCache(self.tmp.name, 10 ** 6)
        path = cache.path_for(1, 1, 60, 80)
        cache.put(path, b"abc")
        self.assertEqual(os.listdir(os.path.dirname(path)), [os.path.basename(path)])


class TestAccel(unittest.TestCase):

    def test_uri_for(self):
        self.assertEqual(accel.uri_for("/_lib/", "/data/lib", "/data/lib/a b/中 (1)/cover.jpg"), "/_lib/a%20b/%E4%B8%AD%20%281%29/cover.jpg")
        self.assertIsNone(accel.uri_for("/_lib/", "/data/lib", "/etc/passwd"))
        self.assertIsNone(accel.uri_for("/_lib/", "/data/lib", "/data/lib/../x"))

    def test_enabled_needs_header_and_setting(self):
        handler = mock.Mock()
        handler.request.headers = {"X-Accel-Support": "1"}
        self.assertTrue(accel.enabled(handler))
        handler.request.headers = {}
        self.assertFalse(accel.enabled(handler))
        handler.request.headers = {"X-Accel-Support": "1"}
        with mock.patch.dict(accel.CONF, {"USE_X_ACCEL": False}):
            self.assertFalse(accel.enabled(handler))


class ImageTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lib = os.path.join(self.tmp.name, "lib")
        self.cache_dir = os.path.join(self.tmp.name, "cache")
        os.makedirs(os.path.join(self.lib, "a", "b (1)"))
        self.cover = os.path.join(self.lib, "a", "b (1)", "cover.jpg")
        with open(self.cover, "wb") as f:
            f.write(jpeg(800, 1200))
        ImageHandler._cover_paths.clear()
        ImageHandler._thumb_inflight.clear()
        ImageHandler._thumb_cache = None
        patcher = mock.patch.dict(static_files.CONF, {"CACHE_DIR": self.cache_dir, "THUMB_CACHE": True, "CACHE_MAX_MB": 10})
        patcher.start()
        self.addCleanup(patcher.stop)

    def handler(self, accel_header=False):
        handler = object.__new__(ImageHandler)
        handler.request = mock.Mock()
        handler.request.headers = {"X-Accel-Support": "1"} if accel_header else {}
        handler.calibre_db_cache = mock.Mock()
        handler.calibre_db_cache.backend.library_path = self.lib
        handler.calibre_db_cache.field_for.return_value = "a/b (1)"
        handler.calibre_db = mock.Mock()
        handler.calibre_db.has_id.return_value = True
        handler.default_cover = b"default"
        handler.db_lock = threading.RLock()
        handler.build_time = __import__("datetime").datetime(2020, 1, 1)
        handler._headers = {}
        handler.set_header = lambda k, v: handler._headers.__setitem__(k, v)
        handler.check_etag_header = lambda: False
        handler.set_status = mock.Mock()
        return handler

    def fetch(self, handler, fmt, id=1):
        return asyncio.run(handler.get_data_async(fmt, id))


class TestImageHandler(ImageTestCase):

    def test_cover_original_direct_read(self):
        handler = self.handler()
        data = self.fetch(handler, "cover")
        self.assertEqual(data, open(self.cover, "rb").read())
        self.assertIn("Etag", handler._headers)

    def test_cover_original_accel(self):
        handler = self.handler(accel_header=True)
        self.assertIsNone(self.fetch(handler, "cover"))
        self.assertEqual(handler._headers["X-Accel-Redirect"], "/_lib/a/b%20%281%29/cover.jpg")

    def test_cover_304(self):
        handler = self.handler()
        handler.check_etag_header = lambda: True
        self.assertIsNone(self.fetch(handler, "cover"))
        handler.set_status.assert_called_with(304)

    def test_thumbnail_miss_then_hit_then_accel(self):
        handler = self.handler()
        first = self.fetch(handler, "thumb_240_320")
        im = Image.open(io.BytesIO(first))
        self.assertLessEqual(im.height, 320)
        cache = ImageHandler.thumb_cache()
        self.assertEqual(cache.misses, 1)
        with mock.patch.object(ImageHandler, "_make_thumbnail", side_effect=AssertionError("must hit cache")):
            self.assertEqual(self.fetch(self.handler(), "thumb_240_320"), first)
            accel_handler = self.handler(accel_header=True)
            self.assertIsNone(self.fetch(accel_handler, "thumb_240_320"))
        self.assertTrue(accel_handler._headers["X-Accel-Redirect"].startswith("/_cache/thumb/240x320/1-"))

    def test_unlisted_size_maps_to_whitelist(self):
        self.fetch(self.handler(), "thumb_100_150")
        self.assertTrue(os.path.isdir(os.path.join(self.cache_dir, "thumb", "120x200")))

    def test_cover_mtime_change_invalidates(self):
        handler = self.handler()
        self.fetch(handler, "thumb_240_320")
        os.utime(self.cover, ns=(1, 1))
        with open(self.cover, "wb") as f:
            f.write(jpeg(400, 600))
        self.fetch(self.handler(), "thumb_240_320")
        self.assertEqual(len(os.listdir(os.path.join(self.cache_dir, "thumb", "240x320"))), 2)

    def test_single_flight(self):
        calls = []

        def slow(path, width, height, quality, use_pillow):
            calls.append(1)
            time.sleep(0.05)
            return b"jpegdata"

        async def main():
            handlers = [self.handler() for _ in range(5)]
            return await asyncio.gather(*(h.get_data_async("thumb_240_320", 1) for h in handlers))

        with mock.patch.object(ImageHandler, "_make_thumbnail", staticmethod(slow)):
            results = asyncio.run(main())
        self.assertEqual(calls, [1])
        self.assertEqual(set(results), {b"jpegdata"})

    def test_no_cover_serves_default(self):
        os.remove(self.cover)
        handler = self.handler()
        self.assertEqual(self.fetch(handler, "thumb_240_320"), b"default")

    def test_unknown_book_404(self):
        handler = self.handler()
        handler.calibre_db.has_id.return_value = False
        with self.assertRaises(web.HTTPError):
            self.fetch(handler, "cover", 999)

    def test_cache_disabled(self):
        with mock.patch.dict(static_files.CONF, {"THUMB_CACHE": False}):
            handler = self.handler()
            self.assertTrue(self.fetch(handler, "thumb_240_320"))
        self.assertFalse(os.path.exists(os.path.join(self.cache_dir, "thumb")))

    def test_path_refreshed_after_rename(self):
        handler = self.handler()
        self.fetch(handler, "cover")
        os.rename(os.path.join(self.lib, "a", "b (1)"), os.path.join(self.lib, "a", "c (1)"))
        handler.calibre_db_cache.field_for.return_value = "a/c (1)"
        self.assertTrue(self.fetch(self.handler(), "cover"))


class TestLiteImages(ImageTestCase):

    def lite_conf(self, **extra):
        conf = {"PERFORMANCE_MODE": "lite"}
        conf.update(extra)
        return mock.patch.dict(static_files.perf.CONF, conf)

    def test_lite_maps_to_two_sizes(self):
        with self.lite_conf():
            self.fetch(self.handler(), "thumb_150_200")
            self.fetch(self.handler(), "thumb_60_80")
        sizes = sorted(os.listdir(os.path.join(self.cache_dir, "thumb")))
        self.assertEqual(sizes, ["120x200", "240x320"])

    def test_lite_uses_lower_jpeg_quality(self):
        seen = []

        def spy(path, width, height, quality, use_pillow):
            seen.append(quality)
            return b"jpeg"

        with self.lite_conf(), mock.patch.object(ImageHandler, "_make_thumbnail", staticmethod(spy)):
            self.fetch(self.handler(), "thumb_240_320")
        self.assertEqual(seen, [70])

    def test_lite_skips_dynamic_cover(self):
        os.remove(self.cover)
        handler = self.handler()
        with self.lite_conf(USE_DYNAMIC_COVER=True), mock.patch.dict(static_files.CONF, {"USE_DYNAMIC_COVER": True}), \
                mock.patch.object(static_files.ImageGenerator, "generate_cover", return_value=b"dyn") as generate:
            self.assertEqual(self.fetch(handler, "thumb_240_320"), b"default")
        generate.assert_not_called()

    def test_normal_still_generates_dynamic_cover(self):
        os.remove(self.cover)
        handler = self.handler()
        handler.calibre_db.get_metadata.return_value = mock.Mock(authors=["a"], title="t")
        with mock.patch.dict(static_files.CONF, {"USE_DYNAMIC_COVER": True}), \
                mock.patch.object(static_files.ImageGenerator, "generate_cover", return_value=b"dyn"):
            self.assertEqual(self.fetch(handler, "thumb_240_320"), b"dyn")


class TestDownloadAccel(unittest.TestCase):

    def make(self, accel_header, path):
        handler = object.__new__(BookDownload)
        handler.request = mock.Mock()
        handler.request.headers = {"X-Accel-Support": "1"} if accel_header else {}
        handler.calibre_db_cache = mock.Mock()
        handler.calibre_db_cache.backend.library_path = os.path.dirname(os.path.dirname(path))
        handler._headers = {}
        handler.set_header = lambda k, v: handler._headers.__setitem__(k, v)
        handler.parse_url_path = lambda p: path
        return handler

    def test_accel_redirect_for_library_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            book_dir = os.path.join(tmp, "a", "b")
            os.makedirs(book_dir)
            path = os.path.join(book_dir, "f.epub")
            open(path, "w").close()
            handler = self.make(True, path)
            asyncio.run(handler.get("1.epub"))
            self.assertEqual(handler._headers["X-Accel-Redirect"], "/_lib/b/f.epub")

    def test_falls_back_without_header(self):
        handler = self.make(False, "/x/y/z.epub")
        with mock.patch.object(web.StaticFileHandler, "get", new=mock.AsyncMock(return_value="fallback")) as parent:
            self.assertEqual(asyncio.run(handler.get("1.epub")), "fallback")
        parent.assert_called_once()
        self.assertNotIn("X-Accel-Redirect", handler._headers)


if __name__ == "__main__":
    unittest.main()
