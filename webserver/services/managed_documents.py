#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""DJVU/UVZ/CBZ 托管文档（扫描版/漫画包）：容器校验与编目。

UVZ 内页多为超星 PDG 等私有格式，只入库保存原始文件供下载；校验只识别容器结构，不解码页面内容。
DJVU/CBZ 的内嵌元数据与封面经 calibre 元数据插件（calibre/plugins 下的 djvu_meta、cbz_meta）读取，
与文件名编目结果合并；插件缺失时 DJVU 退回文件名编目，CBZ 退回 calibre 内置漫画插件。
"""

import logging
import os
import struct
import zipfile

from webserver.constants import CALIBRE_ERROR_FLAG
from webserver.i18n import _
from webserver import utils

# 与 ZIP 容器类工具一致的条目预算：防御性上限，防炸卷/炸内存
MAX_ARCHIVE_ENTRIES = 10000
# CBZ 图片页认可的扩展名
IMAGE_EXTS = frozenset(("jpg", "jpeg", "png", "webp", "gif", "bmp"))


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
    # IFF 块按偶数对齐：FORM 长度为奇数时允许文件末尾多一个不计入长度的填充字节
    expected = {form_size + 12, form_size + 13} if form_size % 2 else {form_size + 12}
    if form_size < 4 or os.path.getsize(fpath) not in expected:
        _invalid(_("无效的DjVu文件"))


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


def _analyze_cbz(fpath):
    """CBZ（漫画图片 ZIP 包）：ZIP 校验之外，至少要含一张常见扩展名的图片页。"""
    if not _read_signature(fpath, 4).startswith(b"PK"):
        _invalid(_("文件内容不是有效的 CBZ ZIP 容器"))
    try:
        with zipfile.ZipFile(fpath) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                _invalid(_("CBZ 容器条目数超出预算(%d)") % MAX_ARCHIVE_ENTRIES)
            if any(info.flag_bits & 0x1 for info in infos):
                _invalid(_("CBZ 容器包含加密条目，无法导入"))
            if not any(
                not info.is_dir()
                and info.filename.rsplit(".", 1)[-1].lower() in IMAGE_EXTS
                for info in infos
            ):
                _invalid(_("CBZ 容器内未找到图片页"))
    except InvalidManagedDocumentError:
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as err:
        logging.info("CBZ container check failed for %s: %s", fpath, err)
        _invalid(_("CBZ 容器已损坏：%s") % err)


def analyze_managed_document(fpath, fmt):
    """校验 DJVU/UVZ/CBZ 文件确为声称的容器格式。非法抛 InvalidManagedDocumentError。"""
    fmt = (fmt or "").lower().lstrip(".")
    try:
        if fmt == "djvu":
            _analyze_djvu(fpath)
        elif fmt == "uvz":
            _analyze_uvz(fpath)
        elif fmt == "cbz":
            _analyze_cbz(fpath)
        else:
            _invalid(_("不支持的托管文档格式: %s") % fmt)
    except InvalidManagedDocumentError:
        raise
    except OSError as err:
        # 文件不可读（权限/磁盘等）：统一转为校验错误，避免调用方 500
        _invalid(_("无法读取文件：%s") % err)


def filename_metadata(name):
    """按文件名构造最小 Calibre 元数据。

    标题/作者沿用 TXT 的文件名解析约定（"书名作者：某某"，解析不出作者时置为佚名）。
    """
    from calibre.ebooks.metadata.book.base import Metadata

    stem = os.path.splitext(os.path.basename(name))[0]
    stem = utils.remove_zlibrary_suffix(stem)
    title, author = utils.guess_title_author_from_filename(stem)
    return Metadata(title or stem, [author] if author else [_("佚名")])


def _read_file_metadata(fpath, fmt):
    from calibre.customize.ui import get_file_type_metadata

    try:
        with open(fpath, "rb") as stream:
            mi = get_file_type_metadata(stream, fmt)
    except Exception as err:
        logging.info("%s metadata read failed for %s: %s", fmt.upper(), fpath, err)
        return None
    if mi.title == CALIBRE_ERROR_FLAG:
        return None
    return mi


def build_managed_metadata(fpath, fmt, name):
    """托管格式的完整编目：文件名元数据，DJVU/CBZ 再合并插件读出的内嵌元数据与封面。"""
    mi = filename_metadata(name)
    fmt = (fmt or "").lower().lstrip(".")
    if fmt in ("djvu", "cbz"):
        file_mi = _read_file_metadata(fpath, fmt)
        if file_mi is not None:
            mi.smart_update(file_mi)
    return mi
