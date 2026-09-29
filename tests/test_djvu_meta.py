#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import importlib.util
import io
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

testdir = os.path.dirname(os.path.realpath(__file__))
projdir = os.path.realpath(testdir + "/..")
plugindir = os.path.join(projdir, "calibre", "plugins", "djvu_meta")
sys.path.append(projdir)

import webserver.main  # noqa: E402
from webserver.constants import CALIBRE_ERROR_FLAG  # noqa: E402

try:
    webserver.main.init_calibre()
    import djvu_rs  # noqa: F401
    from calibre.ebooks.metadata.book.base import Metadata
    from calibre.utils.date import parse_only_date

    _spec = importlib.util.spec_from_file_location("djvu_meta_core", os.path.join(plugindir, "core.py"))
    core = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(core)
    _READY = True
except Exception:
    _READY = False


def make_djvu(width=60, height=80, dpi=100):
    info = struct.pack(">HHBB", width, height, 26, 0) + struct.pack("<H", dpi) + bytes([22, 1])
    body = b"DJVU" + b"INFO" + struct.pack(">I", len(info)) + info
    return b"AT&TFORM" + struct.pack(">I", len(body)) + body


def sample_mi():
    mi = Metadata("测试标题 \"引号\"", ["张三", "李四"])
    mi.comments = "<p>第一段 &amp; <b>加粗</b></p><p>第二段</p>"
    mi.publisher = "某出版社"
    mi.pubdate = parse_only_date("2021-06-15")
    mi.tags = ["历史", "扫描"]
    mi.set_identifiers({"isbn": "9787111111115", "douban": "123456"})
    mi.series = "丛书"
    mi.series_index = 2.5
    mi.languages = ["zho"]
    return mi


@unittest.skipUnless(_READY, "requires calibre and djvu_rs")
class TestDjVuMetaCore(unittest.TestCase):
    def write(self, data, mi, apply_null=False):
        stream = io.BytesIO(data)
        changed = core.write_metadata(stream, mi, apply_null=apply_null)
        return changed, stream.getvalue()

    def test_read_empty_renders_cover(self):
        mi = core.read_metadata(io.BytesIO(make_djvu()))
        self.assertTrue(mi.is_null("title"))
        fmt, data = mi.cover_data
        self.assertEqual(fmt, "jpeg")
        self.assertTrue(data.startswith(b"\xff\xd8"))

    def test_cover_height_limited(self):
        mi = core.read_metadata(io.BytesIO(make_djvu(width=1500, height=3000, dpi=300)))
        from PIL import Image

        img = Image.open(io.BytesIO(mi.cover_data[1]))
        self.assertLessEqual(img.height, core.COVER_MAX_HEIGHT)

    def test_quick_skips_cover(self):
        mi = core.read_metadata(io.BytesIO(make_djvu()), quick=True)
        self.assertFalse(mi.cover_data and mi.cover_data[1])

    def test_round_trip(self):
        changed, out = self.write(make_djvu(), sample_mi())
        self.assertTrue(changed)
        mi = core.read_metadata(io.BytesIO(out), quick=True)
        self.assertEqual(mi.title, "测试标题 \"引号\"")
        self.assertEqual(mi.authors, ["张三", "李四"])
        self.assertEqual(mi.comments, "第一段 & 加粗\n第二段")
        self.assertEqual(mi.publisher, "某出版社")
        self.assertEqual(mi.pubdate.date().isoformat(), sample_mi().pubdate.date().isoformat())
        self.assertEqual(mi.tags, ["历史", "扫描"])
        self.assertEqual(mi.get_identifiers(), {"isbn": "9787111111115", "douban": "123456"})
        self.assertEqual((mi.series, mi.series_index), ("丛书", 2.5))
        self.assertEqual(mi.languages, ["zho"])

    def test_year_only(self):
        editor = djvu_rs.Editor.from_bytes(make_djvu())
        editor.set_metadata({"title": "T", "year": "1999", "keywords": "a; b，c"})
        mi = core.read_metadata(io.BytesIO(editor.to_bytes()), quick=True)
        self.assertEqual(mi.pubdate.year, 1999)
        self.assertEqual(mi.tags, ["a", "b", "c"])

    def test_merge_keeps_unknown_and_old_values(self):
        editor = djvu_rs.Editor.from_bytes(make_djvu())
        editor.set_metadata({"title": "Old", "publisher": "OldPub", "extra": [("custom", "x"), ("isbn", "0000"), ("note", "y")]})
        mi = Metadata("New", ["A"])
        mi.set_identifiers({"isbn": "9787111111115"})
        _, out = self.write(editor.to_bytes(), mi)
        meta = djvu_rs.Document.from_bytes(out).metadata()
        self.assertEqual(meta["title"], "New")
        self.assertEqual(meta["publisher"], "OldPub")
        self.assertEqual(meta["extra"], [("custom", "x"), ("isbn", "9787111111115"), ("note", "y")])

    def test_apply_null_clears(self):
        _, first = self.write(make_djvu(), sample_mi())
        _, out = self.write(first, Metadata("Only", ["A"]), apply_null=True)
        meta = djvu_rs.Document.from_bytes(out).metadata()
        self.assertEqual(meta["title"], "Only")
        self.assertIsNone(meta["publisher"])
        self.assertEqual(meta["extra"], [])

    def test_cover_not_written(self):
        mi = sample_mi()
        mi.cover_data = ("jpeg", b"\xff\xd8" + b"x" * 1000)
        _, out = self.write(make_djvu(), mi)
        keys = [k for k, _ in djvu_rs.Document.from_bytes(out).metadata()["extra"]]
        self.assertFalse([k for k in keys if "cover" in k])

    def test_unchanged_write_skipped(self):
        _, first = self.write(make_djvu(), sample_mi())
        changed, second = self.write(first, sample_mi())
        self.assertFalse(changed)
        self.assertEqual(first, second)

    def test_shorter_write_truncates(self):
        from webserver.services.managed_documents import analyze_managed_document

        _, first = self.write(make_djvu(), sample_mi())
        with tempfile.NamedTemporaryFile(suffix=".djvu", delete=False) as f:
            f.write(first)
        try:
            with open(f.name, "rb+") as stream:
                core.write_metadata(stream, Metadata("S", ["A"]), apply_null=True)
            analyze_managed_document(f.name, "djvu")
            with open(f.name, "rb") as stream:
                self.assertEqual(core.read_metadata(stream, quick=True).title, "S")
        finally:
            os.remove(f.name)

    def test_corrupt_file(self):
        mi = core.read_metadata(io.BytesIO(b"AT&TFORM\x00\x00\x00\x04DJVU"))
        self.assertTrue(mi.is_null("title"))
        with self.assertRaises(Exception):
            core.write_metadata(io.BytesIO(b"not a djvu"), sample_mi())


