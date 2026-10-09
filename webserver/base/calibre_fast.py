"""
@PoxenStudio, 2026
"""

import builtins
import contextlib
import inspect
import logging
import os
import time

from webserver import perf
from webserver.base.book_row_cache import BookRowCache
from webserver.services.perf_monitor import PerfMonitor

row_cache = BookRowCache()
_original = None
_supports_verify = False


def _unknown():
    return getattr(builtins, "_", lambda s: s)("Unknown")


def fast_get_data_as_dict(self, prefix=None, authors_as_string=False, ids=None, convert_to_local_tz=True, verify_formats=True, with_paths=True):
    view = self.data
    id_to_row = getattr(view, "_real_map_filtered_id_to_row", None)
    if ids is None or id_to_row is None or not hasattr(view, "tablerow_for_id"):
        return _original(self, prefix=prefix, authors_as_string=authors_as_string, ids=ids, convert_to_local_tz=convert_to_local_tz)

    from calibre.ebooks.metadata import authors_to_string
    from calibre.utils.date import as_local_time

    backend = getattr(self, "backend", self)
    cacheable = prefix is None and not verify_formats and not with_paths
    if prefix is None:
        prefix = backend.library_path
    fdata = backend.custom_column_num_map

    fields = {
        "title", "sort", "authors", "author_sort", "publisher", "rating", "timestamp", "size", "tags", "comments", "series", "series_index", "uuid", "pubdate", "last_modified", "identifiers",
        "languages"
    }.union(set(fdata))
    for x, column in fdata.items():
        if column["datatype"] == "series":
            fields.add(f"{x}_index")

    field_map = self.FIELD_MAP
    ordered = sorted({i for i in ids if i in id_to_row}, key=id_to_row.__getitem__)
    cache = getattr(view, "cache", None)
    read_lock = getattr(cache, "read_lock", None)
    keys = {}
    cached_rows = {}
    wanted = ordered
    cache_enabled = perf.lite_on("LITE_BOOK_CACHE") and hasattr(cache, "all_field_for")
    if cacheable and cache_enabled:
        stamps = cache.all_field_for("last_modified", ordered)
        keys = {i: (i, stamps.get(i), convert_to_local_tz, authors_as_string) for i in ordered}
        for i in ordered:
            row = row_cache.get(keys[i])
            if row is not None:
                cached_rows[i] = row
        wanted = [i for i in ordered if i not in cached_rows]
    elif not cache_enabled and row_cache.stats()["entries"]:
        row_cache.clear()
    data = []
    monitor = PerfMonitor.instance()
    wait_start = time.perf_counter()
    with read_lock if read_lock is not None else contextlib.nullcontext():
        monitor.record_stage("fast.lock_wait", (time.perf_counter() - wait_start) * 1000)
        fields_start = time.perf_counter()
        for db_id in wanted:
            x = {}
            try:
                record = view.tablerow_for_id(db_id)
                for field in fields:
                    x[field] = record[field_map[field]]
            except IndexError:
                logging.debug("book %s removed while listing, skipped", db_id)
                continue
            if convert_to_local_tz:
                for tf in ("timestamp", "pubdate", "last_modified"):
                    x[tf] = as_local_time(x[tf])

            data.append(x)
            x["id"] = db_id
            x["formats"] = []
            isbn = self.isbn(db_id, index_is_id=True)
            x["isbn"] = isbn or ""
            if not x["authors"]:
                x["authors"] = _unknown()
            x["authors"] = [i.replace("|", ",") for i in x["authors"].split(",")]
            if authors_as_string:
                x["authors"] = authors_to_string(x["authors"])
            x["tags"] = [i.replace("|", ",").strip() for i in x["tags"].split(",")] if x["tags"] else []
            path = os.path.join(prefix, self.path(db_id, index_is_id=True))
            x["cover"] = os.path.join(path, "cover.jpg")
            if not record[field_map["cover"]]:
                x["cover"] = None
    monitor.record_stage("fast.fields", (time.perf_counter() - fields_start) * 1000)
    formats_start = time.perf_counter()
    for x in data:
        db_id = x["id"]
        if _supports_verify:
            formats = self.formats(db_id, index_is_id=True, verify_formats=verify_formats)
        else:
            formats = self.formats(db_id, index_is_id=True)
        if formats:
            for fmt in formats.split(","):
                if with_paths:
                    path = self.format_abspath(db_id, fmt, index_is_id=True)
                    if path is None:
                        continue
                    if prefix != self.library_path:
                        path = os.path.relpath(path, self.library_path)
                        path = os.path.join(prefix, path)
                    x["formats"].append(path)
                    x["fmt_" + fmt.lower()] = path
            x["available_formats"] = [i.upper() for i in formats.split(",")]
    monitor.record_stage("fast.formats", (time.perf_counter() - formats_start) * 1000)
    if not keys:
        return data
    max_items = int(perf.CONF.get("LITE_BOOK_CACHE_SIZE", 2000))
    max_bytes = int(perf.CONF.get("LITE_BOOK_CACHE_MB", 32)) * 1024 * 1024
    built = {}
    for x in data:
        built[x["id"]] = x
        row_cache.put(keys[x["id"]], x, max_items, max_bytes)
    return [cached_rows[i] if i in cached_rows else built[i] for i in ordered]


def install(library_cls):
    global _original, _supports_verify
    if _original is not None:
        return
    _original = library_cls.get_data_as_dict
    _supports_verify = "verify_formats" in inspect.signature(library_cls.formats).parameters
    library_cls.get_data_as_dict = fast_get_data_as_dict
    logging.info("Installed fast get_data_as_dict (verify_formats supported: %s)", _supports_verify)


def list_kwargs():
    if _original is None:
        return {}
    return {"verify_formats": False, "with_paths": False}
