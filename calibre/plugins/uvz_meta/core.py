#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging
import re
import zipfile
import zlib
from datetime import datetime, timezone

from calibre.ebooks.metadata import check_isbn
from calibre.ebooks.metadata.book.base import Metadata

BOOKINFO_NAME = "bookinfo.dat"
COVER_CANDIDATES = (re.compile(r"^cov\d+\.pdg$", re.I), re.compile(r"^bok\d+\.pdg$", re.I))
MAX_BOOKINFO_BYTES = 1024 * 1024
MAX_COVER_ENTRY_BYTES = 20 * 1024 * 1024
LIST_SPLIT_RE = re.compile(r"[,;，；、]")
DATE_RE = re.compile(r"(\d{4})\s*(?:[年.\-/]\s*(\d{1,2}))?")
IMAGE_MAGICS = ((b"\xff\xd8\xff", "jpeg"), (b"\x89PNG\r\n\x1a\n", "png"), (b"GIF8", "gif"), (b"BM", "bmp"))
ZIP_READ_ERRORS = (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError, zlib.error, EOFError, KeyError)

log = logging.getLogger(__name__)


def _basename(info):
    return info.filename.rstrip("/").rsplit("/", 1)[-1]


def _decode(data):
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("gb18030", "replace")


def parse_bookinfo(data):
    info = {}
    for line in _decode(data).splitlines():
        line = line.strip()
        if not line or line.startswith("[") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key and value and key not in info:
            info[key] = value
    return info


def _split(value):
    ans = []
    for item in LIST_SPLIT_RE.split(value or ""):
        item = item.strip()
        if item and item not in ans:
            ans.append(item)
    return ans


def _parse_pubdate(value):
    match = DATE_RE.search(value or "")
    if not match:
        return None
    month = int(match.group(2)) if match.group(2) else 1
    try:
        return datetime(int(match.group(1)), month if 1 <= month <= 12 else 1, 1, 12, tzinfo=timezone.utc)
    except ValueError:
        return None


def bookinfo_to_mi(info, mi=None):
    if mi is None:
        mi = Metadata(None, None)
    title = info.get("书名")
    if title:
        mi.title = title
    authors = _split(info.get("作者"))
    if authors:
        mi.authors = authors
    mi.publisher = info.get("出版社")
    mi.comments = info.get("内容提要") or info.get("摘要")
    mi.tags = _split(info.get("主题词"))
    pubdate = _parse_pubdate(info.get("出版日期"))
    if pubdate is not None:
        mi.pubdate = pubdate

    identifiers = {}
    isbn = check_isbn(info.get("ISBN号") or info.get("ISBN") or "")
    if isbn:
        identifiers["isbn"] = isbn
    for key, name in (("SS号", "ss"), ("DX号", "dx")):
        if info.get(key):
            identifiers[name] = info[key]
    if identifiers:
        mi.set_identifiers(identifiers)
    return mi


def _image_format(data):
    for magic, fmt in IMAGE_MAGICS:
        if data.startswith(magic):
            return fmt
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def extract_cover(zf, infos):
    for pattern in COVER_CANDIDATES:
        candidates = sorted((i for i in infos if not i.is_dir() and pattern.match(_basename(i))), key=lambda i: _basename(i).lower())
        for info in candidates:
            if info.file_size > MAX_COVER_ENTRY_BYTES:
                continue
            try:
                data = zf.read(info)
            except ZIP_READ_ERRORS as err:
                log.info("UVZ cover read failed for %s: %s", info.filename, err)
                continue
            fmt = _image_format(data)
            if fmt:
                return (fmt, data)
    return None


def _find_bookinfo(infos):
    candidates = [i for i in infos if not i.is_dir() and _basename(i).lower() == BOOKINFO_NAME]
    candidates.sort(key=lambda i: (i.filename.count("/"), i.filename))
    return candidates[0] if candidates else None


def read_metadata(stream, quick=False):
    mi = Metadata(None, None)
    try:
        stream.seek(0)
        with zipfile.ZipFile(stream) as zf:
            infos = zf.infolist()
            info = _find_bookinfo(infos)
            if info is not None and info.file_size <= MAX_BOOKINFO_BYTES:
                try:
                    bookinfo_to_mi(parse_bookinfo(zf.read(info)), mi)
                except ZIP_READ_ERRORS as err:
                    log.info("Failed to read UVZ bookinfo.dat: %s", err)
            if not quick:
                mi.cover_data = extract_cover(zf, infos) or (None, None)
    except ZIP_READ_ERRORS as err:
        log.warning("Failed to read UVZ metadata: %s", err)
    return mi
