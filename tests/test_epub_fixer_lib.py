# -*- coding: utf-8 -*-
"""epub_fixer_lib 核心单元测试（standalone，stub 掉 webserver / calibre 依赖）。

覆盖：13 项结构精修操作的探测/修复（正例 / 无问题书零操作 / 幂等）、
删文件级联（manifest/spine/guide/spine@toc）、NCX 与 EPUB3 nav 断链修复
（子级提升、playOrder 重排）、最终守门（本精修引入的断裂拒绝出包）、
analyze 与 repair 计数一致性、DRM 拒绝与字体混淆放行、规范 zip 写出。

运行：python tests/test_epub_fixer_lib.py
"""
import io
import os
import re
import sys
import tempfile
import types
import unittest
import zipfile
import xml.etree.ElementTree as ET

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLBOX_DIR = os.path.join(TESTS_DIR, "..", "webserver", "toolbox")


def _stub_webserver():
    """注入最小 webserver 依赖，使 epub_fixer_lib 可独立导入。"""
    webserver = types.ModuleType("webserver")
    toolbox = types.ModuleType("webserver.toolbox")
    toolbox.__path__ = [TOOLBOX_DIR]
    webserver.toolbox = toolbox

    i18n = types.ModuleType("webserver.i18n")
    i18n._ = lambda s: s
    webserver.i18n = i18n

    sys.modules.update({
        "webserver": webserver,
        "webserver.toolbox": toolbox,
        "webserver.i18n": i18n,
    })


_stub_webserver()

from webserver.toolbox.utils import epub_fixer_lib as lib  # noqa: E402

# ── 造书工具 ──────────────────────────────────────────────────────────────────

CONTAINER = (
    '<?xml version="1.0"?>'
    '<container version="1.0" '
    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
    '<rootfile full-path="OEBPS/content.opf" '
    'media-type="application/oebps-package+xml"/></rootfiles></container>')


def _item(iid, href, mt, props=''):
    p = ' properties="%s"' % props if props else ''
    return '<item id="%s" href="%s" media-type="%s"%s/>' % (iid, href, mt, p)


def _itemref(iid):
    return '<itemref idref="%s"/>' % iid


def _opf(items, spine, guide='', meta='', spine_attrs=' toc="ncx"',
         version='2.0'):
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package version="%s" xmlns="http://www.idpf.org/2007/opf" '
        'xmlns:opf="http://www.idpf.org/2007/opf" '
        'unique-identifier="uid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="uid">test-uid</dc:identifier>'
        '<dc:title>测试书</dc:title>'
        '<dc:creator opf:role="aut">张三</dc:creator>'
        '<dc:language>zh</dc:language>%s</metadata>'
        '<manifest>%s</manifest>'
        '<spine%s>%s</spine>%s</package>'
        % (version, meta, ''.join(items), spine_attrs, ''.join(spine), guide))


def _ncx(points):
    """points: [(src, label)]。"""
    body = ''.join(
        '<navPoint id="np%d" playOrder="%d"><navLabel><text>%s</text></navLabel>'
        '<content src="%s"/></navPoint>' % (i, i, label, src)
        for i, (src, label) in enumerate(points, 1))
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        '<head/><docTitle><text>测试书</text></docTitle>'
        '<navMap>%s</navMap></ncx>' % body)


def _doc(body, title='章'):
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<!DOCTYPE html>'
        '<html xmlns="http://www.w3.org/1999/xhtml">'
        '<head><title>%s</title></head><body>%s</body></html>' % (title, body))


def _css(content):
    return content


def _png(marker=b'PNGDATA'):
    return b'\x89PNG\r\n\x1a\n' + marker


def _nav_doc(toc_items):
    """toc_items: [(href, label)]。"""
    lis = ''.join('<li><a href="%s">%s</a></li>' % (h, t) for h, t in toc_items)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<!DOCTYPE html>'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops">'
        '<head><title>目录</title></head><body>'
        '<nav epub:type="toc"><ol>%s</ol></nav>'
        '<nav epub:type="landmarks"><ol>'
        '<li><a epub:type="bodymatter" href="ch1.xhtml">正文</a></li>'
        '</ol></nav></body></html>' % lis)


def _make_epub(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), files.get(
            "mimetype", b"application/epub+zip"),
            compress_type=zipfile.ZIP_STORED)
        for name, data in files.items():
            if name != "mimetype":
                zf.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def _good_book():
    """两章 + css + 被引用的图片，全部健康。"""
    opf = _opf(
        items=[
            _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
            _item('css', 'style.css', 'text/css'),
            _item('img1', 'cover.png', 'image/png'),
            _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
            _item('ch2', 'ch2.xhtml', 'application/xhtml+xml'),
        ],
        spine=[_itemref('ch1'), _itemref('ch2')])
    return _make_epub({
        'META-INF/container.xml': CONTAINER,
        'OEBPS/content.opf': opf,
        'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '第一章'), ('ch2.xhtml', '第二章')]),
        'OEBPS/style.css': _css('body{margin:0}'),
        'OEBPS/cover.png': _png(),
        'OEBPS/ch1.xhtml': _doc('<p>第一章 正文</p><img src="cover.png"/>', '第一章'),
        'OEBPS/ch2.xhtml': _doc('<p>第二章 正文</p>', '第二章'),
    })


class _TempEpub:
    """bytes → 临时文件路径上下文。"""

    def __init__(self, data: bytes):
        fd, self.path = tempfile.mkstemp(suffix='.epub')
        with os.fdopen(fd, 'wb') as f:
            f.write(data)

    def cleanup(self):
        try:
            os.remove(self.path)
        except OSError:
            pass


