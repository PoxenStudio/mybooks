#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import asyncio
import datetime
import json
import os
import shutil
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from tests.test_main import TestWithUserLogin, get_db, setUpModule as init, main
from webserver import models
from webserver.models import Reading, ReadingRecord
from webserver.services.reader_cache import ReaderStatsCache
from webserver.services.sync_service import MyReaderSyncService


def setUpModule():
    init()


class TestSyncServiceStorage(unittest.TestCase):
    """Unit tests against sync_service directly (no HTTP), DB-backed storage on the
    shared test DB (see tests/test_main.py). Each test uses a uid/book_hash unique
    to itself to avoid cross-test interference, since the DB isn't reset per test."""

    def setUp(self):
        MyReaderSyncService._locks.clear()
        MyReaderSyncService._buffer._pending.clear()

    def test_push_then_pull_roundtrip(self):
        async def run():
            payload = {
                "books": [{
                    "id": "b1", "book_hash": "sync-hash1", "updated_at": 1000, "deleted_at": None,
                    "title": "Title 1", "author": "Author 1", "format": "EPUB",
                }],
            }
            result = await MyReaderSyncService.push(101, payload)
            self.assertEqual(len(result["books"]), 1)
            self.assertEqual(result["books"][0]["title"], "Title 1")

            pulled = MyReaderSyncService.pull(101, since=0, type_="books")
            self.assertEqual(len(pulled["books"]), 1)
            self.assertIsNone(pulled["notes"])
            self.assertIsNone(pulled["configs"])

            # records not newer than `since` are excluded
            pulled_none = MyReaderSyncService.pull(101, since=1000, type_="books")
            self.assertEqual(pulled_none["books"], [])

        asyncio.get_event_loop().run_until_complete(run())

    def test_records_land_in_reading_records_table_after_flush(self):
        async def run():
            await MyReaderSyncService.push(102, {
                "books": [{"id": "b1", "book_hash": "sync-hashA", "updated_at": 1, "title": "A"}],
                "configs": [{"id": "c1", "book_hash": "sync-hashA", "updated_at": 1, "progress": [1, 10]}],
                "notes": [{"id": "n1", "book_hash": "sync-hashA", "updated_at": 1, "note": "hi"}],
            })
            MyReaderSyncService.flush_now()

            db = ReadingRecord._session()
            rows = db.query(ReadingRecord).filter_by(reader_id=102, book_hash="sync-hashA").all()
            self.assertEqual({r.kind for r in rows}, {"books", "configs", "notes"})
            notes_row = next(r for r in rows if r.kind == "notes")
            self.assertEqual(notes_row.payload["note"], "hi")
            self.assertEqual(notes_row.payload["uid"], 102)  # uid 兜底补齐，见 push() 实现

        asyncio.get_event_loop().run_until_complete(run())

    def test_push_drops_notes_that_carry_a_foreign_uid(self):
        """own=0 拉取会把别人的共读 note 混进客户端本地数据；客户端保存/推送时有概率原样带回来，
        这些条目必须被过滤掉，不能落进当前用户自己的 reading_records 行里（见 push() 实现）。"""
        async def run():
            await MyReaderSyncService.push(104, {
                "notes": [{"id": "n1", "book_hash": "sync-hashC", "updated_at": 1, "note": "mine"}],
            })
            result = await MyReaderSyncService.push(104, {
                "notes": [{"id": "n2", "book_hash": "sync-hashC", "updated_at": 2, "note": "not mine", "uid": 999}],
            })
            self.assertNotIn("notes", result)  # 整批都被过滤掉，没有实际生效的变更

            MyReaderSyncService.flush_now()
            db = ReadingRecord._session()
            rows = db.query(ReadingRecord).filter_by(reader_id=104, book_hash="sync-hashC", kind="notes").all()
            self.assertEqual([r.record_id for r in rows], ["n1"])  # n2 没有被存进来

        asyncio.get_event_loop().run_until_complete(run())

    def test_pull_is_visible_before_flush(self):
        async def run():
            await MyReaderSyncService.push(103, {"books": [{"id": "b1", "book_hash": "sync-hashB", "updated_at": 1}]})
            # not flushed yet -- must still be visible via the buffer overlay
            pulled = MyReaderSyncService.pull(103, since=0, type_="books")
            self.assertEqual(len(pulled["books"]), 1)

            db = ReadingRecord._session()
            self.assertIsNone(db.query(ReadingRecord).filter_by(reader_id=103, book_hash="sync-hashB").one_or_none())

        asyncio.get_event_loop().run_until_complete(run())

    def test_pull_scans_all_book_directories(self):
        async def run():
            await MyReaderSyncService.push(104, {"books": [{"id": "b1", "book_hash": "sync-hashC1", "updated_at": 1}]})
            await MyReaderSyncService.push(104, {"books": [{"id": "b2", "book_hash": "sync-hashC2", "updated_at": 1}]})
            pulled = MyReaderSyncService.pull(104, since=0, type_="books")
            self.assertEqual({r["book_hash"] for r in pulled["books"]}, {"sync-hashC1", "sync-hashC2"})

            # filtering by `book` only returns that book's record
            pulled_one = MyReaderSyncService.pull(104, since=0, type_="books", book_hash="sync-hashC1")
            self.assertEqual([r["book_hash"] for r in pulled_one["books"]], ["sync-hashC1"])

        asyncio.get_event_loop().run_until_complete(run())

    def test_last_write_wins_merge(self):
        async def run():
            await MyReaderSyncService.push(105, {"configs": [
                {"id": "c1", "book_hash": "sync-hashD", "updated_at": 100, "progress": [1, 100]},
            ]})
            # stale update (lower updated_at) must be ignored
            stale = await MyReaderSyncService.push(105, {"configs": [
                {"id": "c1", "book_hash": "sync-hashD", "updated_at": 50, "progress": [99, 100]},
            ]})
            self.assertEqual(stale["configs"][0]["progress"], [1, 100])

            # newer update overwrites
            fresh = await MyReaderSyncService.push(105, {"configs": [
                {"id": "c1", "book_hash": "sync-hashD", "updated_at": 200, "progress": [5, 100]},
            ]})
            self.assertEqual(fresh["configs"][0]["progress"], [5, 100])

        asyncio.get_event_loop().run_until_complete(run())

    def test_multiple_notes_per_book(self):
        async def run():
            await MyReaderSyncService.push(106, {"notes": [
                {"id": "n1", "book_hash": "sync-hashE", "updated_at": 10, "note": "first"},
                {"id": "n2", "book_hash": "sync-hashE", "updated_at": 10, "note": "second"},
            ]})
            pulled = MyReaderSyncService.pull(106, since=0, type_="notes")
            self.assertEqual({r["id"] for r in pulled["notes"]}, {"n1", "n2"})

        asyncio.get_event_loop().run_until_complete(run())

    def test_tombstone_visible_via_deleted_at(self):
        async def run():
            await MyReaderSyncService.push(107, {"notes": [
                {"id": "n1", "book_hash": "sync-hashF", "updated_at": 10, "deleted_at": None, "note": "hi"},
            ]})
            await MyReaderSyncService.push(107, {"notes": [
                {"id": "n1", "book_hash": "sync-hashF", "updated_at": 20, "deleted_at": 20, "note": "hi"},
            ]})
            pulled = MyReaderSyncService.pull(107, since=15, type_="notes")
            self.assertEqual(len(pulled["notes"]), 1)
            self.assertEqual(pulled["notes"][0]["deleted_at"], 20)

        asyncio.get_event_loop().run_until_complete(run())

    def test_purge_soft_deleted_removes_only_stale_tombstones(self):
        """软删除记录超过 SYNC_SOFT_DELETE_RETENTION_DAYS 天才物理清理；未过期的
        tombstone、以及未删除的记录都要保留，见 purge_soft_deleted() 实现。"""
        import time
        now_ms = int(time.time() * 1000)
        eight_days_ago = now_ms - 8 * 24 * 3600 * 1000

        async def run():
            # 早已软删除，应当被清理
            await MyReaderSyncService.push(114, {"notes": [
                {"id": "n1", "book_hash": "sync-hashH", "updated_at": eight_days_ago, "deleted_at": eight_days_ago, "note": "old"},
            ]})
            # 刚刚软删除，应当保留
            await MyReaderSyncService.push(114, {"notes": [
                {"id": "n2", "book_hash": "sync-hashH", "updated_at": now_ms, "deleted_at": now_ms, "note": "recent"},
            ]})
            # 未删除，应当保留
            await MyReaderSyncService.push(114, {"notes": [
                {"id": "n3", "book_hash": "sync-hashH", "updated_at": now_ms, "note": "alive"},
            ]})
            MyReaderSyncService.flush_now()

            MyReaderSyncService.purge_soft_deleted()

            db = ReadingRecord._session()
            remaining = {
                r.record_id
                for r in db.query(ReadingRecord).filter_by(reader_id=114, book_hash="sync-hashH").all()
            }
            self.assertEqual(remaining, {"n2", "n3"})

        asyncio.get_event_loop().run_until_complete(run())

    def test_per_user_isolation(self):
        async def run():
            await MyReaderSyncService.push(108, {"books": [{"id": "b1", "book_hash": "sync-hashG1", "updated_at": 1}]})
            await MyReaderSyncService.push(109, {"books": [{"id": "b2", "book_hash": "sync-hashG2", "updated_at": 1}]})
            self.assertEqual(len(MyReaderSyncService.pull(108, 0, "books")["books"]), 1)
            self.assertEqual(len(MyReaderSyncService.pull(109, 0, "books")["books"]), 1)

        asyncio.get_event_loop().run_until_complete(run())

    def test_concurrent_push_same_user_is_serialized(self):
        """push() must wait for an in-flight push for the same uid before reading/writing."""
        async def run():
            lock = MyReaderSyncService._get_lock(110)
            await lock.acquire()
            try:
                task = asyncio.ensure_future(MyReaderSyncService.push(110, {
                    "books": [{"id": "b1", "book_hash": "sync-hashH", "updated_at": 1}],
                }))
                await asyncio.sleep(0.05)
                self.assertFalse(task.done(), "push() must block while another holder owns the per-uid lock")
            finally:
                lock.release()

            result = await task
            self.assertEqual(len(result["books"]), 1)

        asyncio.get_event_loop().run_until_complete(run())

    def test_concurrent_push_different_books_does_not_lose_updates(self):
        """Two concurrent pushes for the same user touching different books must both land."""
        async def run():
            await asyncio.gather(
                MyReaderSyncService.push(111, {"books": [{"id": "b1", "book_hash": "sync-hashI1", "updated_at": 1}]}),
                MyReaderSyncService.push(111, {"books": [{"id": "b2", "book_hash": "sync-hashI2", "updated_at": 1}]}),
            )
            pulled = MyReaderSyncService.pull(111, since=0, type_="books")
            self.assertEqual({r["book_hash"] for r in pulled["books"]}, {"sync-hashI1", "sync-hashI2"})

        asyncio.get_event_loop().run_until_complete(run())

    def test_own_param_excludes_others_notes_by_default(self):
        async def run():
            book_hash = "cloud-90001-epub"
            await MyReaderSyncService.push(112, {"notes": [{"id": "n1", "book_hash": book_hash, "updated_at": 10, "note": "mine"}]})
            await MyReaderSyncService.push(113, {"notes": [{"id": "n2", "book_hash": book_hash, "updated_at": 10, "note": "theirs"}]})
            MyReaderSyncService.flush_now()

            own_only = MyReaderSyncService.pull(112, since=0, type_="notes", book_hash=book_hash, own=1)
            self.assertEqual({r["id"] for r in own_only["notes"]}, {"n1"})

        asyncio.get_event_loop().run_until_complete(run())

    def test_own_param_zero_includes_shared_notes_for_same_book(self):
        async def run():
            book_hash = "cloud-90002-epub"
            await MyReaderSyncService.push(114, {"notes": [{"id": "n1", "book_hash": book_hash, "updated_at": 10, "note": "mine"}]})
            await MyReaderSyncService.push(115, {"notes": [{"id": "n2", "book_hash": book_hash, "updated_at": 10, "note": "theirs"}]})
            MyReaderSyncService.flush_now()  # 跨用户 notes 走 DB 查询，需要先 flush

            shared = MyReaderSyncService.pull(114, since=0, type_="notes", book_hash=book_hash, own=0)
            self.assertEqual({r["id"] for r in shared["notes"]}, {"n1", "n2"})
            other_note = next(r for r in shared["notes"] if r["id"] == "n2")
            self.assertEqual(other_note["uid"], 115)

        asyncio.get_event_loop().run_until_complete(run())

    def test_own_param_zero_excludes_local_books_from_cross_user_query(self):
        async def run():
            book_hash = "local-file-not-cloud-format"
            await MyReaderSyncService.push(116, {"notes": [{"id": "n1", "book_hash": book_hash, "updated_at": 10, "note": "mine"}]})
            await MyReaderSyncService.push(117, {"notes": [{"id": "n2", "book_hash": book_hash, "updated_at": 10, "note": "theirs"}]})
            MyReaderSyncService.flush_now()

            shared = MyReaderSyncService.pull(116, since=0, type_="notes", book_hash=book_hash, own=0)
            # 本地书籍（book_id 为负数占位值）不参与跨用户匹配，即使传 own=0 也只看到自己的
            self.assertEqual({r["id"] for r in shared["notes"]}, {"n1"})

        asyncio.get_event_loop().run_until_complete(run())

    def test_shared_notes_include_author_nickname_and_avatar(self):
        """myreader 需要在共读批注上显示是谁写的（见 document/MyReader_Embedded_WebApp.md
        多用户批注需求），跨用户 note 必须带上作者的 nickname/avatar，自己的 note 不需要。"""
        async def run():
            book_hash = "cloud-90004-epub"
            other = models.Reader(username="shared-author", name="Alice", avatar="alice.png",
                                   create_time=None, update_time=None)
            db = get_db()
            db.add(other)
            db.commit()
            other_id = other.id

            await MyReaderSyncService.push(120, {"notes": [
                {"id": "n1", "book_hash": book_hash, "updated_at": 10, "note": "mine"},
            ]})
            await MyReaderSyncService.push(other_id, {"notes": [
                {"id": "n2", "book_hash": book_hash, "updated_at": 10, "note": "theirs"},
            ]})
            MyReaderSyncService.flush_now()

            shared = MyReaderSyncService.pull(120, since=0, type_="notes", book_hash=book_hash, own=0)
            mine = next(r for r in shared["notes"] if r["id"] == "n1")
            theirs = next(r for r in shared["notes"] if r["id"] == "n2")
            self.assertNotIn("author", mine)
            self.assertEqual(theirs["author"]["nickname"], "Alice")
            self.assertIn("alice.png", theirs["author"]["avatar"])

        asyncio.get_event_loop().run_until_complete(run())

    def test_shared_notes_disabled_by_setting(self):
        async def run():
            book_hash = "cloud-90003-epub"
            await MyReaderSyncService.push(118, {"notes": [{"id": "n1", "book_hash": book_hash, "updated_at": 10, "note": "mine"}]})
            await MyReaderSyncService.push(119, {"notes": [{"id": "n2", "book_hash": book_hash, "updated_at": 10, "note": "theirs"}]})
            MyReaderSyncService.flush_now()

            main.CONF["ENABLE_SHARED_NOTES"] = False
            try:
                shared = MyReaderSyncService.pull(118, since=0, type_="notes", book_hash=book_hash, own=0)
                self.assertEqual({r["id"] for r in shared["notes"]}, {"n1"})
            finally:
                main.CONF["ENABLE_SHARED_NOTES"] = True

        asyncio.get_event_loop().run_until_complete(run())


