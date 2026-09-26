#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

from typing import Dict, Protocol, Sequence, Tuple

from webserver.recommend.context import RecommendContext
from webserver.recommend.crowd import CrowdView
from webserver.recommend.features import BookFeatures


class Scorer(Protocol):
    name: str

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        """Return a value in [0, 1]."""
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


class WeightedScorer:
    name = "weighted"

    def __init__(self, components: Sequence[Tuple[Scorer, float]]):
        self.components = [(s, w) for s, w in components if w > 0]
        total = sum(w for _, w in self.components) or 1.0
        self.components = [(s, w / total) for s, w in self.components]

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        return sum(w * s.score(book, ctx) for s, w in self.components)


class PopularityScorer:
    name = "popular"

    def __init__(self, view: CrowdView):
        self.view = view

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        return 0.7 * self.view.popularity(book.book_id) + 0.3 * self.view.trend(book.book_id)


class ItemPopularityScorer:
    name = "popular"

    def __init__(self, view: CrowdView):
        self.view = view

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        return self.view.item_popularity(book.book_id)


class TrendScorer:
    name = "trending"

    def __init__(self, view: CrowdView):
        self.view = view

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        return self.view.trend(book.book_id)


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
