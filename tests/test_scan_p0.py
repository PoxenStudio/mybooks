"""P0 扫描导入加速回归测试（calibre 轻量检查 / Phase1 批量落库 / set_field 逐本写）。

- 不依赖 calibre 的用例（has_id 存在性、回退路径、暂存可见性、行级隔离、
  行全送达、写锁不变量、put 投递守卫）Windows 直跑；
- 走真实 _import_one_file 的用例（同标题加格式、set_field 逐本、行失败诚实）
  需要 calibre（函数头 import Metadata），缺 calibre 时自动跳过，WSL 全量跑。
"""
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
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
from webserver.models import Item, ScanFile
from webserver.services import scan_service
from webserver.services.scan_service import ScanService, ImportOptions, ImportInternalOptions
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
        self.get_id_map_calls = []
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

    def get_id_map(self, field):
        self.get_id_map_calls.append(field)
        return dict(self._db._titles)


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
                    "REMOVE_IMPORTED_FILE", "UPLOAD_IGNORE_TITLE_CHECKING", "scan_upload_path",
                    "SCAN_IGNORE_DIRS", "SCAN_REPLACE_SAME_TITLE"):
            self._conf_backup[key] = scan_service.CONF.get(key)
        scan_service.CONF["SEND_MAIL_FOR_NEW_BOOKS"] = False
        scan_service.CONF["USE_DYNAMIC_COVER"] = False
        scan_service.CONF["REMOVE_IMPORTED_FILE"] = False
        scan_service.CONF["UPLOAD_IGNORE_TITLE_CHECKING"] = False
        scan_service.CONF["scan_upload_path"] = self.tmpdir
        scan_service.CONF["SCAN_IGNORE_DIRS"] = []
        scan_service.CONF["SCAN_REPLACE_SAME_TITLE"] = False
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

    def test_same_file_ops_grouped_deletes_roll_back_with_failed_save(self):
        # 同一文件的 [del_path, save] 必须同生共死：save 因遗留 UNIQUE(hash) 冲突被丢时，
        # del_path 的删除要一并回滚，不能留下「库里再无该路径任何行」的洞——那种路径没有
        # 行可被 union 回填，目录快照命中后即被剪枝永久漏掉（逐 op 各自 SAVEPOINT 的旧
        # 实现正是如此：删除已释放保存点随批提交，行却在失败 op 里被丢）。
        self.session.execute(text("CREATE UNIQUE INDEX ux_scanfiles_hash ON scanfiles (hash)"))
        self.svc.db = FakeCalibreDB()
        # 同哈希 IMPORTED 锚行：del_hash 不会删它，故新行 INSERT 必然冲突
        anchor = ScanFile(os.path.join(self.tmpdir, "anchor.txt"), "sha256:H", 1)
        anchor.status = ScanFile.IMPORTED
        # 该路径的陈旧残留行（触发 del_path）
        stale = ScanFile(os.path.join(self.tmpdir, "p.txt"), "sha256:old", 1)
        stale.status = ScanFile.NEW
        self.session.add_all([anchor, stale])
        self.session.commit()
        fpath = stale.path

        newrow = ScanFile(fpath, "sha256:H", 1)
        newrow.status = ScanFile.READY
        outcomes = self.svc._apply_phase1_batch(
            self.session, [("del_path", fpath), ("save", newrow, ScanFile.READY)]
        )
        self.session.commit()
        self.assertEqual(outcomes, [])
        survived = self.session.query(ScanFile).filter(ScanFile.path == fpath).all()
        self.assertEqual(len(survived), 1)
        self.assertEqual(survived[0].status, ScanFile.NEW)

    def test_phase2_batch_does_not_hold_write_lock_across_books(self):
        # P1 回归钉：批次写事务只允许在 _apply_phase2_batch 的批边界内打开。worker 的
        # session 若仍是 autoflush=True，每轮开头的 importing_session.get() 会把上一本
        # 改脏的行刷出去，驱动层写事务就此打开并横跨整批的 calibre/导入 IO（NAS 上与
        # Phase1 批提交撞锁 → 最多丢整批 500 行 + 本轮不提交快照 + 下轮全量重扫）。
        # 用文件库 + 独立连接，才能把"worker 连接是否已在写事务中"与 Phase1 分开观测。
        dbpath = os.path.join(self.tmpdir, "lock.db").replace("\\", "/")
        engine = create_engine("sqlite:///%s" % dbpath)
        session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(session)
        models.Base.metadata.create_all(engine)
        self.svc.session = session
        self.svc.scoped_session = session
        self.svc.db = FakeCalibreDB()
        files = [self._touch("w%d.txt" % i, b"w-%d" % i) for i in range(6)]
        txn_at_book_start = []

        def fake_import_one_file(row, session, staged_ops=None, opts=None):
            raw = session.connection().connection.driver_connection
            txn_at_book_start.append(getattr(raw, "in_transaction", None))
            row.status = ScanFile.IMPORTED
            staged_ops.append(("save_row", row))
            return None, ScanFile.IMPORTED

        self.svc._import_one_file = fake_import_one_file
        self.addCleanup(self._restore_import_one_file)
        self.svc.do_import_internal(files, ImportInternalOptions(user_id=9))
        self.assertEqual(len(txn_at_book_start), 6)
        # 每本开工时都不该已经在写事务里（旧 autoflush=True 从第 2 本起恒为 True）
        self.assertEqual(txn_at_book_start, [False] * 6)

    def test_do_import_internal_delivers_all_rows_batched(self):
        db = FakeCalibreDB()
        self.svc.db = db
        files = [self._touch("m%d.txt" % i, b"mcontent-%d" % i) for i in range(5)]
        delivered = []

        def fake_import_one_file(row, session, *args, **kwargs):
            delivered.append(row.path)
            return None, None

        self.svc._import_one_file = fake_import_one_file
        self.addCleanup(self._restore_import_one_file)
        self.svc.do_import_internal(files, ImportInternalOptions(user_id=9))
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

        def fake_import_one_file(row, session, *args, **kwargs):
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
                self.svc.do_import_internal(files, ImportInternalOptions(user_id=9))
        self.assertEqual(batches, [2, 2, 1])
        self.assertEqual(sorted(delivered), sorted(files))
        self.assertEqual(self.session.query(ScanFile).filter(ScanFile.status == ScanFile.READY).count(), 5)

    def test_duplicate_paths_in_filelist_processed_once(self):
        # 同一路径在 filelist 里出现两次（库里同路径多行时 resolve_ready_paths/
        # resolve_filter_paths 会产出重复路径，手动勾选也原样透传）：并行分支的 prepare
        # 发生在收割之前（processed_paths 只在 _scan_finalize 登记），第二条照样过检查 →
        # 多算一次哈希、并可能多落一条 DROP 记录或把同一文件重复入队；串行分支必跳过第二次。
        # 入口保序去重后两条分支都必须「只处理一次、无 DROP 记录」。
        orig = ScanService._import_one_file
        svc = self.svc
        for workers, force in ((1, False), (4, False), (4, True)):
            self.session.query(ScanFile).delete()
            self.session.commit()
            svc.db = FakeCalibreDB()          # 每轮换库，避免标题判重把第二轮判成 EXIST
            fpath = self._touch("dupq.txt", b"dupq-content")
            calls = []

            def counting(row, session, staged_ops=None, opts=None):
                calls.append(row.path)
                return orig(svc, row, session, staged_ops, opts)

            svc._import_one_file = counting
            self.addCleanup(self._restore_import_one_file)
            with mock.patch.dict(scan_service.CONF, {"scan_hash_workers": workers}):
                svc.do_import_internal([fpath, fpath], ImportInternalOptions(user_id=9, force=force))
            self.assertEqual(calls, [fpath], (workers, force))
            rows = self.session.query(ScanFile).all()
            self.assertEqual(len(rows), 1, (workers, force))
            self.assertEqual(rows[0].status, ScanFile.IMPORTED, (workers, force))
            self.assertEqual(rows[0].path, fpath)


