#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mybooks_api.py — MyBooks REST API Client

Usage:
    python3 mybooks_api.py <tool-name> '<json-args>'

Environment Variables:
    MYBOOKS_HOST       Server URL with port (e.g., http://192.168.1.2:8082)
    MYBOOKS_USER       Login username
    MYBOOKS_PASSWORD   Login password
    MYBOOKS_SSL_VERIFY Set to "false" to skip SSL certificate verification (self-signed certs)

Authentication:
    Automatically signs in via /api/user/sign_in before each tool invocation.
    Session cookies (user_id, lt) are maintained throughout the script lifecycle.
    If err=user.need_login is received, the script re-authenticates once and retries.

TTS API Prefix:
    /api/toolbox/mimo_tts/
"""

import json
import math
import os
import re
import sys
import time
import base64
import ipaddress
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
import urllib3
from typing import Any, Dict, List, Tuple

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# book345 (无名图书) 客户端：同目录模块，仅用标准库、不涉及任何凭据。
# 直接以脚本运行时 sys.path[0] 已是本目录，作为模块导入时补一次。
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import wuming_client  # noqa: E402


# ============================================================================
# Constants
# ============================================================================

REQUIRED_ENV_VARS = ["MYBOOKS_HOST", "MYBOOKS_USER", "MYBOOKS_PASSWORD"]

API_TTS_PREFIX = "/api/toolbox/mimo_tts"

# Built-in toolbox tool epub_fixer: /repair starts a background task, /progress reports it
API_EPUB_FIXER_PREFIX = "/api/toolbox/epub_fixer"

# book_upload only reads files with these extensions (blocks sending arbitrary
# local files such as ~/.ssh/id_rsa or .env to the server)
EBOOK_UPLOAD_EXTS = {"epub", "mobi", "azw", "azw3", "pdf", "txt", "lrf", "rtf", "djvu", "docx"}

# Douban is applied by re-fetching from the plugin by provider_value; every other source
# is applied from the metadata payload, so book_refer_apply requires it there
DOUBAN_PROVIDER_KEY = "douban"

# The server-side refer search waits up to REFER_SEARCH_TIMEOUT (default 60s) and then
# answers with the cached candidates, so the client must not cut the connection earlier
REFER_TIMEOUT = 90

ERROR_MESSAGES = {
    "env_missing": {
        "status": "error",
        "message": "MYBOOKS_HOST is not set. Please configure MYBOOKS_HOST (e.g. http://192.168.31.102:8082), MYBOOKS_USER and MYBOOKS_PASSWORD."
    },
    "auth_missing": {
        "status": "error",
        "message": "MYBOOKS_USER or MYBOOKS_PASSWORD is not set. Authentication is required."
    }
}


def validate_host(host: str) -> str:
    """
    Validate MYBOOKS_HOST before any credential is sent to it.

    - Must be an http(s) URL with a hostname and no embedded userinfo.
    - Plain http is only accepted for loopback / private-LAN / *.local hosts
      (the typical self-hosted setup); anything else must use https, unless
      MYBOOKS_ALLOW_INSECURE_HTTP=true is set explicitly.

    Returns the normalized base URL, or exits with an error.
    """
    parsed = urllib.parse.urlparse(host.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        print(json.dumps({"status": "error", "message": "MYBOOKS_HOST must be like http(s)://host[:port] without embedded credentials."}), file=sys.stderr)
        sys.exit(1)

    if parsed.scheme == "http" and os.environ.get("MYBOOKS_ALLOW_INSECURE_HTTP", "false").lower() not in ("true", "1", "yes"):
        name = parsed.hostname
        try:
            ip = ipaddress.ip_address(name)
            local = ip.is_loopback or ip.is_private or ip.is_link_local
        except ValueError:
            local = name == "localhost" or name.endswith(".local")
        if not local:
            print(json.dumps({"status": "error", "message": "Refusing to send credentials over plain http to a non-local host. Use https, or set MYBOOKS_ALLOW_INSECURE_HTTP=true to override."}), file=sys.stderr)
            sys.exit(1)

    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


def parse_bool(value, default: bool = False) -> bool:
    """
    Coerce a tool argument to a real boolean.

    JSON callers pass booleans, but CLI/agent callers often pass the strings
    "true"/"false". Treating any non-empty string as truthy would turn
    force=false into a destructive overwrite, so the usual spellings are honored.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


# ============================================================================
# Credential-free helpers: external metadata source + shared batch utilities
# ============================================================================

# Fields accepted by batch_edit and apply-plan writes (mirrors edit_book)
EDITABLE_FIELDS = (
    "title", "authors", "tags", "publisher", "isbn", "series", "series_index",
    "rating", "languages", "translators", "pubdate", "category", "comments",
    "book_count", "book_type",
)

# Whole-library audit rules: key is the stable rule name used by the tools
RESEARCH_RULES = {
    "isbn": "missing ISBN",
    "publisher": "missing publisher or placeholder (Unknown / -)",
    "publisher_year": "publisher contains a year (should be a bare publisher name)",
    "pubdate": "missing publication date or placeholder 0101-01-01",
    "category": "missing category",
    "tags": "no tags",
    "authors": "no author, or one author element still holds separators",
    "comments": "missing description",
}

_SEP = set(",，、/;；|")
_YEAR_RE = re.compile(r"(19|20)\d{2}")
_PLACEHOLDER_DATE = "0101-01-01"
_CONF_ORDER = {"high": 3, "medium": 2, "low": 1, "none": 0}

# The list endpoints (/api/search, /api/admin/book/list) return a slimmer book
# object than /api/book/{id}: `comments` is always empty there even when the book
# has one. Treat these fields as "unknown" in a snapshot and hydrate them from the
# detail endpoint before judging or writing, otherwise every book looks like it is
# missing a description and a fill would happily overwrite existing text.
LIST_OMITTED_FIELDS = ("comments",)


def _tool_wuming_search(args: Dict[str, Any]) -> Dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"status": "error", "message": "query is required"}
    return wuming_client.search_books(query, int(args.get("count", 10)))


def _tool_wuming_toplist(args: Dict[str, Any]) -> Dict[str, Any]:
    return wuming_client.get_toplist(str(args.get("type") or "top"), int(args.get("count", 10)))


def _tool_wuming_recent_hot(args: Dict[str, Any]) -> Dict[str, Any]:
    tag = str(args.get("tag") or "").strip() or None
    return wuming_client.get_recent_hot(tag, int(args.get("count", 10)))


def _tool_wuming_detail(args: Dict[str, Any]) -> Dict[str, Any]:
    isbn = str(args.get("isbn") or "").strip()
    if not isbn:
        return {"status": "error", "message": "isbn is required"}
    return wuming_client.get_book_detail(isbn)


def _tool_wuming_guide(args: Dict[str, Any]) -> Dict[str, Any]:
    isbn = str(args.get("isbn") or "").strip()
    if not isbn:
        return {"status": "error", "message": "isbn is required"}
    return wuming_client.get_book_guide(isbn)


def _tool_wuming_tags(args: Dict[str, Any]) -> Dict[str, Any]:
    return wuming_client.list_book_tags()


# Tools that talk to book345.com only: they must work without MYBOOKS_* env vars,
# which is the whole point of shipping them next to a self-hosted library client
AUTH_FREE_TOOLS = {
    "wuming_search": _tool_wuming_search,
    "wuming_toplist": _tool_wuming_toplist,
    "wuming_recent_hot": _tool_wuming_recent_hot,
    "wuming_detail": _tool_wuming_detail,
    "wuming_guide": _tool_wuming_guide,
    "wuming_tags": _tool_wuming_tags,
}


def _same_val(a: Any, b: Any) -> bool:
    """Compare metadata values: lists element-wise, scalars as stripped strings."""
    if isinstance(a, list) or isinstance(b, list):
        return [str(x) for x in (a or [])] == [str(x) for x in (b or [])]
    return ("" if a is None else str(a)).strip() == ("" if b is None else str(b)).strip()


def _rule_hit(book: Dict[str, Any], rule: str) -> bool:
    """Return True when the book violates the given audit rule."""
    if rule == "isbn":
        return not (book.get("isbn") or "").strip()
    if rule == "publisher":
        value = (book.get("publisher") or "").strip()
        return not value or value.lower() in ("unknown", "-", "none", "null")
    if rule == "publisher_year":
        return bool(_YEAR_RE.search(book.get("publisher") or ""))
    if rule == "pubdate":
        return str(book.get("pubdate") or "").strip() in ("", _PLACEHOLDER_DATE, "None", "null")
    if rule == "category":
        return not (book.get("category") or "").strip()
    if rule == "tags":
        return not (book.get("tags") or [])
    if rule == "authors":
        authors = book.get("authors") or []
        return (not authors) or any(_SEP & set(str(a)) for a in authors)
    if rule == "comments":
        return not (book.get("comments") or "").strip()
    return False


def _build_todo(books: list, rules: list) -> list:
    """Build the research todo list from a library snapshot."""
    todo = []
    for book in books:
        need = [rule for rule in rules if _rule_hit(book, rule)]
        if not need:
            continue
        todo.append({
            "id": book.get("id"),
            "title": book.get("title"),
            "category": book.get("category"),
            "need": need,
            "current": {k: book.get(k) for k in
                        ("isbn", "publisher", "pubdate", "category", "tags", "authors")},
        })
    return todo


def _shard_ids(ids: list, count: int) -> list:
    """Split ids into count contiguous shards: complete, non-overlapping, ordered."""
    ids = list(ids)
    if not ids or count < 1:
        return []
    count = min(int(count), len(ids))
    size, extra = divmod(len(ids), count)
    out, pos = [], 0
    for i in range(count):
        take = size + (1 if i < extra else 0)
        out.append(ids[pos:pos + take])
        pos += take
    return [shard for shard in out if shard]


def _field_needs_fill(book: Dict[str, Any], field: str) -> bool:
    """True when the field is empty or dirty (the default 'only fill gaps' policy)."""
    if field in ("publisher", "pubdate", "comments", "isbn"):
        return _rule_hit(book, field) or (field == "publisher" and _rule_hit(book, "publisher_year"))
    value = book.get(field)
    return value in (None, "", []) or (isinstance(value, str) and not value.strip())


