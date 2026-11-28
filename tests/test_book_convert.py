#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""格式转换规则单元测试。"""

import unittest

from webserver.services.converter import CONVERT_RULES, normalize_book_format, validate_conversion


class TestConversionRules(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(CONVERT_RULES["txt"], ["epub", "azw3", "pdf"])
        self.assertEqual(CONVERT_RULES["epub"], ["azw3", "pdf"])
        self.assertEqual(CONVERT_RULES["azw3"], ["epub", "pdf"])
        self.assertEqual(CONVERT_RULES["mobi"], ["epub", "pdf"])
        self.assertEqual(CONVERT_RULES["docx"], ["azw3", "epub", "pdf"])
        self.assertEqual(CONVERT_RULES["fb2"], ["azw3", "epub", "pdf"])
        self.assertEqual(CONVERT_RULES["pdf"], ["epub"])

    def test_pdf_is_output_for_non_pdf_sources(self):
        for source in ("txt", "epub", "azw3", "mobi", "docx", "fb2"):
            self.assertIn("pdf", CONVERT_RULES[source])
        self.assertNotIn("pdf", CONVERT_RULES["pdf"])

    def test_normalize_format(self):
        self.assertEqual(normalize_book_format(" EPUB "), "epub")
        self.assertEqual(normalize_book_format(None), "")

    def test_validate_ok(self):
        self.assertEqual(validate_conversion(["txt"], "txt", "epub"), "ok")
        self.assertEqual(validate_conversion(["EPUB"], "epub", "PDF"), "ok")

    def test_validate_errors(self):
        self.assertEqual(validate_conversion(["epub"], "", "azw3"), "missing_params")
        self.assertEqual(validate_conversion(["epub"], "epub", ""), "missing_params")
        self.assertEqual(validate_conversion(["djvu"], "djvu", "epub"), "unsupported_source")
        self.assertEqual(validate_conversion(["epub"], "txt", "epub"), "source_missing")
        self.assertEqual(validate_conversion(["epub"], "epub", "epub"), "unsupported_target")
        self.assertEqual(validate_conversion(["epub", "pdf"], "epub", "pdf"), "target_exists")


if __name__ == "__main__":
    unittest.main()
