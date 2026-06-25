#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import asyncio
import json
import os
import shutil
import tempfile
import unittest

from tests.test_main import TestWithUserLogin, setUpModule as init, main
from webserver.services.sync_service import MyReaderSyncService


def setUpModule():
    init()


class TestSyncServiceStorage(unittest.TestCase):
    """Unit tests against sync_service directly (no HTTP), file storage isolated to a tmp dir."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()
        main.CONF["MYREADER_SYNC_PATH"] = self._tmp_dir
        MyReaderSyncService._locks.clear()

    def tearDown(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def test_push_then_pull_roundtrip(self):
        async def run():
            payload = {
                "books": [{
                    "id": "b1", "book_hash": "hash1", "updated_at": 1000, "deleted_at": None,
                    "title": "Title 1", "author": "Author 1", "format": "EPUB",
                }],
            }
            result = await MyReaderSyncService.push(1, payload)
            self.assertEqual(len(result["books"]), 1)
            self.assertEqual(result["books"][0]["title"], "Title 1")

            pulled = MyReaderSyncService.pull(1, since=0, type_="books")
            self.assertEqual(len(pulled["books"]), 1)
            self.assertIsNone(pulled["notes"])
            self.assertIsNone(pulled["configs"])

            # records not newer than `since` are excluded
            pulled_none = MyReaderSyncService.pull(1, since=1000, type_="books")
            self.assertEqual(pulled_none["books"], [])

        asyncio.get_event_loop().run_until_complete(run())

    def test_each_book_gets_its_own_directory_and_files(self):
        async def run():
            await MyReaderSyncService.push(1, {
                "books": [{"id": "b1", "book_hash": "hashA", "updated_at": 1, "title": "A"}],
                "configs": [{"id": "c1", "book_hash": "hashA", "updated_at": 1, "progress": [1, 10]}],
                "notes": [{"id": "n1", "book_hash": "hashA", "updated_at": 1, "note": "hi"}],
            })
            book_dir = MyReaderSyncService._book_dir(1, "hashA")
            self.assertTrue(os.path.isfile(os.path.join(book_dir, "books.json")))
            self.assertTrue(os.path.isfile(os.path.join(book_dir, "configs.json")))
            self.assertTrue(os.path.isfile(os.path.join(book_dir, "notes.json")))

            # books/configs are stored as a plain record, not wrapped/keyed by book_hash
            with open(os.path.join(book_dir, "books.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["title"], "A")
            # notes.json holds a dict keyed by note id (a book can have many notes)
            with open(os.path.join(book_dir, "notes.json"), encoding="utf-8") as f:
                self.assertIn("n1", json.load(f))

        asyncio.get_event_loop().run_until_complete(run())

    def test_pull_scans_all_book_directories(self):
        async def run():
            await MyReaderSyncService.push(1, {"books": [{"id": "b1", "book_hash": "hashA", "updated_at": 1}]})
            await MyReaderSyncService.push(1, {"books": [{"id": "b2", "book_hash": "hashB", "updated_at": 1}]})
            pulled = MyReaderSyncService.pull(1, since=0, type_="books")
            self.assertEqual({r["book_hash"] for r in pulled["books"]}, {"hashA", "hashB"})

            # filtering by `book` only reads that book's directory
            pulled_one = MyReaderSyncService.pull(1, since=0, type_="books", book_hash="hashA")
            self.assertEqual([r["book_hash"] for r in pulled_one["books"]], ["hashA"])

        asyncio.get_event_loop().run_until_complete(run())

    def test_last_write_wins_merge(self):
        async def run():
            await MyReaderSyncService.push(1, {"configs": [
                {"id": "c1", "book_hash": "hashA", "updated_at": 100, "progress": [1, 100]},
            ]})
            # stale update (lower updated_at) must be ignored
            stale = await MyReaderSyncService.push(1, {"configs": [
                {"id": "c1", "book_hash": "hashA", "updated_at": 50, "progress": [99, 100]},
            ]})
            self.assertEqual(stale["configs"][0]["progress"], [1, 100])

            # newer update overwrites
            fresh = await MyReaderSyncService.push(1, {"configs": [
                {"id": "c1", "book_hash": "hashA", "updated_at": 200, "progress": [5, 100]},
            ]})
            self.assertEqual(fresh["configs"][0]["progress"], [5, 100])

        asyncio.get_event_loop().run_until_complete(run())

    def test_multiple_notes_per_book(self):
        async def run():
            await MyReaderSyncService.push(1, {"notes": [
                {"id": "n1", "book_hash": "hashB", "updated_at": 10, "note": "first"},
                {"id": "n2", "book_hash": "hashB", "updated_at": 10, "note": "second"},
            ]})
            pulled = MyReaderSyncService.pull(1, since=0, type_="notes")
            self.assertEqual({r["id"] for r in pulled["notes"]}, {"n1", "n2"})

        asyncio.get_event_loop().run_until_complete(run())

    def test_tombstone_visible_via_deleted_at(self):
        async def run():
            await MyReaderSyncService.push(1, {"notes": [
                {"id": "n1", "book_hash": "hashB", "updated_at": 10, "deleted_at": None, "note": "hi"},
            ]})
            await MyReaderSyncService.push(1, {"notes": [
                {"id": "n1", "book_hash": "hashB", "updated_at": 20, "deleted_at": 20, "note": "hi"},
            ]})
            pulled = MyReaderSyncService.pull(1, since=15, type_="notes")
            self.assertEqual(len(pulled["notes"]), 1)
            self.assertEqual(pulled["notes"][0]["deleted_at"], 20)

        asyncio.get_event_loop().run_until_complete(run())

    def test_per_user_isolation(self):
        async def run():
            await MyReaderSyncService.push(1, {"books": [{"id": "b1", "book_hash": "h1", "updated_at": 1}]})
            await MyReaderSyncService.push(2, {"books": [{"id": "b2", "book_hash": "h2", "updated_at": 1}]})
            self.assertEqual(len(MyReaderSyncService.pull(1, 0, "books")["books"]), 1)
            self.assertEqual(len(MyReaderSyncService.pull(2, 0, "books")["books"]), 1)

        asyncio.get_event_loop().run_until_complete(run())

    def test_concurrent_push_same_user_is_serialized(self):
        """push() must wait for an in-flight push for the same uid before reading/writing."""
        async def run():
            lock = MyReaderSyncService._get_lock(1)
            await lock.acquire()
            try:
                task = asyncio.ensure_future(MyReaderSyncService.push(1, {
                    "books": [{"id": "b1", "book_hash": "h1", "updated_at": 1}],
                }))
                await asyncio.sleep(0.05)
                self.assertFalse(task.done(), "push() must block while another holder owns the per-uid lock")
            finally:
                lock.release()

            result = await task
            self.assertEqual(len(result["books"]), 1)

        asyncio.get_event_loop().run_until_complete(run())

    def test_concurrent_push_different_books_does_not_lose_updates(self):
        """Two concurrent pushes for the same user touching different books must both land."""
        async def run():
            await asyncio.gather(
                MyReaderSyncService.push(1, {"books": [{"id": "b1", "book_hash": "h1", "updated_at": 1}]}),
                MyReaderSyncService.push(1, {"books": [{"id": "b2", "book_hash": "h2", "updated_at": 1}]}),
            )
            pulled = MyReaderSyncService.pull(1, since=0, type_="books")
            self.assertEqual({r["book_hash"] for r in pulled["books"]}, {"h1", "h2"})

        asyncio.get_event_loop().run_until_complete(run())


class TestSyncHandler(TestWithUserLogin):
    """Integration tests for GET/POST /api/sync over real HTTP, mocked user_id=1."""

    def setUp(self):
        super().setUp()
        self._tmp_dir = tempfile.mkdtemp()
        main.CONF["MYREADER_SYNC_PATH"] = self._tmp_dir
        main.CONF["ENABLE_DATA_SYNC"] = True
        MyReaderSyncService._locks.clear()

    def tearDown(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)
        super().tearDown()

    def test_get_requires_since(self):
        d = self.json("/api/sync")
        self.assertEqual(d["err"], "params.invalid")

    def test_post_then_get(self):
        body = json.dumps({"books": [{
            "id": "b1", "book_hash": "hash1", "updated_at": 1000, "title": "T", "author": "A", "format": "EPUB",
        }]})
        d = self.json("/api/sync", method="POST", body=body)
        self.assertEqual(len(d["books"]), 1)

        d = self.json("/api/sync?since=0&type=books")
        self.assertEqual(len(d["books"]), 1)
        self.assertEqual(d["books"][0]["book_hash"], "hash1")

    def test_disabled_feature_blocks_requests(self):
        main.CONF["ENABLE_DATA_SYNC"] = False
        d = self.json("/api/sync?since=0")
        self.assertEqual(d["err"], "sync.disabled")
