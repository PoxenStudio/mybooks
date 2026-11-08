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


def _write_epub(path, docs, toc_points=None, spine_order=None, non_linear=(), guide=()):
    """组装最小 EPUB2。docs: [(href, body_html)]；toc_points: [(label, src)]。

    spine_order 可指定 spine 中的文档顺序（默认按 manifest 顺序），用于验证
    「兜底扫描按阅读顺序而非 manifest 顺序」；non_linear 里的文档索引写成
    ``linear="no"``（脚注 / 答案页）；guide 里的 href 写进 EPUB2 guide
    （type=toc，目录页不该被朗读）。
    zip 条目名用 href 的 URL 解码形式（真实 EPUB 惯例，ebooklib 0.19 读取时
    会对 manifest href unquote）。
    """
    manifest = ['<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>']
    for i, (href, _body) in enumerate(docs):
        manifest.append('<item id="d%d" href="%s" media-type="application/xhtml+xml"/>' % (i, href))
    order = spine_order if spine_order is not None else range(len(docs))
    spine = ["<itemref idref=\"d%d\"%s/>" % (i, ' linear="no"' if i in non_linear else "")
             for i in order]
    points = "".join(
        '<navPoint id="np%d" playOrder="%d"><navLabel><text>%s</text></navLabel>'
        '<content src="%s"/></navPoint>' % (i, i + 1, label, src)
        for i, (label, src) in enumerate(toc_points or [])
    )
    guide_xml = ""
    if guide:
        guide_xml = "<guide>%s</guide>" % "".join(
            '<reference type="toc" title="目录" href="%s"/>' % href for href in guide)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("content.opf", (OPF % ("".join(manifest), "".join(spine))).replace(
            "</package>", guide_xml + "</package>"))
        zf.writestr("toc.ncx", NCX % points)
        for href, body in docs:
            zf.writestr(unquote(href), body)


def _write_epub3_nav(path, docs, nav_ol):
    """组装 EPUB3（只有 nav 文档、没有 NCX），nav_ol 是 nav 里的 <ol> 内容。"""
    manifest = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>']
    manifest += ['<item id="d%d" href="%s" media-type="application/xhtml+xml"/>' % (i, href)
                 for i, (href, _body) in enumerate(docs)]
    spine = "".join('<itemref idref="d%d"/>' % i for i in range(len(docs)))
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="uid">test-uid</dc:identifier><dc:title>T</dc:title>'
        '<dc:language>zh</dc:language>'
        '<meta property="dcterms:modified">2026-01-01T00:00:00Z</meta></metadata>'
        '<manifest>%s</manifest><spine>%s</spine></package>' % ("".join(manifest), spine))
    nav = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>目录</title></head><body>'
        '<nav epub:type="toc"><ol>%s</ol></nav></body></html>' % nav_ol)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("content.opf", opf)
        zf.writestr("nav.xhtml", nav)
        for href, body in docs:
            zf.writestr(unquote(href), body)


def _usable(chapters):
    """模拟 convert() 调用方对空文本章节的过滤。"""
    return [ch for ch in chapters if ch.get("text", "").strip()]