class TestHashParallel(ScanP0TestBase):
    """C2 哈希并行流水线：保序收割与串行逐位等价 / 哈希确在池线程 / abort 收割契约。"""

    def _restore_import_one_file(self):
        if "_import_one_file" in self.svc.__dict__:
            del self.svc._import_one_file

    def _run_production(self, files, workers):
        """驱动真实 do_import_internal 跑一轮，返回终态行 [(path, status, hash)]。

        旧版用"测试自写的收割循环副本"比对串行/并行，并行臂既不受 CONF["scan_hash_workers"]
        影响、也不走生产收割路径——把生产收割改成任意顺序它都照绿（空钉）。这里改成
        真正跑 do_import_internal，才钉得住并行协议本身。
        """
        self.session.query(ScanFile).delete()
        self.session.commit()
        self.svc.db = FakeCalibreDB()
        with mock.patch.dict(scan_service.CONF, {"scan_hash_workers": workers}):
            self.svc.do_import_internal(files, ImportInternalOptions(user_id=9))
        rows = self.session.query(ScanFile).order_by(ScanFile.path).all()
        return [(r.path, r.status, r.hash) for r in rows]

    def test_pipeline_matches_serial_end_state(self):
        # 内容重复文件（2==0、4==1 两组）走 in-run 哈希去重落 DROP。串行（workers=1）与
        # 并行（4）都驱动真实 do_import_internal：终态逐行相等即"保序收割 + 去重时序"
        # 等价的核心回归钉——收割若按完成序/LIFO，READY/DROP 的归属会互换。
        contents = [b"aaa", b"bbb", b"aaa", b"ccc", b"bbb", b"ddd"]
        files = [self._touch("q%d.txt" % i, contents[i]) for i in range(6)]
        serial = self._run_production(files, 1)
        parallel = self._run_production(files, 4)
        self.assertEqual(serial, parallel)
        self.assertEqual(len(parallel), 6)
        self.assertEqual(sum(1 for _, status, _ in parallel if status == ScanFile.DROP), 2)
        self.assertEqual(sum(1 for _, status, _ in parallel if status == ScanFile.IMPORTED), 4)

    def test_harvest_order_parallel_matches_submit_order(self):
        # 保序收割的最小判别钉：两本同内容文件，让"先提交的那本"哈希更慢（0.4s）。
        # 串行语义下先提交者 READY→IMPORTED、后者 DROP；收割若按完成序/LIFO 则二者互换。
        db = FakeCalibreDB()
        self.svc.db = db
        p1 = self._touch("ord1.txt", b"same-bytes-here")
        p2 = self._touch("ord2.txt", b"same-bytes-here")
        orig_hash = ScanService._compute_hash

        def slow_first(svc_self, fpath):
            if fpath == p1:
                time.sleep(0.4)
            return orig_hash(svc_self, fpath)

        with mock.patch.dict(scan_service.CONF, {"scan_hash_workers": 2}):
            with mock.patch.object(ScanService, "_compute_hash", slow_first):
                self.svc.do_import_internal([p1, p2], ImportInternalOptions(user_id=9))
        status = {r.path: r.status for r in self.session.query(ScanFile).all()}
        self.assertEqual(status[p1], ScanFile.IMPORTED)
        self.assertEqual(status[p2], ScanFile.DROP)

    def test_hash_runs_in_pool_threads(self):
        # 并行分支必须真的把哈希投到 scan_hash 池线程；scan_hash_workers=1（NAS 兜底）
        # 必须完全串行在主线程。驱动真实 do_import_internal——旧版只看测试自建池的线程名，
        # 把生产 if hash_workers > 1 整段删掉（配置变死键）也照样绿。
        files = [self._touch("t%d.txt" % i, b"t-%d" % i) for i in range(4)]
        seen_threads = []
        orig_hash = ScanService._compute_hash

        def spying_hash(svc_self, fpath):
            seen_threads.append(threading.current_thread().name)
            return orig_hash(svc_self, fpath)

        for workers, expect_pool in ((2, True), (1, False)):
            seen_threads.clear()
            self.session.query(ScanFile).delete()
            self.session.commit()
            self.svc.db = FakeCalibreDB()
            with mock.patch.dict(scan_service.CONF, {"scan_hash_workers": workers}):
                with mock.patch.object(ScanService, "_compute_hash", spying_hash):
                    self.svc.do_import_internal(files, ImportInternalOptions(user_id=9))
            self.assertEqual(len(seen_threads), 4)
            if expect_pool:
                self.assertTrue(all(n.startswith("scan_hash") for n in seen_threads), seen_threads)
            else:
                self.assertTrue(all(not n.startswith("scan_hash") for n in seen_threads), seen_threads)

    def test_serial_branch_workers_1_end_to_end(self):
        # scan_hash_workers=1（NAS 兜底模式，注释/文档明示的用法）走 hash_pool
        # is None 串行分支。回归钉：曾把 fpath(str) 当 ctx 传给 _scan_finalize
        # 直接 TypeError，整轮 0 行落库——该分支此前零覆盖。
        db = FakeCalibreDB()
        self.svc.db = db
        files = [self._touch("s%d.txt" % i, b"s-%d" % i) for i in range(2)]
        delivered = []

        def fake_import_one_file(row, session, staged_ops=None, opts=None):
            delivered.append(row.path)
            return None, None

        self.svc._import_one_file = fake_import_one_file
        self.addCleanup(self._restore_import_one_file)
        with mock.patch.dict(scan_service.CONF, {"scan_hash_workers": 1}):
            self.svc.do_import_internal(files, ImportInternalOptions(user_id=9))
        self.assertEqual(sorted(delivered), sorted(files))
        self.assertEqual(self.session.query(ScanFile).filter(ScanFile.status == ScanFile.READY).count(), 2)

    def test_abort_mid_run_still_finalizes_submitted(self):
        # abort 在 prepare 内置位（主线程同步，无竞态）：循环下一轮头部退出；
        # 已提交进流水线的文件仍被收尾收割 finalize 并落行（快照反正不提交）。
        db = FakeCalibreDB()
        self.svc.db = db
        files = [self._touch("a%d.txt" % i, b"a-%d" % i) for i in range(5)]
        delivered = []

        def fake_import_one_file(row, session, *args, **kwargs):
            delivered.append(row.path)
            return None, None

        self.svc._import_one_file = fake_import_one_file
        self.addCleanup(self._restore_import_one_file)
        calls = []
        orig_prepare = ScanService._scan_prepare

        def spying_prepare(svc_self, fpath, session, import_id, processed_paths, force, staged=None):
            calls.append(fpath)
            if len(calls) >= 2:
                ScanService.static_abort_flag = True
            return orig_prepare(svc_self, fpath, session, import_id, processed_paths, force, staged=staged)

        with mock.patch.dict(scan_service.CONF, {"scan_hash_workers": 2}):
            with mock.patch.object(ScanService, "_scan_prepare", spying_prepare):
                self.svc.do_import_internal(files, ImportInternalOptions(user_id=9))
        self.assertEqual(len(calls), 2)
        # abort 语义：worker 跳过队列所有行（保持 READY 下轮 union-pending 重导），
        # 但已提交进流水线的文件必须被收尾收割并落 READY 行（尾批照常提交）。
        self.assertEqual(delivered, [])
        ready_paths = sorted(r.path for r in self.session.query(ScanFile).filter(ScanFile.status == ScanFile.READY).all())
        self.assertEqual(ready_paths, sorted(files[:2]))


