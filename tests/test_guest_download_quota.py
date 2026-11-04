#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import asyncio
import datetime
import unittest
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import models
from webserver.handlers.book import BookDownload, BookDownloadQuota
from webserver.models import GuestDownloadDaily
from webserver.services import guest_download_quota_service
from webserver.services.book_access_service import BookAccessService
from webserver.services.download_quota_service import DownloadQuotaService, QuotaResult
from webserver.services.guest_download_quota_service import GuestDownloadQuotaService, GuestQuotaResult
from tornado import web

DAY = datetime.date(2026, 11, 4)


class TestGuestDownloadQuotaService(unittest.TestCase):

    def setUp(self):
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)
        GuestDownloadQuotaService._last_prune_day = None
        self.conf = mock.patch.dict(
            guest_download_quota_service.CONF,
            {"ENABLE_GUEST_DOWNLOAD_QUOTA": True, "GUEST_DOWNLOAD_QUOTA": 2},
            clear=False,
        )
        self.conf.start()
        self.addCleanup(self.conf.stop)
        self.today = mock.patch.object(guest_download_quota_service.site_time, "site_today", return_value=DAY)
        self.today.start()
        self.addCleanup(self.today.stop)

    def tearDown(self):
        self.session.remove()

    def rows(self):
        return self.session.query(GuestDownloadDaily).all()

    def test_disabled_allows_and_records_nothing(self):
        with mock.patch.dict(guest_download_quota_service.CONF, {"ENABLE_GUEST_DOWNLOAD_QUOTA": False}):
            self.assertTrue(GuestDownloadQuotaService.charge("1.2.3.4", 1).allowed)
            self.assertEqual(self.rows(), [])

    def test_counts_distinct_books(self):
        first = GuestDownloadQuotaService.charge("1.2.3.4", 1)
        self.assertEqual((first.allowed, first.used, first.quota), (True, 1, 2))
        repeat = GuestDownloadQuotaService.charge("1.2.3.4", 1)
        self.assertEqual((repeat.allowed, repeat.used), (True, 1))
        second = GuestDownloadQuotaService.charge("1.2.3.4", 2)
        self.assertEqual((second.allowed, second.used), (True, 2))
        denied = GuestDownloadQuotaService.charge("1.2.3.4", 3)
        self.assertEqual((denied.allowed, denied.used), (False, 2))
        self.assertEqual(len(self.rows()), 2)

    def test_get_usage_still_allows_already_counted_book(self):
        GuestDownloadQuotaService.charge("1.2.3.4", 1)
        GuestDownloadQuotaService.charge("1.2.3.4", 2)
        self.assertFalse(GuestDownloadQuotaService.get_usage("1.2.3.4").allowed)
        repeated = GuestDownloadQuotaService.get_usage("1.2.3.4", 1)
        self.assertEqual((repeated.allowed, repeated.used, repeated.quota), (True, 2, 2))
        self.assertFalse(GuestDownloadQuotaService.get_usage("1.2.3.4", 3).allowed)

    def test_separate_ips_have_separate_buckets(self):
        GuestDownloadQuotaService.charge("1.2.3.4", 1)
        GuestDownloadQuotaService.charge("1.2.3.4", 2)
        self.assertFalse(GuestDownloadQuotaService.get_usage("1.2.3.4").allowed)
        self.assertTrue(GuestDownloadQuotaService.get_usage("5.6.7.8").allowed)

    def test_ipv6_is_aggregated_by_64(self):
        self.assertEqual(GuestDownloadQuotaService.normalize_ip("2001:db8::1"), "2001:db8::")
        self.assertEqual(GuestDownloadQuotaService.normalize_ip("::ffff:1.2.3.4"), "1.2.3.4")
        GuestDownloadQuotaService.charge("2001:db8::1", 1)
        usage = GuestDownloadQuotaService.get_usage("2001:db8::2")
        self.assertEqual(usage.used, 1)
        GuestDownloadQuotaService.charge("2001:db8::2", 2)
        self.assertFalse(GuestDownloadQuotaService.get_usage("2001:db8::3").allowed)
        self.assertTrue(GuestDownloadQuotaService.get_usage("2001:db8:0:1::1").allowed)

    def test_daily_rollover(self):
        GuestDownloadQuotaService.charge("1.2.3.4", 1)
        GuestDownloadQuotaService.charge("1.2.3.4", 2)
        self.assertFalse(GuestDownloadQuotaService.get_usage("1.2.3.4").allowed)
        with mock.patch.object(guest_download_quota_service.site_time, "site_today", return_value=DAY + datetime.timedelta(days=1)):
            usage = GuestDownloadQuotaService.get_usage("1.2.3.4")
            self.assertEqual(usage.used, 0)
            self.assertTrue(usage.allowed)

    def test_zero_quota_means_unlimited(self):
        with mock.patch.dict(guest_download_quota_service.CONF, {"GUEST_DOWNLOAD_QUOTA": 0}):
            for book_id in range(1, 10):
                self.assertTrue(GuestDownloadQuotaService.charge("1.2.3.4", book_id).allowed)
            self.assertEqual(self.rows(), [])

    def test_invalid_ip_is_not_tracked(self):
        self.assertTrue(GuestDownloadQuotaService.charge("", 1).allowed)
        self.assertEqual(self.rows(), [])

    def test_prune_removes_expired_rows(self):
        old_day = DAY - datetime.timedelta(days=guest_download_quota_service.RETENTION_DAYS + 1)
        self.session.add(GuestDownloadDaily("1.2.3.4", old_day, 1))
        self.session.commit()
        GuestDownloadQuotaService.charge("1.2.3.4", 2)
        days = [row.day for row in self.rows()]
        self.assertEqual(days, [DAY])


