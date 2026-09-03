# -*- coding: utf-8 -*-
"""EPUB 美化核心库。

对既有 EPUB 做无损美化（生成新书模式，原书零改动）：
1. **目录**：书内已有目录页时仅样式化；无目录页时从 NCX/nav（EPUB3 nav）
   生成 ``mb-toc.xhtml`` 目录页并注册进 OPF（manifest + spine，幂等）；
2. **章节名**：正文条目三层识别章节标题（h1-h6 / 已知标题类 / 段落文本
   章节正则，后者移植自 hehetoshang/txt2epub-next，MIT）并标记 ``mb-ch``，
   章首段标记 ``data-mb-first``；
3. **字体与排版**：注入 ``mb-beauty.css``（styles/ 预设模板插值），覆盖层
   方式追加，不删除原书任何文件与规则。

EPUB 容器读写（container → OPF → manifest/spine、mimetype 置首 ZIP_STORED
规范重写、编码兜底）沿用「正文查找替换」工具已验证的实现模式。
"""

import logging
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import quote, unquote

from webserver.toolbox.utils import chapter_patterns

_NS_CONTAINER = 'urn:oasis:names:tc:opendocument:xmlns:container'
_NS_OPF = 'http://www.idpf.org/2007/opf'
_NS_XHTML = 'http://www.w3.org/1999/xhtml'
_NS_DTBNCX = 'http://www.daisy.org/z3986/2005/ncx/'

# 前置页文件名特征（跳过章节标题标记，避免把"书籍信息/作者简介"当章节名）
# 用 \b 避免 index 误伤 index_split_001.html 等分章文件
_FRONT_FILE_RE = re.compile(
    r'\b(?:cover|titlepage|title-page|title|banquan|copyright|colophon|imprint|'
    r'feiye|zuozhe|author|mulu|toc|nav|contents|index|description|introduction|'
    r'explanation|version|preface|foreword|afterword|half-title|halftitle|dedication)\b',
    re.IGNORECASE,
)
# body 上的 epub:type 前置标记（只匹配属性上下文，避免 id 名里的 toc 误伤）
_FRONT_TYPE_RE = re.compile(
    r'epub:type\s*=\s*["\'][^"\']*\b(cover|title-page|titlepage|copyright|colophon|frontmatter|toc|imprint)\b',
    re.IGNORECASE,
)
# 已知章节标题类名关键词（配合 h/p 块文本规则）
_TITLE_CLASS_RE = re.compile(
    r'(chapter-title|chaptertitle|contenttitle|pretxttitle|head|title-line|'
    r'title|caption-title|chapter)',
    re.IGNORECASE,
)
# 块级元素扫描（h1-6 / p / blockquote / li；div 单独处理无嵌套形式）
_BLOCK_RE = re.compile(
    r'<(h[1-6]|p|blockquote|li)\b([^>]*)>(.*?)</\1>',
    re.DOTALL | re.IGNORECASE,
)
# 无嵌套 div（内含标签但不含 div 层级）——Calibre 类汤书的标题段常是 div
_SIMPLE_DIV_RE = re.compile(
    r'<div\b([^>]*)>((?:(?!</?div)[\s\S])*?)</div>',
    re.DOTALL | re.IGNORECASE,
)
# 标签/注释（提取文本段用）
_TAG_RE = re.compile(
    r'(<(?:[^>"\']*|"[^"]*"|\'[^\']*\')*>|<!--[\s\S]*?-->)',
    re.DOTALL,
)
# 从块文本里剥掉内联标签
_INLINE_RE = re.compile(r'<[^>]+>')

MB_CSS_NAME = 'mb-beauty.css'
MB_TOC_NAME = 'mb-toc.xhtml'
# 目录条目默认**不截断**（取消 500 条上限；如需限制可显式传 max_toc_entries）

# ── 内容清理（借鉴 Sigil CleanSource 思路，仅思路自研实现）──────────────────
# 段首空白：全角空格/半角空格/tab/换行 + nbsp 实体，出现在 <p> 开标签之后
_LEADING_WS_RE = re.compile(r'(<p\b[^>]*>)((?:&nbsp;|&#160;|[\s\u3000])+)', re.IGNORECASE)
# 空段落：只有空白/nbsp/br 的 p（默认不启用，精排书可能用空段造留白）
_EMPTY_P_RE = re.compile(r'<p\b[^>]*>(?:&nbsp;|&#160;|<br\s*/?>|[\s\u3000])*</p>', re.IGNORECASE)
# 连续 br 收敛：3 个及以上连续 <br/> 收敛为 2 个
_BR_RUN_RE = re.compile(r'(?:<br\s*/?>[\s\u3000]*){3,}', re.IGNORECASE)
# 冗余 meta charset（EPUB 规范要求 UTF-8，无需声明；部分制作工具会残留）
_META_CHARSET_RE = re.compile(r'[ \t]*<meta[^>]+charset[^>]*>[ \t]*\n?', re.IGNORECASE)
# 目录噪音排除（保守清单：只排无争议的制作信息，不动 前言/序/附录 这类正章）
_TOC_EXCLUDE_RE = re.compile(
    r'本书由|版权所有|侵权必究|监制|制作说明|出版说明$|^出品$|更多精彩|'
    r'未完待续|^完$|全书完|^正文完$|'
    r'www\.|https?://|[\w.-]+\.(com|net|cn|org)([/\s]|$)',
    re.IGNORECASE,
)


def _normalize_cleanup(cleanup):
    """归一化清理开关：{"leading":bool,"empty":bool,"meta":bool,"toc_blank":bool}。

    默认（混合策略）：段首空格归一开、空段清理关、meta 移除开、
    NCX/nav 空白条目净化开（只删零信息空条目）。
    """
    c = dict(cleanup) if isinstance(cleanup, dict) else {}
    return {
        'leading': bool(c.get('leading', True)),
        'empty': bool(c.get('empty', False)),
        'meta': bool(c.get('meta', True)),
        'toc_blank': bool(c.get('toc_blank', True)),
    }


def _clean_html_body(html_str: str, cleanup: dict) -> tuple:
    """对单个正文文件执行内容清理。

    :return: (new_html, cleaned_leading, removed_empty)
    """
    n_lead = n_empty = 0
    new = html_str
    if cleanup.get('leading'):
        new, n_lead = _LEADING_WS_RE.subn(r'\1', new)
    if cleanup.get('empty'):
        new, k1 = _EMPTY_P_RE.subn('', new)
        new, _ = _BR_RUN_RE.subn('<br/><br/>', new)
        n_empty = k1
    if cleanup.get('meta'):
        stripped = _META_CHARSET_RE.sub('', new, count=2)
        # DOCTYPE 头规整：声明后保证一个换行（幂等）
        stripped = re.sub(r'(<!DOCTYPE[^>]*>)(?![ \t]*\r?\n)', r'\1\n', stripped, count=1, flags=re.IGNORECASE)
        new = stripped
    return new, n_lead, n_empty


def _toc_entry_allowed(title: str) -> bool:
    """目录条目是否收录（排除制作信息类噪音标题）。"""
    return not _TOC_EXCLUDE_RE.search(title or '')


# ── EPUB 容器基础（沿用 text_replace 模式）────────────────────────────────────

# ZipBomb 阈值（500MB 总量 / 5000 文件；单文件与解压后实际总量同限）
_ZIP_MAX_TOTAL = 500 * 1024 * 1024
_ZIP_MAX_ENTRIES = 5000


def _opf_add_to_manifest(opf_str: str, item_xml: str, what: str) -> str:
    """把 ``<item/>`` 注册进 OPF manifest（P6：``</manifest>`` 缺失/异形时显式
    报错，不再静默 no-op 导致目录/样式注册丢失仍出包）。"""
    new, n = re.subn(r'(</manifest>)', '\n' + item_xml + r'\1', opf_str, count=1)
    if n == 0:
        raise RuntimeError('OPF 缺 </manifest>，无法注册%s' % what)
    return new


def _read_zip_entries(path: str) -> dict:
    """读取 zip 全部文件条目 {name: bytes}（跳过目录项，校验路径与大小）。

    双重校验（P2）：解压前按中央目录 info.file_size 预判，但头部可伪造；
    解压后按实际 len(data) 累计再拦一次，伪造小尺寸的超大解压流在此截停。
    """
    entries = {}
    try:
        with zipfile.ZipFile(path, 'r') as zf:
            declared = 0
            actual = 0
            for info in zf.infolist():
                if info.is_dir():
                    continue
                # 路径穿越校验
                if info.filename.startswith('/') or '..' in info.filename.split('/'):
                    logging.warning("[epub_beautify] Skip traversal entry: %s", info.filename)
                    continue
                declared += info.file_size
                if declared > _ZIP_MAX_TOTAL or len(entries) > _ZIP_MAX_ENTRIES:
                    raise RuntimeError("EPUB 文件过大或条目过多，疑似 Zip Bomb")
                data = zf.read(info.filename)
                actual += len(data)
                if len(data) > _ZIP_MAX_TOTAL or actual > _ZIP_MAX_TOTAL:
                    raise RuntimeError("EPUB 解压后体积异常，疑似 Zip Bomb")
                entries[info.filename] = data
    except zipfile.BadZipFile as e:
        raise RuntimeError("EPUB 解析失败，文件可能已损坏：%s" % e) from e
    except zipfile.LargeZipFile as e:
        raise RuntimeError("EPUB 文件过大：%s" % e) from e
    return entries


