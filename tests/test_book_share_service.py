#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import datetime
import json
import time
import unittest
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import models
from webserver.models import BookShare, Reader
from webserver.services import book_access_service, book_share_service
from webserver.services.book_access_service import BookAccessService
from webserver.services.book_share_service import (
    GRANT_COOKIE,
    GRANT_TTL_SECONDS,
    MAX_FAILURES,
    RESULT_BAD_PASSWORD,
    RESULT_INVALID,
    RESULT_LOCKED,
    RESULT_OK,
    BookShareService,
    ShareParamError,
)


class FakeHandler:

    def __init__(self, cookies=None):
        self.cookies = dict(cookies or {})

    def get_secure_cookie(self, key):
        return self.cookies.get(key)

    def set_secure_cookie(self, key, val):
        self.cookies[key] = val

    def browser(self):
        return FakeHandler(self.cookies)


class ShareTestCase(unittest.TestCase):

    def setUp(self):
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)
        reader = Reader()
        reader.id, reader.username, reader.name = 1, "admin", "Admin"
        self.session.add(reader)
        self.session.commit()
        BookShareService._failures.clear()
        BookShareService.invalidate_cache()
        patcher = mock.patch.dict(book_access_service.CONF, {"ALLOW_GUEST_READ": False, "ALLOW_GUEST_DOWNLOAD": False}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.session.remove()

    def make(self, book_id=10, **kwargs):
        params = dict(allow_read=True, allow_download=False, expire_days=0, max_views=0, password=None)
        params.update(kwargs)
        return BookShareService.create_or_update(book_id, 1, **params)


class TestCreateAndManage(ShareTestCase):

    def test_create_defaults(self):
        share = self.make()
        self.assertEqual(share.status, BookShare.STATUS_ACTIVE)
        self.assertEqual(share.password, "")
        self.assertIsNone(share.expire_time)
        self.assertGreaterEqual(len(share.token), 20)

    def test_one_share_per_book_update_keeps_token(self):
        first = self.make(allow_download=True)
        second = self.make(allow_read=False, allow_download=True, password="abcd", max_views=3)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.token, second.token)
        self.assertEqual(self.session.query(BookShare).count(), 1)
        self.assertEqual((second.password, second.max_views, second.allow_read), ("abcd", 3, False))

    def test_update_keep_expire_with_minus_one(self):
        share = self.make(expire_days=7)
        expire = share.expire_time
        share = self.make(expire_days=-1)
        self.assertEqual(share.expire_time, expire)

    def test_requires_a_permission_and_sane_limits(self):
        with self.assertRaises(ShareParamError):
            self.make(allow_read=False, allow_download=False)
        with self.assertRaises(ShareParamError):
            self.make(max_views=-1)
        with self.assertRaises(ShareParamError):
            self.make(password="x" * 33)

    def test_reactivate_cancelled_share_regenerates_token_and_resets(self):
        share = self.make(max_views=5, password="old")
        old_token = share.token
        share.view_count = 4
        self.session.commit()
        BookShareService.cancel(share.id)
        share = self.make(expire_days=1)
        self.assertNotEqual(share.token, old_token)
        self.assertEqual(share.view_count, 0)
        self.assertEqual(share.status, BookShare.STATUS_ACTIVE)
        self.assertEqual(share.password, "")
        self.assertIsNotNone(share.expire_time)

    def test_cancel_and_delete(self):
        share_id = self.make().id
        self.assertTrue(BookShareService.cancel(share_id))
        self.assertEqual(BookShareService.state_of(BookShareService.get_by_id(share_id)), "cancelled")
        self.assertTrue(BookShareService.delete(share_id))
        self.assertIsNone(BookShareService.get_by_id(share_id))
        self.assertFalse(BookShareService.cancel(share_id))
        self.assertFalse(BookShareService.delete(share_id))

    def test_delete_for_book(self):
        self.make(10)
        self.make(11)
        BookShareService.delete_for_book(10)
        self.assertIsNone(BookShareService.get_by_book(10))
        self.assertIsNotNone(BookShareService.get_by_book(11))

    def test_state_of(self):
        share = self.make(max_views=1)
        self.assertEqual(BookShareService.state_of(share), "active")
        share.view_count = 1
        self.assertEqual(BookShareService.state_of(share), "exhausted")
        share.view_count = 0
        share.expire_time = datetime.datetime.now() - datetime.timedelta(seconds=1)
        self.assertEqual(BookShareService.state_of(share), "expired")

    def test_list_page_newest_first_and_paging(self):
        for i in range(5):
            self.make(100 + i)
            time.sleep(0.002)
        rows, total = BookShareService.list_page(1, 2)
        self.assertEqual(total, 5)
        self.assertEqual([row.book_id for row in rows], [103, 102])

    def test_get_by_token_rejects_garbage(self):
        self.assertIsNone(BookShareService.get_by_token(""))
        self.assertIsNone(BookShareService.get_by_token("x" * 100))

    def test_shared_book_ids_cache_is_invalidated_on_change(self):
        share = self.make(10)
        self.assertEqual(BookShareService.shared_book_ids(), {10})
        BookShareService.cancel(share.id)
        self.assertEqual(BookShareService.shared_book_ids(), set())
        self.make(11, max_views=1)
        self.assertEqual(BookShareService.shared_book_ids(), {11})


