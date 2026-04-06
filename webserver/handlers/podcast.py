#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Podcast Handlers

Tornado request handlers serving podcast RSS feeds for audiobooks.
Supports both public feeds (all/category/tag/author) and
user-specific feeds (favorites/wants/reading/read) via token authentication.
"""

import logging
import os
import re
import urllib.parse

from tornado import web

from webserver import loader
from webserver.handlers.base import BaseHandler
from webserver.podcast.feed_builder import build_book_feed
from webserver.podcast.podcast_provider import PodcastProvider
from webserver import constants

CONF = loader.get_settings()
AUDIO_OUTPUT_FOLDER = CONF.get("audio_output_folder", "/data/books/audios/")

# Module-level provider instance, initialized lazily
_provider = None


def _get_provider(handler):
    """Get or create the PodcastProvider instance."""
    global _provider
    if _provider is None:
        cache = handler.calibre_db.new_api
        scoped_session = handler.settings["ScopedSession"]
        _provider = PodcastProvider(cache, lambda: scoped_session())
    return _provider


class PodcastBaseHandler(BaseHandler):
    """Base handler for all podcast endpoints."""

    def check_podcast_enabled(self):
        if not CONF.get(constants.ENABLE_PODCAST_SERVICE, True):
            raise web.HTTPError(503, reason="Podcast service is not enabled")

    def set_rss_headers(self):
        self.set_header("Content-Type", "application/rss+xml; charset=UTF-8")
        self.set_header("Cache-Control", "max-age=300")

    def _get_full_site_url(self):
        """Get full site URL for building absolute URLs."""
        host = self.request.headers.get("X-Forwarded-Host", self.request.host)
        protocol = self.request.headers.get("X-Forwarded-Proto", self.request.protocol)
        return protocol + "://" + host

    def _get_site_title(self):
        """Get configured site title."""
        return CONF.get("site_title", "Talebook")

    def _get_user_by_token(self, token):
        """Look up a user by their podcast_token."""
        if not token:
            return None
        from webserver.models import Reader

        try:
            user = (
                self.sqlite_session.query(Reader)
                .filter(Reader.podcast_token == token)
                .first()
            )
            return user
        except Exception as e:
            logging.error(f"Error looking up podcast token: {e}")
            return None

    def send_error_of_not_invited(self):
        """Override to return 401 for podcast endpoints (not JSON)."""
        self.set_header("WWW-Authenticate", "Basic")
        self.set_status(401)
        raise web.Finish()

    def should_be_installed(self):
        """Override to return 503 instead of JSON for podcast endpoints."""
        if CONF.get("installed", None) is False:
            raise web.HTTPError(503, reason="Not installed")

    def should_be_invited(self):
        """Skip invite check for podcast endpoints."""
        return

    def render_html_page(self, title, body_html, show_back=True):
        html = [
            "<!DOCTYPE html><html><head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{title}</title>",
            "<style>body{font-family:system-ui,-apple-system,sans-serif;max-width:800px;",
            "margin:40px auto;padding:0 20px;background:#f8f9fa;color:#333}",
            "h1{color:#1a73e8}h2{color:#555;border-bottom:1px solid #ddd;padding-bottom:8px}",
            "ul{list-style:none;padding:0}li{margin:8px 0; background:#fff; padding: 12px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1)}",
            "a{color:#1a73e8;text-decoration:none}a:hover{text-decoration:underline}",
            ".feed-url{font-family:monospace;background:#e8f0fe;padding:8px;",
            "border-radius:4px;font-size:13px; display:block; margin-top:8px; word-break: break-all;}",
            ".section{margin:24px 0}",
            ".token-info{background:#fff3cd;padding:12px;border-radius:8px;margin:16px 0}",
            ".book-meta{color:#666; font-size:14px; margin-top:4px}",
            "</style></head><body>",
            f"<h1>🎧 {title}</h1>",
        ]
        if show_back:
            html.append('<p><a href="/podcast">🔙 返回 Podcast 首页</a></p>')
        html.append(body_html)
        html.append("</body></html>")

        self.set_header("Content-Type", "text/html; charset=UTF-8")
        self.write("\n".join(html))

    def render_book_list(self, page_title, description, entries):
        html = []
        if description:
            html.append(f"<p>{description}</p>")

        if not entries:
            html.append("<p>暂无有声书</p>")
        else:
            html.append("<ul>")
            for book in entries:
                authors = ", ".join(book.get("authors", [])) or "未知作者"
                book_title = book.get("title", "未知书名")
                feed_url = book.get("feed_url", "")
                html.append("<li>")
                html.append(
                    f'<strong>{book_title}</strong> <span class="book-meta">({authors})</span>'
                )
                html.append(
                    '<div class="book-meta">请复制以下XML订阅地址，并在您的Podcast播放器中添加订阅：</div>'
                )
                html.append(f'<a class="feed-url" href="{feed_url}">{feed_url}</a>')
                html.append("</li>")
            html.append("</ul>")

        self.render_html_page(page_title, "\n".join(html))


class PodcastIndex(PodcastBaseHandler):
    """Root podcast page — lists all available feeds as a simple HTML page."""

    def get(self):
        self.check_podcast_enabled()
        site_url = self._get_full_site_url()
        provider = _get_provider(self)
        html = []

        token_to_use = None
        user = self.current_user
        if user and hasattr(user, "podcast_token") and user.podcast_token:
            token_to_use = user.podcast_token

        categories = provider.get_categories(self.current_user)
        tags = provider.get_tags(self.current_user)
        authors = provider.get_authors()

        if token_to_use:
            feed_map = {
                "favorite": ("我的收藏", provider.get_favorites),
                "wants": ("我的待读", provider.get_wants),
                "reading": ("在读", provider.get_reading),
                "read_done": ("已读", provider.get_read_done),
            }
            has_items = False
            for feed_type, (label, getter) in feed_map.items():
                book_ids = getter(user.id)
                if book_ids:
                    entries = provider.get_catalog_entries(
                        book_ids, site_url, token=token_to_use
                    )
                    if entries:
                        has_items = True
                        html.append('<div class="section">')
                        html.append(f"<h2>{label}</h2>")
                        html.append("<ul>")
                        for book in entries:
                            authors_str = (
                                ", ".join(book.get("authors", [])) or "未知作者"
                            )
                            book_title = book.get("title", "未知书名")
                            feed_url = book.get("feed_url", "")
                            html.append("<li>")
                            html.append(
                                f'<strong>{book_title}</strong> <span class="book-meta">({authors_str})</span>'
                            )
                            html.append(
                                '<div class="book-meta">请复制以下XML订阅地址，并在您的Podcast播放器中添加订阅：</div>'
                            )
                            html.append(
                                f'<a class="feed-url" href="{feed_url}">{feed_url}</a>'
                            )
                            html.append("</li>")
                        html.append("</ul>")
                        html.append("</div>")
            if not has_items:
                html.append(
                    '<div class="token-info">您的个人订阅（收藏、待读、在读、已读）中暂无有声书。</div>'
                )
        else:
            html.append('<div class="token-info">')
            html.append(
                "<strong>📌 个人订阅</strong>：收藏、待读、在读、已读 等个人订阅需要在 &lt;<strong>我的设置</strong>&gt; 中生成 Podcast Token，"
            )
            html.append(
                f"然后使用 <code>{site_url}/podcast/&lt;TOKEN&gt;/</code> 等地址访问。"
            )
            html.append("</div>")

        if CONF.get("SHOW_ALL_IN_PODCAST", False):
            html.append('<div class="section">')
            html.append("<h2>全部有声书</h2>")

            all_url = f"{site_url}/podcast/all"
            if token_to_use:
                all_url += f"?token={token_to_use}"

            html.append(f'<p><a class="feed-url" href="{all_url}">{all_url}</a></p>')
            html.append("</div>")

        if categories:
            html.append('<div class="section"><h2>分类</h2><ul>')
            for cat in sorted(categories.keys()):
                count = len(categories[cat])
                url = f"{site_url}/podcast/category/{urllib.parse.quote(cat)}"
                if token_to_use:
                    url += f"?token={token_to_use}"
                html.append(f'<li><a href="{url}">{cat}</a> ({count}本)</li>')
            html.append("</ul></div>")

        if tags:
            html.append('<div class="section"><h2>标签</h2><ul>')
            for tag in sorted(tags.keys()):
                count = len(tags[tag])
                url = f"{site_url}/podcast/tag/{urllib.parse.quote(tag)}"
                if token_to_use:
                    url += f"?token={token_to_use}"
                html.append(f'<li><a href="{url}">{tag}</a> ({count}本)</li>')
            html.append("</ul></div>")

        if authors:
            html.append('<div class="section"><h2>作者</h2><ul>')
            for author_name in sorted(authors.keys()):
                count = len(authors[author_name])
                url = f"{site_url}/podcast/author/{urllib.parse.quote(author_name)}"
                if token_to_use:
                    url += f"?token={token_to_use}"
                html.append(f'<li><a href="{url}">{author_name}</a> ({count}本)</li>')
            html.append("</ul></div>")

        title = f'{CONF.get("site_title", "Talebook")} Podcast'
        self.render_html_page(title, "\n".join(html), show_back=False)


class PodcastAll(PodcastBaseHandler):
    """Catalog feed of all audiobooks."""

    def get(self):
        self.check_podcast_enabled()
        site_url = self._get_full_site_url()
        provider = _get_provider(self)

        token = None
        if (
            self.current_user
            and hasattr(self.current_user, "podcast_token")
            and self.current_user.podcast_token
        ):
            token = self.current_user.podcast_token

        book_ids = provider.get_all_audiobook_ids()
        entries = provider.get_catalog_entries(book_ids, site_url, token=token)

        title = f"{self._get_site_title()} - 全部有声书"
        self.render_book_list(title, "所有有声书合集", entries)


class PodcastBook(PodcastBaseHandler):
    """Individual audiobook feed — each chapter is an episode."""

    def get(self, book_id):
        self.check_podcast_enabled()
        site_url = self._get_full_site_url()
        provider = _get_provider(self)

        token = None
        if (
            self.current_user
            and hasattr(self.current_user, "podcast_token")
            and self.current_user.podcast_token
        ):
            token = self.current_user.podcast_token

        try:
            book_id = int(book_id)
        except ValueError as exc:
            raise web.HTTPError(400, reason="Invalid book ID") from exc

        book_info = provider.get_book_info(book_id, site_url)
        if not book_info:
            raise web.HTTPError(404, reason="Book not found")

        episodes = provider.get_episodes(book_id, site_url, token=token)
        if not episodes:
            raise web.HTTPError(404, reason="No audio files found for this book")

        feed_xml = build_book_feed(
            book_info, episodes, site_url, site_title=self._get_site_title()
        )
        self.set_rss_headers()
        self.write(feed_xml)


class PodcastCategory(PodcastBaseHandler):
    """Catalog feed for a specific category."""

    def get(self, name):
        self.check_podcast_enabled()
        site_url = self._get_full_site_url()
        provider = _get_provider(self)
        name = urllib.parse.unquote(name)

        token = None
        if (
            self.current_user
            and hasattr(self.current_user, "podcast_token")
            and self.current_user.podcast_token
        ):
            token = self.current_user.podcast_token

        categories = provider.get_categories()
        book_ids = categories.get(name, [])
        if not book_ids:
            raise web.HTTPError(
                404, reason=f"Category '{name}' not found or has no audiobooks"
            )

        entries = provider.get_catalog_entries(book_ids, site_url, token=token)
        title = f"{self._get_site_title()} - 分类：{name}"
        self.render_book_list(title, f"分类「{name}」下的有声书", entries)


class PodcastTag(PodcastBaseHandler):
    """Catalog feed for a specific tag."""

    def get(self, name):
        self.check_podcast_enabled()
        site_url = self._get_full_site_url()
        provider = _get_provider(self)
        name = urllib.parse.unquote(name)

        token = None
        if (
            self.current_user
            and hasattr(self.current_user, "podcast_token")
            and self.current_user.podcast_token
        ):
            token = self.current_user.podcast_token

        tags = provider.get_tags()
        book_ids = tags.get(name, [])
        if not book_ids:
            raise web.HTTPError(
                404, reason=f"Tag '{name}' not found or has no audiobooks"
            )

        entries = provider.get_catalog_entries(book_ids, site_url, token=token)
        title = f"{self._get_site_title()} - 标签：{name}"
        self.render_book_list(title, f"标签「{name}」下的有声书", entries)


class PodcastAuthor(PodcastBaseHandler):
    """Catalog feed for a specific author."""

    def get(self, name):
        self.check_podcast_enabled()
        site_url = self._get_full_site_url()
        provider = _get_provider(self)
        name = urllib.parse.unquote(name)

        token = None
        if (
            self.current_user
            and hasattr(self.current_user, "podcast_token")
            and self.current_user.podcast_token
        ):
            token = self.current_user.podcast_token

        authors = provider.get_authors()
        book_ids = authors.get(name, [])
        if not book_ids:
            raise web.HTTPError(
                404, reason=f"Author '{name}' not found or has no audiobooks"
            )

        entries = provider.get_catalog_entries(book_ids, site_url, token=token)
        title = f"{self._get_site_title()} - 作者：{name}"
        self.render_book_list(title, f"作者「{name}」的有声书", entries)


# ------------------------------------------------------------------
# Token-authenticated handlers for user-specific feeds
# ------------------------------------------------------------------


class PodcastTokenBook(PodcastBaseHandler):
    """Individual audiobook feed with token authentication."""

    def get(self, token, book_id):
        self.check_podcast_enabled()
        user = self._get_user_by_token(token)
        if not user:
            raise web.HTTPError(401, reason="Invalid podcast token")

        site_url = self._get_full_site_url()
        provider = _get_provider(self)

        try:
            book_id = int(book_id)
        except ValueError:
            raise web.HTTPError(400, reason="Invalid book ID")

        book_info = provider.get_book_info(book_id, site_url)
        if not book_info:
            raise web.HTTPError(404, reason="Book not found")

        episodes = provider.get_episodes(book_id, site_url, token=token)
        if not episodes:
            raise web.HTTPError(404, reason="No audio files found for this book")

        feed_xml = build_book_feed(
            book_info, episodes, site_url, site_title=self._get_site_title()
        )
        self.set_rss_headers()
        self.write(feed_xml)


class PodcastTokenIndex(PodcastBaseHandler):
    """User-specific root podcast page displaying 4 categories directly under /podcast/<token>."""

    def get(self, token):
        self.check_podcast_enabled()
        user = self._get_user_by_token(token)
        if not user:
            raise web.HTTPError(401, reason="Invalid podcast token")

        site_url = self._get_full_site_url()
        provider = _get_provider(self)

        html = []
        feed_map = {
            "favorite": ("我的收藏", provider.get_favorites),
            "wants": ("我的待读", provider.get_wants),
            "reading": ("在读", provider.get_reading),
            "read_done": ("已读", provider.get_read_done),
        }

        has_items = False
        for feed_type, (label, getter) in feed_map.items():
            book_ids = getter(user.id)
            if book_ids:
                entries = provider.get_catalog_entries(book_ids, site_url, token=token)
                if entries:
                    has_items = True
                    html.append('<div class="section">')
                    html.append(f"<h2>{label}</h2>")
                    html.append("<ul>")
                    for book in entries:
                        authors_str = ", ".join(book.get("authors", [])) or "未知作者"
                        book_title = book.get("title", "未知书名")
                        feed_url = book.get("feed_url", "")
                        html.append("<li>")
                        html.append(
                            f'<strong>{book_title}</strong> <span class="book-meta">({authors_str})</span>'
                        )
                        html.append(
                            '<div class="book-meta">请复制以下XML订阅地址，并在您的Podcast播放器中添加订阅：</div>'
                        )
                        html.append(
                            f'<a class="feed-url" href="{feed_url}">{feed_url}</a>'
                        )
                        html.append("</li>")
                    html.append("</ul>")
                    html.append("</div>")

        if not has_items:
            html.append("<p>您的个人订阅（收藏、待读、在读、已读）中暂无有声书。</p>")

        html.append('<div class="section">')
        html.append("<h2>全部有声书</h2>")
        all_url = f"{site_url}/podcast/all?token={token}"
        html.append(f'<p><a class="feed-url" href="{all_url}">{all_url}</a></p>')
        html.append("</div>")

        categories = provider.get_categories()
        if categories:
            html.append('<div class="section"><h2>分类</h2><ul>')
            for cat in sorted(categories.keys()):
                count = len(categories[cat])
                url = f"{site_url}/podcast/category/{urllib.parse.quote(cat)}?token={token}"
                html.append(f'<li><a href="{url}">{cat}</a> ({count}本)</li>')
            html.append("</ul></div>")

        tags = provider.get_tags()
        if tags:
            html.append('<div class="section"><h2>标签</h2><ul>')
            for tag in sorted(tags.keys()):
                count = len(tags[tag])
                url = f"{site_url}/podcast/tag/{urllib.parse.quote(tag)}?token={token}"
                html.append(f'<li><a href="{url}">{tag}</a> ({count}本)</li>')
            html.append("</ul></div>")

        authors = provider.get_authors()
        if authors:
            html.append('<div class="section"><h2>作者</h2><ul>')
            for author_name in sorted(authors.keys()):
                count = len(authors[author_name])
                url = f"{site_url}/podcast/author/{urllib.parse.quote(author_name)}?token={token}"
                html.append(f'<li><a href="{url}">{author_name}</a> ({count}本)</li>')
            html.append("</ul></div>")

        title = f"{self._get_site_title()} - {user.name} 的个人订阅"
        self.render_html_page(title, "\n".join(html), show_back=True)


class PodcastAudioFile(PodcastBaseHandler):
    """Token-authenticated audio file serving for podcast players."""

    def get(self, book_id, token, filename):
        self.check_podcast_enabled()
        user = self._get_user_by_token(token)
        if not user:
            raise web.HTTPError(401, reason="Invalid podcast token")

        try:
            book_id = int(book_id)
        except ValueError:
            raise web.HTTPError(400, reason="Invalid book ID")

        # URL decode filename
        filename = urllib.parse.unquote(filename)

        # Security check: no path traversal
        if ".." in filename or "/" in filename:
            raise web.HTTPError(403, reason="Invalid filename")

        audio_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
        file_path = os.path.join(audio_dir, filename)

        if not os.path.exists(file_path):
            raise web.HTTPError(404, reason="Audio file not found")

        # Content-Type
        if filename.endswith(".mp3"):
            self.set_header("Content-Type", "audio/mpeg")
        elif filename.endswith(".wav"):
            self.set_header("Content-Type", "audio/wav")
        elif filename.endswith(".m4a"):
            self.set_header("Content-Type", "audio/mp4")
        elif filename.endswith(".opus"):
            self.set_header("Content-Type", "audio/opus")
        else:
            self.set_header("Content-Type", "audio/mpeg")

        # Support range requests for audio playback
        self.set_header("Accept-Ranges", "bytes")
        file_size = os.path.getsize(file_path)

        range_header = self.request.headers.get("Range")
        if range_header:
            range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if range_match:
                start = int(range_match.group(1))
                end = (
                    int(range_match.group(2)) if range_match.group(2) else file_size - 1
                )

                if start >= file_size:
                    self.set_status(416)
                    return

                self.set_status(206)
                self.set_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.set_header("Content-Length", str(end - start + 1))

                with open(file_path, "rb") as f:
                    f.seek(start)
                    remaining = end - start + 1
                    while remaining > 0:
                        chunk_size = min(8192, remaining)
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        self.write(chunk)
                        remaining -= len(chunk)
                return

        # Normal file transfer
        self.set_header("Content-Length", str(file_size))
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                self.write(chunk)


def routes():
    return [
        # Public feeds (no auth required)
        (r"/podcast/?", PodcastIndex),
        (r"/podcast/all", PodcastAll),
        (r"/podcast/book/([0-9]+)", PodcastBook),
        (r"/podcast/category/(.+)", PodcastCategory),
        (r"/podcast/tag/(.+)", PodcastTag),
        (r"/podcast/author/(.+)", PodcastAuthor),
        # Token-authenticated feeds for user-specific content
        (r"/podcast/([a-zA-Z0-9]+)/book/([0-9]+)", PodcastTokenBook),
        (
            r"/podcast/([a-zA-Z0-9]+)/?",
            PodcastTokenIndex,
        ),
        # Token-authenticated audio file serving
        (r"/podcast/audio/([0-9]+)/([a-zA-Z0-9]+)/(.+)", PodcastAudioFile),
    ]
