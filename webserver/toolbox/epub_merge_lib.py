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
简介组合 / 封面拼图 / `merge_epubs` 拼接主体 / `validate_output` 输出守门。
"""

import codecs
import html
import io
import json
import logging
import os
import posixpath
import re
import uuid
import zipfile
from datetime import datetime, timezone
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

# analyze 告警码：preview 边界统一翻译为本地化文案（lib 不依赖 webserver/i18n）
WARN_NO_NCX = "no_ncx"
WARN_NO_SPINE = "no_spine"
WARN_ENCRYPTED_ASSETS = "encrypted_assets"

# 加密/DRM：rights.xml 或正文/CSS/NCX 被加密时拒绝合并；encryption.xml 仅
# 字体混淆（常见于商业电子书）时剔除相关资源并告警，正文照常合并。
_ENCRYPTION_NAME = "META-INF/encryption.xml"
_RIGHTS_NAME = "META-INF/rights.xml"
_CIPHER_URI_RE = re.compile(
    r"""CipherReference\b[^>]*?\bURI\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


class MergeCancelled(Exception):
    """合并任务被用户取消（工具层转为终止态，不作为异常告警）。"""


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


def _get_entry(entries, name: str):
    """按名字大小写不敏感读取条目内容（dict 或 _ZipSource），缺失返回 None。"""
    lower = name.lower()
    if hasattr(entries, "lower_map"):
        real = entries.lower_map().get(lower)
        return entries.read(real) if real else None
    for key in entries:
        if key.lower() == lower:
            return entries[key]
    return None


def _encryption_status(entries, spine_names) -> dict:
    """检测加密/DRM 资源。返回 {"rights","targets","text","other"}；无加密返回 {}。

    text（正文/CSS/NCX 被加密）或 rights.xml 存在时合并必须拒绝；other 多为
    字体混淆（无密钥无法还原），剔除即可、正文不受影响。
    :param entries: dict（全量/lite）或 _ZipSource。
    :param spine_names: 该书的 spine 条目名（用于判定加密目标是否正文）。
    """
    encryption = _get_entry(entries, _ENCRYPTION_NAME)
    rights = _get_entry(entries, _RIGHTS_NAME)
    if encryption is None and rights is None:
        return {}
    spine_low = {n.lower() for n in (spine_names or [])}
    targets = []
    if encryption:
        for uri in _CIPHER_URI_RE.findall(_decode(encryption)):
            name = _normalize_zip_path(uri)
            if name:
                targets.append(name)
    text_suffixes = (".xhtml", ".html", ".htm", ".css", ".ncx")
    text_targets = [
        t for t in targets
        if t.lower() in spine_low or t.lower().endswith(text_suffixes)]
    return {
        "rights": rights is not None,
        "targets": targets,
        "text": text_targets,
        "other": [t for t in targets if t not in text_targets],
    }


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

    @property
    def count(self) -> int:
        """已写入条目数（含 mimetype；供合并侧做输出条目闸）。"""
        return len(self._names)

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
            # 加密/DRM 小文件同样按需读取（preview 据此拒绝加密书）
            for extra in (_ENCRYPTION_NAME, _RIGHTS_NAME):
                real = lower_names.get(extra.lower())
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


def _find_ncx_text(entries, opf_path: str) -> tuple:
    """定位 NCX 文本（合集识别 / 合并共用）。返回 (条目名, 文本) 或 (None, None)。

    多个 NCX 并存时取 navPoint 最多的一本：合集输出只会带一个合并 NCX，
    源书残留 NCX 在合并时已被排除，取最大即正解。
    """
    items = _manifest_items(_decode(entries[opf_path]), opf_path)
    lower_map = {k.lower(): k for k in entries}
    best = (None, None, -1)
    for _iid, (name, mt) in items.items():
        if mt != _NCX_MEDIA_TYPE:
            continue
        real = lower_map.get(name.lower())
        if not real:
            continue
        text = _decode(entries[real])
        count = len(_NAVPOINT_RE.findall(text))
        if count > best[2]:
            best = (real, text, count)
    return best[0], best[1]


def _analyze_from(opf_path: str, entries: dict, size: int) -> dict:
    """共享分析主体：entries 需含 container/OPF/NCX 真实内容，其余条目可 b"" 占位。"""
    opf_text = _decode(entries[opf_path])
    meta = _parse_opf_meta(opf_text)
    spine = _find_spine_entries(entries)
    toc_count, found_ncx = _count_ncx_entries(entries)

    # 加密书直接拒绝：正文被加密时合并出的包无法阅读，必须在 preview 就暴露
    enc = _encryption_status(entries, spine)
    if enc and (enc["rights"] or enc["text"]):
        raise ValueError("书籍含加密正文（DRM/内容加密），无法合并")

    # 合集识别：marker（新产物）优先，旧产物按 contributor + NCX 分组。
    # 先看 OPF 里的轻量标记，普通书不必为识别额外解码 NCX。
    merged = None
    try:
        marker = parse_merge_marker(opf_text)
        legacy = _has_merger_contributor(opf_text)
        if marker or legacy:
            ncx_path, ncx_text = _find_ncx_text(entries, opf_path)
            # marker 自带标题/前缀，缺 NCX 也能按 spine 兜底 TOC；旧版必须靠 NCX
            if marker or (ncx_path and ncx_text):
                ncx_base = (ncx_path.rsplit("/", 1)[0]
                            if ncx_path and "/" in ncx_path else "")
                merged = _detect_merged_books(
                    opf_text, ncx_text or "", ncx_base, spine,
                    want_nodes=False, entry_names=entries)
    except Exception as err:
        logger.warning("[epub_merge] 合集识别失败：%s", err)

    warnings = []
    if enc and enc["other"]:
        warnings.append(WARN_ENCRYPTED_ASSETS)
    if not found_ncx:
        warnings.append(WARN_NO_NCX)
    if not spine:
        warnings.append(WARN_NO_SPINE)

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
        "merged": merged,
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


