#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
#
# 悠久小说网(wap.ujxsw.org) 元数据搜索 API
#
# 通过手机站 searchbooks.php 表单接口搜索，解析结果列表页里的
# 封面(bookimg)、书名(bookname)、作者(作者：)、出版时间(时间：)信息。
# 注意：该站点手机版仅提供 http（非 https）访问。
# @author: PoxenStudio, 2026-08

import datetime
import logging
import urllib.parse
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from webserver.constants import CHROME_MOBILE_HEADERS

KEY = "Ujxsw"

_SITE_ROOT = "http://wap.ujxsw.org"
_SEARCH_URL = f"{_SITE_ROOT}/searchbooks.php"

_SEARCH_HEADERS = {
    **CHROME_MOBILE_HEADERS,
    "Accept": "text/html",
    "Cache-Control": "no-cache",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": _SITE_ROOT,
    "Pragma": "no-cache",
}


def search(keyword, max_count=2):
    """搜索悠久小说网，返回不超过 max_count 条书籍信息（dict 列表）。"""
    if not keyword:
        return []
    payload = {"searchkey": keyword, "submit": ""}
    try:
        resp = requests.post(_SEARCH_URL, data=payload, headers=_SEARCH_HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error("[Ujxsw]搜索请求失败: %s", e)
        return []

    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    items = []
    for box in soup.select("div.bookbox"):
        item = _parse_book_box(box)
        if item:
            items.append(item)
        if len(items) >= max_count:
            break
    return items


def _parse_book_box(box):
    name_tag = box.select_one(".bookname a")
    if not name_tag:
        return None
    title = name_tag.get_text(strip=True)
    if not title:
        return None
    book_href = name_tag.get("href", "")
    book_url = urllib.parse.urljoin(_SITE_ROOT, book_href) if book_href else ""

    author = ""
    author_div = box.find("div", class_="author")
    if author_div:
        author_link = author_div.find("a")
        author = author_link.get_text(strip=True) if author_link else author_div.get_text(strip=True).replace("作者：", "").strip()

    pub_date = ""
    cat_div = box.find("div", class_="cat")
    if cat_div:
        pub_date = cat_div.get_text(strip=True).replace("时间：", "").strip()

    cover_url = ""
    img = box.select_one(".bookimg img")
    if img and img.get("src"):
        cover_url = urllib.parse.urljoin(_SITE_ROOT, img["src"])

    return {
        "id": box.get("id", ""),
        "title": title,
        "author": author or "佚名",
        "pub_date": pub_date,
        "cover_url": cover_url,
        "url": book_url,
    }


def get_cover(cover_url, referer=f"{_SITE_ROOT}/"):
    """下载封面图片，返回 (fmt, bytes) 或 None。"""
    if not cover_url:
        return None
    suffix = Path(urlparse(cover_url).path).suffix.lstrip(".") or "jpg"

    headers = {**CHROME_MOBILE_HEADERS, "Referer": referer}
    try:
        resp = requests.get(cover_url, headers=headers, timeout=10)
        resp.raise_for_status()
        if "image" not in resp.headers.get("Content-Type", ""):
            logging.error("[Ujxsw]封面下载失败，非图片响应: %s", resp.headers.get("Content-Type"))
            return None
        return (suffix, resp.content)
    except requests.exceptions.RequestException as e:
        logging.error("[Ujxsw]封面下载失败: %s", e)
        return None


def _parse_date(s):
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.datetime.strptime(s, fmt).replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    return None


def build_metadata(item, isbn=None, copy_image=False):
    from calibre.ebooks.metadata.book.base import Metadata
    from calibre.utils.date import utcnow

    title = item.get("title", "")
    author = item.get("author") or "佚名"

    mi = Metadata(title)
    mi.authors = [author]
    mi.author = author
    mi.author_sort = author
    mi.timestamp = utcnow()
    mi.source = "悠久小说网"
    mi.provider_key = KEY
    mi.provider_value = item.get("id", "")
    mi.website = item.get("url", "")
    mi.comments = ""

    if isbn:
        mi.isbn = isbn

    pub_date = _parse_date(item.get("pub_date", ""))
    if pub_date:
        mi.pubdate = pub_date

    cover_url = item.get("cover_url", "")
    if cover_url:
        if not copy_image:
            mi.cover_url = cover_url
        else:
            cover_data = get_cover(cover_url)
            mi.cover_url = cover_url
            if cover_data:
                mi.cover_data = cover_data
    return mi


def build_metadata_batch(items, isbn=None, copy_image=False):
    return [build_metadata(item, isbn=isbn, copy_image=copy_image) for item in items]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = search("大魔王", max_count=2)
    print(f"共找到 {len(results)} 条结果")
    for item in results:
        print(item)

    metas = build_metadata_batch(results, copy_image=False)
    for item, mi in zip(results, metas):
        print("-" * 40)
        print(f"Title: {mi.title}")
        print(f"Authors: {mi.authors}")
        print(f"PubDate: {mi.pubdate}")
        print(f"Cover: {mi.cover_url}")
