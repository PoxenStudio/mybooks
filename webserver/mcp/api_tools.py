#!/usr/bin/env python3
"""
MCP tools that mirror the MyBooks skill (skills/mybooks/scripts/mybooks_api.py).

Each tool is a thin wrapper over a MyBooks HTTP API: it validates arguments,
builds the request and calls it through ``call`` — an async callable injected by
MCPService that performs the request in-process (loopback HTTP) as the
MCP-authenticated user. Keeping the argument handling identical to the skill
script means both entry points share one server-side implementation.

Tool names, parameters and behavior MUST stay aligned with the skill; see
.claude/skills/mybooks-mcp-update/SKILL.md for the update procedure.

Deliberately NOT exposed here (they read/write the caller's local filesystem,
which on an MCP server would be the *server's* filesystem):
    book_upload, tts_clone_upload, tts_clone_audio
"""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

# call(method, path, params=None, json=None) -> parsed JSON dict
ApiCall = Callable[..., Awaitable[Dict[str, Any]]]
ToolFunc = Callable[[ApiCall, Dict[str, Any]], Awaitable[Dict[str, Any]]]

API_TTS_PREFIX = "/api/toolbox/mimo_tts"


@dataclass
class ApiTool:
    name: str
    description: str
    properties: Dict[str, Any]
    required: List[str] = field(default_factory=list)
    func: Optional[ToolFunc] = None

    def input_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": dict(self.properties), "required": list(self.required)}


API_TOOLS: Dict[str, ApiTool] = {}


def tool(name: str, description: str, properties: Optional[Dict[str, Any]] = None, required: Optional[List[str]] = None):
    def wrap(func: ToolFunc) -> ToolFunc:
        API_TOOLS[name] = ApiTool(name, description, properties or {}, required or [], func)
        return func
    return wrap


def S(desc: str, **kw) -> Dict[str, Any]:
    return {"type": "string", "description": desc, **kw}


def I(desc: str, **kw) -> Dict[str, Any]:  # noqa: E743
    return {"type": "integer", "description": desc, **kw}


def N(desc: str, **kw) -> Dict[str, Any]:
    return {"type": "number", "description": desc, **kw}


def B(desc: str, **kw) -> Dict[str, Any]:
    return {"type": "boolean", "description": desc, **kw}


def A(desc: str, items: Optional[Dict[str, Any]] = None, **kw) -> Dict[str, Any]:
    return {"type": "array", "description": desc, "items": items or {}, **kw}


def _err(message: str) -> Dict[str, Any]:
    return {"status": "error", "message": message}


BOOK_ID = I("Book ID")
NUM = I("Results per page", default=20)
PAGE = I("Page number, starting from 1", default=1)


def _page(args: Dict[str, Any]):
    num = int(args.get("num", 20))
    page = int(args.get("page", 1))
    return num, (page - 1) * num


# ============================================================================
# User & statistics
# ============================================================================

@tool("get_user_info", "Get current user info and system statistics.")
async def get_user_info(call, args):
    return await call("GET", "/api/user/info")


@tool("library_stats", "Get library statistics: total, ebook and physical book counts.")
async def library_stats(call, args):
    return await call("GET", "/api/library/stats")


@tool("reading_stats", "Get current user's reading statistics (reading / finished counts, current and this month's books).")
async def reading_stats(call, args):
    return await call("GET", "/api/reading/stats")


# ============================================================================
# Search & browse
# ============================================================================

@tool(
    "search_books",
    "Search books. Three ways, combinable: (1) `name` keyword — fuzzy match on title/author/comments with "
    "simplified/traditional Chinese conversion; a bare ISBN is looked up exactly; (2) field parameters "
    "title/author/isbn/publisher/series/tag, combined with AND; (3) a Calibre search expression in `name`, e.g. "
    "'title:=三体', 'authors:余华 AND rating:>=4', 'tags:科幻 AND NOT tags:短篇', 'pubdate:>=2020', '#category:=\"小说\"'.",
    {
        "name": S("Keyword, bare ISBN, or Calibre search expression"),
        "title": S("Exact book title"),
        "author": S("Author (contains match)"),
        "isbn": S("ISBN-10/13, dashes allowed"),
        "publisher": S("Publisher (contains match)"),
        "series": S("Series (contains match)"),
        "tag": S("Tag (contains match)"),
        "exact": B("Use exact match for author/publisher/series/tag", default=False),
        "order": S("Sort field, e.g. pubdate, rating, timestamp"),
        "num": NUM,
        "page": PAGE,
    },
)
async def search_books(call, args):
    num, start = _page(args)
    params: Dict[str, Any] = {"num": num, "start": start}
    for key in ("name", "title", "author", "isbn", "publisher", "series", "tag", "order"):
        value = str(args.get(key) or "").strip()
        if value:
            params[key] = value
    if args.get("exact"):
        params["exact"] = 1
    if len(params) == 2:
        return {"err": "params.invalid", "msg": "At least one of name/title/author/isbn/publisher/series/tag is required"}
    return await call("GET", "/api/search", params=params)


