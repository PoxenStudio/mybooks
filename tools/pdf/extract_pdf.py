#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from pathlib import Path

import fitz


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract PDF pages as JPEG images.")
    parser.add_argument("input_pdf", help="Input PDF file path")
    parser.add_argument(
        "--output",
        default="output",
        help="Output directory for extracted images. Defaults to ./output",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="Maximum number of pages to extract from the start. If omitted or 0, all pages are extracted.",
    )
    parser.add_argument(
        "--page",
        default="",
        help="Comma-separated 1-based page numbers to extract. Overrides --count if specified.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="Render resolution in DPI for extracted images. Default is 300.",
    )
    return parser.parse_args()


def parse_page_list(page_spec: str, total_pages: int) -> list[int]:
    """Parse comma-separated 1-based page numbers and preserve order."""
    if not page_spec.strip():
        return []

    pages: list[int] = []
    seen: set[int] = set()
    for token in page_spec.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            page_number = int(token)
        except ValueError as exc:
            raise ValueError(f"Invalid page number in --page: {token}") from exc

        if page_number == 0:
            raise ValueError("Page number 0 is invalid in --page")

        if page_number < 0:
            page_number = total_pages + page_number + 1

        if page_number < 1 or page_number > total_pages:
            raise ValueError(f"Page number out of range in --page: {token}")

        if page_number not in seen:
            seen.add(page_number)
            pages.append(page_number)

    return pages


def get_page_indices(args: argparse.Namespace, total_pages: int) -> list[int]:
    if args.page:
        return [p - 1 for p in parse_page_list(args.page, total_pages)]

    if args.count <= 0:
        return list(range(total_pages))

    return list(range(min(args.count, total_pages)))


def render_page_as_jpeg(page: fitz.Page, output_path: Path, dpi: int) -> None:
    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    img = pix.tobytes("jpeg")
    output_path.write_bytes(img)


def main() -> int:
    args = parse_args()

    input_path = Path(args.input_pdf).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_path}")
    if input_path.suffix.lower() != ".pdf":
        raise ValueError(f"Input file must be a PDF: {input_path}")
    if args.count < 0:
        raise ValueError("--count must be >= 0")
    if args.dpi <= 0:
        raise ValueError("--dpi must be a positive integer")

    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(input_path))
    total_pages = len(doc)
    if total_pages == 0:
        raise ValueError("Input PDF has no pages")

    page_indices = get_page_indices(args, total_pages)
    if not page_indices:
        raise ValueError("No pages selected for extraction")

    for page_index in page_indices:
        page = doc.load_page(page_index)
        output_file = output_dir / f"page_{page_index + 1}.jpg"
        render_page_as_jpeg(page, output_file, args.dpi)
        print(f"Saved: {output_file}")

    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
