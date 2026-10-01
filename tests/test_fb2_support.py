#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""FB2（FictionBook2）格式接入测试（离线，无需 calibre）。

两块内容：
1. 格式白名单契约——上传/分片上传/追加入库（ACCEPTED_BOOK_FORMATS）、扫描导入
   （scan_service.SCAN_EXT）、MyReader 原生阅读（BookRead.READABLE_FORMATS 与
   MyReader 跳转分支）、流式取路径（BookFilePath.STREAMABLE_FORMATS）、元数据回写
   （META_WRITABLE_FORMATS，运行时由 calibre can_set_metadata 二次过滤）。
2. supplement_fb2_fields 的 XML 手术层——calibre 内置 FB2MetadataWriter 只写八项
   （lang/isbn 只读不写），写回后由本模块补写；此处验证补写位置（lang 在 sequence
   之前、isbn 在 publish-info 末尾）、幂等、双命名空间与坏输入静默跳过。

运行：python tests/test_fb2_support.py
"""

import io
import unittest

from webserver import constants
from webserver.base.book_files import FB2_NAMESPACES, _fb2_inject_fields

FB2_20 = FB2_NAMESPACES[0]

# 经 calibre set_metadata 规范化后的裸 XML fb2 形态（默认命名空间 + l: 前缀 xlink）
FB2_DOC_20 = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<FictionBook xmlns="%(ns)s" xmlns:l="http://www.w3.org/1999/xlink">'
    "<description><title-info>"
    "<genre>sf</genre>"
    "<author><first-name>A</first-name><last-name>B</last-name></author>"
    "<book-title>T</book-title>"
    "<sequence name=\"S\" number=\"1\"/>"
    "</title-info>"
    "<publish-info><publisher>OldPub</publisher></publish-info>"
    "</description>"
    "<body><section><p>hello</p></section></body>"
    "</FictionBook>"
) % {"ns": FB2_20}

# 2.1 命名空间且无 publish-info 的变体
FB2_DOC_21 = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.1">'
    "<description><title-info><book-title>T</book-title></title-info></description>"
    "<body/>"
    "</FictionBook>"
)

VALID_ISBN13 = "9780306406277"  # 标准校验位示例


def _inject(data, lang=None, isbn=None):
    stream = io.BytesIO(data.encode("utf-8"))
    changed = _fb2_inject_fields(stream, lang=lang, isbn=isbn)
    return changed, stream.getvalue().decode("utf-8")


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


class TestFB2MetaSupplement(unittest.TestCase):
    def test_lang_inserted_before_sequence_and_isbn_appended(self):
        changed, out = _inject(FB2_DOC_20, lang="ru", isbn=VALID_ISBN13)
        self.assertTrue(changed)
        self.assertIn("<lang>ru</lang>", out)
        self.assertIn("<isbn>%s</isbn>" % VALID_ISBN13, out)
        # FB2 DTD 顺序：lang 在 sequence 之前、isbn 在 publish-info 末尾
        self.assertLess(out.index("<lang>"), out.index("<sequence"))
        self.assertGreater(out.index("<isbn>"), out.index("<publisher>"))
        # 正文与既有元素原样保留，默认命名空间/xlink 前缀不变
        self.assertIn("<p>hello</p>", out)
        self.assertIn('<sequence name="S" number="1"/>', out)
        self.assertIn('xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"', out)
        self.assertIn('xmlns:l="http://www.w3.org/1999/xlink"', out)
        # XML 声明保持双引号（部分 fb2 阅读器解析不了单引号声明）
        self.assertTrue(out.startswith('<?xml version="1.0" encoding="UTF-8"?>'))

    def test_existing_lang_replaced_and_idempotent(self):
        doc = FB2_DOC_20.replace("<sequence", "<lang>en</lang><sequence")
        changed, out = _inject(doc, lang="ru", isbn=VALID_ISBN13)
        self.assertTrue(changed)
        self.assertIn("<lang>ru</lang>", out)
        self.assertNotIn("<lang>en</lang>", out)
        changed2, out2 = _inject(out, lang="ru", isbn=VALID_ISBN13)
        self.assertFalse(changed2)
        self.assertEqual(out, out2)

    def test_21_namespace_doc_supported(self):
        changed, out = _inject(FB2_DOC_21, lang="en", isbn=VALID_ISBN13)
        self.assertTrue(changed)
        self.assertIn("<lang>en</lang>", out)
        self.assertIn("<isbn>%s</isbn>" % VALID_ISBN13, out)
        # 无 publish-info 时新建，且 title-info 不存在时补建在 description 首位
        self.assertIn("<publish-info>", out)
        self.assertLess(out.index("<title-info>"), out.index("</description>"))
        self.assertNotIn("ns0:", out)

    def test_noop_when_nothing_to_write(self):
        changed, out = _inject(FB2_DOC_20, lang=None, isbn=None)
        self.assertFalse(changed)
        self.assertEqual(out, FB2_DOC_20)

    def test_invalid_xml_silently_skipped(self):
        # zip 包装（calibre 对 zip 输入会重写为 zip）或坏字节 → 静默跳过
        stream = io.BytesIO(b"PK\x03\x04not-xml")
        self.assertFalse(_fb2_inject_fields(stream, lang="ru", isbn=VALID_ISBN13))
        self.assertEqual(stream.getvalue(), b"PK\x03\x04not-xml")

    def test_non_fb2_root_skipped(self):
        changed, out = _inject(
            '<?xml version="1.0" encoding="UTF-8"?><root><description/></root>', lang="ru"
        )
        self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
