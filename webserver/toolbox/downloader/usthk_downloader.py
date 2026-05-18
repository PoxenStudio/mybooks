#!/usr/bin/env python3
import argparse
import concurrent.futures
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import threading
from http import cookiejar
from typing import Callable, List, Optional
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas


LOG_PREFIX = "[USTHK_DOWNLOADER]"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
TIMEOUT_SECONDS = 30
CHUNK_SIZE = 64 * 1024
RETRY_COUNT = 3


def _log(msg: str) -> None:
    print(f"{LOG_PREFIX} {msg}", flush=True)


def _extract_book_id(source_url: str) -> str:
    m = re.search(r"bib/([A-Za-z0-9_-]+)", source_url)
    return m.group(1) if m else ""


class UsthkDownloader:
    """HKUST 古书下载器，支持 hkust.edu.hk 及其子域名。"""

    def __init__(self, url: str):
        self.url = url
        self._opener = self._build_opener()
        self._title: str = ""
        self._author: str = ""
        self._canvases: Optional[List[str]] = None

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @staticmethod
    def is_supported_url(url: str) -> bool:
        """判断 URL 是否属于 hkust.edu.hk 及其子域名。"""
        host = urlparse(url).netloc.lower()
        return host == "hkust.edu.hk" or host.endswith(".hkust.edu.hk")

    def check_valid_url(self) -> dict:
        """访问 URL，获取书名和作者名并缓存。如无法获取书名则抛出异常。

        :return: {"title": str, "author": str}
        :raises ValueError: 如果页面中无法提取到书名
        """
        canvases, title, author = self.fetch_canvases()
        if not title:
            raise ValueError(f"无法从页面获取书名: {self.url}")
        self._title = title
        self._author = author
        self._canvases = canvases
        return {"title": title, "author": author}

    def set_overrides(self, title: str = "", author: str = "") -> None:
        """覆盖已检测到的书名和作者名（供 CLI 使用）。"""
        if title:
            self._title = title
        if author:
            self._author = author

    def preload(self, canvases: List[str], title: str, author: str) -> None:
        """预设书页列表及元数据，跳过自动抓取（供 CLI --title 覆盖使用）。"""
        self._canvases = canvases
        self._title = title
        self._author = author

    def download(
        self,
        output_dir: str,
        callback: Optional[Callable[[int], None]] = None,
        workers: int = 5,
        max_width: int = 1024,
        quality: float = 0.8,
        no_pdf: bool = False,
    ) -> str:
        """下载图片并合成 PDF，通过 callback 报告进度（0-100）。

        下载阶段占 0%–90%，PDF 合成阶段占 90%–100%。

        :param output_dir: 下载目录
        :param callback:   进度回调，参数为 0-100 的整数
        :param workers:    并发下载线程数（1-10）
        :param max_width:  图片最大宽度（像素）
        :param quality:    JPEG 质量 (0, 1]
        :param no_pdf:     为 True 时跳过 PDF 合成，仅保留图片
        :return:           生成的 PDF 路径；no_pdf=True 时返回空字符串
        """
        if self._canvases is None:
            self.check_valid_url()

        canvases = self._canvases
        assert canvases is not None
        title = self._title
        author = self._author
        total = len(canvases)
        if total == 0:
            raise RuntimeError("No files found")

        os.makedirs(output_dir, exist_ok=True)

        # 清理上次中断遗留的临时文件
        for fname in os.listdir(output_dir):
            if fname.startswith("usthk_") and fname.endswith(".part"):
                stale = os.path.join(output_dir, fname)
                os.remove(stale)
                _log(f"Removed stale temp file: {fname}")

        workers = max(1, min(workers, 10))
        _log(f"Start downloading {total} files, workers={workers}, max_width={max_width}, quality={quality}")

        completed_count = 0
        lock = threading.Lock()

        def download_one(args):
            nonlocal completed_count
            i, img_url = args
            ext = _file_extension_from_url(img_url)
            filename = f"{i:04d}{ext}"
            dest = os.path.join(output_dir, filename)
            if os.path.exists(dest):
                _log(f"[{i}/{total}] Already exists, skipped: {filename}")
            else:
                _log(f"[{i}/{total}] Downloading: {img_url}")
                tmp_path = ""
                try:
                    tmp_path = self._download_to_temp(img_url, output_dir)
                    _log(f"[{i}/{total}] Resizing: {filename}")
                    _resize_image_inplace(tmp_path, max_width, quality)
                    os.replace(tmp_path, dest)
                except Exception:
                    if tmp_path and os.path.exists(tmp_path):
                        os.remove(tmp_path)
                    raise

            with lock:
                completed_count += 1
                if callback:
                    callback(int(completed_count / total * 90))

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(download_one, (i, url)): i
                for i, url in enumerate(canvases, start=1)
            }
            for future in concurrent.futures.as_completed(futures):
                future.result()

        _log(f"All {total} files downloaded")

        if no_pdf:
            if callback:
                callback(100)
            return ""

        pdf_title = title or os.path.basename(os.path.abspath(output_dir))
        pdf_author = author or "佚名"
        pdf_path = os.path.join(output_dir, f"{pdf_title}.pdf")
        _create_pdf(output_dir, pdf_title, pdf_author, pdf_path, callback=callback)
        return pdf_path

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_opener(self):
        jar = cookiejar.CookieJar()
        return build_opener(HTTPCookieProcessor(jar))

    def _get_body(self, source_url: str) -> bytes:
        req = Request(source_url, headers={"User-Agent": USER_AGENT})
        with self._opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read()
            if resp.status != 200 or not body:
                raise RuntimeError(f"ErrCode:{resp.status}, body is empty")
            return body

    def fetch_canvases(self):
        """获取书页图片 URL 列表、书名和作者名（不做有效性校验）。"""
        parsed = urlparse(self.url)
        body = self._get_body(self.url).decode("utf-8", errors="ignore")

        title, author = _extract_book_info(body)

        matches = re.findall(r"view_book\([\"'](\S+)[\"']", body)
        if not matches:
            raise RuntimeError("Canvas not found")

        canvases: List[str] = []
        for source_path in matches:
            api_url = (
                f"https://{parsed.netloc}/bookreader/getfilelist.php?"
                f"{urlencode({'path': source_path})}"
            )
            payload = json.loads(self._get_body(api_url).decode("utf-8", errors="ignore"))
            file_list = payload.get("file_list", [])
            if not isinstance(file_list, list):
                raise RuntimeError("Invalid response: file_list is not a list")
            for file_name in file_list:
                canvases.append(f"https://{parsed.netloc}/obj/{source_path}/{file_name}")

        return canvases, title, author

    def _download_to_temp(self, source_url: str, dest_dir: str) -> str:
        attempts = RETRY_COUNT + 1
        tmp_file = ""
        for attempt in range(1, attempts + 1):
            try:
                req = Request(source_url, headers={"User-Agent": USER_AGENT})
                with self._opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
                    expected_size = resp.headers.get("Content-Length")
                    expected_size_int = (
                        int(expected_size)
                        if expected_size and expected_size.isdigit()
                        else None
                    )
                    fd, tmp_file = tempfile.mkstemp(prefix="usthk_", suffix=".part", dir=dest_dir)
                    downloaded = 0
                    with os.fdopen(fd, "wb") as f:
                        while True:
                            chunk = resp.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)

                if expected_size_int is not None and downloaded != expected_size_int:
                    raise RuntimeError(
                        f"incomplete download: expected {expected_size_int} bytes, got {downloaded} bytes"
                    )
                return tmp_file
            except Exception as err:
                if tmp_file and os.path.exists(tmp_file):
                    os.remove(tmp_file)
                    tmp_file = ""
                if attempt >= attempts:
                    raise RuntimeError(
                        f"download failed after {attempts} attempts: {source_url} ({err})"
                    ) from err
                _log(f"Retry {attempt}/{RETRY_COUNT}: {source_url}")
        return ""


