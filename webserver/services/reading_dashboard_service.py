#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Read-side aggregation for the homepage reading-stats banner.

Feeds off webserver.models.Reading/Reader/ReadingState (written by
reading_stats_service.ReadingWriteBuffer). Historical (already-closed) daily
buckets are cached per-user in `<MYREADER_SYNC_PATH>/<uid>/reading.json`, and
only rewritten once a day when the cache falls behind "yesterday" — today's
data is always computed live and never persisted. The "lifetime" block (streak
/ total days / total books / first reading date, read up to yesterday) lives in
the same file and is likewise recomputed only when cached_through advances, so
the full-history scans behind it cost one request per user per day, not every
homepage hit; today's deltas ride on top at read time.

See document/Reading_Dashboard_Design.md for the full design.
"""

import datetime
import json
import logging
import os
from typing import Dict, Optional

from sqlalchemy import func, text

from webserver import loader
from webserver.models import BookReadingStats, Reader, Reading, ReadingState

CONF = loader.get_settings()

CACHE_VERSION = 1
DISPLAY_WEEKS = 8
HEATMAP_WEEKS = 13  # 近 3 个月，见 history.vue 的阅读热力图
# 缓存要覆盖两个消费者里更长的那个（+1 周缓冲，避免自然周边界刚好缺一天）：
# 周图表用 DISPLAY_WEEKS，热力图用 HEATMAP_WEEKS。
CACHE_RETENTION_DAYS = (max(DISPLAY_WEEKS, HEATMAP_WEEKS) + 1) * 7

# 「即将读完」卡：在读且进度 ≥ 该百分位的书才算接近完结，取前 N 本
NEAR_FINISH_MIN_PERCENT = 80.0
NEAR_FINISH_LIMIT = 5

# 逐日区间查询（/api/user/reading_range）的最大跨度，约 10 年
RANGE_MAX_SPAN_DAYS = 3660


def _user_cache_path(uid) -> str:
    return os.path.join(
        CONF.get("MYREADER_SYNC_PATH", "/data/sync/"), str(uid), "reading.json"
    )


def _date_str(d: datetime.date) -> str:
    return d.strftime("%Y-%m-%d")


def _empty_cache() -> Dict:
    return {"version": CACHE_VERSION, "cached_through": None, "days": {}}


def _load_cache(uid) -> Dict:
    path = _user_cache_path(uid)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("days"), dict):
            raise ValueError("malformed reading.json structure")
        return data
    except FileNotFoundError:
        return _empty_cache()
    except Exception as e:
        logging.warning(
            "[reading_dashboard] failed to load %s, rebuilding from scratch: %s",
            path,
            e,
        )
        return _empty_cache()


def _save_cache(uid, cache: Dict) -> None:
    path = _user_cache_path(uid)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        os.replace(tmp_path, path)
    except Exception as e:
        logging.warning("[reading_dashboard] failed to save %s: %s", path, e)


def _query_days(
    db, reader_id: int, start: datetime.date, end: datetime.date
) -> Dict[str, Dict[str, int]]:
    """Aggregate Reading rows for reader_id within [start, end] (inclusive), bucketed by date+action."""
    rows = db.execute(
        text(
            """
            SELECT date, action, SUM(duration) AS total_duration, COUNT(*) AS cnt
            FROM readings
            WHERE reader_id = :reader_id AND date BETWEEN :start AND :end
            GROUP BY date, action
            """
        ),
        dict(reader_id=reader_id, start=start, end=end),
    ).fetchall()

    days: Dict[str, Dict[str, int]] = {}
    for row in rows:
        date_str = row.date if isinstance(row.date, str) else _date_str(row.date)
        bucket = days.setdefault(
            date_str, {"reading_seconds": 0, "download_count": 0, "push_count": 0}
        )
        if row.action == Reading.ACTION_READ:
            bucket["reading_seconds"] += int(row.total_duration or 0)
        elif row.action == Reading.ACTION_DOWNLOAD:
            bucket["download_count"] += int(row.cnt or 0)
        elif row.action == Reading.ACTION_PUSH:
            bucket["push_count"] += int(row.cnt or 0)
    return days


def _prune(days: Dict[str, Dict], today: datetime.date) -> Dict[str, Dict]:
    cutoff = today - datetime.timedelta(days=CACHE_RETENTION_DAYS)
    return {d: v for d, v in days.items() if d >= _date_str(cutoff)}


def _reconcile(db, reader_id: int, cache: Dict, today: datetime.date) -> Dict:
    """Bring the cache's closed-day coverage up to "yesterday", writing to disk only if it moved."""
    yesterday = today - datetime.timedelta(days=1)
    cached_through = cache.get("cached_through")
    cached_through_date = None
    if cached_through:
        try:
            cached_through_date = datetime.datetime.strptime(
                cached_through, "%Y-%m-%d"
            ).date()
        except ValueError:
            cached_through_date = None

    if cached_through_date is not None and cached_through_date >= yesterday:
        return cache

    start = (
        (cached_through_date + datetime.timedelta(days=1))
        if cached_through_date
        else (today - datetime.timedelta(days=CACHE_RETENTION_DAYS))
    )
    if start > yesterday:
        cache["cached_through"] = _date_str(yesterday)
        return cache

    fresh_days = _query_days(db, reader_id, start, yesterday)
    days = cache.get("days", {})
    days.update(fresh_days)
    # days with no activity at all never appear in fresh_days; that's fine, they're
    # simply absent from the cache and treated as zero when read back.
    cache["days"] = _prune(days, today)
    cache["cached_through"] = _date_str(yesterday)
    cache["version"] = CACHE_VERSION
    _save_cache(reader_id, cache)
    return cache