@tool("search_by_category", "List books in a category (custom #category column).",
      {"category": S("Category name, e.g. 科幻"), "num": NUM, "page": PAGE}, ["category"])
async def search_by_category(call, args):
    num, start = _page(args)
    category = args.get("category", "")
    return await call("GET", "/api/search", params={"name": f'#category:="{category}"', "num": num, "start": start})


@tool("categories", "Get all custom categories with book counts.")
async def categories(call, args):
    return await call("GET", "/api/categories")


@tool("list_folders", "Get the folder tree (at most two levels) with book counts.")
async def list_folders(call, args):
    return await call("GET", "/api/folders")


@tool("search_by_folder", "List books directly inside a folder.",
      {"path": S("Folder path such as 文学 or 文学.小说; empty means root"), "num": NUM, "page": PAGE})
async def search_by_folder(call, args):
    num, start = _page(args)
    return await call("GET", "/api/folder/books", params={"path": args.get("path", ""), "size": num, "start": start})


@tool("list_authors", "Get all authors with book counts.", {"show": S("Pass 'all' to show all authors")})
async def list_authors(call, args):
    params = {"show": "all"} if args.get("show") == "all" else None
    return await call("GET", "/api/author", params=params)


@tool("get_author_books", "Get books by an author (paginated).",
      {"author_name": S("Author name"), "num": NUM, "page": PAGE}, ["author_name"])
async def get_author_books(call, args):
    author = args.get("author_name", "")
    if not author:
        return _err("author_name is required")
    num, start = _page(args)
    from urllib.parse import quote
    return await call("GET", f"/api/author/{quote(author)}", params={"num": num, "start": start})


# ============================================================================
# Book detail & edit
# ============================================================================

@tool("get_book", "Get detailed book information.", {"book_id": BOOK_ID}, ["book_id"])
async def get_book(call, args):
    book_id = args.get("book_id")
    if not book_id:
        return _err("book_id is required")
    return await call("GET", f"/api/book/{book_id}")


@tool(
    "edit_book", "Edit book metadata (admin or book owner). Only the fields passed are changed.",
    {
        "book_id": BOOK_ID,
        "title": S("Book title"),
        "authors": A("Author list", {"type": "string"}),
        "tags": A("Tag list", {"type": "string"}),
        "publisher": S("Publisher"),
        "isbn": S("ISBN"),
        "series": S("Series name"),
        "rating": N("Rating (0-10)"),
        "languages": A("Language codes", {"type": "string"}),
        "pubdate": S("Publication date, YYYY-MM-DD"),
        "comments": S("Book description"),
        "category": S("Custom category"),
        "book_count": I("Physical book count"),
        "book_type": I("0=ebook, 1=physical"),
    },
    ["book_id"],
)
async def edit_book(call, args):
    book_id = args.get("book_id")
    if not book_id:
        return _err("book_id is required")
    body = {k: v for k, v in args.items() if k != "book_id"}
    return await call("POST", f"/api/book/{book_id}/edit", json=body)


@tool("book_fill", "Auto-fill book info from online sources (admin only).",
      {"idlist": {"description": 'Array of book IDs, or the string "all"', "oneOf": [{"type": "array", "items": {"type": "integer"}}, {"type": "string", "enum": ["all"]}]}},
      ["idlist"])
async def book_fill(call, args):
    idlist = args.get("idlist")
    if not idlist:
        return _err('idlist is required: an array of book IDs or "all"')
    return await call("POST", "/api/admin/book/fill", json={"idlist": idlist})