def _repair(data: bytes, ops=None, **kw):
    """repair_epub 便捷封装：返回 (out_bytes|None, report|None, error|None)。"""
    src = _TempEpub(data)
    out_path = src.path + '.out'
    try:
        try:
            report = lib.repair_epub(src.path, out_path, ops=ops, **kw)
            with open(out_path, 'rb') as f:
                return f.read(), report, None
        except Exception as err:  # noqa: BLE001
            return None, None, err
    finally:
        src.cleanup()
        try:
            os.remove(out_path)
        except OSError:
            pass


def _analyze(data: bytes, ops=None):
    src = _TempEpub(data)
    try:
        return lib.analyze_epub(src.path, ops=ops)
    finally:
        src.cleanup()


def _out_entries(out_bytes: bytes) -> dict:
    return dict(_zip_pairs(out_bytes))


def _zip_pairs(data: bytes):
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if not name.endswith('/'):
                yield name, zf.read(name)


def _zip_names(data: bytes) -> list:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return [i.filename for i in zf.infolist() if not i.is_dir()]


def _out_text(out_bytes: bytes, name: str) -> str:
    return _out_entries(out_bytes)[name].decode('utf-8')


def _entry_count(entries: dict, needle: str) -> int:
    return sum(1 for n in entries if needle.lower() in n.lower())


# ── normalize_ops ─────────────────────────────────────────────────────────────

class TestNormalizeOps(unittest.TestCase):

    def test_default_excludes_remove_unmanifested(self):
        ops = lib.normalize_ops(None)
        self.assertNotIn('remove_unmanifested', ops)
        self.assertEqual(len(ops), len(lib.OP_KEYS) - 1)

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError):
            lib.normalize_ops(['no_such_op'])

    def test_reordered_to_execution_order(self):
        ops = lib.normalize_ops(
            ['fix_broken_toc', 'remove_artifacts', 'encode_utf8'])
        self.assertEqual(
            ops,
            [k for k in lib.OP_KEYS
             if k in ('remove_artifacts', 'fix_broken_toc', 'encode_utf8')])


# ── remove_artifacts ──────────────────────────────────────────────────────────

class TestRemoveArtifacts(unittest.TestCase):

    def _book_with_junk(self, in_manifest=False):
        items = [
            _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
            _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
        ]
        if in_manifest:
            items.append(_item('junk', 'iTunesMetadata.plist', 'application/xml'))
        opf = _opf(items=items, spine=[_itemref('ch1')])
        files = {
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc('<p>正文</p>'),
            'iTunesMetadata.plist': b'<plist/>',
            'OEBPS/.DS_Store': b'junk',
        }
        return _make_epub(files)

    def test_detect_and_remove(self):
        data, report, err = _repair(self._book_with_junk())
        self.assertIsNone(err)
        entries = _out_entries(data)
        self.assertNotIn('iTunesMetadata.plist', entries)
        self.assertNotIn('OEBPS/.DS_Store', entries)
        self.assertEqual(report['ops']['remove_artifacts'], 2)

    def test_manifest_junk_cascades(self):
        out, report, err = _repair(self._book_with_junk(in_manifest=True))
        self.assertIsNone(err)
        self.assertNotIn('iTunesMetadata.plist', _out_entries(out))
        text = _out_text(out, 'OEBPS/content.opf')
        self.assertNotIn('id="junk"', text)

    def test_healthy_book_zero(self):
        out, report, err = _repair(_good_book())
        self.assertIsNone(err)
        self.assertEqual(report['ops']['remove_artifacts'], 0)

    def test_idempotent(self):
        once, _, _ = _repair(self._book_with_junk())
        _, report, err = _repair(once)
        self.assertIsNone(err)
        self.assertEqual(report['ops']['remove_artifacts'], 0)


# ── remove_missing_manifest ───────────────────────────────────────────────────

class TestRemoveMissingManifest(unittest.TestCase):

    def test_missing_doc_removed_with_spine(self):
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('gone', 'gone.xhtml', 'application/xhtml+xml'),
            ],
            spine=[_itemref('ch1'), _itemref('gone')])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc('<p>正文</p>'),
        })
        out, report, err = _repair(book)
        self.assertIsNone(err)
        text = _out_text(out, 'OEBPS/content.opf')
        self.assertNotIn('id="gone"', text)
        self.assertNotIn('idref="gone"', text)
        self.assertEqual(report['ops']['remove_missing_manifest'], 1)

    def test_missing_ncx_drops_spine_toc_attr(self):
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
            ],
            spine=[_itemref('ch1')])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/ch1.xhtml': _doc('<p>正文</p>'),
        })
        out, report, err = _repair(book)
        self.assertIsNone(err)
        self.assertEqual(report['ops']['remove_missing_manifest'], 1)
        self.assertNotIn('toc="ncx"', _out_text(out, 'OEBPS/content.opf'))

    def test_missing_guide_ref_removed(self):
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('gone', 'gone.xhtml', 'application/xhtml+xml'),
            ],
            spine=[_itemref('ch1')],
            guide='<guide><reference type="cover" title="封面" href="gone.xhtml"/>'
                  '<reference type="text" title="正文" href="ch1.xhtml"/></guide>')
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc('<p>正文</p>'),
        })
        out, _, err = _repair(book)
        self.assertIsNone(err)
        text = _out_text(out, 'OEBPS/content.opf')
        self.assertNotIn('href="gone.xhtml"', text)
        self.assertIn('href="ch1.xhtml"', text)

    def test_preexisting_missing_manifest_allowed_without_op(self):
        # 书自带断清单 + 用户没勾 remove_missing_manifest → 守门不得拦截
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('gone', 'gone.xhtml', 'application/xhtml+xml'),
            ],
            spine=[_itemref('ch1'), _itemref('gone')])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc('<p>正文</p>'),
        })
        out, report, err = _repair(book, ops=['remove_javascript'])
        self.assertIsNone(err)
        self.assertIsNotNone(out)
        # 未勾选的旧断裂原样保留
        self.assertIn('id="gone"', _out_text(out, 'OEBPS/content.opf'))
        self.assertEqual(report['ops']['remove_missing_manifest'], 0)

    def test_no_ops_still_passes_gate_on_dirty_book(self):
        # ops 为空（用户全不勾）→ 不跑精修不写回，守门对旧断裂零拦截
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('gone', 'gone.xhtml', 'application/xhtml+xml'),
            ],
            spine=[_itemref('ch1'), _itemref('gone')])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc('<p>正文</p>'),
        })
        out, report, err = _repair(book, ops=[])
        self.assertIsNone(err)
        self.assertIsNotNone(out)
        self.assertTrue(all(v == 0 for v in report['ops'].values()))


