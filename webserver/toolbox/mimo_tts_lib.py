# -*- coding: utf-8 -*-
"""mimo_tts 纯逻辑库：EPUB / TXT 章节提取（不依赖 MyBooks，可独立测试）。

从 ``mimo_tts.py`` 抽出的提取层，供 TTS 合成前把书籍文件切成章节列表，
每章形如 ``{"title": str, "text": str}``（EPUB TOC 提取另带 ``href``）；
正文为空的章节由调用方过滤。

EPUB
    优先按 TOC（NCX / nav）取章节；TOC 指向的文档**全部无正文文本**时
    （典型：TOC 只登记了纯图片扉页，正文文档不在 TOC 里——calibre 转换
    无标题层级书时的常见产物），兜底扫描全部内容文档，避免
    「有正文却提取到 0 章」。TOC href 与 manifest href 在百分号编码 /
    目录前缀上不一致时逐级放宽匹配。

TXT
    自动探测编码（复用 chinese_converter 的 ``detect_encoding``），
    按行首「第X章 / Chapter N / 序章|楔子|…」标题切章（标题行不含句末
    标点，防正文长句误切）；识别不到标题时整本作为单章。首个标题前的
    开头段（≥ ``TXT_PRELUDE_MIN_CHARS`` 字符）作为「开头」一章保留，
    避免丢失书籍简介等内容。整文件解码前有 ``MAX_TXT_BYTES`` 上限，
    防止超大文件解码 / 切章时内存放大数倍。
"""

import posixpath
import re
from pathlib import Path
from urllib.parse import unquote

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

from webserver.toolbox.chinese_converter.epub_converter import detect_encoding

# 行首章节标题：第X章节卷回部篇集（允许全角数字与字间空格）/ Chapter N /
# 常见特殊章节名（独立成行或「词 + 空格/全角冒号 + 短标题」，防止
# 「楔子正文。」这类以特殊词开头的正文长句被误切）。仅作行首匹配，
# 行中出现不算；句末标点拦截见 _is_heading_line
TXT_HEADING_RE = re.compile(
    r"^\s*(?:"
    r"第\s*[0-9０-９一二三四五六七八九十百千万零两][0-9０-９一二三四五六七八九十百千万零两\s]*[章节卷回部篇集]"
    r"|(?i:chapter)\s+[0-9０-９]+"
    r"|(?:序章|序言|引子|楔子|尾声|终章|后记|番外)(?:[\s：]\S{0,30})?\s*$"
    r")"
)
# 标题行长度上限：超过按正文段落处理，避免误切以「第X章」开头的长句
TXT_HEADING_MAX_LEN = 60
# 首个标题前内容作为「开头」章节的最小字符数（过滤纯书名 / 作者行）
TXT_PRELUDE_MIN_CHARS = 100
# TXT 整文件解码的大小上限：全文 bytes → str → 行列表 → 章节串的内存
# 放大约 4~5 倍，64MB 文件对应峰值 ~300MB，足以容纳任何实际书籍，
# 同时防住异常大文件把服务打挂
MAX_TXT_BYTES = 64 * 1024 * 1024


def _document_items(book) -> dict:
    """全部内容文档，键为 manifest href（与 ebooklib item name 一致）。"""
    return {
        item.get_name(): item
        for item in book.get_items()
        if item.get_type() == ebooklib.ITEM_DOCUMENT
    }


def _resolve_toc(toc_items, chapters: list, seen: set, depth: int = 0) -> None:
    """把 ebooklib TOC 树摊平成 [{title, href}]（嵌套 Section 递归展开）。"""
    for entry in toc_items:
        if isinstance(entry, tuple):
            link, sub = entry
            if hasattr(link, "href") and link.href:
                href = link.href.split("#")[0]
                title = link.title or ""
                if href not in seen:
                    seen.add(href)
                    chapters.append({"title": title, "href": href})
                if sub:
                    _resolve_toc(sub, chapters, seen, depth + 1)
        elif hasattr(entry, "href") and entry.href:
            href = entry.href.split("#")[0]
            title = getattr(entry, "title", "") or ""
            if href not in seen:
                seen.add(href)
                chapters.append({"title": title, "href": href})


def _find_item(spine_items: dict, href: str):
    """TOC href → 内容文档匹配：精确 → URL 解码 → 唯一文件名兜底。

    部分制作工具写出的 TOC href 与 manifest href 在百分号编码 /
    目录前缀上不一致，逐级放宽以免章节文本丢失；同名文档多于一个时
    不猜（返回 None，保持原行为）。
    """
    item = spine_items.get(href)
    if item is not None:
        return item
    unquoted = unquote(href)
    if unquoted in spine_items:
        return spine_items[unquoted]
    base = posixpath.basename(unquoted)
    matches = [v for k, v in spine_items.items()
               if posixpath.basename(unquote(k)) == base]
    return matches[0] if len(matches) == 1 else None


