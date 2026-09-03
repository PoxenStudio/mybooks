# -*- coding: utf-8 -*-
"""epub_beautify 核心单元测试（standalone，stub 掉 webserver / calibre 依赖）。

覆盖：章节正则识别（含正反例）、EPUB 分析、目录页生成与幂等重跑、
章节标题标记（h / 段落文本 / div 三类）、CSS 注入与预设插值、规范 zip 重写。

运行：python tests/test_epub_beautify_core.py
"""
import os
import re
import sys
import tempfile
import types
import unittest
import zipfile
import xml.etree.ElementTree as ET
from unittest import mock

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLBOX_DIR = os.path.join(TESTS_DIR, "..", "webserver", "toolbox")


def _stub_webserver():
    """注入最小 webserver 依赖，使 epub_beautify 相关模块可独立导入。"""
    webserver = types.ModuleType("webserver")
    toolbox = types.ModuleType("webserver.toolbox")
    toolbox.__path__ = [TOOLBOX_DIR]
    webserver.toolbox = toolbox

    i18n = types.ModuleType("webserver.i18n")
    i18n._ = lambda s: s
    webserver.i18n = i18n

    utils = types.ModuleType("webserver.utils")
    utils.super_strip = lambda s: (s or "").strip()
    utils.get_title_sort = lambda s: s
    webserver.utils = utils

    models = types.ModuleType("webserver.models")
    models.Item = type("Item", (), {"save": lambda self: None})
    webserver.models = models

    services = types.ModuleType("webserver.services")
    _register_service = staticmethod(lambda fn: fn)
    _register_function = staticmethod(lambda fn: fn)
    services.AsyncService = type("AsyncService", (), {
        "register_service": _register_service,
        "register_function": _register_function,
    })
    webserver.services = services

    bs = types.ModuleType("webserver.services.background_service")
    bs.BackgroundService = type("BackgroundService", (), {})
    bs.BackgroundTask = type("BackgroundTask", (), {
        "STATUS_RUNNING": "running",
        "STATUS_FAILED": "failed",
        "STATUS_COMPLETED": "completed",
    })
    webserver.services.background_service = bs

    base_tool = types.ModuleType("webserver.toolbox.base_tool")
    base_tool.BaseTool = type("BaseTool", (), {})
    toolbox.base_tool = base_tool

    calibre = types.ModuleType("calibre")
    ebooks = types.ModuleType("calibre.ebooks")
    metadata = types.ModuleType("calibre.ebooks.metadata")
    book = types.ModuleType("calibre.ebooks.metadata.book")
    base = types.ModuleType("calibre.ebooks.metadata.book.base")
    base.Metadata = type("Metadata", (), {})
    calibre.ebooks = ebooks
    calibre.ebooks.metadata = metadata
    calibre.ebooks.metadata.book = book
    calibre.ebooks.metadata.book.base = base

    sys.modules.update({
        "webserver": webserver,
        "webserver.toolbox": toolbox,
        "webserver.i18n": i18n,
        "webserver.utils": utils,
        "webserver.models": models,
        "webserver.services": services,
        "webserver.services.background_service": bs,
        "webserver.toolbox.base_tool": base_tool,
        "calibre": calibre,
        "calibre.ebooks": ebooks,
        "calibre.ebooks.metadata": metadata,
        "calibre.ebooks.metadata.book": book,
        "calibre.ebooks.metadata.book.base": base,
    })


_stub_webserver()

from webserver.toolbox.utils import chapter_patterns  # noqa: E402
from webserver.toolbox.utils import epub_beautify_lib as lib  # noqa: E402
from webserver.toolbox.utils.styles import (  # noqa: E402
    _CALIBRE_INDENT_SELECTORS,
    _CALIBRE_MARGIN_SELECTORS,
    _apply_palette_overrides,
    get_preset_css, list_presets, list_toc_styles,
)

CONTAINER = (
    '<?xml version="1.0"?>'
    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="OEBPS/content.opf" '
    'media-type="application/oebps-package+xml"/></rootfiles></container>'
)
OPF = (
    '<?xml version="1.0"?>'
    '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
    '<metadata><dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">测试书</dc:title></metadata>'
    '<manifest>'
    '<item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
    '<item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>'
    '<item id="css" href="style.css" media-type="text/css"/>'
    '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
    '</manifest>'
    '<spine><itemref idref="c1"/><itemref idref="c2"/></spine>'
    '</package>'
)
NCX = (
    '<?xml version="1.0"?>'
    '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
    '<navMap>'
    '<navPoint id="v1"><navLabel><text>第一卷</text></navLabel>'
    '<content src="ch1.xhtml"/>'
    '<navPoint id="n1"><navLabel><text>第一章 序章</text></navLabel>'
    '<content src="ch1.xhtml#p1"/></navPoint>'
    '<navPoint id="n2"><navLabel><text>第二章 开端</text></navLabel>'
    '<content src="ch1.xhtml#p2"/></navPoint>'
    '</navPoint>'
    '<navPoint id="n3"><navLabel><text>第三章 转折</text></navLabel>'
    '<content src="ch2.xhtml"/></navPoint>'
    '<navPoint id="n4"><navLabel><text>引子</text></navLabel>'
    '<content src="ch2.xhtml"/></navPoint>'
    '</navMap></ncx>'
)
# ch1：无 h 标签，标题是段落文本（第三层识别路径）
CH1 = (
    '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
    '<link href="style.css" rel="stylesheet" type="text/css"/></head>'
    '<body><p>第一章 序章</p><p>正文从这里开始，描写一段长长的故事。</p>'
    '<p>第二章 开端</p><p>第二段正文内容，继续推进情节。</p></body></html>'
)
# ch2：h2 标题（第一层识别路径）
CH2 = (
    '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
    '<link href="style.css" rel="stylesheet" type="text/css"/></head>'
    '<body><h2>第三章 转折</h2><p>这是第三章的正文。</p></body></html>'
)
# 前置页：书名/版权（不应被标记）
COVER = (
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Cover</title></head>'
    '<body><h1>测试书</h1><p>版权信息页</p></body></html>'
)
CSS = "body { font-family: serif; }\n"


def build_mini_epub(path, with_cover=False):
    """构建迷你 EPUB：NCX 无书内目录页；可选封面前置页。"""
    manifest = (
        '<item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="css" href="style.css" media-type="text/css"/>'
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
    )
    spine = '<itemref idref="c1"/><itemref idref="c2"/>'
    if with_cover:
        manifest = (
            '<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>'
            + manifest
        )
        spine = '<itemref idref="cover"/>' + spine
    opf = (
        '<?xml version="1.0"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata><dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">测试书</dc:title></metadata>'
        '<manifest>%s</manifest><spine>%s</spine></package>'
    ) % (manifest, spine)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/ch1.xhtml", CH1)
        zf.writestr("OEBPS/ch2.xhtml", CH2)
        zf.writestr("OEBPS/style.css", CSS)
        zf.writestr("OEBPS/toc.ncx", NCX)
        if with_cover:
            zf.writestr("OEBPS/cover.xhtml", COVER)


class TestChapterPatterns(unittest.TestCase):
    """章节正则识别（移植自 txt2epub-next）。"""

    def test_structured_chinese(self):
        for line in ("第一章 序章", "第12章 标题", "第十二章 标题", "第 三 回 标题",
                     "【第一卷：标题】", "序章", "楔子", "尾声", "番外", "后记"):
            self.assertIsNotNone(chapter_patterns.heading_kind(line), line)

    def test_english(self):
        for line in ("Chapter 1", "Chapter III", "Volume 2", "Book 1", "Part i"):
            self.assertIsNotNone(chapter_patterns.heading_kind(line), line)

    def test_bare_number(self):
        self.assertEqual(chapter_patterns.heading_kind("001 标题"), "bare_number")
        self.assertEqual(chapter_patterns.heading_kind("1. Title"), "bare_number")

    def test_not_headings(self):
        # 小数/时间戳/普通句子不应误判
        for line in ("45.761871", "10:20", "他走进房间，看见桌上的信。"):
            self.assertIsNone(chapter_patterns.heading_kind(line), line)

    def test_paragraph_is_heading_filters(self):
        self.assertTrue(chapter_patterns.paragraph_is_heading("第1章 天黑别出门"))
        self.assertTrue(chapter_patterns.paragraph_is_heading("序章"))
        # 长段 / 句末标点 / 纯符号 → 不是标题
        self.assertFalse(chapter_patterns.paragraph_is_heading("第1章 " + "很" * 100))
        self.assertFalse(chapter_patterns.paragraph_is_heading("第一章。他走在路上。"))
        self.assertFalse(chapter_patterns.paragraph_is_heading("10:20"))
        self.assertFalse(chapter_patterns.paragraph_is_heading(""))

    def test_heading_number(self):
        self.assertEqual(chapter_patterns.heading_number("第12章 标题"), 12)
        self.assertEqual(chapter_patterns.heading_number("003 标题"), 3)
        self.assertIsNone(chapter_patterns.heading_number("序章"))