class TestPhase2Batching(ScanP0TestBase):
    """C3 Phase2 行/链接真批量：暂存语义 / 批节奏与免逐条 commit / 行级失败隔离。"""

    def _restore_import_one_file(self):
        if "_import_one_file" in self.svc.__dict__:
            del self.svc._import_one_file

    def _make_ready_row(self, name, content=b"txt-body"):
        fpath = self._touch(name, content)
        row = ScanFile(fpath, "sha256:" + hashlib.md5(fpath.encode("utf-8")).hexdigest(), 1)
        row.status = ScanFile.READY
        self.session.add(row)
        self.session.commit()
        return row

    @unittest.skipUnless(HAS_CALIBRE, "requires calibre Metadata")
    def test_staged_ops_apply_outcomes_and_item_links(self):
        # 走真实 _import_one_file 的暂存路径：行+Item 全部进 staged_ops，apply 前
        # Item 表为空（证明未逐条落库），apply+commit 后行 IMPORTED、链接齐全。
        db = FakeCalibreDB()
        self.svc.db = db
        row1 = self._make_ready_row("b1.txt")
        row2 = self._make_ready_row("b2.txt")
        staged_ops = []
        for row in (row1, row2):
            new_id, status = self.svc._import_one_file(row, self.session, staged_ops=staged_ops, opts=ImportInternalOptions(user_id=9, scan_upload_path=self.tmpdir, force=False))
            self.assertEqual(status, ScanFile.IMPORTED)
            self.assertIsNotNone(new_id)
        self.assertEqual(len(staged_ops), 4)  # 2 save_row + 2 save_item
        self.assertEqual(self.session.query(Item).count(), 0)
        outcomes = self.svc._apply_phase2_batch(self.session, staged_ops)
        self.session.commit()
        self.assertEqual(outcomes["saved_rows"], {row1.id, row2.id})
        self.assertEqual(outcomes["dropped_rows"], set())
        self.assertEqual(outcomes["dropped_items"], 0)
        self.assertEqual(self.session.query(ScanFile).filter(ScanFile.status == ScanFile.IMPORTED).count(), 2)
        self.assertEqual(self.session.query(Item).count(), 2)

    def test_phase2_batch_cadence_no_per_book_commit(self):
        # 20 本书：mid-loop 恰好一批 [20]（batch_size=20），且暂存路径下
        # save_or_rollback（逐条 commit）一次都不被调用。
        db = FakeCalibreDB()
        self.svc.db = db
        files = [self._touch("c%d.txt" % i, b"c-%d" % i) for i in range(20)]
        batches = []
        orig_apply2 = ScanService._apply_phase2_batch

        def spying_apply2(svc_self, session, staged_ops):
            batches.append(len(staged_ops))
            return orig_apply2(svc_self, session, staged_ops)

        def fake_import_one_file(row, session, staged_ops=None, opts=None):
            row.status = ScanFile.IMPORTED
            staged_ops.append(("save_row", row))
            return None, ScanFile.IMPORTED

        self.svc._import_one_file = fake_import_one_file
        self.addCleanup(self._restore_import_one_file)
        with mock.patch.object(ScanService, "_apply_phase2_batch", spying_apply2):
            with mock.patch.object(ScanService, "save_or_rollback") as mock_save:
                self.svc.do_import_internal(files, ImportInternalOptions(user_id=9))
        self.assertEqual(batches, [20])
        mock_save.assert_not_called()
        self.assertEqual(self.session.query(ScanFile).filter(ScanFile.status == ScanFile.IMPORTED).count(), 20)

    def test_phase2_row_isolation_on_integrity_error(self):
        # UNIQUE(hash) 冲突的暂存行只丢自己（SAVEPOINT 行级隔离），同批其余行照常落库。
        # 注意适用范围：这里是真的「新建对象」——失败对象会被 expunge，故隔离成立；
        # 持久行就地改属性的生产形态另见 test_phase2_persistent_row_failure_is_accounted_not_escaped。
        # 新 schema 无该约束，这里按 legacy 库口径手工建唯一索引注入真实 IntegrityError。
        good_anchor = self._make_ready_row("iso0.txt")
        good_anchor.hash = "sha256:dup-hash"
        self.session.commit()
        self.session.execute(text("CREATE UNIQUE INDEX uniq_hash_iso ON scanfiles (hash)"))
        self.session.commit()
        other = ScanFile(self._touch("iso3.txt", b"iso3"), "sha256:unique-3", 1)
        other.status = ScanFile.IMPORTED
        bad = ScanFile(self._touch("iso2.txt", b"iso2"), "sha256:dup-hash", 1)
        bad.status = ScanFile.IMPORTED
        outcomes = self.svc._apply_phase2_batch(self.session, [("save_row", bad), ("save_row", other)])
        self.session.commit()
        self.assertEqual(outcomes["dropped_rows"], {None})
        self.assertEqual(outcomes["saved_rows"], {other.id})
        self.assertEqual(self.session.query(ScanFile).filter(ScanFile.hash == "sha256:unique-3").count(), 1)

    def test_phase2_persistent_row_failure_is_accounted_not_escaped(self):
        # 生产形态：row 是 session.get 取回的持久行、就地改属性（与新建对象不同——新建
        # 对象失败会被 expunge，同批其余 op 照常落库，见上一用例）。实测：持久行的 ORM
        # flush 失败会把 session 打成 deactivated，pysqlite 下 SAVEPOINT 无法恢复会话语境，
        # 故 _apply_phase2_batch 停手 → 本批整批回滚。这里钉住这一语义：既不以外抛
        # PendingRollbackError 的形式失控，也要把 worker 乐观计入的状态数诚实回调。
        self.session.execute(text("CREATE UNIQUE INDEX ux_hash_heavy ON scanfiles (hash)"))
        anchor = self._make_ready_row("hv_anchor.txt")
        anchor.hash = "sha256:taken"
        anchor.status = ScanFile.IMPORTED
        bad = self._make_ready_row("hv_bad.txt")
        bad.hash = "sha256:b1"
        good = self._make_ready_row("hv_good.txt")
        good.hash = "sha256:g1"
        self.session.commit()
        anchor = self.session.get(ScanFile, anchor.id)
        bad = self.session.get(ScanFile, bad.id)
        good = self.session.get(ScanFile, good.id)
        bad.hash = "sha256:taken"          # 与 anchor 唯一冲突：该行 UPDATE 必失败
        good.status = ScanFile.IMPORTED

        prev_cnt = ScanService.static_status_cnt
        self.addCleanup(setattr, ScanService, "static_status_cnt", prev_cnt)
        ScanService.static_status_cnt = {ScanFile.IMPORTED: 2}   # worker 已乐观计入
        batch_row_status = {bad.id: ScanFile.IMPORTED, good.id: ScanFile.IMPORTED}
        staged_ops = [("save_row", bad), ("save_row", good)]
        self.svc._apply_phase2_batch_checked(self.session, staged_ops, batch_row_status)

        self.assertEqual(staged_ops, [])
        self.assertEqual(batch_row_status, {})
        self.assertEqual(ScanService.static_status_cnt.get(ScanFile.IMPORTED, 0), 0)
        # 本批整批回滚：两行都保持 READY；session 仍可用（查询不抛 PendingRollbackError）
        self.session.expire_all()
        self.assertEqual(self.session.get(ScanFile, bad.id).status, ScanFile.READY)
        self.assertEqual(self.session.get(ScanFile, good.id).status, ScanFile.READY)
        self.assertEqual(self.session.query(ScanFile).count(), 3)


