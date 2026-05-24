# -*- coding: UTF-8 -*-
"""
Podcast OPML Builder

Generates OPML 2.0 documents for audiobooks, suitable for importing
into podcast applications that support OPML subscription lists.

Each audiobook is represented as a podcast outline with all episodes
embedded as child outlines, following the OPML 2.0 specification.
"""

import datetime
import re
import xml.etree.ElementTree as ET


def _safe_xml(text):
    """Remove control characters that are invalid in XML."""
    if not text:
        return ""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(text))


def _format_duration(seconds):
    """Format duration in seconds to HH:MM:SS string."""
    if not seconds or seconds <= 0:
        return "00:00:00"
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _format_rfc2822(dt):
    """Format a datetime object as RFC 2822 date string."""
    if dt is None:
        dt = datetime.datetime.now()
    if isinstance(dt, str):
        try:
            dt = datetime.datetime.fromisoformat(dt)
        except (ValueError, TypeError):
            dt = datetime.datetime.now()
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    months = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    return "{day}, {d:02d} {mon} {y} {h:02d}:{m:02d}:{s:02d} +0000".format(
        day=days[dt.weekday()],
        d=dt.day,
        mon=months[dt.month - 1],
        y=dt.year,
        h=dt.hour,
        m=dt.minute,
        s=dt.second,
    )


def build_book_opml(book_info, episodes, site_url, site_title="MyBooks", token=None):
    """
    Build an OPML 2.0 document for a single audiobook with all episodes embedded.

    Args:
        book_info: dict with keys: id, title, authors, description, cover_url, pub_date, language
        episodes: list of dicts with keys: title, url, size, duration, index, author
        site_url: base URL of the site (e.g. "https://example.com")
        site_title: name of the site for the generator field
        token: optional podcast token (already embedded in episode URLs by the provider)

    Returns:
        XML bytes of the OPML 2.0 document
    """
    opml = ET.Element("opml", {"version": "2.0"})

    # --- head ---
    head = ET.SubElement(opml, "head")

    book_title = _safe_xml(book_info.get("title", "Unknown"))
    authors = book_info.get("authors", [])
    author_str = _safe_xml(", ".join(authors) if authors else "Unknown")
    description = _safe_xml(book_info.get("description", "")) or book_title
    cover_url = book_info.get("cover_url", "")
    if cover_url and token:
        cover_url = cover_url + f"?token={token}"
    language = book_info.get("language", "zh-cn")
    feed_url = f"{site_url}/podcast/book/{book_info['id']}"
    if token:
        feed_url += f"?token={token}"

    ET.SubElement(head, "title").text = book_title
    ET.SubElement(head, "dateCreated").text = _format_rfc2822(
        book_info.get("pub_date")
    )
    ET.SubElement(head, "dateModified").text = _format_rfc2822(datetime.datetime.now())
    ET.SubElement(head, "ownerName").text = author_str
    ET.SubElement(head, "docs").text = "http://opml.org/spec2.opml"

    # --- body ---
    body = ET.SubElement(opml, "body")

    # Top-level outline representing the podcast/book
    book_attrs = {
        "type": "rss",
        "text": book_title,
        "title": book_title,
        "description": description,
        "xmlUrl": feed_url,
        "htmlUrl": f"{site_url}/podcast/book/{book_info['id']}",
        "language": language,
        "author": author_str,
    }
    if cover_url:
        book_attrs["imageUrl"] = cover_url

    book_outline = ET.SubElement(body, "outline", book_attrs)

    # Child outlines — one per episode
    pub_date_base = book_info.get("pub_date") or datetime.datetime(2020, 1, 1)
    if isinstance(pub_date_base, str):
        try:
            pub_date_base = datetime.datetime.fromisoformat(pub_date_base)
        except (ValueError, TypeError):
            pub_date_base = datetime.datetime(2020, 1, 1)

    for i, ep in enumerate(episodes):
        ep_title = _safe_xml(ep.get("title", f"Chapter {i + 1}"))
        ep_url = ep["url"]
        ep_size = str(ep.get("size", 0))
        ep_duration = _format_duration(ep.get("duration", 0))
        ep_author = _safe_xml(ep.get("author") or author_str)
        ep_date = pub_date_base + datetime.timedelta(minutes=ep.get("index", i))

        # Determine MIME type from URL
        if ep_url.endswith(".wav"):
            mime_type = "audio/wav"
        elif ep_url.endswith(".m4a"):
            mime_type = "audio/mp4"
        elif ep_url.endswith(".opus"):
            mime_type = "audio/opus"
        else:
            mime_type = "audio/mpeg"

        ep_attrs = {
            "type": "rss",
            "text": ep_title,
            "title": ep_title,
            "url": ep_url,
            "enclosureUrl": ep_url,
            "enclosureLength": ep_size,
            "enclosureType": mime_type,
            "duration": ep_duration,
            "author": ep_author,
            "pubDate": _format_rfc2822(ep_date),
            "episode": str(ep.get("index", i) + 1),
        }
        ET.SubElement(book_outline, "outline", ep_attrs)

    # Serialize
    tree = ET.ElementTree(opml)
    ET.indent(tree, space="  ")
    xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
    return xml_declaration.encode("utf-8") + ET.tostring(
        opml, encoding="unicode"
    ).encode("utf-8")
