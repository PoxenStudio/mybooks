#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

from typing import Protocol, Sequence, Tuple

from webserver.recommend.context import RecommendContext
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
