#!/usr/bin/env python3

import datetime
import os
import sys
import types
import unittest
from unittest import mock

from webserver.base import calibre_fast

FIELDS = [
    "id", "title", "sort", "authors", "author_sort", "publisher", "rating", "timestamp", "size", "tags", "comments", "series", "series_index", "uuid", "pubdate", "last_modified", "identifiers",
    "languages", "cover"
]


class FakeRow:
    def __init__(self, values):
        self.values = values

    def __getitem__(self, idx):
        return self.values[idx]


class FakeView:
    def __init__(self, rows, order):
        self.rows = rows
        self._real_map_filtered_id_to_row = {book_id: i for i, book_id in enumerate(order)}

    def __iter__(self):
        for book_id in sorted(self._real_map_filtered_id_to_row, key=self._real_map_filtered_id_to_row.get):
            yield self.tablerow_for_id(book_id)

    def tablerow_for_id(self, book_id):
        return FakeRow(self.rows[book_id])


class FakeDB:
    library_path = "/lib"
    FIELD_MAP = {name: i for i, name in enumerate(FIELDS)}
    custom_column_num_map = {}

    def __init__(self, order):
        now = datetime.datetime(2020, 1, 2)
        rows = {}
        for book_id in range(1, 8):
            rows[book_id] = [
                book_id, "t%d" % book_id, "s", "A|b,C" if book_id % 2 else "", "as", "pub", 8, now, 10, "x,y|z" if book_id % 3 else "", "c", None, 1.0, "u", now, now, {}, "zho", book_id != 4
            ]
        self.data = FakeView(rows, order)
        self.backend = self
        self.verify_calls = []

    def isbn(self, book_id, index_is_id=True):
        return None

    def path(self, book_id, index_is_id=True):
        return "a/b (%d)" % book_id

    def formats(self, book_id, index_is_id=True, verify_formats=True):
        self.verify_calls.append(verify_formats)
        return "epub,pdf" if book_id != 2 else ""

    def format_abspath(self, book_id, fmt, index_is_id=True):
        return None if (book_id == 3 and fmt == "pdf") else "/lib/a/b (%d)/f.%s" % (book_id, fmt)


def reference(self, ids=None, convert_to_local_tz=True):
    data = []
    for record in self.data:
        db_id = record[self.FIELD_MAP["id"]]
        if ids is not None and db_id not in ids:
            continue
        x = {}
        for field in FIELDS[1:-1]:
            x[field] = record[self.FIELD_MAP[field]]
        data.append(x)
        x["id"] = db_id
        x["formats"] = []
        x["isbn"] = self.isbn(db_id) or ""
        if not x["authors"]:
            x["authors"] = "Unknown"
        x["authors"] = [i.replace("|", ",") for i in x["authors"].split(",")]
        x["tags"] = [i.replace("|", ",").strip() for i in x["tags"].split(",")] if x["tags"] else []
        x["cover"] = os.path.join("/lib", self.path(db_id), "cover.jpg")
        if not record[self.FIELD_MAP["cover"]]:
            x["cover"] = None
        formats = self.formats(db_id)
        if formats:
            for fmt in formats.split(","):
                path = self.format_abspath(db_id, fmt)
                if path is None:
                    continue
                x["formats"].append(path)
                x["fmt_" + fmt.lower()] = path
            x["available_formats"] = [i.upper() for i in formats.split(",")]
    return data


