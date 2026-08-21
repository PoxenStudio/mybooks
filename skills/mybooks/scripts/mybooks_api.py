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
import os
import sys
import base64
import urllib.parse
import urllib3
from typing import Any, Dict

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ============================================================================
# Constants
# ============================================================================

REQUIRED_ENV_VARS = ["MYBOOKS_HOST", "MYBOOKS_USER", "MYBOOKS_PASSWORD"]

API_TTS_PREFIX = "/api/toolbox/mimo_tts"

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
        self.host = host.rstrip('/')
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
        # Use form-encoded data (not JSON) as required by the server
        data = f"username={self.username}&password={self.password}"

        try:
            resp = self.requests.post(
                url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
                verify=self.verify_ssl
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
        Search books by keyword (title or author).

        Args:
            name (str, required): Search keyword
            num (int, optional): Results per page (default: 20)
            page (int, optional): Page number (default: 1)
        """
        name = args.get("name", "")
        num = args.get("num", 20)
        page = args.get("page", 1)
        start = (page - 1) * num

        encoded_name = urllib.parse.quote(name)
        return self._call_with_auto_relogin(
            "GET",
            f"/api/search?name={encoded_name}&num={num}&start={start}"
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
        Upload ebook file to library.

        Args:
            file_path (str, required): Absolute path to local file
        """
        file_path = args.get("file_path", "")
        if not file_path:
            return {"status": "error", "message": "file_path is required"}

        if not os.path.isfile(file_path):
            return {"status": "error", "message": f"File not found: {file_path}"}

        try:
            with open(file_path, 'rb') as f:
                files = {'ebook': f}
                return self._call_with_auto_relogin(
                    "POST",
                    "/api/book/upload",
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
        tool_method = getattr(self, tool_name, None)

        if tool_method is None or not callable(tool_method):
            available_tools = [
                "get_user_info", "library_stats", "reading_stats",
                "search_books", "search_by_category", "get_book", "edit_book",
                "get_notes", "push_notes", "clear_imported_notes",
                "book_fill", "save_meta_to_file", "mailto", "send_to_device", "categories",
                "list_authors", "get_author_books", "book_upload",
                "book_add_by_isbn", "wants", "list_wants", "favorite",
                "list_favorites", "reading", "list_reading", "read_done",
                "list_read_done", "tts_save_config", "tts_test_connection",
                "tts_convert", "tts_progress", "tts_clone_upload", "tts_clone_list",
                "tts_clone_delete", "tts_clone_audio", "tts_prompt_list",
                "tts_prompt_save", "tts_prompt_delete"
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