def patch_cached_day(reader_id: int, date: datetime.date, delta_seconds: int) -> None:
    """_reconcile 只会向前推进、不会回填已缓存的历史日，手工补录改的是过去某天时需要
    直接把 delta 写进缓存，否则周图表会一直显示旧值。"""
    if not delta_seconds:
        return
    cache = _load_cache(reader_id)
    cached_through = cache.get("cached_through")
    date_str = _date_str(date)
    if not cached_through or date_str > cached_through:
        return
    days = cache.setdefault("days", {})
    bucket = days.setdefault(date_str, {"reading_seconds": 0, "download_count": 0, "push_count": 0})
    bucket["reading_seconds"] = max(0, bucket.get("reading_seconds", 0) + delta_seconds)
    # 补录可能把某个 0 秒日变成有效阅读日（或反之），lifetime 缓存块作废，
    # 下次 get_stats 重算
    cache.pop("lifetime", None)
    _save_cache(reader_id, cache)


def _week_start(d: datetime.date) -> datetime.date:
    return d - datetime.timedelta(days=d.weekday())  # Monday


def _weekly_buckets(days: Dict[str, Dict], today: datetime.date) -> list:
    this_week_start = _week_start(today)
    week_starts = [
        this_week_start - datetime.timedelta(weeks=i)
        for i in range(DISPLAY_WEEKS - 1, -1, -1)
    ]
    weekly = []
    for ws in week_starts:
        reading_seconds = download_count = push_count = 0
        for i in range(7):
            day = ws + datetime.timedelta(days=i)
            if day > today:
                break
            bucket = days.get(_date_str(day))
            if bucket:
                reading_seconds += bucket.get("reading_seconds", 0)
                download_count += bucket.get("download_count", 0)
                push_count += bucket.get("push_count", 0)
        weekly.append(
            {
                "week_start": _date_str(ws),
                "reading_seconds": reading_seconds,
                "download_count": download_count,
                "push_count": push_count,
            }
        )
    return weekly


def _heatmap_days(days: Dict[str, Dict], today: datetime.date, weeks: int = HEATMAP_WEEKS) -> list:
    """近 `weeks` 个自然周（周一起点）的逐日阅读时长，供前端热力图使用。
    只到今天为止，本周未来的日期不生成（前端按 7 天一列补空格子）。"""
    start = _week_start(today) - datetime.timedelta(weeks=weeks - 1)
    result = []
    d = start
    while d <= today:
        bucket = days.get(_date_str(d))
        result.append(
            {"date": _date_str(d), "reading_seconds": (bucket or {}).get("reading_seconds", 0)}
        )
        d += datetime.timedelta(days=1)
    return result


