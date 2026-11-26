import shutil
import struct
import sys
from types import SimpleNamespace

import fitz
import pytest
from PIL import Image, features

from tools.pdf.minify_pdf import (
    _apply_closing,
    _apply_dct_denoise,
    _apply_dilation,
    _apply_opening,
    _bilevel_encoding_candidates,
    _encode_jbig2,
    _format_file_size,
    _image_color_info,
    _page_has_dct_image,
    _page_render_dpi,
    _quality_to_db,
    _save_pdf,
    main,
)


@pytest.mark.parametrize(
    ("size_bytes", "expected"),
    [(512 * 1024, "512.00 KB"), (1024 * 1024, "1.00 MB")],
)
def test_format_file_size_switches_between_kb_and_mb(size_bytes, expected):
    assert _format_file_size(size_bytes) == expected


def test_dilation_expands_dark_text_strokes():
    image = Image.new("L", (9, 9), 255)
    for y in range(9):
        for x in range(3, 6):
            image.putpixel((x, y), 0)

    dilated = _apply_dilation(image, dilate=1)

    assert sum(dilated.getpixel((x, 4)) == 0 for x in range(9)) == 5


def test_half_pixel_dilation_uses_supersampling_and_is_weaker():
    image = Image.new("L", (9, 9), 255)
    for y in range(9):
        for x in range(3, 6):
            image.putpixel((x, y), 0)

    half_dilated = _apply_dilation(image, dilate=0.5)
    fully_dilated = _apply_dilation(image, dilate=1)
    source_ink = sum(255 - value for value in image.getdata())
    half_ink = sum(255 - value for value in half_dilated.getdata())
    full_ink = sum(255 - value for value in fully_dilated.getdata())

    assert source_ink < half_ink < full_ink


def test_dilation_rejects_unsupported_fractional_steps():
    with pytest.raises(ValueError, match="0.25-pixel increments"):
        _apply_dilation(Image.new("L", (9, 9), 255), dilate=0.1)


def test_closing_fills_a_small_gap_in_dark_text_stroke():
    image = Image.new("L", (11, 11), 255)
    for x in range(1, 10):
        if x != 5:
            image.putpixel((x, 5), 0)

    closed = _apply_closing(image)

    assert 0 < closed.getpixel((5, 5)) < 255
    assert closed.getpixel((5, 3)) == 255


def test_opening_reduces_an_isolated_dark_speck():
    image = Image.new("L", (9, 9), 255)
    image.putpixel((4, 4), 0)

    opened = _apply_opening(image)

    assert opened.getpixel((4, 4)) > image.getpixel((4, 4))


@pytest.mark.skipif(not features.check_codec("jpg_2000"), reason="Pillow has no JPEG 2000 support")
def test_gray_pages_use_jpeg2000_and_remain_grayscale(tmp_path):
    images = [Image.new("L", (32, 24), 128), Image.new("1", (32, 24), 1)]
    output_pdf = tmp_path / "gray.pdf"

    _save_pdf(images, output_pdf, quality=75, use_jpeg2000=True)

    with fitz.open(output_pdf) as doc:
        gray_xref = doc[0].get_images(full=True)[0][0]
        binary_xref = doc[1].get_images(full=True)[0][0]
        assert doc.xref_get_key(gray_xref, "Filter") == ("name", "/JPXDecode")
        assert doc.extract_image(gray_xref)["cs-name"] == "DeviceGray"
        candidates = _bilevel_encoding_candidates(images[1], True, shutil.which("jbig2"))
        expected_encoding = min(candidates.items(), key=lambda candidate: len(candidate[1]))[0]
        assert doc.xref_get_key(binary_xref, "Filter") == ("name", f"/{expected_encoding}")
        assert len(doc.xref_stream_raw(binary_xref)) == len(candidates[expected_encoding])


def test_jpeg_fallback_keeps_grayscale_and_dct_encoding(tmp_path):
    image = Image.new("L", (32, 24), 128)
    output_pdf = tmp_path / "fallback.pdf"

    _save_pdf([image], output_pdf, quality=75, use_jpeg2000=False)

    with fitz.open(output_pdf) as doc:
        image_xref = doc[0].get_images(full=True)[0][0]
        assert doc.xref_get_key(image_xref, "Filter") == ("name", "/DCTDecode")
        assert doc.extract_image(image_xref)["cs-name"] == "DeviceGray"


@pytest.mark.skipif(not features.check_codec("jpg_2000"), reason="Pillow has no JPEG 2000 support")
def test_lossless_jpeg2000_preserves_gray_and_bilevel_pixels(tmp_path):
    gray = Image.new("L", (32, 24))
    bilevel = Image.new("1", (32, 24))
    for y in range(24):
        for x in range(32):
            gray.putpixel((x, y), (x * 11 + y * 7) % 256)
            bilevel.putpixel((x, y), (x + y) % 2)

    output_pdf = tmp_path / "lossless.pdf"
    _save_pdf([gray, bilevel], output_pdf, quality=75, use_jpeg2000=True, lossless=True)

    with fitz.open(output_pdf) as doc:
        for page, source in zip(doc, (gray, bilevel)):
            image_xref = page.get_images(full=True)[0][0]
            if source.mode == "1":
                candidates = _bilevel_encoding_candidates(source, True, shutil.which("jbig2"))
                expected_encoding = min(candidates.items(), key=lambda candidate: len(candidate[1]))[0]
            else:
                expected_encoding = "JPXDecode"
            assert doc.xref_get_key(image_xref, "Filter") == ("name", f"/{expected_encoding}")
            pixmap = fitz.Pixmap(doc, image_xref)
            decoded = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
            assert decoded.tobytes() == source.convert("L").tobytes()


