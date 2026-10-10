#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Business logic for user booklists (书单), see document/BookList_Design.md.

This service only touches the three booklist_* tables (pure SQLAlchemy CRUD).
Anything that needs to read book metadata from the Calibre library (title,
cover, existence check) stays in webserver/handlers/booklist.py, because the
Calibre db handle (`self.calibre_db`) lives on the request handler, not here
-- same split as book_review_service.py / BaseHandler.get_book().
"""

import datetime
from typing import List, Optional, Tuple

from webserver.models import BookList, BookListBook, BookListLike


class BookListLimitExceeded(Exception):
    pass


class BookListService:
    @classmethod
    def get(cls, db, booklist_id: int) -> Optional[BookList]:
        return db.query(BookList).filter_by(id=booklist_id).one_or_none()

    @classmethod
    def create(cls, db, reader_id: int, name: str, description: str = "", color: Optional[str] = None, is_public: bool = False) -> BookList:
        count = db.query(BookList).filter_by(reader_id=reader_id).count()
        if count >= BookList.MAX_PER_USER:
            raise BookListLimitExceeded()
        row = BookList(reader_id=reader_id, name=name, description=description, color=color, is_public=is_public)
        db.add(row)
        db.commit()
        return row

    @classmethod
    def update(cls, db, row: BookList, name: Optional[str] = None, description: Optional[str] = None,
               color: Optional[str] = None, is_public: Optional[bool] = None, guest_read: Optional[bool] = None) -> BookList:
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        if color is not None and color in BookList.COLORS:
            row.color = color
        if is_public is not None:
            row.is_public = is_public
        if guest_read is not None:
            row.guest_read = guest_read
        if not row.is_public:
            row.guest_read = False
        row.update_time = datetime.datetime.now()
        db.commit()
        return row

    @classmethod
    def delete(cls, db, row: BookList) -> None:
        """物理硬删除，级联删除关联的 booklist_books / booklist_likes 记录（见方案第 2.1.1 节）。"""
        db.query(BookListBook).filter_by(booklist_id=row.id).delete(synchronize_session=False)
        db.query(BookListLike).filter_by(booklist_id=row.id).delete(synchronize_session=False)
        db.delete(row)
        db.commit()

    @classmethod
    def set_sticky(cls, db, row: BookList, is_sticky: bool, sticky_order: Optional[int] = None) -> BookList:
        row.is_sticky = is_sticky
        row.sticky_order = sticky_order if is_sticky else None
        row.update_time = datetime.datetime.now()
        db.commit()
        return row

    @classmethod
    def list_mine(cls, db, reader_id: int) -> List[BookList]:
        return (
            db.query(BookList)
            .filter(BookList.reader_id == reader_id)
            .order_by(BookList.update_time.desc())
            .all()
        )

    @classmethod
    def list_public(cls, db, page: int = 1, page_size: int = 20) -> Tuple[List[BookList], int]:
        q = db.query(BookList).filter(BookList.is_public.is_(True))
        total = q.count()
        rows = (
            q.order_by(BookList.is_sticky.desc(), BookList.sticky_order.asc(), BookList.update_time.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total

    @classmethod
    def list_liked(cls, db, reader_id: int) -> List[BookList]:
        return (
            db.query(BookList)
            .join(BookListLike, BookListLike.booklist_id == BookList.id)
            .filter(BookListLike.reader_id == reader_id)
            .order_by(BookListLike.create_time.desc())
            .all()
        )

    @classmethod
    def list_for_homepage(cls, db, reader_id: Optional[int], limit: int = 2) -> List[BookList]:
        """首页"书单推荐"挑选规则：置顶 > 我点赞的（未登录跳过） > 其余公共书单，去重，取满 limit 个即止。见方案第六节。"""
        result: List[BookList] = []
        seen = set()

        def _add(rows):
            for row in rows:
                if len(result) >= limit:
                    return
                if row.id in seen:
                    continue
                seen.add(row.id)
                result.append(row)

        sticky_rows = (
            db.query(BookList)
            .filter(BookList.is_public.is_(True), BookList.is_sticky.is_(True))
            .order_by(BookList.sticky_order.asc(), BookList.update_time.desc())
            .all()
        )
        _add(sticky_rows)

        if len(result) < limit and reader_id:
            _add(cls.list_liked(db, reader_id))

        if len(result) < limit:
            public_rows, _ = cls.list_public(db, page=1, page_size=limit + len(seen))
            _add(public_rows)

        return result[:limit]

    @classmethod
    def is_liked(cls, db, booklist_id: int, reader_id: int) -> bool:
        return db.query(BookListLike).filter_by(booklist_id=booklist_id, reader_id=reader_id).count() > 0

    @classmethod
    def toggle_like(cls, db, booklist_id: int, reader_id: int) -> bool:
        """返回切换后的点赞状态（True=已点赞）。"""
        row = db.query(BookList).filter_by(id=booklist_id).one_or_none()
        if row is None:
            raise ValueError("booklist not found")
        like = db.query(BookListLike).filter_by(booklist_id=booklist_id, reader_id=reader_id).one_or_none()
        if like:
            db.delete(like)
            row.like_count = max(0, row.like_count - 1)
            db.commit()
            return False
        db.add(BookListLike(booklist_id=booklist_id, reader_id=reader_id))
        row.like_count += 1
        db.commit()
        return True

    @classmethod
    def bump_view(cls, db, booklist_id: int) -> None:
        db.query(BookList).filter_by(id=booklist_id).update({BookList.view_count: BookList.view_count + 1})
        db.commit()

    @classmethod
    def list_book_ids(cls, db, booklist_id: int, order: str = "desc") -> List[int]:
        q = db.query(BookListBook).filter_by(booklist_id=booklist_id)
        q = q.order_by(BookListBook.update_time.desc() if order != "asc" else BookListBook.update_time.asc())
        return [r.book_id for r in q.all()]

    @classmethod
    def book_ids_in_booklist(cls, db, booklist_id: int, book_ids: List[int]) -> set:
        if not book_ids:
            return set()
        rows = db.query(BookListBook.book_id).filter(
            BookListBook.booklist_id == booklist_id, BookListBook.book_id.in_(book_ids)
        ).all()
        return {r[0] for r in rows}

    @classmethod
    def booklists_containing_book(cls, db, reader_id: int, book_id: int) -> set:
        """当前用户的哪些书单已经包含这本书，供书籍详情页"快速加入书单"面板打勾用。"""
        rows = (
            db.query(BookListBook.booklist_id)
            .join(BookList, BookList.id == BookListBook.booklist_id)
            .filter(BookList.reader_id == reader_id, BookListBook.book_id == book_id)
            .all()
        )
        return {r[0] for r in rows}

    @classmethod
    def add_books(cls, db, row: BookList, book_ids: List[int]) -> int:
        """加入书籍，已存在的跳过（幂等）。返回实际新增的数量。"""
        existing = cls.book_ids_in_booklist(db, row.id, book_ids)
        added = 0
        now = datetime.datetime.now()
        for book_id in book_ids:
            if book_id in existing:
                continue
            db.add(BookListBook(booklist_id=row.id, book_id=book_id))
            added += 1
        if added:
            row.book_count += added
            row.update_time = now
            db.commit()
        return added

    @classmethod
    def remove_book(cls, db, row: BookList, book_id: int) -> bool:
        link = db.query(BookListBook).filter_by(booklist_id=row.id, book_id=book_id).one_or_none()
        if link is None:
            return False
        db.delete(link)
        row.book_count = max(0, row.book_count - 1)
        row.update_time = datetime.datetime.now()
        db.commit()
        return True
