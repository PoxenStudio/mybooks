#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Synthetic benchmark of the home page recommendation engine (design doc §9.1).
@author: PoxenStudio, 2026
"""

import argparse
import datetime
import os
import random
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from webserver.recommend import BookFeatures, RecommendConfig, RecommendContext, RecommendService  # noqa: E402
from webserver.recommend.crowd import CrowdData, Engagement  # noqa: E402
from webserver.recommend.profile import BookSignal  # noqa: E402

NOW = datetime.datetime(2026, 9, 1)


class Static:
    def __init__(self, value):
        self.value = value

    def load(self, *_args):
        return self.value

    def fingerprint(self):
        return 0


class Profiles:
    def __init__(self, signals):
        self.signals = signals

    def load(self, reader_id):
        return self.signals.get(reader_id, [])


def synthetic(books: int, readers: int, per_reader: int, seed: int = 1):
    rnd = random.Random(seed)
    features = {
        i: BookFeatures(
            book_id=i,
            title="t%d" % i,
            authors=("a%d" % rnd.randint(0, books // 5),),
            tags=tuple("t%d" % rnd.randint(0, 300) for _ in range(5)),
            languages=("zho",),
            series=("s%d" % rnd.randint(0, 2000)) if rnd.random() < 0.3 else None,
            timestamp=NOW - datetime.timedelta(days=rnd.randint(0, 2000)),
            rating=rnd.choice([0, 6, 8, 10]),
        )
        for i in range(1, books + 1)
    }
    engagements = [
        Engagement(
            reader_id=r,
            book_id=rnd.randint(1, books),
            read_secs=rnd.randint(0, 20000),
            downloaded=rnd.random() < 0.5,
            favorite=rnd.random() < 0.2,
            finished=rnd.random() < 0.3,
            last_active=NOW - datetime.timedelta(days=rnd.randint(0, 90)),
        )
        for r in range(1, readers + 1)
        for _ in range(per_reader)
    ]
    signals = {}
    for e in engagements:
        signals.setdefault(e.reader_id, []).append(
            BookSignal(e.book_id, favorite=e.favorite, read_state=2 if e.finished else 0, read_secs=e.read_secs, last_active=e.last_active)
        )
    return features, CrowdData(engagements), signals


def timed(fn):
    started = time.perf_counter()
    result = fn()
    return result, (time.perf_counter() - started) * 1000


def run(books: int, readers: int, per_reader: int, requests: int) -> None:
    features, crowd, signals = synthetic(books, readers, per_reader)
    service = RecommendService(Static(features), RecommendConfig, Static(crowd), Profiles(signals))
    print("== %d books, %d readers x %d books" % (books, readers, per_reader))
    library, ms = timed(service.index.refresh)
    print("A  features + inverted index     %7.0f ms" % ms)
    _, ms = timed(service.crowd.refresh)
    print("B' crowd statistics              %7.0f ms" % ms)
    _, ms = timed(service.coread.refresh)
    print("B'' co-reading neighbors         %7.0f ms" % ms)

    for reader_id in (None, 1):
        label = "guest" if reader_id is None else "reader"
        _, ms = timed(lambda: service.home(RecommendContext(reader_id=reader_id, now=NOW), 12, 12))
        print("C+D %-6s first request (pool)  %7.0f ms" % (label, ms))
        samples = []
        for i in range(requests):
            _, ms = timed(lambda: service.home(RecommendContext(reader_id=reader_id, now=NOW, rng=random.Random(i)), 12, 12))
            samples.append(ms)
        samples.sort()
        p95 = samples[int(len(samples) * 0.95) - 1]
        print("E  %-6s request p50 / p95     %7.1f / %.1f ms" % (label, statistics.median(samples), p95))

    _, ms = timed(lambda: service.similar(1, RecommendContext(reader_id=None, now=NOW), 12))
    print("S  related books, first (pool)   %7.0f ms" % ms)
    samples = sorted(timed(lambda: service.similar(1, RecommendContext(reader_id=None, now=NOW, rng=random.Random(i)), 12))[1] for i in range(requests))
    print("S  related books p50 / p95       %7.1f / %.1f ms" % (statistics.median(samples), samples[int(len(samples) * 0.95) - 1]))

    service.invalidate_reader(1)
    _, ms = timed(lambda: service.home(RecommendContext(reader_id=1, now=NOW), 12, 12))
    print("C  reader after invalidation     %7.0f ms (stale pool, rebuild in background)" % ms)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books", type=int, nargs="+", default=[10000, 50000])
    parser.add_argument("--readers", type=int, default=20)
    parser.add_argument("--per-reader", type=int, default=500)
    parser.add_argument("--requests", type=int, default=200)
    args = parser.parse_args()
    for books in args.books:
        run(books, args.readers, args.per_reader, args.requests)


if __name__ == "__main__":
    main()
