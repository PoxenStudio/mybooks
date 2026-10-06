#!/usr/bin/env python3

import unittest
from unittest import mock

from webserver.services.catalog import CatalogExtractService


class TestCatalogDeletedBook(unittest.TestCase):

    def setUp(self):
        self.service = object.__new__(CatalogExtractService)
        self.cache = mock.Mock()
        self.service.db = mock.Mock(new_api=self.cache)

    def test_missing_book_skipped_up_front(self):
        self.cache.has_id.return_value = False
        result = self.service._extract_one(1, True)
        self.assertTrue(result["skipped"])
        self.cache.set_field.assert_not_called()

    def test_book_deleted_during_store_is_ignored(self):
        self.cache.has_id.return_value = False
        self.cache.set_field.side_effect = RuntimeError("Foreign key violation")
        self.assertFalse(CatalogExtractService._store_catalog(self.cache, 1, "x"))

    def test_other_errors_still_raise(self):
        self.cache.has_id.return_value = True
        self.cache.set_field.side_effect = RuntimeError("disk full")
        with self.assertRaises(RuntimeError):
            CatalogExtractService._store_catalog(self.cache, 1, "x")


if __name__ == "__main__":
    unittest.main()
