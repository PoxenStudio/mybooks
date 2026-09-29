#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import importlib.util
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

testdir = os.path.dirname(os.path.realpath(__file__))
projdir = os.path.realpath(testdir + "/..")
pluginsdir = os.environ.get("MYBOOKS_CALIBRE_PLUGINS_SRC") or os.path.join(projdir, "calibre", "plugins")
sys.path.append(projdir)

import webserver.main  # noqa: E402

try:
    webserver.main.init_calibre()
    from calibre.ebooks.metadata.book.base import Metadata

    _spec = importlib.util.spec_from_file_location("cbz_meta_core", os.path.join(pluginsdir, "cbz_meta", "core.py"))
    core = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(core)
    _READY = True
except Exception:
    _READY = False

COMICINFO = """<?xml version="1.0" encoding="utf-8"?>
<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <Title>第一话</Title>
  <Series>海贼王</Series>
  <Number>2.5</Number>
  <Summary>冒险开始</Summary>
  <Year>2021</Year>
  <Month>6</Month>
  <Day>15</Day>
  <Writer>尾田荣一郎, 助手</Writer>
  <Penciller>画师</Penciller>
  <Publisher>集英社</Publisher>
  <Genre>冒险, 热血</Genre>
  <Tags>少年</Tags>
  <LanguageISO>zh</LanguageISO>
  <Manga>Yes</Manga>
  <Pages><Page Image="1" Type="FrontCover"/></Pages>
  <GTIN>9787111111115</GTIN>
</ComicInfo>
"""


def make_cbz(entries, comment=b"", compression=zipfile.ZIP_DEFLATED):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
        zf.comment = comment
    return buf.getvalue()


def names(data):
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return [i.filename for i in zf.infolist()]


def read_entry(data, name):
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.read(name)


@unittest.skipUnless(_READY, "requires calibre")
class TestCbzRead(unittest.TestCase):
    def read(self, data, quick=False):
        return core.read_metadata(io.BytesIO(data), quick=quick)

    def test_comicinfo_fields(self):
        mi = self.read(make_cbz({"001.jpg": b"p1", "002.jpg": b"p2", "ComicInfo.xml": COMICINFO}))
        self.assertEqual(mi.title, "第一话")
        self.assertEqual(mi.authors, ["尾田荣一郎", "助手"])
        self.assertEqual((mi.series, mi.series_index), ("海贼王", 2.5))
        self.assertEqual(mi.comments, "冒险开始")
        self.assertEqual(mi.publisher, "集英社")
        self.assertEqual(mi.pubdate.date().isoformat(), "2021-06-15")
        self.assertEqual(mi.tags, ["冒险", "热血", "少年"])
        self.assertEqual(mi.languages, ["zho"])
        self.assertEqual(mi.get_identifiers(), {"isbn": "9787111111115"})
        self.assertEqual(mi.cover_data, ("jpg", b"p2"))

    def test_title_falls_back_to_series(self):
        xml = "<ComicInfo><Series>S</Series><Number>3</Number></ComicInfo>"
        mi = self.read(make_cbz({"1.png": b"p", "ComicInfo.xml": xml}), quick=True)
        self.assertEqual(mi.title, "S 3")

    def test_cover_natural_order(self):
        mi = self.read(make_cbz({"010.jpg": b"page-10", "002.jpeg": b"page-02"}))
        self.assertEqual(mi.cover_data, ("jpg", b"page-02"))

    def test_cover_skips_oversized_entry(self):
        with mock.patch.object(core, "MAX_COVER_ENTRY_BYTES", 4):
            mi = self.read(make_cbz({"0001.png": b"fake-png"}))
        self.assertEqual(mi.cover_data, (None, None))

    def test_cover_degrades_on_unsupported_compression(self):
        data = bytearray(make_cbz({"0001.jpg": b"fake-jpeg-data"}))
        for sig, off in ((b"PK\x01\x02", 10), (b"PK\x03\x04", 8)):
            idx = data.find(sig)
            while idx != -1:
                struct.pack_into("<H", data, idx + off, 98)
                idx = data.find(sig, idx + 4)
        mi = self.read(bytes(data))
        self.assertEqual(mi.cover_data, (None, None))

    def test_quick_skips_cover(self):
        mi = self.read(make_cbz({"1.jpg": b"p"}), quick=True)
        self.assertFalse(mi.cover_data and mi.cover_data[1])

    def test_comic_book_info_fallback(self):
        cbi = {"ComicBookInfo/1.0": {"title": "CBI Title", "series": "S", "volume": 3, "credits": [{"person": "Doe, John", "role": "Writer"}]}}
        mi = self.read(make_cbz({"1.jpg": b"p"}, comment=json.dumps(cbi).encode()))
        self.assertEqual(mi.title, "CBI Title")
        self.assertEqual(mi.authors, ["John Doe"])
        self.assertEqual((mi.series, mi.series_index), ("S", 3.0))
        self.assertEqual(mi.cover_data, ("jpg", b"p"))

    def test_invalid_comicinfo_ignored(self):
        mi = self.read(make_cbz({"1.jpg": b"p", "ComicInfo.xml": "<not-comicinfo/>"}))
        self.assertTrue(mi.is_null("title"))
        self.assertEqual(mi.cover_data, ("jpg", b"p"))

    def test_corrupt_file(self):
        mi = self.read(b"PK\x03\x04 broken")
        self.assertTrue(mi.is_null("title"))


