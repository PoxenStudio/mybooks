# -*- coding: UTF-8 -*-
"""
WAP Data Provider

Fetches and paginates book data from calibre and SQLite for WAP page rendering.
Designed to be instantiated once per request, wrapping a BaseHandler instance.
"""

import logging

from webserver.base.formatter import cover_stamp
from webserver.models import ReadingState

PAGE_SIZE = 20  # default books per page


class WapDataProvider:
    """
    Provides data for WAP pages by delegating to a BaseHandler's DB connections.
    All public methods return plain Python structures ready for rendering.
    """

    def __init__(self, handler):
        """
        Args:
            handler: A BaseHandler instance with initialised DB connections.
        """
        self.handler = handler

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _format_books(self, books):
        """
        Attach a ``ts`` (Unix timestamp) field to each calibre book dict so
        that renderers can build cover image URLs.
        """
        for book in books:
            book["ts"] = cover_stamp(book)
        return books

    def _search(self, query):
        """
        Execute a calibre full-text search and return a list of book IDs,
        sorted descending (newest first).  Returns empty list on error.
        """
        try:
            ids = list(self.handler.calibre_db_cache.search(query))
        except Exception as exc:
            logging.error("WapDataProvider search failed (query=%r): %s", query, exc)
            return []
        ids.sort(reverse=True)
        return ids

    def _paginate_ids(self, ids, page, page_size):
        """Slice *ids* for the requested page and fetch the books."""
        total = len(ids)
        start = (page - 1) * page_size
        page_ids = ids[start : start + page_size]
        if not page_ids:
            return [], total
        books = self.handler.get_books(ids=page_ids)
        # Restore original ordering (get_books may reorder)
        id_order = {bid: idx for idx, bid in enumerate(page_ids)}
        books.sort(key=lambda b: id_order.get(b["id"], 0))
        return self._format_books(books), total

    # ------------------------------------------------------------------
    # Home / index
    # ------------------------------------------------------------------

    def get_recent_books(self, count=20):
        """Return the most recently added books (up to *count*)."""
        ids = self.handler.books_by_id()[:count]
        books = self.handler.get_books(ids=ids)
        books.sort(key=lambda b: b["id"], reverse=True)
        return self._format_books(books)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_books(self, query, page=1, page_size=PAGE_SIZE):
        """Search using a calibre query string.  Returns ``(books, total)``."""
        ids = self._search(query)
        return self._paginate_ids(ids, page, page_size)

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    def get_categories(self):
        """Return a list of ``{name, count}`` dicts for the custom #category field."""
        from webserver.constants import CALIBRE_COLUMN_CATEGORY

        calibre_db = self.handler.calibre_db
        if CALIBRE_COLUMN_CATEGORY not in calibre_db.field_metadata:
            return []

        meta = calibre_db.field_metadata[CALIBRE_COLUMN_CATEGORY]
        table = f"custom_column_{meta['colnum']}"
        link_table = f"books_{table}_link"
        sql = (
            f"SELECT t.value, count(l.book) as cnt "
            f"FROM {table} t JOIN {link_table} l ON t.id = l.value "
            f"GROUP BY t.id ORDER BY cnt DESC"
        )
        try:
            with self.handler.db_lock:
                rows = self.handler.calibre_db_cache.backend.conn.get(sql)
            return [{"name": row[0], "count": row[1]} for row in rows]
        except Exception as exc:
            logging.error("WapDataProvider.get_categories failed: %s", exc)
            return []

    def get_books_by_category(self, category, page=1, page_size=PAGE_SIZE):
        """Return ``(books, total)`` for all books in *category*."""
        query = f'#category:="{category}"'
        return self.search_books(query, page, page_size)

    # ------------------------------------------------------------------
    # Languages
    # ------------------------------------------------------------------

    def get_languages(self):
        """
        Return a list of ``{name, code, count}`` dicts (name is display name).
        """
        from webserver.handlers.meta import LanguageNameUtil

        items = self.handler.get_category_with_count("language")
        result = []
        for item in items:
            code = item.get("name") or ""
            display = LanguageNameUtil.get_language_name(code)
            result.append({"name": display, "code": code, "count": item["count"]})
        result.sort(key=lambda x: x["count"], reverse=True)
        return result

    def get_books_by_language(self, lang_display_name, page=1, page_size=PAGE_SIZE):
        """
        Return ``(books, total)`` for all books in the given language.
        *lang_display_name* may be either a display name or a language code.
        """
        from webserver.handlers.meta import LanguageNameUtil

        code = LanguageNameUtil.get_language_code(lang_display_name)
        query = f'languages:="{code}"'
        return self.search_books(query, page, page_size)

    # ------------------------------------------------------------------
    # Authors
    # ------------------------------------------------------------------

    def get_authors(self, limit=100):
        """Return the top *limit* authors by book count as ``{name, count}`` dicts."""
        items = self.handler.get_category_with_count("author")
        items.sort(key=lambda x: x["count"], reverse=True)
        return [{"name": i["name"], "count": i["count"]} for i in items[:limit]]

    def get_books_by_author(self, author, page=1, page_size=PAGE_SIZE):
        """Return ``(books, total)`` for all books by *author*."""
        query = f'authors:="{author}"'
        return self.search_books(query, page, page_size)

    # ------------------------------------------------------------------
    # User-specific book lists (require authenticated user)
    # ------------------------------------------------------------------

    def get_reading_books(self, user_id, page=1, page_size=PAGE_SIZE):
        """Return ``(books, total)`` for the user's currently-reading list."""
        states = (
            self.handler.sqlite_session.query(ReadingState)
            .filter(
                ReadingState.reader_id == user_id,
                ReadingState.read_state == 1,
            )
            .order_by(ReadingState.read_date.desc())
            .all()
        )
        return self._books_from_reading_states(states, page, page_size)

    def get_favorite_books(self, user_id, page=1, page_size=PAGE_SIZE):
        """Return ``(books, total)`` for the user's favourite books."""
        states = (
            self.handler.sqlite_session.query(ReadingState)
            .filter(
                ReadingState.reader_id == user_id,
                ReadingState.favorite == 1,
            )
            .order_by(ReadingState.favorite_date.desc())
            .all()
        )
        return self._books_from_reading_states(states, page, page_size)

    def get_wants_books(self, user_id, page=1, page_size=PAGE_SIZE):
        """Return ``(books, total)`` for the user's want-to-read list."""
        states = (
            self.handler.sqlite_session.query(ReadingState)
            .filter(
                ReadingState.reader_id == user_id,
                ReadingState.wants == 1,
            )
            .order_by(ReadingState.wants_date.desc())
            .all()
        )
        return self._books_from_reading_states(states, page, page_size)

    def _books_from_reading_states(self, states, page, page_size):
        """
        Given an ordered list of ReadingState rows, return the paginated
        ``(books, total)`` preserving the state-list ordering.
        """
        total = len(states)
        start = (page - 1) * page_size
        page_states = states[start : start + page_size]
        book_ids = [s.book_id for s in page_states]
        if not book_ids:
            return [], total

        books_map = {b["id"]: b for b in self.handler.get_books(ids=book_ids)}
        ordered = [books_map[bid] for bid in book_ids if bid in books_map]
        return self._format_books(ordered), total
