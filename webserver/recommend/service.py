#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Recommendation service orchestrating features, crowd data, profiles and recommenders.
@author: PoxenStudio, 2026
"""

import itertools
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from webserver.recommend.config import RecommendConfig
from webserver.recommend.context import RecommendContext, utc_now
from webserver.recommend.coread import CoReadIndex, CoReadScorer, build_coread
from webserver.recommend.crowd import CrowdSnapshot, CrowdSource, CrowdView, build_crowd
from webserver.recommend.features import BookFeatures, FeatureIndex, FeatureSource, Library
from webserver.recommend.profile import ProfileSource, SeriesNextScorer, SimilarityScorer, UserProfile, WantsScorer, build_profile
from webserver.recommend.diversity import Scored
from webserver.recommend.recommenders import NewBooksRecommender, SampledRecommender
from webserver.recommend.scoring import (
    FreshnessScorer,
    ItemPopularityScorer,
    OverlayScorer,
    PopularityScorer,
    QualityScorer,
    Reason,
    Scorer,
    SocialProofScorer,
    TrendScorer,
    WeightedScorer,
)
from webserver.recommend.snapshot import BackgroundSnapshot

DEFAULT_RATING = 6.0
SCORE_CACHE_SIZE = 8
Components = List[Tuple[Scorer, float]]


@dataclass
class HomeResult:
    random_ids: List[int]
    new_ids: List[int]
    reasons: Dict[int, Reason] = field(default_factory=dict)


@dataclass
class ProfileState:
    key: tuple
    version: int
    expire_at: float
    profile: UserProfile


@dataclass
class PoolState:
    key: tuple
    new_scorer: Scorer
    random_scorer: Scorer
    new_pool: List[Scored]
    random_pool: List[Scored]


class RecommendService:
    """Scoring happens when a reader's candidate pool is (re)built; requests only pick from the pool.
    A stale pool keeps serving, filtered by the reader's fresh exclusions, while a worker thread rebuilds it."""

    def __init__(
        self,
        source: FeatureSource,
        config_loader: Callable[[], RecommendConfig],
        crowd_source: Optional[CrowdSource] = None,
        profile_source: Optional[ProfileSource] = None,
    ):
        self.config_loader = config_loader
        config = config_loader()
        self.index = FeatureIndex(source, config.feature_ttl_seconds)
        self.crowd: Optional[BackgroundSnapshot[CrowdSnapshot]] = None
        self.coread: Optional[BackgroundSnapshot[CoReadIndex]] = None
        if crowd_source is not None:
            def fingerprint():
                return crowd_source.fingerprint(), self.config_loader()

            self.crowd = BackgroundSnapshot(lambda: self._load_crowd(crowd_source), config.crowd_ttl_seconds, "crowd", fingerprint)
            self.coread = BackgroundSnapshot(lambda: self._load_coread(crowd_source), config.co_ttl_seconds, "coread", fingerprint)
        self.profile_source = profile_source
        self._score_cache: Dict[tuple, Tuple[Dict[int, float], float]] = {}
        self._profiles: Dict[int, ProfileState] = {}
        self._pools: Dict[int, PoolState] = {}
        self._profile_versions = itertools.count(1)
        self._pending: Dict[int, Callable[[], PoolState]] = {}
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _load_crowd(self, crowd_source: CrowdSource) -> CrowdSnapshot:
        config = self.config_loader()
        return build_crowd(crowd_source.load(config), utc_now(), config)

    def _load_coread(self, crowd_source: CrowdSource) -> CoReadIndex:
        config = self.config_loader()
        return build_coread(crowd_source.load(config).engagements, config)

    def invalidate_features(self) -> None:
        self.index.invalidate()

    def invalidate_reader(self, reader_id: int) -> None:
        with self._lock:
            self._profiles.pop(reader_id, None)

    def home(self, ctx: RecommendContext, n_random: int, n_new: int) -> Optional[HomeResult]:
        """None means the feature index is not ready yet; callers fall back to their legacy logic."""
        config = self.config_loader()
        self.index.ttl_seconds = config.feature_ttl_seconds
        library = self.index.snapshot()
        if library is None:
            return None
        crowd, coread = None, None
        if config.use_crowd and self.crowd is not None and self.coread is not None:
            self.crowd.ttl_seconds = config.crowd_ttl_seconds
            self.coread.ttl_seconds = config.co_ttl_seconds
            crowd, coread = self.crowd.snapshot(), self.coread.snapshot()
        view = CrowdView(crowd, ctx.reader_id, config)
        profile_state = self._profile_state(ctx.reader_id, library, config)
        profile = profile_state.profile if profile_state else None
        pool = self._pool_state(ctx, library, crowd, coread, view, profile_state, n_random, n_new, config)
        personal_ctx = ctx.excluding(profile.excluded) if profile else ctx

        new_ids = NewBooksRecommender(config, pool.new_scorer).pick(pool.new_pool, personal_ctx, n_new)
        sampler = SampledRecommender(config, pool.random_scorer)
        random_ids = sampler.pick(pool.random_pool, library.books, library.ids, personal_ctx.excluding(new_ids), n_random)
        if profile and len(random_ids) < n_random and profile.finished:
            relaxed = ctx.excluding(profile.reading | profile.disliked | frozenset(new_ids))
            random_ids = sampler.recommend(library.books, relaxed, n_random)

        reasons: Dict[int, Reason] = {}
        for ids, scorer in ((new_ids, pool.new_scorer), (random_ids, pool.random_scorer)):
            for book_id in ids:
                explanation = scorer.explain(library.books[book_id], ctx)
                if explanation:
                    reasons[book_id] = explanation[0]
        return HomeResult(random_ids=random_ids, new_ids=new_ids, reasons=reasons)

    def _profile_state(self, reader_id: Optional[int], library: Library, config: RecommendConfig) -> Optional[ProfileState]:
        if not reader_id or self.profile_source is None:
            return None
        key = (self.index.version, config)
        with self._lock:
            state = self._profiles.get(reader_id)
            if state and state.key == key and state.expire_at > time.monotonic():
                return state
        profile = build_profile(reader_id, self.profile_source.load(reader_id), library.books, utc_now(), config)
        state = ProfileState(key, next(self._profile_versions), time.monotonic() + config.profile_ttl_seconds, profile)
        with self._lock:
            self._profiles[reader_id] = state
        return state

    def _pool_state(self, ctx: RecommendContext, library: Library, crowd, coread, view: CrowdView, profile_state: Optional[ProfileState], n_random: int, n_new: int, config: RecommendConfig) -> PoolState:
        reader_key = ctx.reader_id or 0
        crowd_version = self.crowd.version if crowd is not None and self.crowd is not None else 0
        coread_version = self.coread.version if coread is not None and self.coread is not None else 0
        key = (self.index.version, crowd_version, coread_version, config, profile_state.version if profile_state else 0, n_random, n_new)
        profile = profile_state.profile if profile_state else None
        build_ctx = RecommendContext(ctx.reader_id, ctx.is_visible, profile.excluded if profile else frozenset(), ctx.now)

        def build() -> PoolState:
            return self._build_pool(key, reader_key, build_ctx, library, crowd, coread, view, profile, n_random, n_new, config)

        with self._lock:
            state = self._pools.get(reader_key)
        if state is None:
            return build()
        if state.key != key:
            self._schedule(reader_key, build)
        return state

    def _build_pool(self, key: tuple, reader_key: int, ctx: RecommendContext, library: Library, crowd, coread, view: CrowdView, profile: Optional[UserProfile], n_random: int, n_new: int, config: RecommendConfig) -> PoolState:
        sim = SimilarityScorer(profile, library.inverted) if profile and not profile.cold else None
        co = CoReadScorer(profile, coread, library.books) if profile and coread is not None else None
        personal = self._personal_components(sim, co if co else None, profile)
        new_scorer = self._new_scorer(view, personal, profile, config)
        random_scorer = self._random_scorer(library.books, crowd, view, personal, ctx, config)
        state = PoolState(
            key=key,
            new_scorer=new_scorer,
            random_scorer=random_scorer,
            new_pool=NewBooksRecommender(config, new_scorer).pool(library.books, ctx, n_new),
            random_pool=SampledRecommender(config, random_scorer).pool(library.books, ctx, n_random),
        )
        with self._lock:
            self._pools[reader_key] = state
        return state

    def _schedule(self, reader_key: int, build: Callable[[], PoolState]) -> None:
        with self._lock:
            self._pending[reader_key] = build
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._drain, name="recommend-pools", daemon=True)
            self._worker.start()

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    self._worker = None
                    return
                _, build = self._pending.popitem()
            try:
                build()
            except Exception:
                logging.exception("[recommend] pool rebuild failed")

    @staticmethod
    def _personal_components(sim: Optional[SimilarityScorer], co: Optional[CoReadScorer], profile: Optional[UserProfile]) -> Dict[str, Scorer]:
        components: Dict[str, Scorer] = {}
        if sim:
            components["sim"] = sim
        if co:
            components["co"] = co
        if profile and profile.wants:
            components["wants"] = WantsScorer(profile)
        if profile and profile.series_progress:
            components["series_next"] = SeriesNextScorer(profile)
        return components

    def _new_scorer(self, view: CrowdView, personal: Dict[str, Scorer], profile: Optional[UserProfile], config: RecommendConfig) -> Scorer:
        components: Components = [(FreshnessScorer(config.new_half_life_days), config.w_new_fresh), (SocialProofScorer(view), config.w_new_social_proof)]
        if view.available:
            components.append((TrendScorer(view), config.w_new_trend))
        weights = {"sim": config.w_new_sim, "co": config.w_new_co, "series_next": config.w_new_series_next}
        components += [(personal[name], w) for name, w in weights.items() if name in personal]
        return WeightedScorer(components)

    def _random_scorer(self, books: Dict[int, BookFeatures], crowd, view: CrowdView, personal: Dict[str, Scorer], ctx: RecommendContext, config: RecommendConfig) -> Scorer:
        guest = not ctx.reader_id
        crowd_version = self.crowd.version if crowd is not None and self.crowd is not None else 0
        key = (self.index.version, crowd_version, config, view.available, guest)
        base, default_rating = self._cached_scores(key, books, crowd, view.available, guest, config)
        shared = self._shared_components(view, guest, default_rating, config)
        components: Components = [(OverlayScorer(base, WeightedScorer(shared), view.own.keys()), sum(w for _, w in shared))]
        weights = {"sim": config.w_random_sim, "co": config.w_random_co, "wants": config.w_random_wants}
        components += [(personal[name], w) for name, w in weights.items() if name in personal]
        return WeightedScorer(components)

    def _cached_scores(self, key: tuple, books: Dict[int, BookFeatures], crowd, available: bool, guest: bool, config: RecommendConfig) -> Tuple[Dict[int, float], float]:
        with self._lock:
            if key in self._score_cache:
                return self._score_cache[key]
        ratings = [b.rating for b in books.values() if b.rating > 0]
        default_rating = sum(ratings) / len(ratings) if ratings else DEFAULT_RATING
        shared_view = CrowdView(crowd, None, config)
        shared_view.available = available
        scorer = WeightedScorer(self._shared_components(shared_view, guest, default_rating, config))
        ctx = RecommendContext(reader_id=None)
        scores = {bid: scorer.score(book, ctx) for bid, book in books.items()}
        with self._lock:
            if len(self._score_cache) >= SCORE_CACHE_SIZE:
                self._score_cache.clear()
            self._score_cache[key] = (scores, default_rating)
        return scores, default_rating

    @staticmethod
    def _shared_components(view: CrowdView, guest: bool, default_rating: float, config: RecommendConfig) -> Components:
        components: Components = [(QualityScorer(view, default_rating), config.w_random_quality)]
        if view.available:
            components.append((PopularityScorer(view), config.w_random_popularity))
        elif guest:
            components.append((ItemPopularityScorer(view), config.w_random_popularity))
        return components