class TestVerify(ShareTestCase):

    def test_open_link_counts_a_view(self):
        share = self.make()
        self.assertEqual(BookShareService.verify(share, "", "1.1.1.1"), RESULT_OK)
        self.assertEqual(share.view_count, 1)

    def test_password_checked_and_not_counted_on_failure(self):
        share = self.make(password="s3cret")
        self.assertEqual(BookShareService.verify(share, "wrong", "1.1.1.1"), RESULT_BAD_PASSWORD)
        self.assertEqual(share.view_count, 0)
        self.assertEqual(BookShareService.verify(share, "s3cret", "1.1.1.1"), RESULT_OK)
        self.assertEqual(share.view_count, 1)

    def test_lockout_after_repeated_failures_is_per_ip(self):
        share = self.make(password="s3cret")
        for _ in range(MAX_FAILURES):
            BookShareService.verify(share, "bad", "1.1.1.1")
        self.assertEqual(BookShareService.verify(share, "s3cret", "1.1.1.1"), RESULT_LOCKED)
        self.assertEqual(BookShareService.verify(share, "s3cret", "2.2.2.2"), RESULT_OK)

    def test_success_clears_failures(self):
        share = self.make(password="s3cret")
        for _ in range(MAX_FAILURES - 1):
            BookShareService.verify(share, "bad", "1.1.1.1")
        self.assertEqual(BookShareService.verify(share, "s3cret", "1.1.1.1"), RESULT_OK)
        for _ in range(MAX_FAILURES - 1):
            BookShareService.verify(share, "bad", "1.1.1.1")
        self.assertEqual(BookShareService.verify(share, "s3cret", "1.1.1.1"), RESULT_OK)

    def test_exhausted_cancelled_and_expired_are_invalid(self):
        share = self.make(max_views=1)
        self.assertEqual(BookShareService.verify(share, "", "ip"), RESULT_OK)
        self.assertEqual(BookShareService.verify(share, "", "ip"), RESULT_INVALID)
        other = self.make(11)
        BookShareService.cancel(other.id)
        self.assertEqual(BookShareService.verify(other, "", "ip"), RESULT_INVALID)
        expired = self.make(12)
        expired.expire_time = datetime.datetime.now() - datetime.timedelta(seconds=1)
        self.assertEqual(BookShareService.verify(expired, "", "ip"), RESULT_INVALID)


