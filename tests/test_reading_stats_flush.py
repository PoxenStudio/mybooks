#!/usr/bin/env python3

import datetime
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import models
from webserver.models import BookReadingStats, Item, Reader, Reading
from webserver.services.reading_stats_service import MANUAL_READING_MAX_SECONDS, ReadingStatsService, ReadingWriteBuffer
from webserver.services.reader_cache import ReaderStatsCache


class TestReadingWriteBufferFlush(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)
        self.session.execute(
            text("CREATE UNIQUE INDEX ux_readings_read ON readings (reader_id, book_id, date) WHERE action='read'")
        )
        reader = Reader()
        reader.id = 1
        reader.username = "u1"
        reader.total_reading_seconds = 0
        reader.download_count = 0
        self.session.add(reader)
        self.session.commit()
        self.buf = ReadingWriteBuffer()
        ReaderStatsCache().invalidate(1)  # singleton cache: don't leak state across tests

    def tearDown(self):
        self.session.remove()

    def test_first_read_creates_row_and_bumps_item_visit_once(self):
        t0 = datetime.datetime(2026, 1, 1, 0, 0, 0)
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, t0)
        self.buf.flush()

        row = self.session.query(Reading).filter_by(reader_id=1, book_id=100, action=Reading.ACTION_READ).one()
        self.assertEqual(row.duration, 0)
        item = self.session.query(Item).filter_by(book_id=100).one()
        self.assertEqual(item.count_visit, 1)

        # Second heartbeat within the same session shouldn't bump count_visit again
        t1 = t0 + datetime.timedelta(seconds=5)
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, t1)
        self.buf.flush()

        row = self.session.query(Reading).filter_by(reader_id=1, book_id=100, action=Reading.ACTION_READ).one()
        self.assertEqual(row.duration, 5)
        item = self.session.query(Item).filter_by(book_id=100).one()
        self.assertEqual(item.count_visit, 1)  # not incremented twice

        reader = self.session.query(Reader).filter_by(id=1).one()
        self.assertEqual(reader.total_reading_seconds, 5)

    def test_reading_on_a_different_day_creates_a_new_row_and_bumps_count_visit_again(self):
        t0 = datetime.datetime(2026, 1, 1, 12, 0, 0)
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, t0)
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, t0 + datetime.timedelta(seconds=5))
        self.buf.flush()

        rows = self.session.query(Reading).filter_by(reader_id=1, book_id=100, action=Reading.ACTION_READ).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].date, t0.date())
        self.assertEqual(rows[0].duration, 5)
        item = self.session.query(Item).filter_by(book_id=100).one()
        self.assertEqual(item.count_visit, 1)

        # same book, next day: a distinct per-day row, and count_visit counts it again
        t1 = t0 + datetime.timedelta(days=1)
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, t1)
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, t1 + datetime.timedelta(seconds=8))
        self.buf.flush()

        rows = self.session.query(Reading).filter_by(reader_id=1, book_id=100, action=Reading.ACTION_READ).order_by(Reading.date).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].date, t0.date())
        self.assertEqual(rows[0].duration, 5)  # untouched by the next day's activity
        self.assertEqual(rows[1].date, t1.date())
        self.assertEqual(rows[1].duration, 8)
        item = self.session.query(Item).filter_by(book_id=100).one()
        self.assertEqual(item.count_visit, 2)  # opened on two distinct days -> counted twice

        reader = self.session.query(Reader).filter_by(id=1).one()
        self.assertEqual(reader.total_reading_seconds, 13)  # 5 + 8, still a global cross-day total

    def test_download_and_push_events_both_bump_item_count_download(self):
        t0 = datetime.datetime(2026, 1, 1, 0, 0, 0)
        self.buf.on_event(1, 200, Reading.ACTION_DOWNLOAD, Reading.PROTOCOL_WEB, t0)
        self.buf.on_event(1, 200, Reading.ACTION_PUSH, Reading.PROTOCOL_DEVICE, t0)
        self.buf.flush()

        item = self.session.query(Item).filter_by(book_id=200).one()
        self.assertEqual(item.count_download, 2)  # download + push both count here

        reader = self.session.query(Reader).filter_by(id=1).one()
        self.assertEqual(reader.download_count, 1)  # Reader.download_count only counts real downloads

        rows = self.session.query(Reading).filter_by(reader_id=1, book_id=200).all()
        self.assertEqual(len(rows), 2)

    def test_explicit_report_lands_in_the_given_day_bucket(self):
        """离线阅读显式上报：不依赖到达间隔，直接把客户端算好的秒数记到指定的那一天。"""
        yesterday = datetime.date(2025, 12, 31)
        t0 = datetime.datetime(2026, 1, 1, 0, 0, 0)
        self.buf.on_explicit(1, 100, Reading.PROTOCOL_APP, yesterday, 1800, t0)
        self.buf.flush()

        row = self.session.query(Reading).filter_by(reader_id=1, book_id=100, action=Reading.ACTION_READ).one()
        self.assertEqual(row.date, yesterday)
        self.assertEqual(row.duration, 1800)
        self.assertEqual(row.protocol, Reading.PROTOCOL_APP)

        reader = self.session.query(Reader).filter_by(id=1).one()
        self.assertEqual(reader.total_reading_seconds, 1800)

        item = self.session.query(Item).filter_by(book_id=100).one()
        self.assertEqual(item.count_visit, 1)

    def test_explicit_reports_for_two_different_days_create_two_rows(self):
        """跨天离线：客户端按本地日期分桶上报，两天各自落一行，互不合并。"""
        day1 = datetime.date(2025, 12, 30)
        day2 = datetime.date(2025, 12, 31)
        t0 = datetime.datetime(2026, 1, 1, 0, 0, 0)
        self.buf.on_explicit(1, 100, Reading.PROTOCOL_APP, day1, 600, t0)
        self.buf.on_explicit(1, 100, Reading.PROTOCOL_APP, day2, 900, t0)
        self.buf.flush()

        rows = self.session.query(Reading).filter_by(reader_id=1, book_id=100, action=Reading.ACTION_READ).order_by(Reading.date).all()
        self.assertEqual([r.date for r in rows], [day1, day2])
        self.assertEqual([r.duration for r in rows], [600, 900])

        reader = self.session.query(Reader).filter_by(id=1).one()
        self.assertEqual(reader.total_reading_seconds, 1500)

        item = self.session.query(Item).filter_by(book_id=100).one()
        self.assertEqual(item.count_visit, 2)  # 两个不同的天各算一次"打开"

    def test_explicit_report_alongside_an_open_heartbeat_session_lands_in_its_own_row(self):
        """同一本书：今天的在线心跳会话仍在内存里打开着，同时又收到昨天的离线补报——
        两者各自落到各自的天，互不覆盖（对应 sync_service.push() 里两条路径分走不同书/
        不同天，但缓冲区自身不假设这一点，也要保证不串)。"""
        today = datetime.date(2026, 1, 1)
        yesterday = today - datetime.timedelta(days=1)
        t0 = datetime.datetime(2026, 1, 1, 12, 0, 0)
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, t0)
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, t0 + datetime.timedelta(seconds=5))
        self.buf.on_explicit(1, 100, Reading.PROTOCOL_APP, yesterday, 1200, t0)
        self.buf.flush()

        rows = {r.date: r for r in self.session.query(Reading).filter_by(reader_id=1, book_id=100, action=Reading.ACTION_READ).all()}
        self.assertEqual(rows[today].duration, 5)
        self.assertEqual(rows[yesterday].duration, 1200)
        reader = self.session.query(Reader).filter_by(id=1).one()
        self.assertEqual(reader.total_reading_seconds, 1205)


