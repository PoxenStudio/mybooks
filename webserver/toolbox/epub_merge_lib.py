# -*- coding: utf-8 -*-
"""EPUB 内容合并引擎（N→1，纯函数库，无 webserver/calibre 依赖，方便单测）。

设计对标站内既有实现（行号均为本地 `fix/epub-beautify-p0-css` 分支行号，
其中 beautify 相关为领先 `origin/develop` 的修复版）：

- 读取：`text_replace.py:373-407` 的全量/按需双模式 +
  本地 `utils/epub_beautify_lib.py:149-190` 的加固版
  （穿越拦截 / declared+actual 双累计 ZipBomb / 分块流式读）；
- 定位：`text_replace.py:441-487` 的 manifest 定位五件套
  （去 fragment/query、前导 `/`、OPF 基址、`../` 归一化、`lower_map`
  大小写不敏感）；
- 解码：utf-8 优先，非 utf-8 时先用站内 `utils/encoding_detect.decode_with_report`
  打分择优（text_replace/beautify 同款，防 Big5 被 gb18030 静默错译），
  检测器不可用时回退 gb18030/big5 试解；
- 写包：mimetype 首项 STORED + 原子写语义 + `create_system=0`；
- 内存：合并全程流式（`_ZipSource` 按需读单条目、`_ZipWriter` 边合并边写、
  路径入参 + `out_path` 落盘），峰值与源书总数/输出大小无关。

实现范围：读取（流式 / 全量 / lite 元数据）/ 定位 / 解码 / 分析 / ISBN /
简介组合 / `merge_epubs` 拼接主体 / `validate_output` 输出守门。
"""

import codecs
import html
import io
import logging
import os
import posixpath
import re
import uuid
import zipfile
from urllib.parse import quote, unquote

logger = logging.getLogger(__name__)

# ZipBomb 阈值：单次读取解压总量上限 1GB；条目数上限 5000。
# 说明：不设单本上限（50MB+ 的合集/画集很常见，且本工具仅管理员可用、
# 输入均为自有书库书籍，威胁模型弱）；分块流式累计照常拦截伪造头炸弹。
_ZIP_MAX_TOTAL = 1024 * 1024 * 1024
_ZIP_MAX_ENTRIES = 5000

# 正文条目 media-type 白名单（抄 text_replace.py:35）
_TEXT_MEDIA_TYPES = ("application/xhtml+xml", "text/html")
_NCX_MEDIA_TYPE = "application/x-dtbncx+xml"

# BOM → 编码（UTF-32 必须排在 UTF-16 前：UTF-32-LE 的 BOM 以 UTF-16-LE 的 BOM 开头）
_BOM_ENCODINGS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

_ITEM_RE = re.compile(r"<item\b[^>]*?>", re.IGNORECASE)
_ITEM_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_ITEM_MT_RE = re.compile(r"""media-type\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_ITEM_ID_RE = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_SPINE_RE = re.compile(r"<spine\b[^>]*>(.*?)</spine>", re.IGNORECASE | re.DOTALL)
_ITEMREF_RE = re.compile(r"""<itemref\b[^>]*?idref\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_NAVPOINT_RE = re.compile(r"<navpoint\b", re.IGNORECASE)
# href 输出编码：zip 名里的 `#`/空格/非 ASCII 直接写进 OPF/NCX 会变成非法 URI
# （`#` 会被当成 fragment，`b0/a#b.xhtml` 会被解析成文件 `b0/a` + 片段，正文
# 文档直接加载不出来）。读取侧 `_normalize_zip_path` 一律 unquote，故
# quote 后 round-trip 无损（`c%20d.xhtml` → `c%2520d.xhtml` → unquote 还原）。
_HREF_SAFE = "/~@$+,-.;=[]!_'"


def _quote_href(name: str) -> str:
    """把 zip 条目名编码为合法 URI 路径（fragment/query/空格/非 ASCII 转义）。"""
    return quote(name or "", safe=_HREF_SAFE)


def _quote_toc_src(path: str, frag) -> str:
    """编码 (路径, fragment) 二元组（路径里的 `#` 会被转义，不与分隔符混淆）。"""
    if frag:
        return "%s#%s" % (_quote_href(path), quote(frag, safe=""))
    return _quote_href(path)


def _normalize_zip_path(href: str, base_dir: str = "") -> str:
    """归一化 OPF 中引用的 href 为 zip 条目名（抄 text_replace 定位逻辑 + 越界拒绝）。

    先按原文切掉 fragment/query、再 unquote（否则文件名里的 `%23` 会被
    误当 fragment 截断）→ 去前导 `/` → 相对 OPF 基址拼接 → 去 `./`、
    解析 `../` → `\\` 转 `/`。`../` 越过根目录时返回 ""（调用方跳过，
    text_replace 版是静默 pop，本库按危险引用拒绝）。
    """
    href = unquote(href.split("#", 1)[0].split("?", 1)[0])
    if href.startswith("/"):
        href = href.lstrip("/")
    elif base_dir:
        href = "%s/%s" % (base_dir, href)
    parts = []
    for seg in href.replace("\\", "/").split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not parts:
                return ""
            parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts)


def _is_traversal(name: str) -> bool:
    """zip 条目路径穿越检查（抄本地加固版 :164）。"""
    return name.startswith("/") or ".." in name.split("/")


def _read_zip_entries(source, max_total=_ZIP_MAX_TOTAL,
                      max_entries=_ZIP_MAX_ENTRIES) -> dict:
    """读取 zip 全部文件条目 {name: bytes}（跳过目录项，校验路径与大小）。

    :param source: EPUB 字节（bytes）或文件路径（str）。
    :raises ValueError: 非 zip / 条目穿越全跳后无可用条目不算错；
        超限（单本/总量/条目数）与损坏抛 ValueError。
    """
    if isinstance(source, (bytes, bytearray)):
        opener = lambda: zipfile.ZipFile(io.BytesIO(bytes(source)), "r")  # noqa: E731
    else:
        opener = lambda: zipfile.ZipFile(source, "r")  # noqa: E731

    entries = {}
    try:
        with opener() as zf:
            declared = 0
            actual = 0
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if _is_traversal(info.filename):
                    logging.warning("[epub_merge] Skip traversal entry: %s", info.filename)
                    continue
                declared += info.file_size
                if declared > max_total or len(entries) >= max_entries:
                    raise ValueError("EPUB 文件过大或条目过多，疑似 Zip Bomb")
                # 分块流式读：伪造中央目录尺寸的大解压流在此截停
                buf = bytearray()
                with zf.open(info.filename) as fh:
                    while True:
                        chunk = fh.read(1 << 20)
                        if not chunk:
                            break
                        buf += chunk
                        if len(buf) > max_total:
                            raise ValueError("EPUB 解压后体积异常，疑似 Zip Bomb")
                data = bytes(buf)
                actual += len(data)
                if actual > max_total:
                    raise ValueError("EPUB 解压后体积异常，疑似 Zip Bomb")
                entries[info.filename] = data
    except zipfile.BadZipFile as err:
        raise ValueError("EPUB 解析失败，文件可能已损坏：%s" % err) from err
    except zipfile.LargeZipFile as err:
        raise ValueError("EPUB 文件过大：%s" % err) from err
    return entries


