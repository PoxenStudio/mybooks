#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

from collections import Counter
from typing import List, Sequence, Tuple

from webserver.recommend.features import BookFeatures

Scored = Tuple[BookFeatures, float]


def book_similarity(a: BookFeatures, b: BookFeatures) -> float:
    if set(a.authors) & set(b.authors):
        return 1.0
    if a.series and a.series == b.series:
        return 0.8
    ta, tb = set(a.tags), set(b.tags)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def mmr_rerank(scored: Sequence[Scored], n: int, diversity: float, max_per_author: int, max_per_series: int) -> List[BookFeatures]:
    """Greedy MMR; hard per-author/series caps are relaxed only when the pool cannot fill n otherwise."""
    remaining = list(scored)
    selected: List[BookFeatures] = []
    authors: Counter = Counter()
    series: Counter = Counter()

    def within_caps(book: BookFeatures) -> bool:
        if any(authors[a] >= max_per_author for a in book.authors):
            return False
        return not (book.series and series[book.series] >= max_per_series)

    for enforce_caps in (True, False):
        while len(selected) < n:
            best, best_value = None, None
            for i, (book, score) in enumerate(remaining):
                if enforce_caps and not within_caps(book):
                    continue
                penalty = max((book_similarity(book, s) for s in selected), default=0.0)
                value = score - diversity * penalty
                if best_value is None or value > best_value:
                    best, best_value = i, value
            if best is None:
                break
            book, _ = remaining.pop(best)
            selected.append(book)
            authors.update(book.authors)
            if book.series:
                series[book.series] += 1
    return selected
