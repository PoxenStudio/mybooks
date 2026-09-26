#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import datetime
from dataclasses import dataclass
from typing import Dict, Optional, Protocol, Tuple

from webserver.constants import CALIBRE_COLUMN_CATEGORY
from webserver.recommend.snapshot import BackgroundSnapshot


@dataclass(frozen=True)
class BookFeatures:
    book_id: int
    authors: Tuple[str, ...] = ()
    series: Optional[str] = None
    series_index: float = 0.0
    tags: Tuple[str, ...] = ()
    publisher: Optional[str] = None
    languages: Tuple[str, ...] = ()
    category: str = ""
    timestamp: Optional[datetime.datetime] = None
    rating: float = 0.0

    def age_days(self, now: datetime.datetime) -> Optional[float]:
        if self.timestamp is None:
            return None
        return max(0.0, (now - self.timestamp).total_seconds() / 86400)


class FeatureSource(Protocol):
    def load(self) -> Dict[int, BookFeatures]:
        ...


class CalibreFeatureSource:
    def __init__(self, cache):
        self.cache = cache

    def _field(self, name, ids, default=None):
        try:
            return self.cache.all_field_for(name, ids, default_value=default)
        except KeyError:
            return {}

    def load(self) -> Dict[int, BookFeatures]:
        ids = self.cache.all_book_ids()
        authors = self._field("authors", ids)
        series = self._field("series", ids)
        series_index = self._field("series_index", ids)
        tags = self._field("tags", ids)
        publisher = self._field("publisher", ids)
        languages = self._field("languages", ids)
        category = self._field(CALIBRE_COLUMN_CATEGORY, ids)
        timestamp = self._field("timestamp", ids)
        rating = self._field("rating", ids)
        return {
            bid: BookFeatures(
                book_id=bid,
                authors=tuple(authors.get(bid) or ()),
                series=series.get(bid) or None,
                series_index=float(series_index.get(bid) or 0),
                tags=tuple(tags.get(bid) or ()),
                publisher=publisher.get(bid) or None,
                languages=tuple(languages.get(bid) or ()),
                category=category.get(bid) or "",
                timestamp=_naive_utc(timestamp.get(bid)),
                rating=float(rating.get(bid) or 0),
            )
            for bid in ids
        }


def _naive_utc(ts: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    if ts is None or ts.tzinfo is None:
        return ts
    return ts.astimezone(datetime.timezone.utc).replace(tzinfo=None)


class FeatureIndex(BackgroundSnapshot[Dict[int, BookFeatures]]):
    def __init__(self, source: FeatureSource, ttl_seconds: float = 300):
        super().__init__(source.load, ttl_seconds, "features")
