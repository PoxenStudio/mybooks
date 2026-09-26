#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

from dataclasses import dataclass
from typing import Mapping


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

    @classmethod
    def from_conf(cls, conf: Mapping) -> "RecommendConfig":
        return cls(
            enable=bool(conf.get("RECOMMEND_ENABLE", cls.enable)),
            feature_ttl_seconds=int(conf.get("RECOMMEND_FEATURE_TTL", cls.feature_ttl_seconds)),
            new_days=int(conf.get("RECOMMEND_NEW_DAYS", cls.new_days)),
            new_by=str(conf.get("RECOMMEND_NEW_BY", cls.new_by)),
            new_half_life_days=float(conf.get("RECOMMEND_NEW_HALF_LIFE_DAYS", cls.new_half_life_days)),
            diversity=float(conf.get("RECOMMEND_DIVERSITY", cls.diversity)),
            max_per_author=int(conf.get("RECOMMEND_MAX_PER_AUTHOR", cls.max_per_author)),
            max_per_series=int(conf.get("RECOMMEND_MAX_PER_SERIES", cls.max_per_series)),
        )
