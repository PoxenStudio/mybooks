# -*- coding: UTF-8 -*-
"""
Podcast RSS 2.0 Feed Builder

Generates RSS 2.0 XML feeds compliant with Apple Podcasts and Spotify specifications.
Each audiobook is represented as a podcast channel with chapters as episodes.
"""

import datetime
import hashlib
import re
import xml.etree.ElementTree as ET


# iTunes namespace
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
# Podcast namespace (Podcasting 2.0)
PODCAST_NS = "https://podcastindex.org/namespace/1.0"

# Register namespaces so they appear cleanly in output
ET.register_namespace("itunes", ITUNES_NS)
ET.register_namespace("podcast", PODCAST_NS)


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
    """Format a datetime object as RFC 2822 date string for RSS."""
    if dt is None:
        dt = datetime.datetime.now()
    if isinstance(dt, str):
        try:
            dt = datetime.datetime.fromisoformat(dt)
        except (ValueError, TypeError):
            dt = datetime.datetime.now()
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    months = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
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


def _make_guid(book_id, episode_index=None):
    """Generate a stable GUID for a podcast item."""
    key = f"talebook-podcast-{book_id}"
    if episode_index is not None:
        key += f"-ep{episode_index}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def build_book_feed(book_info, episodes, site_url, site_title="Talebook"):
    """
    Build an RSS 2.0 podcast feed for a single audiobook.

    Args:
        book_info: dict with keys: id, title, authors, description, cover_url, pub_date, language
        episodes: list of dicts with keys: title, url, size, duration, index
        site_url: base URL of the site (e.g. "https://example.com")

    Returns:
        XML bytes of the RSS 2.0 feed
    """
    rss = ET.Element(
        "rss",
        {
            "version": "2.0",
        },
    )

    channel = ET.SubElement(rss, "channel")

    # Required channel elements
    title = _safe_xml(book_info.get("title", "Unknown"))
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = f"{site_url}/podcast/book/{book_info['id']}"
    description = _safe_xml(book_info.get("description", ""))
    if not description:
        description = title
    ET.SubElement(channel, "description").text = description
    ET.SubElement(channel, "language").text = book_info.get("language", "zh-cn")
    ET.SubElement(channel, "generator").text = f"{site_title} Podcast Service"

    # iTunes specific elements
    itunes_author = ET.SubElement(channel, f"{{{ITUNES_NS}}}author")
    authors = book_info.get("authors", [])
    itunes_author.text = ", ".join(authors) if authors else "Unknown"

    itunes_summary = ET.SubElement(channel, f"{{{ITUNES_NS}}}summary")
    itunes_summary.text = description

    # Cover image
    cover_url = book_info.get("cover_url", "")
    if cover_url:
        ET.SubElement(channel, f"{{{ITUNES_NS}}}image", {"href": cover_url})
        image = ET.SubElement(channel, "image")
        ET.SubElement(image, "url").text = cover_url
        ET.SubElement(image, "title").text = title
        ET.SubElement(image, "link").text = f"{site_url}/podcast/book/{book_info['id']}"

    # Category
    ET.SubElement(channel, f"{{{ITUNES_NS}}}category", {"text": "Arts"})
    ET.SubElement(channel, f"{{{ITUNES_NS}}}explicit").text = "false"
    ET.SubElement(channel, f"{{{ITUNES_NS}}}type").text = "serial"

    # Publication date
    pub_date = book_info.get("pub_date")
    ET.SubElement(channel, "pubDate").text = _format_rfc2822(pub_date)
    ET.SubElement(channel, "lastBuildDate").text = _format_rfc2822(
        datetime.datetime.now()
    )

    # Episodes (chapters)
    for i, ep in enumerate(episodes):
        item = ET.SubElement(channel, "item")
        ep_title = _safe_xml(ep.get("title", f"Chapter {i + 1}"))
        ET.SubElement(item, "title").text = ep_title

        # Enclosure - required for podcast players
        ET.SubElement(
            item,
            "enclosure",
            {
                "url": ep["url"],
                "length": str(ep.get("size", 0)),
                "type": "audio/mpeg",
            },
        )

        # GUID
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = _make_guid(
            book_info["id"], ep.get("index", i)
        )

        # Description
        ET.SubElement(item, "description").text = ep_title

        # iTunes episode metadata
        duration = ep.get("duration", 0)
        if duration:
            ET.SubElement(item, f"{{{ITUNES_NS}}}duration").text = _format_duration(
                duration
            )
        ET.SubElement(item, f"{{{ITUNES_NS}}}episode").text = str(
            ep.get("index", i) + 1
        )
        ET.SubElement(item, f"{{{ITUNES_NS}}}episodeType").text = "full"
        ET.SubElement(item, f"{{{ITUNES_NS}}}title").text = ep_title

        # Pub date - spread episodes across time so they order correctly
        ep_date = pub_date or datetime.datetime(2020, 1, 1)
        if isinstance(ep_date, str):
            try:
                ep_date = datetime.datetime.fromisoformat(ep_date)
            except (ValueError, TypeError):
                ep_date = datetime.datetime(2020, 1, 1)
        ep_date = ep_date + datetime.timedelta(minutes=ep.get("index", i))
        ET.SubElement(item, "pubDate").text = _format_rfc2822(ep_date)

    # Serialize
    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
    return xml_declaration.encode("utf-8") + ET.tostring(
        rss, encoding="unicode"
    ).encode("utf-8")