def make_cover_grid(images: list) -> "bytes | None":
    """前 9 张封面无缝拼图 → JPEG 字节；无图 / PIL 缺失 / 全部解析失败返回 None。

    统一列宽（≤360px 且不放大小图）整图满贴：不裁切、不变形、图与图之间
    零留白；同排高度取该排最大值（封面比例不一时短图下方或有细缝），
    末行不满时整排水平居中；画布纵横比随本数与封面比例自然形成
    （9 张 2:3 封面 → 1080×1620 竖版，贴近站内 11:15 书封展示槽）。
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    imgs = []
    for raw in (images or [])[:9]:
        try:
            imgs.append(Image.open(io.BytesIO(raw)).convert("RGB"))
        except Exception:
            continue
    if not imgs:
        return None
    # 列数：1/2/3 本各占满一排、4 本 2×2、5 本起 3 列（避免 3 本出现空格子）
    cols = 2 if len(imgs) == 4 else min(3, len(imgs))
    col_w = min(360, min(im.width for im in imgs))
    scaled = [
        im.resize((col_w, max(1, round(im.height * col_w / im.width))), Image.LANCZOS)
        for im in imgs
    ]
    rows = (len(scaled) + cols - 1) // cols
    row_h = [max(s.height for s in scaled[r * cols:(r + 1) * cols]) for r in range(rows)]
    canvas = Image.new("RGB", (cols * col_w, sum(row_h)), (255, 255, 255))
    for i, im in enumerate(scaled):
        r, c = divmod(i, cols)
        x = c * col_w
        last = len(scaled) - r * cols
        if last < cols:  # 末行不满：整排水平居中，避免角上留空格
            x += (cols - last) * col_w // 2
        canvas.paste(im, (x, sum(row_h[:r])))
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=85, optimize=True)
    return buf.getvalue()


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
    """简介片段转 HTML：已是标签才原样嵌入；纯文本转义后换行变 <br />；空填暂无简介。

    用「成对/自闭合标签」正则判定 HTML，而非 `"<" in text`：纯文本里的
    小于号（如「3 < 5」）不是标签，按 HTML 原样嵌入会丢内容/破坏结构。
    """
    text = (comments or "").strip()
    if not text:
        return "暂无简介"
    if _HTML_TAG_RE.search(text):
        return text
    return html.escape(text).replace("\n", "<br />")


def compose_description(items: list, isbns=None) -> str:
    """组合集简介 HTML：逐本【源书名】+简介 + ISBN 尾行。

    合集标题不写入简介——书名栏已有，正文重复一遍读起来冗余。

    :param items: [{"title": str, "comments": str, "html": bool?}, ...]，
        顺序即展示顺序；comments 为空/空白时填“暂无简介”。
        `html=True` 表示 comments 已是 HTML 片段（如从旧合集简介拆出的块），
        原样嵌入，避免二次转义。
    :param isbns: ISBN 列表；多于 1 个时附末尾 `ISBN：a / b` 行。
    """
    parts = []
    for item in items:
        parts.append("<p>【%s】</p>" % html.escape(item.get("title") or ""))
        if item.get("html"):
            body = (item.get("comments") or "").strip()
            parts.append(body or "暂无简介")
        else:
            parts.append(_to_html_block(item.get("comments")))
    clean_isbns = [i.strip() for i in (isbns or []) if (i or "").strip()]
    if len(clean_isbns) > 1:
        parts.append("<p>ISBN：%s</p>" % html.escape(" / ".join(clean_isbns)))
    return "".join(parts)


def split_composed_description(comments: str, titles: list):
    """把本工具生成的合集简介按 `<p>【书名】</p>` 拆回逐本块。

    :return: 与 titles 等长的 HTML 块列表；任一标题缺失/顺序不匹配返回 None
        （调用方整本回退，不猜测简介归属）。
    """
    text = (comments or "").strip()
    titles = [str(t or "").strip() for t in (titles or [])]
    if not text or not titles or any(not t for t in titles):
        return None
    # compose_description 末尾的 ISBN 尾行由调用方按并集重新生成，先剥掉，
    # 否则会被算进最后一本的简介里。允许编辑器给 <p> 加属性。
    text = re.sub(r"<p\b[^>]*>\s*ISBN：[^<]*</p>\s*$", "", text,
                  flags=re.IGNORECASE).rstrip()
    positions = []
    cursor = 0
    for title in titles:
        found = None
        for variant in (html.escape(title), title):
            pattern = re.compile(
                r"<p\b[^>]*>\s*【\s*%s\s*】\s*</p>" % re.escape(variant),
                re.IGNORECASE)
            found = pattern.search(text, cursor)
            if found:
                break
        if not found:
            return None
        positions.append((found.start(), found.end()))
        cursor = found.end()
    # 首个【书名】之前还有内容（前言/外层 wrapper）：不拆，整本回退，
    # 避免静默丢掉用户写在简介开头的文字。
    if positions and text[:positions[0][0]].strip():
        return None
    blocks = []
    for idx, (_start, end) in enumerate(positions):
        next_start = positions[idx + 1][0] if idx + 1 < len(positions) else len(text)
        block = text[end:next_start].strip()
        blocks.append(block or "暂无简介")
    return blocks


def expand_preview_books(books: list) -> tuple:
    """按合集展开预览默认标题/简介（纯函数，工具层与单测共用）。

    :param books: preview 的 ok_books，含 title/comments/merged。
    :return: (titles, description_items, merged_sources, expanded_count)
        合集结构按叶子书展开；简介只在能完整解析【书名】分段时展开，
        否则整本回退一条，不猜测归属。
    """
    titles = []
    items = []
    merged_sources = []
    for book in books:
        merged = book.get("merged") or {}
        sub_books = merged.get("books") or []
        sub_titles = [str(b.get("title") or "").strip() for b in sub_books]
        if len(sub_titles) < 2:
            titles.append(book.get("title") or "")
            items.append({"title": book.get("title") or "",
                          "comments": book.get("comments") or ""})
            continue
        titles.extend(sub_titles)
        blocks = split_composed_description(
            book.get("comments") or "", sub_titles)
        if blocks:
            for title, block in zip(sub_titles, blocks):
                # 块来自旧合集简介 HTML，已转义，原样嵌入防二次转义
                items.append({"title": title, "comments": block,
                              "html": True})
        else:
            items.append({"title": book.get("title") or "",
                          "comments": book.get("comments") or ""})
        merged_sources.append({
            "book_id": book.get("book_id"),
            "title": book.get("title") or "",
            "count": len(sub_titles),
            "books": sub_titles,
        })
    return titles, items, merged_sources, len(titles)


# ------------------------------------------------------------ 请求参数纯函数
# （工具/handler 共用；下沉到 lib 便于 standalone 单测，不依赖 calibre/webserver）

def ordered_unique(values) -> list:
    """strip 去空保序去重（作者/标签/ISBN 并集用）。"""
    seen = set()
    out = []
    for v in values or []:
        s = str(v).strip() if v is not None else ""
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def default_merge_title(titles: list, max_len: int = 100) -> str:
    """默认合集标题：源书名用 `，` 连接 + `合集`，超限硬截断（前后端双截）。"""
    title = "，".join([t for t in (titles or []) if t]) + "合集"
    return title[:max_len]


def normalize_book_ids(book_ids, min_books: int = 2, max_books: int = None) -> list:
    """校验并归一化 ID 列表（整数、无重复），越界/非法抛 ValueError。

    `max_books` 缺省取模块常量 `MERGE_MAX_BOOKS`：常量定义在下方常量段，
    而默认参数在函数定义时求值，故这里用 None 哨兵延迟取值。
    """
    max_books = MERGE_MAX_BOOKS if max_books is None else max_books
    if not isinstance(book_ids, list) or not (min_books <= len(book_ids) <= max_books):
        raise ValueError("请选择 %d–%d 本书进行合并" % (min_books, max_books))
    ids = []
    for bid in book_ids:
        try:
            ids.append(int(bid))
        except (TypeError, ValueError):
            raise ValueError("书籍 ID 非法：%r" % (bid,)) from None
    if len(set(ids)) != len(ids):
        raise ValueError("书籍重复选择，请去重后再试")
    return ids


def coerce_bool(value, default: bool = False) -> bool:
    """布尔兼容 string/bool（裸 API 传 "false"/"0" 时 bool() 会误判为 True）。"""
    if value is None:
        return default
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("false", "0", "no", ""):
            return False
        if s in ("true", "1", "yes"):
            return True
        return True
    return bool(value)


def clean_text(value, max_len: int = 0) -> str:
    """str 归一化 + strip（None/空安全），max_len>0 时截断。"""
    s = str(value).strip() if value not in (None, "") else ""
    return s[:max_len] if max_len else s


def clean_str_list(value) -> list:
    """字符串列表归一化（strip 去空）；非列表抛 ValueError（防字符串被逐字迭代）。"""
    if not isinstance(value, list):
        raise ValueError("列表格式不合法")
    return [s for s in (str(v).strip() if v is not None else "" for v in value) if s]


# 单次合并输出上限 1GB（与读取总量上限对齐；合集超 50MB 很常见，不再设单本上限）
_MERGE_MAX_OUTPUT = 1024 * 1024 * 1024
# 源文件总体积闸：合并期间全部输入与输出同时驻留内存，峰值约为总体积的数倍，
# 不设总和闸时 200×1GB 的理论输入可拖垮后台线程（工具层加载期同样引用此值快速失败）
MERGE_MAX_INPUT_TOTAL = 2 * 1024 * 1024 * 1024
_MERGE_MIN_BOOKS = 2
# 单次合并可选书数上限（handler / preview / 前端提示统一引用此常量）。
# 200 本按实测中位源书（75 条目 / 1.4MB）约 1.5 万条目、300MB 级输出，
# 仍在总量闸 2GB 与条目闸 6 万之内；引擎为流式合并、耗时随本数线性
# （实测 200 本 285MB 用时 48s，Python 峰值内存 25MB）。
MERGE_MAX_BOOKS = 200
# 输出条目闸：ZIP 非 ZIP64 的条目上限是 65535，超出后 zipfile 会自动切 ZIP64，
# 而旧阅读器 / 老 WebView 对 ZIP64 支持参差。留 5000 余量给 mimetype/opf/ncx 等，
# 超限时提前失败并提示分批，避免产出打不开的合集。
_MERGE_MAX_TOTAL_ENTRIES = 60000

# 合集标记：输出 OPF 的 <meta property="mybooks:merge">，值为紧凑 JSON。
# v1: {"v":1,"books":[{"title":"A","prefix":"b0/"}, ...]}
# 用途：再次合并本工具产物时无需启发式猜测，直接按叶子书展开。
MERGE_MARKER_PROPERTY = "mybooks:merge"
MERGE_MARKER_PREFIX = "mybooks: https://mybooks.top/ns/merge#"
MERGE_MARKER_VERSION = 1
# 旧版合集（无 marker）递归识别深度上限：正常产物最多两层，5 留足余量。
MERGE_MAX_EXPAND_DEPTH = 5
# marker 中书名保留上限（防异常包把 OPF 撑大；正常书名远小于此值）
_MERGE_MARKER_TITLE_MAX = 500
_MERGE_MARKER_RE = re.compile(
    r"""<meta\b[^>]*\bproperty\s*=\s*["']mybooks:merge["'][^>]*>(.*?)</meta>""",
    re.IGNORECASE | re.DOTALL)
