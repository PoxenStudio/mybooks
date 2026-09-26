#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Recommendation service orchestrating features, crowd data, profiles and recommenders.
@author: PoxenStudio, 2026
"""

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
class PersonalState:
    key: tuple
    expire_at: float
    profile: UserProfile
    sim: Optional[SimilarityScorer]
    co: Optional[CoReadScorer]


class RecommendService:
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
            self.crowd = BackgroundSnapshot(lambda: self._load_crowd(crowd_source), config.crowd_ttl_seconds, "crowd")
            self.coread = BackgroundSnapshot(lambda: self._load_coread(crowd_source), config.co_ttl_seconds, "coread")
        self.profile_source = profile_source
        self._score_cache: Dict[tuple, Tuple[Dict[int, float], float]] = {}
        self._personal: Dict[int, PersonalState] = {}
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
            self._personal.pop(reader_id, None)

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
        personal = self._personal_state(ctx.reader_id, library, coread, config)
        profile = personal.profile if personal else None
        personal_ctx = ctx.excluding(profile.excluded) if profile else ctx

        new_scorer = self._new_scorer(view, personal, config)
        new_ids = NewBooksRecommender(config, new_scorer).recommend(library.books, personal_ctx, n_new)

        random_scorer = self._random_scorer(library.books, crowd, view, personal, ctx, config)
        sampler = SampledRecommender(config, random_scorer)
        random_ids = sampler.recommend(library.books, personal_ctx.excluding(new_ids), n_random)
        if profile and len(random_ids) < n_random and profile.finished:
            relaxed = ctx.excluding(profile.reading | profile.disliked | frozenset(new_ids))
            random_ids = sampler.recommend(library.books, relaxed, n_random)

        reasons: Dict[int, Reason] = {}
        for ids, scorer in ((new_ids, new_scorer), (random_ids, random_scorer)):
            for book_id in ids:
                explanation = scorer.explain(library.books[book_id], ctx)
                if explanation:
                    reasons[book_id] = explanation[0]
        return HomeResult(random_ids=random_ids, new_ids=new_ids, reasons=reasons)

    def _personal_state(self, reader_id: Optional[int], library: Library, coread: Optional[CoReadIndex], config: RecommendConfig) -> Optional[PersonalState]:
        if not reader_id or self.profile_source is None:
            return None
        key = (self.index.version, self.coread.version if coread is not None and self.coread is not None else 0, config)
        with self._lock:
            state = self._personal.get(reader_id)
            if state and state.key == key and state.expire_at > time.monotonic():
                return state
        profile = build_profile(reader_id, self.profile_source.load(reader_id), library.books, utc_now(), config)
        co = CoReadScorer(profile, coread, library.books) if coread is not None else None
        state = PersonalState(
            key=key,
            expire_at=time.monotonic() + config.profile_ttl_seconds,
            profile=profile,
            sim=None if profile.cold else SimilarityScorer(profile, library.inverted),
            co=co if co else None,
        )
        with self._lock:
            self._personal[reader_id] = state
        return state

    @staticmethod
    def _personal_components(personal: Optional[PersonalState], w_sim: float, w_co: float) -> Components:
        components: Components = []
        if personal and personal.sim:
            components.append((personal.sim, w_sim))
        if personal and personal.co:
            components.append((personal.co, w_co))
        return components

    def _new_scorer(self, view: CrowdView, personal: Optional[PersonalState], config: RecommendConfig) -> Scorer:
        components: Components = [(FreshnessScorer(config.new_half_life_days), config.w_new_fresh), (SocialProofScorer(view), config.w_new_social_proof)]
        if view.available:
            components.append((TrendScorer(view), config.w_new_trend))
        components += self._personal_components(personal, config.w_new_sim, config.w_new_co)
        if personal and personal.profile.series_progress:
            components.append((SeriesNextScorer(personal.profile), config.w_new_series_next))
        return WeightedScorer(components)

    def _random_scorer(self, books: Dict[int, BookFeatures], crowd, view: CrowdView, personal: Optional[PersonalState], ctx: RecommendContext, config: RecommendConfig) -> Scorer:
        guest = not ctx.reader_id
        crowd_version = self.crowd.version if crowd is not None and self.crowd is not None else 0
        key = (self.index.version, crowd_version, config, view.available, guest)
        base, default_rating = self._cached_scores(key, books, crowd, view.available, guest, config)
        shared = self._shared_components(view, guest, default_rating, config)
        components: Components = [(OverlayScorer(base, WeightedScorer(shared), view.own.keys()), sum(w for _, w in shared))]
        components += self._personal_components(personal, config.w_random_sim, config.w_random_co)
        if personal and personal.profile.wants:
            components.append((WantsScorer(personal.profile), config.w_random_wants))
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
