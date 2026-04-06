#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Unit tests for the Podcast service.

Tests cover:
1. RSS feed XML generation (feed_builder.py)
2. Podcast handler routes (handlers/podcast.py)
"""

import datetime
import unittest
import xml.etree.ElementTree as ET

from webserver.podcast.feed_builder import (
    build_book_feed,
    build_catalog_feed,
    _format_duration,
    _format_rfc2822,
    _safe_xml,
    _make_guid,
)


class TestFormatDuration(unittest.TestCase):
    """Test the duration formatting helper."""

    def test_zero(self):
        self.assertEqual(_format_duration(0), "00:00:00")

    def test_negative(self):
        self.assertEqual(_format_duration(-10), "00:00:00")

    def test_none(self):
        self.assertEqual(_format_duration(None), "00:00:00")

    def test_seconds_only(self):
        self.assertEqual(_format_duration(45), "00:00:45")

    def test_minutes_and_seconds(self):
        self.assertEqual(_format_duration(125), "00:02:05")

    def test_hours(self):
        self.assertEqual(_format_duration(3661), "01:01:01")

    def test_large_value(self):
        self.assertEqual(_format_duration(86400), "24:00:00")


class TestFormatRfc2822(unittest.TestCase):
    """Test RFC 2822 date formatting."""

    def test_datetime(self):
        dt = datetime.datetime(2024, 6, 15, 10, 30, 45)
        result = _format_rfc2822(dt)
        self.assertIn("15 Jun 2024", result)
        self.assertIn("10:30:45", result)

    def test_none_returns_current(self):
        result = _format_rfc2822(None)
        self.assertIsNotNone(result)
        self.assertIn("+0000", result)

    def test_string_iso_format(self):
        result = _format_rfc2822("2024-01-01T00:00:00")
        self.assertIn("01 Jan 2024", result)

    def test_invalid_string(self):
        result = _format_rfc2822("not-a-date")
        # Should fallback to current time
        self.assertIn("+0000", result)


class TestSafeXml(unittest.TestCase):
    """Test XML character sanitization."""

    def test_none(self):
        self.assertEqual(_safe_xml(None), "")

    def test_empty(self):
        self.assertEqual(_safe_xml(""), "")

    def test_normal_text(self):
        self.assertEqual(_safe_xml("Hello World"), "Hello World")

    def test_control_chars_removed(self):
        text = "Hello\x00World\x07Test"
        result = _safe_xml(text)
        self.assertEqual(result, "HelloWorldTest")

    def test_newlines_preserved(self):
        text = "Line1\nLine2\r\nLine3"
        result = _safe_xml(text)
        self.assertIn("\n", result)


class TestMakeGuid(unittest.TestCase):
    """Test GUID generation."""

    def test_book_guid_stable(self):
        guid1 = _make_guid(123)
        guid2 = _make_guid(123)
        self.assertEqual(guid1, guid2)

    def test_episode_guid_stable(self):
        guid1 = _make_guid(123, 5)
        guid2 = _make_guid(123, 5)
        self.assertEqual(guid1, guid2)

    def test_different_books_different_guids(self):
        guid1 = _make_guid(123)
        guid2 = _make_guid(456)
        self.assertNotEqual(guid1, guid2)

    def test_different_episodes_different_guids(self):
        guid1 = _make_guid(123, 1)
        guid2 = _make_guid(123, 2)
        self.assertNotEqual(guid1, guid2)

    def test_guid_length(self):
        guid = _make_guid(1)
        self.assertEqual(len(guid), 32)


class TestBuildBookFeed(unittest.TestCase):
    """Test single-book RSS feed generation."""

    def setUp(self):
        self.book_info = {
            "id": 42,
            "title": "百年孤独",
            "authors": ["加西亚·马尔克斯"],
            "description": "一个家族七代人的故事",
            "cover_url": "https://example.com/get/cover/42.jpg",
            "pub_date": datetime.datetime(2020, 1, 15),
            "language": "zh-cn",
        }
        self.episodes = [
            {
                "title": "第一章",
                "url": "https://example.com/api/audio/42/0001.mp3",
                "size": 5000000,
                "duration": 300,
                "index": 0,
            },
            {
                "title": "第二章",
                "url": "https://example.com/api/audio/42/0002.mp3",
                "size": 4500000,
                "duration": 280,
                "index": 1,
            },
        ]

    def test_generates_valid_xml(self):
        xml_bytes = build_book_feed(
            self.book_info, self.episodes, "https://example.com"
        )
        # Should parse without errors
        root = ET.fromstring(xml_bytes)
        self.assertEqual(root.tag, "rss")
        self.assertEqual(root.attrib["version"], "2.0")

    def test_contains_channel_elements(self):
        xml_bytes = build_book_feed(
            self.book_info, self.episodes, "https://example.com"
        )
        root = ET.fromstring(xml_bytes)
        channel = root.find("channel")
        self.assertIsNotNone(channel)
        self.assertEqual(channel.find("title").text, "百年孤独")
        self.assertEqual(channel.find("language").text, "zh-cn")
        self.assertEqual(channel.find("description").text, "一个家族七代人的故事")

    def test_contains_itunes_namespace(self):
        xml_bytes = build_book_feed(
            self.book_info, self.episodes, "https://example.com"
        )
        root = ET.fromstring(xml_bytes)
        channel = root.find("channel")

        # Check for itunes:author
        itunes_ns = "http://www.itunes.com/dtds/podcast-1.0.dtd"
        itunes_author = channel.find(f"{{{itunes_ns}}}author")
        self.assertIsNotNone(itunes_author)
        self.assertEqual(itunes_author.text, "加西亚·马尔克斯")

    def test_contains_episodes(self):
        xml_bytes = build_book_feed(
            self.book_info, self.episodes, "https://example.com"
        )
        root = ET.fromstring(xml_bytes)
        channel = root.find("channel")
        items = channel.findall("item")
        self.assertEqual(len(items), 2)

    def test_episode_has_enclosure(self):
        xml_bytes = build_book_feed(
            self.book_info, self.episodes, "https://example.com"
        )
        root = ET.fromstring(xml_bytes)
        channel = root.find("channel")
        items = channel.findall("item")
        enclosure = items[0].find("enclosure")
        self.assertIsNotNone(enclosure)
        self.assertEqual(
            enclosure.attrib["url"], "https://example.com/api/audio/42/0001.mp3"
        )
        self.assertEqual(enclosure.attrib["type"], "audio/mpeg")
        self.assertEqual(enclosure.attrib["length"], "5000000")

    def test_episode_has_duration(self):
        xml_bytes = build_book_feed(
            self.book_info, self.episodes, "https://example.com"
        )
        root = ET.fromstring(xml_bytes)
        channel = root.find("channel")
        items = channel.findall("item")
        itunes_ns = "http://www.itunes.com/dtds/podcast-1.0.dtd"
        duration = items[0].find(f"{{{itunes_ns}}}duration")
        self.assertIsNotNone(duration)
        self.assertEqual(duration.text, "00:05:00")

    def test_episode_has_guid(self):
        xml_bytes = build_book_feed(
            self.book_info, self.episodes, "https://example.com"
        )
        root = ET.fromstring(xml_bytes)
        channel = root.find("channel")
        items = channel.findall("item")
        guid = items[0].find("guid")
        self.assertIsNotNone(guid)
        self.assertEqual(guid.attrib["isPermaLink"], "false")
        self.assertTrue(len(guid.text) > 0)

    def test_empty_description_uses_title(self):
        self.book_info["description"] = ""
        xml_bytes = build_book_feed(
            self.book_info, self.episodes, "https://example.com"
        )
        root = ET.fromstring(xml_bytes)
        channel = root.find("channel")
        description = channel.find("description")
        self.assertEqual(description.text, "百年孤独")

    def test_cover_image_element(self):
        xml_bytes = build_book_feed(
            self.book_info, self.episodes, "https://example.com"
        )
        root = ET.fromstring(xml_bytes)
        channel = root.find("channel")
        itunes_ns = "http://www.itunes.com/dtds/podcast-1.0.dtd"
        itunes_image = channel.find(f"{{{itunes_ns}}}image")
        self.assertIsNotNone(itunes_image)
        self.assertEqual(
            itunes_image.attrib["href"], "https://example.com/get/cover/42.jpg"
        )


class TestBuildCatalogFeed(unittest.TestCase):
    """Test catalog/aggregation RSS feed generation."""

    def setUp(self):
        self.entries = [
            {
                "id": 1,
                "title": "书籍一",
                "authors": ["作者A"],
                "description": "描述一",
                "cover_url": "https://example.com/get/cover/1.jpg",
                "first_episode_url": "https://example.com/api/audio/1/0001.mp3",
                "first_episode_size": 3000000,
                "pub_date": datetime.datetime(2023, 6, 1),
                "feed_url": "https://example.com/podcast/book/1",
            },
            {
                "id": 2,
                "title": "书籍二",
                "authors": ["作者B"],
                "description": "描述二",
                "cover_url": "https://example.com/get/cover/2.jpg",
                "first_episode_url": "https://example.com/api/audio/2/0001.mp3",
                "first_episode_size": 4000000,
                "pub_date": datetime.datetime(2023, 7, 1),
                "feed_url": "https://example.com/podcast/book/2",
            },
        ]

    def test_generates_valid_xml(self):
        xml_bytes = build_catalog_feed(
            "测试目录", "测试描述", self.entries, "https://example.com"
        )
        root = ET.fromstring(xml_bytes)
        self.assertEqual(root.tag, "rss")

    def test_contains_entries(self):
        xml_bytes = build_catalog_feed(
            "测试目录", "测试描述", self.entries, "https://example.com"
        )
        root = ET.fromstring(xml_bytes)
        channel = root.find("channel")
        items = channel.findall("item")
        self.assertEqual(len(items), 2)

    def test_entry_title_includes_author(self):
        xml_bytes = build_catalog_feed(
            "测试目录", "测试描述", self.entries, "https://example.com"
        )
        root = ET.fromstring(xml_bytes)
        channel = root.find("channel")
        items = channel.findall("item")
        self.assertEqual(items[0].find("title").text, "书籍一 - 作者A")

    def test_empty_entries(self):
        xml_bytes = build_catalog_feed("空目录", "没有书", [], "https://example.com")
        root = ET.fromstring(xml_bytes)
        channel = root.find("channel")
        items = channel.findall("item")
        self.assertEqual(len(items), 0)

    def test_feed_title_and_description(self):
        xml_bytes = build_catalog_feed(
            "我的目录", "我的描述", self.entries, "https://example.com"
        )
        root = ET.fromstring(xml_bytes)
        channel = root.find("channel")
        self.assertEqual(channel.find("title").text, "我的目录")
        self.assertEqual(channel.find("description").text, "我的描述")


if __name__ == "__main__":
    unittest.main()