def test_quality_factor_maps_to_jpeg2000_db():
    assert _quality_to_db(1) == pytest.approx(20.2)
    assert _quality_to_db(75) == pytest.approx(35.0)
    assert _quality_to_db(100) == pytest.approx(40.0)


def test_dct_denoise_removes_speckles_without_erasing_edge():
    image = Image.new("L", (9, 9), 255)
    for y in range(9):
        for x in range(4):
            image.putpixel((x, y), 0)
    image.putpixel((6, 4), 0)

    denoised = _apply_dct_denoise(image, strength=1)

    assert denoised.getpixel((6, 4)) == 255
    assert denoised.getpixel((3, 4)) == 0
    assert denoised.getpixel((4, 4)) == 255


def test_page_has_dct_image_detects_jpeg_only(tmp_path):
    jpeg_path = tmp_path / "image.jpg"
    png_path = tmp_path / "image.png"
    Image.new("RGB", (16, 16), "white").save(jpeg_path, format="JPEG")
    Image.new("RGB", (16, 16), "white").save(png_path, format="PNG")

    with fitz.open() as doc:
        jpeg_page = doc.new_page()
        jpeg_page.insert_image(jpeg_page.rect, filename=str(jpeg_path))
        png_page = doc.new_page()
        png_page.insert_image(png_page.rect, filename=str(png_path))

        assert _page_has_dct_image(doc.load_page(0))
        assert not _page_has_dct_image(doc.load_page(1))


def test_jbig2_encoding_uses_pdf_mode_and_validates_dimensions(monkeypatch):
    image = Image.new("1", (16, 8), 1)
    encoded = b"\x00" * 11 + struct.pack(">IIII", 16, 8, 0, 0) + b"jbig2-data"

    def fake_run(command, capture_output, check):
        assert command[0] == "/tools/jbig2"
        assert command[1] == "-p"
        assert capture_output and not check
        assert Image.open(command[2]).mode == "1"
        return SimpleNamespace(returncode=0, stdout=encoded, stderr=b"")

    monkeypatch.setattr("tools.pdf.minify_pdf.subprocess.run", fake_run)

    assert _encode_jbig2(image, "/tools/jbig2") == encoded


def test_bw_page_uses_jbig2_when_its_stream_is_smallest(tmp_path, monkeypatch):
    image = Image.new("1", (32, 24), 1)
    output_pdf = tmp_path / "jbig2.pdf"
    monkeypatch.setattr("tools.pdf.minify_pdf.shutil.which", lambda _: "/tools/jbig2")

    def fake_encode(img, encoder_path):
        assert img.mode == "1"
        assert encoder_path == "/tools/jbig2"
        return b"jbig2"

    monkeypatch.setattr("tools.pdf.minify_pdf._encode_jbig2", fake_encode)

    filter_counts = _save_pdf([image], output_pdf, quality=75, use_jpeg2000=False)

    assert filter_counts["JBIG2Decode"] == 1
    with fitz.open(output_pdf) as doc:
        image_xref = doc[0].get_images(full=True)[0][0]
        assert doc.xref_get_key(image_xref, "Filter") == ("name", "/JBIG2Decode")
        assert doc.xref_stream_raw(image_xref) == b"jbig2"


@pytest.mark.parametrize(
    ("colorspace", "bits_per_component", "expected"),
    [
        ("DeviceRGB", 8, ("RGB", 3)),
        ("DeviceGray", 8, ("Gray", 1)),
        ("DeviceGray", 1, ("BW", 1)),
        ("Indexed", 8, ("Indexed", 1)),
    ],
)
def test_image_color_info_reports_mode_and_channel_count(colorspace, bits_per_component, expected):
    assert _image_color_info(colorspace, "", bits_per_component) == expected


def test_full_page_scan_is_not_upsampled_and_retains_page_size(tmp_path, monkeypatch):
    source_pdf = tmp_path / "scan.pdf"
    source_doc = fitz.open()
    page = source_doc.new_page(width=300, height=450)
    pixels = Image.new("RGB", (400, 600), "white")
    image_buffer = tmp_path / "scan.jpg"
    pixels.save(image_buffer, format="JPEG")
    page.insert_image(page.rect, filename=str(image_buffer))
    assert _page_render_dpi(page) == pytest.approx(96)
    source_doc.save(source_pdf)
    source_doc.close()

    output_dir = tmp_path / "output"
    monkeypatch.setattr(sys, "argv", ["minify_pdf.py", str(source_pdf), "--output-dir", str(output_dir), "--gray"])
    assert main() == 0

    with fitz.open(output_dir / "scan_minify.pdf") as doc:
        image_xref = doc[0].get_images(full=True)[0][0]
        assert doc.extract_image(image_xref)["width"] == 400
        assert doc.extract_image(image_xref)["height"] == 600
        assert doc[0].rect.width == pytest.approx(300)
        assert doc[0].rect.height == pytest.approx(450)


