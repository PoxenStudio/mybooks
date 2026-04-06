# -*- coding: UTF-8 -*-
"""
Podcast Data Provider

Aggregates audiobook data from the calibre cache and SQLAlchemy models,
mirroring the categorization logic in dav_provider.py but filtered
to only include books that have audio files.
"""

import logging
import os
import time
from urllib.parse import quote

from webserver import loader
from webserver import constants

CONF = loader.get_settings()
AUDIO_OUTPUT_FOLDER = CONF.get("audio_output_folder", "/data/books/audios/")

_aggregate_cache = {
    "timestamp": 0,
    "categories": {},
    "tags": {},
    "authors": {},
}


class PodcastProvider:
    """
    Data provider for podcast feeds. Fetches audiobook metadata and
    audio file information, filtered by various aggregation criteria.
    """

    def __init__(self, cache, get_session_func):
        """
        Args:
            cache: Calibre library cache (new_api)
            get_session_func: callable that returns a SQLAlchemy session
        """
        self.cache = cache
        self.get_session_func = get_session_func

    # ------------------------------------------------------------------
    # Audio book ID helpers
    # ------------------------------------------------------------------

    def _get_audio_book_ids(self):
        """Get the set of book IDs that have audio files."""
        from webserver.handlers.audio import AudioBooksCache

        return AudioBooksCache.get_audio_book_ids_set()

    def _filter_audio_ids(self, book_ids):
        """Filter a list of book_ids to only those that have audio."""
        audio_ids = self._get_audio_book_ids()
        return [bid for bid in book_ids if bid in audio_ids]

    # ------------------------------------------------------------------
    # Book metadata
    # ------------------------------------------------------------------

    def get_book_info(self, book_id, site_url):
        """
        Get enriched metadata for a single book.

        Returns:
            dict with: id, title, authors, description, cover_url, pub_date, language
            or None if book not found
        """
        try:
            mi = self.cache.get_metadata(
                book_id, get_cover=False, get_user_categories=False
            )
            if not mi or mi.is_null("title"):
                return None

            # Description from calibre comments
            description = ""
            try:
                comments = mi.comments
                if comments:
                    # Strip HTML tags for plain text description
                    import re

                    description = re.sub(r"<[^>]+>", "", comments).strip()
            except Exception:
                pass

            # Publication date
            pub_date = None
            try:
                if mi.pubdate and str(mi.pubdate.year) != "101":
                    pub_date = mi.pubdate
            except Exception:
                pass

            # Language
            language = "zh-cn"
            try:
                langs = mi.languages
                if langs:
                    language = langs[0].lower().replace("_", "-")
            except Exception:
                pass

            return {
                "id": book_id,
                "title": mi.title or "Unknown",
                "authors": list(mi.authors) if mi.authors else [],
                "description": description,
                "cover_url": f"{site_url}/get/cover/{book_id}.jpg",
                "pub_date": pub_date,
                "language": language,
            }
        except Exception as e:
            logging.error(f"Error getting book info for {book_id}: {e}")
            return None

    # ------------------------------------------------------------------
    # Audio episodes
    # ------------------------------------------------------------------

    def get_episodes(self, book_id, site_url, token=None):
        """
        Get list of audio episodes (chapters) for a book.

        Args:
            book_id: calibre book ID
            site_url: base URL for building audio file URLs
            token: optional podcast token for building authenticated URLs

        Returns:
            list of dicts with: title, url, size, duration, index
        """
        audio_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
        if not os.path.exists(audio_dir):
            return []

        def _get_sort_key(filename):
            import re

            m = re.match(r"^(\d+)", filename)
            return int(m.group(1)) if m else 999999

        audio_files = sorted(
            [
                f
                for f in os.listdir(audio_dir)
                if f.endswith((".mp3", ".wav", ".m4a", ".opus"))
                and os.path.getsize(os.path.join(audio_dir, f)) > 1024
            ],
            key=_get_sort_key,
        )

        if not audio_files:
            return []

        episodes = []
        for i, filename in enumerate(audio_files):
            file_path = os.path.join(audio_dir, filename)
            file_size = os.path.getsize(file_path)

            # Get title from filename (remove extension and numeric prefix)
            title = os.path.splitext(filename)[0]
            # Files are typically named like "0001_Chapter_Title.mp3"
            parts = title.split("_", 1)
            if len(parts) > 1 and parts[0].isdigit():
                title = parts[1]
            title = title.replace("_", " ")

            # Try to get metadata and duration using mutagen
            duration = 0
            author = None
            try:
                from mutagen.mp3 import MP3

                audio = MP3(file_path)
                duration = int(audio.info.length)

                if audio.tags:
                    if "TIT2" in audio.tags and audio.tags["TIT2"].text:
                        title_tag = audio.tags["TIT2"].text[0]
                        if title_tag:
                            title = str(title_tag)
                    if "TPE1" in audio.tags and audio.tags["TPE1"].text:
                        author_tag = audio.tags["TPE1"].text[0]
                        if author_tag:
                            author = str(author_tag)
            except Exception as e:
                logging.warning(
                    f"Failed to read audio metadata for {file_path} via mutagen: {e}"
                )
                # Estimate duration: ~128kbps average for MP3
                duration = int(file_size / (128 * 1024 / 8))

            # Build audio URL - with or without token
            encoded_filename = quote(filename)
            if token:
                audio_url = (
                    f"{site_url}/podcast/audio/{book_id}/{token}/{encoded_filename}"
                )
            else:
                audio_url = f"{site_url}/api/audio/{book_id}/{encoded_filename}"

            episodes.append(
                {
                    "title": title,
                    "author": author,
                    "url": audio_url,
                    "size": file_size,
                    "duration": duration,
                    "index": i,
                }
            )

        return episodes

    # ------------------------------------------------------------------
    # Catalog book entries (for aggregation feeds)
    # ------------------------------------------------------------------

    def _build_catalog_entry(self, book_id, site_url, token=None):
        """Build a catalog entry dict for a single book."""
        book_info = self.get_book_info(book_id, site_url)
        if not book_info:
            return None

        episodes = self.get_episodes(book_id, site_url, token=token)
        first_ep_url = episodes[0]["url"] if episodes else ""
        first_ep_size = episodes[0]["size"] if episodes else 0

        # Build feed URL for this book
        if token:
            feed_url = f"{site_url}/podcast/{token}/book/{book_id}"
        else:
            feed_url = f"{site_url}/podcast/book/{book_id}"

        return {
            "id": book_id,
            "title": book_info["title"],
            "authors": book_info["authors"],
            "description": book_info["description"],
            "cover_url": book_info["cover_url"],
            "first_episode_url": first_ep_url,
            "first_episode_size": first_ep_size,
            "pub_date": book_info["pub_date"],
            "feed_url": feed_url,
        }

    def get_catalog_entries(self, book_ids, site_url, token=None):
        """Build catalog entries for a list of book IDs."""
        entries = []
        for bid in book_ids:
            entry = self._build_catalog_entry(bid, site_url, token=token)
            if entry:
                entries.append(entry)
        return entries

    def _refresh_aggregations(self):
        """Update aggregation cache if older than 3 minutes."""
        now = time.time()
        if (
            now - _aggregate_cache["timestamp"] < 180
            and _aggregate_cache["timestamp"] > 0
        ):
            return

        categories = {}
        tags = {}
        authors = {}

        audio_ids = self._get_audio_book_ids()
        if not audio_ids:
            return

        for book_id in audio_ids:
            try:
                mi = self.cache.get_metadata(
                    book_id, get_cover=False, get_user_categories=False
                )
                if not mi:
                    continue

                # Category caching
                cat_val = mi.get("#category")
                cat_list = []
                if isinstance(cat_val, (list, tuple)):
                    cat_list = [str(c) for c in cat_val]
                elif cat_val:
                    cat_list = [str(cat_val)]
                for c in cat_list:
                    categories.setdefault(c, []).append(book_id)

                # Tags caching
                if mi.tags:
                    for t in mi.tags:
                        if not t or len(t) < 2:
                            continue
                        tags.setdefault(t, []).append(book_id)

                # Authors caching
                if mi.authors:
                    for a in mi.authors:
                        authors.setdefault(a, []).append(book_id)
            except Exception as e:
                logging.error(f"Error fetching metadata for audiobook {book_id}: {e}")

        _aggregate_cache["categories"] = categories
        _aggregate_cache["tags"] = tags
        _aggregate_cache["authors"] = authors
        _aggregate_cache["timestamp"] = now

    def get_categories(self, user=None):
        """
        Get categories that contain audiobooks.

        Returns:
            dict of {category_name: [book_ids]}
        """
        self._refresh_aggregations()

        categories = _aggregate_cache["categories"]
        if CONF.get(constants.ALLOW_READ_RANGE_SETTING, False):
            if not user:
                return []
            read_limit = getattr(user, "read_limit", 0) or 0
            if read_limit > 0:
                limit_categories = set(filter(None, (user.limit_categories or "").split(",")))
                if read_limit == 1:
                    # books = [b for b in books if self.is_book_in_reading_range(b, user)]
                    categories = [category for category in categories if category in limit_categories]
                else:
                    categories = [category for category in categories if category not in limit_categories]
        return categories

    def get_tags(self, user=None):
        """
        Get tags that contain audiobooks.

        Returns:
            dict of {tag_name: [book_ids]}
        """
        self._refresh_aggregations()
        tags = _aggregate_cache["tags"]
        if CONF.get(constants.ALLOW_READ_RANGE_SETTING, False):
            if not user:
                return []
            read_limit = getattr(user, "read_limit", 0) or 0
            if read_limit > 0:
                limit_tags = set(filter(None, (user.limit_tags or "").split(",")))
                if read_limit == 1:
                    tags = [tag for tag in tags if tag in limit_tags]
                else:
                    tags = [tag for tag in tags if tag not in limit_tags]
        return tags

    def get_authors(self):
        """
        Get authors that have audiobooks.

        Returns:
            dict of {author_name: [book_ids]}
        """
        self._refresh_aggregations()
        return _aggregate_cache["authors"]

    # ------------------------------------------------------------------
    # Aggregation: user reading states
    # ------------------------------------------------------------------

    def _get_reading_state_books(self, user_id, filter_func):
        """Get audiobook IDs matching a reading state filter for a user."""
        if not user_id or not self.get_session_func:
            return []
        try:
            from webserver.models import ReadingState

            session = self.get_session_func()
            states = (
                session.query(ReadingState)
                .filter(ReadingState.reader_id == user_id)
                .all()
            )
            book_ids = [s.book_id for s in states if filter_func(s)]
            return self._filter_audio_ids(book_ids)
        except Exception as e:
            logging.error(f"Error getting reading state books: {e}")
            return []

    def get_favorites(self, user_id):
        """Get favorite audiobooks for a user."""
        return self._get_reading_state_books(user_id, lambda s: s.favorite == 1)

    def get_wants(self, user_id):
        """Get to-read audiobooks for a user."""
        return self._get_reading_state_books(user_id, lambda s: s.wants == 1)

    def get_reading(self, user_id):
        """Get currently reading audiobooks for a user."""
        return self._get_reading_state_books(user_id, lambda s: s.read_state == 1)

    def get_read_done(self, user_id):
        """Get finished audiobooks for a user."""
        return self._get_reading_state_books(user_id, lambda s: s.read_state == 2)

    def get_all_audiobook_ids(self):
        """Get all book IDs that have audio files."""
        return list(self._get_audio_book_ids())