class TestReadingStatsServiceReportDuration(unittest.TestCase):
    """ReadingStatsService.report_duration() 是薅了 ReadingWriteBuffer/BookFormatStatsBuffer
    的 on_explicit() 之外，额外做的一层校验/联动（上限封顶、未来日期兜底、按格式统计联动、
    统计开关），这层薅出来的逻辑不属于任何一个 buffer 类，专门测。

    ReadingStatsService._buffer/_format_buffer 是进程级单例，这里在每个用例前后把它们的
    内存态清空/复原，避免和同进程里其它测试文件互相污染。
    """

    def setUp(self):
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)
        self.session.execute(
            text("CREATE UNIQUE INDEX ux_readings_read ON readings (reader_id, book_id, date) WHERE action='read'")
        )
        reader = Reader()
        reader.id = 1
        reader.username = "u1"
        reader.total_reading_seconds = 0
        reader.download_count = 0
        self.session.add(reader)
        self.session.commit()
        ReaderStatsCache().invalidate(1)
        self._reset_singleton_buffers()

    def tearDown(self):
        self._reset_singleton_buffers()
        ReaderStatsCache().invalidate(1)
        self.session.remove()

    @staticmethod
    def _reset_singleton_buffers():
        buf = ReadingStatsService._buffer
        buf._sessions.clear()
        buf._explicit.clear()
        buf._events.clear()
        buf._reader_seconds_delta.clear()
        buf._reader_download_delta.clear()
        buf._reader_push_delta.clear()
        ReadingStatsService._format_buffer._states.clear()

    def test_report_duration_updates_reading_bucket_and_book_format_stats(self):
        yesterday = datetime.date(2025, 12, 31)
        ReadingStatsService.report_duration(1, 100, Reading.PROTOCOL_APP, yesterday, 1800, fmt="epub", progress=(10, 200))
        ReadingStatsService.flush_now()

        row = self.session.query(Reading).filter_by(reader_id=1, book_id=100, action=Reading.ACTION_READ).one()
        self.assertEqual(row.date, yesterday)
        self.assertEqual(row.duration, 1800)

        fmt_row = self.session.query(BookReadingStats).filter_by(reader_id=1, book_id=100, format="epub").one()
        self.assertEqual(fmt_row.total_seconds, 1800)
        self.assertEqual(fmt_row.progress_current, 10)

    def test_duration_is_capped_at_manual_reading_max_seconds(self):
        yesterday = datetime.date(2025, 12, 31)
        ReadingStatsService.report_duration(1, 100, Reading.PROTOCOL_APP, yesterday, MANUAL_READING_MAX_SECONDS + 5000, fmt="epub")
        ReadingStatsService.flush_now()

        row = self.session.query(Reading).filter_by(reader_id=1, book_id=100, action=Reading.ACTION_READ).one()
        self.assertEqual(row.duration, MANUAL_READING_MAX_SECONDS)

    def test_future_dates_are_pulled_back_to_today(self):
        """客户端已按方案在上报前把日期转成 UTC，这里是服务端兜底：无法信任的未来日期
        会被拉回服务端的"今天"，而不是原样落库。"""
        far_future = datetime.date(2099, 1, 1)
        ReadingStatsService.report_duration(1, 100, Reading.PROTOCOL_APP, far_future, 120, fmt="epub")
        ReadingStatsService.flush_now()

        row = self.session.query(Reading).filter_by(reader_id=1, book_id=100, action=Reading.ACTION_READ).one()
        self.assertLess(row.date, far_future)

    def test_skipped_entirely_when_reader_opted_out_of_statistics(self):
        ReaderStatsCache().set_allow_statistic(1, False)
        ReadingStatsService.report_duration(1, 100, Reading.PROTOCOL_APP, datetime.date(2025, 12, 31), 600, fmt="epub")
        ReadingStatsService.flush_now()
        self.assertIsNone(
            self.session.query(Reading).filter_by(reader_id=1, book_id=100, action=Reading.ACTION_READ).one_or_none()
        )

    def test_zero_or_negative_duration_is_a_no_op(self):
        ReadingStatsService.report_duration(1, 100, Reading.PROTOCOL_APP, datetime.date(2025, 12, 31), 0, fmt="epub")
        ReadingStatsService.flush_now()
        self.assertIsNone(
            self.session.query(Reading).filter_by(reader_id=1, book_id=100, action=Reading.ACTION_READ).one_or_none()
        )


if __name__ == "__main__":
    unittest.main()
