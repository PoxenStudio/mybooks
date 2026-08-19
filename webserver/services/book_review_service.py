#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Business logic for user book ratings/reviews ("共读" — one review per
(reader, book), rating + optional comment, review = recommendation).
See plan/Social_Reading_Plan.md §2.4/§2.6/§5.1.

Handlers (webserver/handlers/book_review.py) stay thin: auth/param checks,
then delegate here.
"""

import datetime
from typing import List, Optional, Tuple

from sqlalchemy import or_

from webserver import loader
from webserver.models import READ_STATE_FINISHED, READ_STATE_READING, BookReview, ReadingRecord, ReadingState
from webserver.services.cache import TTLCache

CONF = loader.get_settings()

_stats_cache = TTLCache()
_STATS_TTL_SEC = 60


def _stats_key(book_id: int) -> str:
    return f"book_social_stats:{book_id}"


class BookReviewService:
    @staticmethod
    def is_enabled() -> bool:
        return CONF.get("ENABLE_BOOK_REVIEW", True)

    @staticmethod
    def recommend_enabled() -> bool:
        return CONF.get("ENABLE_BOOK_RECOMMEND_TO_OTHERS", True)

    @staticmethod
    def requires_approval() -> bool:
        return CONF.get("REVIEW_REQUIRES_APPROVAL", False)

    @classmethod
    def get_own(cls, db, book_id: int, reader_id: int) -> Optional[BookReview]:
        row = db.query(BookReview).filter_by(book_id=book_id, reader_id=reader_id).one_or_none()
        if row is None or row.deleted_at is not None:
            return None
        return row

    @classmethod
    def upsert(cls, db, book_id: int, reader_id: int, rating: int, comment: str) -> BookReview:
        row = db.query(BookReview).filter_by(book_id=book_id, reader_id=reader_id).one_or_none()
        now = datetime.datetime.now()
        if row is None:
            row = BookReview(reader_id=reader_id, book_id=book_id, create_time=now)
            db.add(row)
        row.rating = rating
        row.comment = comment or ""
        row.update_time = now
        row.deleted_at = None
        # 新建、或者编辑一条曾经被隐藏/待审核的评论，都按当前的审核开关重新判定一次状态
        # （§2.4d：不会永久卡在 hidden，重新编辑视为一次新的提交）
        row.status = BookReview.STATUS_PENDING if cls.requires_approval() else BookReview.STATUS_APPROVED
        row.prev_status = None
        db.commit()
        _stats_cache.invalidate(_stats_key(book_id))
        return row

    @classmethod
    def soft_delete(cls, db, book_id: int, reader_id: int) -> bool:
        row = db.query(BookReview).filter_by(book_id=book_id, reader_id=reader_id).one_or_none()
        if row is None or row.deleted_at is not None:
            return False
        row.deleted_at = datetime.datetime.now()
        db.commit()
        _stats_cache.invalidate(_stats_key(book_id))
        return True

    @classmethod
    def moderate(cls, db, review_id: int, action: str) -> Optional[BookReview]:
        """管理员操作：approve（未审核 -> 通过）、hide（任意状态 -> 屏蔽，记录 prev_status）、
        restore（屏蔽 -> 恢复到 prev_status）。见 plan §2.6。"""
        row = db.query(BookReview).filter_by(id=review_id).one_or_none()
        if row is None:
            return None
        if action == "approve":
            row.status = BookReview.STATUS_APPROVED
            row.prev_status = None
        elif action == "hide":
            if row.status != BookReview.STATUS_HIDDEN:
                row.prev_status = row.status
                row.status = BookReview.STATUS_HIDDEN
        elif action == "restore":
            row.status = row.prev_status or BookReview.STATUS_APPROVED
            row.prev_status = None
        else:
            return None
        db.commit()
        _stats_cache.invalidate(_stats_key(row.book_id))
        return row

    @classmethod
    def hard_delete(cls, db, review_id: int) -> bool:
        """管理员物理删除一条评论（不同于 §2.4b 用户自己的软删除）：直接从表中移除，
        不再作为"隐藏"状态出现在任何地方，也无法恢复。"""
        row = db.query(BookReview).filter_by(id=review_id).one_or_none()
        if row is None:
            return False
        book_id = row.book_id
        db.delete(row)
        db.commit()
        _stats_cache.invalidate(_stats_key(book_id))
        return True

    @classmethod
    def list_for_book(
        cls, db, book_id: int, viewer_reader_id: Optional[int] = None, limit: int = 50,
    ) -> Tuple[List[BookReview], int]:
        """普通用户可见的评论：approved 的都能看；未登录/其他人的 pending、hidden 都看不到，
        但当前登录用户自己的 pending/hidden 那条（如果有）例外可见，方便自己确认审核状态。
        不做日期筛选/分页，只取最近更新的 `limit` 条（见 plan §2.4c）。"""
        q = db.query(BookReview).filter(BookReview.book_id == book_id, BookReview.deleted_at.is_(None))
        conds = [BookReview.status == BookReview.STATUS_APPROVED]
        if viewer_reader_id is not None:
            conds.append(BookReview.reader_id == viewer_reader_id)
        q = q.filter(or_(*conds))
        total = q.count()
        rows = q.order_by(BookReview.update_time.desc()).limit(limit).all()
        if viewer_reader_id is not None:
            # 当前用户的评价置顶（若命中这最近 limit 条）
            rows.sort(key=lambda r: 0 if r.reader_id == viewer_reader_id else 1)
        return rows, total

    @classmethod
    def list_for_admin(cls, db, status: Optional[str] = None, page: int = 1, page_size: int = 20) -> Tuple[List[BookReview], int]:
        q = db.query(BookReview).filter(BookReview.deleted_at.is_(None))
        if status:
            q = q.filter(BookReview.status == status)
        total = q.count()
        rows = q.order_by(BookReview.update_time.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return rows, total

    @classmethod
    def get_stats(cls, db, book_id: int) -> dict:
        def _load():
            reading_count = db.query(ReadingState).filter(
                ReadingState.book_id == book_id, ReadingState.read_state == READ_STATE_READING
            ).count()
            finished_count = db.query(ReadingState).filter(
                ReadingState.book_id == book_id, ReadingState.read_state == READ_STATE_FINISHED
            ).count()
            favorite_count = db.query(ReadingState).filter(ReadingState.book_id == book_id, ReadingState.favorite == 1).count()
            recommend_count = 0
            if cls.recommend_enabled():
                recommend_count = db.query(BookReview).filter(
                    BookReview.book_id == book_id,
                    BookReview.status == BookReview.STATUS_APPROVED,
                    BookReview.deleted_at.is_(None),
                ).count()
            return {
                "reading_count": reading_count,
                "finished_count": finished_count,
                "favorite_count": favorite_count,
                "recommend_count": recommend_count,
            }

        return _stats_cache.get_or_set(_stats_key(book_id), _STATS_TTL_SEC, _load)

    @classmethod
    def invalidate_stats(cls, book_id: int) -> None:
        """供 favorite/在读状态变化的地方调用，让下次 social-stats 读取立刻反映最新值。"""
        _stats_cache.invalidate(_stats_key(book_id))

    @classmethod
    def recent_recommendations(cls, db, days: int = 7, limit: int = 10) -> List[BookReview]:
        """最近 `days` 天内、状态为通过的评价，按 `book_id` 去重（每本书只取最新一条），
        用于首页"其他用户推荐"，见 plan §2.3。"""
        since = datetime.datetime.now() - datetime.timedelta(days=days)
        rows = (
            db.query(BookReview)
            .filter(BookReview.status == BookReview.STATUS_APPROVED, BookReview.deleted_at.is_(None), BookReview.update_time >= since)
            .order_by(BookReview.update_time.desc())
            .all()
        )
        seen_books = set()
        result: List[BookReview] = []
        for row in rows:
            if row.book_id in seen_books:
                continue
            seen_books.add(row.book_id)
            result.append(row)
            if len(result) >= limit:
                break
        return result

    @classmethod
    def cascade_delete_book(cls, db, book_id: int, commit: bool = True) -> None:
        """书籍被删除/下架时级联清理评价、共读同步记录与阅读状态（收藏/在读/待读），见 plan §6。

        commit=False 供调用方把这次级联清理并入自己的事务（例如与 Item 的删除放进同一次
        commit），此时清理是否落盘由调用方负责。
        """
        db.query(BookReview).filter(BookReview.book_id == book_id).delete(synchronize_session=False)
        db.query(ReadingRecord).filter(ReadingRecord.book_id == book_id).delete(synchronize_session=False)
        db.query(ReadingState).filter(ReadingState.book_id == book_id).delete(synchronize_session=False)
        if commit:
            db.commit()
        _stats_cache.invalidate(_stats_key(book_id))