@unittest.skipUnless(HAS_CALIBRE, "needs calibre icu")
class TestTitleDedupIndex(ScanP0TestBase):
    """标题判重索引：语义与 calibre books_with_same_title 逐位一致
    （同 icu_lower 折叠 + 等值），运行内回填可见，close 销毁临时文件。"""

    def _make(self, titles):
        db = FakeCalibreDB(titles=titles)
        return scan_service._TitleDedupIndex(db)

    def test_semantics_parity_with_icu_lower(self):
        index = self._make({
            1: "A", 2: "a", 4: "Abc",
            3: "ＡＢＣ",
            5: "红楼梦", 6: "红楼梦（上下册）",
            7: "école", 8: "e\u0301cole",
            9: "\ufeff",          # icu_lower 折成空串：legacy 会与全库逐个比该空键
        })
        try:
            probes = {
                "a": {1, 2},          # icu_lower 折叠后等值（同源语义）
                "Abc": {4},
                "abc": {4},
                "ＡＢＣ": {3},         # icu_lower 不做 NFKC：全角不与半角互撞
                "红楼梦": {5},         # 带书名号副标题不算同名
                "ÉCOLE": {7},         # icu_lower 只做大小写映射不做规范化
                "E\u0301COLE": {8},   # NFC/NFD 不互撞（原路径同行为）
                "\ufeff": {9},        # 空折叠键照 legacy 口径参与比较（不额外过滤）
                "": set(),            # 守卫只看原始标题真假（照抄 legacy if title:）
                "不存在": set(),
            }
            for probe, expected in probes.items():
                self.assertEqual(index.lookup(probe), expected, repr(probe))
        finally:
            index.close()

    def test_add_visible_to_lookup_and_close_removes_file(self):
        index = self._make({1: "x"})
        path = index._path
        self.assertTrue(os.path.exists(path))
        index.add("新书", 99)
        self.assertEqual(index.lookup("新书"), {99})
        self.assertEqual(index.lookup("X"), {1})
        index.close()
        self.assertFalse(os.path.exists(path))
        self.assertRaises(AttributeError, index.lookup, "x")  # 关闭后连接不可用


