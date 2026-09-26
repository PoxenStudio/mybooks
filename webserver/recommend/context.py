#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import datetime
import random
from dataclasses import dataclass, field
from typing import Callable, FrozenSet, Optional

from webserver.recommend.features import BookFeatures


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def home_seed(reader_id: Optional[int], now: datetime.datetime, bucket_minutes: int) -> str:
    bucket = int((now - datetime.datetime(1970, 1, 1)).total_seconds() // (max(bucket_minutes, 1) * 60))
    return "%d:%d" % (reader_id or 0, bucket)


@dataclass
class RecommendContext:
    reader_id: Optional[int]
    is_visible: Callable[[BookFeatures], bool] = lambda _book: True
    exclude_ids: FrozenSet[int] = frozenset()
    now: datetime.datetime = field(default_factory=utc_now)
    rng: random.Random = field(default_factory=random.Random)

    def accepts(self, book: BookFeatures) -> bool:
        return book.book_id not in self.exclude_ids and self.is_visible(book)

    def excluding(self, ids) -> "RecommendContext":
        return RecommendContext(self.reader_id, self.is_visible, self.exclude_ids | frozenset(ids), self.now, self.rng)