def _research_one(book: Dict[str, Any], fields: list, allow_title_isbn: bool) -> Dict[str, Any]:
    """Look one book up on book345: by ISBN when present, otherwise by title.

    Title matches only produce candidates; they are applied only when exactly one
    exact-title match exists AND allow_title_isbn is set. Nothing is written here.
    """
    title = book.get("title") or ""
    out: Dict[str, Any] = {
        "book_id": book.get("id"), "title": title, "proposed": {},
        "confidence": "none", "source": None, "note": None, "candidates": [],
    }
    isbn = (book.get("isbn") or "").strip()
    if isbn:
        detail = wuming_client.get_book_detail(isbn)
        if isinstance(detail, dict) and detail.get("title"):
            proposed = {}
            if "publisher" in fields and detail.get("publisher"):
                proposed["publisher"] = str(detail["publisher"]).strip()
            if "pubdate" in fields and detail.get("pubDate"):
                proposed["pubdate"] = str(detail["pubDate"]).strip()
            if "comments" in fields and detail.get("summary"):
                proposed["comments"] = str(detail["summary"]).strip()
            if "isbn" in fields:
                proposed["isbn"] = isbn
            out.update(proposed=proposed, confidence="high", source=f"book345 detail/{isbn}")
            if not proposed:
                out["note"] = "source has none of the requested fields"
        else:
            out["note"] = f"book345 has no record for ISBN {isbn}"
        return out

    result = wuming_client.search_books(title, 5)
    candidates = (result.get("books") if isinstance(result, dict) else None) or []
    out["candidates"] = [{
        "isbn": c.get("isbn"), "title": c.get("title"),
        "author": c.get("author"), "publisher": c.get("publisher"),
    } for c in candidates[:5]]

    normalized = re.sub(r"\s+", "", title)
    exact = [c for c in candidates
             if re.sub(r"\s+", "", str(c.get("title") or "")) == normalized]
    if len(exact) == 1 and allow_title_isbn:
        candidate = exact[0]
        proposed = {}
        if "isbn" in fields and candidate.get("isbn"):
            proposed["isbn"] = str(candidate["isbn"]).strip()
        if "publisher" in fields and candidate.get("publisher"):
            proposed["publisher"] = str(candidate["publisher"]).strip()
        out.update(proposed=proposed, confidence="medium",
                   source="book345 search (exact title)")
        if not proposed:
            out["note"] = "exact title match but the source lacks the requested fields"
    elif len(exact) > 1:
        out["confidence"] = "low"
        out["note"] = f"{len(exact)} versions share this exact title; pick one manually"
    else:
        out["note"] = "no exact title match; needs manual research"
    return out

# ============================================================================
# MyBooksAPI Class
# ============================================================================


