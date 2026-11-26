#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评估 PDF/图片处理后的画质：无参考噪声指标、可选的有参考指标，以及基线对比。

用法：
    python pdf_quality_report.py processed.pdf
    python pdf_quality_report.py processed.pdf --reference source.pdf --json report.json
    python pdf_quality_report.py processed_new.pdf --reference source.pdf --baseline processed_old.pdf --csv report.csv

指标（逐页）：
    ink_ratio              墨量比：二值化后墨像素占比
    background_noise       背景噪声：背景区域 Laplacian 响应的 Immerkaer 估计
    speck_density          孤立墨点密度：3x3 邻域内墨像素 <= 2 的墨点，每百万像素个数
    broken_stroke_ratio    断笔率：3x3 闭运算新增的墨像素 / 原墨像素
    gradient_mean          平均梯度：模糊降低、噪声抬高
    psnr / ssim            与参考图的保真度（需要 --reference）
    ink_precision/recall/f1 墨迹重合度（需要 --reference）
    encoded_kb/bits_per_pixel 每页编码体积

依赖 numpy；Pillow 需支持输出 PDF 的图片编码（JPEG 2000 等）。
"""

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import fitz
import numpy as np
from PIL import Image
from PIL import ImageFilter

try:
    from .pdf_image_processor import otsu_threshold
except ImportError:
    from pdf_image_processor import otsu_threshold

DEFAULT_RENDER_DPI = 150
BACKGROUND_BRIGHTNESS = 200
SPEC_MAX_NEIGHBOR_INK = 2
SSIM_WINDOW = 8
SSIM_C1 = (0.01 * 255) ** 2
SSIM_C2 = (0.03 * 255) ** 2

METRIC_KEYS = (
    "ink_ratio",
    "background_noise",
    "speck_density",
    "broken_stroke_ratio",
    "gradient_mean",
    "psnr",
    "ssim",
    "ink_precision",
    "ink_recall",
    "ink_f1",
)


@dataclass
class PageImage:
    index: int
    image: Image.Image
    encoded_bytes: Optional[int] = None


def _finite(value: Optional[float]) -> Optional[float]:
    if value is None or not math.isfinite(value):
        return None
    return value


def _render_page_image(page: fitz.Page, target_size: Optional[tuple[int, int]] = None) -> Image.Image:
    if target_size is not None and page.rect.width > 0 and page.rect.height > 0:
        scale_x = target_size[0] / page.rect.width
        scale_y = target_size[1] / page.rect.height
    else:
        scale_x = scale_y = DEFAULT_RENDER_DPI / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(scale_x, scale_y), alpha=False)
    mode = "RGB" if pix.n >= 3 else "L"
    return Image.frombytes(mode, (pix.width, pix.height), pix.samples)


def _page_embedded_image(doc: fitz.Document, page: fitz.Page) -> Optional[tuple[Image.Image, int]]:
    """Return the single full-page embedded image without re-rendering the page."""
    images = page.get_images(full=True)
    if len(images) != 1:
        return None
    xref = images[0][0]
    page_area = page.rect.width * page.rect.height
    covered = sum(rect.width * rect.height for rect in page.get_image_rects(xref))
    if page_area <= 0 or covered / page_area < 0.9:
        return None
    try:
        pix = fitz.Pixmap(doc, xref)
        if pix.alpha:
            pix = fitz.Pixmap(pix, 0)
        colorspace = pix.colorspace
        standard = colorspace is not None and colorspace.name in ("DeviceGray", "DeviceRGB", "ICCBased")
        if colorspace is None or colorspace.n not in (1, 3) or not standard:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        mode = "L" if pix.n == 1 else "RGB"
        image = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
        encoded = len(doc.xref_stream_raw(xref))
    except Exception:
        return None
    return image, encoded


class PageImageSource:
    """按页读取图片；PDF 优先取嵌入图像，参考图按目标像素尺寸渲染。"""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        if not self.path.exists():
            raise FileNotFoundError(f"Input not found: {self.path}")
        self._file_size = self.path.stat().st_size
        self._doc: Optional[fitz.Document] = None
        self._image: Optional[Image.Image] = None
        if self.path.suffix.lower() == ".pdf":
            self._doc = fitz.open(str(self.path))
            if len(self._doc) == 0:
                self._doc.close()
                raise ValueError(f"PDF has no pages: {self.path}")
        else:
            with Image.open(self.path) as source:
                self._image = source.copy()

    def __len__(self) -> int:
        return len(self._doc) if self._doc is not None else 1

    def load(
        self,
        index: int,
        target_size: Optional[tuple[int, int]] = None,
        embedded: bool = False,
    ) -> PageImage:
        if self._doc is None:
            assert self._image is not None
            image = self._image
            if target_size is not None and image.size != tuple(target_size):
                image = image.resize(tuple(target_size), resample=Image.Resampling.LANCZOS)
            return PageImage(index, image, self._file_size if embedded else None)

        page = self._doc.load_page(index)
        if embedded:
            extracted = _page_embedded_image(self._doc, page)
            if extracted is not None:
                return PageImage(index, extracted[0], extracted[1])
        return PageImage(index, _render_page_image(page, target_size), None)

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None


def _window_sum(values: np.ndarray, window: int) -> np.ndarray:
    """Sum over window x window neighborhoods using an integral image."""
    pad_before = window // 2
    padded = np.pad(
        values,
        ((pad_before, window - 1 - pad_before), (pad_before, window - 1 - pad_before)),
        mode="edge",
    )
    integral = np.zeros((padded.shape[0] + 1, padded.shape[1] + 1), dtype=np.float64)
    integral[1:, 1:] = padded.cumsum(axis=0).cumsum(axis=1)
    height, width = values.shape
    return (
        integral[window : window + height, window : window + width]
        - integral[0:height, window : window + width]
        - integral[window : window + height, 0:width]
        + integral[0:height, 0:width]
    )


def _ssim(reference: np.ndarray, processed: np.ndarray) -> float:
    """Mean SSIM with uniform window x window blocks."""
    window = min(SSIM_WINDOW, reference.shape[0], reference.shape[1])
    if window < 2:
        return float("nan")
    count = window * window
    mean_ref = _window_sum(reference, window) / count
    mean_proc = _window_sum(processed, window) / count
    var_ref = np.maximum(_window_sum(reference * reference, window) / count - mean_ref**2, 0)
    var_proc = np.maximum(_window_sum(processed * processed, window) / count - mean_proc**2, 0)
    covariance = _window_sum(reference * processed, window) / count - mean_ref * mean_proc
    numerator = (2 * mean_ref * mean_proc + SSIM_C1) * (2 * covariance + SSIM_C2)
    denominator = (mean_ref**2 + mean_proc**2 + SSIM_C1) * (var_ref + var_proc + SSIM_C2)
    return float(np.mean(numerator / denominator))


def _background_noise(gray: np.ndarray, ink: np.ndarray) -> Optional[float]:
    """Immerkaer noise sigma computed from the Laplacian response on paper pixels."""
    paper = (gray >= BACKGROUND_BRIGHTNESS) & ~ink
    if np.count_nonzero(paper) < 1000:
        return None
    mask = Image.fromarray((paper * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3))
    interior = np.asarray(mask) > 0
    if np.count_nonzero(interior) < 1000:
        return None

    response = np.zeros_like(gray)
    response[1:-1, 1:-1] = (
        gray[:-2, :-2]
        - 2 * gray[:-2, 1:-1]
        + gray[:-2, 2:]
        - 2 * gray[1:-1, :-2]
        + 4 * gray[1:-1, 1:-1]
        - 2 * gray[1:-1, 2:]
        + gray[2:, :-2]
        - 2 * gray[2:, 1:-1]
        + gray[2:, 2:]
    )
    return float(math.sqrt(math.pi / 2) / 6 * np.mean(np.abs(response[interior])))


def _speck_density(ink: np.ndarray) -> float:
    """Isolated ink pixels (3x3 neighborhood ink count <= threshold) per megapixel."""
    total = ink.size
    if total == 0:
        return 0.0
    padded = np.pad(ink.astype(np.uint8), 1)
    neighbors = np.zeros_like(ink, dtype=np.uint8)
    for dy in range(3):
        for dx in range(3):
            neighbors += padded[dy : dy + ink.shape[0], dx : dx + ink.shape[1]]
    specks = int(np.count_nonzero(ink & (neighbors <= SPEC_MAX_NEIGHBOR_INK)))
    return specks / (total / 1_000_000)


def _broken_stroke_ratio(ink: np.ndarray) -> float:
    """Pixels added by a 3x3 closing, relative to the ink pixel count."""
    ink_pixels = int(np.count_nonzero(ink))
    if ink_pixels == 0:
        return 0.0
    mask = Image.fromarray((ink * 255).astype(np.uint8))
    closed = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    added = int(np.count_nonzero((np.asarray(closed) > 0) & ~ink))
    return added / ink_pixels


def _gradient_mean(gray: np.ndarray) -> float:
    horizontal = np.abs(np.diff(gray, axis=1)).mean() if gray.shape[1] > 1 else 0.0
    vertical = np.abs(np.diff(gray, axis=0)).mean() if gray.shape[0] > 1 else 0.0
    return float((horizontal + vertical) / 2)


def _psnr(reference: np.ndarray, processed: np.ndarray) -> float:
    mse = float(np.mean((reference - processed) ** 2))
    if mse <= 1e-10:
        return float("inf")
    return 10 * math.log10(255**2 / mse)


def _ink_scores(reference_ink: np.ndarray, processed_ink: np.ndarray) -> tuple[Optional[float], ...]:
    reference_pixels = int(np.count_nonzero(reference_ink))
    processed_pixels = int(np.count_nonzero(processed_ink))
    if reference_pixels == 0 or processed_pixels == 0:
        return None, None, None
    overlap = int(np.count_nonzero(reference_ink & processed_ink))
    precision = overlap / processed_pixels
    recall = overlap / reference_pixels
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def evaluate_page(
    image: Image.Image,
    reference: Optional[Image.Image] = None,
    encoded_bytes: Optional[int] = None,
) -> dict:
    gray_image = image.convert("L")
    gray = np.asarray(gray_image, dtype=np.float64)
    ink = gray <= otsu_threshold(gray_image)

    row = {
        "width": image.width,
        "height": image.height,
        "ink_ratio": float(np.mean(ink)),
        "background_noise": _background_noise(gray, ink),
        "speck_density": _speck_density(ink),
        "broken_stroke_ratio": _broken_stroke_ratio(ink),
        "gradient_mean": _gradient_mean(gray),
        "psnr": None,
        "ssim": None,
        "ink_precision": None,
        "ink_recall": None,
        "ink_f1": None,
        "encoded_kb": encoded_bytes / 1024 if encoded_bytes else None,
        "bits_per_pixel": encoded_bytes * 8 / (image.width * image.height) if encoded_bytes else None,
    }

    if reference is not None:
        if reference.size != image.size:
            reference = reference.resize(image.size, resample=Image.Resampling.LANCZOS)
        reference_image = reference.convert("L")
        reference_gray = np.asarray(reference_image, dtype=np.float64)
        reference_ink = reference_gray <= otsu_threshold(reference_image)
        row["psnr"] = _finite(_psnr(reference_gray, gray))
        row["ssim"] = _finite(_ssim(reference_gray, gray))
        precision, recall, f1 = _ink_scores(reference_ink, ink)
        row["ink_precision"] = precision
        row["ink_recall"] = recall
        row["ink_f1"] = f1

    return row


def summarize(rows: list[dict]) -> dict:
    summary: dict = {"pages": len(rows)}
    for key in METRIC_KEYS:
        values = [row[key] for row in rows if row.get(key) is not None]
        summary[f"avg_{key}"] = float(np.mean(values)) if values else None
    total_kb = sum(row["encoded_kb"] for row in rows if row.get("encoded_kb") is not None)
    summary["total_encoded_kb"] = total_kb if total_kb else None
    summary["encoded_kb_per_page"] = total_kb / len(rows) if rows and total_kb else None
    return summary


def _fmt(value: Optional[float], digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _percent(value: Optional[float], digits: int = 2) -> str:
    return "-" if value is None else f"{value * 100:.{digits}f}"


def _print_rows(rows: list[dict]) -> None:
    print(
        f"{'page':>4} {'size':>11} {'ink%':>6} {'noise':>6} {'spk/Mpx':>7} "
        f"{'broken%':>7} {'grad':>6} {'psnr':>6} {'ssim':>5} {'inkF1':>5} {'KB':>7}"
    )
    for row in rows:
        size = f"{row['width']}x{row['height']}"
        print(
            f"{row['page']:>4} {size:>11}"
            f" {_fmt(row['ink_ratio'] * 100):>6}"
            f" {_fmt(row['background_noise']):>6}"
            f" {_fmt(row['speck_density']):>7}"
            f" {_fmt(row['broken_stroke_ratio'] * 100):>7}"
            f" {_fmt(row['gradient_mean']):>6}"
            f" {_fmt(row['psnr']):>6}"
            f" {_fmt(row['ssim'], 3):>5}"
            f" {_fmt(row['ink_f1'], 3):>5}"
            f" {_fmt(row['encoded_kb'], 1):>7}"
        )


def _print_summary(title: str, summary: dict) -> None:
    psnr = summary["avg_psnr"]
    parts = [
        f"pages={summary['pages']}",
        f"ink={_percent(summary['avg_ink_ratio'])}%",
        f"noise={_fmt(summary['avg_background_noise'])}",
        f"specks={_fmt(summary['avg_speck_density'])}/Mpx",
        f"broken={_percent(summary['avg_broken_stroke_ratio'])}%",
        f"grad={_fmt(summary['avg_gradient_mean'])}",
        f"psnr={_fmt(psnr)}" + ("dB" if psnr is not None else ""),
        f"ssim={_fmt(summary['avg_ssim'], 3)}",
        f"inkF1={_fmt(summary['avg_ink_f1'], 3)}",
        f"KB/page={_fmt(summary['encoded_kb_per_page'], 1)}",
    ]
    print(f"{title}: " + ", ".join(parts))


def _print_comparison(processed: dict, baseline: dict) -> None:
    keys = [
        ("avg_background_noise", "noise sigma"),
        ("avg_speck_density", "specks/Mpx"),
        ("avg_broken_stroke_ratio", "broken ratio"),
        ("avg_gradient_mean", "gradient"),
        ("avg_psnr", "PSNR"),
        ("avg_ssim", "SSIM"),
        ("avg_ink_f1", "ink F1"),
        ("encoded_kb_per_page", "KB/page"),
    ]
    print(f"{'metric':<14}{'processed':>10}{'baseline':>10}{'delta':>10}")
    for key, label in keys:
        current = processed.get(key)
        previous = baseline.get(key)
        delta = current - previous if current is not None and previous is not None else None
        print(f"{label:<14}{_fmt(current, 3):>10}{_fmt(previous, 3):>10}{_fmt(delta, 3):>10}")


def _flatten_with_baseline(rows: list[dict], baseline_rows: list[dict]) -> list[dict]:
    baseline_by_page = {row["page"]: row for row in baseline_rows}
    flattened = []
    for row in rows:
        merged = dict(row)
        baseline = baseline_by_page.get(row["page"], {})
        for key in ("encoded_kb", "bits_per_pixel", *METRIC_KEYS):
            merged[f"baseline_{key}"] = baseline.get(key)
        flattened.append(merged)
    return flattened


def _write_json(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate image quality of a processed PDF or image.")
    parser.add_argument("processed", help="Processed PDF or image to evaluate")
    parser.add_argument("--reference", default=None, help="Original PDF or image for PSNR/SSIM/ink scores")
    parser.add_argument("--baseline", default=None, help="Another processed file to compare against")
    parser.add_argument("--json", dest="json_path", default=None, help="Write a JSON report to this path")
    parser.add_argument("--csv", dest="csv_path", default=None, help="Write a CSV report to this path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    processed_source = PageImageSource(Path(args.processed))
    reference_source = PageImageSource(Path(args.reference)) if args.reference else None
    baseline_source = PageImageSource(Path(args.baseline)) if args.baseline else None

    try:
        processed_pages = len(processed_source)
        if reference_source is not None and len(reference_source) != processed_pages:
            print(
                f"Warning: reference has {len(reference_source)} page(s), processed has {processed_pages}; "
                "comparing overlapping pages only."
            )
        if baseline_source is not None and len(baseline_source) < processed_pages:
            print(
                f"Warning: baseline has {len(baseline_source)} page(s), processed has {processed_pages}; "
                "comparing overlapping pages only."
            )

        rows = []
        baseline_rows = []
        for index in range(processed_pages):
            page = processed_source.load(index, embedded=True)
            reference = None
            if reference_source is not None and index < len(reference_source):
                reference = reference_source.load(index, target_size=page.image.size).image
            rows.append({"page": index + 1, **evaluate_page(page.image, reference, page.encoded_bytes)})

            if baseline_source is not None and index < len(baseline_source):
                baseline_page = baseline_source.load(index, embedded=True)
                baseline_rows.append(
                    {"page": index + 1, **evaluate_page(baseline_page.image, reference, baseline_page.encoded_bytes)}
                )
    finally:
        processed_source.close()
        if reference_source is not None:
            reference_source.close()
        if baseline_source is not None:
            baseline_source.close()

    summary = summarize(rows)
    _print_rows(rows)
    _print_summary("Summary", summary)

    baseline_summary = None
    if baseline_rows:
        baseline_summary = summarize(baseline_rows)
        _print_summary("Baseline", baseline_summary)
        _print_comparison(summary, baseline_summary)

    if args.json_path:
        report = {
            "processed": str(processed_source.path),
            "reference": str(reference_source.path) if reference_source is not None else None,
            "baseline": str(baseline_source.path) if baseline_source is not None else None,
            "summary": summary,
            "pages": rows,
        }
        if baseline_rows:
            report["baseline_summary"] = baseline_summary
            report["baseline_pages"] = baseline_rows
        _write_json(Path(args.json_path), report)
        print(f"Saved JSON report: {args.json_path}")

    if args.csv_path:
        csv_rows = _flatten_with_baseline(rows, baseline_rows) if baseline_rows else rows
        _write_csv(Path(args.csv_path), csv_rows)
        print(f"Saved CSV report: {args.csv_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
