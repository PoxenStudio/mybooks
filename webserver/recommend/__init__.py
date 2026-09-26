#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Home page recommendation engine, see document/Recommendation_Engine_Design.md.
@author: PoxenStudio, 2026
"""

from webserver.recommend.config import RecommendConfig
from webserver.recommend.context import RecommendContext, home_seed, utc_now
from webserver.recommend.features import BookFeatures, CalibreFeatureSource, FeatureIndex
from webserver.recommend.scoring import Reason
from webserver.recommend.service import HomeResult, RecommendService
from webserver.recommend.sql_source import SqlCrowdSource, SqlProfileSource

__all__ = ["BookFeatures", "CalibreFeatureSource", "FeatureIndex", "HomeResult", "RecommendConfig", "RecommendContext", "Reason", "RecommendService", "SqlCrowdSource", "SqlProfileSource", "home_seed", "utc_now"]