@tool("save_meta_to_file", "Write book metadata into the ebook file itself (epub/azw3/pdf only; admin or book owner).",
      {"book_id": BOOK_ID, "fmt": S("Limit to one format: epub/azw3/pdf; all supported formats if omitted")}, ["book_id"])
async def save_meta_to_file(call, args):
    book_id = args.get("book_id")
    if not book_id:
        return _err("book_id is required")
    fmt = args.get("fmt")
    return await call("POST", f"/api/book/{book_id}/savemeta", params={"fmt": str(fmt)} if fmt else None)


@tool("book_add_by_isbn", "Add a physical book by ISBN (metadata fetched online).", {"isbn": S("ISBN number")}, ["isbn"])
async def book_add_by_isbn(call, args):
    isbn = args.get("isbn", "")
    if not isbn:
        return _err("isbn is required")
    return await call("POST", "/api/book/add", json={"isbn": isbn})


# ============================================================================
# Folders
# ============================================================================

@tool("set_folder", "Set the folder of one book, or of many books (admin only).",
      {"book_id": I("Book ID for a single book"), "book_ids": A("Book IDs for a batch", {"type": "integer"}),
       "folder": S('Folder path such as 文学.小说; "" or "清除" moves the book out of any folder')},
      ["folder"])
async def set_folder(call, args):
    if "folder" not in args:
        return _err("folder is required")
    if args.get("book_ids"):
        return await call("POST", "/api/book/folder", json={"ids": args["book_ids"], "folder": args["folder"]})
    book_id = args.get("book_id")
    if not book_id:
        return _err("book_id or book_ids is required")
    return await call("POST", f"/api/book/{book_id}/folder", json={"folder": args["folder"]})


@tool("rename_folder",
      "Rename the last segment of a folder (admin only). If the target exists the server answers folder.exists without "
      "changing anything; merging is irreversible and only happens with merge=true after the user confirms.",
      {"path": S("Existing folder path"), "name": S("New name of the last segment"),
       "merge": B("Confirm merging into an existing folder", default=False)},
      ["path", "name"])
async def rename_folder(call, args):
    if not args.get("path") or not args.get("name"):
        return _err("path and name are required")
    return await call("POST", "/api/folder/rename", json={"path": args["path"], "name": args["name"], "merge": bool(args.get("merge", False))})


# ============================================================================
# Notes (reading annotations)
# ============================================================================

@tool(
    "push_notes",
    "Import third-party annotations (e.g. WeChat Reading highlights/thoughts) into a book's reading records. "
    "ALWAYS call with dry_run=true first, show the report, and only call with dry_run=false after explicit confirmation. "
    "Re-syncs are deduplicated server-side; only set force=true if the EPUB itself was replaced.",
    {
        "book_id": I("MyBooks book ID (must have an EPUB format)"),
        "anchors": A("Annotations to import", {
            "type": "object",
            "properties": {
                "id": S("Stable id from the source system, used for idempotency"),
                "text": S("Highlighted original text to locate; omit for chapter-/book-level notes"),
                "chapterHint": S("Source chapter title, helps locate a chapter-start position"),
                "note": S("User's own thought/comment"),
                "color": S("Highlight color", default="yellow"),
                "style": S("highlight / underline / squiggly", default="highlight"),
                "createdAt": I("ms epoch timestamp from the source system"),
                "source": S("Provenance tag", default="wxread"),
            },
            "required": ["id"],
        }),
        "on_ambiguous": S("Behavior when text matches more than once", enum=["error", "first_match"], default="error"),
        "dry_run": B("true = only resolve and report; false = also write", default=True),
        "force": B("Re-resolve everything from scratch", default=False),
    },
    ["book_id", "anchors"],
)
async def push_notes(call, args):
    if not args.get("book_id"):
        return _err("book_id is required")
    if not args.get("anchors"):
        return _err("anchors is required and must be non-empty")
    body = {
        "book_id": args["book_id"],
        "anchors": args["anchors"],
        "on_ambiguous": args.get("on_ambiguous", "error"),
        "dry_run": args.get("dry_run", True),
        "force": args.get("force", False),
    }
    return await call("POST", "/api/sync/import", json=body)


@tool("get_notes", "Query a book's reading annotations (bookmarks/highlights/notes). Provide book_id or title; "
      "a title must match exactly one book, otherwise candidates are returned.",
      {"book_id": I("MyBooks book ID"), "title": S("Book title, used when book_id is omitted"),
       "own": I("1 = only my notes (default); 0 = also other users' shared notes", enum=[0, 1], default=1)})