# ── add_unmanifested / remove_unmanifested ────────────────────────────────────

class TestUnmanifested(unittest.TestCase):

    def _book_with_loose_css(self):
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
            ],
            spine=[_itemref('ch1')])
        return _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc('<p>正文</p>'),
            'OEBPS/loose.css': _css('p{margin:0}'),
        })

    def test_add_unmanifested_registers(self):
        out, report, err = _repair(self._book_with_loose_css())
        self.assertIsNone(err)
        self.assertEqual(report['ops']['add_unmanifested'], 1)
        text = _out_text(out, 'OEBPS/content.opf')
        self.assertIn('href="loose.css"', text)
        self.assertIn('media-type="text/css"', text)

    def test_add_xhtml_sniffed(self):
        opf = _opf(
            items=[_item('ncx', 'toc.ncx', 'application/x-dtbncx+xml')],
            spine=[])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/extra.html': _doc('<p>x</p>'),
        })
        out, report, err = _repair(book, ops=['add_unmanifested'])
        self.assertIsNone(err)
        self.assertIn('media-type="application/xhtml+xml"',
                      _out_text(out, 'OEBPS/content.opf'))

    def test_add_skips_meta_inf_and_percent_encodes(self):
        opf = _opf(
            items=[_item('ncx', 'toc.ncx', 'application/x-dtbncx+xml')],
            spine=[])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'META-INF/extra.xml': b'<x/>',
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/has space.png': _png(),
        })
        out, report, err = _repair(book, ops=['add_unmanifested'])
        self.assertIsNone(err)
        text = _out_text(out, 'OEBPS/content.opf')
        self.assertNotIn('extra.xml', text)
        self.assertIn('has%20space.png', text)

    def test_add_skips_unknown_binary_with_warning(self):
        # EPUB3 下未知媒体类型无 fallback 过不了 epubcheck：只告警不登记
        opf = _opf(
            items=[_item('ncx', 'toc.ncx', 'application/x-dtbncx+xml')],
            spine=[])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/notes.txt': '备注'.encode('utf-8'),
            'OEBPS/data.bin': b'\x00\x01binary',
        })
        out, report, err = _repair(book, ops=['add_unmanifested'])
        self.assertIsNone(err)
        self.assertEqual(report['ops']['add_unmanifested'], 1)
        text = _out_text(out, 'OEBPS/content.opf')
        self.assertIn('notes.txt', text)
        self.assertNotIn('data.bin', text)
        self.assertTrue(any('data.bin' in w for w in report['warnings']),
                        report['warnings'])

    def test_remove_unmanifested_skips_ahref_linked(self):
        # 被正文 <a href> 引用的散件跳过删除（互链感知），无关散件照删
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
            ],
            spine=[_itemref('ch1')])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc('<p>见<a href="extra.xhtml">附录</a></p>'),
            'OEBPS/extra.xhtml': _doc('<p>附录</p>'),
            'OEBPS/loose.css': _css('p{}'),
        })
        out, report, err = _repair(book, ops=['remove_unmanifested'])
        self.assertIsNone(err)
        entries = _out_entries(out)
        self.assertIn('OEBPS/extra.xhtml', entries)  # 被互链引用 → 保留
        self.assertNotIn('OEBPS/loose.css', entries)  # 无关散件 → 照删
        self.assertEqual(report['ops']['remove_unmanifested'], 1)
        self.assertTrue(any('extra.xhtml' in w for w in report['warnings']),
                        report['warnings'])

    def test_remove_unmanifested_not_default(self):
        _, report, err = _repair(self._book_with_loose_css())
        self.assertIsNone(err)
        self.assertEqual(report['ops']['remove_unmanifested'], 0)

    def test_remove_unmanifested_explicit(self):
        out, report, err = _repair(
            self._book_with_loose_css(), ops=['remove_unmanifested'])
        self.assertIsNone(err)
        self.assertEqual(report['ops']['remove_unmanifested'], 1)
        self.assertNotIn('OEBPS/loose.css', _out_entries(out))

    def test_remove_unmanifested_gate_blocks_referenced(self):
        # 未登记图片被已登记文档引用：删除会断链，守门必须拒绝出包
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
            ],
            spine=[_itemref('ch1')])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc('<p>图</p><img src="extra.png"/>'),
            'OEBPS/extra.png': _png(),
        })
        out, _, err = _repair(book, ops=['remove_unmanifested'])
        self.assertIsInstance(err, lib.EpubRepairError)
        self.assertIsNone(out)

    def test_remove_unmanifested_with_toc_fix_cleans_nav(self):
        # 未登记文档被 NCX 引用 + fix_broken_toc 兜底 → 允许出包且目录干净
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
            ],
            spine=[_itemref('ch1')])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一'),
                                   ('extra.xhtml', '散件')]),
            'OEBPS/ch1.xhtml': _doc('<p>正文</p>'),
            'OEBPS/extra.xhtml': _doc('<p>未登记</p>'),
        })
        out, _, err = _repair(
            book, ops=['remove_unmanifested', 'fix_broken_toc'])
        self.assertIsNone(err)
        self.assertNotIn('OEBPS/extra.xhtml', _out_entries(out))
        ncx_text = _out_text(out, 'OEBPS/toc.ncx')
        self.assertNotIn('extra.xhtml', ncx_text)
        self.assertIn('ch1.xhtml', ncx_text)