class TestGrantsAndAccess(ShareTestCase):

    def grant(self, share, handler=None):
        handler = handler or FakeHandler()
        BookShareService.issue_grant(handler, share)
        return handler

    def test_grant_allows_read_for_that_book_only(self):
        share = self.make(10)
        self.make(11)
        handler = self.grant(share)
        self.assertTrue(BookAccessService.guest_read_allowed(handler, 10))
        self.assertFalse(BookAccessService.guest_read_allowed(handler, 11))
        self.assertEqual(BookAccessService.guest_read_source(handler, 10), "share")

    def test_no_cookie_means_no_access(self):
        self.make(10)
        self.assertFalse(BookAccessService.guest_read_allowed(FakeHandler(), 10))
        self.assertFalse(BookAccessService.guest_download_allowed(FakeHandler(), 10))

    def test_permission_bits_are_independent(self):
        read_only = self.make(10, allow_read=True, allow_download=False)
        dl_only = self.make(11, allow_read=False, allow_download=True)
        handler = self.grant(read_only, self.grant(dl_only))
        self.assertTrue(BookAccessService.guest_read_allowed(handler, 10))
        self.assertFalse(BookAccessService.guest_download_allowed(handler, 10))
        self.assertFalse(BookAccessService.guest_read_allowed(handler, 11))
        self.assertTrue(BookAccessService.guest_download_allowed(handler, 11))
        self.assertTrue(BookAccessService.share_read_granted(handler, 10))
        self.assertTrue(BookAccessService.share_download_granted(handler, 11))
        self.assertFalse(BookAccessService.share_download_granted(handler, 10))

    def test_cancel_revokes_existing_grant_immediately(self):
        share = self.make(10)
        handler = self.grant(share)
        BookShareService.cancel(share.id)
        self.assertFalse(BookAccessService.guest_read_allowed(handler, 10))

    def test_expiry_revokes_existing_grant(self):
        share = self.make(10)
        handler = self.grant(share)
        share.expire_time = datetime.datetime.now() - datetime.timedelta(seconds=1)
        self.session.commit()
        self.assertFalse(BookAccessService.guest_read_allowed(handler, 10))

    def test_exhausted_share_keeps_existing_grant(self):
        share = self.make(10, max_views=1)
        BookShareService.verify(share, "", "ip")
        handler = self.grant(share)
        self.assertTrue(share.is_exhausted())
        self.assertTrue(BookAccessService.guest_read_allowed(handler, 10))

    def test_password_change_invalidates_grant(self):
        share = self.make(10, password="one")
        handler = self.grant(share)
        self.make(10, password="two")
        self.assertFalse(BookAccessService.guest_read_allowed(handler, 10))

    def test_token_regeneration_invalidates_grant(self):
        share = self.make(10)
        handler = self.grant(share)
        BookShareService.cancel(share.id)
        self.make(10)
        self.assertFalse(BookAccessService.guest_read_allowed(handler, 10))

    def test_grant_expires_after_ttl(self):
        share = self.make(10)
        handler = self.grant(share)
        with mock.patch.object(book_share_service.time, "time", return_value=time.time() + GRANT_TTL_SECONDS + 5):
            self.assertFalse(BookAccessService.guest_read_allowed(handler, 10))

    def test_tampered_and_garbage_cookies_are_ignored(self):
        share = self.make(10)
        for raw in (b"not json", b"[]", json.dumps({str(share.id): ["bad", int(time.time())]}).encode(), json.dumps({str(share.id): "x"}).encode()):
            self.assertFalse(BookAccessService.guest_read_allowed(FakeHandler({GRANT_COOKIE: raw}), 10), raw)

    def test_generic_check_without_book_id_uses_any_grant(self):
        share = self.make(10)
        self.assertFalse(BookAccessService.guest_read_allowed(FakeHandler()))
        handler = self.grant(share)
        self.assertTrue(BookAccessService.guest_read_allowed(handler))
        BookShareService.cancel(share.id)
        self.assertFalse(BookAccessService.guest_read_allowed(handler))

    def test_multiple_grants_coexist_in_one_cookie(self):
        a, b = self.make(10), self.make(11)
        handler = self.grant(b, self.grant(a))
        self.assertTrue(BookAccessService.guest_read_allowed(handler, 10))
        self.assertTrue(BookAccessService.guest_read_allowed(handler, 11))

    def test_has_grant_is_per_share(self):
        a, b = self.make(10), self.make(11)
        handler = self.grant(a)
        self.assertTrue(BookShareService.has_grant(handler, a))
        self.assertFalse(BookShareService.has_grant(handler, b))

    def test_global_flag_still_wins_without_cookie(self):
        with mock.patch.dict(book_access_service.CONF, {"ALLOW_GUEST_READ": True}):
            self.assertEqual(BookAccessService.guest_read_source(FakeHandler(), 10), "global")


if __name__ == "__main__":
    unittest.main()
