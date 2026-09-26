#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Crowd signals aggregated from other readers' reading, downloads, favorites and finishes.
@author: PoxenStudio, 2026
"""

import datetime
import math
import statistics
from dataclasses import dataclass, field, fields
from typing import Dict, Hashable, Iterable, Optional, Protocol, Tuple

from webserver.recommend.config import RecommendConfig

TREND_HALF_LIFE_DAYS = 7.0


@dataclass
class Engagement:
    reader_id: int
    book_id: int
    read_secs: int = 0
    downloaded: bool = False
    favorite: bool = False
    finished: bool = False
    started: bool = False
    rating: Optional[int] = None
    last_active: Optional[datetime.datetime] = None


@dataclass
class BookCrowd:
    readers: float = 0.0
    dl_users: float = 0.0
    favs: float = 0.0
    finishers: float = 0.0
    starters: float = 0.0
    reach: float = 0.0
    secs: float = 0.0
    trend: float = 0.0

    def add(self, other: "BookCrowd", sign: float = 1.0) -> "BookCrowd":
        for f in fields(self):
            setattr(self, f.name, getattr(self, f.name) + sign * getattr(other, f.name))
        return self

    def minus(self, other: Optional["BookCrowd"]) -> "BookCrowd":
        result = BookCrowd().add(self)
        return result.add(other, -1.0) if other else result

    def popularity_raw(self) -> float:
        return 1.0 * self.readers + 0.6 * self.dl_users + 0.8 * self.favs + 0.5 * math.log1p(self.secs / 3600)


@dataclass
class CrowdData:
    engagements: Iterable[Engagement]
    reviews: Dict[int, Tuple[int, int]] = field(default_factory=dict)
    item_counts: Dict[int, int] = field(default_factory=dict)


class CrowdSource(Protocol):
    def load(self, config: RecommendConfig) -> CrowdData:
        ...

    def fingerprint(self) -> Hashable:
        """Cheap value that changes whenever load() would return different data."""
        ...


@dataclass
class CrowdSnapshot:
    totals: Dict[int, BookCrowd]
    by_reader: Dict[int, Dict[int, BookCrowd]]
    reviews: Dict[int, Tuple[int, int]]
    item_counts: Dict[int, int]
    max_popularity_raw: float
    max_trend: float
    max_item_count: int
    p_finish: float
    p_favorite: float
    deep_secs: float


def contribution(e: Engagement, now: datetime.datetime, config: RecommendConfig) -> BookCrowd:
    recent = 0.0
    if e.last_active is not None:
        age = max(0.0, (now - e.last_active).total_seconds() / 86400)
        if age <= config.trend_days:
            recent = 0.5 ** (age / TREND_HALF_LIFE_DAYS)
    return BookCrowd(
        readers=1.0 if e.read_secs > 0 else 0.0,
        dl_users=1.0 if e.downloaded else 0.0,
        favs=1.0 if e.favorite else 0.0,
        finishers=1.0 if e.finished else 0.0,
        starters=1.0 if e.started or e.read_secs > 0 or e.finished else 0.0,
        reach=1.0,
        secs=float(min(e.read_secs, config.crowd_secs_cap)),
        trend=recent * (1.0 * (e.read_secs > 0) + 0.6 * e.downloaded + 0.8 * e.favorite),
    )


def build_crowd(data: CrowdData, now: datetime.datetime, config: RecommendConfig) -> CrowdSnapshot:
    totals: Dict[int, BookCrowd] = {}
    by_reader: Dict[int, Dict[int, BookCrowd]] = {}
    for e in data.engagements:
        c = contribution(e, now, config)
        by_reader.setdefault(e.reader_id, {})[e.book_id] = c
        totals.setdefault(e.book_id, BookCrowd()).add(c)

    all_books = BookCrowd()
    for c in totals.values():
        all_books.add(c)
    per_reader_secs = [c.secs / c.readers for c in totals.values() if c.readers > 0]
    return CrowdSnapshot(
        totals=totals,
        by_reader=by_reader,
        reviews=dict(data.reviews),
        item_counts=dict(data.item_counts),
        max_popularity_raw=max((c.popularity_raw() for c in totals.values()), default=0.0),
        max_trend=max((c.trend for c in totals.values()), default=0.0),
        max_item_count=max(data.item_counts.values(), default=0),
        p_finish=all_books.finishers / all_books.starters if all_books.starters else 0.3,
        p_favorite=all_books.favs / all_books.reach if all_books.reach else 0.1,
        deep_secs=statistics.median(per_reader_secs) if per_reader_secs else 0.0,
    )


class CrowdView:
    """Crowd statistics as seen by one reader: their own activity is subtracted."""

    def __init__(self, snapshot: Optional[CrowdSnapshot], reader_id: Optional[int], config: RecommendConfig):
        self.snapshot = snapshot
        self.config = config
        self.own: Dict[int, BookCrowd] = snapshot.by_reader.get(reader_id, {}) if snapshot and reader_id else {}
        others = len(snapshot.by_reader) - (1 if self.own else 0) if snapshot else 0
        self.available = others >= config.crowd_min_users

    def stats(self, book_id: int) -> BookCrowd:
        total = self.snapshot.totals.get(book_id) if self.snapshot else None
        return total.minus(self.own.get(book_id)) if total else BookCrowd()

    def popularity(self, book_id: int) -> float:
        return _log_norm(self.stats(book_id).popularity_raw(), self.snapshot.max_popularity_raw)

    def trend(self, book_id: int) -> float:
        return _log_norm(self.stats(book_id).trend, self.snapshot.max_trend)

    def item_popularity(self, book_id: int) -> float:
        if not self.snapshot:
            return 0.0
        return _log_norm(self.snapshot.item_counts.get(book_id, 0), self.snapshot.max_item_count)

    def finish_rate(self, book_id: int) -> float:
        s, m = self.stats(book_id), self.config.quality_prior_strength
        rate = (s.finishers + m * self.snapshot.p_finish) / (s.starters + m)
        if s.readers > 0 and self.snapshot.deep_secs > 0 and s.secs / s.readers >= self.snapshot.deep_secs:
            rate += 0.1
        return min(rate, 1.0)

    def favorite_rate(self, book_id: int) -> float:
        s = self.stats(book_id)
        return (s.favs + self.snapshot.p_favorite) / (s.reach + 1)

    def review(self, book_id: int) -> Tuple[int, int]:
        if not self.snapshot or not self.config.use_reviews:
            return 0, 0
        return self.snapshot.reviews.get(book_id, (0, 0))


def _log_norm(value: float, max_value: float) -> float:
    if max_value <= 0 or value <= 0:
        return 0.0
    return min(math.log1p(value) / math.log1p(max_value), 1.0)
