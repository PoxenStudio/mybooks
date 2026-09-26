#!/usr/bin/env python3
# -*- coding: UTF-8 -*-


import heapq
import math
from typing import Dict, List, Protocol, Sequence

from webserver.recommend.config import RecommendConfig
from webserver.recommend.context import RecommendContext
from webserver.recommend.diversity import Scored, mmr_rerank
from webserver.recommend.features import BookFeatures
from webserver.recommend.scoring import Scorer

NEW_WINDOW_STEPS_DAYS = (90, 180)
POOL_FACTOR = 10
SAMPLE_POOL_FACTOR = 3
MAX_POOL_EXTRA = 500


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
        picked = mmr_rerank(scored[:min(n * POOL_FACTOR, n + MAX_POOL_EXTRA)], n, self.config.diversity, self.config.max_per_author, self.config.max_per_series)
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


def weighted_sample(scored: Sequence[Scored], k: int, temperature: float, rng) -> List[Scored]:
    """Efraimidis-Spirakis sampling without replacement, weights exp(score / T), keys compared in log space."""
    t = max(temperature, 1e-3)
    keyed = ((math.log(1.0 - rng.random()) * math.exp(-score / t), i) for i, (_, score) in enumerate(scored))
    return [scored[i] for _, i in heapq.nlargest(k, keyed)]


class SampledRecommender:
    def __init__(self, config: RecommendConfig, scorer: Scorer):
        self.config = config
        self.scorer = scorer

    def recommend(self, features: Dict[int, BookFeatures], ctx: RecommendContext, n: int) -> List[int]:
        candidates = sorted((b for b in features.values() if ctx.accepts(b)), key=lambda b: b.book_id)
        if n <= 0 or not candidates:
            return []
        n_explore = int(round(n * self.config.explore_ratio)) if len(candidates) > n else 0
        scored = [(b, self.scorer.score(b, ctx)) for b in candidates]
        pool = weighted_sample(scored, (n - n_explore) * SAMPLE_POOL_FACTOR, self.config.temperature, ctx.rng)
        picked = [b.book_id for b in mmr_rerank(pool, n - n_explore, self.config.diversity, self.config.max_per_author, self.config.max_per_series)]
        chosen = set(picked)
        rest = [b.book_id for b in candidates if b.book_id not in chosen]
        picked += ctx.rng.sample(rest, min(n - len(picked), len(rest)))
        ctx.rng.shuffle(picked)
        return picked
