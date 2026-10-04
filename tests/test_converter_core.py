"""繁简转换工具核心单元测试（standalone，不依赖 MyBooks）。

Usage: python tests/test_converter_core.py   (or pytest tests/)
"""

import os
import sys
import tempfile
import zipfile

# Allow running from the repo root without installing the webserver package
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from webserver.toolbox.chinese_converter import epub_converter  # noqa: E402
from webserver.toolbox.chinese_converter.opencc_engine import OpenCC  # noqa: E402

A5_PATH = os.path.join(_ROOT, "webserver", "toolbox", "chinese_converter", "a5_phrases.txt")

# ── 引擎测试 ─────────────────────────────────────────────────

def test_t2s_basic():
    oc = OpenCC("t2s")
    assert oc.convert("作為一個發展中的國家。") == "作为一个发展中的国家。"
    assert oc.convert("後台管理員的頭髮很長，為人低調。") == "后台管理员的头发很长，为人低调。"


def test_t2s_phrase_priority():
    # 词组优先：後台 → 后台（而非 後→后、台→台 的拼接）
    oc = OpenCC("t2s")
    assert oc.convert("後台") == "后台"
    assert oc.convert("電腦") == "电脑"


def test_t2s_punctuation_preserved():
    oc = OpenCC("t2s")
    text = "「你好」，世界！——測試…"
    assert oc.convert(text) == "「你好」，世界！——测试…"


def test_tw2s():
    oc = OpenCC("tw2s")
    # 臺→台（TWVariantsRev 字级映射）
    assert oc.convert("臺灣的軟體業者") == "台湾的软体业者"


def test_s2t():
    oc = OpenCC("s2t")
    assert oc.convert("作为发展中的国家，软件产业蓬勃发展。") == "作爲發展中的國家，軟件產業蓬勃發展。"
    assert oc.convert("后台管理员的头发很长。") == "後臺管理員的頭髮很長。"


def test_s2tw():
    oc = OpenCC("s2tw")
    assert oc.convert("作为发展中的国家。") == "作為發展中的國家。"


def test_s2twp_taiwan_phrases():
    # s2twp：简→台繁 + 台湾用词（TWPhrases，官方 OpenCC 数据）
    oc = OpenCC("s2twp")
    assert oc.convert("软件产业蓬勃发展。") == "軟體產業蓬勃發展。"
    assert oc.convert("鼠标") == "滑鼠"
    assert oc.convert("网络") == "網路"
    assert oc.convert("视频") == "影片"


def test_tw2sp_taiwan_phrases():
    # tw2sp：台繁（含台湾用词）→ 简
    oc = OpenCC("tw2sp")
    assert oc.convert("臺灣的軟體產業蓬勃發展。") == "台湾的软件产业蓬勃发展。"
    assert oc.convert("滑鼠") == "鼠标"
    assert oc.convert("網路") == "网络"
    assert oc.convert("影片") == "视频"


def test_s2twp_without_phrases_is_s2tw():
    # 对照：s2tw（不含用词）不转 软件→軟體（仅字级 软件→軟件）
    oc = OpenCC("s2tw")
    assert oc.convert("软件") == "軟件"


def test_t2tw_and_tw2t_work():
    oc1 = OpenCC("t2tw")
    assert "體驗" in oc1.convert("這個軟件的用戶體驗很好。")
    oc2 = OpenCC("tw2t")
    assert "體驗" in oc2.convert("這個軟體的用戶體驗很好。")


def test_a5_enhancement():
    # 不带增强词表：幹麼 → 干么（OpenCC 默认）
    plain = OpenCC("t2s")
    assert plain.convert("幹麼這樣？") == "干么这样？"
    # 带增强词表：幹麼 → 干嘛（a5 个人修正词条优先）
    enhanced = OpenCC("t2s", extra_dicts=[A5_PATH])
    assert enhanced.convert("幹麼這樣？") == "干嘛这样？"


def test_a5_ignored_for_s2t():
    # 增强词表是繁→简词条，注入 s2t 不应干扰（键为繁体，输入为简体不会命中）
    oc = OpenCC("s2t", extra_dicts=[A5_PATH])
    assert oc.convert("软件产业") == "軟件產業"


def test_invalid_direction_raises():
    try:
        OpenCC("no_such_direction")
    except (IOError, ValueError, OSError):
        return
    raise AssertionError("invalid direction should raise")


def test_no_conversion():
    oc = OpenCC("t2s")
    oc.set_conversion("no_conversion")
    assert oc.convert("繁體中文") == "繁體中文"
    oc.set_conversion("t2s")
    assert oc.convert("繁體中文") == "繁体中文"


# ── EPUB 测试 ─────────────────────────────────────────────────

