"""
epub_helper — EPUB 电子书生成模块。

独立于 MyBooks Toolbox，可直接 CLI 调用，也可被 book_source_tool 调用。
依赖: ebooklib, bs4, requests
"""

import hashlib
import logging
import os
import re
import urllib.parse
from typing import Optional

import requests
from bs4 import BeautifulSoup

try:
    from .rule_engine import build_source_session
except ImportError:  # standalone 运行（CLI / PyInstaller）
    try:
        from rule_engine import build_source_session
    except ImportError:
        build_source_session = None

try:
    from ebooklib import epub
except ImportError:
    epub = None

logger = logging.getLogger(__name__)

# 默认 CSS 样式
_DEFAULT_CSS = """
body {
    font-family: "Microsoft YaHei", "SimSun", serif;
    line-height: 1.8;
    padding: 1em;
    max-width: 800px;
    margin: 0 auto;
}
h1, h2, h3 {
    text-align: center;
    font-weight: bold;
}
p {
    text-indent: 2em;
    margin: 0.5em 0;
}
img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 1em auto;
}
"""


def _clean_html_for_epub(html_text: str) -> str:
    """清理 HTML 正文，使其适合 EPUB XHTML。

    关键：移除 XML 声明（lxml HTML parser 无法处理 Unicode 字符串中的 <?xml?>）。
    """
    if not html_text:
        return "<p></p>"
    text = html_text
    # 移除 XML 声明
    text = re.sub(r'^<\?xml[^>]*\?>', '', text).strip()
    # 用 bs4 清洗
    try:
        soup = BeautifulSoup(text, "lxml")
        # 移除 <script> 和 <style>
        for tag in soup.find_all(["script", "style"]):
            tag.decompose()
        body = soup.find("body")
        if body:
            inner = "".join(str(c) for c in body.children)
        else:
            inner = str(soup)
    except Exception:
        inner = text
    # 确保有段落包裹
    inner = inner.strip()
    if not inner.startswith("<"):
        inner = f"<p>{inner}</p>"
    return inner


def _make_chapter_xhtml(title: str, content_html: str, index: int) -> epub.EpubHtml:
    """生成单章 XHTML。"""
    chapter = epub.EpubHtml(
        title=title,
        file_name=f"chapter_{index:04d}.xhtml",
        lang="zh-CN",
    )
    chapter.content = (
        f"<h2>{title}</h2>\n{content_html}"
    )
    return chapter


