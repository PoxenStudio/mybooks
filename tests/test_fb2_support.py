#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""FB2（FictionBook2）格式接入的格式白名单契约测试（离线，无需 calibre）。

fb2 走常规电子书链路：上传/分片上传/追加入库（ACCEPTED_BOOK_FORMATS）、扫描导入
（scan_service.SCAN_EXT）、MyReader 原生阅读（BookRead.READABLE_FORMATS 与 MyReader
跳转分支）、元数据回写（META_WRITABLE_FORMATS，运行时由 calibre can_set_metadata
按插件可用性二次过滤）。本测试锁定各白名单确实含 fb2，防止后续重构悄悄漏掉。

运行：python tests/test_fb2_support.py
"""

import unittest

from webserver import constants


class TestFB2Whitelists(unittest.TestCase):
    def test_supported_ebook_formats_contains_fb2(self):
        self.assertIn("fb2", constants.SUPPORTED_EBOOK_FORMATS)

    def test_accepted_book_formats_contains_fb2(self):
        # 上传/分片上传/追加格式三处闸门由 ACCEPTED_BOOK_FORMATS 驱动
        self.assertIn("fb2", constants.ACCEPTED_BOOK_FORMATS)

    def test_meta_writable_formats_contains_fb2(self):
        # utils.meta_writable_formats() 在有 calibre 的环境会用 can_set_metadata 再过滤；
        # calibre 7.x 内置 FB2MetadataReader/Writer，缺插件时自动排除，无需在此模拟
        self.assertIn("fb2", constants.META_WRITABLE_FORMATS)

    def test_scan_ext_contains_fb2(self):
        # 目录扫描/批量上传/监控导入共用 scan_service.SCAN_EXT（= ACCEPTED_BOOK_FORMATS）
        from webserver.services.scan_service import SCAN_EXT

        self.assertIn("fb2", SCAN_EXT)

    def test_book_read_readable_formats_contains_fb2(self):
        # 阅读心跳的分格式统计优先级表
        from webserver.handlers.book import BookRead

        self.assertIn("fb2", BookRead.READABLE_FORMATS)

    def test_book_path_streamable_formats_contains_fb2(self):
        # MyReader 嵌入阅读的流式链路依赖 /api/book/<id>/filepath 取物理路径
        from webserver.handlers.book import BookFilePath

        self.assertIn("fb2", BookFilePath.STREAMABLE_FORMATS)


if __name__ == "__main__":
    unittest.main()