async def get_notes(call, args):
    book_id = args.get("book_id")
    title = args.get("title")
    own = args.get("own", 1)
    if own not in (0, 1):
        return _err("own must be 0 or 1")
    if not book_id:
        if not title:
            return _err("book_id or title is required")
        found = await search_books(call, {"name": title, "num": 5, "page": 1})
        if found.get("err") != "ok":
            return found
        books = found.get("books") or []
        if not books:
            return _err(f"No book found matching title: {title}")
        if len(books) > 1:
            return {
                "status": "error",
                "message": "Multiple books matched this title; specify book_id",
                "candidates": [{"id": b.get("id"), "title": b.get("title"), "authors": b.get("authors")} for b in books],
            }
        book_id = books[0].get("id")
        if not book_id:
            return _err("Search result missing book id")
    # cloud 书籍的 book_hash 固定为 "cloud-<book_id>-epub"，与 sync_import_service.book_hash_for() 保持一致
    book_hash = f"cloud-{book_id}-epub"
    result = await call("GET", "/api/sync", params={"since": 0, "type": "notes", "book": book_hash, "own": own})
    if isinstance(result, dict):
        result["book_id"] = book_id
        result["book_hash"] = book_hash
    return result


@tool("clear_imported_notes", "Remove all annotations push_notes imported for one book (current user only). "
      "Only use when the user explicitly asks to undo/reset an import.", {"book_id": BOOK_ID}, ["book_id"])
async def clear_imported_notes(call, args):
    if not args.get("book_id"):
        return _err("book_id is required")
    return await call("POST", "/api/sync/import/clear", json={"book_id": args["book_id"]})


# ============================================================================
# Delivery
# ============================================================================

@tool("mailto", "Send a book to an email address as attachment.", {"book_id": BOOK_ID, "email": S("Target email address")}, ["book_id", "email"])
async def mailto(call, args):
    if not args.get("book_id"):
        return _err("book_id is required")
    if not args.get("email"):
        return _err("email is required")
    return await call("POST", f"/api/book/{args['book_id']}/mailto", json={"email": args["email"]})


@tool("send_to_device", "Send a book to a reading device.",
      {"book_id": BOOK_ID, "device_type": S("Device type: kindle/duokan/ireader/etc."),
       "device_url": S("Device WiFi address (non-kindle)"), "mailbox": S("Kindle email address (kindle)")},
      ["book_id", "device_type"])
async def send_to_device(call, args):
    book_id = args.get("book_id")
    if not book_id:
        return _err("book_id is required")
    body = {k: v for k, v in args.items() if k != "book_id"}
    return await call("POST", f"/api/book/{book_id}/send_to_device", json=body)


# ============================================================================
# Personal shelves: wants / favorites / reading state
# ============================================================================

@tool("wants", "Mark/unmark a book as want-to-read.", {"book_id": BOOK_ID, "wants": B("true=mark, false=unmark", default=True)}, ["book_id"])
async def wants(call, args):
    if not args.get("book_id"):
        return _err("book_id is required")
    return await call("POST", f"/api/book/{args['book_id']}/wants", json={"wants": args.get("wants", True)})


@tool("list_wants", "Get current user's want-to-read list.")
async def list_wants(call, args):
    return await call("GET", "/api/wants")


@tool("favorite", "Mark/unmark a book as favorite.", {"book_id": BOOK_ID, "favorite": B("true=favorite, false=unfavorite", default=True)}, ["book_id"])
async def favorite(call, args):
    if not args.get("book_id"):
        return _err("book_id is required")
    return await call("POST", f"/api/book/{args['book_id']}/favorite", json={"favorite": args.get("favorite", True)})


@tool("list_favorites", "Get current user's favorite list.")
async def list_favorites(call, args):
    return await call("GET", "/api/favorites")


@tool("reading", "Set a book's reading state.", {"book_id": BOOK_ID, "read_state": I("0=unread, 1=reading, 2=finished", enum=[0, 1, 2])}, ["book_id", "read_state"])
async def reading(call, args):
    if not args.get("book_id"):
        return _err("book_id is required")
    return await call("POST", f"/api/book/{args['book_id']}/readstate", json={"read_state": args.get("read_state", 1)})


