#!/usr/bin/env python3

import asyncio
import os
import tempfile
import unittest
from unittest import mock

from webserver.handlers import book as book_module
from webserver.handlers.book import BookDelete, BookUpload


class FakeMeta:
    authors = ["a"]
    title = "t"


def make_upload():
    handler = object.__new__(BookUpload)
    handler.add_msg = mock.Mock()
    return handler


class TestResolveSameTitle(unittest.TestCase):

    def setUp(self):
        self.handler = make_upload()
        self.db = mock.Mock()
        self.handler.calibre_db = self.db

    def meta(self, book_id, authors, formats, book_type=0):
        info = mock.MagicMock()
        info.get.side_effect = lambda key, default=None: {"id": book_id, "authors": authors, book_module.CALIBRE_COLUMN_BOOK_TYPE: book_type}.get(key, default)
        info.formats = formats
        return info

    def resolve(self, books, metas):
        self.db.books_with_same_title.return_value = books
        self.db.get_metadata.side_effect = lambda i, **kw: metas[i]
        mi = FakeMeta()
        mi.authors = ["a"]
        return self.handler._resolve_same_title(mi, "epub")

    def test_no_candidates_is_new_with_translators(self):
        self.assertEqual(self.resolve([], {}), ("new", True))

    def test_same_author_other_format_adds_format(self):
        self.assertEqual(self.resolve([7], {7: self.meta(7, ["a"], ["PDF"])}), ("existing", 7))

    def test_same_format_is_samebook(self):
        kind, payload = self.resolve([7], {7: self.meta(7, ["a"], ["EPUB"])})
        self.assertEqual(kind, "samebook")
        self.assertEqual(payload["book_id"], 7)

    def test_different_author_is_new_without_translators(self):
        self.assertEqual(self.resolve([7], {7: self.meta(7, ["b"], ["PDF"])}), ("new", False))

    def test_physical_book_skipped(self):
        self.assertEqual(self.resolve([7], {7: self.meta(7, ["a"], ["PDF"], book_type=book_module.BOOK_TYPE_PHYSICAL)}), ("new", False))


class TestImportFlow(unittest.TestCase):

    def run_flow(self, resolve_result, translators):
        handler = make_upload()
        fd, path = tempfile.mkstemp()
        os.close(fd)
        calls = []

        async def run_calibre(func, *args, **kwargs):
            calls.append(func)
            if func == handler._resolve_same_title:
                return resolve_result
            return None

        async def add_new(mi, fpaths, fmt):
            calls.append("add_new")
            return 42

        async def threadpool(func, *args, **kwargs):
            return (None, path, FakeMeta(), translators)

        handler.run_calibre_async = run_calibre
        handler._add_new_book_async = add_new
        handler.calibre_db = mock.Mock()
        handler.calibre_db_cache = mock.Mock()
        with mock.patch.object(book_module.utils, "run_in_threadpool", threadpool):
            result = asyncio.run(handler._import_uploaded_book("a.epub", b"x", "epub"))
        return result, calls, path, handler

    def test_new_book_sets_translators_and_cleans_file(self):
        result, calls, path, handler = self.run_flow(("new", True), ["tr"])
        self.assertEqual(result, {"err": "ok", "book_id": 42})
        self.assertIn(handler.calibre_db_cache.set_field, calls)
        self.assertFalse(os.path.exists(path))

    def test_new_book_without_translators_flag(self):
        _, calls, _, handler = self.run_flow(("new", False), ["tr"])
        self.assertNotIn(handler.calibre_db_cache.set_field, calls)

    def test_existing_book_adds_format(self):
        result, calls, _, handler = self.run_flow(("existing", 9), [])
        self.assertEqual(result["book_id"], 9)
        self.assertIn(handler.calibre_db.add_format, calls)

    def test_samebook_returned_and_file_removed(self):
        response = {"err": "samebook", "book_id": 3}
        result, _, path, _ = self.run_flow(("samebook", response), [])
        self.assertEqual(result, response)
        self.assertFalse(os.path.exists(path))


class TestUploadSlot(unittest.TestCase):

    def test_slot_limits_concurrency(self):
        BookUpload._upload_slots = None
        running, peak = [0], [0]

        async def job():
            async with BookUpload._upload_slot():
                running[0] += 1
                peak[0] = max(peak[0], running[0])
                await asyncio.sleep(0.01)
                running[0] -= 1

        async def main():
            await asyncio.gather(*(job() for _ in range(4)))

        asyncio.run(main())
        BookUpload._upload_slots = None
        self.assertEqual(peak[0], 1)


class TestDeleteDedupe(unittest.TestCase):

    def test_concurrent_delete_runs_once(self):
        BookDelete._deleting.clear()
        handler = object.__new__(BookDelete)
        handler.request = mock.Mock(headers={})
        handler.set_header = mock.Mock()
        handler.write = mock.Mock()
        handler.finish = mock.Mock()
        user = mock.Mock()
        user.can_edit.return_value = True
        user.can_delete.return_value = True
        handler.current_user = user
        handler.is_admin = lambda: True
        handler.get_book_async = mock.AsyncMock(return_value={"id": 5, "title": "t", "collector": {"id": 1}})
        started = asyncio.Event()
        calls = []

        async def delete(book_id, title):
            calls.append(book_id)
            started.set()
            await asyncio.sleep(0.02)
            return True

        handler.delete_book_async = delete

        async def threadpool(func, *args, **kwargs):
            return None

        async def main():
            with mock.patch.object(book_module.utils, "run_in_threadpool", threadpool):
                await asyncio.gather(handler.post("5"), handler.post("5"))

        asyncio.run(main())
        self.assertEqual(calls, [5])
        self.assertEqual(BookDelete._deleting, set())


if __name__ == "__main__":
    unittest.main()