# ------------------------------------------------------------------
# Module-level helpers (also used by CLI main)
# ------------------------------------------------------------------

def _extract_book_info(html: str):
    """从 USTHK 书目页面 HTML 中提取 (title, author)。"""
    title = ""
    m = re.search(r'<h3[^>]*class="post-title"[^>]*>\s*([^<]+?)\s*</h3>', html)
    if m:
        title = m.group(1).strip()

    author = ""
    m = re.search(r'>Authors</strong>\s*<br[^/]*/?>\s*<ul[^>]*>(.*?)</ul>', html, re.DOTALL)
    if m:
        items = re.findall(r'<li>([^<]+)</li>', m.group(1))
        # Strip trailing date ranges like ", 962-1033" or ", 556-627"
        names = [re.sub(r',\s*\d[\d\-]*\s*$', '', item).strip() for item in items]
        author = "、".join(n for n in names if n)

    return title, author


def _file_extension_from_url(source_url: str) -> str:
    ext = os.path.splitext(urlparse(source_url).path)[1]
    return ext if ext else ".jpg"


def _resize_image_inplace(filepath: str, max_width: int, quality: float) -> None:
    """按比例缩小图片（从不放大），原地保存为 JPEG。"""
    with Image.open(filepath) as img:
        if img.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = rgb_img
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        width, height = img.size
        if width > max_width:
            new_height = int(height * max_width / width)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

        img.save(filepath, format='JPEG', quality=int(quality * 100))


