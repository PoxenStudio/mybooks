import fitz
from PIL import Image, features

from webserver.services.async_service import AsyncService
from webserver.toolbox.minify_pdf import MinifyPdfTool, _page_render_dpi


def test_toolbox_minify_uses_jpeg2000_for_gray_pages(tmp_path, monkeypatch):
    source_pdf = tmp_path / "source.pdf"
    source_doc = fitz.open()
    page = source_doc.new_page(width=400, height=600)
    scan_path = tmp_path / "scan.jpg"
    Image.new("RGB", (400, 600), "white").save(scan_path, format="JPEG")
    page.insert_image(page.rect, filename=str(scan_path))
    page.insert_text((40, 50), "A grayscale PDF conversion check.")
    assert _page_render_dpi(page) == 72
    source_doc.save(source_pdf)
    source_doc.close()

    tool = MinifyPdfTool()
    monkeypatch.setattr(AsyncService, "async_mode", lambda self: False)
    monkeypatch.setattr(tool, "setup", lambda *_args: None)
    monkeypatch.setattr(tool, "create_task", lambda **_kwargs: 1)
    monkeypatch.setattr(tool, "make_progress_callback", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tool, "complete_task", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tool, "get_work_dir", lambda _key: str(tmp_path))

    result = tool.minify(str(source_pdf), {"gray": True}, user_id=1)
    assert result is not None

    with fitz.open(result["pdf_path"]) as doc:
        image_xref = doc[0].get_images(full=True)[0][0]
        expected_filter = "/JPXDecode" if features.check_codec("jpg_2000") else "/DCTDecode"
        assert doc.xref_get_key(image_xref, "Filter") == ("name", expected_filter)
        assert doc.extract_image(image_xref)["cs-name"] == "DeviceGray"
        assert doc.extract_image(image_xref)["width"] == 400
        assert doc.extract_image(image_xref)["height"] == 600
        assert doc[0].rect.width == 400
        assert doc[0].rect.height == 600
        assert doc.metadata["creator"] == "MyBooks(https://mybooks.top) MinifyTool"
        if features.check_codec("jpg_2000"):
            assert doc.xref_get_key(doc.pdf_catalog(), "Version") == ("name", "/1.5")
