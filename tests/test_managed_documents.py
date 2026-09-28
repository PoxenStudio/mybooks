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
from webserver.services.managed_documents import (
    InvalidManagedDocumentError,
    _extract_cbz_cover,
    analyze_managed_document,
)

try:
    import calibre.ebooks.metadata.book.base  # noqa: F401

    _HAS_CALIBRE_META = True
except ImportError:
    _HAS_CALIBRE_META = False

from webserver.services.managed_documents import build_managed_metadata, filename_metadata


def _make_djvu(payload=b"", form_size=None):
    """构造最小合法 DjVu IFF 容器字节串。"""
    if form_size is None:
        form_size = 4 + len(payload)
    return b"AT&TFORM" + struct.pack(">I", form_size) + b"DJVU" + payload


def _make_zip(entries):
    """entries: {name: bytes}; 以 None 值表示目录条目。"""
    buf = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            if data is None:
                zf.writestr(zipfile.ZipInfo(name + "/"), b"")
            else:
                zf.writestr(name, data)
    buf.close()
    return buf.name


# 兼容既有引用（UVZ/CBZ 共用同一 ZIP fixture 构造器）
_make_uvz = _make_zip


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

    def test_cbz_valid(self):
        p = _make_zip({"010.jpg": b"fake-jpeg", "002.jpg": b"fake-jpeg", "ComicInfo.xml": b"<xml/>"})
        try:
            self.assertIsNone(analyze_managed_document(p, "cbz"))
        finally:
            os.remove(p)

    def test_cbz_without_images_rejected(self):
        p = _make_zip({"info.xml": b"<xml/>", "notes.txt": b"text"})
        try:
            with self.assertRaises(InvalidManagedDocumentError):
                analyze_managed_document(p, "cbz")
        finally:
            os.remove(p)

    def test_cbz_not_zip_rejected(self):
        p = self._write("fake.cbz", b"not a zip file at all........")
        with self.assertRaises(InvalidManagedDocumentError):
            analyze_managed_document(p, "cbz")

    def test_cbz_encrypted_entry_rejected(self):
        p = _make_zip({"0001.jpg": b"fake-jpeg"})
        try:
            real_infolist = zipfile.ZipFile.infolist

            def encrypted_infolist(zf):
                infos = real_infolist(zf)
                for info in infos:
                    info.flag_bits |= 0x1
                return infos

            with mock.patch.object(zipfile.ZipFile, "infolist", encrypted_infolist):
                with self.assertRaises(InvalidManagedDocumentError):
                    analyze_managed_document(p, "cbz")
        finally:
            os.remove(p)

    @staticmethod
    def _patch_zip_method(path, method):
        """把 ZIP 里全部本地/中央目录条目的压缩方法字段改成指定值（如 98=PPMd）。"""
        data = bytearray(open(path, "rb").read())
        for sig, off in ((b"PK\x01\x02", 10), (b"PK\x03\x04", 8)):
            idx = data.find(sig)
            while idx != -1:
                struct.pack_into("<H", data, idx + off, method)
                idx = data.find(sig, idx + 4)
        open(path, "wb").write(bytes(data))
        return path

    def test_cbz_ppmd_cover_degrades_to_none(self):
        # P2 回归：WinRAR 等工具会产出 PPMd(98) 压缩的 CBZ——容器校验不解压必须放行，
        # 封面提取遇 NotImplementedError 降级为无封面，绝不让合法 CBZ 入库失败
        p = self._patch_zip_method(_make_zip({"0001.jpg": b"fake-jpeg-data"}), 98)
        try:
            self.assertIsNone(analyze_managed_document(p, "cbz"))
            self.assertIsNone(_extract_cbz_cover(p))
        finally:
            os.remove(p)

    def test_cbz_corrupt_stream_cover_degrades_to_none(self):
        # 容器合法但压缩流损坏（zlib.error 从 zipfile.read 裸抛）同样降级为无封面
        payload = bytes(range(256)) * 64
        p = _make_zip({"0001.jpg": payload})
        try:
            data = bytearray(open(p, "rb").read())
            info_at = zipfile.ZipFile(p).infolist()[0]
            start = data.find(b"PK\x03\x04") + 30 + len(info_at.filename)
            mid = start + info_at.compress_size // 2
            for i in range(mid, mid + 4):
                data[i] ^= 0xFF
            open(p, "wb").write(bytes(data))
            self.assertIsNone(analyze_managed_document(p, "cbz"))
            self.assertIsNone(_extract_cbz_cover(p))
        finally:
            os.remove(p)


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

    def test_cbz_cover_natural_order(self):
        # 自然排序：002.jpg 是首页（字典序会把 010.jpg 排在 002.jpg 前）
        p = _make_zip({"010.jpg": b"page-10", "002.jpg": b"page-02", "ComicInfo.xml": b"<xml/>"})
        try:
            mi = build_managed_metadata(p, "cbz", "某漫画.cbz")
            self.assertEqual(mi.cover_data[0], "jpg")
            self.assertEqual(mi.cover_data[1], b"page-02")
        finally:
            os.remove(p)

    def test_cbz_cover_skips_oversized_entry(self):
        p = _make_zip({"0001.png": b"fake-png"})
        try:
            with mock.patch.object(md, "MAX_COVER_ENTRY_BYTES", 4):
                mi = build_managed_metadata(p, "cbz", "某漫画.cbz")
            self.assertEqual(mi.cover_data, (None, None))
        finally:
            os.remove(p)

    def test_cbz_without_images_has_no_cover(self):
        # 容器校验会拦下无图 CBZ；这里直接验证封面函数对无图包返回 None 兜底
        p = _make_zip({"info.xml": b"<xml/>"})
        try:
            mi = build_managed_metadata(p, "cbz", "某漫画.cbz")
            self.assertEqual(mi.cover_data, (None, None))
        finally:
            os.remove(p)


if __name__ == "__main__":
    unittest.main()
