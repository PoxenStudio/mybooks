#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import datetime
import random
import time
import unittest

from webserver.constants import CALIBRE_COLUMN_CATEGORY
from webserver.recommend import BookFeatures, CalibreFeatureSource, FeatureIndex, RecommendConfig, RecommendContext, RecommendService
from webserver.recommend.diversity import mmr_rerank
from webserver.recommend.recommenders import NewBooksRecommender, UniformRandomRecommender
from webserver.recommend.scoring import FreshnessScorer, WeightedScorer

NOW = datetime.datetime(2026, 9, 1)


def book(book_id, days_ago=None, authors=("A",), series=None, tags=(), category=""):
    ts = NOW - datetime.timedelta(days=days_ago) if days_ago is not None else None
    return BookFeatures(book_id=book_id, authors=tuple(authors), series=series, tags=tuple(tags), category=category, timestamp=ts)


def library(*books):
    return {b.book_id: b for b in books}


def ctx(**kwargs):
    kwargs.setdefault("reader_id", 1)
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("rng", random.Random(0))
    return RecommendContext(**kwargs)


class StaticSource:
    def __init__(self, features):
        self.features = features
        self.loads = 0

    def load(self):
        self.loads += 1
        return self.features


class TestScoring(unittest.TestCase):
    def test_freshness_half_life(self):
        scorer = FreshnessScorer(7)
        self.assertAlmostEqual(scorer.score(book(1, 0), ctx()), 1.0)
        self.assertAlmostEqual(scorer.score(book(1, 7), ctx()), 0.5)
        self.assertEqual(scorer.score(book(1, None), ctx()), 0.0)

    def test_weighted_scorer_renormalizes_and_drops_zero_weights(self):
        scorer = WeightedScorer([(FreshnessScorer(7), 3.0), (FreshnessScorer(1), 0.0)])
        self.assertEqual(len(scorer.components), 1)
        self.assertAlmostEqual(scorer.score(book(1, 7), ctx()), 0.5)


class TestDiversity(unittest.TestCase):
    def test_author_cap(self):
        scored = [(book(i, authors=("A",)), 1.0 - i * 0.01) for i in range(5)] + [(book(10, authors=("B",)), 0.1)]
        picked = mmr_rerank(scored, 3, 0.3, max_per_author=2, max_per_series=2)
        self.assertEqual([b.authors[0] for b in picked].count("A"), 2)
        self.assertIn(10, [b.book_id for b in picked])

    def test_series_cap(self):
        scored = [(book(i, authors=(str(i),), series="S"), 1.0) for i in range(4)] + [(book(9, authors=("X",)), 0.2)]
        picked = mmr_rerank(scored, 3, 0.0, max_per_author=2, max_per_series=2)
        self.assertEqual(sum(1 for b in picked if b.series == "S"), 2)

    def test_caps_relaxed_when_pool_too_small(self):
        scored = [(book(i, authors=("A",)), 1.0) for i in range(4)]
        self.assertEqual(len(mmr_rerank(scored, 4, 0.3, max_per_author=2, max_per_series=2)), 4)


class TestNewBooks(unittest.TestCase):
    def recommender(self, **overrides):
        config = RecommendConfig(**overrides)
        return NewBooksRecommender(config, WeightedScorer([(FreshnessScorer(config.new_half_life_days), 1.0)]))

    def test_prefers_newest_by_timestamp(self):
        features = library(*[book(i, days_ago=i, authors=(str(i),)) for i in range(1, 11)])
        self.assertEqual(self.recommender().recommend(features, ctx(), 3), [1, 2, 3])

    def test_timestamp_beats_id(self):
        features = library(book(100, days_ago=400, authors=("x",)), book(1, days_ago=1, authors=("y",)))
        self.assertEqual(self.recommender().recommend(features, ctx(), 1), [1])

    def test_book_added_today_is_in_window(self):
        books = [book(1, days_ago=0, authors=("x",)), book(2, days_ago=0, authors=("y",)), book(3, days_ago=50, authors=("z",))]
        self.assertEqual({b.book_id for b in self.recommender()._window(books, ctx(), 1)}, {1, 2})

    def test_window_expands_when_recent_books_are_few(self):
        features = library(book(1, days_ago=1, authors=("a",)), *[book(i, days_ago=100 + i, authors=(str(i),)) for i in range(2, 8)])
        self.assertEqual(len(self.recommender().recommend(features, ctx(), 3)), 3)

    def test_new_by_id(self):
        features = library(book(5, days_ago=900, authors=("a",)), book(1, days_ago=1, authors=("b",)))
        self.assertEqual(self.recommender(new_by="id").recommend(features, ctx(), 2)[0], 1)
        self.assertEqual(set(self.recommender(new_by="id").recommend(features, ctx(), 2)), {1, 5})

    def test_respects_visibility_and_exclusions(self):
        features = library(*[book(i, days_ago=i, authors=(str(i),)) for i in range(1, 7)])
        c = ctx(is_visible=lambda b: b.book_id != 1, exclude_ids=frozenset({2}))
        self.assertEqual(self.recommender().recommend(features, c, 2), [3, 4])

    def test_no_author_clusters(self):
        features = library(*[book(i, days_ago=i, authors=("same",)) for i in range(1, 6)], *[book(i, days_ago=i, authors=(str(i),)) for i in range(6, 9)])
        picked = self.recommender().recommend(features, ctx(), 4)
        self.assertLessEqual(sum(1 for i in picked if features[i].authors == ("same",)), 2)


