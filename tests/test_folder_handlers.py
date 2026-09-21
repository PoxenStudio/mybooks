#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import json

from tests.test_main import TestWithUserLogin, setUpModule as init, BIDS


def setUpModule():
    init()


class TestFolderHandlers(TestWithUserLogin):
    def post(self, url, body):
        return self.json(url, method="POST", body=json.dumps(body))

    def set_folder(self, bid, folder):
        d = self.post("/api/book/%d/folder" % bid, {"folder": folder})
        self.assertEqual(d["err"], "ok")

    def tree(self):
        return {n["name"]: n for n in self.json("/api/folders")["folders"]}

    def clear_all(self):
        self.post("/api/book/folder", {"ids": BIDS, "folder": ""})

    def setUp(self):
        super().setUp()
        self.clear_all()

    def tearDown(self):
        self.clear_all()
        super().tearDown()

    def test_set_and_tree(self):
        self.set_folder(1, "文学.小说")
        self.set_folder(2, "文学")
        tree = self.tree()
        self.assertEqual(tree["文学"]["count"], 2)
        self.assertEqual(tree["文学"]["children"], [{"name": "小说", "count": 1, "children": []}])
        self.assertEqual(self.json("/api/folders")["root_count"], len(BIDS) - 2)

    def test_invalid(self):
        for folder in ("a.b.c", "a b", "x" * 25):
            d = self.post("/api/book/1/folder", {"folder": folder})
            self.assertEqual(d["err"], "params.folder.invalid")

    def test_books_direct_only(self):
        self.set_folder(1, "文学.小说")
        self.set_folder(2, "文学")
        ids = lambda p: sorted(b["id"] for b in self.json("/api/folder/books?path=" + p)["books"])  # noqa: E731
        self.assertEqual(ids("文学"), [2])
        self.assertEqual(ids("文学.小说"), [1])
        self.assertEqual(ids(""), [3, 4, 5])

    def test_batch(self):
        d = self.post("/api/book/folder", {"ids": [1, 2, 3], "folder": "科技"})
        self.assertEqual(d["count"], 3)
        self.assertEqual(self.tree()["科技"]["count"], 3)
        book = self.json("/api/book/1")["book"]
        self.assertEqual(book["folder"], "科技")

    def test_rename_with_children(self):
        self.set_folder(1, "文学.小说")
        self.set_folder(2, "文学")
        d = self.post("/api/folder/rename", {"path": "文学", "name": "读物"})
        self.assertEqual((d["err"], d["path"]), ("ok", "读物"))
        tree = self.tree()
        self.assertNotIn("文学", tree)
        self.assertEqual(tree["读物"]["count"], 2)
        self.assertEqual(tree["读物"]["children"], [{"name": "小说", "count": 1, "children": []}])

    def test_rename_merge_needs_confirm(self):
        self.set_folder(1, "文学")
        self.set_folder(2, "读物")
        self.set_folder(3, "读物")
        d = self.post("/api/folder/rename", {"path": "文学", "name": "读物"})
        self.assertEqual((d["err"], d["count"], d["target"]), ("folder.exists", 1, "读物"))
        self.assertEqual(self.tree()["文学"]["count"], 1)
        d = self.post("/api/folder/rename", {"path": "文学", "name": "读物", "merge": True})
        self.assertEqual(d["err"], "ok")
        tree = self.tree()
        self.assertNotIn("文学", tree)
        self.assertEqual(tree["读物"]["count"], 3)

    def test_rename_invalid(self):
        self.set_folder(1, "文学")
        d = self.post("/api/folder/rename", {"path": "文学", "name": "a.b"})
        self.assertEqual(d["err"], "params.folder.invalid")
        d = self.post("/api/folder/rename", {"path": "不存在", "name": "x"})
        self.assertEqual(d["err"], "params.folder.not_found")

    def test_candidates(self):
        self.set_folder(1, "文学.小说")
        d = self.json("/api/folder/candidates?level=1")
        self.assertIn({"name": "文学", "count": 1}, d["items"])
        d = self.json("/api/folder/candidates?level=2&parent=文学")
        self.assertEqual(d["items"][0], {"name": "小说", "count": 1})
        self.assertEqual(self.json("/api/folder/candidates?level=1&q=zzzz")["items"], [])
