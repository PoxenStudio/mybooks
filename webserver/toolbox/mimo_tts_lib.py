# -*- coding: utf-8 -*-
"""mimo_tts 纯逻辑库：EPUB / TXT 章节提取（不依赖 MyBooks，可独立测试）。

从 ``mimo_tts.py`` 抽出的提取层，供 TTS 合成前把书籍文件切成章节列表，
每章形如 ``{"title": str, "text": str}``（EPUB TOC 提取另带 ``href``）；
正文为空的章节由调用方过滤。

EPUB
    优先按 TOC（NCX / nav）取章节；TOC 覆盖的正文不足一半时（典型：TOC 只
    登记了纯图片扉页 / 只有一个字的标题页 / 目录页——calibre 转换无标题层级
    书时的常见产物），把**未被 TOC 覆盖**的 spine 文档补成章节。合并时按
    spine 阅读顺序插入，TOC 章节保留原位置与原标题，不会把补扫章节一律排到
    书尾。TOC href 与 manifest href 在百分号编码 / 目录前缀上不一致时逐级
    放宽匹配。

TXT
    自动探测编码（复用 chinese_converter 的 ``detect_encoding``），
    按行首「第X章 / Chapter N / 序章|楔子|…」标题切章（标题行不含句末
    标点，防正文长句误切）；识别不到标题时整本作为单章。首个标题前的
    开头段（≥ ``TXT_PRELUDE_MIN_CHARS`` 字符）作为「开头」一章保留，
    避免丢失书籍简介等内容。整文件读取前有 ``MAX_TXT_BYTES`` 上限，
    防止超大文件读取 / 解码 / 切章时内存放大数倍。
"""

import logging
import os
import posixpath
import re
from pathlib import Path
from urllib.parse import unquote

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

from webserver.toolbox.chinese_converter.epub_converter import detect_encoding

logger = logging.getLogger(__name__)

# 「第X回/部/集…」后紧跟这些字时多半是普通词（第一回合、第三部队、第三节目），
# 不当作章节标题。带分隔符的（第二回 大闹天宫）不受影响
_UNIT_CONTINUATION = "合来去队分门部长署位落集目日奏约曲电作"

# 行首章节标题：第X章节卷回部篇集（允许全角数字与字间空格）/ Chapter N /
# 常见特殊章节名（独立成行或「词 + 空格/全角冒号 + 短标题」，防止
# 「楔子正文。」这类以特殊词开头的正文长句被误切；「番外」允许直接跟序号，
# 「番外 一 后日谈」这类中间带空格的多段标题也算）。仅作行首匹配，行中
# 出现不算；句末标点拦截见 _is_heading_line
TXT_HEADING_RE = re.compile(
    r"^\s*(?:"
    r"第\s*[0-9０-９一二三四五六七八九十百千万零两][0-9０-９一二三四五六七八九十百千万零两\s]*"
    r"[章节卷回部篇集](?![" + _UNIT_CONTINUATION + r"])"
    r"|(?i:chapter)\s+(?:[0-9０-９]+|[IVXLCDMivxlcdm]+)"
    r"|(?:序章|序言|引子|楔子|尾声|终章|后记)(?:[\s：:（(][^\s。！？!?…，、；]{0,30})?\s*$"
    r"|番外(?:篇)?(?:[\s：]?[0-9０-９一二三四五六七八九十]{1,3})?"
    r"(?:[\s：:（(][^\s。！？!?…，、；]{0,30})?\s*$"
    r")"
)
# 标题行长度上限：超过按正文段落处理，避免误切以「第X章」开头的长句
TXT_HEADING_MAX_LEN = 60
# 无分隔符的「第X章标题」中，标题部分的长度上限（「第一章大梦初醒」放行，
# 「第一章的内容我已经忘了」按正文处理）
TXT_HEADING_TITLE_MAX = 6
# 首个标题前内容作为「开头」章节的最小字符数（过滤纯书名 / 作者行）
TXT_PRELUDE_MIN_CHARS = 100
# TXT 整文件读取的大小上限：全文 bytes → str → 行列表 → 章节串的内存
# 放大约 4~5 倍，64MB 文件对应峰值 ~300MB，足以容纳任何实际书籍，
# 同时防住异常大文件把服务打挂
MAX_TXT_BYTES = 64 * 1024 * 1024
# TOC 覆盖度：TOC 覆盖的正文（或章节数）不足一半时，认为 TOC 不可信
# （只登记扉页 / 目录页 / 版权页），补扫 spine 文档。字数与篇数同时判定，
# 避免「两三个大章 + 几十个小章」被长章的字数掩盖
TOC_TEXT_COVERAGE_RATIO = 0.5
# TOC 判定「可信」后，仍未进 TOC 的文档达到这个字数才补成章节：
# 过滤版权行 / 制作说明这类零页，又不放过确实漏在目录外的正文
TRUSTED_MIN_DOC_CHARS = 500