class TestSyncServiceReadingSeconds(unittest.TestCase):
    """离线阅读显式上报（payload 里的 `reading_seconds`）与在线心跳的互斥关系，见
    document/Reading_Stats_Design.md 的离线阅读扩展：同一本书这次 push 只走其中一条
    路径，不会两条都算，否则会对同一段时间重复计入一次。"""

    def setUp(self):
        MyReaderSyncService._locks.clear()
        MyReaderSyncService._buffer._pending.clear()
        for uid in (301, 302, 303, 304):
            ReaderStatsCache().invalidate(uid)

    def _reading_row(self, uid, book_id):
        db = get_db()
        return db.query(Reading).filter_by(reader_id=uid, book_id=book_id, action=Reading.ACTION_READ).one_or_none()

    def test_explicit_reading_seconds_skips_heartbeat_for_that_book(self):
        """带了 reading_seconds 的书，这次 push 只走显式上报，不再叠加心跳到达间隔推算
        （心跳推算这次 push 本身贡献的 delta 就是 0——第一次心跳恒定如此，见
        on_heartbeat()——但用来确认没有额外触发心跳路径本身，下面用总时长核对）。"""
        async def run():
            book_hash = "cloud-90101-epub"
            await MyReaderSyncService.push(301, {
                "configs": [{"id": book_hash, "book_hash": book_hash, "updated_at": 1, "progress": [10, 100]}],
                "reading_seconds": [{"book_hash": book_hash, "date": "2025-12-31", "seconds": 600}],
            })
            MyReaderSyncService.flush_now()

            row = self._reading_row(301, 90101)
            self.assertIsNotNone(row)
            self.assertEqual(row.date, datetime.date(2025, 12, 31))
            self.assertEqual(row.duration, 600)

        asyncio.get_event_loop().run_until_complete(run())

    def test_book_without_reading_seconds_still_uses_heartbeat(self):
        """没带 reading_seconds 的书，行为完全不变——继续走心跳到达间隔推算。"""
        async def run():
            book_hash = "cloud-90102-epub"
            await MyReaderSyncService.push(302, {
                "configs": [{"id": book_hash, "book_hash": book_hash, "updated_at": 1, "progress": [1, 100]}],
            })
            MyReaderSyncService.flush_now()
            first = self._reading_row(302, 90102)
            self.assertIsNotNone(first)
            self.assertEqual(first.duration, 0)  # 心跳首次落地，本身贡献 0 秒

            await MyReaderSyncService.push(302, {
                "configs": [{"id": book_hash, "book_hash": book_hash, "updated_at": 2, "progress": [2, 100]}],
            })
            MyReaderSyncService.flush_now()
            second = self._reading_row(302, 90102)
            self.assertGreaterEqual(second.duration, 0)  # 心跳路径正常工作，未受影响

        asyncio.get_event_loop().run_until_complete(run())

    def test_reading_seconds_applies_even_when_configs_did_not_change(self):
        """用户全程停在同一页（configs 合并后没有实际变化），但确实读了这么久——显式
        上报不依赖 configs 是否 applied，这是和心跳路径的关键差异之一。"""
        async def run():
            book_hash = "cloud-90103-epub"
            # 先落一次相同的 progress，让第二次 push 的 configs 合并判定为"没有变化"
            await MyReaderSyncService.push(303, {
                "configs": [{"id": book_hash, "book_hash": book_hash, "updated_at": 5, "progress": [3, 100]}],
            })
            MyReaderSyncService.flush_now()

            await MyReaderSyncService.push(303, {
                "configs": [{"id": book_hash, "book_hash": book_hash, "updated_at": 5, "progress": [3, 100]}],
                "reading_seconds": [{"book_hash": book_hash, "date": "2025-12-31", "seconds": 300}],
            })
            MyReaderSyncService.flush_now()

            rows = get_db().query(Reading).filter_by(reader_id=303, book_id=90103, action=Reading.ACTION_READ).all()
            backfilled = next(r for r in rows if r.date == datetime.date(2025, 12, 31))
            self.assertEqual(backfilled.duration, 300)

        asyncio.get_event_loop().run_until_complete(run())

    def test_malformed_reading_seconds_entries_are_dropped_without_error(self):
        async def run():
            book_hash = "cloud-90104-epub"
            await MyReaderSyncService.push(304, {
                "configs": [{"id": book_hash, "book_hash": book_hash, "updated_at": 1, "progress": [1, 100]}],
                "reading_seconds": [
                    {"book_hash": book_hash, "date": "not-a-date", "seconds": 100},
                    {"book_hash": book_hash, "date": "2025-12-31", "seconds": "not-a-number"},
                    {"book_hash": book_hash, "seconds": 100},  # missing date
                    {"date": "2025-12-31", "seconds": 100},  # missing book_hash
                ],
            })
            MyReaderSyncService.flush_now()  # must not raise

            row = self._reading_row(304, 90104)
            self.assertIsNotNone(row)  # 心跳路径仍然正常工作（没有一条合法的 reading_seconds）

        asyncio.get_event_loop().run_until_complete(run())