class TestFastGetDataAsDict(unittest.TestCase):

    def setUp(self):
        stub_meta = types.ModuleType("calibre.ebooks.metadata")
        stub_meta.authors_to_string = lambda a: " & ".join(a)
        stub_date = types.ModuleType("calibre.utils.date")
        stub_date.as_local_time = lambda d: d
        modules = {
            "calibre": types.ModuleType("calibre"),
            "calibre.ebooks": types.ModuleType("calibre.ebooks"),
            "calibre.ebooks.metadata": stub_meta,
            "calibre.utils": types.ModuleType("calibre.utils"),
            "calibre.utils.date": stub_date,
        }
        patcher = mock.patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.original_state = (calibre_fast._original, calibre_fast._supports_verify)
        calibre_fast._original = lambda self, **kw: reference(self, ids=kw.get("ids"))
        calibre_fast._supports_verify = True
        self.addCleanup(lambda: setattr(calibre_fast, "_original", self.original_state[0]))
        self.addCleanup(lambda: setattr(calibre_fast, "_supports_verify", self.original_state[1]))
        self.db = FakeDB([5, 3, 7, 1, 2, 6, 4])

    def test_matches_reference_for_ids(self):
        for ids in ([3], [7, 1, 5], {2, 4, 6}, [99], [], [1, 1, 3], list(range(1, 8))):
            expected = reference(self.db, ids=ids)
            self.assertEqual(calibre_fast.fast_get_data_as_dict(self.db, ids=ids), expected, ids)

    def test_order_follows_view_not_ids(self):
        books = calibre_fast.fast_get_data_as_dict(self.db, ids=[1, 5, 7])
        self.assertEqual([b["id"] for b in books], [5, 7, 1])

    def test_unknown_ids_skipped(self):
        self.assertEqual(calibre_fast.fast_get_data_as_dict(self.db, ids=[100, "3"]), [])

    def test_book_removed_after_snapshot_is_skipped(self):
        view = self.db.data
        real = view.tablerow_for_id

        def vanishing(book_id):
            if book_id == 3:
                raise IndexError("No book with id 3 present")
            return real(book_id)

        view.tablerow_for_id = vanishing
        books = calibre_fast.fast_get_data_as_dict(self.db, ids=[5, 3, 7])
        self.assertEqual([b["id"] for b in books], [5, 7])

    def test_ids_none_uses_original(self):
        self.assertEqual(len(calibre_fast.fast_get_data_as_dict(self.db)), 7)

    def test_list_mode_skips_verification_and_paths(self):
        books = calibre_fast.fast_get_data_as_dict(self.db, ids=[3], verify_formats=False, with_paths=False)
        self.assertEqual(self.db.verify_calls, [False])
        self.assertEqual(books[0]["available_formats"], ["EPUB", "PDF"])
        self.assertEqual(books[0]["formats"], [])
        self.assertNotIn("fmt_epub", books[0])

    def test_default_mode_verifies(self):
        calibre_fast.fast_get_data_as_dict(self.db, ids=[3])
        self.assertEqual(self.db.verify_calls, [True])

    def test_read_lock_taken_once_for_the_batch(self):
        entered = []

        class CountingLock:
            def __enter__(self):
                entered.append(1)

            def __exit__(self, *exc):
                return False

        self.db.data.cache = types.SimpleNamespace(read_lock=CountingLock())
        books = calibre_fast.fast_get_data_as_dict(self.db, ids=[1, 2, 3, 5])
        self.assertEqual(len(books), 4)
        self.assertEqual(len(entered), 1)

    def test_list_kwargs_only_when_installed(self):
        calibre_fast._original = None
        self.assertEqual(calibre_fast.list_kwargs(), {})
        calibre_fast._original = object()
        self.assertEqual(calibre_fast.list_kwargs(), {"verify_formats": False, "with_paths": False})