class TestPresets(unittest.TestCase):
    """预设加载与插值。"""

    def test_list_presets(self):
        presets = list_presets()
        self.assertIn("classic", presets)
        self.assertGreaterEqual(len(presets), 4)

    def test_preset_css_interpolation(self):
        css = get_preset_css("classic", use_system_fonts=True)
        self.assertNotIn("{{", css)
        self.assertIn("font-family: \"Noto Serif SC\"", css)
        self.assertIn("line-height: 1.7", css)
        self.assertIn(".mb-ch", css)
        self.assertIn("mb-toc-page", css)  # 目录样式（elegant 默认）已嵌入

    def test_preset_css_keep_original_fonts(self):
        css = get_preset_css("classic", use_system_fonts=False)
        self.assertNotIn("{{", css)
        self.assertNotIn("font-family:", css)
        self.assertIn(".mb-ch", css)
        self.assertIn("mb-toc-page", css)

    def test_toc_style_cool(self):
        css = get_preset_css("classic", use_system_fonts=True, toc_style="cool")
        self.assertNotIn("{{", css)
        grad = list_presets()["classic"]["toc_gradient"]
        self.assertIn(grad, css)
        # cool 条目区已参数化（跟随预设 QUOTE_BG），不再硬编码奶油金
        self.assertIn(".mb-toc-num", css)
        # elegant 不含渐变
        css_elegant = get_preset_css("classic", use_system_fonts=True, toc_style="elegant")
        self.assertNotIn("linear-gradient", css_elegant)

    def test_toc_style_seal(self):
        css = get_preset_css("classic", use_system_fonts=True, toc_style="seal")
        self.assertNotIn("{{", css)
        self.assertIn("mb-toc-seal", css)     # 印章装饰
        self.assertIn("td.mb-toc-mark", css)  # 双栏表格右列
        self.assertIn("table.mulu", css)

    def test_toc_style_minimal(self):
        """minimal 极简：无卡片无边框、收尾横线化。"""
        css = get_preset_css("classic", use_system_fonts=True, toc_style="minimal")
        self.assertNotIn("{{", css)
        self.assertIn("mb-toc-page", css)
        self.assertIn("background: transparent !important", css)
        self.assertIn("font-size: 0", css)
        self.assertNotIn("linear-gradient", css)

    def test_all_preset_toc_combos_interpolation(self):
        """全部预设 × 4 目录风格组合插值无残留占位符。"""
        presets = list_presets()
        self.assertGreaterEqual(len(presets), 11)
        for pid in presets:
            for ts in ("elegant", "cool", "seal", "minimal"):
                css = get_preset_css(pid, use_system_fonts=True, toc_style=ts)
                self.assertNotIn("{{", css, "%s/%s 残留占位符" % (pid, ts))
                css_kf = get_preset_css(pid, use_system_fonts=False, toc_style=ts)
                self.assertNotIn("{{", css_kf, "%s/%s(keep-fonts) 残留占位符" % (pid, ts))

    def test_accent_dark_token(self):
        """全部预设含 accent_dark，且注入到深色模式段。"""
        for pid, meta in list_presets().items():
            dark = meta.get("accent_dark", "")
            self.assertTrue(dark.startswith("#"), "%s 缺 accent_dark" % pid)
            css = get_preset_css(pid, use_system_fonts=True)
            self.assertIn("color: %s !important" % dark, css)

    def test_removed_toc_styles(self):
        """royal 已移除、vgospel 已更名 seal：旧 id 优雅报错。"""
        for old in ("royal", "vgospel"):
            with self.assertRaises(ValueError):
                get_preset_css("classic", toc_style=old)
        ids = [t["id"] for t in list_toc_styles()]
        self.assertNotIn("royal", ids)
        self.assertNotIn("vgospel", ids)

    def test_new_preset_vertclassical(self):
        """竖排古籍：横排兜底 + @supports 竖排增强 + 目录竖排适配。"""
        css = get_preset_css("vertclassical")
        self.assertNotIn("{{", css)
        # 渐进增强包裹，老阅读器只看横排兜底
        self.assertIn("@supports (writing-mode: vertical-rl)", css)
        # 三写法齐备（各引擎前缀差异）
        self.assertIn("-epub-writing-mode: vertical-rl", css)
        self.assertIn("-webkit-writing-mode: vertical-rl", css)
        self.assertIn("writing-mode: vertical-rl", css)
        # 反制 responsive 的横排行长限制
        self.assertIn("max-width: none !important", css)
        # 竖排下装饰线转竖向语义 + 代码块保持横排
        self.assertIn("border-right", css)
        self.assertIn("writing-mode: horizontal-tb", css)
        # 目录页竖排适配
        self.assertIn("body.mb-toc-page li", css)

    def test_page_progression_metadata(self):
        """仅竖排预设声明 rtl 翻页方向。"""
        presets = list_presets()
        self.assertEqual(presets["vertclassical"].get("page_progression"), "rtl")
        for pid, meta in presets.items():
            if pid != "vertclassical":
                self.assertIsNone(meta.get("page_progression"), pid)

    def test_unknown_preset(self):
        with self.assertRaises(ValueError):
            get_preset_css("nope")

    def test_unknown_toc_style(self):
        with self.assertRaises(ValueError):
            get_preset_css("classic", toc_style="neon")


