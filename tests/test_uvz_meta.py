#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import importlib.util
import io
import os
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
    from calibre.ebooks.metadata.book.base import Metadata  # noqa: F401

    _spec = importlib.util.spec_from_file_location("uvz_meta_core", os.path.join(pluginsdir, "uvz_meta", "core.py"))
    core = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(core)
    _READY = True
except Exception:
    _READY = False

BOOKINFO = "[General Information]\r\n书名=云南地方志考\r\n作者=李硕\r\n页数=126\r\nSS号=10647901\r\n出版日期=1988年02月第1版\r\n"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00fake-jpeg"
PNG = b"\x89PNG\r\n\x1a\nfake-png"
PDG = b"HH\x02\x00proprietary-page"


def make_uvz(entries, folder="云南地方志考_10647901"):
    # 与超星样本一致：目录名为 GBK 字节、无 UTF-8 标志
    prefix = folder.encode("gbk").decode("cp437") + "/" if folder else ""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if prefix:
            zf.writestr(zipfile.ZipInfo(prefix), b"")
        for name, data in entries.items():
            zf.writestr(prefix + name, data)
    return buf.getvalue()


@unittest.skipUnless(_READY, "requires calibre")
class TestUvzRead(unittest.TestCase):
    def read(self, data, quick=False):
        return core.read_metadata(io.BytesIO(data), quick=quick)

    def test_bookinfo_fields(self):
        data = make_uvz({"!00001.pdg": PDG, "000001.pdg": PDG, "bookinfo.dat": BOOKINFO.encode("gbk"), "cov001.pdg": JPEG})
        mi = self.read(data)
        self.assertEqual(mi.title, "云南地方志考")
        self.assertEqual(mi.authors, ["李硕"])
        self.assertEqual((mi.pubdate.year, mi.pubdate.month), (1988, 2))
        self.assertEqual(mi.get_identifiers(), {"ss": "10647901"})
        self.assertEqual(mi.cover_data, ("jpeg", JPEG))

    def test_optional_fields(self):
        info = "书名=书\n作者=甲，乙、丙\n出版社=中华书局\nISBN号=9787111111115\nDX号=000001\n主题词=地方志；云南\n内容提要=简介\n出版日期=2001.7\n"
        mi = self.read(make_uvz({"bookinfo.dat": info.encode("utf-8"), "000001.pdg": PDG}), quick=True)
        self.assertEqual(mi.authors, ["甲", "乙", "丙"])
        self.assertEqual((mi.publisher, mi.comments), ("中华书局", "简介"))
        self.assertEqual(mi.tags, ["地方志", "云南"])
        self.assertEqual(mi.get_identifiers(), {"isbn": "9787111111115", "dx": "000001"})
        self.assertEqual((mi.pubdate.year, mi.pubdate.month), (2001, 7))

    def test_proprietary_cover_falls_back_to_title_page(self):
        mi = self.read(make_uvz({"cov001.pdg": PDG, "bok001.pdg": PNG, "000001.pdg": PDG}))
        self.assertEqual(mi.cover_data, ("png", PNG))

    def test_no_decodable_cover(self):
        mi = self.read(make_uvz({"cov001.pdg": PDG, "000001.pdg": JPEG}))
        self.assertEqual(mi.cover_data, (None, None))

    def test_oversized_cover_skipped(self):
        with mock.patch.object(core, "MAX_COVER_ENTRY_BYTES", 4):
            mi = self.read(make_uvz({"cov001.pdg": JPEG}))
        self.assertEqual(mi.cover_data, (None, None))

    def test_quick_skips_cover(self):
        mi = self.read(make_uvz({"cov001.pdg": JPEG}), quick=True)
        self.assertFalse(mi.cover_data and mi.cover_data[1])

    def test_without_bookinfo(self):
        mi = self.read(make_uvz({"000001.pdg": PDG}, folder=""))
        self.assertTrue(mi.is_null("title"))
        self.assertTrue(mi.is_null("authors"))

    def test_corrupt_file(self):
        mi = self.read(b"PK\x03\x04 broken")
        self.assertTrue(mi.is_null("title"))


@unittest.skipUnless(_READY, "requires calibre")
class TestUvzPlugin(unittest.TestCase):
    def test_zip_plugin_loads_and_works(self):
        spec = importlib.util.spec_from_file_location("calibre_plugins_build", os.path.join(pluginsdir, "build.py"))
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        from calibre.customize import PluginInstallationType
        from calibre.customize.ui import initialize_plugin, load_plugin

        with tempfile.TemporaryDirectory() as out_dir:
            (reader_zip,) = build.build(out_dir, ["uvz_meta"])
            reader = initialize_plugin(load_plugin(reader_zip), reader_zip, PluginInstallationType.SYSTEM)
            self.assertEqual(reader.file_types, {"uvz"})
            with reader:
                reader.quick = False
                mi = reader.get_metadata(io.BytesIO(make_uvz({"bookinfo.dat": BOOKINFO.encode("gbk"), "cov001.pdg": JPEG})), "uvz")
            self.assertEqual(mi.title, "云南地方志考")
            self.assertEqual(mi.cover_data, ("jpeg", JPEG))


@unittest.skipUnless(_READY, "requires calibre")
class TestUvzBookMetadata(unittest.TestCase):
    def test_file_metadata_overrides_filename(self):
        from webserver.base.book_files import read_book_metadata, validate_book_file

        file_mi = core.read_metadata(io.BytesIO(make_uvz({"bookinfo.dat": BOOKINFO.encode("gbk"), "cov001.pdg": JPEG})))
        with tempfile.NamedTemporaryFile(suffix=".uvz", delete=False) as f:
            f.write(make_uvz({"bookinfo.dat": BOOKINFO.encode("gbk"), "cov001.pdg": JPEG}))
        try:
            validate_book_file(f.name, "uvz")
            with mock.patch("calibre.customize.ui.get_file_type_metadata", return_value=file_mi):
                mi = read_book_metadata(f.name, "uvz", "SS10647901.uvz")
            self.assertEqual((mi.title, list(mi.authors)), ("云南地方志考", ["李硕"]))
            self.assertEqual(mi.cover_data, ("jpeg", JPEG))
        finally:
            os.remove(f.name)


if __name__ == "__main__":
    unittest.main()