class TestLegacyMigration(unittest.TestCase):
    """Migration from <MYREADER_SYNC_PATH>/<uid>/<book_hash>/{kind}.json into
    reading_records, on an isolated in-memory DB (see tests/test_reading_stats_flush.py
    for the same pattern)."""

    def setUp(self):
        self._shared_session = get_db()
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)

        self._tmp_dir = tempfile.mkdtemp()
        main.CONF["MYREADER_SYNC_PATH"] = self._tmp_dir
        main.CONF["SYNC_LEGACY_MIGRATION_DONE"] = False
        MyReaderSyncService._locks.clear()
        MyReaderSyncService._buffer._pending.clear()

    def tearDown(self):
        self.session.remove()
        models.bind_session(self._shared_session)  # 恢复共享 app 的 DB 绑定，避免影响其它测试
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _write_legacy_file(self, uid, book_hash, kind, data):
        book_dir = os.path.join(self._tmp_dir, str(uid), book_hash)
        os.makedirs(book_dir, exist_ok=True)
        with open(os.path.join(book_dir, f"{kind}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_migrates_all_three_kinds_and_removes_directories(self):
        self._write_legacy_file(201, "cloud-1-epub", "books", {
            "id": "b1", "book_hash": "cloud-1-epub", "updated_at": 1, "title": "A",
        })
        self._write_legacy_file(201, "cloud-1-epub", "configs", {
            "id": "c1", "book_hash": "cloud-1-epub", "updated_at": 1,
        })
        self._write_legacy_file(201, "cloud-1-epub", "notes", {
            "n1": {"id": "n1", "book_hash": "cloud-1-epub", "updated_at": 1, "note": "hi"},
        })

        MyReaderSyncService.migrate_legacy_data()

        rows = self.session.query(ReadingRecord).filter_by(reader_id=201).all()
        self.assertEqual({r.kind for r in rows}, {"books", "configs", "notes"})
        note_row = next(r for r in rows if r.kind == "notes")
        self.assertEqual(note_row.payload["uid"], 201)  # 迁移历史数据时补齐 uid
        book_row = next(r for r in rows if r.kind == "books")
        self.assertEqual(book_row.book_id, 1)  # 从 book_hash 提取的整型 book_id

        self.assertFalse(os.path.isdir(os.path.join(self._tmp_dir, "201")))
        self.assertTrue(main.CONF["SYNC_LEGACY_MIGRATION_DONE"])

    def test_no_dirs_marks_migration_done_immediately(self):
        MyReaderSyncService.migrate_legacy_data()
        self.assertTrue(main.CONF["SYNC_LEGACY_MIGRATION_DONE"])

    def test_migration_is_resumable_across_runs(self):
        self._write_legacy_file(202, "cloud-2-epub", "books", {
            "id": "b1", "book_hash": "cloud-2-epub", "updated_at": 5, "title": "X",
        })
        MyReaderSyncService.migrate_legacy_data()
        self.assertFalse(os.path.isdir(os.path.join(self._tmp_dir, "202")))

        # 新增一个"还没迁移"的目录（模拟迁移完成后又有旧文件残留/新用户目录出现），
        # 重新触发迁移应当只处理新增部分，此前已迁移的数据不受影响
        self._write_legacy_file(202, "cloud-3-epub", "books", {
            "id": "b2", "book_hash": "cloud-3-epub", "updated_at": 5, "title": "Y",
        })
        main.CONF["SYNC_LEGACY_MIGRATION_DONE"] = False
        MyReaderSyncService.migrate_legacy_data()

        rows = self.session.query(ReadingRecord).filter_by(reader_id=202).all()
        self.assertEqual({r.book_hash for r in rows}, {"cloud-2-epub", "cloud-3-epub"})

    def test_migration_keeps_newer_live_push_over_stale_legacy_file(self):
        """不停机迁移：迁移开始前，该用户已经通过新路径 push 了一条更新的数据，
        迁移不能用旧文件覆盖它（last-write-wins，见 plan §7.1 第 3 点）。"""
        async def push_live():
            await MyReaderSyncService.push(203, {
                "books": [{"id": "b1", "book_hash": "cloud-4-epub", "updated_at": 100, "title": "Live"}],
            })

        asyncio.get_event_loop().run_until_complete(push_live())
        MyReaderSyncService.flush_now()

        self._write_legacy_file(203, "cloud-4-epub", "books", {
            "id": "b1", "book_hash": "cloud-4-epub", "updated_at": 10, "title": "Stale",
        })
        MyReaderSyncService.migrate_legacy_data()

        row = self.session.query(ReadingRecord).filter_by(reader_id=203, book_hash="cloud-4-epub").one()
        self.assertEqual(row.payload["title"], "Live")


class TestSyncHandler(TestWithUserLogin):
    """Integration tests for GET/POST /api/sync over real HTTP, mocked user_id=1."""

    def setUp(self):
        super().setUp()
        main.CONF["ENABLE_DATA_SYNC"] = True
        MyReaderSyncService._locks.clear()
        MyReaderSyncService._buffer._pending.clear()

    def test_get_requires_since(self):
        d = self.json("/api/sync")
        self.assertEqual(d["err"], "params.invalid")

    def test_post_then_get(self):
        body = json.dumps({"books": [{
            "id": "b1", "book_hash": "http-hash1", "updated_at": 1000, "title": "T", "author": "A", "format": "EPUB",
        }]})
        d = self.json("/api/sync", method="POST", body=body)
        self.assertEqual(len(d["books"]), 1)

        d = self.json("/api/sync?since=0&type=books&book=http-hash1")
        self.assertEqual(len(d["books"]), 1)
        self.assertEqual(d["books"][0]["book_hash"], "http-hash1")

    def test_own_param_via_http(self):
        # own=1（默认）只看自己（uid=1，见 mock）；own=0 且 ENABLE_SHARED_NOTES=True 时
        # 还能看到其他用户对同一本书提交的 notes。
        book_hash = "cloud-90010-epub"
        asyncio.get_event_loop().run_until_complete(
            MyReaderSyncService.push(999, {"notes": [{"id": "nX", "book_hash": book_hash, "updated_at": 1, "note": "other"}]})
        )
        MyReaderSyncService.flush_now()

        d = self.json(f"/api/sync?since=0&type=notes&book={book_hash}&own=1")
        self.assertEqual(d["notes"], [])

        d = self.json(f"/api/sync?since=0&type=notes&book={book_hash}&own=0")
        self.assertEqual([r["id"] for r in d["notes"]], ["nX"])

    def test_own_defaults_from_show_other_annotations_preference(self):
        # 不传 own 时按用户偏好决定：show_other_annotations 默认 True -> 等价 own=0（能看到别人的）
        book_hash = "cloud-90011-epub"
        asyncio.get_event_loop().run_until_complete(
            MyReaderSyncService.push(998, {"notes": [{"id": "nY", "book_hash": book_hash, "updated_at": 1, "note": "other"}]})
        )
        MyReaderSyncService.flush_now()

        d = self.json(f"/api/sync?since=0&type=notes&book={book_hash}")
        self.assertEqual([r["id"] for r in d["notes"]], ["nY"])

        # 关闭偏好后，不传 own 时应等价 own=1（看不到别人的）
        self.json("/api/user/update", method="POST", body=json.dumps({"show_other_annotations": False}))
        try:
            d = self.json(f"/api/sync?since=0&type=notes&book={book_hash}")
            self.assertEqual(d["notes"], [])
        finally:
            self.json("/api/user/update", method="POST", body=json.dumps({"show_other_annotations": True}))

    def test_disabled_feature_blocks_requests(self):
        main.CONF["ENABLE_DATA_SYNC"] = False
        d = self.json("/api/sync?since=0")
        self.assertEqual(d["err"], "sync.disabled")