# ── remove_javascript ─────────────────────────────────────────────────────────

class TestRemoveJavascript(unittest.TestCase):

    def _book_with_js(self):
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('app', 'app.js', 'application/javascript'),
            ],
            spine=[_itemref('ch1')])
        return _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc(
                '<p>正文</p><script type="text/javascript">alert(1)</script>'
                '<p>之后</p>'),
            'OEBPS/app.js': b'alert(1);',
        })

    def test_removed(self):
        out, report, err = _repair(self._book_with_js())
        self.assertIsNone(err)
        entries = _out_entries(out)
        self.assertNotIn('OEBPS/app.js', entries)
        self.assertNotIn(b'<script', entries['OEBPS/ch1.xhtml'])
        self.assertIn('之后'.encode('utf-8'), entries['OEBPS/ch1.xhtml'])
        self.assertEqual(report['ops']['remove_javascript'], 2)

    def test_healthy_book_zero(self):
        _, report, err = _repair(_good_book())
        self.assertIsNone(err)
        self.assertEqual(report['ops']['remove_javascript'], 0)

    def test_idempotent(self):
        once, _, _ = _repair(self._book_with_js())
        _, report, err = _repair(once)
        self.assertIsNone(err)
        self.assertEqual(report['ops']['remove_javascript'], 0)


# ── remove_drm_meta_tags ──────────────────────────────────────────────────────

class TestRemoveDrmMetaTags(unittest.TestCase):

    def _book(self, with_rights=True):
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
            ],
            spine=[_itemref('ch1')],
            meta='<meta name="adept.expected.resource" content="x"/>')
        files = {
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc(
                '<p>正文</p><meta name="adept.resource" content="y"/>'),
        }
        if with_rights:
            files['META-INF/rights.xml'] = b'<rights/>'
        return _make_epub(files)

    def test_removed(self):
        out, report, err = _repair(self._book())
        self.assertIsNone(err)
        entries = _out_entries(out)
        self.assertNotIn('META-INF/rights.xml', entries)
        self.assertNotIn(b'adept', entries['OEBPS/ch1.xhtml'])
        self.assertNotIn('adept', _out_text(out, 'OEBPS/content.opf'))
        self.assertEqual(report['ops']['remove_drm_meta_tags'], 3)

    def test_zero_when_clean(self):
        _, report, err = _repair(_good_book())
        self.assertIsNone(err)
        self.assertEqual(report['ops']['remove_drm_meta_tags'], 0)


# ── remove_page_maps ──────────────────────────────────────────────────────────

class TestRemovePageMaps(unittest.TestCase):

    def _book(self, spine_attrs=' toc="ncx" page-map="pm"'):
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('pm', 'pages.pagemap', 'application/oebps-page-map+xml'),
            ],
            spine=[_itemref('ch1')], spine_attrs=spine_attrs)
        return _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc(
                '<p>正文</p><a id="GBS.PG3" name="GBS.PG3"/>'),
            'OEBPS/pages.pagemap': b'<pageMap/>',
        })

    def test_removed(self):
        out, report, err = _repair(self._book())
        self.assertIsNone(err)
        entries = _out_entries(out)
        self.assertNotIn('OEBPS/pages.pagemap', entries)
        self.assertNotIn('page-map=', _out_text(out, 'OEBPS/content.opf'))
        self.assertNotIn(b'GBS.PG3', entries['OEBPS/ch1.xhtml'])
        self.assertEqual(report['ops']['remove_page_maps'], 3)

    def test_zero_when_clean(self):
        _, report, err = _repair(_good_book())
        self.assertIsNone(err)
        self.assertEqual(report['ops']['remove_page_maps'], 0)


# ── remove_xpgt ───────────────────────────────────────────────────────────────

class TestRemoveXpgt(unittest.TestCase):

    def _book(self):
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('css', 'style.css', 'text/css'),
                _item('tpl', 'page-template.xpgt',
                      'application/vnd.adobe-page-template+xml'),
            ],
            spine=[_itemref('ch1')])
        return _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc(
                '<p>正文</p>'
                '<link rel="stylesheet" href="page-template.xpgt"/>'),
            'OEBPS/style.css': _css(
                '@import url("page-template.xpgt");\np{margin:0}'),
            'OEBPS/page-template.xpgt': b'<template/>',
        })

    def test_removed(self):
        out, report, err = _repair(self._book())
        self.assertIsNone(err)
        entries = _out_entries(out)
        self.assertNotIn('OEBPS/page-template.xpgt', entries)
        self.assertNotIn(b'.xpgt', entries['OEBPS/style.css'])
        self.assertNotIn(b'.xpgt', entries['OEBPS/ch1.xhtml'])
        self.assertEqual(report['ops']['remove_xpgt'], 3)

    def test_zero_when_clean(self):
        _, report, err = _repair(_good_book())
        self.assertIsNone(err)
        self.assertEqual(report['ops']['remove_xpgt'], 0)


# ── strip_kobo ────────────────────────────────────────────────────────────────