def _document_items(book) -> dict:
    """全部内容文档，键为 manifest href（与 ebooklib item name 一致）。"""
    return {
        item.get_name(): item
        for item in book.get_items()
        if item.get_type() == ebooklib.ITEM_DOCUMENT
    }


def _basename_index(spine_items: dict) -> dict:
    """basename → [manifest 名]，供 TOC href 兜底匹配（避免每条都全量扫）。"""
    index = {}
    for name in spine_items:
        index.setdefault(posixpath.basename(unquote(name)), []).append(name)
    return index


def _nav_names(book) -> set:
    """EPUB2 guide 里登记的目录页（type=toc）在 manifest 中的文件名。"""
    names = set()
    for ref in getattr(book, "guide", None) or []:
        if not isinstance(ref, dict) or str(ref.get("type", "")).lower() != "toc":
            continue
        href = unquote((ref.get("href") or "").split("#")[0])
        if href:
            names.add(href)
            names.add(posixpath.basename(href))
    return names


# 常见导航页文件名（精确匹配，不用前缀——`naval_battle.xhtml` / `toc2.xhtml`
# 这类正文不能被误伤）
_NAV_FILENAMES = frozenset({
    "nav.xhtml", "nav.html", "nav.htm",
    "toc.xhtml", "toc.html", "toc.htm",
    "contents.xhtml", "contents.html",
    "toc_page.xhtml", "toc_page.html",
})


def _is_nav_document(name: str, nav_names=None) -> bool:
    """导航页判定：guide 登记的目录页，或文件名命中常见导航页名。

    只看文件名（不带目录），如 OEBPS/nav.xhtml 也要跳过；只用于**未被 TOC
    引用**的文档，TOC 明确登记的章节一律按正文处理。
    """
    if not name:
        return True
    base = posixpath.basename(name).lower()
    if nav_names and (name in nav_names or base in nav_names):
        return True
    return base in _NAV_FILENAMES


def _spine_documents(book) -> list:
    """按 spine 阅读顺序返回内容文档（跳过 linear="no"）；spine 不可用时退回 manifest 顺序。

    ``book.get_items()`` 是 manifest 顺序，与阅读顺序无关；补扫必须按 spine
    走，否则章节会跳着读（实测 spine=c3,c1,c2 时按 manifest 会出 c1,c2,c3）。
    """
    items = []
    for entry in book.spine or []:
        if isinstance(entry, (tuple, list)):
            idref = entry[0]
            linear = entry[1] if len(entry) > 1 else "yes"
            if str(linear).lower() == "no":
                continue  # 脚注 / 答案页等非线性内容，不念
        else:
            idref = entry
        item = book.get_item_with_id(idref)
        if item is not None and item.get_type() == ebooklib.ITEM_DOCUMENT:
            items.append(item)
    if items:
        return items
    return [it for it in book.get_items() if it.get_type() == ebooklib.ITEM_DOCUMENT]