CH1 = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>第一章</title></head>
<body>
<p>作為一個發展中的國家，電腦產業蓬勃發展。</p>
<p>後台管理員的頭髮很長。</p>
<script type="text/javascript">var msg = "作為";</script>
</body>
</html>
"""

OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">urn:uuid:test</dc:identifier>
    <dc:title>繁體測試書</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="css" href="style.css" media-type="text/css"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>
"""

CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

CSS = b".test { content: \"\xe4\xbd\x9c\xe7\x82\xba\"; }"  # .test { content: "作為"; }
PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes"


def _make_epub(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), b"application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", OPF)
        z.writestr("OEBPS/ch1.xhtml", CH1)
        z.writestr("OEBPS/style.css", CSS)
        z.writestr("OEBPS/cover.png", PNG)


def test_epub_conversion():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.epub")
        out = os.path.join(tmp, "out.epub")
        _make_epub(src)

        oc = OpenCC("t2s")
        epub_converter.convert_epub(src, out, oc.convert, convert_metadata=True)

        with zipfile.ZipFile(out, "r") as z:
            names = z.namelist()
            # mimetype 必须为第一项且不压缩（EPUB 规范）
            assert names[0] == "mimetype"
            assert z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
            assert z.read("mimetype") == b"application/epub+zip"

            html = z.read("OEBPS/ch1.xhtml").decode("utf-8")
            assert "作为一个发展中的国家" in html
            assert "后台管理员的头发很长" in html
            assert "第一章" in html  # <title> 文本也被转换
            # script 内容不得被转换
            assert 'var msg = "作為";' in html
            # XML 声明应保留
            assert html.lstrip().startswith("<?xml")

            opf = z.read("OEBPS/content.opf").decode("utf-8")
            assert "<dc:title>繁体测试书</dc:title>" in opf

            # 非文档条目字节级保留
            assert z.read("OEBPS/style.css") == CSS
            assert z.read("OEBPS/cover.png") == PNG


def test_epub_metadata_off():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.epub")
        out = os.path.join(tmp, "out.epub")
        _make_epub(src)

        oc = OpenCC("t2s")
        epub_converter.convert_epub(src, out, oc.convert, convert_metadata=False)

        with zipfile.ZipFile(out, "r") as z:
            opf = z.read("OEBPS/content.opf").decode("utf-8")
            assert "<dc:title>繁體測試書</dc:title>" in opf
            html = z.read("OEBPS/ch1.xhtml").decode("utf-8")
            assert "作为一个发展中的国家" in html


def test_html_cdata_preserved():
    # CDATA 段必须整体原样保留（标记 + 原始内容，不参与繁简转换），
    # 正文普通文本照常转换
    html = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p>作為正文，包含繁體。</p>'
        '<div><![CDATA[<raw 繁體 內容 & 数据>]]></div>'
        '<script><![CDATA[var 測試 = "ok";]]></script>'
        '</body></html>'
    ).encode("utf-8")
    oc = OpenCC("t2s")
    out = epub_converter._convert_html_doc(html, oc.convert).decode("utf-8")
    assert "作为正文，包含繁体。" in out
    assert "<![CDATA[<raw 繁體 內容 & 数据>]]>" in out
    assert '<![CDATA[var 測試 = "ok";]]>' in out
    # 占位符不应泄漏到输出
    assert "MYBOOKS_CDATA" not in out


def test_html_comment_preserved():
    # 注释类节点（Comment / IE 条件注释 / Doctype）必须整体保留：bs4 中它们是
    # NavigableString 的子类，会被 string=True 匹配到——replace_with 会剥掉
    # 注释标记使内容变成可见正文（条件注释还会遭转义），且内容不应参与繁简转换
    html = (
        '<!DOCTYPE html><html><body>'
        '<!-- 這是註釋請勿轉換 -->'
        '<p>作為正文。</p>'
        '<!--[if IE]>老舊瀏覽器<![endif]-->'
        '</body></html>'
    ).encode("utf-8")
    oc = OpenCC("t2s")
    out = epub_converter._convert_html_doc(html, oc.convert).decode("utf-8")
    assert "<!-- 這是註釋請勿轉換 -->" in out
    assert "<!--[if IE]>老舊瀏覽器<![endif]-->" in out
    assert out.lstrip().startswith("<!DOCTYPE html>")
    assert "作为正文。" in out


def test_xml_identifier_not_converted():
    # OPF 元数据文本参与转换（与库内元数据同步转换的产品语义一致），
    # 但机器标识符 dc:identifier 除外——转换会破坏 UUID/来源引用与跨书去重
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="uid">urn:uuid:繁體編號-123</dc:identifier>'
        '<dc:title>繁體測試書</dc:title>'
        '<dc:description>這是簡介，含繁體。</dc:description>'
        '</metadata></package>'
    ).encode("utf-8")
    oc = OpenCC("t2s")
    out = epub_converter._convert_xml_doc(opf, oc.convert).decode("utf-8")
    assert "urn:uuid:繁體編號-123" in out
    assert "繁体测试书" in out
    assert "这是简介，含繁体。" in out


