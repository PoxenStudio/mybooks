#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Unit tests for the home page recommendation engine.
@author: PoxenStudio, 2026
"""

import datetime
import random
import time
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import models
from webserver.constants import CALIBRE_COLUMN_CATEGORY
from webserver.models import BookReadingStats, BookReview, Item, Reader, Reading, ReadingState
from webserver.recommend import BookFeatures, CalibreFeatureSource, FeatureIndex, RecommendConfig, RecommendContext, RecommendService, SqlCrowdSource, SqlProfileSource, home_seed
from webserver.recommend.coread import CoReadScorer, build_coread
from webserver.recommend.crowd import CrowdData, CrowdView, Engagement, build_crowd
from webserver.recommend.diversity import mmr_rerank
from webserver.recommend.features import InvertedIndex
from webserver.recommend.profile import BookSignal, SeriesNextScorer, SimilarityScorer, WantsScorer, book_weight, build_profile
from webserver.recommend.recommenders import NewBooksRecommender, SampledRecommender, weighted_sample
from webserver.recommend.scoring import FreshnessScorer, QualityScorer, Reason, WeightedScorer

NOW = datetime.datetime(2026, 9, 1)


def book(book_id, days_ago=None, authors=("A",), series=None, tags=(), category="", series_index=0.0):
    ts = NOW - datetime.timedelta(days=days_ago) if days_ago is not None else None
    return BookFeatures(
        book_id=book_id, title="t%d" % book_id, authors=tuple(authors), series=series, series_index=series_index, tags=tuple(tags), category=category, timestamp=ts
    )


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


class FixedScorer:
    name = "fixed"

    def __init__(self, scores):
        self.scores = scores

    def score(self, b, _ctx):
        return self.scores.get(b.book_id, 0.0)


class TestSampledRecommender(unittest.TestCase):
    def test_excludes_and_filters(self):
        features = library(*[book(i) for i in range(1, 11)])
        c = ctx(is_visible=lambda b: b.book_id % 2 == 0).excluding([2, 4])
        picked = SampledRecommender(RecommendConfig(), FixedScorer({})).recommend(features, c, 10)
        self.assertEqual(sorted(picked), [6, 8, 10])

    def test_same_seed_same_result(self):
        features = library(*[book(i, authors=(str(i),)) for i in range(1, 101)])
        rec = SampledRecommender(RecommendConfig(), FixedScorer({}))
        first = rec.recommend(features, ctx(rng=random.Random("1:42")), 10)
        self.assertEqual(first, rec.recommend(features, ctx(rng=random.Random("1:42")), 10))
        self.assertNotEqual(first, rec.recommend(features, ctx(rng=random.Random("1:43")), 10))
        self.assertEqual(len(set(first)), 10)

    def test_high_scores_are_favoured_but_not_exclusive(self):
        features = library(*[book(i, authors=(str(i),)) for i in range(1, 101)])
        rec = SampledRecommender(RecommendConfig(), FixedScorer({i: 1.0 for i in range(1, 11)}))
        picks = [i for seed in range(200) for i in rec.recommend(features, ctx(rng=random.Random(seed)), 8)]
        high = sum(1 for i in picks if i <= 10) / len(picks)
        self.assertGreater(high, 0.5)
        self.assertLess(high, 1.0)

    def test_weighted_sample_is_without_replacement(self):
        scored = [(book(i), 0.5) for i in range(20)]
        picked = weighted_sample(scored, 10, 0.35, random.Random(0))
        self.assertEqual(len({b.book_id for b, _ in picked}), 10)


def engagement(reader_id, book_id, **kwargs):
    return Engagement(reader_id=reader_id, book_id=book_id, **kwargs)


class TestCrowd(unittest.TestCase):
    config = RecommendConfig(crowd_min_users=2)

    def snapshot(self, *engagements, reviews=None, items=None):
        return build_crowd(CrowdData(list(engagements), reviews or {}, items or {}), NOW, self.config)

    def test_seconds_capped_per_reader(self):
        snap = self.snapshot(engagement(1, 1, read_secs=50000), engagement(2, 1, read_secs=100))
        self.assertEqual(snap.totals[1].secs, 10800 + 100)

    def test_own_activity_is_subtracted(self):
        snap = self.snapshot(engagement(1, 1, read_secs=60), engagement(2, 1, read_secs=60), engagement(3, 2, downloaded=True))
        self.assertEqual(CrowdView(snap, None, self.config).stats(1).readers, 2)
        self.assertEqual(CrowdView(snap, 1, self.config).stats(1).readers, 1)
        self.assertGreater(CrowdView(snap, 3, self.config).popularity(1), CrowdView(snap, 1, self.config).popularity(1))

    def test_needs_enough_other_readers(self):
        snap = self.snapshot(engagement(1, 1, read_secs=60), engagement(2, 1, read_secs=60))
        self.assertTrue(CrowdView(snap, None, self.config).available)
        self.assertFalse(CrowdView(snap, 1, self.config).available)
        self.assertFalse(CrowdView(None, None, self.config).available)

    def test_finish_rate_is_smoothed(self):
        lucky = [engagement(1, 1, read_secs=30, finished=True)]
        solid = [engagement(r, 2, read_secs=30, finished=r <= 9) for r in range(1, 11)]
        others = [engagement(r, 3 + r % 2, read_secs=6000) for r in range(1, 21)]
        view = CrowdView(self.snapshot(*lucky, *solid, *others), None, self.config)
        self.assertGreater(view.finish_rate(2), view.finish_rate(1))
        self.assertLess(view.finish_rate(1), 0.6)

    def test_deep_reading_bonus(self):
        view = CrowdView(self.snapshot(engagement(1, 1, read_secs=6000), engagement(2, 2, read_secs=60), engagement(3, 3, read_secs=600)), None, self.config)
        self.assertAlmostEqual(view.finish_rate(1) - view.finish_rate(2), 0.1)

    def test_trend_prefers_recent_activity(self):
        snap = self.snapshot(
            engagement(1, 1, read_secs=60, last_active=NOW - datetime.timedelta(days=1)),
            engagement(2, 2, read_secs=60, last_active=NOW - datetime.timedelta(days=60)),
        )
        view = CrowdView(snap, None, self.config)
        self.assertGreater(view.trend(1), 0.9)
        self.assertEqual(view.trend(2), 0.0)

    def test_quality_falls_back_to_reviews_without_crowd(self):
        view = CrowdView(self.snapshot(reviews={1: (2, 20)}), None, self.config)
        scorer = QualityScorer(view, default_rating=6.0)
        rated = BookFeatures(book_id=1, rating=6.0)
        unrated = BookFeatures(book_id=2)
        self.assertAlmostEqual(scorer.score(rated, ctx()), (20 + 3 * 6) / 5 / 10)
        self.assertAlmostEqual(scorer.score(unrated, ctx()), 0.6)


class TestSqlCrowdSource(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        models.Base.metadata.create_all(engine)
        self.session = scoped_session(sessionmaker(bind=engine))
        readers = []
        for rid, allow in ((1, True), (2, True), (3, False), (4, True)):
            r = Reader()
            r.id, r.username, r.name, r.allow_statistic = rid, "u%d" % rid, "u%d" % rid, allow
            readers.append(r)
        self.session.add_all(readers)
        t = datetime.datetime(2026, 8, 30, 10)
        for day in range(3):
            self.session.add(Reading(1, 100, "read", "web", t, duration=600, date=(t + datetime.timedelta(days=day)).date()))
        for _ in range(10):
            self.session.add(Reading(2, 100, "download", "web", t))
        self.session.add(Reading(3, 100, "read", "web", t, duration=600))
        self.session.add(Reading(4, 100, "read", "web", t, duration=600))
        state = ReadingState(100, 2)
        state.set_favorite(True)
        state.set_read_state(2)
        self.session.add(state)
        item = Item()
        item.book_id, item.count_visit, item.count_download = 100, 3, 4
        self.session.add(item)
        for rid, status, rating in ((1, BookReview.STATUS_APPROVED, 8), (2, BookReview.STATUS_HIDDEN, 2)):
            self.session.add(BookReview(reader_id=rid, book_id=100, rating=rating, status=status, create_time=t, update_time=t))
        self.session.commit()

    def tearDown(self):
        self.session.remove()

    def test_load(self):
        data = SqlCrowdSource(self.session).load(RecommendConfig(crowd_exclude_readers=(4,)))
        by_reader = {e.reader_id: e for e in data.engagements}
        self.assertEqual(set(by_reader), {1, 2})
        self.assertEqual(by_reader[1].read_secs, 1800)
        self.assertTrue(by_reader[2].downloaded and by_reader[2].favorite and by_reader[2].finished)
        self.assertEqual(data.reviews, {100: (1, 8)})
        self.assertEqual(data.item_counts, {100: 7})
        snap = build_crowd(data, NOW, RecommendConfig())
        self.assertEqual(snap.totals[100].dl_users, 1)

    def test_profile_source(self):
        t = datetime.datetime(2026, 8, 30, 10)
        self.session.add(BookReadingStats(reader_id=1, book_id=100, format="epub", total_seconds=5000, create_time=t, update_time=t))
        wants = ReadingState(200, 1)
        wants.set_wants(True)
        self.session.add(wants)
        self.session.commit()
        signals = {s.book_id: s for s in SqlProfileSource(self.session).load(1)}
        self.assertEqual(signals[100].read_secs, 5000)
        self.assertEqual(signals[100].rating, 8)
        self.assertTrue(signals[200].wants)
        signals = {s.book_id: s for s in SqlProfileSource(self.session).load(3)}
        self.assertEqual(signals, {})

    def test_crowd_engagement_carries_own_rating(self):
        data = SqlCrowdSource(self.session).load(RecommendConfig())
        self.assertEqual({e.reader_id: e.rating for e in data.engagements}[1], 8)

    def test_reviews_disabled(self):
        self.assertEqual(SqlCrowdSource(self.session).load(RecommendConfig(use_reviews=False)).reviews, {})


class TestSeed(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(home_seed(1, NOW, 30), home_seed(1, NOW + datetime.timedelta(minutes=29), 30))
        self.assertNotEqual(home_seed(1, NOW, 30), home_seed(1, NOW + datetime.timedelta(minutes=30), 30))
        self.assertNotEqual(home_seed(1, NOW, 30), home_seed(2, NOW, 30))
        self.assertEqual(home_seed(None, NOW, 30), home_seed(0, NOW, 30))


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
        self.assertIn(1, self.wait_built(index).books)
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


class StaticCrowd:
    def __init__(self, data):
        self.data = data

    def load(self, _config):
        return self.data


class TestRecommendService(unittest.TestCase):
    def service(self, features, crowd=None):
        service = RecommendService(StaticSource(features), RecommendConfig, StaticCrowd(crowd) if crowd else None)
        service.index.refresh()
        if service.crowd:
            service.crowd.refresh()
        return service

    def test_not_ready_returns_none(self):
        service = RecommendService(StaticSource({}), RecommendConfig)
        service.index.snapshot = lambda: None
        self.assertIsNone(service.home(ctx(), 3, 3))

    def test_random_and_new_are_disjoint(self):
        features = library(*[book(i, days_ago=i, authors=(str(i),)) for i in range(1, 21)])
        result = self.service(features).home(ctx(exclude_ids=frozenset({1})), 10, 5)
        self.assertEqual(result.new_ids, [2, 3, 4, 5, 6])
        self.assertEqual(len(result.random_ids), 10)
        self.assertFalse(set(result.random_ids) & (set(result.new_ids) | {1}))

    def test_crowd_favourite_shows_up_more(self):
        features = library(*[book(i, days_ago=400 + i, authors=(str(i),)) for i in range(1, 201)])
        crowd = CrowdData([engagement(r, 7, read_secs=3600, finished=True, favorite=True) for r in range(2, 6)])
        service = self.service(features, crowd)
        hits = sum(7 in service.home(ctx(reader_id=None, rng=random.Random(seed)), 8, 0).random_ids for seed in range(100))
        uniform_hits = 100 * 8 / 200
        self.assertGreater(hits, 3 * uniform_hits)

    def test_user_scores_exclude_own_activity(self):
        features = library(*[book(i, authors=(str(i),)) for i in range(1, 51)])
        crowd = CrowdData([engagement(1, 7, read_secs=3600, favorite=True), engagement(2, 8, read_secs=60), engagement(3, 8, read_secs=60)])
        service = self.service(features, crowd)
        c = ctx(reader_id=1)
        config, snap = service.config_loader(), service.crowd.snapshot()
        scorer = service._random_scorer(features, snap, CrowdView(snap, 1, config), None, c, config)
        guest = service._random_scorer(features, snap, CrowdView(snap, None, config), None, ctx(reader_id=None), config)
        self.assertLess(scorer.score(features[7], c), guest.score(features[7], c))
        self.assertAlmostEqual(scorer.score(features[8], c), guest.score(features[8], c))


def signal(book_id, days_ago=0, **kwargs):
    return BookSignal(book_id=book_id, last_active=NOW - datetime.timedelta(days=days_ago), **kwargs)


class TestProfile(unittest.TestCase):
    config = RecommendConfig()

    def weight(self, **kwargs):
        return book_weight(signal(1, **kwargs), NOW, self.config)

    def test_behaviour_order_and_max_not_sum(self):
        self.assertGreater(self.weight(favorite=True), self.weight(read_state=2))
        self.assertGreater(self.weight(read_state=2), self.weight(read_state=1))
        self.assertGreater(self.weight(read_state=1), self.weight(wants=True))
        self.assertEqual(self.weight(favorite=True, read_state=2), self.weight(favorite=True))

    def test_decay_and_rating(self):
        self.assertAlmostEqual(self.weight(favorite=True, days_ago=180), self.weight(favorite=True) / 2)
        self.assertAlmostEqual(self.weight(read_state=2, rating=10), 2 * self.weight(read_state=2))
        self.assertLess(self.weight(read_state=2, rating=2), 0)
        self.assertAlmostEqual(self.weight(rating=8), 1.5 * 1.5)

    def test_build(self):
        features = library(book(1, authors=("Liu",), series="S", series_index=1), book(2, authors=("Liu",)), book(3, authors=("Bad",)), book(4))
        signals = [signal(1, favorite=True), signal(2, read_state=1), signal(3, read_state=2, rating=2), signal(4, wants=True)]
        profile = build_profile(1, signals, features, NOW, self.config)
        self.assertFalse(profile.cold)
        self.assertEqual(profile.excluded, frozenset({2, 3}))
        self.assertEqual(profile.wants, frozenset({4}))
        self.assertEqual(profile.series_progress, {"S": 1})
        self.assertAlmostEqual(sum(abs(v) for v in profile.vectors["author"].values()), 1.0)
        self.assertLess(profile.vectors["author"]["Bad"], 0)

    def test_cold_start(self):
        profile = build_profile(1, [signal(1, wants=True)], library(book(1)), NOW, self.config)
        self.assertTrue(profile.cold)


class TestPersonalScorers(unittest.TestCase):
    def setUp(self):
        self.features = library(
            book(1, authors=("Liu",), tags=("scifi",)),
            book(2, authors=("Bad",)),
            book(10, authors=("Liu",)),
            book(11, authors=("Other",), tags=("scifi",)),
            book(12, authors=("Bad",)),
            book(13, authors=("Nobody",)),
            book(20, series="S", series_index=2),
            book(21, series="S", series_index=0.5),
        )
        signals = [signal(1, favorite=True), signal(2, read_state=2, rating=0), signal(99, wants=True)]
        self.profile = build_profile(1, signals, self.features, NOW, RecommendConfig())
        self.profile.series_progress["S"] = 1

    def test_similarity(self):
        sim = SimilarityScorer(self.profile, InvertedIndex(self.features))
        score = {i: sim.score(self.features[i], ctx()) for i in (10, 11, 12, 13)}
        self.assertGreater(score[10], score[11])
        self.assertGreater(score[11], score[13])
        self.assertEqual(score[13], 0.5)
        self.assertLess(score[12], 0.5)
        self.assertEqual(sim.explain(self.features[10], ctx())[0], Reason("author", "Liu"))
        self.assertIsNone(sim.explain(self.features[12], ctx()))

    def test_wants_and_series_next(self):
        self.assertEqual(WantsScorer(self.profile).explain(BookFeatures(book_id=99), ctx())[0], Reason("wants"))
        series = SeriesNextScorer(self.profile)
        self.assertEqual(series.score(self.features[20], ctx()), 1.0)
        self.assertEqual(series.score(self.features[21], ctx()), 0.0)


class TestCoRead(unittest.TestCase):
    config = RecommendConfig(crowd_min_users=2)

    def test_needs_two_co_readers(self):
        index = build_coread([engagement(1, 1, finished=True), engagement(1, 2, finished=True)], self.config)
        self.assertEqual(index.neighbors, {})
        index = build_coread([engagement(r, b, finished=True) for r in (1, 2) for b in (1, 2)], self.config)
        self.assertEqual([n for n, _, _ in index.neighbors[1]], [2])

    def test_heavy_readers_count_less_and_dislikes_are_ignored(self):
        light = [engagement(r, b, finished=True) for r in (1, 2) for b in (1, 2)]
        heavy = [engagement(r, b, downloaded=True) for r in (3, 4) for b in [1, *range(3, 200)]]
        disliked = [engagement(r, 500, finished=True, rating=2) for r in (1, 2)]
        index = build_coread(light + heavy + disliked, self.config)
        sims = {n: sim for n, sim, _ in index.neighbors[1]}
        self.assertEqual(index.neighbors[1][0][0], 2)
        self.assertGreater(sims[2], 2 * max(v for n, v in sims.items() if n != 2))
        self.assertNotIn(500, index.neighbors)
        self.assertLessEqual(len(index.neighbors[3]), self.config.co_neighbors)

    def test_scorer_reason_names_source_book(self):
        features = library(book(1), book(2), book(3))
        index = build_coread([engagement(r, b, finished=True) for r in (2, 3) for b in (1, 2)], self.config)
        profile = build_profile(1, [signal(1, favorite=True)], features, NOW, self.config)
        scorer = CoReadScorer(profile, index, features)
        self.assertEqual(scorer.score(features[2], ctx()), 1.0)
        self.assertEqual(scorer.explain(features[2], ctx())[0], Reason("co_read", "t1"))
        self.assertIsNone(scorer.explain(features[3], ctx()))


class StaticProfiles:
    def __init__(self, signals):
        self.signals = signals
        self.loads = 0

    def load(self, reader_id):
        self.loads += 1
        return self.signals.get(reader_id, [])


class TestPersonalizedService(unittest.TestCase):
    def setUp(self):
        self.features = library(*[book(i, days_ago=400 + i, authors=("a%d" % (i % 20),)) for i in range(1, 101)])
        self.profiles = StaticProfiles({1: [signal(i, read_state=2) for i in range(1, 60)] + [signal(60, favorite=True), signal(61, read_state=1)]})
        crowd = CrowdData([engagement(r, b, finished=True) for r in (2, 3) for b in (60, 70)])
        self.service = RecommendService(StaticSource(self.features), RecommendConfig, StaticCrowd(crowd), self.profiles)
        self.service.index.refresh()
        self.service.crowd.refresh()
        self.service.coread.refresh()

    def test_excludes_read_and_reading(self):
        result = self.service.home(ctx(reader_id=1), 20, 10)
        shown = set(result.random_ids) | set(result.new_ids)
        self.assertFalse(shown & (set(range(1, 60)) | {61}))

    def test_relaxes_finished_when_short(self):
        result = self.service.home(ctx(reader_id=1), 60, 0)
        self.assertEqual(len(result.random_ids), 60)
        self.assertNotIn(61, result.random_ids)

    def test_co_read_reason(self):
        reasons = [self.service.home(ctx(reader_id=1, rng=random.Random(seed)), 12, 0).reasons.get(70) for seed in range(30)]
        self.assertIn(Reason("co_read", "t60"), reasons)

    def test_invalidate_reader(self):
        self.service.home(ctx(reader_id=1), 5, 5)
        self.service.home(ctx(reader_id=1), 5, 5)
        self.assertEqual(self.profiles.loads, 1)
        self.service.invalidate_reader(1)
        self.service.home(ctx(reader_id=1), 5, 5)
        self.assertEqual(self.profiles.loads, 2)

    def test_guest_has_no_profile(self):
        self.service.home(ctx(reader_id=None), 5, 5)
        self.assertEqual(self.profiles.loads, 0)


if __name__ == "__main__":
    unittest.main()