def _resolve_toc(toc_items, chapters: list, seen: set) -> None:
    """把 ebooklib TOC 树摊平成 [{title, href}]。

    嵌套 Section（EPUB3 的 ``<span>卷名</span><ol>…``）自身没有 href，
    递归必须放在 href 判定之外，否则整棵子树会被丢掉。
    """
    for entry in toc_items:
        if isinstance(entry, tuple):
            link, sub = entry
            href = str(getattr(link, "href", "") or "").split("#")[0]
            if href and href not in seen:
                seen.add(href)
                chapters.append({"title": getattr(link, "title", "") or "", "href": href})
            if sub:
                _resolve_toc(sub, chapters, seen)
        elif getattr(entry, "href", ""):
            href = str(entry.href).split("#")[0]
            if href not in seen:
                seen.add(href)
                chapters.append({"title": getattr(entry, "title", "") or "", "href": href})


def _find_item(spine_items: dict, basename_index: dict, href: str):
    """TOC href → 内容文档匹配：精确 → URL 解码 → 唯一文件名兜底。

    部分制作工具写出的 TOC href 与 manifest href 在百分号编码 /
    目录前缀上不一致，逐级放宽以免章节文本丢失；同名文档多于一个时
    不猜（返回 None，交给补扫路径按 spine 补齐）。
    """
    item = spine_items.get(href)
    if item is not None:
        return item
    unquoted = unquote(href)
    if unquoted in spine_items:
        return spine_items[unquoted]
    matches = basename_index.get(posixpath.basename(unquoted)) or []
    return spine_items[matches[0]] if len(matches) == 1 else None


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


def _is_heading_line(line: str) -> bool:
    """行首标题判定：匹配 TXT_HEADING_RE、长度受限、不含句末标点。

    - 句末标点（含逗号、顿号、分号）拦截正文长句，如「第一章讲完了。大家
      休息。」「第二回合我们输了，只能认命」；「第一章大梦初醒」这类无分隔
      符短标题仍放行。
    - 无分隔符且标题部分超过 ``TXT_HEADING_TITLE_MAX`` 的按正文处理
      （「第一章的内容我已经忘了」）。
    - 英文「Chapter 1 of the book was boring」这种带全小写单词的按正文处理，
      Title Case 的「Chapter 1 The Beginning」仍是标题。
    """
    if len(line.strip()) > TXT_HEADING_MAX_LEN:
        return False
    match = TXT_HEADING_RE.match(line)
    if not match:
        return False
    rest = line[match.end():]
    if re.search(r"[。！？!?…，、；]", rest):
        return False
    if re.search(r"\b[a-z]{2,}\b", rest):
        return False
    if rest and not rest[0].isspace() and rest[0] not in "：:、" \
            and len(rest.strip()) > TXT_HEADING_TITLE_MAX:
        return False
    return True


def _is_trusted_toc(toc_text_len: int, toc_count: int,
                    rest_text_len: int, rest_count: int) -> bool:
    """TOC 覆盖是否够全：字数与篇数都要**超过**一半。

    边界取严格大于：刚好一半时按「不可信」处理，宁可多补几章也不要丢半本。
    """
    ratio = TOC_TEXT_COVERAGE_RATIO
    if rest_text_len * ratio >= toc_text_len * (1 - ratio):
        return False
    return rest_count * ratio < toc_count * (1 - ratio)


