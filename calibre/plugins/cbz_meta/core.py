#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging
import re
from datetime import datetime, timezone
import shutil
import zipfile
import zlib
from tempfile import SpooledTemporaryFile

from calibre.ebooks.metadata import check_isbn, fmt_sidx
from calibre.ebooks.metadata.book.base import Metadata
from calibre.utils.date import as_local_time
from calibre.utils.localization import canonicalize_lang, lang_as_iso639_1
from calibre.utils.xml_parse import safe_xml_fromstring
from lxml import etree

COMICINFO_NAME = "ComicInfo.xml"
IMAGE_EXTS = frozenset(("jpg", "jpeg", "png", "webp", "gif", "bmp"))
MAX_COVER_ENTRY_BYTES = 20 * 1024 * 1024
MAX_COMICINFO_BYTES = 4 * 1024 * 1024
LIST_SPLIT_RE = re.compile(r"[,;，；]")
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
XSD_NS = "http://www.w3.org/2001/XMLSchema"
ELEMENT_ORDER = (
    "Title", "Series", "Number", "Count", "Volume", "AlternateSeries", "AlternateNumber", "AlternateCount", "Summary", "Notes",
    "Year", "Month", "Day", "Writer", "Penciller", "Inker", "Colorist", "Letterer", "CoverArtist", "Editor", "Translator",
    "Publisher", "Imprint", "Genre", "Tags", "Web", "PageCount", "LanguageISO", "Format", "BlackAndWhite", "Manga",
    "Characters", "Teams", "Locations", "ScanInformation", "StoryArc", "StoryArcNumber", "SeriesGroup", "AgeRating",
    "Pages", "CommunityRating", "MainCharacterOrTeam", "Review", "GTIN",
)
MANAGED_ELEMENTS = ("Title", "Series", "Number", "Summary", "Year", "Month", "Day", "Writer", "Publisher", "Genre", "Tags", "LanguageISO", "GTIN")
ZIP_READ_ERRORS = (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError, zlib.error, EOFError, KeyError)

log = logging.getLogger(__name__)


class CbzMetadataError(Exception):
    pass


def natural_key(name):
    return tuple((0, int(t)) if t.isdigit() else (1, t) for t in re.split(r"(\d+)", name))


def _ext(name):
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _split(value):
    ans = []
    for item in LIST_SPLIT_RE.split(value or ""):
        item = item.strip()
        if item and item not in ans:
            ans.append(item)
    return ans


def _find_comicinfo(infos):
    candidates = [i for i in infos if not i.is_dir() and i.filename.rsplit("/", 1)[-1].lower() == COMICINFO_NAME.lower()]
    candidates.sort(key=lambda i: (i.filename.count("/"), i.filename))
    return candidates[0] if candidates else None


def _image_infos(infos):
    images = [i for i in infos if not i.is_dir() and _ext(i.filename) in IMAGE_EXTS and not i.filename.startswith("__MACOSX/")]
    images.sort(key=lambda i: natural_key(i.filename))
    return images


def _parse_comicinfo(data):
    if not data:
        return None
    try:
        root = safe_xml_fromstring(data)
    except Exception as err:
        log.info("Invalid ComicInfo.xml: %s", err)
        return None
    if root is None or etree.QName(root).localname != "ComicInfo":
        return None
    return root


def _child(root, tag):
    for el in root:
        if isinstance(el.tag, str) and etree.QName(el).localname == tag:
            return el
    return None


def _value(root, tag):
    el = _child(root, tag)
    return _text(el.text) if el is not None else None


def _front_cover_index(root):
    pages = _child(root, "Pages") if root is not None else None
    if pages is None:
        return None
    for page in pages:
        if isinstance(page.tag, str) and page.get("Type") == "FrontCover":
            try:
                return int(page.get("Image"))
            except (TypeError, ValueError):
                return None
    return None


