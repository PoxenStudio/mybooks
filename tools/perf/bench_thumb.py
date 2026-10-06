#!/usr/bin/env python3
"""封面缩放算法基准：对比 calibre 现状（Qt Smooth+画布+optimize）与 Pillow 各方案。

用法（建议在 RK3568 容器内执行，PyQt5/Pillow 随 calibre 环境提供）:
    python3 bench_thumb.py [--size 240x320] [--cover a.jpg --cover b.jpg ...]
不传 --cover 时用合成的 800x1200/1600x2400/3000x4500 JPEG。
"""
import argparse
import io
import os
import random
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw  # noqa: E402
from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PyQt5.QtGui import QColor, QImage, QImageWriter, QPainter  # noqa: E402


def make(width, height):
    random.seed(1)
    im = Image.linear_gradient("L").resize((width, height)).convert("RGB")
    draw = ImageDraw.Draw(im)
    for _ in range(80):
        x0, x1 = sorted((random.randint(0, width), random.randint(0, width)))
        y0, y1 = sorted((random.randint(0, height), random.randint(0, height)))
        draw.rectangle([x0, y0, x1, y1], fill=tuple(random.randint(0, 255) for _ in range(3)))
    im = Image.blend(im, Image.effect_noise((width, height), 40).convert("RGB"), 0.25)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def fit(ow, oh, w, h):
    ratio = min(w / ow, h / oh)
    return ratio < 1, max(1, int(ow * ratio)), max(1, int(oh * ratio))


def qt_encode(img, quality=83, optimized=False):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    writer = QImageWriter(buf, b"JPEG")
    writer.setOptimizedWrite(optimized)
    writer.setQuality(quality)
    writer.write(img)
    return ba.data()


def calibre_like(data, w, h, optimized=True, canvas=True):
    img = QImage()
    img.loadFromData(data)
    scaled, nw, nh = fit(img.width(), img.height(), w, h)
    if scaled:
        img = img.scaled(nw, nh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    if canvas:
        base = QImage(img.width(), img.height(), QImage.Format_RGB32)
        base.fill(QColor("#ffffff"))
        painter = QPainter(base)
        painter.drawImage(0, 0, img)
        painter.end()
        img = base
    return qt_encode(img, optimized=optimized)


def qt_fast(data, w, h):
    img = QImage()
    img.loadFromData(data)
    scaled, nw, nh = fit(img.width(), img.height(), w, h)
    if scaled:
        img = img.scaled(nw, nh, Qt.IgnoreAspectRatio, Qt.FastTransformation)
    return qt_encode(img)


def pil(data, w, h, resample, draft=False, gap=None):
    im = Image.open(io.BytesIO(data))
    if draft and im.format == "JPEG":
        im.draft("RGB", (w * 2, h * 2))
    if im.mode != "RGB":
        im = im.convert("RGB")
    im.thumbnail((w, h), resample, reducing_gap=gap)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=83)
    return out.getvalue()


def bench(fn, rounds=12):
    fn()
    start = time.perf_counter()
    for _ in range(rounds):
        result = fn()
    return (time.perf_counter() - start) / rounds * 1000, len(result)


def run(label, data, w, h):
    print(f"\n{label} JPEG {len(data) // 1024}KB -> {w}x{h}")
    rows = [
        ("calibre 现状(Qt Smooth+画布+optimize)", lambda: calibre_like(data, w, h)),
        ("Qt Smooth 去画布/optimize", lambda: calibre_like(data, w, h, optimized=False, canvas=False)),
        ("Qt Fast(最近邻)", lambda: qt_fast(data, w, h)),
        ("Pillow LANCZOS", lambda: pil(data, w, h, Image.LANCZOS)),
        ("Pillow BILINEAR", lambda: pil(data, w, h, Image.BILINEAR)),
        ("Pillow BILINEAR+draft+gap2", lambda: pil(data, w, h, Image.BILINEAR, True, 2.0)),
        ("Pillow BOX+draft", lambda: pil(data, w, h, Image.BOX, True)),
        ("Pillow LANCZOS+draft+gap2", lambda: pil(data, w, h, Image.LANCZOS, True, 2.0)),
    ]
    base = None
    for name, fn in rows:
        ms, size = bench(fn)
        base = base or ms
        print(f"  {name:38s} {ms:7.1f}ms  x{base / ms:4.1f}  {size // 1024}KB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="240x320")
    ap.add_argument("--cover", action="append", default=[])
    args = ap.parse_args()
    w, h = (int(x) for x in args.size.split("x"))
    if args.cover:
        for path in args.cover:
            with open(path, "rb") as f:
                run(os.path.basename(path), f.read(), w, h)
    else:
        for width, height in ((800, 1200), (1600, 2400), (3000, 4500)):
            run(f"合成 {width}x{height}", make(width, height), w, h)


if __name__ == "__main__":
    main()
