#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import argparse
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PARTS = ("reader", "writer")


def plugin_names():
    return sorted(
        name for name in os.listdir(HERE)
        if os.path.isfile(os.path.join(HERE, name, "core.py")) and any(os.path.isdir(os.path.join(HERE, name, part)) for part in PARTS)
    )


def build(out_dir, names=None):
    os.makedirs(out_dir, exist_ok=True)
    targets = []
    for name in names or plugin_names():
        root = os.path.join(HERE, name)
        for part in PARTS:
            src = os.path.join(root, part)
            if not os.path.isdir(src):
                continue
            target = os.path.join(out_dir, "%s_%s.zip" % (name, part))
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
                for entry in sorted(os.listdir(src)):
                    path = os.path.join(src, entry)
                    if os.path.isfile(path) and not entry.endswith((".pyc", ".pyo")):
                        zf.write(path, entry)
                zf.write(os.path.join(root, "core.py"), "core.py")
            targets.append(target)
    return targets


def main():
    parser = argparse.ArgumentParser(description="Build MyBooks calibre plugins")
    parser.add_argument("--out", default=os.path.join(HERE, "dist"), help="output directory")
    parser.add_argument("names", nargs="*", help="plugin directories to build (default: all)")
    args = parser.parse_args()
    for target in build(args.out, args.names):
        print(target)


if __name__ == "__main__":
    main()
