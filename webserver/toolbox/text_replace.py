# -*- coding: utf-8 -*-
"""正文查找替换工具

对书籍的 TXT / EPUB 格式执行正文级字符串替换（支持普通文本与正则两种模式），
以「生成新书」模式入库，原书零改动。

- **TXT**：检测编码 → str 层替换 → 原编码写回（UTF-16/32 按 BOM 字节序并保留 BOM）
  → 新书入库；
- **EPUB**：zipfile 遍历（container → OPF → xhtml 条目）逐文件 str 替换，
  未修改条目字节原样保留，mimetype 置首且 ZIP_STORED 规范重写 → 新书入库。
  container / OPF 按规范 XML 解析（ElementTree 优先、正则兜底），href 按 URI
  unquote 后与 zip 条目名比对，单引号属性 / 百分号编码文件名均可定位。

对外接口：
- :meth:`preview` 同步返回匹配数 + 上下文样本 + 正则错误；
- :meth:`run` 后台执行替换并入库（未命中任何匹配时不生成新书）。

@author: 黏菌, 2026
"""
import codecs
import logging
import os
import re
import threading
import time
import traceback
import xml.etree.ElementTree as ET
import zipfile
from typing import Callable, Iterator, List, Optional, Tuple
from urllib.parse import unquote

from webserver.i18n import _
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver.toolbox.base_tool import BaseTool

from webserver.toolbox.utils import book_utils
from webserver.toolbox.utils import encoding_detect

# EPUB 文本条目（正文）的 media-type
_TEXT_MEDIA_TYPES = ("application/xhtml+xml", "text/html")
# 以下正则仅作非良构 OPF 的兜底解析（ET 解析失败时启用），属性单双引号都认；
# 负向环视避免把 data-href 之类的属性误当 href
_ITEM_RE = re.compile(r"<item\b[^>]*?>", re.IGNORECASE)
_ITEM_HREF_RE = re.compile(r"""(?<![\w-])href\s*=\s*(?:"([^"]+)"|'([^']+)')""", re.IGNORECASE)
_ITEM_MT_RE = re.compile(r"""(?<![\w-])media-type\s*=\s*(?:"([^"]+)"|'([^']+)')""", re.IGNORECASE)
_FULL_PATH_RE = re.compile(r"""(?<![\w-])full-path\s*=\s*(?:"([^"]+)"|'([^']+)')""", re.IGNORECASE)

SAMPLE_CTX = 50   # 预览上下文（前后各 N 字符）
SAMPLE_MAX = 5    # 预览样本条数上限
PREVIEW_LIMIT = 200000  # 预览统计 / 采样的最大字符数（防病态正则 / 超大书卡死请求线程）


