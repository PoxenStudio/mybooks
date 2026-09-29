#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""扫描导入服务端选择器与 scanfiles 索引迁移测试。

纯单元测试：内存 sqlite + 临时文件，不依赖 tornado 服务与 calibre。
覆盖：
- ScanService.resolve_ready_paths / resolve_filter_paths / resolve_dir_paths
- handlers.scan.normalize_import_filelist
- handlers.scan.Scanner.summary 的 ready 计数
- async_service._ensure_scanfiles_indexes 的幂等、旧库 UNIQUE(hash) 兼容与 (status, import_type) 复合索引
- 按状态的选择/批删/summary 一律排除有声书记录（import_type=2），NULL 视为电子书
- handlers.scan.parse_delete_files 的缺省 False（真删必须显式传 true）与未知形态拒绝
- ScanService._bulk_delete_core 的批次边界取消（已提交批次不回滚）
"""

import os
import shutil
import tempfile
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import constants, models
from webserver.handlers.scan import Scanner, normalize_import_filelist, parse_delete_files
from webserver.models import ScanFile
from webserver.services.async_service import _ensure_scanfiles_indexes
from webserver.services.scan_service import ScanService


class ScanSelectorTestBase(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)
        self.tmpdir = tempfile.mkdtemp(prefix="scan_selector_test_")
        self._hash_seq = 0

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _touch(self, rel):
        path = os.path.join(self.tmpdir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"x")
        return path

    def _row(self, path, status, import_type=None):
        self._hash_seq += 1
        row = ScanFile(path, "sha256:%d" % self._hash_seq, 1)
        row.status = status
        if import_type is not None:
            row.import_type = import_type
        self.session.add(row)
        return row

    def _audio_row(self, path, status):
        return self._row(path, status, import_type=constants.IMPORT_TYPE_AUDIOBOOK)


class TestResolveReadyPaths(ScanSelectorTestBase):
    def test_existing_file_returned_and_missing_marked_missed(self):
        existing = self._touch("a.epub")
        self._row(existing, ScanFile.READY)
        missing = os.path.join(self.tmpdir, "gone.epub")
        self._row(missing, ScanFile.READY)

        paths = ScanService.resolve_ready_paths(self.session)

        self.assertEqual(paths, [existing])
        row = self.session.query(ScanFile).filter(ScanFile.path == missing).one()
        self.assertEqual(row.status, ScanFile.MISSED)

    def test_mark_missing_false_leaves_status(self):
        missing = os.path.join(self.tmpdir, "gone.epub")
        self._row(missing, ScanFile.READY)

        self.assertEqual(ScanService.resolve_ready_paths(self.session, mark_missing=False), [])

        row = self.session.query(ScanFile).filter(ScanFile.path == missing).one()
        self.assertEqual(row.status, ScanFile.READY)

    def test_only_ready_considered(self):
        existing = self._touch("b.epub")
        self._row(existing, ScanFile.NEW)
        self._row(existing, ScanFile.IMPORTED)
        self._row(existing, ScanFile.EXIST)
        self._row(existing, ScanFile.INVALID)

        self.assertEqual(ScanService.resolve_ready_paths(self.session), [])

    def test_audiobook_ready_excluded(self):
        # READY 只由电子书扫描阶段写入；万一有声书记录带上该状态，续导选择器也不该碰它
        # （旧行为会把目录当成"源文件已不存在"，顺手把跳表记录标成 MISSED）
        audio_dir = os.path.join(self.tmpdir, "audiobooks", "有声书A")
        os.makedirs(audio_dir, exist_ok=True)
        self._audio_row(audio_dir, ScanFile.READY)

        self.assertEqual(ScanService.resolve_ready_paths(self.session), [])

        row = self.session.query(ScanFile).filter(ScanFile.path == audio_dir).one()
        self.assertEqual(row.status, ScanFile.READY)


class TestEbookScopeFilter(ScanSelectorTestBase):
    """按状态的公共过滤口径只认电子书扫描记录（有声书 import_type=2 不参与）。"""

    def test_status_filter_excludes_audiobooks(self):
        ebook = self._touch("bad.epub")
        audio_dir = os.path.join(self.tmpdir, "audiobooks", "有声书A")
        os.makedirs(audio_dir, exist_ok=True)
        self._row(ebook, ScanFile.INVALID)
        self._audio_row(audio_dir, ScanFile.INVALID)
        self._audio_row(audio_dir, ScanFile.EXIST)
        self._audio_row(audio_dir, ScanFile.IMPORTED)

        invalid = ScanService.status_filter(
            self.session.query(ScanFile.id), ScanFile.INVALID
        )
        self.assertEqual(invalid.count(), 1)
        # 有声书的 EXIST 同样不进电子书 todo 口径
        todo = ScanService.status_filter(self.session.query(ScanFile.id), "todo")
        self.assertEqual(todo.count(), 1)

    def test_legacy_null_import_type_treated_as_ebook(self):
        # import_type 是后加列，历史行可能为 NULL，必须按电子书处理而非被过滤掉
        legacy = self._touch("legacy.epub")
        row = self._row(legacy, ScanFile.INVALID)
        row.import_type = None
        self.session.flush()

        query = ScanService.status_filter(self.session.query(ScanFile.id), ScanFile.INVALID)

        self.assertEqual(query.count(), 1)


class TestResolveFilterPaths(ScanSelectorTestBase):
    def test_todo_excludes_imported_and_missing(self):
        ready = self._touch("r.epub")
        invalid = self._touch("i.epub")
        imported = self._touch("done.epub")
        missing = os.path.join(self.tmpdir, "gone.epub")
        self._row(ready, ScanFile.READY)
        self._row(invalid, ScanFile.INVALID)
        self._row(imported, ScanFile.IMPORTED)
        self._row(missing, ScanFile.MISSED)

        paths = ScanService.resolve_filter_paths(self.session, "todo")

        self.assertEqual(sorted(paths), sorted([ready, invalid]))
        # 不改记录状态
        imported_row = self.session.query(ScanFile).filter(ScanFile.path == imported).one()
        self.assertEqual(imported_row.status, ScanFile.IMPORTED)

    def test_status_equality(self):
        drop = self._touch("d.epub")
        ready = self._touch("r.epub")
        self._row(drop, ScanFile.DROP)
        self._row(ready, ScanFile.READY)

        self.assertEqual(ScanService.resolve_filter_paths(self.session, ScanFile.DROP), [drop])
        self.assertEqual(ScanService.resolve_filter_paths(self.session, ScanFile.MISSED), [])
        self.assertEqual(ScanService.resolve_filter_paths(self.session, "bogus"), [])


class TestResolveDirPaths(ScanSelectorTestBase):
    def setUp(self):
        super().setUp()
        self.scan_dir = os.path.join(self.tmpdir, "imports")
        os.makedirs(os.path.join(self.scan_dir, "科幻"))
        os.makedirs(os.path.join(self.scan_dir, ".hidden"))
        os.makedirs(os.path.join(self.scan_dir, "audiobooks"))

    def test_valid_dirs_dedup(self):
        dirs = ScanService.resolve_dir_paths(self.scan_dir, ["科幻", "科幻/", "科幻"])
        self.assertEqual(dirs, [os.path.realpath(os.path.join(self.scan_dir, "科幻"))])

    def test_nested_path_rejected(self):
        # 一级子目录契约：名字里带路径分隔符的嵌套子路径不收
        os.makedirs(os.path.join(self.scan_dir, "科幻", "子目录"))
        dirs = ScanService.resolve_dir_paths(self.scan_dir, ["科幻/子目录", "科幻\\子目录"])
        self.assertEqual(dirs, [])

    def test_invalid_names_skipped(self):
        dirs = ScanService.resolve_dir_paths(
            self.scan_dir, ["nope", ".hidden", "audiobooks", "", None, 123]
        )
        self.assertEqual(dirs, [])

    def test_traversal_outside_rejected(self):
        dirs = ScanService.resolve_dir_paths(self.scan_dir, ["..", "../outside", "科幻/../../outside"])
        self.assertEqual(dirs, [])

    def test_inner_segment_bypass_exclusions(self):
        # 内层段不能绕过排除项：解析后按相对路径首段复核
        dirs = ScanService.resolve_dir_paths(self.scan_dir, ["科幻/../audiobooks", "科幻/../.hidden"])
        self.assertEqual(dirs, [])

    def test_tilde_dir_excluded(self):
        os.makedirs(os.path.join(self.scan_dir, "~temp"))
        dirs = ScanService.resolve_dir_paths(self.scan_dir, ["~temp"])
        self.assertEqual(dirs, [])

    def test_absolute_outside_rejected(self):
        dirs = ScanService.resolve_dir_paths(self.scan_dir, [self.tmpdir, os.path.realpath(self.tmpdir)])
        self.assertEqual(dirs, [])

    def test_missing_base(self):
        self.assertEqual(ScanService.resolve_dir_paths(os.path.join(self.tmpdir, "nope"), ["科幻"]), [])
        self.assertEqual(ScanService.resolve_dir_paths("", ["科幻"]), [])


class TestBulkDeleteCore(ScanSelectorTestBase):
    def test_deletes_records_and_confined_files(self):
        scan_dir = os.path.join(self.tmpdir, "imports")
        in1 = self._touch(os.path.join("imports", "a.epub"))
        in2 = self._touch(os.path.join("imports", "b.epub"))
        outside = self._touch("outside.epub")
        gone = os.path.join(scan_dir, "gone.epub")  # 记录在、文件本就缺失
        self._row(in1, ScanFile.DROP)
        self._row(in2, ScanFile.DROP)
        self._row(outside, ScanFile.DROP)
        self._row(gone, ScanFile.MISSED)
        progress = []

        total, deleted_files, skipped = ScanService._bulk_delete_core(
            self.session, ScanFile.DROP, True, scan_dir,
            progress=lambda p, t, f, s: progress.append((p, t, f, s)),
        )

        # 目录内 2 条真删（文件一并删除），目录外 1 条只删记录并计 skip
        self.assertEqual(total, 3)
        self.assertEqual(deleted_files, 2)
        self.assertEqual(skipped, 1)
        self.assertFalse(os.path.exists(in1))
        self.assertFalse(os.path.exists(in2))
        self.assertTrue(os.path.exists(outside))
        self.assertEqual(
            self.session.query(ScanFile).filter(ScanFile.status == ScanFile.DROP).count(), 0
        )
        self.assertEqual(self.session.query(ScanFile).filter(ScanFile.path == gone).count(), 1)
        self.assertEqual(progress[-1], (3, 3, 2, 1))

    def test_todo_removes_all_non_imported(self):
        scan_dir = os.path.join(self.tmpdir, "imports")
        in1 = self._touch(os.path.join("imports", "a.epub"))
        in2 = self._touch(os.path.join("imports", "b.epub"))
        imported = self._touch(os.path.join("imports", "c.epub"))
        self._row(in1, ScanFile.DROP)
        self._row(in2, ScanFile.INVALID)
        self._row(imported, ScanFile.IMPORTED)

        total, deleted_files, skipped = ScanService._bulk_delete_core(
            self.session, "todo", True, scan_dir,
        )

        self.assertEqual(total, 2)
        self.assertEqual(deleted_files, 2)
        self.assertTrue(os.path.exists(imported))
        self.assertEqual(self.session.query(ScanFile).count(), 1)

    def test_records_only_mode_keeps_files(self):
        scan_dir = os.path.join(self.tmpdir, "imports")
        in1 = self._touch(os.path.join("imports", "a.epub"))
        self._row(in1, ScanFile.DROP)

        ScanService._bulk_delete_core(self.session, ScanFile.DROP, False, scan_dir)

        self.assertTrue(os.path.exists(in1))
        self.assertEqual(self.session.query(ScanFile).count(), 0)

    def test_missing_scan_dir_keeps_files(self):
        scan_dir = os.path.join(self.tmpdir, "nope")
        in1 = self._touch(os.path.join("imports", "a.epub"))
        self._row(in1, ScanFile.NEW)

        total, deleted_files, skipped = ScanService._bulk_delete_core(
            self.session, ScanFile.NEW, True, scan_dir,
        )

        self.assertEqual(total, 1)
        self.assertEqual(deleted_files, 0)
        self.assertTrue(os.path.exists(in1))

    def test_multi_batch_commits(self):
        scan_dir = os.path.join(self.tmpdir, "imports")
        paths = [self._touch(os.path.join("imports", "m%02d.epub" % i)) for i in range(12)]
        for p in paths:
            self._row(p, ScanFile.DROP)
        progress = []

        total, deleted_files, skipped = ScanService._bulk_delete_core(
            self.session, ScanFile.DROP, True, scan_dir,
            progress=lambda p_, t, f, s: progress.append((p_, t, f, s)),
            batch_size=5,
        )

        self.assertEqual(total, 12)
        self.assertEqual(deleted_files, 12)
        self.assertEqual(skipped, 0)
        self.assertTrue(all(not os.path.exists(p) for p in paths))
        self.assertEqual(self.session.query(ScanFile).count(), 0)
        # 12 行、批 5 → 3 次提交回调，processed 单调推进
        self.assertEqual([row[0] for row in progress], [5, 10, 12])
        self.assertEqual(progress[-1], (12, 12, 12, 0))

    def test_cancel_after_first_batch_keeps_rest(self):
        """取消在批次边界生效：已提交的批次不回滚，剩余记录与文件保留。"""
        scan_dir = os.path.join(self.tmpdir, "imports")
        paths = [self._touch(os.path.join("imports", "m%02d.epub" % i)) for i in range(12)]
        for p in paths:
            self._row(p, ScanFile.DROP)
        calls = {"n": 0}

        def should_cancel():
            calls["n"] += 1
            return calls["n"] > 1  # 第一批跑完后再检查即取消

        total, deleted_files, skipped = ScanService._bulk_delete_core(
            self.session, ScanFile.DROP, True, scan_dir,
            batch_size=5, should_cancel=should_cancel,
        )

        # total 仍是开工前的全量计数，实际只处理了第一批
        self.assertEqual(total, 12)
        self.assertEqual(deleted_files, 5)
        self.assertEqual(skipped, 0)
        self.assertEqual(self.session.query(ScanFile).count(), 7)
        self.assertTrue(all(not os.path.exists(p) for p in paths[:5]))
        self.assertTrue(all(os.path.exists(p) for p in paths[5:]))
        # 循环头检查一次 + 第一批结束后检查一次即退出，不再进入第三轮
        self.assertEqual(calls["n"], 2)

    def test_cancel_before_any_batch_deletes_nothing(self):
        scan_dir = os.path.join(self.tmpdir, "imports")
        in1 = self._touch(os.path.join("imports", "a.epub"))
        self._row(in1, ScanFile.DROP)

        total, deleted_files, skipped = ScanService._bulk_delete_core(
            self.session, ScanFile.DROP, True, scan_dir,
            should_cancel=lambda: True,
        )

        self.assertEqual(total, 1)
        self.assertEqual(deleted_files, 0)
        self.assertEqual(skipped, 0)
        self.assertTrue(os.path.exists(in1))
        self.assertEqual(self.session.query(ScanFile).count(), 1)

    def test_commonpath_valueerror_counts_outside(self):
        scan_dir = os.path.join(self.tmpdir, "imports")
        in1 = self._touch(os.path.join("imports", "a.epub"))
        self._row(in1, ScanFile.DROP)

        from unittest import mock

        with mock.patch("os.path.commonpath", side_effect=ValueError("cross-drive")):
            total, deleted_files, skipped = ScanService._bulk_delete_core(
                self.session, ScanFile.DROP, True, scan_dir,
            )

        # commonpath 解析失败按越界保守处理：只删记录计 skip，绝不动文件
        self.assertEqual(total, 1)
        self.assertEqual(deleted_files, 0)
        self.assertEqual(skipped, 1)
        self.assertTrue(os.path.exists(in1))
        self.assertEqual(self.session.query(ScanFile).count(), 0)

    def test_symlink_outside_keeps_target(self):
        scan_dir = os.path.join(self.tmpdir, "imports")
        outside_dir = os.path.join(self.tmpdir, "outside")
        os.makedirs(outside_dir, exist_ok=True)
        target = os.path.join(outside_dir, "t.epub")
        with open(target, "wb") as fh:
            fh.write(b"x")
        link = os.path.join(scan_dir, "link.epub")
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable on this platform/account")
        self._row(link, ScanFile.DROP)

        total, deleted_files, skipped = ScanService._bulk_delete_core(
            self.session, ScanFile.DROP, True, scan_dir,
        )

        # realpath 解析到目录外：只删记录，链接与目标文件都保留
        self.assertEqual(total, 1)
        self.assertEqual(deleted_files, 0)
        self.assertEqual(skipped, 1)
        self.assertTrue(os.path.exists(target))
        self.assertTrue(os.path.lexists(link))
        self.assertEqual(self.session.query(ScanFile).count(), 0)

    def test_audiobook_records_and_dirs_kept(self):
        """有声书记录不参与批删——它是"目录已处理过"的跳表，删了下次导入全量重跑。

        旧行为实锤：选「无效」批删会把有声书 INVALID 目录记录一并清掉。
        """
        scan_dir = os.path.join(self.tmpdir, "imports")
        ebook = self._touch(os.path.join("imports", "bad.epub"))
        self._touch(os.path.join("audiobooks", "有声书A", "01.mp3"))
        audio_dir = os.path.join(self.tmpdir, "audiobooks", "有声书A")
        self._row(ebook, ScanFile.INVALID)
        self._audio_row(audio_dir, ScanFile.INVALID)

        total, deleted_files, skipped = ScanService._bulk_delete_core(
            self.session, ScanFile.INVALID, True, scan_dir,
        )

        self.assertEqual(total, 1)
        self.assertEqual(deleted_files, 1)
        self.assertFalse(os.path.exists(ebook))
        audio_row = self.session.query(ScanFile).filter(ScanFile.path == audio_dir).one()
        self.assertEqual(audio_row.import_type, constants.IMPORT_TYPE_AUDIOBOOK)
        self.assertTrue(os.path.isfile(os.path.join(audio_dir, "01.mp3")))

    def test_todo_bulk_delete_keeps_audiobook_records(self):
        scan_dir = os.path.join(self.tmpdir, "imports")
        ebook = self._touch(os.path.join("imports", "a.epub"))
        audio_dir = os.path.join(self.tmpdir, "audiobooks", "有声书B")
        os.makedirs(audio_dir, exist_ok=True)
        self._row(ebook, ScanFile.DROP)
        self._audio_row(audio_dir, ScanFile.INVALID)

        total, deleted_files, skipped = ScanService._bulk_delete_core(
            self.session, "todo", True, scan_dir,
        )

        self.assertEqual(total, 1)
        self.assertEqual(deleted_files, 1)
        rows = self.session.query(ScanFile).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].import_type, constants.IMPORT_TYPE_AUDIOBOOK)


class TestNormalizeImportFilelist(unittest.TestCase):
    def test_legacy_forms(self):
        self.assertEqual(normalize_import_filelist("all"), ("all", None))
        self.assertEqual(
            normalize_import_filelist(["/a.epub", "/b.epub"]),
            ("paths", ["/a.epub", "/b.epub"]),
        )

    def test_selectors(self):
        self.assertEqual(normalize_import_filelist("ready"), ("ready", None))
        self.assertEqual(normalize_import_filelist({"dirs": "科幻"}), ("dirs", ["科幻"]))
        self.assertEqual(normalize_import_filelist({"dirs": ["a", "b"]}), ("dirs", ["a", "b"]))
        self.assertEqual(normalize_import_filelist({"filter": "todo"}), ("filter", "todo"))
        for status in (
            ScanFile.NEW,
            ScanFile.READY,
            ScanFile.DROP,
            ScanFile.EXIST,
            ScanFile.INVALID,
            ScanFile.MISSED,
            ScanFile.PERMISSION,
        ):
            self.assertEqual(normalize_import_filelist({"filter": status}), ("filter", status))

    def test_invalid_forms(self):
        for bad in (
            None,
            "",
            42,
            {},
            {"dirs": 123},
            {"filter": "done"},
            {"filter": "all"},
            {"filter": "imported"},
            {"filter": "NEW"},
            {"filter": "bogus"},
            {"filter": ""},
            {"dirs": [], "filter": "todo"},
            {"unknown": 1},
        ):
            self.assertIsNone(normalize_import_filelist(bad), repr(bad))


class TestParseDeleteFiles(unittest.TestCase):
    """delete_files 解析：缺省为 False（真删高危，API 必须显式声明）。"""

    def test_default_is_false(self):
        self.assertIs(parse_delete_files(None), False)
        # 显式传 default 时可覆盖（服务层缺省亦为 False）
        self.assertIs(parse_delete_files(None, default=False), False)

    def test_bool_passthrough(self):
        self.assertIs(parse_delete_files(True), True)
        self.assertIs(parse_delete_files(False), False)

    def test_string_forms(self):
        for raw, want in (
            ("true", True), ("True", True), (" TRUE ", True), ("1", True), ("yes", True),
            ("false", False), ("False", False), ("0", False), ("no", False), ("", False),
        ):
            self.assertIs(parse_delete_files(raw), want, repr(raw))

    def test_unknown_forms_rejected(self):
        # "false" 决不能被当成真删，"maybe" 也不能被当成默认值
        for bad in ("maybe", "TRUE!", 1, 0, 2, [], {}, ["true"], object()):
            self.assertIsNone(parse_delete_files(bad), repr(bad))


class TestScanfilesIndexes(unittest.TestCase):
    def _index_columns(self, session):
        result = {}
        for row in session.execute(text('PRAGMA index_list("scanfiles")')).fetchall():
            result[row[1]] = [
                c[2] for c in session.execute(text('PRAGMA index_info("%s")' % row[1])).fetchall()
            ]
        return result

    def test_fresh_table_idempotent(self):
        engine = create_engine("sqlite://")
        session = scoped_session(sessionmaker(bind=engine))
        models.bind_session(session)
        models.Base.metadata.create_all(engine)

        self.assertTrue(_ensure_scanfiles_indexes(session))
        cols = self._index_columns(session)
        for name in ("ix_scanfiles_path", "ix_scanfiles_hash", "ix_scanfiles_import_id"):
            self.assertIn(name, cols)
            self.assertEqual(cols[name], [name.rsplit("ix_scanfiles_", 1)[1]])
        # status 索引是 (status, import_type) 复合：按状态的查询一律带电子书口径过滤
        self.assertEqual(cols["ix_scanfiles_status_import_type"], ["status", "import_type"])

        # 幂等：第二次不再新建
        self.assertFalse(_ensure_scanfiles_indexes(session))
        self.assertEqual(self._index_columns(session), cols)

    def test_legacy_unique_hash_not_duplicated(self):
        engine = create_engine("sqlite://")
        session = scoped_session(sessionmaker(bind=engine))
        models.bind_session(session)
        session.execute(text(
            "CREATE TABLE scanfiles ("
            " id INTEGER PRIMARY KEY, name VARCHAR(512), path VARCHAR(1024),"
            " hash VARCHAR(512) UNIQUE, status VARCHAR(24), import_id INTEGER)"
        ))
        # 真实升级路径：adjust_scanfile_table 先补 import_type 列，再建索引
        session.execute(text("ALTER TABLE scanfiles ADD COLUMN import_type INTEGER DEFAULT 0"))

        self.assertTrue(_ensure_scanfiles_indexes(session))
        cols = self._index_columns(session)
        hash_leading = [name for name, cs in cols.items() if cs and cs[0] == "hash"]
        self.assertEqual(len(hash_leading), 1)
        self.assertNotIn("ix_scanfiles_hash", cols)
        self.assertIn("ix_scanfiles_path", cols)
        self.assertIn("ix_scanfiles_import_id", cols)
        self.assertEqual(cols["ix_scanfiles_status_import_type"], ["status", "import_type"])

    def test_failed_index_does_not_rollback_other_changes(self):
        engine = create_engine("sqlite://")
        session = scoped_session(sessionmaker(bind=engine))
        models.bind_session(session)
        session.execute(text(
            "CREATE TABLE scanfiles ("
            " id INTEGER PRIMARY KEY, name VARCHAR(512), path VARCHAR(1024),"
            " hash VARCHAR(512), status VARCHAR(24), import_id INTEGER)"
        ))
        session.commit()
        session.execute(text("CREATE TABLE pending_migration (id INTEGER)"))

        self.assertTrue(_ensure_scanfiles_indexes(session))
        session.rollback()
        cols = self._index_columns(session)
        self.assertNotIn("ix_scanfiles_status_import_type", cols)
        for name in ("ix_scanfiles_path", "ix_scanfiles_hash", "ix_scanfiles_import_id"):
            self.assertIn(name, cols)
        tables = [r[0] for r in session.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))]
        self.assertIn("pending_migration", tables)


class TestScannerSummary(ScanSelectorTestBase):
    def test_ready_count_in_summary(self):
        for name, status in [
            ("a.epub", ScanFile.IMPORTED),
            ("b.epub", ScanFile.IMPORTED),
            ("c.epub", ScanFile.EXIST),
            ("d.epub", ScanFile.READY),
            ("e.epub", ScanFile.READY),
            ("f.epub", ScanFile.READY),
            ("g.epub", ScanFile.INVALID),
        ]:
            self._row(os.path.join(self.tmpdir, name), status)

        scanner = Scanner(None, self.session)
        try:
            summary = scanner.summary()
        finally:
            scanner.close()

        self.assertEqual(summary["total"], 7)
        self.assertEqual(summary["done"], 3)
        self.assertEqual(summary["todo"], 4)
        self.assertEqual(summary["ready"], 3)
        self.assertEqual(summary["counts"].get(ScanFile.READY), 3)
        self.assertEqual(summary["counts"].get(ScanFile.IMPORTED), 2)
        self.assertEqual(summary["counts"].get(ScanFile.INVALID), 1)

    def test_audiobooks_excluded_and_total_matches_counts(self):
        # summary 与批量删除同口径：total 必须等于 sum(counts)，确认框条数才与实际删除数一致
        self._row(os.path.join(self.tmpdir, "a.epub"), ScanFile.INVALID)
        self._audio_row(os.path.join(self.tmpdir, "audiobooks", "有声书A"), ScanFile.INVALID)
        self._audio_row(os.path.join(self.tmpdir, "audiobooks", "有声书A"), ScanFile.IMPORTED)

        scanner = Scanner(None, self.session)
        try:
            summary = scanner.summary()
        finally:
            scanner.close()

        self.assertEqual(summary["total"], 1)
        self.assertEqual(sum(summary["counts"].values()), summary["total"])
        self.assertEqual(summary["counts"].get(ScanFile.INVALID), 1)

    def test_counts_match_bulk_delete_totals_for_every_status(self):
        """确认框条数（summary.counts）必须等于批删实际条数，逐状态都比一遍。

        summary 与批删各自实现过滤，口径一旦漂移这里必红——前端显示 N 条就得真删 N 条。
        """
        scan_dir = os.path.join(self.tmpdir, "imports")
        statuses = [
            ScanFile.NEW, ScanFile.READY, ScanFile.DROP, ScanFile.EXIST,
            ScanFile.INVALID, ScanFile.MISSED, ScanFile.PERMISSION,
        ]
        for i, st in enumerate(statuses):
            self._row(self._touch(os.path.join("imports", "e%d.epub" % i)), st)
            # 每个状态再配一条有声书记录：既不进 summary，也不被批删带走
            self._audio_row(os.path.join(self.tmpdir, "audiobooks", "A%d" % i), st)
        self._row(self._touch(os.path.join("imports", "done.epub")), ScanFile.IMPORTED)
        self._audio_row(os.path.join(self.tmpdir, "audiobooks", "done"), ScanFile.IMPORTED)
        # Scanner.close() 会回滚未提交事务，浏览器侧的 summary 也在它自己的会话里查已提交数据
        self.session.commit()

        scanner = Scanner(None, self.session)
        try:
            summary = scanner.summary()
        finally:
            scanner.close()
        counts = summary["counts"]

        self.assertEqual(summary["total"], sum(counts.values()))
        self.assertEqual(summary["total"], len(statuses) + 1)
        for st in statuses:
            total, deleted, skipped = ScanService._bulk_delete_core(
                self.session, st, False, scan_dir,
            )
            self.assertEqual(total, counts.get(st, 0), "status=%s" % st)
        # IMPORTED 不在批删白名单内，只核对计数（确认框要显示它的条数）
        self.assertEqual(counts.get(ScanFile.IMPORTED), 1)
        # 有声书记录一条未动
        remaining_audio = (
            self.session.query(ScanFile)
            .filter(ScanFile.import_type == constants.IMPORT_TYPE_AUDIOBOOK)
            .count()
        )
        self.assertEqual(remaining_audio, len(statuses) + 1)

    def test_todo_dialog_count_matches_deletion(self):
        """「全部待处理」的确认框条数来自 counts 求和（排除 imported），须等于批删条数。"""
        scan_dir = os.path.join(self.tmpdir, "imports")
        self._row(self._touch(os.path.join("imports", "a.epub")), ScanFile.DROP)
        self._row(self._touch(os.path.join("imports", "b.epub")), ScanFile.EXIST)
        self._row(self._touch(os.path.join("imports", "c.epub")), ScanFile.IMPORTED)
        self._audio_row(os.path.join(self.tmpdir, "audiobooks", "有声书A"), ScanFile.INVALID)
        self.session.commit()  # Scanner.close() 会回滚未提交事务

        scanner = Scanner(None, self.session)
        try:
            counts = scanner.summary()["counts"]
        finally:
            scanner.close()
        expected = sum(v for k, v in counts.items() if k != ScanFile.IMPORTED)

        total, deleted, skipped = ScanService._bulk_delete_core(
            self.session, "todo", False, scan_dir,
        )

        self.assertEqual(expected, 2)
        self.assertEqual(total, expected)


if __name__ == "__main__":
    unittest.main()