@unittest.skipUnless(_READY, "requires calibre and djvu_rs")
class TestDjVuMetaPlugins(unittest.TestCase):
    def test_zip_plugins_load_and_work(self):
        spec = importlib.util.spec_from_file_location("djvu_meta_build", os.path.join(plugindir, "build.py"))
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        from calibre.customize import PluginInstallationType
        from calibre.customize.ui import initialize_plugin, load_plugin

        with tempfile.TemporaryDirectory() as out_dir:
            reader_zip, writer_zip = build.build(out_dir)
            reader = initialize_plugin(load_plugin(reader_zip), reader_zip, PluginInstallationType.SYSTEM)
            writer = initialize_plugin(load_plugin(writer_zip), writer_zip, PluginInstallationType.SYSTEM)
            self.assertEqual(reader.file_types, {"djvu"})
            self.assertEqual(writer.file_types, {"djvu"})

            stream = io.BytesIO(make_djvu())
            with writer:
                writer.set_metadata(stream, Metadata("Plugin", ["A"]), "djvu")
            with reader:
                reader.quick = False
                mi = reader.get_metadata(stream, "djvu")
            self.assertEqual(mi.title, "Plugin")
            self.assertEqual(mi.cover_data[0], "jpeg")


@unittest.skipUnless(_READY, "requires calibre and djvu_rs")
class TestManagedDjVuMetadata(unittest.TestCase):
    def setUp(self):
        with tempfile.NamedTemporaryFile(suffix=".djvu", delete=False) as f:
            f.write(make_djvu())
        self.path = f.name

    def tearDown(self):
        os.remove(self.path)

    def build(self, file_mi):
        from webserver.services.managed_documents import build_managed_metadata

        with mock.patch("calibre.customize.ui.get_file_type_metadata", return_value=file_mi):
            return build_managed_metadata(self.path, "djvu", "SampleTitle.djvu")

    def test_file_metadata_preferred(self):
        file_mi = Metadata("内嵌书名", ["内嵌作者"])
        file_mi.cover_data = ("jpeg", b"\xff\xd8cover")
        mi = self.build(file_mi)
        self.assertEqual(mi.title, "内嵌书名")
        self.assertEqual(mi.authors, ["内嵌作者"])
        self.assertEqual(mi.cover_data, ("jpeg", b"\xff\xd8cover"))

    def test_filename_fallback(self):
        mi = self.build(Metadata(None, None))
        self.assertEqual(mi.title, "SampleTitle")

    def test_error_flag_ignored(self):
        mi = self.build(Metadata(CALIBRE_ERROR_FLAG, None))
        self.assertEqual(mi.title, "SampleTitle")


if __name__ == "__main__":
    unittest.main()