# 工具产物每本源书的路径前缀 / 分卷页：b0/、b0/b1/、b0_divider.xhtml…
_B_PREFIX_SEG_RE = re.compile(r"^b\d+$", re.IGNORECASE)
_B_DIVIDER_RE = re.compile(r"^(b\d+)_divider\.xhtml$", re.IGNORECASE)

_EXTERNAL_SCHEMES = ("http:", "https:", "mailto:", "data:", "ftp:", "ftps:")

# 属性名前加 (?<![-\w]) 负向断言：`\b` 挡不住 `data-id` / `data-src`
# （`-` 是非词字符，词边界依然成立），会把无关属性值一并改写。
# poster/object data 也是引用属性；srcset 是逗号列表，单独用 _SRCSET_RE 处理。
_ATTR_RE = re.compile(
    r'''(?P<attr>(?<![-\w])(?:href|src|xlink:href|poster|data)\s*=\s*)(?P<q>["'])(?P<val>.*?)(?P=q)''',
    re.IGNORECASE | re.DOTALL)
_SRCSET_RE = re.compile(
    r'''(?P<attr>(?<![-\w])srcset\s*=\s*)(?P<q>["'])(?P<val>.*?)(?P=q)''',
    re.IGNORECASE | re.DOTALL)
# 简介 HTML 判定：形如 <p> / </p> / <br/> / <img ...> 的标签才视为 HTML
_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][\w:-]*(?:\s[^<>]*)?/?>")
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


def _out_media_type(mt: str) -> str:
    """出包 media-type 归一：text/html 改标 application/xhtml+xml。

    EPUB3 内容文档只允许 application/xhtml+xml（text/html 是 EPUB2 概念，
    出包 version=3.0 后原样保留会被 epubcheck 判违规）。只改 OPF 描述、
    不动文档字节（无损红线：内容是否良构 XML 是源书自带属性，不在此修）。
    """
    return "application/xhtml+xml" if mt == "text/html" else mt


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

    def _map_ref_value(val: str):
        """把单个引用值映射为新值；无需改写返回 None（保持原文）。"""
        low = val.lower()
        if "://" in val or low.startswith(_EXTERNAL_SCHEMES):
            return None
        if "#" in val:
            fpart, frag = val.split("#", 1)
        else:
            fpart, frag = val, None
        if not fpart:
            # 同文档片段：目标 id 未改名，这里原样保留
            return None
        if fpart.startswith("/"):
            new_name = _map_file(fpart)
            if new_name is None:
                warnings.append("无法解析的根引用：%s" % val)
                return None
            # 合成的相对路径按 URI 规则转义（目标名可能含空格/非 ASCII/#）
            out = _quote_href(_rel(new_name))
        else:
            old = _normalize_zip_path(fpart, old_dir)
            if not old or old.lower() not in lower_map:
                # 相对引用保持原样（结构保留即有效）；映射外引用仅提示
                if old and fpart not in ("", "."):
                    warnings.append("引用目标缺失，已保留原文：%s" % val)
                return None
            return None
        if frag:
            out += "#%s" % frag
        return out

    def _repl_attr(m):
        attr, q, val = m.group("attr"), m.group("q"), m.group("val")
        out = _map_ref_value(val)
        if out is None:
            return m.group(0)
        return "%s%s%s%s" % (attr, q, out, q)

    def _repl_srcset(m):
        attr, q, val = m.group("attr"), m.group("q"), m.group("val")
        if "data:" in val.lower():
            # data URI 负载自带逗号，按逗号切分会改坏 base64；整组跳过（不改写
            # 根绝对引用是保守取舍，避免产生损坏的 data URI）
            return m.group(0)
        changed = False
        parts = []
        for candidate in val.split(","):
            bits = candidate.strip().split(None, 1)
            if not bits:
                parts.append(candidate)
                continue
            url = bits[0]
            desc = (" " + bits[1]) if len(bits) > 1 else ""
            new_url = _map_ref_value(url)
            if new_url is not None:
                changed = True
                parts.append(new_url + desc)
            else:
                parts.append(candidate.strip())
        if not changed:
            return m.group(0)
        return "%s%s%s%s" % (attr, q, ", ".join(parts), q)

    def _rewrite_segment(segment: str) -> str:
        return _SRCSET_RE.sub(_repl_srcset, _ATTR_RE.sub(_repl_attr, segment))

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


def _parse_ncx_tree(ncx_text: str) -> list:
    """按 navPoint 嵌套结构提取 NCX 目录树（命名空间无关）。

    与 `_parse_ncx_pairs` 同一套 token 扫描/栈逻辑，区别是保留父子层级：
    每个节点 `{"label","src","children"}`。合并输出据此重建多级目录，
    不再把三级目录压平。
    """
    m = _NCX_NAVMAP_RE.search(ncx_text)
    if not m:
        return []
    roots = []
    stack = []
    for tok in _NCX_TOKEN_RE.finditer(m.group(1)):
        raw = tok.group(0)
        low = raw[:12].lower()
        if low.startswith("<navpoint"):
            node = {"label": "", "src": None, "children": []}
            if stack:
                stack[-1]["children"].append(node)
            else:
                roots.append(node)
            stack.append(node)
        elif low.startswith("</navpoint"):
            if stack:
                stack.pop()
        elif low.startswith("<navlabel"):
            if stack:
                label = _strip_tags(tok.group(1) or "")
                if label and not stack[-1]["label"]:
                    stack[-1]["label"] = label
        else:  # <content src="...">
            if stack and not stack[-1]["src"]:
                stack[-1]["src"] = tok.group(2)
    return roots


def _toc_nodes_from_tree(nodes: list, base_dir: str, lower_o2n: dict,
                         fallback_label: str) -> list:
    """把 NCX 树映射为新包内 TOC 节点，保留嵌套。

    映射失败/无 src 的分组节点不产出自身 navPoint（NCX DTD 要求 content），
    其子节点上提一级，避免生成非法或死链目录项。
    """
    out = []
    for node in nodes:
        kids = _toc_nodes_from_tree(node["children"], base_dir, lower_o2n,
                                    fallback_label)
        mapped = _map_toc_src(node["src"], base_dir, lower_o2n) if node["src"] else None
        if mapped:
            out.append((node["label"] or fallback_label,
                        mapped[0], mapped[1], kids))
        else:
            out.extend(kids)
    return out


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


# ---------------------------------------------------------------- 合集识别
# 目的：再次合并本工具产出的合集时，识别其内部叶子书并按叶子展开，
# 而不是把整个合集当成 1 本。新产物优先读 OPF marker；旧产物按
# dc:contributor + NCX 顶层分组 + bN/ 路径前缀做启发式识别。

def _xml_safe_text(value, max_len: int = 0) -> str:
    """去掉 XML 1.0 非法控制字符与孤立代理项；可选截断。

    marker/NCX 来自 EPUB 文件本身，可能被手工编辑或伪造。控制字符
    （如 U+0001）与孤立代理项会让写出的 XML 非法或在 UTF-8 编码时抛错，
    必须在进入分卷页/NCX/nav 之前清洗。
    """
    text = str(value or "").strip()
    out = []
    for char in text:
        code = ord(char)
        if code in (0x09, 0x0A, 0x0D):
            out.append(char)
        elif 0x20 <= code <= 0xD7FF:
            out.append(char)
        elif 0xE000 <= code <= 0xFFFD:
            out.append(char)
        elif 0x10000 <= code <= 0x10FFFF:
            out.append(char)
    text = "".join(out).strip()
    return text[:max_len] if max_len else text


