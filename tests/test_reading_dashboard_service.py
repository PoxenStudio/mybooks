#!/usr/bin/env python3

import datetime
import json
import os
import shutil
import tempfile
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import loader, models
from webserver.models import BookReadingStats, Reader, Reading, ReadingState
from webserver.services import reading_dashboard_service as svc


class TestReadingDashboardService(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.conf = loader.get_settings()
        self._orig_sync_path = self.conf.get("MYREADER_SYNC_PATH")
        self.conf["MYREADER_SYNC_PATH"] = self.tmp_dir

        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)
        self.session.execute(
            text("CREATE UNIQUE INDEX ux_readings_read ON readings (reader_id, book_id, date) WHERE action='read'")
        )
        # 与 async_service.adjust_readings_table 同步建齐，_today_read_book_ids 的
        # INDEXED BY ix_readings_reader_date 依赖它存在
        self.session.execute(
            text("CREATE INDEX ix_readings_reader_book_action ON readings (reader_id, book_id, action)")
        )
        self.session.execute(
            text("CREATE INDEX ix_readings_reader_date ON readings (reader_id, date)")
        )
        # _rank_seconds 的 INDEXED BY ix_readings_date_read 依赖（同 async_service DDL）
        self.session.execute(
            text("CREATE INDEX ix_readings_date_read ON readings (date, reader_id) WHERE action='read'")
        )

        self.reader = Reader()
        self.reader.id = 1
        self.reader.username = "u1"
        self.reader.total_reading_seconds = 100
        self.reader.download_count = 3
        self.reader.push_count = 2
        self.session.add(self.reader)
        self.session.commit()

    def tearDown(self):
        self.session.remove()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        if self._orig_sync_path is None:
            self.conf.pop("MYREADER_SYNC_PATH", None)
        else:
            self.conf["MYREADER_SYNC_PATH"] = self._orig_sync_path

    def _add_reading(self, date, duration=0, action=Reading.ACTION_READ, book_id=100):
        row = Reading(1, book_id, action, Reading.PROTOCOL_APP, datetime.datetime.combine(date, datetime.time()), duration=duration)
        self.session.add(row)
        self.session.commit()

    def test_homepage_stats_disabled_only_for_home_request(self):
        # 开关只对首页请求（home=1）生效：非首页请求（阅读记录页/管理端）不受影响
        self.conf["ENABLE_HOMEPAGE_READING_STATS"] = False
        try:
            self.assertTrue(svc.homepage_stats_disabled(True))
            self.assertFalse(svc.homepage_stats_disabled(False))
            self.assertFalse(svc.homepage_stats_disabled(None))
            # 关闭首页开关时 get_stats 本身仍可用（不再全局返回 None）
            self.assertIsNotNone(svc.get_stats(self.session, self.reader))
        finally:
            self.conf["ENABLE_HOMEPAGE_READING_STATS"] = True

    def test_homepage_stats_enabled_never_gated(self):
        self.conf["ENABLE_HOMEPAGE_READING_STATS"] = True
        self.assertFalse(svc.homepage_stats_disabled(True))
        self.assertFalse(svc.homepage_stats_disabled(False))

    def test_totals_come_from_reader_columns(self):
        stats = svc.get_stats(self.session, self.reader)
        self.assertEqual(stats["totals"], {"total_reading_seconds": 100, "download_count": 3, "push_count": 2})

    def test_missing_cache_file_recomputes_from_db(self):
        today = datetime.datetime.utcnow().date()
        yesterday = today - datetime.timedelta(days=1)
        self._add_reading(yesterday, duration=600)
        self._add_reading(today, duration=120)

        stats = svc.get_stats(self.session, self.reader)
        weekly = stats["weekly"]
        self.assertEqual(len(weekly), 8)
        total_seconds = sum(w["reading_seconds"] for w in weekly)
        self.assertEqual(total_seconds, 720)

        # cache file should now exist with yesterday folded in
        cache_path = svc._user_cache_path(1)
        self.assertTrue(os.path.exists(cache_path))
        with open(cache_path) as f:
            cache = json.load(f)
        self.assertEqual(cache["cached_through"], svc._date_str(yesterday))
        self.assertIn(svc._date_str(yesterday), cache["days"])
        self.assertNotIn(svc._date_str(today), cache["days"])  # today never persisted

    def test_corrupt_cache_file_falls_back_to_recompute(self):
        os.makedirs(os.path.dirname(svc._user_cache_path(1)), exist_ok=True)
        with open(svc._user_cache_path(1), "w") as f:
            f.write("{not valid json")

        today = datetime.datetime.utcnow().date()
        yesterday = today - datetime.timedelta(days=1)
        self._add_reading(yesterday, duration=42)

        stats = svc.get_stats(self.session, self.reader)
        self.assertEqual(sum(w["reading_seconds"] for w in stats["weekly"]), 42)

    def test_second_call_same_day_does_not_rewrite_cache(self):
        today = datetime.datetime.utcnow().date()
        yesterday = today - datetime.timedelta(days=1)
        self._add_reading(yesterday, duration=10)
        svc.get_stats(self.session, self.reader)

        cache_path = svc._user_cache_path(1)
        mtime1 = os.path.getmtime(cache_path)

        # more "today" activity shouldn't touch the cache file
        self._add_reading(today, duration=5)
        svc.get_stats(self.session, self.reader)
        mtime2 = os.path.getmtime(cache_path)
        self.assertEqual(mtime1, mtime2)

    def test_book_status_categorizes_reading_to_read_finished(self):
        s1 = ReadingState(101, 1)
        s1.read_state = 1
        s2 = ReadingState(102, 1)
        s2.read_state = 2
        s3 = ReadingState(103, 1)
        s3.wants = 1
        s3.read_state = 0
        self.session.add_all([s1, s2, s3])
        self.session.commit()

        stats = svc.get_stats(self.session, self.reader)
        self.assertEqual(stats["book_status"], {"reading": 1, "finished": 1, "to_read": 1})

    def test_weekly_buckets_use_monday_start_and_cover_8_weeks(self):
        stats = svc.get_stats(self.session, self.reader)
        weekly = stats["weekly"]
        self.assertEqual(len(weekly), 8)
        today = datetime.datetime.utcnow().date()
        self.assertEqual(weekly[-1]["week_start"], svc._date_str(svc._week_start(today)))
        for w in weekly:
            d = datetime.datetime.strptime(w["week_start"], "%Y-%m-%d").date()
            self.assertEqual(d.weekday(), 0)  # Monday

    def test_heatmap_covers_13_weeks_starting_on_monday_through_today(self):
        today = datetime.datetime.utcnow().date()
        yesterday = today - datetime.timedelta(days=1)
        self._add_reading(yesterday, duration=1800)

        stats = svc.get_stats(self.session, self.reader)
        heatmap = stats["heatmap"]
        self.assertEqual(heatmap["weeks"], svc.HEATMAP_WEEKS)
        days = heatmap["days"]

        expected_start = svc._week_start(today) - datetime.timedelta(weeks=svc.HEATMAP_WEEKS - 1)
        self.assertEqual(days[0]["date"], svc._date_str(expected_start))
        self.assertEqual(days[-1]["date"], svc._date_str(today))
        # no future dates beyond today
        self.assertEqual(len(days), (today - expected_start).days + 1)

        by_date = {d["date"]: d["reading_seconds"] for d in days}
        self.assertEqual(by_date[svc._date_str(yesterday)], 1800)
        self.assertEqual(by_date[svc._date_str(today)], 0)

    def test_heatmap_uses_live_today_value_not_stale_cache(self):
        today = datetime.datetime.utcnow().date()
        self._add_reading(today, duration=300)
        stats = svc.get_stats(self.session, self.reader)
        days = stats["heatmap"]["days"]
        self.assertEqual(days[-1]["date"], svc._date_str(today))
        self.assertEqual(days[-1]["reading_seconds"], 300)

    # ---- 阅读记录页仪表盘新增字段（first_reading_date/total_days/total_books/streak/period/near_finish）----

    def test_lifetime_fields_empty_user(self):
        stats = svc.get_stats(self.session, self.reader)
        self.assertIsNone(stats["first_reading_date"])
        self.assertEqual(stats["total_days"], 0)
        self.assertEqual(stats["total_books"], 0)
        self.assertEqual(stats["streak"], {"current": 0, "best": 0})
        self.assertEqual(
            stats["period"],
            {
                "last7_seconds": 0,
                "prev7_seconds": 0,
                "last30_seconds": 0,
                "week_to_date_seconds": 0,
                "prev_week_same_span_seconds": 0,
            },
        )

    def test_lifetime_fields_and_current_streak(self):
        today = datetime.datetime.utcnow().date()
        # 昨天、前天连续 + 9 天前孤立一天（当天读了两本书）；3 天前只有 0 秒空桶不算阅读日
        for offset in (1, 2, 9):
            self._add_reading(today - datetime.timedelta(days=offset), duration=60)
        self._add_reading(today - datetime.timedelta(days=9), duration=60, book_id=200)
        self._add_reading(today - datetime.timedelta(days=3), duration=0)

        stats = svc.get_stats(self.session, self.reader)
        self.assertEqual(stats["first_reading_date"], svc._date_str(today - datetime.timedelta(days=9)))
        self.assertEqual(stats["total_days"], 3)
        self.assertEqual(stats["total_books"], 2)
        # 今天还没读：从昨天往回数连续 2 天；9 天前孤立一天不影响 best
        self.assertEqual(stats["streak"], {"current": 2, "best": 2})

    def test_streak_current_resets_and_best_kept(self):
        today = datetime.datetime.utcnow().date()
        for offset in (5, 4, 1):
            self._add_reading(today - datetime.timedelta(days=offset), duration=60)

        stats = svc.get_stats(self.session, self.reader)
        self.assertEqual(stats["streak"], {"current": 1, "best": 2})

    def test_streak_counts_today_when_read(self):
        today = datetime.datetime.utcnow().date()
        for offset in (0, 1, 2):
            self._add_reading(today - datetime.timedelta(days=offset), duration=60)

        stats = svc.get_stats(self.session, self.reader)
        self.assertEqual(stats["streak"]["current"], 3)

    def test_period_sums_windows(self):
        today = datetime.datetime.utcnow().date()
        for offset, seconds in {0: 100, 3: 200, 10: 300, 20: 400, 40: 500}.items():
            self._add_reading(today - datetime.timedelta(days=offset), duration=seconds)

        period = svc.get_stats(self.session, self.reader)["period"]
        self.assertEqual(period["last7_seconds"], 300)  # 今天 + 3 天前
        self.assertEqual(period["prev7_seconds"], 300)  # 上一个 7 天窗口只有 10 天前
        self.assertEqual(period["last30_seconds"], 1000)  # 40 天前不计入

    def test_week_to_date_period_and_leaderboard_share_week_window(self):
        """本周时长卡的 week_to_date == 排行榜本周同一读者同一窗口（口径一致回归钉）"""
        today = datetime.datetime.utcnow().date()
        week_start = svc._week_start(today)
        # 本周内两天：周一 + 今天（今天若就是周一则用不同 book 叠加，避免同日覆盖）
        self._add_reading(week_start, 40, book_id=101)
        if week_start != today:
            self._add_reading(today, 100, book_id=101)
        # 上周同期（上周一 + 与今天同星期几）也在 readings 表，但只进 prev 口径
        self._add_reading(week_start - datetime.timedelta(days=7), 20, book_id=102)

        stats = svc.get_stats(self.session, self.reader)
        period = stats["period"]
        # 本周至今 = 40 + (100 若今天非周一)
        expected_week = 40 + (100 if week_start != today else 0)
        self.assertEqual(period["week_to_date_seconds"], expected_week)
        # 与排行榜本周档 admin 行完全一致（同 SQL 同窗口，这是用户报的不一致点）
        board = svc.get_leaderboard(self.session, today=today)
        admin_row = next(e for e in board["week"] if e["reader_id"] == 1)
        self.assertEqual(admin_row["seconds"], period["week_to_date_seconds"])

    def test_near_finish_multi_format_books_do_not_eat_slots(self):
        """评审 P4：4 本×4 格式 + 第 5 本单格式，旧实现按格式行 LIMIT 会让前 4 本占满、丢第 5 本"""
        now = datetime.datetime.utcnow()
        formats = ["epub", "mobi", "azw3", "pdf"]
        percents = {
            20: [96.0, 95.0, 94.0, 93.0],
            21: [92.0, 91.0, 90.0, 89.0],
            22: [88.0, 87.0, 86.0, 85.6],
            23: [85.5, 85.4, 85.3, 85.2],
        }
        for book_id, book_percents in percents.items():
            for fmt, percent in zip(formats, book_percents):
                self.session.add(BookReadingStats(
                    reader_id=1, book_id=book_id, format=fmt, state=0,
                    total_seconds=int(percent * 10), progress_percent=percent,
                    create_time=now, update_time=now,
                ))
        self.session.add(BookReadingStats(
            reader_id=1, book_id=24, format="epub", state=0,
            total_seconds=850, progress_percent=85.0,
            create_time=now, update_time=now,
        ))
        self.session.commit()

        rows = svc.get_stats(self.session, self.reader)["near_finish"]
        self.assertEqual([r["book_id"] for r in rows], [20, 21, 22, 23, 24])
        self.assertEqual(rows[4]["progress_percent"], 85.0)
        # total_seconds 取该本进度最高的那一行（与旧去重口径一致）
        self.assertEqual(rows[0]["total_seconds"], 960)

    def test_near_finish_rows_filters_and_dedupes(self):
        now = datetime.datetime.utcnow()

        def add_stats(book_id, fmt, state, percent):
            self.session.add(
                BookReadingStats(
                    reader_id=1, book_id=book_id, format=fmt, state=state,
                    total_seconds=600, progress_percent=percent,
                    create_time=now, update_time=now,
                )
            )

        add_stats(10, "epub", 0, 50.0)  # 进度不足，排除
        add_stats(11, "epub", 0, 85.5)  # 入选
        add_stats(12, "epub", 0, 92.0)  # 入选，进度最高
        add_stats(12, "mobi", 0, 88.0)  # 同书另一格式，去重保留最高
        add_stats(13, "epub", 1, 99.0)  # 已读完，排除
        self.session.commit()

        rows = svc.get_stats(self.session, self.reader)["near_finish"]
        self.assertEqual([r["book_id"] for r in rows], [12, 11])
        self.assertEqual(rows[0]["progress_percent"], 92.0)

    def test_lifetime_block_persisted_and_reused_after_db_wipe(self):
        """评审 P3-2：lifetime 聚合写进 reading.json，同日第二次请求不再扫全历史"""
        today = datetime.datetime.utcnow().date()
        yesterday = today - datetime.timedelta(days=1)
        self._add_reading(yesterday, duration=60, book_id=100)
        self._add_reading(today, duration=30, book_id=200)

        stats = svc.get_stats(self.session, self.reader)
        self.assertEqual(stats["total_days"], 2)
        self.assertEqual(stats["total_books"], 2)

        with open(svc._user_cache_path(1), encoding="utf-8") as f:
            cache = json.load(f)
        lifetime = cache["lifetime"]
        self.assertEqual(lifetime["computed_through"], svc._date_str(yesterday))
        # 缓存块只算到昨天：今天的一切由读时增量现叠
        self.assertEqual(lifetime["total_days"], 1)
        # 评审 P3-3：本数存 book_ids 集合（读时内存差集叠今天），不再存计数
        self.assertEqual(lifetime["book_ids"], [100])
        self.assertEqual(lifetime["first_reading_date"], svc._date_str(yesterday))
        self.assertEqual(lifetime["streak_chain"], 1)
        self.assertEqual(lifetime["streak_best"], 1)

        # 清空数据库后同日再查：聚合值应全部来自缓存块（若还在逐请求直查 DB 会掉回 0）
        self.session.execute(text("DELETE FROM readings"))
        self.session.commit()
        stats2 = svc.get_stats(self.session, self.reader)
        self.assertEqual(stats2["total_days"], 1)
        self.assertEqual(stats2["total_books"], 1)
        self.assertEqual(stats2["first_reading_date"], svc._date_str(yesterday))
        self.assertEqual(stats2["streak"], {"current": 1, "best": 1})

    def test_first_read_new_book_today_counts_immediately(self):
        """今天第一次读书：至今口径立即生效（lifetime 块里没有也照常显示）"""
        today = datetime.datetime.utcnow().date()
        self._add_reading(today, duration=60, book_id=300)

        stats = svc.get_stats(self.session, self.reader)
        self.assertEqual(stats["first_reading_date"], svc._date_str(today))
        self.assertEqual(stats["total_days"], 1)
        self.assertEqual(stats["total_books"], 1)
        self.assertEqual(stats["streak"], {"current": 1, "best": 1})

        with open(svc._user_cache_path(1), encoding="utf-8") as f:
            cache = json.load(f)
        self.assertEqual(cache["lifetime"]["book_ids"], [])
        self.assertIsNone(cache["lifetime"]["first_reading_date"])

    def test_new_book_today_not_double_counted_when_seen_before(self):
        """今天读的书如果以前读过，不重复计入 total_books"""
        today = datetime.datetime.utcnow().date()
        long_ago = today - datetime.timedelta(days=30)
        self._add_reading(long_ago, duration=60, book_id=400)
        svc.get_stats(self.session, self.reader)  # 先落一份 lifetime 缓存
        self._add_reading(today, duration=60, book_id=400)

        stats = svc.get_stats(self.session, self.reader)
        self.assertEqual(stats["total_books"], 1)

    def test_backfill_invalidates_lifetime_block(self):
        """补录改历史日后 lifetime 块作废并即时重算（reading_stats_service 补录同改 DB 行）"""
        today = datetime.datetime.utcnow().date()
        old_day = today - datetime.timedelta(days=5)
        self._add_reading(old_day, duration=0)

        stats1 = svc.get_stats(self.session, self.reader)
        self.assertEqual(stats1["total_days"], 0)

        row = self.session.query(Reading).filter_by(reader_id=1, date=old_day).one()
        row.duration = 600
        self.session.commit()
        svc.patch_cached_day(1, old_day, 600)

        with open(svc._user_cache_path(1), encoding="utf-8") as f:
            cache = json.load(f)
        self.assertNotIn("lifetime", cache)

        stats2 = svc.get_stats(self.session, self.reader)
        self.assertEqual(stats2["total_days"], 1)
        self.assertEqual(stats2["first_reading_date"], svc._date_str(old_day))
        self.assertEqual(stats2["streak"], {"current": 0, "best": 1})

    def test_streak_span_broken_then_restarted_across_days(self):
        """连击链条跨天语义：昨天=前天=连续段尾，今天没读维持；今天读了 +1"""
        today = datetime.datetime.utcnow().date()
        for offset in (1, 2, 3, 10):
            self._add_reading(today - datetime.timedelta(days=offset), duration=60)

        stats = svc.get_stats(self.session, self.reader)
        self.assertEqual(stats["streak"], {"current": 3, "best": 3})
        self._add_reading(today, duration=60)
        stats2 = svc.get_stats(self.session, self.reader)
        self.assertEqual(stats2["streak"], {"current": 4, "best": 4})

    # ---- 逐日区间查询（/api/user/reading_range）----

    def test_get_range_days_buckets(self):
        today = datetime.datetime.utcnow().date()
        start = today - datetime.timedelta(days=6)
        self._add_reading(today - datetime.timedelta(days=5), duration=120)
        self._add_reading(today, duration=30)
        self._add_reading(start, action=Reading.ACTION_DOWNLOAD)

        days = svc.get_range_days(self.session, 1, start, today)
        self.assertEqual(len(days), 7)
        by_date = {d["date"]: d for d in days}
        self.assertEqual(by_date[svc._date_str(today - datetime.timedelta(days=5))]["reading_seconds"], 120)
        self.assertEqual(by_date[svc._date_str(today)]["reading_seconds"], 30)
        self.assertEqual(by_date[svc._date_str(start)]["download_count"], 1)
        self.assertEqual(
            by_date[svc._date_str(today - datetime.timedelta(days=2))],
            {"date": svc._date_str(today - datetime.timedelta(days=2)),
             "reading_seconds": 0, "download_count": 0, "push_count": 0},
        )

    def test_normalize_range_parses_and_clamps(self):
        today = datetime.date(2026, 10, 7)
        # 非法输入一律 None
        self.assertIsNone(svc.normalize_range("bad", "2026-10-01", today))
        self.assertIsNone(svc.normalize_range("2026-10-02", "2026-10-01", today))
        self.assertIsNone(svc.normalize_range("", "", today))
        # end 超过今天钳到今天
        self.assertEqual(
            svc.normalize_range("2026-10-01", "2026-12-31", today),
            (datetime.date(2026, 10, 1), today),
        )
        # 超长跨度钳到 RANGE_MAX_SPAN_DAYS
        start, end = svc.normalize_range("2000-01-01", "2026-10-07", today)
        self.assertEqual(end, today)
        self.assertEqual((end - start).days, svc.RANGE_MAX_SPAN_DAYS - 1)
        # 正常区间原样通过
        self.assertEqual(
            svc.normalize_range("2026-09-01", "2026-09-30", today),
            (datetime.date(2026, 9, 1), datetime.date(2026, 9, 30)),
        )
        # 评审 P6-1：整体在未来的区间，end 钳到今天后 start>end，判非法而非返回坏区间
        self.assertIsNone(svc.normalize_range("2026-12-01", "2026-12-31", today))
        self.assertIsNone(svc.normalize_range("2026-10-08", "2026-10-08", today))


