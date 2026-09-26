#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Reader taste profile built from reading states, reading time, downloads and own ratings.
@author: PoxenStudio, 2026
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Protocol

from webserver.recommend.config import RecommendConfig
from webserver.recommend.context import RecommendContext
from webserver.recommend.features import BookFeatures, InvertedIndex, feature_keys
from webserver.recommend.scoring import Explanation, Reason

READ_STATE_READING = 1
READ_STATE_FINISHED = 2

W_FAVORITE = 3.0
W_FINISHED = 2.5
W_READING = 1.5
W_WANTS = 1.0
W_RATED = 1.5
W_DURATION_PER_HOUR = 0.3
DURATION_CAP_HOURS = 2.0
W_DOWNLOAD = 0.3
W_DISLIKE = 2.0

DIMENSION_WEIGHTS = {"author": 3.0, "series": 2.5, "tag": 1.0, "publisher": 0.5, "language": 0.5}
REASON_DIMENSIONS = ("author", "series", "tag")


@dataclass
class BookSignal:
    book_id: int
    favorite: bool = False
    wants: bool = False
    read_state: int = 0
    read_secs: int = 0
    downloaded: bool = False
    rating: Optional[int] = None
    last_active: Optional[datetime.datetime] = None


class ProfileSource(Protocol):
    def load(self, reader_id: int) -> List[BookSignal]:
        ...


@dataclass
class UserProfile:
    reader_id: int
    weights: Dict[int, float] = field(default_factory=dict)
    vectors: Dict[str, Dict[str, float]] = field(default_factory=dict)
    finished: FrozenSet[int] = frozenset()
    reading: FrozenSet[int] = frozenset()
    disliked: FrozenSet[int] = frozenset()
    wants: FrozenSet[int] = frozenset()
    series_progress: Dict[str, float] = field(default_factory=dict)
    cold: bool = True

    @property
    def excluded(self) -> FrozenSet[int]:
        return self.finished | self.reading | self.disliked


def book_weight(signal: BookSignal, now: datetime.datetime, config: RecommendConfig) -> float:
    base = max(
        W_FAVORITE * signal.favorite,
        W_FINISHED * (signal.read_state == READ_STATE_FINISHED),
        W_READING * (signal.read_state == READ_STATE_READING),
        W_WANTS * signal.wants,
    )
    if base == 0 and signal.rating is not None:
        base = W_RATED
    weight = base + W_DURATION_PER_HOUR * min(signal.read_secs / 3600, DURATION_CAP_HOURS) + W_DOWNLOAD * signal.downloaded
    if signal.last_active is not None:
        age = max(0.0, (now - signal.last_active).total_seconds() / 86400)
        weight *= 0.5 ** (age / config.half_life_days)
    if signal.rating is not None:
        m = (signal.rating - 6) / 4
        weight = -W_DISLIKE * abs(m) if signal.rating <= config.dislike_max_rating else weight * (1 + m)
    return weight


def build_profile(reader_id: int, signals: List[BookSignal], features: Dict[int, BookFeatures], now: datetime.datetime, config: RecommendConfig) -> UserProfile:
    weights = {s.book_id: book_weight(s, now, config) for s in signals}
    raw: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    series_progress: Dict[str, float] = {}
    for s in signals:
        book = features.get(s.book_id)
        w = weights[s.book_id]
        if book is None or w == 0:
            continue
        for dim, key, share in feature_keys(book):
            raw[dim][key] += w * share
        if book.series and w > 0 and (s.favorite or s.read_state == READ_STATE_FINISHED):
            series_progress[book.series] = max(series_progress.get(book.series, 0.0), book.series_index)

    vectors = {}
    for dim, values in raw.items():
        norm = sum(abs(v) for v in values.values())
        if norm > 0:
            vectors[dim] = {k: v / norm for k, v in values.items()}
    return UserProfile(
        reader_id=reader_id,
        weights=weights,
        vectors=vectors,
        finished=frozenset(s.book_id for s in signals if s.read_state == READ_STATE_FINISHED),
        reading=frozenset(s.book_id for s in signals if s.read_state == READ_STATE_READING),
        disliked=frozenset(s.book_id for s in signals if s.rating is not None and s.rating <= config.dislike_max_rating),
        wants=frozenset(s.book_id for s in signals if s.wants),
        series_progress=series_progress,
        cold=sum(w for w in weights.values() if w > 0) < config.cold_start_threshold,
    )


class SimilarityScorer:
    """Metadata similarity to the profile, clipped to [-1, 1] and mapped to [0, 1]; unmatched books score 0.5."""

    name = "sim"

    def __init__(self, profile: UserProfile, inverted: InvertedIndex):
        self.profile = profile
        self.total_weight = sum(DIMENSION_WEIGHTS.values())
        self.partial: Dict[int, float] = defaultdict(float)
        for dim, values in profile.vectors.items():
            for key, value in values.items():
                for book_id in inverted.books_with(dim, key):
                    self.partial[book_id] += DIMENSION_WEIGHTS[dim] * value

    def raw(self, book: BookFeatures) -> float:
        languages = self.profile.vectors.get("language", {})
        lang = sum(languages.get(lang, 0.0) for lang in book.languages)
        return (self.partial.get(book.book_id, 0.0) + DIMENSION_WEIGHTS["language"] * lang) / self.total_weight

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        return (max(-1.0, min(1.0, self.raw(book))) + 1) / 2

    def explain(self, book: BookFeatures, ctx: RecommendContext) -> Optional[Explanation]:
        best = None
        for dim, key, _ in feature_keys(book):
            if dim not in REASON_DIMENSIONS:
                continue
            value = DIMENSION_WEIGHTS[dim] * self.profile.vectors.get(dim, {}).get(key, 0.0) / self.total_weight
            if value > 0 and (best is None or value > best[1]):
                best = (Reason(dim, key), value)
        return best


class WantsScorer:
    name = "wants"

    def __init__(self, profile: UserProfile):
        self.profile = profile

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        return 1.0 if book.book_id in self.profile.wants else 0.0

    def explain(self, book: BookFeatures, ctx: RecommendContext) -> Optional[Explanation]:
        return (Reason("wants"), 1.0) if book.book_id in self.profile.wants else None


class SeriesNextScorer:
    name = "series_next"

    def __init__(self, profile: UserProfile):
        self.profile = profile

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        if not book.series or book.series not in self.profile.series_progress:
            return 0.0
        return 1.0 if book.series_index > self.profile.series_progress[book.series] else 0.0

    def explain(self, book: BookFeatures, ctx: RecommendContext) -> Optional[Explanation]:
        return (Reason("series_next", book.series or ""), 1.0) if self.score(book, ctx) else None
