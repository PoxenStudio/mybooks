#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from tests.test_main import BID_EPUB, TestWithUserLogin, get_db, setUpModule as init, main
from webserver import models
from webserver.models import BookReview, Reader
from webserver.services.book_review_service import BookReviewService


def setUpModule():
    init()


class TestBookReviewService(unittest.TestCase):
    """Unit tests against BookReviewService directly, on an isolated in-memory DB
    (see tests/test_reading_stats_flush.py for the same pattern)."""

    def setUp(self):
        self._shared_session = get_db()
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)

        r1, r2 = Reader(), Reader()
        r1.id, r1.username, r1.name = 1, "u1", "Alice"
        r2.id, r2.username, r2.name = 2, "u2", "Bob"
        self.session.add_all([r1, r2])
        self.session.commit()

        BookReviewService.invalidate_stats(100)

    def tearDown(self):
        self.session.remove()
        models.bind_session(self._shared_session)

    def test_upsert_creates_then_edits_same_row(self):
        row = BookReviewService.upsert(self.session, book_id=100, reader_id=1, rating=8, comment="great")
        self.assertEqual(row.status, BookReview.STATUS_APPROVED)

        edited = BookReviewService.upsert(self.session, book_id=100, reader_id=1, rating=10, comment="even better")
        self.assertEqual(edited.id, row.id)
        self.assertEqual(edited.rating, 10)
        self.assertEqual(self.session.query(BookReview).filter_by(book_id=100, reader_id=1).count(), 1)

    def test_upsert_requires_approval_when_enabled(self):
        main.CONF["REVIEW_REQUIRES_APPROVAL"] = True
        try:
            row = BookReviewService.upsert(self.session, book_id=100, reader_id=1, rating=8, comment="")
            self.assertEqual(row.status, BookReview.STATUS_PENDING)
        finally:
            main.CONF["REVIEW_REQUIRES_APPROVAL"] = False

    def test_empty_comment_allowed(self):
        row = BookReviewService.upsert(self.session, book_id=100, reader_id=1, rating=5, comment="")
        self.assertEqual(row.comment, "")

    def test_soft_delete_then_recreate_reuses_row(self):
        row = BookReviewService.upsert(self.session, book_id=100, reader_id=1, rating=8, comment="x")
        self.assertTrue(BookReviewService.soft_delete(self.session, 100, 1))
        self.assertIsNone(BookReviewService.get_own(self.session, 100, 1))

        recreated = BookReviewService.upsert(self.session, book_id=100, reader_id=1, rating=3, comment="y")
        self.assertEqual(recreated.id, row.id)  # 复用同一行，不撞唯一约束
        self.assertIsNone(recreated.deleted_at)

    def test_double_delete_is_a_noop(self):
        BookReviewService.upsert(self.session, book_id=100, reader_id=1, rating=8, comment="x")
        self.assertTrue(BookReviewService.soft_delete(self.session, 100, 1))
        self.assertFalse(BookReviewService.soft_delete(self.session, 100, 1))

    def test_moderate_hide_then_restore_round_trips_status(self):
        row = BookReviewService.upsert(self.session, book_id=100, reader_id=1, rating=8, comment="x")
        hidden = BookReviewService.moderate(self.session, row.id, "hide")
        self.assertEqual(hidden.status, BookReview.STATUS_HIDDEN)
        self.assertEqual(hidden.prev_status, BookReview.STATUS_APPROVED)

        restored = BookReviewService.moderate(self.session, row.id, "restore")
        self.assertEqual(restored.status, BookReview.STATUS_APPROVED)
        self.assertIsNone(restored.prev_status)

    def test_editing_a_hidden_review_resubmits_it(self):
        row = BookReviewService.upsert(self.session, book_id=100, reader_id=1, rating=8, comment="x")
        BookReviewService.moderate(self.session, row.id, "hide")
        edited = BookReviewService.upsert(self.session, book_id=100, reader_id=1, rating=9, comment="y")
        self.assertEqual(edited.status, BookReview.STATUS_APPROVED)  # 重新走审核判定，不再卡在 hidden

    def test_list_for_book_hides_others_pending_but_shows_own(self):
        main.CONF["REVIEW_REQUIRES_APPROVAL"] = True
        try:
            BookReviewService.upsert(self.session, book_id=100, reader_id=1, rating=8, comment="mine")
            BookReviewService.upsert(self.session, book_id=100, reader_id=2, rating=5, comment="theirs")

            rows, total = BookReviewService.list_for_book(self.session, 100, viewer_reader_id=1)
            self.assertEqual(total, 1)
            self.assertEqual([r.reader_id for r in rows], [1])

            rows_admin_view, total_admin = BookReviewService.list_for_book(self.session, 100, viewer_reader_id=None)
            self.assertEqual(total_admin, 0)  # 未登录：两条都是 pending，都看不到
        finally:
            main.CONF["REVIEW_REQUIRES_APPROVAL"] = False

    def test_list_for_book_puts_current_user_first(self):
        BookReviewService.upsert(self.session, book_id=100, reader_id=2, rating=5, comment="theirs")
        BookReviewService.upsert(self.session, book_id=100, reader_id=1, rating=8, comment="mine")
        rows, _ = BookReviewService.list_for_book(self.session, 100, viewer_reader_id=2)
        self.assertEqual(rows[0].reader_id, 2)

    def test_stats_counts_approved_reviews_and_caches(self):
        BookReviewService.upsert(self.session, book_id=100, reader_id=1, rating=8, comment="")
        BookReviewService.upsert(self.session, book_id=100, reader_id=2, rating=5, comment="")
        stats = BookReviewService.get_stats(self.session, 100)
        self.assertEqual(stats["recommend_count"], 2)

        BookReviewService.soft_delete(self.session, 100, 2)
        stats2 = BookReviewService.get_stats(self.session, 100)  # invalidated by soft_delete
        self.assertEqual(stats2["recommend_count"], 1)

    def test_stats_ignore_reviews_when_recommend_disabled(self):
        BookReviewService.upsert(self.session, book_id=100, reader_id=1, rating=8, comment="")
        main.CONF["ENABLE_BOOK_RECOMMEND_TO_OTHERS"] = False
        try:
            BookReviewService.invalidate_stats(100)
            stats = BookReviewService.get_stats(self.session, 100)
            self.assertEqual(stats["recommend_count"], 0)
        finally:
            main.CONF["ENABLE_BOOK_RECOMMEND_TO_OTHERS"] = True