@unittest.skipUnless(_READY, "requires calibre")
class TestCbzWrite(unittest.TestCase):
    def write(self, data, mi, apply_null=False):
        stream = io.BytesIO(data)
        changed = core.write_metadata(stream, mi, apply_null=apply_null)
        return changed, stream.getvalue()

    def sample_mi(self):
        from calibre.utils.date import parse_only_date

        mi = Metadata("新标题", ["作者甲", "作者乙"])
        mi.series, mi.series_index = "丛书", 4
        mi.comments = "简介"
        mi.publisher = "出版社"
        mi.pubdate = parse_only_date("2020-03-09")
        mi.tags = ["标签一", "标签二"]
        mi.languages = ["zho"]
        mi.set_identifiers({"isbn": "9787111111115"})
        return mi

    def test_add_comicinfo_and_round_trip(self):
        src = make_cbz({"001.jpg": b"p1" * 100, "002.jpg": b"p2" * 100}, comment=b"keep-me", compression=zipfile.ZIP_STORED)
        changed, out = self.write(src, self.sample_mi())
        self.assertTrue(changed)
        self.assertEqual(names(out), ["001.jpg", "002.jpg", "ComicInfo.xml"])
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            self.assertEqual(zf.comment, b"keep-me")
            self.assertEqual(zf.getinfo("001.jpg").compress_type, zipfile.ZIP_STORED)
            self.assertEqual(zf.read("002.jpg"), b"p2" * 100)
        mi = core.read_metadata(io.BytesIO(out), quick=True)
        self.assertEqual(mi.title, "新标题")
        self.assertEqual(mi.authors, ["作者甲", "作者乙"])
        self.assertEqual((mi.series, mi.series_index), ("丛书", 4.0))
        self.assertEqual((mi.comments, mi.publisher), ("简介", "出版社"))
        self.assertEqual(mi.pubdate.date().isoformat(), "2020-03-09")
        self.assertEqual(mi.tags, ["标签一", "标签二"])
        self.assertEqual(mi.languages, ["zho"])
        self.assertEqual(mi.get_identifiers(), {"isbn": "9787111111115"})
        self.assertIn(b"<LanguageISO>zh</LanguageISO>", read_entry(out, "ComicInfo.xml"))

    def test_update_keeps_unknown_elements_and_order(self):
        src = make_cbz({"001.jpg": b"p1", "002.jpg": b"p2", "ComicInfo.xml": COMICINFO})
        mi = Metadata("改名", ["作者甲"])
        _, out = self.write(src, mi)
        xml = read_entry(out, "ComicInfo.xml").decode("utf-8")
        for kept in ("<Penciller>画师</Penciller>", "<Manga>Yes</Manga>", 'Type="FrontCover"', "<Publisher>集英社</Publisher>", "<Tags>少年</Tags>"):
            self.assertIn(kept, xml)
        self.assertIn("<Title>改名</Title>", xml)
        self.assertLess(xml.index("<Title>"), xml.index("<Series>"))
        self.assertEqual(core.read_metadata(io.BytesIO(out)).cover_data, ("jpg", b"p2"))

    def test_new_elements_inserted_in_schema_order(self):
        src = make_cbz({"1.jpg": b"p", "ComicInfo.xml": "<ComicInfo><Title>T</Title><Manga>Yes</Manga></ComicInfo>"})
        mi = Metadata("T", ["W"])
        mi.publisher = "P"
        _, out = self.write(src, mi)
        xml = read_entry(out, "ComicInfo.xml").decode("utf-8")
        self.assertLess(xml.index("<Writer>"), xml.index("<Publisher>"))
        self.assertLess(xml.index("<Publisher>"), xml.index("<Manga>"))

    def test_tags_replace_genre_and_tags(self):
        src = make_cbz({"1.jpg": b"p", "ComicInfo.xml": COMICINFO})
        mi = Metadata("T", ["W"])
        mi.tags = ["新标签"]
        _, out = self.write(src, mi)
        self.assertEqual(core.read_metadata(io.BytesIO(out), quick=True).tags, ["新标签"])

    def test_apply_null_clears(self):
        src = make_cbz({"1.jpg": b"p", "ComicInfo.xml": COMICINFO})
        _, out = self.write(src, Metadata("Only", ["A"]), apply_null=True)
        xml = read_entry(out, "ComicInfo.xml").decode("utf-8")
        for gone in ("<Series>", "<Publisher>", "<Summary>", "<Genre>", "<Tags>", "<GTIN>"):
            self.assertNotIn(gone, xml)
        self.assertIn("<Penciller>画师</Penciller>", xml)

    def test_unchanged_write_skipped(self):
        _, first = self.write(make_cbz({"1.jpg": b"p"}), self.sample_mi())
        changed, second = self.write(first, self.sample_mi())
        self.assertFalse(changed)
        self.assertEqual(first, second)

    def test_empty_metadata_does_not_add_comicinfo(self):
        src = make_cbz({"1.jpg": b"p"})
        changed, out = self.write(src, Metadata(None, None))
        self.assertFalse(changed)
        self.assertEqual(out, src)

    def test_cover_not_written(self):
        mi = self.sample_mi()
        mi.cover_data = ("jpg", b"new-cover")
        _, out = self.write(make_cbz({"1.jpg": b"p"}), mi)
        self.assertEqual(names(out), ["1.jpg", "ComicInfo.xml"])

    def test_nested_comicinfo_replaced_in_place(self):
        src = make_cbz({"book/1.jpg": b"p", "book/ComicInfo.xml": "<ComicInfo><Title>Old</Title></ComicInfo>"})
        _, out = self.write(src, Metadata("New", ["A"]))
        self.assertEqual(names(out), ["book/1.jpg", "book/ComicInfo.xml"])
        self.assertIn(b"<Title>New</Title>", read_entry(out, "book/ComicInfo.xml"))

    def test_file_write_truncates_and_stays_valid(self):
        from webserver.base.book_files import validate_book_file

        src = make_cbz({"1.jpg": b"p" * 5000, "ComicInfo.xml": COMICINFO * 1})
        with tempfile.NamedTemporaryFile(suffix=".cbz", delete=False) as f:
            f.write(src)
        try:
            with open(f.name, "rb+") as stream:
                core.write_metadata(stream, Metadata("S", ["A"]), apply_null=True)
            validate_book_file(f.name, "cbz")
            with open(f.name, "rb") as stream:
                self.assertEqual(core.read_metadata(stream, quick=True).title, "S")
        finally:
            os.remove(f.name)

    def test_corrupt_file_raises(self):
        with self.assertRaises(Exception):
            core.write_metadata(io.BytesIO(b"not a zip"), self.sample_mi())


