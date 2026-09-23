#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""书籍删除时的应用侧关联数据级联清理。

宿主删除路径（BaseHandler.delete_book）与工具箱删除路径（BaseTool.delete_book_by_id，
即 CoreAPI.calibre.delete_book）共用这一份实现，避免两边清理范围逐渐漂移。
"""

import datetime

from webserver.models import (
    BookList,
    BookListBook,
    BookReadingStats,
    BookReview,
    Item,
    ManualReadingLog,
    Reading,
    ReadingRecord,
    ReadingState,
)
from webserver.services.book_review_service import BookReviewService


def cascade_delete_book_data(db, book_id: int, commit: bool = True) -> None:
    """书籍被删除/下架时级联清理所有关联数据：Item（收藏/待读等标记）、评价、共读同步
    记录、阅读状态（收藏/在读/待读）、手工补录的阅读时长记录、阅读时长统计
    （Reading 按天分桶 / BookReadingStats 按格式累计），以及书单关联（同步扣减书单的 book_count）。

    刻意不清理的表：
    - ReaderPaidBook：购买记录属于交易历史，书从回收站还原后应继续有效。
    - ScanFile：扫描记录描述的是磁盘上的文件，删掉会导致该文件下次扫描时被当作新文件重新导入。

    commit=False 供调用方把这次级联清理并入自己的事务，此时清理是否落盘由调用方负责。
    """
    db.query(Item).filter(Item.book_id == book_id).delete(synchronize_session=False)
    db.query(BookReview).filter(BookReview.book_id == book_id).delete(synchronize_session=False)
    db.query(ReadingRecord).filter(ReadingRecord.book_id == book_id).delete(synchronize_session=False)
    db.query(ReadingState).filter(ReadingState.book_id == book_id).delete(synchronize_session=False)
    db.query(ManualReadingLog).filter(ManualReadingLog.book_id == book_id).delete(synchronize_session=False)
    db.query(Reading).filter(Reading.book_id == book_id).delete(synchronize_session=False)
    db.query(BookReadingStats).filter(BookReadingStats.book_id == book_id).delete(synchronize_session=False)

    # 书单：book_count 是计数器，删关联行时必须同步扣减，否则书单显示的数量比实际列出的多
    booklist_ids = [r[0] for r in db.query(BookListBook.booklist_id).filter(BookListBook.book_id == book_id).all()]
    if booklist_ids:
        now = datetime.datetime.now()
        for row in db.query(BookList).filter(BookList.id.in_(booklist_ids)).all():
            row.book_count = max(0, (row.book_count or 0) - 1)
            row.update_time = now
        db.query(BookListBook).filter(BookListBook.book_id == book_id).delete(synchronize_session=False)

    if commit:
        db.commit()
    BookReviewService.invalidate_stats(book_id)
