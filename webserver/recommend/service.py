#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

from dataclasses import dataclass
from typing import Callable, List, Optional

from webserver.recommend.config import RecommendConfig
from webserver.recommend.context import RecommendContext
from webserver.recommend.features import FeatureIndex, FeatureSource
from webserver.recommend.recommenders import NewBooksRecommender, UniformRandomRecommender
from webserver.recommend.scoring import FreshnessScorer, WeightedScorer


@dataclass
class HomeResult:
    random_ids: List[int]
    new_ids: List[int]


class RecommendService:
    def __init__(self, source: FeatureSource, config_loader: Callable[[], RecommendConfig]):
        self.config_loader = config_loader
        self.index = FeatureIndex(source, config_loader().feature_ttl_seconds)

    def home(self, ctx: RecommendContext, n_random: int, n_new: int) -> Optional[HomeResult]:
        """None means the feature index is not ready yet; callers fall back to their legacy logic."""
        config = self.config_loader()
        self.index.ttl_seconds = config.feature_ttl_seconds
        features = self.index.snapshot()
        if features is None:
            return None
        new_scorer = WeightedScorer([(FreshnessScorer(config.new_half_life_days), 1.0)])
        new_ids = NewBooksRecommender(config, new_scorer).recommend(features, ctx, n_new)
        random_ids = UniformRandomRecommender().recommend(features, ctx.excluding(new_ids), n_random)
        return HomeResult(random_ids=random_ids, new_ids=new_ids)

    def invalidate_features(self) -> None:
        self.index.invalidate()