@tool("list_reading", "Get current user's currently-reading list.")
async def list_reading(call, args):
    return await call("GET", "/api/reading")


@tool("read_done", "Mark a book as finished.", {"book_id": BOOK_ID}, ["book_id"])
async def read_done(call, args):
    if not args.get("book_id"):
        return _err("book_id is required")
    return await call("POST", f"/api/book/{args['book_id']}/readstate", json={"read_state": 2})


@tool("list_read_done", "Get current user's finished list.")
async def list_read_done(call, args):
    return await call("GET", "/api/read-done")


# ============================================================================
# Reading stats & manual reading time
# ============================================================================

@tool("get_book_reading_stats", "Get current user's reading duration/progress for a book, broken down by ebook format.", {"book_id": BOOK_ID}, ["book_id"])
async def get_book_reading_stats(call, args):
    if not args.get("book_id"):
        return _err("book_id is required")
    return await call("GET", f"/api/book/{args['book_id']}/reading_stats")


@tool(
    "update_book_reading_stats",
    "Manually update/correct current user's reading duration or progress for one ebook format of a book.",
    {
        "book_id": BOOK_ID,
        "format": S("Ebook format, e.g. epub/pdf/mobi/azw3/txt"),
        "duration_seconds": I("Seconds to ADD to the cumulative duration (not an absolute value)"),
        "progress": A("[current, total], e.g. [120, 488]; ~100% auto-marks the format finished", {"type": "integer"}, minItems=2, maxItems=2),
        "start_time": S("ISO8601 string or epoch timestamp; explicitly starts a new reading round"),
        "finish_time": S("ISO8601 string or epoch timestamp; marks the current round finished"),
        "state": I("0=reading, 1=finished (alternative to finish_time)", enum=[0, 1]),
    },
    ["book_id", "format"],
)
async def update_book_reading_stats(call, args):
    book_id = args.get("book_id")
    if not book_id or not args.get("format"):
        return _err("book_id and format are required")
    body = {k: v for k, v in args.items() if k != "book_id"}
    return await call("POST", f"/api/book/{book_id}/reading_stats", json=body)


@tool("get_reading_time", "Get the manual reading-time entry (and reference totals) of a book on a date.",
      {"book_id": BOOK_ID, "date": S("YYYY-MM-DD")}, ["book_id", "date"])
async def get_reading_time(call, args):
    if not args.get("book_id") or not args.get("date"):
        return _err("book_id and date are required")
    return await call("GET", f"/api/book/{args['book_id']}/reading_time", params={"date": args["date"]})


@tool("set_reading_time", "Add or overwrite the manual reading-time entry of a book on a date.",
      {"book_id": BOOK_ID, "date": S("YYYY-MM-DD, must not be in the future"),
       "duration_seconds": I("0~64800 (18h); overwrites that day's manual entry"),
       "start_time": S("Free-form start time text"), "end_time": S("Free-form end time text")},
      ["book_id", "date", "duration_seconds"])
async def set_reading_time(call, args):
    book_id = args.get("book_id")
    if not book_id or not args.get("date") or args.get("duration_seconds") is None:
        return _err("book_id, date and duration_seconds are required")
    body = {k: v for k, v in args.items() if k != "book_id"}
    return await call("POST", f"/api/book/{book_id}/reading_time", json=body)


@tool("delete_reading_time", "Delete the manual reading-time entry of a book on a date. Without confirm=true nothing is "
      "deleted and the entry is returned as a preview; only confirm after the user explicitly agrees.",
      {"book_id": BOOK_ID, "date": S("YYYY-MM-DD"), "confirm": B("Must be true to actually delete", default=False)},
      ["book_id", "date"])
async def delete_reading_time(call, args):
    book_id = args.get("book_id")
    date = args.get("date")
    if not book_id or not date:
        return _err("book_id and date are required")
    if args.get("confirm") is not True:
        preview = await call("GET", f"/api/book/{book_id}/reading_time", params={"date": date})
        return {
            "err": "confirm.required",
            "msg": "Nothing deleted. Show this entry to the user and, only after they explicitly agree, call again with \"confirm\": true.",
            "entry": preview.get("entry"),
            "preview_err": preview.get("err"),
        }
    return await call("DELETE", f"/api/book/{book_id}/reading_time", params={"date": date})


# ============================================================================
# Booklists
# ============================================================================

