#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import html
import io
import logging
import os
import re

from calibre.ebooks.metadata import authors_to_string, check_isbn, fmt_sidx, string_to_authors
from calibre.ebooks.metadata.book.base import Metadata
from calibre.utils.date import isoformat, parse_date, parse_only_date
from calibre.utils.localization import canonicalize_lang

MAX_EDIT_BYTES = 512 * 1024 * 1024
COVER_MAX_HEIGHT = 1200
COVER_JPEG_QUALITY = 85
FIXED_KEYS = ("title", "author", "subject", "publisher", "year", "keywords")
MANAGED_EXTRA_KEYS = ("isbn", "series", "series_index", "language", "pubdate")
IDENTIFIER_PREFIX = "identifier:"
TAG_SPLIT_RE = re.compile(r"[,;，；]")
BLOCK_END_RE = re.compile(r"(?i)<br\s*/?>|</(p|div|li|h[1-6])\s*>")
TAG_RE = re.compile(r"<[^>]*>")

log = logging.getLogger(__name__)


class DjVuMetadataError(Exception):
    pass


def _open_document(stream):
    import djvu_rs

    stream.seek(0)
    name = getattr(stream, "name", None)
    if isinstance(name, str) and os.path.isfile(name):
        return djvu_rs.Document.open(name)
    return djvu_rs.Document.from_bytes(stream.read())


def _text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _is_managed_extra(key):
    return key in MANAGED_EXTRA_KEYS or key.startswith(IDENTIFIER_PREFIX)


def _parse_pubdate(pubdate, year):
    for raw, parser in ((pubdate, parse_date), (year, None)):
        if not raw:
            continue
        try:
            if parser:
                return parser(raw, assume_utc=True)
            match = re.match(r"^\s*(\d{4})", raw)
            if match:
                return parse_only_date("%s-01-01" % match.group(1))
        except Exception:
            log.info("Ignore invalid DjVu date: %r", raw)
    return None


def meta_to_mi(meta, mi=None):
    if mi is None:
        mi = Metadata(None, None)
    meta = meta or {}
    extra = {}
    for key, value in meta.get("extra") or []:
        extra.setdefault(key, value)

    title = _text(meta.get("title"))
    if title:
        mi.title = title
    authors = string_to_authors(_text(meta.get("author")) or "")
    if authors:
        mi.authors = authors
    mi.comments = _text(meta.get("subject"))
    mi.publisher = _text(meta.get("publisher"))
    mi.tags = [t.strip() for t in TAG_SPLIT_RE.split(meta.get("keywords") or "") if t.strip()]

    pubdate = _parse_pubdate(_text(extra.get("pubdate")), _text(meta.get("year")))
    if pubdate is not None:
        mi.pubdate = pubdate

    identifiers = {}
    isbn = check_isbn(_text(extra.get("isbn")) or "")
    if isbn:
        identifiers["isbn"] = isbn
    for key, value in extra.items():
        if key.startswith(IDENTIFIER_PREFIX) and _text(value):
            identifiers[key[len(IDENTIFIER_PREFIX):]] = _text(value)
    if identifiers:
        mi.set_identifiers(identifiers)

    series = _text(extra.get("series"))
    if series:
        mi.series = series
        try:
            mi.series_index = float(extra.get("series_index") or 1)
        except ValueError:
            mi.series_index = 1.0
    languages = [canonicalize_lang(x.strip()) for x in (extra.get("language") or "").split(",") if x.strip()]
    languages = [x for x in languages if x]
    if languages:
        mi.languages = languages
    return mi


def _comments_to_text(comments):
    comments = _text(comments)
    if not comments or comments == "<>":
        return None
    if "<" not in comments:
        return comments
    text = html.unescape(TAG_RE.sub("", BLOCK_END_RE.sub("\n", comments)))
    return _text(re.sub(r"\n{3,}", "\n\n", text))