def _normalize_merge_prefix(value) -> str:
    """校验并归一化 marker 中的子书路径前缀（必须安全、以 `/` 结尾）。"""
    prefix = str(value or "").strip().replace("\\", "/")
    if not prefix or not prefix.endswith("/") or prefix.startswith("/"):
        return ""
    if _is_traversal(prefix):
        return ""
    parts = prefix[:-1].split("/")
    if not parts or any(p in ("", ".", "..") for p in parts):
        return ""
    return prefix


def parse_merge_marker(opf_text: str):
    """解析 OPF 里的 mybooks:merge 标记；缺失/损坏/版本不符返回 None。"""
    match = _MERGE_MARKER_RE.search(opf_text or "")
    if not match:
        return None
    try:
        data = json.loads(html.unescape(match.group(1)).strip())
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("v") != MERGE_MARKER_VERSION:
        return None
    raw_books = data.get("books")
    if not isinstance(raw_books, list) or not (
            _MERGE_MIN_BOOKS <= len(raw_books) <= MERGE_MAX_BOOKS):
        return None
    books = []
    for item in raw_books:
        if not isinstance(item, dict):
            return None
        title = _xml_safe_text(item.get("title"), _MERGE_MARKER_TITLE_MAX)
        prefix = _normalize_merge_prefix(item.get("prefix"))
        if not prefix:
            return None
        books.append({"title": title, "prefix": prefix})
    return {"version": MERGE_MARKER_VERSION, "books": books}


def _build_merge_marker(books: list) -> str:
    """生成 marker JSON（紧凑、非 ASCII 原样保留）。"""
    payload = {"v": MERGE_MARKER_VERSION, "books": [
        {"title": _xml_safe_text(b.get("title"), _MERGE_MARKER_TITLE_MAX),
         "prefix": str(b.get("prefix") or "")}
        for b in (books or [])]}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _has_merger_contributor(opf_text: str) -> bool:
    """旧版产物识别：OPF 是否带 `MyBooks epub_merge` contributor。"""
    for match in re.finditer(
            r"<dc:contributor[^>]*>(.*?)</dc:contributor>",
            opf_text or "", re.IGNORECASE | re.DOTALL):
        if "mybooks epub_merge" in html.unescape(match.group(1)).strip().lower():
            return True
    return False


def _entry_b_prefix(name: str) -> str:
    """从 zip 条目名推断工具产物的书前缀。

    例：`b0/OEBPS/ch1.xhtml` → `b0/`；`b0/b0_divider.xhtml` → `b0/b0/`；
    `ch1.xhtml`（无前缀）→ ""。
    """
    parts = [p for p in (name or "").replace("\\", "/").split("/") if p]
    if not parts:
        return ""
    if _is_divider_name(name):
        divider = _B_DIVIDER_RE.match(parts[-1])
        return "/".join(parts[:-1] + [divider.group(1)]) + "/"
    segs = []
    for part in parts[:-1]:
        if not _B_PREFIX_SEG_RE.match(part):
            break
        segs.append(part)
    return ("/".join(segs) + "/") if segs else ""


def _common_b_prefix(prefixes: list) -> str:
    """多个 `bN/` 前缀的公共前缀（按路径段，大小写不敏感）。"""
    segs = [[s for s in (p or "").strip("/").split("/") if s]
            for p in prefixes if p]
    if not segs:
        return ""
    common = list(segs[0])
    for item in segs[1:]:
        idx = 0
        while idx < len(common) and idx < len(item):
            if common[idx].lower() != item[idx].lower():
                break
            idx += 1
        common = common[:idx]
        if not common:
            return ""
    return "/".join(common) + "/"


def _ncx_src_entry(node: dict, base_dir: str) -> str:
    """NCX 节点 src → 包内条目名（外链返回空）。"""
    src = (node.get("src") or "").strip()
    if not src or "://" in src or src.lower().startswith(_EXTERNAL_SCHEMES):
        return ""
    return _normalize_zip_path(src, base_dir)


def _node_b_prefix(node: dict, base_dir: str) -> str:
    """推断 NCX 节点对应的书前缀。

    优先取直接子节点 src 的公共 `bN/` 前缀（顶层合集节点因此得到 `b0/`，
    其子书节点得到 `b0/b0/`）；无子节点/子节点无前缀时退回自身 src。
    """
    kids = node.get("children") or []
    child_prefixes = []
    for kid in kids:
        entry = _ncx_src_entry(kid, base_dir)
        if entry:
            child_prefixes.append(_entry_b_prefix(entry))
    common = _common_b_prefix(child_prefixes)
    if common:
        return common
    entry = _ncx_src_entry(node, base_dir)
    return _entry_b_prefix(entry) if entry else ""


def _leaves_from_ncx_node(node: dict, base_dir: str, depth: int = 0,
                          entry_names=None) -> list:
    """把 NCX 节点递归拆成叶子书；识别依据是子节点前缀比父前缀更深。

    递归额外要求每个子前缀下存在 `bN_divider.xhtml`：正常书内部恰好有
    `b0/`、`b1/` 子目录时不会仅凭目录名被误拆成多本。
    """
    entry_names = entry_names or set()
    kids = node.get("children") or []
    own = _node_b_prefix(node, base_dir)
    if depth < MERGE_MAX_EXPAND_DEPTH and len(kids) >= 2 and own:
        kid_prefixes = [_node_b_prefix(kid, base_dir) for kid in kids]
        own_low = own.lower()
        deeper = all(
            p and p.lower().startswith(own_low) and len(p) > len(own)
            for p in kid_prefixes)
        unique = len({p.lower() for p in kid_prefixes}) == len(kid_prefixes)
        dividers = all(
            _is_tool_divider_path(p.rstrip("/") + "_divider.xhtml",
                                  entry_names)
            for p in kid_prefixes if p)
        if deeper and unique and dividers:
            leaves = []
            for kid in kids:
                leaves.extend(_leaves_from_ncx_node(
                    kid, base_dir, depth + 1, entry_names))
            return leaves
    return [{
        "title": _xml_safe_text(node.get("label"), _MERGE_MARKER_TITLE_MAX),
        "prefix": own,
        "toc_nodes": kids,
    }]


def _leaves_from_ncx(ncx_text: str, base_dir: str,
                     entry_names=None) -> list:
    leaves = []
    for root in _parse_ncx_tree(ncx_text):
        leaves.extend(_leaves_from_ncx_node(root, base_dir, 0, entry_names))
    return leaves


def _leaf_owns(prefix: str, name: str) -> bool:
    """条目是否归属该书前缀（含该书的旧分卷页）。"""
    p = (prefix or "").lower()
    n = (name or "").lower()
    if not p or not n:
        return False
    return n.startswith(p) or n == (p[:-1] + "_divider.xhtml")


def _divider_group_prefix(name: str) -> str:
    """`b0_divider.xhtml` → `b0/`；`b0/b1_divider.xhtml` → `b0/b1/`。

    只在“父目录全是 bN/ 段”时成立；`OEBPS/b1_divider.xhtml` 这类正文文件名
    不按分卷页处理。
    """
    if not _is_divider_name(name):
        return ""
    parts = [p for p in (name or "").replace("\\", "/").split("/") if p]
    divider = _B_DIVIDER_RE.match(parts[-1])
    return "/".join(parts[:-1] + [divider.group(1)]) + "/"


def _is_ancestor_divider(name: str, prefixes: list) -> bool:
    """祖先合集的分卷页不属于任何叶子，覆盖校验时忽略。"""
    group = _divider_group_prefix(name)
    if not group:
        return False
    low_group = group.lower()
    return any(p.lower().startswith(low_group) and p.lower() != low_group
               for p in prefixes)


def _is_divider_name(name: str) -> bool:
    """是否为工具产物的分卷页路径（父目录必须是 bN/ 段）。

    只看 basename 会把 `OEBPS/b1_divider.xhtml` 这类正常正文文件误判成
    分卷页；工具分卷页只会出现在包根或 `bN/` 目录下。
    """
    parts = [p for p in (name or "").replace("\\", "/").split("/") if p]
    if not parts or not _B_DIVIDER_RE.match(parts[-1]):
        return False
    return all(_B_PREFIX_SEG_RE.match(p) for p in parts[:-1])


def _is_tool_divider_path(name: str, entry_names) -> bool:
    low = (name or "").lower()
    return low in (entry_names or ()) and _is_divider_name(low)


