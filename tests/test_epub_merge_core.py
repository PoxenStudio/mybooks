# -*- coding: utf-8 -*-
"""epub_merge 核心单元测试（standalone：epub_merge_lib 无 webserver 依赖，直接可测）。

运行：在本文件夹根目录执行 `python -m pytest tests/test_epub_merge_core.py -q`。
当前为 Phase A 范围：读取 / 定位 / 解码 / 分析 / ISBN / 简介组合。
"""
import io
import os
import re
import shutil
import struct
import sys
import tempfile
import tracemalloc
import unittest
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import quote, unquote

TMP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TMP_ROOT, "webserver", "toolbox"))

import epub_merge_lib as lib  # noqa: E402


def _build_opf(title, authors, docs, ncx=True, publisher="测试社",
               languages=("zho",), identifiers=None, resources=None):
    """组装最小 OPF。docs: [(id, href, media-type)]；spine 顺序即 docs 顺序。
    resources: 仅进 manifest 不进 spine 的资源 [(id, href, media-type)]。"""
    manifest = []
    for iid, href, mt in docs:
        manifest.append(
            '<item id="%s" href="%s" media-type="%s"/>' % (iid, href, mt))
    for iid, href, mt in (resources or []):
        manifest.append(
            '<item id="%s" href="%s" media-type="%s"/>' % (iid, href, mt))
    if ncx:
        manifest.append(
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
    spine = "".join('<itemref idref="%s"/>' % iid for iid, _h, _m in docs)
    idents = ""
    for scheme, value in (identifiers or {}).items():
        idents += '<dc:identifier opf:scheme="%s">%s</dc:identifier>' % (scheme, value)
    authors_xml = "".join(
        '<dc:creator opf:role="aut">%s</dc:creator>' % a for a in authors)
    langs_xml = "".join("<dc:language>%s</dc:language>" % lang for lang in languages)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package version="2.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="uid">'
        "<metadata>"
        '<dc:identifier id="uid">test-uid</dc:identifier>' + idents +
        "<dc:title>%s</dc:title>" % title + authors_xml +
        "<dc:publisher>%s</dc:publisher>" % publisher + langs_xml +
        "</metadata>"
        "<manifest>%s</manifest>" % "".join(manifest) +
        '<spine toc="ncx">%s</spine>' % spine +
        "</package>")


def _build_ncx(title, navpoints):
    """navpoints: [(play_order_src, label)]。"""
    items = "".join(
        '<navPoint id="np%d"><navLabel><text>%s</text></navLabel>'
        '<content src="%s"/></navPoint>' % (i, label, src)
        for i, (src, label) in enumerate(navpoints, 1))
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        "<head></head>"
        "<docTitle><text>%s</text></docTitle>" % title +
        "<navMap>%s</navMap></ncx>" % items)