class MyBooksAPI:
    """Main API client for MyBooks REST API."""

    def __init__(self, host: str, username: str, password: str):
        """
        Initialize MyBooks API client.

        Args:
            host: Server URL with port (e.g., http://127.0.0.1:8082)
            username: Login username
            password: Login password
        """
        self.host = validate_host(host)
        self.username = username
        self.password = password
        self.session_cookies = {}

        # Try importing requests
        try:
            import requests
            self.requests = requests
            self.verify_ssl = os.environ.get("MYBOOKS_SSL_VERIFY", "true").lower() in ("true", "1", "yes")
        except ImportError:
            self._print_error("Python 'requests' library is required. Install with: pip3 install requests")
            sys.exit(1)

    def _print_error(self, message: str) -> None:
        """Print error to stderr."""
        print(json.dumps({"status": "error", "message": message}), file=sys.stderr)

    def sign_in(self) -> None:
        """Authenticate with the server and store session cookies."""
        url = f"{self.host}/api/user/sign_in"
        # Form-encoded (not JSON) as required by the server; requests url-encodes the values
        data = {"username": self.username, "password": self.password}

        try:
            resp = self.requests.post(
                url,
                data=data,
                timeout=30,
                verify=self.verify_ssl,
                allow_redirects=False  # never forward credentials to a redirect target
            )
            resp.raise_for_status()
            result = resp.json()

            if result.get("err") != "ok":
                self._print_error(f"Login failed: {json.dumps(result)}")
                sys.exit(1)

            # Store cookies for subsequent requests
            self.session_cookies.update(resp.cookies.get_dict())

        except Exception as e:
            self._print_error(f"Login failed: {str(e)}")
            sys.exit(1)

    def _call_api(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """
        Internal method to call API endpoints.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (e.g., /api/user/info)
            **kwargs: Additional arguments for requests (data, json, files, etc.)

        Returns:
            Parsed JSON response
        """
        url = f"{self.host}{path}"
        kwargs.setdefault('cookies', self.session_cookies)
        kwargs.setdefault('timeout', 30)
        kwargs.setdefault('verify', self.verify_ssl)

        try:
            resp = self.requests.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _call_with_auto_relogin(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """
        Call API and automatically re-authenticate if session expired.

        Args:
            method: HTTP method
            path: API path
            **kwargs: Additional arguments for requests

        Returns:
            Parsed JSON response
        """
        result = self._call_api(method, path, **kwargs)

        if result.get("err") == "user.need_login":
            self.sign_in()
            result = self._call_api(method, path, **kwargs)

        return result

    # ========================================================================
    # Tool Methods
    # ========================================================================

    def get_user_info(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get current user info and system statistics."""
        return self._call_with_auto_relogin("GET", "/api/user/info")

    def library_stats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get library statistics: total, ebook, physical book counts."""
        return self._call_with_auto_relogin("GET", "/api/library/stats")

    def reading_stats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get current user's reading statistics."""
        return self._call_with_auto_relogin("GET", "/api/reading/stats")

    def search_books(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search books by keyword, by field conditions (combined with AND), or
        by a raw Calibre search expression.

        Args:
            name (str, optional): Keyword (title/author/comments), a bare ISBN,
                or a Calibre expression such as 'title:=三体' or
                'authors:余华 AND rating:>=4'
            title (str, optional): Exact book title
            author (str, optional): Author (contains match)
            isbn (str, optional): ISBN-10/13, dashes allowed
            publisher (str, optional): Publisher (contains match)
            series (str, optional): Series (contains match)
            tag (str, optional): Tag (contains match)
            exact (bool, optional): Use exact match for author/publisher/series/tag
            order (str, optional): Sort field, e.g. 'pubdate'
            num (int, optional): Results per page (default: 20)
            page (int, optional): Page number (default: 1)
        """
        num = args.get("num", 20)
        page = args.get("page", 1)
        params: Dict[str, Any] = {"num": num, "start": (page - 1) * num}
        for key in ("name", "title", "author", "isbn", "publisher", "series", "tag", "order"):
            value = str(args.get(key) or "").strip()
            if value:
                params[key] = value
        if args.get("exact"):
            params["exact"] = 1
        if len(params) == 2:
            return {"err": "params.invalid", "msg": "At least one of name/title/author/isbn/publisher/series/tag is required"}

        return self._call_with_auto_relogin(
            "GET",
            "/api/search?" + urllib.parse.urlencode(params)
        )

    def search_by_category(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search books by category.

        Args:
            category (str, required): Category name
            num (int, optional): Results per page (default: 20)
            page (int, optional): Page number (default: 1)
        """
        category = args.get("category", "")
        num = args.get("num", 20)
        page = args.get("page", 1)
        start = (page - 1) * num

        query = urllib.parse.quote(f'#category:="{category}"')
        return self._call_with_auto_relogin(
            "GET",
            f"/api/search?name={query}&num={num}&start={start}"
        )

    def get_book(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get detailed book information.

        Args:
            book_id (int, required): Book ID
        """
        book_id = args.get("book_id")
        if not book_id:
            return {"status": "error", "message": "book_id is required"}

        return self._call_with_auto_relogin("GET", f"/api/book/{book_id}")

    def edit_book(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Edit book metadata.

        Args:
            book_id (int, required): Book ID
            title (str, optional): Book title
            authors (array/string, optional): Author list
            tags (array/string, optional): Tag list
            publisher (str, optional): Publisher
            isbn (str, optional): ISBN
            series (str, optional): Series name
            rating (number, optional): Rating (0-10)
            languages (array, optional): Language codes
            pubdate (str, optional): Publication date
            comments (str, optional): Book description
            category (str, optional): Custom category
            book_count (int, optional): Physical book count
            book_type (int, optional): 0=ebook, 1=physical
        """
        book_id = args.get("book_id")
        if not book_id:
            return {"status": "error", "message": "book_id is required"}

        body = {k: v for k, v in args.items() if k != "book_id"}
        return self._call_with_auto_relogin(
            "POST",
            f"/api/book/{book_id}/edit",
            json=body
        )

    def push_notes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Import third-party annotations (e.g. WeChat Reading highlights/thoughts)
        into a book's reading records via server-side full-text CFI resolution.

        Args:
            book_id (int, required): MyBooks book ID (must have an EPUB format)
            anchors (array, required): each item:
                id (str, required): stable id from the source system (e.g. WeChat
                    Reading bookmarkId/reviewId) — used to build an idempotent
                    record id, safe to call repeatedly with the same anchors.
                text (str, optional): the highlighted/quoted original text to
                    search for. Omit for a chapter-/book-level note with no
                    precise anchor (falls back to a chapter-start bookmark).
                chapterHint (str, optional): source chapter title, used to help
                    locate a chapter-start position when `text` is omitted.
                note (str, optional): the user's own thought/comment text.
                color (str, optional): highlight color, default "yellow".
                style (str, optional): "highlight"/"underline"/"squiggly", default "highlight".
                createdAt (int, optional): ms epoch timestamp from the source system.
                source (str, optional): provenance tag, default "wxread".
            on_ambiguous (str, optional): "error" (default) or "first_match" —
                behavior when the anchor text matches more than once in the book.
            dry_run (bool, optional): default true. true = only resolve and return
                a report, write nothing; false = also write the resolved notes.
                ALWAYS call with dry_run=true first, show the caller the report
                (how many resolved/ambiguous/no_match), and only call again with
                dry_run=false after explicit confirmation — never write blind.
            force (bool, optional): default false. Re-syncing is automatically
                deduplicated server-side — an anchor whose `text`/`chapterHint`
                haven't changed since a previous import reuses its stored `cfi`
                instead of being re-searched (results[].reused: true marks this).
                Only set force=true if you actually need everything re-resolved
                from scratch (e.g. the book's EPUB file itself was replaced) —
                do not set it on routine re-syncs, the dedup already handles those.
        """
        book_id = args.get("book_id")
        anchors = args.get("anchors")
        if not book_id:
            return {"status": "error", "message": "book_id is required"}
        if not anchors:
            return {"status": "error", "message": "anchors is required and must be non-empty"}

        body = {
            "book_id": book_id,
            "anchors": anchors,
            "on_ambiguous": args.get("on_ambiguous", "error"),
            "dry_run": args.get("dry_run", True),
            "force": args.get("force", False),
        }
        return self._call_with_auto_relogin("POST", "/api/sync/import", json=body)

    def get_notes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Query a book's reading annotations (bookmarks/highlights/notes) via
        GET /api/sync.

        Args:
            book_id (int, optional): MyBooks book ID. Provide this OR `title`.
            title (str, optional): Book title; if `book_id` is omitted, this
                is resolved via search_books. Must match exactly one book —
                if the search returns more than one hit, the response comes
                back as an error with a `candidates` list instead of guessing.
            own (int, optional): 1 (default) = only the current user's own
                notes; 0 = also include other users' shared notes on this
                book (subject to the server's ENABLE_SHARED_NOTES setting).
        """
        book_id = args.get("book_id")
        title = args.get("title")
        own = args.get("own", 1)
        if own not in (0, 1):
            return {"status": "error", "message": "own must be 0 or 1"}

        if not book_id:
            if not title:
                return {"status": "error", "message": "book_id or title is required"}
            found = self.search_books({"name": title, "num": 5, "page": 1})
            if found.get("err") != "ok":
                return found
            books = found.get("books") or []
            if not books:
                return {"status": "error", "message": f"No book found matching title: {title}"}
            if len(books) > 1:
                candidates = [{"id": b.get("id"), "title": b.get("title"), "authors": b.get("authors")} for b in books]
                return {
                    "status": "error",
                    "message": "Multiple books matched this title; specify book_id",
                    "candidates": candidates,
                }
            book_id = books[0].get("id")
            if not book_id:
                return {"status": "error", "message": "Search result missing book id"}

        # cloud 书籍的 book_hash 固定为 "cloud-<book_id>-epub"，与 push_notes/
        # sync_import_service.book_hash_for() 保持一致
        book_hash = f"cloud-{book_id}-epub"
        query = urllib.parse.urlencode({"since": 0, "type": "notes", "book": book_hash, "own": own})
        result = self._call_with_auto_relogin("GET", f"/api/sync?{query}")
        if isinstance(result, dict):
            result["book_id"] = book_id
            result["book_hash"] = book_hash
        return result

    def clear_imported_notes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove all annotations `push_notes` previously imported for one book
        (current user only) — a "start over" escape hatch, NOT the normal way
        to handle a re-sync (push_notes already dedups automatically; see its
        docstring). Only use this if the user explicitly asks to undo/reset an
        import, e.g. because it was run with wrong data or bad on_ambiguous
        matches.

        Args:
            book_id (int, required): MyBooks book ID
        """
        book_id = args.get("book_id")
        if not book_id:
            return {"status": "error", "message": "book_id is required"}

        return self._call_with_auto_relogin("POST", "/api/sync/import/clear", json={"book_id": book_id})

    def book_fill(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Auto-fill book info from online sources (admin only).

        Args:
            idlist (array or "all", required): Book ID array or "all"
        """
        idlist = args.get("idlist")
        if not idlist:
            return {
                "status": "error",
                "message": 'idlist is required: an array of book IDs or "all"'
            }

        return self._call_with_auto_relogin(
            "POST",
            "/api/admin/book/fill",
            json={"idlist": idlist}
        )

    def book_refer_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search online sources for metadata candidates of one book (the search step
        of the web UI's "联网更新信息"). Read-only; pass a candidate's provider_key /
        provider_value to book_refer_apply.

        Args:
            book_id (int, required): Book ID
            title (str, optional): Search with this title instead of the book's own
            isbn (str, optional): Search with this ISBN
            publisher (str, optional): Narrow the search by publisher
        """
        book_id = args.get("book_id")
        if not book_id:
            return {"status": "error", "message": "book_id is required"}

        params = {k: args[k] for k in ("title", "isbn", "publisher") if args.get(k)}
        # 服务端最慢要等 REFER_SEARCH_TIMEOUT（默认 60s）才回退给缓存候选，别用默认的 30s 先掐断
        return self._call_with_auto_relogin("GET", f"/api/book/{book_id}/refer", params=params, timeout=REFER_TIMEOUT)

    def book_refer_apply(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply one online metadata candidate to a book (the apply step of the web UI's
        "联网更新信息"), optionally limited to a subset of fields.

        Args:
            book_id (int, required): Book ID
            provider_key (str, required): Source key from book_refer_search (e.g. douban)
            provider_value (str, required): Source-side ID from book_refer_search
            mode (str, optional): full (default: info + cover) / only_meta (info without
                cover) / only_cover / only_author_comments — one at most
            metadata (object, optional): A candidate object from book_refer_search;
                required unless provider_key is douban, which re-fetches from the plugin
        """
        book_id = args.get("book_id")
        if not book_id:
            return {"status": "error", "message": "book_id is required"}

        provider_key = args.get("provider_key")
        if not provider_key:
            return {"status": "error", "message": "provider_key is required"}
        provider_value = args.get("provider_value")
        if not provider_value:
            return {"status": "error", "message": "provider_value is required"}

        metadata = args.get("metadata")
        # 非豆瓣源是"用这份候选去写库"：不带 metadata 时服务端会退回用书自身元数据并返回 ok，
        # 调用方会以为更新成功了，所以这里直接拦下
        if not metadata and provider_key != DOUBAN_PROVIDER_KEY:
            return {
                "status": "error",
                "message": f"metadata (a candidate from book_refer_search) is required for provider '{provider_key}'",
            }

        flags = {
            "full": {},
            "only_meta": {"only_meta": "yes"},
            "only_cover": {"only_cover": "yes"},
            "only_author_comments": {"only_author_comments": "yes"},
        }
        mode = args.get("mode") or "full"
        if mode not in flags:
            return {"status": "error", "message": f"mode must be one of: {', '.join(flags)}"}

        data = {"provider_key": provider_key, "provider_value": provider_value}
        if metadata:
            data["metadata"] = metadata if isinstance(metadata, str) else json.dumps(metadata, ensure_ascii=False)
        data.update(flags[mode])

        return self._call_with_auto_relogin("POST", f"/api/book/{book_id}/refer", data=data, timeout=REFER_TIMEOUT)

    def save_meta_to_file(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Save book metadata into the ebook file itself (epub/azw3/pdf only).

        Args:
            book_id (int, required): Book ID
            fmt (str, optional): Limit to one format (epub/azw3/pdf); if omitted, all supported formats are updated
        """
        book_id = args.get("book_id")
        if not book_id:
            return {"status": "error", "message": "book_id is required"}

        fmt = args.get("fmt")
        path = f"/api/book/{book_id}/savemeta"
        if fmt:
            path += f"?fmt={urllib.parse.quote(str(fmt))}"

        return self._call_with_auto_relogin("POST", path)

    def mailto(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send book to email as attachment.

        Args:
            book_id (int, required): Book ID
            email (str, required): Target email address
        """
        book_id = args.get("book_id")
        email = args.get("email", "")

        if not book_id:
            return {"status": "error", "message": "book_id is required"}
        if not email:
            return {"status": "error", "message": "email is required"}

        return self._call_with_auto_relogin(
            "POST",
            f"/api/book/{book_id}/mailto",
            json={"email": email}
        )

    def send_to_device(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send book to reading device via WiFi.

        Args:
            book_id (int, required): Book ID
            device_type (str, required): Device type (kindle/duokan/ireader/etc.)
            device_url (str, required for non-kindle): Device WiFi address
            mailbox (str, required for kindle): Kindle email address
        """
        book_id = args.get("book_id")
        if not book_id:
            return {"status": "error", "message": "book_id is required"}

        body = {k: v for k, v in args.items() if k != "book_id"}
        return self._call_with_auto_relogin(
            "POST",
            f"/api/book/{book_id}/send_to_device",
            json=body
        )

    def categories(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get all custom categories and book counts."""
        return self._call_with_auto_relogin("GET", "/api/categories")

    def list_folders(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get the folder tree (at most two levels) with book counts."""
        return self._call_with_auto_relogin("GET", "/api/folders")

    def search_by_folder(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        List books directly inside a folder.

        Args:
            path (str, optional): Folder path such as "文学" or "文学.小说"; empty means root
            num (int, optional): Results per page (default: 20)
            page (int, optional): Page number (default: 1)
        """
        path = urllib.parse.quote(args.get("path", ""))
        num = args.get("num", 20)
        start = (args.get("page", 1) - 1) * num
        return self._call_with_auto_relogin(
            "GET",
            f"/api/folder/books?path={path}&size={num}&start={start}"
        )

    def set_folder(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Set the folder of one book, or of many books (admin only).

        Args:
            book_id (int, optional): Book ID for a single book
            book_ids (array, optional): Book IDs for a batch
            folder (str, required): Folder path such as "文学.小说"; "" or "清除" moves out of any folder
        """
        if "folder" not in args:
            return {"status": "error", "message": "folder is required"}
        if args.get("book_ids"):
            return self._call_with_auto_relogin(
                "POST", "/api/book/folder",
                json={"ids": args["book_ids"], "folder": args["folder"]}
            )
        book_id = args.get("book_id")
        if not book_id:
            return {"status": "error", "message": "book_id or book_ids is required"}
        return self._call_with_auto_relogin(
            "POST", f"/api/book/{book_id}/folder", json={"folder": args["folder"]}
        )

    def rename_folder(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Rename the last segment of a folder (admin only). If the target already
        exists the server answers folder.exists without changing anything; merging
        is irreversible and only happens when merge is true.

        Args:
            path (str, required): Existing folder path
            name (str, required): New name of the last segment
            merge (bool, optional): Confirm merging into an existing folder (default: false)
        """
        if not args.get("path") or not args.get("name"):
            return {"status": "error", "message": "path and name are required"}
        return self._call_with_auto_relogin(
            "POST", "/api/folder/rename",
            json={"path": args["path"], "name": args["name"], "merge": bool(args.get("merge", False))}
        )

    def list_authors(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get all authors and book counts.

        Args:
            show (str, optional): Pass "all" to show all authors
        """
        show = args.get("show", "")
        path = "/api/author?show=all" if show == "all" else "/api/author"
        return self._call_with_auto_relogin("GET", path)

    def get_author_books(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get books by specific author (paginated).

        Args:
            author_name (str, required): Author name
            num (int, optional): Results per page (default: 20)
            page (int, optional): Page number (default: 1)
        """
        author = args.get("author_name", "")
        num = args.get("num", 20)
        page = args.get("page", 1)
        start = (page - 1) * num

        author_enc = urllib.parse.quote(author)
        return self._call_with_auto_relogin(
            "GET",
            f"/api/author/{author_enc}?num={num}&start={start}"
        )

    def book_upload(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Upload an ebook file: import it as a new book, or — when book_id is given —
        add one format to that existing book, optionally replacing the file of a
        format that already exists (the web UI's "上传新格式文件").

        Args:
            file_path (str, required): Absolute path to local file
            book_id (int, optional): Target this existing book instead of importing a new one
            force (bool, optional): With book_id, replace the format file if the format
                already exists; without it the server replies format.already_exists
        """
        file_path = args.get("file_path", "")
        if not file_path:
            return {"status": "error", "message": "file_path is required"}

        if not os.path.isfile(file_path):
            return {"status": "error", "message": f"File not found: {file_path}"}

        ext = os.path.splitext(file_path)[1].lower().lstrip('.')
        if ext not in EBOOK_UPLOAD_EXTS:
            return {"status": "error", "message": f"Unsupported file type '.{ext}'. Allowed: {', '.join(sorted(EBOOK_UPLOAD_EXTS))}"}

        path = "/api/book/upload"
        book_id = args.get("book_id")
        if book_id:
            query = {"bid": book_id}
            if parse_bool(args.get("force")):
                query["force"] = 1
            path += "?" + urllib.parse.urlencode(query)

        try:
            with open(file_path, 'rb') as f:
                files = {'ebook': f}
                return self._call_with_auto_relogin(
                    "POST",
                    path,
                    files=files
                )
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def book_add_by_isbn(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add physical book by ISBN.

        Args:
            isbn (str, required): ISBN number
        """
        isbn = args.get("isbn", "")
        if not isbn:
            return {"status": "error", "message": "isbn is required"}

        return self._call_with_auto_relogin(
            "POST",
            "/api/book/add",
            json={"isbn": isbn}
        )

    def wants(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mark/unmark book as "want to read".

        Args:
            book_id (int, required): Book ID
            wants (bool, optional): true=mark, false=unmark (default: true)
        """
        book_id = args.get("book_id")
        if not book_id:
            return {"status": "error", "message": "book_id is required"}

        wants_val = args.get("wants", True)
        return self._call_with_auto_relogin(
            "POST",
            f"/api/book/{book_id}/wants",
            json={"wants": wants_val}
        )

    def list_wants(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get current user's want-to-read book list."""
        return self._call_with_auto_relogin("GET", "/api/wants")

    def favorite(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mark/unmark book as favorite.

        Args:
            book_id (int, required): Book ID
            favorite (bool, optional): true=favorite, false=unfavorite (default: true)
        """
        book_id = args.get("book_id")
        if not book_id:
            return {"status": "error", "message": "book_id is required"}

        fav_val = args.get("favorite", True)
        return self._call_with_auto_relogin(
            "POST",
            f"/api/book/{book_id}/favorite",
            json={"favorite": fav_val}
        )

    def list_favorites(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get current user's favorite book list."""
        return self._call_with_auto_relogin("GET", "/api/favorites")

    def reading(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Set book reading state.

        Args:
            book_id (int, required): Book ID
            read_state (int, required): 0=unread, 1=reading, 2=finished
        """
        book_id = args.get("book_id")
        if not book_id:
            return {"status": "error", "message": "book_id is required"}

        read_state = args.get("read_state", 1)
        return self._call_with_auto_relogin(
            "POST",
            f"/api/book/{book_id}/readstate",
            json={"read_state": read_state}
        )

    def list_reading(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get current user's reading book list."""
        return self._call_with_auto_relogin("GET", "/api/reading")

    def read_done(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mark book as finished reading.

        Args:
            book_id (int, required): Book ID
        """
        book_id = args.get("book_id")
        if not book_id:
            return {"status": "error", "message": "book_id is required"}

        return self._call_with_auto_relogin(
            "POST",
            f"/api/book/{book_id}/readstate",
            json={"read_state": 2}
        )

    def list_read_done(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get current user's finished book list."""
        return self._call_with_auto_relogin("GET", "/api/read-done")

    def get_book_reading_stats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get the current user's reading duration/progress statistics for a
        book, broken down by ebook format (epub/pdf/mobi/etc).

        Args:
            book_id (int, required): Book ID
        """
        book_id = args.get("book_id")
        if not book_id:
            return {"status": "error", "message": "book_id is required"}

        return self._call_with_auto_relogin("GET", f"/api/book/{book_id}/reading_stats")

    def update_book_reading_stats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Manually update/correct the current user's reading duration or
        progress for one ebook format of a book. Useful for backfilling
        historical reading records, or marking a format as started/finished
        when there is no automatic heartbeat (e.g. reading outside MyReader).

        Args:
            book_id (int, required): Book ID
            format (str, required): Ebook format, e.g. epub/pdf/mobi/azw3/txt
            duration_seconds (int, optional): Seconds to ADD to the cumulative
                reading duration (not an absolute value)
            progress (array, optional): [current, total], e.g. [120, 488];
                reaching ~100% auto-marks the format as finished
            start_time (str, optional): ISO8601 string or epoch timestamp;
                explicitly starts a new reading round
            finish_time (str, optional): ISO8601 string or epoch timestamp;
                explicitly marks the current round finished
            state (int, optional): 0=reading, 1=finished (alternative to finish_time)
        """
        book_id = args.get("book_id")
        fmt = args.get("format")
        if not book_id or not fmt:
            return {"status": "error", "message": "book_id and format are required"}

        body = {k: v for k, v in args.items() if k not in ("book_id",)}
        return self._call_with_auto_relogin(
            "POST",
            f"/api/book/{book_id}/reading_stats",
            json=body
        )

    # ========================================================================
    # Manual reading time (v4.3.0+)
    # ========================================================================

    def get_reading_time(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get the manual reading-time entry (and reference totals) of a book on a date.

        Args:
            book_id (int, required): Book ID
            date (str, required): YYYY-MM-DD
        """
        book_id = args.get("book_id")
        date = args.get("date")
        if not book_id or not date:
            return {"status": "error", "message": "book_id and date are required"}
        return self._call_with_auto_relogin("GET", f"/api/book/{book_id}/reading_time", params={"date": date})

    def set_reading_time(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add or overwrite the manual reading-time entry of a book on a date.

        Args:
            book_id (int, required): Book ID
            date (str, required): YYYY-MM-DD, must not be in the future
            duration_seconds (int, required): 0~64800 (18h); overwrites that day's manual entry
            start_time (str, optional): free-form start time text
            end_time (str, optional): free-form end time text
        """
        book_id = args.get("book_id")
        if not book_id or not args.get("date") or args.get("duration_seconds") is None:
            return {"status": "error", "message": "book_id, date and duration_seconds are required"}
        body = {k: v for k, v in args.items() if k != "book_id"}
        return self._call_with_auto_relogin("POST", f"/api/book/{book_id}/reading_time", json=body)

    def delete_reading_time(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Delete the manual reading-time entry of a book on a date.

        Args:
            book_id (int, required): Book ID
            date (str, required): YYYY-MM-DD
            confirm (bool, optional): must be true to actually delete; otherwise
                the current entry is returned as a preview and nothing is deleted
        """
        book_id = args.get("book_id")
        date = args.get("date")
        if not book_id or not date:
            return {"status": "error", "message": "book_id and date are required"}
        if args.get("confirm") is not True:
            preview = self._call_with_auto_relogin("GET", f"/api/book/{book_id}/reading_time", params={"date": date})
            return {
                "err": "confirm.required",
                "msg": "Nothing deleted. Show this entry to the user and, only after they explicitly agree, call again with \"confirm\": true.",
                "entry": preview.get("entry"),
                "preview_err": preview.get("err"),
            }
        return self._call_with_auto_relogin("DELETE", f"/api/book/{book_id}/reading_time", params={"date": date})

    # ========================================================================
    # Booklist Tool Methods (v4.3.0+)
    # ========================================================================

    def list_my_booklists(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List the current user's own booklists."""
        return self._call_with_auto_relogin("GET", "/api/booklists/mine")

    def list_public_booklists(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        List public booklists.

        Args:
            page (int, optional): default 1
            page_size (int, optional): default 20, max 50
        """
        params = {k: args[k] for k in ("page", "page_size") if k in args}
        return self._call_with_auto_relogin("GET", "/api/booklists/public", params=params)

    def list_liked_booklists(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List booklists liked by the current user."""
        return self._call_with_auto_relogin("GET", "/api/booklists/liked")

    def get_booklist(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get a booklist with its books.

        Args:
            booklist_id (int, required): Booklist ID
            order (str, optional): desc (default) / asc, by time added
            page (int, optional): default 1
            page_size (int, optional): default 24, max 60
        """
        booklist_id = args.get("booklist_id")
        if not booklist_id:
            return {"status": "error", "message": "booklist_id is required"}
        params = {k: args[k] for k in ("order", "page", "page_size") if k in args}
        return self._call_with_auto_relogin("GET", f"/api/booklist/{booklist_id}", params=params)

    def create_booklist(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a booklist.

        Args:
            name (str, required): Booklist name
            description (str, optional): up to 500 chars
            color (str, optional): Booklist color
            is_public (bool, optional): default false
        """
        if not args.get("name"):
            return {"status": "error", "message": "name is required"}
        return self._call_with_auto_relogin("POST", "/api/booklist/create", json=args)

    def update_booklist(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update a booklist (owner or admin). Only the fields passed are changed.

        Args:
            booklist_id (int, required): Booklist ID
            name / description / color / is_public (optional)
        """
        booklist_id = args.get("booklist_id")
        if not booklist_id:
            return {"status": "error", "message": "booklist_id is required"}
        body = {k: v for k, v in args.items() if k != "booklist_id"}
        return self._call_with_auto_relogin("POST", f"/api/booklist/{booklist_id}/update", json=body)

    def delete_booklist(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Delete a booklist (owner or admin). The books themselves are not deleted.

        Two-step, enforced in code: without confirm=true nothing is deleted and a
        preview of the target is returned instead.

        Args:
            booklist_id (int, required): Booklist ID
            confirm (bool, optional): must be true to actually delete
        """
        booklist_id = args.get("booklist_id")
        if not booklist_id:
            return {"status": "error", "message": "booklist_id is required"}
        if args.get("confirm") is not True:
            preview = self._call_with_auto_relogin("GET", f"/api/booklist/{booklist_id}", params={"page_size": 1})
            info = preview.get("booklist") or {}
            return {
                "err": "confirm.required",
                "msg": "Nothing deleted. Show this booklist to the user and, only after they explicitly agree, call again with \"confirm\": true.",
                "booklist": {k: info.get(k) for k in ("id", "name", "book_count", "is_public", "like_count", "is_owner")},
                "preview_err": preview.get("err"),
            }
        return self._call_with_auto_relogin("POST", f"/api/booklist/{booklist_id}/delete", json={})

    def booklist_add_books(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add books to a booklist (owner or admin).

        Args:
            booklist_id (int, required): Booklist ID
            book_ids (array, required): Book IDs (a single book_id is also accepted)
        """
        booklist_id = args.get("booklist_id")
        if not booklist_id:
            return {"status": "error", "message": "booklist_id is required"}
        body = {k: v for k, v in args.items() if k in ("book_ids", "book_id")}
        return self._call_with_auto_relogin("POST", f"/api/booklist/{booklist_id}/books/add", json=body)

    def booklist_remove_book(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove one book from a booklist (owner or admin).

        Args:
            booklist_id (int, required): Booklist ID
            book_id (int, required): Book ID
        """
        booklist_id = args.get("booklist_id")
        book_id = args.get("book_id")
        if not booklist_id or not book_id:
            return {"status": "error", "message": "booklist_id and book_id are required"}
        return self._call_with_auto_relogin("POST", f"/api/booklist/{booklist_id}/books/remove", json={"book_id": book_id})

    def like_booklist(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Toggle like on a booklist.

        Args:
            booklist_id (int, required): Booklist ID
        """
        booklist_id = args.get("booklist_id")
        if not booklist_id:
            return {"status": "error", "message": "booklist_id is required"}
        return self._call_with_auto_relogin("POST", f"/api/booklist/{booklist_id}/like", json={})

    def get_book_booklists(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        List the current user's booklists, marking which already contain the book.

        Args:
            book_id (int, required): Book ID
        """
        book_id = args.get("book_id")
        if not book_id:
            return {"status": "error", "message": "book_id is required"}
        return self._call_with_auto_relogin("GET", f"/api/book/{book_id}/booklists")

    # ========================================================================
    # EPUB fix Tool Methods (built-in toolbox tool epub_fixer, admin only)
    # ========================================================================

    def epub_fix(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Start the EPUB structure repair task for one or more books (admin only,
        async — poll with epub_fix_progress).

        Args:
            book_ids (int or array, required): One book ID or a list of IDs (up to 100)
            write_mode (str, optional): overwrite (default: replaces the book's EPUB) or
                new_book (keeps the original, imports the repaired copy as a new book)
            backup (bool, optional): Keep a copy of the pre-repair EPUB in the tool work dir
            reconvert (bool, optional): Also re-convert epub->epub after the structural pass
            suffix (str, optional): Title suffix used by new_book mode (default: （精修）)
        """
        book_ids = args.get("book_ids")
        if not book_ids:
            return {"status": "error", "message": "book_ids is required: one book ID or an array of IDs"}
        if not isinstance(book_ids, list):
            book_ids = [book_ids]

        body = {"book_ids": book_ids}
        for key in ("write_mode", "suffix"):
            if args.get(key) is not None:
                body[key] = args[key]
        # 服务端对 backup 只做 bool(...)（字符串 "false" 会变成 True），对 reconvert 才认字符串，
        # 这里统一归一成真布尔再发
        for key in ("backup", "reconvert"):
            if args.get(key) is not None:
                body[key] = parse_bool(args[key])

        return self._call_with_auto_relogin("POST", f"{API_EPUB_FIXER_PREFIX}/repair", json=body)

    def epub_fix_progress(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Query the EPUB repair task progress and per-book results.

        Args: none
        """
        return self._call_with_auto_relogin("GET", f"{API_EPUB_FIXER_PREFIX}/progress")

    # ========================================================================
    # TTS Tool Methods (MiMo TTS audiobook, admin only)
    # ========================================================================

    def tts_save_config(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Save TTS API configuration (encrypted server-side).

        Args:
            api_url (str, required): API endpoint URL
            model_name (str, required): Model ID (e.g., mimo-v2.5-tts)
            api_type (str, required): chat_completions / audio_speech / custom
            api_key (str, required): API key
            auth_type (str, optional): bearer / basic / custom (default: bearer)
            voice_name (str, optional): Preset voice ID or audio_speech voice
            voice_desc (str, optional): Custom voice description
            clone_voice (str, optional): Clone voice name
        """
        required = ["api_url", "model_name", "api_type", "api_key"]
        for field in required:
            if not args.get(field):
                return {"status": "error", "message": f"{field} is required"}

        body = {k: v for k, v in args.items() if v is not None}
        return self._call_with_auto_relogin(
            "POST",
            f"{API_TTS_PREFIX}/config",
            json=body,
        )

    def tts_test_connection(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Test API connection using saved configuration.

        Args: none
        """
        return self._call_with_auto_relogin("POST", f"{API_TTS_PREFIX}/test")

    def tts_convert(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Start EPUB-to-audiobook conversion (async background task).

        Args:
            book_id (int, required): Book ID
            api_url (str, required): API endpoint URL
            model_name (str, required): Model ID
            api_type (str, required): chat_completions / audio_speech / custom
            api_key (str, required): API key
            auth_type (str, optional): bearer / basic / custom
            voice_name (str, optional): Preset voice ID or audio_speech voice
            voice_desc (str, optional): Custom voice description
            clone_voice (str, optional): Clone voice name
        """
        required = ["book_id", "api_url", "model_name", "api_type", "api_key"]
        for field in required:
            if not args.get(field):
                return {"status": "error", "message": f"{field} is required"}

        body = {k: v for k, v in args.items() if v is not None}
        return self._call_with_auto_relogin(
            "POST",
            f"{API_TTS_PREFIX}/convert",
            json=body,
        )

    def tts_progress(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Query current TTS conversion progress.

        Args: none
        """
        return self._call_with_auto_relogin("GET", f"{API_TTS_PREFIX}/progress")

    def tts_clone_upload(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Upload a clone voice sample (MP3/WAV, <=7MB).

        Args:
            voice_name (str, required): Clone voice name
            file_path (str, required): Absolute path to local audio file
        """
        voice_name = args.get("voice_name", "")
        file_path = args.get("file_path", "")

        if not voice_name:
            return {"status": "error", "message": "voice_name is required"}
        if not file_path:
            return {"status": "error", "message": "file_path is required"}

        if not os.path.isfile(file_path):
            return {"status": "error", "message": f"File not found: {file_path}"}

        # Validate format
        ext = os.path.splitext(file_path)[1].lower().lstrip('.')
        if ext not in ('mp3', 'wav'):
            return {"status": "error", "message": "Only MP3 and WAV formats are supported"}

        # Validate size (7MB limit)
        file_size = os.path.getsize(file_path)
        if file_size > 7 * 1024 * 1024:
            return {"status": "error", "message": f"File too large: {file_size} bytes (max 7MB)"}

        try:
            with open(file_path, 'rb') as f:
                files = {'file': f}
                data = {'voice_name': voice_name}
                return self._call_with_auto_relogin(
                    "POST",
                    f"{API_TTS_PREFIX}/clone/upload",
                    data=data,
                    files=files,
                )
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def tts_clone_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        List all uploaded clone voices.

        Args: none
        """
        return self._call_with_auto_relogin("GET", f"{API_TTS_PREFIX}/clone/list")

    def tts_clone_delete(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Delete a clone voice by name.

        Args:
            voice_name (str, required): Clone voice name to delete
        """
        voice_name = args.get("voice_name", "")
        if not voice_name:
            return {"status": "error", "message": "voice_name is required"}

        return self._call_with_auto_relogin(
            "POST",
            f"{API_TTS_PREFIX}/clone/delete",
            json={"voice_name": voice_name},
        )

    def tts_clone_audio(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Download/preview a clone voice audio file (binary WAV).

        Args:
            voice_name (str, required): Clone voice name
            save_to (str, optional): Local path to save the audio;
                                     if omitted, returns base64-encoded audio
        """
        voice_name = args.get("voice_name", "")
        if not voice_name:
            return {"status": "error", "message": "voice_name is required"}

        save_to = args.get("save_to", "")
        query = urllib.parse.urlencode({"voice_name": voice_name})

        url = f"{self.host}{API_TTS_PREFIX}/clone/audio?{query}"
        kwargs = {
            'cookies': self.session_cookies,
            'timeout': 60,
            'verify': self.verify_ssl,
        }

        try:
            resp = self.requests.get(url, **kwargs)

            # Check for auth redirect
            try:
                ct = resp.headers.get('Content-Type', '')
                if 'json' in ct:
                    result = resp.json()
                    if result.get("err") == "user.need_login":
                        self.sign_in()
                        kwargs['cookies'] = self.session_cookies
                        resp = self.requests.get(url, **kwargs)
                        ct = resp.headers.get('Content-Type', '')
                        if 'json' in ct:
                            return resp.json()
            except Exception:
                pass

            content = resp.content

            if save_to:
                if not save_to.lower().endswith(".wav"):
                    return {"status": "error", "message": "save_to must end with .wav"}
                if os.path.exists(save_to):
                    return {"status": "error", "message": f"Refusing to overwrite existing file: {save_to}"}
                with open(save_to, 'wb') as f:
                    f.write(content)
                return {
                    "err": "ok",
                    "msg": "Audio saved",
                    "path": save_to,
                    "size": len(content),
                }
            else:
                # Return base64 for small files
                b64 = base64.b64encode(content).decode('ascii')
                return {
                    "err": "ok",
                    "msg": "Audio retrieved",
                    "voice_name": voice_name,
                    "size": len(content),
                    "base64": b64,
                }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def tts_prompt_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        List all saved voice prompt descriptions.

        Args: none
        """
        return self._call_with_auto_relogin("GET", f"{API_TTS_PREFIX}/prompt/list")

    def tts_prompt_save(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Save a voice prompt description (same name overwrites).

        Args:
            name (str, required): Prompt name
            desc (str, required): Voice description text
        """
        name = args.get("name", "")
        desc = args.get("desc", "")

        if not name:
            return {"status": "error", "message": "name is required"}
        if not desc:
            return {"status": "error", "message": "desc is required"}

        return self._call_with_auto_relogin(
            "POST",
            f"{API_TTS_PREFIX}/prompt/save",
            json={"name": name, "desc": desc},
        )

    def tts_prompt_delete(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Delete a voice prompt by name.

        Args:
            name (str, required): Prompt name to delete
        """
        name = args.get("name", "")
        if not name:
            return {"status": "error", "message": "name is required"}

        return self._call_with_auto_relogin(
            "POST",
            f"{API_TTS_PREFIX}/prompt/delete",
            json={"name": name},
        )

    # ========================================================================
    # Whole-library tools: batch edit / audit / research / enrich
    # ========================================================================

    def _fetch_library(self, page_size: int = 100, workers: int = 3) -> Tuple[List[Dict[str, Any]], int]:
        """Return ``(books, total)`` for the whole library.

        The primary path is the regular-user search endpoint driven by Calibre's
        ``all:true`` expression, so a non-admin account can use it. The server may
        cap a page below the requested ``num`` (lite performance mode returns 60),
        so pagination advances by the number of books actually returned instead of
        the requested page size -- otherwise pages are skipped and the snapshot is
        silently short. If the search path yields nothing, fall back to the admin
        list endpoint, which does require an admin account.
        """

        def search_page(start_at: int) -> Dict[str, Any]:
            params = urllib.parse.urlencode({"name": "all:true", "num": page_size, "start": start_at})
            return self._call_with_auto_relogin("GET", "/api/search?" + params)

        first = search_page(0)
        if not isinstance(first, dict) or first.get("err") not in (None, "ok"):
            first = {}
        total = int(first.get("total") or 0)
        books: List[Dict[str, Any]] = list(first.get("books") or [])

        if books:
            seen = {b.get("id") for b in books}
            while len(books) < total:
                page = search_page(len(books))
                chunk = (page.get("books") or []) if isinstance(page, dict) else []
                fresh = [b for b in chunk if b.get("id") not in seen]
                if not fresh:  # no progress: stop instead of looping forever
                    break
                seen.update(b.get("id") for b in fresh)
                books += fresh
        else:
            first = self._call_with_auto_relogin("GET", f"/api/admin/book/list?page=1&num={page_size}")
            if not isinstance(first, dict):
                first = {}
            total = int(first.get("total") or 0)
            books = list(first.get("items") or [])
            if not books:
                reason = str(first.get("msg") or first.get("message") or first.get("err") or "")
                if first.get("err") == "permission.not_admin":
                    reason = ("this tool reads the whole library, which requires an admin "
                              "account on servers that do not support the all:true search")
                raise RuntimeError(f"cannot read the library ({reason or 'empty response'})")
            page_no = 2
            while len(books) < total:
                page = self._call_with_auto_relogin(
                    "GET", f"/api/admin/book/list?page={page_no}&num={page_size}")
                chunk = (page.get("items") or []) if isinstance(page, dict) else []
                if not chunk:
                    break
                books += chunk
                page_no += 1

        return books, max(total, len(books))

    def _hydrate(self, books: List[Dict[str, Any]], fields: List[str],
                 workers: int = 6) -> List[Dict[str, Any]]:
        """Fill in fields the list endpoint does not return (LIST_OMITTED_FIELDS).

        Only books whose snapshot lacks a requested field are re-read from
        /api/book/{id}, so work on publisher/pubdate costs no extra requests.
        """
        needed = [f for f in fields if f in LIST_OMITTED_FIELDS]
        if not needed:
            return books

        def one(book: Dict[str, Any]) -> Dict[str, Any]:
            if all(book.get(f) for f in needed):
                return book
            detail = self._read_book(book.get("id"))
            if not isinstance(detail, dict):
                return book
            merged = dict(book)
            for field in needed:
                if field in detail:
                    merged[field] = detail[field]
            return merged

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            return list(pool.map(one, books))

    def _read_book(self, book_id: Any) -> Dict[str, Any]:
        resp = self._call_with_auto_relogin("GET", f"/api/book/{book_id}")
        if not isinstance(resp, dict):
            return {}
        book = resp.get("book")
        return book if isinstance(book, dict) else resp

    def _write_book(self, book_id: Any, fields: Dict[str, Any]) -> Dict[str, Any]:
        return self._call_with_auto_relogin("POST", f"/api/book/{book_id}/edit", json=fields)

    def batch_edit(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update metadata for many books at once: per-book diff, optional skip of
        no-op writes, optional read-back verification.

        Args:
            items (array, optional): [{"book_id": 1, "category": "小说"}, ...]
            ids (array, optional): Book IDs that all receive the same fields
            set (object, optional): Fields applied to every id in ``ids``
            workers (int, optional): Concurrency (default 4, max 8)
            dry_run (bool, optional): Default true - preview only; pass false to write
            verify (bool, optional): Default true - read back each written book
            skip_unchanged (bool, optional): Default true - skip books already matching

        Returns a per-book ``diff`` plus ok/failed/skipped/changed counters.
        """
        items = list(args.get("items") or [])
        ids = list(args.get("ids") or [])
        uniform = dict(args.get("set") or {})
        if ids and uniform:
            items += [{"book_id": book_id, **uniform} for book_id in ids]
        if not items:
            return {"status": "error", "message": "provide items, or ids together with set"}

        workers = max(1, min(int(args.get("workers", 4)), 8))
        dry_run = parse_bool(args.get("dry_run"), True)
        verify = parse_bool(args.get("verify"), True)
        skip_unchanged = parse_bool(args.get("skip_unchanged"), True)

        allowed = set(EDITABLE_FIELDS)
        tasks = []
        for item in items:
            if not isinstance(item, dict) or not item.get("book_id"):
                return {"status": "error", "message": f"invalid item (book_id required): {item}"}
            fields = {k: v for k, v in item.items() if k != "book_id"}
            unknown = sorted(set(fields) - allowed)
            if unknown:
                return {"status": "error",
                        "message": f"book_id={item['book_id']} has non-editable fields {unknown}; "
                                   f"editable: {sorted(allowed)}"}
            tasks.append({"book_id": item["book_id"], "fields": fields})

        def work(task: Dict[str, Any]) -> Dict[str, Any]:
            book_id = task["book_id"]
            fields = task["fields"]
            try:
                book = self._read_book(book_id)
                if not book or book.get("err"):
                    return {"book_id": book_id, "ok": False, "error": f"read failed: {str(book)[:150]}"}
                diff = {k: {"before": book.get(k), "after": v}
                        for k, v in fields.items() if not _same_val(book.get(k), v)}
                if not diff and skip_unchanged:
                    return {"book_id": book_id, "ok": True, "title": book.get("title"),
                            "skipped": True, "reason": "fields already match"}
                if dry_run:
                    return {"book_id": book_id, "ok": True, "title": book.get("title"),
                            "dry_run": True, "diff": diff}
                self._write_book(book_id, fields)
                if not verify:
                    return {"book_id": book_id, "ok": True, "title": book.get("title"), "diff": diff}
                after = self._read_book(book_id)
                mismatch = {k: {"expect": v, "actual": after.get(k)}
                            for k, v in fields.items() if not _same_val(after.get(k), v)}
                return {"book_id": book_id, "ok": not mismatch,
                        "title": after.get("title") or book.get("title"),
                        "diff": diff, "mismatch": mismatch or None,
                        "error": (f"read-back mismatch: {mismatch}" if mismatch else None)}
            except Exception as e:  # noqa: BLE001
                return {"book_id": book_id, "ok": False, "error": f"{type(e).__name__}: {e}"}

        started = time.time()
        results: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results.extend(pool.map(work, tasks))
        results.sort(key=lambda r: r["book_id"])

        ok = sum(1 for r in results if r.get("ok"))
        return {
            "status": "ok" if ok == len(results) else ("partial" if ok else "error"),
            "dry_run": dry_run, "verify": verify, "workers": workers,
            "total": len(results), "ok": ok, "failed": len(results) - ok,
            "skipped": sum(1 for r in results if r.get("skipped")),
            "changed": sum(1 for r in results if r.get("diff") and not r.get("skipped")),
            "elapsed_seconds": round(time.time() - started, 2),
            "results": results,
        }

    def library_audit(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Report metadata problems across the library without writing anything.

        Args:
            rules (array, optional): Subset of RESEARCH_RULES to check (default all)

        Returns one bucket per rule plus per-book detail in ``books``.
        """
        rules = [r for r in (args.get("rules") or list(RESEARCH_RULES)) if r in RESEARCH_RULES]
        if args.get("rules") and not rules:
            return {"status": "error", "message": f"unknown rules; available: {sorted(RESEARCH_RULES)}"}

        started = time.time()
        books, _ = self._fetch_library()
        books = self._hydrate(books, rules)

        report: Dict[str, Any] = {"status": "ok", "source": "live library", "total": len(books),
                                  "hydrated_fields": [r for r in rules if r in LIST_OMITTED_FIELDS]}
        for rule in rules:
            report[rule] = [{"id": b.get("id"), "title": b.get("title"), "current": b.get(rule)}
                            for b in books if _rule_hit(b, rule)]
        report["metrics"] = {rule: len(report[rule]) for rule in rules}
        report["complete"] = sum(1 for b in books if not any(_rule_hit(b, r) for r in rules))
        report["elapsed_seconds"] = round(time.time() - started, 2)
        return report

    def authors_normalize(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build an author-name normalization plan (read-only; never writes to the library).

        Rules: split elements that still hold separators, drop watermarks and role
        suffixes (著/编/译…), unify country prefixes to ``(美)`` style and full-width
        parentheses, normalize dot glyphs, then de-duplicate. ``canon`` lets the
        caller map known misspellings onto one form.

        Args:
            canon (object, optional): {"旧名": "统一名"} overrides applied after cleanup
            output_file (str, optional): Write the plan to this JSON path
        """
        books, _ = self._fetch_library()
        canon = {str(k): str(v) for k, v in (args.get("canon") or {}).items()}

        watermarks = re.compile(r"ePUBw\s*[·.\-_]?\s*COM", re.I)
        role_tail = re.compile(r"\s*(编著|著|编|出品|撰文|摄影|主编|译|译者|编撰|校注|注|整理|选编|改编|审校|绘|绘著)\s*$")
        # 只统一"国别前缀"这一种括号：全角/方括号变体才是同一作者被检索成两个名字的原因。
        # （原名）这类括号保持原样，避免制造无意义的元数据改动。
        country_prefix = {
            "【美】": "(美)", "(美国)": "(美)", "[美]": "(美)", "[美] ": "(美)",
            "（美）": "(美)", "（美国）": "(美)",
            "【德】": "(德)", "(德国)": "(德)", "[德]": "(德)", "（德）": "(德)", "（德国）": "(德)",
            "【英】": "(英)", "(英国)": "(英)", "[英]": "(英)", "（英）": "(英)", "（英国）": "(英)",
            "【日】": "(日)", "(日本)": "(日)", "[日]": "(日)", "（日）": "(日)", "（日本）": "(日)",
            "【法】": "(法)", "(法国)": "(法)", "[法]": "(法)", "（法）": "(法)", "（法国）": "(法)",
        }

        def split_paren(text: str):
            match = re.match(r"^(.*?)(（[^（）]*）|\([^()]*\))(.*)$", text)
            if not match:
                return text, "", ""
            return match.group(1), match.group(2), match.group(3)

        def clean_one(name: str) -> str:
            value = watermarks.sub("", name.strip()).strip()
            for prefix, replacement in country_prefix.items():
                if value.startswith(prefix):
                    value = replacement + value[len(prefix):]
                    break
            head, sep, tail = split_paren(value)
            head = head.replace("•", "·").replace("‧", "·")
            value = head + sep + tail
            value = value.rstrip("，,、;； ")
            match = role_tail.search(value)
            if match and len(re.findall(r"[\u4e00-\u9fff]", value[:match.start()])) >= 2:
                value = value[:match.start()].strip()

            head, sep, tail = split_paren(value)
            head = re.sub(r"·\s+", "·", head)
            head = re.sub(r"\s+·", "·", head)
            # 只清空括号对内容，绝不 strip 括号本身——"(美)" 这类国别前缀必须保留
            return re.sub(r"[（(]\s*[)）]", "", head + sep + tail)

        plan = []
        for book in books:
            before = list(book.get("authors") or [])
            if not before:
                continue
            cleaned, changed = [], False
            for author in before:
                value = clean_one(author)
                value = canon.get(value, value)
                if value != author:
                    changed = True
                cleaned.append(value)

            after = []
            for author in cleaned:
                parts = [p.strip(" []《》") for p in re.split(r"[,，、/;；]", author) if p.strip()]
                if len(parts) > 1:
                    changed = True
                after.extend(canon.get(p, p) for p in parts if canon.get(p, p))

            deduped, seen = [], set()
            for author in after:
                if author and author not in seen:
                    seen.add(author)
                    deduped.append(author)
            if len(deduped) != len(after):
                changed = True

            if changed and deduped:
                plan.append({"book_id": book.get("id"), "title": book.get("title"),
                             "before": before, "after": deduped,
                             "why": "split / clean / unify / merge duplicates"})

        result: Dict[str, Any] = {
            "status": "ok", "read_only": True, "source": "live library",
            "total_books": len(books), "changed_books": len(plan), "plan": plan,
        }
        output_file = args.get("output_file")
        if output_file:
            with open(output_file, "w", encoding="utf-8") as handle:
                json.dump(plan, handle, ensure_ascii=False, indent=1)
            result["output_file"] = output_file
        result["message"] = ("Review the plan, then apply it with batch_edit "
                             "(fields: authors) - this tool never writes to the library.")
        return result

    def library_research_todo(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        List books that need metadata work, optionally split into shards for
        parallel research. Read-only.

        Args:
            rules (array, optional): Subset of RESEARCH_RULES (default all)
            shard_size (int, optional): Also return ``shards`` of this many books each
            output_file (str, optional): Write the full result to a JSON path
        """
        rules = args.get("rules") or list(RESEARCH_RULES)
        unknown = [r for r in rules if r not in RESEARCH_RULES]
        if unknown:
            return {"status": "error",
                    "message": f"unknown rules {unknown}; available: {sorted(RESEARCH_RULES)}"}

        started = time.time()
        books, total = self._fetch_library()
        todo = _build_todo(books, rules)
        metrics = {rule: sum(1 for t in todo if rule in t["need"]) for rule in rules}
        ids = [t["id"] for t in todo]
        shard_size = int(args.get("shard_size") or 0)
        shards = (_shard_ids(ids, math.ceil(len(ids) / shard_size))
                  if shard_size > 0 and ids else ([ids] if ids else []))
        result: Dict[str, Any] = {
            "status": "ok", "total_books": total, "complete": len(books) == total,
            "todo_count": len(todo), "metrics": metrics, "shards": shards,
            "elapsed_seconds": round(time.time() - started, 2), "todo": todo,
        }
        output_file = args.get("output_file")
        if output_file:
            with open(output_file, "w", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=1)
            result["output_file"] = output_file
        return result

    def library_research(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Look up candidate metadata for many books on book345 (read-only).

        Books that already have an ISBN use the detail endpoint (high confidence).
        Books without an ISBN fall back to a title search that only returns
        candidates, never an automatic choice.

        Args:
            ids (array, optional): Book IDs; omit to pick from ``rules``
            fields (array, optional): Default ["publisher", "pubdate"]
            rules (array, optional): Used when ``ids`` is omitted
            allow_title_isbn (bool, optional): Default false - allow applying an ISBN
                when exactly one exact-title match is found
            limit (int, optional): Cap the number of books researched
            workers (int, optional): Concurrency (default 6, max 8)
            output_file (str, optional): Write the full result to a JSON path
        """
        fields = [str(f) for f in (args.get("fields") or ["publisher", "pubdate"])]
        allow = parse_bool(args.get("allow_title_isbn"), False)
        workers = max(1, min(int(args.get("workers", 6)), 8))
        limit = int(args.get("limit") or 0)

        books, total = self._fetch_library()
        ids = [int(i) for i in (args.get("ids") or [])]
        if ids:
            wanted = set(ids)
            targets = [b for b in books if b.get("id") in wanted]
        else:
            default_rules = ["isbn", "publisher", "pubdate", "category", "tags", "authors"]
            rules = [r for r in (args.get("rules") or default_rules) if r in RESEARCH_RULES]
            targets = [b for b in books if any(_rule_hit(b, r) for r in rules)]
        if limit:
            targets = targets[:limit]

        started = time.time()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            research = list(pool.map(lambda b: _research_one(b, fields, allow), targets))

        result: Dict[str, Any] = {
            "status": "ok", "library_total": total, "researched": len(research),
            "filled": sum(1 for r in research if r.get("proposed")),
            "needs_manual": sum(1 for r in research if not r.get("proposed")),
            "workers": workers, "fields": fields,
            "elapsed_seconds": round(time.time() - started, 2),
            "results": research,
        }
        output_file = args.get("output_file")
        if output_file:
            with open(output_file, "w", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=1)
            result["output_file"] = output_file
        return result

    def _apply_plan(self, items: List[Dict[str, Any]], workers: int = 3,
                    dry_run: bool = True, verify: bool = True) -> Dict[str, Any]:
        """Write a plan back: snapshot compare, skip no-ops, merge fields per book."""
        started = time.time()
        books, total = self._fetch_library()
        snapshot = {b.get("id"): b for b in books}

        # Only the books named in the plan need a detail read when the plan touches
        # a field the list endpoint omits.
        plan_fields = {k for item in items if isinstance(item, dict)
                       for k in item if k not in ("book_id", "id")}
        if plan_fields & set(LIST_OMITTED_FIELDS):
            plan_ids = set()
            for item in items:
                if not isinstance(item, dict):
                    continue
                raw_id = item.get("book_id") or item.get("id")
                if raw_id and str(raw_id).isdigit():
                    plan_ids.add(int(raw_id))
            for book in self._hydrate([snapshot[i] for i in plan_ids if i in snapshot],
                                      list(plan_fields)):
                snapshot[book.get("id")] = book

        results: List[Dict[str, Any]] = []
        tasks: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            book_id = item.get("book_id") or item.get("id")
            if not book_id:
                continue
            try:
                book_id = int(book_id)
            except (TypeError, ValueError):
                pass
            fields = {k: v for k, v in item.items()
                      if k not in ("book_id", "id") and v not in (None, "")}
            unknown = sorted(set(fields) - set(EDITABLE_FIELDS))
            if unknown:
                results.append({"book_id": book_id, "ok": False,
                                "error": f"non-editable fields {unknown}"})
                continue
            current = snapshot.get(book_id) or {}
            diff = {k: {"before": current.get(k), "after": v}
                    for k, v in fields.items() if not _same_val(current.get(k), v)}
            if not diff:
                results.append({"book_id": book_id, "ok": True, "title": current.get("title"),
                                "skipped": True, "reason": "fields already match"})
            else:
                tasks.append({"book_id": book_id, "title": current.get("title"),
                              "fields": {k: v["after"] for k, v in diff.items()},
                              "diff": diff})

        if dry_run:
            results += [{"book_id": t["book_id"], "ok": True, "title": t["title"],
                         "dry_run": True, "diff": t["diff"]} for t in tasks]
        else:
            def work(task: Dict[str, Any]) -> Dict[str, Any]:
                book_id = task["book_id"]
                try:
                    resp = self._write_book(book_id, task["fields"])
                    if isinstance(resp, dict) and resp.get("err") not in (None, "ok"):
                        return {"book_id": book_id, "ok": False, "title": task["title"],
                                "error": f"write rejected: {str(resp)[:180]}"}
                    if not verify:
                        return {"book_id": book_id, "ok": True, "title": task["title"],
                                "diff": task["diff"]}
                    after = self._read_book(book_id)
                    mismatch = {k: {"expect": v, "actual": after.get(k)}
                                for k, v in task["fields"].items()
                                if not _same_val(after.get(k), v)}
                    return {"book_id": book_id, "ok": not mismatch, "title": task["title"],
                            "diff": task["diff"], "mismatch": mismatch or None,
                            "error": (f"read-back mismatch: {mismatch}" if mismatch else None)}
                except Exception as e:  # noqa: BLE001
                    return {"book_id": book_id, "ok": False, "title": task["title"],
                            "error": f"{type(e).__name__}: {e}"}

            with ThreadPoolExecutor(max_workers=workers) as pool:
                results += list(pool.map(work, tasks))

        ok = sum(1 for r in results if r.get("ok"))
        return {
            "status": "ok" if ok == len(results) else ("partial" if ok else "error"),
            "dry_run": dry_run, "library_total": total,
            "total": len(results), "ok": ok, "failed": len(results) - ok,
            "skipped": sum(1 for r in results if r.get("skipped")),
            "changed": sum(1 for r in results if r.get("diff") and not r.get("skipped")),
            "elapsed_seconds": round(time.time() - started, 2),
            "results": results,
        }

    def library_enrich_apply(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Write a previously prepared plan back to the library.

        Args:
            items (array, optional): [{"book_id": 1, "publisher": "...", "pubdate": "..."}]
            plan_file (str, optional): Read the plan from JSON (accepts the output of
                library_research as well); ignored when ``items`` is given
            workers (int, optional): Concurrency (default 3, max 6 - the server
                serializes writes, so more workers rarely help)
            dry_run (bool, optional): Default true - preview the diff only
            verify (bool, optional): Default true - read back every written book
        """
        items = list(args.get("items") or [])
        plan_file = args.get("plan_file")
        if not items and plan_file:
            with open(plan_file, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                items = data.get("plan") or data.get("items") or data.get("results") or []
            else:
                items = data
        if not items:
            return {"status": "error", "message": "provide items or plan_file"}

        return self._apply_plan(
            items,
            workers=max(1, min(int(args.get("workers", 3)), 6)),
            dry_run=parse_bool(args.get("dry_run"), True),
            verify=parse_bool(args.get("verify"), True),
        )

    def library_enrich(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        One-shot metadata completion: find targets, research on book345 in
        parallel, then write the accepted values back.

        Args:
            ids (array, optional): Book IDs; omit to pick from ``rules``
            fields (array, optional): Default ["publisher", "pubdate"]
            rules (array, optional): Used when ``ids`` is omitted
            dry_run (bool, optional): Default true - plan and preview only
            allow_title_isbn (bool, optional): Default false
            apply_confidence (str, optional): "high" (default) or "medium"
            overwrite (bool, optional): Default false - only fill gaps/dirty values
            research_workers (int, optional): Default 6, max 8
            write_workers (int, optional): Default 3, max 6
        """
        fields = [str(f) for f in (args.get("fields") or ["publisher", "pubdate"])]
        rules = [r for r in (args.get("rules") or list(RESEARCH_RULES)) if r in RESEARCH_RULES]
        dry_run = parse_bool(args.get("dry_run"), True)
        allow = parse_bool(args.get("allow_title_isbn"), False)
        overwrite = parse_bool(args.get("overwrite"), False)
        research_workers = max(1, min(int(args.get("research_workers", 6)), 8))
        write_workers = max(1, min(int(args.get("write_workers", 3)), 6))
        confidence = str(args.get("apply_confidence") or "high")
        allowed = {"high"} if confidence == "high" else {"high", "medium"}

        started = time.time()
        books, total = self._fetch_library()
        ids = [int(i) for i in (args.get("ids") or [])]
        if ids:
            wanted = set(ids)
            targets = [b for b in books if b.get("id") in wanted]
        else:
            targets = [b for b in books if any(_rule_hit(b, r) for r in rules)]

        targets = self._hydrate(targets, fields)
        with ThreadPoolExecutor(max_workers=research_workers) as pool:
            research = list(pool.map(lambda b: _research_one(b, fields, allow), targets))

        by_id = {b.get("id"): b for b in targets}
        plan = []
        for item in research:
            if item.get("confidence") not in allowed:
                continue
            current = by_id.get(item["book_id"]) or {}
            proposed = {}
            for key, value in (item.get("proposed") or {}).items():
                if value in (None, ""):
                    continue
                if overwrite or _field_needs_fill(current, key):
                    proposed[key] = value
            if proposed:
                plan.append({"book_id": item["book_id"], **proposed})

        applied = None
        if plan:
            applied = self._apply_plan(plan, workers=write_workers,
                                       dry_run=dry_run, verify=not dry_run)

        return {
            "status": "ok", "dry_run": dry_run, "library_total": total,
            "targets": len(targets), "researched": len(research),
            "filled": sum(1 for r in research if r.get("proposed")),
            "needs_manual": sum(1 for r in research if not r.get("proposed")),
            "plan_count": len(plan), "plan": plan, "apply": applied,
            "elapsed_seconds": round(time.time() - started, 2),
            "research": research,
        }

    def book_add_from_wuming(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add one book found on book345 to the library, after checking for duplicates.

        Args:
            query (str, optional): Keyword (title/author/ISBN); required unless ``isbn``
            isbn (str, optional): Exact ISBN lookup
            auto_add (bool, optional): Default false - return candidates for confirmation
            fields (array, optional): Fields written on import (default title, authors,
                publisher, isbn, pubdate, category, rating, comments)
            include_source (bool, optional): Default false - append the book345 page URL
                to comments. Off by default so library metadata stays clean.
        """
        query = str(args.get("query") or "").strip()
        isbn = str(args.get("isbn") or "").strip()
        auto_add = parse_bool(args.get("auto_add"), False)
        include_source = parse_bool(args.get("include_source"), False)
        fields = args.get("fields") or ["title", "authors", "publisher", "isbn",
                                        "pubdate", "category", "rating", "comments"]
        if not query and not isbn:
            return {"status": "error", "message": "provide query or isbn"}

        # 1) Duplicate check against the local library first
        if isbn:
            found = self.search_books({"isbn": isbn, "num": 5})
        else:
            found = self.search_books({"name": query, "num": 5})
        if isinstance(found, dict) and found.get("books"):
            return {"status": "exists", "source": "mybooks", "book": found["books"][0]}

        # 2) Look it up on book345
        result = wuming_client.get_book_detail(isbn) if isbn \
            else wuming_client.search_books(query, 5)
        if not isinstance(result, dict) or result.get("status") == "error":
            return {"status": "error", "message": f"book345 lookup failed: {result}"}

        books = result.get("books")
        candidate = books[0] if books else (result if result.get("title") else None)
        if not candidate:
            return {"status": "not_found", "message": "book345 has no matching book"}

        candidate_isbn = str(candidate.get("isbn") or "").strip()
        preview = {key: candidate.get(key) for key in
                   ("title", "author", "isbn", "publisher", "pubDate", "rate", "url")}

        if not auto_add:
            return {"status": "candidates", "candidates": [preview],
                    "message": "not in the local library; call again with auto_add=true to import"}

        # The ISBN may already be taken by another record
        if candidate_isbn:
            check = self.search_books({"isbn": candidate_isbn, "num": 5})
            if isinstance(check, dict) and check.get("books"):
                return {"status": "exists", "source": "mybooks_isbn", "book": check["books"][0]}

        if not candidate_isbn:
            return {"status": "needs_isbn",
                    "message": "no ISBN, so the record cannot be created automatically; "
                               "upload an ebook (book_upload) or add it by ISBN first",
                    "candidate": preview}

        added = self.book_add_by_isbn({"isbn": candidate_isbn})
        if not isinstance(added, dict) or added.get("err") not in (None, "ok"):
            return {"status": "error", "message": f"book_add_by_isbn failed: {added}",
                    "candidate": preview}
        book_id = added.get("book_id") or (added.get("book") or {}).get("id")
        if not book_id:
            return {"status": "error", "message": f"server returned no book_id: {added}",
                    "candidate": preview}

        body: Dict[str, Any] = {}
        if "title" in fields and candidate.get("title"):
            body["title"] = candidate["title"]
        if "authors" in fields and candidate.get("author"):
            raw = str(candidate["author"]).replace("；", ";").replace("，", ",")
            authors = [a.strip() for a in re.split(r"[;,/]", raw) if a.strip()]
            if authors:
                body["authors"] = authors
        if "publisher" in fields and candidate.get("publisher"):
            body["publisher"] = candidate["publisher"]
        if "pubdate" in fields and candidate.get("pubDate"):
            body["pubdate"] = str(candidate["pubDate"])[:10]
        if "rating" in fields and candidate.get("rate") is not None:
            try:
                body["rating"] = float(candidate["rate"])
            except (TypeError, ValueError):
                pass
        if "comments" in fields and candidate.get("summary"):
            body["comments"] = candidate["summary"]
        if include_source and candidate.get("url"):
            body["comments"] = (body.get("comments") or "") + \
                f"\n\n来源：无名图书 {candidate['url']}"

        edit_result = self.edit_book({"book_id": book_id, **body}) if body else None
        return {"status": "added", "book_id": book_id, "method": "isbn_add",
                "result": added, "applied_fields": sorted(body), "edit": edit_result}

    # ========================================================================
    # Tool Dispatcher
    # ========================================================================

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool by name.

        Args:
            tool_name: Name of the tool to execute
            args: Tool arguments as dict

        Returns:
            Tool execution result
        """
        if tool_name in AUTH_FREE_TOOLS:
            return AUTH_FREE_TOOLS[tool_name](args)

        tool_method = getattr(self, tool_name, None)

        if tool_method is None or not callable(tool_method):
            available_tools = [
                "get_user_info", "library_stats", "reading_stats",
                "search_books", "search_by_category", "list_folders", "search_by_folder",
                "set_folder", "rename_folder", "get_book", "edit_book",
                "get_notes", "push_notes", "clear_imported_notes",
                "book_fill", "book_refer_search", "book_refer_apply", "save_meta_to_file", "mailto", "send_to_device", "categories",
                "list_authors", "get_author_books", "book_upload",
                "book_add_by_isbn", "wants", "list_wants", "favorite",
                "list_favorites", "reading", "list_reading", "read_done",
                "list_read_done", "get_book_reading_stats", "update_book_reading_stats",
                "get_reading_time", "set_reading_time", "delete_reading_time",
                "list_my_booklists", "list_public_booklists", "list_liked_booklists",
                "get_booklist", "create_booklist", "update_booklist", "delete_booklist",
                "booklist_add_books", "booklist_remove_book", "like_booklist", "get_book_booklists",
                "epub_fix", "epub_fix_progress",
                "tts_save_config", "tts_test_connection",
                "tts_convert", "tts_progress", "tts_clone_upload", "tts_clone_list",
                "tts_clone_delete", "tts_clone_audio", "tts_prompt_list",
                "tts_prompt_save", "tts_prompt_delete",
                "wuming_search", "wuming_toplist", "wuming_recent_hot",
                "wuming_detail", "wuming_guide", "wuming_tags",
                "batch_edit", "library_audit", "authors_normalize",
                "library_research_todo", "library_research",
                "library_enrich_apply", "library_enrich", "book_add_from_wuming"
            ]
            return {
                "status": "error",
                "message": f"Unknown tool: {tool_name}. Available tools: {', '.join(available_tools)}"
            }

        return tool_method(args)


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """Command-line entry point."""
    # Check arguments
    if len(sys.argv) < 2:
        print(json.dumps({
            "status": "error",
            "message": "Usage: mybooks_api.py <tool-name> '<json-args>'"
        }), file=sys.stderr)
        sys.exit(1)

    tool_name = sys.argv[1]
    args_json = sys.argv[2] if len(sys.argv) > 2 else "{}"

    # Parse arguments
    try:
        args = json.loads(args_json)
    except json.JSONDecodeError as e:
        print(json.dumps({
            "status": "error",
            "message": f"Invalid JSON arguments: {str(e)}"
        }), file=sys.stderr)
        sys.exit(1)

    # book345-only tools need no MyBooks credentials: dispatch before the env check
    if tool_name in AUTH_FREE_TOOLS:
        print(json.dumps(AUTH_FREE_TOOLS[tool_name](args), ensure_ascii=False, indent=2))
        return

    # Check environment variables
    host = os.environ.get("MYBOOKS_HOST", "")
    username = os.environ.get("MYBOOKS_USER", "")
    password = os.environ.get("MYBOOKS_PASSWORD", "")

    if not host:
        print(json.dumps(ERROR_MESSAGES["env_missing"]), file=sys.stderr)
        sys.exit(1)

    if not username or not password:
        print(json.dumps(ERROR_MESSAGES["auth_missing"]), file=sys.stderr)
        sys.exit(1)

    # Create API client and execute
    api = MyBooksAPI(host, username, password)
    api.sign_in()
    result = api.execute_tool(tool_name, args)

    # Output result
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
