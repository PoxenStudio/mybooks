#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Item-to-item related books for the book detail page, the same for every reader.
@author: PoxenStudio, 2026
"""

import heapq
import math
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from webserver.recommend.config import RecommendConfig
from webserver.recommend.context import RecommendContext
from webserver.recommend.coread import CoReadIndex
from webserver.recommend.features import BookFeatures, Library
from webserver.recommend.scoring import Reason, Scorer

UNKNOWN_AUTHORS = frozenset({"佚名", "未知", "Unknown", "unknown"})
W_AUTHOR = 3.0
W_SERIES = 2.5
W_TAG = 2.0
W_PUBLISHER = 0.5
W_CONTENT_TOTAL = W_AUTHOR + W_SERIES + W_TAG + W_PUBLISHER
SERIES_SAME = 0.8
SERIES_NEXT = 1.0
SERIES_REASONS = ("series_next", "same_series")


@dataclass
class Related:
    book: BookFeatures
    score: float
    reason: Optional[Reason]


def normalize_title(title: str) -> str:
    return re.sub(r"[\W_]+", "", title or "").casefold()


class RelatedBooks:
    def __init__(self, library: Library, coread: Optional[CoReadIndex], shared: Sequence[Tuple[Scorer, float]], config: RecommendConfig):
        self.library = library
        self.coread = coread
        self.shared = [(s, w) for s, w in shared if w > 0]
        self.config = config
        self.total_books = len(library.books)

    def idf(self, tag: str) -> float:
        return math.log((self.total_books + 1) / (len(self.library.inverted.books_with("tag", tag)) + 1))

    def _recall(self, source: BookFeatures, authors: Set[str], co: Dict[int, float]) -> Set[int]:
        index = self.library.inverted
        ids: Set[int] = set(co)
        for author in authors:
            ids.update(index.books_with("author", author))
        if source.series:
            ids.update(index.books_with("series", source.series))
        for tag in source.tags:
            posting = index.books_with("tag", tag)
            if len(posting) <= self.config.similar_max_tag_books:
                ids.update(posting)
        ids.discard(source.book_id)
        return ids

    def rank(self, source: BookFeatures, size: int) -> List[Related]:
        authors = set(source.authors) - UNKNOWN_AUTHORS
        neighbors = self.coread.neighbors.get(source.book_id, []) if self.coread else []
        top_sim = max((sim for _, sim, _ in neighbors), default=0.0)
        co = {n: sim / top_sim for n, sim, _ in neighbors} if top_sim > 0 else {}
        tag_idf = {t: self.idf(t) for t in source.tags}
        tag_total = sum(tag_idf.values())
        next_index = self._next_series_index(source)
        title = normalize_title(source.title)

        weights = [self.config.w_similar_content] + ([self.config.w_similar_co] if co else []) + [w for _, w in self.shared]
        total_weight = sum(weights) or 1.0
        ctx = RecommendContext(reader_id=None)
        ranked = []
        for book_id in self._recall(source, authors, co):
            book = self.library.books.get(book_id)
            if book is None or (title and normalize_title(book.title) == title and set(book.authors) & set(source.authors)):
                continue
            parts = self._content_parts(source, book, authors, tag_idf, tag_total, next_index)
            content = sum(value for value, _ in parts) / W_CONTENT_TOTAL
            score = self.config.w_similar_content * content + sum(w * s.score(book, ctx) for s, w in self.shared)
            candidates = [(self.config.w_similar_content * value / W_CONTENT_TOTAL, reason) for value, reason in parts]
            if co:
                score += self.config.w_similar_co * co.get(book_id, 0.0)
                candidates.append((self.config.w_similar_co * co.get(book_id, 0.0), Reason("co_read")))
            ranked.append(Related(book, score / total_weight, self._reason(candidates)))
        return heapq.nlargest(size, ranked, key=lambda r: (r.score, -r.book.book_id))

    @staticmethod
    def _reason(candidates: List[Tuple[float, Reason]]) -> Optional[Reason]:
        """Series reasons are the most specific; otherwise the largest weighted contribution wins."""
        for value, reason in candidates:
            if reason.type in SERIES_REASONS and value > 0:
                return reason
        best = max(candidates, key=lambda x: x[0], default=(0.0, None))
        return best[1] if best[0] > 0 else None

    def _next_series_index(self, source: BookFeatures) -> Optional[float]:
        if not source.series:
            return None
        later = [
            self.library.books[i].series_index
            for i in self.library.inverted.books_with("series", source.series)
            if i in self.library.books and self.library.books[i].series_index > source.series_index
        ]
        return min(later, default=None)

    def _content_parts(self, source: BookFeatures, book: BookFeatures, authors: Set[str], tag_idf: Dict[str, float], tag_total: float, next_index: Optional[float]):
        parts: List[Tuple[float, Reason]] = []
        shared_authors = [a for a in book.authors if a in authors]
        if shared_authors:
            parts.append((W_AUTHOR, Reason("same_author", shared_authors[0])))
        if source.series and book.series == source.series:
            if next_index is not None and book.series_index == next_index:
                parts.append((W_SERIES * SERIES_NEXT, Reason("series_next", source.series)))
            else:
                parts.append((W_SERIES * SERIES_SAME, Reason("same_series", source.series)))
        shared_tags = [t for t in book.tags if t in tag_idf]
        if shared_tags and tag_total > 0:
            rarest = max(shared_tags, key=lambda t: tag_idf[t])
            parts.append((W_TAG * sum(tag_idf[t] for t in shared_tags) / tag_total, Reason("same_tag", rarest)))
        if source.publisher and book.publisher == source.publisher:
            parts.append((W_PUBLISHER, Reason("same_publisher", source.publisher)))
        return parts