def test_xml_ncx_navlabel_converted():
    # NCX 的 docTitle/navLabel 文本参与转换；meta dtb:uid 是属性、不受影响
    ncx = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        '<head><meta name="dtb:uid" content="urn:uuid:繁體編號-999"/></head>'
        '<docTitle><text>繁體書名</text></docTitle>'
        '<navMap><navPoint id="n1"><navLabel><text>第一章 繁體標題</text></navLabel>'
        '<content src="ch1.xhtml"/></navPoint></navMap></ncx>'
    ).encode("utf-8")
    oc = OpenCC("t2s")
    out = epub_converter._convert_xml_doc(ncx, oc.convert).decode("utf-8")
    assert "繁体书名" in out
    assert "第一章 繁体标题" in out
    assert "urn:uuid:繁體編號-999" in out


def test_html_gbk_entry_roundtrip():
    # 非 UTF-8 条目（GB18030 繁体）：解码兜底后统一以 UTF-8 回写——bs4 会把
    # <meta charset> 重写为 utf-8，字节若按原编码写回会产生"声明 utf-8、
    # 字节 gb18030"的矛盾（按声明解码即乱码），故声明与字节一并统一
    html = (
        '<?xml version="1.0" encoding="gbk"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        '<meta charset="gbk"/></head><body>'
        '<p>作為一個發展中的國家，電腦產業蓬勃發展。</p>'
        '</body></html>'
    ).encode("gb18030")
    oc = OpenCC("t2s")
    out = epub_converter._convert_html_doc(html, oc.convert)
    text = out.decode("utf-8")  # 回写必为 UTF-8
    assert "作为一个发展中的国家，电脑产业蓬勃发展。" in text
    assert "\ufffd" not in text
    assert 'encoding="utf-8"' in text.split("?>")[0]
    assert 'charset="utf-8"' in text
    assert 'charset="gbk"' not in text


def test_html_big5_entry_utf8_writeback():
    # BIG5 繁体条目：统一 UTF-8 回写，XML 声明与字节一致
    html = (
        '<?xml version="1.0" encoding="big5"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p>電腦產業蓬勃發展。</p>'
        '</body></html>'
    ).encode("big5")
    oc = OpenCC("t2s")
    out = epub_converter._convert_html_doc(html, oc.convert)
    text = out.decode("utf-8")
    assert "电脑产业蓬勃发展。" in text
    assert 'encoding="utf-8"' in text.split("?>")[0]
    assert "big5" not in text.split("?>")[0]


def test_official_semantics_maxmatch():
    # 对齐 OpenCC 官方 mmseg 逐位置贪心最长匹配。此前 Hopkins 树版是
    # "全局最长（先长度后最左）"：位置靠后的长词条会抢走位置靠前的词组
    # 命中（如"沈詩任筆"抢掉"陰沈→阴沉"、"一丝不挂"抢掉"周一→週一"）
    assert OpenCC("s2t").convert("周一丝不挂") == "週一絲不掛"
    assert OpenCC("t2s").convert("陰沈詩任筆") == "阴沉诗任笔"
    assert OpenCC("t2s").convert("藉以免藉口") == "借以免借口"
    # multiple mapping 取第一候选：单字"沈"保持（姓氏），词组"陰沈"才转
    assert OpenCC("t2s").convert("沈") == "沈"


def test_long_text_no_recursion():
    # 无分隔符长段：此前树递归深度≈段长，约 2000 字即 RecursionError
    # 导致整本书转换失败；线性匹配后不再受段长限制
    oc = OpenCC("t2s")
    out = oc.convert("發展國家" * 2500)
    assert len(out) == 10000
    assert "发展国家" in out


def test_direction_label_new_directions():
    from webserver.toolbox.chinese_converter.opencc_engine import DIRECTION_LABELS  # noqa: E402
    assert DIRECTION_LABELS["s2twp"] == "简体→台湾繁体（含台湾用词）"
    assert DIRECTION_LABELS["tw2sp"] == "台湾繁体（含台湾用词）→简体"
    assert len(DIRECTION_LABELS) == 8


# ── TXT 测试 ──────────────────────────────────────────────────

