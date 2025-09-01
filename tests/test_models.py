#!/usr/bin/env python3


import json
import logging
import unittest

from webserver import models


class TestUser(unittest.TestCase):

    def test_shrink_extra_size2(self):
        n = 200
        a = models.Reader()
        a.extra = {}
        a.extra["read_history"] = [{"id": 123, "title": "name", "timestamp": 1643347670}] * n
        a.shrink_column_extra()
        # should not shrink
        self.assertEqual(len(a.extra["read_history"]), n)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(levelname)5s %(pathname)s:%(lineno)d %(message)s",
    )
    unittest.main()
