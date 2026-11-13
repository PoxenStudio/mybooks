#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import os
import tempfile
import unittest
from unittest import mock

from webserver.base.formatter import SimpleBookFormatter
from webserver.constants import CALIBRE_COLUMN_WORD_COUNT
from webserver.plugins.parser.txt import TxtParser, count_words
from webserver.services import AsyncService
from webserver.services.word_count import WordCountService

TEST_DIR = os.path.dirname(os.path.realpath(__file__))


class TestCountWords(unittest.TestCase):
    def test_chinese_characters(self):
        self.assertEqual(count_words("你好世界"), 4)

    def test_chinese_punctuation_counts_as_characters(self):
        self.assertEqual(count_words("你好，世界！"), 6)

    def test_english_words(self):
        self.assertEqual(count_words("hello world"), 2)

    def test_mixed_text(self):
        self.assertEqual(count_words("你好 world"), 3)

    def test_whitespace_is_not_counted(self):
        self.assertEqual(count_words("你好\n世界"), 4)

    def test_empty_text(self):
        self.assertEqual(count_words(""), 0)


class TestTxtCountFile(unittest.TestCase):
    def _count_file(self, text):
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return TxtParser().count_file(path)

    def test_counts_whole_file(self):
        text = "第一章 测试\n这是一段正文。\n第二段 english words\n"
        result = self._count_file(text)
        expected = sum(count_words(line) for line in text.splitlines(True))
        self.assertEqual(result["word_count"], expected)
        self.assertGreater(result["word_count"], 0)


class TestEpubCount(unittest.TestCase):
    def test_counts_real_epub(self):
        path = os.path.join(TEST_DIR, "cases", "new.epub")
        self.assertGreater(WordCountService._count_epub(path), 0)


class TestCountBook(unittest.TestCase):
    def setUp(self):
        fd_epub, self.epub_path = tempfile.mkstemp(suffix=".epub")
        os.close(fd_epub)
        fd_txt, self.txt_path = tempfile.mkstemp(suffix=".txt")
        os.close(fd_txt)
        self.addCleanup(lambda: os.path.exists(self.epub_path) and os.remove(self.epub_path))
        self.addCleanup(lambda: os.path.exists(self.txt_path) and os.remove(self.txt_path))
        self.db = mock.Mock()
        self.db.format_abspath.side_effect = lambda bid, fmt, index_is_id=False: {
            "EPUB": self.epub_path,
            "TXT": self.txt_path,
        }[fmt]

    def test_epub_has_priority_over_txt(self):
        self.db.formats.return_value = ["TXT", "EPUB"]
        with mock.patch.object(WordCountService, "_count_epub", return_value=123) as epub_count:
            with mock.patch.object(WordCountService, "_count_txt") as txt_count:
                result = WordCountService.count_book(7, self.db)

        self.assertEqual(result["err"], "ok")
        self.assertEqual(result["word_count"], 123)
        self.assertEqual(result["format"], "EPUB")
        epub_count.assert_called_once_with(self.epub_path)
        txt_count.assert_not_called()
        self.db.set_field.assert_called_once_with(CALIBRE_COLUMN_WORD_COUNT, {7: 123})

    def test_txt_is_used_when_epub_missing(self):
        self.db.formats.return_value = ["TXT"]
        with mock.patch.object(WordCountService, "_count_txt", return_value=456):
            result = WordCountService.count_book(7, self.db)

        self.assertEqual(result["err"], "ok")
        self.assertEqual(result["word_count"], 456)
        self.assertEqual(result["format"], "TXT")
        self.db.set_field.assert_called_once_with(CALIBRE_COLUMN_WORD_COUNT, {7: 456})

    def test_unsupported_format_does_not_write(self):
        self.db.formats.return_value = ["PDF", "MOBI"]
        result = WordCountService.count_book(7, self.db)

        self.assertEqual(result["err"], "word_count.unsupported")
        self.db.set_field.assert_not_called()

    def test_save_failure_is_reported(self):
        self.db.formats.return_value = ["TXT"]
        self.db.set_field.side_effect = RuntimeError("no column")
        with mock.patch.object(WordCountService, "_count_txt", return_value=10):
            result = WordCountService.count_book(7, self.db)

        self.assertEqual(result["err"], "word_count.save_failed")

    def test_existing_count_is_skipped_when_not_forced(self):
        self.db.field_for.return_value = 321
        result = WordCountService.count_book(7, self.db, force=False)

        self.assertTrue(result["skipped"])
        self.assertEqual(result["word_count"], 321)
        self.db.formats.assert_not_called()
        self.db.set_field.assert_not_called()

    def test_force_recounts_existing(self):
        self.db.field_for.return_value = 321
        self.db.formats.return_value = ["TXT"]
        with mock.patch.object(WordCountService, "_count_txt", return_value=456):
            result = WordCountService.count_book(7, self.db, force=True)

        self.assertEqual(result["err"], "ok")
        self.assertEqual(result["word_count"], 456)


class TestWordCountBatch(unittest.TestCase):
    def _service(self):
        service = object.__new__(WordCountService)
        service.db = mock.Mock(new_api=mock.Mock())
        service.add_msg = mock.Mock()
        service.is_running = False
        service.task_id = None
        service.current_book_id = None
        service.count_total = 0
        service.count_done = 0
        service.count_fail = 0
        service.count_skip = 0
        return service

    def _run_batch(self, service, results):
        with mock.patch.object(AsyncService, "setup", return_value=False):
            with mock.patch.object(AsyncService, "async_mode", return_value=False):
                with mock.patch("webserver.services.word_count.BackgroundService") as bg:
                    bg.return_value.update_task.return_value.id = 99
                    with mock.patch.object(WordCountService, "count_book", side_effect=results):
                        service.count_batch(1, [1, 2, 3], force=False)
        return bg

    def test_batch_counts_done_skip_fail(self):
        service = self._service()
        bg = self._run_batch(service, [
            {"err": "ok", "word_count": 10},
            {"err": "word_count.unsupported"},
            {"err": "ok", "skipped": True, "word_count": 20},
        ])

        self.assertEqual(service.count_done, 1)
        self.assertEqual(service.count_skip, 2)
        self.assertEqual(service.count_fail, 0)
        self.assertFalse(service.is_running)
        bg.return_value.complete_task.assert_called_once_with(task_id=99)
        service.add_msg.assert_called_once()

    def test_batch_failure_is_counted(self):
        service = self._service()
        self._run_batch(service, [{"err": "word_count.failed"}] * 3)

        self.assertEqual(service.count_done, 0)
        self.assertEqual(service.count_fail, 3)


class TestFormatterWordCount(unittest.TestCase):
    def _format(self, **fields):
        book = {
            "id": 1,
            "title": "测试书",
            "authors": ["作者"],
            "tags": [],
            "rating": 0,
            "series_index": None,
        }
        book.update(fields)
        return SimpleBookFormatter(book, "").format()

    def test_returns_cached_word_count(self):
        self.assertEqual(self._format(**{CALIBRE_COLUMN_WORD_COUNT: 12345})["word_count"], 12345)

    def test_missing_word_count_defaults_to_zero(self):
        self.assertEqual(self._format()["word_count"], 0)


if __name__ == "__main__":
    unittest.main()
