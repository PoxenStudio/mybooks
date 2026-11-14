# -*- coding: utf-8 -*-
"""mimo_tts 音频文件命名 / 清单 / 清理的单元测试（只操作临时目录，不联网）。

覆盖 0.4.1 的「旧音频清理」：文件名计划与写盘必须同名（否则会误删刚生成的
文件）、只删清单里记录过的文件、部分失败时不丢旧记录。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

TMP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TMP_ROOT)

from webserver.toolbox.mimo_tts import AUDIO_MANIFEST_NAME, MimoTTSTool  # noqa: E402


class ChapterFilenameTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(MimoTTSTool._chapter_filename(0, "第一章 起点", 0, 1),
                         "0001_第一章_起点.wav")

    def test_part_suffix_and_sanitize(self):
        self.assertEqual(MimoTTSTool._chapter_filename(11, "a/b", 1, 2),
                         "0012_a_b_part002.wav")

    def test_empty_title_falls_back_to_index(self):
        self.assertEqual(MimoTTSTool._chapter_filename(2, "", 0, 1), "0003_ch3.wav")


class AudioManifestTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._dir, ignore_errors=True)

    def _touch(self, name, size=64):
        path = os.path.join(self._dir, name)
        with open(path, "wb") as f:
            f.write(b"\0" * size)
        return path

    def test_manifest_records_only_existing_files(self):
        # 计划里有、实际没生成的名字不记（否则下一轮会当成自己写过的文件删掉）
        self._touch("0001_a.wav")
        MimoTTSTool._write_manifest(self._dir, "EPUB", {"0001_a.wav", "0002_missing.wav"})
        self.assertEqual(MimoTTSTool._read_manifest_files(self._dir), {"0001_a.wav"})

    def test_prune_removes_only_recorded_stale(self):
        self._touch("0001_a.wav")
        self._touch("0009_old.wav")
        self._touch("mine.wav")  # 用户自己放的文件，不在清单里
        MimoTTSTool._write_manifest(self._dir, "EPUB", {"0001_a.wav", "0009_old.wav"})

        self.assertEqual(MimoTTSTool._prune_stale_audio(self._dir, {"0001_a.wav"}), 1)
        self.assertEqual(sorted(f for f in os.listdir(self._dir) if f.endswith(".wav")),
                         ["0001_a.wav", "mine.wav"])

    def test_prune_without_manifest_is_noop(self):
        self._touch("0009_old.wav")
        self.assertEqual(MimoTTSTool._prune_stale_audio(self._dir, set()), 0)
        self.assertTrue(os.path.exists(os.path.join(self._dir, "0009_old.wav")))

    def test_prune_ignores_traversal_entries(self):
        with open(os.path.join(self._dir, AUDIO_MANIFEST_NAME), "w", encoding="utf-8") as f:
            json.dump({"files": ["../evil.wav", "/tmp/evil.wav", "a/b.wav"]}, f)
        self.assertEqual(MimoTTSTool._prune_stale_audio(self._dir, set()), 0)

    def test_partial_failure_keeps_old_records(self):
        # 本轮有分片失败 → 不清理；清单必须并入上一轮记录，否则旧文件永远清不掉
        self._touch("0001_a.wav")
        self._touch("0002_b.wav")
        MimoTTSTool._write_manifest(self._dir, "EPUB", {"0001_a.wav", "0002_b.wav"})
        MimoTTSTool._write_manifest(self._dir, "TXT", {"0001_a.wav", "0002_c.wav"})
        self.assertEqual(MimoTTSTool._read_manifest_files(self._dir),
                         {"0001_a.wav", "0002_b.wav"})


class AudioDirHousekeepingTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._dir, ignore_errors=True)

    def _touch(self, name):
        with open(os.path.join(self._dir, name), "wb") as f:
            f.write(b"\0" * 64)

    def test_drop_audio_zip(self):
        # 音频集合变了要让打包下载的缓存重建，其它文件不动
        self._touch("audio_collection_7.zip")
        self._touch("0001_a.wav")
        MimoTTSTool._drop_audio_zip(self._dir)
        self.assertEqual(sorted(os.listdir(self._dir)), ["0001_a.wav"])

    def test_clean_partial_files(self):
        # 上一轮中断留下的 .part 要清掉，正式 WAV 不动
        self._touch("0001_a.wav.part")
        self._touch("0001_a.wav")
        MimoTTSTool._clean_partial_files(self._dir)
        self.assertEqual(sorted(os.listdir(self._dir)), ["0001_a.wav"])


if __name__ == "__main__":
    unittest.main()