def test_gray_cli_output_is_grayscale_pdf(tmp_path, monkeypatch, capsys):
    source_pdf = tmp_path / "source.pdf"
    source_doc = fitz.open()
    page = source_doc.new_page(width=400, height=600)
    page.insert_text((40, 50), "A grayscale PDF conversion check.")
    source_doc.save(source_pdf)
    source_doc.close()

    output_dir = tmp_path / "output"
    monkeypatch.setattr("tools.pdf.minify_pdf.shutil.which", lambda _: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "minify_pdf.py",
            str(source_pdf),
            "--output-dir",
            str(output_dir),
            "--max-width",
            "800",
            "--auto",
            "--gray",
            "--closing",
            "--dilate",
            "0.5",
            "--blur",
            "0.1",
        ],
    )

    assert main() == 0
    output = capsys.readouterr().out
    assert f"Source file size: {source_pdf.stat().st_size / 1024:.2f} KB" in output
    assert "JBIG2Enc: not available" in output
    assert "No embedded images found." in output

    output_pdf = output_dir / "source_minify.pdf"
    assert f"Output file size: {output_pdf.stat().st_size / 1024:.2f} KB" in output
    with fitz.open(output_pdf) as doc:
        image_xref = doc[0].get_images(full=True)[0][0]
        expected_filter = "/JPXDecode" if features.check_codec("jpg_2000") else "/DCTDecode"
        assert doc.xref_get_key(image_xref, "Filter") == ("name", expected_filter)
        assert doc.extract_image(image_xref)["cs-name"] == "DeviceGray"
        assert doc[0].rect.width == pytest.approx(400)
        assert doc[0].rect.height == pytest.approx(600)
        assert doc.metadata["creator"] == "MyBooks(https://mybooks.top)"
        if features.check_codec("jpg_2000"):
            assert doc.xref_get_key(doc.pdf_catalog(), "Version") == ("name", "/1.5")


def test_dry_run_skips_full_image_format_summary(tmp_path, monkeypatch, capsys):
    source_pdf = tmp_path / "source.pdf"
    source_doc = fitz.open()
    page = source_doc.new_page(width=200, height=300)
    page.insert_text((20, 30), "Dry run preview.")
    source_doc.save(source_pdf)
    source_doc.close()

    output_dir = tmp_path / "output"
    monkeypatch.setattr("tools.pdf.minify_pdf.shutil.which", lambda _: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "minify_pdf.py",
            str(source_pdf),
            "--dry-run-pages",
            "1",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert main() == 0

    output = capsys.readouterr().out
    assert "Dry run completed: 1 page(s)" in output
    assert "No embedded images found." not in output
    assert "Image 1:" not in output
    assert (output_dir / "source_preview_0001.png").exists()


def test_inspect_cli_reports_at_most_five_distinct_image_info_items(tmp_path, monkeypatch, capsys):
    source_pdf = tmp_path / "source.pdf"
    image_path = tmp_path / "image.jpg"
    Image.new("RGB", (96, 64), "white").save(image_path, format="JPEG")

    source_doc = fitz.open()
    for page_index in range(8):
        page = source_doc.new_page(width=300, height=400)
        if page_index == 4:
            rect = fitz.Rect(0, 0, 48, 32)
        elif page_index == 5:
            rect = fitz.Rect(0, 0, 24, 16)
        elif page_index == 6:
            rect = fitz.Rect(0, 0, 36, 24)
        elif page_index == 7:
            rect = fitz.Rect(0, 0, 18, 12)
        else:
            rect = fitz.Rect(0, 0, 72, 48)
        page.insert_image(rect, filename=str(image_path))
    source_doc.save(source_pdf)
    source_doc.close()

    output_dir = tmp_path / "output"
    monkeypatch.setattr(
        sys,
        "argv",
        ["minify_pdf.py", str(source_pdf), "--inspect", "--output-dir", str(output_dir)],
    )
    assert main() == 0

    output = capsys.readouterr().out
    assert output.count("Image ") == 5
    assert output.count("DCTDecode") == 5
    assert "Image 1: decoder=DCTDecode | dpi=96 DPI | size=96 x 64 px | color=RGB | channels=3" in output
    assert "Image 2: decoder=DCTDecode | dpi=144 DPI | size=96 x 64 px | color=RGB | channels=3" in output
    assert "Image 3: decoder=DCTDecode | dpi=288 DPI | size=96 x 64 px | color=RGB | channels=3" in output
    assert "Image 5: decoder=DCTDecode | dpi=384 DPI | size=96 x 64 px | color=RGB | channels=3" in output
    assert "Image 6:" not in output
    assert "JBIG2Enc: " in output
    assert "Source file size: " in output
    assert not output_dir.exists()
