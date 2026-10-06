import logging
import random
import threading
import time

from webserver import utils


def _timed(name, func):
    start = time.perf_counter()
    try:
        func()
        logging.info("[STARTUP-TIMING] step=warmup:%s status=done cost_ms=%.0f", name, (time.perf_counter() - start) * 1000)
    except Exception as e:
        logging.warning("[STARTUP-TIMING] step=warmup:%s status=failed error=%s", name, e)


def _opencc():
    utils.get_opencc("s2t")
    utils.get_opencc("t2s")


def _jieba():
    import jieba

    jieba.initialize()


def _metadata(legacy, cache):
    ids = sorted(cache.all_book_ids(), reverse=True)[:20]
    if ids:
        legacy.get_data_as_dict(ids=ids)


def _recommend(service, session_factory):
    from webserver.recommend import RecommendContext

    ctx = RecommendContext(reader_id=None, is_visible=lambda f: True, exclude_ids=frozenset(), rng=random.Random(0), avoid_ids=frozenset(), shuffle=False)
    try:
        service.home(ctx, 12, 12)
    finally:
        session_factory.remove()


def run(legacy, cache, db_lock, recommend, session_factory, delay):
    time.sleep(delay)
    steps = [("opencc", _opencc), ("jieba", _jieba), ("metadata", lambda: _metadata(legacy, cache))]
    if recommend is not None:
        steps.append(("recommend", lambda: _recommend(recommend, session_factory)))
    for name, func in steps:
        _timed(name, func)


def start(legacy, cache, db_lock, recommend, session_factory, delay=10):
    thread = threading.Thread(target=run, args=(legacy, cache, db_lock, recommend, session_factory, delay), name="mybooks-warmup", daemon=True)
    thread.start()
    return thread
