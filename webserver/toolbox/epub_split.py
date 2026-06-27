"""
EPUB 拆分新书工具

从指定 EPUB 书籍中挑选若干章节，提取为一本独立的新书：作者、标签、
分类、出版社、丛书信息默认继承自原书；封面默认沿用原书封面，若用户
勾选"使用第一章节大图作为封面"则尝试从所选第一章节中提取一张满足
最小尺寸的图片作为新封面。

@author: PoxenStudio, 2026
"""
import io
import logging
import os
import threading
import time

from webserver.i18n import _
from webserver.services import AsyncService
from webserver.toolbox.base_tool import BaseTool
from webserver.toolbox.epub_split_lib import SplitEpub, strip_html, get_title_of_html
from webserver import loader, utils
from webserver.constants import AUTO_FILL_META
from webserver.models import Item
from webserver.services.autofill import AutoFillService

PREVIEW_LENGTH = 300
COVER_MIN_WIDTH = 400
COVER_MIN_HEIGHT = 600


class EpubSplitTool(BaseTool):
    service_item_name = ""  # 同步执行，不使用后台任务

    @staticmethod
    def info() -> dict:
        return {
            "tool_id": "epub_split",
            "name": "EPUB拆分新书",
            "description": "从指定 EPUB 书籍中选择若干章节，提取为一本独立的新书",
            "revision": "0.1.0",
            "author": "MyBooks",
            "publish_date": "2026-06-27",
        }

    def _load_epub(self, book_id: int):
        books = self.db.get_data_as_dict(ids=[book_id])
        if not books:
            raise RuntimeError(_("书籍不存在：ID=%d") % book_id)
        book = books[0]
        fmts = [f.upper() for f in (book.get("available_formats") or [])]
        if "EPUB" not in fmts:
            raise RuntimeError(_("该书籍没有 EPUB 格式，无法执行拆分"))
        epub_path = self.db.format_abspath(book_id, "EPUB", index_is_id=True)
        if not epub_path or not os.path.exists(epub_path):
            raise RuntimeError(_("找不到 EPUB 文件，可能已被移除"))
        with open(epub_path, "rb") as f:
            data = f.read()
        return book, SplitEpub(io.BytesIO(data))

    @AsyncService.register_function
    def list_chapters(self, book_id: int) -> dict:
        """返回指定书籍的章节列表（含 200 字预览），供前端勾选。"""
        book, epub = self._load_epub(book_id)
        lines = epub.get_split_lines()
        chapters = []
        for line in lines:
            page_title = get_title_of_html(line["sample"])
            if line["toc"]:
                title = " / ".join(line["toc"])
                if page_title not in line["toc"]:
                    title = title + " [" + page_title + "]"
            else:
                title = "... " + page_title
            chapters.append({
                "num": line["num"],
                "title": title,
                "preview": strip_html(line["sample"])[:PREVIEW_LENGTH],
            })
        return {"book_id": book_id, "title": book.get("title", ""), "chapters": chapters}

    @AsyncService.register_function
    def split(self, book_id: int, linenums: list, use_first_chapter_cover: bool, user_id: int) -> dict:
        """按所选章节生成一本新书，返回 {"book_id": ..., "title": ...}。"""
        from calibre.ebooks.metadata.book.base import Metadata

        if not linenums:
            raise RuntimeError(_("请至少选择一个章节"))

        linenums = sorted({int(n) for n in linenums})
        book, epub = self._load_epub(book_id)
        lines = epub.get_split_lines()  # 同时填充 epub.orig_title / orig_authors

        first_line = next((line for line in lines if line["num"] == linenums[0]), None)
        new_title = (first_line["toc"][0] if first_line and first_line["toc"] else None) or utils.super_strip(book.get("title", ""))

        src_mi = self.get_book_metadata(book_id)

        cover_data = None
        if use_first_chapter_cover:
            candidate = epub.find_cover_candidate([linenums[0]], COVER_MIN_WIDTH, COVER_MIN_HEIGHT)
            if candidate:
                ext, raw = candidate
                cover_data = ("jpeg" if ext in ("jpg", "jpeg") else ext, raw)
            else:
                logging.info("[EpubSplit]Not found the first image")
        if cover_data is None:
            raw_cover = self.db.cover(book_id, index_is_id=True)
            if raw_cover:
                cover_data = ("jpeg", raw_cover)

        languages = list(src_mi.languages) if src_mi.languages else ["zho"]
        authors = list(src_mi.authors) if src_mi.authors else []

        work_dir = self.get_work_dir(str(book_id))
        out_path = os.path.join(work_dir, "split_%d.epub" % int(time.time()))
        try:
            with open(out_path, "wb") as f:
                epub.write_split_epub(
                    f, linenums,
                    title=new_title,
                    authors=authors,
                    tags=list(src_mi.tags) if src_mi.tags else [],
                    languages=languages,
                    description=src_mi.comments,
                    cover_data=cover_data,
                )

            mi = Metadata(utils.super_strip(new_title), authors)
            mi.title_sort = utils.get_title_sort(mi.title)
            mi.tags = list(src_mi.tags) if src_mi.tags else []
            mi.publisher = src_mi.publisher
            mi.series = src_mi.series
            mi.languages = languages
            if cover_data:
                logging.info("[EPUB]Has valid cover data")
                mi.cover_data = cover_data

            new_book_id = self.db.import_book(mi, [out_path])
            if new_book_id is None:
                raise RuntimeError(_("导入拆分后的 EPUB 失败"))

            try:
                item = Item()
                item.book_id = new_book_id
                item.collector_id = user_id
                item.save()
            except Exception as err:
                logging.error("[EpubSplitTool] Failed to create Item for book_id=%s: %s", new_book_id, err)

            logging.info(
                "[EpubSplitTool] Split book_id=%d -> new book_id=%d, title=%s [uid:%d]",
                book_id, new_book_id, mi.title, user_id,
            )
        finally:
            self.cleanup_work_dir(work_dir)

        if loader.get_settings().get(AUTO_FILL_META, False):
            threading.Thread(target=AutoFillService().auto_fill, args=(new_book_id,), daemon=True).start()

        return {"book_id": new_book_id, "title": mi.title}