class TestStripKobo(unittest.TestCase):

    def _book(self, nested_span=False):
        span = ('<span id="kobo.1.1"><b>加</b>粗</span>' if not nested_span
                else '<span id="kobo.1.1">外<b>内<span>嵌</span></b></span>')
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('kjs', 'js/kobo.js', 'application/javascript'),
                _item('kcss', 'css/kobo.css', 'text/css'),
            ],
            spine=[_itemref('ch1')])
        return _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc(
                '<!-- koboStyle --><p>前</p>' + span +
                '<link rel="stylesheet" href="css/kobo.css"/>'
                '<p>后</p>'),
            'OEBPS/js/kobo.js': b'kobo();',
            'OEBPS/css/kobo.css': _css('body{}'),
        })

    def test_removed(self):
        out, report, err = _repair(self._book())
        self.assertIsNone(err)
        entries = _out_entries(out)
        self.assertNotIn('OEBPS/js/kobo.js', entries)
        self.assertNotIn('OEBPS/css/kobo.css', entries)
        ch1 = entries['OEBPS/ch1.xhtml']
        self.assertNotIn(b'kobo', ch1)
        self.assertIn('<b>加</b>粗'.encode('utf-8'), ch1)
        # kobo.js 由先执行的 remove_javascript 删除，strip_kobo 剩 css+正文两个单元
        self.assertEqual(report['ops']['strip_kobo'], 2)

    def test_nested_span_conservative(self):
        out, _, err = _repair(self._book(nested_span=True))
        self.assertIsNone(err)
        ch1 = _out_entries(out)['OEBPS/ch1.xhtml']
        # 嵌套结构不暴力解包：内容保持完整（外层 span 保留）
        self.assertIn('外'.encode('utf-8'), ch1)
        self.assertIn('嵌'.encode('utf-8'), ch1)

    def test_no_marker_no_touch(self):
        # 有 kobo.js 文件但内容无任何 kobo 痕迹 → 不动手（标记门）
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('kjs', 'js/kobo.js', 'application/javascript'),
            ],
            spine=[_itemref('ch1')])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc('<p>纯正文</p>'),
            'js/kobo.js': b'x();',
        })
        _, report, err = _repair(book)
        self.assertIsNone(err)
        self.assertEqual(report['ops']['strip_kobo'], 0)

    def test_zero_when_clean(self):
        _, report, err = _repair(_good_book())
        self.assertIsNone(err)
        self.assertEqual(report['ops']['strip_kobo'], 0)


# ── remove_unused_images ──────────────────────────────────────────────────────

class TestRemoveUnusedImages(unittest.TestCase):

    def _book(self, opf_meta_cover=True, css_ref=True):
        meta = '<meta name="cover" content="img1"/>' if opf_meta_cover else ''
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('css', 'style.css', 'text/css'),
                _item('img1', 'cover.png', 'image/png'),
                _item('img2', 'used.png', 'image/png'),
                _item('img3', 'cssbg.png', 'image/png'),
                _item('img4', 'unused.png', 'image/png'),
            ],
            spine=[_itemref('ch1')], meta=meta)
        css = ('body{background:url(cssbg.png)}' if css_ref
               else 'body{color:#000}')
        return _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc('<p>图</p><img src="used.png"/>'),
            'OEBPS/style.css': _css(css),
            'OEBPS/cover.png': _png(b'COVER'),
            'OEBPS/used.png': _png(b'USED'),
            'OEBPS/cssbg.png': _png(b'CSSBG'),
            'OEBPS/unused.png': _png(b'UNUSED'),
        })

    def test_unused_deleted_referenced_kept(self):
        out, report, err = _repair(self._book())
        self.assertIsNone(err)
        entries = _out_entries(out)
        self.assertNotIn('OEBPS/unused.png', entries)
        for keep in ('OEBPS/cover.png', 'OEBPS/used.png', 'OEBPS/cssbg.png'):
            self.assertIn(keep, entries)
        self.assertEqual(report['ops']['remove_unused_images'], 1)

    def test_cover_meta_keeps_image_without_meta(self):
        out, report, err = _repair(self._book(opf_meta_cover=False))
        self.assertIsNone(err)
        entries = _out_entries(out)
        # 无 meta name=cover 时 cover.png 无引用 → 删；css 引用仍在
        self.assertNotIn('OEBPS/cover.png', entries)
        self.assertIn('OEBPS/cssbg.png', entries)
        self.assertEqual(report['ops']['remove_unused_images'], 2)

    def test_css_basename_conservative(self):
        # CSS 里引用一个不存在路径但同名 basename 的图 → 保守保留
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('css', 'style.css', 'text/css'),
                _item('img1', 'images/bg.png', 'image/png'),
            ],
            spine=[_itemref('ch1')])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc('<p>文</p>'),
            'OEBPS/style.css': _css('body{background:url(../missing/bg.png)}'),
            'OEBPS/images/bg.png': _png(),
        })
        _, report, err = _repair(book)
        self.assertIsNone(err)
        self.assertEqual(report['ops']['remove_unused_images'], 0)

    def test_svg_xlink_ref_counted(self):
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('svg', 'pic.svg', 'image/svg+xml'),
                _item('img1', 'inner.png', 'image/png'),
            ],
            spine=[_itemref('ch1')])
        svg = ('<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
               'xmlns:xlink="http://www.w3.org/1999/xlink">'
               '<image xlink:href="inner.png"/></svg>')
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc('<p>文</p><img src="pic.svg"/>'),
            'OEBPS/pic.svg': svg,
            'OEBPS/inner.png': _png(),
        })
        _, report, err = _repair(book)
        self.assertIsNone(err)
        self.assertEqual(report['ops']['remove_unused_images'], 0)

    def test_epub3_cover_image_property_kept(self):
        opf = _opf(
            version='3.0',
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('img1', 'cover.png', 'image/png', props='cover-image'),
                _item('img2', 'unused.png', 'image/png'),
            ],
            spine=[_itemref('ch1')])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc('<p>文</p>'),
            'OEBPS/cover.png': _png(),
            'OEBPS/unused.png': _png(),
        })
        out, report, err = _repair(book)
        self.assertIsNone(err)
        self.assertIn('OEBPS/cover.png', _out_entries(out))
        self.assertEqual(report['ops']['remove_unused_images'], 1)

    def test_ahref_linked_image_kept(self):
        # 点开大图反模式：<a href="fig.jpg"><img src="thumb.jpg"/></a>
        # fig 只被 <a href> 引用，漏判会误删并被守门整本拦下
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('img1', 'fig1.jpg', 'image/jpeg'),
                _item('img2', 'thumb.jpg', 'image/jpeg'),
                _item('img3', 'unused.png', 'image/png'),
            ],
            spine=[_itemref('ch1')])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc(
                '<p><a href="fig1.jpg"><img src="thumb.jpg"/></a></p>'),
            'OEBPS/fig1.jpg': b'\xff\xd8fakejpg',
            'OEBPS/thumb.jpg': b'\xff\xd8fakethumb',
            'OEBPS/unused.png': _png(),
        })
        out, report, err = _repair(book)
        self.assertIsNone(err)
        entries = _out_entries(out)
        self.assertIn('OEBPS/fig1.jpg', entries)   # <a href> 引用 → 保留
        self.assertIn('OEBPS/thumb.jpg', entries)  # img src 引用 → 保留
        self.assertNotIn('OEBPS/unused.png', entries)
        self.assertEqual(report['ops']['remove_unused_images'], 1)


