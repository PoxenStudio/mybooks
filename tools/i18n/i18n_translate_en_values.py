#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import argparse
import json
import re
import socket
import time
from deep_translator import MyMemoryTranslator

PATH = "webserver/i18n/en.json"

cjk_re = re.compile(r"[\u4e00-\u9fff]")
# Keep Python %-format placeholders and strftime placeholders intact.
ph_re = re.compile(r"%(?:\([^)]+\))?[#0\- +]?\d*(?:\.\d+)?[a-zA-Z]")

special_map = {
    "%Y年": "%Y",
    "%Y年%m月": "%Y-%m",
    "%Y年%m月%d日": "%Y-%m-%d",
}


def mask_placeholders(text):
    holders = []

    def repl(m):
        token = f"__PH_{len(holders)}__"
        holders.append((token, m.group(0)))
        return token

    masked = ph_re.sub(repl, text)
    return masked, holders


def unmask(text, holders):
    for token, val in holders:
        text = text.replace(token, val)
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default=PATH)
    parser.add_argument("--max-items", type=int, default=80)
    parser.add_argument("--sleep", type=float, default=0.05)
    args = parser.parse_args()

    # Prevent network calls from hanging forever.
    socket.setdefaulttimeout(12)

    with open(args.path, "r", encoding="utf-8") as f:
        data = json.load(f)

    translator = MyMemoryTranslator(source="zh-CN", target="en-US")

    candidates = [
        (k, v)
        for k, v in data.items()
        if isinstance(v, str) and cjk_re.search(v)
    ]

    updated = 0
    failed = []

    for idx, (k, v) in enumerate(candidates[: args.max_items], start=1):
        if v in special_map:
            nv = special_map[v]
            if nv != v:
                data[k] = nv
                updated += 1
            print(f"[{idx}/{min(len(candidates), args.max_items)}] mapped: {k}")
            continue

        masked, holders = mask_placeholders(v)
        tries = 0
        translated = None
        while tries < 2:
            tries += 1
            try:
                translated = translator.translate(masked)
                break
            except Exception:
                time.sleep(0.5 * tries)

        if not translated:
            failed.append((k, v))
            print(f"[{idx}/{min(len(candidates), args.max_items)}] failed: {k}")
            continue

        translated = unmask(translated, holders).strip()
        if not translated:
            failed.append((k, v))
            print(f"[{idx}/{min(len(candidates), args.max_items)}] empty: {k}")
            continue

        data[k] = translated
        updated += 1
        print(f"[{idx}/{min(len(candidates), args.max_items)}] ok: {k}")
        time.sleep(args.sleep)

    with open(args.path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")

    remaining = [
        (k, v) for k, v in data.items() if isinstance(v, str) and cjk_re.search(v)
    ]
    print("updated", updated)
    print("failed", len(failed))
    print("remaining_cn_values", len(remaining))
    if failed:
        print("failed_sample")
        for fk, fv in failed[:10]:
            print(fk, "=>", fv)


if __name__ == "__main__":
    main()
