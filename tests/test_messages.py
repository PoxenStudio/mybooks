#!/usr/bin/env python3

import datetime
import json
import unittest
from unittest import mock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from webserver import models
from webserver.models import Message
from webserver.services.async_service import AsyncService


class MessageTestCase(unittest.TestCase):

    def setUp(self):
        self.engine = create_engine("sqlite://")
        models.Base.metadata.create_all(self.engine, tables=[Message.__table__])
        self.session = sessionmaker(bind=self.engine)()
        patcher = mock.patch.object(Message, "_session", classmethod(lambda cls: self.session))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.session.close)

    def add(self, reader_id, text_, unread=True, age_days=0):
        msg = Message(reader_id, "info", text_)
        msg.unread = unread
        msg.update_time = msg.create_time = datetime.datetime.now() - datetime.timedelta(days=age_days)
        self.session.add(msg)
        self.session.commit()
        return msg.id


class TestUnreadPage(MessageTestCase):

    def test_filters_orders_and_counts(self):
        ids = [self.add(1, "m%d" % i) for i in range(60)]
        self.add(1, "read", unread=False)
        self.add(2, "other")
        rows, total = Message.unread_page(self.session, 1)
        self.assertEqual(total, 60)
        self.assertEqual(len(rows), 50)
        self.assertEqual(rows[0].id, ids[-1])

    def test_after_id_is_incremental(self):
        ids = [self.add(1, "m%d" % i) for i in range(5)]
        rows, total = Message.unread_page(self.session, 1, after_id=ids[2])
        self.assertEqual([r.id for r in rows], [ids[4], ids[3]])
        self.assertEqual(total, 5)

    def test_to_brief(self):
        self.add(1, "hello")
        rows, _ = Message.unread_page(self.session, 1)
        self.assertEqual(rows[0].to_brief()["data"], {"message": "hello"})


class TestCleanup(MessageTestCase):

    def test_same_content_removed_only_for_reader(self):
        self.add(1, "dup")
        self.add(2, "dup")
        keep = self.add(1, "other")
        self.assertEqual(Message.cleanup_messages(1, "dup"), 1)
        remaining = {m.id for m in self.session.query(Message).filter(Message.reader_id == 1)}
        self.assertEqual(remaining, {keep})
        self.assertEqual(self.session.query(Message).filter(Message.reader_id == 2).count(), 1)

    def test_old_messages_removed(self):
        self.add(1, "old", age_days=40)
        self.add(1, "new")
        Message.cleanup_messages(1, "x")
        self.assertEqual(self.session.query(Message).count(), 1)

    def test_cap_per_user(self):
        for i in range(Message.MAX_PER_USER + 30):
            self.add(1, "m%d" % i)
        self.add(2, "other")
        Message.cleanup_messages(1, "new")
        self.assertEqual(self.session.query(Message).filter(Message.reader_id == 1).count(), Message.MAX_PER_USER - 1)
        self.assertEqual(self.session.query(Message).filter(Message.reader_id == 2).count(), 1)

    def test_cleanup_old_messages(self):
        self.add(1, "old", age_days=40)
        self.add(1, "new")
        self.assertEqual(Message.cleanup_old_messages(), 1)


class TestMigration(unittest.TestCase):

    def test_adds_hash_and_indexes_to_old_table(self):
        engine = create_engine("sqlite://")
        session = sessionmaker(bind=engine)()
        session.execute(text("CREATE TABLE messages (id INTEGER PRIMARY KEY, title VARCHAR(200), status VARCHAR(100), unread BOOLEAN, create_time DATETIME, update_time DATETIME, data TEXT, reader_id INTEGER)"))
        session.execute(text("INSERT INTO messages (id, status, unread, data, reader_id) VALUES (1, 'info', 1, :d, 1)"), {"d": json.dumps({"message": "hello"})})
        service = object.__new__(AsyncService)
        service.session = session
        service.adjust_messages_table()
        service.adjust_messages_table()
        row = session.execute(text("SELECT content_hash FROM messages WHERE id=1")).fetchone()
        self.assertEqual(row[0], Message.hash_content("hello"))
        indexes = {r[1] for r in session.execute(text("PRAGMA index_list(messages)")).fetchall()}
        self.assertIn("ix_messages_reader_unread_id", indexes)
        self.assertIn("ix_messages_reader_id", indexes)


if __name__ == "__main__":
    unittest.main()
