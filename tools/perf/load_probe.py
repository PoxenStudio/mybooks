#!/usr/bin/env python3
"""并发压测 + ioloop 探针：后台打重请求，前台持续测 /api/user/info 延迟，结束后拉 /api/admin/perf。

用法: python3 tools/perf/load_probe.py --base http://nas:8083 --token <管理员 podcast token> \
          [--scenario search,download,index,thumb] [--duration 60] [--book 2063]
"""
import argparse
import json
import statistics
import threading
import time
import urllib.parse
import urllib.request


def fetch(base, path, token, timeout=60, read=True):
    req = urllib.request.Request(base + path, headers={"X-MYBOOKS-TOKEN": token})
    start = time.perf_counter()
    status = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as rsp:
            status = rsp.status
            if read:
                rsp.read()
    except Exception:
        status = -1
    return status, (time.perf_counter() - start) * 1000.0


def scenario_paths(name, book):
    if name == "search":
        q = urllib.parse.quote("书 OR 書")
        return ["/api/search?name=%s&start=0&size=1000" % q, "/api/search?name=%s&start=0&size=60&order=title" % q]
    if name == "download":
        return ["/api/book/%d.EPUB" % book, "/api/book/%d.PDF" % book]
    if name == "index":
        return ["/api/index?refresh=1", "/api/categories", "/api/all"]
    if name == "thumb":
        return ["/get/thumb_150_200/%d.jpg?t=%d" % (i, time.time()) for i in range(1, 41)]
    raise SystemExit("unknown scenario: " + name)


def worker(base, token, paths, stop, results):
    i = 0
    while not stop.is_set():
        path = paths[i % len(paths)]
        i += 1
        status, ms = fetch(base, path, token)
        results.append((path.split("?")[0], status, ms))


def percentile(values, pct):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * pct))] if ordered else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--scenario", default="search,index,thumb")
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--concurrency", type=int, default=2, help="每个场景的并发数")
    ap.add_argument("--book", type=int, default=1)
    ap.add_argument("--probe-interval", type=float, default=0.5)
    args = ap.parse_args()

    urllib.request.urlopen(urllib.request.Request(args.base + "/api/admin/perf", data=b"", headers={"X-MYBOOKS-TOKEN": args.token}))

    stop = threading.Event()
    load_results = []
    threads = []
    for name in args.scenario.split(","):
        paths = scenario_paths(name.strip(), args.book)
        for _ in range(args.concurrency):
            t = threading.Thread(target=worker, args=(args.base, args.token, paths, stop, load_results), daemon=True)
            t.start()
            threads.append(t)

    probe = []
    end = time.time() + args.duration
    while time.time() < end:
        probe.append(fetch(args.base, "/api/user/info", args.token, timeout=30)[1])
        time.sleep(args.probe_interval)
    stop.set()
    for t in threads:
        t.join(timeout=70)

    print("== 探针 /api/user/info (%d 次) ==" % len(probe))
    print("p50=%.0fms p95=%.0fms max=%.0fms mean=%.0fms" % (percentile(probe, 0.5), percentile(probe, 0.95), max(probe), statistics.mean(probe)))
    print("== 负载请求 ==")
    by_path = {}
    for path, status, ms in load_results:
        by_path.setdefault(path, []).append((status, ms))
    for path, rows in sorted(by_path.items()):
        times = [m for _, m in rows]
        errs = sum(1 for s, _ in rows if s != 200 and s != 206)
        print("%-40s n=%-4d err=%-3d p50=%.0f p95=%.0f max=%.0f" % (path[:40], len(rows), errs, percentile(times, 0.5), percentile(times, 0.95), max(times)))

    req = urllib.request.Request(args.base + "/api/admin/perf", headers={"X-MYBOOKS-TOKEN": args.token})
    with urllib.request.urlopen(req) as rsp:
        perf = json.loads(rsp.read())["perf"]
    print("== 服务端 /api/admin/perf ==")
    print("loop_lag_ms:", perf["loop_lag_ms"], "stall_total:", perf["stall_total"])
    print("calibre:", json.dumps(perf["calibre"], ensure_ascii=False))
    for s in perf["stalls"][-5:]:
        print("--- stall %sms @ %s ---\n%s" % (s["stalled_ms"], s["time"], s["stack"]))


if __name__ == "__main__":
    main()