class TestReadingLeaderboard(unittest.TestCase):
    """阅读时长排行榜三档（本周 / 本月 / 总时长）"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.conf = loader.get_settings()
        self._orig_sync_path = self.conf.get("MYREADER_SYNC_PATH")
        self.conf["MYREADER_SYNC_PATH"] = self.tmp_dir

        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)
        # _rank_seconds 依赖 date 前导部分索引（INDEXED BY），对齐 async_service 生产 DDL
        self.session.execute(
            text("CREATE INDEX ix_readings_date_read ON readings (date, reader_id) WHERE action='read'")
        )

        self.readers = {}
        for i in range(1, 7):
            r = Reader()
            r.id = i
            r.username = "user%d" % i
            r.name = "" if i % 2 else "昵称%d" % i  # 偶数 id 有昵称，奇数留空试 username 兜底
            r.total_reading_seconds = i * 100
            self.session.add(r)
            self.readers[i] = r
        self.session.commit()

    def tearDown(self):
        self.session.remove()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        if self._orig_sync_path is None:
            self.conf.pop("MYREADER_SYNC_PATH", None)
        else:
            self.conf["MYREADER_SYNC_PATH"] = self._orig_sync_path

    def _add(self, reader_id, date, duration=60, action=Reading.ACTION_READ, book_id=100):
        self.session.add(
            Reading(reader_id, book_id, action, Reading.PROTOCOL_APP,
                    datetime.datetime.combine(date, datetime.time()), duration=duration)
        )
        self.session.commit()

    def test_week_ranking_sums_orders_and_falls_back_to_username(self):
        today = datetime.datetime.utcnow().date()
        # user1 今天跨两本书累加：60+40；user3 昨天读 200
        self._add(1, today, 60)
        self._add(1, today, 40, book_id=101)
        self._add(3, today - datetime.timedelta(days=1), 200)
        # 非 read 动作与 0 秒行不入榜
        self._add(5, today, 9999, action=Reading.ACTION_DOWNLOAD)
        self._add(6, today, 0)

        board = svc.get_leaderboard(self.session)
        self.assertEqual([e["reader_id"] for e in board["week"]], [3, 1])
        self.assertEqual(board["week"][0]["seconds"], 200)
        self.assertEqual(board["week"][1]["seconds"], 100)  # 60 + 40 累加
        # user3 奇数 id 无昵称 → username 兜底
        self.assertEqual(board["week"][0]["name"], "user3")

    def test_opted_out_reader_excluded_from_all_boards(self):
        today = datetime.datetime.utcnow().date()
        self._add(3, today, 200)
        self._add(1, today, 60)
        self.readers[3].allow_statistic = False
        self.session.commit()

        board = svc.get_leaderboard(self.session)
        self.assertEqual([e["reader_id"] for e in board["week"]], [1])
        self.assertEqual([e["reader_id"] for e in board["month"]], [1])
        self.assertNotIn(3, [e["reader_id"] for e in board["all_time"]])

    def test_all_time_uses_reader_column_and_excludes_zero(self):
        for r in self.session.query(Reader).all():
            r.total_reading_seconds = 0 if r.id == 2 else r.id * 100
        self.session.commit()

        board = svc.get_leaderboard(self.session)
        self.assertEqual([e["reader_id"] for e in board["all_time"]], [6, 5, 4, 3, 1])
        self.assertEqual(board["all_time"][0]["seconds"], 600)
        self.assertNotIn(2, [e["reader_id"] for e in board["all_time"]])

    def test_limit_caps_at_leaderboard_limit(self):
        today = datetime.datetime.utcnow().date()
        for i in range(1, 7):
            self._add(i, today, i * 10)
        board = svc.get_leaderboard(self.session)
        self.assertEqual(len(board["week"]), svc.LEADERBOARD_LIMIT)
        self.assertEqual(len(board["month"]), svc.LEADERBOARD_LIMIT)

    def test_week_and_month_windows_are_independent(self):
        """固定 today 到月中周三：本周内的进两榜，上周但在本月的只进月榜，上月两个都不进"""
        today = datetime.date(2026, 6, 17)
        week_start = today - datetime.timedelta(days=today.weekday())
        # week_start ∈ [6-11, 6-17]（6 月 17 日无论星期几）：
        # week_start+1 必在本周且必在 6 月；6-05 早于任何 week_start，在本月不在本周
        self._add(1, week_start + datetime.timedelta(days=1), 10)  # 本周、本月
        self._add(3, datetime.date(2026, 6, 5), 20)                # 本月、不在本周
        self._add(4, datetime.date(2026, 5, 30), 30)               # 上月，两榜都不进

        board = svc.get_leaderboard(self.session, today=today)
        self.assertEqual([(e["reader_id"], e["seconds"]) for e in board["week"]], [(1, 10)])
        self.assertEqual([(e["reader_id"], e["seconds"]) for e in board["month"]], [(3, 20), (1, 10)])

    def test_no_readings_returns_empty_window_lists(self):
        board = svc.get_leaderboard(self.session)
        self.assertEqual(board["week"], [])
        self.assertEqual(board["month"], [])
        # all_time 吃 Reader 列，与 readings 表无关，此处非空
        self.assertEqual([e["reader_id"] for e in board["all_time"]], [6, 5, 4, 3, 2, 1][:svc.LEADERBOARD_LIMIT])


if __name__ == "__main__":
    unittest.main()
