#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""扫描导入「本次导入设为私藏」(sole) 参数透传测试。

纯单元测试：内存 sqlite（StaticPool 跨线程共享连接）+ 临时文件，不依赖 tornado 服务与 calibre。
覆盖：
- do_import_internal → _importing_worker（跨线程边界）→ _import_one_file 的 sole 全链透传
- 缺省 sole=False（既有行为不变）
- sole=True 时跳过 SEND_MAIL_FOR_NEW_BOOKS 新书邮件（私藏书名不外泄），sole=False 时照发
"""

import os
import queue as _queue
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool

from webserver import models
from webserver.models import Reader, ScanFile
from webserver.services import scan_service
from webserver.services import mail as mail_module
from webserver.services.scan_service import ScanService


class ScanImportSoleTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)
        self.tmpdir = tempfile.mkdtemp(prefix="scan_sole_test_")
        self.svc = ScanService()
        self.svc.session = self.session
        self.svc.scoped_session = self.session
        self.svc.db = mock.MagicMock()
        self.svc.db.get_metadata.return_value = SimpleNamespace(title="私藏书A")
        self._old_mail_flag = scan_service.CONF.get("SEND_MAIL_FOR_NEW_BOOKS", False)
        self.mail_calls = []
        # 邮件与自动填充/目录抽取服务在导入完成后触发，测试中全部替换为桩
        self._patch(mock.patch.object(mail_module, "MailService", self._fake_mail_service()))
        self._patch(mock.patch.object(scan_service, "AutoFillService", mock.MagicMock()))
        self._patch(mock.patch.object(scan_service, "CatalogExtractService", mock.MagicMock()))

    def tearDown(self):
        scan_service.CONF["SEND_MAIL_FOR_NEW_BOOKS"] = self._old_mail_flag
        self.session.remove()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def _fake_mail_service(self):
        calls = self.mail_calls

        class FakeMailService:
            def send_new_book_notification(self, emails, book_names, site_url=""):
                calls.append((list(emails), list(book_names)))

        return FakeMailService

    def _touch_txt(self, name="a.txt"):
        path = os.path.join(self.tmpdir, name)
        with open(path, "wb") as f:
            f.write(b"hello sole test")
        return path

    def _add_active_reader(self, email="reader@example.com"):
        r = Reader()
        r.username = "reader"
        r.email = email
        r.active = 1
        # 生产环境 Reader.extra 恒含 upload_history 等键（非空 dict）；邮件开关判断是
        # `if r.extra and r.extra.get(...)`, 空 dict 会短路跳过该读者
        r.extra = {"kindle_email": ""}
        self.session.add(r)
        self.session.commit()
        return r

    def _run_import(self, sole=None):
        """跑真实 do_import_internal（Phase1 扫描真文件 + 真worker线程），_import_one_file 打桩捕获 sole。"""
        fpath = self._touch_txt()
        captured = []

        def fake_import_one_file(row, user_id, scan_upload_path, session, force, sole=False, *args, **kwargs):
            captured.append(sole)
            return 501, None

        self.svc._import_one_file = fake_import_one_file
        if sole is None:
            self.svc.do_import_internal([fpath], 9)
        else:
            self.svc.do_import_internal([fpath], 9, sole=sole)
        return captured

    def test_sole_true_reaches_import_one_file(self):
        self.assertEqual(self._run_import(sole=True), [True])

    def test_sole_false_reaches_import_one_file(self):
        self.assertEqual(self._run_import(sole=False), [False])

    def test_default_sole_is_false(self):
        self.assertEqual(self._run_import(), [False])

    def test_worker_passes_sole_to_import_one_file(self):
        path = self._touch_txt("w.txt")
        row = ScanFile(path, "sha256:1", 1)
        row.status = ScanFile.READY
        self.session.add(row)
        self.session.commit()

        captured = []

        def fake_import_one_file(row, user_id, scan_upload_path, session, force, sole=False, *args, **kwargs):
            captured.append(sole)
            return None, None

        self.svc._import_one_file = fake_import_one_file
        work_queue = _queue.Queue()
        work_queue.put(row.id)
        work_queue.put(None)  # sentinel: Phase 1 done
        imported = []
        self.svc._importing_worker(work_queue, imported, None, 9, self.tmpdir, 20, False, True)
        self.assertEqual(captured, [True])
        self.assertEqual(imported, [])

    def test_sole_true_skips_new_book_mail(self):
        self._add_active_reader()
        scan_service.CONF["SEND_MAIL_FOR_NEW_BOOKS"] = True
        self.assertEqual(self._run_import(sole=True), [True])
        self.assertEqual(self.mail_calls, [])

    def test_sole_false_sends_new_book_mail(self):
        reader = self._add_active_reader()
        scan_service.CONF["SEND_MAIL_FOR_NEW_BOOKS"] = True
        self.assertEqual(self._run_import(sole=False), [False])
        self.assertEqual(len(self.mail_calls), 1)
        emails, book_names = self.mail_calls[0]
        self.assertEqual(emails, [reader.email])
        self.assertEqual(book_names, ["私藏书A"])


if __name__ == "__main__":
    unittest.main()
