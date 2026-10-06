#!/usr/bin/env python3
"""离线对比两份 baseline_probe.py 的 --json-out 结果（在开发机上运行，不需要连接服务器）。

用法: python3 compare_results.py before/baseline_cold.json after/baseline_cold.json [--min-ratio 0]
输出每个共有项目的 p50/p95 前后对比与倍数；--min-ratio 只显示倍数低于该值的项目（找回退）。
"""
import argparse
import json


def percentile(values, pct):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * pct))] if ordered else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--min-ratio", type=float, default=0, help="只显示 p50 倍数低于该值的项目，如 1.0 表示只看变慢的")
    args = ap.parse_args()
    with open(args.before, encoding="utf-8") as f:
        before = json.load(f)
    with open(args.after, encoding="utf-8") as f:
        after = json.load(f)
    print("之前：%s  %s" % (before["meta"]["time"], before["meta"]["base"]))
    print("之后：%s  %s" % (after["meta"]["time"], after["meta"]["base"]))
    print("%-44s %8s %8s %7s | %8s %8s %7s | %s" % ("项目", "p50前", "p50后", "倍数", "p95前", "p95后", "倍数", "失败 前→后"))
    for name, new in after["results"].items():
        old = before["results"].get(name)
        if not old:
            continue
        p50_old, p50_new = percentile(old["values"], 0.5), percentile(new["values"], 0.5)
        p95_old, p95_new = percentile(old["values"], 0.95), percentile(new["values"], 0.95)
        ratio50 = p50_old / p50_new if p50_new else 0
        ratio95 = p95_old / p95_new if p95_new else 0
        if args.min_ratio and ratio50 >= args.min_ratio:
            continue
        print("%-44s %8.0f %8.0f %6.1fx | %8.0f %8.0f %6.1fx | %d→%d" % (
            name[:44], p50_old, p50_new, ratio50, p95_old, p95_new, ratio95, old["fail"], new["fail"]))


if __name__ == "__main__":
    main()
