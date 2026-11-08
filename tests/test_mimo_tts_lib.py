# -*- coding: utf-8 -*-
"""mimo_tts_lib 单元测试（standalone：mimo_tts_lib 无 webserver 依赖，直接可测）。

运行：在本仓库根目录执行 `python -m pytest tests/test_mimo_tts_lib.py -q`。

覆盖 0.4.1 两个变更：
1. EPUB TOC 只登记纯图片扉页时兜底扫描全部文档（修复「未从 EPUB 中提取到
   任何章节内容」）+ TOC href 编码 / 前缀不一致的放宽匹配；
2. TXT 编码探测与行首标题切章。
"""
import os
import sys
import tempfile
import unittest
import zipfile
from urllib.parse import unquote

TMP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TMP_ROOT)

from webserver.toolbox import mimo_tts_lib as lib  # noqa: E402

CONTAINER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="content.opf" '
    'media-type="application/oebps-package+xml"/></rootfiles></container>'
)

NCX = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
    '<head><meta name="dtb:uid" content="test-uid"/></head>'
    '<docTitle><text>T</text></docTitle>'
    '<navMap>%s</navMap></ncx>'
)

OPF = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<package version="2.0" xmlns="http://www.idpf.org/2007/opf" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'unique-identifier="uid"><metadata>'
    '<dc:identifier id="uid">test-uid</dc:identifier>'
    '<dc:title>T</dc:title><dc:language>zh</dc:language>'
    '</metadata><manifest>%s</manifest>'
    '<spine toc="ncx">%s</spine></package>'
)


def _page(text=""):
    if text:
        body = "<p>%s</p>" % text
    else:
        body = '<img src="cover.jpg"/>'
    return "<?xml version='1.0' encoding='utf-8'?>" \
        "<html xmlns='http://www.w3.org/1999/xhtml'><head><title>T</title></head>" \
        "<body>%s</body></html>" % body