def _book_status(db, reader_id: int, calibre_db=None) -> Dict[str, int]:
    rows = (
        db.query(ReadingState.read_state, ReadingState.wants, ReadingState.book_id)
        .filter(ReadingState.reader_id == reader_id)
        .all()
    )
    status = {"reading": 0, "to_read": 0, "finished": 0}
    for read_state, wants, _book_id in rows:
        if calibre_db and not calibre_db.has_id(_book_id):
            continue
        if read_state == 1:
            status["reading"] += 1
        elif read_state == 2:
            status["finished"] += 1
        elif wants:
            status["to_read"] += 1
    return status


def _read_dates(db, reader_id: int, end: Optional[datetime.date] = None) -> list:
    """全部"有效阅读日"（当天累计时长 > 0），升序返回 list[date]。

    供连击/阅读天数/首读日期使用；与热力图同口径——0 秒的空桶不算阅读日。
    `end`（含）用于 lifetime 缓存块"算到昨天为止"的口径。
    """
    sql = (
        "SELECT date, SUM(duration) AS total_duration"
        " FROM readings"
        " WHERE reader_id = :reader_id AND action = 'read'"
    )
    params = {"reader_id": reader_id}
    if end is not None:
        sql += " AND date <= :end"
        params["end"] = end
    sql += " GROUP BY date HAVING total_duration > 0"
    rows = db.execute(text(sql), params).fetchall()
    dates = []
    for row in rows:
        d = row.date if not isinstance(row.date, str) else datetime.datetime.strptime(row.date, "%Y-%m-%d").date()
        dates.append(d)
    dates.sort()
    return dates