# ── remove_broken_cover_pages ─────────────────────────────────────────────────

class TestRemoveBrokenCoverPages(unittest.TestCase):

    def _book(self, body='<img src="cover.png"/>', img_exists=False):
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('cover', 'titlepage.xhtml', 'application/xhtml+xml'),
            ] + ([_item('img1', 'cover.png', 'image/png')] if img_exists else []),
            spine=[_itemref('cover'), _itemref('ch1')])
        files = {
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('titlepage.xhtml', '封面'),
                                   ('ch1.xhtml', '正文')]),
            'OEBPS/ch1.xhtml': _doc('<p>正文</p>'),
            'OEBPS/titlepage.xhtml': _doc(body, '封面'),
        }
        if img_exists:
            files['OEBPS/cover.png'] = _png()
        return _make_epub(files)

    def test_broken_cover_page_removed(self):
        out, report, err = _repair(self._book())
        self.assertIsNone(err)
        entries = _out_entries(out)
        self.assertNotIn('OEBPS/titlepage.xhtml', entries)
        self.assertEqual(report['ops']['remove_broken_cover_pages'], 1)
        self.assertIn('OEBPS/ch1.xhtml', entries)

    def test_text_page_kept(self):
        _, report, err = _repair(self._book(body='<img src="cover.png"/><p>说</p>'))
        self.assertIsNone(err)
        self.assertEqual(report['ops']['remove_broken_cover_pages'], 0)

    def test_resolved_image_kept(self):
        _, report, err = _repair(self._book(img_exists=True))
        self.assertIsNone(err)
        self.assertEqual(report['ops']['remove_broken_cover_pages'], 0)

    def test_toc_entry_cleaned_without_toc_op(self):
        # 不勾 fix_broken_toc：兜底级联也应清掉指向已删页的 NCX 条目
        out, _, err = _repair(self._book(), ops=['remove_broken_cover_pages'])
        self.assertIsNone(err)
        ncx_text = _out_text(out, 'OEBPS/toc.ncx')
        self.assertNotIn('titlepage.xhtml', ncx_text)
        self.assertIn('ch1.xhtml', ncx_text)
        self.assertIn('playOrder="1"', ncx_text)

    def test_cascade_keeps_empty_navpoint(self):
        # 级联模式只删「指向已删文件」的条目：预存在的空壳 navPoint 不动
        ncx = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
            '<head/><docTitle><text>t</text></docTitle><navMap>'
            '<navPoint id="e" playOrder="1"><navLabel><text>空壳</text></navLabel>'
            '</navPoint>'
            '<navPoint id="p" playOrder="2"><navLabel><text>封面</text></navLabel>'
            '<content src="titlepage.xhtml"/></navPoint>'
            '<navPoint id="c" playOrder="3"><navLabel><text>正文</text></navLabel>'
            '<content src="ch1.xhtml"/></navPoint>'
            '</navMap></ncx>')
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('cover', 'titlepage.xhtml', 'application/xhtml+xml'),
            ],
            spine=[_itemref('cover'), _itemref('ch1')])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': ncx,
            'OEBPS/ch1.xhtml': _doc('<p>正文</p>'),
            'OEBPS/titlepage.xhtml': _doc('<img src="missing.png"/>', '封面'),
        })
        out, _, err = _repair(book, ops=['remove_broken_cover_pages'])
        self.assertIsNone(err)
        ncx_text = _out_text(out, 'OEBPS/toc.ncx')
        self.assertNotIn('titlepage.xhtml', ncx_text)
        self.assertIn('id="e"', ncx_text)  # 空壳保留（级联不越界）
        self.assertIn('ch1.xhtml', ncx_text)

    def test_broken_cover_page_linked_skipped(self):
        # 候选页被幸存章节 <a href> 互链引用 → 跳过删除（否则静默断链）
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('cover', 'titlepage.xhtml', 'application/xhtml+xml'),
            ],
            spine=[_itemref('cover'), _itemref('ch1')])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('titlepage.xhtml', '封面'),
                                   ('ch1.xhtml', '正文')]),
            'OEBPS/ch1.xhtml': _doc('<p>回到<a href="titlepage.xhtml">封面</a></p>'),
            'OEBPS/titlepage.xhtml': _doc('<img src="missing.png"/>', '封面'),
        })
        out, report, err = _repair(book)
        self.assertIsNone(err)
        entries = _out_entries(out)
        self.assertIn('OEBPS/titlepage.xhtml', entries)  # 被互链引用 → 保留
        self.assertEqual(report['ops']['remove_broken_cover_pages'], 0)


# ── fix_broken_toc ────────────────────────────────────────────────────────────