def _write_epub(path, docs, toc_points=None):
    """组装最小 EPUB2。docs: [(href, body_html)]；toc_points: [(label, src)]。

    zip 条目名用 href 的 URL 解码形式（真实 EPUB 惯例，ebooklib 0.19 读取时
    会对 manifest href unquote）。
    """
    manifest = ['<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>']
    spine = []
    for i, (href, _body) in enumerate(docs):
        manifest.append('<item id="d%d" href="%s" media-type="application/xhtml+xml"/>' % (i, href))
        spine.append('<itemref idref="d%d"/>' % i)
    points = "".join(
        '<navPoint id="np%d" playOrder="%d"><navLabel><text>%s</text></navLabel>'
        '<content src="%s"/></navPoint>' % (i, i + 1, label, src)
        for i, (label, src) in enumerate(toc_points or [])
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("content.opf", OPF % ("".join(manifest), "".join(spine)))
        zf.writestr("toc.ncx", NCX % points)
        for href, body in docs:
            zf.writestr(unquote(href), body)


def _usable(chapters):
    """模拟 convert() 调用方对空文本章节的过滤。"""
    return [ch for ch in chapters if ch.get("text", "").strip()]


class ExtractEpubTest(unittest.TestCase):
    def _epub(self, docs, toc_points=None):
        fd, path = tempfile.mkstemp(suffix=".epub")
        os.close(fd)
        self.addCleanup(os.remove, path)
        _write_epub(path, docs, toc_points)
        return path

    def test_toc_only_titlepage_falls_back_to_documents(self):
        # 回归：TOC 只登记纯图片扉页，正文 index.html 不在 TOC 里
        # → 0.4.0 会因唯一 TOC 章节无文本而报「未从 EPUB 中提取到任何章节内容」
        path = self._epub(
            docs=[("titlepage.xhtml", _page()), ("index.html", _page("同学们，上课！正文内容"))],
            toc_points=[("Start", "titlepage.xhtml")],
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual(len(chapters), 1)
        self.assertIn("同学们，上课", chapters[0]["text"])

    def test_normal_toc_respected(self):
        # TOC 正常：按 TOC 顺序与标题取章，不触发兜底
        path = self._epub(
            docs=[("c1.xhtml", _page("第一章正文")), ("c2.xhtml", _page("第二章正文"))],
            toc_points=[("一", "c1.xhtml"), ("二", "c2.xhtml")],
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual([ch["title"] for ch in chapters], ["一", "二"])
        self.assertIn("第一章正文", chapters[0]["text"])

    def test_empty_toc_uses_documents(self):
        path = self._epub(
            docs=[("nav.xhtml", _page("目录 目录")), ("c1.xhtml", _page("正文甲"))],
            toc_points=[],
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        titles = {ch["title"] for ch in chapters}
        self.assertIn("c1", titles)  # nav.xhtml 被跳过，c1 由文档扫描兜底
        self.assertIn("正文甲", chapters[0]["text"])

    def test_toc_href_percent_encoded(self):
        # TOC src 用百分号编码、manifest/ebooklib 侧为解码名：unquote 兜底后文本不丢
        path = self._epub(
            docs=[("chapter%201.xhtml", _page("编码章节正文"))],
            toc_points=[("Ch1", "chapter%201.xhtml")],
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual(len(chapters), 1)
        self.assertIn("编码章节正文", chapters[0]["text"])


class ExtractTxtTest(unittest.TestCase):
    def _txt(self, text, encoding="utf-8"):
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        with open(path, "wb") as f:
            f.write(text.encode(encoding))
        self.addCleanup(os.remove, path)
        return path

    def test_gbk_numbered_chapters(self):
        content = (
            "书名：测试书\n作者：某人\n" + "开头介绍内容。" * 30 + "\n"
            "第一章 起点\n正文一。\n"
            "第二章 转折\n正文二。\n"
        )
        chapters = lib.extract_txt_chapters(self._txt(content, "gbk"))
        self.assertEqual([ch["title"] for ch in chapters], ["开头", "第一章 起点", "第二章 转折"])
        self.assertIn("正文二", chapters[2]["text"])
        self.assertIn("第一章 起点", chapters[1]["text"])  # 标题行保留在正文中

    def test_no_headings_single_chapter(self):
        chapters = lib.extract_txt_chapters(self._txt("没有任何章节标题的正文。\n" * 10))
        self.assertEqual(len(chapters), 1)
        self.assertIn("没有任何章节标题的正文", chapters[0]["text"])

    def test_special_headings(self):
        content = "楔子\n楔子正文。\nChapter 1\nThe beginning.\n后记\n记于结尾。\n"
        chapters = lib.extract_txt_chapters(self._txt(content))
        self.assertEqual([ch["title"] for ch in chapters], ["楔子", "Chapter 1", "后记"])

    def test_long_line_not_heading(self):
        # 以「第一章」开头但远超标题长度的行按正文处理，不切章
        long_line = "第一章" + "这是一句很长的话。" * 20
        chapters = lib.extract_txt_chapters(self._txt(long_line + "\n后续正文。"))
        self.assertEqual(len(chapters), 1)

    def test_crlf_and_bom(self):
        content = "第一章 起点\r\n正文一。\r\n第二章 终点\r\n正文二。\r\n"
        chapters = lib.extract_txt_chapters(self._txt(content, "utf-8-sig"))
        self.assertEqual([ch["title"] for ch in chapters], ["第一章 起点", "第二章 终点"])

    def test_short_prelude_dropped(self):
        # 首个标题前只有书名/作者行（<100 字符）不生成「开头」章
        content = "测试书\n佚名\n第一章 起点\n正文。\n"
        chapters = lib.extract_txt_chapters(self._txt(content))
        self.assertEqual([ch["title"] for ch in chapters], ["第一章 起点"])


if __name__ == "__main__":
    unittest.main()