def test_txt_utf8_conversion():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.txt")
        out = os.path.join(tmp, "out.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("作為一個發展中的國家。\n後台管理員的頭髮很長。\n")
        oc = OpenCC("t2s")
        enc = epub_converter.convert_txt_file(src, out, oc.convert)
        assert enc == "utf-8"
        with open(out, encoding="utf-8") as f:
            assert f.read() == "作为一个发展中的国家。\n后台管理员的头发很长。\n"


def test_txt_gb18030_detection():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.txt")
        out = os.path.join(tmp, "out.txt")
        with open(src, "wb") as f:
            f.write("作為一個發展中的國家。".encode("gb18030"))
        oc = OpenCC("t2s")
        enc = epub_converter.convert_txt_file(src, out, oc.convert)
        # 繁体文本同时满足 BIG5/GB18030 严格解码，big5 优先（两者解码结果一致）
        assert enc in ("big5", "gb18030")
        with open(out, encoding="utf-8") as f:
            assert f.read() == "作为一个发展中的国家。"


def test_txt_big5_detection():
    # 繁体 BIG5 TXT：检测为 big5 且转换正确（原实现按 GB18030 硬解成乱码）
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.txt")
        out = os.path.join(tmp, "out.txt")
        with open(src, "wb") as f:
            f.write("作為一個發展中的國家，電腦產業蓬勃發展。".encode("big5"))
        oc = OpenCC("t2s")
        enc = epub_converter.convert_txt_file(src, out, oc.convert)
        assert enc == "big5"
        with open(out, encoding="utf-8") as f:
            assert f.read() == "作为一个发展中的国家，电脑产业蓬勃发展。"


def test_detect_encoding():
    assert epub_converter.detect_encoding("你好".encode("utf-8")) == "utf-8"
    assert epub_converter.detect_encoding(b"\xef\xbb\xbf" + "你好".encode("utf-8")) == "utf-8-sig"
    assert epub_converter.detect_encoding("繁體中文".encode("gb18030")) == "big5"
    assert epub_converter.detect_encoding("简体中文".encode("gb18030")) == "gb18030"


def test_detect_encoding_utf16_32():
    # UTF-16/32 BOM（Windows 导出 TXT 常见形态）：此前回落 utf-8 + replace
    # 静默毁坏（gb18030 甚至能"成功"解码部分 UTF-16 字节产出更隐蔽的乱码）
    assert epub_converter.detect_encoding(b"\xff\xfe" + "你好".encode("utf-16-le")) == "utf-16"
    assert epub_converter.detect_encoding(b"\xfe\xff" + "你好".encode("utf-16-be")) == "utf-16"
    # UTF-32LE BOM 以 UTF-16LE BOM 开头，必须先判 UTF-32
    assert epub_converter.detect_encoding(b"\xff\xfe\x00\x00" + "你好".encode("utf-32-le")) == "utf-32"
    assert epub_converter.detect_encoding(b"\x00\x00\xfe\xff" + "你好".encode("utf-32-be")) == "utf-32"
    # 无 BOM：靠 \x00 密度启发式（ASCII 字符高字节），且须先于 UTF-8 尝试——
    # 纯 ASCII 的 UTF-16 是合法 UTF-8（NUL）
    assert epub_converter.detect_encoding("Hello".encode("utf-16-le")) == "utf-16-le"
    assert epub_converter.detect_encoding("Hello 世界 123".encode("utf-16-le")) == "utf-16-le"
    assert epub_converter.detect_encoding("Hello 世界 123".encode("utf-16-be")) == "utf-16-be"


def test_txt_utf16_roundtrip():
    # Windows 导出的 UTF-16（带 BOM）TXT：完整转换 + 输出统一 UTF-8
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.txt")
        out = os.path.join(tmp, "out.txt")
        with open(src, "wb") as f:
            f.write("作為一個發展中的國家。\n後台管理員的頭髮很長。".encode("utf-16"))
        oc = OpenCC("t2s")
        enc = epub_converter.convert_txt_file(src, out, oc.convert)
        assert enc == "utf-16"
        with open(out, encoding="utf-8") as f:
            assert f.read() == "作为一个发展中的国家。\n后台管理员的头发很长。"


def test_html_utf16_entry_writeback():
    # EPUB 内 UTF-16 条目（OPF 规范允许 UTF-16）：解码转换后统一 UTF-8 回写
    html = (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p>電腦產業蓬勃發展。</p>'
        '</body></html>'
    ).encode("utf-16")
    oc = OpenCC("t2s")
    out = epub_converter._convert_html_doc(html, oc.convert)
    text = out.decode("utf-8")
    assert "电脑产业蓬勃发展。" in text
    assert 'encoding="utf-8"' in text.split("?>")[0]
    assert "\x00" not in text


if __name__ == "__main__":
    failures = 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        try:
            t()
            print("PASS  %s" % t.__name__)
        except Exception as err:
            failures += 1
            import traceback
            print("FAIL  %s: %s" % (t.__name__, err))
            traceback.print_exc()
    print("\n%d/%d tests passed" % (len(tests) - failures, len(tests)))
    sys.exit(1 if failures else 0)