class TestFixBrokenToc(unittest.TestCase):

    def _ncx_book(self, points):
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
            ],
            spine=[_itemref('ch1')])
        return _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx(points),
            'OEBPS/ch1.xhtml': _doc('<p>正文</p>'),
        })

    def test_ncx_broken_removed_and_renumbered(self):
        out, report, err = _repair(self._ncx_book(
            [('gone.xhtml', '丢失'), ('ch1.xhtml', '一')]))
        self.assertIsNone(err)
        ncx_text = _out_text(out, 'OEBPS/toc.ncx')
        self.assertNotIn('gone.xhtml', ncx_text)
        self.assertIn('ch1.xhtml', ncx_text)
        self.assertEqual(report['ops']['fix_broken_toc'], 1)
        self.assertIn('playOrder="1"', ncx_text)

    def test_children_promoted(self):
        ncx = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
            '<head/><docTitle><text>t</text></docTitle><navMap>'
            '<navPoint id="p1" playOrder="1"><navLabel><text>丢失卷</text></navLabel>'
            '<content src="gone.xhtml"/>'
            '<navPoint id="p2" playOrder="2"><navLabel><text>一</text></navLabel>'
            '<content src="ch1.xhtml"/></navPoint>'
            '</navPoint></navMap></ncx>')
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
            ],
            spine=[_itemref('ch1')])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': ncx,
            'OEBPS/ch1.xhtml': _doc('<p>正文</p>'),
        })
        out, report, err = _repair(book)
        self.assertIsNone(err)
        ncx_text = _out_text(out, 'OEBPS/toc.ncx')
        self.assertNotIn('gone.xhtml', ncx_text)
        self.assertIn('ch1.xhtml', ncx_text)
        # 子级提升后父级不再嵌套包裹（ch1 条目与卷同级保留）
        self.assertEqual(report['ops']['fix_broken_toc'], 1)

    def test_empty_navpoint_removed_container_kept(self):
        ncx = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
            '<head/><docTitle><text>t</text></docTitle><navMap>'
            '<navPoint id="e" playOrder="1"><navLabel><text>空</text></navLabel>'
            '</navPoint>'
            '<navPoint id="c" playOrder="2"><navLabel><text>容器</text></navLabel>'
            '<navPoint id="c1" playOrder="3"><navLabel><text>一</text></navLabel>'
            '<content src="ch1.xhtml"/></navPoint>'
            '</navPoint></navMap></ncx>')
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
            ],
            spine=[_itemref('ch1')])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': ncx,
            'OEBPS/ch1.xhtml': _doc('<p>正文</p>'),
        })
        out, report, err = _repair(book)
        self.assertIsNone(err)
        ncx_text = _out_text(out, 'OEBPS/toc.ncx')
        self.assertNotIn('id="e"', ncx_text)
        self.assertIn('id="c"', ncx_text)
        self.assertEqual(report['ops']['fix_broken_toc'], 1)

    def test_epub3_nav_broken_removed(self):
        opf = _opf(
            version='3.0',
            items=[
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('nav', 'nav.xhtml', 'application/xhtml+xml', props='nav'),
            ],
            spine=[_itemref('ch1')], spine_attrs='')
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/nav.xhtml': _nav_doc(
                [('gone.xhtml', '丢失'), ('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc('<p>正文</p>'),
        })
        out, report, err = _repair(book)
        self.assertIsNone(err)
        nav_text = _out_text(out, 'OEBPS/nav.xhtml')
        self.assertNotIn('gone.xhtml', nav_text)
        self.assertIn('ch1.xhtml', nav_text)
        # landmarks nav 不受影响
        self.assertIn('bodymatter', nav_text)
        self.assertEqual(report['ops']['fix_broken_toc'], 1)

    def test_zero_when_clean(self):
        _, report, err = _repair(_good_book())
        self.assertIsNone(err)
        self.assertEqual(report['ops']['fix_broken_toc'], 0)


# ── encode_utf8 ───────────────────────────────────────────────────────────────

class TestEncodeUtf8(unittest.TestCase):

    def test_gbk_doc_converted(self):
        gbk_body = '<p>中文正文，GBK 编码。</p>'.encode('gbk')
        html = (
            '<?xml version="1.0" encoding="gbk"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml">'
            '<head><meta http-equiv="Content-Type" content="text/html; charset=gbk"/>'
            '</head><body>%s</body></html>' % gbk_body.decode('gbk'))
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
            ],
            spine=[_itemref('ch1')])
        book = _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': html.encode('gbk'),
        })
        out, report, err = _repair(book)
        self.assertIsNone(err)
        ch1 = _out_entries(out)['OEBPS/ch1.xhtml']
        self.assertIn('中文正文，GBK 编码。'.encode('utf-8'), ch1)
        self.assertNotIn('charset=gbk'.encode('utf-8'), ch1)
        self.assertEqual(report['ops']['encode_utf8'], 1)

    def test_zero_when_clean(self):
        _, report, err = _repair(_good_book())
        self.assertIsNone(err)
        self.assertEqual(report['ops']['encode_utf8'], 0)


# ── DRM ───────────────────────────────────────────────────────────────────────

class TestDrm(unittest.TestCase):

    def _book_with_encryption(self, algorithm):
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
            ],
            spine=[_itemref('ch1')])
        enc = (
            '<?xml version="1.0"?>'
            '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<enc:EncryptedData xmlns:enc="http://www.w3.org/2001/04/xmlenc#">'
            '<enc:EncryptionMethod Algorithm="%s"/>'
            '<enc:CipherData><enc:CipherReference URI="OEBPS/ch1.xhtml"/>'
            '</enc:CipherData></enc:EncryptedData></encryption>' % algorithm)
        return _make_epub({
            'META-INF/container.xml': CONTAINER,
            'META-INF/encryption.xml': enc,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc('<p>正文</p>'),
        })

    def test_real_drm_refused(self):
        out, _, err = _repair(self._book_with_encryption(
            'http://www.w3.org/2001/04/xmlenc#aes128-cbc'))
        self.assertIsInstance(err, lib.EpubDrmError)
        self.assertIsNone(out)

    def test_font_obfuscation_allowed(self):
        out, _, err = _repair(self._book_with_encryption(
            'http://www.idpf.org/2008/embedding'))
        self.assertIsNone(err)
        self.assertIsNotNone(out)

    def test_analyze_reports_drm_flag(self):
        result = _analyze(self._book_with_encryption(
            'http://www.w3.org/2001/04/xmlenc#aes128-cbc'))
        self.assertTrue(result['drm'])
        self.assertEqual(result['findings'], {})


