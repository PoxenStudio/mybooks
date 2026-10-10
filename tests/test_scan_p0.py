"""P0 扫描导入加速回归测试（calibre 轻量检查 / Phase1 批量落库 / set_field 攒批）。

- 不依赖 calibre 的用例（has_id 存在性、回退路径、暂存可见性、行级隔离、
  行全送达、写锁不变量、put 投递守卫）Windows 直跑；
- 走真实 _import_one_file 的用例（同标题加格式、set_field 攒批、行失败诚实）
  需要 calibre（函数头 import Metadata），缺 calibre 时自动跳过，WSL 全量跑。
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

# apt 版 calibre（/usr/lib/calibre）需要解释器预置 extensions_location 等属性
# （与 /usr/bin/calibre 启动脚本一致）；没有该目录（Windows/CI）时直接跳过。
if not hasattr(sys, "extensions_location") and os.path.isdir("/usr/lib/calibre"):
    sys.path.insert(0, "/usr/lib/calibre")
    sys.resources_location = "/usr/share/calibre"
    sys.extensions_location = "/usr/lib/calibre/calibre/plugins"
    sys.executables_location = "/usr/bin"
    sys.system_plugins_location = None

from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool

from webserver import models
from webserver.models import ScanFile
from webserver.services import scan_service
from webserver.services.scan_service import ScanService
from webserver import constants

try:
    from calibre import force_unicode  # noqa: F401
    HAS_CALIBRE = True
except Exception:
    HAS_CALIBRE = False


class FakeNewAPI:
    def __init__(self, db):
        self._db = db
        self.has_id_calls = []
        self.set_field_calls = []
        self.fail_set_field = False

    def has_id(self, book_id):
        self.has_id_calls.append(book_id)
        return book_id in self._db._ids

    def set_field(self, name, mapping, **kwargs):
        self.set_field_calls.append((name, dict(mapping)))
        if self.fail_set_field:
            raise RuntimeError("fake set_field boom")

    def add_book(self, book_id, title):
        self._db._ids.add(book_id)
        self._db._titles[book_id] = title


class FakeBookMeta:
    """calibre get_metadata 返回的 Metadata 替身：属性访问 .formats + .get(自定义列)"""

    def __init__(self, book_type=0, formats=()):
        self._book_type = book_type
        self.formats = list(formats)

    def get(self, key, default=None):
        if key == constants.CALIBRE_COLUMN_BOOK_TYPE:
            return self._book_type
        return default


class FakeCalibreDB:
    """最简 calibre 替身（标题判重用精确相等；归一化正确性由映射路径在 WSL 另测）"""

    def __init__(self, existing=(), titles=None, with_new_api=True):
        self._ids = set(existing)
        self._titles = dict(titles or {})
        self.new_api = FakeNewAPI(self) if with_new_api else None
        self.get_data_as_dict_calls = []
        self.same_title_calls = []
        self.import_calls = []
        self.add_format_calls = []
        self._next_id = 1000

    def get_data_as_dict(self, ids=None):
        self.get_data_as_dict_calls.append(list(ids or []))
        return [{"id": i} for i in (ids or []) if i in self._ids]

    def books_with_same_title(self, mi):
        self.same_title_calls.append(mi.title)
        return {bid for bid, t in self._titles.items() if t == mi.title}

    def get_metadata(self, bid, index_is_id=True, get_user_categories=False):
        return FakeBookMeta()

    def import_book(self, mi, files, notify=False, import_hooks=False):
        self._next_id += 1
        bid = self._next_id
        self._ids.add(bid)
        self._titles[bid] = mi.title
        self.import_calls.append((bid, mi.title))
        return bid

    def add_format(self, bid, fmt, path, replace):
        self.add_format_calls.append((bid, fmt, path))


class NoNewAPIDB(FakeCalibreDB):
    """无 new_api 的老式替身：必须回退到旧的逐本调用"""

    def __init__(self):
        FakeCalibreDB.__init__(self, with_new_api=False)


class ScanP0TestBase(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)
        self.tmpdir = tempfile.mkdtemp(prefix="scan_p0_test_")
        self.svc = ScanService()
        # ScanService 是单例：其他用例（本文件或别的文件）可能在实例上打桩
        # _import_one_file 后未清理，这里统一恢复为类方法，保证端到端用例
        # 跑的是真实实现。
        if "_import_one_file" in self.svc.__dict__:
            del self.svc._import_one_file
        self.svc.session = self.session
        self.svc.scoped_session = self.session
        self._conf_backup = {}
        for key in ("SEND_MAIL_FOR_NEW_BOOKS", "USE_DYNAMIC_COVER", "IMPORT_CATEGORY_WITH_FOLDER",
                    "REMOVE_IMPORTED_FILE", "UPLOAD_IGNORE_TITLE_CHECKING", "scan_upload_path"):
            self._conf_backup[key] = scan_service.CONF.get(key)
        scan_service.CONF["SEND_MAIL_FOR_NEW_BOOKS"] = False
        scan_service.CONF["USE_DYNAMIC_COVER"] = False
        scan_service.CONF["REMOVE_IMPORTED_FILE"] = False
        scan_service.CONF["UPLOAD_IGNORE_TITLE_CHECKING"] = False
        scan_service.CONF["scan_upload_path"] = self.tmpdir
        self._patch(mock.patch.object(scan_service, "AutoFillService", mock.MagicMock()))
        self._patch(mock.patch.object(scan_service, "CatalogExtractService", mock.MagicMock()))

    def tearDown(self):
        for key, value in self._conf_backup.items():
            if value is None:
                scan_service.CONF.pop(key, None)
            else:
                scan_service.CONF[key] = value
        # 类级运行态必须复位：wiring 用例可能置位 abort/persist_failed/is_importing，
        # 泄漏会让后续 do_import 系用例静默跳过或误判
        ScanService.static_abort_flag = False
        ScanService.static_phase1_persist_failed = False
        ScanService.static_is_importing = False
        ScanService.static_import_user_id = 0
        self.session.remove()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def _touch(self, name, content=b"x"):
        path = os.path.join(self.tmpdir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return path


class TestHasIdExistence(ScanP0TestBase):
    def test_imported_path_skip_uses_has_id(self):
        fpath = self._touch("a.epub", b"fake-epub-bytes")
        row = ScanFile(fpath, "sha256:1", 1)
        row.status = ScanFile.IMPORTED
        row.book_id = 7
        self.session.add(row)
        self.session.commit()
        db = FakeCalibreDB(existing={7})
        self.svc.db = db
        rid, state = self.svc._scan_one_file(fpath, self.session, 1, set(), set(), False)
        self.assertEqual((rid, state), (None, None))
        self.assertEqual(db.new_api.has_id_calls, [7])
        self.assertEqual(db.get_data_as_dict_calls, [])

    def test_imported_path_missing_book_falls_through(self):
        fpath = self._touch("b.epub", b"other-bytes-here")
        row = ScanFile(fpath, "sha256:1", 1)
        row.status = ScanFile.IMPORTED
        row.book_id = 8
        self.session.add(row)
        self.session.commit()
        db = FakeCalibreDB(existing=set())
        self.svc.db = db
        rid, state = self.svc._scan_one_file(fpath, self.session, 1, set(), set(), False)
        self.assertEqual(state, ScanFile.READY)
        self.assertIsNotNone(rid)
        self.assertEqual(db.new_api.has_id_calls, [8])
        self.assertEqual(db.get_data_as_dict_calls, [])

    def test_hash_hit_uses_has_id(self):
        fpath = self._touch("c.epub", b"hash-hit-content")
        file_hash, bad = self.svc._compute_hash(fpath)
        self.assertIsNone(bad)
        # 同哈希的 IMPORTED 记录挂在另一条已不存在的路径上
        row = ScanFile(os.path.join(self.tmpdir, "gone.epub"), file_hash, 1)
        row.status = ScanFile.IMPORTED
        row.book_id = 9
        self.session.add(row)
        self.session.commit()
        db = FakeCalibreDB(existing={9})
        self.svc.db = db
        rid, state = self.svc._scan_one_file(fpath, self.session, 1, set(), set(), False)
        self.assertEqual(state, ScanFile.DROP)
        self.assertEqual(db.new_api.has_id_calls, [9])
        self.assertEqual(db.get_data_as_dict_calls, [])

    def test_fallback_without_new_api(self):
        fpath = self._touch("d.epub", b"fallback-bytes")
        row = ScanFile(fpath, "sha256:1", 1)
        row.status = ScanFile.IMPORTED
        row.book_id = 11
        self.session.add(row)
        self.session.commit()
        db = NoNewAPIDB()
        db._ids.add(11)
        self.svc.db = db
        rid, state = self.svc._scan_one_file(fpath, self.session, 1, set(), set(), False)
        self.assertEqual((rid, state), (None, None))
        # 回退到旧的逐本 get_data_as_dict，且同样能跳过
        self.assertEqual(db.get_data_as_dict_calls, [[11]])


class TestPhase1Batching(ScanP0TestBase):
    def _raw_count(self, dbpath):
        con = sqlite3.connect(dbpath)
        try:
            return con.execute("SELECT COUNT(*) FROM scanfiles").fetchone()[0]
        finally:
            con.close()

    def test_staged_rows_invisible_until_apply_commit(self):
        dbpath = os.path.join(self.tmpdir, "batch.db").replace("\\", "/")
        engine = create_engine("sqlite:///%s" % dbpath)
        session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(session)
        models.Base.metadata.create_all(engine)
        self.svc.session = session
        self.svc.db = FakeCalibreDB()
        staged = []
        files = [self._touch("n%d.txt" % i, b"content-%d" % i) for i in range(3)]
        for fpath in files:
            rid, state = self.svc._scan_one_file(fpath, session, 1, set(), set(), False, staged=staged)
            self.assertEqual((rid, state), (None, ScanFile.READY))
        # 只暂存未落库：独立连接看不到
        self.assertEqual(self._raw_count(dbpath), 0)
        outcomes = self.svc._apply_phase1_batch(session, staged)
        session.commit()
        self.assertEqual([st for _rid, st in outcomes], [ScanFile.READY] * 3)
        self.assertTrue(all(rid is not None for rid, _st in outcomes))
        rows = session.query(ScanFile).order_by(ScanFile.id).all()
        self.assertEqual([r.status for r in rows], [ScanFile.READY] * 3)
        self.assertEqual(self._raw_count(dbpath), 3)
        session.remove()

    def test_unstaged_rows_visible_immediately(self):
        db = FakeCalibreDB()
        self.svc.db = db
        fpath = self._touch("legacy.txt", b"legacy-content")
        rid, state = self.svc._scan_one_file(fpath, self.session, 1, set(), set(), False)
        self.assertEqual(state, ScanFile.READY)
        row = self.session.query(ScanFile).filter(ScanFile.path == fpath).one()
        self.assertEqual(row.status, ScanFile.READY)

    def test_apply_isolates_row_error(self):
        # 遗留 UNIQUE(hash) 约束库：第二行落库失败不能毒化第一行
        self.session.execute(text("CREATE UNIQUE INDEX ux_scanfiles_hash ON scanfiles (hash)"))
        self.svc.db = FakeCalibreDB()
        r1 = ScanFile(os.path.join(self.tmpdir, "u1.txt"), "sha256:dup", 1)
        r1.status = ScanFile.READY
        r2 = ScanFile(os.path.join(self.tmpdir, "u2.txt"), "sha256:dup", 1)
        r2.status = ScanFile.READY
        outcomes = self.svc._apply_phase1_batch(
            self.session, [("save", r1, ScanFile.READY), ("save", r2, ScanFile.READY)]
        )
        self.session.commit()
        rows = self.session.query(ScanFile).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].path, r1.path)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0][1], ScanFile.READY)

    def test_do_import_internal_delivers_all_rows_batched(self):
        db = FakeCalibreDB()
        self.svc.db = db
        files = [self._touch("m%d.txt" % i, b"mcontent-%d" % i) for i in range(5)]
        delivered = []

        def fake_import_one_file(row, user_id, scan_upload_path, session, force, sole=False, *args, **kwargs):
            delivered.append(row.path)
            return None, None

        self.svc._import_one_file = fake_import_one_file
        self.addCleanup(self._restore_import_one_file)
        self.svc.do_import_internal(files, 9)
        self.assertEqual(sorted(delivered), sorted(files))
        self.assertEqual(self.session.query(ScanFile).filter(ScanFile.status == ScanFile.READY).count(), 5)

    def _restore_import_one_file(self):
        if "_import_one_file" in self.svc.__dict__:
            del self.svc._import_one_file

    def test_do_import_internal_multi_batch(self):
        db = FakeCalibreDB()
        self.svc.db = db
        files = [self._touch("k%d.txt" % i, b"kcontent-%d" % i) for i in range(5)]
        delivered = []

        def fake_import_one_file(row, user_id, scan_upload_path, session, force, sole=False, *args, **kwargs):
            delivered.append(row.path)
            return None, None

        self.svc._import_one_file = fake_import_one_file
        self.addCleanup(self._restore_import_one_file)
        # spy 批次边界：只断言终态时，删掉阈值触发的提交、只留批尾 flush 也照样过；
        # 批尺寸序列 [2,2,1] 钉住阈值提交真实发生（Sourcery C8）
        batches = []
        orig_apply = ScanService._apply_phase1_batch

        def spying_apply(svc_self, session, staged):
            batches.append(len(staged))
            return orig_apply(svc_self, session, staged)

        with mock.patch.object(scan_service, "PHASE1_BATCH_SIZE", 2):
            with mock.patch.object(ScanService, "_apply_phase1_batch", spying_apply):
                self.svc.do_import_internal(files, 9)
        self.assertEqual(batches, [2, 2, 1])
        self.assertEqual(sorted(delivered), sorted(files))
        self.assertEqual(self.session.query(ScanFile).filter(ScanFile.status == ScanFile.READY).count(), 5)


class TestPersistFailureGate(ScanP0TestBase):
    """C2 修复：Phase1 持久化失败必须阻止快照提交与暂存清理——失败批次没落库的
    路径一旦被快照剪枝就永久漏书（union-pending 救不了没有行的文件）。"""

    def _restore_import_one_file(self):
        if "_import_one_file" in self.svc.__dict__:
            del self.svc._import_one_file

    def _stub_import_one_file(self):
        def fake_import_one_file(row, user_id, scan_upload_path, session, force, sole=False, *args, **kwargs):
            return None, None

        self.svc._import_one_file = fake_import_one_file
        self.addCleanup(self._restore_import_one_file)

    def _run_do_import(self, staged_dir):
        # do_import 的注册器包装在同步模式下经 AsyncService 单例 setup 注入 db/session
        # （与 test_scan_snapshot.TestDoImportWiring 同款）。
        asc = scan_service.AsyncService()
        old_scoped, old_db = asc.scoped_session, getattr(asc, "db", None)
        asc.db = FakeCalibreDB()
        asc.scoped_session = self.session
        self.addCleanup(setattr, asc, "scoped_session", old_scoped)
        self.addCleanup(setattr, asc, "db", old_db)
        with mock.patch.object(scan_service.AsyncService, "async_mode", lambda self: False):
            self.svc.do_import("all", 9, cleanup_dir=staged_dir)

    def test_apply_failure_skips_snapshot_and_keeps_staging(self):
        self._stub_import_one_file()
        self._touch(os.path.join("d1", "g1.txt"), b"gated-content")
        staged_dir = os.path.join(self.tmpdir, "staging")
        os.makedirs(staged_dir, exist_ok=True)
        with mock.patch.object(scan_service, "BackgroundService", mock.MagicMock()):
            with mock.patch.object(
                ScanService, "_apply_phase1_batch", side_effect=RuntimeError("db boom")
            ):
                with mock.patch.object(ScanService, "_commit_dir_snapshots") as snap:
                    self._run_do_import(staged_dir)
        self.assertTrue(ScanService.static_phase1_persist_failed)
        snap.assert_not_called()
        self.assertTrue(os.path.isdir(staged_dir))

    def test_success_run_commits_snapshot_and_cleans_staging(self):
        self._stub_import_one_file()
        self._touch(os.path.join("d1", "g2.txt"), b"ok-content")
        staged_dir = os.path.join(self.tmpdir, "staging")
        os.makedirs(staged_dir, exist_ok=True)
        with mock.patch.object(scan_service, "BackgroundService", mock.MagicMock()):
            with mock.patch.object(ScanService, "_commit_dir_snapshots") as snap:
                self._run_do_import(staged_dir)
        self.assertFalse(ScanService.static_phase1_persist_failed)
        snap.assert_called_once()
        self.assertFalse(os.path.isdir(staged_dir))

    def test_commit_failure_sets_flag(self):
        db = FakeCalibreDB()
        self.svc.db = db
        fpath = self._touch("cb.txt", b"commit-boom")
        real_session = self.session

        class CommitBoom:
            def __init__(self, real):
                self._real = real

            def commit(self, *args, **kwargs):
                raise RuntimeError("commit boom")

            def __getattr__(self, name):
                return getattr(self._real, name)

        self.svc.session = CommitBoom(real_session)
        self._stub_import_one_file()
        self.svc.do_import_internal([fpath], 9)
        self.assertTrue(ScanService.static_phase1_persist_failed)

    def test_dropped_save_sets_flag(self):
        # 行级 save 被丢也必须置位（第三个置位分支）：legacy UNIQUE(hash) 库上同哈希
        # IMPORTED 行占位时 READY 行落库被行级 SAVEPOINT 丢弃，该文件本轮无行，
        # 不置位就会照常提交快照、路径被剪枝永久漏掉
        self.session.execute(text("CREATE UNIQUE INDEX ux_scanfiles_hash ON scanfiles (hash)"))
        imp = ScanFile(os.path.join(self.tmpdir, "imported.epub"), "sha256:dup", 1)
        imp.status = ScanFile.IMPORTED
        imp.book_id = 424242  # 不在 FakeCalibreDB：存在性为假，不走 DROP 分支
        self.session.add(imp)
        self.session.commit()
        db = FakeCalibreDB()
        self.svc.db = db
        fpath = self._touch("dupfile.txt", b"dup-content")
        self._stub_import_one_file()
        with mock.patch.object(ScanService, "_compute_hash", return_value=("sha256:dup", None)):
            self.svc.do_import_internal([fpath], 9)
        self.assertTrue(ScanService.static_phase1_persist_failed)


class TestUnreadableFileRow(ScanP0TestBase):
    """C5 修复：文件在但读不了必须落 PERMISSION 行进 union-pending，否则目录快照
    照常提交、该路径被剪枝永久漏掉。文件消失则不落行（无可重试对象）。"""

    def test_unreadable_file_creates_permission_row(self):
        db = FakeCalibreDB()
        self.svc.db = db
        fpath = self._touch("locked.txt", b"locked-content")
        with mock.patch.object(scan_service.os, "access", return_value=False):
            rid, state = self.svc._scan_one_file(fpath, self.session, 1, set(), set(), False)
        self.assertEqual((rid, state), (None, ScanFile.PERMISSION))
        row = self.session.query(ScanFile).filter(ScanFile.path == fpath).one()
        self.assertEqual(row.status, ScanFile.PERMISSION)
        self.assertEqual(row.hash, "")

    def test_unreadable_file_no_duplicate_rows(self):
        fpath = self._touch("locked2.txt", b"locked-content-2")
        with mock.patch.object(scan_service.os, "access", return_value=False):
            self.svc._scan_one_file(fpath, self.session, 1, set(), set(), False)
            self.svc._scan_one_file(fpath, self.session, 1, set(), set(), False)
        self.assertEqual(
            self.session.query(ScanFile).filter(ScanFile.path == fpath).count(), 1
        )

    def test_vanished_file_creates_no_row(self):
        rid, state = self.svc._scan_one_file(
            os.path.join(self.tmpdir, "gone.txt"), self.session, 1, set(), set(), False
        )
        self.assertEqual((rid, state), (None, None))
        self.assertEqual(self.session.query(ScanFile).count(), 0)

    def test_unreadable_imported_file_creates_no_row(self):
        # 已导入且书仍在：文件读不了也不落 PERMISSION 行（对齐旧预检行为，
        # 否则 IMPORTED 行与 PERMISSION 行并存且永不清理，审查 P2-1）
        db = FakeCalibreDB(existing={7})
        self.svc.db = db
        fpath = self._touch("implocked.txt", b"implocked-content")
        row = ScanFile(fpath, "sha256:9", 1)
        row.status = ScanFile.IMPORTED
        row.book_id = 7
        self.session.add(row)
        self.session.commit()
        with mock.patch.object(scan_service.os, "access", return_value=False):
            rid, state = self.svc._scan_one_file(fpath, self.session, 1, set(), set(), False)
        self.assertEqual((rid, state), (None, None))
        self.assertEqual(
            self.session.query(ScanFile).filter(ScanFile.path == fpath).count(), 1
        )


@unittest.skipUnless(HAS_CALIBRE, "needs calibre (real _import_one_file)")
class TestSameTitleEndToEnd(ScanP0TestBase):
    def test_same_title_second_file_adds_format(self):
        # 同标题两本：逐本 books_with_same_title 判重，第二本走加格式分支，不建重复书
        db = FakeCalibreDB()
        self.svc.db = db
        f1 = self._touch(os.path.join("d1", "同名书.txt"), b"first-content-aaa")
        f2 = self._touch(os.path.join("d2", "同名书.txt"), b"second-content-bbb")
        self.svc.do_import_internal([f1, f2], 9)
        self.assertEqual(len(db.import_calls), 1)
        self.assertEqual(len(db.add_format_calls), 1)
        self.assertEqual(len(db.same_title_calls), 2)
        statuses = sorted(r.status for r in self.session.query(ScanFile).all())
        self.assertEqual(statuses, [ScanFile.IMPORTED, ScanFile.IMPORTED])


@unittest.skipUnless(HAS_CALIBRE, "needs calibre (real _import_one_file)")
class TestSetFieldBatching(ScanP0TestBase):
    def test_category_set_field_batched(self):
        scan_service.CONF["IMPORT_CATEGORY_WITH_FOLDER"] = True
        db = FakeCalibreDB()
        self.svc.db = db
        files = []
        for i in range(25):
            files.append(self._touch(os.path.join("c%d" % (i % 3), "book%02d.txt" % i), b"cat-content-%02d" % i))
        self.svc.do_import_internal(files, 9)
        cat_calls = [m for name, m in db.new_api.set_field_calls if name == constants.CALIBRE_COLUMN_CATEGORY]
        # 攒批水位 5：25 本 = 5 次批量写回，而不是 25 次逐本；批提交/尾批 flush 都是空操作
        self.assertEqual(len(cat_calls), 5)
        covered = set()
        for m in cat_calls:
            covered.update(m.keys())
        self.assertEqual(len(covered), 25)
        self.assertEqual(self.session.query(ScanFile).filter(ScanFile.status == ScanFile.IMPORTED).count(), 25)

    def test_final_flush_fires_below_threshold(self):
        # 单本（低于水位 5）也必须落 category：只能来自 worker finally 的兜底 flush，
        # 阈值 flush 触发不了、批提交（20 的倍数）也赶不上——删掉 finally flush 本用例必挂
        # （原 test_pending_fields_flushed_without_category 用根目录 txt，pending 恒空，
        # flush 是空操作，什么都钉不住——Sourcery C7）
        old_val = scan_service.CONF.get("IMPORT_CATEGORY_WITH_FOLDER")
        scan_service.CONF["IMPORT_CATEGORY_WITH_FOLDER"] = True
        self.addCleanup(
            lambda: scan_service.CONF.update({"IMPORT_CATEGORY_WITH_FOLDER": old_val})
            if old_val is not None
            else scan_service.CONF.pop("IMPORT_CATEGORY_WITH_FOLDER", None)
        )
        db = FakeCalibreDB()
        self.svc.db = db
        fpath = self._touch(os.path.join("cats", "plain.txt"), b"plain-content")
        self.svc.do_import_internal([fpath], 9)
        row = self.session.query(ScanFile).filter(ScanFile.path == fpath).one()
        self.assertEqual(row.status, ScanFile.IMPORTED)
        cat_calls = [m for name, m in db.new_api.set_field_calls if name == constants.CALIBRE_COLUMN_CATEGORY]
        self.assertEqual(len(cat_calls), 1)
        self.assertEqual(list(cat_calls[0].keys()), [row.book_id])


class TestPhase1NoWriteHold(ScanP0TestBase):
    """P1 核心不变量：Phase1 读算阶段不持有写事务，worker 并发写永不撞锁。

    文件库（真锁语义）+ timeout=0.5s + 每文件 0.3s 慢哈希 + 批大小 4（强制批中
    并发）：旧实现（写事务横跨哈希 IO）在 0.5s 超时下必丢行；新实现零丢失。
    """

    def test_concurrent_worker_writes_never_lock(self):
        dbpath = os.path.join(self.tmpdir, "contend.db").replace("\\", "/")
        engine = create_engine(
            "sqlite:///%s" % dbpath, connect_args={"timeout": 0.5, "check_same_thread": False}
        )
        session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(session)
        models.Base.metadata.create_all(engine)
        self.svc.session = session
        self.svc.scoped_session = session
        self.svc.db = FakeCalibreDB()
        files = [self._touch("h%d.txt" % i, b"hold-content-%d" % i) for i in range(12)]
        delivered = []
        orig_hash = ScanService._compute_hash

        def slow_hash(svc_self, fpath):
            time.sleep(0.3)
            return orig_hash(svc_self, fpath)

        def writing_stub(row, user_id, scan_upload_path, wsession, force, sole=False, *args, **kwargs):
            delivered.append(row.path)
            row.status = ScanFile.IMPORTED
            ok = self.svc.save_or_rollback(row, wsession)
            return (None, ScanFile.IMPORTED) if ok else (None, None)

        self.svc._import_one_file = writing_stub
        self.addCleanup(self._restore_import_one_file)
        with mock.patch.object(ScanService, "_compute_hash", slow_hash):
            with mock.patch.object(scan_service, "PHASE1_BATCH_SIZE", 4):
                self.svc.do_import_internal(files, 9)
        self.assertEqual(len(delivered), 12)
        self.assertEqual(
            session.query(ScanFile).filter(ScanFile.status == ScanFile.IMPORTED).count(), 12
        )
        session.remove()

    def _restore_import_one_file(self):
        if "_import_one_file" in self.svc.__dict__:
            del self.svc._import_one_file


@unittest.skipUnless(HAS_CALIBRE, "needs calibre (real _import_one_file)")
class TestRowSaveHonesty(ScanP0TestBase):
    def test_row_save_failure_returns_none(self):
        # 行落库失败必须诚实返回 (None, None)，worker 才不会计数/公告幽灵成功
        db = FakeCalibreDB()
        self.svc.db = db
        fpath = self._touch("honest.txt", b"honest-content")
        row = ScanFile(fpath, "sha256:h", 1)
        row.status = ScanFile.READY
        with mock.patch.object(ScanService, "save_or_rollback", return_value=False):
            new_id, status = self.svc._import_one_file(row, 9, self.tmpdir, self.session, False)
        self.assertEqual((new_id, status), (None, None))


class TestNonReadyNotEnqueued(ScanP0TestBase):
    def test_drop_rows_never_reach_worker(self):
        # 同内容两文件同批：第二本 DROP 落库但绝不入队，worker 只处理 READY
        db = FakeCalibreDB()
        self.svc.db = db
        f1 = self._touch("dup1.txt", b"same-bytes")
        f2 = self._touch("dup2.txt", b"same-bytes")
        delivered = []

        def fake_import_one_file(row, user_id, scan_upload_path, session, force, sole=False, *args, **kwargs):
            delivered.append(row.path)
            return None, None

        self.svc._import_one_file = fake_import_one_file
        self.addCleanup(self._restore_import_one_file)
        self.svc.do_import_internal([f1, f2], 9)
        self.assertEqual(delivered, [f1])
        statuses = sorted(r.status for r in self.session.query(ScanFile).all())
        self.assertEqual(statuses, [ScanFile.DROP, ScanFile.READY])

    def _restore_import_one_file(self):
        if "_import_one_file" in self.svc.__dict__:
            del self.svc._import_one_file


class TestPutWork(ScanP0TestBase):
    def test_put_raises_when_worker_dead(self):
        import queue as queue_mod

        q = queue_mod.Queue(maxsize=1)
        q.put("x")
        dead = mock.Mock()
        dead.is_alive.return_value = False
        with self.assertRaises(RuntimeError):
            ScanService._put_work(q, dead, "y", timeout=0.1)

    def test_put_waits_for_live_worker(self):
        import queue as queue_mod
        import threading

        q = queue_mod.Queue(maxsize=1)
        q.put("x")
        live = mock.Mock()
        live.is_alive.return_value = True

        def drain():
            time.sleep(0.2)
            q.get()

        threading.Thread(target=drain, daemon=True).start()
        ScanService._put_work(q, live, "y", timeout=5)
        self.assertEqual(q.qsize(), 1)

    def test_put_gives_up_after_cancel_grace(self):
        # 取消后连续 2 轮超时仍投不进（worker 卡死无法排空）：有界放弃而不是永久挂起
        import queue as queue_mod

        q = queue_mod.Queue(maxsize=1)
        q.put("x")
        live = mock.Mock()
        live.is_alive.return_value = True
        ScanService.static_abort_flag = True
        try:
            with self.assertRaises(RuntimeError):
                ScanService._put_work(q, live, "y", timeout=0.05)
        finally:
            ScanService.static_abort_flag = False


if __name__ == "__main__":
    unittest.main()
