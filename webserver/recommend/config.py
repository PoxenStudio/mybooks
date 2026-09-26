#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

from dataclasses import dataclass
from typing import Mapping, Tuple

DEFAULT_WEIGHTS = {
    "random_popularity": 0.15,
    "random_quality": 0.10,
    "new_fresh": 0.25,
    "new_trend": 0.10,
}


@dataclass(frozen=True)
class RecommendConfig:
    enable: bool = True
    feature_ttl_seconds: int = 300
    new_days: int = 30
    new_by: str = "timestamp"
    new_half_life_days: float = 7.0
    diversity: float = 0.3
    max_per_author: int = 2
    max_per_series: int = 2
    use_crowd: bool = True
    crowd_ttl_seconds: int = 600
    crowd_min_users: int = 2
    crowd_secs_cap: int = 10800
    crowd_exclude_readers: Tuple[int, ...] = ()
    trend_days: int = 30
    use_reviews: bool = True
    quality_prior_strength: float = 3.0
    explore_ratio: float = 0.25
    temperature: float = 0.35
    seed_bucket_minutes: int = 30
    w_random_popularity: float = DEFAULT_WEIGHTS["random_popularity"]
    w_random_quality: float = DEFAULT_WEIGHTS["random_quality"]
    w_new_fresh: float = DEFAULT_WEIGHTS["new_fresh"]
    w_new_trend: float = DEFAULT_WEIGHTS["new_trend"]

    @classmethod
    def from_conf(cls, conf: Mapping) -> "RecommendConfig":
        weights = {**DEFAULT_WEIGHTS, **(conf.get("RECOMMEND_WEIGHTS") or {})}
        return cls(
            enable=bool(conf.get("RECOMMEND_ENABLE", cls.enable)),
            feature_ttl_seconds=int(conf.get("RECOMMEND_FEATURE_TTL", cls.feature_ttl_seconds)),
            new_days=int(conf.get("RECOMMEND_NEW_DAYS", cls.new_days)),
            new_by=str(conf.get("RECOMMEND_NEW_BY", cls.new_by)),
            new_half_life_days=float(conf.get("RECOMMEND_NEW_HALF_LIFE_DAYS", cls.new_half_life_days)),
            diversity=float(conf.get("RECOMMEND_DIVERSITY", cls.diversity)),
            max_per_author=int(conf.get("RECOMMEND_MAX_PER_AUTHOR", cls.max_per_author)),
            max_per_series=int(conf.get("RECOMMEND_MAX_PER_SERIES", cls.max_per_series)),
            use_crowd=bool(conf.get("RECOMMEND_USE_CROWD", cls.use_crowd)),
            crowd_ttl_seconds=int(conf.get("RECOMMEND_CROWD_TTL", cls.crowd_ttl_seconds)),
            crowd_min_users=int(conf.get("RECOMMEND_CROWD_MIN_USERS", cls.crowd_min_users)),
            crowd_secs_cap=int(conf.get("RECOMMEND_CROWD_SECS_CAP", cls.crowd_secs_cap)),
            crowd_exclude_readers=tuple(int(i) for i in conf.get("RECOMMEND_CROWD_EXCLUDE_READERS") or ()),
            trend_days=int(conf.get("RECOMMEND_TREND_DAYS", cls.trend_days)),
            use_reviews=bool(conf.get("RECOMMEND_USE_REVIEWS", cls.use_reviews)) and bool(conf.get("ENABLE_BOOK_REVIEW", True)),
            quality_prior_strength=float(conf.get("RECOMMEND_QUALITY_PRIOR_STRENGTH", cls.quality_prior_strength)),
            explore_ratio=float(conf.get("RECOMMEND_EXPLORE_RATIO", cls.explore_ratio)),
            temperature=float(conf.get("RECOMMEND_TEMPERATURE", cls.temperature)),
            seed_bucket_minutes=int(conf.get("RECOMMEND_SEED_BUCKET_MINUTES", cls.seed_bucket_minutes)),
            w_random_popularity=float(weights["random_popularity"]),
            w_random_quality=float(weights["random_quality"]),
            w_new_fresh=float(weights["new_fresh"]),
            w_new_trend=float(weights["new_trend"]),
        )