BOOKLIST_ID = I("Booklist ID")


@tool("list_my_booklists", "List the current user's own booklists.")
async def list_my_booklists(call, args):
    return await call("GET", "/api/booklists/mine")


@tool("list_public_booklists", "List public booklists.",
      {"page": I("Page number", default=1), "page_size": I("Page size, max 50", default=20)})
async def list_public_booklists(call, args):
    return await call("GET", "/api/booklists/public", params={k: args[k] for k in ("page", "page_size") if k in args})


@tool("list_liked_booklists", "List booklists liked by the current user.")
async def list_liked_booklists(call, args):
    return await call("GET", "/api/booklists/liked")


@tool("get_booklist", "Get a booklist with its books.",
      {"booklist_id": BOOKLIST_ID, "order": S("By time added", enum=["desc", "asc"], default="desc"),
       "page": I("Page number", default=1), "page_size": I("Page size, max 60", default=24)},
      ["booklist_id"])
async def get_booklist(call, args):
    booklist_id = args.get("booklist_id")
    if not booklist_id:
        return _err("booklist_id is required")
    return await call("GET", f"/api/booklist/{booklist_id}", params={k: args[k] for k in ("order", "page", "page_size") if k in args})


BOOKLIST_FIELDS = {
    "name": S("Booklist name"),
    "description": S("Up to 500 chars"),
    "color": S("Booklist color"),
    "is_public": B("Whether the booklist is public", default=False),
}


@tool("create_booklist", "Create a booklist.", dict(BOOKLIST_FIELDS), ["name"])
async def create_booklist(call, args):
    if not args.get("name"):
        return _err("name is required")
    return await call("POST", "/api/booklist/create", json=args)


@tool("update_booklist", "Update a booklist (owner or admin). Only the fields passed are changed.",
      {"booklist_id": BOOKLIST_ID, **BOOKLIST_FIELDS}, ["booklist_id"])
async def update_booklist(call, args):
    booklist_id = args.get("booklist_id")
    if not booklist_id:
        return _err("booklist_id is required")
    body = {k: v for k, v in args.items() if k != "booklist_id"}
    return await call("POST", f"/api/booklist/{booklist_id}/update", json=body)


@tool("delete_booklist", "Delete a booklist (owner or admin); books themselves are kept. Without confirm=true nothing is "
      "deleted and a preview is returned; only confirm after the user explicitly agrees.",
      {"booklist_id": BOOKLIST_ID, "confirm": B("Must be true to actually delete", default=False)}, ["booklist_id"])
async def delete_booklist(call, args):
    booklist_id = args.get("booklist_id")
    if not booklist_id:
        return _err("booklist_id is required")
    if args.get("confirm") is not True:
        preview = await call("GET", f"/api/booklist/{booklist_id}", params={"page_size": 1})
        info = preview.get("booklist") or {}
        return {
            "err": "confirm.required",
            "msg": "Nothing deleted. Show this booklist to the user and, only after they explicitly agree, call again with \"confirm\": true.",
            "booklist": {k: info.get(k) for k in ("id", "name", "book_count", "is_public", "like_count", "is_owner")},
            "preview_err": preview.get("err"),
        }
    return await call("POST", f"/api/booklist/{booklist_id}/delete", json={})


@tool("booklist_add_books", "Add books to a booklist (owner or admin).",
      {"booklist_id": BOOKLIST_ID, "book_ids": A("Book IDs", {"type": "integer"}), "book_id": I("A single book ID")},
      ["booklist_id"])
async def booklist_add_books(call, args):
    booklist_id = args.get("booklist_id")
    if not booklist_id:
        return _err("booklist_id is required")
    body = {k: v for k, v in args.items() if k in ("book_ids", "book_id")}
    return await call("POST", f"/api/booklist/{booklist_id}/books/add", json=body)


@tool("booklist_remove_book", "Remove one book from a booklist (owner or admin).",
      {"booklist_id": BOOKLIST_ID, "book_id": BOOK_ID}, ["booklist_id", "book_id"])
async def booklist_remove_book(call, args):
    booklist_id = args.get("booklist_id")
    book_id = args.get("book_id")
    if not booklist_id or not book_id:
        return _err("booklist_id and book_id are required")
    return await call("POST", f"/api/booklist/{booklist_id}/books/remove", json={"book_id": book_id})