def _write_zip(entries: dict, out_path: str) -> None:
    """规范重写 zip：mimetype 置首且 ZIP_STORED，其余 DEFLATED（原子写）。"""
    order = [k for k in entries if k != 'mimetype']
    tmp = out_path + ".tmp"
    with zipfile.ZipFile(tmp, 'w') as zout:
        zout.writestr(
            zipfile.ZipInfo('mimetype'),
            entries.get('mimetype', b'application/epub+zip'),
            compress_type=zipfile.ZIP_STORED,
        )
        for name in order:
            zout.writestr(name, entries[name], compress_type=zipfile.ZIP_DEFLATED)
    os.replace(tmp, out_path)


def _decode(data: bytes) -> str:
    """UTF-8 优先，失败用编码检测（支持 GBK/Big5/Shift_JIS 等），并重写 XML 声明为 utf-8。"""
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        # 复用 txt 编码修复的检测器，对 GBK/Big5 做可读性打分择优，避免 Big5 被 gb18030 静默错译
        try:
            from .encoding_detect import decode_with_report
            text, report = decode_with_report(data)
            if not report.get('garbage') and not report.get('unrecoverable'):
                if text.lstrip().startswith('<?xml'):
                    text = re.sub(r"""(<\?xml[^>]*encoding\s*=\s*)["'][^"']*["']""", r'\1"utf-8"', text, count=1, flags=re.IGNORECASE)
                return text
        except Exception:
            pass
        # 回退：依次尝试 GB18030 / Big5，择优或兜底
        for enc in ('gb18030', 'big5'):
            try:
                text = data.decode(enc)
                if text.lstrip().startswith('<?xml'):
                    text = re.sub(r"""(<\?xml[^>]*encoding\s*=\s*)["'][^"']*["']""", r'\1"utf-8"', text, count=1, flags=re.IGNORECASE)
                return text
            except UnicodeDecodeError:
                continue
        text = data.decode('utf-8', errors='replace')
        if text.lstrip().startswith('<?xml'):
            text = re.sub(r"""(<\?xml[^>]*encoding\s*=\s*)["'][^"']*["']""", r'\1"utf-8"', text, count=1, flags=re.IGNORECASE)
        return text


# ── OPF 解析 ──────────────────────────────────────────────────────────────────

def _q(tag, ns=_NS_OPF):
    return '{%s}%s' % (ns, tag)


class OpfContext:
    """解析后的 OPF 上下文。"""

    def __init__(self):
        self.opf_path = ''
        self.opf_dir = ''
        self.title = ''
        self.manifest = {}       # id -> {'href','mt','props'}
        self.spine = []          # [(idref, linear_bool)]
        self.ncx_path = ''       # zip 内 NCX 路径（可能为空）
        self.nav_path = ''       # zip 内 EPUB3 nav 文档路径（可能为空）
        self.nav_id = ''         # nav 文档的 manifest id


def _parse_opf(entries: dict) -> OpfContext:
    """从 container.xml 定位 OPF 并解析 manifest/spine/NCX/nav。"""
    ctx = OpfContext()
    container = entries.get('META-INF/container.xml')
    if not container:
        raise RuntimeError('缺少 META-INF/container.xml')
    root = ET.fromstring(_decode(container))
    full_path = ''
    for rf in root.iter(_q('rootfile', _NS_CONTAINER)):
        full_path = rf.get('full-path') or ''
        break
    if not full_path or full_path not in entries:
        raise RuntimeError('无法定位 OPF 文件')
    ctx.opf_path = full_path
    ctx.opf_dir = full_path.rsplit('/', 1)[0] + '/' if '/' in full_path else ''

    opf = ET.fromstring(_decode(entries[full_path]))
    # 标题（dc:title，Dublin Core 命名空间）
    for t in opf.iter(_q('title', 'http://purl.org/dc/elements/1.1/')):
        ctx.title = (t.text or '').strip()
        break
    # manifest
    for item in opf.iter(_q('item')):
        iid = item.get('id') or ''
        href = item.get('href') or ''
        mt = (item.get('media-type') or '').lower()
        props = item.get('properties') or ''
        ctx.manifest[iid] = {'href': href, 'mt': mt, 'props': props}
        if mt == 'application/x-dtbncx+xml':
            ctx.ncx_path = _snap_entry(entries, _resolve_zip(ctx.opf_dir, href))
        if 'nav' in props.split():
            ctx.nav_path = _snap_entry(entries, _resolve_zip(ctx.opf_dir, href))
            ctx.nav_id = iid
    # spine
    spine = opf.find(_q('spine'))
    if spine is not None:
        for itemref in spine.iter(_q('itemref')):
            ctx.spine.append((itemref.get('idref') or '', itemref.get('linear', 'yes').lower() != 'no'))
    return ctx


def _resolve_zip(base_dir: str, href: str) -> str:
    """把 OPF 相对 href 解析为 zip 内绝对路径。"""
    href = href.split('#')[0].split('?')[0]
    if href.startswith('/'):
        return href.lstrip('/')
    return base_dir + href


def _snap_entry(entries: dict, path: str) -> str:
    """把解析出的路径对齐到 zip 实际条目名。

    部分制作工具（如掌书系）OPF manifest 的 href 为百分号编码
    （``%2A_%2A%3A…``），而 zip 条目名是原始字符（``*_ *:_|…``），
    直接用解析路径查 entries 会 KeyError；此处先精确匹配，
    再回退到解码名，均未命中则原样返回（保持旧行为）。
    """
    if path in entries:
        return path
    try:
        decoded = unquote(path)
    except Exception:
        return path
    if decoded in entries:
        return decoded
    return path


def _quote_href(path: str) -> str:
    """把 zip 内路径转为可写入 XHTML href 的百分号编码形式（保留 / 与锚点）。"""
    if '#' in path:
        body, anchor = path.split('#', 1)
        return quote(body, safe='/') + '#' + anchor
    return quote(path, safe='/')


def _snap_with_anchor(entries: dict, ref: str) -> str:
    """_snap_entry 的带锚点版本：仅对路径主体对齐，锚点原样保留。"""
    if '#' in ref:
        body, anchor = ref.split('#', 1)
        return _snap_entry(entries, body) + '#' + anchor
    return _snap_entry(entries, ref)


def _relative_href(from_zip_path: str, to_zip_path: str) -> str:
    """计算 zip 内两文件间的相对 URL（复用 curie 思路）。"""
    from_parts = from_zip_path.split('/')
    to_parts = to_zip_path.split('/')
    from_dirs = from_parts[:-1]
    to_dirs = to_parts[:-1]
    common = 0
    for a, b in zip(from_dirs, to_dirs):
        if a == b:
            common += 1
        else:
            break
    up = len(from_dirs) - common
    return '../' * up + '/'.join(to_parts[common:])


def _text_entries(ctx: OpfContext, entries: dict = None) -> list:
    """按 spine 顺序返回正文（xhtml/html）条目 zip 路径列表（linear=yes）。

    entries 提供时对解析路径做条目名对齐（兼容百分号编码 href 的书）。
    """
    out = []
    for idref, linear in ctx.spine:
        if not linear:
            continue
        item = ctx.manifest.get(idref)
        if not item:
            continue
        if item['mt'] not in ('application/xhtml+xml', 'text/html'):
            continue
        path = _resolve_zip(ctx.opf_dir, item['href'])
        if entries is not None:
            path = _snap_entry(entries, path)
        out.append(path)
    return out


def _is_front_file(zip_path: str) -> bool:
    """文件名是否疑似前置页（封面/版权/目录等）。"""
    base = zip_path.rsplit('/', 1)[-1]
    return bool(_FRONT_FILE_RE.search(base))


# ── NCX / nav 解析 ────────────────────────────────────────────────────────────

def _parse_ncx(data: bytes) -> list:
    """解析 NCX 为 [(level, title, src)] 扁平列表（navPoint 嵌套 = 层级）。"""
    items = []
    try:
        root = ET.fromstring(_decode(data))
    except ET.ParseError as e:
        logging.warning("[epub_beautify] NCX parse failed: %s", e)
        return []

    def walk(elem, level):
        for nav_point in elem:
            if nav_point.tag != _q('navPoint', _NS_DTBNCX):
                continue
            label = nav_point.find(_q('navLabel', _NS_DTBNCX))
            title = ''
            if label is not None:
                t = label.find(_q('text', _NS_DTBNCX))
                title = (t.text or '').strip() if t is not None else ''
            content = nav_point.find(_q('content', _NS_DTBNCX))
            src = content.get('src', '') if content is not None else ''
            items.append((level, title, src))
            walk(nav_point, level + 1)

    nav_map = root.find(_q('navMap', _NS_DTBNCX))
    if nav_map is not None:
        walk(nav_map, 0)
    return items


def _parse_nav_doc(data: bytes) -> list:
    """解析 EPUB3 nav 文档（epub:type=toc 的 nav）为 [(level, title, href)]。"""
    items = []
    try:
        root = ET.fromstring(_decode(data))
    except ET.ParseError as e:
        logging.warning("[epub_beautify] nav parse failed: %s", e)
        return []
    nav = None
    for n in root.iter(_q('nav', _NS_XHTML)):
        ntype = n.get('{%s}type' % 'http://www.idpf.org/2007/ops') or ''
        if 'toc' in ntype:
            nav = n
            break
    if nav is None:
        return items

    def walk(ul, level):
        for li in list(ul):
            if li.tag != _q('li', _NS_XHTML):
                continue
            a = li.find(_q('a', _NS_XHTML))
            title = ''
            href = ''
            if a is not None:
                title = ''.join(a.itertext()).strip()
                href = a.get('href', '')
            items.append((level, title, href))
            child = li.find(_q('ol', _NS_XHTML))
            if child is None:
                child = li.find(_q('ul', _NS_XHTML))
            if child is not None:
                walk(child, level + 1)

    # Element 真值判断已弃用（空 <ol/> 为假会误回落到 ul），必须用 is not None
    first_ul = nav.find(_q('ol', _NS_XHTML))
    if first_ul is None:
        first_ul = nav.find(_q('ul', _NS_XHTML))
    if first_ul is not None:
        walk(first_ul, 0)
    return items