def extract_epub_chapters(epub_path: str) -> list:
    """EPUB → 章节列表。TOC 优先；TOC 之外仍有实质正文时按 spine 合并。"""
    book = epub.read_epub(epub_path)
    spine_items = _document_items(book)
    basename_index = _basename_index(spine_items)
    nav_names = _nav_names(book)

    # 先把 spine 文档解析成「manifest 名 → 正文」，TOC 与补扫共用同一份，
    # 避免两边口径不一致（TOC 指向 spine 外的文档不该算进覆盖率）。
    # 导航页不参与覆盖率统计，但 TOC 明确引用的文档一律信任（哪怕名字像导航页）
    spine_docs = _spine_documents(book)
    text_by_name = {it.get_name(): _soup_text(it.get_content()) for it in spine_docs}

    # 空 navMap 时 ebooklib 会返回单个 Link 而非列表（0.19 实测），统一包成列表
    toc = book.toc
    if toc and not isinstance(toc, (list, tuple)):
        toc = [toc]

    entries, seen = [], set()
    _resolve_toc(toc or [], entries, seen)

    toc_by_name = {}
    for ch in entries:
        item = _find_item(spine_items, basename_index, ch["href"])
        name = item.get_name() if item is not None else None
        if name is None or name not in text_by_name or name in toc_by_name:
            # 解析失败 / 指向 spine 外 / 同一文档写了两次：不进 TOC 章节表，
            # 正文由下面的补扫按阅读顺序补，标题与重复朗读都不会产生
            continue
        ch["href"] = name
        ch["text"] = text_by_name[name]
        toc_by_name[name] = ch

    rest_names = [n for n in text_by_name
                  if n not in toc_by_name and not _is_nav_document(n, nav_names)]
    toc_text_len = sum(len(ch["text"]) for ch in toc_by_name.values())
    rest_text_len = sum(len(text_by_name[n]) for n in rest_names)
    # 篇数只数「有正文」的 TOC 章：纯图片页 / 空章不该把覆盖率抬上去
    toc_count = sum(1 for ch in toc_by_name.values() if ch["text"].strip())
    trusted = _is_trusted_toc(toc_text_len, toc_count, rest_text_len, len(rest_names))

    # TOC 可信时不补零页（版权行 / 制作说明），但**实质正文**仍要补：
    # calibre 常把「正文不在 TOC 里」的书做成 TOC 覆盖大半、剩余几十万字
    # 完全不在目录里，只按「不足一半」判断会把后半本静默吞掉
    min_chars = TRUSTED_MIN_DOC_CHARS if trusted else 1
    supplements = [n for n in rest_names if len(text_by_name[n]) >= min_chars]
    if not supplements:
        return list(toc_by_name.values())  # 没有要补的：保持 TOC 顺序

    if trusted:
        logger.info(
            "[mimo_tts] TOC 之外仍有 %d 篇实质正文（%d 字），按 spine 合并：%s",
            len(supplements), sum(len(text_by_name[n]) for n in supplements), epub_path,
        )
    else:
        logger.warning(
            "[mimo_tts] TOC 覆盖不足（TOC %d 字/%d 章，未覆盖 %d 字/%d 章），按 spine 补扫：%s",
            toc_text_len, len(toc_by_name), rest_text_len, len(rest_names), epub_path,
        )

    # 按 spine 阅读顺序重建，TOC 章节插回原位（保留标题），补扫章节按位置插入；
    # 空文本（纯图片页）交给调用方过滤。spine 里重复的 itemref 只出一次
    chapters = []
    supplement_names = set(supplements)
    emitted = set()
    for item in spine_docs:
        name = item.get_name()
        if name in emitted:
            continue
        if name in toc_by_name:
            chapters.append(toc_by_name[name])
        elif name in supplement_names:
            chapters.append({"title": Path(name).stem, "href": name, "text": text_by_name[name]})
        else:
            continue
        emitted.add(name)
    return chapters


def extract_txt_chapters(txt_path: str) -> list:
    """TXT → 章节列表。行首标题切章；无标题整本单章。

    - 编码自动探测（UTF-16/32 BOM 与无 BOM → UTF-8 → GB18030 / BIG5）；
    - 首个标题前的内容满 ``TXT_PRELUDE_MIN_CHARS`` 记为「开头」一章；
    - 标题行本身保留在章节正文中（朗读时念出章节名）。
    """
    size = os.path.getsize(txt_path)
    if size > MAX_TXT_BYTES:
        # 先看文件大小再读：read_bytes() 会把整本读进内存，
        # 上限检查放在读之后等于没防住超大文件
        raise ValueError(
            "TXT 文件过大（%dMB > 上限 %dMB），无法转换"
            % (size // (1024 * 1024), MAX_TXT_BYTES // (1024 * 1024))
        )
    data = Path(txt_path).read_bytes()
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