class ExtractEpubTest(unittest.TestCase):
    def _epub(self, docs, toc_points=None, spine_order=None, non_linear=(), guide=()):
        fd, path = tempfile.mkstemp(suffix=".epub")
        os.close(fd)
        self.addCleanup(os.remove, path)
        _write_epub(path, docs, toc_points, spine_order, non_linear, guide)
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

    def test_toc_titlepage_with_text_still_merges_body(self):
        # 回归加固：扉页不是空的（<p>测试发音</p>）时旧实现「有文本就不兜底」
        # → 整本有声书只剩书名。TOC 覆盖正文不足一半时必须补扫
        body = "正文内容。" * 200
        path = self._epub(
            docs=[("titlepage.xhtml", _page("测试发音")),
                  ("b1.xhtml", _page(body)), ("b2.xhtml", _page(body))],
            toc_points=[("Start", "titlepage.xhtml")],
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        texts = "".join(ch["text"] for ch in chapters)
        self.assertIn("Start", [ch["title"] for ch in chapters])  # TOC 标题保留
        self.assertEqual(texts.count("正文内容"), 400)             # 两章正文都在

    def test_fallback_follows_spine_order(self):
        # 兜底扫描必须按 spine 阅读顺序：manifest=c1,c2,c3 而 spine=c3,c1,c2
        path = self._epub(
            docs=[("titlepage.xhtml", _page()), ("c1.xhtml", _page("壹")),
                  ("c2.xhtml", _page("贰")), ("c3.xhtml", _page("叁"))],
            toc_points=[("Start", "titlepage.xhtml")],
            spine_order=[3, 1, 2, 0],  # spine: c3 → c1 → c2 → titlepage
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual([ch["title"] for ch in chapters], ["c3", "c1", "c2"])

    def test_partial_toc_keeps_titles_and_appends_rest(self):
        # TOC 覆盖一章（远少于其余正文）时：保留 TOC 标题，补上未覆盖章节
        small = "短章正文。" * 10
        big = "长章正文。" * 300
        path = self._epub(
            docs=[("c0.xhtml", _page(small)), ("b1.xhtml", _page(big)), ("b2.xhtml", _page(big))],
            toc_points=[("序", "c0.xhtml")],
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual(chapters[0]["title"], "序")
        self.assertEqual(len(chapters), 3)
        self.assertTrue(chapters[1]["title"].startswith("b"))

    def test_full_toc_coverage_no_extra_chapters(self):
        # TOC 覆盖全部正文时不得把版权页 / 制作说明补成章节
        body = "正文内容。" * 200
        path = self._epub(
            docs=[("copyright.xhtml", _page("版权所有 侵权必究")),
                  ("c1.xhtml", _page(body)), ("c2.xhtml", _page(body))],
            toc_points=[("一", "c1.xhtml"), ("二", "c2.xhtml")],
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual([ch["title"] for ch in chapters], ["一", "二"])

    def test_non_spine_document_excluded(self):
        # manifest 里有、spine 里没有的文档（注释页等）不属于阅读顺序，不得成章
        path = self._epub(
            docs=[("titlepage.xhtml", _page()), ("c1.xhtml", _page("正文甲")),
                  ("notes.xhtml", _page("不在阅读顺序里的注释"))],
            toc_points=[("Start", "titlepage.xhtml")],
            spine_order=[0, 1],
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual([ch["title"] for ch in chapters], ["c1"])

    def test_fallback_interleaves_toc_chapters_in_place(self):
        # TOC 只登记中间两章：补扫章节要按 spine 插回原位，不能一律排到书尾
        body = "正文内容。" * 200
        path = self._epub(
            docs=[("c1.xhtml", _page(body)), ("c2.xhtml", _page(body)),
                  ("c3.xhtml", _page(body)), ("c4.xhtml", _page(body))],
            toc_points=[("二", "c2.xhtml"), ("三", "c3.xhtml")],
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual([ch["title"] for ch in chapters], ["c1", "二", "三", "c4"])

    def test_toc_target_outside_spine_does_not_hide_body(self):
        # TOC 指向 spine 外的附录（有 900 字）不能把覆盖率撑起来而吞掉正文
        body = "正文内容。" * 200
        path = self._epub(
            docs=[("cover.xhtml", _page()), ("c1.xhtml", _page(body)), ("c2.xhtml", _page(body)),
                  ("appendix.xhtml", _page("附录。" * 300))],
            toc_points=[("封面", "cover.xhtml"), ("附录", "appendix.xhtml")],
            spine_order=[0, 1, 2],
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual([ch["title"] for ch in chapters], ["c1", "c2"])

    def test_duplicate_toc_href_not_read_twice(self):
        # 同一文档在 TOC 里写了两种路径：只成一章，不重复朗读
        body = "正文内容。" * 200
        path = self._epub(docs=[("text/c1.xhtml", _page(body))],
                          toc_points=[("一", "text/c1.xhtml"), ("一b", "c1.xhtml")])
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual(len(chapters), 1)

    def test_ambiguous_basename_keeps_body(self):
        # basename 撞名时不猜（TOC 解析失败），但正文仍要通过补扫拿到
        path = self._epub(
            docs=[("text/c1.xhtml", _page("甲" * 100)), ("notes/c1.xhtml", _page("乙" * 10))],
            toc_points=[("一", "c1.xhtml")],
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual("".join(ch["text"] for ch in chapters).count("甲"), 100)

    def test_linear_no_document_skipped(self):
        # spine 里 linear="no" 的脚注页不念
        body = "正文内容。" * 200
        path = self._epub(
            docs=[("c1.xhtml", _page(body)), ("notes.xhtml", _page("脚注。" * 100))],
            toc_points=[("一", "c1.xhtml")],
            non_linear={1},
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual([ch["title"] for ch in chapters], ["一"])

    def test_images_only_book_returns_empty(self):
        path = self._epub(docs=[("cover.xhtml", _page())], toc_points=[("封面", "cover.xhtml")])
        self.assertEqual(_usable(lib.extract_epub_chapters(path)), [])

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

    def test_trusted_toc_still_adds_large_unlisted_doc(self):
        # TOC 覆盖 2/3（判定可信）但第 3 章 2000 字不在目录里 → 仍要补上
        body = "正文内容。" * 200
        path = self._epub(
            docs=[("c1.xhtml", _page(body)), ("c2.xhtml", _page(body)),
                  ("c3.xhtml", _page("正文内容。" * 400))],
            toc_points=[("一", "c1.xhtml"), ("二", "c2.xhtml")],
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual([ch["title"] for ch in chapters], ["一", "二", "c3"])

    def test_trusted_toc_ignores_small_backmatter(self):
        # 可信 TOC 下，几百字的版权 / 制作说明不单独成章
        body = "正文内容。" * 200
        path = self._epub(
            docs=[("colophon.xhtml", _page("版权所有。" * 15)),
                  ("c1.xhtml", _page(body)), ("c2.xhtml", _page(body))],
            toc_points=[("一", "c1.xhtml"), ("二", "c2.xhtml")],
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual([ch["title"] for ch in chapters], ["一", "二"])

    def test_nav_prefixed_chapter_name_kept(self):
        # naval_battle.xhtml 名字以 nav 开头，但 TOC 里是正常章节，不能被当导航页
        body = "正文内容。" * 200
        path = self._epub(
            docs=[("naval_battle.xhtml", _page(body)), ("c2.xhtml", _page(body))],
            toc_points=[("海战", "naval_battle.xhtml"), ("二", "c2.xhtml")],
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual([ch["title"] for ch in chapters], ["海战", "二"])

    def test_guide_toc_page_not_read(self):
        # EPUB2 guide 登记为 toc 的 contents 页即使有一千字也不进有声书
        body = "正文内容。" * 200
        path = self._epub(
            docs=[("contents.xhtml", _page("目录项 " * 200)),
                  ("c1.xhtml", _page(body)), ("c2.xhtml", _page(body))],
            toc_points=[("一", "c1.xhtml"), ("二", "c2.xhtml")],
            guide=["contents.xhtml"],
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual([ch["title"] for ch in chapters], ["一", "二"])

    def test_epub3_nested_sections_keep_titles(self):
        # EPUB3 目录用 <span> 分组时（Section 自身没有 href），子项不能整棵丢
        body = "正文内容。" * 200
        fd, path = tempfile.mkstemp(suffix=".epub")
        os.close(fd)
        self.addCleanup(os.remove, path)
        _write_epub3_nav(
            path,
            docs=[("c1.xhtml", _page(body)), ("c2.xhtml", _page(body)), ("c3.xhtml", _page(body))],
            nav_ol=('<li><span>第一卷</span><ol>'
                    '<li><a href="c1.xhtml">第一章</a></li>'
                    '<li><a href="c2.xhtml">第二章</a></li></ol></li>'
                    '<li><a href="c3.xhtml">第三章</a></li>'),
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual([ch["title"] for ch in chapters], ["第一章", "第二章", "第三章"])

    def test_empty_toc_pages_do_not_inflate_coverage(self):
        # TOC 里 10 个纯图片页（0 字）不该把「篇数」抬上去；目录外 3 个 300 字
        # 的短章仍属正文，必须补上（旧实现会判可信再用 500 字门槛全部丢掉）
        body = "正文内容。" * 200
        docs = [("c1.xhtml", _page(body))]
        toc = [("一", "c1.xhtml")]
        for i in range(10):
            href = "img%d.xhtml" % i
            docs.append((href, _page()))
            toc.append(("图%d" % i, href))
        for i in range(3):
            docs.append(("s%d.xhtml" % i, _page("短章正文。" * 60)))
        path = self._epub(docs=docs, toc_points=toc)
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual([ch["title"] for ch in chapters], ["一", "s0", "s1", "s2"])

    def test_duplicate_spine_itemref_emitted_once(self):
        # spine 里重复的 itemref（制作工具 bug）不能让同一章念两遍
        body = "正文内容。" * 200
        path = self._epub(
            docs=[("titlepage.xhtml", _page()), ("c1.xhtml", _page(body)), ("c2.xhtml", _page(body))],
            toc_points=[("Start", "titlepage.xhtml")],
            spine_order=[0, 1, 1, 2],
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual([ch["title"] for ch in chapters], ["c1", "c2"])

    def test_nav_in_subdir_skipped(self):
        # 兜底扫描按文件名（而非全路径）跳过导航页：OEBPS/nav.xhtml 不入正文
        path = self._epub(
            docs=[("OEBPS/nav.xhtml", _page("目录 目录")), ("OEBPS/c1.xhtml", _page("正文甲"))],
            toc_points=[],
        )
        chapters = _usable(lib.extract_epub_chapters(path))
        self.assertEqual([ch["title"] for ch in chapters], ["c1"])
        self.assertIn("正文甲", chapters[0]["text"])


class SoupTextTest(unittest.TestCase):
    def test_ignores_head(self):
        # <head><title>/<style> 不是正文：不参与「是否有正文」判定，也不进 TTS
        html = ("<html><head><title>书名</title>"
                "<style>.x{}</style></head><body><p>正文-only</p></body></html>").encode("utf-8")
        self.assertEqual(lib._soup_text(html), "正文-only")

    def test_no_body_falls_back(self):
        html = "<html><p>无 body 标签的正文</p></html>".encode("utf-8")
        self.assertEqual(lib._soup_text(html), "无 body 标签的正文")


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
        # 标题识别之外，正文也必须完整进章节（防「识别到标题但文本为空」回归）
        self.assertIn("楔子正文", chapters[0]["text"])
        self.assertIn("The beginning", chapters[1]["text"])
        self.assertIn("记于结尾", chapters[2]["text"])

    def test_uppercase_chapter_heading(self):
        content = "CHAPTER 1\nThe beginning.\nCHAPTER 2\nThe end.\n"
        chapters = lib.extract_txt_chapters(self._txt(content))
        self.assertEqual([ch["title"] for ch in chapters], ["CHAPTER 1", "CHAPTER 2"])
        self.assertIn("The end", chapters[1]["text"])

    def test_prose_with_sentence_punct_not_heading(self):
        # 以「第一章」开头的正文长句（含句末标点）不切章
        content = "第一章讲完了。大家休息一下。\n正文的其余部分继续。\n"
        chapters = lib.extract_txt_chapters(self._txt(content))
        self.assertEqual(len(chapters), 1)
        self.assertIn("正文的其余部分继续", chapters[0]["text"])

    def test_prose_starting_with_unit_word_not_heading(self):
        # 「第二回合」「第三部队」这类以章节单位字开头的正文，含逗号即不切章
        content = (
            "第二回合我们输了，只能认命。\n"
            "第三部队的补给到了，先搬进仓库。\n"
            "第一章 他说的那句话，我记到现在。\n"
            "Chapter 1 of the book was boring, honestly.\n"
        )
        chapters = lib.extract_txt_chapters(self._txt(content))
        self.assertEqual(len(chapters), 1)
        self.assertIn("第三部队", chapters[0]["text"])

    def test_special_heading_variants(self):
        # 番外允许直接跟序号、也允许「番外 一 后日谈」这种中间带空格的多段标题
        content = "番外 一 后日谈\n后日谈正文。\n番外篇\n番外篇正文。\n番外二\n第二个番外。\n"
        chapters = lib.extract_txt_chapters(self._txt(content))
        self.assertEqual([ch["title"] for ch in chapters],
                         ["番外 一 后日谈", "番外篇", "番外二"])
        self.assertIn("后日谈正文", chapters[0]["text"])

    def test_short_prose_with_special_word_not_heading(self):
        # 「楔子正文，从这里开始」不是标题（特殊词后必须跟分隔符）
        content = "楔子正文，从这里开始。\n后面还有别的正文。\n"
        chapters = lib.extract_txt_chapters(self._txt(content))
        self.assertEqual(len(chapters), 1)

    def test_unit_word_prose_without_punct_not_heading(self):
        # 单位字后接普通词尾（电影 / 合 / 队）时按正文；无分隔符长尾也算正文
        content = (
            "第一部电影我看过三遍\n"
            "第二回合他赢了\n"
            "第三部队的补给到了\n"
            "第一章的内容我已经忘了\n"
        )
        chapters = lib.extract_txt_chapters(self._txt(content))
        self.assertEqual(len(chapters), 1)

    def test_english_prose_with_lowercase_words_not_heading(self):
        # 「Chapter 1 is / was …」是全小写单词的正文；Title Case 标题仍要识别
        content = (
            "Chapter 1 is about a boy\n"
            "Chapter 2 was better\n"
            "Chapter 3 The Beginning\n"
            "正文。\n"
        )
        chapters = lib.extract_txt_chapters(self._txt(content))
        self.assertEqual([ch["title"] for ch in chapters], ["Chapter 3 The Beginning"])

    def test_special_heading_with_bracket_number(self):
        # 「楔子（一）」「番外（二）」这类带括号序号的标题
        content = "楔子（一）\n开头正文。\n番外（二）\n番外正文。\n"
        chapters = lib.extract_txt_chapters(self._txt(content))
        self.assertEqual([ch["title"] for ch in chapters], ["楔子（一）", "番外（二）"])

    def test_roman_chapter_heading(self):
        content = "Chapter IV\n正文一。\nChapter V\n正文二。\n"
        chapters = lib.extract_txt_chapters(self._txt(content))
        self.assertEqual([ch["title"] for ch in chapters], ["Chapter IV", "Chapter V"])

    def test_txt_size_limit(self):
        original = lib.MAX_TXT_BYTES
        lib.MAX_TXT_BYTES = 100
        try:
            with self.assertRaises(ValueError):
                lib.extract_txt_chapters(self._txt("一" * 200))
        finally:
            lib.MAX_TXT_BYTES = original

    def test_utf32_without_bom(self):
        # 无 BOM 的 UTF-32 不得被 UTF-16 NUL 启发式误判成乱码
        content = "第一章 起点\n中文正文。\n"
        chapters = lib.extract_txt_chapters(self._txt(content, "utf-32-le"))
        self.assertEqual(chapters[0]["title"], "第一章 起点")
        self.assertIn("中文正文", chapters[0]["text"])

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


class TocCoverageTest(unittest.TestCase):
    """覆盖率阈值：字数与篇数都要过半数才认为 TOC 可信（边界从严）。"""

    def test_boundary_matrix(self):
        t = lib._is_trusted_toc
        self.assertTrue(t(100, 2, 0, 0))          # TOC 全覆盖
        self.assertFalse(t(100, 2, 100, 2))       # 恰好一半 → 不可信
        self.assertTrue(t(100, 2, 99, 1))         # 字数与篇数都未过半
        self.assertFalse(t(10, 1, 1000000, 100))  # 长章掩盖不了海量短章
        self.assertFalse(t(1000, 2, 900, 3))      # 字数 90% 但缺的篇数更多
        self.assertFalse(t(0, 0, 0, 0))           # 全空
        self.assertFalse(t(0, 0, 10, 1))          # TOC 空、有正文


if __name__ == "__main__":
    unittest.main()
