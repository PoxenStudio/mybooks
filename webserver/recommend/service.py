#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from webserver.recommend.config import RecommendConfig
from webserver.recommend.context import RecommendContext, utc_now
from webserver.recommend.crowd import CrowdSnapshot, CrowdSource, CrowdView, build_crowd
from webserver.recommend.features import BookFeatures, FeatureIndex, FeatureSource
from webserver.recommend.recommenders import NewBooksRecommender, SampledRecommender
from webserver.recommend.scoring import (
    FreshnessScorer,
    ItemPopularityScorer,
    OverlayScorer,
    PopularityScorer,
    QualityScorer,
    Scorer,
    TrendScorer,
    WeightedScorer,
)
from webserver.recommend.snapshot import BackgroundSnapshot

DEFAULT_RATING = 6.0
SCORE_CACHE_SIZE = 8


@dataclass
class HomeResult:
    random_ids: List[int]
    new_ids: List[int]


class RecommendService:
    def __init__(self, source: FeatureSource, config_loader: Callable[[], RecommendConfig], crowd_source: Optional[CrowdSource] = None):
        self.config_loader = config_loader
        config = config_loader()
        self.index = FeatureIndex(source, config.feature_ttl_seconds)
        self.crowd: Optional[BackgroundSnapshot[CrowdSnapshot]] = None
        if crowd_source is not None:
            self.crowd = BackgroundSnapshot(lambda: self._load_crowd(crowd_source), config.crowd_ttl_seconds, "crowd")
        self._score_cache: Dict[tuple, Tuple[Dict[int, float], float]] = {}
        self._cache_lock = threading.Lock()

    def _load_crowd(self, crowd_source: CrowdSource) -> CrowdSnapshot:
        config = self.config_loader()
        return build_crowd(crowd_source.load(config), utc_now(), config)

    def home(self, ctx: RecommendContext, n_random: int, n_new: int) -> Optional[HomeResult]:
        """None means the feature index is not ready yet; callers fall back to their legacy logic."""
        config = self.config_loader()
        self.index.ttl_seconds = config.feature_ttl_seconds
        features = self.index.snapshot()
        if features is None:
            return None
        crowd = None
        if config.use_crowd and self.crowd is not None:
            self.crowd.ttl_seconds = config.crowd_ttl_seconds
            crowd = self.crowd.snapshot()
        view = CrowdView(crowd, ctx.reader_id, config)

        new_components: List[Tuple[Scorer, float]] = [(FreshnessScorer(config.new_half_life_days), config.w_new_fresh)]
        if view.available:
            new_components.append((TrendScorer(view), config.w_new_trend))
        new_ids = NewBooksRecommender(config, WeightedScorer(new_components)).recommend(features, ctx, n_new)

        random_scorer = self._random_scorer(features, crowd, view, ctx, config)
        random_ids = SampledRecommender(config, random_scorer).recommend(features, ctx.excluding(new_ids), n_random)
        return HomeResult(random_ids=random_ids, new_ids=new_ids)

    def _random_scorer(self, features: Dict[int, BookFeatures], crowd, view: CrowdView, ctx: RecommendContext, config: RecommendConfig) -> Scorer:
        guest = not ctx.reader_id
        crowd_version = self.crowd.version if crowd is not None and self.crowd is not None else 0
        key = (self.index.version, crowd_version, config, view.available, guest)
        base, default_rating = self._cached_scores(key, features, crowd, view.available, guest, config)
        own = self._compose(view, guest, default_rating, config)
        return OverlayScorer(base, own, view.own.keys())

    def _cached_scores(self, key: tuple, features, crowd, available: bool, guest: bool, config: RecommendConfig) -> Tuple[Dict[int, float], float]:
        with self._cache_lock:
            if key in self._score_cache:
                return self._score_cache[key]
        ratings = [b.rating for b in features.values() if b.rating > 0]
        default_rating = sum(ratings) / len(ratings) if ratings else DEFAULT_RATING
        shared_view = CrowdView(crowd, None, config)
        shared_view.available = available
        scorer = self._compose(shared_view, guest, default_rating, config)
        ctx = RecommendContext(reader_id=None)
        scores = {bid: scorer.score(book, ctx) for bid, book in features.items()}
        with self._cache_lock:
            if len(self._score_cache) >= SCORE_CACHE_SIZE:
                self._score_cache.clear()
            self._score_cache[key] = (scores, default_rating)
        return scores, default_rating

    @staticmethod
    def _compose(view: CrowdView, guest: bool, default_rating: float, config: RecommendConfig) -> Scorer:
        components: List[Tuple[Scorer, float]] = [(QualityScorer(view, default_rating), config.w_random_quality)]
        if view.available:
            components.append((PopularityScorer(view), config.w_random_popularity))
        elif guest:
            components.append((ItemPopularityScorer(view), config.w_random_popularity))
        return WeightedScorer(components)

    def invalidate_features(self) -> None:
        self.index.invalidate()
