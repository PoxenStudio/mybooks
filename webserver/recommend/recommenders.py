#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

from typing import Dict, List, Protocol, Sequence

from webserver.recommend.config import RecommendConfig
from webserver.recommend.context import RecommendContext
from webserver.recommend.diversity import mmr_rerank
from webserver.recommend.features import BookFeatures
from webserver.recommend.scoring import Scorer

NEW_WINDOW_STEPS_DAYS = (90, 180)
POOL_FACTOR = 10


class Recommender(Protocol):
    def recommend(self, features: Dict[int, BookFeatures], ctx: RecommendContext, n: int) -> List[int]:
        ...


class NewBooksRecommender:
    def __init__(self, config: RecommendConfig, scorer: Scorer):
        self.config = config
        self.scorer = scorer

    def recommend(self, features: Dict[int, BookFeatures], ctx: RecommendContext, n: int) -> List[int]:
        if n <= 0:
            return []
        window = self._window([b for b in features.values() if ctx.accepts(b)], ctx, n)
        scored = sorted(((b, self.scorer.score(b, ctx)) for b in window), key=lambda x: (x[1], x[0].book_id), reverse=True)
        picked = mmr_rerank(scored[:n * POOL_FACTOR], n, self.config.diversity, self.config.max_per_author, self.config.max_per_series)
        return [b.book_id for b in picked]

    def _window(self, candidates: Sequence[BookFeatures], ctx: RecommendContext, n: int) -> List[BookFeatures]:
        if self.config.new_by == "id":
            return sorted(candidates, key=lambda b: b.book_id, reverse=True)[:n * 4]
        ages = [(b, b.age_days(ctx.now)) for b in candidates]
        for days in (self.config.new_days, *NEW_WINDOW_STEPS_DAYS):
            window = [b for b, age in ages if age is not None and age <= days]
            if len(window) >= n * 2:
                return window
        return sorted(candidates, key=lambda b: (b.timestamp is not None, b.timestamp, b.book_id), reverse=True)[:n * 4]


class UniformRandomRecommender:
    def recommend(self, features: Dict[int, BookFeatures], ctx: RecommendContext, n: int) -> List[int]:
        ids = sorted(b.book_id for b in features.values() if ctx.accepts(b))
        return ctx.rng.sample(ids, min(n, len(ids)))
