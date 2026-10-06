#!/usr/bin/env python3

import unittest
from unittest import mock

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from webserver import models
from webserver.handlers.base import BaseHandler
from webserver.models import Item, Reader


class TestItemMaps(unittest.TestCase):

    def setUp(self):
        engine = create_engine("sqlite://")
        models.Base.metadata.create_all(engine, tables=[Reader.__table__, Item.__table__])
        self.session = sessionmaker(bind=engine)()
        self.addCleanup(self.session.close)
        self.statements = []
        event.listen(engine, "before_cursor_execute", lambda conn, cur, stmt, *a: self.statements.append(stmt))
        for name in ("admin", "alice"):
            reader = Reader()
            reader.username = name
            reader.password = "x"
            self.session.add(reader)
        self.session.commit()
        self.handler = object.__new__(BaseHandler)
        self.handler.sqlite_session = self.session

    def add_item(self, book_id, collector_id):
        item = Item()
        item.book_id = book_id
        item.collector_id = collector_id
        self.session.add(item)
        self.session.commit()

    def reader_selects(self):
        return [s for s in self.statements if s.lstrip().upper().startswith("SELECT") and "FROM readers" in s and "ORDER BY" in s]

    def test_collector_dict_shared_by_collector_id(self):
        for book_id in (1, 2, 3):
            self.add_item(book_id, 2)
        with mock.patch.object(Reader, "to_dict", autospec=True, side_effect=lambda self: {"id": self.id, "username": self.username}) as to_dict:
            maps, _ = self.handler._item_maps([1, 2, 3])
        self.assertEqual(to_dict.call_count, 1)
        self.assertEqual({m["collector"]["username"] for m in maps.values()}, {"alice"})
        maps[1]["collector"]["username"] = "changed"
        self.assertEqual(maps[2]["collector"]["username"], "alice")

    def test_default_collector_not_queried_when_all_books_have_items(self):
        self.add_item(1, 2)
        self.statements.clear()
        maps, empty_item = self.handler._item_maps([1])
        self.assertEqual(self.reader_selects(), [])
        self.assertNotIn("collector", empty_item)
        self.assertEqual(maps[1]["collector_id"], 2)

    def test_default_collector_used_for_books_without_item(self):
        self.add_item(1, 2)
        maps, empty_item = self.handler._item_maps([1, 99])
        self.assertEqual(empty_item["collector"].username, "admin")
        self.assertNotIn(99, maps)

    def test_empty_ids(self):
        maps, empty_item = self.handler._item_maps([])
        self.assertEqual(maps, {})
        self.assertFalse(empty_item["sole"])

    def test_offloaded_runs_off_ioloop_with_own_session(self):
        import asyncio
        import threading

        seen = {}
        scoped = mock.Mock(side_effect=lambda: seen.setdefault("session", self.session))
        patcher = mock.patch.object(BaseHandler, "settings", new_callable=mock.PropertyMock, return_value={"ScopedSession": scoped})
        patcher.start()
        self.addCleanup(patcher.stop)

        def spy(ids, session=None):
            seen["thread"] = threading.current_thread().name
            seen["passed"] = session
            return {1: {"collector_id": 2}}, {}

        self.handler._item_maps = spy
        maps, _ = asyncio.run(self.handler._item_maps_async([1]))
        self.assertNotEqual(seen["thread"], threading.current_thread().name)
        self.assertIs(seen["passed"], self.session)
        scoped.remove.assert_called_once()
        self.assertEqual(maps[1]["collector_id"], 2)


if __name__ == "__main__":
    unittest.main()
