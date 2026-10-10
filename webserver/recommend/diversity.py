#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Diversity re-ranking (MMR) with per-author and per-series caps.
@author: PoxenStudio, 2026
"""

from collections import Counter
from typing import List, Sequence, Tuple

from webserver.recommend.features import UNKNOWN_AUTHORS, BookFeatures

Scored = Tuple[BookFeatures, float]

MMR_MAX_N = 100


def _known_authors(book: BookFeatures):
    return [a for a in book.authors if a not in UNKNOWN_AUTHORS]


def book_similarity(a: BookFeatures, b: BookFeatures) -> float:
    if set(_known_authors(a)) & set(_known_authors(b)):
        return 1.0
    if a.series and a.series == b.series:
        return 0.8
    ta, tb = set(a.tags), set(b.tags)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class _Caps:
    def __init__(self, max_per_author: int, max_per_series: int):
        self.max_per_author = max_per_author
        self.max_per_series = max_per_series
        self.authors: Counter = Counter()
        self.series: Counter = Counter()

    def allows(self, book: BookFeatures) -> bool:
        if any(self.authors[a] >= self.max_per_author for a in _known_authors(book)):
            return False
        return not (book.series and self.series[book.series] >= self.max_per_series)

    def take(self, book: BookFeatures) -> None:
        self.authors.update(_known_authors(book))
        if book.series:
            self.series[book.series] += 1


def mmr_rerank(scored: Sequence[Scored], n: int, diversity: float, max_per_author: int, max_per_series: int) -> List[BookFeatures]:
    """Greedy MMR; hard per-author/series caps are relaxed only when the pool cannot fill n otherwise."""
    if diversity <= 0 or n > MMR_MAX_N:
        return _capped(scored, n, max_per_author, max_per_series)
    remaining = list(scored)
    penalty = [0.0] * len(remaining)
    selected: List[BookFeatures] = []
    caps = _Caps(max_per_author, max_per_series)
    for enforce_caps in (True, False):
        while len(selected) < n and remaining:
            best, best_value = None, None
            for i, (book, score) in enumerate(remaining):
                if enforce_caps and not caps.allows(book):
                    continue
                value = score - diversity * penalty[i]
                if best_value is None or value > best_value:
                    best, best_value = i, value
            if best is None:
                break
            book, _ = remaining.pop(best)
            penalty.pop(best)
            selected.append(book)
            caps.take(book)
            penalty = [max(p, book_similarity(other, book)) for p, (other, _) in zip(penalty, remaining)]
    return selected


def _capped(scored: Sequence[Scored], n: int, max_per_author: int, max_per_series: int) -> List[BookFeatures]:
    ordered = sorted(scored, key=lambda x: x[1], reverse=True)
    caps = _Caps(max_per_author, max_per_series)
    selected: List[BookFeatures] = []
    skipped: List[BookFeatures] = []
    for book, _ in ordered:
        if len(selected) >= n:
            break
        if caps.allows(book):
            selected.append(book)
            caps.take(book)
        else:
            skipped.append(book)
    return selected + skipped[:n - len(selected)]