class TestTitleDedupDispatch(ScanP0TestBase):
    """判重入口门限分发（索引对象 mock，Windows 直跑）：
    小批量回退 / 达标只建一次 / 构建失败不重试 / 运行收尾销毁。"""

    def _restore_import_one_file(self):
        if "_import_one_file" in self.svc.__dict__:
            del self.svc._import_one_file

    def setUp(self):
        super().setUp()
        ScanService.static_title_index = None
        ScanService.static_title_index_total = 0

    def tearDown(self):
        ScanService.static_title_index = None
        ScanService.static_title_index_total = 0
        super().tearDown()

    def test_small_batch_falls_back_without_building(self):
        db = FakeCalibreDB(titles={1: "t"})
        self.svc.db = db
        ScanService.static_title_index_total = 10
        self.assertEqual(self.svc._title_dedup_ids(mock.MagicMock(title="t")), {1})
        self.assertIsNone(ScanService.static_title_index)
        self.assertEqual(db.same_title_calls, ["t"])  # 走的是 calibre 全库扫描

    def test_large_batch_builds_once_and_uses_index(self):
        db = FakeCalibreDB()
        self.svc.db = db
        ScanService.static_title_index_total = 60
        mock_index = mock.MagicMock()
        mock_index.lookup.return_value = {7}
        with mock.patch.object(scan_service, "_TitleDedupIndex", return_value=mock_index) as mock_cls:
            self.assertEqual(self.svc._title_dedup_ids(mock.MagicMock(title="x")), {7})
            self.assertEqual(self.svc._title_dedup_ids(mock.MagicMock(title="y")), {7})
        mock_cls.assert_called_once()  # 整个运行只构建一次
        mock_index.lookup.assert_called_with("y")
        self.assertIs(ScanService.static_title_index, mock_index)

    def test_build_failure_falls_back_without_retry(self):
        db = FakeCalibreDB(titles={1: "t"})
        self.svc.db = db
        ScanService.static_title_index_total = 60
        with mock.patch.object(scan_service, "_TitleDedupIndex", side_effect=RuntimeError("boom")) as mock_cls:
            self.assertEqual(self.svc._title_dedup_ids(mock.MagicMock(title="t")), {1})
            self.assertEqual(self.svc._title_dedup_ids(mock.MagicMock(title="t")), {1})
        mock_cls.assert_called_once()  # False 哨兵：本轮不再重试构建
        self.assertIs(ScanService.static_title_index, False)

    def test_do_import_internal_destroys_index_after_run(self):
        db = FakeCalibreDB()
        self.svc.db = db
        files = [self._touch("ti%d.txt" % i, b"ti-%d" % i) for i in range(3)]

        svc = self.svc

        def fake_import_one_file(row, session, staged_ops=None, opts=None):
            # 仿真实流程：Phase2 每本书都走一次判重入口（索引在此首次构建）
            svc._title_dedup_ids(type("MI", (), {"title": row.path})())
            row.status = ScanFile.IMPORTED
            staged_ops.append(("save_row", row))
            return None, ScanFile.IMPORTED

        self.svc._import_one_file = fake_import_one_file
        self.addCleanup(self._restore_import_one_file)
        mock_index = mock.MagicMock()

        def fake_dedup(mi):
            if ScanService.static_title_index is None:
                ScanService.static_title_index = mock_index
            return set()

        self.svc._title_dedup_ids = fake_dedup
        self.addCleanup(self._restore_dedup_ids)
        ScanService.static_title_index_total = 60
        self.svc.do_import_internal(files, ImportInternalOptions(user_id=9))
        mock_index.close.assert_called_once()
        self.assertIsNone(ScanService.static_title_index)
        self.assertEqual(ScanService.static_title_index_total, 0)  # 收尾连门限一起清：lingering worker 不再重建孤儿索引

    def _restore_dedup_ids(self):
        if "_title_dedup_ids" in self.svc.__dict__:
            del self.svc._title_dedup_ids