class TestBookReviewHandler(TestWithUserLogin):
    """Integration tests for GET/POST/DELETE /api/book/:id/review(s) over real HTTP,
    mocked user_id=1."""

    def setUp(self):
        super().setUp()
        main.CONF["ENABLE_BOOK_REVIEW"] = True
        main.CONF["REVIEW_REQUIRES_APPROVAL"] = False
        main.CONF["ENABLE_BOOK_RECOMMEND_TO_OTHERS"] = True
        BookReviewService.invalidate_stats(BID_EPUB)

    def test_get_own_review_before_any_submission(self):
        d = self.json("/api/book/%d/review" % BID_EPUB)
        self.assertIsNone(d["review"])

    def test_post_then_get_review(self):
        body = json.dumps({"rating": 8, "comment": "nice book"})
        d = self.json("/api/book/%d/review" % BID_EPUB, method="POST", body=body)
        self.assertEqual(d["err"], "ok")
        self.assertEqual(d["review"]["rating"], 8)

        d = self.json("/api/book/%d/review" % BID_EPUB)
        self.assertEqual(d["review"]["comment"], "nice book")

    def test_post_rejects_invalid_rating(self):
        d = self.json("/api/book/%d/review" % BID_EPUB, method="POST", body=json.dumps({"rating": 99}))
        self.assertEqual(d["err"], "params.invalid")

    def test_post_then_delete(self):
        self.json("/api/book/%d/review" % BID_EPUB, method="POST", body=json.dumps({"rating": 5, "comment": ""}))
        d = self.json("/api/book/%d/review" % BID_EPUB, method="DELETE")
        self.assertEqual(d["err"], "ok")
        d = self.json("/api/book/%d/review" % BID_EPUB)
        self.assertIsNone(d["review"])

    def test_review_disabled_blocks_post(self):
        main.CONF["ENABLE_BOOK_REVIEW"] = False
        d = self.json("/api/book/%d/review" % BID_EPUB, method="POST", body=json.dumps({"rating": 5}))
        self.assertEqual(d["err"], "review.disabled")

    def test_allow_review_false_blocks_post(self):
        db = get_db()
        reader = db.query(Reader).filter_by(id=1).one()
        reader.allow_review = False
        db.commit()
        try:
            d = self.json("/api/book/%d/review" % BID_EPUB, method="POST", body=json.dumps({"rating": 5}))
            self.assertEqual(d["err"], "review.banned")
        finally:
            reader.allow_review = True
            db.commit()

    def test_reviews_list_and_social_stats(self):
        self.json("/api/book/%d/review" % BID_EPUB, method="POST", body=json.dumps({"rating": 9, "comment": "hi"}))

        d = self.json("/api/book/%d/reviews" % BID_EPUB)
        self.assertEqual(d["total"], 1)
        self.assertEqual(d["reviews"][0]["rating"], 9)
        self.assertTrue(d["reviews"][0]["is_own"])  # mocked current_user 提交的那条

        d = self.json("/api/book/%d/social-stats" % BID_EPUB)
        self.assertEqual(d["recommend_count"], 1)


class TestHomeSocialRecommendations(TestWithUserLogin):
    """`/api/index` 的 `social_recommend_books` 字段，见 plan §2.3。"""

    def setUp(self):
        super().setUp()
        main.CONF["ENABLE_BOOK_RECOMMEND_TO_OTHERS"] = True
        BookReviewService.invalidate_stats(BID_EPUB)

    def test_shows_recently_recommended_book(self):
        self.json("/api/book/%d/review" % BID_EPUB, method="POST", body=json.dumps({"rating": 9, "comment": "great"}))
        d = self.json("/api/index")
        self.assertEqual(d["err"], "ok")
        book_ids = [b["id"] for b in d["social_recommend_books"]]
        self.assertIn(BID_EPUB, book_ids)
        rec = next(b for b in d["social_recommend_books"] if b["id"] == BID_EPUB)
        self.assertEqual(rec["recommender"]["nickname"], "Rex")

    def test_hidden_when_recommend_disabled(self):
        self.json("/api/book/%d/review" % BID_EPUB, method="POST", body=json.dumps({"rating": 9, "comment": ""}))
        main.CONF["ENABLE_BOOK_RECOMMEND_TO_OTHERS"] = False
        try:
            d = self.json("/api/index")
            self.assertEqual(d["social_recommend_books"], [])
        finally:
            main.CONF["ENABLE_BOOK_RECOMMEND_TO_OTHERS"] = True

    def test_hidden_when_user_preference_off(self):
        self.json("/api/book/%d/review" % BID_EPUB, method="POST", body=json.dumps({"rating": 9, "comment": ""}))
        self.json("/api/user/update", method="POST", body=json.dumps({"show_home_recommendations": False}))
        try:
            d = self.json("/api/index")
            self.assertEqual(d["social_recommend_books"], [])
        finally:
            self.json("/api/user/update", method="POST", body=json.dumps({"show_home_recommendations": True}))