@unittest.skipUnless(_READY, "requires calibre")
class TestCbzPlugins(unittest.TestCase):
    def test_zip_plugins_load_and_work(self):
        spec = importlib.util.spec_from_file_location("calibre_plugins_build", os.path.join(pluginsdir, "build.py"))
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        from calibre.customize import PluginInstallationType
        from calibre.customize.ui import initialize_plugin, load_plugin

        self.assertIn("cbz_meta", build.plugin_names())
        with tempfile.TemporaryDirectory() as out_dir:
            reader_zip, writer_zip = build.build(out_dir, ["cbz_meta"])
            reader = initialize_plugin(load_plugin(reader_zip), reader_zip, PluginInstallationType.SYSTEM)
            writer = initialize_plugin(load_plugin(writer_zip), writer_zip, PluginInstallationType.SYSTEM)
            self.assertEqual(reader.file_types, {"cbz"})
            self.assertEqual(writer.file_types, {"cbz"})

            stream = io.BytesIO(make_cbz({"1.jpg": b"p"}))
            with writer:
                writer.set_metadata(stream, Metadata("Plugin", ["A"]), "cbz")
            with reader:
                reader.quick = False
                mi = reader.get_metadata(stream, "cbz")
            self.assertEqual(mi.title, "Plugin")
            self.assertEqual(mi.cover_data, ("jpg", b"p"))


if __name__ == "__main__":
    unittest.main()