# ── 全书组合 / 守门 / 写出质量 ─────────────────────────────────────────────────

class TestPipeline(unittest.TestCase):

    def _dirty_book(self):
        """集齐各类问题的书：垃圾、缺清单、断链 NCX、JS、未用图片、GBS。"""
        opf = _opf(
            items=[
                _item('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
                _item('ch1', 'ch1.xhtml', 'application/xhtml+xml'),
                _item('gone', 'gone.xhtml', 'application/xhtml+xml'),
                _item('app', 'app.js', 'application/javascript'),
                _item('junk_img', 'unused.png', 'image/png'),
            ],
            spine=[_itemref('ch1'), _itemref('gone')],
            meta='<meta name="adept.expected.resource" content="x"/>')
        return _make_epub({
            'META-INF/container.xml': CONTAINER,
            'OEBPS/content.opf': opf,
            'OEBPS/toc.ncx': _ncx([('gone.xhtml', '丢'), ('ch1.xhtml', '一')]),
            'OEBPS/ch1.xhtml': _doc(
                '<p>正文</p><script>a()</script><a id="GBS.PG1"/>'),
            'OEBPS/app.js': b'a();',
            'OEBPS/unused.png': _png(),
            '.DS_Store': b'junk',
        })

    def test_full_pipeline(self):
        out, report, err = _repair(self._dirty_book())
        self.assertIsNone(err)
        entries = _out_entries(out)
        self.assertNotIn('.DS_Store', entries)
        self.assertNotIn('OEBPS/app.js', entries)
        self.assertNotIn('OEBPS/unused.png', entries)
        opf_text = entries['OEBPS/content.opf'].decode('utf-8')
        self.assertNotIn('id="gone"', opf_text)
        self.assertNotIn('idref="gone"', opf_text)
        self.assertNotIn('adept', opf_text)
        ch1 = entries['OEBPS/ch1.xhtml']
        self.assertNotIn(b'<script', ch1)
        self.assertNotIn(b'GBS.PG1', ch1)
        ncx_text = entries['OEBPS/toc.ncx'].decode('utf-8')
        self.assertNotIn('gone.xhtml', ncx_text)
        self.assertIn('ch1.xhtml', ncx_text)
        for key in ('remove_artifacts', 'remove_missing_manifest',
                    'remove_javascript', 'remove_drm_meta_tags',
                    'remove_unused_images', 'remove_page_maps',
                    'fix_broken_toc'):
            self.assertGreater(report['ops'][key], 0, key)

    def test_analyze_matches_repair_counts(self):
        result = _analyze(self._dirty_book())
        out, report, err = _repair(self._dirty_book())
        self.assertIsNone(err)
        for key, info in result['findings'].items():
            self.assertEqual(
                info['count'], report['ops'][key],
                'analyze/repair 计数不一致：%s' % key)

    def test_repaired_book_is_clean(self):
        once, _, err = _repair(self._dirty_book())
        self.assertIsNone(err)
        result = _analyze(once)
        for key, info in result['findings'].items():
            self.assertEqual(info['count'], 0, '二次分析仍有问题：%s' % key)

    def test_output_zip_canonical(self):
        out, _, err = _repair(self._dirty_book())
        self.assertIsNone(err)
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            infos = zf.infolist()
            self.assertEqual(infos[0].filename, 'mimetype')
            self.assertEqual(infos[0].compress_type, zipfile.ZIP_STORED)
            self.assertEqual(zf.read('mimetype'), b'application/epub+zip')

    def test_source_file_untouched(self):
        src = _TempEpub(self._dirty_book())
        try:
            with open(src.path, 'rb') as f:
                before = f.read()
            lib.repair_epub(src.path, src.path + '.out')
            with open(src.path, 'rb') as f:
                self.assertEqual(f.read(), before)
        finally:
            src.cleanup()
            try:
                os.remove(src.path + '.out')
            except OSError:
                pass

    def test_progress_callback(self):
        stages = []
        src = _TempEpub(self._dirty_book())
        out_path = src.path + '.out'
        try:
            lib.repair_epub(src.path, out_path,
                            progress_cb=lambda p, s: stages.append((p, s)))
            self.assertGreaterEqual(len(stages), 3)
            pcts = [p for p, _ in stages]
            self.assertEqual(pcts, sorted(pcts))
            self.assertIn('gate', [s for _, s in stages])
        finally:
            src.cleanup()
            try:
                os.remove(out_path)
            except OSError:
                pass

    def test_opf_prefixed_attrs_preserved(self):
        """OPF 文本级手术不得重序列化：opf: 前缀属性必须原样保留。"""
        out, _, err = _repair(self._dirty_book())
        self.assertIsNone(err)
        opf_text = _out_text(out, 'OEBPS/content.opf')
        self.assertIn('opf:role="aut"', opf_text)
        root = ET.fromstring(opf_text)
        creator = root.find('.//{http://purl.org/dc/elements/1.1/}creator')
        self.assertIsNotNone(creator)
        self.assertEqual(
            creator.get('{http://www.idpf.org/2007/opf}role'), 'aut')

    def test_corrupt_zip_rejected(self):
        src = _TempEpub(b'not a zip at all')
        try:
            with self.assertRaises(lib.EpubRepairError):
                lib.repair_epub(src.path, src.path + '.out')
        finally:
            src.cleanup()
            try:
                os.remove(src.path + '.out')
            except OSError:
                pass


if __name__ == '__main__':
    unittest.main(verbosity=1)