class TextReplaceTool(BaseTool):
    """对指定书籍的 TXT / EPUB 格式执行正文查找替换。"""

    service_item_name = "正文查找替换"

    _run_lock = threading.Lock()
    _last_task_id: Optional[int] = None

    @classmethod
    def is_running(cls) -> bool:
        task = cls.get_last_task()
        return bool(task and task.get("status") == BackgroundTask.STATUS_RUNNING)

    @classmethod
    def get_last_task(cls) -> Optional[dict]:
        if cls._last_task_id is None:
            return None
        return BackgroundService().get_task(cls._last_task_id)

    @staticmethod
    def info() -> dict:
        return {
            "tool_id": "text_replace",
            "name": "正文查找替换",
            "description": "对 TXT / EPUB 正文执行查找替换（支持正则），生成新书",
            "revision": "0.1.0",
            "author": "黏菌",
            "publish_date": "2026-08-09",
        }

    # ------------------------------------------------------------------ 工具

    @staticmethod
    def _compile(pattern: str, replacement: str, use_regex: bool):
        """编译替换规则。返回 (apply_fn, regex_error)。

        ``apply_fn(text) -> (new_text, count)``；编译失败时 apply_fn 为 None，
        错误信息写入 ``regex_error``。
        """
        if not pattern:
            return None, _("查找内容不能为空")
        if use_regex:
            try:
                rx = re.compile(pattern)
            except re.error as err:
                return None, _("正则表达式错误：%s") % err
            return (lambda text: rx.subn(replacement, text)), None
        return (lambda text: (text.replace(pattern, replacement),
                              text.count(pattern))), None

    @staticmethod
    def _sample_from(text: str, idx: int, length: int) -> dict:
        """构造单条上下文样本（pre / match / post 三段，前端直接渲染高亮）。"""
        lo, hi = max(0, idx - SAMPLE_CTX), min(len(text), idx + length + SAMPLE_CTX)
        return {
            "index": idx,
            "pre": text[lo:idx],
            "match": text[idx:idx + length],
            "post": text[idx + length:hi],
        }

    @staticmethod
    def _scan_samples(text: str, pattern: str, use_regex: bool, cap: int = SAMPLE_MAX):
        """单次扫描统计命中数并收集上下文样本，避免预览时对全文重复扫描。

        普通模式按非重叠匹配（与 ``str.replace`` / ``str.count`` 一致）；
        正则模式单趟 ``finditer`` 同时计数与采样。

        :return: (count, samples)
        """
        samples = []
        if use_regex:
            rx = re.compile(pattern)
            count = 0
            for m in rx.finditer(text):
                count += 1
                if len(samples) < cap:
                    samples.append(TextReplaceTool._sample_from(
                        text, m.start(), m.end() - m.start()))
            return count, samples
        if not pattern:
            return 0, samples
        count = 0
        start = 0
        while True:
            idx = text.find(pattern, start)
            if idx < 0:
                break
            count += 1
            if len(samples) < cap:
                samples.append(TextReplaceTool._sample_from(text, idx, len(pattern)))
            start = idx + max(1, len(pattern))
        return count, samples

    @staticmethod
    def _collect_samples(text: str, pattern: str, use_regex: bool) -> List[dict]:
        """收集匹配上下文样本，用于预览。"""
        _, samples = TextReplaceTool._scan_samples(text, pattern, use_regex)
        return samples

    # ------------------------------------------------------------ 预览（同步）

    @AsyncService.register_function
    def preview(self, book_id: int, pattern: str, replacement: str, use_regex: bool,
                fmt: Optional[str] = None) -> dict:
        """同步返回匹配数 + 上下文样本 + 正则错误。

        :param book_id:    Calibre 书籍 ID。
        :param pattern:    查找内容（普通文本或正则表达式）。
        :param replacement: 替换内容。
        :param use_regex:  是否按正则解析 pattern。
        :param fmt:        指定格式（TXT / EPUB，大写）；不指定时自动选择（EPUB 优先）。
        :return dict: ``format``（TXT / EPUB）/ ``matches`` / ``samples`` /
            ``regex_error`` / ``truncated``（是否因超过 PREVIEW_LIMIT 只统计了前缀）。
        :raises RuntimeError: 书籍不存在 / 无 TXT、EPUB 格式 / 指定格式缺失 / 文件缺失。
        """
        apply_fn, regex_error = self._compile(pattern, replacement, use_regex)
        if apply_fn is None:
            return {"format": None, "matches": 0, "samples": [], "regex_error": regex_error,
                    "truncated": False}

        fmt, texts = self._load_texts(book_id, fmt)
        total = 0
        samples: List[dict] = []
        truncated = False
        offset = 0
        for full_text in texts:
            if len(full_text) > PREVIEW_LIMIT:
                truncated = True
            text = full_text[:PREVIEW_LIMIT]
            count, entry_samples = self._scan_samples(text, pattern, use_regex,
                                                      cap=SAMPLE_MAX - len(samples))
            total += count
            for s in entry_samples:
                s["index"] += offset
                samples.append(s)
            if len(samples) >= SAMPLE_MAX:
                break
            offset += len(full_text)
        return {"format": fmt, "matches": total, "samples": samples,
                "regex_error": None, "truncated": truncated}

    # ------------------------------------------------------------- 后台执行

    @AsyncService.register_service
    def run(self, book_id: int, pattern: str, replacement: str,
            use_regex: bool, suffix: str, user_id: int,
            fmt: Optional[str] = None) -> None:
        """后台执行查找替换并生成新书。

        未命中任何匹配（count == 0）时不生成新书——那只会得到一本与原书
        内容完全相同的副本，改为直接结束任务并发出提示。

        :param book_id:    Calibre 书籍 ID。
        :param pattern:    查找内容（普通文本或正则表达式）。
        :param replacement: 替换内容。
        :param use_regex:  是否按正则解析 pattern。
        :param suffix:     新书标题后缀（如「正文替换版」）。
        :param user_id:    操作用户 ID。
        :param fmt:        指定格式（TXT / EPUB，大写）；不指定时自动选择（EPUB 优先）。
        """
        if not TextReplaceTool._run_lock.acquire(blocking=False):
            logging.warning(
                "[TextReplaceTool] Already running, skipping run for book_id=%d [uid:%d]",
                book_id, user_id,
            )
            return

        # create_task 等全部放入 try：若中途抛异常，finally 仍会释放锁
        task_id = None
        error_message = None
        book_title = "Unknown"

        try:
            task_id = self.create_task(progress_data={"status": "starting", "book_id": book_id})
            TextReplaceTool._last_task_id = task_id
            progress_callback = self.make_progress_callback(task_id)

            apply_fn, regex_error = self._compile(pattern, replacement, use_regex)
            if apply_fn is None:
                error_message = regex_error
                logging.error("[TextReplaceTool] Bad rule: %s [uid:%d]", regex_error, user_id)
                return

            books = self.api.calibre.get_data_as_dict([book_id])
            if not books:
                error_message = _("书籍不存在：ID=%d") % book_id
                logging.error("[TextReplaceTool] Book not found: ID=%d [uid:%d]", book_id, user_id)
                return
            book = books[0]
            book_title = book.get("title", "Unknown")

            self.update_task_progress(task_id, 10, {"status": "running", "stage": "reading"})
            progress_callback(10)

            try:
                fmt = self._detect_format(book, fmt)
            except RuntimeError as err:
                error_message = str(err)
                logging.error("[TextReplaceTool] %s for book_id=%d [uid:%d]", error_message, book_id, user_id)
                return
            if fmt is None:
                error_message = _("该书籍没有 TXT 或 EPUB 格式，无法执行替换")
                logging.error("[TextReplaceTool] No TXT/EPUB format for book_id=%d [uid:%d]", book_id, user_id)
                return

            work_dir = self.get_work_dir(str(book_id))
            out_path = os.path.join(work_dir, "replaced_%d.%s" % (int(time.time()), fmt.lower()))

            self.update_task_progress(task_id, 30, {"status": "running", "stage": "processing"})
            progress_callback(30)

            if fmt == "TXT":
                count = self._replace_txt(book_id, apply_fn, out_path)
            else:
                count = self._replace_epub(book_id, apply_fn, out_path)

            if count == 0:
                self.cleanup_work_dir(work_dir)
                logging.info(
                    "[TextReplaceTool] No matches for %s book_id=%d, skip import [uid:%d]",
                    fmt, book_id, user_id,
                )
                self.add_msg(
                    user_id, "warning",
                    _(u"书籍 [%s] 未找到任何匹配内容，未生成新书") % book_title,
                )
                return

            self.update_task_progress(task_id, 80, {"status": "running", "stage": "saving"})
            progress_callback(80)

            new_book_id = book_utils.import_as_new_book(
                self, book_id, out_path, suffix or _("（正文替换版）"), user_id,
            )
            logging.info(
                "[TextReplaceTool] Replaced %s book_id=%d (%d hits) -> new book_id=%d [uid:%d]",
                fmt, book_id, count, new_book_id, user_id,
            )
            self.cleanup_work_dir(work_dir)

            self.add_msg(
                user_id, "success",
                _(u"书籍 [%s] 正文替换成功！命中 %d 处，已生成新书") % (book_title, count),
            )

        except Exception as err:
            error_message = str(err)
            self.add_msg(user_id, "danger", _(u"书籍 [%s] 正文替换失败！") % book_title)
            logging.error("[TextReplaceTool] Unexpected error for book_id=%d: %s", book_id, err)
            logging.error(traceback.format_exc())
        finally:
            # create_task 失败时 task_id 为 None，跳过任务收尾（锁仍必须释放）
            if task_id is not None:
                self.complete_task(task_id, error_message=error_message)
                if error_message is None:
                    self.update_task_progress(task_id, 100, {"status": "completed", "book_id": book_id})
            TextReplaceTool._run_lock.release()

    # ------------------------------------------------------------ 内部实现

    @staticmethod
    def _detect_format(book: dict, fmt: Optional[str] = None) -> Optional[str]:
        """确定可用格式。

        :param fmt: 指定格式（TXT / EPUB，大写）；仅在该格式存在时返回；
            指定但缺失时 raise RuntimeError（带明确提示）。
        :return: 未指定时按 EPUB 优先、TXT 其次自动选择；无可用格式返回 None。
        """
        fmts = [f.upper() for f in (book.get("available_formats") or [])]
        if fmt:
            fmt = fmt.upper()
            if fmt not in fmts:
                raise RuntimeError(_("该书籍没有 %s 格式，无法执行替换") % fmt)
            return fmt
        for fmt in ("EPUB", "TXT"):
            if fmt in fmts:
                return fmt
        return None

    def _load_texts(self, book_id: int, fmt: Optional[str] = None) -> Tuple[str, List[str]]:
        """读取书籍 TXT / EPUB 正文并返回 (fmt, 文本列表)。

        TXT 返回单段解码文本；EPUB 按 manifest 正文条目逐段返回，
        与 :meth:`_replace_epub` 的逐条目替换一一对应（预览命中数与实跑一致）。

        :param fmt: 指定格式（TXT / EPUB，大写）；不指定时自动选择（EPUB 优先）。
        """
        books = self.api.calibre.get_data_as_dict([book_id])
        book = books[0] if books else {}
        fmts = [f.upper() for f in (book.get("available_formats") or [])]
        if fmt:
            fmt = fmt.upper()
            if fmt not in fmts:
                raise RuntimeError(_("该书籍没有 %s 格式，无法执行替换") % fmt)
        else:
            fmt = "EPUB" if "EPUB" in fmts else ("TXT" if "TXT" in fmts else None)
        if fmt is None:
            raise RuntimeError(_("该书籍没有 TXT 或 EPUB 格式，无法执行替换"))
        if fmt == "TXT":
            txt_path = book_utils.get_book_file(self, book_id, "TXT")
            with open(txt_path, "rb") as f:
                data = f.read()
            text, enc_report = encoding_detect.decode_with_report(data)
            return "TXT", [text]
        epub_path = book_utils.get_book_file(self, book_id, "EPUB")
        # 预览只读正文条目，避免图片/字体等全量读入内存
        entries = _read_text_entries(epub_path)
        texts = [_decode_entry(entries[name])[0] for name in _find_text_entries(entries)]
        return "EPUB", texts

    def _replace_txt(self, book_id: int, apply_fn: Callable, out_path: str) -> int:
        """TXT：检测编码 → str 替换 → 原编码写回。返回命中数。

        替换文本可能包含原编码（如 BIG5）无法表示的字符，此时降级为 UTF-8 写回。
        """
        txt_path = book_utils.get_book_file(self, book_id, "TXT")
        with open(txt_path, "rb") as f:
            data = f.read()
        text, report = encoding_detect.decode_with_report(data)
        new_text, count = apply_fn(text)
        with open(out_path, "wb") as f:
            f.write(_encode_entry(new_text, report["encoding"]))
        return count

    def _replace_epub(self, book_id: int, apply_fn: Callable, out_path: str) -> int:
        """EPUB：container → OPF → xhtml 条目逐文件替换，规范重写 zip。返回命中数。"""
        epub_path = book_utils.get_book_file(self, book_id, "EPUB")
        entries = _read_zip_entries(epub_path)
        total = 0
        for name in _find_text_entries(entries):
            text, enc = _decode_entry(entries[name])
            new_text, count = apply_fn(text)
            if count > 0:
                entries[name] = _encode_entry(new_text, enc)
                total += count
        _write_zip(entries, out_path)
        return total


