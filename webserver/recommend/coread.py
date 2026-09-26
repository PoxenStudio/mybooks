#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Item-item co-reading neighbors ("readers of this book also read") and the matching scorer.
@author: PoxenStudio, 2026
"""

import datetime
import heapq
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from webserver.recommend.config import RecommendConfig
from webserver.recommend.context import RecommendContext
from webserver.recommend.crowd import Engagement
from webserver.recommend.features import BookFeatures
from webserver.recommend.profile import UserProfile
from webserver.recommend.scoring import Explanation, Reason

SIMILARITY_SHRINK = 2.0
Neighbor = Tuple[int, float, int]


@dataclass
class CoReadIndex:
    neighbors: Dict[int, List[Neighbor]] = field(default_factory=dict)


def engagement_strength(e: Engagement, config: RecommendConfig) -> float:
    if e.rating is not None and e.rating <= config.dislike_max_rating:
        return 0.0
    if e.finished or e.favorite:
        return 1.0
    if e.read_secs >= config.co_min_secs:
        return 0.7
    return 0.4 if e.downloaded else 0.0


def build_coread(engagements: Iterable[Engagement], config: RecommendConfig) -> CoReadIndex:
    by_reader: Dict[int, List[Tuple[int, float, datetime.datetime]]] = defaultdict(list)
    for e in engagements:
        s = engagement_strength(e, config)
        if s > 0:
            by_reader[e.reader_id].append((e.book_id, s, e.last_active or datetime.datetime.min))

    norms: Dict[int, float] = defaultdict(float)
    co: Dict[Tuple[int, int], float] = defaultdict(float)
    co_users: Dict[Tuple[int, int], int] = defaultdict(int)
    for items in by_reader.values():
        items = sorted(items, key=lambda x: x[2], reverse=True)[:config.co_max_books_per_reader]
        damping = 1.0 / math.log2(2 + len(items))
        for i, (a, sa, _) in enumerate(items):
            norms[a] += sa * damping
            for b, sb, _ in items[i + 1:]:
                key = (a, b) if a < b else (b, a)
                co[key] += min(sa, sb) * damping
                co_users[key] += 1

    candidates: Dict[int, List[Neighbor]] = defaultdict(list)
    for (a, b), value in co.items():
        c = co_users[(a, b)]
        if c < config.crowd_min_users:
            continue
        sim = value / math.sqrt(norms[a] * norms[b]) * c / (c + SIMILARITY_SHRINK)
        candidates[a].append((b, sim, c))
        candidates[b].append((a, sim, c))
    return CoReadIndex({book: heapq.nlargest(config.co_neighbors, items, key=lambda x: x[1]) for book, items in candidates.items()})


class CoReadScorer:
    name = "co_read"

    def __init__(self, profile: UserProfile, index: CoReadIndex, features: Dict[int, BookFeatures]):
        self.features = features
        totals: Dict[int, float] = defaultdict(float)
        sources: Dict[int, Tuple[int, float]] = {}
        for book_id, weight in profile.weights.items():
            if weight <= 0:
                continue
            for neighbor, sim, _ in index.neighbors.get(book_id, ()):
                contribution = weight * sim
                totals[neighbor] += contribution
                if neighbor not in sources or contribution > sources[neighbor][1]:
                    sources[neighbor] = (book_id, contribution)
        top = max(totals.values(), default=0.0)
        self.scores = {b: v / top for b, v in totals.items()} if top > 0 else {}
        self.sources = {b: src for b, (src, _) in sources.items()}

    def __bool__(self) -> bool:
        return bool(self.scores)

    def score(self, book: BookFeatures, ctx: RecommendContext) -> float:
        return self.scores.get(book.book_id, 0.0)

    def explain(self, book: BookFeatures, ctx: RecommendContext) -> Optional[Explanation]:
        value = self.scores.get(book.book_id, 0.0)
        source = self.features.get(self.sources.get(book.book_id, -1))
        if value <= 0 or source is None:
            return None
        return Reason("co_read", source.title), value