class TestBookDownloadGuestQuota(unittest.TestCase):

    def make_handler(self, method="GET", current_user=None):
        handler = object.__new__(BookDownload)
        handler.request = mock.Mock(method=method, remote_ip="1.2.3.4")
        handler.current_user = current_user
        handler.is_opds = False
        handler.requested_book_id = lambda: 15
        return handler

    def test_guest_charge_uses_ip_quota(self):
        handler = self.make_handler()
        with mock.patch.object(BookAccessService, "share_download_granted", return_value=False), \
                mock.patch.object(GuestDownloadQuotaService, "enabled", return_value=True), \
                mock.patch.object(GuestDownloadQuotaService, "charge", return_value=GuestQuotaResult(True, 1, 10)) as charge:
            handler._charge_download("15", "epub")
            charge.assert_called_once_with("1.2.3.4", "15")

    def test_guest_denied_returns_429(self):
        handler = self.make_handler()
        with mock.patch.object(BookAccessService, "share_download_granted", return_value=False), \
                mock.patch.object(GuestDownloadQuotaService, "enabled", return_value=True), \
                mock.patch.object(GuestDownloadQuotaService, "charge", return_value=GuestQuotaResult(False, 10, 10)):
            with self.assertRaises(web.HTTPError) as ctx:
                handler._charge_download("15", "epub")
            self.assertEqual(ctx.exception.status_code, 429)

    def test_head_and_share_downloads_do_not_charge(self):
        with mock.patch.object(BookAccessService, "share_download_granted", return_value=False), \
                mock.patch.object(GuestDownloadQuotaService, "charge") as charge:
            self.make_handler(method="HEAD")._charge_download("15", "epub")
            charge.assert_not_called()
        with mock.patch.object(BookAccessService, "share_download_granted", return_value=True), \
                mock.patch.object(GuestDownloadQuotaService, "charge") as charge:
            self.make_handler()._charge_download("15", "epub")
            charge.assert_not_called()

    def test_logged_in_user_does_not_use_guest_quota(self):
        handler = self.make_handler(current_user=mock.Mock())
        with mock.patch.object(BookAccessService, "share_download_granted", return_value=False), \
                mock.patch.object(GuestDownloadQuotaService, "charge") as guest_charge, \
                mock.patch.object(DownloadQuotaService, "charge", return_value=QuotaResult(True, 1, 10)) as user_charge:
            handler._charge_download("15", "epub")
            guest_charge.assert_not_called()
            user_charge.assert_called_once()


class FakeQuotaHandler:

    def __init__(self, book_id="15", current_user=None, remote_ip="1.2.3.4"):
        self.current_user = current_user
        self.request = mock.Mock(remote_ip=remote_ip)
        self.request.headers = {}
        self._book_id = book_id
        self.written = None

    def get_argument(self, name, default=None):
        if name == "book_id":
            return self._book_id
        return default

    def set_header(self, *args, **kwargs):
        pass

    def write(self, rsp):
        self.written = rsp

    def finish(self):
        pass


class TestBookDownloadQuotaCheck(unittest.TestCase):

    def call(self, handler):
        asyncio.run(BookDownloadQuota.get(handler))
        return handler.written

    def test_guest_share_download_is_exempt(self):
        handler = FakeQuotaHandler()
        with mock.patch.object(BookAccessService, "share_download_granted", return_value=True), \
                mock.patch.object(GuestDownloadQuotaService, "get_usage") as usage:
            rsp = self.call(handler)
            self.assertEqual(rsp, {"err": "ok", "allowed": True, "used": 0, "quota": 0})
            usage.assert_not_called()

    def test_guest_without_limit_is_allowed(self):
        handler = FakeQuotaHandler()
        with mock.patch.object(BookAccessService, "share_download_granted", return_value=False), \
                mock.patch.object(GuestDownloadQuotaService, "enabled", return_value=False):
            rsp = self.call(handler)
            self.assertEqual(rsp, {"err": "ok", "allowed": True, "used": 0, "quota": 0})

    def test_guest_exceeded_reports_quota(self):
        handler = FakeQuotaHandler()
        with mock.patch.object(BookAccessService, "share_download_granted", return_value=False), \
                mock.patch.object(GuestDownloadQuotaService, "enabled", return_value=True), \
                mock.patch.object(GuestDownloadQuotaService, "get_usage", return_value=GuestQuotaResult(False, 10, 10)) as usage:
            rsp = self.call(handler)
            self.assertEqual(rsp["err"], "quota.exceeded")
            self.assertFalse(rsp["allowed"])
            self.assertEqual((rsp["used"], rsp["quota"]), (10, 10))
            self.assertIn("10/10", rsp["msg"])
            usage.assert_called_once_with("1.2.3.4", 15)


if __name__ == "__main__":
    unittest.main()