# --------------------------------------------------------------------- EPUB 助手


def _read_zip_entries(path: str) -> dict:
    """读取 zip 全部条目（跳过目录项），返回 {name: bytes}。

    仅在需要写回全部条目（run 替换）时使用；预览请用 :func:`_read_text_entries`。
    """
    entries = {}
    with zipfile.ZipFile(path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            entries[info.filename] = zf.read(info.filename)
    return entries


def _read_text_entries(path: str) -> dict:
    """仅读取正文相关条目（container / OPF / xhtml 文本条目），
    避免将图片、字体等非文本条目全量读入内存（预览场景）。"""
    entries = {}
    with zipfile.ZipFile(path, "r") as zf:
        all_names = [i.filename for i in zf.infolist() if not i.is_dir()]
        container_name = "META-INF/container.xml"
        if container_name in all_names:
            entries[container_name] = zf.read(container_name)
        opf_path = _opf_path_from_container(
            entries.get(container_name, b"").decode("utf-8", errors="replace"))
        if opf_path and opf_path in all_names:
            entries[opf_path] = zf.read(opf_path)
            # 正文条目尚未读入，用"名字视图"（空字节占位）让 manifest 定位可命中；
            # 已读入的 container/opf 保留真实内容
            view = dict(entries)
            view.update({n: b"" for n in all_names if n not in entries})
            for name in _find_text_entries(view):
                if name in all_names:
                    entries[name] = zf.read(name)
    return entries


def _decode_entry(data: bytes) -> Tuple[str, str]:
    """解码 EPUB 文本条目：UTF-8 优先，失败则用检测器兜底。

    :return: (text, encoding)，encoding 供原编码写回使用。
    """
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        text, report = encoding_detect.decode_with_report(data)
        return text, report["encoding"]


# 按 BOM 字节序精确报告的编码写回时需补对应 BOM（utf-16-le 等编解码器
# 本身不输出 BOM；用 "utf-16" 写回则恒为本机字节序，会把 UTF-16BE 翻转成 LE）
_BOM_PREFIX = {
    "utf-16-le": codecs.BOM_UTF16_LE,
    "utf-16-be": codecs.BOM_UTF16_BE,
    "utf-32-le": codecs.BOM_UTF32_LE,
    "utf-32-be": codecs.BOM_UTF32_BE,
}


def _encode_entry(text: str, enc: str) -> bytes:
    """按原编码写回；原编码无法表示文本（如 BIG5 遇简体/生僻字）时降级 UTF-8，
    并同步改写 XML 声明（如有），避免阅读器按声明解码出错。

    UTF-16/32 按检测报告的精确字节序（utf-16-le / utf-16-be / …）写回并保留 BOM。
    """
    if enc in ("utf-8", "utf-8-sig"):
        return text.encode(enc)
    try:
        if enc in _BOM_PREFIX:
            return _BOM_PREFIX[enc] + text.encode(enc)
        return text.encode(enc)
    except (UnicodeEncodeError, LookupError):
        return _set_xml_encoding(text, "utf-8").encode("utf-8")


def _set_xml_encoding(text: str, enc: str) -> str:
    """改写 XML 声明的 encoding（仅在声明存在时生效）。"""
    return re.sub(
        r'(<\?xml[^>]*encoding\s*=\s*")[^"]+(")',
        r"\g<1>%s\2" % enc, text, count=1, flags=re.IGNORECASE,
    )


def _quoted_value(match: Optional["re.Match"]) -> Optional[str]:
    """取单/双引号二选一分组捕获的属性值。"""
    if match is None:
        return None
    return match.group(1) if match.group(1) is not None else match.group(2)


def _find_text_entries(entries: dict) -> List[str]:
    """按 container.xml → OPF 的 manifest 定位正文（xhtml/html）条目名。

    container 与 OPF 都是规范 XML，优先 ElementTree 解析（单/双引号属性、
    命名空间、属性顺序均不影响），含未声明实体等非良构形态时回退正则。
    manifest href 是 URI（RFC 3986）：文件名含空格等字符时写作 %20，
    与 zip 内真实条目名比对前先 unquote；大小写不敏感兜底。
    """
    container = entries.get("META-INF/container.xml")
    if not container:
        return []
    opf_path = _opf_path_from_container(container.decode("utf-8", errors="replace"))
    if not opf_path:
        return []
    opf_path = _resolve_href(unquote(opf_path), "")
    # 大小写不敏感查找（zip 条目名大小写与 manifest 引用可能不一致）
    lower_map = {k.lower(): k for k in entries}
    opf_entry = opf_path if opf_path in entries else lower_map.get(opf_path.lower())
    if opf_entry is None:
        return []
    opf_text = _decode_entry(entries[opf_entry])[0]
    base_dir = opf_entry.rsplit("/", 1)[0] if "/" in opf_entry else ""
    names = []
    for href, mt in _iter_manifest_items(opf_text):
        if not href or (mt or "").lower() not in _TEXT_MEDIA_TYPES:
            continue
        name = _resolve_href(unquote(href), base_dir)
        real = lower_map.get(name.lower())
        if real and real not in names:
            names.append(real)
    return names


def _iter_manifest_items(opf_text: str) -> Iterator[Tuple[Optional[str], Optional[str]]]:
    """遍历 OPF manifest，逐项 yield (href, media-type)。

    ElementTree 解析成功即信任其结构（含「解析正常但无 manifest」的形态）；
    仅在解析失败（未声明实体等）时回退正则，正则对单/双引号属性都能识别。
    """
    try:
        root = ET.fromstring(opf_text)
    except ET.ParseError:
        for tag in _ITEM_RE.findall(opf_text):
            mh = _ITEM_HREF_RE.search(tag)
            mm = _ITEM_MT_RE.search(tag)
            yield _quoted_value(mh), _quoted_value(mm)
        return
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "manifest":
            continue
        for child in el:
            if child.tag.rsplit("}", 1)[-1] == "item":
                yield child.get("href"), child.get("media-type")


def _resolve_href(href: str, base_dir: str) -> str:
    """href → zip 条目名：剥 fragment/query、剥根斜杠、拼 base_dir、
    归一化 ./ 与 ../、反斜杠统一为正斜杠。"""
    href = href.split("#", 1)[0].split("?", 1)[0]
    if href.startswith("/"):
        href = href.lstrip("/")
    elif base_dir:
        href = "%s/%s" % (base_dir, href)
    parts = []
    for seg in href.replace("\\", "/").split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts)


def _opf_path_from_container(container_text: str) -> Optional[str]:
    """从 container.xml 提取 OPF 路径（首个 rootfile 的 full-path）。

    ElementTree 优先；非良构时回退正则（单/双引号都认）。
    """
    try:
        root = ET.fromstring(container_text)
    except ET.ParseError:
        return _quoted_value(_FULL_PATH_RE.search(container_text))
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == "rootfile" and el.get("full-path"):
            return el.get("full-path")
    return None


def _write_zip(entries: dict, out_path: str) -> None:
    """规范重写 zip：mimetype 置首且 ZIP_STORED，其余 DEFLATED。"""
    order = [k for k in entries if k != "mimetype"]
    with zipfile.ZipFile(out_path, "w") as zout:
        zout.writestr(zipfile.ZipInfo("mimetype"),
                      entries.get("mimetype", b"application/epub+zip"),
                      compress_type=zipfile.ZIP_STORED)
        for name in order:
            zout.writestr(name, entries[name], compress_type=zipfile.ZIP_DEFLATED)
