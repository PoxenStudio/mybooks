#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""小说排版整理（批量）后端接口。

配合管理端「图书管理 → 批量操作 → 小说排版整理」使用：
- ``GET  /api/novel_format/<book_id>/text`` 读取书籍 TXT 原文（解码后返回，供前端排版）；
- ``POST /api/novel_format/<book_id>/save`` 用排版结果整篇覆盖原 TXT（走 calibre add_format，
  自动更新文件大小 / last_modified，并重建 TXT 章节索引）；
- ``POST /api/novel_format/convert`` 纯文本繁简转换（复用 toolbox 内的 OpenCC 引擎，
  避免前端再引一份字典）。

只处理 TXT：小说排版算法基于纯文本，EPUB 等格式不在本功能范围内。
"""
import logging
import os
import tempfile

import tornado.escape

from webserver.handlers.base import BaseHandler, js, is_admin
from webserver.i18n import _
from webserver.loader import get_settings
from webserver.plugins.parser.txt import get_content_encoding
from webserver.services.extract import ExtractService

CONF = get_settings()

# 单本上限：排版算法与前端 textarea 都在内存里跑，40MB 纯文本已远超正常网文体量
MAX_TEXT_BYTES = 40 * 1024 * 1024
# 编码检测只需要样本，整本读进来再交给 chardet 会白白多占一份内存
ENCODING_SAMPLE_BYTES = 64 * 1024
# 繁简转换单次上限：纯 Python OpenCC 是逐词匹配，超大文本会长时间占住请求线程
MAX_CONVERT_CHARS = 8 * 1024 * 1024

CONVERT_DIRECTIONS = {
    "t2s": "繁➔简",
    "s2t": "简➔繁",
}

# 覆盖成功后打的标记标签：下一批排版整理会自动跳过带此标签的书，避免重复校正
REVISED_TAG = "精校"

# 作者名长度上限：再长基本就是误提取的整句（算法本身也有严格约束，这里兜底）
MAX_AUTHOR_LEN = 40


def _clean_author(value):
    """校验前端传来的作者名，不合法一律返回空串（宁缺毋滥）。"""
    if not isinstance(value, str):
        return ""
    author = value.strip().strip("\"'“”‘’")
    if not author or len(author) > MAX_AUTHOR_LEN:
        return ""
    if any(ch in author for ch in "\r\n\t"):
        return ""
    return author



def _get_txt_path(handler, book_id):
    """取书籍 TXT 的真实路径，不存在时返回 (None, 错误响应)。"""
    book = handler.get_book(book_id, raise_exception=False)
    if not book:
        return None, {"err": "params.book.invalid", "msg": _("书籍已不存在")}
    fpath = book.get("fmt_txt")
    if not fpath or not os.path.isfile(fpath):
        return None, {"err": "format.not_supported", "msg": _("该书籍没有 TXT 格式，无法排版整理")}
    return fpath, None


class NovelFormatText(BaseHandler):
    """读取单本书的 TXT 全文（解码后）。"""

    @js
    @is_admin
    def get(self, bid):
        book_id = int(bid)
        fpath, err = _get_txt_path(self, book_id)
        if err:
            return err

        size = os.path.getsize(fpath)
        if size > MAX_TEXT_BYTES:
            return {
                "err": "text.too_large",
                "msg": _("文件超过 %(size)s MB，暂不支持排版整理") % {"size": MAX_TEXT_BYTES // (1024 * 1024)},
            }

        with open(fpath, "rb") as f:
            raw = f.read()

        encoding = get_content_encoding(raw[:ENCODING_SAMPLE_BYTES]) or "utf-8"
        try:
            text = raw.decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError):
            # chardet 给的是猜测值，个别文件会在中途出现非法字节：退回 UTF-8 容错解码
            encoding = "utf-8"
            text = raw.decode("utf-8", errors="replace")

        # 编辑场景不需要 BOM，去掉后前端拿到的就是纯正文；保存时按原编码写回（UTF-8-SIG 会补回 BOM）
        if text.startswith("\ufeff"):
            text = text.lstrip("\ufeff")

        book = self.get_book(book_id, raise_exception=False) or {}
        return {
            "err": "ok",
            "data": {
                "id": book_id,
                "title": book.get("title", ""),
                "content": text,
                "encoding": encoding,
                "size": size,
            },
        }


class NovelFormatSave(BaseHandler):
    """用排版结果覆盖书籍的 TXT 原文件。"""

    @js
    @is_admin
    async def post(self, bid):
        book_id = int(bid)
        try:
            data = tornado.escape.json_decode(self.request.body)
        except Exception:
            return {"err": "params.invalid", "msg": _("请求内容不是合法 JSON")}

        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            return {"err": "params.content.empty", "msg": _("排版结果为空，已取消覆盖")}

        fpath, err = _get_txt_path(self, book_id)
        if err:
            return err

        # 「自动识别作者」开关打开时前端会把识别结果带上来；开关关闭则不带 author 字段
        author = _clean_author(data.get("author"))

        # 按原文件编码写回（保住 GBK 等老文件的可读性）；目标编码装不下转换后的字符时退回 UTF-8
        wanted = (data.get("encoding") or "utf-8").strip() or "utf-8"
        payload = None
        used_encoding = wanted
        for enc in (wanted, "utf-8"):
            try:
                payload = content.encode(enc)
                used_encoding = enc
                break
            except (LookupError, UnicodeEncodeError):
                continue
        if payload is None:
            used_encoding = "utf-8"
            payload = content.encode("utf-8", errors="replace")

        fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="novel_format_")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
            # 与「上传替换格式」同一条路径：calibre 负责落盘到书库并更新 data 表的大小 / mtime
            await self.run_calibre_async(
                self.calibre_db.add_format,
                book_id,
                "TXT",
                tmp_path,
                index_is_id=True,
                replace=True,
            )
        except Exception as exc:
            logging.error("[novel_format] save book %s failed: %s", book_id, exc)
            return {"err": "internal", "msg": _("覆盖失败：%s") % str(exc)}
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        # 作者改写放在 add_format 之后、重建索引之前：改作者会触发 calibre 重命名书目录，
        # 索引里存的是绝对路径，必须在改名后再取一次 fmt_txt。
        author_applied = False
        if author:
            try:
                # do_path_update=False：只改作者字段，不搬动书库目录。
                # 否则 calibre 会按新作者重命名文件夹，批量整理时整库路径都会变动。
                await self.run_calibre_async(
                    self.calibre_db_cache.set_field,
                    "authors",
                    {book_id: [author]},
                    do_path_update=False,
                )
                await self.run_calibre_async(
                    self.calibre_db_cache.set_field, "author_sort", {book_id: author}
                )
                author_applied = True
            except Exception as exc:
                # 作者写失败不回滚正文覆盖，但要在响应里如实返回
                logging.warning("[novel_format] set author failed for %s: %s", book_id, exc)

        # 旧索引里的 start/end 是上一份文件的字节偏移，必须强制重算，否则阅读器跳章会错位
        try:
            txt_path = self.calibre_db.format_abspath(book_id, "TXT", index_is_id=True)
            if txt_path:
                ExtractService().preheat_txt_content(book_id, txt_path, force=True)
        except Exception as exc:
            logging.warning("[novel_format] preheat txt content failed for %s: %s", book_id, exc)

        # 打「精校」标记：批次入口据此跳过已校正过的书，避免同一本被反复排版。
        # 用 bulk_modify_tags(add=...) 而不是 set_field("tags", ...)：前者是"追加标签"语义，
        # 不会动书上原有的标签（set_field 是整字段覆盖，一旦读到的旧值不全会把原标签冲掉）。
        tagged = False
        try:
            tags = list(self.calibre_db_cache.field_for("tags", book_id, default_value=()) or ())
            if REVISED_TAG not in tags:
                await self.run_calibre_async(
                    self.calibre_db.bulk_modify_tags,
                    [book_id],
                    add=[REVISED_TAG],
                    notify=True,
                )
                tagged = True
        except Exception as exc:
            # 打标签失败不影响正文已覆盖的结果，只记录日志
            logging.warning("[novel_format] add tag failed for %s: %s", book_id, exc)

        return {
            "err": "ok",
            "msg": _("已覆盖原文件"),
            "data": {
                "id": book_id,
                "size": len(payload),
                "encoding": used_encoding,
                "tagged": tagged,
                "author": author if author_applied else "",
            },
        }


class NovelFormatConvert(BaseHandler):
    """纯文本繁简转换（排版前预处理）。"""

    @js
    @is_admin
    def post(self):
        try:
            data = tornado.escape.json_decode(self.request.body)
        except Exception:
            return {"err": "params.invalid", "msg": _("请求内容不是合法 JSON")}

        text = data.get("text")
        direction = (data.get("direction") or "").strip()
        if not isinstance(text, str) or not text:
            return {"err": "params.text.empty", "msg": _("转换内容为空")}
        if direction not in CONVERT_DIRECTIONS:
            return {"err": "params.direction.invalid", "msg": _("不支持的转换方向")}
        if len(text) > MAX_CONVERT_CHARS:
            return {"err": "text.too_large", "msg": _("文本过大，请关闭繁简转换后重试")}

        from webserver.toolbox.chinese_converter.opencc_engine import OpenCC

        try:
            converted = OpenCC(direction).convert(text)
        except Exception as exc:
            logging.error("[novel_format] convert failed (%s): %s", direction, exc)
            return {"err": "internal", "msg": _("繁简转换失败：%s") % str(exc)}
        return {"err": "ok", "data": {"text": converted}}


def routes():
    return [
        (r"/api/novel_format/convert", NovelFormatConvert),
        (r"/api/novel_format/([0-9]+)/text", NovelFormatText),
        (r"/api/novel_format/([0-9]+)/save", NovelFormatSave),
    ]
