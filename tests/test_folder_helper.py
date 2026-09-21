import unittest
from unittest import mock

from webserver.base import folder_helper as fh


class TestNormalize(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(fh.normalize_folder("文学"), "文学")
        self.assertEqual(fh.normalize_folder(" 文学.小说 "), "文学.小说")
        self.assertEqual(fh.normalize_folder("Sci Fi".replace(" ", "")), "SciFi")

    def test_clear(self):
        for raw in ("", "  ", "清除", "Clear", None):
            self.assertEqual(fh.normalize_folder(raw), "")

    def test_invalid(self):
        for raw in ("a.b.c", "a..b", ".a", "a.", "a b", "a,b", "a/b", "a#b", "a_b", "文学。", "x" * 25):
            with self.assertRaises(ValueError, msg=raw):
                fh.normalize_folder(raw)

    def test_depth_follows_constant(self):
        with mock.patch.object(fh, "MAX_DEPTH", 3):
            self.assertEqual(fh.normalize_folder("a.b.c"), "a.b.c")
            with self.assertRaises(ValueError):
                fh.normalize_folder("a.b.c.d")

    def test_max_length(self):
        self.assertEqual(fh.normalize_folder("x" * 24), "x" * 24)

    def test_segment_rejects_dot(self):
        with self.assertRaises(ValueError):
            fh.normalize_segment("a.b")


class TestTree(unittest.TestCase):
    def test_build_tree(self):
        counts = {"文学": 2, "文学.小说": 3, "文学.诗歌": 1, "科技": 4, "空": 0}
        tree = fh.build_tree(counts)
        self.assertEqual([n["name"] for n in tree], ["文学", "科技"])
        self.assertEqual(tree[0]["count"], 6)
        self.assertEqual(tree[0]["children"], [{"name": "小说", "count": 3, "children": []}, {"name": "诗歌", "count": 1, "children": []}])
        self.assertEqual(tree[1]["children"], [])

    def test_deeper_tree_and_find_children(self):
        tree = fh.build_tree({"a": 1, "a.b": 2, "a.b.c": 3})
        self.assertEqual(tree[0]["count"], 6)
        self.assertEqual([n["name"] for n in fh.find_children(tree, ["a", "b"])], ["c"])
        self.assertEqual(fh.find_children(tree, ["x"]), [])

    def test_top_level_count(self):
        self.assertEqual(fh.top_level_count({"a": 1, "a.b": 1, "c": 0, "d.e": 2}), 2)


class TestCandidateNames(unittest.TestCase):
    def setUp(self):
        self.tree = fh.build_tree({"文学.小说": 3, "文学.诗歌": 1, "科技.小说": 2, "科技.数学": 5, "历史": 1})

    def test_level1_only_existing_top_folders(self):
        self.assertEqual([n for n, _c in fh.candidate_names(self.tree, [])], ["科技", "文学", "历史"])

    def test_existing_parent_lists_its_children(self):
        self.assertEqual(fh.candidate_names(self.tree, ["文学"]), [("小说", 3), ("诗歌", 1)])

    def test_missing_or_leaf_parent_falls_back_to_all_level2_names(self):
        expected = [("小说", 5), ("数学", 5), ("诗歌", 1)]
        self.assertEqual(fh.candidate_names(self.tree, ["新目录"]), expected)
        self.assertEqual(fh.candidate_names(self.tree, ["历史"]), expected)


class TestPlanRename(unittest.TestCase):
    def test_leaf(self):
        self.assertEqual(fh.plan_rename(["文学", "文学.小说", "文学.诗歌"], "文学.小说", "故事"), {"文学.小说": "文学.故事"})

    def test_top_with_children(self):
        plan = fh.plan_rename(["文学", "文学.小说", "文学二", "科技"], "文学", "读物")
        self.assertEqual(plan, {"文学": "读物", "文学.小说": "读物.小说"})
