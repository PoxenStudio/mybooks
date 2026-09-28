#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import contextlib
import os
import warnings
from unittest import mock
from tests.test_main import TestWithUserLogin, setUpModule as init, testdir
from tests.test_managed_documents import _make_djvu, _make_uvz

def setUpModule():
    init()

class TestUpload(TestWithUserLogin):
    @mock.patch("webserver.handlers.book.BookUpload.get_upload_file")
    def test_upload_bad_filename(self, m1):
        name = "索恩·德国史"
        path = testdir + "/cases/old.epub"
        with open(path, "rb") as f:
            data = f.read()
            m1.return_value = (name, data)

            d = self.json("/api/book/upload", method="POST", body="k=1")
            self.assertEqual(d["err"], "params.filename")

    # @mock.patch("webserver.handlers.book.BookUpload.get_upload_file")
    # def test_upload_old_file_zh(self, m1):
    #     name = "索恩·德国史.epub"
    #     path = testdir + "/cases/old.epub"
    #     with open(path, "rb") as f:
    #         data = f.read()
    #         m1.return_value = (name, data)

    #         d = self.json("/api/book/upload", method="POST", body="k=1")
    #         self.assertEqual(d["err"], "samebook")

    # @mock.patch("webserver.handlers.book.BookUpload.get_upload_file")
    # def test_upload_old_file(self, m1):
    #     name = "abc.epub"
    #     path = testdir + "/cases/old.epub"
    #     with open(path, "rb") as f:
    #         data = f.read()
    #         m1.return_value = (name, data)

    #         d = self.json("/api/book/upload", method="POST", body="k=1")
    #         self.assertEqual(d["err"], "samebook")

    @mock.patch("webserver.handlers.book.BookUpload.get_upload_file")
    @mock.patch("webserver.handlers.base.BaseHandler.user_history")
    @mock.patch("webserver.handlers.base.BaseHandler.add_msg")
    @mock.patch("webserver.models.Item.save")
    @mock.patch("calibre.db.legacy.LibraryDatabase.import_book")
    def test_upload_new_file(self, m5, m4, m3, m2, m1):
        warnings.simplefilter('ignore', ResourceWarning)
        name = "new.epub"
        path = testdir + "/cases/new.epub"
        with open(path, "rb") as f:
            data = f.read()
            m1.return_value = (name, data)
            m2.return_value = True
            m3.return_value = True
            m4.return_value = True
            m5.return_value = 1008610086

            d = self.json("/api/book/upload", method="POST", body="k=1", request_timeout=30)
            self.assertEqual(d["err"], "ok")

    # ---- DJVU/UVZ 扫描版托管文档（下载专用）----

    def _upload_managed(self, name, data):
        warnings.simplefilter('ignore', ResourceWarning)
        patches = [
            mock.patch("webserver.handlers.book.BookUpload.get_upload_file", return_value=(name, data)),
            mock.patch("webserver.handlers.base.BaseHandler.user_history"),
            mock.patch("webserver.handlers.base.BaseHandler.add_msg"),
            mock.patch("webserver.models.Item.save", return_value=True),
            mock.patch("calibre.db.legacy.LibraryDatabase.import_book", return_value=1008610086),
        ]
        with contextlib.ExitStack() as stack:
            for pt in patches:
                stack.enter_context(pt)
            return self.json("/api/book/upload", method="POST", body="k=1", request_timeout=30)

    def test_upload_djvu_new_file(self):
        data = _make_djvu(b"DJVI" + b"\x00" * 8)
        d = self._upload_managed("managed_djvu_smoke.djvu", data)
        self.assertEqual(d["err"], "ok")

    def test_upload_djvu_invalid_container(self):
        d = self._upload_managed("bad_djvu.djvu", b"NOTDJVU" + b"\x00" * 32)
        self.assertEqual(d["err"], "book.invalid")

    def test_upload_uvz_new_file(self):
        p = _make_uvz({"0001.pdg": b"fake-page"})
        try:
            with open(p, "rb") as f:
                data = f.read()
            d = self._upload_managed("managed_uvz_smoke.uvz", data)
            self.assertEqual(d["err"], "ok")
        finally:
            os.remove(p)

    def test_upload_cbz_new_file(self):
        # CBZ 走托管路径并提取首页封面（jpeg 魔数，不应触发 RIFF→jpeg 转换分支）
        p = _make_uvz({"010.jpg": b"page-10", "002.jpg": b"\xff\xd8\xff\xe0fake-jpeg"})
        try:
            with open(p, "rb") as f:
                data = f.read()
            d = self._upload_managed("managed_cbz_smoke.cbz", data)
            self.assertEqual(d["err"], "ok")
        finally:
            os.remove(p)

    def test_upload_managed_unsupported_format_still_rejected(self):
        d = self._upload_managed("managed_smoke.xyz", b"data")
        self.assertEqual(d["err"], "params.format.unsupported")

    def test_chunk_upload_accepts_managed_format_gate(self):
        d = self.json(
            "/api/book/upload/chunk?filename=managed_djvu_smoke.djvu&chunk_index=0&total_chunks=1",
            method="POST", body="k=1",
        )
        # 通过格式闸门后因缺少 hash 被拦下，说明 DJVU 已被放行
        self.assertEqual(d["err"], "params.hash")

    def test_chunk_upload_rejects_unknown_format(self):
        d = self.json(
            "/api/book/upload/chunk?filename=managed_smoke.xyz&chunk_index=0&total_chunks=1",
            method="POST", body="k=1",
        )
        self.assertEqual(d["err"], "params.format.unsupported")

    @staticmethod
    def _chunk_multipart(data):
        boundary = "----mybooksTestBoundary"
        part = (
            "--" + boundary + "\r\n"
            'Content-Disposition: form-data; name="chunk"; filename="chunk_0"\r\n'
            "Content-Type: application/octet-stream\r\n"
            "\r\n"
        ).encode("utf-8") + data + ("\r\n--" + boundary + "--\r\n").encode("utf-8")
        return part, boundary

    def test_chunk_upload_djvu_merge_new_book(self):
        # 分片上传 djvu 走完整合并链：托管元数据无封面（cover_data=(None, None)），
        # 回归 _add_new_book 里 RIFF 检查缺 [1] 守卫时的 TypeError（P1）
        data = _make_djvu(b"DJVI" + b"\x00" * 8)
        part, boundary = self._chunk_multipart(data)
        with mock.patch("calibre.db.legacy.LibraryDatabase.import_book", return_value=1008610086), \
                mock.patch("webserver.handlers.base.BaseHandler.user_history"), \
                mock.patch("webserver.handlers.base.BaseHandler.add_msg"), \
                mock.patch("webserver.models.Item.save", return_value=True):
            d = self.json(
                "/api/book/upload/chunk?filename=managed_chunk_smoke.djvu"
                "&chunk_index=0&total_chunks=1&file_hash=abcdef0123456789",
                method="POST", body=part,
                headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary},
            )
        self.assertEqual(d["err"], "ok")

    def test_chunk_upload_djvu_merge_invalid_container(self):
        part, boundary = self._chunk_multipart(b"NOTDJVU" + b"\x00" * 32)
        d = self.json(
            "/api/book/upload/chunk?filename=bad_chunk_smoke.djvu"
            "&chunk_index=0&total_chunks=1&file_hash=abcdef0123456789",
            method="POST", body=part,
            headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary},
        )
        self.assertEqual(d["err"], "book.invalid")