class _ZipSource:
    """按需读取源 EPUB 条目（流式，峰值内存 = 单个条目，不随整本/多本增长）。

    与 `_read_zip_entries` 的关系：后者一次性把整本解压成 dict（analyze /
    封面提取用，单本场景）；本类只预读中央目录做 ZipBomb 与条目数预检，
    正文条目在用到时逐块读取，供 `merge_epubs` 逐本流式处理。
    支持字节（bytes）与文件路径（str/PathLike）两种输入。
    """

    def __init__(self, source, max_total=_ZIP_MAX_TOTAL,
                 max_entries=_ZIP_MAX_ENTRIES):
        self._max_total = max_total
        try:
            if isinstance(source, (bytes, bytearray)):
                self._zf = zipfile.ZipFile(io.BytesIO(bytes(source)), "r")
            else:
                self._zf = zipfile.ZipFile(source, "r")
        except zipfile.BadZipFile as err:
            raise ValueError("EPUB 解析失败，文件可能已损坏：%s" % err) from err
        except zipfile.LargeZipFile as err:
            raise ValueError("EPUB 文件过大：%s" % err) from err
        infos = [i for i in self._zf.infolist()
                 if not i.is_dir() and not _is_traversal(i.filename)]
        if len(infos) > max_entries or sum(
                i.file_size for i in infos) > max_total:
            self._zf.close()
            raise ValueError("EPUB 文件过大或条目过多，疑似 Zip Bomb")
        # 同名条目只保留一个（dict 语义，读取时 zipfile 返回最后一条，与
        # `_read_zip_entries` 的 dict 覆盖行为一致）
        self._names = list(dict.fromkeys(i.filename for i in infos))
        self._nameset = set(self._names)
        self._lower = {n.lower(): n for n in self._names}
        self._counted = set()
        self._actual = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        try:
            self._zf.close()
        except Exception:
            pass

    def __contains__(self, name):
        return name in self._nameset

    def __iter__(self):
        return iter(self._names)

    def keys(self):
        return list(self._names)

    def lower_map(self) -> dict:
        """{小写条目名: 真实条目名}（大小写不敏感定位）。"""
        return dict(self._lower)

    def get(self, name, default=None):
        return self.read(name) if name in self._nameset else default

    def __getitem__(self, name):
        return self.read(name)

    def read(self, name: str) -> bytes:
        """逐块读取单条目（分块累计拦截伪造中央目录尺寸的 ZipBomb）。"""
        return b"".join(self.iter_chunks(name))

    def iter_chunks(self, name: str, chunk_size: int = 1 << 20):
        """按块产出单条目字节（大资源直接转写目标包时用，不过内存）。"""
        if name not in self._nameset:
            raise KeyError(name)
        total = 0
        with self._zf.open(name) as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > self._max_total:
                    raise ValueError("EPUB 解压后体积异常，疑似 Zip Bomb")
                yield chunk
        if name not in self._counted:
            self._counted.add(name)
            self._actual += total
            if self._actual > self._max_total:
                raise ValueError("EPUB 解压后体积异常，疑似 ZipBomb")


class _ZipWriter:
    """把条目流式写入目标 EPUB（mimetype 首项 STORED，其余 DEFLATED）。"""

    def __init__(self, out):
        self._zf = zipfile.ZipFile(out, "w")
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        info.create_system = 0
        self._zf.writestr(info, b"application/epub+zip")
        self._names = {"mimetype"}

    def write(self, name: str, data: bytes) -> None:
        if name in self._names:
            return
        info = zipfile.ZipInfo(name)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 0
        self._zf.writestr(info, data)
        self._names.add(name)

    def write_stream(self, name: str, chunks) -> None:
        """逐块转写条目（大图/字体等无需改写的资源不过内存）。"""
        if name in self._names:
            return
        info = zipfile.ZipInfo(name)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 0
        with self._zf.open(info, "w") as dst:
            for chunk in chunks:
                dst.write(chunk)
        self._names.add(name)

    def close(self):
        self._zf.close()


def _opf_path_from_container(container_text: str):
    """从 container.xml 提取 OPF 路径（正则兜底，坏 XML 也能定位）。"""
    m = re.search(r"""full-path\s*=\s*["']([^"']+)["']""", container_text, re.IGNORECASE)
    return m.group(1) if m else None


def _manifest_items(opf_text: str, opf_path: str) -> dict:
    """解析 OPF manifest 为 {id: (zip条目名, media-type)}（命名空间无关的正则版）。"""
    base_dir = opf_path.rsplit("/", 1)[0] if "/" in opf_path else ""
    items = {}
    for tag in _ITEM_RE.findall(opf_text):
        mt = _ITEM_MT_RE.search(tag)
        href = _ITEM_HREF_RE.search(tag)
        iid = _ITEM_ID_RE.search(tag)
        if not mt or not href or not iid:
            continue
        name = _normalize_zip_path(href.group(1), base_dir)
        if not name:
            continue
        items[iid.group(1)] = (name, mt.group(1).lower())
    return items


def _find_spine_entries(entries: dict) -> list:
    """按 container → OPF → spine 顺序定位正文条目名（大小写不敏感）。

    spine 缺失/为空时降级为 manifest 文本条目顺序；container/OPF 缺失返回 []。
    """
    container = entries.get("META-INF/container.xml")
    if not container:
        return []
    opf_path = _opf_path_from_container(container.decode("utf-8", errors="replace"))
    if not opf_path or opf_path not in entries:
        return []
    opf_text = _decode(entries[opf_path])
    items = _manifest_items(opf_text, opf_path)
    lower_map = {k.lower(): k for k in entries}

    ordered = []
    m = _SPINE_RE.search(opf_text)
    if m:
        for idref in _ITEMREF_RE.findall(m.group(1)):
            if idref in items:
                name, _mt = items[idref]
                real = lower_map.get(name.lower())
                if real and real not in ordered:
                    ordered.append(real)
    if ordered:
        return ordered
    # 降级：manifest 文本条目顺序
    for _iid, (name, mt) in items.items():
        if mt in _TEXT_MEDIA_TYPES:
            real = lower_map.get(name.lower())
            if real and real not in ordered:
                ordered.append(real)
    return ordered


# preview 轻量模式：container / OPF / NCX 属元数据小条目，超限视为异常
_META_ENTRY_MAX = 8 * 1024 * 1024


def _read_meta_entries(source) -> tuple:
    """仅读取 container / OPF / NCX 条目（preview 轻量路径，不解压正文与图片）。

    总量按中央目录 declared size 预检（不解压即可拦截 Zip Bomb），其余条目
    只取名字。正文全量校验留给 merge 阶段的 `_read_zip_entries`。

    :return: ({元数据条目名: 内容}, {全部条目名: b"" 占位})。
    :raises ValueError: 非 zip / 超限 / 元数据条目超限。
    """
    if isinstance(source, (bytes, bytearray)):
        opener = lambda: zipfile.ZipFile(io.BytesIO(bytes(source)), "r")  # noqa: E731
    else:
        opener = lambda: zipfile.ZipFile(source, "r")  # noqa: E731
    meta = {}
    try:
        with opener() as zf:
            infos = [i for i in zf.infolist()
                     if not i.is_dir() and not _is_traversal(i.filename)]
            declared = sum(i.file_size for i in infos)
            if declared > _ZIP_MAX_TOTAL or len(infos) > _ZIP_MAX_ENTRIES:
                raise ValueError("EPUB 文件过大或条目过多，疑似 Zip Bomb")
            names_view = {i.filename: b"" for i in infos}
            lower_names = {n.lower(): n for n in names_view}
            size_by_name = {i.filename: i.file_size for i in infos}

            def _read_small(name: str) -> bytes:
                size = size_by_name.get(name, 0)
                if size > _META_ENTRY_MAX:
                    raise ValueError("EPUB 元数据条目过大：%s" % name)
                # 按「声明上限 + 1」读取，不能用 zf.read()：后者无参走
                # `_read1(MAX_N=2**31-1)`，一次性 decompress 整条压缩流，
                # 伪造中央目录（声明小、实际巨大）能绕过上面的声明检查把
                # 内存打满（实测 200MB 伪造包峰值 458MB）；带 max_length 的
                # read(n) 每块产出受 n 与声明大小双重约束。
                with zf.open(name) as fh:
                    data = fh.read(_META_ENTRY_MAX + 1)
                    if len(data) > _META_ENTRY_MAX or fh.read(1):
                        raise ValueError("EPUB 元数据条目过大：%s" % name)
                return data

            container_name = "META-INF/container.xml"
            if container_name in names_view:
                meta[container_name] = _read_small(container_name)
                opf_path = _opf_path_from_container(
                    meta[container_name].decode("utf-8", errors="replace"))
                if opf_path and opf_path in names_view:
                    meta[opf_path] = _read_small(opf_path)
                    for _iid, (name, mt) in _manifest_items(
                            _decode(meta[opf_path]), opf_path).items():
                        if mt != _NCX_MEDIA_TYPE:
                            continue
                        real = lower_names.get(name.lower())
                        if real and real not in meta:
                            meta[real] = _read_small(real)
    except zipfile.BadZipFile as err:
        raise ValueError("EPUB 解析失败，文件可能已损坏：%s" % err) from err
    except zipfile.LargeZipFile as err:
        raise ValueError("EPUB 文件过大：%s" % err) from err
    return meta, names_view