# ── 目录数据净化（cleanup.toc_blank）──────────────────────────────────
# 只删零信息的空条目：label 全空且无存活后代的 navPoint / 空 <li>；
# 不动任何有文字的条目，playOrder 顺序重排。

def _prune_ncx_bytes(data: bytes) -> tuple:
    """剔除 NCX 中空标签 navPoint（子级优先递归）。:return: (new_bytes, pruned)"""
    try:
        root = ET.fromstring(_decode(data))
    except ET.ParseError:
        return data, 0
    nav_map = root.find(_q('navMap', _NS_DTBNCX))
    if nav_map is None:
        return data, 0

    pruned = 0

    def _label(np):
        lab = np.find(_q('navLabel', _NS_DTBNCX))
        if lab is None:
            return ''
        t = lab.find(_q('text', _NS_DTBNCX))
        return (t.text or '').strip() if t is not None else ''

    def _clean(elem):
        nonlocal pruned
        for np in list(elem):
            if np.tag != _q('navPoint', _NS_DTBNCX):
                continue
            _clean(np)
            children = [c for c in np if c.tag == _q('navPoint', _NS_DTBNCX)]
            if not _label(np) and not children:
                elem.remove(np)
                pruned += 1

    _clean(nav_map)
    if not pruned:
        return data, 0
    order = 0
    for np in root.iter(_q('navPoint', _NS_DTBNCX)):
        order += 1
        np.set('playOrder', str(order))
    ET.register_namespace('', _NS_DTBNCX)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True), pruned


def _prune_nav_bytes(data: bytes) -> tuple:
    """剔除 EPUB3 nav 文档 toc 列表中的空 <li>。:return: (new_bytes, pruned)"""
    try:
        root = ET.fromstring(_decode(data))
    except ET.ParseError:
        return data, 0
    pruned = 0

    def _li_text(li):
        # 兼容包裹型：<li><span><a> 等深层嵌套
        a = li.find('.//' + _q('a', _NS_XHTML))
        return ''.join(a.itertext()).strip() if a is not None else ''

    def _clean_ol(ol):
        nonlocal pruned
        for li in list(ol):
            if li.tag != _q('li', _NS_XHTML):
                continue
            subs = [c for c in li if c.tag in (_q('ol', _NS_XHTML), _q('ul', _NS_XHTML))]
            for s in subs:
                _clean_ol(s)
            has_live_sub = any(
                len(c) for c in li
                if c.tag in (_q('ol', _NS_XHTML), _q('ul', _NS_XHTML))
            )
            if not _li_text(li) and not has_live_sub:
                ol.remove(li)
                pruned += 1

    for n in root.iter(_q('nav', _NS_XHTML)):
        ntype = n.get('{http://www.idpf.org/2007/ops}type') or ''
        if 'toc' not in ntype:
            continue
        top = n.find(_q('ol', _NS_XHTML))
        if top is None:
            top = n.find(_q('ul', _NS_XHTML))
        if top is not None:
            _clean_ol(top)
    if not pruned:
        return data, 0
    ET.register_namespace('', _NS_XHTML)
    ET.register_namespace('epub', 'http://www.idpf.org/2007/ops')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True), pruned


# ── 目录页生成 ────────────────────────────────────────────────────────────────

# 标题已自带中文序号（第X章）或数字前缀（01.）时不再注入编号
_NUM_PREFIX_RE = re.compile(
    r'^(?:第\s*[0-9零〇一二三四五六七八九十百千万兩两]+\s*[章节回篇卷部集]|\d{1,4}\s*[.、．]?)',
)


def _build_toc_page(toc_items: list, ref_dir: str, truncated: bool = False,
                    toc_style: str = 'elegant') -> bytes:
    """生成 mb-toc.xhtml。toc_items = [(level, title, zip_href)]。

    zip_href 为条目目标文件在 zip 内的路径（可含 #锚点）。
    ref_dir 为 toc 页所在目录（opf_dir），条目 href 相对它计算。
    toc_style: elegant/cool/minimal 用 ol/li 结构；seal（朱印风）用双栏表格。

    注意：使用**普通 div 结构而非 <nav epub:type="toc">**——nav 文档会被
    手机阅读器（多看/KOReader/微信读书等）当作目录数据源特殊处理（跳过
    渲染或不应用书内 CSS），普通 div 目录页在所有阅读器都当普通页面渲染。
    装饰元素（副题/印章/收尾符）用真实元素生成，不依赖 ::before/::after 伪元素。
    """
    num = 0
    entries = []
    for level, title, zip_href in toc_items:
        if not title:
            continue
        if '#' in zip_href:
            zip_path, anchor = zip_href.split('#', 1)
            anchor = '#' + anchor
        else:
            zip_path, anchor = zip_href, ''
        # 锚点来自书内 NCX/nav，属性上下文需转义（防引号破坏 href 结构）
        rel = _quote_href(_relative_href(ref_dir + MB_TOC_NAME, zip_path)) + _esc(anchor)
        lv = 'lv1' if level <= 1 else 'lv2'
        num_span = ''
        if lv == 'lv1':
            num += 1
            if not _NUM_PREFIX_RE.match(title):
                num_span = '<span class="mb-toc-num">%02d</span>' % num
        if toc_style == 'seal':
            # 朱印式：双栏表格行（编号在链接内，右列装饰标记）
            td_cls = ' class="mb-toc-l2"' if lv == 'lv2' else ''
            entries.append(
                '<tr><td%s><a href="%s">%s %s</a></td>'
                '<td class="mb-toc-mark">　✦</td></tr>'
                % (td_cls, rel, num_span, _esc(title))
            )
        else:
            entries.append(
                '<li class="%s">%s<a href="%s">%s</a></li>'
                % (lv, num_span, rel, _esc(title))
            )
    trunc = ('<p class="mb-toc-truncated">……（目录过长，仅显示前 %d 条）</p>' % len(toc_items)) if truncated else ''

    if toc_style == 'seal':
        head = (
            '<h1>目 录<span class="mb-toc-seal">隐</span>'
            '<span class="mb-toc-sub">CONTENT</span></h1>'
        )
        body_rows = '<table class="mulu"><tbody>\n%s\n</tbody></table>' % '\n'.join(entries)
    else:
        head = '<h1>目　录<span class="mb-toc-sub">C O N T E N T S</span></h1>'
        body_rows = '<ol>%s</ol>' % '\n'.join(entries)

    xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        '<head><title>目录</title>'
        '<link rel="stylesheet" type="text/css" href="%s"/></head>\n'
        '<body class="mb-toc-page" id="mb-toc">\n'
        '<div class="mb-toc">\n'
        '%s\n'
        '%s\n'
        '%s\n'
        '<p class="mb-toc-end">◆</p>\n'
        '</div>\n'
        '</body>\n'
        '</html>'
    ) % (MB_CSS_NAME, head, body_rows, trunc)
    return xhtml.encode('utf-8')


def _esc(text: str) -> str:
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


# ── 章节标题标记 ──────────────────────────────────────────────────────────────

def _block_text(inner_html: str) -> str:
    """块内纯文本（剥内联标签 + 压空白）。"""
    text = _INLINE_RE.sub('', inner_html)
    text = text.replace('&nbsp;', ' ').replace('&#160;', ' ')
    return ' '.join(text.split())


def _looks_like_title(text: str) -> bool:
    """块文本是否像标题（配合类名关键词时用更宽松的长度）。"""
    if not text or len(text) > 80:
        return False
    if text.endswith(('。', '！', '？', '；', '.', '!', '?', ';')):
        return False
    return True


def _add_class(attrs: str, cls: str) -> str:
    """给开标签属性串追加 class（已含 class 则合并，兼容单/双引号）。"""
    m = re.search(r'''\bclass\s*=\s*(?:"([^"]*)"|'([^']*)')''', attrs)
    if m:
        # 兼容双引号与单引号两种写法
        existing = m.group(1) if m.group(1) is not None else m.group(2)
        if cls in existing.split():
            return attrs
        # 统一回写为双引号，避免重复 class 属性
        new_val = (existing + ' ' + cls).strip()
        # 替换整个 class=... 为双引号形式
        return attrs[:m.start()] + ' class="%s"' % new_val + attrs[m.end():]
    return attrs + ' class="%s"' % cls


def _inject_css_link(html_str: str, rel_href: str) -> str:
    """在 <head> 末尾注入 mb-beauty.css 引用（幂等）。"""
    if 'mb-beauty.css' in html_str:
        return html_str
    link = '<link rel="stylesheet" type="text/css" href="%s"/>' % rel_href
    m = re.search(r'</head>', html_str, re.IGNORECASE)
    if m:
        return html_str[:m.start()] + link + html_str[m.start():]
    # 无 head：在 <body> 前补一个
    m = re.search(r'<body\b', html_str, re.IGNORECASE)
    if m:
        return html_str[:m.start()] + '<head>' + link + '</head>' + html_str[m.start():]
    return html_str