@unittest.skipUnless(HAS_CALIBRE, "needs calibre (real _import_one_file)")
class TestTitleIndexEndToEnd(ScanP0TestBase):
    """运行内回填端到端（门限 patch 到 1 强制走索引）：同批同名第二本经索引
    命中并入已有书，一次都不走 calibre 全库扫描，也不重复建书；收尾后
    索引销毁、临时文件已删。"""

    def test_same_title_second_book_merges_via_index(self):
        db = FakeCalibreDB()
        self.svc.db = db
        f1 = self._touch(os.path.join("d1", "同名书.txt"), b"first-content-aaa")
        f2 = self._touch(os.path.join("d2", "同名书.txt"), b"second-content-bbb")
        import glob as _glob
        temp_files_before = set(_glob.glob(os.path.join(tempfile.gettempdir(), "scan_title_idx_*.sqlite")))
        with mock.patch.object(scan_service, "TITLE_INDEX_MIN_BOOKS", 1):
            self.svc.do_import_internal([f1, f2], ImportInternalOptions(user_id=9))
        self.assertEqual(len(db.import_calls), 1)  # 第二本并入，不重复建书
        self.assertEqual(len(db.add_format_calls), 1)
        self.assertEqual(db.same_title_calls, [])  # 两次判重全部走索引，零全库扫描
        self.assertEqual(db.new_api.get_id_map_calls, ["title"])  # 库映射只取一次
        statuses = sorted(r.status for r in self.session.query(ScanFile).all())
        self.assertEqual(statuses, [ScanFile.IMPORTED, ScanFile.IMPORTED])
        self.assertIsNone(ScanService.static_title_index)  # 收尾销毁
        # 临时索引文件必须已删（close 跨线程生效性回归钉——check_same_thread 缺失时
        # 此断言在 Windows 上稳定失败）
        temp_files_after = set(_glob.glob(os.path.join(tempfile.gettempdir(), "scan_title_idx_*.sqlite")))
        self.assertEqual(temp_files_after - temp_files_before, set())


class TestPersistFailureGate(ScanP0TestBase):
    """C2 修复：Phase1 持久化失败必须阻止快照提交与暂存清理——失败批次没落库的
    路径一旦被快照剪枝就永久漏书（union-pending 救不了没有行的文件）。"""

    def _restore_import_one_file(self):
        if "_import_one_file" in self.svc.__dict__:
            del self.svc._import_one_file

    def _stub_import_one_file(self):
        def fake_import_one_file(row, session, *args, **kwargs):
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
            self.svc.do_import("all", 9, ImportOptions(cleanup_dir=staged_dir))

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
        self.svc.do_import_internal([fpath], ImportInternalOptions(user_id=9))
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
            self.svc.do_import_internal([fpath], ImportInternalOptions(user_id=9))
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
        self.svc.do_import_internal([f1, f2], ImportInternalOptions(user_id=9))
        self.assertEqual(len(db.import_calls), 1)
        self.assertEqual(len(db.add_format_calls), 1)
        self.assertEqual(len(db.same_title_calls), 2)
        statuses = sorted(r.status for r in self.session.query(ScanFile).all())
        self.assertEqual(statuses, [ScanFile.IMPORTED, ScanFile.IMPORTED])


@unittest.skipUnless(HAS_CALIBRE, "needs calibre (real _import_one_file)")
class TestSetFieldPerBook(ScanP0TestBase):
    """Fix 2 回归：calibre 自定义列一律逐本 set_field（不攒批）。

    攒批（pending_fields）在 crash 时会静默丢未落盘列、且 #category 无自愈路径
    （只在新导入时写、重扫走 EXIST 不重算），实测收益 ~0.03ms/本/列可忽略（对照
    import_book ~50ms/本），故回到逐本同步写。这里钉「每本一次、每 dict 单键」。
    """

    def test_category_set_field_per_book(self):
        scan_service.CONF["IMPORT_CATEGORY_WITH_FOLDER"] = True
        db = FakeCalibreDB()
        self.svc.db = db
        files = []
        for i in range(25):
            files.append(self._touch(os.path.join("c%d" % (i % 3), "book%02d.txt" % i), b"cat-content-%02d" % i))
        self.svc.do_import_internal(files, ImportInternalOptions(user_id=9))
        cat_calls = [m for name, m in db.new_api.set_field_calls if name == constants.CALIBRE_COLUMN_CATEGORY]
        # 逐本写回：25 本 = 25 次调用，且每次只写一本（不是攒批的多键映射）
        self.assertEqual(len(cat_calls), 25)
        self.assertTrue(all(len(m) == 1 for m in cat_calls), cat_calls)
        covered = set()
        for m in cat_calls:
            covered.update(m.keys())
        self.assertEqual(len(covered), 25)
        self.assertEqual(self.session.query(ScanFile).filter(ScanFile.status == ScanFile.IMPORTED).count(), 25)

    def test_category_set_for_single_book(self):
        # 单本也必须落 category：逐本写是同步的，不依赖任何批提交/尾批兜底 flush
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
        self.svc.do_import_internal([fpath], ImportInternalOptions(user_id=9))
        row = self.session.query(ScanFile).filter(ScanFile.path == fpath).one()
        self.assertEqual(row.status, ScanFile.IMPORTED)
        cat_calls = [m for name, m in db.new_api.set_field_calls if name == constants.CALIBRE_COLUMN_CATEGORY]
        self.assertEqual(len(cat_calls), 1)
        self.assertEqual(list(cat_calls[0].keys()), [row.book_id])

    def test_category_not_set_without_flag(self):
        # IMPORT_CATEGORY_WITH_FOLDER 关闭（默认）时不写 #category
        old_val = scan_service.CONF.get("IMPORT_CATEGORY_WITH_FOLDER")
        scan_service.CONF["IMPORT_CATEGORY_WITH_FOLDER"] = False
        self.addCleanup(
            lambda: scan_service.CONF.update({"IMPORT_CATEGORY_WITH_FOLDER": old_val})
            if old_val is not None
            else scan_service.CONF.pop("IMPORT_CATEGORY_WITH_FOLDER", None)
        )
        db = FakeCalibreDB()
        self.svc.db = db
        fpath = self._touch(os.path.join("cats2", "plain.txt"), b"plain-content-2")
        self.svc.do_import_internal([fpath], ImportInternalOptions(user_id=9))
        cat_calls = [m for name, m in db.new_api.set_field_calls if name == constants.CALIBRE_COLUMN_CATEGORY]
        self.assertEqual(cat_calls, [])