def _validate_merge_leaves(leaves: list, spine_files: list) -> bool:
    """校验叶子前缀：数量/唯一性/每个 spine 条目归属恰好一本。"""
    if not (_MERGE_MIN_BOOKS <= len(leaves) <= MERGE_MAX_BOOKS):
        return False
    prefixes = [leaf.get("prefix") or "" for leaf in leaves]
    low = [p.lower() for p in prefixes]
    if any(not p for p in low) or len(set(low)) != len(low):
        return False
    for name in spine_files:
        owners = [p for p in low if _leaf_owns(p, name)]
        if len(owners) == 1:
            continue
        if _is_ancestor_divider(name, low):
            continue
        return False
    for prefix in low:
        own_divider = prefix[:-1] + "_divider.xhtml"
        owned = [name for name in spine_files if _leaf_owns(prefix, name)]
        # 只拥有本卷分卷页的叶子是坏结构：展开后无正文可写，会打断整次合并。
        # 同名前缀的其它正文文件（如 b0/b1_divider.xhtml）不算分卷页。
        if not any(name.lower() != own_divider for name in owned):
            return False
    return True


def _marker_books(marker: dict, ncx_text: str, ncx_base: str,
                  spine_files: list, entry_names=None) -> list:
    """marker 叶子 → 补全 spine_files 与 NCX 子树（按前缀匹配顶层节点）。

    marker 正常记录的是叶子；若该叶子节点下仍有更深的 ``bN/`` 子书证据
    （例如用 ``expand_merged=False`` 生成的嵌套产物），继续递归展开。
    """
    books = []
    roots = _parse_ncx_tree(ncx_text) if ncx_text else []
    root_map = {}
    for root in roots:
        prefix = _node_b_prefix(root, ncx_base)
        if prefix and prefix.lower() not in root_map:
            root_map[prefix.lower()] = root
    for marker_book in marker["books"]:
        prefix = marker_book["prefix"]
        node = root_map.get(prefix.lower())
        exact = node is not None
        if node is None:
            # 兼容 calibre 改写路径后前缀不完全一致：取包含关系最深者。
            # 但此时节点已未必是“整卷根”，只用于兜底、不拿它的 children 当 TOC。
            low = prefix.lower()
            candidates = [
                (p, root) for p, root in root_map.items()
                if p.startswith(low) or low.startswith(p)]
            if candidates:
                candidates.sort(key=lambda item: len(item[0]), reverse=True)
                node = candidates[0][1]
        sub = _leaves_from_ncx_node(
            node, ncx_base, 0, entry_names) if exact else []

        def _under_marker(leaf):
            p = leaf.get("prefix") or ""
            return bool(p) and p.lower().startswith(prefix.lower())

        if len(sub) >= 2 and all(_under_marker(leaf) for leaf in sub):
            for leaf in sub:
                leaf["spine_files"] = [
                    n for n in spine_files
                    if _leaf_owns(leaf.get("prefix") or "", n)]
            books.extend(sub)
            continue
        book = dict(marker_book)
        book["spine_files"] = [n for n in spine_files if _leaf_owns(prefix, n)]
        book["toc_nodes"] = (node.get("children") or []) if exact else []
        books.append(book)
    return books


def _legacy_books(ncx_text: str, ncx_base: str, spine_files: list,
                  entry_names=None) -> list:
    leaves = _leaves_from_ncx(ncx_text, ncx_base, entry_names)
    for idx, leaf in enumerate(leaves):
        if not leaf.get("title"):
            leaf["title"] = "分册%d" % (idx + 1)
        leaf["spine_files"] = [
            n for n in spine_files if _leaf_owns(leaf.get("prefix") or "", n)]
    return leaves


def _detect_merged_books(opf_text: str, ncx_text: str, ncx_base: str,
                         spine_files: list, want_nodes: bool = False,
                         entry_names=None):
    """识别 EPUB 是否为合集。返回 {"version", "books"} 或 None。

    marker 有效时以 marker 为准；否则在 contributor 命中时按 NCX 递归识别。
    任一校验失败都返回 None（调用方按普通单本处理，不冒险展开）。
    """
    spine_files = list(spine_files or [])
    entry_names = {str(n).lower() for n in (entry_names or ())}
    books = None
    version = MERGE_MARKER_VERSION
    marker = parse_merge_marker(opf_text)
    if marker:
        books = _marker_books(marker, ncx_text, ncx_base, spine_files,
                              entry_names)
        if not _validate_merge_leaves(books, spine_files):
            books = None
    if books is None:
        version = 0
        if _has_merger_contributor(opf_text) and ncx_text:
            books = _legacy_books(ncx_text, ncx_base, spine_files,
                                  entry_names)
    if books:
        for idx, book in enumerate(books):
            if not book.get("title"):
                book["title"] = "分册%d" % (idx + 1)
    if not books or not _validate_merge_leaves(books, spine_files):
        return None
    result = []
    for book in books:
        item = {"title": book.get("title") or "",
                "prefix": book.get("prefix") or ""}
        if want_nodes:
            item["toc_nodes"] = book.get("toc_nodes") or []
            item["spine_files"] = book.get("spine_files") or []
        result.append(item)
    detected = {"version": version, "books": result}
    if want_nodes:
        # 合并侧必须用与识别相同的 NCX 基址映射 toc_nodes（多 NCX 源）
        detected["ncx_base"] = ncx_base or ""
    return detected


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
               cover_name: str | None, cover_mt: str | None,
               merge_books: list | None = None) -> bytes:
    """组装新书 OPF（EPUB 3.0；href 统一 URI 转义）。

    3.0 而非 2.0：输出带 EPUB3 导航文档（`properties="nav"`），EPUB2 包
    不支持 nav 文件（epubcheck HTM-004），必须整体按 3.0 出包；NCX 保留并
    由 `spine toc="ncx"` 引用，兼容 EPUB2 阅读器。EPUB3 必需项：
    `dcterms:modified`；封面改用 `cover-image` 属性（EPUB2 的
    `<meta name="cover">`/`<guide>` 在 3.0 里不合法/已废弃，不再输出）。

    `merge_books` 非空时写入 mybooks:merge 标记：后续再次合并本产物时
    直接按叶子书展开，不再依赖 NCX 启发式。
    """
    creators = "".join(
        "<dc:creator>%s</dc:creator>" % html.escape(a)
        for a in meta.get("authors") or [])
    langs = "".join(
        "<dc:language>%s</dc:language>" % html.escape(lang)
        for lang in meta.get("languages") or ["zho"])
    subjects = "".join(
        "<dc:subject>%s</dc:subject>" % html.escape(t)
        for t in meta.get("tags") or [])
    items = "".join(
        '<item id="%s" href="%s" media-type="%s"%s/>' % (
            iid, _xml_attr(_quote_href(href)), mt,
            ' properties="nav"' if href == "nav.xhtml" else "")
        for iid, href, mt in manifest)
    if cover_name:
        items += ('<item id="cover-image" href="%s" media-type="%s" '
                  'properties="cover-image"/>'
                  % (_xml_attr(_quote_href(cover_name)), cover_mt))
    refs = "".join('<itemref idref="%s"/>' % iid for iid in spine)
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    package_attrs = ('version="3.0" xmlns="http://www.idpf.org/2007/opf" '
                     'unique-identifier="merge-id"')
    if merge_books:
        package_attrs += ' prefix="%s"' % _xml_attr(MERGE_MARKER_PREFIX)
    head = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<package %s>" % package_attrs,
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">',
        '<dc:identifier id="merge-id">%s</dc:identifier>' % uid,
        "<dc:title>%s</dc:title>" % html.escape(meta.get("title") or ""),
        creators,
        "<dc:contributor>MyBooks epub_merge</dc:contributor>",
        langs,
        "<dc:description>%s</dc:description>" % html.escape(
            _strip_tags(meta.get("description") or "")),
        subjects,
        '<meta property="dcterms:modified">%s</meta>' % modified,
    ]
    if merge_books:
        head.append(
            '<meta property="%s">%s</meta>' % (
                MERGE_MARKER_PROPERTY,
                html.escape(_build_merge_marker(merge_books), quote=False)))
    if meta.get("publisher"):
        head.append("<dc:publisher>%s</dc:publisher>"
                    % html.escape(meta["publisher"]))
    head.append("</metadata>")
    head.append("<manifest>%s</manifest>" % items)
    head.append('<spine toc="ncx">%s</spine>' % refs)
    head.append("</package>")
    return "".join(head).encode("utf-8")