def _compute_streaks(dates: list, today: datetime.date) -> Dict[str, int]:
    """current = 今天（或今天还没读时的昨天）往回数的连续阅读天数；best = 史上最长连续段。"""
    if not dates:
        return {"current": 0, "best": 0}
    date_set = set(dates)
    best = run = 1
    for prev, cur in zip(dates, dates[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        best = max(best, run)

    anchor = today if today in date_set else today - datetime.timedelta(days=1)
    if anchor not in date_set:
        return {"current": 0, "best": best}
    current = 0
    d = anchor
    while d in date_set:
        current += 1
        d -= datetime.timedelta(days=1)
    return {"current": current, "best": best}


def _chain_ending_at(dates: list, end: datetime.date) -> int:
    """恰好以 `end` 收尾的连续阅读段长度；`end` 当天没读返回 0（连击已断）。"""
    date_set = set(dates)
    if end not in date_set:
        return 0
    n = 0
    d = end
    while d in date_set:
        n += 1
        d -= datetime.timedelta(days=1)
    return n


def _compute_lifetime(db, reader_id: int, through: datetime.date) -> Dict:
    """截至 `through`（含）的全历史聚合，写进 reading.json 的 lifetime 块。

    这是全历史扫描（重度用户实测 ~80ms），只随 cached_through 每日推进重算一次；
    streak_chain 存"恰好止于 through 的连续段"，今天开读与否由 get_stats 现叠。
    本数存 book_ids 集合而非计数：今天首读的书用纯内存差集并入"读过 N 本"，
    避免逐请求再查一遍 `date < today` 的回表历史行（评审一轮 P3-3：那样重度用户
    实测每请求 28.8ms，热路径成本等于没修）。
    """
    read_dates = _read_dates(db, reader_id, end=through)
    streaks = _compute_streaks(read_dates, through)
    book_rows = db.execute(
        text(
            """
            SELECT DISTINCT book_id
            FROM readings
            WHERE reader_id = :reader_id AND action = 'read' AND duration > 0
              AND date <= :end
            """
        ),
        dict(reader_id=reader_id, end=through),
    ).fetchall()
    return {
        "computed_through": _date_str(through),
        "first_reading_date": _date_str(read_dates[0]) if read_dates else None,
        "total_days": len(read_dates),
        "book_ids": sorted(row.book_id for row in book_rows),
        "streak_best": streaks["best"],
        "streak_chain": _chain_ending_at(read_dates, through),
    }


def _today_read_book_ids(db, reader_id: int, today: datetime.date) -> list:
    """今天读了（时长 > 0）的 book_id 列表。是否"新书"由调用方与 lifetime.book_ids
    做内存差集，不再逐请求回表扫历史（评审一轮 P3-3）。

    INDEXED BY 是刻意的：这组表上 SQLite 的启发式代价会在"reader_id=? AND date=?"
    上错挑 ux_readings_read / ix_readings_reader_book_action 只用到 reader_id 前缀，
    实测退化成整用户历史扫描（2.5~30ms/请求）。(reader_id, date) 单点才是今天桶的
    正确形态（个位数行）。索引由 async_service.adjust_readings_table 启动时必建，
    与 ReadingWriteBuffer upsert 依赖的部分唯一索引同一 DDL 步骤，可信赖存在。
    """
    rows = db.execute(
        text(
            """
            SELECT DISTINCT book_id
            FROM readings INDEXED BY ix_readings_reader_date
            WHERE reader_id = :reader_id AND date = :today AND action = 'read' AND duration > 0
            """
        ),
        dict(reader_id=reader_id, today=today),
    ).fetchall()
    return [row.book_id for row in rows]


def _period_sums(days: Dict[str, Dict], today: datetime.date) -> Dict[str, int]:
    """近 7 天 / 上一个 7 天 / 近 30 天的阅读秒数，从已加载的逐日桶里累加（今日为实时值）。"""

    def _sum(start: datetime.date, end: datetime.date) -> int:
        total = 0
        d = start
        while d <= end:
            bucket = days.get(_date_str(d))
            if bucket:
                total += bucket.get("reading_seconds", 0)
            d += datetime.timedelta(days=1)
        return total

    return {
        "last7_seconds": _sum(today - datetime.timedelta(days=6), today),
        "prev7_seconds": _sum(today - datetime.timedelta(days=13), today - datetime.timedelta(days=7)),
        "last30_seconds": _sum(today - datetime.timedelta(days=29), today),
    }


def _near_finish_rows(db, reader_id: int) -> list:
    """在读且进度接近完结的书：先按 book_id 分组取各格式里的最高进度，再按书倒序取前 N。

    必须先 GROUP BY 再 LIMIT：按格式行排序去重会让多格式的书以格式行数占坑、
    挤掉后面的书（实测 4 本×4 格式占满预取行，第 5 本被切）。total_seconds 取该
    本最高进度那一行，与旧实现的去重口径一致。
    """
    top = (
        db.query(
            BookReadingStats.book_id,
            func.max(BookReadingStats.progress_percent).label("max_percent"),
        )
        .filter(
            BookReadingStats.reader_id == reader_id,
            BookReadingStats.state == BookReadingStats.STATE_READING,
            BookReadingStats.progress_percent >= NEAR_FINISH_MIN_PERCENT,
        )
        .group_by(BookReadingStats.book_id)
        .order_by(func.max(BookReadingStats.progress_percent).desc())
        .limit(NEAR_FINISH_LIMIT)
        .all()
    )
    if not top:
        return []
    max_by_book = {row.book_id: float(row.max_percent or 0) for row in top}
    detail = (
        db.query(
            BookReadingStats.book_id,
            BookReadingStats.progress_percent,
            BookReadingStats.total_seconds,
        )
        .filter(
            BookReadingStats.reader_id == reader_id,
            BookReadingStats.state == BookReadingStats.STATE_READING,
            BookReadingStats.book_id.in_(list(max_by_book)),
        )
        .all()
    )
    seconds_by_book: Dict[int, int] = {}
    for book_id, percent, total_seconds in detail:
        if book_id in seconds_by_book:
            continue
        if float(percent or 0) == max_by_book[book_id]:
            seconds_by_book[book_id] = int(total_seconds or 0)
    return [
        {
            "book_id": row.book_id,
            "progress_percent": round(float(row.max_percent or 0), 1),
            "total_seconds": seconds_by_book.get(row.book_id, 0),
        }
        for row in top
    ]


def normalize_range(start_str, end_str, today):
    """解析并钳制逐日查询区间：非法/倒序返回 None；end 不超过今天；跨度不超过 RANGE_MAX_SPAN_DAYS。

    返回 (start, end) tuple 或 None。
    """

    def _parse(value):
        try:
            return datetime.datetime.strptime(value, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    start = _parse(start_str)
    end = _parse(end_str)
    if start is None or end is None or start > end:
        return None
    end = min(end, today)
    if start > end:
        # end 被钳到今天之后，区间整体在未来：视为非法，不返回 start > end 的坏区间
        return None
    if (end - start).days >= RANGE_MAX_SPAN_DAYS:
        start = end - datetime.timedelta(days=RANGE_MAX_SPAN_DAYS - 1)
    return start, end


def get_range_days(db, reader_id: int, start: datetime.date, end: datetime.date) -> list:
    """[start, end]（含两端）逐日阅读聚合，直接查 readings 表，今天的数据天然实时。

    供阅读记录页周/月/年/总四种时间档的图表使用；调用方负责钳制区间长度。
    """
    buckets = _query_days(db, reader_id, start, end)
    result = []
    d = start
    while d <= end:
        bucket = buckets.get(_date_str(d)) or {}
        result.append(
            {
                "date": _date_str(d),
                "reading_seconds": bucket.get("reading_seconds", 0),
                "download_count": bucket.get("download_count", 0),
                "push_count": bucket.get("push_count", 0),
            }
        )
        d += datetime.timedelta(days=1)
    return result


def get_stats(db, reader: Reader, calibre_db=None) -> Optional[Dict]:
    if not CONF.get("ENABLE_HOMEPAGE_READING_STATS", True):
        return None

    today = datetime.datetime.utcnow().date()
    cache = _load_cache(reader.id)
    cache = _reconcile(db, reader.id, cache, today)

    days = dict(cache.get("days", {}))
    # today is never cached, always live
    today_bucket = _query_days(db, reader.id, today, today)
    days.update(today_bucket)

    # 全历史聚合（连击/天数/首读日/本数）进 reading.json 的 lifetime 块：全历史查询
    # 只随 cached_through 每日推进重算一次（重度用户实测 ~80ms，首页热路径不该逐请求
    # 付费）；今天对"至今"的影响按当天桶现算增量叠加。reading.json 的 days 缓存只
    # 保留 98 天，lifetime 块则扫全表算的就是"至今"。
    cached_through = cache.get("cached_through")
    lifetime = cache.get("lifetime")
    if not isinstance(lifetime, dict) or lifetime.get("computed_through") != cached_through or not isinstance(lifetime.get("book_ids"), list):
        # _reconcile 之后 cached_through 恒为"昨天"的合法日期串；异常缺失时钳到昨天，
        # 让今天的增量仍走统一的现叠口径（若算到今天再叠会双计今天）
        through = (
            datetime.datetime.strptime(cached_through, "%Y-%m-%d").date()
            if cached_through
            else today - datetime.timedelta(days=1)
        )
        lifetime = _compute_lifetime(db, reader.id, through)
        cache["lifetime"] = lifetime
        _save_cache(reader.id, cache)

    # 恒等式：streak_chain 恰好止于 cached_through（= 昨天）。今天读了则连击 +1
    # （昨天没读时 chain=0，+1 恰为 1）；今天没读则连击原样维持。
    read_today = (days.get(_date_str(today)) or {}).get("reading_seconds", 0) > 0
    streak_current = lifetime["streak_chain"] + 1 if read_today else lifetime["streak_chain"]
    streak_best = max(lifetime["streak_best"], streak_current)
    read_book_ids = set(lifetime["book_ids"])
    first_reading_date = lifetime["first_reading_date"]
    if read_today:
        new_books = [b for b in _today_read_book_ids(db, reader.id, today) if b not in read_book_ids]
        total_books = len(read_book_ids) + len(new_books)
        if first_reading_date is None:
            first_reading_date = _date_str(today)
    else:
        total_books = len(read_book_ids)

    return {
        "totals": {
            "total_reading_seconds": reader.total_reading_seconds or 0,
            "download_count": reader.download_count or 0,
            "push_count": reader.push_count or 0,
        },
        "weekly": _weekly_buckets(days, today),
        "heatmap": {"weeks": HEATMAP_WEEKS, "days": _heatmap_days(days, today)},
        "book_status": _book_status(db, reader.id, calibre_db),
        # ---- 以下为阅读记录页仪表盘新增（向后兼容，首页 banner 不消费）----
        "first_reading_date": first_reading_date,
        "total_days": lifetime["total_days"] + (1 if read_today else 0),
        "total_books": total_books,
        "streak": {"current": streak_current, "best": streak_best},
        "period": _period_sums(days, today),
        "near_finish": _near_finish_rows(db, reader.id),
    }
