# -*- coding: utf-8 -*-
"""书籍处理公共工具（TXT 编码修复 / 正文查找替换 两插件共用，依赖 BaseTool 环境）。

两个工具统一采用「生成新书」模式，原书文件零改动：
1. :func:`get_book_file` 校验书籍存在且具备目标格式，返回文件绝对路径；
2. 工具在临时工作目录中生成处理后的新文件；
3. :func:`import_as_new_book` 复用原书完整元数据（标题追加后缀、作者、标签、
   出版社、丛书、简介、语言、封面）以新书身份入库，并创建 Item 记录。

参考实现：``epub_split.py`` 的 ``import_book`` + ``cover_data`` 模式。
"""

import logging
import os
from typing import Optional

from calibre.ebooks.metadata.book.base import Metadata

from webserver import utils
from webserver.i18n import _


def get_book_file(tool, book_id: int, fmt: str) -> str:
    """校验书籍存在且具备指定格式，返回该格式文件的绝对路径。

    :param tool:    调用方 Tool 实例（提供 ``api`` / ``get_book_metadata`` 等）。
    :param book_id: Calibre 书籍 ID。
    :param fmt:     大写格式名，如 ``"TXT"`` / ``"EPUB"``。
    :return: 文件绝对路径。
    :raises RuntimeError: 书籍不存在 / 无该格式 / 文件缺失 / 路径不是文件 / 无法读取。
    """
    books = tool.api.calibre.get_data_as_dict([book_id])
    if not books:
        raise RuntimeError(_("书籍不存在：ID=%d") % book_id)
    fmts = [f.upper() for f in (books[0].get("available_formats") or [])]
    if fmt not in fmts:
        raise RuntimeError(_("该书籍没有 %s 格式，无法处理") % fmt)
    path = tool.api.calibre.format_abspath(book_id, fmt)
    if not path or not os.path.exists(path):
        raise RuntimeError(_("找不到 %s 文件，可能已被移除") % fmt)
    if not os.path.isfile(path):
        # 目录 / 特殊设备等非普通文件：给出明确提示而非 IsADirectoryError 堆栈
        raise RuntimeError(_("%s 文件路径异常（不是普通文件），可能已被破坏") % fmt)
    try:
        # 提前验证可读性（权限 / 独占锁定 / 已删除句柄等），转成友好错误
        with open(path, "rb") as f:
            f.read(1)
    except (PermissionError, OSError) as err:
        raise RuntimeError(_("无法读取 %s 文件：%s") % (fmt, err)) from err
    return path


def import_as_new_book(
    tool,
    book_id: int,
    out_path: str,
    suffix: str,
    user_id: int,
    language: Optional[str] = None,
) -> int:
    """以新书身份入库：复用原书完整元数据 + 封面，标题追加后缀。

    :param tool:     调用方 Tool 实例。
    :param book_id:  原书 ID（元数据来源）。
    :param out_path: 处理后新文件的绝对路径。
    :param suffix:   追加到标题末尾的后缀（如 ``"（简体版）"``、``"「正文替换版」"``）。
    :param user_id:  操作用户 ID（用于创建 Item 记录）。
    :param language: 可选，覆盖语言字段（如 ``"zh"`` / ``"zht"``），None 时沿用原书。
    :return: 新书 Calibre book_id。
    :raises RuntimeError: 入库失败。
    """
    src_mi = tool.get_book_metadata(book_id)

    title = utils.super_strip(src_mi.title or "")
    if suffix:
        title = "%s%s" % (title, suffix)
    authors = list(src_mi.authors) if src_mi.authors else []

    cover_data = None
    raw_cover = tool.api.calibre.cover(book_id)
    if raw_cover:
        cover_data = ("jpeg", raw_cover)

    mi = Metadata(title, authors)
    mi.title_sort = utils.get_title_sort(mi.title)
    mi.tags = list(src_mi.tags) if src_mi.tags else []
    mi.publisher = src_mi.publisher
    mi.series = src_mi.series
    mi.comments = src_mi.comments
    if src_mi.pubdate:
        mi.pubdate = src_mi.pubdate
    if src_mi.identifiers:
        mi.identifiers = dict(src_mi.identifiers)  # 含 ISBN 等全部外部标识
    if src_mi.rating:
        mi.rating = src_mi.rating
    if language:
        mi.languages = [language]
    elif src_mi.languages:
        mi.languages = list(src_mi.languages)
    # 原书无语言时留空：猜测 "zho" 会把英文书误标中文，交给用户/刮削补全更诚实
    if cover_data:
        mi.cover_data = cover_data

    logging.info(
        "[%s] Importing as new book: book_id=%d -> %s",
        tool.__class__.__name__, book_id, title,
    )
    new_book_id = tool.api.calibre.import_book(mi, [out_path])
    if new_book_id is None:
        raise RuntimeError(_("导入新书失败：%s") % title)

    try:
        tool.api.db.create_item(new_book_id, user_id)
    except Exception as err:
        logging.error(
            "[%s] Failed to create Item for book_id=%s: %s",
            tool.__class__.__name__, new_book_id, err,
        )

    return new_book_id