class TestIncrementalSnapshotCommit(ScanP0TestBase):
    """Fix 1 回归：目录快照在 Phase1 中按目录增量提交（崩溃落在 Phase2 时下轮仍能剪枝）。

    do_import_internal 自身不调 _commit_dir_snapshots（那是 do_import 尾部的整轮兜底），
    故断言「跑完 do_import_internal 后快照已落库」只能来自增量路径。
    """

    def _fake_import_one_file(self):
        def fake(row, session, staged_ops=None, opts=None):
            row.status = ScanFile.IMPORTED
            staged_ops.append(("save_row", row))
            return None, ScanFile.IMPORTED
        return fake

    def _install_fake(self):
        self.svc._import_one_file = self._fake_import_one_file()
        self.addCleanup(lambda: self.svc.__dict__.pop("_import_one_file", None))

    def _snapshot_dirs(self):
        return {r.dir for r in self.session.query(models.ScanDirSnapshot).all()}

    def test_snapshot_committed_incrementally(self):
        self.svc.db = FakeCalibreDB()
        f1 = self._touch(os.path.join("d1", "a.txt"), b"a-content")
        f2 = self._touch(os.path.join("d1", "b.txt"), b"b-content")
        f3 = self._touch(os.path.join("d2", "c.txt"), b"c-content")
        filelist, visited, file_dir = self.svc._collect_files([self.tmpdir], use_snapshot=False)
        self.assertEqual(sorted(filelist), sorted([f1, f2, f3]))
        self._install_fake()
        self.svc.do_import_internal(filelist, visited=visited, file_dir=file_dir, opts=ImportInternalOptions(user_id=9))
        # d1 两个文件、d2 一个文件都已走完 Phase1 → 两者快照已增量落库
        snap = self._snapshot_dirs()
        self.assertIn(os.path.realpath(os.path.dirname(f1)), snap)
        self.assertIn(os.path.realpath(os.path.dirname(f3)), snap)
        self.assertEqual(self.session.query(ScanFile).filter(ScanFile.status == ScanFile.IMPORTED).count(), 3)

    def test_no_incremental_snapshot_without_visited(self):
        self.svc.db = FakeCalibreDB()
        self._touch(os.path.join("d1", "a.txt"), b"a-content")
        filelist, _visited, _file_dir = self.svc._collect_files([self.tmpdir], use_snapshot=False)
        self._install_fake()
        self.svc.do_import_internal(filelist, ImportInternalOptions(user_id=9))  # 无 visited/file_dir → 无增量提交
        self.assertEqual(self._snapshot_dirs(), set())

    def test_dropped_phase1_row_suppresses_incremental_snapshot(self):
        # 行级丢行（如遗留 UNIQUE(hash) 冲突）时不得推进任何增量快照：无行的文件一旦被
        # 剪枝即永久漏掉。模拟 _apply_phase1_batch 丢一行 → 目录快照必须为空。
        self.svc.db = FakeCalibreDB()
        self._touch(os.path.join("d1", "a.txt"), b"a-content")
        self._touch(os.path.join("d1", "b.txt"), b"b-content")
        filelist, visited, file_dir = self.svc._collect_files([self.tmpdir], use_snapshot=False)
        self._install_fake()
        orig = ScanService._apply_phase1_batch

        def dropping_apply(svc_self, session, staged):
            outcomes = orig(svc_self, session, staged)
            return outcomes[:-1] if outcomes else []

        with mock.patch.object(ScanService, "_apply_phase1_batch", dropping_apply):
            self.svc.do_import_internal(filelist, visited=visited, file_dir=file_dir, opts=ImportInternalOptions(user_id=9))
        self.assertEqual(self._snapshot_dirs(), set())

    def test_abort_suppresses_incremental_snapshot_in_flight(self):
        # abort 时「进行中」的目录不推进快照（下轮按老快照重扫）：已算的行照常落库
        # （取消不丢已算行），但该目录的增量快照被门控拦下。注：abort 前已随成功批
        # 落盘的目录快照不回滚（那是崩溃恢复特性，非本用例范围）。
        self.svc.db = FakeCalibreDB()
        self._touch(os.path.join("d1", "a.txt"), b"a-content")
        filelist, visited, file_dir = self.svc._collect_files([self.tmpdir], use_snapshot=False)
        self._install_fake()
        orig_fin = ScanService._scan_finalize

        def aborting_finalize(svc_self, *args, **kwargs):
            r = orig_fin(svc_self, *args, **kwargs)
            ScanService.static_abort_flag = True
            return r

        with mock.patch.dict(scan_service.CONF, {"scan_hash_workers": 1}):
            with mock.patch.object(ScanService, "_scan_finalize", aborting_finalize):
                self.svc.do_import_internal(filelist, visited=visited, file_dir=file_dir, opts=ImportInternalOptions(user_id=9))
        self.assertGreaterEqual(self.session.query(ScanFile).count(), 1)
        self.assertEqual(self._snapshot_dirs(), set())

    def test_midloop_error_commits_complete_dir_only(self):
        # 一个目录已完整落库后循环中途异常：该目录快照已增量提交，未走完的目录不提交。
        # 强制串行（hash_pool is None）保证 d1 在 d2 抛错前完成，规避 walk 顺序不确定性。
        self.svc.db = FakeCalibreDB()
        f1 = self._touch(os.path.join("d1", "a.txt"), b"a-content")
        f2 = self._touch(os.path.join("d2", "b.txt"), b"b-content")
        _fl, visited, file_dir = self.svc._collect_files([self.tmpdir], use_snapshot=False)
        filelist = [f1, f2]
        self._install_fake()
        orig_prep = ScanService._scan_prepare

        def raising_prepare(svc_self, fpath, *args, **kwargs):
            if os.path.dirname(fpath) == os.path.dirname(f2):
                raise RuntimeError("boom mid-loop")
            return orig_prep(svc_self, fpath, *args, **kwargs)

        with mock.patch.dict(scan_service.CONF, {"scan_hash_workers": 1}):
            with mock.patch.object(ScanService, "_scan_prepare", raising_prepare):
                with self.assertRaises(RuntimeError):
                    self.svc.do_import_internal(filelist, visited=visited, file_dir=file_dir, opts=ImportInternalOptions(user_id=9))
        snap = self._snapshot_dirs()
        self.assertIn(os.path.realpath(os.path.dirname(f1)), snap)
        self.assertNotIn(os.path.realpath(os.path.dirname(f2)), snap)


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

        def writing_stub(row, wsession, *args, **kwargs):
            delivered.append(row.path)
            row.status = ScanFile.IMPORTED
            ok = self.svc.save_or_rollback(row, wsession)
            return (None, ScanFile.IMPORTED) if ok else (None, None)

        self.svc._import_one_file = writing_stub
        self.addCleanup(self._restore_import_one_file)
        with mock.patch.object(ScanService, "_compute_hash", slow_hash):
            with mock.patch.object(scan_service, "PHASE1_BATCH_SIZE", 4):
                self.svc.do_import_internal(files, ImportInternalOptions(user_id=9))
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
            new_id, status = self.svc._import_one_file(row, self.session, opts=ImportInternalOptions(user_id=9, scan_upload_path=self.tmpdir, force=False))
        self.assertEqual((new_id, status), (None, None))


