#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Server-side orchestration for `POST /api/sync/import`
@author: PoxenStudio, 2026-08
"""

import time
from typing import Any, Dict, List, Tuple, TypedDict

from webserver.services.cfi_gen.launcher import (
    CfiAnchor,
    CfiBatchError,
    OnAmbiguous,
    generate_cfis,
)
from webserver.services.sync_service import MyReaderSyncService

# All record ids this pipeline writes get this prefix — makes re-running the
# import idempotent (same id -> same LWW-merged record, see sync_service.py)
ID_PREFIX = "wxread-"

DEFAULT_STYLE = "highlight"
DEFAULT_COLOR = "yellow"
DEFAULT_SOURCE = "wxread"


class ImportAnchor(TypedDict, total=False):
    id: str  # externally-stable id from the source (e.g. WeChat Reading bookmarkId/reviewId)
    text: str  # highlighted/anchor text; omit/empty for chapter- or book-level notes (§4.5)
    chapterHint: str
    note: str  # the user's own thought/comment text, if any
    color: str
    style: str
    createdAt: int  # ms epoch, from the source system
    source: str  # provenance tag; stored as-is, `sync_service.py` does not filter fields (§3.2/§9 Q4)


class ImportResultItem(TypedDict, total=False):
    id: str
    status: str  # "ok" | "no_match" | "ambiguous" | "error"
    cfi: str
    matchCount: int
    ambiguousResolution: str
    degraded: str
    error: str
    reused: bool  # True: cfi was reused from a previous import, CFI generator was not invoked for this anchor (dedup, see module docstring)


class SyncImportError(Exception):
    """A whole-request failure — the CFI batch subprocess failed outright.
    Distinct from a per-anchor `status` in the report."""


def book_hash_for(book_id: int) -> str:
    return f"cloud-{book_id}-epub"


def _load_existing_by_source_id(uid: int, book_hash: str) -> Dict[str, Dict[str, Any]]:
    pulled = MyReaderSyncService.pull(
        uid, since=0, type_="notes", book_hash=book_hash, own=1
    )
    existing = {}
    for note in pulled.get("notes") or []:
        note_id = note.get("id") or ""
        if not note_id.startswith(ID_PREFIX):
            continue  # not ours — e.g. a note the user made natively in MyReader
        if note.get("deleted_at") or note.get("deletedAt"):
            continue  # tombstoned -> treat as if it never existed
        existing[note_id[len(ID_PREFIX) :]] = note
    return existing


def _anchor_unchanged(anchor: ImportAnchor, existing: Dict[str, Any]) -> bool:
    if not existing.get("cfi"):
        return False
    if (anchor.get("text") or "") != (existing.get("text") or ""):
        return False
    if not (anchor.get("text") or ""):
        if (anchor.get("chapterHint") or "") != (existing.get("chapterHint") or ""):
            return False
    return True


def partition_for_dedup(
    uid: int, book_hash: str, anchors: List[ImportAnchor], force: bool = False
) -> Tuple[List[ImportAnchor], List[ImportResultItem]]:
    if force:
        return anchors, []

    existing_by_source_id = _load_existing_by_source_id(uid, book_hash)
    to_resolve: List[ImportAnchor] = []
    reused: List[ImportResultItem] = []
    for anchor in anchors:
        existing = existing_by_source_id.get(anchor["id"])
        if existing is not None and _anchor_unchanged(anchor, existing):
            item: ImportResultItem = {
                "id": anchor["id"],
                "status": "ok",
                "cfi": existing["cfi"],
                "reused": True,
            }
            if existing.get("type") == "bookmark":
                item["degraded"] = "chapter_start"
            reused.append(item)
        else:
            to_resolve.append(anchor)
    return to_resolve, reused


async def preview(
    uid: int,
    book_hash: str,
    epub_path: str,
    anchors: List[ImportAnchor],
    on_ambiguous: OnAmbiguous = "error",
    force: bool = False,
) -> List[ImportResultItem]:
    to_resolve, reused = partition_for_dedup(uid, book_hash, anchors, force=force)

    resolved: List[ImportResultItem] = []
    if to_resolve:
        cfi_anchors: List[CfiAnchor] = [
            {
                "id": a["id"],
                "text": a.get("text") or "",
                "chapterHint": a.get("chapterHint") or "",
            }
            for a in to_resolve
        ]
        try:
            resolved = await generate_cfis(
                epub_path, cfi_anchors, on_ambiguous=on_ambiguous
            )
        except CfiBatchError as e:
            raise SyncImportError(str(e)) from e

    results_by_id = {r["id"]: r for r in (*resolved, *reused)}
    # preserve the caller's original anchor order in the response
    return [results_by_id[a["id"]] for a in anchors if a["id"] in results_by_id]


def build_note_records(
    book_hash: str,
    anchors: List[ImportAnchor],
    cfi_results: List[ImportResultItem],
    uid: int,
) -> List[Dict[str, Any]]:
    results_by_id = {r["id"]: r for r in cfi_results}
    now = int(time.time() * 1000)
    records = []
    for anchor in anchors:
        result = results_by_id.get(anchor["id"])
        if not result or result.get("status") != "ok" or not result.get("cfi"):
            continue
        record_id = (
            anchor["id"]
            if anchor["id"].startswith(ID_PREFIX)
            else f"{ID_PREFIX}{anchor['id']}"
        )
        created_at = anchor.get("createdAt") or now
        records.append(
            {
                "id": record_id,
                "book_hash": book_hash,
                "bookHash": book_hash,
                "uid": uid,
                "type": "bookmark" if result.get("degraded") else "annotation",
                "cfi": result["cfi"],
                "text": anchor.get("text") or "",
                "chapterHint": anchor.get("chapterHint") or "",
                "note": anchor.get("note") or "",
                "style": anchor.get("style") or DEFAULT_STYLE,
                "color": anchor.get("color") or DEFAULT_COLOR,
                "source": anchor.get("source") or DEFAULT_SOURCE,
                "createdAt": created_at,
                "updatedAt": now,
                "deletedAt": None,
                "updated_at": now,
                "deleted_at": None,
            }
        )
    return records


async def commit(
    uid: int,
    book_hash: str,
    anchors: List[ImportAnchor],
    cfi_results: List[ImportResultItem],
) -> Dict[str, Any]:
    records = build_note_records(book_hash, anchors, cfi_results, uid)
    if not records:
        return {"notes": []}
    return await MyReaderSyncService.push(uid, {"notes": records})


async def clear(uid: int, book_hash: str) -> Dict[str, Any]:
    existing_by_source_id = _load_existing_by_source_id(uid, book_hash)
    if not existing_by_source_id:
        return {"notes": []}
    now = int(time.time() * 1000)
    records = [
        {
            "id": f"{ID_PREFIX}{source_id}",
            "book_hash": book_hash,
            "bookHash": book_hash,
            "uid": uid,
            "updatedAt": now,
            "deletedAt": now,
            "updated_at": now,
            "deleted_at": now,
        }
        for source_id in existing_by_source_id
    ]
    return await MyReaderSyncService.push(uid, {"notes": records})
