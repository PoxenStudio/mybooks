#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
从书籍文件中提取目录结构（EPUB > PDF > TXT）
@author: PoxenStudio, 2026
"""

import logging
import os
import traceback

from webserver.i18n import _
from webserver.constants import CALIBRE_COLUMN_CATALOG
from webserver.services import AsyncService

# 目录提取的格式优先级：其他格式（mobi/azw3/docx等）暂无可靠的目录提取方案，先忽略
CATALOG_FORMAT_PRIORITY = ["EPUB", "PDF", "TXT"]
MAX_TITLE_LENGTH = 200
MAX_CATALOG_LEN = 204800


class CatalogExtractService(AsyncService):
    def _md_line(self, title, depth):
        title = (title or "").strip().replace("\n", " ")
        if not title:
            return None
        if len(title) > MAX_TITLE_LENGTH:
            title = title[:MAX_TITLE_LENGTH] + "..."
        return "%s- %s" % ("  " * max(depth, 0), title)

    def _extract_epub_toc(self, fpath):
        from ebooklib import epub

        book = epub.read_epub(fpath, {"ignore_ncx": True})
        lines = []

        def walk(items, depth):
            for item in items or []:
                if isinstance(item, tuple) and len(item) == 2:
                    section, children = item
                    line = self._md_line(getattr(section, "title", None), depth)
                    if line:
                        lines.append(line)
                    walk(children, depth + 1)
                else:
                    line = self._md_line(getattr(item, "title", None), depth)
                    if line:
                        lines.append(line)
                    walk(getattr(item, "children", None), depth + 1)

        walk(book.toc, 0)
        return "\n".join(lines)

    def _extract_pdf_toc(self, fpath):
        import fitz

        doc = fitz.open(fpath)
        try:
            toc = doc.get_toc() or []
        finally:
            doc.close()
        lines = []
        for level, title, _page in toc:
            line = self._md_line(title, level - 1)
            if line:
                lines.append(line)
        return "\n".join(lines)

    def _extract_txt_toc(self, fpath):
        from webserver.plugins.parser.txt import TxtParser

        result = TxtParser().parse(fpath)
        lines = []
        for item in result.get("toc", []):
            line = self._md_line(item.get("title"), 0)
            if line:
                lines.append(line)
        return "\n".join(lines)

    def _extract_one(self, book_id, force):
        cache = self.db.new_api
        if not force:
            existing = (cache.field_for(CALIBRE_COLUMN_CATALOG, book_id) or "").strip()
            if existing:
                return {"err": "ok", "skipped": True, "msg": _("已有目录信息，跳过")}

        available = set(cache.formats(book_id, verify_formats=False) or [])
        last_error = _("书籍不包含可提取目录的格式（EPUB/PDF/TXT）")
        for fmt in CATALOG_FORMAT_PRIORITY:
            if fmt not in available:
                continue
            fpath = self.db.format_abspath(book_id, fmt, index_is_id=True)
            if not fpath or not os.path.isfile(fpath):
                continue
            try:
                if fmt == "EPUB":
                    markdown = self._extract_epub_toc(fpath)
                elif fmt == "PDF":
                    markdown = self._extract_pdf_toc(fpath)
                else:
                    markdown = self._extract_txt_toc(fpath)
            except Exception as e:
                logging.warning("[Catalog] extract failed for book=%s fmt=%s: %s", book_id, fmt, e)
                logging.debug(traceback.format_exc())
                last_error = str(e)
                continue

            if markdown and len(markdown.splitlines()) > 1:
                if len(markdown) > MAX_CATALOG_LEN:
                    markdown = markdown[:MAX_CATALOG_LEN] + "\n\n* 目录过长，已被截断*"
                cache.set_field(CALIBRE_COLUMN_CATALOG, {book_id: markdown})
                return {"err": "ok", "format": fmt, "catalog": markdown}
            else:
                cache.set_field(CALIBRE_COLUMN_CATALOG, {book_id: ""})
            last_error = _("未能从%s格式中解析出目录") % fmt

        return {"err": "catalog.not_found", "msg": last_error}

    @AsyncService.register_function
    def extract_one(self, book_id, force=True):
        """提取单本书籍的目录，默认强制重新提取"""
        return self._extract_one(book_id, force)

    @AsyncService.register_function
    def extract_batch(self, book_ids, force=False):
        """批量提取，force=False 时跳过已有目录信息的书籍"""
        summary = {"total": len(book_ids), "done": 0, "skip": 0, "fail": 0}
        for book_id in book_ids:
            try:
                ret = self._extract_one(book_id, force)
            except Exception as e:
                logging.error("[Catalog] batch extract error book=%s: %s", book_id, e)
                ret = {"err": "internal"}
            if ret.get("err") != "ok":
                summary["fail"] += 1
            elif ret.get("skipped"):
                summary["skip"] += 1
            else:
                summary["done"] += 1
        return summary
