#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import argparse
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PARTS = ("reader", "writer")


def build(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    targets = []
    for part in PARTS:
        target = os.path.join(out_dir, "djvu_meta_%s.zip" % part)
        src = os.path.join(HERE, part)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(os.listdir(src)):
                path = os.path.join(src, name)
                if os.path.isfile(path) and not name.endswith((".pyc", ".pyo")):
                    zf.write(path, name)
            zf.write(os.path.join(HERE, "core.py"), "core.py")
        targets.append(target)
    return targets


def main():
    parser = argparse.ArgumentParser(description="Build DjVu metadata calibre plugins")
    parser.add_argument("--out", default=os.path.join(os.path.dirname(HERE), "dist"), help="output directory")
    args = parser.parse_args()
    for target in build(args.out):
        print(target)


if __name__ == "__main__":
    main()
