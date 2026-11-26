#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单张图像的渲染后处理：缩放、去噪、对比度校正、形态学处理、模糊、二值化与灰度化。

用法：
    python pdf_image_processor.py input.png --bw --dilate 0.5 --output-dir output

参数与 minify_pdf.py 中对应的图像处理选项一致；处理结果以 PNG 保存到指定目录。
"""

import argparse
import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Optional

from PIL import Image
from PIL import ImageFilter
from PIL import ImageOps

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

MORPHOLOGY_SUPERSAMPLE_FACTOR = 2
ENABLE_OPENING = False
JPEG_SUFFIXES = {".jpg", ".jpeg"}


def otsu_threshold(gray_img: Image.Image) -> int:
    """Compute Otsu threshold from a grayscale image."""
    hist = gray_img.histogram()
    total = sum(hist)
    if total == 0:
        return 127

    sum_total = 0
    for i, count in enumerate(hist):
        sum_total += i * count

    sum_bg = 0
    weight_bg = 0
    var_max = -1.0
    threshold = 127

    for i, count in enumerate(hist):
        weight_bg += count
        if weight_bg == 0:
            continue

        weight_fg = total - weight_bg
        if weight_fg == 0:
            break

        sum_bg += i * count
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_total - sum_bg) / weight_fg

        var_between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if var_between > var_max:
            var_max = var_between
            threshold = i

    return threshold


def _to_binary(img: Image.Image) -> Image.Image:
    """Convert image to black/white with Otsu threshold."""
    gray = img.convert("L")
    threshold = otsu_threshold(gray)
    return gray.point(lambda x: 255 if x > threshold else 0, mode="1")


def _apply_dct_denoise(img: Image.Image, strength: int) -> Image.Image:
    """Suppress small DCT ringing and speckles with repeated 3x3 median filtering."""
    for _ in range(strength):
        img = img.filter(ImageFilter.MedianFilter(size=3))
    return img


def _auto_correct_by_histogram(img: Image.Image) -> Image.Image:
    """Auto-correct image contrast based on page histogram."""
    # Use a small cutoff to avoid extreme outliers dominating the stretch.
    return ImageOps.autocontrast(img, cutoff=1)


def _cleanup_gray_background(img: Image.Image, max_brightness: int) -> Image.Image:
    """Whiten brighter grayscale pixels to reduce background noise."""
    gray = img.convert("L")
    return gray.point(lambda value: 255 if value > max_brightness else value)


def dilate_scale_and_radius(dilate: float) -> tuple[int, int]:
    """Return bounded supersampling scale and the corresponding pixel radius."""
    fraction = Fraction(str(dilate)).limit_denominator(4)
    if fraction.denominator not in (1, 2, 4) or not math.isclose(float(fraction), dilate, rel_tol=0, abs_tol=1e-6):
        raise ValueError("--dilate must use 0.25-pixel increments")
    return fraction.denominator, fraction.numerator


def _apply_dilation(img: Image.Image, dilate: float) -> Image.Image:
    """Apply dilation to thicken text strokes before blur or binarization."""
    if dilate <= 0:
        return img

    scale, radius = dilate_scale_and_radius(dilate)
    original_size = img.size
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), resample=Image.Resampling.LANCZOS)

    size = radius * 2 + 1
    inverted = ImageOps.invert(img)
    dilated = ImageOps.invert(inverted.filter(ImageFilter.MaxFilter(size=size)))
    if scale > 1:
        dilated = dilated.resize(original_size, resample=Image.Resampling.LANCZOS)
    return dilated


def _apply_closing(img: Image.Image) -> Image.Image:
    """Apply a supersampled 3x3 morphological closing to dark strokes."""
    return _apply_morphology(img, closing=True)


def _apply_opening(img: Image.Image) -> Image.Image:
    """Apply a supersampled 3x3 morphological opening to dark strokes."""
    return _apply_morphology(img, closing=False)


def _apply_morphology(img: Image.Image, closing: bool) -> Image.Image:
    """Apply a 3x3 morphology operation on dark foreground at higher resolution."""
    original_size = img.size
    scale = MORPHOLOGY_SUPERSAMPLE_FACTOR
    enlarged = img.resize((img.width * scale, img.height * scale), resample=Image.Resampling.LANCZOS)
    foreground = ImageOps.invert(enlarged)
    if closing:
        processed = foreground.filter(ImageFilter.MaxFilter(size=3)).filter(ImageFilter.MinFilter(size=3))
    else:
        processed = foreground.filter(ImageFilter.MinFilter(size=3)).filter(ImageFilter.MaxFilter(size=3))
    result = ImageOps.invert(processed)
    return result.resize(original_size, resample=Image.Resampling.LANCZOS)


def _apply_inpaint(img: Image.Image) -> Image.Image:
    """Use OpenCV to inpaint small dark-stroke gaps detected by morphological closing."""
    if cv2 is None or np is None:
        raise RuntimeError("--inpaint requires OpenCV and NumPy; install opencv-python")

    source = np.asarray(img.convert("L") if img.mode == "L" else img.convert("RGB"))
    gray = source if source.ndim == 2 else cv2.cvtColor(source, cv2.COLOR_RGB2GRAY)
    _, foreground = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

    kernel = np.ones((3, 3), dtype=np.uint8)
    closed = cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, kernel)
    mask = cv2.subtract(closed, foreground)
    if not np.any(mask):
        return img

    background = cv2.bitwise_not(foreground)
    _, labels = cv2.connectedComponents(background, connectivity=8)
    border_labels = np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
    external_background = np.isin(labels, border_labels)
    mask[~external_background] = 0
    if not np.any(mask):
        return img

    repaired = cv2.inpaint(source, mask, 1.0, cv2.INPAINT_TELEA)
    return Image.fromarray(repaired)


def _scale_to_width(img: Image.Image, max_width: int) -> Image.Image:
    """Downscale the image proportionally when it is wider than max_width."""
    if max_width <= 0 or img.width <= max_width:
        return img
    height = max(1, round(img.height * max_width / img.width))
    return img.resize((max_width, height), resample=Image.Resampling.LANCZOS)


@dataclass(frozen=True)
class ImageProcessOptions:
    """Processing parameters applied to one image."""

    to_bw: bool = False
    to_gray: bool = False
    auto_correct: bool = False
    max_brightness: Optional[int] = None
    dilate: float = 0.0
    blur: float = 0.0
    closing: bool = False
    opening: bool = False
    inpaint: bool = False
    dct_denoise: int = 0
    max_width: Optional[int] = None

    def __post_init__(self) -> None:
        if self.to_bw and self.to_gray:
            raise ValueError("--bw and --gray cannot be used together")
        if self.max_brightness is not None and not self.to_gray:
            raise ValueError("--max-brightness requires --gray")
        if self.max_brightness is not None and not 0 <= self.max_brightness <= 255:
            raise ValueError("--max-brightness must be in range 0-255")
        if self.blur < 0:
            raise ValueError("--blur must be >= 0")
        if self.dilate < 0:
            raise ValueError("--dilate must be >= 0")
        dilate_scale_and_radius(self.dilate)
        if not 0 <= self.dct_denoise <= 3:
            raise ValueError("--dct-denoise must be in range 0-3")
        if self.inpaint and (cv2 is None or np is None):
            raise ValueError("--inpaint requires OpenCV and NumPy; install opencv-python")
        if self.max_width is not None and self.max_width <= 0:
            raise ValueError("--max-width must be a positive integer")


class PdfImageProcessor:
    """Apply the full page-image pipeline to one image and save the result."""

    def __init__(self, options: Optional[ImageProcessOptions] = None) -> None:
        self.options = options or ImageProcessOptions()

    def process(self, img: Image.Image, has_dct_image: bool = False) -> Image.Image:
        options = self.options
        if options.max_width is not None:
            img = _scale_to_width(img, options.max_width)
        if img.mode not in ("RGB", "L", "1"):
            img = img.convert("RGB")

        if options.dct_denoise and has_dct_image:
            img = _apply_dct_denoise(img, options.dct_denoise)
        if options.auto_correct:
            img = _auto_correct_by_histogram(img)
        if options.inpaint:
            img = _apply_inpaint(img)
        if options.closing:
            img = _apply_closing(img)
        if options.opening:
            img = _apply_opening(img)
        if options.dilate > 0:
            img = _apply_dilation(img, options.dilate)
        if options.blur > 0:
            img = img.filter(ImageFilter.GaussianBlur(radius=options.blur))

        if options.to_bw:
            return _to_binary(img)
        if options.to_gray:
            img = img.convert("L")
            if options.max_brightness is not None:
                img = _cleanup_gray_background(img, options.max_brightness)
            return img
        return img if img.mode == "RGB" else img.convert("RGB")

    def process_file(
        self,
        input_image: Path,
        output_dir: Path,
        name: Optional[str] = None,
        has_dct_image: Optional[bool] = None,
    ) -> Path:
        input_path = Path(input_image).expanduser().resolve()
        if not input_path.exists():
            raise FileNotFoundError(f"Input image not found: {input_path}")

        with Image.open(input_path) as source:
            img = source.copy()
        if has_dct_image is None:
            has_dct_image = input_path.suffix.lower() in JPEG_SUFFIXES

        processed = self.process(img, has_dct_image=has_dct_image)
        output_directory = Path(output_dir).expanduser().resolve()
        output_directory.mkdir(parents=True, exist_ok=True)
        output_path = output_directory / (name or f"{input_path.stem}_processed.png")
        processed.save(output_path, format="PNG")
        return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process one image with the PDF page image pipeline.")
    parser.add_argument("input_image", help="Input image path")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--bw", action="store_true", help="Convert to a 1-bit image using Otsu threshold.")
    mode_group.add_argument("--gray", action="store_true", help="Convert to grayscale.")
    parser.add_argument("--auto", action="store_true", help="Auto-correct contrast based on histogram.")
    parser.add_argument("--blur", type=float, default=0.0, help="Gaussian blur radius applied before binarization/grayscale.")
    parser.add_argument("--dilate", type=float, default=0.0, help="Dilation radius; supports 0.25-pixel increments.")
    parser.add_argument("--closing", action="store_true", help="Apply a supersampled 3x3 morphological closing.")
    parser.add_argument("--opening", action="store_true", help="Apply a supersampled 3x3 morphological opening.")
    parser.add_argument("--inpaint", action="store_true", help="Repair small text gaps with OpenCV. Requires opencv-python.")
    parser.add_argument("--dct-denoise", type=int, default=0, help="Apply 1-3 passes of a 3x3 median filter to JPEG input.")
    parser.add_argument("--max-brightness", type=int, default=None, help="In --gray mode, pixels above this brightness become white.")
    parser.add_argument("--max-width", type=int, default=None, help="Downscale the image when it is wider than this value.")
    parser.add_argument("--output-dir", default="output", help="Output directory. Defaults to ./output")
    parser.add_argument("--name", default=None, help="Output file name. Defaults to <input>_processed.png")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    options = ImageProcessOptions(
        to_bw=args.bw,
        to_gray=args.gray,
        auto_correct=args.auto,
        max_brightness=args.max_brightness,
        dilate=args.dilate,
        blur=args.blur,
        closing=args.closing,
        opening=args.opening,
        inpaint=args.inpaint,
        dct_denoise=args.dct_denoise,
        max_width=args.max_width,
    )
    output_path = PdfImageProcessor(options).process_file(args.input_image, args.output_dir, args.name)
    print(f"Saved processed image: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