def _make_epub(files: dict) -> bytes:
    """按 {zip名: bytes} 打包（mimetype 首项 STORED）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), files.get(
            "mimetype", b"application/epub+zip"), compress_type=zipfile.ZIP_STORED)
        for name, data in files.items():
            if name != "mimetype":
                zf.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def _make_min_epub(title="卷一", authors=("作者A",), n_docs=2, with_ncx=True,
                   publisher="测试社", identifiers=None, opf_dir="OEBPS",
                   mark=""):
    """构造最小合法 EPUB。mark 非空时写入正文/CSS 作区分标记。返回 bytes。"""
    container = (
        '<?xml version="1.0"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="%s/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>') % opf_dir
    docs = [("ch%d" % i, "ch%d.xhtml" % i, "application/xhtml+xml")
            for i in range(1, n_docs + 1)]
    opf = _build_opf(title, authors, docs, ncx=with_ncx, publisher=publisher,
                     identifiers=identifiers,
                     resources=[("css", "style.css", "text/css")])
    files = {
        "META-INF/container.xml": container.encode("utf-8"),
        "%s/content.opf" % opf_dir: opf.encode("utf-8"),
    }
    for i in range(1, n_docs + 1):
        files["%s/ch%d.xhtml" % (opf_dir, i)] = (
            "<html><body><p>第%d章正文%s</p></body></html>" % (i, mark)).encode("utf-8")
    css = "p { color: red; }" if not mark else "p.mark-%s { color: red; }" % mark
    files["%s/style.css" % opf_dir] = css.encode("utf-8")
    if with_ncx:
        nav = [("ch%d.xhtml" % i, "第%d章" % i) for i in range(1, n_docs + 1)]
        files["%s/toc.ncx" % opf_dir] = _build_ncx(title, nav).encode("utf-8")
    return _make_epub(files)


class TestZipReading(unittest.TestCase):
    def test_valid_reads_all(self):
        entries = lib._read_zip_entries(_make_min_epub())
        self.assertIn("mimetype", entries)
        self.assertIn("OEBPS/ch1.xhtml", entries)
        self.assertIn("OEBPS/style.css", entries)

    def test_bad_zip_raises(self):
        with self.assertRaises(ValueError):
            lib._read_zip_entries(b"not a zip at all")

    def test_traversal_entries_skipped(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("META-INF/container.xml", b"<container/>")
            zf.writestr("../../evil.txt", b"evil")
            zf.writestr("/abs.txt", b"abs")
        entries = lib._read_zip_entries(buf.getvalue())
        self.assertIn("META-INF/container.xml", entries)
        self.assertNotIn("../../evil.txt", entries)
        self.assertNotIn("/abs.txt", entries)

    def test_entries_limit(self):
        data = _make_min_epub(n_docs=3)
        with self.assertRaises(ValueError):
            lib._read_zip_entries(data, max_entries=3)

    def test_declared_total_limit(self):
        data = _make_min_epub()
        with self.assertRaises(ValueError):
            lib._read_zip_entries(data, max_total=10)

    def test_no_single_input_cap(self):
        # 需求：不设单本上限（50MB+ 合集常见），总量上限仍生效
        self.assertFalse(hasattr(lib, "_ZIP_MAX_SINGLE"))
        data = _make_min_epub()
        lib._read_zip_entries(data, max_total=10 * 1024 * 1024)

    def test_read_meta_entries_only_meta(self):
        files = {
            "META-INF/container.xml": (
                '<?xml version="1.0"?><container version="1.0" '
                'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                'media-type="application/oebps-package+xml"/></rootfiles></container>'
            ).encode(),
        }
        data = _make_min_epub()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for n in ("OEBPS/content.opf", "OEBPS/ch1.xhtml", "OEBPS/style.css",
                      "OEBPS/toc.ncx"):
                files[n] = zf.read(n)
        files["OEBPS/font.ttf"] = b"\x00" * 100
        packed = _make_epub(files)
        meta, names_view = lib._read_meta_entries(packed)
        # 仅 container/OPF/NCX 解压内容，正文与资源只占名字
        self.assertIn("META-INF/container.xml", meta)
        self.assertIn("OEBPS/content.opf", meta)
        self.assertIn("OEBPS/toc.ncx", meta)
        self.assertNotIn("OEBPS/ch1.xhtml", meta)
        self.assertNotIn("OEBPS/style.css", meta)
        self.assertNotIn("OEBPS/font.ttf", meta)
        self.assertEqual(names_view["OEBPS/ch1.xhtml"], b"")
        self.assertIn("OEBPS/font.ttf", names_view)


class TestLiteAnalyze(unittest.TestCase):
    def test_lite_matches_full(self):
        data = _make_min_epub(title="卷一", authors=("作者A",), n_docs=2,
                              identifiers={"ISBN": "978-7-123-45678-9"})
        full = lib.analyze_epub(data)
        lite = lib.analyze_epub(data, lite=True)
        for key in ("title", "authors", "publisher", "languages", "isbns",
                    "spine_count", "toc_count", "size", "warnings"):
            self.assertEqual(full[key], lite[key], key)

    def test_lite_bad_zip_raises(self):
        with self.assertRaises(ValueError):
            lib.analyze_epub(b"garbage", lite=True)

    def test_lite_missing_container_raises(self):
        with self.assertRaises(ValueError):
            lib.analyze_epub(_make_epub({"x.txt": b"hi"}), lite=True)


class TestSpineFinding(unittest.TestCase):
    def test_spine_order(self):
        entries = lib._read_zip_entries(_make_min_epub(n_docs=3))
        spine = lib._find_spine_entries(entries)
        self.assertEqual(spine, ["OEBPS/ch1.xhtml", "OEBPS/ch2.xhtml", "OEBPS/ch3.xhtml"])

    def test_dot_and_dotdot_hrefs(self):
        data = _make_min_epub(n_docs=1)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            opf = zf.read("OEBPS/content.opf").decode("utf-8")
        opf = opf.replace('href="ch1.xhtml"', 'href="./Text/../ch1.xhtml"')
        files = {}
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                if not info.is_dir() and info.filename != "OEBPS/content.opf":
                    files[info.filename] = zf.read(info.filename)
        files["OEBPS/content.opf"] = opf.encode("utf-8")
        entries = lib._read_zip_entries(_make_epub(files))
        self.assertEqual(lib._find_spine_entries(entries), ["OEBPS/ch1.xhtml"])

    def test_case_insensitive_match(self):
        data = _make_min_epub(n_docs=1)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            opf = zf.read("OEBPS/content.opf").decode("utf-8")
        opf = opf.replace('href="ch1.xhtml"', 'href="CH1.XHTML"')
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            files = {info.filename: zf.read(info.filename)
                     for info in zf.infolist() if not info.is_dir()}
        files["OEBPS/content.opf"] = opf.encode("utf-8")
        entries = lib._read_zip_entries(_make_epub(files))
        self.assertEqual(lib._find_spine_entries(entries), ["OEBPS/ch1.xhtml"])

    def test_missing_container_returns_empty(self):
        self.assertEqual(lib._find_spine_entries({"a": b"b"}), [])


class TestDecode(unittest.TestCase):
    def test_utf8(self):
        self.assertEqual(lib._decode("中文".encode("utf-8")), "中文")

    def test_gb18030_fallback(self):
        self.assertEqual(lib._decode("中文".encode("gb18030")), "中文")

    def test_replace_fallback(self):
        text = lib._decode(b"\xff\xff abc")
        self.assertIn("abc", text)

    def _with_fake_detector(self, decode_with_report):
        """注入假检测器（含 `utils` 父包，`__import__` 先导父包才查得到子模块）。
        返回供 with 语句用的 patcher。

        两个包路径都要替换：`webserver.toolbox.utils.encoding_detect` 是生产路径
        （clone 里真实存在，只替换 `utils.encoding_detect` 会被真实模块抢先命中），
        `utils.encoding_detect` 是 standalone 单测路径。
        """
        import sys
        import types
        from unittest import mock

        def _pkg(name):
            mod = types.ModuleType(name)
            mod.__path__ = []
            return mod

        def _fake(name):
            mod = types.ModuleType(name)
            mod.decode_with_report = decode_with_report
            return mod

        return mock.patch.dict(sys.modules, {
            "utils": _pkg("utils"),
            "utils.encoding_detect": _fake("utils.encoding_detect"),
            "webserver.toolbox.utils": _pkg("webserver.toolbox.utils"),
            "webserver.toolbox.utils.encoding_detect":
                _fake("webserver.toolbox.utils.encoding_detect"),
        })

    def test_detector_preferred_when_clean(self):
        # 站内检测器可用且判干净时优先采用（防 Big5 被 gb18030 静默错译）；
        # 用假模块验证接线，不依赖检测器真实质量
        with self._with_fake_detector(
                lambda data: ("DETECTOR", {"encoding": "big5", "garbage": False,
                                           "unrecoverable": False})):
            self.assertEqual(lib._decode("中文".encode("big5")), "DETECTOR")

    def test_detector_garbage_falls_back(self):
        # 检测器判垃圾时回退逐编码试解，不采用其输出
        with self._with_fake_detector(
                lambda data: ("GARBAGE", {"garbage": True,
                                          "unrecoverable": False})):
            self.assertEqual(lib._decode("中文".encode("gb18030")), "中文")

    def test_detector_non_gb_big5_pick_ignored(self):
        # 检测器偶把纯 GB 长文本判为 euc_kr（干净高置信）：只采纳 GB/Big5 系
        # 结论，其余回退试解，避免简体章节被永久写成韩文乱码
        with self._with_fake_detector(
                lambda data: ("한글", {"encoding": "euc_kr", "garbage": False,
                                      "unrecoverable": False,
                                      "confidence": 1.0})):
            self.assertEqual(lib._decode("中文".encode("gb18030")), "中文")


class TestAnalyze(unittest.TestCase):
    def test_fields(self):
        data = _make_min_epub(
            title="卷一", authors=("作者A", "作者B"), n_docs=2,
            identifiers={"ISBN": "978-7-123-45678-9"})
        info = lib.analyze_epub(data)
        self.assertEqual(info["title"], "卷一")
        self.assertEqual(info["authors"], ["作者A", "作者B"])
        self.assertEqual(info["publisher"], "测试社")
        self.assertEqual(info["languages"], ["zho"])
        self.assertEqual(info["isbns"], ["978-7-123-45678-9"])
        self.assertEqual(info["spine_count"], 2)
        self.assertEqual(info["toc_count"], 2)
        self.assertEqual(info["size"], len(data))
        self.assertEqual(info["warnings"], [])

    def test_no_ncx_warning(self):
        info = lib.analyze_epub(_make_min_epub(with_ncx=False))
        self.assertEqual(info["toc_count"], 0)
        self.assertTrue(any("NCX" in w for w in info["warnings"]))

    def test_empty_input_raises(self):
        with self.assertRaises(ValueError):
            lib.analyze_epub(b"")

    def test_missing_container_raises(self):
        with self.assertRaises(ValueError):
            lib.analyze_epub(_make_epub({"x.txt": b"hi"}))

    def test_creator_role_filter(self):
        docs = [("ch1", "ch1.xhtml", "application/xhtml+xml")]
        opf = _build_opf("卷", ["作者A"], docs, ncx=False)
        opf = opf.replace(
            '<dc:creator opf:role="aut">作者A</dc:creator>',
            '<dc:creator opf:role="aut">作者A</dc:creator>'
            '<dc:creator opf:role="ill">插画B</dc:creator>')
        self.assertEqual(lib._parse_opf_meta(opf)["authors"], ["作者A"])
        # 无 role 声明时降级全收；全非 aut 时同样降级全收
        no_role = re.sub(r' opf:role="aut"', "", opf)
        self.assertEqual(lib._parse_opf_meta(no_role)["authors"], ["作者A"])
        only_ill = _build_opf("卷", [], docs, ncx=False).replace(
            "</metadata>",
            '<dc:creator opf:role="ill">插画B</dc:creator></metadata>')
        self.assertEqual(lib._parse_opf_meta(only_ill)["authors"], ["插画B"])


class TestIsbn(unittest.TestCase):
    def test_valid_13(self):
        self.assertTrue(lib.is_valid_isbn("978-7-123-45678-9"))

    def test_valid_13_spaces(self):
        self.assertTrue(lib.is_valid_isbn("978 7 123 45678 9"))

    def test_valid_10(self):
        self.assertTrue(lib.is_valid_isbn("7-123-45678-1"))

    def test_invalid(self):
        self.assertFalse(lib.is_valid_isbn("abc"))
        self.assertFalse(lib.is_valid_isbn("12345"))
        self.assertFalse(lib.is_valid_isbn(""))


class TestComposeDescription(unittest.TestCase):
    def test_basic(self):
        html_out = lib.compose_description(
            "A，B合集",
            [{"title": "A", "comments": "<p>简介A</p>"},
             {"title": "B", "comments": ""}],
            isbns=["9780000000001"])
        self.assertIn("<b>A，B合集</b>", html_out)
        self.assertIn("【A】", html_out)
        self.assertIn("<p>简介A</p>", html_out)
        self.assertIn("【B】", html_out)
        self.assertIn("暂无简介", html_out)
        self.assertNotIn("ISBN", html_out)

    def test_title_escaped(self):
        html_out = lib.compose_description(
            "<script>&", [{"title": "A<b>", "comments": "x"}])
        self.assertIn("&lt;script&gt;&amp;", html_out)
        self.assertIn("A&lt;b&gt;", html_out)
        self.assertNotIn("<script>", html_out)

    def test_plain_text_comments_br(self):
        html_out = lib.compose_description(
            "合集", [{"title": "A", "comments": "第一行\n第二行"}])
        self.assertIn("第一行<br />第二行", html_out)

    def test_isbn_tail_multi(self):
        html_out = lib.compose_description(
            "合集", [{"title": "A", "comments": "x"}],
            isbns=["9780000000001", "9780000000002"])
        self.assertIn("ISBN：9780000000001 / 9780000000002", html_out)


class TestMerge(unittest.TestCase):
    def _merge_two(self, reverse=False, **kw):
        b1 = _make_min_epub(title="卷一", authors=("作者A",), n_docs=2)
        b2 = _make_min_epub(title="卷二", authors=("作者B",), n_docs=2)
        inputs = [{"data": b1, "title": "卷一"}, {"data": b2, "title": "卷二"}]
        if reverse:
            inputs = inputs[::-1]
        meta = {"title": "卷一，卷二合集", "authors": ["作者A", "作者B"],
                "languages": ["zho"], "tags": ["科幻"],
                "description": "<p><b>卷一，卷二合集</b></p>",
                "publisher": "测试社"}
        out = lib.merge_epubs(inputs, meta, kw.get("options"))
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            entries = {i.filename: zf.read(i.filename) for i in zf.infolist()}
        return out, entries

    def test_order_and_metadata(self):
        out, entries = self._merge_two(reverse=True)
        names = [n for n in entries if n.endswith(".xhtml")]
        # 输入顺序优先：卷二（b0）在前
        self.assertTrue(names[0].startswith("b0/"))
        div0 = entries["b0_divider.xhtml"].decode("utf-8")
        self.assertIn("卷二", div0)
        opf = entries["content.opf"].decode("utf-8")
        self.assertIn("<dc:title>卷一，卷二合集</dc:title>", opf)
        # round-trip：输出本身可被 analyze
        info = lib.analyze_epub(out)
        self.assertEqual(info["title"], "卷一，卷二合集")
        self.assertEqual(info["spine_count"], 6)  # 2+2 正文 + 2 分卷

    def test_no_divider(self):
        out, entries = self._merge_two(options={"divider": False})
        self.assertFalse([n for n in entries if "divider" in n])
        self.assertEqual(lib.analyze_epub(out)["spine_count"], 4)

    def test_resource_collision(self):
        b1 = _make_min_epub(title="卷一", n_docs=1, mark="A")
        b2 = _make_min_epub(title="卷二", n_docs=1, mark="B")
        out = lib.merge_epubs(
            [{"data": b1, "title": "卷一"}, {"data": b2, "title": "卷二"}],
            {"title": "合集", "authors": ["作者"]})
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            entries = {i.filename: zf.read(i.filename) for i in zf.infolist()}
        self.assertIn("mark-A", entries["b0/OEBPS/style.css"].decode("utf-8"))
        self.assertIn("mark-B", entries["b1/OEBPS/style.css"].decode("utf-8"))
        self.assertIn("第1章正文A", entries["b0/OEBPS/ch1.xhtml"].decode("utf-8"))
        self.assertIn("第1章正文B", entries["b1/OEBPS/ch1.xhtml"].decode("utf-8"))

    def _make_ref_book(self):
        container = (
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>')
        docs = [("ch1", "ch1.xhtml", "application/xhtml+xml"),
                ("ch2", "ch2.xhtml", "application/xhtml+xml")]
        opf = _build_opf("特殊", ["作者"], docs, ncx=False)
        doc1 = ('<html><body><p id="p1">段</p><a href="#p1">跳</a>'
                '<a href="ch2.xhtml#p2">去</a>'
                '<a href="https://example.com/x">外</a>'
                '<img src="/OEBPS/img.png"/></body></html>')
        doc2 = '<html><body><p id="p2">段二</p></body></html>'
        return _make_epub({
            "META-INF/container.xml": container.encode("utf-8"),
            "OEBPS/content.opf": opf.encode("utf-8"),
            "OEBPS/ch1.xhtml": doc1.encode("utf-8"),
            "OEBPS/ch2.xhtml": doc2.encode("utf-8"),
            "OEBPS/img.png": b"\x89PNG-fake",
        })

    def _merge_ref(self, **kw):
        b1 = self._make_ref_book()
        b2 = _make_min_epub(title="卷二", n_docs=1)
        out = lib.merge_epubs(
            [{"data": b1, "title": "特殊"}, {"data": b2, "title": "卷二"}],
            {"title": "合集", "authors": ["作者"]}, kw.get("options"))
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            return {i.filename: zf.read(i.filename) for i in zf.infolist()}

    def test_ids_fragments_untouched(self):
        # id/name/#frag 不改名（各书分属不同文档，无跨书碰撞；改名反而单边
        # 破坏 <style> #id 选择器与脚本引用），文件部分映射照常
        entries = self._merge_ref()
        doc = entries["b0/OEBPS/ch1.xhtml"].decode("utf-8")
        self.assertIn('id="p1"', doc)
        self.assertIn('href="#p1"', doc)
        self.assertIn('href="ch2.xhtml#p2"', doc)

    def test_root_absolute_and_external(self):
        entries = self._merge_ref()
        doc = entries["b0/OEBPS/ch1.xhtml"].decode("utf-8")
        self.assertIn('src="img.png"', doc)
        self.assertIn('href="https://example.com/x"', doc)
        self.assertIn("b0/OEBPS/img.png", entries)

    def test_ncx_parents_playorder(self):
        _out, entries = self._merge_two()
        ncx = entries["toc.ncx"].decode("utf-8")
        orders = [int(x) for x in re.findall(r'playOrder="(\d+)"', ncx)]
        self.assertEqual(orders, [1, 2, 3, 4, 5, 6])
        self.assertIn("卷一", ncx)
        self.assertIn("卷二", ncx)

    def test_ncx_parent_points_to_divider(self):
        # 开分卷页时父节点 content 应指向分卷页（卷名页），而非首篇正文
        _out, entries = self._merge_two()
        root = ET.fromstring(entries["toc.ncx"])
        ns = "{http://www.daisy.org/z3986/2005/ncx/}"
        parents = root.find("%snavMap" % ns)
        srcs = [np.find(ns + "content").get("src") for np in parents]
        self.assertEqual(srcs, ["b0_divider.xhtml", "b1_divider.xhtml"])
        self.assertEqual(lib.validate_output(_out), [])

    def test_no_ncx_fallback(self):
        b1 = _make_min_epub(title="卷一", n_docs=1, with_ncx=False)
        b2 = _make_min_epub(title="卷二", n_docs=1, with_ncx=False)
        out = lib.merge_epubs(
            [{"data": b1, "title": "卷一"}, {"data": b2, "title": "卷二"}],
            {"title": "合集", "authors": ["作者"]})
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            ncx = zf.read("toc.ncx").decode("utf-8")
        self.assertIn("卷一", ncx)
        self.assertIn("卷二", ncx)

    def test_cover_embed(self):
        _out, entries = self._merge_two(
            options={"cover": {"data": b"\x89PNG-fake", "ext": "png"}})
        self.assertIn("cover.png", entries)
        opf = entries["content.opf"].decode("utf-8")
        self.assertIn('id="cover-image"', opf)
        self.assertIn('name="cover"', opf)
        self.assertIn("<guide>", opf)

    def test_empty_spine_raises(self):
        opf = _build_opf("空书", ["作者"], [], ncx=False)
        container = (
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>')
        bad = _make_epub({"META-INF/container.xml": container.encode(),
                          "OEBPS/content.opf": opf.encode()})
        good = _make_min_epub(title="卷二", n_docs=1)
        with self.assertRaises(ValueError):
            lib.merge_epubs([{"data": bad, "title": "空书"},
                             {"data": good, "title": "卷二"}],
                            {"title": "合集", "authors": ["作者"]})

    def test_input_count_bounds(self):
        good = _make_min_epub(title="卷", n_docs=1)
        with self.assertRaises(ValueError):
            lib.merge_epubs([{"data": good, "title": "卷"}],
                            {"title": "合集", "authors": []})
        many = [{"data": good, "title": "卷%d" % i} for i in range(21)]
        with self.assertRaises(ValueError):
            lib.merge_epubs(many, {"title": "合集", "authors": []})

    def test_meta_subjects_description(self):
        _out, entries = self._merge_two()
        opf = entries["content.opf"].decode("utf-8")
        self.assertIn("<dc:subject>科幻</dc:subject>", opf)
        m = re.search(r"<dc:description>(.*?)</dc:description>", opf)
        self.assertIsNotNone(m)
        self.assertNotIn("<p>", m.group(1))
        self.assertIn("卷一，卷二合集", m.group(1))

    def test_output_valid_zip(self):
        out, _entries = self._merge_two()
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            self.assertIsNone(zf.testzip())
            first = zf.infolist()[0]
            self.assertEqual(first.filename, "mimetype")
            self.assertEqual(first.compress_type, zipfile.ZIP_STORED)

    def test_source_ncx_excluded(self):
        _out, entries = self._merge_two()
        ncx_files = [n for n in entries if n.endswith(".ncx")]
        self.assertEqual(ncx_files, ["toc.ncx"])

    def test_roundtrip_toc_count(self):
        out, entries = self._merge_two()
        ncx = entries["toc.ncx"].decode("utf-8")
        expect = len(re.findall(r"<navPoint", ncx))
        self.assertGreater(expect, 0)
        self.assertEqual(lib.analyze_epub(out)["toc_count"], expect)

    def test_loose_skips_container_files(self):
        _out, entries = self._merge_two()
        self.assertFalse([n for n in entries if "/mimetype" in n])
        self.assertFalse([n for n in entries
                          if n.startswith("b") and "/META-INF/" in n])
        self.assertIn("META-INF/container.xml", entries)

    def test_opf_namespaces_and_spine_toc(self):
        # 回归：metadata 缺 xmlns:dc 会导致严格解析器读不到书名（EbookLib KeyError）
        _out, entries = self._merge_two()
        root = ET.fromstring(entries["content.opf"])
        ns = {"opf": "http://www.idpf.org/2007/opf",
              "dc": "http://purl.org/dc/elements/1.1/"}
        title = root.find("./opf:metadata/dc:title", ns)
        self.assertIsNotNone(title)
        self.assertEqual(title.text, "卷一，卷二合集")
        creators = root.findall("./opf:metadata/dc:creator", ns)
        self.assertEqual([c.text for c in creators], ["作者A", "作者B"])
        spine = root.find("./opf:spine", ns)
        toc_id = spine.get("toc")
        ncx_item = root.find("./opf:manifest/opf:item[@id='%s']" % toc_id, ns)
        self.assertIsNotNone(ncx_item)
        self.assertEqual(ncx_item.get("media-type"), "application/x-dtbncx+xml")

    def test_ncx_uid_and_playorder_unique(self):
        _out, entries = self._merge_two()
        root = ET.fromstring(entries["toc.ncx"])
        ns = {"ncx": "http://www.daisy.org/z3986/2005/ncx/"}
        uid = root.find("./ncx:head/ncx:meta[@name='dtb:uid']", ns)
        self.assertIsNotNone(uid)
        self.assertTrue(uid.get("content"))
        orders = [int(n.get("playOrder"))
                  for n in root.iter("{http://www.daisy.org/z3986/2005/ncx/}navPoint")]
        self.assertEqual(sorted(orders), list(range(1, len(orders) + 1)))

    def _repack(self, out, drop=None, patch_opf=None, patch_ncx=None):
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            items = [(i, zf.read(i.filename)) for i in zf.infolist()
                     if not i.is_dir() and i.filename != (drop or "\0")]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for i, data in items:
                if i.filename == "content.opf" and patch_opf:
                    data = patch_opf(data)
                if i.filename == "toc.ncx" and patch_ncx:
                    data = patch_ncx(data)
                info = zipfile.ZipInfo(i.filename)
                info.compress_type = i.compress_type
                zf.writestr(info, data)
        return buf.getvalue()

    def test_validate_ok(self):
        out, _entries = self._merge_two()
        self.assertEqual(lib.validate_output(out), [])

    def test_validate_bad_zip(self):
        with self.assertRaises(ValueError):
            lib.validate_output(b"nope")

    def test_validate_missing_file(self):
        out, _entries = self._merge_two()
        bad = self._repack(out, drop="b0/OEBPS/ch1.xhtml")
        with self.assertRaises(ValueError):
            lib.validate_output(bad)

    def test_validate_no_dc_namespace(self):
        # 回归：metadata 缺 xmlns:dc 即打不开，必须拦下
        out, _entries = self._merge_two()

        def _strip_ns(data):
            return data.replace(
                b'xmlns:dc="http://purl.org/dc/elements/1.1/" ', b"")
        with self.assertRaises(ValueError):
            lib.validate_output(self._repack(out, patch_opf=_strip_ns))

    def test_validate_dup_playorder(self):
        out, _entries = self._merge_two()

        def _dup(data):
            return data.replace(b'playOrder="2"', b'playOrder="1"', 1)
        with self.assertRaises(ValueError):
            lib.validate_output(self._repack(out, patch_ncx=_dup))


class TestReviewFixes(unittest.TestCase):
    """2026-09-05 review 修复项的回归用例。"""

    CONTAINER = (
        '<?xml version="1.0"?><container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>')

    def _pack(self, files: dict) -> bytes:
        files.setdefault("META-INF/container.xml", self.CONTAINER.encode("utf-8"))
        return _make_epub(files)

    def _merge_two_first(self, first_data: bytes, first_title="卷一") -> bytes:
        second = _make_min_epub(title="卷二", n_docs=1)
        return lib.merge_epubs(
            [{"data": first_data, "title": first_title},
             {"data": second, "title": "卷二"}],
            {"title": "合集", "authors": ["作者"]})

    def test_data_attrs_not_touched(self):
        # `\b` 挡不住 `data-id`/`data-src`（`-` 是非词字符），lookbehind 生效才行
        opf = _build_opf("卷", ["作者"],
                         [("ch1", "ch1.xhtml", "application/xhtml+xml")], ncx=False)
        doc = ('<html><body><p id="p1" data-id="p1" data-src="img.png">段</p>'
               '<a name="anchor">跳</a></body></html>')
        data = self._pack({
            "OEBPS/content.opf": opf.encode("utf-8"),
            "OEBPS/ch1.xhtml": doc.encode("utf-8"),
        })
        out = self._merge_two_first(data)
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            doc_out = zf.read("b0/OEBPS/ch1.xhtml").decode("utf-8")
        # id/name 不改名（文档内作用域），data-* 照常不受影响
        self.assertIn('id="p1"', doc_out)
        self.assertIn('name="anchor"', doc_out)
        self.assertIn('data-id="p1"', doc_out)
        self.assertIn('data-src="img.png"', doc_out)

    def test_style_script_comment_cdata_untouched(self):
        # <style> #id 选择器、脚本内同文档引用、注释/CDATA 文本一律原样保留
        opf = _build_opf("卷", ["作者"],
                         [("ch1", "ch1.xhtml", "application/xhtml+xml")], ncx=False)
        doc = ('<html><head><style>#p1 { color: red; }</style></head><body>'
               '<p id="p1">段</p><a href="#p1">跳</a>'
               '<script>var u = "ch1.xhtml#p1";</script>'
               '<!-- href="/OEBPS/gone.xhtml" -->'
               '<p><![CDATA[href="/OEBPS/gone.xhtml"]]></p>'
               '</body></html>')
        data = self._pack({
            "OEBPS/content.opf": opf.encode("utf-8"),
            "OEBPS/ch1.xhtml": doc.encode("utf-8"),
        })
        out = self._merge_two_first(data)
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            doc_out = zf.read("b0/OEBPS/ch1.xhtml").decode("utf-8")
        self.assertIn("#p1 { color: red; }", doc_out)
        self.assertIn('id="p1"', doc_out)
        self.assertIn('href="#p1"', doc_out)
        self.assertIn('var u = "ch1.xhtml#p1";', doc_out)
        self.assertIn('<!-- href="/OEBPS/gone.xhtml" -->', doc_out)
        self.assertIn('<![CDATA[href="/OEBPS/gone.xhtml"]]>', doc_out)

    def test_gbk_decl_normalized(self):
        # GBK 源文档按 utf-8 重编码后，XML 声明必须同步改写
        opf = _build_opf("卷", ["作者"],
                         [("ch1", "ch1.xhtml", "application/xhtml+xml")], ncx=False)
        doc = ('<?xml version="1.0" encoding="gb18030"?>'
               "<html><body><p>中文正文</p></body></html>")
        data = self._pack({
            "OEBPS/content.opf": opf.encode("utf-8"),
            "OEBPS/ch1.xhtml": doc.encode("gb18030"),
        })
        out = self._merge_two_first(data)
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            doc_out = zf.read("b0/OEBPS/ch1.xhtml").decode("utf-8")
        self.assertIn('encoding="utf-8"', doc_out)
        self.assertIn("中文正文", doc_out)
        self.assertNotIn("gb18030", doc_out)

    def test_epub3_nav_skipped(self):
        opf = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<package version="3.0" xmlns="http://www.idpf.org/2007/opf" '
            'unique-identifier="uid">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:identifier id="uid">u</dc:identifier>'
            "<dc:title>卷</dc:title><dc:language>zho</dc:language></metadata>"
            "<manifest>"
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
            'properties="nav"/>'
            '<item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
            "</manifest>"
            '<spine><itemref idref="nav"/><itemref idref="ch1"/></spine></package>')
        data = self._pack({
            "OEBPS/content.opf": opf.encode("utf-8"),
            "OEBPS/nav.xhtml": "<html><body><ol><li>目录</li></ol></body></html>".encode("utf-8"),
            "OEBPS/ch1.xhtml": b"<html><body><p>body</p></body></html>",
        })
        out = self._merge_two_first(data)
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            entries = {i.filename: zf.read(i.filename) for i in zf.infolist()}
        # nav 页不进包：ch1+分卷 ×2 = 4
        self.assertFalse([n for n in entries if "nav.xhtml" in n])
        self.assertEqual(lib.analyze_epub(out)["spine_count"], 4)
        self.assertEqual(lib.validate_output(out), [])

    def test_hash_encoded_href(self):
        # 文件名里的 %23 应在切掉 fragment 之后再解码
        opf = _build_opf("卷", ["作者"],
                         [("ch1", "a%23b.xhtml", "application/xhtml+xml")], ncx=False)
        data = self._pack({
            "OEBPS/content.opf": opf.encode("utf-8"),
            "OEBPS/a#b.xhtml": "<html><body><p>哈</p></body></html>".encode("utf-8"),
        })
        self.assertEqual(
            lib._find_spine_entries(lib._read_zip_entries(data)),
            ["OEBPS/a#b.xhtml"])

    def test_ncx_content_extra_attrs(self):
        # <content> 带其他属性时目录条目不得丢失
        b1 = _make_min_epub(title="卷一", n_docs=1)
        with zipfile.ZipFile(io.BytesIO(b1)) as zf:
            files = {i.filename: zf.read(i.filename)
                     for i in zf.infolist() if not i.is_dir()}
        files["OEBPS/toc.ncx"] = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
            "<head></head><docTitle><text>卷一</text></docTitle><navMap>"
            '<navPoint id="np1" playOrder="1"><navLabel><text>第1章</text></navLabel>'
            '<content id="c1" src="ch1.xhtml"/></navPoint>'
            "</navMap></ncx>").encode("utf-8")
        b1 = _make_epub(files)
        out = self._merge_two_first(b1)
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            ncx = zf.read("toc.ncx").decode("utf-8")
        self.assertIn("第1章", ncx)

    def test_input_total_cap(self):
        b1 = _make_min_epub(title="卷一", n_docs=1)
        b2 = _make_min_epub(title="卷二", n_docs=1)
        old = lib.MERGE_MAX_INPUT_TOTAL
        lib.MERGE_MAX_INPUT_TOTAL = 10
        try:
            with self.assertRaises(ValueError):
                lib.merge_epubs(
                    [{"data": b1, "title": "卷一"}, {"data": b2, "title": "卷二"}],
                    {"title": "合集", "authors": ["作者"]})
        finally:
            lib.MERGE_MAX_INPUT_TOTAL = old


def _make_cover_book(items_xml, files, guide=""):
    """构造带封面线索的书。items_xml 为 manifest 内条目片段。"""
    container = (
        '<?xml version="1.0"?><container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>')
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package version="2.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="uid">'
        "<metadata><dc:identifier id=\"uid\">u</dc:identifier>"
        "<dc:title>T</dc:title></metadata>"
        "<manifest>%s</manifest>"
        '<spine><itemref idref="ch1"/></spine>%s</package>') % (items_xml, guide)
    base = {"META-INF/container.xml": container.encode("utf-8"),
            "OEBPS/content.opf": opf.encode("utf-8"),
            "OEBPS/ch1.xhtml": b"<html><body><p>x</p></body></html>"}
    base.update(files)
    return _make_epub(base)


class TestExtractCover(unittest.TestCase):
    X = ("<item id=\"ch1\" href=\"ch1.xhtml\" media-type=\"application/xhtml+xml\"/>"
         "<item id=\"a\" href=\"a.png\" media-type=\"image/png\"/>")

    def test_properties_wins(self):
        items = self.X + ("<item id=\"c\" href=\"cov.jpg\" media-type=\"image/jpeg\" "
                          "properties=\"cover-image\"/>")
        data = _make_cover_book(items, {"OEBPS/a.png": b"OTHER",
                                        "OEBPS/cov.jpg": b"COVER"})
        self.assertEqual(lib.extract_cover(data), (b"COVER", "jpg"))

    def test_id_fallback(self):
        items = self.X.replace(
            "<item id=\"a\"",
            "<item id=\"cover\"").replace("a.png", "cov.png")
        data = _make_cover_book(items, {"OEBPS/cov.png": b"COVER"})
        self.assertEqual(lib.extract_cover(data), (b"COVER", "png"))

    def test_guide_fallback(self):
        guide = ("<guide><reference type=\"cover\" title=\"Cover\" "
                 "href=\"g.jpeg\"/></guide>")
        data = _make_cover_book(self.X, {"OEBPS/a.png": b"OTHER",
                                         "OEBPS/g.jpeg": b"GUIDE"}, guide)
        self.assertEqual(lib.extract_cover(data), (b"GUIDE", "jpeg"))

    def test_first_image_fallback(self):
        data = _make_cover_book(self.X, {"OEBPS/a.png": b"OTHER"})
        self.assertEqual(lib.extract_cover(data), (b"OTHER", "png"))

    def test_none_and_broken(self):
        data = _make_cover_book(
            "<item id=\"ch1\" href=\"ch1.xhtml\" "
            "media-type=\"application/xhtml+xml\"/>", {})
        self.assertEqual(lib.extract_cover(data), (None, None))
        self.assertEqual(lib.extract_cover(b"garbage"), (None, None))


def _make_epub3(title="卷", n_docs=2, nav=True):
    """构造 EPUB3 书：nav 页带 properties="nav"，无 NCX。"""
    container = (
        '<?xml version="1.0"?><container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>')
    docs = "".join('<item id="c%d" href="ch%d.xhtml" '
                   'media-type="application/xhtml+xml"/>' % (i, i)
                   for i in range(1, n_docs + 1))
    nav_item = ('<item id="nav" href="nav.xhtml" '
                'media-type="application/xhtml+xml" properties="nav"/>'
                if nav else "")
    spine = ("<itemref idref=\"nav\"/>" if nav else "") + "".join(
        '<itemref idref="c%d"/>' % i for i in range(1, n_docs + 1))
    opf = ('<?xml version="1.0" encoding="utf-8"?><package version="3.0" '
           'xmlns="http://www.idpf.org/2007/opf" unique-identifier="uid">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           '<dc:identifier id="uid">u</dc:identifier><dc:title>%s</dc:title>'
           '<dc:language>zho</dc:language></metadata><manifest>%s%s</manifest>'
           '<spine>%s</spine></package>') % (title, nav_item, docs, spine)
    lis = "".join('<li><a href="ch%d.xhtml">第%d章</a></li>' % (i, i)
                  for i in range(1, n_docs + 1))
    nav_doc = ('<html xmlns="http://www.w3.org/1999/xhtml" '
               'xmlns:epub="http://www.idpf.org/2007/ops"><body>'
               '<nav epub:type="toc"><ol>%s</ol></nav></body></html>') % lis
    files = {"META-INF/container.xml": container.encode("utf-8"),
             "OEBPS/content.opf": opf.encode("utf-8")}
    if nav:
        files["OEBPS/nav.xhtml"] = nav_doc.encode("utf-8")
    for i in range(1, n_docs + 1):
        files["OEBPS/ch%d.xhtml" % i] = (
            "<html><body><p>ch%d</p></body></html>" % i).encode("utf-8")
    return _make_epub(files)


def _merge_two_epubs(first, second, meta=None, options=None):
    return lib.merge_epubs(
        [{"data": first, "title": "卷一"}, {"data": second, "title": "卷二"}],
        meta or {"title": "合集", "authors": ["作者"]}, options)


def _zip_entries(data):
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {i.filename: zf.read(i.filename) for i in zf.infolist()}


class TestStreamingAndPaths(unittest.TestCase):
    """2026-09-08 深审第三轮：流式读写（内存口径）与路径输入。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="epub_merge_test_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name, data):
        path = os.path.join(self.tmpdir, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_out_path_matches_bytes(self):
        # out_path 模式与内存模式除随机 uid 外必须完全一致（仅落盘方式不同）
        b1 = _make_min_epub(title="卷一", n_docs=2)
        b2 = _make_min_epub(title="卷二", n_docs=2)
        inputs = [{"data": b1, "title": "卷一"}, {"data": b2, "title": "卷二"}]
        meta = {"title": "合集", "authors": ["作者"]}
        out_bytes = lib.merge_epubs(inputs, meta)
        out_file = os.path.join(self.tmpdir, "merged.epub")
        self.assertIsNone(lib.merge_epubs(inputs, meta, {"out_path": out_file}))
        with open(out_file, "rb") as f:
            from_file = f.read()
        entries_bytes = _zip_entries(out_bytes)
        entries_file = _zip_entries(from_file)
        self.assertEqual(sorted(entries_bytes), sorted(entries_file))
        for name in entries_bytes:
            if name in ("content.opf", "toc.ncx"):
                continue
            self.assertEqual(entries_bytes[name], entries_file[name], name)
        for name in ("content.opf", "toc.ncx"):
            self.assertEqual(
                re.sub(rb"epubmerge-[0-9a-f]+", b"UID", entries_bytes[name]),
                re.sub(rb"epubmerge-[0-9a-f]+", b"UID", entries_file[name]), name)
        self.assertEqual(lib.validate_output(out_file), [])

    def test_path_inputs(self):
        p1 = self._write("a.epub", _make_min_epub(title="卷一", n_docs=1))
        p2 = self._write("b.epub", _make_min_epub(title="卷二", n_docs=1))
        out = lib.merge_epubs(
            [{"path": p1, "title": "卷一"}, {"path": p2, "title": "卷二"}],
            {"title": "合集", "authors": ["作者"]})
        self.assertEqual(lib.analyze_epub(out)["title"], "合集")
        self.assertEqual(lib.validate_output(out), [])

    def test_path_input_total_cap(self):
        p1 = self._write("a.epub", _make_min_epub(title="卷一", n_docs=1))
        p2 = self._write("b.epub", _make_min_epub(title="卷二", n_docs=1))
        old = lib.MERGE_MAX_INPUT_TOTAL
        lib.MERGE_MAX_INPUT_TOTAL = 10
        try:
            with self.assertRaises(ValueError):
                lib.merge_epubs(
                    [{"path": p1, "title": "卷一"}, {"path": p2, "title": "卷二"}],
                    {"title": "合集", "authors": ["作者"]})
        finally:
            lib.MERGE_MAX_INPUT_TOTAL = old

    def test_missing_path_raises(self):
        with self.assertRaises(ValueError):
            lib.merge_epubs(
                [{"path": os.path.join(self.tmpdir, "nope.epub"), "title": "卷一"},
                 {"data": _make_min_epub(n_docs=1), "title": "卷二"}],
                {"title": "合集", "authors": ["作者"]})

    def test_zip_source_guards(self):
        data = _make_min_epub(n_docs=3)
        with lib._ZipSource(data) as src:
            self.assertIn("OEBPS/ch1.xhtml", src)
            self.assertIsNone(src.get("nope"))
            with self.assertRaises(KeyError):
                src["nope"]
            self.assertTrue(src.read("OEBPS/ch1.xhtml"))
            self.assertEqual(src.lower_map()["oebps/ch1.xhtml"], "OEBPS/ch1.xhtml")
        with self.assertRaises(ValueError):
            lib._ZipSource(data, max_entries=3)
        with self.assertRaises(ValueError):
            lib._ZipSource(data, max_total=10)
        with self.assertRaises(ValueError):
            lib._ZipSource(b"not a zip")

    def test_zip_source_skips_traversal(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("META-INF/container.xml", b"<container/>")
            zf.writestr("../../evil.txt", b"evil")
            zf.writestr("/abs.txt", b"abs")
        with lib._ZipSource(buf.getvalue()) as src:
            self.assertIn("META-INF/container.xml", src)
            self.assertNotIn("../../evil.txt", src)
            self.assertNotIn("/abs.txt", src)

    def test_analyze_path_matches_bytes(self):
        data = _make_min_epub(title="卷", n_docs=2)
        path = self._write("a.epub", data)
        for lite in (False, True):
            self.assertEqual(lib.analyze_epub(data, lite=lite),
                             lib.analyze_epub(path, lite=lite))
        with self.assertRaises(ValueError):
            lib.analyze_epub(os.path.join(self.tmpdir, "missing.epub"))

    def test_validate_output_path(self):
        out = _merge_two_epubs(_make_min_epub(title="卷一", n_docs=1),
                               _make_min_epub(title="卷二", n_docs=1))
        path = self._write("out.epub", out)
        self.assertEqual(lib.validate_output(path), [])


class TestTocFallbacks(unittest.TestCase):
    """目录兜底：NCX 扫描式配对 → EPUB3 nav → spine。"""

    def test_parse_ncx_pairs_order_tolerant(self):
        normal = ('<navMap><navPoint id="n1"><navLabel><text>第一章</text></navLabel>'
                  '<content src="ch1.xhtml"/></navPoint></navMap>')
        self.assertEqual(lib._parse_ncx_pairs(normal), [("第一章", "ch1.xhtml")])
        # content 在 navLabel 之前（非 DTD 顺序但现实存在）
        content_first = ('<navMap><navPoint id="n1"><content src="ch1.xhtml"/>'
                         '<navLabel><text>第一章</text></navLabel></navPoint></navMap>')
        self.assertEqual(lib._parse_ncx_pairs(content_first),
                         [("第一章", "ch1.xhtml")])
        # 没有 content 的 navPoint（纯分组标题）不得吞掉下一条目
        no_content = ('<navMap>'
                      '<navPoint id="n1"><navLabel><text>卷一</text></navLabel></navPoint>'
                      '<navPoint id="n2"><navLabel><text>第一章</text></navLabel>'
                      '<content src="ch1.xhtml"/></navPoint></navMap>')
        self.assertEqual(lib._parse_ncx_pairs(no_content), [("第一章", "ch1.xhtml")])

    def test_parse_ncx_pairs_nested_preorder(self):
        nested = ('<navMap><navPoint id="n1"><navLabel><text>卷一</text></navLabel>'
                  '<content src="ch1.xhtml"/>'
                  '<navPoint id="n1a"><navLabel><text>第一章</text></navLabel>'
                  '<content src="ch2.xhtml"/></navPoint></navPoint></navMap>')
        self.assertEqual(lib._parse_ncx_pairs(nested),
                         [("卷一", "ch1.xhtml"), ("第一章", "ch2.xhtml")])

    def test_parse_ncx_pairs_ignores_pagelist(self):
        ncx = ('<navMap><navPoint id="n1"><navLabel><text>第一章</text></navLabel>'
               '<content src="ch1.xhtml"/></navPoint></navMap>'
               '<pageList><pageTarget id="p1" type="normal" value="1">'
               '<navLabel><text>1</text></navLabel>'
               '<content src="ch1.xhtml#p1"/></pageTarget></pageList>')
        self.assertEqual(lib._parse_ncx_pairs(ncx), [("第一章", "ch1.xhtml")])

    def test_nav_fallback_labels(self):
        out = _merge_two_epubs(_make_epub3("卷A", 3), _make_epub3("卷B", 2))
        entries = _zip_entries(out)
        ncx = entries["toc.ncx"].decode("utf-8")
        labels = re.findall(r"<text>(.*?)</text>", ncx)
        for label in ("第1章", "第2章", "第3章"):
            self.assertIn(label, labels)
        srcs = re.findall(r'<content src="([^"]*)"', ncx)
        self.assertIn("b0/OEBPS/ch1.xhtml", srcs)
        self.assertIn("b1/OEBPS/ch2.xhtml", srcs)
        # nav 页本身不进包，也不出现在目录里
        self.assertFalse([n for n in entries if "nav.xhtml" in n])
        self.assertEqual(lib.validate_output(out), [])

    def test_nav_without_type_attribute(self):
        # 部分工具不写 epub:type="toc"，退回首个 <nav>
        data = _make_epub3("卷A", 2)
        entries = _zip_entries(data)
        entries["OEBPS/nav.xhtml"] = (
            '<html xmlns="http://www.w3.org/1999/xhtml"><body><nav><ol>'
            '<li><a href="ch1.xhtml">一</a></li>'
            '<li><a href="ch2.xhtml">二</a></li></ol></nav></body></html>'
        ).encode("utf-8")
        out = _merge_two_epubs(_make_epub(entries), _make_epub3("卷B", 1))
        labels = re.findall(r"<text>(.*?)</text>",
                            _zip_entries(out)["toc.ncx"].decode("utf-8"))
        self.assertIn("一", labels)
        self.assertIn("二", labels)

    def test_spine_fallback_when_no_toc(self):
        b1 = _make_min_epub(title="卷一", n_docs=2, with_ncx=False)
        b2 = _make_min_epub(title="卷二", n_docs=1, with_ncx=False)
        out = _merge_two_epubs(b1, b2)
        ncx = _zip_entries(out)["toc.ncx"].decode("utf-8")
        labels = re.findall(r"<text>(.*?)</text>", ncx)
        # spine 兜底：label 取文件名主干
        self.assertIn("ch1", labels)
        self.assertIn("ch2", labels)
        self.assertEqual(lib.validate_output(out), [])

    def test_ncx_reference_to_loose_file_kept(self):
        # 回归：NCX 引用 manifest 未列、靠散件兜底入包的文件时，目录项不得被丢
        container = (
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>')
        opf = ('<?xml version="1.0"?><package version="2.0" '
               'xmlns="http://www.idpf.org/2007/opf" unique-identifier="u">'
               '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
               '<dc:identifier id="u">u</dc:identifier><dc:title>卷一</dc:title>'
               '</metadata><manifest>'
               '<item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
               '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
               '</manifest><spine toc="ncx"><itemref idref="c1"/></spine></package>')
        data = _make_epub({
            "META-INF/container.xml": container.encode("utf-8"),
            "OEBPS/content.opf": opf.encode("utf-8"),
            "OEBPS/toc.ncx": _build_ncx("卷一", [("loose.xhtml", "散件章")]).encode("utf-8"),
            "OEBPS/ch1.xhtml": b"<html><body><p>ch1</p></body></html>",
            "OEBPS/loose.xhtml": b"<html><body><p>loose</p></body></html>",
        })
        out = _merge_two_epubs(data, _make_min_epub(title="卷二", n_docs=1))
        entries = _zip_entries(out)
        self.assertIn("b0/OEBPS/loose.xhtml", entries)
        out_ncx = entries["toc.ncx"].decode("utf-8")
        self.assertIn("散件章", out_ncx)
        self.assertIn('src="b0/OEBPS/loose.xhtml"', out_ncx)
        self.assertEqual(lib.validate_output(out), [])


class TestHrefEncoding(unittest.TestCase):
    """生成的 OPF/NCX 引用必须按 URI 规则转义（`#`/空格/非 ASCII/字面 %）。"""

    CONTAINER = (
        '<?xml version="1.0"?><container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>')

    def _book(self, docs, title="卷", extra_files=None):
        """docs: [(zip 名, 内容 bytes)]，manifest href 按 URI 规则编码。"""
        items = "".join(
            '<item id="d%d" href="%s" media-type="application/xhtml+xml"/>'
            % (i, quote(name, safe="/")) for i, (name, _data) in enumerate(docs))
        spine = "".join('<itemref idref="d%d"/>' % i for i in range(len(docs)))
        opf = ('<?xml version="1.0"?><package version="2.0" '
               'xmlns="http://www.idpf.org/2007/opf" unique-identifier="u">'
               '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
               '<dc:identifier id="u">u</dc:identifier><dc:title>%s</dc:title>'
               '</metadata><manifest>%s</manifest><spine>%s</spine></package>'
               ) % (title, items, spine)
        files = {"META-INF/container.xml": self.CONTAINER.encode("utf-8"),
                 "OEBPS/content.opf": opf.encode("utf-8")}
        for name, data in docs:
            files["OEBPS/" + name] = data
        files.update(extra_files or {})
        return _make_epub(files)

    def test_hrefs_quoted_and_resolvable(self):
        names = ["a#b.xhtml", "my page.xhtml", "百分百.xhtml", "c%20d.xhtml"]
        doc = b"<html><body><p>x</p></body></html>"
        b1 = self._book([(n, doc) for n in names])
        b2 = self._book([(n, doc) for n in names], title="卷二")
        out = _merge_two_epubs(b1, b2)
        entries = _zip_entries(out)
        hrefs = re.findall(r'<item [^>]*href="([^"]*)"', entries["content.opf"].decode("utf-8"))
        for href in hrefs:
            self.assertNotIn("#", href)
            self.assertIn(unquote(href), entries)
        self.assertIn("b0/OEBPS/a%23b.xhtml", hrefs)
        self.assertIn("b0/OEBPS/my%20page.xhtml", hrefs)
        self.assertIn("b0/OEBPS/c%2520d.xhtml", hrefs)
        self.assertEqual(lib.validate_output(out), [])

    def test_ncx_src_hash_filename_keeps_fragment(self):
        # 文件名含 `#`（源 href 写作 %23）且带 fragment：路径与 fragment 分别编码
        ncx = ('<?xml version="1.0"?><ncx '
               'xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
               '<head></head><docTitle><text>T</text></docTitle><navMap>'
               '<navPoint id="n1" playOrder="1"><navLabel><text>第一章</text></navLabel>'
               '<content src="a%23b.xhtml#p1"/></navPoint></navMap></ncx>')
        items = ('<item id="d0" href="a%23b.xhtml" '
                 'media-type="application/xhtml+xml"/>'
                 '<item id="ncx" href="toc.ncx" '
                 'media-type="application/x-dtbncx+xml"/>')
        opf = ('<?xml version="1.0"?><package version="2.0" '
               'xmlns="http://www.idpf.org/2007/opf" unique-identifier="u">'
               '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
               '<dc:identifier id="u">u</dc:identifier><dc:title>T</dc:title>'
               '</metadata><manifest>%s</manifest>'
               '<spine toc="ncx"><itemref idref="d0"/></spine></package>') % items
        data = _make_epub({
            "META-INF/container.xml": self.CONTAINER.encode("utf-8"),
            "OEBPS/content.opf": opf.encode("utf-8"),
            "OEBPS/a#b.xhtml": b'<html><body><p id="p1">x</p></body></html>',
            "OEBPS/toc.ncx": ncx.encode("utf-8"),
        })
        out = _merge_two_epubs(data, self._book([("ch1.xhtml", b"<html/>")]))
        ncx_out = _zip_entries(out)["toc.ncx"].decode("utf-8")
        srcs = re.findall(r'<content src="([^"]*)"', ncx_out)
        self.assertIn("b0/OEBPS/a%23b.xhtml#p1", srcs)
        self.assertEqual(lib.validate_output(out), [])


class TestCssRewrite(unittest.TestCase):
    """CSS 内根绝对 url()/@import 改写（相对引用与无改写文件保持原字节）。"""

    CONTAINER = TestHrefEncoding.CONTAINER

    def _book(self, css_bytes):
        opf = ('<?xml version="1.0"?><package version="2.0" '
               'xmlns="http://www.idpf.org/2007/opf" unique-identifier="u">'
               '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
               '<dc:identifier id="u">u</dc:identifier><dc:title>T</dc:title>'
               '</metadata><manifest>'
               '<item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
               '<item id="css" href="style.css" media-type="text/css"/>'
               '<item id="css2" href="other.css" media-type="text/css"/>'
               '<item id="img" href="img.png" media-type="image/png"/>'
               '</manifest><spine><itemref idref="ch1"/></spine></package>')
        return _make_epub({
            "META-INF/container.xml": self.CONTAINER.encode("utf-8"),
            "OEBPS/content.opf": opf.encode("utf-8"),
            "OEBPS/ch1.xhtml": b"<html><body><p>x</p></body></html>",
            "OEBPS/style.css": css_bytes,
            "OEBPS/other.css": b"body{margin:0}",
            "OEBPS/img.png": b"\x89PNG-fake",
        })

    def test_root_absolute_url_rewritten(self):
        css = '@charset "gb18030";\np { background: url(/OEBPS/img.png); }'
        out = _merge_two_epubs(self._book(css.encode("utf-8")),
                               self._book(b"p{color:red}"))
        css_out = _zip_entries(out)["b0/OEBPS/style.css"].decode("utf-8")
        self.assertIn("url(img.png)", css_out)
        self.assertNotIn("/OEBPS/", css_out)
        self.assertIn('@charset "utf-8";', css_out)
        self.assertEqual(lib.validate_output(out), [])

    def test_root_absolute_import_rewritten(self):
        css = '@import "/OEBPS/other.css";'
        out = _merge_two_epubs(self._book(css.encode("utf-8")),
                               self._book(b"p{color:red}"))
        css_out = _zip_entries(out)["b0/OEBPS/style.css"].decode("utf-8")
        self.assertIn('@import "other.css"', css_out)

    def test_relative_css_untouched(self):
        css = b"p { background: url(../img.png); }"
        out = _merge_two_epubs(self._book(css), self._book(b"p{color:red}"))
        self.assertEqual(_zip_entries(out)["b0/OEBPS/style.css"], css)


class TestLinkTocExclusion(unittest.TestCase):
    """无 nav 语义的链接列表目录页不计正文（文件名 + 链接密度双门槛）。"""

    CONTAINER = TestHrefEncoding.CONTAINER

    def _book(self, toc_name, n_links=6):
        links = "".join('<p><a href="ch%d.xhtml">第%d章</a></p>' % (i, i)
                        for i in range(1, n_links + 1))
        items = ('<item id="toc" href="%s" media-type="application/xhtml+xml"/>'
                 % quote(toc_name, safe="/"))
        items += "".join('<item id="c%d" href="ch%d.xhtml" '
                         'media-type="application/xhtml+xml"/>' % (i, i)
                         for i in range(1, n_links + 1))
        spine = '<itemref idref="toc"/>' + "".join(
            '<itemref idref="c%d"/>' % i for i in range(1, n_links + 1))
        opf = ('<?xml version="1.0"?><package version="2.0" '
               'xmlns="http://www.idpf.org/2007/opf" unique-identifier="u">'
               '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
               '<dc:identifier id="u">u</dc:identifier><dc:title>T</dc:title>'
               '</metadata><manifest>%s</manifest><spine>%s</spine></package>'
               ) % (items, spine)
        files = {"META-INF/container.xml": self.CONTAINER.encode("utf-8"),
                 "OEBPS/content.opf": opf.encode("utf-8"),
                 "OEBPS/" + toc_name: ("<html><body>%s</body></html>" % links).encode("utf-8")}
        for i in range(1, n_links + 1):
            files["OEBPS/ch%d.xhtml" % i] = (
                "<html><body><p>ch%d</p></body></html>" % i).encode("utf-8")
        return _make_epub(files)

    def test_link_toc_page_excluded(self):
        out = _merge_two_epubs(self._book("toc.xhtml"),
                               _make_min_epub(title="卷二", n_docs=1))
        entries = _zip_entries(out)
        self.assertFalse([n for n in entries if "toc.xhtml" in n])
        self.assertIn("b0/OEBPS/ch1.xhtml", entries)
        self.assertEqual(lib.validate_output(out), [])

    def test_non_toc_named_page_kept(self):
        # 名字不含 nav/toc 的页面即使链接密度高也不剔除（防误伤正文）
        out = _merge_two_epubs(self._book("index.xhtml"),
                               _make_min_epub(title="卷二", n_docs=1))
        self.assertIn("b0/OEBPS/index.xhtml", _zip_entries(out))

    def test_toc_named_page_without_links_kept(self):
        # 名字像目录但链接不足（<5）不剔除
        out = _merge_two_epubs(self._book("toc.xhtml", n_links=2),
                               _make_min_epub(title="卷二", n_docs=1))
        self.assertIn("b0/OEBPS/toc.xhtml", _zip_entries(out))


def _forge_central_dir_size(data: bytes, name: str, size: int) -> bytes:
    """改写中央目录里某条目的 uncompressed size（伪造 ZipBomb 用）。"""
    data = bytearray(data)
    idx = data.find(b"PK\x01\x02")
    while idx >= 0:
        n = struct.unpack_from("<H", data, idx + 28)[0]
        if bytes(data[idx + 46: idx + 46 + n]) == name.encode("utf-8"):
            struct.pack_into("<I", data, idx + 24, size)
            return bytes(data)
        idx = data.find(b"PK\x01\x02", idx + 4)
    raise AssertionError("central directory entry not found: %s" % name)


class TestBombAndHandleFixes(unittest.TestCase):
    """2026-09-08 第四轮：lite 路径 ZipBomb、句柄释放、UTF-16 解码。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="epub_merge_test_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_forged_central_dir_bomb_capped(self):
        # 伪造中央目录（声明 1KB、实际 64MB）：lite 路径不得一次性解压整条
        # （zipfile.read() 无参会按 MAX_N=2**31-1 一次性 decompress，旧实现
        # 实测 200MB 伪造包峰值 458MB）
        payload = b"\x00" * (64 * 1024 * 1024)
        packed = _make_epub({"META-INF/container.xml": payload})
        forged = _forge_central_dir_size(packed, "META-INF/container.xml", 1024)
        tracemalloc.start()
        try:
            with self.assertRaises(ValueError):
                lib.analyze_epub(forged, lite=True)
            _cur, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(
            peak, 32 * 1024 * 1024,
            "lite 路径一次性解压了伪造条目（峰值 %.1f MB）" % (peak / 1e6))

    def test_oversized_meta_entry_rejected(self):
        # 声明即超限的元数据条目直接拒绝（保留原语义）
        packed = _make_epub({"META-INF/container.xml": b"x" * (9 * 1024 * 1024)})
        with self.assertRaises(ValueError):
            lib._read_meta_entries(packed)

    def test_validate_output_releases_handle_on_error(self):
        # 失败路径必须释放句柄：异常回溯持有帧时，Windows 下文件会被锁住
        path = os.path.join(self.tmpdir, "not_epub.epub")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("content.opf", b"<package/>")   # 缺 mimetype → 校验失败
        removed = False
        try:
            lib.validate_output(path)
        except ValueError:
            try:
                os.remove(path)          # 句柄未关则抛 WinError 32
                removed = True
            except OSError as err:
                self.fail("validate_output 失败后文件仍被占用：%s" % err)
        self.assertTrue(removed, "validate_output 未按预期失败")

    def test_utf16_decode(self):
        # 带 BOM：任意文本（UTF-32 BOM 以 UTF-16 BOM 开头，顺序不能错）
        self.assertEqual(lib._decode("中文正文".encode("utf-16")), "中文正文")
        self.assertEqual(lib._decode("中文正文".encode("utf-32")), "中文正文")
        # 无 BOM：按 `<` 的宽字符形态识别（XML/HTML 文本）
        doc = '<?xml version="1.0"?><html>中文</html>'
        self.assertEqual(lib._decode(doc.encode("utf-16-le")), doc)
        self.assertEqual(lib._decode(doc.encode("utf-16-be")), doc)


class TestCoverPathFix(unittest.TestCase):
    """extract_cover 支持路径（只解压封面条目，不读整本）。"""

    def test_extract_cover_path(self):
        container = (
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>')
        opf = ('<?xml version="1.0"?><package version="2.0" '
               'xmlns="http://www.idpf.org/2007/opf" unique-identifier="u">'
               '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
               '<dc:identifier id="u">u</dc:identifier><dc:title>T</dc:title>'
               '</metadata><manifest>'
               '<item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
               '<item id="c" href="cov.jpg" media-type="image/jpeg" '
               'properties="cover-image"/></manifest>'
               '<spine><itemref idref="ch1"/></spine></package>')
        data = _make_epub({
            "META-INF/container.xml": container.encode("utf-8"),
            "OEBPS/content.opf": opf.encode("utf-8"),
            "OEBPS/ch1.xhtml": b"<html><body><p>x</p></body></html>",
            "OEBPS/cov.jpg": b"COVER",
        })
        tmp = tempfile.mkdtemp(prefix="epub_merge_test_")
        try:
            path = os.path.join(tmp, "a.epub")
            with open(path, "wb") as f:
                f.write(data)
            self.assertEqual(lib.extract_cover(path), (b"COVER", "jpg"))
            self.assertEqual(lib.extract_cover(data), (b"COVER", "jpg"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