def build_catalog_feed(
    title, description, book_entries, site_url, language="zh-cn", site_title="Talebook"
):
    """
    Build an RSS 2.0 feed listing multiple audiobooks (catalog/aggregation feed).

    Each audiobook becomes one episode in this catalog feed, with the first chapter
    as the enclosure and the book's own feed URL as the link.

    Args:
        title: feed title (e.g. "科幻" or "全部有声书")
        description: feed description
        book_entries: list of dicts with keys:
            id, title, authors, description, cover_url, first_episode_url,
            first_episode_size, pub_date, feed_url
        site_url: base URL
        language: feed language code

    Returns:
        XML bytes of the RSS 2.0 feed
    """
    rss = ET.Element(
        "rss",
        {
            "version": "2.0",
        },
    )

    channel = ET.SubElement(rss, "channel")

    feed_title = _safe_xml(title)
    ET.SubElement(channel, "title").text = feed_title
    ET.SubElement(channel, "link").text = site_url + "/podcast/"
    ET.SubElement(channel, "description").text = _safe_xml(description) or feed_title
    ET.SubElement(channel, "language").text = language
    ET.SubElement(channel, "generator").text = f"{site_title} Podcast Service"
    ET.SubElement(channel, "lastBuildDate").text = _format_rfc2822(
        datetime.datetime.now()
    )

    # iTunes metadata
    ET.SubElement(channel, f"{{{ITUNES_NS}}}author").text = site_title
    ET.SubElement(channel, f"{{{ITUNES_NS}}}summary").text = (
        _safe_xml(description) or feed_title
    )
    ET.SubElement(channel, f"{{{ITUNES_NS}}}explicit").text = "false"
    ET.SubElement(channel, f"{{{ITUNES_NS}}}type").text = "episodic"

    # Book entries as episodes
    for i, book in enumerate(book_entries):
        item = ET.SubElement(channel, "item")
        book_title = _safe_xml(book.get("title", "Unknown"))
        authors = book.get("authors", [])
        author_str = ", ".join(authors) if authors else "Unknown"
        ET.SubElement(item, "title").text = f"{book_title} - {author_str}"

        book_desc = _safe_xml(book.get("description", ""))
        ET.SubElement(item, "description").text = book_desc or book_title

        # Link to individual book feed
        feed_url = book.get("feed_url", "")
        if feed_url:
            ET.SubElement(item, "link").text = feed_url

        # Enclosure with first episode
        first_ep_url = book.get("first_episode_url", "")
        if first_ep_url:
            ET.SubElement(
                item,
                "enclosure",
                {
                    "url": first_ep_url,
                    "length": str(book.get("first_episode_size", 0)),
                    "type": "audio/mpeg",
                },
            )

        # GUID
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = _make_guid(
            book["id"]
        )

        # iTunes metadata
        ET.SubElement(item, f"{{{ITUNES_NS}}}author").text = author_str
        if book.get("cover_url"):
            ET.SubElement(item, f"{{{ITUNES_NS}}}image", {"href": book["cover_url"]})
        ET.SubElement(item, f"{{{ITUNES_NS}}}episode").text = str(i + 1)

        # Publication date
        pub_date = book.get("pub_date")
        ET.SubElement(item, "pubDate").text = _format_rfc2822(pub_date)

    # Serialize
    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
    return xml_declaration.encode("utf-8") + ET.tostring(
        rss, encoding="unicode"
    ).encode("utf-8")