# 目录页文件名特征（书内目录文档）
_TOC_FILE_RE = re.compile(r'(mulu|toc|contents|nav)', re.IGNORECASE)
# nav 语义目录页标记（内容含 <nav epub:type="toc">）
_NAV_TOC_RE = re.compile(r'<nav\b[^>]*epub:type\s*=\s*["\']toc', re.IGNORECASE)
# 目录文档标记（body 上打 mb-toc-page 供 CSS 精确作用）
_TOC_BODY_CLASS = 'mb-toc-page'


def _has_nav_toc_semantics(html_str: str) -> bool:
    """HTML 头部是否含 ``<nav epub:type="toc">`` 结构。"""
    return bool(_NAV_TOC_RE.search(html_str or ''))


def _looks_like_link_toc(html_str: str) -> bool:
    """链接列表型目录页检测：calibre「Table of Contents」等无 nav 语义的
    纯链接目录（<p><a>第x章</a></p> 列表）。≥3 个链接且多数行文本呈
    章节标题形态即判定。真章节页的链接是脚注/引用（文本非标题形态），
    占比远低于阈值，不会误判。"""
    anchors = re.findall(r'<a\b[^>]*href=[^>]*>(.*?)</a>', html_str, re.I | re.S)
    if len(anchors) < 3:
        return False
    texts = [t for t in (_block_text(a) for a in anchors) if t]
    if len(texts) < 3:
        return False
    like = sum(
        1 for t in texts
        if len(t) <= 60 and chapter_patterns.paragraph_is_heading(t)
    )
    return like >= 3 and like * 2 >= len(texts)


def _is_toc_doc(zip_path: str, html_str: str = '') -> bool:
    """判断条目是否为书内目录页：文件名（mulu/toc/nav/contents）、
    ``<nav epub:type="toc">`` 结构、或链接列表形态（P：纯链接目录页此前
    检测不到，会落入章节标记，mb-ch 的 page-break-before 把目录页炸成
    多个「第x章」独立页）。"""
    base = zip_path.rsplit('/', 1)[-1]
    if _TOC_FILE_RE.search(base):
        return True
    if html_str and _has_nav_toc_semantics(html_str):
        return True
    return bool(html_str) and _looks_like_link_toc(html_str)


# 误打在目录页上的章节标记清理（修复旧版缺陷输出，见 _is_toc_doc）
_MB_SEP_DIV_RE = re.compile(
    r'<div class="[^"]*mb-ch-sep[^"]*"[^>]*>\s*</div>\s*', re.IGNORECASE)
_CH_MARK_TOKENS = ('mb-ch', 'mb-vol', 'mb-ch-split')


def _strip_chapter_marks(html_str: str) -> str:
    """移除误打在目录页上的章节标记（mb-ch/mb-vol/mb-ch-split 类 + 长线 div）。

    正常流程不给目录页打标，页面上的标记只能来自旧版检测缺陷，剥离即修复。
    幂等：无标记时原样返回。"""
    out = _MB_SEP_DIV_RE.sub('', html_str)

    def _fix_class(m):
        tokens = [t for t in m.group(1).split() if t not in _CH_MARK_TOKENS]
        return ' class="%s"' % ' '.join(tokens)

    return re.sub(r'class="([^"]*)"', _fix_class, out)


def _mark_toc_page_body(html_str: str) -> str:
    """给目录页 <body> 打 mb-toc-page 类（幂等）。"""
    if _TOC_BODY_CLASS in html_str:
        return html_str
    m = re.search(r'<body\b([^>]*)>', html_str, re.IGNORECASE)
    if not m:
        return html_str
    new_attrs = _add_class(m.group(1), _TOC_BODY_CLASS)
    return html_str[:m.start()] + '<body%s>' % new_attrs + html_str[m.end():]


def _decorate_toc_page(html_str: str) -> str:
    """给书内普通目录页注入真实装饰元素（幂等）：标题英文副题 + 收尾 ◆。

    使用真实元素而非 ::before/::after content（移动阅读器兼容性差）。
    """
    if 'mb-toc-sub' in html_str and 'mb-toc-end' in html_str:
        return html_str
    # 标题内注入英文副题 span（朱印式双行标题）
    m = re.search(r'(<h[12]\b[^>]*>)(.*?)(</h[12]>)', html_str, re.S | re.IGNORECASE)
    if m and 'mb-toc-sub' not in m.group(2):
        sub = '<span class="mb-toc-sub">C O N T E N T S</span>'
        html_str = html_str[:m.end(2)] + sub + html_str[m.start(3):]
    # body 末尾注入收尾装饰符
    if 'mb-toc-end' not in html_str:
        m2 = re.search(r'</body>', html_str, re.IGNORECASE)
        if m2:
            html_str = html_str[:m2.start()] + '<p class="mb-toc-end">◆</p>' + html_str[m2.start():]
    return html_str


_MB_SEP = '<div class="mb-ch-sep"></div>'

# 章节号前缀拆分（双行排版）：第X章节回篇卷部集季 / Chapter N
_CH_PREFIX_RE = re.compile(
    r'^\s*(?P<num>第\s*[0-9零〇一二三四五六七八九十百千万兩两]+\s*[章节回篇卷部集季]'
    r'|(?:chapter|chap\.?)\s*\d+)'
    r'[\s、．.:：\-—·]*(?P<rest>.+)$',
    re.IGNORECASE,
)


def _split_chapter_title(text: str):
    """把「第三章 血尸」拆为 ('第三章', '血尸')；无剩余标题时返回 None。

    前缀压缩内部空白；仅用于双行排版（split_title），卷级标题不拆。
    """
    m = _CH_PREFIX_RE.match((text or '').strip())
    if not m:
        return None
    rest = m.group('rest').strip()
    if not rest:
        return None
    return re.sub(r'\s+', '', m.group('num')), rest


# 卷级标题（样式分级用）：仅 卷/部/篇 算卷级；「回」在章回体中是章节单元，
# 不沿用 chapter_patterns 的分组语义（那里 回 与 部篇 同级用于分组）
_MB_VOL_RE = re.compile(
    r'^\s*(?:[【\[]\s*)?(?:'
    r'第\s*[0-9零〇一二三四五六七八九十百千万兩两]+\s*[卷部篇]'
    r'|0*\d{1,4}\s*卷'
    r'|卷\s*[0-9零〇一二三四五六七八九十百千万兩两]+'
    r'|[上中下]\s*卷)'
)


def _is_volume_text(text: str) -> bool:
    return bool(_MB_VOL_RE.match((text or '').strip()))


def mark_chapters_in_html(html_str: str, split_title: bool = False) -> tuple:
    """正文条目内标记章节标题（mb-ch / 卷级 mb-vol）与章首段（data-mb-first）。

    幂等：已含 mb-ch 的条目直接返回原样。
    :param split_title: True 时把纯文本章题拆为 mb-ch-num + mb-ch-title 两行
        span（双行排版，仅章级；块内含子标签则跳过不动）。拆分时标题元素追加
        mb-ch-split 类，供预设关闭章扉式大顶距（双 span 已增高，见 xuanzhi.css）。
    :return: (new_html, stats)，stats = {'chapters','volumes','splits'}
    """
    empty = {'chapters': 0, 'volumes': 0, 'splits': 0}
    if (re.search(r'class="[^"]*\bmb-ch\b', html_str) or re.search(r'class="[^"]*\bmb-vol\b', html_str)) or ('<html' not in html_str.lower() and '<body' not in html_str.lower()):
        return html_str, dict(empty)
    if _FRONT_TYPE_RE.search(html_str[:4000]):
        return html_str, dict(empty)

    stats = dict(empty)
    first_done = False
    heading_seen = False
    # 性能护栏：开闭不齐的大文件跳过块级正则（避免 _BLOCK_RE O(n²) 退化）
    if len(html_str) > 80000:
        # 粗略统计 p 标签开闭数，不匹配且文件较大则跳过标记（与 analyze 的 p_close_mismatch 思路一致）
        try:
            _open = len(re.findall(r'<p\b', html_str, re.IGNORECASE))
            _close = len(re.findall(r'</p>', html_str, re.IGNORECASE))
            if _open != _close and max(_open, _close) > 50:
                return html_str, dict(empty)
        except Exception:
            pass

    def _handle_block(tag, attrs, inner, is_div=False):
        nonlocal stats, heading_seen, first_done
        # 弹注条目豁免（mb-note-item 由 mark_notes_in_html 打标）：注释内容
        # 不是章节标题，且 ◎《…》/短条目可能撞上弱正则
        if 'mb-note-item' in (attrs or ''):
            return None
        # 同名标签嵌套（多级 li 大纲 / 嵌套引用）：正则的惰性匹配会把内层
        # 闭合标签吞进 outer match，重建后结构破坏——直接跳过不修改
        if re.search(r'<%s\b' % tag, inner or '', re.IGNORECASE):
            return None
        cls_attr = attrs or ''
        text = _block_text(inner)
        if not text.strip():
            return None
        is_heading = False
        if _TITLE_CLASS_RE.search(cls_attr) and _looks_like_title(text):
            is_heading = True
        elif chapter_patterns.paragraph_is_heading(text):
            is_heading = True
        if is_heading:
            # 卷级（第N卷/卷N/上中下卷/第N部篇）单独样式：独页大字、无长线；
            # 章回体「第X回」视为章节，不升级
            is_volume = _is_volume_text(text)
            new_attrs = _add_class(cls_attr, 'mb-vol' if is_volume else 'mb-ch')
            if is_volume:
                stats['volumes'] += 1
            else:
                stats['chapters'] += 1
            if split_title and not is_volume and '<' not in inner:
                parts = _split_chapter_title(text)
                if parts:
                    inner = (
                        '<span class="mb-ch-num">%s</span>'
                        '<span class="mb-ch-title">%s</span>'
                    ) % (_esc(parts[0]), _esc(parts[1]))
                    stats['splits'] += 1
                    # 拆分标记类：预设据此关闭章扉式大顶距（双 span 已增高）
                    new_attrs = _add_class(new_attrs, 'mb-ch-split')
            heading_seen = True
            return '<%s%s>%s</%s>%s' % (tag, new_attrs, inner, tag,
                                        '' if is_volume else _MB_SEP)
        if heading_seen and not first_done and not is_div:
            if 'data-mb-first' in (cls_attr or ''):
                return None
            new_attrs = cls_attr + ' data-mb-first="true"'
            first_done = True
            return '<%s%s>%s</%s>' % (tag, new_attrs, inner, tag)
        return None

    # 第一遍：替换 h/p/blockquote/li 块
    def _replace_block(m):
        tag, attrs, inner = m.group(1), m.group(2), m.group(3)
        out = _handle_block(tag, attrs, inner)
        return out if out is not None else m.group(0)

    new_html = _BLOCK_RE.sub(_replace_block, html_str)
    if not first_done:
        # 第二遍：无嵌套 div（Calibre 类汤）
        def _replace_div(m):
            attrs, inner = m.group(1), m.group(2)
            out = _handle_block('div', attrs, inner, is_div=True)
            return out if out is not None else m.group(0)

        new_html = _SIMPLE_DIV_RE.sub(_replace_div, new_html)
    return new_html, stats


