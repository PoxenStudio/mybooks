#!/usr/bin/env python3

import datetime
import unittest

from webserver.base.formatter import cover_stamp


class TestCoverStamp(unittest.TestCase):

    def test_prefers_last_modified(self):
        book = {"timestamp": datetime.datetime(2020, 1, 1), "last_modified": datetime.datetime(2021, 6, 1)}
        self.assertEqual(cover_stamp(book), int(datetime.datetime(2021, 6, 1).timestamp()))

    def test_falls_back_to_timestamp(self):
        book = {"timestamp": datetime.datetime(2020, 1, 1)}
        self.assertEqual(cover_stamp(book), int(datetime.datetime(2020, 1, 1).timestamp()))

    def test_missing_values(self):
        self.assertEqual(cover_stamp({}), 0)

    def test_changes_when_book_modified(self):
        old = {"timestamp": datetime.datetime(2020, 1, 1), "last_modified": datetime.datetime(2021, 1, 1)}
        new = dict(old, last_modified=datetime.datetime(2021, 1, 2))
        self.assertNotEqual(cover_stamp(old), cover_stamp(new))


if __name__ == "__main__":
    unittest.main()
