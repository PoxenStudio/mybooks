# -*- coding: utf-8 -*-
"""EPUB 结构精修库（EPUB修复工具「精修」阶段的核心）。

对既有 EPUB 做**外科手术式**结构清理，与 ``epub_fixer.py`` 的 epub→epub
重转（ebook-convert 全量重建）互补：重转会重排版、慢且丢原始结构；精修
在 zip 层原位修结构问题，不碰排版与元数据语义。

探测与修复**分离且同源**：每个操作先跑只读探测器（analyze 与 repair 共
用同一函数），修复器按探测器给的问题单元逐个动手，保证「检测到什么就
能修什么」。问题单元统一为 ``(kind, payload)``：

- ``('file', zip路径)``     删包内文件（级联 manifest/spine/guide）
- ``('doc',  zip路径)``     编辑文档内容（去 script / adept meta / kobo 痕迹…）
- ``('attr', 属性名)``      删 spine 上的属性（page-map / toc）
- ``('pair', (iid, 路径))`` 删一个图片 manifest 条目
- ``('item', (iid, href) 或 src)`` 删一个清单条目（指向缺失文件）／标记一个断链条目
- ``('opf',  'OPF metadata adept meta')`` 清 OPF 元数据级 adept meta

所有操作幂等（重复跑第二次计数为 0）；删文件的级联由 ``_OpfEditor``
统一负责；**删除类操作互链感知**——被幸存内容文档 ``<a href>`` 引用的
目标不会成为删项（unused_images 直接计入引用集；另两个删除操作跳过并
记录告警——正文互链不在级联职责内，宁可不删不断链）；写包前有
``_final_gate`` 守门：**本精修引入**的引用断裂（含正文互链）一律拒绝
出包（书自带的旧断裂不在精修职责内）。

操作清单（语义口径与外置质量体检工具的 check id 一一对应；实现为本仓
自研代码，不含任何第三方插件代码）：

===========================  =============================================  ==========================
op key                       行为                                           对应体检 check
===========================  =============================================  ==========================
remove_artifacts             删 iTunes plist / calibre_bookmarks / OS 垃圾   --
remove_missing_manifest      清单指向缺失文件的条目（级联 spine/guide/toc）  epub_manifest_files_missing
add_unmanifested             未登记文件补登记（未知扩展名跳过并告警）         epub_unmanifested_files
remove_unmanifested          删除未登记文件（**默认关**；被互链引用的跳过）   epub_unmanifested_files
remove_javascript            删 script 元素与 .js 文件                       epub_javascript
remove_drm_meta_tags         删 Adobe adept resource meta + rights.xml       epub_drm_meta
remove_page_maps             Adobe page-map / spine page-map / GBS 锚点      --
remove_xpgt                  删 .xpgt 模板与 link/@import 引用               epub_xpgt_margins
strip_kobo                   Kobo 痕迹（有 kobo 标记才动手）                 --
remove_unused_images         删无引用图片（img/svg/url()/a-href 均算引用，     epub_unused_images
                             CSS basename 保守匹配）
remove_broken_cover_pages    整页图片全断且无正文的封面页删除（被互链跳过）   --
fix_broken_toc               NCX 与 EPUB3 nav 断链条目剔除（子级提升）        epub_ncx_toc_broken_links
encode_utf8                  内容文档统一 UTF-8（写出阶段生效）               --
===========================  =============================================  ==========================

明确**不做**的操作（设计决策，勿"补全"）：
- 删内嵌字体：CJK 书删字体会出豆腐块；同类第三方实现还有删字体文件
  不清理 encryption.xml 混淆条目导致坏书的缺陷；
- 智能标点（英文中心，对中文有害）、删非 DC 元数据（会毁 EPUB3
  rendition:*/竖排/固定布局声明）、jacket / 封面插入替换（宿主已有封面
  工具与裁剪）、CSS 页边距重写 / HTML 瘦身 / 通用 span 解包 / 目录压平
  （低价值或与 EPUB美化 重叠）。

容器读写 / OPF 解析 / NCX、nav 解析 / 规范 zip 写出 / 编码兜底复用同包
``epub_beautify_lib`` 已验证实现；OPF 修改走**文本级手术**（正则删
``<item>``/``<itemref>``/``<reference>`` 标签，不整体重序列化，避免 ET 改写
丢 ``opf:`` 前缀属性命名空间），NCX/nav 修改走 ET（同 ``_prune_ncx_bytes``
先例）。加密拒绝语义：``META-INF/encryption.xml`` 出现字体混淆之外的
算法即判定全书加密，拒绝精修。
"""

import logging
import posixpath
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

from webserver.toolbox.utils.epub_beautify_lib import (
    _NS_DTBNCX,
    _NS_XHTML,
    _decode,
    _opf_add_to_manifest,
    _parse_opf,
    _q,
    _read_zip_entries,
    _resolve_zip,
    _snap_entry,
    _write_zip,
)

logger = logging.getLogger(__name__)

# ── 操作注册表 ────────────────────────────────────────────────────────────────
# 执行顺序即列表顺序：垃圾/清单修正在前，引用扫描类居中，目录修正在图片
# 与坏封面页删除之后（删除产生的断链由 fix_broken_toc 统一收尾），编码统
# 一在写出前最后一步。

OP_KEYS = [
    'remove_artifacts',
    'remove_missing_manifest',
    'add_unmanifested',
    'remove_unmanifested',
    'remove_javascript',
    'remove_drm_meta_tags',
    'remove_page_maps',
    'remove_xpgt',
    'strip_kobo',
    'remove_unused_images',
    'remove_broken_cover_pages',
    'fix_broken_toc',
    'encode_utf8',
]

# remove_unmanifested 删除的未登记文件可能被已登记文档互链引用（断链由
# 重转阶段兜底修复），默认不勾选，由用户看到检测结果后显式开启
DEFAULT_OPS = [k for k in OP_KEYS if k != 'remove_unmanifested']

# 字体混淆算法（OCF 规范）：视为非 DRM，书仍可精修
_FONT_OBFUSCATION_ALGOS = {
    'http://www.idpf.org/2008/embedding',
    'http://ns.adobe.com/pdf/enc#RC',
}


class EpubRepairError(RuntimeError):
    """精修失败（书级）。"""


class EpubDrmError(EpubRepairError):
    """全书加密（非字体混淆），拒绝精修。"""


def normalize_ops(raw) -> list:
    """归一化勾选项：None/空 → 默认集；列表 → 白名单过滤并按执行顺序排序。

    :raises ValueError: 传入未知 op key 时（调用方应转为参数错误）。
    """
    if raw is None:
        return list(DEFAULT_OPS)
    if not isinstance(raw, (list, tuple, set)):
        raise ValueError('ops 必须是列表')
    unknown = [k for k in raw if k not in OP_KEYS]
    if unknown:
        raise ValueError('未知修复项：%s' % ','.join(map(str, unknown)))
    wanted = set(raw)
    return [k for k in OP_KEYS if k in wanted]