# ── 对话行点缀（mb-dialog）────────────────────────────────────────────

# 开引号字符集：直角引号（「『）、中文弯双引、全角直引号、ASCII 双引号；
# ASCII 单引号不参与（英文撇号/内嵌引用误判率高）
_DIALOG_OPEN_QUOTES = ('「', '『', '“', '＂', '"')


def _is_dialogue_text(text: str) -> bool:
    """段落纯文本是否为对话行：容忍前导空白，以开引号起始。

    保守策略——仅识别开引号起始；``张三道："…"` ` 等叙述引导句式不标
    （避免把整段叙述一起染色）。
    """
    t = (text or '').lstrip(' \u3000')
    return bool(t) and t.startswith(_DIALOG_OPEN_QUOTES)


def mark_dialogue_in_html(html_str: str) -> tuple:
    """为以开引号起始的普通段落打 ``mb-dialog`` 类（幂等，配合开关使用）。

    只处理 ``<p>``（li/blockquote 不动）；标题块（mb-ch）跳过；同名标签
    嵌套整块跳过。:return: (new_html, marked_count)
    """
    if 'mb-dialog' in html_str or '<html' not in html_str.lower():
        return html_str, 0
    marked = 0

    def _replace_p(m):
        nonlocal marked
        tag, attrs, inner = m.group(1), m.group(2), m.group(3)
        if tag.lower() != 'p' or 'mb-ch' in (attrs or ''):
            return m.group(0)
        if re.search(r'<%s\b' % tag, inner or '', re.IGNORECASE):
            return m.group(0)
        if not _is_dialogue_text(_block_text(inner)):
            return m.group(0)
        marked += 1
        return '<%s%s>%s</%s>' % (tag, _add_class(attrs or '', 'mb-dialog'), inner, tag)

    return _BLOCK_RE.sub(_replace_p, html_str), marked


# ── 弹注/标注（mb-notemark / mb-notes）───────────────────────────────────────

# 文内标注符：<a class="duokan-footnote" ...>…</a>（A 型带 epub:type/id，B 型仅 class+href）
_NOTE_REF_RE = re.compile(
    r'<a\b([^>]*?class\s*=\s*["\'][^"\']*duokan-footnote[^"\']*["\'][^>]*?)>(.*?)</a>',
    re.I | re.S,
)
# 注释容器：aside[epub:type~=footnote]（A 型）或裸 ol.duokan-footnote-content（B 型）
_FOOTNOTE_ASIDE_RE = re.compile(r'<aside\b[^>]*epub:type\s*=\s*["\'][^"\']*footnote', re.I)
_NOTES_OL_BLOCK_RE = re.compile(
    r'<ol\b[^>]*duokan-footnote-content[^>]*>.*?</ol>', re.I | re.S)
_NOTE_ITEM_CNT_RE = re.compile(r'class\s*=\s*["\'][^"\']*duokan-footnote-item', re.I)

# 自绘 SVG 标注模板（viewBox 24×24，fill=currentColor 随预设主题染色；
# 全部为本插件原创 path，可随插件分发）
NOTE_MARK_SVGS = {
    'dot': (
        '<circle cx="12" cy="12" r="7" fill="none" stroke="currentColor" stroke-width="2"/>'
        '<circle cx="12" cy="12" r="2.6"/>'
    ),
    'fold': (
        '<path d="M6 3h9l4 4v14H6z" fill="none" stroke="currentColor" stroke-width="2"/>'
        '<path d="M15 3v4h4" fill="none" stroke="currentColor" stroke-width="2"/>'
        '<circle cx="12" cy="14.5" r="2"/>'
    ),
    'inkdrop': (
        '<path d="M12 3.5c3.2 4.4 6 7.6 6 11a6 6 0 1 1-12 0c0-3.4 2.8-6.6 6-11z"/>'
    ),
    'spark': (
        '<path d="M12 2l2.2 7.8L22 12l-7.8 2.2L12 22l-2.2-7.8L2 12l7.8-2.2z"/>'
    ),
    'sealdot': (
        '<rect x="5" y="5" width="14" height="14" rx="2" fill="none" '
        'stroke="currentColor" stroke-width="2"/>'
        '<rect x="10.4" y="10.4" width="3.2" height="3.2" rx="0.6"/>'
    ),
}

NOTE_MARK_MODES = ('orig', 'sym', 'num')


def _validate_note_mark(note_mark: str) -> None:
    """校验标注样式 id：orig/sym/num 或 svg:<模板id>；非法抛 ValueError。"""
    if note_mark in NOTE_MARK_MODES:
        return
    if isinstance(note_mark, str) and note_mark.startswith('svg:'):
        if note_mark[4:] in NOTE_MARK_SVGS:
            return
        raise ValueError('unknown svg note mark: %s' % note_mark)
    raise ValueError('unknown note_mark: %r' % (note_mark,))


def _make_mark_inner(note_mark: str, seq: int) -> str:
    """按样式生成标注符内部元素（替换原 <img>；外层 <a> 与属性不动）。"""
    if note_mark == 'sym':
        return '<sup class="mb-marktxt">※</sup>'
    if note_mark == 'num':
        return '<sup class="mb-marktxt">[%d]</sup>' % seq
    if note_mark.startswith('svg:'):
        return ('<svg class="mb-marksvg" viewBox="0 0 24 24" aria-hidden="true">%s</svg>'
                % NOTE_MARK_SVGS[note_mark[4:]])
    raise ValueError('note_mark %r does not replace inner element' % (note_mark,))


def _add_epub_type_noteref(attrs: str) -> str:
    """为缺语义的标注 <a> 补 epub:type="noteref"（已有则原样）。"""
    if re.search(r'epub:type\s*=', attrs or '', re.I):
        return attrs
    return attrs.rstrip() + ' epub:type="noteref"'


def mark_notes_in_html(html_str: str, normalize: bool = True,
                       note_mark: str = 'orig') -> tuple:
    """美化书内多看系弹注：标注符与注释容器打标，可选语义归一化/换标记元素。

    - 所有 `a.duokan-footnote` 追加 ``mb-notemark`` 类与 ``data-mb-mark``；
      note_mark != 'orig' 时把内部 `<img>` 替换为文本/SVG 标记（序号按文件内顺序）；
      normalize 时为缺 `epub:type` 的 ref 补 `noteref`；
    - 容器：已有 `aside[epub:type~=footnote]` 打 ``mb-notes`` 类；
      裸 `ol.duokan-footnote-content` 且无 aside 时包进
      `<aside epub:type="footnote" class="mb-notes">`（提升 EPUB3 引擎弹出兼容）；
    - 条目 li 追加 ``mb-note-item`` 豁免类——章末注释不会被章节标题扫描误标。

    安全红线：只增不改不删（除用户显式选择的 img 替换），href/id/class 原样保留。
    幂等：已含 mb-notemark 的文件直接原样返回。
    :return: (new_html, stats)；stats = {refs, items, normalized, wrapped}
    """
    _validate_note_mark(note_mark)
    empty = {'refs': 0, 'items': 0, 'normalized': 0, 'wrapped': 0}
    if 'mb-notemark' in html_str or 'mb-notes' in html_str:
        return html_str, dict(empty)
    refs_found = _NOTE_REF_RE.findall(html_str)
    items_found = _NOTE_ITEM_CNT_RE.findall(html_str)
    if not refs_found and not items_found:
        return html_str, dict(empty)

    stats = {'refs': len(refs_found), 'items': len(items_found),
             'normalized': 0, 'wrapped': 0}
    seq = {'n': 0}

    def _ref_repl(m):
        attrs, inner = m.group(1), m.group(2)
        seq['n'] += 1
        new_attrs = _add_class(attrs, 'mb-notemark')
        new_attrs += ' data-mb-mark="%s"' % note_mark
        if normalize and not re.search(r'epub:type\s*=', new_attrs, re.I):
            new_attrs = _add_epub_type_noteref(new_attrs)
            stats['normalized'] += 1
        if note_mark != 'orig':
            inner = _make_mark_inner(note_mark, seq['n'])
        return '<a%s>%s</a>' % (new_attrs, inner)

    html_str = _NOTE_REF_RE.sub(_ref_repl, html_str)

    # 条目豁免类（防章节标题扫描误标）
    def _item_repl(m):
        return m.group(0).replace('duokan-footnote-item', 'duokan-footnote-item mb-note-item', 1)
    html_str = re.sub(
        r'<li\b[^>]*class\s*=\s*["\'][^"\']*duokan-footnote-item[^"\']*["\'][^>]*>',
        _item_repl, html_str, flags=re.I)

    has_aside = bool(_FOOTNOTE_ASIDE_RE.search(html_str))
    if has_aside:
        # A 型：给 footnote aside 追加容器类
        def _aside_repl(m):
            tag = m.group(0)
            cls_m = re.search(r'\bclass\s*=\s*"([^"]*)"', tag)
            if cls_m:
                if 'mb-notes' in cls_m.group(1):
                    return tag
                return tag.replace(cls_m.group(0),
                                   'class="%s mb-notes"' % cls_m.group(1), 1)
            return tag[:-1] + ' class="mb-notes">'
        html_str = re.sub(r'<aside\b[^>]*epub:type\s*=\s*["\'][^"\']*footnote[^>]*>',
                          _aside_repl, html_str, flags=re.I)
    elif normalize:
        # B 型归一化：裸 ol 包进 aside（EPUB3 引擎弹出信号）
        def _wrap_repl(m):
            stats['wrapped'] += 1
            return '<aside epub:type="footnote" class="mb-notes">\n%s\n</aside>' % m.group(0)
        html_str = _NOTES_OL_BLOCK_RE.sub(_wrap_repl, html_str)
    else:
        # 不归一化也要让 CSS 命中裸 ol：追加容器类
        def _ol_cls_repl(m):
            block = m.group(0)
            tag_end = block.index('>') + 1
            return _add_class(block[:tag_end], 'mb-notes') + block[tag_end:]
        html_str = _NOTES_OL_BLOCK_RE.sub(_ol_cls_repl, html_str)

    return html_str, stats