def _xml_attr(value: str) -> str:
    """XML 属性值转义（href 里已无裸 `&`，此处兜底引号/尖括号）。"""
    return html.escape(value or "", quote=True)


def _build_ncx(title: str, books_toc: list, uid: str) -> bytes:
    """组装新书 NCX：每源书一个父节点挂其条目，playOrder 全局重排。

    :param books_toc: [(book_title, (parent_path, parent_frag),
        [TOC 节点, ...]), ...]；TOC 节点 = (label, path, frag, [子节点...])，
        即源 NCX 的嵌套层级原样保留。路径均为新包内路径；开分卷页时父节点
        指向分卷页。路径与 fragment 分开传入（路径可能含 `#`）。
    """
    order = 0

    def _emit_nodes(nodes, bi):
        nonlocal order
        xml = []
        for label, path, frag, kids in nodes:
            order += 1
            cur = order
            xml.append(
                '<navPoint id="m%d_%d" playOrder="%d"><navLabel><text>%s</text>'
                '</navLabel><content src="%s"/>%s</navPoint>'
                % (bi, cur, cur, html.escape(label),
                   _xml_attr(_quote_toc_src(path, frag)),
                   "".join(_emit_nodes(kids, bi))))
        return xml

    navpoints = []
    for bi, (book_title, parent, nodes) in enumerate(books_toc):
        order += 1
        parent_order = order
        navpoints.append(
            '<navPoint id="m%d" playOrder="%d"><navLabel><text>%s</text></navLabel>'
            '<content src="%s"/>%s</navPoint>'
            % (bi, parent_order, html.escape(book_title),
               _xml_attr(_quote_toc_src(parent[0], parent[1])),
               "".join(_emit_nodes(nodes, bi))))
    head = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">',
        "<head>",
        '<meta name="dtb:uid" content="%s"/>' % _xml_attr(uid),
        '<meta name="dtb:depth" content="3"/>',
        '<meta name="dtb:totalPageCount" content="0"/>',
        '<meta name="dtb:maxPageNumber" content="0"/>',
        "</head>",
        "<docTitle><text>%s</text></docTitle>" % html.escape(title),
        "<navMap>%s</navMap></ncx>" % "".join(navpoints),
    ]
    return "".join(head).encode("utf-8")


def _build_nav(title: str, books_toc: list) -> bytes:
    """生成 EPUB3 导航文档（`properties="nav"`，与 NCX 同源同层级）。

    输出 OPF 仍为 EPUB2 风格，nav.xhtml 是给 EPUB3 阅读器的加分项；
    href 与 NCX 相同（路径已 URI 转义）。
    """
    def _emit_nodes(nodes):
        lis = []
        for label, path, frag, kids in nodes:
            sub = _emit_nodes(kids)
            lis.append('<li><a href="%s">%s</a>%s</li>' % (
                _xml_attr(_quote_toc_src(path, frag)), html.escape(label),
                ("<ol>%s</ol>" % sub) if sub else ""))
        return "".join(lis)

    books = []
    for book_title, parent, nodes in books_toc:
        books.append('<li><a href="%s">%s</a><ol>%s</ol></li>' % (
            _xml_attr(_quote_toc_src(parent[0], parent[1])),
            html.escape(book_title), _emit_nodes(nodes)))
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops">'
        "<head><title>%s</title></head><body>"
        '<nav epub:type="toc" id="toc"><h1>%s</h1><ol>%s</ol></nav>'
        "</body></html>" % (html.escape(title), html.escape(title), "".join(books))
    ).encode("utf-8")


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


def _inspect_merged_source(source):
    """读取源 EPUB 的 OPF/NCX/spine 并识别合集结构（含 NCX 子树）。

    识别失败/普通书返回 None；只读 container/OPF/NCX，不解压正文与图片。
    """
    try:
        with _ZipSource(source) as src:
            opf_path = _locate_opf(src)
            opf_text = _decode(src.read(opf_path))
            marker = parse_merge_marker(opf_text)
            if not marker and not _has_merger_contributor(opf_text):
                return None
            spine = _find_spine_entries(src)
            if not spine:
                return None
            ncx_path, ncx_text = _find_ncx_text(src, opf_path)
            # marker 自带标题/前缀，缺 NCX 时 TOC 走 spine 兜底；旧版必须靠 NCX
            if not ncx_path and not marker:
                return None
            ncx_base = (ncx_path.rsplit("/", 1)[0]
                        if ncx_path and "/" in ncx_path else "")
            return _detect_merged_books(
                opf_text, ncx_text or "", ncx_base, spine, want_nodes=True,
                entry_names=src)
    except Exception as err:
        logger.warning("[epub_merge] 合集源解析失败：%s", err)
        return None


def _build_merge_job(item: dict, expand_merged: bool = True) -> dict:
    """把一个选中输入变成 job：source + 一个或多个输出卷（segment）。"""
    source, size = _input_source(item)
    title = _xml_safe_text(item.get("title"), _MERGE_MARKER_TITLE_MAX)
    # 不相信调用方的缓存识别结果：加载期分析后源文件可能被替换（甚至同
    # 尺寸/同 mtime），必须以合并时实际文件重新识别，否则会被当单本漏展开。
    merged = _inspect_merged_source(source) if expand_merged else None
    segments = []
    if merged:
        for book in merged["books"]:
            prefix = book["prefix"]
            segments.append({
                "title": book.get("title") or "",
                "selector": {
                    "prefix": prefix,
                    "divider": prefix[:-1] + "_divider.xhtml",
                    # 用识别时实际读取的 NCX 基址，避免多 NCX 源映射分叉
                    "ncx_base": merged.get("ncx_base") or "",
                    "toc_nodes": book.get("toc_nodes") or [],
                },
            })
    if not segments:
        segments.append({"title": title, "selector": None})
    return {"source": source, "size": size, "title": title,
            "segments": segments}


def expand_merge_inputs(inputs: list, expand_merged: bool = True,
                        cancel_event=None) -> list:
    """归一化输入为 jobs；合集按叶子书拆成多个输出卷。

    :return: [{"source", "size", "title", "segments": [...]}, ...]。
        同一源只保留一份 source（展开不复制字节），segment 共享该 source。
    :raises ValueError: 展开后总卷数越界。
    :raises MergeCancelled: cancel_event 在预检阶段置位。
    """
    jobs = []
    for item in inputs:
        if cancel_event is not None and cancel_event.is_set():
            raise MergeCancelled("任务已取消")
        jobs.append(_build_merge_job(item, expand_merged))
    total = sum(len(job["segments"]) for job in jobs)
    if total < _MERGE_MIN_BOOKS:
        raise ValueError(
            "合集展开后不足 %d 本，请选择更多书籍" % _MERGE_MIN_BOOKS)
    if total > MERGE_MAX_BOOKS:
        raise ValueError(
            "合集展开后共 %d 本，超过单次 %d 本上限，请减少选择"
            % (total, MERGE_MAX_BOOKS))
    return jobs


