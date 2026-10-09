"""P0 扫描导入加速回归测试（calibre 轻量检查 / 标题映射 / Phase1 批量落库 / set_field 攒批）。

- 不依赖 calibre 的用例（has_id 存在性、回退路径、批量提交可见性、行级隔离、
  do_import_internal 行全送达）Windows 直跑；
- 走真实 _import_one_file 的用例（标题映射、大小写归一、set_field 攒批）需要
  calibre（函数头 import Metadata），缺 calibre 时自动跳过，WSL 全量跑。
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
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
        self.get_id_map_calls = []
        self.set_field_calls = []
        self.fail_set_field = False

    def has_id(self, book_id):
        self.has_id_calls.append(book_id)
        return book_id in self._db._ids

    def all_book_ids(self):
        return frozenset(self._db._ids)

    def get_id_map(self, field):
        self.get_id_map_calls.append(field)
        assert field == "title"
        return dict(self._db._titles)

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

    def test_same_title_fallback_without_new_api(self):
        db = NoNewAPIDB()
        db.new_api = None
        self.svc.db = db
        mi = SimpleNamespace(title="Fallback Title")
        ids = self.svc._same_title_ids(mi, {"map": None, "built": True})
        self.assertEqual(ids, set())
        self.assertEqual(db.same_title_calls, ["Fallback Title"])


class TestPhase1Batching(ScanP0TestBase):
    def _raw_count(self, dbpath):
        con = sqlite3.connect(dbpath)
        try:
            return con.execute("SELECT COUNT(*) FROM scanfiles").fetchone()[0]
        finally:
            con.close()

    def test_batched_rows_invisible_until_commit(self):
        dbpath = os.path.join(self.tmpdir, "batch.db").replace("\\", "/")
        engine = create_engine("sqlite:///%s" % dbpath)
        session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(session)
        models.Base.metadata.create_all(engine)
        self.svc.session = session
        self.svc.db = FakeCalibreDB()
        files = [self._touch("n%d.txt" % i, b"content-%d" % i) for i in range(3)]
        for fpath in files:
            rid, state = self.svc._scan_one_file(fpath, session, 1, set(), set(), False, batched=True)
            self.assertEqual(state, ScanFile.READY)
            self.assertIsNotNone(rid)
        # 只 flush 未 commit：独立连接看不到
        self.assertEqual(self._raw_count(dbpath), 0)
        session.commit()
        rows = session.query(ScanFile).order_by(ScanFile.id).all()
        self.assertEqual([r.status for r in rows], [ScanFile.READY] * 3)
        self.assertEqual(self._raw_count(dbpath), 3)
        session.remove()

    def test_unbatched_rows_visible_immediately(self):
        db = FakeCalibreDB()
        self.svc.db = db
        fpath = self._touch("legacy.txt", b"legacy-content")
        rid, state = self.svc._scan_one_file(fpath, self.session, 1, set(), set(), False, batched=False)
        self.assertEqual(state, ScanFile.READY)
        row = self.session.query(ScanFile).filter(ScanFile.path == fpath).one()
        self.assertEqual(row.status, ScanFile.READY)

    def test_phase1_save_isolates_row_error(self):
        # 遗留 UNIQUE(hash) 约束库：第二行 flush 失败不能毒化第一行
        self.session.execute(text("CREATE UNIQUE INDEX ux_scanfiles_hash ON scanfiles (hash)"))
        self.svc.db = FakeCalibreDB()
        r1 = ScanFile(os.path.join(self.tmpdir, "u1.txt"), "sha256:dup", 1)
        r2 = ScanFile(os.path.join(self.tmpdir, "u2.txt"), "sha256:dup", 1)
        self.assertTrue(self.svc._phase1_save(r1, self.session, True))
        self.assertFalse(self.svc._phase1_save(r2, self.session, True))
        self.session.commit()
        rows = self.session.query(ScanFile).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].path, r1.path)

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
        with mock.patch.object(scan_service, "PHASE1_BATCH_SIZE", 2):
            self.svc.do_import_internal(files, 9)
        self.assertEqual(sorted(delivered), sorted(files))
        self.assertEqual(self.session.query(ScanFile).filter(ScanFile.status == ScanFile.READY).count(), 5)


@unittest.skipUnless(HAS_CALIBRE, "needs calibre (real _import_one_file)")
class TestTitleMapEndToEnd(ScanP0TestBase):
    def test_title_map_built_once_and_no_duplicate(self):
        db = FakeCalibreDB()
        self.svc.db = db
        f1 = self._touch(os.path.join("d1", "同名书.txt"), b"first-content-aaa")
        f2 = self._touch(os.path.join("d2", "同名书.txt"), b"second-content-bbb")
        self.svc.do_import_internal([f1, f2], 9)
        # 全轮只拉一次全库映射；第二本走加格式分支，不建重复书
        self.assertEqual(len(db.new_api.get_id_map_calls), 1)
        self.assertEqual(len(db.import_calls), 1)
        self.assertEqual(len(db.add_format_calls), 1)
        statuses = sorted(r.status for r in self.session.query(ScanFile).all())
        self.assertEqual(statuses, [ScanFile.IMPORTED, ScanFile.IMPORTED])

    def test_title_normalization_matches_calibre(self):
        # 库内 "Hello Book"，文件标题全小写：精确相等会漏判，icu 口径必须命中
        db = FakeCalibreDB(titles={5: "Hello Book"})
        self.svc.db = db
        f1 = self._touch("hello book.txt", b"norm-content")
        self.svc.do_import_internal([f1], 9)
        self.assertEqual(len(db.new_api.get_id_map_calls), 1)
        self.assertEqual(db.import_calls, [])
        self.assertEqual(len(db.add_format_calls), 1)
        row = self.session.query(ScanFile).filter(ScanFile.path == f1).one()
        self.assertEqual(row.status, ScanFile.IMPORTED)
        self.assertEqual(row.book_id, 5)


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
        # worker 批大小 20：20 本一批 + 尾批 5 本 = 2 次调用，而不是 25 次
        self.assertEqual(len(cat_calls), 2)
        covered = set()
        for m in cat_calls:
            covered.update(m.keys())
        self.assertEqual(len(covered), 25)
        self.assertEqual(self.session.query(ScanFile).filter(ScanFile.status == ScanFile.IMPORTED).count(), 25)

    def test_pending_fields_flushed_without_category(self):
        db = FakeCalibreDB()
        self.svc.db = db
        f1 = self._touch("plain.txt", b"plain-content")
        self.svc.do_import_internal([f1], 9)
        row = self.session.query(ScanFile).filter(ScanFile.path == f1).one()
        self.assertEqual(row.status, ScanFile.IMPORTED)


if __name__ == "__main__":
    unittest.main()
