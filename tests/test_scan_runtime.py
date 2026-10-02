#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""扫描导入运行时工具与批量事务的离线单元测试。

纯单元测试：内存/文件 sqlite + 临时文件，不依赖 tornado 服务与 calibre
（calibre 相关调用一律 mock）。覆盖：
- scan_runtime.file_signature 的稳定性、变化检测与不可判定语义
- scan_runtime.MetadataCache 的命中/签名失效/逐出/副本隔离
- ScanService 批量事务：批内只 flush 不提交、批尾提交可见、行级 SAVEPOINT
  失败不拖垮整批、提交失败整批回滚
- ScanService._scan_one_file 的哈希复用签名门槛与签名持久化
- ScanService._import_one_file 的导入前签名复核（文件被替换回退 NEW、
  签名一致不拦）
- ScanService._remove_imported_file 的签名复核
- ScanService._collect_imported_path 游标分批与 NULL import_id 兜底
- ScanService.resolve_ready_paths 跨批（>500 行）分页
- ScanService._parse_metadata_cached / _metadata_prefetch_worker 缓存与预取
- ScanService._importing_worker 的批提交节奏、取消排空与致命错误回传
"""

import copy
import os
import queue
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import sqlalchemy
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import models
from webserver.models import ScanFile
from webserver.base.book_files import InvalidBookFileError
from webserver.services.scan_runtime import MetadataCache, file_signature
from webserver.services.scan_service import ScanService


class _Deepcopyable:
    """模拟 calibre Metadata：带自有 deepcopy 方法的可变对象。"""

    def __init__(self, title):
        self.title = title

    def deepcopy(self):
        return copy.deepcopy(self)


class FileSignatureTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="scan_runtime_test_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _path(self, name="a.epub"):
        return os.path.join(self.tmpdir, name)

    def test_stable_for_unchanged_file(self):
        path = self._path()
        with open(path, "wb") as f:
            f.write(b"hello")
        self.assertEqual(file_signature(path), file_signature(path))

    def test_changes_when_content_and_mtime_change(self):
        path = self._path()
        with open(path, "wb") as f:
            f.write(b"hello")
        old = file_signature(path)
        with open(path, "wb") as f:
            f.write(b"world!")
        os.utime(path, ns=(old[3] + 10_000_000, old[4] + 10_000_000))
        self.assertNotEqual(old, file_signature(path))

    def test_missing_file_returns_none(self):
        self.assertIsNone(file_signature(os.path.join(self.tmpdir, "gone.epub")))

    def test_symlink_returns_none(self):
        target = self._path()
        with open(target, "wb") as f:
            f.write(b"x")
        link = self._path("link.epub")
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink not available on this platform/account")
        self.assertIsNone(file_signature(link))


class MetadataCacheTest(unittest.TestCase):
    def test_roundtrip_and_expiry_by_signature(self):
        cache = MetadataCache()
        cache.put("/a", [1, 2], {"metadata": _Deepcopyable("A")})
        self.assertEqual(cache.get("/a", [1, 2])["metadata"].title, "A")
        # 签名不一致即失效，且条目被剔除
        self.assertIsNone(cache.get("/a", [1, 2, 3]))
        cache.put("/a", [1, 2], {"metadata": _Deepcopyable("A")})
        cache.get("/a", [9, 9])
        self.assertIsNone(cache.get("/a", [1, 2]))

    def test_returned_copy_is_independent(self):
        cache = MetadataCache()
        cache.put("/a", [1], {"metadata": _Deepcopyable("A"), "note": ["keep"]})
        got = cache.get("/a", [1])
        got["metadata"].title = "MUTATED"
        got["note"].append("dirty")
        again = cache.get("/a", [1])
        self.assertEqual(again["metadata"].title, "A")
        self.assertEqual(again["note"], ["keep"])

    def test_capacity_eviction(self):
        cache = MetadataCache(capacity=2)
        for i in range(3):
            cache.put("/p%d" % i, [i], {"metadata": _Deepcopyable(str(i))})
        self.assertIsNone(cache.get("/p0", [0]))
        self.assertIsNotNone(cache.get("/p2", [2]))

    def test_oversized_entry_not_cached(self):
        cache = MetadataCache(capacity=8, byte_limit=64)
        cache.put("/big", [1], {"metadata": _Deepcopyable("x" * 4096)})
        self.assertIsNone(cache.get("/big", [1]))


class ScanServiceBatchTestBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="scan_batch_test_")
        self.dbpath = os.path.join(self.tmpdir, "app.db")
        self.engine = create_engine("sqlite:///%s" % self.dbpath)
        self.session = scoped_session(sessionmaker(bind=self.engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(self.engine)
        self.service = ScanService()
        self.service.session = self.session
        # 类级缓存按测试隔离
        ScanService._metadata_cache = MetadataCache()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _row(self, path, hash_value="sha256:a", status=ScanFile.READY, import_id=1):
        row = ScanFile(path, hash_value, import_id)
        row.status = status
        self.session.add(row)
        self.session.flush()
        return row


class SaveOrRollbackBatchTest(ScanServiceBatchTestBase):
    def test_non_batch_commits_immediately(self):
        row = self._row("p1")
        row.status = ScanFile.INVALID
        self.assertTrue(self.service.save_or_rollback(row, self.session))
        self.session.rollback()
        self.assertEqual(
            self.session.query(ScanFile).filter(ScanFile.id == row.id).one().status, ScanFile.INVALID
        )

    def test_batch_flush_only_until_commit(self):
        row = self._row("p1")
        self.session.commit()  # 批前的已提交基线：READY
        row.status = ScanFile.INVALID
        self.service._begin_import_batch(self.session)
        self.assertTrue(self.service.save_or_rollback(row, self.session))
        # 批内未提交：另一个连接看到的仍是 READY
        probe = create_engine("sqlite:///%s" % self.dbpath)
        try:
            with probe.connect() as conn:
                val = conn.execute(
                    sqlalchemy.text("SELECT status FROM scanfiles WHERE id=:i"), {"i": row.id}
                ).scalar()
            self.assertEqual(val, ScanFile.READY)
            self.service._commit_import_batch(self.session)
            with probe.connect() as conn:
                val = conn.execute(
                    sqlalchemy.text("SELECT status FROM scanfiles WHERE id=:i"), {"i": row.id}
                ).scalar()
            self.assertEqual(val, ScanFile.INVALID)
        finally:
            probe.dispose()

    def test_savepoint_failure_does_not_poison_batch(self):
        # 手工造 hash 唯一约束，制造行级 IntegrityError
        self.session.execute(text("CREATE UNIQUE INDEX ux_test_hash ON scanfiles (hash)"))
        self.session.commit()
        first = self._row("p1", hash_value="sha256:one")
        row = self._row("p2", hash_value="sha256:two")
        self.session.commit()

        self.service._begin_import_batch(self.session)
        with self.assertRaises(IntegrityError):
            with self.session.begin_nested():
                # 与已提交行的 hash 冲突 → flush 失败 → 批模式原样上抛
                row.hash = "sha256:one"
                self.service.save_or_rollback(row, self.session)
        # 行级失败被保存点回滚：该行回到批前状态
        row.status
        self.assertEqual(row.hash, "sha256:two")
        # 批内其它变更照常提交
        first.title = "touched-in-batch"
        self.assertTrue(self.service.save_or_rollback(first, self.session))
        self.service._commit_import_batch(self.session)
        self.assertEqual(self.session.query(ScanFile).filter(ScanFile.id == row.id).one().hash, "sha256:two")
        self.assertEqual(self.session.query(ScanFile).filter(ScanFile.id == first.id).one().title, "touched-in-batch")
        self.assertFalse(getattr(self.service._local, "import_batch", False))

    def test_commit_failure_rolls_back_whole_batch(self):
        row = self._row("p1")
        self.session.commit()  # 批前基线：READY
        row.status = ScanFile.INVALID
        self.service._begin_import_batch(self.session)
        self.assertTrue(self.service.save_or_rollback(row, self.session))
        with mock.patch.object(self.session, "commit", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                self.service._commit_import_batch(self.session)
        # 整批回滚 + 标志复位：另一个连接看到的仍是批前的 READY
        self.assertFalse(getattr(self.service._local, "import_batch", False))
        probe = create_engine("sqlite:///%s" % self.dbpath)
        try:
            with probe.connect() as conn:
                val = conn.execute(
                    sqlalchemy.text("SELECT status FROM scanfiles WHERE id=:i"), {"i": row.id}
                ).scalar()
            self.assertEqual(val, ScanFile.READY)
        finally:
            probe.dispose()


class ImportOneFileSignatureTest(ScanServiceBatchTestBase):
    def test_reverts_to_new_when_file_changed_after_scan(self):
        path = os.path.join(self.tmpdir, "book.epub")
        with open(path, "wb") as f:
            f.write(b"old content")
        row = self._row(path)
        row.data = {"file_signature": [9, 9, 9, 9, 9]}  # 与当前 stat 必然不同
        self.session.commit()

        book_id, status = self.service._import_one_file(
            row, user_id=1, scan_upload_path=self.tmpdir, session=self.session, force=False
        )
        self.assertIsNone(book_id)
        self.assertEqual(status, ScanFile.NEW)
        self.assertEqual(row.status, ScanFile.NEW)
        self.assertEqual(row.data.get("processing_error"), "文件在导入前已变化，请重新扫描")

    def test_matching_signature_passes_the_gate(self):
        """签名一致时不拦：走到 validate 分支（mock 其失败 → INVALID 而非 NEW）。

        calibre 未安装的环境用 sys.modules 假模块顶住函数内的 calibre import。
        """
        path = os.path.join(self.tmpdir, "book.epub")
        with open(path, "wb") as f:
            f.write(b"content")
        row = self._row(path)
        row.data = {"file_signature": file_signature(path)}
        self.session.commit()
        fake_calibre = mock.MagicMock()
        with mock.patch.dict(sys.modules, {"calibre.ebooks.metadata.book.base": fake_calibre}), \
                mock.patch("webserver.services.scan_service.validate_book_file",
                           side_effect=InvalidBookFileError("bad file")):
            book_id, status = self.service._import_one_file(
                row, user_id=1, scan_upload_path=self.tmpdir, session=self.session, force=False
            )
        self.assertIsNone(book_id)
        self.assertEqual(status, ScanFile.INVALID)


class RemoveImportedFileTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="scan_rm_test_")
        self.path = os.path.join(self.tmpdir, "book.epub")
        with open(self.path, "wb") as f:
            f.write(b"content")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_matching_signature_removes(self):
        sig = file_signature(self.path)
        self.assertTrue(ScanService._remove_imported_file(self.path, expected_signature=sig))
        self.assertFalse(os.path.exists(self.path))

    def test_mismatched_signature_retains(self):
        self.assertFalse(ScanService._remove_imported_file(self.path, expected_signature=[9, 9, 9, 9, 9]))
        self.assertTrue(os.path.exists(self.path))

    def test_no_signature_keeps_legacy_behavior(self):
        self.assertTrue(ScanService._remove_imported_file(self.path))
        self.assertFalse(os.path.exists(self.path))


class ScanOneFileSignatureTest(ScanServiceBatchTestBase):
    def _make_file(self, name="book.epub", content=b"content"):
        path = os.path.join(self.tmpdir, name)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def test_fresh_scan_persists_signature(self):
        path = self._make_file()
        row_id, state = self.service._scan_one_file(path, self.session, 1, set(), set(), force=False)
        self.assertIsNotNone(row_id)
        self.assertEqual(state, ScanFile.READY)
        row = self.session.query(ScanFile).filter(ScanFile.id == row_id).one()
        self.assertEqual(row.data.get("file_signature"), file_signature(path))

    def test_hash_reuse_requires_matching_signature(self):
        path = self._make_file()
        row_id, _ = self.service._scan_one_file(path, self.session, 1, set(), set(), force=False)
        first_hash = self.session.query(ScanFile).filter(ScanFile.id == row_id).one().hash
        self.session.expunge_all()

        # 签名一致 → 复用缓存哈希（_compute_hash 不应被调用）
        with mock.patch.object(self.service, "_compute_hash", side_effect=AssertionError("should reuse")):
            row_id2, state2 = self.service._scan_one_file(path, self.session, 2, set(), set(), force=False)
        self.assertIsNotNone(row_id2)
        self.assertEqual(state2, ScanFile.READY)
        self.assertEqual(self.session.query(ScanFile).filter(ScanFile.id == row_id2).one().hash, first_hash)

        # 签名不符（模拟文件被替换）→ 重算
        self.session.expunge_all()
        stale = self.session.query(ScanFile).filter(ScanFile.id == row_id2).one()
        stale.data = dict(stale.data or {})
        stale.data["file_signature"] = [9, 9, 9, 9, 9]
        self.session.commit()
        with mock.patch.object(self.service, "_compute_hash", return_value=("sha256:recomputed", None)) as m_hash:
            row_id3, _ = self.service._scan_one_file(path, self.session, 3, set(), set(), force=False)
        m_hash.assert_called_once()
        self.assertEqual(
            self.session.query(ScanFile).filter(ScanFile.id == row_id3).one().hash, "sha256:recomputed"
        )

    def test_legacy_row_without_signature_recomputes(self):
        path = self._make_file()
        legacy = self._row(path, hash_value="sha256:legacy", status=ScanFile.READY)
        legacy.data = {}
        self.session.commit()
        with mock.patch.object(self.service, "_compute_hash", return_value=("sha256:fresh", None)) as m_hash:
            self.service._scan_one_file(path, self.session, 1, set(), set(), force=False)
        m_hash.assert_called_once()


class CollectImportedPathTest(ScanServiceBatchTestBase):
    def _imported(self, path, import_id):
        row = ScanFile(path, "sha256:%d" % abs(hash(path)), import_id)
        row.status = ScanFile.IMPORTED
        self.session.add(row)

    def test_keyset_pagination_matches_legacy_semantics(self):
        dir_a = os.path.join(self.tmpdir, "a")
        dir_b = os.path.join(self.tmpdir, "b")
        os.makedirs(dir_a)
        os.makedirs(dir_b)
        # 两个 import 批次、两个目录，跨 500 的分页边界
        for i in range(600):
            self._imported(os.path.join(dir_a, "f%d.epub" % i), import_id=100)
        for i in range(30):
            self._imported(os.path.join(dir_b, "g%d.epub" % i), import_id=200)
        self.session.commit()

        # 最新批次是 200（dir_b）→ last_imported_dir=dir_b，dir_a 整目录进 dirs
        dirs, files_in_last_dir, last_import_id = self.service._collect_imported_path(skip_last=False)
        self.assertEqual(last_import_id, 200)
        self.assertEqual(
            set(files_in_last_dir),
            {os.path.realpath(os.path.join(dir_b, "g%d.epub" % i)) for i in range(30)},
        )
        self.assertIn(os.path.realpath(dir_a), dirs)
        self.assertNotIn(os.path.realpath(dir_b), dirs)

    def test_skip_last_only_loads_last_batch(self):
        dir_a = os.path.join(self.tmpdir, "a")
        os.makedirs(dir_a)
        for i in range(3):
            self._imported(os.path.join(dir_a, "f%d.epub" % i), import_id=100)
        self.session.commit()
        dirs, files_in_last_dir, last_import_id = self.service._collect_imported_path(skip_last=True)
        self.assertEqual(last_import_id, 100)
        self.assertEqual(len(files_in_last_dir), 3)

    def test_null_import_id_rows_still_contribute_dirs(self):
        # NULL import_id 的存量行不参与 (import_id, id) 键集比较，单独兜底并入：
        # 更新的非 NULL 批次确定 last 目录，NULL 行所在目录进 dirs（等价旧排序中的末尾段）
        dir_a = os.path.join(self.tmpdir, "a")
        dir_c = os.path.join(self.tmpdir, "c")
        os.makedirs(dir_a)
        os.makedirs(dir_c)
        self._imported(os.path.join(dir_a, "x.epub"), import_id=100)
        row = ScanFile(os.path.join(dir_c, "n.epub"), "sha256:n", None)
        row.status = ScanFile.IMPORTED
        self.session.add(row)
        self.session.commit()
        dirs, files_in_last_dir, last_import_id = self.service._collect_imported_path(skip_last=False)
        self.assertEqual(last_import_id, 100)
        self.assertIn(os.path.realpath(dir_c), dirs)
        self.assertIn(os.path.realpath(os.path.join(dir_a, "x.epub")), files_in_last_dir)


class ResolveReadyPaginationTest(ScanServiceBatchTestBase):
    def test_more_than_one_batch(self):
        paths = []
        for i in range(520):
            p = os.path.join(self.tmpdir, "f%d.epub" % i)
            with open(p, "wb") as f:
                f.write(b"x")
            paths.append(p)
            self._row(p)
        self.session.commit()
        got = ScanService.resolve_ready_paths(self.session)
        self.assertEqual(sorted(got), sorted(paths))


class MetadataParseCacheTest(ScanServiceBatchTestBase):
    def test_cache_hit_avoids_reparse(self):
        path = os.path.join(self.tmpdir, "book.epub")
        with open(path, "wb") as f:
            f.write(b"content")
        with mock.patch("webserver.services.scan_service.read_book_metadata",
                        side_effect=[_Deepcopyable("T1"), _Deepcopyable("T2")]) as m_read:
            mi1 = self.service._parse_metadata_cached(path, "epub", "book.epub")
            mi2 = self.service._parse_metadata_cached(path, "epub", "book.epub")
            self.assertEqual(m_read.call_count, 1)
        self.assertEqual(mi1.title, "T1")
        self.assertEqual(mi2.title, "T1")
        # 命中返回的是副本：改写不污染缓存
        mi2.title = "MUTATED"
        with mock.patch("webserver.services.scan_service.read_book_metadata") as m_read2:
            self.assertEqual(self.service._parse_metadata_cached(path, "epub", "book.epub").title, "T1")
            m_read2.assert_not_called()

    def test_signature_change_forces_reparse(self):
        path = os.path.join(self.tmpdir, "book.epub")
        with open(path, "wb") as f:
            f.write(b"content")
        sig = file_signature(path)
        with mock.patch("webserver.services.scan_service.read_book_metadata",
                        side_effect=[_Deepcopyable("T1"), _Deepcopyable("T2")]) as m_read:
            self.service._parse_metadata_cached(path, "epub", "book.epub")
            # 文件被替换（内容 + mtime 变化）
            with open(path, "wb") as f:
                f.write(b"replaced!")
            os.utime(path, ns=(sig[3] + 10_000_000, sig[4] + 10_000_000))
            mi = self.service._parse_metadata_cached(path, "epub", "book.epub")
        self.assertEqual(m_read.call_count, 2)
        self.assertEqual(mi.title, "T2")

    def test_prefetch_worker_fills_cache(self):
        path = os.path.join(self.tmpdir, "book.epub")
        with open(path, "wb") as f:
            f.write(b"content")
        prefetch_queue = queue.Queue()
        done = threading.Event()
        ScanService.static_abort_flag = False
        try:
            with mock.patch("webserver.services.scan_service.read_book_metadata",
                            return_value=_Deepcopyable("T")) as m_read:
                prefetch_queue.put((path, "epub", "book.epub"))
                worker = threading.Thread(
                    target=self.service._metadata_prefetch_worker, args=(prefetch_queue, done)
                )
                worker.start()
                deadline = time.time() + 5
                while m_read.call_count == 0 and time.time() < deadline:
                    time.sleep(0.02)
                self.assertEqual(m_read.call_count, 1)
            done.set()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            cached = self.service._metadata_cache.get(path, file_signature(path))
            self.assertEqual(cached["metadata"].title, "T")
        finally:
            done.set()
            ScanService.static_abort_flag = False


class ImportingWorkerBatchTest(ScanServiceBatchTestBase):
    """worker 级批量事务集成测试：_import_one_file 全 mock，不依赖 calibre。"""

    def _feed(self, count):
        import queue as _q
        ids = []
        for i in range(count):
            p = os.path.join(self.tmpdir, "f%d.epub" % i)
            with open(p, "wb") as f:
                f.write(b"x")
            ids.append(self._row(p).id)
        self.session.commit()
        q = _q.Queue()
        for rid in ids:
            q.put(rid)
        q.put(None)  # sentinel: Phase 1 done
        return q

    def test_worker_commits_in_batches(self):
        q = self._feed(45)  # batch_size=20 → 3 次批提交（20/20/5）
        imported = []

        def fake_import(row, *a, **k):
            row.status = ScanFile.IMPORTED
            return row.id, ScanFile.IMPORTED

        with mock.patch.object(self.service, "scoped_session", return_value=self.session), \
                mock.patch.object(self.service, "_import_one_file", side_effect=fake_import) as m_imp:
            self.service._importing_worker(q, imported, None, 1, self.tmpdir, 20, False)
        self.assertEqual(m_imp.call_count, 45)
        self.assertEqual(len(imported), 45)
        # 全部已提交：另一个连接可见
        probe = create_engine("sqlite:///%s" % self.dbpath)
        try:
            with probe.connect() as conn:
                n = conn.execute(
                    sqlalchemy.text("SELECT count(*) FROM scanfiles WHERE status=:s"), {"s": ScanFile.IMPORTED}
                ).scalar()
            self.assertEqual(n, 45)
        finally:
            probe.dispose()

    def test_worker_abort_drains_queue_without_importing(self):
        q = self._feed(3)
        ScanService.static_abort_flag = True
        try:
            with mock.patch.object(self.service, "scoped_session", return_value=self.session), \
                    mock.patch.object(self.service, "_import_one_file",
                                      side_effect=AssertionError("should not import when aborted")):
                self.service._importing_worker(q, [], None, 1, self.tmpdir, 20, False)
        finally:
            ScanService.static_abort_flag = False
        probe = create_engine("sqlite:///%s" % self.dbpath)
        try:
            with probe.connect() as conn:
                n = conn.execute(
                    sqlalchemy.text("SELECT count(*) FROM scanfiles WHERE status=:s"), {"s": ScanFile.READY}
                ).scalar()
            self.assertEqual(n, 3)
        finally:
            probe.dispose()

    def test_worker_fatal_error_recorded_on_commit_failure(self):
        q = self._feed(3)
        with mock.patch.object(self.service, "scoped_session", return_value=self.session), \
                mock.patch.object(self.session, "commit", side_effect=RuntimeError("disk full")), \
                mock.patch.object(self.service, "_import_one_file",
                                  side_effect=lambda row, *a, **k: (None, ScanFile.IMPORTED)):
            self.service._importing_worker(q, [], None, 1, self.tmpdir, 1, False)
        # 批提交失败 → worker 记录致命错误（do_import_internal 在 join 后据此显式失败）
        self.assertIsNotNone(self.service._worker_error)
        self.service._worker_error = None


if __name__ == "__main__":
    unittest.main()