# ── 基础判定 ──────────────────────────────────────────────────────────────────

_CONTENT_MT = ('application/xhtml+xml', 'text/html')
_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.bmp', '.webp'}
_TEXT_EXTS_FOR_SCAN = {'.xhtml', '.html', '.htm', '.css', '.svg', '.ncx', '.opf'}

# 垃圾文件（basename 小写精确匹配）
_JUNK_NAMES = {
    'itunesmetadata.plist', 'itunesartwork', 'itunesartwork@2x',
    'calibre_bookmarks.txt', '.ds_store', 'thumbs.db', 'desktop.ini',
}

_MEDIA_BY_EXT = {
    '.xhtml': 'application/xhtml+xml', '.htm': 'application/xhtml+xml',
    '.html': 'application/xhtml+xml', '.css': 'text/css',
    '.js': 'application/javascript', '.png': 'image/png',
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
    '.svg': 'image/svg+xml', '.bmp': 'image/bmp', '.webp': 'image/webp',
    '.ttf': 'application/x-font-ttf', '.otf': 'application/x-font-opentype',
    '.woff': 'application/font-woff', '.woff2': 'font/woff2',
    '.ncx': 'application/x-dtbncx+xml', '.mp3': 'audio/mpeg',
    '.mp4': 'video/mp4', '.ogg': 'audio/ogg', '.pls': 'audio/x-mpegurl',
    '.xpgt': 'application/vnd.adobe-page-template+xml', '.xml': 'application/xml',
    '.plist': 'application/xml', '.txt': 'text/plain',
}


def _ext(name: str) -> str:
    base = name.rsplit('/', 1)[-1]
    return base.rsplit('.', 1)[-1].lower() if '.' in base else ''


def _basename(name: str) -> str:
    return name.rsplit('/', 1)[-1]


def _dir_of(path: str) -> str:
    return path.rsplit('/', 1)[0] + '/' if '/' in path else ''


def _is_image_path(path: str) -> bool:
    return ('.' + _ext(path)) in _IMAGE_EXTS


def _media_type_for(name: str, data: bytes = b'') -> str:
    """按扩展名猜 media-type；htm/html 嗅探 XML 命名空间强标 XHTML。"""
    ext = _ext(name)
    if ext in ('.htm', '.html', '.xhtml'):
        head = data[:2048].lstrip()
        if b'xmlns' in head or b'<html' in head.lower() or b'<!DOCTYPE' in head.upper():
            return 'application/xhtml+xml'
        return 'text/html'
    return _MEDIA_BY_EXT.get('.' + ext, 'application/octet-stream') if ext \
        else 'application/octet-stream'


def _esc(text: str) -> str:
    return (text or '').replace('&', '&amp;').replace('<', '&lt;') \
        .replace('>', '&gt;').replace('"', '&quot;')


# ── 加密检测 ──────────────────────────────────────────────────────────────────

def _encryption_entries(entries: dict) -> list:
    """解析 META-INF/encryption.xml，返回 [(algorithm, target_name)]。"""
    data = entries.get('META-INF/encryption.xml')
    if not data:
        return []
    try:
        root = ET.fromstring(_decode(data))
    except ET.ParseError as err:
        logger.warning("[epub_fixer] encryption.xml parse failed: %s", err)
        return []
    enc_ns = 'urn:oasis:names:tc:opendocument:xmlns:container'
    xmlenc_ns = 'http://www.w3.org/2001/04/xmlenc#'
    out = []
    for enc in root.iter('{%s}EncryptedData' % xmlenc_ns):
        alg = ''
        method = enc.find('{%s}EncryptionMethod' % xmlenc_ns)
        if method is not None:
            alg = method.get('Algorithm') or ''
        for ref in enc.iter('{%s}CipherReference' % xmlenc_ns):
            out.append((alg, (ref.get('Reference') or '').lstrip('/')))
    return out


def _drm_targets(entries: dict) -> list:
    """全书加密条目（字体混淆除外）。非空 = 拒绝精修。"""
    return [(a, t) for a, t in _encryption_entries(entries)
            if a and a not in _FONT_OBFUSCATION_ALGOS]


def _require_not_drm(entries: dict) -> None:
    if _drm_targets(entries):
        raise EpubDrmError('EPUB 内容已加密（DRM），无法精修')


# ── OPF 文本级编辑器 ──────────────────────────────────────────────────────────
# 只做删标签 / 删属性 / 插 item 三类手术，不整体重序列化（避免 ET 改写丢
# opf: 前缀属性命名空间）。