def _detector_decode(data: bytes):
    """用站内编码检测器解码（text_replace/beautify 同款 `decode_with_report`）。

    只采纳结论为 GB/Big5 系且判干净的结果：实测检测器偶把纯 GB 长文本
    判为 euc_kr（干净高置信），合并是静默后台写盘，无用户确认环节，
    照单全收会把简体章节永久写成韩文乱码；GB/Big5 二选一正是本次要
    解决的（gb18030 从不抛错，Big5 会被静默错译），其余结论回退试解，
    行为与过去一致，不引入新风险。

    检测器按包路径惰性引入：生产环境走 `webserver.toolbox...` 全路径，
    standalone 单测走 `utils...` 短路径；均不可用（或不采纳/判垃圾）时
    返回 None，调用方回退逐编码试解。任何异常一律吞掉，不阻断合并。
    """
    for name in ("webserver.toolbox.utils.encoding_detect",
                 "utils.encoding_detect"):
        try:
            mod = __import__(name, fromlist=["decode_with_report"])
            text, report = mod.decode_with_report(data)
            if report.get("garbage") or report.get("unrecoverable"):
                return None
            enc = str(report.get("encoding") or "").lower().replace("_", "-")
            if enc in ("gb18030", "gbk", "gb2312", "big5", "big5-hkscs"):
                return text
            logger.debug("[epub_merge] detector pick ignored: %s", enc)
            return None
        except Exception:
            continue
    return None