def comicinfo_to_mi(root, mi=None):
    if mi is None:
        mi = Metadata(None, None)
    series = _value(root, "Series")
    number = _value(root, "Number") or _value(root, "Volume")
    title = _value(root, "Title")
    if not title and series:
        title = "%s %s" % (series, number) if number else series
    if title:
        mi.title = title
    authors = _split(_value(root, "Writer")) or _split(_value(root, "Penciller"))
    if authors:
        mi.authors = authors
    mi.comments = _value(root, "Summary")
    mi.publisher = _value(root, "Publisher")
    mi.tags = _split(";".join(filter(None, (_value(root, "Genre"), _value(root, "Tags")))))
    if series:
        mi.series = series
        try:
            mi.series_index = float(number) if number else 1.0
        except ValueError:
            mi.series_index = 1.0

    year = _value(root, "Year")
    if year and year.isdigit() and int(year) > 0:
        parts = [int(year)] + [int(v) if v and v.isdigit() else 1 for v in (_value(root, "Month"), _value(root, "Day"))]
        for ymd in (parts, parts[:1] + [1, 1]):
            try:
                mi.pubdate = datetime(*ymd, 12, tzinfo=timezone.utc)
                break
            except ValueError:
                continue

    lang = canonicalize_lang(_value(root, "LanguageISO") or "")
    if lang:
        mi.languages = [lang]
    isbn = check_isbn(_value(root, "GTIN") or "")
    if isbn:
        mi.set_identifiers({"isbn": isbn})
    return mi


def _cbi_metadata(stream):
    from calibre.ebooks.metadata.archive import get_comic_metadata

    try:
        stream.seek(0)
        return get_comic_metadata(stream, "cbz")
    except Exception as err:
        log.info("Failed to read ComicBookInfo comment: %s", err)
        return None


def extract_cover(zf, infos, front_index=None):
    images = [i for i in _image_infos(infos) if i.file_size <= MAX_COVER_ENTRY_BYTES]
    if not images:
        return None
    order = images
    if front_index is not None and 0 <= front_index < len(images):
        order = [images[front_index]] + [i for i in images if i is not images[front_index]]
    for info in order[:2]:
        try:
            data = zf.read(info)
        except ZIP_READ_ERRORS as err:
            log.info("CBZ cover extraction failed for %s: %s", info.filename, err)
            continue
        if data:
            fmt = _ext(info.filename)
            return ("jpg" if fmt == "jpeg" else fmt, data)
    return None


def read_metadata(stream, quick=False):
    mi = Metadata(None, None)
    try:
        stream.seek(0)
        with zipfile.ZipFile(stream) as zf:
            infos = zf.infolist()
            info = _find_comicinfo(infos)
            root = None
            if info is not None and info.file_size <= MAX_COMICINFO_BYTES:
                try:
                    root = _parse_comicinfo(zf.read(info))
                except ZIP_READ_ERRORS as err:
                    log.info("Failed to read ComicInfo.xml: %s", err)
            if root is not None:
                comicinfo_to_mi(root, mi)
            if not quick:
                mi.cover_data = extract_cover(zf, infos, _front_cover_index(root)) or (None, None)
    except ZIP_READ_ERRORS as err:
        log.warning("Failed to read CBZ metadata: %s", err)
        return mi
    if root is None:
        cbi = _cbi_metadata(stream)
        if cbi is not None:
            cover = mi.cover_data
            mi.smart_update(cbi)
            mi.cover_data = cover
    return mi