def merge_epubs(inputs: list, meta: dict, options: dict | None = None):
    """按 `inputs` 顺序合并多本 EPUB；合集的叶子书自动展开为多卷。

    :param inputs: [{"data": bytes, "title": str} | {"path": str, "title": str},
        ...]，顺序即拼接顺序。`path` 模式逐本按需读取：峰值内存只与
        「单本最大条目 + 单本解压总量」相关，不再随源书总大小与输出大小增长。
    :param meta: {"title", "authors", "languages", "tags", "description",
        "publisher"}，缺失键用空值/缺省。
    :param options: {"divider": bool（默认 True）, "cover": {"data": bytes,
        "ext": str} | None, "out_path": str | None, "progress_cb": callable,
        "cancel_event": threading.Event-like | None,
        "expand_merged": bool（默认 True，内部测试/应急可关）}。cover 由工具层
        决议后传入原始字节；progress_cb(book_index, book_total) 按展开后的
        输出卷逐卷回调；cancel_event 每卷开始前检查，置位时抛 MergeCancelled；
        给定 out_path 时输出流式写入该文件并返回 None，否则返回合并结果字节。
    :raises ValueError: 本数越界 / 单本结构异常 / 输出超限。
    :raises MergeCancelled: cancel_event 置位。
    """
    options = options or {}
    divider = options.get("divider", True)
    cover = options.get("cover")
    out_path = options.get("out_path")
    progress_cb = options.get("progress_cb")
    cancel_event = options.get("cancel_event")
    expand_merged = coerce_bool(options.get("expand_merged"), True)
    if not isinstance(inputs, list) or not (_MERGE_MIN_BOOKS <= len(inputs) <= MERGE_MAX_BOOKS):
        raise ValueError("请选择 %d–%d 本书进行合并" % (_MERGE_MIN_BOOKS, MERGE_MAX_BOOKS))
    jobs = expand_merge_inputs(inputs, expand_merged=expand_merged,
                               cancel_event=cancel_event)
    total_input = sum(job["size"] for job in jobs)
    if total_input > MERGE_MAX_INPUT_TOTAL:
        raise ValueError("合集源文件总体积超过上限（2GB），请减少本数或分批合并")

    uid = "epubmerge-%s" % uuid.uuid4().hex
    if out_path:
        with open(out_path, "wb") as fh:
            _merge_into(fh, jobs, meta, divider, cover, uid,
                        progress_cb, cancel_event)
        result = None
        out_size = os.path.getsize(out_path)
    else:
        buf = io.BytesIO()
        _merge_into(buf, jobs, meta, divider, cover, uid,
                    progress_cb, cancel_event)
        result = buf.getvalue()
        out_size = len(result)
    if out_size > _MERGE_MAX_OUTPUT:
        raise ValueError("合并输出超过上限（1GB）")
    return result