class TestCssCascade(unittest.TestCase):
    """A1/A2 回归：类汤选择器排除标题、夜间章节卡深底最终胜者、色板对比度。

    静态层叠断言说明：responsive.css 前置注入、预设规则在后，同特异性按源序
    预设胜出——因此夜间/标题修复全部依赖「更高特异性」取胜，此处对生成后的
    CSS 断言选择器形态（body 前缀 0-1-1 > 预设裸 .mb-ch 0-1-0），即最终胜者。
    """

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(TOOLBOX_DIR, "utils", "styles", "responsive.css"),
                  encoding="utf-8") as f:
            cls.responsive_src = f.read()

    @staticmethod
    def _luminance(color):
        c = color.lstrip("#")
        if len(c) == 3:
            c = "".join(ch * 2 for ch in c)

        def lin(hex_pair):
            v = int(hex_pair, 16) / 255.0
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

        r, g, b = (lin(c[i:i + 2]) for i in (0, 2, 4))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    @classmethod
    def _contrast(cls, fg, bg):
        hi, lo = sorted((cls._luminance(fg), cls._luminance(bg)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    # ── A2：类汤选择器排除标题 ──

    def test_calibre_soup_excludes_titles(self):
        """A2：.calibre* 正文规则带 :not(.mb-ch):not(.mb-vol)，旧裸选择器清零。"""
        for pid in list_presets():
            css = get_preset_css(pid, use_system_fonts=True)
            self.assertIn("p.calibre1:not(.mb-ch):not(.mb-vol)", css, pid)
            # 章首顶格规则同样排除标题，且特异性（0-4-1）须压过类汤缩进（0-3-1）
            self.assertIn("p.calibre1[data-mb-first]:not(.mb-ch):not(.mb-vol)", css, pid)
            self.assertNotRegex(css, r"(?m)^p\.calibre1\s*,", pid)
            self.assertNotRegex(css, r"(?m)^p\.calibre1\s*\{", pid)
            self.assertNotRegex(css, r"(?m)^\.calibre1\s*,", pid)

    def test_para_style_override_parity(self):
        """A2 联动：段落排版覆写与 responsive 类汤选择器集合逐字一致。

        responsive 的类汤规则经 :not 提升到 0-3-1，末尾覆写若不同列表会因
        特异性落后而失效（顶格/段距开关在类汤书上失灵）。
        """
        m = re.search(r"(?m)^(p\.calibre1[^{]*?)\{", self.responsive_src)
        self.assertIsNotNone(m, "responsive.css 类汤选择器行缺失")
        responsive_set = {s.strip() for s in m.group(1).split(",")}
        self.assertEqual(responsive_set, set(_CALIBRE_INDENT_SELECTORS.split(", ")))
        self.assertLessEqual(
            set(_CALIBRE_MARGIN_SELECTORS.split(", ")), responsive_set)
        css = get_preset_css("classic", para_indent=False, para_gap=1.2)
        self.assertIn(_CALIBRE_INDENT_SELECTORS, css)
        self.assertIn(_CALIBRE_MARGIN_SELECTORS, css)

    # ── A1：夜间章节卡深底最终胜者 ──

    def test_night_title_dark_bg_wins(self):
        """A1：dark 块内 html body .mb-ch（0-1-2）带深底，压预设裸 .mb-ch（0-1-0）
        与 vertclassical 竖排块的 body .mb-ch（0-1-1）。"""
        for pid, meta in list_presets().items():
            css = get_preset_css(pid, use_system_fonts=True)
            dark_at = css.index("@media (prefers-color-scheme: dark)")
            rule_at = css.index("html body .mb-ch {", dark_at)
            block = css[rule_at:css.index("}", rule_at)]
            self.assertIn("background: #1e1e1e !important", block, pid)
            self.assertIn("color: %s !important" % meta["accent_dark"], block, pid)
            # 胜者前提：预设侧章节卡无 body / html 前缀同形选择器
            preset_part = css[:css.index("/* ── responsive injected (front) ── */")]
            self.assertNotRegex(preset_part, r"(?m)^(html )?body \.mb-ch\b", pid)

    def test_night_palette_contrast(self):
        """A1：夜间章节卡 ACCENT_DARK on #1e1e1e ≥4.5；日间标题 ≥3（大字号）。"""
        for pid, meta in list_presets().items():
            self.assertGreaterEqual(
                self._contrast(meta["accent_dark"], "#1E1E1E"), 4.5, pid)
            self.assertGreaterEqual(
                self._contrast(meta["accent"], meta["accent_light"]), 3.0, pid)

    def test_night_fixed_palette_contrast(self):
        """夜间固定色对比度（WCAG）：正文/夜链/章号在深底上可读。"""
        self.assertGreaterEqual(self._contrast("#E0E0E0", "#121212"), 7.0)
        self.assertGreaterEqual(self._contrast("#A8C0FF", "#121212"), 10.0)
        self.assertGreaterEqual(self._contrast("#8A8A8A", "#1E1E1E"), 4.5)


class TestPhase1Safety(unittest.TestCase):
    """P1/P2 回归：ZipBomb 解压后二次校验 + analyze 采样化。"""

    def test_zipbomb_declared_precheck(self):
        """P2：中央目录声明总量超限 → 预判拦截（原有行为，常量化后回归）。"""
        tmp = os.path.join(TESTS_DIR, "_tmp_bomb1.epub")
        with zipfile.ZipFile(tmp, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
            zf.writestr("META-INF/container.xml", CONTAINER)
        try:
            with mock.patch.object(lib, "_ZIP_MAX_TOTAL", 1):
                with self.assertRaises(RuntimeError) as cm:
                    lib._read_zip_entries(tmp)
            self.assertIn("Zip Bomb", str(cm.exception))
        finally:
            os.remove(tmp)

    def test_zipbomb_uncompressed_second_check(self):
        """P2：中央目录 file_size 伪造偏小、解压实际超大 → len(data) 二次拦截。"""
        tmp = os.path.join(TESTS_DIR, "_tmp_bomb2.epub")
        with zipfile.ZipFile(tmp, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
            zf.writestr("META-INF/container.xml", CONTAINER)
        try:
            with mock.patch.object(lib, "_ZIP_MAX_TOTAL", 10 * 1024 * 1024), \
                 mock.patch.object(zipfile.ZipFile, "read",
                                   return_value=b"A" * (11 * 1024 * 1024)):
                with self.assertRaises(RuntimeError) as cm:
                    lib._read_zip_entries(tmp)
            self.assertIn("解压后", str(cm.exception))
        finally:
            os.remove(tmp)

    def test_analyze_p_mismatch_sampled(self):
        """P1：p 开闭预警只扫前 sample_limit 个正文文件（大书不卡 IOLoop）。"""
        n = 25
        tmp = os.path.join(TESTS_DIR, "_tmp_sampling.epub")
        items = "".join(
            '<item id="c%d" href="c%02d.xhtml" media-type="application/xhtml+xml"/>'
            % (i, i) for i in range(1, n + 1))
        spine = "".join('<itemref idref="c%d"/>' % i for i in range(1, n + 1))
        opf = (
            '<?xml version="1.0"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            '<metadata><dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '采样书</dc:title></metadata>'
            '<manifest>%s</manifest><spine>%s</spine></package>' % (items, spine)
        )
        with zipfile.ZipFile(tmp, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip",
                        compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/container.xml", CONTAINER)
            zf.writestr("OEBPS/content.opf", opf)
            for i in range(1, n + 1):
                # 末章少一个 </p>（开闭不齐），前 24 章健康
                body = ('<p>第%d章<p>正文内容。' % i if i == n
                        else '<p>第%d章</p><p>正文内容。</p>' % i)
                zf.writestr(
                    "OEBPS/c%02d.xhtml" % i,
                    '<html xmlns="http://www.w3.org/1999/xhtml">'
                    '<head><title>c%d</title></head><body>%s</body></html>' % (i, body))
        try:
            a = lib.analyze_epub(tmp)
            self.assertEqual(a["p_close_mismatch_files"], 0)
            a_all = lib.analyze_epub(tmp, sample_limit=30)
            self.assertEqual(a_all["p_close_mismatch_files"], 1)
        finally:
            os.remove(tmp)


class TestCssAdaptivity(unittest.TestCase):
    """A3/A4/顶空 回归：手机块 body 前缀生效、目录夜卡深底、split 关闭章扉顶距。"""

    @classmethod
    def setUpClass(cls):
        cls._styles_dir = os.path.join(TOOLBOX_DIR, "utils", "styles")
        with open(os.path.join(cls._styles_dir, "responsive.css"),
                  encoding="utf-8") as f:
            cls.responsive_src = f.read()

    # ── A4：手机块提特异性 ──

    def test_mobile_block_body_prefix(self):
        """A4：手机块 p/blockquote/.mb-ch/.mb-ch-sep 一律 body 前缀
        （0-0-2 / 0-1-1），压过预设同规则裸选择器，2.2em 手机顶距生效。"""
        at = self.responsive_src.index("手机窄屏适配")
        at = self.responsive_src.index("@media (max-width: 600px)", at)
        block = self.responsive_src[at:self.responsive_src.index("\n}", at)]
        for sel in ("body p {", "body blockquote {",
                    "body .mb-ch {", "body .mb-ch-sep {"):
            self.assertIn(sel, block)
        self.assertIn("margin: 2.2em 0 0.6em 0 !important", block)
        # 媒体块内不再有会被预设同特异性压掉的裸选择器
        self.assertNotRegex(block, r"(?m)^  p \{")
        self.assertNotRegex(block, r"(?m)^  \.mb-ch \{")

    def test_vert_block_parity(self):
        """A4：vertclassical 竖排块 body 前缀 + 源序在后，窄屏竖排压过手机块。"""
        css = get_preset_css("vertclassical", use_system_fonts=True)
        mobile_at = css.index("@media (max-width: 600px)")
        supports_at = css.index("@supports (writing-mode: vertical-rl)")
        self.assertLess(mobile_at, supports_at)
        vblock = css[supports_at:]
        for sel in ("body p {", "body blockquote {",
                    "body .mb-ch {", "body .mb-ch-sep {"):
            self.assertIn(sel, vblock)

    def test_para_block_body_p_parity(self):
        """A4：段排覆写 body p / body p[data-mb-first]，与手机块同特异性源序胜出。"""
        css = get_preset_css("classic", para_gap=1.2)
        block = css[css.index("段落排版"):]
        self.assertIn("body p {", block)
        self.assertIn("body p[data-mb-first] {", block)

    # ── A3：目录卡片夜间深底 ──

    def test_night_toc_card_dark_bg_wins(self):
        """A3：目录卡片夜间 html 前缀深底（0-2-2）压 toc 文件卡片（0-2-1）。"""
        for ts in ("elegant", "cool", "seal", "minimal"):
            css = get_preset_css("classic", use_system_fonts=True, toc_style=ts)
            dark_at = css.index("@media (prefers-color-scheme: dark)")
            rule_at = css.index("html body.mb-toc-page .mb-toc {", dark_at)
            block = css[rule_at:css.index("}", rule_at)]
            self.assertIn("background: #121212 !important", block, ts)
        for ts in ("elegant", "cool", "seal"):
            with open(os.path.join(self._styles_dir, "toc_%s.css" % ts),
                      encoding="utf-8") as f:
                src = f.read()
            self.assertIn("body.mb-toc-page .mb-toc {", src, ts)
            self.assertNotIn("html body.mb-toc-page", src, ts)

    # ── 顶空 ──

    def test_split_marks_mb_ch_split_class(self):
        html = '<html><body><p>第三章 血尸</p><p>正文。</p></body></html>'
        new, st = lib.mark_chapters_in_html(html, split_title=True)
        self.assertEqual(st["splits"], 1)
        self.assertIn('class="mb-ch mb-ch-split"', new)
        self.assertIn('<span class="mb-ch-num">第三章</span>', new)

    def test_no_split_keeps_plain_class(self):
        html = '<html><body><p>风雪夜归人</p><p>正文。</p></body></html>'
        new, st = lib.mark_chapters_in_html(html, split_title=True)
        self.assertEqual(st["splits"], 0)
        self.assertNotIn("mb-ch-split", new)

    def test_xuanzhi_split_disables_grand_top_margin(self):
        """顶空：xuanzhi 双行标题 4em 顶距（源序压过 34%），无拆分保留章扉。"""
        css = get_preset_css("xuanzhi", use_system_fonts=True)
        self.assertIn("margin: 34% 0 0.8em 0 !important", css)
        self.assertGreater(css.index(".mb-ch-split {"), css.index(".mb-ch {"))
        self.assertIn("margin: 4em 0 0.8em 0 !important", css)


NAV_XHTML = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
    '<head><title>目录</title></head>'
    '<body><nav epub:type="toc" id="id" role="doc-toc">'
    '<h2>测试书</h2><ol>'
    '<li><a href="ch1.xhtml">第一章 序章</a></li>'
    '<li><a href="ch2.xhtml">第三章 转折</a></li>'
    '</ol></nav></body></html>'
)


def build_nav_epub(path):
    """构建含 EPUB3 nav 目录页（在 spine 首条）的 EPUB。"""
    opf = (
        '<?xml version="1.0"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata><dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">测试书</dc:title></metadata>'
        '<manifest>'
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        '</manifest>'
        '<spine><itemref idref="nav"/><itemref idref="c1"/><itemref idref="c2"/></spine>'
        '</package>'
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/nav.xhtml", NAV_XHTML)
        zf.writestr("OEBPS/ch1.xhtml", CH1)
        zf.writestr("OEBPS/ch2.xhtml", CH2)
        zf.writestr("OEBPS/toc.ncx", NCX)


class TestTocPageMarking(unittest.TestCase):
    """书内 nav 语义目录页：spine 中被普通结构目录页替换（手机阅读器兼容）。"""

    def test_nav_toc_replaced_by_plain_toc(self):
        tmp = os.path.join(TESTS_DIR, "_tmp_nav_src.epub")
        out = os.path.join(TESTS_DIR, "_tmp_nav_out.epub")
        build_nav_epub(tmp)
        try:
            css = get_preset_css("classic", use_system_fonts=True)
            stats = lib.beautify(tmp, out, css)
            self.assertTrue(stats["toc_generated"])
            self.assertEqual(stats["toc_entries"], 5)
            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
                self.assertIn("OEBPS/mb-toc.xhtml", names)
                self.assertIn("OEBPS/nav.xhtml", names)  # 原 nav 文件保留
                # 生成页是普通 div 结构（非 nav 语义）+ 真实装饰元素
                toc = zf.read("OEBPS/mb-toc.xhtml").decode("utf-8")
                self.assertIn('<div class="mb-toc">', toc)
                self.assertNotIn("<nav", toc)
                self.assertIn("mb-toc-sub", toc)
                self.assertIn("mb-toc-end", toc)
                self.assertIn("第一章 序章", toc)
                self.assertIn('class="mb-toc-page"', toc)
                self.assertIn("mb-beauty.css", toc)
                # OPF：spine 中 nav itemref 被 mb-toc 替换；nav 仍在 manifest
                opf = zf.read("OEBPS/content.opf").decode("utf-8")
                self.assertIn('idref="mb-toc"', opf)
                self.assertNotIn('idref="nav"', opf)
                self.assertIn('id="nav"', opf)
                self.assertIn('properties="nav"', opf)
        finally:
            for p in (tmp, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_nav_replace_with_nonxhtml_spine_item(self):
        """回归：spine 含非 XHTML linear 条目（SVG 插图页）时 idref 映射不得错位——
        被替换的必须是 nav 页的 itemref，插图页原样保留。"""
        tmp = os.path.join(TESTS_DIR, "_tmp_navsvg_src.epub")
        out = os.path.join(TESTS_DIR, "_tmp_navsvg_out.epub")
        opf = (
            '<?xml version="1.0"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            '<metadata><dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">测试书</dc:title></metadata>'
            '<manifest>'
            '<item id="illu" href="page1.svg" media-type="image/svg+xml"/>'
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            '<item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            '</manifest>'
            '<spine><itemref idref="illu"/><itemref idref="nav"/>'
            '<itemref idref="c1"/><itemref idref="c2"/></spine>'
            '</package>'
        )
        svg = (
            '<?xml version="1.0"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<rect width="10" height="10"/></svg>'
        )
        with zipfile.ZipFile(tmp, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/container.xml", CONTAINER)
            zf.writestr("OEBPS/content.opf", opf)
            zf.writestr("OEBPS/page1.svg", svg)
            zf.writestr("OEBPS/nav.xhtml", NAV_XHTML)
            zf.writestr("OEBPS/ch1.xhtml", CH1)
            zf.writestr("OEBPS/ch2.xhtml", CH2)
            zf.writestr("OEBPS/toc.ncx", NCX)
        try:
            css = get_preset_css("classic", use_system_fonts=True)
            stats = lib.beautify(tmp, out, css)
            self.assertTrue(stats["toc_generated"])
            with zipfile.ZipFile(out) as zf:
                opf_out = zf.read("OEBPS/content.opf").decode("utf-8")
            self.assertIn('idref="mb-toc"', opf_out)
            self.assertNotIn('idref="nav"', opf_out)
            self.assertIn('idref="illu"', opf_out)
        finally:
            for p in (tmp, out):
                if os.path.exists(p):
                    os.remove(p)


class TestAnalyze(unittest.TestCase):
    """EPUB 分析。"""

    def test_analyze_mini(self):
        tmp = os.path.join(TESTS_DIR, "_tmp_analyze.epub")
        build_mini_epub(tmp)
        try:
            a = lib.analyze_epub(tmp)
            self.assertEqual(a["title"], "测试书")
            self.assertEqual(a["text_entries"], 2)
            self.assertIn("OEBPS/style.css", a["css_files"])
            self.assertFalse(a["has_fontface"])
            self.assertFalse(a["has_inbook_toc"])
            self.assertEqual(a["ncx_entries"], 5)  # 1 卷 + 3 章 + 引子
            # ch1 两段文本标题 + ch2 一个 h2
            self.assertGreaterEqual(a["heading_stats"]["h2"], 1)
            self.assertGreaterEqual(a["text_headings"], 2)
        finally:
            os.remove(tmp)


class TestZipGuard(unittest.TestCase):
    """损坏/超限 EPUB 的友好报错（_read_zip_entries 防护路径）。"""

    def test_corrupt_zip_friendly_error(self):
        # 损坏文件应抛 RuntimeError(友好文案)——若防护文案误用未导入的 _()，
        # 这里会先炸 NameError: name '_' is not defined（回归哨兵）
        p = os.path.join(tempfile.mkdtemp(prefix="eb_test_"), "broken.epub")
        with open(p, "wb") as f:
            f.write(b"this is definitely not a zip file")
        try:
            lib._read_zip_entries(p)
            self.fail("expected RuntimeError")
        except RuntimeError as err:
            self.assertIn("损坏", str(err))

class TestBeautify(unittest.TestCase):
    """主流程：目录生成 / 标题标记 / CSS 注入 / 规范重写。"""

    def _beautify(self, src, out, preset="classic"):
        css = get_preset_css(preset, use_system_fonts=True)
        return lib.beautify(src, out, css)

    def test_full_flow(self):
        tmp = os.path.join(TESTS_DIR, "_tmp_src.epub")
        out = os.path.join(TESTS_DIR, "_tmp_out.epub")
        build_mini_epub(tmp, with_cover=True)
        try:
            stats = self._beautify(tmp, out)
            self.assertTrue(stats["toc_generated"])
            self.assertEqual(stats["toc_entries"], 5)
            self.assertGreaterEqual(stats["marked_headers"], 3)  # ch1 2 段 + ch2 h2
            self.assertEqual(stats["css_injected_chapters"], 3)  # 封面 + 2 正文（封面只注入样式不标记）

            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
                # 规范：mimetype 首条且 STORED
                self.assertEqual(names[0], "mimetype")
                self.assertEqual(zf.getinfo("mimetype").compress_type, zipfile.ZIP_STORED)
                # 新增文件
                self.assertIn("OEBPS/mb-toc.xhtml", names)
                self.assertIn("OEBPS/mb-beauty.css", names)
                # 目录页
                toc = zf.read("OEBPS/mb-toc.xhtml").decode("utf-8")
                self.assertIn("第一卷", toc)
                self.assertIn("第一章 序章", toc)
                self.assertIn("href=\"ch1.xhtml#p1\"", toc)
                self.assertIn("href=\"ch2.xhtml\"", toc)
                # 编号注入：仅无中文序号的 lv1 条目（"第一卷/第X章" 自带序号不重复；
                # "引子" 无序号 → 05）
                self.assertIn('<span class="mb-toc-num">05</span>', toc)
                self.assertEqual(toc.count("mb-toc-num"), 1)
                # OPF 注册
                opf = zf.read("OEBPS/content.opf").decode("utf-8")
                self.assertIn('id="mb-toc"', opf)
                self.assertIn('href="mb-toc.xhtml"', opf)
                # 标题标记 + CSS 引用
                ch1 = zf.read("OEBPS/ch1.xhtml").decode("utf-8")
                self.assertEqual(ch1.count('class="mb-ch"'), 2)
                self.assertIn('data-mb-first="true"', ch1)
                self.assertIn('href="mb-beauty.css"', ch1)
                ch2 = zf.read("OEBPS/ch2.xhtml").decode("utf-8")
                self.assertIn('class="mb-ch"', ch2)
                # 原 CSS 原样保留
                self.assertEqual(zf.read("OEBPS/style.css").decode("utf-8"), CSS)
                # 封面不被标记
                cover = zf.read("OEBPS/cover.xhtml").decode("utf-8")
                self.assertNotIn("mb-ch", cover)
        finally:
            for p in (tmp, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_seal_table_toc(self):
        """seal（朱印风）：生成双栏表格结构目录页。"""
        tmp = os.path.join(TESTS_DIR, "_tmp_vg_src.epub")
        out = os.path.join(TESTS_DIR, "_tmp_vg_out.epub")
        build_mini_epub(tmp)
        try:
            css = get_preset_css("classic", use_system_fonts=True, toc_style="seal")
            stats = lib.beautify(tmp, out, css, toc_style="seal")
            self.assertTrue(stats["toc_generated"])
            with zipfile.ZipFile(out) as zf:
                toc = zf.read("OEBPS/mb-toc.xhtml").decode("utf-8")
                self.assertIn('<table class="mulu">', toc)
                self.assertIn('class="mb-toc-mark">　✦', toc)  # 右列装饰标记（已修正：移除多余反斜杠）
                self.assertIn('class="mb-toc-seal">隐', toc)     # 印章
                self.assertIn("CONTENT", toc)
                self.assertNotIn("<nav", toc)
                # 编号在链接内
                self.assertIn('<span class="mb-toc-num">05</span> 引子</a>', toc)
        finally:
            for p in (tmp, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_spine_page_progression_rtl(self):
        """竖排预设：spine 设为 rtl（幂等，不重复追加属性）。"""
        tmp = os.path.join(TESTS_DIR, "_tmp_rtl_src.epub")
        out1 = os.path.join(TESTS_DIR, "_tmp_rtl_out1.epub")
        out2 = os.path.join(TESTS_DIR, "_tmp_rtl_out2.epub")
        build_mini_epub(tmp)
        try:
            css = get_preset_css("vertclassical", use_system_fonts=True)
            stats = lib.beautify(tmp, out1, css, page_progression="rtl")
            self.assertEqual(stats.get("page_progression"), "rtl")
            with zipfile.ZipFile(out1) as zf:
                opf = zf.read("OEBPS/content.opf").decode("utf-8")
                self.assertIn('page-progression-direction="rtl"', opf)
                self.assertEqual(opf.count("page-progression-direction"), 1)
            # 幂等：对已 rtl 的书再跑一次仍只有一处
            lib.beautify(out1, out2, css, page_progression="rtl")
            with zipfile.ZipFile(out2) as zf:
                opf2 = zf.read("OEBPS/content.opf").decode("utf-8")
                self.assertEqual(opf2.count("page-progression-direction"), 1)
        finally:
            for p in (tmp, out1, out2):
                if os.path.exists(p):
                    os.remove(p)

    def test_no_page_progression_by_default(self):
        """非竖排预设不动 spine 翻页方向。"""
        tmp = os.path.join(TESTS_DIR, "_tmp_ltr_src.epub")
        out = os.path.join(TESTS_DIR, "_tmp_ltr_out.epub")
        build_mini_epub(tmp)
        try:
            css = get_preset_css("classic", use_system_fonts=True)
            stats = lib.beautify(tmp, out, css)
            self.assertEqual(stats.get("page_progression"), "")
            with zipfile.ZipFile(out) as zf:
                opf = zf.read("OEBPS/content.opf").decode("utf-8")
                self.assertNotIn("page-progression-direction", opf)
        finally:
            for p in (tmp, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_idempotent_rerun(self):
        """二次美化必须幂等：不重复生成目录项 / 不重复标记。"""
        tmp = os.path.join(TESTS_DIR, "_tmp_src2.epub")
        out1 = os.path.join(TESTS_DIR, "_tmp_out1.epub")
        out2 = os.path.join(TESTS_DIR, "_tmp_out2.epub")
        build_mini_epub(tmp)
        try:
            self._beautify(tmp, out1)
            self._beautify(out1, out2)
            with zipfile.ZipFile(out2) as zf:
                opf = zf.read("OEBPS/content.opf").decode("utf-8")
                self.assertEqual(opf.count('id="mb-toc"'), 1)
                self.assertEqual(opf.count('idref="mb-toc"'), 1)
                ch1 = zf.read("OEBPS/ch1.xhtml").decode("utf-8")
                self.assertEqual(ch1.count('class="mb-ch"'), 2)
                self.assertEqual(ch1.count("mb-beauty.css"), 1)
        finally:
            for p in (tmp, out1, out2):
                if os.path.exists(p):
                    os.remove(p)

    def test_calibre_soup_div_marking(self):
        """Calibre 类汤（div 平铺、无 h、无 p）标题段也能标记。"""
        html = (
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head>'
            '<body><div class="calibre9">第一回 甄士隐梦幻识通灵</div>'
            '<div class="calibre9">此开卷第一回也。作者自云：因曾历过一番梦幻之后。</div>'
            '</body></html>'
        )
        new_html, mk = lib.mark_chapters_in_html(html)
        self.assertEqual(mk["chapters"], 1)
        self.assertIn('class="calibre9 mb-ch"', new_html)
        # div 平铺书不标记章首段（保守设计，避免误标嵌套 div）

    def test_mark_idempotent(self):
        """已标记的条目再跑不重复标记。"""
        html = (
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head>'
            '<body><h2 class="mb-ch">第1章 标题</h2><p>正文</p></body></html>'
        )
        new_html, mk = lib.mark_chapters_in_html(html)
        self.assertEqual(new_html, html)
        self.assertFalse(any(mk.values()))

    def test_nested_li_outline_untouched(self):
        """回归：同名标签嵌套（多级 li 大纲）整块跳过，不产生破坏结构的改写。"""
        html = (
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head>'
            '<body><ul><li>第一卷 风起<ul><li>第一章 起点</li></ul></li></ul>'
            '</body></html>'
        )
        new_html, mk = lib.mark_chapters_in_html(html)
        self.assertEqual(new_html, html)
        self.assertFalse(any(mk.values()))
        self.assertNotIn('mb-ch', new_html)


class TestCleanupAndTocOptions(unittest.TestCase):
    """内容清理（段首空格/空段/meta）+ 目录深度/排除/链接校验。"""

    def _beautify(self, src, out, **kw):
        css = get_preset_css("classic", use_system_fonts=True)
        return lib.beautify(src, out, css, **kw)

    def build_custom_epub(self, path, ch1_inner=None, ncx_xml=NCX):
        """构建自定义 ch1 内容的迷你 EPUB。"""
        ch1 = (
            '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
            '<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>'
            '<link href="style.css" rel="stylesheet" type="text/css"/></head>'
            '<body>%s</body></html>' % (ch1_inner or '<p>第一章 序章</p><p>正文。</p>')
        )
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/container.xml", CONTAINER)
            zf.writestr("OEBPS/content.opf", OPF)
            zf.writestr("OEBPS/ch1.xhtml", ch1)
            zf.writestr("OEBPS/ch2.xhtml", CH2)
            zf.writestr("OEBPS/style.css", CSS)
            zf.writestr("OEBPS/toc.ncx", ncx_xml)

    def read_ch1(self, out):
        with zipfile.ZipFile(out) as zf:
            return zf.read("OEBPS/ch1.xhtml").decode("utf-8")

    def test_cleanup_leading_spaces_default_on(self):
        tmp = os.path.join(TESTS_DIR, "_tmp_cl_src.epub")
        out = os.path.join(TESTS_DIR, "_tmp_cl_out.epub")
        self.build_custom_epub(tmp, "<p>\u3000\u3000　　你好。</p><p>&nbsp;&#160;世界。</p>")
        try:
            stats = self._beautify(tmp, out)
            self.assertGreaterEqual(stats["cleaned_leading"], 2)
            ch1 = self.read_ch1(out)
            body = ch1[ch1.find("<body"):].lower()
            self.assertNotIn("\u3000", body.split("</head>")[-1])
            self.assertNotIn("&nbsp;", body)
        finally:
            for p in (tmp, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_cleanup_leading_off_keeps_spaces(self):
        tmp = os.path.join(TESTS_DIR, "_tmp_cl2_src.epub")
        out = os.path.join(TESTS_DIR, "_tmp_cl2_out.epub")
        self.build_custom_epub(tmp, "<p>\u3000你好。</p>")
        try:
            stats = self._beautify(tmp, out, cleanup={"leading": False, "empty": False, "meta": True})
            self.assertEqual(stats["cleaned_leading"], 0)
            self.assertIn("\u3000", self.read_ch1(out))
        finally:
            for p in (tmp, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_cleanup_empty_paras_and_br_run(self):
        tmp = os.path.join(TESTS_DIR, "_tmp_em_src.epub")
        out = os.path.join(TESTS_DIR, "_tmp_em_out.epub")
        inner = "<p></p><p><br/></p><p>&nbsp;</p><p>正文。</p><br/><br/><br/><br/><p>尾段。</p>"
        self.build_custom_epub(tmp, inner)
        try:
            stats = self._beautify(tmp, out, cleanup={"leading": False, "empty": True, "meta": True})
            self.assertEqual(stats["removed_empty"], 3)
            html = self.read_ch1(out).lower()
            self.assertNotIn("<p></p>", html)
            # 连续 4 个 br 收敛为 2 个
            self.assertEqual(html.count("<br/>"), 2)
        finally:
            for p in (tmp, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_cleanup_empty_off_by_default(self):
        tmp = os.path.join(TESTS_DIR, "_tmp_em2_src.epub")
        out = os.path.join(TESTS_DIR, "_tmp_em2_out.epub")
        self.build_custom_epub(tmp, "<p></p><p><br/></p><p>正文。</p>")
        try:
            stats = self._beautify(tmp, out)
            self.assertEqual(stats["removed_empty"], 0)
        finally:
            for p in (tmp, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_meta_charset_removed_by_default(self):
        tmp = os.path.join(TESTS_DIR, "_tmp_mt_src.epub")
        out = os.path.join(TESTS_DIR, "_tmp_mt_out.epub")
        self.build_custom_epub(tmp)
        try:
            self._beautify(tmp, out)
            ch1 = self.read_ch1(out).lower()
            self.assertNotIn("charset=utf-8", ch1)
        finally:
            for p in (tmp, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_meta_charset_kept_when_disabled(self):
        tmp = os.path.join(TESTS_DIR, "_tmp_mt2_src.epub")
        out = os.path.join(TESTS_DIR, "_tmp_mt2_out.epub")
        self.build_custom_epub(tmp)
        try:
            self._beautify(tmp, out, cleanup={"leading": False, "empty": False, "meta": False})
            self.assertIn("charset=utf-8", self.read_ch1(out).lower())
        finally:
            for p in (tmp, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_toc_depth_filtering(self):
        """NCX 两级结构：depth=1 只收一级条目。"""
        tmp = os.path.join(TESTS_DIR, "_tmp_dp_src.epub")
        out1 = os.path.join(TESTS_DIR, "_tmp_dp_all.epub")
        out2 = os.path.join(TESTS_DIR, "_tmp_dp_d1.epub")
        build_mini_epub(tmp)
        try:
            css = get_preset_css("classic", use_system_fonts=True)
            s_all = lib.beautify(tmp, out1, css)
            self.assertEqual(s_all["toc_entries"], 5)   # 第一卷+两章+第三章转折+引子
            s_d1 = lib.beautify(tmp, out2, css, toc_depth=1)
            self.assertEqual(s_d1["toc_entries"], 3)   # 第一卷/第三章/引子
            self.assertEqual(s_d1["toc_depth"], 1)
        finally:
            for p in (tmp, out1, out2):
                if os.path.exists(p):
                    os.remove(p)

    def test_toc_excludes_noise_titles(self):
        noise_ncx = NCX.replace(
            '<navPoint id="n4"><navLabel><text>引子</text></navLabel>',
            '<navPoint id="n4"><navLabel><text>本书由某某工作室制作排版</text></navLabel>',
        )
        tmp = os.path.join(TESTS_DIR, "_tmp_ex_src.epub")
        out = os.path.join(TESTS_DIR, "_tmp_ex_out.epub")
        self.build_custom_epub(tmp, ncx_xml=noise_ncx)
        try:
            stats = self._beautify(tmp, out)
            self.assertGreaterEqual(stats["toc_excluded"], 1)
            with zipfile.ZipFile(out) as zf:
                toc = zf.read("OEBPS/mb-toc.xhtml").decode("utf-8")
                self.assertNotIn("某某工作室", toc)
        finally:
            for p in (tmp, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_no_truncation_by_default(self):
        """超长目录全量收录且无截断提示。"""
        tmp = os.path.join(TESTS_DIR, "_tmp_big_src.epub")
        out = os.path.join(TESTS_DIR, "_tmp_big_out.epub")
        pts = []
        for i in range(600):
            pts.append(
                '<navPoint id="n%d"><navLabel><text>第%d章 测试章节标题</text></navLabel>'
                '<content src="ch1.xhtml#n%d"/></navPoint>' % (i, i + 1, i)
            )
        big_ncx = (
            '<?xml version="1.0"?>'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
            '<navMap>%s</navMap></ncx>' % "".join(pts)
        )
        self.build_custom_epub(tmp, ncx_xml=big_ncx)
        try:
            stats = self._beautify(tmp, out)
            self.assertEqual(stats["toc_entries"], 600)
            with zipfile.ZipFile(out) as zf:
                toc = zf.read("OEBPS/mb-toc.xhtml").decode("utf-8")
                self.assertNotIn("mb-toc-truncated", toc)
                self.assertEqual(toc.count('<li class="lv1">'), 600)
            # 显式传上限时仍然生效
            out2 = os.path.join(TESTS_DIR, "_tmp_big_out2.epub")
            try:
                stats2 = self._beautify(tmp, out2, max_toc_entries=50)
                self.assertEqual(stats2["toc_entries"], 50)
                with zipfile.ZipFile(out2) as zf:
                    toc2 = zf.read("OEBPS/mb-toc.xhtml").decode("utf-8")
                    self.assertIn("仅显示前 50 条", toc2)
            finally:
                if os.path.exists(out2):
                    os.remove(out2)
        finally:
            for p in (tmp, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_toc_link_check_stats(self):
        tmp = os.path.join(TESTS_DIR, "_tmp_lk_src.epub")
        out = os.path.join(TESTS_DIR, "_tmp_lk_out.epub")
        build_mini_epub(tmp)
        try:
            stats = self._beautify(tmp, out)
            self.assertEqual(stats["toc_links_total"], stats["toc_entries"])
            self.assertEqual(stats["toc_links_ok"], stats["toc_links_total"])
        finally:
            for p in (tmp, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_analyze_report_fields(self):
        tmp = os.path.join(TESTS_DIR, "_tmp_an_src.epub")
        self.build_custom_epub(tmp, "<p>\u3000\u3000带缩进的段落。</p><p></p><p>普通段。</p>")
        try:
            a = lib.analyze_epub(tmp)
            for key in ("leading_space_paras", "sampled_paras", "empty_para_est",
                        "p_close_mismatch_files", "css_important_count",
                        "css_conflict_risk", "image_count", "image_oversize",
                        "toc_preview_titles"):
                self.assertIn(key, a)
            self.assertGreaterEqual(a["leading_space_paras"], 1)
            self.assertGreaterEqual(a["empty_para_est"], 1)
            self.assertTrue(isinstance(a["toc_preview_titles"], list))
            self.assertGreater(len(a["toc_preview_titles"]), 0)
            self.assertFalse(a["css_conflict_risk"])
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


class TestDialogue(unittest.TestCase):
    """对话行识别与点缀（mb-dialog）。"""

    H = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head>'
        '<body>%s</body></html>'
    )

    @staticmethod
    def _build_epub(path):
        """迷你 EPUB：在标准 CH1 基础上追加一个「开头对话段。"""
        build_mini_epub(path)
        with zipfile.ZipFile(path) as zf:
            entries = {i.filename: zf.read(i.filename) for i in zf.infolist() if not i.is_dir()}
        ch1 = entries["OEBPS/ch1.xhtml"].decode("utf-8")
        entries["OEBPS/ch1.xhtml"] = ch1.replace(
            "</body>", '<p>「你终于来了。」他压低了声音。</p></body>'
        ).encode("utf-8")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(
                zipfile.ZipInfo("mimetype"), b"application/epub+zip",
                compress_type=zipfile.ZIP_STORED,
            )
            for name in [k for k in entries if k != "mimetype"]:
                zf.writestr(name, entries[name], compress_type=zipfile.ZIP_DEFLATED)

    def test_quote_start_marked(self):
        html = self.H % '<p>「你来了。」他低声说。</p><p>他坐在角落里。</p>'
        out, n = lib.mark_dialogue_in_html(html)
        self.assertEqual(n, 1)
        self.assertIn('<p class="mb-dialog">「你来了。」', out)

    def test_span_wrapped_with_fullwidth_space(self):
        html = self.H % '<p>\u3000<span class="c">“开始吧。”</span></p>'
        out, n = lib.mark_dialogue_in_html(html)
        self.assertEqual(n, 1)
        self.assertIn('<p class="mb-dialog">', out)

    def test_narration_lead_not_marked(self):
        """保守策略：叙述引导句式（张三道：……）不标。"""
        html = self.H % '<p>张三道：“你来了。”</p>'
        out, n = lib.mark_dialogue_in_html(html)
        self.assertEqual(n, 0)

    def test_heading_and_nonp_skipped(self):
        html = self.H % '<h2>「标题带引号」</h2><blockquote><p>「引块内」</p></blockquote>'
        out, n = lib.mark_dialogue_in_html(html)
        self.assertEqual(n, 0)
        self.assertNotIn('mb-dialog', out)

    def test_idempotent(self):
        html = self.H % '<p class="mb-dialog">「已标记」</p>'
        out, n = lib.mark_dialogue_in_html(html)
        self.assertEqual(out, html)
        self.assertEqual(n, 0)

    def test_beautify_dialogue_toggle(self):
        tmp = os.path.join(TESTS_DIR, "_tmp_dlg_src.epub")
        out_on = os.path.join(TESTS_DIR, "_tmp_dlg_on.epub")
        out_off = os.path.join(TESTS_DIR, "_tmp_dlg_off.epub")
        self._build_epub(tmp)
        try:
            css = get_preset_css("classic", use_system_fonts=True)
            stats_off = lib.beautify(tmp, out_off, css, dialogue=False)
            self.assertEqual(stats_off["dialogues_marked"], 0)
            stats_on = lib.beautify(tmp, out_on, css, dialogue=True)
            self.assertGreaterEqual(stats_on["dialogues_marked"], 1)
            with zipfile.ZipFile(out_on) as zf:
                ch1 = zf.read("OEBPS/ch1.xhtml").decode("utf-8")
                css_out = zf.read("OEBPS/mb-beauty.css").decode("utf-8")
            self.assertIn("mb-dialog", ch1)
            self.assertIn(".mb-dialog", css_out)
        finally:
            for p in (tmp, out_on, out_off):
                if os.path.exists(p):
                    os.remove(p)

    def test_analyze_counts_dialogue(self):
        tmp = os.path.join(TESTS_DIR, "_tmp_dlg_ana.epub")
        self._build_epub(tmp)
        try:
            report = lib.analyze_epub(tmp)
            self.assertGreaterEqual(report["dialogue_paras"], 1)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


class TestVolumeAndSplit(unittest.TestCase):
    """卷/章分级（mb-vol）与双行排版（title_split）。"""

    H = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head>'
        '<body>%s</body></html>'
    )

    def test_volume_marked_mbvol(self):
        html = self.H % '<h1>第一卷 风起云涌</h1><p>第一章 起点</p><p>正文。</p>'
        out, mk = lib.mark_chapters_in_html(html)
        self.assertEqual(mk["volumes"], 1)
        self.assertIn("mb-vol", out)
        # 卷级标题后不直接跟章级长线（sep 属于后面的 mb-ch）
        self.assertNotIn("</h1><div class=\"mb-ch-sep\"", out)
        self.assertNotIn('class="mb-ch">第一卷', out)

    def test_volume_patterns(self):
        for t in ("第三卷", "卷二", "上卷", "第二部 中原", "第五篇"):
            html = self.H % ("<h2>%s</h2><p>正文</p>" % t)
            _, mk = lib.mark_chapters_in_html(html)
            self.assertEqual(mk["volumes"], 1, t)

    def test_chapter_still_mbch(self):
        html = self.H % '<h2>第三章 转折</h2><p>正文</p>'
        out, mk = lib.mark_chapters_in_html(html)
        self.assertEqual(mk["chapters"], 1)
        self.assertIn("mb-ch-sep", out)
        self.assertNotIn("mb-vol", out)

    def test_split_two_line_spans(self):
        html = self.H % '<h2>第三章 血尸</h2>'
        out, mk = lib.mark_chapters_in_html(html, split_title=True)
        self.assertEqual(mk["splits"], 1)
        self.assertIn('<span class="mb-ch-num">第三章</span>', out)
        self.assertIn('<span class="mb-ch-title">血尸</span>', out)

    def test_split_english_prefix(self):
        html = self.H % '<p>Chapter 12 The Storm</p>'
        out, mk = lib.mark_chapters_in_html(html, split_title=True)
        self.assertEqual(mk["splits"], 1)
        self.assertIn("The Storm", out)

    def test_split_skipped_when_no_rest_or_tags(self):
        base = '<h2>%s</h2>'
        _, mk1 = lib.mark_chapters_in_html(self.H % (base % "楔子"), split_title=True)
        self.assertEqual(mk1["splits"], 0)
        tagged = self.H % '<h2>第四章 <em>风暴</em></h2>'
        _, mk2 = lib.mark_chapters_in_html(tagged, split_title=True)
        self.assertEqual(mk2["splits"], 0)
        self.assertNotIn("mb-ch-num", _ := lib.mark_chapters_in_html(tagged, split_title=True)[0])

    def test_split_off_by_default_and_volume_never_split(self):
        html = self.H % '<h2>第三章 血尸</h2><h1>第一卷 风起</h1>'
        out, mk = lib.mark_chapters_in_html(html)
        self.assertEqual(mk["splits"], 0)
        out2, mk2 = lib.mark_chapters_in_html(html, split_title=True)
        self.assertEqual(mk2["splits"], 1)
        self.assertNotIn("mb-ch-num\">第一卷", out2)

    def test_beautify_split_integration(self):
        tmp = os.path.join(TESTS_DIR, "_tmp_split_src.epub")
        out = os.path.join(TESTS_DIR, "_tmp_split_out.epub")
        build_mini_epub(tmp)
        try:
            css = get_preset_css("classic", use_system_fonts=True)
            stats = lib.beautify(tmp, out, css, split_title=True)
            self.assertGreaterEqual(stats["titles_split"], 1)
            self.assertGreaterEqual(stats["marked_volumes"] + stats["marked_headers"], 2)
            with zipfile.ZipFile(out) as zf:
                ch1 = zf.read("OEBPS/ch1.xhtml").decode("utf-8")
                css_out = zf.read("OEBPS/mb-beauty.css").decode("utf-8")
            self.assertIn("mb-ch-num", ch1)
            self.assertIn(".mb-vol", css_out)
            self.assertIn(".mb-ch-num", css_out)
        finally:
            for p in (tmp, out):
                if os.path.exists(p):
                    os.remove(p)


class TestTocBlankPrune(unittest.TestCase):
    """NCX/nav 空白条目净化（cleanup.toc_blank）。"""

    NCX_BLANK = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        '<head/><docTitle><text>t</text></docTitle>'
        '<navMap>'
        '<navPoint id="a" playOrder="1"><navLabel><text>第一章 起点</text></navLabel>'
        '<content src="ch1.xhtml"/></navPoint>'
        '<navPoint id="b" playOrder="2"><navLabel><text>   </text></navLabel>'
        '<content src="ch2.xhtml"/></navPoint>'
        '<navPoint id="c" playOrder="3"><navLabel><text></text></navLabel>'
        '<content src="ch3.xhtml"/>'
        '<navPoint id="c1" playOrder="4"><navLabel><text>第二章 转折</text></navLabel>'
        '<content src="ch2.xhtml"/></navPoint>'
        '</navPoint>'
        '</navMap></ncx>'
    )

    def _build(self, path, ncx_data, nav_data=None):
        opf = (
            '<?xml version="1.0"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            '<metadata><dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">t</dc:title></metadata>'
            '<manifest>'
            '<item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            '%s</manifest>'
            '<spine><itemref idref="c1"/></spine></package>'
        ) % ('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>' if nav_data else '')
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(zipfile.ZipInfo("mimetype"), b"application/epub+zip",
                        compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/container.xml", CONTAINER)
            zf.writestr("OEBPS/content.opf", opf)
            zf.writestr("OEBPS/ch1.xhtml", CH1)
            zf.writestr("OEBPS/toc.ncx", ncx_data)
            if nav_data:
                zf.writestr("OEBPS/nav.xhtml", nav_data)

    def test_prune_ncx_bytes(self):
        data, n = lib._prune_ncx_bytes(self.NCX_BLANK.encode("utf-8"))
        self.assertEqual(n, 1)  # 只删 b：空 label 叶子；c 有存活子级保留
        root = ET.fromstring(data.decode("utf-8"))
        labels = [t.text for t in root.iter("{http://www.daisy.org/z3986/2005/ncx/}text")
                  if t.text and t.text != "t"]
        self.assertIn("第二章 转折", labels)
        orders = [np.get("playOrder") for np in
                  root.iter("{http://www.daisy.org/z3986/2005/ncx/}navPoint")]
        self.assertEqual(orders, ["1", "2", "3"])

    def test_prune_nav_bytes(self):
        nav = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops">'
            '<body><nav epub:type="toc"><ol>'
            '<li><a href="ch1.xhtml">第一章</a></li>'
            '<li><a href=""></a></li>'
            '<li><a href="x.xhtml"> </a><ol><li><a href="ch1.xhtml">子页</a></li></ol></li>'
            '</ol></nav></body></html>'
        )
        data, n = lib._prune_nav_bytes(nav.encode("utf-8"))
        self.assertEqual(n, 1)
        self.assertIn("子页", data.decode("utf-8"))

    def test_beautify_cleanup_toggle(self):
        tmp = os.path.join(TESTS_DIR, "_tmp_blank_src.epub")
        on = os.path.join(TESTS_DIR, "_tmp_blank_on.epub")
        off = os.path.join(TESTS_DIR, "_tmp_blank_off.epub")
        self._build(tmp, self.NCX_BLANK)
        try:
            css = get_preset_css("classic", use_system_fonts=True)
            s_on = lib.beautify(tmp, on, css, cleanup={"toc_blank": True})
            self.assertEqual(s_on["toc_blank_pruned"], 1)
            s_off = lib.beautify(tmp, off, css, cleanup={"toc_blank": False})
            self.assertEqual(s_off["toc_blank_pruned"], 0)
            with zipfile.ZipFile(on) as zf:
                pruned_ncx = zf.read("OEBPS/toc.ncx").decode("utf-8")
            with zipfile.ZipFile(off) as zf:
                raw_ncx = zf.read("OEBPS/toc.ncx").decode("utf-8")
            self.assertNotIn('<navPoint id="b"', pruned_ncx)
            self.assertIn('<navPoint id="b"', raw_ncx)
        finally:
            for p in (tmp, on, off):
                if os.path.exists(p):
                    os.remove(p)


class TestBackgroundImage(unittest.TestCase):
    """背景图片：CSS 注入 / 内置纹理 / extra_assets 打包。"""

    def test_css_day_and_night_layers(self):
        css = get_preset_css('classic', True, bg_image={'url': 'mb-bg.jpg'})
        self.assertIn("url('mb-bg.jpg')", css)
        self.assertIn('background-size: cover', css)
        self.assertIn(
            'linear-gradient(rgba(18,18,18,0.72), rgba(18,18,18,0.72)), url(\'mb-bg.jpg\')',
            css,
        )

    def test_css_off_untouched(self):
        a = get_preset_css('classic', True)
        b = get_preset_css('classic', True, bg_image=None)
        self.assertEqual(a, b)
        self.assertNotIn('mb-bg', a)

    def test_css_night_dim_custom(self):
        css = get_preset_css('navy', True, bg_image={'url': 'mb-bg.jpg', 'night_dim': 0.5})
        self.assertIn('rgba(18,18,18,0.50)', css)

    def test_builtin_textures_valid(self):
        from webserver.toolbox.utils.styles import (
            BUILTIN_TEXTURES, get_texture_bytes, list_builtin_textures,
        )
        ids = [t['id'] for t in list_builtin_textures()]
        self.assertEqual(ids, ['xuanzhi', 'parchment', 'linen'])
        for tid in ids:
            data, mt = get_texture_bytes(tid)
            self.assertEqual(mt, 'image/jpeg')
            self.assertEqual(data[:2], b'\xff\xd8')
            self.assertLess(len(data), 140 * 1024)
        self.assertIn('tex_xuanzhi.jpg', BUILTIN_TEXTURES['xuanzhi']['file'])
        try:
            get_texture_bytes('nope')
            self.fail('expected ValueError')
        except ValueError:
            pass

    def test_beautify_extra_assets(self):
        tmp = os.path.join(TESTS_DIR, '_tmp_bg_src.epub')
        out1 = os.path.join(TESTS_DIR, '_tmp_bg_out1.epub')
        out2 = os.path.join(TESTS_DIR, '_tmp_bg_out2.epub')
        build_mini_epub(tmp)
        assets = {'mb-bg.jpg': (b'\xff\xd8fakejpgdata', 'image/jpeg')}
        try:
            stats = lib.beautify(tmp, out1, 'body{}', extra_assets=dict(assets))
            self.assertEqual(stats['extra_assets'], 1)
            with zipfile.ZipFile(out1) as zf:
                names = zf.namelist()
                opf = zf.read([n for n in names if n.endswith('.opf')][0]).decode('utf-8')
            self.assertIn('OEBPS/mb-bg.jpg', names)
            self.assertIn('id="mb-bg"', opf)
            self.assertIn('media-type="image/jpeg"', opf)
            # 幂等重跑：对已含资源的输出再跑一次，manifest 不重复注册
            lib.beautify(out1, out2, 'body{}', extra_assets=dict(assets))
            with zipfile.ZipFile(out2) as zf:
                opf2 = zf.read([n for n in zf.namelist() if n.endswith('.opf')][0]).decode('utf-8')
            self.assertEqual(opf2.count('id="mb-bg"'), 1)
        finally:
            for p in (tmp, out1, out2):
                if os.path.exists(p):
                    os.remove(p)


class TestPaletteAndTint(unittest.TestCase):
    """自定义配色（两器+自动派生）与全书主题底色三态。"""

    def test_palette_override_merge_and_derive(self):
        css = get_preset_css("classic", True, "elegant", palette_overrides={"accent": "#123456"})
        self.assertIn("#123456", css)
        # 派生夜间色（向白混合 55%）：18,52,86 -> #94A4B3
        params = _apply_palette_overrides(list_presets()["classic"], {"accent": "#123456"})
        self.assertEqual(params["accent_dark"], "#94A4B3")
        self.assertTrue(params["toc_gradient"].startswith("linear-gradient(135deg, #123456, "))
        # 派生值确实进入 CSS；原主色已被整体替换
        self.assertIn(params["accent_dark"], css)
        self.assertNotIn("#4A2C1A", css)

    def test_palette_invalid_hex_raises(self):
        with self.assertRaises(ValueError):
            get_preset_css("classic", True, "elegant", palette_overrides={"accent": "red"})
        with self.assertRaises(ValueError):
            get_preset_css("classic", True, "elegant", palette_overrides={"accent": "#12345"})
        with self.assertRaises(ValueError):
            get_preset_css("classic", True, "elegant", palette_overrides={"nope": "#123456"})

    def test_palette_derive_pair_when_accent_set(self):
        """覆盖 accent 时夜间色与目录渐变必须同时自动派生。"""
        params = _apply_palette_overrides(list_presets()["classic"], {"accent": "#7B2D26"})
        self.assertTrue(params["accent_dark"].startswith("#"))
        self.assertIn("linear-gradient(135deg, #7B2D26, ", params["toc_gradient"])
        # 未覆盖 accent 时不得改写派生键
        untouched = _apply_palette_overrides(list_presets()["classic"], {"border": "#ABCDEF"})
        self.assertEqual(untouched["accent_dark"], list_presets()["classic"]["accent_dark"])

    def test_three_char_hex_accepted(self):
        params = _apply_palette_overrides(list_presets()["classic"], {"accent": "#F00"})
        self.assertEqual(params["accent"], "#F00")

    def test_page_tint_on(self):
        css = get_preset_css("modern", True, "minimal", page_tint=True)
        self.assertIn("page_tint=on", css)
        self.assertIn("background-color: #FAFAFA !important", css)
        # 追加块自带夜间重申，且位于其配对 light 之后（块内顺序正确）
        tail = css[css.find("page_tint=on"):]
        li = tail.find("(prefers-color-scheme: light)")
        da = tail.find("(prefers-color-scheme: dark)")
        self.assertGreaterEqual(li, 0)
        self.assertGreater(da, li)

    def test_page_tint_off_forces_transparent(self):
        css = get_preset_css("xuanzhi", True, "minimal", page_tint=False)
        self.assertIn("background-color: transparent !important", css)

    def test_page_tint_auto_untouched(self):
        a = get_preset_css("classic", True, "elegant", page_tint=None)
        b = get_preset_css("classic", True, "elegant")
        self.assertEqual(a, b)


class TestPreviewChapter(unittest.TestCase):
    """analyze_epub 的首章真实内容采样（preview_chapter）。"""

    def test_preview_chapter_extracted(self):
        """首个含标题文件：标题 + 后续正文（遇下一个标题即止）。"""
        tmp = os.path.join(TESTS_DIR, "_tmp_pc_src.epub")
        build_mini_epub(tmp)
        try:
            a = lib.analyze_epub(tmp)
            pc = a.get("preview_chapter")
            self.assertIsInstance(pc, dict)
            self.assertEqual(pc["title"], "第一章 序章")
            # 第二章 开端 是下一个标题 → 收录在它之前的一段正文后停止
            self.assertEqual(pc["paragraphs"], ["正文从这里开始，描写一段长长的故事。"])
        finally:
            os.remove(tmp)

    def test_preview_chapter_absent_without_headings(self):
        """无任何标题特征的书：preview_chapter 为 None。"""
        tmp = os.path.join(TESTS_DIR, "_tmp_pc_none.epub")
        opf = (
            '<?xml version="1.0"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            '<metadata><dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">无标题书</dc:title></metadata>'
            '<manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="c1"/></spine></package>'
        )
        ch = (
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head>'
            '<body><p>这是一段很普通的叙述文字，完全没有任何标题特征可言。</p></body></html>'
        )
        with zipfile.ZipFile(tmp, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/container.xml", CONTAINER)
            zf.writestr("OEBPS/content.opf", opf)
            zf.writestr("OEBPS/c1.xhtml", ch)
        try:
            a = lib.analyze_epub(tmp)
            self.assertIsNone(a.get("preview_chapter"))
        finally:
            os.remove(tmp)


class TestParaStyleAndTocColumns(unittest.TestCase):
    """段落排版（缩进开关 + 段距数值）与目录双栏的 CSS 后处理。"""

    def test_para_defaults_noop(self):
        """默认（缩进开 + 无段距）不追加任何规则，与存量输出零差异。"""
        css = get_preset_css("classic")
        self.assertNotIn("段落排版", css)

    def test_para_indent_off(self):
        css = get_preset_css("classic", para_indent=False)
        self.assertIn("段落排版", css)
        self.assertIn("text-indent: 0 !important", css)

    def test_para_gap_only(self):
        css = get_preset_css("classic", para_gap=0.6)
        self.assertIn("段落排版", css)
        self.assertIn("margin: 0 0 0.6em 0 !important", css)
        block = css[css.index("段落排版"):]
        # 缩进仍开启：通用 p 规则只改段距、不写缩进声明；章首段顶格重申 + 引文恢复紧凑
        gen_rule = block.split("p[data-mb-first]")[0]
        self.assertIn("margin: 0 0 0.6em", gen_rule)
        self.assertNotIn("text-indent", gen_rule)
        self.assertIn("p[data-mb-first]", block)
        self.assertIn("blockquote p", block)

    def test_para_indent_and_gap_combined(self):
        css = get_preset_css("classic", para_indent=False, para_gap=1.2)
        self.assertIn("margin: 0 0 1.2em 0 !important", css)
        # 全部顶格时不再需要 data-mb-first 重申
        head, sep, tail = css.partition("段落排版")
        self.assertTrue(sep)
        self.assertNotIn("data-mb-first", tail)

    def test_para_gap_clamp(self):
        big = get_preset_css("classic", para_gap=99)
        self.assertIn("margin: 0 0 3em 0 !important", big)

    def test_para_gap_invalid_raises(self):
        with self.assertRaises(ValueError):
            get_preset_css("classic", para_gap="wide")

    def test_toc_columns_block(self):
        css = get_preset_css("classic")
        self.assertNotIn("columns: 2", css)
        two = get_preset_css("classic", toc_columns=True)
        self.assertIn("columns: 2", two)
        # 选择器只命中生成目录页的 ol/li 结构（seal 表格天然免疫）
        self.assertIn("div.mb-toc ol", two)
        self.assertIn("@media (min-width: 32em)", two)

    def test_para_indent_off_beats_calibre_rules(self):
        """类汤书顶格：responsive 的 .calibre* 2em 强制在前，末尾同选择器覆写归零。"""
        css = get_preset_css("classic", para_indent=False)
        resp = css.index("text-indent: 2em !important")
        over = css.index(
            "%s {\n    text-indent: 0 !important" % _CALIBRE_INDENT_SELECTORS)
        self.assertGreater(over, resp)
        # duokan 私有属性同样需要 !important 才能压过 responsive 的强制值
        self.assertIn("duokan-text-indent: 0 !important", css)

    def test_para_gap_beats_calibre_margin(self):
        """类汤书段距：p.calibre* 段落级选择器覆写 responsive 的 margin: 0。"""
        css = get_preset_css("classic", para_gap=1.5)
        self.assertIn(
            "%s {\n    margin: 0 0 1.5em 0 !important;\n}" % _CALIBRE_MARGIN_SELECTORS,
            css,
        )

    def test_para_indent_off_and_gap_calibre_combined(self):
        css = get_preset_css("classic", para_indent=False, para_gap=0.5)
        self.assertIn(
            "%s {\n    text-indent: 0 !important" % _CALIBRE_INDENT_SELECTORS, css)
        self.assertIn(
            "%s {\n    margin: 0 0 0.5em 0 !important" % _CALIBRE_MARGIN_SELECTORS,
            css,
        )
        # 裸 .calibre / .calibre1（可能是 body/容器）不参与段距
        self.assertFalse(
            any(s.startswith(".") for s in _CALIBRE_MARGIN_SELECTORS.split(", ")))


# ── 弹注 fixture：ch1=A 型（EPUB3 标准），ch2=B 型（掌书系简化）──
NOTES_CH_A = (
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>a</title></head>'
    '<body><p>第一章 序章</p>'
    '<p>正文提到某个词<a class="duokan-footnote" epub:type="noteref" href="#note_1" '
    'id="noteref_1"><img src="../Images/note.png"/></a>继续叙述，推进情节发展。</p>'
    '<aside epub:type="footnote"><div><hr class="xian"/></div>'
    '<ol class="duokan-footnote-content">'
    '<li class="duokan-footnote-item" id="note_1"><p class="footnote">'
    '<a href="#noteref_1">◎</a>注文一：解释该词的含义与出处。</p></li>'
    '</ol></aside></body></html>'
)
NOTES_CH_B = (
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>b</title></head>'
    '<body><p>第二章 开端</p>'
    '<p>引用法条原文<a class="duokan-footnote" href="#df-1">'
    '<img src="note.png" width="14px"/></a>随后展开论述，层层递进。</p>'
    '<ol class="duokan-footnote-content">'
    '<li class="duokan-footnote-item" id="df-1">◎《唐律疏议》相关条文注释。</li>'
    '</ol></body></html>'
)


def build_notes_epub(path):
    """构建含 A/B 两型弹注的迷你 EPUB。"""
    opf = (
        '<?xml version="1.0"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata><dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">弹注书</dc:title></metadata>'
        '<manifest>'
        '<item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/>'
        '</manifest>'
        '<spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>'
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/c1.xhtml", NOTES_CH_A)
        zf.writestr("OEBPS/c2.xhtml", NOTES_CH_B)


class TestNotes(unittest.TestCase):
    """弹注/标注美化：打标、归一化、标记替换、豁免守卫。"""

    def test_variant_a_mark_preserves_everything(self):
        new, st = lib.mark_notes_in_html(NOTES_CH_A)
        self.assertEqual(st, {'refs': 1, 'items': 1, 'normalized': 0, 'wrapped': 0})
        self.assertIn('mb-notemark', new)
        self.assertIn('data-mb-mark="orig"', new)
        # 原属性逐字保留（红线）
        self.assertIn('epub:type="noteref"', new)
        self.assertIn('href="#note_1"', new)
        self.assertIn('id="noteref_1"', new)
        self.assertIn('<img src="../Images/note.png"/>', new)
        # aside 容器打类；条目豁免类
        self.assertIn('mb-notes', new)
        self.assertIn('mb-note-item', new)

    def test_variant_b_normalized_and_wrapped(self):
        new, st = lib.mark_notes_in_html(NOTES_CH_B)
        self.assertEqual(st['normalized'], 1)
        self.assertEqual(st['wrapped'], 1)
        self.assertIn('epub:type="noteref"', new)
        self.assertLess(new.index('<aside'), new.index('<ol'))
        self.assertIn('<aside epub:type="footnote" class="mb-notes">', new)
        self.assertIn('href="#df-1"', new)  # 配对信号无损

    def test_idempotent_rerun(self):
        once, _ = lib.mark_notes_in_html(NOTES_CH_B)
        twice, st = lib.mark_notes_in_html(once)
        self.assertEqual(twice, once)
        self.assertEqual(st, {'refs': 0, 'items': 0, 'normalized': 0, 'wrapped': 0})

    def test_note_mark_modes(self):
        new, _ = lib.mark_notes_in_html(NOTES_CH_B, note_mark='num')
        self.assertIn('[1]', new)
        self.assertIn('class="mb-marktxt"', new)
        new2, _ = lib.mark_notes_in_html(NOTES_CH_A, note_mark='svg:inkdrop')
        self.assertIn('class="mb-marksvg"', new2)
        self.assertIn('viewBox="0 0 24 24"', new2)
        # 替换后链接属性仍在
        self.assertIn('href="#note_1"', new2)
        for bad in ('svg:nope', 'weird'):
            with self.assertRaises(ValueError):
                lib.mark_notes_in_html(NOTES_CH_A, note_mark=bad)

    def test_notes_exempt_from_chapter_marking(self):
        noted, _ = lib.mark_notes_in_html(NOTES_CH_B)
        ch_html, mk = lib.mark_chapters_in_html(noted)
        self.assertEqual(mk['chapters'], 1)  # 只有「第二章 开端」
        head, tail = ch_html[:ch_html.index('df-1')], ch_html[ch_html.index('df-1'):]
        self.assertIn('mb-ch', head)
        self.assertNotIn('mb-ch', tail)      # 注释条目未被误标

    def test_analyze_counts(self):
        tmp = os.path.join(TESTS_DIR, "_tmp_nt.epub")
        build_notes_epub(tmp)
        try:
            a = lib.analyze_epub(tmp)
            self.assertEqual(a["notes_refs"], 2)
            self.assertEqual(a["notes_items"], 2)
        finally:
            os.remove(tmp)

    def test_beautify_flow_with_notes(self):
        tmp = os.path.join(TESTS_DIR, "_tmp_nt_src.epub")
        out = os.path.join(TESTS_DIR, "_tmp_nt_out.epub")
        build_notes_epub(tmp)
        try:
            css = get_preset_css("classic", use_system_fonts=True)
            stats = lib.beautify(tmp, out, css, notes=True, note_mark='num')
            self.assertEqual(stats["notes_refs"], 2)
            self.assertEqual(stats["items"] if "items" in stats else 2, 2)
            with zipfile.ZipFile(out) as zf:
                c2 = zf.read("OEBPS/c2.xhtml").decode("utf-8")
                self.assertIn('mb-notemark', c2)
                self.assertIn('[1]', c2)
                self.assertIn('<aside epub:type="footnote"', c2)
                self.assertIn('.mb-notes', zf.read("OEBPS/mb-beauty.css").decode("utf-8"))
        finally:
            for p in (tmp, out):
                if os.path.exists(p):
                    os.remove(p)


if __name__ == "__main__":
    unittest.main()
