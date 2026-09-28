#!/usr/bin/env python3
"""
List MyBooks HTTP routes from webserver/handlers/*.py and check which ones are
documented in document/WebAPI.md.

Usage (from repo root):
    python3 .claude/skills/mybooks-api-doc-update/scripts/list_routes.py            # all routes + doc status
    python3 .claude/skills/mybooks-api-doc-update/scripts/list_routes.py --missing  # only undocumented
    python3 .claude/skills/mybooks-api-doc-update/scripts/list_routes.py --stale    # documented paths no longer routed
    python3 .claude/skills/mybooks-api-doc-update/scripts/list_routes.py --json

Only static analysis (regex over source) — no server/Calibre import needed.
For each route it reports: module, handler class, HTTP methods implemented by
the class, and the auth decorators on each method (auth / is_admin / js).
"""

import argparse
import glob
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
HANDLERS = os.path.join(ROOT, "webserver", "handlers")
DOC = os.path.join(ROOT, "document", "WebAPI.md")

ROUTE_RE = re.compile(r"""\(\s*r?["'](/[^"']*)["']\s*,\s*([A-Za-z_][\w.]*)""")
CLASS_RE = re.compile(r"^class\s+(\w+)\s*\(([^)]*)\)\s*:", re.M)
METHOD_RE = re.compile(r"((?:^[ \t]+@[\w.]+(?:\(.*\))?\s*\n)*)^[ \t]+(?:async\s+)?def\s+(get|post|put|delete|patch)\s*\(", re.M)
COMPACT_ENTRY_RE = re.compile(r"^\s*[-*] `(?:GET|POST|PUT|DELETE|PATCH)(?: / ?(?:GET|POST|PUT|DELETE|PATCH))* /")
DOC_PATH_RE = re.compile(r"`((?:GET|POST|PUT|DELETE|PATCH)\s+)?(/[^`\s]+)`")
# 只关心 JSON API；OPDS/静态/页面等非 /api 路由用 --all 查看
API_PREFIXES = ("/api/",)


def normalize(path):
    """Regex route or documented path -> comparable skeleton ('*' for any param)."""
    path = path.split("?")[0]
    path = path.replace("\\.", ".")
    path = re.sub(r"\((?:[^()]|\([^()]*\))*\)", "*", path)  # regex groups (one nesting level)
    path = re.sub(r"<[^>]+>|\{[^}]+\}|:\w+", "*", path)  # doc placeholders
    path = path.replace("\\.", ".").replace("/?", "").rstrip("$").rstrip("/")
    path = re.sub(r"\*+", "*", path)
    path = path.replace("*.*", "*")  # /api/book/<id>.<ext> 与路由 ([0-9]+\..+) 视为同一路径
    return path or "/"


def parse_classes():
    classes = {}
    for f in sorted(glob.glob(os.path.join(HANDLERS, "*.py"))):
        src = open(f, encoding="utf-8").read()
        starts = [(m.start(), m.group(1), m.group(2)) for m in CLASS_RE.finditer(src)]
        for i, (pos, name, bases) in enumerate(starts):
            end = starts[i + 1][0] if i + 1 < len(starts) else len(src)
            body = src[pos:end]
            methods = {}
            for m in METHOD_RE.finditer(body):
                decos = re.findall(r"@([\w.]+)", m.group(1))
                methods[m.group(2).upper()] = decos
            classes[name] = {"module": os.path.basename(f), "bases": [b.strip() for b in bases.split(",")], "methods": methods}
    # 继承父类方法（同文件/跨文件的简单单继承）
    for name, info in classes.items():
        seen = set()
        bases = list(info["bases"])
        while bases:
            b = bases.pop(0).split(".")[-1]
            if b in seen or b not in classes:
                continue
            seen.add(b)
            for k, v in classes[b]["methods"].items():
                info["methods"].setdefault(k, v)
            bases += classes[b]["bases"]
    return classes


def parse_routes(include_all):
    routes = []
    for f in sorted(glob.glob(os.path.join(HANDLERS, "*.py"))):
        src = open(f, encoding="utf-8").read()
        for m in ROUTE_RE.finditer(src):
            path, handler = m.group(1), m.group(2).split(".")[-1]
            if not include_all and not path.startswith(API_PREFIXES):
                continue
            routes.append({"path": path, "handler": handler, "module": os.path.basename(f)})
    return routes


def doc_paths():
    text = open(DOC, encoding="utf-8").read()
    paths = set()
    # 只认各接口条目的"**路径**"行，以及紧凑写法的"- `METHOD /api/...`"条目，
    # 避免正文示例里的 /api/... 被当成已文档化路径
    for line in text.splitlines():
        if "**路径**" not in line and not COMPACT_ENTRY_RE.match(line):
            continue
        for m in DOC_PATH_RE.finditer(line):
            paths.add(normalize(m.group(2)))
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--missing", action="store_true", help="only routes not found in WebAPI.md")
    ap.add_argument("--stale", action="store_true", help="documented /api paths without a matching route")
    ap.add_argument("--all", action="store_true", help="include non-/api routes (opds, static, pages...)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    classes = parse_classes()
    routes = parse_routes(args.all)
    documented = doc_paths()

    if args.stale:
        routed = {normalize(r["path"]) for r in parse_routes(True)}
        stale = sorted(p for p in documented if p.startswith("/api") and p not in routed)
        print(json.dumps(stale, ensure_ascii=False, indent=2) if args.json else "\n".join(stale))
        return 0

    rows = []
    for r in routes:
        info = classes.get(r["handler"], {})
        methods = info.get("methods", {})
        r["methods"] = {k: [d for d in v if d in ("auth", "is_admin", "js")] for k, v in methods.items()}
        r["documented"] = normalize(r["path"]) in documented
        if args.missing and r["documented"]:
            continue
        rows.append(r)

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    for r in rows:
        meth = " ".join(f"{k}[{','.join(v) or '-'}]" for k, v in sorted(r["methods"].items())) or "?"
        flag = "  " if r["documented"] else "✗ "
        print(f"{flag}{r['path']:<55} {r['handler']:<32} {r['module']:<18} {meth}")
    total = len(rows)
    missing = sum(1 for r in rows if not r["documented"])
    print(f"\n{total} routes listed, {missing} not documented in document/WebAPI.md", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