class TestUniformRandom(unittest.TestCase):
    def test_excludes_and_filters(self):
        features = library(*[book(i) for i in range(1, 11)])
        c = ctx(is_visible=lambda b: b.book_id % 2 == 0).excluding([2, 4])
        picked = UniformRandomRecommender().recommend(features, c, 10)
        self.assertEqual(sorted(picked), [6, 8, 10])


class FakeCalibreCache:
    def __init__(self, fields):
        self.fields = fields

    def all_book_ids(self):
        return frozenset({1, 2})

    def all_field_for(self, name, ids, default_value=None):
        if name not in self.fields:
            raise KeyError(name)
        return {i: self.fields[name].get(i, default_value) for i in ids}


class TestFeatureSource(unittest.TestCase):
    def test_calibre_source_tolerates_missing_custom_column(self):
        aware = datetime.datetime(2026, 1, 1, 8, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
        cache = FakeCalibreCache({"authors": {1: ("A",)}, "tags": {1: ("t",)}, "timestamp": {1: aware}, "series": {}})
        features = CalibreFeatureSource(cache).load()
        self.assertEqual(features[1].authors, ("A",))
        self.assertEqual(features[1].category, "")
        self.assertEqual(features[1].timestamp, datetime.datetime(2026, 1, 1, 0))
        self.assertEqual(features[2].tags, ())

    def test_category_column(self):
        cache = FakeCalibreCache({CALIBRE_COLUMN_CATEGORY: {1: "小说"}})
        self.assertEqual(CalibreFeatureSource(cache).load()[1].category, "小说")


class TestFeatureIndex(unittest.TestCase):
    def wait_built(self, index):
        for _ in range(100):
            if index.snapshot() is not None:
                return index.snapshot()
            time.sleep(0.01)
        self.fail("feature index never built")

    def test_builds_in_background_then_serves_snapshot(self):
        source = StaticSource(library(book(1)))
        index = FeatureIndex(source, ttl_seconds=60)
        self.assertIn(1, self.wait_built(index))
        index.snapshot()
        self.assertEqual(source.loads, 1)

    def test_invalidate_triggers_rebuild(self):
        source = StaticSource(library(book(1)))
        index = FeatureIndex(source, ttl_seconds=60)
        index.refresh()
        index.invalidate()
        self.assertIsNotNone(index.snapshot())
        for _ in range(100):
            if source.loads == 2:
                break
            time.sleep(0.01)
        self.assertEqual(source.loads, 2)


class TestRecommendService(unittest.TestCase):
    def test_not_ready_returns_none(self):
        service = RecommendService(StaticSource({}), RecommendConfig)
        service.index.snapshot = lambda: None
        self.assertIsNone(service.home(ctx(), 3, 3))

    def test_random_and_new_are_disjoint(self):
        features = library(*[book(i, days_ago=i, authors=(str(i),)) for i in range(1, 21)])
        service = RecommendService(StaticSource(features), RecommendConfig)
        service.index.refresh()
        result = service.home(ctx(exclude_ids=frozenset({1})), 10, 5)
        self.assertEqual(result.new_ids, [2, 3, 4, 5, 6])
        self.assertEqual(len(result.random_ids), 10)
        self.assertFalse(set(result.random_ids) & (set(result.new_ids) | {1}))


if __name__ == "__main__":
    unittest.main()