def _merge_into(out, jobs: list, meta: dict, divider: bool,
                cover, uid: str, progress_cb=None, cancel_event=None) -> None:
    """流式合并主体：逐卷读取源条目并立即写入 `out`（zip 输出流）。

    jobs 由 `expand_merge_inputs` 生成：一个 job 对应一个选中源文件，
    其 segments 是该源要输出的卷（普通书 1 卷；合集按叶子 N 卷）。
    manifest / spine / TOC 只累积小结构（id 与路径字符串），条目字节不驻留。
    每卷开始前检查 cancel_event（置位抛 MergeCancelled）并回调 progress_cb。
    """
    manifest = []           # (id, href, media-type)
    spine = []              # manifest id 顺序
    # [(book_title, (parent_path, parent_frag), [TOC 节点, ...]), ...]
    # TOC 节点 = (label, path, frag, [子节点, ...])，保留源 NCX 嵌套层级
    books_toc = []
    # [{"title", "prefix"}]：写入 OPF mybooks:merge 标记，供下次再合并时展开
    books_meta = []
    warnings = []
    counter = 0
    total = sum(len(job["segments"]) for job in jobs)
    seg_index = 0

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

        for job in jobs:
            if cancel_event is not None and cancel_event.is_set():
                raise MergeCancelled("任务已取消")
            source = job["source"]
            source_title = (job.get("title") or "").strip() or "合集"
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
                    raise ValueError(
                        "书籍 [%s] 未定位到正文条目，无法合并" % source_title)

                lower_entries = src.lower_map()
                # 加密/DRM：正文或 rights.xml 存在 → 拒绝整本；仅字体混淆 → 剔除资源
                enc = _encryption_status(
                    src, [items[i][0] for i in ordered_ids if i in items])
                if enc and (enc["rights"] or enc["text"]):
                    raise ValueError(
                        "书籍 [%s] 含加密正文（DRM/内容加密），无法合并"
                        % source_title)
                enc_asset_reals = set()
                if enc and enc["other"]:
                    for target in enc["other"]:
                        real = lower_entries.get(target.lower())
                        if real:
                            enc_asset_reals.add(real)
                            warnings.append(
                                "[%s] 混淆字体已剔除（无法还原）：%s"
                                % (source_title, real))
                # EPUB3 nav 文档按目录处理：不进 spine / manifest / 散件，
                # 残留引用走「目标缺失」告警而非静默死链
                nav_reals = {lower_entries[n] for n in nav_names
                             if n in lower_entries}
                for real in nav_reals:
                    warnings.append("[%s] EPUB3 nav 目录页不进正文：%s"
                                    % (source_title, real))
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
                    warnings.append("[%s] 链接列表目录页不进正文：%s"
                                    % (source_title, real))
                skip_reals = nav_reals | link_toc_reals | enc_asset_reals

                # 源 NCX 只解析一次：普通书整树映射，合集按叶子子树映射。
                # 合集 selector 已带识别时的 ncx_base 与 toc_nodes，无需再读 NCX。
                need_source_toc = any(
                    seg.get("selector") is None for seg in job["segments"])
                need_ncx_base = any(
                    seg.get("selector") and not seg["selector"].get("ncx_base")
                    for seg in job["segments"])
                ncx_path, ncx_text = None, None
                if need_source_toc or need_ncx_base:
                    # 取 manifest 中第一个 NCX（与旧实现一致）
                    for _iid, (name, mt) in items.items():
                        if mt != _NCX_MEDIA_TYPE:
                            continue
                        real = lower_entries.get(name.lower())
                        if real:
                            ncx_path = real
                            ncx_text = _decode(src.read(real))
                        break
                ncx_base = (ncx_path.rsplit("/", 1)[0]
                            if ncx_path and "/" in ncx_path else "")
                ncx_tree = (_parse_ncx_tree(ncx_text)
                            if need_source_toc and ncx_text else [])

                # 散件：manifest 未列但真实存在的非结构文件同样复制（防劣质书丢图），
                # media-type 按扩展名推断后注册进新 manifest，保证输出合法。
                structural = {"META-INF/container.xml", opf_path}
                structural.update(skip_reals)
                manifest_reals = set()
                for _iid, (name, mt) in items.items():
                    real = lower_entries.get(name.lower())
                    if not real:
                        continue
                    manifest_reals.add(real)
                    if mt == _NCX_MEDIA_TYPE:
                        structural.add(real)
                loose_names = []
                for name in src:
                    if name in manifest_reals or name in structural:
                        continue
                    if name == "mimetype" or name.startswith("META-INF/"):
                        # 容器级文件（mimetype/签名/加密/书签）不入合集
                        continue
                    loose_names.append(name)

                for seg in job["segments"]:
                    seg_index += 1
                    if cancel_event is not None and cancel_event.is_set():
                        raise MergeCancelled("任务已取消")
                    if progress_cb is not None:
                        progress_cb(seg_index, total)
                    prefix = "b%d" % (seg_index - 1)
                    book_title = _xml_safe_text(
                        seg.get("title"), _MERGE_MARKER_TITLE_MAX)
                    if not book_title:
                        book_title = "分册%d" % seg_index
                    selector = seg.get("selector")
                    seg_prefix = selector.get("prefix") if selector else None
                    if selector is not None and not seg_prefix:
                        raise ValueError(
                            "书籍 [%s] 的子书路径前缀缺失，无法展开" % book_title)

                    def _owned(real):
                        if selector is None:
                            return True
                        return _leaf_owns(seg_prefix, real)

                    def _new_name(real):
                        if selector is None:
                            return "%s/%s" % (prefix, real)
                        rel = (real[len(seg_prefix):]
                               if real.lower().startswith(seg_prefix.lower())
                               else real)
                        return ("%s/%s" % (prefix, rel)) if rel else ""

                    seg_divider = ((selector.get("divider") or "").lower()
                                   if selector else "")

                    def _is_old_divider(real):
                        # 只跳过本卷自己的旧分卷页；同名前缀的合法正文保留
                        return bool(seg_divider) and (real or "").lower() == seg_divider

                    # 本卷的旧→新路径映射：只含归属本卷的条目；
                    # 合集展开时旧分卷页不复制（统一重新生成）。
                    old_to_new = {}
                    for real in manifest_reals:
                        if not _owned(real) or real in skip_reals:
                            continue
                        if selector is not None and _is_old_divider(real):
                            continue
                        new_name = _new_name(real)
                        if new_name:
                            old_to_new[real] = new_name
                    for name in loose_names:
                        if not _owned(name):
                            continue
                        if selector is not None and _is_old_divider(name):
                            continue
                        new_name = _new_name(name)
                        if new_name:
                            old_to_new[name] = new_name
                    # TOC 映射必须在散件登记后重建：NCX/nav 可能引用 manifest
                    # 未列、靠散件兜底才进包的文件，用旧映射会把这类目录项丢掉
                    lower_o2n = {k.lower(): v for k, v in old_to_new.items()}

                    def _emit(real, new_name, mt):
                        """非 spine 资源：CSS 读入改写，其余直接流式转写。"""
                        if mt == "text/css" or real.lower().endswith(".css"):
                            writer.write(new_name, _maybe_rewrite_css(
                                real, mt, src.read(real),
                                real.rsplit("/", 1)[0] if "/" in real else "",
                                new_name.rsplit("/", 1)[0], old_to_new,
                                book_title, warnings))
                        else:
                            writer.write_stream(new_name, src.iter_chunks(real))

                    new_spine_docs = []
                    emitted = set()
                    relabeled = 0  # text/html 出包改标 application/xhtml+xml 的文档数
                    for iid in ordered_ids:
                        name, mt = items[iid]
                        real = lower_entries.get(name.lower())
                        if not real:
                            warnings.append("[%s] 正文条目缺失，已跳过：%s"
                                            % (book_title, name))
                            continue
                        if not _owned(real):
                            continue
                        if name.lower() in nav_names or real in skip_reals:
                            continue
                        # 合集展开时旧分卷页只是边界标记，不复制、不告警
                        if selector is not None and _is_old_divider(real):
                            continue
                        new_name = old_to_new.get(real)
                        if not new_name:
                            warnings.append(
                                "[%s] 正文条目不在子书范围内，已跳过：%s"
                                % (book_title, name))
                            continue
                        # 同一文件被多条 itemref 别名引用：只登记一次，
                        # 防重复 manifest/spine
                        if new_name in emitted:
                            continue
                        raw = src.read(real)
                        if mt in _TEXT_MEDIA_TYPES:
                            text = _decode(raw)
                            old_dir = real.rsplit("/", 1)[0] if "/" in real else ""
                            new_text, warns = _rewrite_doc_refs(
                                text, old_dir, new_name.rsplit("/", 1)[0],
                                old_to_new)
                            for w in warns:
                                warnings.append("[%s] %s" % (book_title, w))
                            # 文档所在旧目录：以该文档自身目录为准，而非 OPF 目录
                            writer.write(new_name,
                                         _normalize_xml_encoding(new_text)
                                         .encode("utf-8"))
                        else:
                            writer.write(new_name, _maybe_rewrite_css(
                                real, mt, raw,
                                real.rsplit("/", 1)[0] if "/" in real else "",
                                new_name.rsplit("/", 1)[0], old_to_new,
                                book_title, warnings))
                        emitted.add(new_name)
                        mid = _next_id()
                        mt_out = _out_media_type(mt)
                        relabeled += mt_out != mt
                        manifest.append((mid, new_name, mt_out))
                        spine.append(mid)
                        new_spine_docs.append(new_name)

                    if not new_spine_docs:
                        raise ValueError(
                            "书籍 [%s] 正文条目全部缺失，无法合并" % book_title)

                    # manifest 非 spine 资源（CSS/图/字体）原样收录；源 NCX 与
                    # 目录页除外（已被合并后的 toc.ncx 取代）
                    for _iid, (name, mt) in items.items():
                        if mt == _NCX_MEDIA_TYPE or name.lower() in nav_names:
                            continue
                        real = lower_entries.get(name.lower())
                        if not real or real in skip_reals:
                            continue
                        if not _owned(real):
                            continue
                        new_name = old_to_new.get(real)
                        if not new_name or new_name in emitted:
                            continue
                        _emit(real, new_name, mt)
                        mt_out = _out_media_type(mt)
                        relabeled += mt_out != mt
                        manifest.append((_next_id(), new_name, mt_out))
                        emitted.add(new_name)

                    for name in loose_names:
                        if name == "mimetype":
                            continue
                        if not _owned(name):
                            continue
                        if selector is not None and _is_old_divider(name):
                            continue
                        new_name = old_to_new.get(name)
                        if not new_name:
                            continue
                        warnings.append("[%s] 散件已收录：%s"
                                        % (book_title, name))
                        guess_mt = _guess_media_type(name)
                        loose_mt = _out_media_type(guess_mt)
                        relabeled += loose_mt != guess_mt
                        _emit(name, new_name, loose_mt)
                        manifest.append((_next_id(), new_name, loose_mt))
                    if relabeled:
                        warnings.append(
                            "[%s] %d 个 text/html 文档已按 EPUB3 规范改标 "
                            "application/xhtml+xml" % (book_title, relabeled))

                    # 分卷页插到本卷首篇之前
                    div_name = None
                    if divider:
                        div_name = "%s_divider.xhtml" % prefix
                        writer.write(div_name, _build_divider(
                            book_title, seg_index - 1, total))
                        div_id = _next_id()
                        manifest.append((div_id, div_name,
                                         "application/xhtml+xml"))
                        first_mid = next(m0 for m0, h, _m in manifest
                                         if h == new_spine_docs[0])
                        spine.insert(spine.index(first_mid), div_id)

                    # TOC：合集取该叶子在源 NCX 中的子树；普通书取整树。
                    # 映射都在本卷 old_to_new 内，跨卷引用自然落空并被滤掉，
                    # 不会把别的书的目录项带进来。
                    if selector is not None:
                        raw_nodes = selector.get("toc_nodes") or []
                        toc_base = selector.get("ncx_base") or ncx_base
                    else:
                        raw_nodes = ncx_tree
                        toc_base = ncx_base
                    nodes = _toc_nodes_from_tree(
                        raw_nodes, toc_base, lower_o2n, book_title)
                    if not nodes:
                        nav_real = next((lower_entries[n] for n in nav_names
                                         if n in lower_entries), None)
                        if nav_real:
                            nav_base = (nav_real.rsplit("/", 1)[0]
                                        if "/" in nav_real else "")
                            for label, href in _parse_nav_pairs(
                                    _decode(src.read(nav_real))):
                                mapped = _map_toc_src(href, nav_base, lower_o2n)
                                if mapped:
                                    nodes.append((label or book_title,
                                                  mapped[0], mapped[1], []))
                            if nodes:
                                warnings.append(
                                    "[%s] 无 NCX 目录，已改用 EPUB3 导航"
                                    % book_title)
                    if not nodes:
                        # spine 兜底：条目名取文件名主干（排除目录页）
                        nodes = []
                        for doc in new_spine_docs:
                            label = posixpath.basename(doc).rsplit(".", 1)[0]
                            nodes.append((label or book_title, doc, None, []))
                        warnings.append(
                            "[%s] 无 NCX / EPUB3 导航，已降级为 spine 顺序"
                            % book_title)
                    # 父节点指向分卷页（开 divider 时点父节点先见卷名页），
                    # 否则指向首篇
                    parent = ((div_name, None) if divider
                              else (nodes[0][1], nodes[0][2]))
                    books_toc.append((book_title, parent, nodes))
                    books_meta.append({"title": book_title,
                                       "prefix": "%s/" % prefix})
                    # 输出条目闸：逐卷检查，超 ZIP 非 ZIP64 上限前提前失败
                    if writer.count > _MERGE_MAX_TOTAL_ENTRIES:
                        raise ValueError(
                            "合集输出条目过多（超过 %d 条），已超出常见阅读器的"
                            "支持范围，请分批合并" % _MERGE_MAX_TOTAL_ENTRIES)

        manifest.append(("ncx", "toc.ncx", _NCX_MEDIA_TYPE))
        manifest.append(("nav", "nav.xhtml", "application/xhtml+xml"))
        writer.write("content.opf",
                     _build_opf(meta, manifest, spine, uid, cover_name, cover_mt,
                                merge_books=books_meta))
        writer.write("toc.ncx",
                     _build_ncx(meta.get("title") or "", books_toc, uid))
        writer.write("nav.xhtml",
                     _build_nav(meta.get("title") or "", books_toc))
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
    无 EPUB3 不允许的 text/html 内容文档 / guide 引用存在 /
    dc:title 非空 / NCX 良构且 playOrder 唯一。
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
        if item.get("media-type") == "text/html":
            # EPUB3 内容文档只允许 application/xhtml+xml（出包侧已归一，
            # 这里守门防回归）
            raise ValueError("输出含 EPUB3 不允许的 text/html 文档：%s" % href)

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
