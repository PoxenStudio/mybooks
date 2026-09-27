#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""DJVU/UVZ 扫描版托管文档：容器校验与文件名编目测试。

纯单元测试（不依赖 tornado/calibre 环境）；filename_metadata 依赖 calibre
元数据库，在缺 calibre 的环境下自动跳过。
"""

import os
import struct
import tempfile
import unittest
import zipfile
from unittest import mock

from webserver.services import managed_documents as md
from webserver.services.managed_documents import InvalidManagedDocumentError, analyze_managed_document

try:
    import calibre.ebooks.metadata.book.base  # noqa: F401

    _HAS_CALIBRE_META = True
except ImportError:
    _HAS_CALIBRE_META = False

from webserver.services.managed_documents import filename_metadata


def _make_djvu(payload=b"", form_size=None):
    """构造最小合法 DjVu IFF 容器字节串。"""
    if form_size is None:
        form_size = 4 + len(payload)
    return b"AT&TFORM" + struct.pack(">I", form_size) + b"DJVU" + payload


def _make_uvz(entries):
    """entries: {name: bytes}; 以 None 值表示目录条目。"""
    buf = tempfile.NamedTemporaryFile(suffix=".uvz", delete=False)
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            if data is None:
                zf.writestr(zipfile.ZipInfo(name + "/"), b"")
            else:
                zf.writestr(name, data)
    buf.close()
    return buf.name


class TestAnalyzeManagedDocument(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _write(self, name, data):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_djvu_valid(self):
        p = self._write("ok.djvu", _make_djvu(b"DJVI" + b"\x00" * 8))
        self.assertIsNone(analyze_managed_document(p, "djvu"))

    def test_djvu_invalid_magic(self):
        p = self._write("bad.djvu", b"AT&TFORM" + b"\x00" * 4 + b"XXXX" + b"\x00" * 4)
        with self.assertRaises(InvalidManagedDocumentError):
            analyze_managed_document(p, "djvu")

    def test_djvu_size_mismatch(self):
        p = self._write("short.djvu", _make_djvu(form_size=999))
        with self.assertRaises(InvalidManagedDocumentError):
            analyze_managed_document(p, "djvu")

    def test_djvu_truncated(self):
        p = self._write("trunc.djvu", _make_djvu()[:10])
        with self.assertRaises(InvalidManagedDocumentError):
            analyze_managed_document(p, "djvu")

    def test_uvz_valid(self):
        p = _make_uvz({"0001.pdg": b"fake-page", "cover.jpg": b"jpegdata"})
        try:
            self.assertIsNone(analyze_managed_document(p, "uvz"))
        finally:
            os.remove(p)

    def test_uvz_not_zip(self):
        p = self._write("fake.uvz", b"not a zip file at all........")
        with self.assertRaises(InvalidManagedDocumentError):
            analyze_managed_document(p, "uvz")

    def test_uvz_empty(self):
        p = _make_uvz({"dir_only": None})
        try:
            with self.assertRaises(InvalidManagedDocumentError):
                analyze_managed_document(p, "uvz")
        finally:
            os.remove(p)

    def test_uvz_encrypted_entry(self):
        p = _make_uvz({"0001.pdg": b"fake-page"})
        try:
            real_infolist = zipfile.ZipFile.infolist

            def encrypted_infolist(zf):
                infos = real_infolist(zf)
                for info in infos:
                    info.flag_bits |= 0x1
                return infos

            with mock.patch.object(zipfile.ZipFile, "infolist", encrypted_infolist):
                with self.assertRaises(InvalidManagedDocumentError):
                    analyze_managed_document(p, "uvz")
        finally:
            os.remove(p)

    def test_uvz_entry_budget(self):
        p = _make_uvz({"a.pdg": b"1", "b.pdg": b"2", "c.pdg": b"3"})
        try:
            with mock.patch.object(md, "MAX_ARCHIVE_ENTRIES", 2):
                with self.assertRaises(InvalidManagedDocumentError):
                    analyze_managed_document(p, "uvz")
        finally:
            os.remove(p)

    def test_unsupported_format(self):
        p = self._write("x.txt", b"hello")
        with self.assertRaises(InvalidManagedDocumentError):
            analyze_managed_document(p, "txt")

    def test_unreadable_file_wrapped_as_invalid(self):
        # 文件不可读（不存在/权限）应转为校验错误而非 OSError 直抛
        p = os.path.join(self.tmp, "missing.djvu")
        with self.assertRaises(InvalidManagedDocumentError):
            analyze_managed_document(p, "djvu")


@unittest.skipUnless(_HAS_CALIBRE_META, "requires calibre metadata libs")
class TestFilenameMetadata(unittest.TestCase):
    def test_title_with_author(self):
        mi = filename_metadata("三国志作者：陈寿.djvu")
        self.assertEqual(mi.title, "三国志")
        self.assertEqual(list(mi.authors), ["陈寿"])

    def test_title_only_falls_back_to_anonymous(self):
        mi = filename_metadata("某本无名扫描书.uvz")
        self.assertEqual(mi.title, "某本无名扫描书")
        self.assertEqual(list(mi.authors), ["佚名"])


if __name__ == "__main__":
    unittest.main()
