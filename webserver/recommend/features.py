#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Book feature snapshot loaded from the Calibre library.
@author: PoxenStudio, 2026
"""

import datetime
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Hashable, List, Optional, Protocol, Tuple

from webserver.constants import CALIBRE_COLUMN_CATEGORY
from webserver.recommend.snapshot import BackgroundSnapshot


@dataclass(frozen=True)
class BookFeatures:
    book_id: int
    title: str = ""
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

    def fingerprint(self) -> Hashable:
        """Cheap value that changes whenever load() would return different data."""
        ...


class CalibreFeatureSource:
    def __init__(self, cache):
        self.cache = cache

    def fingerprint(self) -> Hashable:
        return self.cache.last_modified(), len(self.cache.all_book_ids())

    def _field(self, name, ids, default=None):
        try:
            return self.cache.all_field_for(name, ids, default_value=default)
        except KeyError:
            return {}

    def load(self) -> Dict[int, BookFeatures]:
        ids = self.cache.all_book_ids()
        title = self._field("title", ids)
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
                title=title.get(bid) or "",
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


INDEXED_DIMENSIONS = ("author", "series", "tag", "publisher")

# Placeholder author names meaning "no known author". They carry no taste signal:
# every anonymous book would otherwise link to every other one through this key.
UNKNOWN_AUTHORS = frozenset({"佚名", "未知", "Unknown", "unknown", ""})


def feature_keys(book: BookFeatures) -> List[Tuple[str, str, float]]:
    """(dimension, key, share) pairs; tags share 1/sqrt(n) so heavily tagged books do not dominate a profile."""
    keys = [("author", a, 1.0) for a in book.authors if a not in UNKNOWN_AUTHORS]
    if book.series:
        keys.append(("series", book.series, 1.0))
    keys += [("tag", t, 1.0 / math.sqrt(len(book.tags))) for t in book.tags]
    if book.publisher:
        keys.append(("publisher", book.publisher, 1.0))
    keys += [("language", lang, 1.0) for lang in book.languages]
    return keys


class InvertedIndex:
    def __init__(self, features: Dict[int, BookFeatures]):
        self.postings: Dict[str, Dict[str, List[int]]] = {d: defaultdict(list) for d in INDEXED_DIMENSIONS}
        for book in features.values():
            for dim, key, _ in feature_keys(book):
                if dim in self.postings:
                    self.postings[dim][key].append(book.book_id)

    def books_with(self, dim: str, key: str) -> List[int]:
        return self.postings.get(dim, {}).get(key, [])


class Library:
    def __init__(self, books: Dict[int, BookFeatures]):
        self.books = books
        self.ids = sorted(books)
        self.inverted = InvertedIndex(books)


class FeatureIndex(BackgroundSnapshot[Library]):
    def __init__(self, source: FeatureSource, ttl_seconds: float = 300):
        super().__init__(lambda: Library(source.load()), ttl_seconds, "features", fingerprint=source.fingerprint)