def _mi_fixed(mi):
    pubdate = None if mi.is_null("pubdate") else mi.pubdate
    return {
        "title": None if mi.is_null("title") else _text(mi.title),
        "author": None if mi.is_null("authors") else _text(authors_to_string(mi.authors)),
        "subject": _comments_to_text(mi.comments),
        "publisher": _text(mi.publisher),
        "year": str(pubdate.year) if pubdate else None,
        "keywords": ", ".join(mi.tags) if mi.tags else None,
    }


def _mi_extra(mi):
    extra = {}
    identifiers = dict(mi.get_identifiers() or {})
    isbn = identifiers.pop("isbn", None)
    if isbn:
        extra["isbn"] = isbn
    if not mi.is_null("series"):
        extra["series"] = mi.series
        extra["series_index"] = fmt_sidx(mi.series_index if mi.series_index is not None else 1)
    if mi.languages:
        extra["language"] = ",".join(mi.languages)
    if not mi.is_null("pubdate"):
        extra["pubdate"] = isoformat(mi.pubdate, as_utc=True)
    for key, value in sorted(identifiers.items()):
        if value:
            extra[IDENTIFIER_PREFIX + key] = value
    return extra


def mi_to_meta(mi, old=None, apply_null=False):
    old = old or {}
    meta = {}
    for key, value in _mi_fixed(mi).items():
        meta[key] = value if value is not None or apply_null else old.get(key)

    wanted = _mi_extra(mi)
    extra, emitted = [], set()
    for key, value in old.get("extra") or []:
        if not _is_managed_extra(key):
            extra.append((key, value))
        elif key in emitted:
            continue
        elif key in wanted:
            extra.append((key, wanted[key]))
            emitted.add(key)
        elif not apply_null:
            extra.append((key, value))
            emitted.add(key)
    extra.extend((k, v) for k, v in wanted.items() if k not in emitted)
    meta["extra"] = extra
    return meta


def normalize_meta(meta):
    meta = meta or {}
    ans = {k: meta.get(k) for k in FIXED_KEYS if meta.get(k) is not None}
    extra = [tuple(pair) for pair in meta.get("extra") or []]
    if extra:
        ans["extra"] = extra
    return ans


def render_cover(doc):
    from PIL import Image

    if doc.page_count() < 1:
        return None
    page = doc.page(0)
    dpi = page.dpi
    if page.height > COVER_MAX_HEIGHT:
        dpi = max(1, int(page.dpi * COVER_MAX_HEIGHT / page.height))
    img = page.render(dpi=dpi).to_pil()
    canvas = Image.new("RGB", img.size, "white")
    canvas.paste(img, mask=img.getchannel("A"))
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=COVER_JPEG_QUALITY)
    return ("jpeg", buf.getvalue())


def read_metadata(stream, quick=False):
    mi = Metadata(None, None)
    try:
        doc = _open_document(stream)
        meta_to_mi(doc.metadata(), mi)
    except Exception as err:
        log.warning("Failed to read DjVu metadata: %s", err)
        return mi
    if not quick:
        try:
            mi.cover_data = render_cover(doc) or (None, None)
        except Exception as err:
            log.warning("Failed to render DjVu cover: %s", err)
    return mi


def write_metadata(stream, mi, apply_null=False):
    import djvu_rs

    stream.seek(0, os.SEEK_END)
    if stream.tell() > MAX_EDIT_BYTES:
        raise DjVuMetadataError("DjVu file is larger than %d MB, skip writing metadata" % (MAX_EDIT_BYTES // 1024 // 1024))
    stream.seek(0)
    editor = djvu_rs.Editor.from_bytes(stream.read())
    old = editor.metadata() or {}
    new = mi_to_meta(mi, old, apply_null)
    if normalize_meta(new) == normalize_meta(old):
        return False

    editor.set_metadata(new)
    out = editor.to_bytes()
    check = djvu_rs.Document.from_bytes(out)
    if check.page_count() != editor.page_count() or normalize_meta(check.metadata()) != normalize_meta(new):
        raise DjVuMetadataError("DjVu metadata verification failed, file left unchanged")

    stream.seek(0)
    stream.write(out)
    stream.truncate()
    stream.flush()
    return True