class TestRowCache(unittest.TestCase):

    def setUp(self):
        stub_meta = types.ModuleType("calibre.ebooks.metadata")
        stub_meta.authors_to_string = lambda a: " & ".join(a)
        stub_date = types.ModuleType("calibre.utils.date")
        stub_date.as_local_time = lambda d: d
        modules = {
            "calibre": types.ModuleType("calibre"),
            "calibre.ebooks": types.ModuleType("calibre.ebooks"),
            "calibre.ebooks.metadata": stub_meta,
            "calibre.utils": types.ModuleType("calibre.utils"),
            "calibre.utils.date": stub_date,
        }
        patcher = mock.patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        saved = (calibre_fast._original, calibre_fast._supports_verify)
        calibre_fast._original = lambda self, **kw: reference(self, ids=kw.get("ids"))
        calibre_fast._supports_verify = True
        self.addCleanup(lambda: setattr(calibre_fast, "_original", saved[0]))
        self.addCleanup(lambda: setattr(calibre_fast, "_supports_verify", saved[1]))
        calibre_fast.row_cache.clear()
        calibre_fast.row_cache.hits = calibre_fast.row_cache.misses = 0
        self.addCleanup(calibre_fast.row_cache.clear)
        self.db = FakeDB([5, 3, 7, 1, 2, 6, 4])
        self.stamps = {i: datetime.datetime(2020, 1, i) for i in range(1, 8)}
        self.db.data.cache = types.SimpleNamespace(read_lock=None, all_field_for=lambda field, ids: {i: self.stamps[i] for i in ids})
        conf = mock.patch.dict(calibre_fast.perf.CONF, {"PERFORMANCE_MODE": "lite", "LITE_GROUP_LISTING": True, "LITE_BOOK_CACHE_SIZE": 2000, "LITE_BOOK_CACHE_MB": 32})
        conf.start()
        self.addCleanup(conf.stop)

    def fetch(self, ids, **kw):
        return calibre_fast.fast_get_data_as_dict(self.db, ids=ids, verify_formats=False, with_paths=False, **kw)

    def test_second_call_served_from_cache(self):
        first = self.fetch([1, 3, 5])
        calls = len(self.db.verify_calls)
        second = self.fetch([1, 3, 5])
        self.assertEqual(first, second)
        self.assertEqual(len(self.db.verify_calls), calls)
        self.assertEqual(calibre_fast.row_cache.stats()["hits"], 3)

    def test_mixed_hits_and_misses_keep_order_and_content(self):
        self.fetch([1, 3])
        mixed = self.fetch([1, 3, 5, 7])
        calibre_fast.row_cache.clear()
        self.assertEqual(mixed, self.fetch([1, 3, 5, 7]))
        self.assertEqual([b["id"] for b in mixed], [5, 3, 7, 1])

    def test_returned_rows_are_isolated_from_cache(self):
        first = self.fetch([3])
        first[0]["authors"].append("mutated")
        first[0]["title"] = "changed"
        again = self.fetch([3])
        self.assertNotIn("mutated", again[0]["authors"])
        self.assertEqual(again[0]["title"], "t3")

    def test_last_modified_change_invalidates(self):
        self.fetch([3])
        self.stamps[3] = datetime.datetime(2021, 1, 1)
        self.fetch([3])
        self.assertEqual(calibre_fast.row_cache.stats()["hits"], 0)

    def test_only_list_mode_is_cached(self):
        calibre_fast.fast_get_data_as_dict(self.db, ids=[3])
        calibre_fast.fast_get_data_as_dict(self.db, ids=[3])
        self.assertEqual(calibre_fast.row_cache.stats()["entries"], 0)

    def test_detail_style_call_keeps_cached_rows(self):
        self.fetch([1, 3])
        calibre_fast.fast_get_data_as_dict(self.db, ids=[3])
        calibre_fast.fast_get_data_as_dict(self.db, ids=[3], verify_formats=True, with_paths=False)
        calibre_fast.fast_get_data_as_dict(self.db, ids=[3], verify_formats=False, with_paths=True)
        self.assertEqual(calibre_fast.row_cache.stats()["entries"], 2)
        hits = calibre_fast.row_cache.stats()["hits"]
        self.fetch([1, 3])
        self.assertEqual(calibre_fast.row_cache.stats()["hits"], hits + 2)

    def test_disabled_outside_lite(self):
        with mock.patch.dict(calibre_fast.perf.CONF, {"PERFORMANCE_MODE": "normal"}):
            self.fetch([1, 3])
            self.fetch([1, 3])
        self.assertEqual(calibre_fast.row_cache.stats()["entries"], 0)

    def test_individual_switch_off(self):
        with mock.patch.dict(calibre_fast.perf.CONF, {"LITE_GROUP_LISTING": False}):
            self.fetch([1, 3])
        self.assertEqual(calibre_fast.row_cache.stats()["entries"], 0)

    def test_turning_lite_off_releases_memory(self):
        self.fetch([1, 3])
        self.assertEqual(calibre_fast.row_cache.stats()["entries"], 2)
        with mock.patch.dict(calibre_fast.perf.CONF, {"PERFORMANCE_MODE": "normal"}):
            self.fetch([1])
        self.assertEqual(calibre_fast.row_cache.stats()["entries"], 0)

    def test_lru_evicts_least_recently_used(self):
        with mock.patch.dict(calibre_fast.perf.CONF, {"LITE_BOOK_CACHE_SIZE": 3}):
            self.fetch([3])
            self.fetch([1])
            self.fetch([2])
            self.fetch([3])
            self.fetch([4])
            self.assertEqual(calibre_fast.row_cache.stats()["entries"], 3)
            hits = calibre_fast.row_cache.stats()["hits"]
            self.fetch([1])
            self.assertEqual(calibre_fast.row_cache.stats()["hits"], hits)
            self.fetch([3])
            self.assertEqual(calibre_fast.row_cache.stats()["hits"], hits + 1)

    def test_byte_cap_skips_oversized_rows(self):
        with mock.patch.dict(calibre_fast.perf.CONF, {"LITE_BOOK_CACHE_MB": 0}):
            self.fetch([1, 3])
        self.assertEqual(calibre_fast.row_cache.stats()["entries"], 0)

    def test_byte_total_stays_under_cap(self):
        calibre_fast.row_cache.put("a", {"title": "x" * 3000}, 100, 10000)
        calibre_fast.row_cache.put("b", {"title": "y" * 3000}, 100, 10000)
        calibre_fast.row_cache.put("c", {"title": "z" * 3000}, 100, 10000)
        stats = calibre_fast.row_cache.stats()
        self.assertLessEqual(stats["bytes"], 10000)
        self.assertEqual(stats["entries"], 2)