class _OpfEditor:

    def __init__(self, opf_text: str, opf_dir: str, entries: dict):
        self.text = opf_text
        self.opf_dir = opf_dir
        self.entries = entries
        try:
            self._reload()
        except ET.ParseError as err:
            raise EpubRepairError('OPF 解析失败：%s' % err) from err

    # ---- 视图（每次变更后重建） ----

    def _reload(self):
        root = ET.fromstring(self.text)
        self.item_hrefs = {}     # iid -> href 原始属性值
        self.item_mts = {}       # iid -> media-type（小写）
        self.item_props = {}     # iid -> properties
        for item in root.iter(_q('item')):
            iid = item.get('id') or ''
            if not iid:
                continue
            self.item_hrefs[iid] = item.get('href') or ''
            self.item_mts[iid] = (item.get('media-type') or '').lower()
            self.item_props[iid] = item.get('properties') or ''
        self.item_paths = {
            iid: _snap_entry(self.entries, _resolve_zip(self.opf_dir, href))
            for iid, href in self.item_hrefs.items() if href
        }
        self.spine_idrefs = [
            m.group(1) for m in re.finditer(
                r'<itemref\b[^>]*\bidref\s*=\s*["\']([^"\']+)["\']',
                self.text, re.IGNORECASE)]
        m = re.search(r'<spine\b[^>]*>', self.text, re.IGNORECASE)
        self.spine_tag = m.group(0) if m else ''
        toc_m = re.search(r'\stoc\s*=\s*["\']([^"\']+)["\']', self.spine_tag) \
            if self.spine_tag else None
        self.spine_toc_id = toc_m.group(1) if toc_m else ''

    def path_of(self, iid: str) -> str:
        return self.item_paths.get(iid, '')

    def ids_for_path(self, path: str) -> list:
        return [iid for iid, p in self.item_paths.items() if p == path]

    def ids_by_media(self, mts) -> list:
        return [iid for iid, mt in self.item_mts.items() if mt in mts]

    def ids_by_ext(self, exts) -> list:
        return [iid for iid, p in self.item_paths.items()
                if p in self.entries and ('.' + _ext(p)) in exts]

    def cover_item_paths(self) -> set:
        """封面图目标路径：OPF2 ``<meta name="cover">`` + EPUB3 properties。"""
        covers = set()
        m = re.search(
            r'<meta\b[^>]*\bname\s*=\s*["\']cover["\'][^>]*\bcontent\s*=\s*["\']([^"\']+)["\']',
            self.text, re.IGNORECASE)
        if not m:
            m = re.search(
                r'<meta\b[^>]*\bcontent\s*=\s*["\']([^"\']+)["\'][^>]*\bname\s*=\s*["\']cover["\']',
                self.text, re.IGNORECASE)
        if m and m.group(1) in self.item_paths:
            covers.add(self.item_paths[m.group(1)])
        for iid, props in self.item_props.items():
            if 'cover-image' in props.split() and self.item_paths.get(iid):
                covers.add(self.item_paths[iid])
        return covers

    # ---- 变更 ----

    def _remove_tags_with_attr(self, tag: str, attr: str, value: str) -> int:
        """删除形如 <tag ... attr="value" .../> 的标签（自闭合优先，回落成对）。"""
        pat_self = re.compile(
            r'<%s\b[^>]*\b(?:opf:)?%s\s*=\s*["\']%s["\'][^>]*/>'
            % (tag, attr, re.escape(value)), re.IGNORECASE)
        new, n = pat_self.subn('', self.text)
        if n == 0:
            pat_pair = re.compile(
                r'<%s\b[^>]*\b(?:opf:)?%s\s*=\s*["\']%s["\'][^>]*>\s*</%s\s*>'
                % (tag, attr, re.escape(value), tag), re.IGNORECASE | re.DOTALL)
            new, n = pat_pair.subn('', self.text)
        self.text = new
        return n

    def _guide_refs(self) -> list:
        """guide 内全部 reference：[(tag_text, resolved_path)]。"""
        gm = re.search(r'(?is)<guide\b.*?</guide\s*>', self.text)
        if not gm:
            return []
        out = []
        for rm in re.finditer(r'<reference\b[^>]*>', gm.group(0), re.IGNORECASE):
            tag = rm.group(0)
            hm = re.search(r'\bhref\s*=\s*["\']([^"\']+)["\']', tag, re.IGNORECASE)
            if not hm:
                continue
            out.append((tag, _snap_entry(self.entries,
                                         _resolve_zip(self.opf_dir, hm.group(1)))))
        return out

    def _remove_guide_refs_to(self, path: str) -> int:
        n = 0
        for tag, target in self._guide_refs():
            if target == path:
                self.text = self.text.replace(tag, '', 1)
                n += 1
        return n

    def remove_item(self, iid: str) -> bool:
        """删除 manifest 条目并级联 spine itemref / guide reference / spine@toc。"""
        if iid not in self.item_hrefs:
            return False
        path = self.item_paths.get(iid, '')
        self._remove_tags_with_attr('item', 'id', iid)
        self._remove_tags_with_attr('itemref', 'idref', iid)
        if path:
            self._remove_guide_refs_to(path)
        if self.spine_toc_id == iid and self.spine_tag:
            new_tag = re.sub(r'\s*toc\s*=\s*["\']%s["\']' % re.escape(iid), '',
                             self.spine_tag, count=1)
            self.text = self.text.replace(self.spine_tag, new_tag, 1)
        self._reload()
        return True

    def remove_items_for_path(self, path: str) -> int:
        n = 0
        for iid in self.ids_for_path(path):
            if self.remove_item(iid):
                n += 1
        return n

    def gen_item_id(self, base='fx-item') -> str:
        i = 1
        while '%s-%d' % (base, i) in self.item_hrefs:
            i += 1
        return '%s-%d' % (base, i)

    def add_item(self, href: str, mt: str, props: str = '') -> str:
        iid = self.gen_item_id()
        attrs = 'id="%s" href="%s" media-type="%s"' % (iid, _esc(href), _esc(mt))
        if props:
            attrs += ' properties="%s"' % _esc(props)
        self.text = _opf_add_to_manifest(
            self.text, '<item %s/>' % attrs, '精修补登记项')
        self._reload()
        return iid

    def remove_spine_attr(self, attr: str) -> int:
        if not self.spine_tag:
            return 0
        new_tag, n = re.subn(
            r'\s*%s\s*=\s*["\'][^"\']*["\']' % re.escape(attr), '',
            self.spine_tag, count=1)
        if n:
            self.text = self.text.replace(self.spine_tag, new_tag, 1)
            self._reload()
        return n

    def remove_adept_meta(self) -> int:
        new, n = re.subn(
            r'<meta\b[^>]*\bname\s*=\s*["\']adept[^"\']*["\'][^>]*/?>',
            '', self.text, flags=re.IGNORECASE)
        if n:
            self.text = new
            self._reload()
        return n


# ── 状态容器 ──────────────────────────────────────────────────────────────────

class _State:
    """一次精修/分析的共享状态。探测器只读；修复器经由本类变更。"""

    def __init__(self, entries: dict, ops: list):
        self.entries = entries
        self.ops = set(ops)
        try:
            self.ctx = _parse_opf(entries)
        except RuntimeError as err:
            raise EpubRepairError(str(err)) from err
        if not self.ctx.manifest:
            raise EpubRepairError('OPF manifest 解析为空，文件可能已损坏，请改用重转修复')
        self.editor = _OpfEditor(
            _decode(entries[self.ctx.opf_path]), self.ctx.opf_dir, entries)
        self.pre_item_ids = set(self.editor.item_hrefs)
        self.samples = {k: [] for k in OP_KEYS}
        self.deleted_paths = set()
        self.warnings = []

    # ---- 常用视图 ----

    def content_paths(self) -> list:
        """全部已登记内容文档（含不在 spine 的），已对齐条目名且存在。"""
        out = []
        for iid in self.editor.ids_by_media(_CONTENT_MT):
            p = self.editor.path_of(iid)
            if p and p in self.entries:
                out.append(p)
        return out

    def css_paths(self) -> list:
        out = []
        for iid in self.editor.ids_by_media(('text/css',)):
            p = self.editor.path_of(iid)
            if p and p in self.entries:
                out.append(p)
        return out

    def svg_paths(self) -> list:
        """已登记 SVG（本身可引用其它图片，也参与引用扫描）。"""
        out = []
        for iid in self.editor.ids_by_media(('image/svg+xml',)):
            p = self.editor.path_of(iid)
            if p and p in self.entries:
                out.append(p)
        return out

    def image_items(self) -> list:
        """[(iid, zip_path)]：媒体类型或扩展名是图片的已登记条目。"""
        out = []
        seen = set()
        for iid in self.editor.ids_by_media(('image/svg+xml',)) + \
                self.editor.ids_by_ext(_IMAGE_EXTS):
            if iid in seen:
                continue
            seen.add(iid)
            p = self.editor.path_of(iid)
            if p:
                out.append((iid, p))
        return out

    def ncx_dir(self) -> str:
        return _dir_of(self.ctx.ncx_path) if self.ctx.ncx_path else ''

    def nav_dir(self) -> str:
        return _dir_of(self.ctx.nav_path) if self.ctx.nav_path else ''

    # ---- 变更原语 ----

    def delete_entry(self, path: str) -> bool:
        """删除包内文件并级联 manifest（含 spine/guide/spine@toc）。"""
        if path not in self.entries:
            return False
        self.editor.remove_items_for_path(path)
        del self.entries[path]
        self.deleted_paths.add(path)
        return True

    def note(self, op_key: str, sample: str):
        if len(self.samples[op_key]) < 10:
            self.samples[op_key].append(sample)


