"""目录快照增量扫描（mtime+size 方案）回归测试。

覆盖：快照剪枝/深层新增检出/签名复用与失效/TOCTOU 撕裂/VACUUM/
abort 熔断/scope 归一/locale 键。Windows 直跑（无 calibre 依赖）。
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool

from webserver import constants
from webserver import models
from webserver.models import ScanDirSnapshot, ScanFile
from webserver.services import scan_service
from webserver.services.scan_service import ScanService


class SnapshotTestBase(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)
        self.tmpdir = tempfile.mkdtemp(prefix="scan_snapshot_test_")
        self.root = os.path.realpath(self.tmpdir)
        self.svc = ScanService()
        self.svc.session = self.session
        self.svc.scoped_session = self.session
        self._conf_backup = dict(scan_service.CONF)
        scan_service.CONF["scan_upload_path"] = self.tmpdir

    def tearDown(self):
        scan_service.CONF.clear()
        scan_service.CONF.update(self._conf_backup)
        self.session.remove()
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        ScanService.static_abort_flag = False
        ScanService.static_is_importing = False
        ScanService.static_import_user_id = 0

    def _touch(self, relpath, content=b"x"):
        path = os.path.join(self.tmpdir, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def _collect(self, use_snapshot=True):
        return self.svc._collect_files([self.tmpdir], use_snapshot=use_snapshot)

    def _commit(self, visited):
        self.svc._commit_dir_snapshots(self.session, visited, self.root)


class TestSnapshotPrune(SnapshotTestBase):
    def test_second_run_collects_nothing(self):
        self._touch(os.path.join("d1", "a.txt"), b"aaa")
        self._touch(os.path.join("d2", "b.txt"), b"bbb")
        files, visited = self._collect()
        self.assertEqual(len(files), 2)
        self.assertTrue(len(visited) >= 3)  # root + d1 + d2
        self._commit(visited)
        files2, visited2 = self._collect()
        self.assertEqual(files2, [])
        self.assertEqual(visited2, {})

    def test_deep_new_file_detected_despite_matched_ancestors(self):
        # 祖先目录 mtime 不变时仍必须下钻：深层新增只 bump 直接父目录。
        # 本用例在“剪下钻”实现下失败，是核心回归钉。
        self._touch(os.path.join("d1", "sub", "old.txt"), b"old")
        files, visited = self._collect()
        self.assertEqual(len(files), 1)
        self._commit(visited)
        new_path = self._touch(os.path.join("d1", "sub", "new.txt"), b"new-bytes")
        files2, _visited2 = self._collect()
        # 变化目录里的老文件会被重新枚举（去重是 Phase1 的活）；关键是深层新文件
        # 必须出现——“剪下钻”的错误实现在这里返回 []。
        old_path = os.path.join(self.tmpdir, "d1", "sub", "old.txt")
        self.assertEqual(sorted(files2), sorted([old_path, new_path]))

    def test_new_subdir_detected(self):
        self._touch(os.path.join("d1", "a.txt"), b"a")
        _files, visited = self._collect()
        self._commit(visited)
        self._touch(os.path.join("brandnew", "c.txt"), b"c")
        files2, _visited2 = self._collect()
        self.assertEqual(len(files2), 1)
        self.assertTrue(files2[0].endswith("c.txt"))

    def test_bypass_flag_walks_fully(self):
        self._touch(os.path.join("d1", "a.txt"), b"a")
        _files, visited = self._collect()
        self._commit(visited)
        files2, _visited2 = self.svc._collect_files([self.tmpdir], use_snapshot=False)
        self.assertEqual(len(files2), 1)


class TestFileSignature(SnapshotTestBase):
    def _row(self, path, hash_val="sha256:cached", status=ScanFile.NEW, sig=None):
        row = ScanFile(path, hash_val, 1)
        row.status = status
        if sig is not None:
            row.data = {scan_service.FILE_SIG_KEY: sig}
        self.session.add(row)
        self.session.commit()
        return row

    def test_sig_match_reuses_hash(self):
        fpath = self._touch("s.txt", b"sig-content")
        sig = ScanService.file_signature(fpath)
        self.assertIsNotNone(sig)
        self._row(fpath, sig=sig)
        staged = []
        with mock.patch.object(ScanService, "_compute_hash") as hc:
            rid, state = self.svc._scan_one_file(fpath, self.session, 1, set(), set(), False, staged=staged)
        hc.assert_not_called()
        self.assertEqual(state, ScanFile.READY)
        self.assertEqual(staged[-1][0], "save")
        self.assertEqual(staged[-1][1].hash, "sha256:cached")

    def test_sig_mismatch_recomputes(self):
        fpath = self._touch("m.txt", b"mismatch-content")
        self._row(fpath, sig=[0, 0, 0, 0])
        staged = []
        with mock.patch.object(
            ScanService, "_compute_hash", return_value=("sha256:fresh", None)
        ) as hc:
            _rid, state = self.svc._scan_one_file(fpath, self.session, 1, set(), set(), False, staged=staged)
        hc.assert_called_once_with(fpath)
        self.assertEqual(state, ScanFile.READY)
        self.assertEqual(staged[-1][1].hash, "sha256:fresh")

    def test_legacy_row_without_sig_recomputes(self):
        fpath = self._touch("legacy.txt", b"legacy-content")
        self._row(fpath)  # 无 data 签名
        staged = []
        with mock.patch.object(
            ScanService, "_compute_hash", return_value=("sha256:re", None)
        ) as hc:
            _rid, state = self.svc._scan_one_file(fpath, self.session, 1, set(), set(), False, staged=staged)
        hc.assert_called_once_with(fpath)
        self.assertEqual(state, ScanFile.READY)

    def test_torn_read_defers_to_next_run(self):
        fpath = self._touch("torn.txt", b"torn-content")
        staged = []
        with mock.patch.object(
            ScanService, "file_signature", side_effect=[[1, 2, 3, 4], [9, 9, 9, 9]]
        ):
            with mock.patch.object(
                ScanService, "_compute_hash", return_value=("sha256:torn", None)
            ):
                _rid, state = self.svc._scan_one_file(
                    fpath, self.session, 1, set(), set(), False, staged=staged
                )
        # 哈希前后签名不一致：空哈希 NEW 行占位，不入库撕裂哈希
        self.assertEqual(state, ScanFile.NEW)
        kind, row, st = staged[-1]
        self.assertEqual(kind, "save")
        self.assertEqual((row.hash, st), ("", ScanFile.NEW))

    def test_file_signature_none_on_missing(self):
        self.assertIsNone(ScanService.file_signature(os.path.join(self.tmpdir, "nope.txt")))


class TestSnapshotCommit(SnapshotTestBase):
    def test_vacuum_removes_gone_and_foreign_dirs(self):
        keep = os.path.join(self.tmpdir, "keep")
        os.makedirs(keep)
        gone = os.path.join(self.tmpdir, "gone")
        self.session.add(ScanDirSnapshot(os.path.realpath(keep), 1, 1))
        self.session.add(ScanDirSnapshot(os.path.realpath(gone), 2, 2))
        self.session.add(ScanDirSnapshot("/elsewhere/foreign", 3, 3))
        self.session.commit()
        self.svc._commit_dir_snapshots(self.session, {os.path.realpath(keep): (100, 1)}, self.root)
        remaining = sorted(d for (d,) in self.session.query(ScanDirSnapshot.dir).all())
        self.assertEqual(remaining, [os.path.realpath(keep)])
        row = self.session.query(ScanDirSnapshot).filter(
            ScanDirSnapshot.dir == os.path.realpath(keep)
        ).one()
        self.assertEqual((row.mtime_ns, row.entry_count), (100, 1))

    def test_abort_skips_commit(self):
        ScanService.static_abort_flag = True
        try:
            self.svc._commit_dir_snapshots(
                self.session, {os.path.realpath(self.tmpdir): (1, 1)}, self.root
            )
        finally:
            ScanService.static_abort_flag = False
        self.assertEqual(self.session.query(ScanDirSnapshot).count(), 0)

    def test_empty_root_noop(self):
        self.svc._commit_dir_snapshots(self.session, {"x": (1, 1)}, "")
        self.assertEqual(self.session.query(ScanDirSnapshot).count(), 0)


class TestScopeNormalize(SnapshotTestBase):
    def test_legacy_scopes_map_to_full(self):
        self.assertEqual(ScanService._normalize_scope(1), 0)
        self.assertEqual(ScanService._normalize_scope(2), 0)

    def test_current_scopes_pass_through(self):
        self.assertEqual(ScanService._normalize_scope(0), 0)
        self.assertEqual(ScanService._normalize_scope(3), 3)
        self.assertEqual(ScanService._normalize_scope(4), 4)

    def test_collect_imported_path_deleted(self):
        self.assertFalse(hasattr(ScanService, "_collect_imported_path"))


class TestPendingUnion(SnapshotTestBase):
    def _row(self, path, status, import_type=0):
        row = ScanFile(path, "", 1)
        row.status = status
        row.import_type = import_type
        self.session.add(row)
        self.session.commit()
        return row

    def test_stalled_rows_requeued_despite_prune(self):
        # 剪枝目录里躺着三类行：torn 占位 NEW、修好待重试 INVALID/PERMISSION。
        # DROP/IMPORTED/有声书行不并入（有声书必须是真实文件路径 + import_type=2，
        # 才真正考验 ebook_scan_filter 而非 isfile/扩展名顺带排除）。
        # 所有文件先建好、先快照，第二轮全目录剪枝 —— 此时 filelist 只能来自并集。
        old = self._touch(os.path.join("d1", "old.txt"), b"old-bytes")
        bad = self._touch(os.path.join("d1", "bad.txt"), b"bad-bytes")
        perm = self._touch(os.path.join("d1", "perm.txt"), b"perm-bytes")
        drop = self._touch(os.path.join("d1", "drop.txt"), b"drop-bytes")
        imp = self._touch(os.path.join("d1", "imp.txt"), b"imp-bytes")
        audio_file = self._touch(os.path.join("audiobooks", "a.epub"), b"audio-bytes")
        files, visited = self._collect()
        self.assertEqual(len(files), 6)
        self._commit(visited)
        self.assertEqual(self.session.query(ScanDirSnapshot).count(), 3)  # root + d1 + audiobooks
        self._row(old, ScanFile.NEW)
        self._row(bad, ScanFile.INVALID)
        self._row(perm, ScanFile.PERMISSION)
        self._row(drop, ScanFile.DROP)
        self._row(imp, ScanFile.IMPORTED)
        self._row(audio_file, ScanFile.INVALID, import_type=constants.IMPORT_TYPE_AUDIOBOOK)
        files2, visited2 = self._collect()
        self.assertEqual(visited2, {})  # 全目录剪枝，走的是并集
        self.assertEqual(sorted(files2), sorted([old, bad, perm]))

    def test_force_skips_reuse_and_prune(self):
        fpath = self._touch("f.txt", b"force-content")
        sig = ScanService.file_signature(fpath)
        row = ScanFile(fpath, "sha256:cached", 1)
        row.status = ScanFile.NEW
        row.data = {scan_service.FILE_SIG_KEY: sig}
        self.session.add(row)
        self.session.commit()
        staged = []
        with mock.patch.object(
            ScanService, "_compute_hash", return_value=("sha256:re", None)
        ) as hc:
            _rid, state = self.svc._scan_one_file(
                fpath, self.session, 1, set(), set(), True, staged=staged
            )
        hc.assert_called_once_with(fpath)
        self.assertEqual(state, ScanFile.READY)
        self.assertTrue(ScanService._snapshot_active("all", True, 0) is False)


class TestSnapshotGating(SnapshotTestBase):
    def test_snapshot_active_matrix(self):
        active = ScanService._snapshot_active
        self.assertTrue(active(None, False, 0))
        self.assertTrue(active("all", False, 0))
        self.assertFalse(active(["/x"], False, 0))
        self.assertFalse(active(["/d"], False, 3))  # dirs 选择器到这里已是路径数组
        self.assertFalse(active("all", True, 0))
        self.assertFalse(active("all", False, 4))
        self.assertFalse(active("all", False, 3))  # 选项 3 即使误传 all 也不剪枝

    def test_normalize_coerces_types(self):
        norm = ScanService._normalize_scope
        self.assertEqual(norm("1"), 0)
        self.assertEqual(norm("4"), 4)
        self.assertEqual(norm("bogus"), 0)
        self.assertEqual(norm(None), 0)
        self.assertEqual(norm(0), 0)
        self.assertEqual(norm(float("inf")), 0)  # OverflowError 不外抛


class TestDoImportWiring(SnapshotTestBase):
    def test_empty_filelist_still_commits_snapshot(self):
        # 只有非扫描格式的目录：filelist 为空也应提交快照，否则每轮重走、增量失效
        self._touch("notes.md", b"not a book")
        # do_import 的注册器包装用的是 AsyncService 单例（与 ScanService 单例不同），
        # 需把测试 session 也挂上去，wrapper 才会同步执行在测试会话上。
        asc = scan_service.AsyncService()
        asc.db = None
        asc.scoped_session = self.session
        self.addCleanup(setattr, asc, "scoped_session", lambda: "no-session")
        with mock.patch.object(scan_service.AsyncService, "async_mode", lambda self: False):
            self.svc.do_import("all", 9)
        self.assertGreaterEqual(self.session.query(ScanDirSnapshot).count(), 1)


class TestNullData(SnapshotTestBase):
    def test_null_data_recomputes(self):
        # 真遗留 NULL（列默认 {} 是建库填充，老库手工行可能是 NULL）
        fpath = self._touch("nulldata.txt", b"nulldata-content")
        row = ScanFile(fpath, "sha256:old", 1)
        row.status = ScanFile.NEW
        self.session.add(row)
        self.session.commit()
        self.session.execute(text("UPDATE scanfiles SET data=NULL"))
        self.session.commit()
        staged = []
        with mock.patch.object(
            ScanService, "_compute_hash", return_value=("sha256:re", None)
        ) as hc:
            _rid, state = self.svc._scan_one_file(
                fpath, self.session, 1, set(), set(), False, staged=staged
            )
        hc.assert_called_once_with(fpath)
        self.assertEqual(state, ScanFile.READY)


class TestSnapshotLocales(unittest.TestCase):
    def test_scope_keys(self):
        # 本文件在 <worktree>/tests/ 下，locales 在 <worktree>/app/locales/
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("zh.json", "en.json", "zh-TW.json"):
            with open(os.path.join(root, "app", "locales", name), encoding="utf-8") as f:
                data = json.load(f)
            imports = data["imports"]
            self.assertIn("scan_scope_full_noskip", imports)
            self.assertNotIn("scan_scope_exclude_last", imports)
            self.assertNotIn("scan_scope_exclude_all", imports)


if __name__ == "__main__":
    unittest.main()