# ── 分析（preview 用）─────────────────────────────────────────────────────────

def _sample_preview_chapter(html_str: str) -> dict:
    """从单个正文文件提取首章真实预览：首个标题块 + 至多 3 段后续正文。

    标题判定与 mark_chapters_in_html 同源（h1-h6 标签或段落文本章节正则）；
    遇到下一个标题块即停止收录；输出纯文本（剥内联标签、压空白、截断）。
    增强：兼顾纯 div 平铺文件（Calibre 类汤）、标题后无段落的短章。
    """
    blocks = list(_BLOCK_RE.finditer(html_str))
    # 纯 div 文件兜底：若未命中块，尝试 div 采样
    if not blocks:
        divs = list(_SIMPLE_DIV_RE.finditer(html_str))
        for i, m in enumerate(divs):
            text = _block_text(m.group(2))
            if not text:
                continue
            if chapter_patterns.paragraph_is_heading(text):
                title = text[:80]
                paras = []
                for dm in divs[i + 1:]:
                    pt = _block_text(dm.group(2))
                    if not pt:
                        continue
                    if chapter_patterns.paragraph_is_heading(pt):
                        break
                    paras.append(pt[:120])
                    if len(paras) >= 3:
                        break
                # 短章允许仅标题
                return {'title': title, 'paragraphs': paras}
        return None
    start = -1
    for i, m in enumerate(blocks):
        tag = m.group(1).lower()
        text = _block_text(m.group(3))
        if not text:
            continue
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6') or \
                chapter_patterns.paragraph_is_heading(text):
            start = i
            break
    if start < 0:
        return None
    title = _block_text(blocks[start].group(3))[:80]
    paras = []
    for m in blocks[start + 1:]:
        tag = m.group(1).lower()
        text = _block_text(m.group(3))
        if not text:
            continue
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6') or \
                chapter_patterns.paragraph_is_heading(text):
            break
        paras.append(text[:120])
        if len(paras) >= 3:
            break
    # 短章允许仅标题，前端 MOCKS 会补段落
    return {'title': title, 'paragraphs': paras}


def analyze_epub(epub_path: str, sample_limit: int = 20) -> dict:
    """扫描 EPUB，返回美化方案分析（不写文件）。

    :param sample_limit: 标题统计与 p 开闭预警的采样正文文件数上限（防超大书卡死）。
    """
    entries = _read_zip_entries(epub_path)
    ctx = _parse_opf(entries)
    text_entries = _text_entries(ctx, entries)
    css_names = [n for n in entries if n.lower().endswith('.css')]
    has_fontface = False
    calibre_soup = False
    css_important_count = 0
    for n in css_names:
        css = _decode(entries[n])
        if '@font-face' in css:
            has_fontface = True
        css_important_count += css.count('!important')
    for n in css_names:
        if '.calibre' in _decode(entries[n]):
            calibre_soup = True
            break

    ncx_count = 0
    if ctx.ncx_path and ctx.ncx_path in entries:
        ncx_count = len(_parse_ncx(entries[ctx.ncx_path]))
    nav_count = 0
    if ctx.nav_path and ctx.nav_path in entries:
        nav_count = len(_parse_nav_doc(entries[ctx.nav_path]))

    # 与 beautify 同源判定（_is_toc_doc）：文件名或 nav 结构均为目录页；
    # nav 语义页运行时会被替换为普通结构目录页，不计为「书内已有」
    has_inbook_toc = False
    for t in text_entries:
        if t not in entries:
            continue
        # 切片后解码（P1）：先解全量再截 4000 字，大文件白白多解码数 MB
        head = _decode(entries[t][:8192])[:4000]
        if _is_toc_doc(t, head) and not _has_nav_toc_semantics(head):
            has_inbook_toc = True
            break

    h_stats = {'h1': 0, 'h2': 0, 'h3': 0, 'h4': 0, 'h5': 0, 'h6': 0}
    text_headings = 0
    sampled = 0
    # 首章真实内容（前端预览用）：{title, paragraphs:[≤3]}
    preview_chapter = None
    # 健康报告采样：段首空格占比 / 空段估计 / p 开闭不齐文件数 / 对话行估计
    leading_space_paras = 0
    total_paras = 0
    empty_para_est = 0
    dialogue_paras = 0
    # p 开闭不齐（烂书预警）：限采样计数（P1：全量两次正则扫描大书会卡死 IOLoop，
    # 与标题统计共用 sample_limit 上限，统计语义为「采样内不齐文件数」）
    p_close_mismatch_files = sum(
        1 for t in text_entries[:sample_limit]
        if t in entries
        and len(re.findall(rb'<p\b', entries[t], re.IGNORECASE))
        != len(re.findall(rb'</p>', entries[t], re.IGNORECASE))
    )
    for t in text_entries:
        if t not in entries:
            continue
        if _is_front_file(t):
            continue
        if sampled >= sample_limit:
            break
        sampled += 1
        html = _decode(entries[t])
        empty_para_est += len(_EMPTY_P_RE.findall(html))
        # 首章真实预览：取第一个可提取的正文文件（跳过目录页）
        if preview_chapter is None and not _is_toc_doc(t, html[:2000]):
            preview_chapter = _sample_preview_chapter(html)
        for tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            h_stats[tag] += len(re.findall(r'<%s\b' % tag, html, re.IGNORECASE))
        for m in _BLOCK_RE.finditer(html):
            inner = m.group(3)
            total_paras += 1
            if m.group(1).lower() == 'p' and (
                re.match(r'^[\s\u3000]*(?:&nbsp;|&#160;)+', inner, re.IGNORECASE)
                or re.match(r'^[\s\u3000]{2,}', inner)
            ):
                leading_space_paras += 1
            if m.group(1).lower() == 'p' and _is_dialogue_text(_block_text(inner)):
                dialogue_paras += 1
            if chapter_patterns.paragraph_is_heading(_block_text(inner)):
                text_headings += 1

    # 弹注统计（全量正文文件，健康报告与推荐徽章用）
    notes_refs = 0
    notes_items = 0
    for t in text_entries:
        if t not in entries:
            continue
        h = _decode(entries[t])
        notes_refs += len(_NOTE_REF_RE.findall(h))
        notes_items += len(_NOTE_ITEM_CNT_RE.findall(h))

    # 目录预览：应用排除规则后的前若干条标题（与生成逻辑同源）
    toc_preview_titles = []
    raw_toc = []
    if ctx.ncx_path and ctx.ncx_path in entries:
        raw_toc = [(lv, title, src) for lv, title, src in _parse_ncx(entries[ctx.ncx_path])]
    if not raw_toc and ctx.nav_path and ctx.nav_path in entries:
        raw_toc = [(lv, title, href) for lv, title, href in _parse_nav_doc(entries[ctx.nav_path])]
    for lv, title, _src in raw_toc:
        if title and _toc_entry_allowed(title):
            toc_preview_titles.append(title)
        if len(toc_preview_titles) >= 12:
            break

    # 图片体检：数量 + 超大图计数（只报不改）
    img_exts = ('.jpg', '.jpeg', '.png', '.gif', '.webp')
    image_count = sum(1 for k in entries if k.lower().endswith(img_exts))
    image_oversize = sum(
        1 for k, v in entries.items()
        if k.lower().endswith(img_exts) and len(v) > 2 * 1024 * 1024
    )

    return {
        'title': ctx.title,
        'text_entries': len(text_entries),
        'css_files': css_names,
        'has_fontface': has_fontface,
        'calibre_soup': calibre_soup,
        'has_inbook_toc': has_inbook_toc,
        'ncx_entries': ncx_count,
        'nav_entries': nav_count,
        'heading_stats': h_stats,
        'text_headings': text_headings,
        'preview_chapter': preview_chapter,
        'notes_refs': notes_refs,
        'notes_items': notes_items,
        # ── 健康报告 ──
        'leading_space_paras': leading_space_paras,
        'sampled_paras': total_paras,
        'empty_para_est': empty_para_est,
        'dialogue_paras': dialogue_paras,
        'p_close_mismatch_files': p_close_mismatch_files,
        'css_important_count': css_important_count,
        'css_conflict_risk': css_important_count > 30,
        'image_count': image_count,
        'image_oversize': image_oversize,
        'toc_preview_titles': toc_preview_titles,
    }


