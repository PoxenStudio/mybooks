#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""lite 模式下载读块（BookDownload.get_content 覆写）测试。

tornado 原生 get_content 的 64KB 读块硬编码在方法内、且它是 classmethod，原实现
里 ``self.CHUNK_SIZE = 256 * 1024``（实例属性）不会生效。本文件钉住覆写后的行为：
lite 模式整本下载按 LITE_CHUNK_SIZE 分块、字节正确；普通模式与带 Range 的请求与
tornado 原生输出一致（零行为变化）。
"""

import os
import tempfile
import unittest
from unittest import mock

from tornado import web

from webserver import perf
from webserver.handlers.book import BookDownload


def lite():
    return mock.patch.dict(perf.CONF, {"PERFORMANCE_MODE": "lite"})


def normal():
    return mock.patch.dict(perf.CONF, {"PERFORMANCE_MODE": "normal"})


class TestDownloadLiteChunk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunk = BookDownload.LITE_CHUNK_SIZE
        cls.data = os.urandom(cls.chunk * 2 + 12345)
        fd, cls.path = tempfile.mkstemp(suffix=".bin")
        with os.fdopen(fd, "wb") as f:
            f.write(cls.data)

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.path)

    def test_lite_full_download_uses_bigger_chunks(self):
        with lite():
            chunks = list(BookDownload.get_content(self.path))
        self.assertEqual([len(c) for c in chunks], [self.chunk, self.chunk, len(self.data) - self.chunk * 2])
        self.assertEqual(b"".join(chunks), self.data)

    def test_normal_mode_matches_native(self):
        with normal():
            ours = list(BookDownload.get_content(self.path))
        native = list(web.StaticFileHandler.get_content(self.path))
        self.assertEqual(ours, native)

    def test_lite_range_request_matches_native(self):
        with lite():
            ours = list(BookDownload.get_content(self.path, 100, 5000))
        native = list(web.StaticFileHandler.get_content(self.path, 100, 5000))
        self.assertEqual(ours, native)
        self.assertEqual(b"".join(ours), self.data[100:5000])