def _create_pdf(
    output_dir: str,
    title: str,
    author: str,
    pdf_path: str,
    callback: Optional[Callable[[int], None]] = None,
) -> None:
    """将 output_dir 中的所有图片合并为单个 PDF，合并后删除源图片。
    进度区间为 90%–100%，通过 callback 上报。
    """
    exts = ('.jpg', '.jpeg', '.png', '.tif', '.tiff')
    images = sorted(
        [
            os.path.join(output_dir, f)
            for f in os.listdir(output_dir)
            if f.lower().endswith(exts)
        ],
        key=lambda x: os.path.basename(x).lower(),
    )
    if not images:
        raise RuntimeError(f"No images found in {output_dir}")

    total = len(images)
    _log(f"Merging {total} images into PDF: {pdf_path}")
    c = pdf_canvas.Canvas(pdf_path)
    c.setTitle(title)
    c.setAuthor(author)
    c.setCreator("Talebook(https://mybooks.top)")

    for idx, img_path in enumerate(images, start=1):
        _log(f"[{idx}/{total}] Adding page: {os.path.basename(img_path)}")
        with open(img_path, "rb") as f:
            img_bytes = io.BytesIO(f.read())
        img_reader = ImageReader(img_bytes)
        img_width, img_height = img_reader.getSize()
        c.setPageSize((img_width, img_height))
        c.drawImage(img_reader, 0, 0, width=img_width, height=img_height)
        c.showPage()
        if callback:
            callback(90 + int(idx / total * 10))

    c.save()
    _log(f"PDF saved: {pdf_path}")

    _log("Deleting source images ...")
    for img_path in images:
        os.remove(img_path)
    _log(f"Deleted {total} source images")


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="USTHK file list downloader")
    parser.add_argument("url", help="USTHK page URL, e.g. https://.../bib/xxx")
    parser.add_argument("-o", "--output", default="", help="Download directory (default: use book_id)")
    parser.add_argument("-w", "--workers", type=int, default=5, metavar="N",
                        help="Concurrent download workers (1-10, default: 5)")
    parser.add_argument("--title", default="",
                        help="Book title for PDF filename (default: auto-detected)")
    parser.add_argument("--author", default="",
                        help="Author name for PDF metadata (default: auto-detected, fallback: 佚名)")
    parser.add_argument("--width", type=int, default=1024,
                        help="Max image width in pixels (default: 1024, never upscales)")
    parser.add_argument("--quality", type=float, default=0.8,
                        help="JPEG quality in range (0, 1] (default: 0.8)")
    parser.add_argument("--no-pdf", action="store_true",
                        help="Skip PDF generation and keep images as-is")
    args = parser.parse_args()

    if not 0 < args.quality <= 1:
        _log("Error: --quality must be in range (0, 1]")
        return 1

    book_id = _extract_book_id(args.url)
    if not book_id and not args.output:
        _log("Error: no book_id matched in URL, please use --output to specify a download directory")
        return 1

    if args.output:
        url_hash = hashlib.md5(args.url.encode()).hexdigest()[:16]
        output_dir = os.path.join(args.output, url_hash)
        _log(f"Output subdirectory: {url_hash}")
    else:
        output_dir = book_id

    workers = max(1, min(args.workers, 10))

    try:
        d = UsthkDownloader(args.url)
        try:
            d.check_valid_url()
        except ValueError:
            if not args.title:
                raise
            # title cannot be detected from page, but user provided --title override
            canvases, _, page_author = d.fetch_canvases()
            d.preload(canvases, args.title, args.author or page_author or "佚名")

        d.set_overrides(title=args.title, author=args.author)

        def cli_progress(p: int) -> None:
            _log(f"Progress: {p}%")

        pdf_path = d.download(
            output_dir,
            callback=cli_progress,
            workers=workers,
            max_width=args.width,
            quality=args.quality,
            no_pdf=args.no_pdf,
        )
        if pdf_path:
            _log(f"Done, PDF: {pdf_path}")
        else:
            _log(f"Done, output directory: {output_dir}")
        return 0
    except Exception as err:
        _log(f"Error: {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
