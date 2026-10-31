#!/usr/bin/env python3

import asyncio
import io
import os
import shutil
import tempfile
import unittest
from unittest import mock

from PIL import Image
from tornado import web

from webserver.base import cover_background as cover_background_module
from webserver.base.cover_background import CoverBackgroundError, CoverBackgroundService
from webserver.base.image_generator import ImageGenerator
from webserver.handlers.cover_background import CoverBackgroundFile, CoverBackgroundPreview

FONT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "public", "static", "epubreader", "assets", "font", "HuiwenZhengKai.ttf",
)


def make_image(width, height, fmt="JPEG", mode="RGB", color=(30, 110, 170)):
    buffer = io.BytesIO()
    Image.new(mode, (width, height), color).save(buffer, fmt)
    return buffer.getvalue()


class CoverBackgroundServiceTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="coverbg-")
        self.patches = [
            mock.patch.object(cover_background_module, "COVER_BACKGROUND_DIR", self.tmpdir),
            mock.patch.dict(cover_background_module.CONF, {"USE_COVER_BACKGROUND": True}),
        ]
        for patch in self.patches:
            patch.start()
        CoverBackgroundService.invalidate_cache()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        CoverBackgroundService.invalidate_cache()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def save(self, body):
        return CoverBackgroundService.save({"body": body})

    def test_empty_library_returns_none(self):
        self.assertIsNone(CoverBackgroundService.pick_for("测试书名"))
        self.assertEqual(CoverBackgroundService.count(), 0)

    def test_save_normalizes_to_portrait_ratio(self):
        name = self.save(make_image(2000, 800))
        self.assertTrue(CoverBackgroundService.is_valid_name(name))
        with Image.open(os.path.join(self.tmpdir, name)) as image:
            self.assertEqual(image.size, (1200, 1600))
            self.assertEqual(image.format, "JPEG")

    def test_save_is_idempotent_for_same_content(self):
        body = make_image(800, 1200)
        self.assertEqual(self.save(body), self.save(body))
        self.assertEqual(CoverBackgroundService.count(), 1)

    def test_pick_is_stable_per_seed(self):
        self.save(make_image(1200, 1600, color=(200, 20, 20)))
        self.save(make_image(1200, 1600, color=(20, 200, 20)))
        first = CoverBackgroundService.pick_for("同名书")
        for _ in range(5):
            self.assertEqual(first, CoverBackgroundService.pick_for("同名书"))
        self.assertTrue(os.path.exists(first))

    def test_pick_respects_switch(self):
        self.save(make_image(1200, 1600))
        with mock.patch.dict(cover_background_module.CONF, {"USE_COVER_BACKGROUND": False}):
            self.assertIsNone(CoverBackgroundService.pick_for("任意书名"))

    def test_reject_non_image_payload(self):
        with self.assertRaises(CoverBackgroundError):
            self.save(b"not an image at all")

    def test_reject_oversized_payload(self):
        body = b"\x00" * (cover_background_module.MAX_UPLOAD_BYTES + 1)
        with self.assertRaises(CoverBackgroundError):
            self.save(body)

    def test_reject_unsupported_format(self):
        for image_format in ("TIFF", "GIF", "BMP"):
            with self.assertRaises(CoverBackgroundError):
                self.save(make_image(200, 200, fmt=image_format))

    def test_reject_huge_dimensions(self):
        with mock.patch.object(cover_background_module, "MAX_PIXELS", 100):
            with self.assertRaises(CoverBackgroundError):
                self.save(make_image(200, 200))

    def test_exif_orientation_is_applied(self):
        source = Image.new("RGB", (2000, 1000), (255, 0, 0))
        source.paste((0, 0, 255), (1000, 0, 2000, 1000))
        exif = source.getexif()
        exif[274] = 6
        buffer = io.BytesIO()
        source.save(buffer, "JPEG", exif=exif)

        name = self.save(buffer.getvalue())
        with Image.open(os.path.join(self.tmpdir, name)) as image:
            top = image.getpixel((600, 100))
            bottom = image.getpixel((600, 1500))
        self.assertGreater(top[0], 150)
        self.assertLess(top[2], 100)
        self.assertGreater(bottom[2], 150)
        self.assertLess(bottom[0], 100)

    def test_reject_when_gallery_is_full(self):
        with mock.patch.object(cover_background_module, "MAX_BACKGROUNDS", 1):
            self.save(make_image(1200, 1600, color=(1, 2, 3)))
            with self.assertRaises(CoverBackgroundError):
                self.save(make_image(1200, 1600, color=(4, 5, 6)))

    def test_transparent_png_gets_white_underlay(self):
        name = self.save(make_image(1200, 1600, fmt="PNG", mode="RGBA", color=(0, 0, 0, 0)))
        with Image.open(os.path.join(self.tmpdir, name)) as image:
            self.assertEqual(image.mode, "RGB")
            corner = image.getpixel((0, 0))
        self.assertGreater(min(corner), 240)

    def test_delete_and_invalid_names(self):
        name = self.save(make_image(1200, 1600))
        self.assertTrue(CoverBackgroundService.delete(name))
        self.assertFalse(CoverBackgroundService.delete(name))
        for bad in ("../etc/passwd", "bg_zzzzzzzzzzzzzzzz.jpg", "bg_short.jpg", "x.jpg", ""):
            with self.assertRaises(CoverBackgroundError):
                CoverBackgroundService.delete(bad)
        self.assertIsNone(CoverBackgroundService.read("../../etc/passwd"))


class GenerateCoverWithBackgroundTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="coverbg-")
        self.patches = [
            mock.patch.object(cover_background_module, "COVER_BACKGROUND_DIR", self.tmpdir),
            mock.patch.dict(cover_background_module.CONF, {"USE_COVER_BACKGROUND": True}),
        ]
        for patch in self.patches:
            patch.start()
        CoverBackgroundService.invalidate_cache()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        CoverBackgroundService.invalidate_cache()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_output_uses_requested_size_not_source_size(self):
        CoverBackgroundService.save({"body": make_image(3000, 1000, color=(40, 40, 40))})
        data = ImageGenerator.generate_cover("测试书名", "作者", 300, 400, font_path=FONT_PATH)
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.size, (300, 400))

    def test_stroke_keeps_title_visible_on_white_background(self):
        CoverBackgroundService.save({"body": make_image(1200, 1600, color=(255, 255, 255))})
        data = ImageGenerator.generate_cover("测试书名", "", 300, 400, font_path=FONT_PATH)
        with Image.open(io.BytesIO(data)).convert("L") as image:
            darkest = min(image.tobytes())
        # 白底白字若无描边，全图最暗也只到 JPEG 噪声量级；出现深色像素说明描边已绘制
        self.assertLess(darkest, 80)

    def test_empty_library_still_generates(self):
        data = ImageGenerator.generate_cover("测试书名", "", 300, 400, font_path=FONT_PATH, no_graident=True)
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.size, (300, 400))

    def test_explicit_background_path_takes_precedence(self):
        CoverBackgroundService.save({"body": make_image(1200, 1600, color=(0, 0, 255))})
        explicit = os.path.join(self.tmpdir, "explicit.jpg")
        Image.new("RGB", (100, 100), (255, 0, 0)).save(explicit, "JPEG")
        data = ImageGenerator.generate_cover(
            "测试书名", "", 200, 300, font_path=FONT_PATH, bk_img_path=explicit)
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.size, (200, 300))
            pixel = image.getpixel((5, 295))
        self.assertGreater(pixel[0], 150)
        self.assertLess(pixel[1], 100)


class CoverBackgroundHandlerPermissionTest(unittest.TestCase):
    """二进制接口不走 @is_admin，必须确认它们调用 is_admin() 而不是直接读 admin_user。

    后者只在 get_current_user() 里赋值，若 prepare 没有触发过登录态解析就是 None，
    表现为管理员也恒 403。
    """

    def test_file_handler_checks_is_admin(self):
        handler = CoverBackgroundFile.__new__(CoverBackgroundFile)
        handler.admin_user = None
        calls = []

        def deny():
            calls.append(True)
            return False

        handler.is_admin = deny
        with self.assertRaises(web.HTTPError) as ctx:
            handler.get("bg_0123456789abcdef.jpg")
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(calls, [True])

    def test_preview_handler_checks_is_admin(self):
        handler = CoverBackgroundPreview.__new__(CoverBackgroundPreview)
        handler.admin_user = None
        calls = []

        def deny():
            calls.append(True)
            return False

        handler.is_admin = deny
        with self.assertRaises(web.HTTPError) as ctx:
            asyncio.run(handler.get())
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(calls, [True])


if __name__ == "__main__":
    unittest.main()
