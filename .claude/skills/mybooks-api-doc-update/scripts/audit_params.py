#!/usr/bin/env python3
"""
Heuristic cross-check of documented parameters vs. handler code.

For every entry in document/WebAPI.md that has a "**路径**" line, find the
route's handler class and compare the parameter names documented in that entry
(bullets like "- `name` (...)") with the names the handler reads
(get_argument / data.get / req.get / request.files ...).

Usage (repo root):
    python3 .claude/skills/mybooks-api-doc-update/scripts/audit_params.py

Output: one line per entry with differences:
    doc-only  = documented but never read by the handler (renamed/removed param?)
    code-only = read by the handler but not documented (missing param?)

It is noisy by design — response fields also look like "doc-only", and params
written inline ("JSON Body：`x`") or inherited from a base class are missed.
Treat each line as a pointer to go read the handler, not as a verdict.
"""

import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import list_routes as L  # noqa: E402

PATTERNS = [
    r'get_(?:query_|body_)?argument[s]?\(\s*["\'](\w+)',
    r'\b(?:data|req|body|payload|params|args|request_data|json_data)\.get\(\s*["\'](\w+)',
    r'\b(?:data|req|body|payload)\[\s*["\'](\w+)',
    r'request\.files(?:\.get\(|\[)\s*["\'](\w+)',
]


def handler_sources():
    out = {}
    for f in glob.glob(os.path.join(L.HANDLERS, "*.py")):
        src = open(f, encoding="utf-8").read()
        for m in re.finditer(r"^class (\w+)\b.*?(?=^class |^def routes|\Z)", src, re.S | re.M):
            out[m.group(1)] = m.group(0)
    return out


def main():
    sources = handler_sources()
    routes = {}
    for r in L.parse_routes(True):
        routes.setdefault(L.normalize(r["path"]), r)
    doc = open(L.DOC, encoding="utf-8").read()
    for entry in re.split(r"(?m)^(?=#{3,4} )", doc):
        paths = [L.normalize(m.group(2)) for line in entry.splitlines() if "**路径**" in line for m in L.DOC_PATH_RE.finditer(line)]
        if not paths:
            continue
        head = entry.splitlines()[0]
        documented = set(re.findall(r"^\s*- `(\w+)` \(", entry, re.M)) | set(re.findall(r"`(\w+)` \([a-z\[\]|]+, ", entry))
        for path in paths:
            r = routes.get(path)
            if not r:
                continue
            body = sources.get(r["handler"], "")
            code = set()
            for p in PATTERNS:
                code |= set(re.findall(p, body))
            doc_only = {x for x in documented - code if f"`{x}` (path" not in entry}
            code_only = code - documented - set(re.findall(r"`(\w+)`", entry))
            if doc_only or code_only:
                print(f"{head[:40]:<40} {path:<42} doc-only={sorted(doc_only)} code-only={sorted(code_only)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