# ── 引用扫描 ──────────────────────────────────────────────────────────────────

_RE_IMG_SRC = re.compile(
    r'<img\b[^>]*?\bsrc\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_RE_SVG_IMAGE_HREF = re.compile(
    r'<image\b[^>]*?\b(?:xlink:)?href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_RE_CSS_URL = re.compile(r'url\s*\(\s*([\'"]?)([^\'")]+)\1\s*\)', re.IGNORECASE)


def _resolve_ref(state: _State, base_dir: str, ref: str):
    """文档内引用 → zip 目标路径；非本地引用返回 None。"""
    ref = (ref or '').strip()
    if not ref or ref.lower().startswith(
            ('data:', 'http://', 'https://', 'mailto:')) or ref.startswith('#'):
        return None
    return _snap_entry(state.entries, _resolve_zip(base_dir, ref))


def _scan_doc_refs(state: _State, path: str) -> set:
    """扫描一个文本文档引用的本地资源目标（img / svg image / 内联 url()）。"""
    refs = set()
    base = _dir_of(path)
    text = _decode(state.entries[path])
    for pattern in (_RE_IMG_SRC, _RE_SVG_IMAGE_HREF):
        for m in pattern.finditer(text):
            p = _resolve_ref(state, base, m.group(1).split('#')[0])
            if p:
                refs.add(p)
    for m in _RE_CSS_URL.finditer(text):
        p = _resolve_ref(state, base, m.group(2).split('#')[0])
        if p:
            refs.add(p)
    return refs


_RE_A_HREF = re.compile(
    r'<a\b[^>]*?\bhref\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


def _scan_doc_ahrefs(state: _State, path: str) -> set:
    """扫描一个文本文档的本地 <a href> 互链目标（name 锚点无 href 不算）。"""
    refs = set()
    base = _dir_of(path)
    for m in _RE_A_HREF.finditer(_decode(state.entries[path])):
        p = _resolve_ref(state, base, m.group(1).split('#')[0])
        if p:
            refs.add(p)
    return refs


def _ahref_linked_targets(state: _State, exclude: set) -> set:
    """全部幸存内容文档 <a href> 指向的目标集合（exclude 内的文档不算来源）。"""
    linked = set()
    for p in state.content_paths():
        if p in exclude or p not in state.entries:
            continue
        linked |= _scan_doc_ahrefs(state, p)
    return linked


def _css_url_basenames(state: _State, paths: list) -> set:
    """CSS url() 引用的 basename 集合（保守匹配用，宁可少删）。"""
    out = set()
    for p in paths:
        for m in _RE_CSS_URL.finditer(_decode(state.entries[p])):
            ref = m.group(2).split('#')[0]
            if ref.lower().startswith(('data:', 'http://', 'https://')):
                continue
            out.add(_basename(ref).lower())
    return out


# ── NCX / nav 断链判定（探测器、修复器、守门三方共用同一谓词） ────────────────

def _ncx_np_is_broken(state: _State, np, known_deleted) -> bool:
    """navPoint 是否断链：content 缺失/空 src 且无子级，或目标文件不存在。

    known_deleted 非 None 时只把「指向该集合」的视为断链（级联模式，供
    fix_broken_toc 未勾选时的删除兜底与最终守门使用）——空 src 空壳不属
    于级联职责，不动。
    """
    content = np.find(_q('content', _NS_DTBNCX))
    src = content.get('src', '') if content is not None else ''
    if not src:
        if known_deleted is not None:
            return False
        return not any(c.tag == _q('navPoint', _NS_DTBNCX) for c in np)
    target = _resolve_ref(state, state.ncx_dir(), src.split('#')[0])
    if target and target in state.entries:
        return False
    if known_deleted is not None:
        return target in known_deleted if target else False
    return True


def _nav_li_is_broken(state: _State, li, known_deleted) -> bool:
    """nav <li> 是否断链（有 <a href> 且目标不存在；纯文本分组标题不动）。"""
    a = li.find(_q('a', _NS_XHTML))
    if a is None:
        return False
    href = a.get('href') or ''
    if not href or href.startswith('#'):
        return False
    target = _resolve_ref(state, state.nav_dir(), href.split('#')[0])
    if target and target in state.entries:
        return False
    if known_deleted is not None:
        return target in known_deleted if target else False
    return True


def _ncx_broken_srcs(state: _State, known_deleted=None) -> list:
    """[(src, target)]：NCX 中全部断链 navPoint（只读）。"""
    if not state.ctx.ncx_path or state.ctx.ncx_path not in state.entries:
        return []
    try:
        root = ET.fromstring(_decode(state.entries[state.ctx.ncx_path]))
    except ET.ParseError:
        return []
    out = []
    for np in root.iter(_q('navPoint', _NS_DTBNCX)):
        if not _ncx_np_is_broken(state, np, known_deleted):
            continue
        content = np.find(_q('content', _NS_DTBNCX))
        src = content.get('src', '') if content is not None else ''
        target = _resolve_ref(state, state.ncx_dir(), src.split('#')[0]) if src else None
        out.append((src, target))
    return out


def _nav_broken_hrefs(state: _State, known_deleted=None) -> list:
    """[(href, target)]：EPUB3 nav toc 中全部断链 <li>（只读）。"""
    if not state.ctx.nav_path or state.ctx.nav_path not in state.entries:
        return []
    try:
        root = ET.fromstring(_decode(state.entries[state.ctx.nav_path]))
    except ET.ParseError:
        return []
    out = []
    for n in root.iter(_q('nav', _NS_XHTML)):
        ntype = n.get('{http://www.idpf.org/2007/ops}type') or ''
        if 'toc' not in ntype:
            continue
        for li in n.iter(_q('li', _NS_XHTML)):
            if not _nav_li_is_broken(state, li, known_deleted):
                continue
            a = li.find(_q('a', _NS_XHTML))
            href = a.get('href') or '' if a is not None else ''
            target = _resolve_ref(state, state.nav_dir(), href.split('#')[0]) if href else None
            out.append((href, target))
    return out


def _fix_ncx_broken(state: _State, known_deleted=None) -> tuple:
    """剔除 NCX 断链 navPoint（子级提升到父级同位置），重排 playOrder。

    :return: (new_bytes, removed_count)
    """
    data = state.entries.get(state.ctx.ncx_path)
    if not data:
        return data, 0
    try:
        root = ET.fromstring(_decode(data))
    except ET.ParseError:
        return data, 0
    nav_map = root.find(_q('navMap', _NS_DTBNCX))
    if nav_map is None:
        return data, 0
    removed = 0

    def _clean(elem):
        nonlocal removed
        for np in list(elem):
            if np.tag != _q('navPoint', _NS_DTBNCX):
                continue
            _clean(np)
            if not _ncx_np_is_broken(state, np, known_deleted):
                continue
            removed += 1
            idx = list(elem).index(np)
            children = [c for c in np if c.tag == _q('navPoint', _NS_DTBNCX)]
            elem.remove(np)
            for off, child in enumerate(children):
                np.remove(child)
                elem.insert(idx + off, child)

    _clean(nav_map)
    if not removed:
        return data, 0
    order = 0
    for np in root.iter(_q('navPoint', _NS_DTBNCX)):
        order += 1
        np.set('playOrder', str(order))
    ET.register_namespace('', _NS_DTBNCX)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True), removed


def _fix_nav_broken(state: _State, known_deleted=None) -> tuple:
    """剔除 EPUB3 nav（epub:type=toc）断链 <li>（子列表条目上提）。

    :return: (new_bytes, removed_count)
    """
    data = state.entries.get(state.ctx.nav_path)
    if not data:
        return data, 0
    try:
        root = ET.fromstring(_decode(data))
    except ET.ParseError:
        return data, 0
    nav = None
    for n in root.iter(_q('nav', _NS_XHTML)):
        ntype = n.get('{http://www.idpf.org/2007/ops}type') or ''
        if 'toc' in ntype:
            nav = n
            break
    if nav is None:
        return data, 0
    removed = 0

    def _first_list(elem):
        for tag in ('ol', 'ul'):
            child = elem.find(_q(tag, _NS_XHTML))
            if child is not None:
                return child
        return None

    def _clean_list(lst):
        nonlocal removed
        for li in list(lst):
            if li.tag != _q('li', _NS_XHTML):
                continue
            sub = _first_list(li)
            if sub is not None:
                _clean_list(sub)
            if not _nav_li_is_broken(state, li, known_deleted):
                continue
            removed += 1
            idx = list(lst).index(li)
            sub = _first_list(li)
            if sub is not None:
                items = [c for c in sub if c.tag in
                         (_q('li', _NS_XHTML), _q('ol', _NS_XHTML), _q('ul', _NS_XHTML))]
                lst.remove(li)
                for off, item in enumerate(items):
                    sub.remove(item)
                    lst.insert(idx + off, item)
            else:
                lst.remove(li)

    top = _first_list(nav)
    if top is not None:
        _clean_list(top)
    if not removed:
        return data, 0
    ET.register_namespace('', _NS_XHTML)
    ET.register_namespace('epub', 'http://www.idpf.org/2007/ops')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True), removed


def _toc_remove_targets(state: _State, paths: set) -> int:
    """级联兜底：fix_broken_toc 未勾选时，只删指向已删文件的目录条目。"""
    if not paths:
        return 0
    n = 0
    if state.ctx.ncx_path and state.ctx.ncx_path in state.entries:
        new_data, k = _fix_ncx_broken(state, known_deleted=paths)
        if k:
            state.entries[state.ctx.ncx_path] = new_data
            n += k
    if state.ctx.nav_path and state.ctx.nav_path in state.entries:
        new_data, k = _fix_nav_broken(state, known_deleted=paths)
        if k:
            state.entries[state.ctx.nav_path] = new_data
            n += k
    return n


# ── 探测器 / 修复器（findings 为 (kind, payload) 列表，kind 见模块 docstring）──

def _det_remove_artifacts(state):
    return [('file', n) for n in state.entries
            if _basename(n).lower() in _JUNK_NAMES]


def _rep_remove_artifacts(state, findings):
    n = 0
    for _kind, p in findings:
        if state.delete_entry(p):
            state.note('remove_artifacts', p)
            n += 1
    return n


def _det_remove_missing_manifest(state):
    return [('item', (iid, href)) for iid, href in state.editor.item_hrefs.items()
            if href and state.editor.path_of(iid) not in state.entries]


def _rep_remove_missing_manifest(state, findings):
    n = 0
    for _kind, (iid, href) in findings:
        if state.editor.remove_item(iid):
            state.note('remove_missing_manifest', '%s -> %s' % (iid, href))
            n += 1
    return n


def _unmanifested_candidates(state):
    manifested = set(state.editor.item_paths.values())
    opf_path = state.ctx.opf_path
    out = []
    for name in state.entries:
        if name == 'mimetype' or name == opf_path:
            continue
        if name.startswith('META-INF/') or name.startswith('__MACOSX/'):
            continue
        if _basename(name).lower() in _JUNK_NAMES:
            continue
        if name in manifested:
            continue
        out.append(name)
    return sorted(out)


def _det_add_unmanifested(state):
    return [('file', n) for n in _unmanifested_candidates(state)]


def _rep_add_unmanifested(state, findings):
    n = 0
    for _kind, p in findings:
        mt = _media_type_for(p, state.entries[p])
        if mt == 'application/octet-stream':
            # EPUB3 下非核心媒体类型无 fallback 过不了 epubcheck：未知类型不登记
            state.warnings.append(
                '未登记文件 %s 扩展名未知，未登记（EPUB3 要求已知媒体类型）' % p)
            state.note('add_unmanifested', '%s（未知类型，跳过）' % p)
            continue
        rel = posixpath.relpath(p, state.ctx.opf_dir) if state.ctx.opf_dir else p
        state.editor.add_item(quote(rel, safe='/'), mt)
        state.note('add_unmanifested', p)
        n += 1
    return n


def _det_remove_unmanifested(state):
    out = []
    for p in _unmanifested_candidates(state):
        out.append(('file', p))
    if not out:
        return out
    # 互链感知：被幸存内容文档 <a href> 引用的散件跳过删除（否则静默断链）
    linked = _ahref_linked_targets(state, exclude=set())
    kept = []
    for kind, p in out:
        if p in linked:
            state.note('remove_unmanifested', '被正文互链引用，跳过删除：%s' % p)
            state.warnings.append(
                '未登记文件 %s 被正文互链引用，已跳过删除' % p)
            continue
        kept.append((kind, p))
    return kept


def _rep_remove_unmanifested(state, findings):
    n = 0
    for _kind, p in findings:
        if state.delete_entry(p):
            state.note('remove_unmanifested', p)
            n += 1
    return n


_RE_SCRIPT_BLOCK = re.compile(
    r'<script\b[^>]*>.*?</script\s*>|<script\b[^>]*/>',
    re.IGNORECASE | re.DOTALL)


def _doc_head(state, path: str) -> str:
    """嗅探用头部解码（64KB 足够覆盖 head 区；截断处多字节字符被 ignore 丢弃，
    只用于正则存在性判断，不做内容改写）。"""
    return state.entries[path][:65536].decode('utf-8', errors='ignore')


def _det_remove_javascript(state):
    out = [('file', n) for n in state.entries if _ext(n) == 'js']
    for p in state.content_paths():
        if re.search(r'<script\b', _doc_head(state, p), re.IGNORECASE):
            out.append(('doc', p))
    return out


def _rep_remove_javascript(state, findings):
    n = 0
    for kind, p in findings:
        if kind == 'file':
            if state.delete_entry(p):
                state.note('remove_javascript', p)
                n += 1
        elif p in state.entries:
            new, k = _RE_SCRIPT_BLOCK.subn('', _decode(state.entries[p]))
            if k:
                state.entries[p] = new.encode('utf-8')
                state.note('remove_javascript', '%s（%d 处 script）' % (p, k))
                n += 1
    return n


_RE_ADEPT_META = re.compile(
    r'<meta\b[^>]*\bname\s*=\s*["\']adept[^"\']*["\'][^>]*/?>', re.IGNORECASE)


def _det_remove_drm_meta_tags(state):
    out = []
    if 'META-INF/rights.xml' in state.entries and not _drm_targets(state.entries):
        out.append(('file', 'META-INF/rights.xml'))
    if re.search(r'<meta\b[^>]*\bname\s*=\s*["\']adept[^"\']*["\']',
                 state.editor.text, re.IGNORECASE):
        out.append(('opf', 'OPF metadata adept meta'))
    for p in state.content_paths():
        if _RE_ADEPT_META.search(_doc_head(state, p)):
            out.append(('doc', p))
    return out


def _rep_remove_drm_meta_tags(state, findings):
    n = 0
    for kind, p in findings:
        if kind == 'file':
            if state.delete_entry(p):
                state.note('remove_drm_meta_tags', p)
                n += 1
        elif kind == 'opf':
            k = state.editor.remove_adept_meta()
            if k:
                state.note('remove_drm_meta_tags', 'OPF metadata adept meta ×%d' % k)
                n += 1
        elif p in state.entries:
            new, k = _RE_ADEPT_META.subn('', _decode(state.entries[p]))
            if k:
                state.entries[p] = new.encode('utf-8')
                state.note('remove_drm_meta_tags', '%s（%d 处 adept meta）' % (p, k))
                n += 1
    return n


_RE_GBS_ANCHOR = re.compile(
    r'<a\b[^>]*\bid\s*=\s*["\']GBS\.[^"\']*["\'][^>]*/>|'
    r'<a\b[^>]*\bid\s*=\s*["\']GBS\.[^"\']*["\'][^>]*>\s*</a\s*>', re.IGNORECASE)


def _det_remove_page_maps(state):
    out = []
    for iid in state.editor.ids_by_media(('application/oebps-page-map+xml',)):
        p = state.editor.path_of(iid)
        if p in state.entries:
            out.append(('file', p))
    out += [('file', n) for n in state.entries if _ext(n) == 'pagemap']
    if re.search(r'<spine\b[^>]*\spage-map\s*=', state.editor.text, re.IGNORECASE):
        out.append(('attr', 'page-map'))
    for p in state.content_paths():
        if _RE_GBS_ANCHOR.search(_doc_head(state, p)):
            out.append(('doc', p))
    return out


def _rep_remove_page_maps(state, findings):
    n = 0
    for kind, p in findings:
        if kind == 'file':
            if state.delete_entry(p):
                state.note('remove_page_maps', p)
                n += 1
        elif kind == 'attr':
            if state.editor.remove_spine_attr(p):
                state.note('remove_page_maps', 'spine@%s 属性' % p)
                n += 1
        elif p in state.entries:
            new, k = _RE_GBS_ANCHOR.subn('', _decode(state.entries[p]))
            if k:
                state.entries[p] = new.encode('utf-8')
                state.note('remove_page_maps', '%s（%d 处 GBS 锚点）' % (p, k))
                n += 1
    return n


_RE_LINK_XPGT = re.compile(
    r'<link\b[^>]*\bhref\s*=\s*["\'][^"\']*\.xpgt["\'][^>]*/?>', re.IGNORECASE)
_RE_IMPORT_XPGT = re.compile(
    r'@import\s+(?:url\s*\(\s*)?["\']?[^"\')\s;]*\.xpgt["\']?\s*\)?\s*;?',
    re.IGNORECASE)


def _det_remove_xpgt(state):
    out = [('file', n) for n in state.entries if _ext(n) == 'xpgt']
    for p in state.content_paths() + state.css_paths():
        head = _doc_head(state, p)
        if _RE_LINK_XPGT.search(head) or _RE_IMPORT_XPGT.search(head):
            out.append(('doc', p))
    return out


def _rep_remove_xpgt(state, findings):
    n = 0
    for kind, p in findings:
        if kind == 'file':
            if state.delete_entry(p):
                state.note('remove_xpgt', p)
                n += 1
        elif p in state.entries:
            text = _decode(state.entries[p])
            new, k1 = _RE_LINK_XPGT.subn('', text)
            new, k2 = _RE_IMPORT_XPGT.subn('', new)
            if k1 + k2:
                state.entries[p] = new.encode('utf-8')
                state.note('remove_xpgt', '%s（%d 处引用）' % (p, k1 + k2))
                n += 1
    return n


_KOBO_COMMENT = re.compile(r'<!--\s*kobo.*?-->', re.IGNORECASE | re.DOTALL)
_KOBO_LINK = re.compile(r'<link\b[^>]*kobo\.css[^>]*/?>', re.IGNORECASE)
_KOBO_SCRIPT = re.compile(
    r'<script\b[^>]*kobo\.js[^>]*>\s*</script\s*>', re.IGNORECASE)
_KOBO_SPAN = re.compile(
    r'<span\b[^>]*\bid\s*=\s*["\']kobo\.[^"\']*["\'][^>]*>'
    r'((?:(?!<span\b)[\s\S])*?)</span\s*>', re.IGNORECASE)
_KOBO_REF = re.compile(r'kobo\.(?:js|css)', re.IGNORECASE)


def _kobo_marked(state) -> bool:
    """仅当书里确有 kobo 痕迹才启用（避免把含 kobo 字样的正常内容误伤）。"""
    for p in state.content_paths() + state.css_paths():
        head = _doc_head(state, p)
        if _KOBO_COMMENT.search(head) or _KOBO_SPAN.search(head) \
                or _KOBO_REF.search(head):
            return True
    return False


def _det_strip_kobo(state):
    if not _kobo_marked(state):
        return []
    out = [('file', n) for n in state.entries
           if _basename(n).lower() in ('kobo.js', 'kobo.css') or n == 'rights.xml']
    for p in state.content_paths():
        head = _doc_head(state, p)
        if _KOBO_COMMENT.search(head) or _KOBO_SPAN.search(head) \
                or _KOBO_LINK.search(head) or _KOBO_SCRIPT.search(head):
            out.append(('doc', p))
    return out


def _rep_strip_kobo(state, findings):
    if not _kobo_marked(state):
        return 0
    n = 0
    for kind, p in findings:
        if kind == 'file':
            if state.delete_entry(p):
                state.note('strip_kobo', p)
                n += 1
        elif p in state.entries:
            text = _decode(state.entries[p])
            new, k1 = _KOBO_COMMENT.subn('', text)
            new, k2 = _KOBO_LINK.subn('', new)
            new, k3 = _KOBO_SCRIPT.subn('', new)
            k4 = 0
            while True:
                # 只解包不含嵌套 span 的 kobo 包裹（嵌套结构正则不可靠，保守跳过）
                new, k = _KOBO_SPAN.subn(r'\1', new)
                k4 += k
                if not k:
                    break
            if k1 + k2 + k3 + k4:
                state.entries[p] = new.encode('utf-8')
                state.note('strip_kobo', '%s（%d 处痕迹）' % (p, k1 + k2 + k3 + k4))
                n += 1
    return n


def _det_remove_unused_images(state):
    scan_paths = state.content_paths() + state.css_paths() + state.svg_paths()
    referenced = set()
    for p in scan_paths:
        referenced |= _scan_doc_refs(state, p)
    # <a href> 互链引用的文件同样是"被引用"（点开大图反模式
    # <a href="fig.jpg"><img src="thumb.jpg"/></a>：img src 只见 thumb，
    # 漏判 fig 会被误删、随后守门把整本拦下）
    for p in state.content_paths() + state.svg_paths():
        referenced |= _scan_doc_ahrefs(state, p)
    # CSS url() 保守匹配：basename 相同即视为引用（宁可少删）
    base_names = _css_url_basenames(state, state.css_paths())
    cover_paths = state.editor.cover_item_paths()
    out = []
    for iid, p in state.image_items():
        if p not in state.entries:
            continue
        if p in referenced or p in cover_paths:
            continue
        if _basename(p).lower() in base_names:
            continue
        out.append(('pair', (iid, p)))
    return out


def _rep_remove_unused_images(state, findings):
    n = 0
    for _kind, (_iid, p) in findings:
        if state.delete_entry(p):
            state.note('remove_unused_images', p)
            n += 1
    return n


_RE_BODY = re.compile(r'<body\b[^>]*>(.*)</body\s*>', re.IGNORECASE | re.DOTALL)
_TAG_STRIP = re.compile(r'<[^>]+>')
_ENTITY_STRIP = re.compile(r'&[a-z#0-9]+;', re.IGNORECASE)


def _body_text(state, path: str) -> str:
    text = _decode(state.entries[path])
    m = _RE_BODY.search(text)
    seg = m.group(1) if m else text
    seg = _TAG_STRIP.sub(' ', seg)
    seg = _ENTITY_STRIP.sub(' ', seg)
    return seg.strip()


def _det_remove_broken_cover_pages(state):
    candidates = []
    for p in state.content_paths():
        if p in (state.ctx.ncx_path, state.ctx.nav_path, state.ctx.opf_path):
            continue
        img_refs = {r for r in _scan_doc_refs(state, p) if _is_image_path(r)}
        if not img_refs:
            continue
        if any(r in state.entries for r in img_refs):
            continue
        if _body_text(state, p):
            continue
        candidates.append(p)
    if not candidates:
        return []
    # 互链感知：被幸存内容文档 <a href> 引用的候选页跳过删除（否则静默断链）
    linked = _ahref_linked_targets(state, exclude=set(candidates))
    out = []
    for p in candidates:
        if p in linked:
            state.note('remove_broken_cover_pages', '被正文互链引用，跳过删除：%s' % p)
            continue
        out.append(('doc', p))
    return out


def _rep_remove_broken_cover_pages(state, findings):
    n = 0
    deleted = set()
    for _kind, p in findings:
        if state.delete_entry(p):
            state.note('remove_broken_cover_pages', p)
            deleted.add(p)
            n += 1
    if deleted and 'fix_broken_toc' not in state.ops:
        k = _toc_remove_targets(state, deleted)
        if k:
            state.note('remove_broken_cover_pages', '目录级联清理 %d 条' % k)
            n += k
    return n


def _det_fix_broken_toc(state):
    out = [('item', src) for src, _t in _ncx_broken_srcs(state)]
    out += [('item', href) for href, _t in _nav_broken_hrefs(state)]
    return out


def _rep_fix_broken_toc(state, findings):
    n = 0
    if state.ctx.ncx_path and state.ctx.ncx_path in state.entries:
        new_data, k = _fix_ncx_broken(state)
        if k:
            state.entries[state.ctx.ncx_path] = new_data
            state.note('fix_broken_toc', 'NCX 断链条目 %d 个' % k)
            n += k
    if state.ctx.nav_path and state.ctx.nav_path in state.entries:
        new_data, k = _fix_nav_broken(state)
        if k:
            state.entries[state.ctx.nav_path] = new_data
            state.note('fix_broken_toc', 'nav 断链条目 %d 个' % k)
            n += k
    return n


_UTF8_TARGET_EXTS = {'.xhtml', '.html', '.htm', '.css', '.ncx', '.svg', '.opf'}
_RE_META_CHARSET = re.compile(
    r'[ \t]*<meta[^>]+charset[^>]*>[ \t]*\n?', re.IGNORECASE)


def _utf8_targets(state) -> list:
    targets = set()
    for p in state.editor.item_paths.values():
        if p in state.entries and ('.' + _ext(p)) in _UTF8_TARGET_EXTS:
            targets.add(p)
    for p in (state.ctx.ncx_path, state.ctx.nav_path):
        if p and p in state.entries:
            targets.add(p)
    return sorted(targets)


def _is_utf8(data: bytes) -> bool:
    try:
        data.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False


def _det_encode_utf8(state):
    return [('doc', p) for p in _utf8_targets(state)
            if not _is_utf8(state.entries[p])]


def _rep_encode_utf8(state, findings):
    n = 0
    for _kind, p in findings:
        text = _decode(state.entries[p])
        if _ext(p) in ('xhtml', 'html', 'htm'):
            text = _RE_META_CHARSET.sub('', text, count=2)
        state.entries[p] = text.encode('utf-8')
        state.note('encode_utf8', p)
        n += 1
    return n


_DETECT = {
    'remove_artifacts': _det_remove_artifacts,
    'remove_missing_manifest': _det_remove_missing_manifest,
    'add_unmanifested': _det_add_unmanifested,
    'remove_unmanifested': _det_remove_unmanifested,
    'remove_javascript': _det_remove_javascript,
    'remove_drm_meta_tags': _det_remove_drm_meta_tags,
    'remove_page_maps': _det_remove_page_maps,
    'remove_xpgt': _det_remove_xpgt,
    'strip_kobo': _det_strip_kobo,
    'remove_unused_images': _det_remove_unused_images,
    'remove_broken_cover_pages': _det_remove_broken_cover_pages,
    'fix_broken_toc': _det_fix_broken_toc,
    'encode_utf8': _det_encode_utf8,
}

_REPAIR = {
    'remove_artifacts': _rep_remove_artifacts,
    'remove_missing_manifest': _rep_remove_missing_manifest,
    'add_unmanifested': _rep_add_unmanifested,
    'remove_unmanifested': _rep_remove_unmanifested,
    'remove_javascript': _rep_remove_javascript,
    'remove_drm_meta_tags': _rep_remove_drm_meta_tags,
    'remove_page_maps': _rep_remove_page_maps,
    'remove_xpgt': _rep_remove_xpgt,
    'strip_kobo': _rep_strip_kobo,
    'remove_unused_images': _rep_remove_unused_images,
    'remove_broken_cover_pages': _rep_remove_broken_cover_pages,
    'fix_broken_toc': _rep_fix_broken_toc,
    'encode_utf8': _rep_encode_utf8,
}


# ── 最终守门 ──────────────────────────────────────────────────────────────────

def _final_gate(state: _State) -> None:
    """写出前自检：**本精修引入**的引用断裂一律拒绝出包。

    全部按增量口径校验（以 ``deleted_paths`` 为准）：书自带的旧断裂
    （断清单/断 spine/断 guide/断链目录）不是精修的职责——那正是
    remove_missing_manifest / fix_broken_toc 的活，用户没勾就不动也不拦。
    """
    editor = state.editor
    for dp in state.deleted_paths:
        if editor.ids_for_path(dp):
            raise EpubRepairError('精修后 manifest 残留已删文件条目：%s' % dp)
    for idref in editor.spine_idrefs:
        if idref not in editor.item_hrefs and idref in state.pre_item_ids:
            raise EpubRepairError('精修后 spine 引用不明：%s' % idref)
    for tag, target in editor._guide_refs():
        if target in state.deleted_paths:
            raise EpubRepairError('精修后 guide 引用指向已删文件：%s' % tag[:80])
    for p in state.content_paths():
        for ref in _scan_doc_refs(state, p):
            if ref in state.deleted_paths:
                raise EpubRepairError(
                    '精修后内容引用指向已删文件：%s -> %s' % (p, ref))
        # 正文 <a href> 互链也在守门覆盖内（删除类操作已在探测阶段对被
        # 互链引用的目标跳过删除，此检查是防回归的最后一道网）
        for ref in _scan_doc_ahrefs(state, p):
            if ref in state.deleted_paths:
                raise EpubRepairError(
                    '精修后正文互链指向已删文件：%s -> %s' % (p, ref))
    for css in state.css_paths():
        for name in _css_url_basenames(state, [css]):
            for dp in state.deleted_paths:
                if _basename(dp).lower() == name:
                    raise EpubRepairError(
                        '精修后 CSS 引用指向已删文件：%s -> %s' % (css, dp))
    for _src, target in _ncx_broken_srcs(state):
        if target in state.deleted_paths:
            raise EpubRepairError('精修后 NCX 引用指向已删文件')
    for _href, target in _nav_broken_hrefs(state):
        if target in state.deleted_paths:
            raise EpubRepairError('精修后 nav 引用指向已删文件')


# ── 对外入口 ──────────────────────────────────────────────────────────────────

def _load_entries(path: str) -> dict:
    """``_read_zip_entries`` 的包装：损坏 zip 统一转为 :class:`EpubRepairError`。"""
    try:
        return _read_zip_entries(path)
    except RuntimeError as err:
        raise EpubRepairError(str(err)) from err


def analyze_epub(epub_path: str, ops: list = None) -> dict:
    """只读分析单本 EPUB 的结构问题。

    :return: ``{"drm": bool, "findings": {op_key: {"count": n, "samples": [...]}}}``
    :raises EpubDrmError: 不会——加密书以 ``drm=True`` 返回（findings 为空）。
    :raises EpubRepairError: zip/OPF 无法解析时。
    """
    ops = normalize_ops(ops) if ops is not None else list(OP_KEYS)
    entries = _load_entries(epub_path)
    drm = bool(_drm_targets(entries))
    findings = {}
    if not drm:
        state = _State(entries, ops)
        for key in ops:
            found = _DETECT[key](state)
            findings[key] = {
                'count': len(found),
                'samples': [str(payload) if payload is not None else kind
                            for kind, payload in found[:10]],
            }
    return {'drm': drm, 'findings': findings}


def repair_epub(epub_path: str, out_path: str, ops: list = None,
                progress_cb=None) -> dict:
    """执行精修并写出新 EPUB（不改动源文件）。

    :param ops: 勾选项（None 用默认集）。
    :param progress_cb: ``cb(pct:int, stage:str)``，stage 为 op key。
    :return: ``{"ops": {op_key: applied_count}, "warnings": []}``
    :raises EpubDrmError: 全书加密。
    :raises EpubRepairError: zip/OPF 损坏、manifest 为空或守门不过（此时
        ``out_path`` 不会被写入）。
    """
    ops = normalize_ops(ops)
    entries = _load_entries(epub_path)
    _require_not_drm(entries)
    state = _State(entries, ops)
    counts = {k: 0 for k in OP_KEYS}

    def _cb(pct, stage):
        if progress_cb:
            try:
                progress_cb(pct, stage)
            except Exception:
                pass

    total = max(len(ops), 1)
    for i, key in enumerate(ops):
        findings = _DETECT[key](state)
        applied = _REPAIR[key](state, findings)
        counts[key] = applied
        _cb(5 + int(90 * (i + 1) / total), key)

    entries[state.ctx.opf_path] = state.editor.text.encode('utf-8')
    _final_gate(state)
    _cb(96, 'gate')
    _write_zip(entries, out_path)
    _cb(99, 'write')
    return {'ops': counts, 'warnings': state.warnings}
