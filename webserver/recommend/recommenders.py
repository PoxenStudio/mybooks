#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
New-book and sampled random recommenders.
@author: PoxenStudio, 2026
"""

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


EXPLORE_ATTEMPTS_PER_BOOK = 50


class Recommender(Protocol):
    def pool(self, features: Dict[int, BookFeatures], ctx: RecommendContext, n: int) -> List[Scored]:
        """Expensive part: score the library and keep the best candidates for later picks."""
        ...

    def recommend(self, features: Dict[int, BookFeatures], ctx: RecommendContext, n: int) -> List[int]:
        ...


class NewBooksRecommender:
    def __init__(self, config: RecommendConfig, scorer: Scorer):
        self.config = config
        self.scorer = scorer

    def pool(self, features: Dict[int, BookFeatures], ctx: RecommendContext, n: int) -> List[Scored]:
        if n <= 0:
            return []
        window = self._window([b for b in features.values() if ctx.accepts(b)], ctx, n)
        scored = sorted(((b, self.scorer.score(b, ctx)) for b in window), key=lambda x: (x[1], x[0].book_id), reverse=True)
        return scored[:min(n * POOL_FACTOR, n + MAX_POOL_EXTRA)]

    def pick(self, pool: Sequence[Scored], ctx: RecommendContext, n: int) -> List[int]:
        if n <= 0:
            return []
        candidates = [(b, s) for b, s in pool if ctx.accepts(b)]
        picked = mmr_rerank(candidates, n, self.config.diversity, self.config.max_per_author, self.config.max_per_series)
        return [b.book_id for b in picked]

    def recommend(self, features: Dict[int, BookFeatures], ctx: RecommendContext, n: int) -> List[int]:
        return self.pick(self.pool(features, ctx, n), ctx, n)

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
    """Weighted sampling from the top-scored pool plus uniform exploration over the whole library."""

    def __init__(self, config: RecommendConfig, scorer: Scorer):
        self.config = config
        self.scorer = scorer

    def pool_size(self, n: int) -> int:
        return max(self.config.pool_size, n * SAMPLE_POOL_FACTOR * 2)

    def pool(self, features: Dict[int, BookFeatures], ctx: RecommendContext, n: int) -> List[Scored]:
        scored = ((b, self.scorer.score(b, ctx)) for b in features.values() if ctx.accepts(b))
        return heapq.nlargest(self.pool_size(n), scored, key=lambda x: (x[1], -x[0].book_id))

    def pick(self, pool: Sequence[Scored], features: Dict[int, BookFeatures], library_ids: Sequence[int], ctx: RecommendContext, n: int) -> List[int]:
        candidates = sorted(((b, s) for b, s in pool if ctx.accepts(b)), key=lambda x: x[0].book_id)
        if n <= 0 or not library_ids:
            return []
        n_explore = int(round(n * self.config.explore_ratio)) if len(library_ids) > n else 0
        sampled = weighted_sample(candidates, (n - n_explore) * SAMPLE_POOL_FACTOR, self.config.temperature, ctx.rng)
        picked = [b.book_id for b in mmr_rerank(sampled, n - n_explore, self.config.diversity, self.config.max_per_author, self.config.max_per_series)]
        chosen = set(picked)
        for _ in range((n - len(picked)) * EXPLORE_ATTEMPTS_PER_BOOK):
            if len(picked) >= n:
                break
            book_id = ctx.rng.choice(library_ids)
            if book_id not in chosen and ctx.accepts(features[book_id]):
                picked.append(book_id)
                chosen.add(book_id)
        if len(picked) < n:
            rest = [i for i in library_ids if i not in chosen and ctx.accepts(features[i])]
            picked += ctx.rng.sample(rest, min(n - len(picked), len(rest)))
        ctx.rng.shuffle(picked)
        return picked

    def recommend(self, features: Dict[int, BookFeatures], ctx: RecommendContext, n: int) -> List[int]:
        return self.pick(self.pool(features, ctx, n), features, sorted(features), ctx, n)