def _mi_values(mi):
    pubdate = None if mi.is_null("pubdate") else as_local_time(mi.pubdate)
    series = None if mi.is_null("series") else _text(mi.series)
    comments = _text(mi.comments)
    lang = lang_as_iso639_1(mi.languages[0]) if mi.languages else None
    return {
        "Title": None if mi.is_null("title") else _text(mi.title),
        "Series": series,
        "Number": fmt_sidx(mi.series_index if mi.series_index is not None else 1) if series else None,
        "Summary": None if comments in (None, "<>") else comments,
        "Year": str(pubdate.year) if pubdate else None,
        "Month": str(pubdate.month) if pubdate else None,
        "Day": str(pubdate.day) if pubdate else None,
        "Writer": None if mi.is_null("authors") else ", ".join(mi.authors),
        "Publisher": _text(mi.publisher),
        "Genre": ", ".join(mi.tags) if mi.tags else None,
        "Tags": None,
        "LanguageISO": lang or (mi.languages[0] if mi.languages else None),
        "GTIN": (mi.get_identifiers() or {}).get("isbn"),
    }


def _new_root():
    return etree.Element("ComicInfo", nsmap={"xsi": XSI_NS, "xsd": XSD_NS})


def _insert_ordered(root, el):
    rank = ELEMENT_ORDER.index(etree.QName(el).localname)
    for idx, child in enumerate(root):
        if isinstance(child.tag, str) and etree.QName(child).localname in ELEMENT_ORDER and ELEMENT_ORDER.index(etree.QName(child).localname) > rank:
            root.insert(idx, el)
            return
    root.append(el)


def update_comicinfo(root, mi, apply_null=False):
    root = _new_root() if root is None else root
    tags_replaced = bool(mi.tags)
    for tag, value in _mi_values(mi).items():
        el = _child(root, tag)
        if tag == "Tags":
            if el is not None and (tags_replaced or apply_null):
                root.remove(el)
            continue
        if value is None:
            if apply_null and el is not None:
                root.remove(el)
            continue
        if el is None:
            el = etree.Element(tag)
            _insert_ordered(root, el)
        el.text = value
    return root


def comicinfo_bytes(root):
    etree.indent(root, space="  ")
    return etree.tostring(root, xml_declaration=True, encoding="utf-8")


def normalize_comicinfo(root):
    if root is None:
        return {}
    return {tag: _value(root, tag) for tag in MANAGED_ELEMENTS if _value(root, tag) is not None}


def _rewrite_zip(stream, name, data, exists):
    from calibre.utils.zipfile import ZipFile

    stream.seek(0)
    src = ZipFile(stream, "r")
    temp = SpooledTemporaryFile(max_size=100 * 1024 * 1024)
    dst = ZipFile(temp, "w")
    count = 0
    for info in src.infolist():
        if info.filename == name:
            dst.writestr(info, data)
        else:
            dst.writestr(info, src.read_raw(info), raw_bytes=True)
        count += 1
    if not exists:
        dst.writestr(name, data)
        count += 1
    dst.comment = src.comment
    dst.close()
    src.close()
    return temp, count


def write_metadata(stream, mi, apply_null=False):
    stream.seek(0)
    with zipfile.ZipFile(stream) as zf:
        info = _find_comicinfo(zf.infolist())
        old_root = None
        if info is not None:
            if info.file_size > MAX_COMICINFO_BYTES:
                raise CbzMetadataError("ComicInfo.xml is too large")
            old_root = _parse_comicinfo(zf.read(info))
    before = normalize_comicinfo(old_root)
    root = update_comicinfo(old_root, mi, apply_null)
    expected = normalize_comicinfo(root)
    if expected == before and (old_root is not None or not expected):
        return False

    name = info.filename if info is not None else COMICINFO_NAME
    temp, count = _rewrite_zip(stream, name, comicinfo_bytes(root), info is not None)
    with temp:
        temp.seek(0)
        with zipfile.ZipFile(temp) as check:
            if len(check.infolist()) != count or normalize_comicinfo(_parse_comicinfo(check.read(name))) != expected:
                raise CbzMetadataError("CBZ metadata verification failed, file left unchanged")
        temp.seek(0)
        stream.seek(0)
        stream.truncate()
        shutil.copyfileobj(temp, stream)
        stream.flush()
    return True