# ── 主流程 ────────────────────────────────────────────────────────────────────

def _set_page_progression(opf_str: str, direction: str) -> str:
    """幂等设置 spine 的 page-progression-direction（竖排书右翻的标准信号）。

    已有该属性则更新其值，没有则追加；找不到 spine 标签时原样返回。
    """
    m = re.search(r'<spine\b[^>]*>', opf_str)
    if not m:
        return opf_str
    tag = m.group(0)
    if re.search(r'page-progression-direction\s*=', tag):
        new_tag = re.sub(
            r'page-progression-direction\s*=\s*(["\'])[^"\']*\1',
            'page-progression-direction="%s"' % direction,
            tag, count=1,
        )
    else:
        # 插到闭合符前（兼容 <spine> 与 <spine toc="ncx"> 及自闭合 <spine/>）
        if tag.rstrip().endswith('/>'):
            new_tag = tag.rstrip()[:-2].rstrip() + ' page-progression-direction="%s"/>' % direction
        else:
            new_tag = tag[:-1].rstrip() + ' page-progression-direction="%s">' % direction
    if new_tag == tag:
        return opf_str
    return opf_str[:m.start()] + new_tag + opf_str[m.end():]


def beautify(
    epub_path: str,
    out_path: str,
    preset_css: str,
    max_toc_entries: int = None,
    toc_style: str = 'elegant',
    page_progression: str = None,
    toc_depth: int = None,
    cleanup: dict = None,
    dialogue: bool = False,
    split_title: bool = False,
    extra_assets: dict = None,
    notes: bool = False,
    note_mark: str = 'orig',
) -> dict:
    """执行美化并写新 EPUB。

    :param preset_css: 已插值的 mb-beauty.css 内容（styles.get_preset_css）。
    :param page_progression: 'rtl' 时把 spine 设为从左向右翻页（竖排预设用），
        None 保持原书设置。
    :param max_toc_entries: 目录条目上限；**None = 不截断（默认）**，
        显式传数字时超出部分丢弃并附截断提示。深度/噪音过滤先于截断执行。
    :param toc_depth: 目录收录层级上限（None=全部；1/2/3=只收 level < N 的条目）。
    :param cleanup: 内容清理开关 {"leading":bool,"empty":bool,"meta":bool}，
        见 _normalize_cleanup；None 用默认（段首空格开/空段关/meta 开）。
    :param dialogue: 对话行点缀开关（True=为「『“起始段落打 mb-dialog，
        样式由 mb-beauty.css 的 .mb-dialog 规则提供）。
    :param split_title: 双行排版开关（True=纯文本章题拆为 mb-ch-num +
        mb-ch-title 两行 span，卷级不拆）。
    :param extra_assets: 附加资源 {zip内文件名: (bytes, media_type)}，
        如背景图片 {'mb-bg.jpg': (data, 'image/jpeg')}；写入包体并注册 manifest（幂等）。
    :param notes: 弹注/标注美化开关（标注符与注释容器打标 + B 型语义归一化）。
    :param note_mark: 标注样式 orig/sym/num/svg:<模板id>，见 mark_notes_in_html。
    :return: 统计 dict（marked_headers / marked_volumes / titles_split /
        toc_generated / toc_entries / injected_css / chapters / rtl /
        cleaned_leading / removed_empty / toc_excluded / toc_links_ok /
        toc_links_total / dialogues_marked / notes_refs / notes_items /
        notes_normalized / notes_wrapped）
    """
    if notes:
        _validate_note_mark(note_mark)
    cleanup_n = _normalize_cleanup(cleanup)
    entries = _read_zip_entries(epub_path)
    ctx = _parse_opf(entries)
    text_entries = _text_entries(ctx, entries)

    # ── 0. 目录数据净化：剔除 NCX/nav 空白条目（阅读器侧边栏空行元凶）──
    toc_blank_pruned = 0
    if cleanup_n.get('toc_blank'):
        if ctx.ncx_path and ctx.ncx_path in entries:
            new_ncx, n = _prune_ncx_bytes(entries[ctx.ncx_path])
            if n:
                entries[ctx.ncx_path] = new_ncx
                toc_blank_pruned += n
        if ctx.nav_path and ctx.nav_path in entries:
            new_nav, n2 = _prune_nav_bytes(entries[ctx.nav_path])
            if n2:
                entries[ctx.nav_path] = new_nav
                toc_blank_pruned += n2
        if toc_blank_pruned:
            logging.getLogger(__name__).info(
                "[epub_beautify] pruned %d blank TOC entries", toc_blank_pruned)

    # ── 1. 目录：生成普通结构目录页 / 替换 nav 语义目录页 / 保留普通目录页 ──
    # 手机阅读器（多看/KOReader/微信读书等）把 <nav epub:type="toc"> 文档当
    # 目录数据源特殊处理（跳过渲染或不应用书内 CSS），因此：
    #   - 无书内目录页 → 生成 mb-toc.xhtml（普通 div 结构）插入 spine 首条；
    #   - 书内目录页是 nav 语义且在 spine → 生成普通结构目录页**替换** spine
    #     中的 nav 条目（原 nav 文件保留在 manifest，properties="nav" 不动，
    #     阅读器侧边栏目录数据源不丢）；
    #   - 书内目录页是普通结构（mulu.xhtml 等）→ 保留原页，仅注入样式与装饰。
    toc_generated = False
    toc_entries = 0
    toc_items = []
    toc_excluded = 0
    toc_links_ok = 0
    toc_links_total = 0

    def _abs_with_anchor(base_dir, ref):
        """把目录条目引用解析为 zip 绝对路径（保留 #锚点）。"""
        if '#' in ref:
            path, anchor = ref.split('#', 1)
            return _resolve_zip(base_dir, path) + '#' + anchor
        return _resolve_zip(base_dir, ref)

    def _collect_toc(items):
        """应用噪音排除 + 深度过滤，返回 (items, excluded_count)。"""
        kept = []
        excluded = 0
        for it in items:
            lv, title, src = it
            if not title or not _toc_entry_allowed(title):
                excluded += 1
                continue
            if toc_depth is not None and lv >= toc_depth:
                excluded += 1
                continue
            kept.append(it)
        return kept, excluded

    # 目录数据源：NCX 优先，其次 EPUB3 nav 文档
    if ctx.ncx_path and ctx.ncx_path in entries:
        ncx_dir = ctx.ncx_path.rsplit('/', 1)[0] + '/' if '/' in ctx.ncx_path else ''
        raw = [
            (lv, title, _snap_with_anchor(entries, _abs_with_anchor(ncx_dir, src)))
            for lv, title, src in _parse_ncx(entries[ctx.ncx_path])
        ]
        toc_items, toc_excluded = _collect_toc(raw)
    elif ctx.nav_path and ctx.nav_path in entries:
        nav_dir = ctx.nav_path.rsplit('/', 1)[0] + '/' if '/' in ctx.nav_path else ''
        raw = [
            (lv, title, _snap_with_anchor(entries, _abs_with_anchor(nav_dir, href)))
            for lv, title, href in _parse_nav_doc(entries[ctx.nav_path])
        ]
        toc_items, toc_excluded = _collect_toc(raw)

    # 书内目录页：spine 中文件名为目录特征或含 <nav epub:type="toc">
    inbook_toc_paths = [
        t for t in text_entries
        if _is_toc_doc(t, _decode(entries[t])[:2000] if t in entries else '')
    ]
    # nav 语义目录页（内容含 <nav epub:type="toc">）：手机阅读器当目录数据源
    # 特殊处理，spine 中无论 manifest 是否标 properties 都需替换为普通结构
    nav_semantic_paths = [
        t for t in text_entries
        if t in entries
        and _has_nav_toc_semantics(_decode(entries[t])[:4000])
    ]
    nav_semantic_in_spine = bool(nav_semantic_paths)
    # spine 条目 zip 路径 → idref 映射（用于替换 itemref）。
    # 必须从 ctx.spine 逐项解析构建，不能 zip(text_entries, linear idrefs)——
    # spine 含非 XHTML 的 linear 条目（SVG 插图页 / 烂书直接塞图）或 manifest
    # 缺 idref 时两者长度与顺序均会错位，导致 nav 替换误伤其他条目。
    path_to_idref = {}
    for idref, linear in ctx.spine:
        if not linear:
            continue
        item = ctx.manifest.get(idref)
        if not item or item['mt'] not in ('application/xhtml+xml', 'text/html'):
            continue
        p = _snap_entry(entries, _resolve_zip(ctx.opf_dir, item['href']))
        path_to_idref.setdefault(p, idref)

    if (not inbook_toc_paths or nav_semantic_in_spine) and toc_items:
        # 截断仅在显式传入 max_toc_entries 时发生（默认 None = 全量收录）
        truncated = (max_toc_entries is not None) and len(toc_items) > max_toc_entries
        if truncated:
            toc_items = toc_items[:max_toc_entries]
        toc_path = ctx.opf_dir + MB_TOC_NAME

        # 链接完整性校验：所有条目目标必须真实存在于包内（生成前校验，零成本）
        toc_links_ok = sum(1 for _, _, src in toc_items if src.split('#', 1)[0] in entries)
        toc_links_total = len(toc_items)

        entries[toc_path] = _build_toc_page(toc_items, ctx.opf_dir, truncated, toc_style)
        toc_entries = len(toc_items)
        # OPF 注册（幂等）。P5：解析 manifest 精确比对 href，不做全文字串匹配——
        # 'mb-toc.xhtml' 子串会被 href="old-mb-toc.xhtml" 等误判成已注册而漏注册；
        # id 同步防撞（既有 id="mb-toc" 时顺延 -x）
        opf_str = _decode(entries[ctx.opf_path])
        if not any(it.get('href') == MB_TOC_NAME for it in ctx.manifest.values()):
            mb_id = 'mb-toc'
            while mb_id in ctx.manifest:
                mb_id += '-x'
            opf_str = _opf_add_to_manifest(
                opf_str,
                '<item id="%s" href="%s" media-type="application/xhtml+xml"/>'
                % (mb_id, MB_TOC_NAME),
                '目录页',
            )
            # 找出 spine 中待替换的 idref：有 nav 语义时只替换 nav 页，否则为无目录时的插入
            if nav_semantic_in_spine:
                replace_ids = [
                    path_to_idref[t] for t in nav_semantic_paths
                    if path_to_idref.get(t) and path_to_idref[t] != mb_id
                ]
            else:
                replace_ids = []
            if replace_ids:
                # 替换第一个 nav 语义目录页条目；其余的直接移除。
                # idref 兼容单引号属性；首替换 miss 会静默丢 spine 条目，显式报错
                opf_str, n_ref = re.subn(
                    r'\s*<itemref\b[^>]*idref=["\']%s["\'][^>]*/?>' % re.escape(replace_ids[0]),
                    '\n<itemref idref="%s" linear="yes"/>' % mb_id,
                    opf_str, count=1,
                )
                if n_ref == 0:
                    raise RuntimeError('OPF spine 缺 idref=%s 条目，无法挂载目录页' % replace_ids[0])
                for extra in replace_ids[1:]:
                    opf_str = re.sub(
                        r'\s*<itemref\b[^>]*idref=["\']%s["\'][^>]*/?>' % re.escape(extra),
                        '', opf_str, count=1,
                    )
            else:
                # 插入 spine 第一个 linear 条目之前
                spine_m = re.search(r'<spine[^>]*>', opf_str)
                if spine_m:
                    insert_at = spine_m.end()
                    opf_str = (
                        opf_str[:insert_at]
                        + '\n<itemref idref="%s" linear="yes"/>' % mb_id
                        + opf_str[insert_at:]
                    )
            entries[ctx.opf_path] = opf_str.encode('utf-8')
            toc_generated = True

    # ── 1.5 附加资源（如背景图片）：写入包体 + manifest 注册（幂等）──
    extra_count = 0
    if extra_assets:
        opf_now = _decode(entries[ctx.opf_path])
        # P5：href 用解析集合精确比对（替代 href="..." 子串匹配）；
        # id 由 rsplit 取名而来，会与既有 id / 彼此相撞（bg.jpg vs bg.png），
        # 顺延 -x 防撞；mb-toc / mb-beauty 为本流程保留 id
        manifest_hrefs = {it.get('href') for it in ctx.manifest.values()}
        used_ids = set(ctx.manifest) | {'mb-toc', 'mb-beauty'}
        added = ''
        for name, (blob, mtype) in extra_assets.items():
            entries[ctx.opf_dir + name] = blob
            extra_count += 1
            if name in manifest_hrefs:
                continue
            item_id = name.rsplit('.', 1)[0]
            while item_id in used_ids:
                item_id += '-x'
            used_ids.add(item_id)
            added += ('\n<item id="%s" href="%s" media-type="%s"/>'
                      % (item_id, name, mtype))
        if added:
            opf_now = _opf_add_to_manifest(opf_now, added.lstrip('\n'), '附加资源')
            entries[ctx.opf_path] = opf_now.encode('utf-8')

    # ── 2. mb-beauty.css 注入 ──
    css_zip_path = ctx.opf_dir + MB_CSS_NAME
    entries[css_zip_path] = preset_css.encode('utf-8')
    # 注册到 OPF manifest（部分阅读器要求 CSS 在 manifest 中才生效）。
    # P5：解析比对 href；P6：缺 </manifest> 显式报错
    opf_raw = _decode(entries[ctx.opf_path])
    if not any(it.get('href') == MB_CSS_NAME for it in ctx.manifest.values()):
        mb_css_id = 'mb-beauty'
        while mb_css_id in ctx.manifest:
            mb_css_id += '-x'
        opf_raw = _opf_add_to_manifest(
            opf_raw,
            '<item id="%s" href="%s" media-type="text/css"/>' % (mb_css_id, MB_CSS_NAME),
            '样式表',
        )
        entries[ctx.opf_path] = opf_raw.encode('utf-8')

    # ── 3. 逐正文条目：内容清理 + 目录页标记 + 章节名标记 + 对话行标记 + 注入 CSS ──
    marked_headers = 0
    marked_volumes = 0
    titles_split = 0
    injected = 0
    cleaned_leading = 0
    removed_empty = 0
    dialogues_marked = 0
    notes_refs = notes_items = notes_normalized = notes_wrapped = 0
    for t in text_entries:
        if t not in entries:
            continue
        html = _decode(entries[t])
        # 统一 XML 声明为 utf-8（GBK/Big5 原文件头修正，避免 utf-8 实体与声明不一致）
        if html.lstrip().startswith('<?xml'):
            html = re.sub(r"""(<\?xml[^>]*encoding\s*=\s*)["'][^"']*["']""", r'\1"utf-8"', html, count=1, flags=re.IGNORECASE)
        changed = False
        # 弹注/标注美化（先于章节标记执行，豁免类才能生效；目录/前置页不做）
        if notes and not _is_toc_doc(t, html) and not _is_front_file(t):
            new_html, nstats = mark_notes_in_html(html, normalize=True,
                                                  note_mark=note_mark)
            if nstats['refs'] or nstats['items']:
                notes_refs += nstats['refs']
                notes_items += nstats['items']
                notes_normalized += nstats['normalized']
                notes_wrapped += nstats['wrapped']
                changed = True
                html = new_html
        # 内容清理（段首空格归一/空段/meta），目录页不做文本清理避免破坏布局
        if not _is_toc_doc(t, html):
            new_html, n_lead, n_empty = _clean_html_body(html, cleanup_n)
            if n_lead or n_empty or new_html != html:
                cleaned_leading += n_lead
                removed_empty += n_empty
                if new_html != html:
                    changed = True
                    html = new_html
        # 目录页：body 打 mb-toc-page 标记 + 注入真实装饰元素，不做章节标记
        if _is_toc_doc(t, html):
            # 修复旧版缺陷输出：目录行曾被误当章节标题打标，mb-ch 的
            # page-break-before 会把目录页炸成多个「第x章」独立页
            fixed = _strip_chapter_marks(html)
            if fixed != html:
                changed = True
                html = fixed
            new_html = _mark_toc_page_body(html)
            if new_html != html:
                changed = True
                html = new_html
            new_html = _decorate_toc_page(html)
            if new_html != html:
                changed = True
                html = new_html
        elif not _is_front_file(t):
            new_html, mk = mark_chapters_in_html(html, split_title=bool(split_title))
            if mk['chapters'] or mk['volumes'] or mk['splits']:
                marked_headers += mk['chapters']
                marked_volumes += mk['volumes']
                titles_split += mk['splits']
                changed = True
                html = new_html
        # 对话行点缀（开关控制打标；目录/前置页不做）
        if dialogue and not _is_toc_doc(t, html) and not _is_front_file(t):
            new_html, dcount = mark_dialogue_in_html(html)
            if dcount:
                dialogues_marked += dcount
                changed = True
                html = new_html
        new_html = _inject_css_link(html, _relative_href(t, css_zip_path))
        if new_html != html:
            changed = True
            html = new_html
        if changed:
            entries[t] = html.encode('utf-8')
            injected += 1

    # ── 4. 翻页方向：竖排预设把 spine 设为 rtl（从左向右翻）──
    rtl_set = False
    if page_progression:
        opf_now = _decode(entries[ctx.opf_path])
        opf_new = _set_page_progression(opf_now, page_progression)
        if opf_new != opf_now:
            entries[ctx.opf_path] = opf_new.encode('utf-8')
        rtl_set = 'page-progression-direction="%s"' % page_progression in opf_new

    _write_zip(entries, out_path)
    return {
        'marked_headers': marked_headers,
        'marked_volumes': marked_volumes,
        'titles_split': titles_split,
        'toc_generated': toc_generated,
        'toc_entries': toc_entries,
        'css_injected_chapters': injected,
        'chapters': len(text_entries),
        'page_progression': page_progression if rtl_set else '',
        'cleaned_leading': cleaned_leading,
        'removed_empty': removed_empty,
        'toc_excluded': toc_excluded,
        'toc_depth': toc_depth or 0,
        'toc_links_ok': toc_links_ok if toc_generated else 0,
        'toc_links_total': toc_links_total if toc_generated else 0,
        'dialogues_marked': dialogues_marked,
        'notes_refs': notes_refs,
        'notes_items': notes_items,
        'notes_normalized': notes_normalized,
        'notes_wrapped': notes_wrapped,
        'note_mark': note_mark if notes else '',
        'toc_blank_pruned': toc_blank_pruned,
        'extra_assets': extra_count,
    }