def _browser_headers(referer: str = "") -> dict:
    """浏览器风格请求头（含 Referer）。"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/125.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": referer,
    }
    if not referer:
        headers.pop("Referer", None)
    return headers


def _make_session(referer: str = ""):
    """复用 rule_engine 的反爬会话（随机 UA + 浏览器头 + 可选 curl_cffi），失败退回 requests。"""
    if build_source_session is not None:
        try:
            return build_source_session(None), True
        except Exception:
            pass
    session = requests.Session()
    session.headers.update(_browser_headers(referer))
    return session, False


def _download_cover(session: requests.Session, cover_url: str,
                    referer: str = "") -> tuple[Optional[bytes], str]:
    """下载封面图片，返回 (图片字节, 扩展名)。不落盘，避免在输出目录留垃圾文件。"""
    if not cover_url:
        return None, ".jpg"
    try:
        headers = _browser_headers(referer)
        resp = session.get(cover_url, headers=headers, timeout=15)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        ext = ".jpg"
        if "png" in content_type:
            ext = ".png"
        elif "webp" in content_type:
            ext = ".webp"
        elif "gif" in content_type:
            ext = ".gif"
        logger.debug("封面已下载: %s (%d bytes)", cover_url, len(resp.content))
        return resp.content, ext
    except Exception as exc:
        logger.warning("封面下载失败: %s — %s", cover_url, exc)
        return None, ".jpg"


def _inline_images(soup, session: requests.Session, book, chapter_url: str = "",
                   referer: str = "", chapter_index: int = 0) -> None:
    """下载正文中的 <img> 并内嵌为 EpubImage，重写 src 为本地路径。

    chapter_index 用于生成全局唯一的 uid/文件名 —— 否则多章节有图的书
    会因每章都从 image_0000.jpg 开始而互相覆盖/uid 冲突。
    """
    if soup is None:
        return
    headers = _browser_headers(referer)
    for i, img in enumerate(soup.find_all("img")):
        src = (img.get("src") or "").strip()
        if not src or src.startswith("data:"):
            continue
        if not src.startswith(("http://", "https://", "//")):
            if chapter_url:
                src = urllib.parse.urljoin(chapter_url, src)
            else:
                continue
        if src.startswith("//"):
            src = "https:" + src
        try:
            resp = session.get(src, headers=headers, timeout=15)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("正文图片下载失败: %s — %s", src, exc)
            continue
        content_type = resp.headers.get("content-type", "image/jpeg")
        ext = ".jpg"
        if "png" in content_type:
            ext = ".png"
        elif "gif" in content_type:
            ext = ".gif"
        elif "webp" in content_type:
            ext = ".webp"
        elif "svg" in content_type:
            ext = ".svg"
        fname = f"ch{chapter_index:04d}_img{i:04d}{ext}"
        try:
            item = epub.EpubImage(
                uid=f"ch{chapter_index:04d}_img_{i}",
                file_name=f"images/{fname}",
                media_type=content_type.split(";")[0].strip() or "image/jpeg",
                content=resp.content,
            )
            book.add_item(item)
            img["src"] = f"images/{fname}"
        except Exception as exc:
            logger.warning("正文图片内嵌失败: %s — %s", src, exc)


def generate_epub(title: str, author: str,
                  chapters: list[dict],
                  cover_url: str = "",
                  output_path: str = "",
                  referer: str = "") -> str:
    """生成 EPUB 文件。

    Args:
        title: 书名
        author: 作者
        chapters: 章节列表，每项包含 title / content / (可选) url
        cover_url: 封面图 URL
        output_path: 输出路径（含 .epub 扩展名）。为空则自动生成。

    Returns:
        生成的 EPUB 文件路径
    """
    if epub is None:
        raise ImportError("需要安装 ebooklib: pip install ebooklib")

    if not output_path:
        safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)
        output_path = f"{safe_title}.epub"

    book = epub.EpubBook()

    # 元信息（identifier 用确定性 hash，避免内建 hash() 进程间随机导致同书不同 ID）
    book.set_identifier(f"book-{hashlib.md5((title + author).encode('utf-8')).hexdigest()[:16]}")
    book.set_title(title)
    book.set_language("zh-CN")
    book.add_author(author)

    # 默认 CSS
    css = epub.EpubItem(
        uid="style_default",
        file_name="style/default.css",
        media_type="text/css",
        content=_DEFAULT_CSS,
    )
    book.add_item(css)

    # 封面
    session, _ = _make_session(referer)

    if cover_url:
        cover_content, cover_ext = _download_cover(session, cover_url, referer)
        if cover_content:
            book.set_cover(f"images/cover{cover_ext}", cover_content)

    # 章节
    spine = ["nav"]
    toc = []

    for i, ch in enumerate(chapters, 1):
        ch_title = ch.get("title", f"第{i}章")
        ch_content = ch.get("content", "")
        ch_url = ch.get("url", "")
        ch_html = _clean_html_for_epub(ch_content)
        if ch_url:
            soup = BeautifulSoup(ch_html, "lxml")
            _inline_images(soup, session, book, chapter_url=ch_url, referer=referer,
                           chapter_index=i)
            ch_html = str(soup)
        chapter_item = _make_chapter_xhtml(ch_title, ch_html, i)
        chapter_item.add_item(css)
        book.add_item(chapter_item)
        spine.append(chapter_item)
        toc.append(chapter_item)

    book.toc = toc
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine

    # 输出
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    epub.write_epub(output_path, book, {})
    logger.info("EPUB 已生成: %s (%d chapters)", output_path, len(chapters))
    return output_path
