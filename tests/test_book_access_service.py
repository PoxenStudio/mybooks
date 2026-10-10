#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import pathlib
import unittest
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import models
from webserver.models import Reader
from webserver.services import book_access_service
from webserver.services.book_access_service import BookAccessService
from webserver.services.booklist_service import BookListService

WEBSERVER = pathlib.Path(__file__).resolve().parent.parent / "webserver"
ALLOWED_DIRECT_USERS = {"services/book_access_service.py", "settings.py", "base/setting_saver.py", "handlers/base.py"}


class NoCookieHandler:

    def get_secure_cookie(self, key):
        return None


class TestBookAccessService(unittest.TestCase):

    def check(self, conf, func, book_id=None):
        with mock.patch.dict(book_access_service.CONF, conf, clear=False), mock.patch.object(BookAccessService, "_booklist_allows_read", return_value=False):
            return func(NoCookieHandler(), book_id)

    def test_guest_read_follows_global_flag(self):
        self.assertTrue(self.check({"ALLOW_GUEST_READ": True}, BookAccessService.guest_read_allowed, 1))
        self.assertFalse(self.check({"ALLOW_GUEST_READ": False}, BookAccessService.guest_read_allowed, 1))
        self.assertFalse(self.check({"ALLOW_GUEST_READ": False}, BookAccessService.guest_read_allowed))

    def test_guest_download_follows_global_flag(self):
        self.assertTrue(self.check({"ALLOW_GUEST_DOWNLOAD": True}, BookAccessService.guest_download_allowed, 1))
        self.assertFalse(self.check({"ALLOW_GUEST_DOWNLOAD": False}, BookAccessService.guest_download_allowed, 1))

    def test_read_and_download_flags_are_independent(self):
        conf = {"ALLOW_GUEST_READ": True, "ALLOW_GUEST_DOWNLOAD": False}
        self.assertTrue(self.check(conf, BookAccessService.guest_read_allowed))
        self.assertFalse(self.check(conf, BookAccessService.guest_download_allowed))

    def test_handlers_do_not_read_guest_flags_directly(self):
        offenders = []
        for path in WEBSERVER.rglob("*.py"):
            rel = path.relative_to(WEBSERVER).as_posix()
            if rel in ALLOWED_DIRECT_USERS or rel.startswith("epub_to_audio/"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "ALLOW_GUEST_READ" in text or "ALLOW_GUEST_DOWNLOAD" in text:
                offenders.append(rel)
        self.assertEqual(offenders, [])


class TestBookListGuestRead(unittest.TestCase):

    def setUp(self):
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)
        reader = Reader()
        reader.id, reader.username, reader.name = 1, "u1", "Alice"
        self.session.add(reader)
        self.session.commit()
        patcher = mock.patch.dict(book_access_service.CONF, {"ALLOW_GUEST_READ": False}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.session.remove()

    def make_list(self, public=True, guest_read=True, books=(10,)):
        row = BookListService.create(self.session, 1, "showcase", is_public=public)
        if books:
            BookListService.add_books(self.session, row, list(books))
        if guest_read:
            row = BookListService.update(self.session, row, guest_read=True)
        return row

    def allowed(self, book_id=None):
        return BookAccessService.guest_read_allowed(NoCookieHandler(), book_id)

    def test_book_in_guest_read_booklist_is_readable(self):
        self.make_list()
        self.assertTrue(self.allowed(10))

    def test_book_outside_booklist_is_not_readable(self):
        self.make_list()
        self.assertFalse(self.allowed(11))

    def test_booklist_without_flag_grants_nothing(self):
        self.make_list(guest_read=False)
        self.assertFalse(self.allowed(10))

    def test_generic_check_true_only_when_a_guest_booklist_exists(self):
        self.assertFalse(self.allowed())
        self.make_list()
        self.assertTrue(self.allowed())

    def test_making_private_clears_guest_read(self):
        row = self.make_list()
        row = BookListService.update(self.session, row, is_public=False)
        self.assertFalse(row.guest_read)
        self.assertFalse(self.allowed(10))

    def test_cannot_keep_guest_read_on_private_list(self):
        row = self.make_list(public=False, guest_read=False)
        row = BookListService.update(self.session, row, guest_read=True)
        self.assertFalse(row.guest_read)

    def test_deleting_booklist_revokes_access(self):
        row = self.make_list()
        BookListService.delete(self.session, row)
        self.assertFalse(self.allowed(10))

    def test_removing_book_from_booklist_revokes_access(self):
        row = self.make_list(books=(10, 11))
        BookListService.remove_book(self.session, row, 10)
        self.assertFalse(self.allowed(10))
        self.assertTrue(self.allowed(11))

    def test_read_source_reports_origin(self):
        self.assertIsNone(BookAccessService.guest_read_source(NoCookieHandler(), 10))
        self.make_list()
        self.assertEqual(BookAccessService.guest_read_source(NoCookieHandler(), 10), "booklist")
        self.assertIsNone(BookAccessService.guest_read_source(NoCookieHandler(), 11))
        with mock.patch.dict(book_access_service.CONF, {"ALLOW_GUEST_READ": True}):
            self.assertEqual(BookAccessService.guest_read_source(NoCookieHandler(), 11), "global")

    def test_global_flag_still_wins(self):
        with mock.patch.dict(book_access_service.CONF, {"ALLOW_GUEST_READ": True}):
            self.assertTrue(self.allowed(99))

    def test_invalid_book_id_is_rejected(self):
        self.make_list()
        self.assertFalse(self.allowed("abc"))


if __name__ == "__main__":
    unittest.main()