def _decode(data: bytes) -> str:
    """解码文本条目：BOM（UTF-16/32）→ utf-8 → 站内检测器（仅采纳 GB/Big5 系
    干净结论，防 Big5 被 gb18030 静默错译）→ gb18030/big5 逐个试解 → replace。

    说明：gb18030 几乎从不抛错，Big5 字节会被它静默错译（如台版书），
    故非 utf-8 时优先走检测器打分；检测器不可用/判垃圾时才回退试解。
    UTF-16/32 文档同样会被 gb18030 静默错译（每字符夹 NUL 字节），先按 BOM
    或 `<` 的宽字符形态识别，避免整章乱码。
    """
    for bom, enc in _BOM_ENCODINGS:
        if data.startswith(bom):
            try:
                return data[len(bom):].decode(enc)
            except UnicodeDecodeError:
                break
    if data[:2] in (b"<\x00", b"\x00<"):
        # 无 BOM 的 UTF-16 文本（XML/HTML 以 `<` 开头）
        try:
            return data.decode("utf-16-le" if data[:1] == b"<" else "utf-16-be")
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    detected = _detector_decode(data)
    if detected is not None:
        return detected
    for enc in ("gb18030", "big5"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _parse_opf_meta(opf_text: str) -> dict:
    """提取 OPF 元数据（标题/作者/出版社/语言/标识符，命名空间无关）。"""
    def _all(pattern):
        return [html.unescape(m.strip()) for m in re.findall(pattern, opf_text, re.IGNORECASE | re.DOTALL)]

    titles = _all(r"<dc:title[^>]*>(.*?)</dc:title>")
    creators = []
    for m in re.finditer(
            r"""<dc:creator([^>]*)>(.*?)</dc:creator>""",
            opf_text, re.IGNORECASE | re.DOTALL):
        attrs, value = m.group(1), html.unescape(m.group(2).strip())
        if not value:
            continue
        r = re.search(r"""(?:opf:)?role\s*=\s*["']([^"']+)["']""", attrs, re.IGNORECASE)
        creators.append(((r.group(1).strip().lower() if r else ""), value))
    # role=aut（或无 role，缺省即作者）优先；插画等其他角色不混入作者
    aut = [name for role, name in creators if role in ("aut", "")]
    authors = aut if aut else [name for _role, name in creators]
    publishers = _all(r"<dc:publisher[^>]*>(.*?)</dc:publisher>")
    languages = _all(r"<dc:language[^>]*>(.*?)</dc:language>")
    identifiers = {}
    for m in re.finditer(
            r"""<dc:identifier([^>]*)>(.*?)</dc:identifier>""",
            opf_text, re.IGNORECASE | re.DOTALL):
        attrs, value = m.group(1), html.unescape(m.group(2).strip())
        s = re.search(r"""scheme\s*=\s*["']([^"']+)["']""", attrs, re.IGNORECASE)
        scheme = (s.group(1).strip().upper() if s else "NONE")
        if value:
            identifiers.setdefault(scheme, value)
    isbns = [v for k, v in identifiers.items() if k in ("ISBN", "ISBN13", "ISBN10")]
    return {
        "title": titles[0] if titles else "",
        "authors": authors,
        "publisher": publishers[0] if publishers else "",
        "languages": [lang for lang in languages if lang],
        "identifiers": identifiers,
        "isbns": isbns,
    }


def _count_ncx_entries(entries: dict) -> tuple:
    """统计 NCX 目录条数。返回 (count, found_ncx)。

    多个 NCX 并存时取最大值（合集输出只会带一个合并 NCX；源书残留 NCX
    已在 merge 时排除，此处取最大即为正解，单书行为不变）。
    """
    container = entries.get("META-INF/container.xml")
    if not container:
        return 0, False
    opf_path = _opf_path_from_container(container.decode("utf-8", errors="replace"))
    if not opf_path or opf_path not in entries:
        return 0, False
    items = _manifest_items(_decode(entries[opf_path]), opf_path)
    best = 0
    found = False
    for _iid, (name, mt) in items.items():
        if mt == _NCX_MEDIA_TYPE:
            real = {k.lower(): k for k in entries}.get(name.lower())
            if real:
                found = True
                count = len(_NAVPOINT_RE.findall(_decode(entries[real])))
                best = max(best, count)
    return best, found


def _analyze_from(opf_path: str, entries: dict, size: int) -> dict:
    """共享分析主体：entries 需含 container/OPF/NCX 真实内容，其余条目可 b"" 占位。"""
    meta = _parse_opf_meta(_decode(entries[opf_path]))
    spine = _find_spine_entries(entries)
    toc_count, found_ncx = _count_ncx_entries(entries)

    warnings = []
    if not found_ncx:
        warnings.append("无 NCX 目录，合并时改用 EPUB3 导航 / spine 顺序兜底")
    if not spine:
        warnings.append("未定位到正文条目")

    return {
        "title": meta["title"],
        "authors": meta["authors"],
        "publisher": meta["publisher"],
        "languages": meta["languages"],
        "identifiers": meta["identifiers"],
        "isbns": meta["isbns"],
        "spine_files": spine,
        "spine_count": len(spine),
        "toc_count": toc_count,
        "size": size,
        "warnings": warnings,
    }


def analyze_epub(data, lite: bool = False) -> dict:
    """返回单本 EPUB 的摘要，供 preview 用。

    :param data: EPUB 字节（bytes）或文件路径（str/PathLike，避免整本读进内存）。
    :param lite: True 时仅解压 container/OPF/NCX 元数据小条目（preview 用，
        避免在请求线程里全量解压大书）；False 全量读取并校验。
    :raises ValueError: 非法 zip / 缺 container.xml / 缺 OPF 时抛出。
    """
    if isinstance(data, (bytes, bytearray)):
        if not data:
            raise ValueError("EPUB 输入为空")
        size = len(data)
    elif isinstance(data, (str, os.PathLike)):
        try:
            size = os.path.getsize(data)
        except OSError as err:
            raise ValueError("EPUB 源文件不可读：%s" % err) from err
        if not size:
            raise ValueError("EPUB 输入为空")
    else:
        raise ValueError("EPUB 输入为空")
    if lite:
        meta_entries, names_view = _read_meta_entries(data)
        view = dict(names_view)
        view.update(meta_entries)
        return _analyze_from(_locate_opf(view), view, size)
    entries = _read_zip_entries(data)
    return _analyze_from(_locate_opf(entries), entries, size)


def extract_cover(source) -> tuple:
    """从 EPUB 内取封面。返回 (raw_bytes, ext) 或 (None, None)。

    :param source: EPUB 字节或文件路径。路径模式下只解压封面候选条目
        （`_ZipSource` 按需读），不会把整本书解压进内存。
    策略（按优先级）：manifest `properties` 含 cover-image → id 为 cover 系 →
    guide `type="cover"` → 首个图片条目。结构异常返回 (None, None) 而不抛。
    """
    try:
        with _ZipSource(source) as src:
            opf_path = _locate_opf(src)
            opf_text = _decode(src.read(opf_path))
            base = opf_path.rsplit("/", 1)[0] if "/" in opf_path else ""
            lower_map = src.lower_map()

            def _real(href):
                name = _normalize_zip_path(href, base)
                if not name:
                    return None
                return lower_map.get(name.lower())

            def _read_real(href):
                real = _real(href)
                return src.read(real) if real else None

            def _ext_of(href):
                return href.rsplit(".", 1)[-1].lower() if "." in href else ""

            tagged = []
            for tag in _ITEM_RE.findall(opf_text):
                mt = _ITEM_MT_RE.search(tag)
                href = _ITEM_HREF_RE.search(tag)
                iid = _ITEM_ID_RE.search(tag)
                if not mt or not href:
                    continue
                tagged.append((iid.group(1) if iid else "", href.group(1),
                               mt.group(1).lower(), tag))
            for _iid, href, _mt, tag in tagged:
                if "cover-image" in tag.lower():
                    raw = _read_real(href)
                    if raw:
                        return raw, _ext_of(href)
            for _iid, href, _mt, _tag in tagged:
                if _iid.lower() in ("cover", "cover-image", "cover-img"):
                    raw = _read_real(href)
                    if raw:
                        return raw, _ext_of(href)
            m = re.search(
                r"""<reference\b[^>]*type\s*=\s*["']cover["'][^>]*href\s*=\s*["']([^"']+)["']""",
                opf_text, re.IGNORECASE)
            if m:
                raw = _read_real(m.group(1))
                if raw:
                    return raw, _ext_of(m.group(1))
            for _iid, href, mt, _tag in tagged:
                if mt.startswith("image/"):
                    raw = _read_real(href)
                    if raw:
                        return raw, _ext_of(href)
            return None, None
    except ValueError:
        return None, None


def is_valid_isbn(isbn: str) -> bool:
    """ISBN 弱校验（抄 `book_ai_client._is_valid_isbn`，仅长度+首字规则）。"""
    cleaned = (isbn or "").replace("-", "").replace(" ", "")
    if not cleaned.isdigit():
        return False
    if len(cleaned) == 10:
        return cleaned[0].isdigit()
    if len(cleaned) == 13:
        return cleaned[0] == "9"
    return False


def _to_html_block(comments: str) -> str:
    """简介片段转 HTML：已有标签原样嵌入；纯文本转义后换行变 <br />；空填暂无简介。"""
    text = (comments or "").strip()
    if not text:
        return "暂无简介"
    if "<" in text:
        return text
    return html.escape(text).replace("\n", "<br />")


def compose_description(new_title: str, items: list, isbns=None) -> str:
    """组合集简介 HTML：首行新标题 + 逐本【源书名】+简介 + ISBN 尾行。

    :param new_title: 合集标题（会被转义）。
    :param items: [{"title": str, "comments": str}, ...]，顺序即展示顺序；
        comments 为空/空白时填“暂无简介”。
    :param isbns: ISBN 列表；多于 1 个时附末尾 `ISBN：a / b` 行。
    """
    parts = ["<p><b>%s</b></p>" % html.escape(new_title or "")]
    for item in items:
        parts.append("<p>【%s】</p>" % html.escape(item.get("title") or ""))
        parts.append(_to_html_block(item.get("comments")))
    clean_isbns = [i.strip() for i in (isbns or []) if (i or "").strip()]
    if len(clean_isbns) > 1:
        parts.append("<p>ISBN：%s</p>" % html.escape(" / ".join(clean_isbns)))
    return "".join(parts)


# 单次合并输出上限 1GB（与读取总量上限对齐；合集超 50MB 很常见，不再设单本上限）
_MERGE_MAX_OUTPUT = 1024 * 1024 * 1024
# 源文件总体积闸：合并期间全部输入与输出同时驻留内存，峰值约为总体积的数倍，
# 不设总和闸时 20×1GB 的理论输入可拖垮后台线程（工具层加载期同样引用此值快速失败）
MERGE_MAX_INPUT_TOTAL = 2 * 1024 * 1024 * 1024
_MERGE_MIN_BOOKS = 2
_MERGE_MAX_BOOKS = 20

_EXTERNAL_SCHEMES = ("http:", "https:", "mailto:", "data:", "ftp:", "ftps:")

# 属性名前加 (?<![-\w]) 负向断言：`\b` 挡不住 `data-id` / `data-src`
# （`-` 是非词字符，词边界依然成立），会把无关属性值一并改写。
_ATTR_RE = re.compile(
    r'''(?P<attr>(?<![-\w])(?:href|src|xlink:href)\s*=\s*)(?P<q>["'])(?P<val>.*?)(?P=q)''',
    re.IGNORECASE | re.DOTALL)
# 改写禁区：HTML 注释与 CDATA 段不是代码，里面的路径文本不得改写
# （注释不可见无影响但不该动；CDATA 作正文展示时改写会篡改读者看到的文字）。
# script/style 不在此列：其内的 href=/src= `=` 形式多为真实 URL 字符串，
# 根绝对引用改写后仍有效，相对引用原样保留；而 id 不再改名（见下），
# 不存在单边改写风险。
_SKIP_RE = re.compile(r"(<!--.*?-->|<!\[CDATA\[.*?\]\]>)", re.DOTALL)
# NCX navMap 内按文档顺序扫描的 token（navPoint 开/闭、navLabel 文本、content src）。
# 旧实现用「navLabel 紧跟 content」的单条正则，遇到 <content> 在 <navLabel> 之前
# 或没有 content 的 navPoint 会错配/漏配（整本目录塌成单条目）；扫描式配对对
# 元素顺序不敏感。
_NCX_TOKEN_RE = re.compile(
    r"<navPoint\b[^>]*>|</navPoint\s*>"
    r"|<navLabel\b[^>]*>(.*?)</navLabel\s*>"
    r"""|<content\b[^>]*?\bsrc\s*=\s*["']([^"']+)["'][^>]*?/?>""",
    re.IGNORECASE | re.DOTALL)
_NCX_NAVMAP_RE = re.compile(r"<navMap\b[^>]*>(.*)</navMap\s*>",
                            re.IGNORECASE | re.DOTALL)
# EPUB3 nav 文档：toc 导航块与其中的 <a href>
_NAV_BLOCK_RE = re.compile(r"<nav\b[^>]*>(.*?)</nav\s*>",
                           re.IGNORECASE | re.DOTALL)
_NAV_TOC_TYPE_RE = re.compile(r"""\btype\s*=\s*["'][^"']*\btoc\b[^"']*["']""",
                              re.IGNORECASE)
_NAV_A_RE = re.compile(
    r"""<a\b[^>]*?\bhref\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a\s*>""",
    re.IGNORECASE | re.DOTALL)
# CSS 引用（只改写根绝对引用；相对引用随整树前缀天然有效）
_CSS_URL_RE = re.compile(
    r"""(url\(\s*)(?P<q>["']?)(?P<val>[^"')]+)(?P=q)(?P<tail>\s*\))""",
    re.IGNORECASE)
_CSS_IMPORT_RE = re.compile(
    r"""(@import\s+)(?P<q>["'])(?P<val>[^"']+)(?P=q)""", re.IGNORECASE)
# CSS 重编码为 utf-8 后需同步修正的 @charset 声明（与 XML 声明同理）
_CSS_CHARSET_RE = re.compile(r"""@charset\s+["'][^"']*["']\s*;""", re.IGNORECASE)
# 无 nav 语义的链接列表目录页：文件名先过这一关（避免误伤正文页），
# 再叠加链接密度门槛（见 `_looks_like_link_toc`）
_TOC_NAME_RE = re.compile(r"nav|toc|contents|目录|目次", re.IGNORECASE)
# EPUB3 nav 文档的 properties 标记（导航清单页，合并时按目录处理、不入正文）
_ITEM_PROPS_RE = re.compile(r"""properties\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
# 重编码 utf-8 后需同步修正的 XML 声明（gb18030/big5 源文档声明与字节不符会乱码）
_XML_DECL_RE = re.compile(
    r'''(<\?xml\b[^>]*?\bencoding\s*=\s*["'])[^"']*(["'])''', re.IGNORECASE)

_COVER_MEDIA_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
}


_GUESS_MEDIA_TYPES = {
    ".css": "text/css", ".xhtml": "application/xhtml+xml", ".html": "text/html",
    ".htm": "text/html", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
    ".bmp": "image/bmp", ".svg": "image/svg+xml", ".ttf": "font/ttf",
    ".otf": "font/otf", ".woff": "font/woff", ".woff2": "font/woff2",
    ".mp3": "audio/mpeg", ".mp4": "video/mp4",
}


def _guess_media_type(name: str) -> str:
    """按扩展名推断 media-type（散件注册用），未知回退 octet-stream。"""
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return _GUESS_MEDIA_TYPES.get(ext, "application/octet-stream")


def _locate_opf(entries: dict) -> str:
    """定位 OPF 路径，缺失抛 ValueError（analyze 与 merge 共用）。"""
    container = entries.get("META-INF/container.xml")
    if container is None:
        raise ValueError("EPUB 缺少 container.xml，结构异常")
    opf_path = _opf_path_from_container(container.decode("utf-8", errors="replace"))
    if not opf_path or opf_path not in entries:
        raise ValueError("EPUB 缺少 OPF 描述文件，结构异常")
    return opf_path


def _rewrite_doc_refs(text: str, old_dir: str, new_dir: str,
                      old_to_new: dict) -> tuple:
    """重写单篇正文文档的内部引用（目标属性正则版，不动其余字节）。

    - 相对文件引用保持原样（整树按 `b{idx}/` 前缀整体保留，相对结构天然有效）；
    - 根绝对引用（`/x/y`）按映射改写为相对路径；
    - 外链（http/mailto/data/…）与映射外引用原样保留；
    - `id` / `<a name>` / `#frag` 一律**不改名**：各源书文件分属不同文档，
      片段标识符天然文档内作用域，不存在跨书碰撞；改名反而会单边破坏
      `<style>` 中的 `#id` 选择器、SVG `url(#…)`、脚本 `getElementById`
      等正则覆盖不到的引用点；
    - HTML 注释与 CDATA 段整体跳过（非代码文本）。

    :return: (new_text, warnings[])。
    """
    warnings = []
    lower_map = {k.lower(): v for k, v in old_to_new.items()}

    def _map_file(ref: str):
        old = _normalize_zip_path(ref, old_dir)
        if not old:
            return None
        return lower_map.get(old.lower())

    def _rel(new_name: str) -> str:
        rel = posixpath.relpath(new_name, new_dir or ".")
        return rel.replace("\\", "/")

    def _repl_attr(m):
        attr, q, val = m.group("attr"), m.group("q"), m.group("val")
        low = val.lower()
        if "://" in val or low.startswith(_EXTERNAL_SCHEMES):
            return m.group(0)
        if "#" in val:
            fpart, frag = val.split("#", 1)
        else:
            fpart, frag = val, None
        if not fpart:
            # 同文档片段：目标 id 未改名，这里原样保留
            return m.group(0)
        if fpart.startswith("/"):
            new_name = _map_file(fpart)
            if new_name is None:
                warnings.append("无法解析的根引用：%s" % val)
                return m.group(0)
            # 合成的相对路径按 URI 规则转义（目标名可能含空格/非 ASCII/#）
            out = _quote_href(_rel(new_name))
        else:
            old = _normalize_zip_path(fpart, old_dir)
            if not old or old.lower() not in lower_map:
                # 相对引用保持原样（结构保留即有效）；映射外引用仅提示
                if old and fpart not in ("", "."):
                    warnings.append("引用目标缺失，已保留原文：%s" % val)
                return m.group(0)
            out = fpart
        if frag:
            out += "#%s" % frag
        return "%s%s%s%s" % (attr, q, out, q)

    def _rewrite_segment(segment: str) -> str:
        return _ATTR_RE.sub(_repl_attr, segment)

    # 注释/CDATA 禁区原样保留，其余段改写后拼回
    parts = _SKIP_RE.split(text)
    for i in range(0, len(parts), 2):
        parts[i] = _rewrite_segment(parts[i])
    return "".join(parts), warnings


def _normalize_xml_encoding(text: str) -> str:
    """重编码为 utf-8 后同步修正 XML 声明。

    GBK/big5 源文档经 `_decode` 解出 str 后按 utf-8 回写，若保留
    `encoding="gb18030"` 声明，阅读器按声明解码即整章乱码。
    """
    if text.lstrip().startswith("<?xml"):
        return _XML_DECL_RE.sub(lambda m: "%sutf-8%s" % (m.group(1), m.group(2)),
                                text, count=1)
    return text


def _nav_doc_names(opf_text: str, opf_path: str) -> set:
    """EPUB3 nav 文档（manifest `properties` 含 nav）的 zip 条目名（小写）集合。

    nav 页是渲染出来的目录清单，合并后与生成的 toc.ncx 功能重复，
    按 plan「纯链接列表目录页不计正文」跳过，不进 spine、不入包。
    """
    base_dir = opf_path.rsplit("/", 1)[0] if "/" in opf_path else ""
    names = set()
    for tag in _ITEM_RE.findall(opf_text):
        props = _ITEM_PROPS_RE.search(tag)
        href = _ITEM_HREF_RE.search(tag)
        if not props or not href:
            continue
        if any(p.strip().lower() == "nav" for p in props.group(1).split()):
            name = _normalize_zip_path(href.group(1), base_dir)
            if name:
                names.add(name.lower())
    return names


def _strip_tags(html_text: str) -> str:
    """去标签取纯文本（OPF dc:description 用），连续空白折叠。"""
    text = re.sub(r"<[^>]+>", " ", html_text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _parse_ncx_pairs(ncx_text: str) -> list:
    """按文档顺序提取 NCX（label, src）对（命名空间无关，嵌套按前序输出）。

    用 token 扫描 + navPoint 栈配对，而非「navLabel 紧跟 content」的单条正则：
    `<content>` 在 `<navLabel>` 之前（现实存在、阅读器容忍）也能配对；没有
    `<content>` 的 navPoint（纯分组标题）不会吞掉下一个条目的 label/src。
    只在 `<navMap>` 段内扫描，`<pageList>` 的 pageTarget 不会混进目录。
    """
    m = _NCX_NAVMAP_RE.search(ncx_text)
    if not m:
        return []
    pairs = []
    stack = []
    for tok in _NCX_TOKEN_RE.finditer(m.group(1)):
        raw = tok.group(0)
        low = raw[:12].lower()
        if low.startswith("<navpoint"):
            stack.append({"label": "", "src": None, "done": False})
        elif low.startswith("</navpoint"):
            if stack:
                frame = stack.pop()
                if not frame["done"] and frame["label"] and frame["src"]:
                    pairs.append((frame["label"], frame["src"]))
        elif low.startswith("<navlabel"):
            if not stack:
                continue
            label = _strip_tags(tok.group(1) or "")
            if label and not stack[-1]["label"]:
                stack[-1]["label"] = label
                if stack[-1]["src"] and not stack[-1]["done"]:
                    pairs.append((label, stack[-1]["src"]))
                    stack[-1]["done"] = True
        else:  # <content src="...">
            if not stack:
                continue
            if not stack[-1]["src"]:
                stack[-1]["src"] = tok.group(2)
            if stack[-1]["label"] and not stack[-1]["done"]:
                pairs.append((stack[-1]["label"], stack[-1]["src"]))
                stack[-1]["done"] = True
    return pairs


def _parse_nav_pairs(nav_text: str) -> list:
    """提取 EPUB3 nav 文档 toc 导航里的 (label, href) 对（文档顺序）。

    优先 `<nav epub:type="toc">`（或 `type="toc"`）块，没有类型标记时退回
    首个 `<nav>`；再退回整篇找 `<a href>`（部分工具把 nav 写成裸 `<ol>`）。
    """
    blocks = _NAV_BLOCK_RE.findall(nav_text)
    body = nav_text
    for block in blocks:
        head = block[:300]
        if _NAV_TOC_TYPE_RE.search(head):
            body = block
            break
    else:
        if blocks:
            body = blocks[0]
    pairs = []
    for href, inner in _NAV_A_RE.findall(body):
        label = _strip_tags(inner)
        if href and label:
            pairs.append((label, href))
    return pairs


def _map_toc_src(src_ref: str, base_dir: str, lower_o2n: dict):
    """把 NCX/nav 引用映射到新包内路径。

    :return: `(新路径, fragment | None)`；目标不在本次合并映射内（外链、
        已被剔除的 nav 页等）时返回 None。路径与 fragment 分开返回：
    条目名本身可能含 `#`（源 href 写作 `a%23b.xhtml`），合并成一个字符串后
    无法再区分哪个 `#` 是 fragment 分隔符。
    """
    if "#" in src_ref:
        fpart, frag = src_ref.split("#", 1)
    else:
        fpart, frag = src_ref, None
    old = _normalize_zip_path(fpart, base_dir)
    new_src = lower_o2n.get(old.lower()) if old else None
    if new_src is None:
        return None
    return new_src, frag


def _is_toc_like_name(name: str) -> bool:
    """文件名是否像目录页（合并时用于挑选链接列表目录页复核候选）。"""
    stem = (name or "").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return bool(_TOC_NAME_RE.search(stem))


def _looks_like_link_toc(html_text: str, name: str) -> bool:
    """无 nav 语义的链接列表目录页检测（calibre「Table of Contents」等）。

    保守双门槛，防误伤正文页：文件名须含 nav/toc/contents/目录/目次，且
    书内链接 ≥5 条、块级元素中带链接的比例 ≥60%（抄 beautify
    `_looks_like_link_toc` 的信号 2，未引入其 chapter_patterns 依赖）。
    """
    if not _is_toc_like_name(name):
        return False
    hrefs = re.findall(r"""<a\b[^>]*?\bhref\s*=\s*["']([^"']+)["']""",
                       html_text, re.IGNORECASE)
    internal = [h for h in hrefs
                if "://" not in h and not h.lower().startswith(_EXTERNAL_SCHEMES)]
    if len(internal) < 5:
        return False
    blocks = len(re.findall(r"<(?:p|div|li|h[1-6]|td)\b", html_text, re.IGNORECASE))
    if blocks and len(internal) * 10 < blocks * 6:
        return False
    return True


def _rewrite_css_refs(text: str, old_dir: str, new_dir: str,
                      old_to_new: dict) -> tuple:
    """重写 CSS 中的根绝对引用（`url(/x)` / `@import "/x"`）。

    与正文同规则：相对引用原样保留（整树前缀下相对结构天然有效），
    外链与映射外引用原样保留；只处理 CSS 文件本身，正文内联 `<style>`
    不在本函数范围内（其根绝对引用同样罕见，且改写正文文本风险更高）。
    :return: (new_text, warnings[])。
    """
    warnings = []
    lower_map = {k.lower(): v for k, v in old_to_new.items()}

    def _repl(val):
        if "://" in val or val.strip().lower().startswith(_EXTERNAL_SCHEMES):
            return None
        if "#" in val:
            fpart, frag = val.split("#", 1)
        else:
            fpart, frag = val, None
        if not fpart.startswith("/"):
            return None
        old = _normalize_zip_path(fpart, old_dir)
        new_name = lower_map.get(old.lower()) if old else None
        if new_name is None:
            warnings.append("无法解析的根引用：%s" % val)
            return None
        rel = posixpath.relpath(new_name, new_dir or ".").replace("\\", "/")
        rel = _quote_href(rel)
        return "%s#%s" % (rel, frag) if frag else rel

    def _sub_url(m):
        new = _repl(m.group("val"))
        if new is None:
            return m.group(0)
        return "%s%s%s%s" % (m.group(1), m.group("q"), new, m.group("tail"))

    def _sub_import(m):
        new = _repl(m.group("val"))
        if new is None:
            return m.group(0)
        return "%s%s%s" % (m.group(1), m.group("q"), new + m.group("q"))

    text = _CSS_URL_RE.sub(_sub_url, text)
    text = _CSS_IMPORT_RE.sub(_sub_import, text)
    return text, warnings


def _maybe_rewrite_css(name: str, mt: str, raw: bytes, old_dir: str,
                       new_dir: str, old_to_new: dict, book_title: str,
                       warnings: list) -> bytes:
    """CSS 条目按需改写：无改写时原字节返回（保留源编码，无损）。"""
    if mt != "text/css" and not name.lower().endswith(".css"):
        return raw
    text = _decode(raw)
    new_text, warns = _rewrite_css_refs(text, old_dir, new_dir, old_to_new)
    for w in warns:
        warnings.append("[%s] %s" % (book_title, w))
    if new_text == text:
        return raw
    # 重新编码为 utf-8 时必须同步修正 @charset（与 XML 声明同理）
    new_text = _CSS_CHARSET_RE.sub('@charset "utf-8";', new_text, count=1)
    return new_text.encode("utf-8")


def _build_divider(book_title: str, index: int, total: int) -> bytes:
    """生成分卷页（卷名=源书名）。"""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>%s</title></head>'
        "<body><h1>%s</h1><p>第%d卷 / 共%d卷</p></body></html>"
        % (html.escape(book_title), html.escape(book_title), index + 1, total)
    ).encode("utf-8")


def _build_opf(meta: dict, manifest: list, spine: list, uid: str,
               cover_name: str | None, cover_mt: str | None) -> bytes:
    """组装新书 OPF（EPUB2 风格，抄 split 写包语义；href 统一 URI 转义）。"""
    creators = "".join(
        '<dc:creator opf:role="aut">%s</dc:creator>' % html.escape(a)
        for a in meta.get("authors") or [])
    langs = "".join(
        "<dc:language>%s</dc:language>" % html.escape(lang)
        for lang in meta.get("languages") or ["zho"])
    subjects = "".join(
        "<dc:subject>%s</dc:subject>" % html.escape(t)
        for t in meta.get("tags") or [])
    items = "".join(
        '<item id="%s" href="%s" media-type="%s"/>' % (
            iid, _xml_attr(_quote_href(href)), mt)
        for iid, href, mt in manifest)
    if cover_name:
        items += '<item id="cover-image" href="%s" media-type="%s"/>' % (
            _xml_attr(_quote_href(cover_name)), cover_mt)
    refs = "".join('<itemref idref="%s"/>' % iid for iid in spine)
    cover_meta = ""
    guide = ""
    if cover_name:
        cover_meta = '<meta name="cover" content="cover-image"/>'
        guide = ('<guide><reference type="cover" title="Cover" href="%s"/></guide>'
                 % _xml_attr(_quote_href(cover_name)))
    head = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<package version="2.0" xmlns="http://www.idpf.org/2007/opf" '
        'unique-identifier="merge-id">',
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf">',
        '<dc:identifier id="merge-id">%s</dc:identifier>' % uid,
        "<dc:title>%s</dc:title>" % html.escape(meta.get("title") or ""),
        creators,
        '<dc:contributor opf:role="bkp">MyBooks epub_merge</dc:contributor>',
        langs,
        "<dc:description>%s</dc:description>" % html.escape(
            _strip_tags(meta.get("description") or "")),
        subjects,
    ]
    if meta.get("publisher"):
        head.append("<dc:publisher>%s</dc:publisher>"
                    % html.escape(meta["publisher"]))
    head.append(cover_meta)
    head.append("</metadata>")
    head.append("<manifest>%s</manifest>" % items)
    head.append('<spine toc="ncx">%s</spine>' % refs)
    head.append(guide)
    head.append("</package>")
    return "".join(head).encode("utf-8")


def _xml_attr(value: str) -> str:
    """XML 属性值转义（href 里已无裸 `&`，此处兜底引号/尖括号）。"""
    return html.escape(value or "", quote=True)


def _build_ncx(title: str, books_toc: list, uid: str) -> bytes:
    """组装新书 NCX：每源书一个父节点挂其条目，playOrder 全局重排。

    :param books_toc: [(book_title, (parent_path, parent_frag),
        [(label, path, frag), ...]), ...]，路径均为新包内路径；开分卷页时
        父节点指向分卷页。路径与 fragment 分开传入（路径可能含 `#`）。
    """
    order = 0
    navpoints = []
    for bi, (book_title, parent, pairs) in enumerate(books_toc):
        order += 1
        parent_order = order
        children = []
        for label, path, frag in pairs:
            order += 1
            children.append(
                '<navPoint id="m%d_%d" playOrder="%d"><navLabel><text>%s</text>'
                '</navLabel><content src="%s"/></navPoint>'
                % (bi, order, order, html.escape(label),
                   _xml_attr(_quote_toc_src(path, frag))))
        navpoints.append(
            '<navPoint id="m%d" playOrder="%d"><navLabel><text>%s</text></navLabel>'
            '<content src="%s"/>%s</navPoint>'
            % (bi, parent_order, html.escape(book_title),
               _xml_attr(_quote_toc_src(parent[0], parent[1])),
               "".join(children)))
    head = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">',
        "<head>",
        '<meta name="dtb:uid" content="%s"/>' % _xml_attr(uid),
        '<meta name="dtb:depth" content="2"/>',
        '<meta name="dtb:totalPageCount" content="0"/>',
        '<meta name="dtb:maxPageNumber" content="0"/>',
        "</head>",
        "<docTitle><text>%s</text></docTitle>" % html.escape(title),
        "<navMap>%s</navMap></ncx>" % "".join(navpoints),
    ]
    return "".join(head).encode("utf-8")


def _input_source(item: dict) -> tuple:
    """归一化单个合并输入：返回 (source, size)。

    source 为 bytes（内存）或文件路径（str，逐本按需读取，不驻留内存）。
    """
    if not isinstance(item, dict):
        raise ValueError("合并输入格式异常")
    data = item.get("data")
    if data:
        return bytes(data), len(data)
    path = item.get("path")
    if path:
        try:
            size = os.path.getsize(path)
        except OSError as err:
            raise ValueError("EPUB 源文件不可读：%s" % err) from err
        if not size:
            raise ValueError("EPUB 输入为空")
        return path, size
    raise ValueError("EPUB 输入为空")


def merge_epubs(inputs: list, meta: dict, options: dict | None = None):
    """按 `inputs` 顺序合并多本 EPUB。

    :param inputs: [{"data": bytes, "title": str} | {"path": str, "title": str},
        ...]，顺序即拼接顺序。`path` 模式逐本按需读取：峰值内存只与
        「单本最大条目 + 单本解压总量」相关，不再随源书总大小与输出大小增长。
    :param meta: {"title", "authors", "languages", "tags", "description",
        "publisher"}，缺失键用空值/缺省。
    :param options: {"divider": bool（默认 True）, "cover": {"data": bytes,
        "ext": str} | None, "out_path": str | None}。cover 由工具层决议后传入
        原始字节；给定 out_path 时输出流式写入该文件并返回 None（避免在内存里
        再拼一份完整 zip），否则返回合并结果字节。
    :raises ValueError: 本数越界 / 单本结构异常 / 输出超限。
    """
    options = options or {}
    divider = options.get("divider", True)
    cover = options.get("cover")
    out_path = options.get("out_path")
    if not isinstance(inputs, list) or not (_MERGE_MIN_BOOKS <= len(inputs) <= _MERGE_MAX_BOOKS):
        raise ValueError("请选择 %d–%d 本书进行合并" % (_MERGE_MIN_BOOKS, _MERGE_MAX_BOOKS))
    sources = [_input_source(item) for item in inputs]
    total_input = sum(size for _src, size in sources)
    if total_input > MERGE_MAX_INPUT_TOTAL:
        raise ValueError("合集源文件总体积超过上限（2GB），请减少本数或分批合并")

    uid = "epubmerge-%s" % uuid.uuid4().hex
    if out_path:
        with open(out_path, "wb") as fh:
            _merge_into(fh, sources, inputs, meta, divider, cover, uid)
        result = None
        out_size = os.path.getsize(out_path)
    else:
        buf = io.BytesIO()
        _merge_into(buf, sources, inputs, meta, divider, cover, uid)
        result = buf.getvalue()
        out_size = len(result)
    if out_size > _MERGE_MAX_OUTPUT:
        raise ValueError("合并输出超过上限（1GB）")
    return result


def _merge_into(out, sources: list, inputs: list, meta: dict, divider: bool,
                cover, uid: str) -> None:
    """流式合并主体：逐本读取源条目并立即写入 `out`（zip 输出流）。

    manifest / spine / TOC 只累积小结构（id 与路径字符串），条目字节不驻留。
    """
    manifest = []           # (id, href, media-type)
    spine = []              # manifest id 顺序
    # [(book_title, (parent_path, parent_frag), [(label, path, frag), ...]), ...]
    books_toc = []
    warnings = []
    counter = 0

    def _next_id():
        nonlocal counter
        counter += 1
        return "a%d" % counter

    writer = _ZipWriter(out)
    try:
        cover_name, cover_mt = None, None
        if cover and cover.get("data"):
            ext = (cover.get("ext") or "jpg").lower().lstrip(".")
            cover_mt = _COVER_MEDIA_TYPES.get(ext, "image/jpeg")
            cover_name = "cover.%s" % ("jpg" if ext == "jpeg" else ext)
            writer.write(cover_name, cover["data"])

        total = len(sources)
        for idx, ((source, _size), item) in enumerate(zip(sources, inputs)):
            prefix = "b%d" % idx
            book_title = (item.get("title") or "").strip() or ("分册%d" % (idx + 1))
            with _ZipSource(source) as src:
                opf_path = _locate_opf(src)
                opf_text = _decode(src.read(opf_path))
                items = _manifest_items(opf_text, opf_path)
                nav_names = _nav_doc_names(opf_text, opf_path)

                # spine 顺序（idref 序列，无 spine 降级 manifest 文本顺序；nav 页两路都不进）
                ordered_ids = []
                m = _SPINE_RE.search(opf_text)
                if m:
                    ordered_ids = [r for r in _ITEMREF_RE.findall(m.group(1))
                                   if r in items]
                if not ordered_ids:
                    ordered_ids = [
                        i for i, (n, mt) in items.items()
                        if mt in _TEXT_MEDIA_TYPES and n.lower() not in nav_names]
                if not ordered_ids:
                    raise ValueError("书籍 [%s] 未定位到正文条目，无法合并" % book_title)

                old_to_new = {}
                lower_entries = src.lower_map()
                for _iid, (name, _mt) in items.items():
                    real = lower_entries.get(name.lower())
                    if real:
                        old_to_new[real] = "%s/%s" % (prefix, real)
                # EPUB3 nav 文档按目录处理：不进 spine / manifest / 散件，从映射移除，
                # 残留引用走「目标缺失」告警而非静默死链
                nav_reals = {lower_entries[n] for n in nav_names
                             if n in lower_entries}
                for real in nav_reals:
                    old_to_new.pop(real, None)
                    warnings.append("[%s] EPUB3 nav 目录页不进正文：%s"
                                    % (book_title, real))
                # 无 nav 语义的链接列表目录页（calibre「Table of Contents」等）：
                # 先按文件名筛候选，再读内容复核，命中同样不计正文
                link_toc_reals = set()
                for iid in ordered_ids:
                    name, mt = items[iid]
                    real = lower_entries.get(name.lower())
                    if not real or mt not in _TEXT_MEDIA_TYPES:
                        continue
                    if real in nav_reals or not _is_toc_like_name(real):
                        continue
                    if _looks_like_link_toc(_decode(src.read(real)), real):
                        link_toc_reals.add(real)
                for real in link_toc_reals:
                    old_to_new.pop(real, None)
                    warnings.append("[%s] 链接列表目录页不进正文：%s"
                                    % (book_title, real))
                skip_reals = nav_reals | link_toc_reals
                lower_o2n = {k.lower(): v for k, v in old_to_new.items()}

                def _emit(real, new_name, mt):
                    """非 spine 资源：CSS 读入改写，其余直接流式转写（不过内存）。"""
                    if mt == "text/css" or real.lower().endswith(".css"):
                        writer.write(new_name, _maybe_rewrite_css(
                            real, mt, src.read(real),
                            real.rsplit("/", 1)[0] if "/" in real else "",
                            new_name.rsplit("/", 1)[0], old_to_new, book_title,
                            warnings))
                    else:
                        writer.write_stream(new_name, src.iter_chunks(real))

                # 散件：manifest 未列但真实存在的非结构文件同样复制（防劣质书丢图），
                # media-type 按扩展名推断后注册进新 manifest，保证输出合法。
                structural = {"META-INF/container.xml", opf_path}
                structural.update(skip_reals)
                for _iid, (name, mt) in items.items():
                    if mt == _NCX_MEDIA_TYPE:
                        real = lower_entries.get(name.lower())
                        if real:
                            structural.add(real)
                loose = []
                for name in src:
                    if name in old_to_new or name in structural:
                        continue
                    if name == "mimetype" or name.startswith("META-INF/"):
                        # 容器级文件（mimetype/签名/加密/书签）不入合集
                        continue
                    new_name = "%s/%s" % (prefix, name)
                    old_to_new[name] = new_name
                    loose.append((name, new_name))
                for name, new_name in loose:
                    warnings.append("[%s] 散件已收录：%s" % (book_title, name))

                new_spine_docs = []
                emitted = set()
                for iid in ordered_ids:
                    name, mt = items[iid]
                    real = lower_entries.get(name.lower())
                    if not real:
                        warnings.append("[%s] 正文条目缺失，已跳过：%s"
                                        % (book_title, name))
                        continue
                    if name.lower() in nav_names or real in skip_reals:
                        continue
                    new_name = old_to_new[real]
                    raw = src.read(real)
                    if mt in _TEXT_MEDIA_TYPES:
                        text = _decode(raw)
                        old_dir = real.rsplit("/", 1)[0] if "/" in real else ""
                        new_text, warns = _rewrite_doc_refs(
                            text, old_dir, new_name.rsplit("/", 1)[0], old_to_new)
                        for w in warns:
                            warnings.append("[%s] %s" % (book_title, w))
                        # 文档所在旧目录：以该文档自身目录为准，而非 OPF 目录
                        writer.write(new_name,
                                     _normalize_xml_encoding(new_text).encode("utf-8"))
                    else:
                        writer.write(new_name, _maybe_rewrite_css(
                            real, mt, raw, real.rsplit("/", 1)[0] if "/" in real else "",
                            new_name.rsplit("/", 1)[0], old_to_new, book_title,
                            warnings))
                    emitted.add(new_name)
                    mid = _next_id()
                    manifest.append((mid, new_name, mt))
                    spine.append(mid)
                    new_spine_docs.append(new_name)

                if not new_spine_docs:
                    raise ValueError("书籍 [%s] 正文条目全部缺失，无法合并" % book_title)

                # manifest 非 spine 资源（CSS/图/字体）原样收录；源 NCX 与
                # 目录页除外（已被合并后的 toc.ncx 取代，复制只会留下混淆视听的死文件）
                for _iid, (name, mt) in items.items():
                    if mt == _NCX_MEDIA_TYPE or name.lower() in nav_names:
                        continue
                    real = lower_entries.get(name.lower())
                    if not real or real in skip_reals:
                        continue
                    new_name = old_to_new[real]
                    if new_name in emitted:
                        continue
                    _emit(real, new_name, mt)
                    manifest.append((_next_id(), new_name, mt))
                    emitted.add(new_name)

                for name, new_name in loose:
                    if name == "mimetype":
                        continue
                    _emit(name, new_name, _guess_media_type(name))
                    manifest.append((_next_id(), new_name,
                                     _guess_media_type(name)))

                # 分卷页插到该书首篇之前
                div_name = None
                if divider:
                    div_name = "%s_divider.xhtml" % prefix
                    writer.write(div_name, _build_divider(book_title, idx, total))
                    div_id = _next_id()
                    manifest.append((div_id, div_name, "application/xhtml+xml"))
                    first_mid = next(m0 for m0, h, _m in manifest
                                     if h == new_spine_docs[0])
                    spine.insert(spine.index(first_mid), div_id)

                # TOC：NCX 重映射（src 相对 NCX 自身目录解析）→ EPUB3 nav 兜底
                # → spine 兜底。frag 原样保留：目标 id 未改名（见 _rewrite_doc_refs）。
                pairs = []
                for _iid, (name, mt) in items.items():
                    if mt != _NCX_MEDIA_TYPE:
                        continue
                    real = lower_entries.get(name.lower())
                    if not real:
                        break
                    ncx_base = real.rsplit("/", 1)[0] if "/" in real else ""
                    for label, src_ref in _parse_ncx_pairs(_decode(src.read(real))):
                        mapped = _map_toc_src(src_ref, ncx_base, lower_o2n)
                        if mapped:
                            pairs.append((label or book_title,
                                          mapped[0], mapped[1]))
                    break
                if not pairs:
                    nav_real = next((lower_entries[n] for n in nav_names
                                     if n in lower_entries), None)
                    if nav_real:
                        nav_base = nav_real.rsplit("/", 1)[0] if "/" in nav_real else ""
                        for label, href in _parse_nav_pairs(_decode(src.read(nav_real))):
                            mapped = _map_toc_src(href, nav_base, lower_o2n)
                            if mapped:
                                pairs.append((label or book_title,
                                              mapped[0], mapped[1]))
                        if pairs:
                            warnings.append("[%s] 无 NCX 目录，已改用 EPUB3 导航"
                                            % book_title)
                if not pairs:
                    # spine 兜底：条目名取文件名主干（排除目录页；nav 页已不在 spine）
                    pairs = [(posixpath.basename(n).rsplit(".", 1)[0] or book_title,
                              n, None) for n in new_spine_docs]
                    warnings.append("[%s] 无 NCX / EPUB3 导航，已降级为 spine 顺序"
                                    % book_title)
                # 父节点指向分卷页（开 divider 时点父节点先见卷名页），否则指向首篇
                parent = (div_name, None) if divider else (pairs[0][1], pairs[0][2])
                books_toc.append((book_title, parent, pairs))

        manifest.append(("ncx", "toc.ncx", _NCX_MEDIA_TYPE))
        writer.write("content.opf",
                     _build_opf(meta, manifest, spine, uid, cover_name, cover_mt))
        writer.write("toc.ncx",
                     _build_ncx(meta.get("title") or "", books_toc, uid))
        writer.write("META-INF/container.xml", (
            '<?xml version="1.0"?>'
            '<container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>'
        ).encode("utf-8"))
    finally:
        writer.close()
    for w in warnings:
        logging.warning("[epub_merge] %s", w)


def validate_output(data) -> list:
    """校验合并输出合法性（入库前守门；命名空间感知，严于普通阅读器）。

    :param data: 输出字节（bytes）或文件路径（str/PathLike，避免为校验把整本读进内存）。
    检查：mimetype 首项 STORED / container→OPF 可达 / OPF 可解析 /
    manifest id 唯一 / spine idref 全命中 / manifest href 全存在 /
    guide 引用存在 / dc:title 非空 / NCX 良构且 playOrder 唯一。
    href 与 NCX src 按 URI 规则 unquote 后再比对条目名（写包侧已转义）。
    通过返回 warnings（目前恒为空，留扩展）；致命问题抛 ValueError。
    """
    if isinstance(data, (str, os.PathLike)):
        source = data
    else:
        source = io.BytesIO(bytes(data))
    try:
        zf = zipfile.ZipFile(source)
    except zipfile.BadZipFile as err:
        raise ValueError("输出不是合法 zip：%s" % err) from err
    # with 关闭：path 入参时不能把句柄留给 GC（异常回溯会一直持有帧，
    # Windows 下文件被锁，失败路径的 work_dir 清理会静默失败）
    with zf:
        return _validate_open_zip(zf)


def _validate_open_zip(zf) -> list:
    """`validate_output` 的校验主体（zip 已打开，由调用方负责关闭）。"""
    import xml.etree.ElementTree as _ET

    infos = [i for i in zf.infolist() if not i.is_dir()]
    if not infos or infos[0].filename != "mimetype" \
            or infos[0].compress_type != zipfile.ZIP_STORED:
        raise ValueError("输出 mimetype 缺失或位置/压缩方式不规范")
    names = {i.filename for i in infos}

    def _read(name):
        try:
            return zf.read(name)
        except KeyError:
            raise ValueError("输出缺文件：%s" % name) from None

    def _target(href):
        """href/src → 条目名（unquote + fragment/query 剥离 + `../` 归一）。"""
        return _normalize_zip_path(href or "")

    container = _read("META-INF/container.xml").decode("utf-8", errors="replace")
    opf_path = _opf_path_from_container(container)
    if not opf_path or opf_path not in names:
        raise ValueError("输出缺 OPF 描述文件")
    try:
        root = _ET.fromstring(_read(opf_path))
    except _ET.ParseError as err:
        raise ValueError("输出 OPF 解析失败：%s" % err) from err

    _OPF = "{http://www.idpf.org/2007/opf}"
    _DC = "{http://purl.org/dc/elements/1.1/}"
    title_el = root.find("./%smetadata/%stitle" % (_OPF, _DC))
    if title_el is None or not (title_el.text or "").strip():
        raise ValueError("输出缺书名（metadata 命名空间异常？）")

    man_ids = set()
    man_href = {}
    for item in root.findall("./%smanifest/%sitem" % (_OPF, _OPF)):
        iid, href = item.get("id"), item.get("href")
        if not iid or not href:
            raise ValueError("输出 manifest 条目缺 id/href")
        if iid in man_ids:
            raise ValueError("输出 manifest id 重复：%s" % iid)
        man_ids.add(iid)
        man_href[iid] = href
        if _target(href) not in names:
            raise ValueError("输出 manifest 引用缺失：%s" % href)

    spine_el = root.find("./%sspine" % _OPF)
    if spine_el is None:
        raise ValueError("输出缺 spine")
    toc_id = spine_el.get("toc")
    if toc_id and toc_id not in man_ids:
        raise ValueError("输出 spine toc 指向不明：%s" % toc_id)
    for ref in spine_el.findall("./%sitemref" % _OPF):
        if ref.get("idref") not in man_ids:
            raise ValueError("输出 spine 引用不明：%s" % ref.get("idref"))

    guide_el = root.find("./%sguide" % _OPF)
    if guide_el is not None:
        for ref in guide_el.findall("./%sreference" % _OPF):
            href = ref.get("href") or ""
            if href and _target(href) not in names:
                raise ValueError("输出 guide 引用缺失：%s" % href)

    ncx_name = next(
        (h for i, h in man_href.items()
         if h.lower().endswith(".ncx")), None)
    if ncx_name:
        try:
            ncx_root = _ET.fromstring(_read(_target(ncx_name)))
        except _ET.ParseError as err:
            raise ValueError("输出 NCX 解析失败：%s" % err) from err
        _NCX = "{http://www.daisy.org/z3986/2005/ncx/}"
        orders = []
        for np in ncx_root.iter(_NCX + "navPoint"):
            try:
                orders.append(int(np.get("playOrder")))
            except (TypeError, ValueError):
                raise ValueError("输出 NCX playOrder 非法") from None
            src = ""
            content = np.find(_NCX + "content")
            if content is not None:
                src = _target((content.get("src") or "").split("#", 1)[0])
            if src and src not in names:
                raise ValueError("输出 NCX 引用缺失：%s" % src)
        if len(set(orders)) != len(orders):
            raise ValueError("输出 NCX playOrder 重复")
    return []
