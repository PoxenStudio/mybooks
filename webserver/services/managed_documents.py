#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""DJVU/UVZ 扫描版托管文档：容器校验与文件名编目。

这类格式无法解出可供在线阅读的电子书内容（UVZ 内页多为超星 PDG 等私有格式），
因此只入库保存原始文件供下载；BookRead 对无可读格式的书籍一律 404，天然禁读。
校验只识别容器结构，不解压、不解码页面内容。
"""

import logging
import os
import struct
import zipfile

from webserver.i18n import _
from webserver import utils

# 与 ZIP 容器类工具一致的条目预算：防御性上限，防炸卷/炸内存
MAX_ARCHIVE_ENTRIES = 10000


class InvalidManagedDocumentError(Exception):
    """容器校验失败；message 为可直接展示给用户的说明。"""


def _invalid(message):
    raise InvalidManagedDocumentError(message)


def _read_signature(fpath, size):
    with open(fpath, "rb") as f:
        return f.read(size)


def _analyze_djvu(fpath):
    """IFF FORM 容器：'AT&TFORM' + 大端长度 + 'DJVU'/'DJVM' 子类型，长度须与文件自洽。"""
    header = _read_signature(fpath, 16)
    if len(header) != 16 or header[:8] != b"AT&TFORM" or header[12:16] not in (b"DJVU", b"DJVM"):
        _invalid(_("文件内容不是有效的 DjVu 容器"))
    form_size = struct.unpack(">I", header[8:12])[0]
    if form_size < 4 or form_size + 12 != os.path.getsize(fpath):
        _invalid(_("DjVu 容器长度不匹配"))


def _analyze_uvz(fpath):
    """ZIP 容器：校验中央目录与条目预算，不施加图片类限制（内页可能是 PDG 私有格式）。"""
    if not _read_signature(fpath, 4).startswith(b"PK"):
        _invalid(_("文件内容不是有效的 UVZ ZIP 容器"))
    try:
        with zipfile.ZipFile(fpath) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                _invalid(_("UVZ 容器条目数超出预算(%d)") % MAX_ARCHIVE_ENTRIES)
            if not any(not info.is_dir() for info in infos):
                _invalid(_("UVZ 容器为空"))
            if any(info.flag_bits & 0x1 for info in infos):
                _invalid(_("UVZ 容器包含加密条目，无法导入"))
    except InvalidManagedDocumentError:
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as err:
        logging.info("UVZ container check failed for %s: %s", fpath, err)
        _invalid(_("UVZ 容器已损坏：%s") % err)


def analyze_managed_document(fpath, fmt):
    """校验 DJVU/UVZ 文件确为声称的容器格式。非法抛 InvalidManagedDocumentError。"""
    fmt = (fmt or "").lower().lstrip(".")
    if fmt == "djvu":
        _analyze_djvu(fpath)
    elif fmt == "uvz":
        _analyze_uvz(fpath)
    else:
        _invalid(_("不支持的托管文档格式: %s") % fmt)


def filename_metadata(name):
    """按文件名构造最小 Calibre 元数据。

    标题/作者沿用 TXT 的文件名解析约定（"书名作者：某某"，解析不出作者时置为佚名）。
    """
    from calibre.ebooks.metadata.book.base import Metadata

    stem = os.path.splitext(os.path.basename(name))[0]
    stem = utils.remove_zlibrary_suffix(stem)
    title, author = utils.guess_title_author_from_filename(stem)
    return Metadata(title or stem, [author] if author else [_("佚名")])