@tool("like_booklist", "Toggle like on a booklist.", {"booklist_id": BOOKLIST_ID}, ["booklist_id"])
async def like_booklist(call, args):
    if not args.get("booklist_id"):
        return _err("booklist_id is required")
    return await call("POST", f"/api/booklist/{args['booklist_id']}/like", json={})


@tool("get_book_booklists", "List the current user's booklists, marking which already contain the book.", {"book_id": BOOK_ID}, ["book_id"])
async def get_book_booklists(call, args):
    if not args.get("book_id"):
        return _err("book_id is required")
    return await call("GET", f"/api/book/{args['book_id']}/booklists")


# ============================================================================
# TTS (MiMo TTS audiobook, admin only)
# ============================================================================

TTS_API_FIELDS = {
    "api_url": S("API endpoint URL"),
    "model_name": S("Model ID, e.g. mimo-v2.5-tts"),
    "api_type": S("API type", enum=["chat_completions", "audio_speech", "custom"]),
    "api_key": S("API key"),
    "auth_type": S("Auth type", enum=["bearer", "basic", "custom"], default="bearer"),
    "voice_name": S("Preset voice ID or audio_speech voice"),
    "voice_desc": S("Custom voice description"),
    "clone_voice": S("Clone voice name"),
}
TTS_API_REQUIRED = ["api_url", "model_name", "api_type", "api_key"]


def _missing(args: Dict[str, Any], required: List[str]) -> Optional[Dict[str, Any]]:
    for name in required:
        if not args.get(name):
            return _err(f"{name} is required")
    return None


@tool("tts_save_config", "Save TTS API configuration (encrypted server-side, admin only).", dict(TTS_API_FIELDS), TTS_API_REQUIRED)
async def tts_save_config(call, args):
    err = _missing(args, TTS_API_REQUIRED)
    if err:
        return err
    return await call("POST", f"{API_TTS_PREFIX}/config", json={k: v for k, v in args.items() if v is not None})


@tool("tts_test_connection", "Test the TTS API connection using the saved configuration (admin only).")
async def tts_test_connection(call, args):
    return await call("POST", f"{API_TTS_PREFIX}/test", json={})


@tool("tts_convert", "Start EPUB-to-audiobook conversion as a background task (admin only).",
      {"book_id": BOOK_ID, **TTS_API_FIELDS}, ["book_id"] + TTS_API_REQUIRED)
async def tts_convert(call, args):
    err = _missing(args, ["book_id"] + TTS_API_REQUIRED)
    if err:
        return err
    return await call("POST", f"{API_TTS_PREFIX}/convert", json={k: v for k, v in args.items() if v is not None})


@tool("tts_progress", "Query current TTS conversion progress (admin only).")
async def tts_progress(call, args):
    return await call("GET", f"{API_TTS_PREFIX}/progress")


@tool("tts_clone_list", "List uploaded clone voices (admin only).")
async def tts_clone_list(call, args):
    return await call("GET", f"{API_TTS_PREFIX}/clone/list")


@tool("tts_clone_delete", "Delete a clone voice by name (admin only).", {"voice_name": S("Clone voice name")}, ["voice_name"])
async def tts_clone_delete(call, args):
    if not args.get("voice_name"):
        return _err("voice_name is required")
    return await call("POST", f"{API_TTS_PREFIX}/clone/delete", json={"voice_name": args["voice_name"]})


@tool("tts_prompt_list", "List saved voice prompt descriptions (admin only).")
async def tts_prompt_list(call, args):
    return await call("GET", f"{API_TTS_PREFIX}/prompt/list")


@tool("tts_prompt_save", "Save a voice prompt description; same name overwrites (admin only).",
      {"name": S("Prompt name"), "desc": S("Voice description text")}, ["name", "desc"])
async def tts_prompt_save(call, args):
    err = _missing(args, ["name", "desc"])
    if err:
        return err
    return await call("POST", f"{API_TTS_PREFIX}/prompt/save", json={"name": args["name"], "desc": args["desc"]})


@tool("tts_prompt_delete", "Delete a voice prompt by name (admin only).", {"name": S("Prompt name")}, ["name"])
async def tts_prompt_delete(call, args):
    if not args.get("name"):
        return _err("name is required")
    return await call("POST", f"{API_TTS_PREFIX}/prompt/delete", json={"name": args["name"]})
