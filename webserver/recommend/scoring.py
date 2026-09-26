#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Scorers that rate a candidate book in [0, 1] and explain their contribution.
@author: PoxenStudio, 2026
"""

from dataclasses import dataclass
from typing import Dict, Optional, Protocol, Sequence, Tuple

from webserver.recommend.context import RecommendContext
from webserver.recommend.crowd import CrowdView
from webserver.recommend.features import BookFeatures

COUNT_BUCKETS = (100, 50, 20, 10, 5, 2)
GOOD_REVIEW_AVG = 8


@dataclass(frozen=True)
class Reason:
    type: str
    value: str = ""


Explanation = Tuple[Reason, float]


def count_bucket(n: float) -> str:
    for threshold in COUNT_BUCKETS:
        if n >= threshold:
            return "%d+" % threshold
    return ""


class Scorer(Protocol):
    name: str

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        """Return a value in [0, 1]."""
        ...

    def explain(self, book: BookFeatures, ctx: RecommendContext) -> Optional[Explanation]:
        """Return the reason this scorer favours the book and its evidence strength in [0, 1]."""
        ...


class FreshnessScorer:
    name = "fresh"

    def __init__(self, half_life_days: float):
        self.half_life_days = half_life_days

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        age = book.age_days(ctx.now)
        if age is None:
            return 0.0
        return 0.5 ** (age / self.half_life_days)

    def explain(self, book: BookFeatures, ctx: RecommendContext) -> Optional[Explanation]:
        return None


class WeightedScorer:
    name = "weighted"

    def __init__(self, components: Sequence[Tuple[Scorer, float]]):
        self.components = [(s, w) for s, w in components if w > 0]
        total = sum(w for _, w in self.components) or 1.0
        self.components = [(s, w / total) for s, w in self.components]

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        return sum(w * s.score(book, ctx) for s, w in self.components)

    def explain(self, book: BookFeatures, ctx: RecommendContext) -> Optional[Explanation]:
        best = None
        for scorer, weight in self.components:
            explanation = scorer.explain(book, ctx)
            if explanation and (best is None or weight * explanation[1] > best[1]):
                best = (explanation[0], weight * explanation[1])
        return best


class PopularityScorer:
    name = "popular"

    def __init__(self, view: CrowdView):
        self.view = view

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        return 0.7 * self.view.popularity(book.book_id) + 0.3 * self.view.trend(book.book_id)

    def explain(self, book: BookFeatures, ctx: RecommendContext) -> Optional[Explanation]:
        reach = self.view.stats(book.book_id).reach
        if reach < self.view.config.crowd_min_users:
            return None
        return Reason("popular", count_bucket(reach)), self.score(book, ctx)


class ItemPopularityScorer:
    name = "popular"

    def __init__(self, view: CrowdView):
        self.view = view

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        return self.view.item_popularity(book.book_id)

    def explain(self, book: BookFeatures, ctx: RecommendContext) -> Optional[Explanation]:
        return None


class TrendScorer:
    name = "trending"

    def __init__(self, view: CrowdView):
        self.view = view

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        return self.view.trend(book.book_id)

    def explain(self, book: BookFeatures, ctx: RecommendContext) -> Optional[Explanation]:
        stats = self.view.stats(book.book_id)
        if stats.trend <= 0 or stats.reach < self.view.config.crowd_min_users:
            return None
        return Reason("trending", count_bucket(stats.reach)), self.score(book, ctx)


class QualityScorer:
    """Implicit quality from other readers, blended with Bayesian-averaged reviews over the Calibre rating."""

    name = "quality"

    def __init__(self, view: CrowdView, default_rating: float):
        self.view = view
        self.default_rating = default_rating

    def review_quality(self, book: BookFeatures) -> float:
        n, total = self.view.review(book.book_id)
        m = self.view.config.quality_prior_strength
        prior = book.rating or self.default_rating
        return (total + m * prior) / (n + m) / 10

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        review = self.review_quality(book)
        if not self.view.available:
            return review
        return 0.6 * self.view.finish_rate(book.book_id) + 0.2 * self.view.favorite_rate(book.book_id) + 0.2 * review

    def explain(self, book: BookFeatures, ctx: RecommendContext) -> Optional[Explanation]:
        return None


class SocialProofScorer:
    """1 when others already recommend the book: a good review, or enough other readers finished it."""

    name = "social_proof"

    def __init__(self, view: CrowdView):
        self.view = view

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        return 1.0 if self.explain(book, ctx) else 0.0

    def explain(self, book: BookFeatures, ctx: RecommendContext) -> Optional[Explanation]:
        n, total = self.view.review(book.book_id)
        if n >= 1 and total / n >= GOOD_REVIEW_AVG:
            return Reason("reviewed", str(n)), 1.0
        if self.view.available:
            finishers = self.view.stats(book.book_id).finishers
            if finishers >= max(2, self.view.config.crowd_min_users):
                return Reason("finished_by_others", count_bucket(finishers)), 1.0
        return None


class OverlayScorer:
    """Precomputed shared scores, recomputed only for the books in `own_ids`."""

    name = "overlay"

    def __init__(self, base: Dict[int, float], scorer: Scorer, own_ids):
        self.base = base
        self.scorer = scorer
        self.own_ids = own_ids

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        if book.book_id in self.own_ids or book.book_id not in self.base:
            return self.scorer.score(book, ctx)
        return self.base[book.book_id]

    def explain(self, book: BookFeatures, ctx: RecommendContext) -> Optional[Explanation]:
        return self.scorer.explain(book, ctx)