class TestNonReadyNotEnqueued(ScanP0TestBase):
    def test_drop_rows_never_reach_worker(self):
        # 同内容两文件同批：第二本 DROP 落库但绝不入队，worker 只处理 READY
        db = FakeCalibreDB()
        self.svc.db = db
        f1 = self._touch("dup1.txt", b"same-bytes")
        f2 = self._touch("dup2.txt", b"same-bytes")
        delivered = []

        def fake_import_one_file(row, session, *args, **kwargs):
            delivered.append(row.path)
            return None, None

        self.svc._import_one_file = fake_import_one_file
        self.addCleanup(self._restore_import_one_file)
        self.svc.do_import_internal([f1, f2], ImportInternalOptions(user_id=9))
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


class TestScanIgnoreDirsAndReplace(ScanP0TestBase):
    def test_collect_files_skips_ignored_dirs(self):
        scan_service.CONF["SCAN_IGNORE_DIRS"] = ["skipme"]
        self._touch(os.path.join("skipme", "a.epub"), b"ignored")
        kept = self._touch(os.path.join("keep", "b.epub"), b"kept")
        files, _, _ = self.svc._collect_files(paths="all")
        self.assertEqual(files, [kept])

    def test_imported_unchanged_signature_is_skipped(self):
        scan_service.CONF["SCAN_REPLACE_SAME_TITLE"] = True
        fpath = self._touch("same.epub", b"content-1")
        row = ScanFile(fpath, "sha256:old", 1)
        row.status = ScanFile.IMPORTED
        row.book_id = 7
        row.data = {
            scan_service.FILE_SIG_KEY: ScanService.file_signature(fpath)
        }
        self.session.add(row)
        self.session.commit()
        self.svc.db = FakeCalibreDB(existing={7})
        rid, state = self.svc._scan_one_file(fpath, self.session, 1, set(), set(), False)
        self.assertEqual((rid, state), (None, None))

    def test_imported_changed_signature_is_reevaluated(self):
        scan_service.CONF["SCAN_REPLACE_SAME_TITLE"] = True
        fpath = self._touch("changed.epub", b"content-2")
        row = ScanFile(fpath, "sha256:old", 1)
        row.status = ScanFile.IMPORTED
        row.book_id = 7
        row.data = {scan_service.FILE_SIG_KEY: [1, 1, 1, 1]}
        self.session.add(row)
        self.session.commit()
        self.svc.db = FakeCalibreDB(existing={7})
        rid, state = self.svc._scan_one_file(fpath, self.session, 1, set(), set(), False)
        self.assertIsNotNone(rid)
        self.assertEqual(state, ScanFile.READY)

    def test_file_content_compare_attr_then_hash(self):
        a = self._touch("a.bin", b"abc")
        b = self._touch("b.bin", b"abc")
        c = self._touch("c.bin", b"abd")
        hash_a, _ = self.svc._compute_hash(a)
        hash_c, _ = self.svc._compute_hash(c)
        self.assertTrue(self.svc._scan_files_same_content(a, b, hash_a))
        self.assertFalse(self.svc._scan_files_same_content(a, c, hash_c))


if __name__ == "__main__":
    unittest.main()
