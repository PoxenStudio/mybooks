#!/usr/bin/env python3
"""「本月在读/读完」按站点时区切月的 SQL 边界（handlers/book.py 的 _read_state_month_filter）。

``reading_state.read_date`` 存的是服务器本地 naive 时间（models.py 用 ``datetime.now()``
写入），区间端点必须换算到同一坐标系再比较。这里用真实 sqlite 跑三条边界行，钉住
``[月初, 下月初)`` 的半开语义——起点含、终点不含。
"""

import datetime
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import loader, models, site_time
from webserver.handlers.book import _read_state_month_filter
from webserver.models import ReadingState


class TestReadingStateMonthFilter(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)

        self.conf = loader.get_settings()
        self._orig_tz = self.conf.get("site_timezone")
        self.conf["site_timezone"] = "Asia/Shanghai"

    def tearDown(self):
        self.session.remove()
        if self._orig_tz is None:
            self.conf.pop("site_timezone", None)
        else:
            self.conf["site_timezone"] = self._orig_tz

    def _add(self, book_id, read_date, read_state=2):
        row = ReadingState(book_id, 1)
        # 直接赋列、不走 set_read_state：那个方法会用 datetime.now() 覆盖成"现在"
        row.read_state = read_state
        row.read_date = read_date
        self.session.add(row)
        self.session.commit()

    def test_half_open_boundaries_use_server_local_time(self):
        today = datetime.date(2026, 11, 15)
        # 站点东八区、服务器时区注入 UTC：站点 11 月 = [10-31 16:00, 11-30 16:00)
        start, end = site_time.site_month_bounds_server_local(today, datetime.timezone.utc)
        self._add(1, start - datetime.timedelta(microseconds=1))  # 上月末，排除
        self._add(2, start)  # 月初当刻，计入
        self._add(3, end - datetime.timedelta(microseconds=1))  # 月末最后一刻，计入
        self._add(4, end)  # 下月初当刻，排除

        conds = _read_state_month_filter(today, datetime.timezone.utc)
        rows = (
            self.session.query(ReadingState.book_id)
            .filter(ReadingState.reader_id == 1, *conds)
            .order_by(ReadingState.book_id)
            .all()
        )
        self.assertEqual([row.book_id for row in rows], [2, 3])

    def test_early_morning_mark_on_the_first_counts_for_the_new_month(self):
        """东八区 11-01 00:30 标记"读完"不能被算进 10 月（旧 extract 实现的 bug）。"""
        today = datetime.date(2026, 11, 15)
        # 服务器时区=UTC 时，read_date 记作 10-31 16:30
        self._add(1, datetime.datetime(2026, 10, 31, 16, 30))
        conds = _read_state_month_filter(today, datetime.timezone.utc)
        rows = self.session.query(ReadingState.book_id).filter(ReadingState.reader_id == 1, *conds).all()
        self.assertEqual([row.book_id for row in rows], [1])


if __name__ == "__main__":
    unittest.main()