def _soup_text(content) -> str:
    """HTML 文档 → 纯文本（剥 script/style/nav，只取 body，按非空行拼回）。

    只取 body：``<head><title>`` 等非正文文本不参与「章节是否有正文」
    判定，也绝不进入 TTS（ebooklib 0.19/0.20 的 get_content() 对规整
    XHTML 会重序列化丢掉 head，但 XML 解析失败时走 raw 兜底，head 仍在）。
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "nav"]):
        tag.decompose()
    root = soup.body or soup
    text = root.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _fill_text(chapters: list, spine_items: dict) -> None:
    for ch in chapters:
        item = _find_item(spine_items, ch["href"])
        ch["text"] = _soup_text(item.get_content()) if item else ""


def _is_heading_line(line: str) -> bool:
    """行首标题判定：匹配 TXT_HEADING_RE、长度受限、不含句末标点。

    句末标点拦截正文长句（如「第一章讲完了。大家休息。」）——标题行
    几乎不会带 。！？；「第一章大梦初醒」这类无分隔符标题仍放行。
    """
    if len(line.strip()) > TXT_HEADING_MAX_LEN:
        return False
    match = TXT_HEADING_RE.match(line)
    if not match:
        return False
    return not re.search(r"[。！？!?…]", line[match.end():])


def _collect_documents(book, chapters: list, seen: set) -> None:
    """兜底：扫描全部内容文档（跳过 nav/toc 导航页），标题取文件名 stem。"""
    for item in book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        name = item.get_name()
        # 导航页按文件名判断，与所在目录无关（如 OEBPS/nav.xhtml）
        if name and posixpath.basename(name).lower().startswith(("nav", "toc")):
            continue
        if name in seen:
            continue
        seen.add(name)
        chapters.append({"title": Path(name).stem, "href": name})


def extract_epub_chapters(epub_path: str) -> list:
    """EPUB → 章节列表。TOC 优先；TOC 提取不到任何正文时扫描全部文档。"""
    book = epub.read_epub(epub_path)
    spine_items = _document_items(book)

    # 空 navMap 时 ebooklib 会返回单个 Link 而非列表（0.19 实测），统一包成列表
    toc = book.toc
    if toc and not isinstance(toc, (list, tuple)):
        toc = [toc]

    chapters = []
    seen = set()
    _resolve_toc(toc or [], chapters, seen)
    _fill_text(chapters, spine_items)

    if not any(ch["text"].strip() for ch in chapters):
        # TOC 存在但指向的文档全部无正文（典型：TOC 只登记纯图片扉页，
        # 正文文档不在 TOC 里）——此时按 spine 文档兜底，否则有正文也提取到 0 章
        chapters = []
        seen = set()
        _collect_documents(book, chapters, seen)
        _fill_text(chapters, spine_items)

    return chapters


def extract_txt_chapters(txt_path: str) -> list:
    """TXT → 章节列表。行首标题切章；无标题整本单章。

    - 编码自动探测（UTF-16/32 BOM 与无 BOM → UTF-8 → GB18030 / BIG5）；
    - 首个标题前的内容满 ``TXT_PRELUDE_MIN_CHARS`` 记为「开头」一章；
    - 标题行本身保留在章节正文中（朗读时念出章节名）。
    """
    data = Path(txt_path).read_bytes()
    if len(data) > MAX_TXT_BYTES:
        raise ValueError(
            "TXT 文件过大（%dMB > 上限 %dMB），无法转换"
            % (len(data) // (1024 * 1024), MAX_TXT_BYTES // (1024 * 1024))
        )
    text = data.decode(detect_encoding(data), errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    heads = [i for i, line in enumerate(lines) if _is_heading_line(line)]

    chapters = []
    if not heads:
        body = text.strip()
        if body:
            chapters.append({"title": Path(txt_path).stem, "text": body})
        return chapters

    prelude = "\n".join(lines[:heads[0]]).strip()
    if len(prelude) >= TXT_PRELUDE_MIN_CHARS:
        chapters.append({"title": "开头", "text": prelude})
    for n, start in enumerate(heads):
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        body = "\n".join(lines[start:end]).strip()
        if body:
            chapters.append({"title": lines[start].strip(), "text": body})
    return chapters
