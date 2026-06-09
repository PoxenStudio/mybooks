#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

"""
Extract i18n strings from Python source and report/update missing entries in en catalog.

Usage:
  python tools/i18n_extract_missing.py
  python tools/i18n_extract_missing.py --update
"""

import argparse
import ast
import json
import os
from typing import Dict, List, Set


def is_python_file(path: str) -> bool:
    return path.endswith(".py")


def should_skip(path: str, excludes: List[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(normalized.startswith(prefix) for prefix in excludes)


def collect_py_files(root: str, excludes: List[str]) -> List[str]:
    files = []
    for base, _, names in os.walk(root):
        for name in names:
            path = os.path.join(base, name)
            rel = os.path.relpath(path).replace("\\", "/")
            if should_skip(rel, excludes):
                continue
            if is_python_file(path):
                files.append(path)
    files.sort()
    return files


def extract_i18n_strings_from_file(path: str) -> Set[str]:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    strings: Set[str] = set()
    try:
        tree = ast.parse(content, filename=path)
    except SyntaxError:
        return strings

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func

        # Match _("...")
        if isinstance(func, ast.Name) and func.id == "_" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                strings.add(first.value)

        # Match i18n._("...")
        if isinstance(func, ast.Attribute) and func.attr == "_" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                strings.add(first.value)

    return strings


def load_json(path: str) -> Dict[str, str]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {}
    return data


def save_json(path: str, data: Dict[str, str]):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Extract and update missing i18n entries")
    parser.add_argument("--source-dir", default="webserver")
    parser.add_argument("--catalog", default="webserver/i18n/en.json")
    parser.add_argument("--missing-output", default="webserver/i18n/missing_en.json")
    parser.add_argument("--exclude", action="append", default=["webserver/test/", "webserver/i18n/", "webserver/epub_to_audio/"])
    parser.add_argument("--update", action="store_true", help="Update en catalog with missing keys")
    parser.add_argument(
        "--default-value-mode",
        default="source",
        choices=["source", "todo"],
        help="source: use source text as default value; todo: prefix with TODO marker",
    )
    args = parser.parse_args()

    py_files = collect_py_files(args.source_dir, args.exclude)

    source_strings: Set[str] = set()
    for path in py_files:
        source_strings.update(extract_i18n_strings_from_file(path))

    catalog = load_json(args.catalog)
    missing = sorted([s for s in source_strings if s not in catalog])

    missing_map: Dict[str, str] = {}
    for key in missing:
        if args.default_value_mode == "todo":
            missing_map[key] = "TODO: " + key
        else:
            missing_map[key] = key

    save_json(args.missing_output, missing_map)

    if args.update and missing:
        catalog.update(missing_map)
        save_json(args.catalog, catalog)

    print(f"python_files={len(py_files)}")
    print(f"i18n_strings={len(source_strings)}")
    print(f"catalog_entries={len(catalog)}")
    print(f"missing={len(missing)}")
    print(f"missing_output={args.missing_output}")
    if args.update:
        print(f"catalog_updated={args.catalog}")


if __name__ == "__main__":
    main()