try:
    from calibre.db.legacy import LibraryDatabase
except Exception:
    LibraryDatabase = None

LIBRARY = os.path.join(os.path.dirname(__file__), "library")


@unittest.skipIf(LibraryDatabase is None, "calibre not available")
class TestAgainstRealCalibre(unittest.TestCase):

    def setUp(self):
        import shutil
        import tempfile

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(LIBRARY, os.path.join(tmp, "lib"))
        self.db = LibraryDatabase(os.path.join(tmp, "lib"))
        self.addCleanup(self.db.close)
        self.original = LibraryDatabase.get_data_as_dict
        if calibre_fast._original is None:
            calibre_fast._original = self.original

    def test_equivalent_to_original(self):
        all_ids = sorted(self.db.all_ids())
        self.assertTrue(all_ids)
        for ids in (all_ids[:1], all_ids[:50], all_ids[::-1][:20], all_ids[-3:] + [999999]):
            self.assertEqual(calibre_fast.fast_get_data_as_dict(self.db, ids=ids), calibre_fast._original(self.db, ids=ids))

    def test_row_cache_matches_uncached_output(self):
        ids = sorted(self.db.all_ids())[:30]
        calibre_fast.row_cache.clear()
        with mock.patch.dict(calibre_fast.perf.CONF, {"PERFORMANCE_MODE": "lite", "LITE_GROUP_LISTING": True}):
            first = calibre_fast.fast_get_data_as_dict(self.db, ids=ids, verify_formats=False, with_paths=False)
            second = calibre_fast.fast_get_data_as_dict(self.db, ids=ids, verify_formats=False, with_paths=False)
        calibre_fast.row_cache.clear()
        plain = calibre_fast.fast_get_data_as_dict(self.db, ids=ids, verify_formats=False, with_paths=False)
        self.assertEqual(first, plain)
        self.assertEqual(second, plain)

    def test_row_cache_follows_real_metadata_writes(self):
        import io

        from calibre.ebooks.metadata.book.base import Metadata
        from PIL import Image

        out = io.BytesIO()
        Image.new("RGB", (60, 80), "red").save(out, "JPEG")
        bid = sorted(self.db.all_ids())[0]
        api = self.db.new_api

        def fetch():
            with mock.patch.dict(calibre_fast.perf.CONF, {"PERFORMANCE_MODE": "lite", "LITE_GROUP_LISTING": True}):
                return calibre_fast.fast_get_data_as_dict(self.db, ids=[bid], verify_formats=False, with_paths=False)[0]

        calibre_fast.row_cache.clear()
        fetch()
        api.set_field("publisher", {bid: "出版社-新"})
        self.assertEqual(fetch()["publisher"], "出版社-新")
        api.set_metadata(bid, Metadata("新书名-集成", ["新作者"]))
        self.assertEqual(fetch()["title"], "新书名-集成")
        api.set_cover({bid: None})
        self.assertIsNone(fetch()["cover"])
        api.set_cover({bid: out.getvalue()})
        self.assertIsNotNone(fetch()["cover"])
        calibre_fast.row_cache.clear()

    def test_unverified_keeps_available_formats(self):
        ids = sorted(self.db.all_ids())[:20]
        fast = calibre_fast.fast_get_data_as_dict(self.db, ids=ids, verify_formats=False, with_paths=False)
        full = calibre_fast._original(self.db, ids=ids)
        self.assertEqual([b["id"] for b in fast], [b["id"] for b in full])
        self.assertEqual([b.get("available_formats") for b in fast], [b.get("available_formats") for b in full])


if __name__ == "__main__":
    unittest.main()
