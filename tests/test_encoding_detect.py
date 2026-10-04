# -*- coding: utf-8 -*-
"""encoding_detect 核心单元测试（standalone，不依赖 MyBooks）。

运行：python -m unittest discover -s tests 或 python tests/test_encoding_detect.py
"""
import os
import random
import sys
import unittest

# 模块位于 webserver/toolbox/utils/（72f44b4c 目录重构后的布局）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webserver", "toolbox", "utils"))

from encoding_detect import (  # noqa: E402
    detect_encoding,
    decode_with_report,
    fix_to_utf8,
)

BIG5_TEXT = "第一章\u3000序章\n這是一本關於人工智慧發展的書籍，內容涵蓋機器學習與深度學習。"
GBK_TEXT = "第一章\u3000序章\n人工智能的发展历程，包括机器学习与深度学习。"


class TestDetectBasic(unittest.TestCase):
    """常规编码检测。"""

    def test_utf8(self):
        data = GBK_TEXT.encode("utf-8")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "utf-8")
        self.assertGreaterEqual(r["confidence"], 0.9)
        self.assertFalse(r["mojibake"])
        self.assertFalse(r["garbage"])

    def test_gb18030(self):
        data = GBK_TEXT.encode("gb18030")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "gb18030")
        self.assertFalse(r["mojibake"])

    def test_big5(self):
        data = BIG5_TEXT.encode("big5")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "big5")
        self.assertFalse(r["mojibake"])

    def test_utf8_bom(self):
        data = b"\xef\xbb\xbf" + GBK_TEXT.encode("utf-8")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "utf-8-sig")
        self.assertEqual(r["confidence"], 1.0)
        self.assertFalse(r["mojibake"])

    def test_english_text(self):
        data = "Hello world, this is a plain English book sample.\n".encode("utf-8")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "utf-8")
        self.assertFalse(r["garbage"])

    def test_binary_garbage(self):
        data = bytes(range(256)) * 4
        r = detect_encoding(data)
        self.assertTrue(r["garbage"])

    def test_empty(self):
        r = detect_encoding(b"")
        self.assertEqual(r["encoding"], "utf-8")
        self.assertEqual(r["confidence"], 0.0)
        self.assertFalse(r["garbage"])  # 空文件不是垃圾，绝不报错拒绝

    def test_str_input_guard(self):
        # str 输入自动按 UTF-8 编码，不应抛 TypeError
        r = detect_encoding(GBK_TEXT)
        self.assertIn("encoding", r)


class TestDecodeRoundtrip(unittest.TestCase):
    """decode_with_report / fix_to_utf8 解码一致性。"""

    def test_gb18030_roundtrip(self):
        data = GBK_TEXT.encode("gb18030")
        text, report = decode_with_report(data)
        self.assertEqual(text, GBK_TEXT)
        out, _ = fix_to_utf8(data)
        self.assertEqual(out.decode("utf-8"), GBK_TEXT)

    def test_big5_roundtrip(self):
        data = BIG5_TEXT.encode("big5")
        text, report = decode_with_report(data)
        self.assertEqual(text, BIG5_TEXT)
        out, _ = fix_to_utf8(data)
        self.assertEqual(out.decode("utf-8"), BIG5_TEXT)

    def test_bom_stripped(self):
        data = b"\xef\xbb\xbf" + GBK_TEXT.encode("utf-8")
        text, report = decode_with_report(data)
        self.assertEqual(text, GBK_TEXT)
        self.assertFalse(text.startswith("\ufeff"))


class TestMojibake(unittest.TestCase):
    """乱码反转恢复：BIG5 字节被按 GB18030 误读后以 UTF-8 存盘。"""

    def test_big5_as_gbk_saved_utf8(self):
        mojibake_str = BIG5_TEXT.encode("big5").decode("gb18030")
        data = mojibake_str.encode("utf-8")  # 乱码以 UTF-8 写入文件
        r = detect_encoding(data)
        self.assertTrue(r["mojibake"])
        self.assertEqual(r["encoding"], "big5")
        text, _ = decode_with_report(data)
        self.assertEqual(text, BIG5_TEXT)
        out, _ = fix_to_utf8(data)
        self.assertEqual(out.decode("utf-8"), BIG5_TEXT)

    def test_big5_as_gbk_high_readability_variant(self):
        # 变体：误读文本全部落在合法 CJK 区（直解可读性 96/100），
        # 统计可读性无法区分——依赖常用字占比识别并反转恢复
        BIG5_BOOK = "第一章\u3000序章\n這是一本關於人工智慧的書籍。"
        data = BIG5_BOOK.encode("big5").decode("gb18030").encode("utf-8")
        r = detect_encoding(data)
        self.assertTrue(r["mojibake"])
        self.assertEqual(r["encoding"], "big5")
        text, _ = decode_with_report(data)
        self.assertEqual(text, BIG5_BOOK)

    def test_utf8_as_gbk_all_cjk_mojibake(self):
        # UTF-8 被按 GB18030 误读后以 UTF-8 存盘，误读字全为合法 CJK
        # （浜哄伐鏅鸿兘鏈哄櫒瀛︿範）——统计可读性满分，靠常用字占比识别
        data = "人工智能机器学习\n".encode("utf-8").decode("gb18030").encode("utf-8")
        r = detect_encoding(data)
        self.assertTrue(r["mojibake"])
        text, _ = decode_with_report(data)
        self.assertEqual(text, "人工智能机器学习\n")

    def test_double_mojibake_cycle_not_loop(self):
        # 双重乱码 A→B→A 反转循环：必须标记 unrecoverable 且不进入死循环、
        # 不误采纳反转中间态（鍙岄噸 ↔ 锛堥崣）
        data = "（鍙岄噸涔辩爜鍚庣殑鏂囨湰）".encode("utf-8")
        r = detect_encoding(data)
        self.assertTrue(r["unrecoverable"])
        self.assertFalse(r["mojibake"])

    def test_mid_signal_mojibake_still_recovered(self):
        # 中信号乱码：原文常用字率中等（ratio~0.4，如古文/专业书）被 BIG5-as-GBK
        # 误读，恢复差值仅 ~+16——受保护门槛（+10）不得误伤，仍须恢复
        mid = "昔者莊周夢為胡蝶，栩栩然胡蝶也，自喻適志與！不知周也。"
        data = mid.encode("big5").decode("gb18030").encode("utf-8")
        r = detect_encoding(data)
        self.assertTrue(r["mojibake"], r["reasons"])
        self.assertEqual(r["encoding"], "big5")
        text, _ = decode_with_report(data)
        self.assertEqual(text, mid)

    def test_ansi_latin1_mojibake_recovery(self):
        # UTF-8 被按 ANSI/Latin-1 误读后另存为 UTF-8（è…çš„ 型）：反转链 latin-1 对恢复
        src = "第一章　序章\n夜色渐深，他站在窗前，望着远处灯火阑珊的城市。"
        data = src.encode("utf-8").decode("latin-1").encode("utf-8")
        r = detect_encoding(data)
        self.assertTrue(r["mojibake"], r["reasons"])
        text, _ = decode_with_report(data)
        self.assertEqual(text, src)

    def test_double_ansi_mojibake_recovery(self):
        # 双层 ANSI 误读：中间层为纯 latin-1 区间（可读性低）须允许过渡继续反转
        src = "第一章　序章\n夜色渐深，他站在窗前，望着远处灯火阑珊的城市。"
        data = src.encode("utf-8").decode("latin-1").encode("utf-8").decode("latin-1").encode("utf-8")
        r = detect_encoding(data)
        self.assertTrue(r["mojibake"], r["reasons"])
        text, _ = decode_with_report(data)
        self.assertEqual(text, src)


class TestIdempotency(unittest.TestCase):
    """幂等性：正常 UTF-8 中文必须原样输出，绝不能反转成乱码。

    UTF-8 中文的字节组合（如 E4 BD A0）在 GBK 字典中可能恰好合法，
    反转候选必须无法胜过 UTF-8 直解（常用字保护 + 总分打平直解优先）。
    """

    def _assert_idempotent(self, text):
        data = text.encode("utf-8")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "utf-8", r["reasons"])
        self.assertFalse(r["mojibake"], r["reasons"])
        self.assertFalse(r["garbage"])
        out, _ = fix_to_utf8(data)
        self.assertEqual(out.decode("utf-8"), text)

    def test_utf8_ni_hao_shi_jie(self):
        # 你好世界 UTF-8（E4 BD A0 E5 A5 BD 在 GBK 中全合法）
        self._assert_idempotent("你好世界")

    def test_utf8_mixed_ascii_chinese(self):
        self._assert_idempotent("The quick brown fox 跳过了 lazy dog，12345。")

    def test_utf8_novel_paragraph(self):
        # 简体小说段落
        self._assert_idempotent(
            "第一章　序章\n夜色渐深，他站在窗前，望着远处灯火阑珊的城市。"
            "这一去，不知何时才能回来。")
        # 繁体小说段落
        self._assert_idempotent(
            "第一章　序章\n夜色漸深，他站在窗前，望著遠處燈火闌珊的城市。"
            "這一去，不知何時才能回來。")

    def test_utf8_long_text(self):
        self._assert_idempotent(
            "人工智能的发展历程，包括机器学习与深度学习。" * 50
            + "这是对幂等性的长文回归验证。" * 30)

    def test_utf8_rare_chars(self):
        # 僻字密集（常用字占比为 0）：不得因评分低/反转候选微胜而误判 GBK/BIG5
        self._assert_idempotent("龘靐齉爨癵籱饢驫麣纞")

    def test_utf8_rare_chars_long(self):
        self._assert_idempotent("龘靐齉爨癵籱饢驫麣纞" * 20)

    def test_utf8_repeated_rare_char(self):
        # 低熵 + 零常用字：重复生僻字不得误判
        self._assert_idempotent("龘" * 50000)

    def test_ascii_punctuation_only(self):
        # 纯 ASCII 符号全集：所有编码等价，锁死 utf-8 直解
        self._assert_idempotent("""1234567890!@#$%^&*()_+-=[]{};':",./<>?""")

    def test_repeated_single_byte(self):
        # 低熵重复单字节：不弃权、不误判
        self._assert_idempotent("A" * 100000)


class TestSamplingBoundary(unittest.TestCase):
    """采样边界：多字节字符横跨 2MB 采样边界时检测不得失败或损坏。"""

    def test_utf8_emoji_across_boundary(self):
        line = ("人工智能的发展历程" * 100000).encode("utf-8")  # 27 字节/行
        head = line[:27 * 77672] + b"abcdef"  # 2097150 字节，完整合法
        data = head + "😊".encode("utf-8") + "后续内容".encode("utf-8")
        self.assertGreater(len(data), 2 * 1024 * 1024)
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "utf-8")
        self.assertFalse(r["garbage"])
        text, _ = decode_with_report(data)
        self.assertEqual(text, data.decode("utf-8"))

    def test_gb18030_4byte_across_boundary(self):
        line = ("人工智能的发展历程" * 200000).encode("gb18030")  # 18 字节/行
        head = line[:2097150]  # 完整合法
        data = head + "𠀀".encode("gb18030") + "GBK内容".encode("gb18030")
        self.assertGreater(len(data), 2 * 1024 * 1024)
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "gb18030")
        self.assertFalse(r["garbage"])
        text, _ = decode_with_report(data)
        self.assertIn("𠀀", text)


class TestRobustness(unittest.TestCase):
    """真实世界的边界输入。"""

    def test_gb2312_text(self):
        # GB2312 是 GB18030 子集，应判 gb18030 而非二进制垃圾
        data = "人工智能的发展历程".encode("gb2312")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "gb18030")
        self.assertFalse(r["garbage"])

    def test_ascii_only(self):
        # 纯 ASCII：所有编码等价，必须判 utf-8 且不误报乱码/循环
        r = detect_encoding(b"abc123")
        self.assertEqual(r["encoding"], "utf-8")
        self.assertFalse(r["mojibake"])
        self.assertFalse(r["unrecoverable"])

    def test_truncated_gbk_byte(self):
        # GBK "你好" 截断只剩首字节 0xC4：拒绝而非崩溃
        r = detect_encoding(b"\xc4")
        self.assertTrue(r["garbage"])

    def test_truncated_utf8_emoji(self):
        # UTF-8 emoji（F0 9F 98 8A）截断为 F0 9F 98：拒绝而非崩溃
        r = detect_encoding(b"\xf0\x9f\x98")
        self.assertTrue(r["garbage"])

    def test_utf16be_without_bom(self):
        # UTF-16BE 无 BOM：靠"车道结构校验"识别（高字节车道集中于合法高字节集合）
        r = detect_encoding("你好世界".encode("utf-16-be"))
        self.assertEqual(r["encoding"], "utf-16-be")
        self.assertFalse(r["garbage"])
        text, _ = decode_with_report("你好世界".encode("utf-16-be"))
        self.assertEqual(text, "你好世界")

    def test_utf16le_without_bom(self):
        r = detect_encoding("你好世界".encode("utf-16-le"))
        self.assertEqual(r["encoding"], "utf-16-le")
        self.assertFalse(r["garbage"])
        text, _ = decode_with_report("你好世界".encode("utf-16-le"))
        self.assertEqual(text, "你好世界")

    def test_utf16_32_with_bom_roundtrip(self):
        # 带 BOM 的 UTF-16/32（Windows 导出常见）：四种组合都必须正确解码并
        # 字节级还原——绝不允许回落 utf-8 replace 产出替换符（P1 回归钉）
        src = GBK_TEXT + "The river flows quietly.\n"
        for bom, enc in ((b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"),
                         (b"\xff\xfe\x00\x00", "utf-32-le"), (b"\x00\x00\xfe\xff", "utf-32-be")):
            with self.subTest(enc=enc):
                data = bom + src.encode(enc)
                r = detect_encoding(data)
                self.assertFalse(r["garbage"], r["reasons"])
                self.assertEqual(r["confidence"], 1.0)
                text, _ = decode_with_report(data)
                self.assertEqual(text, src)
                self.assertEqual(text.count("\ufffd"), 0)
                out, _ = fix_to_utf8(data)
                self.assertEqual(out.decode("utf-8"), src)

    def test_single_gbk_char_no_cycle(self):
        # 合法 GBK 单字：不得因反转 A↔B 摇摆被误判"多重误读循环"而拒绝
        r = detect_encoding("你".encode("gb18030"))
        self.assertEqual(r["encoding"], "gb18030")
        self.assertFalse(r["garbage"])
        self.assertFalse(r["unrecoverable"])
        text, _ = decode_with_report("你".encode("gb18030"))
        self.assertEqual(text, "你")

    def test_head_byte_loss_repair(self):
        # 头部丢 2 字节（丢换行+首字首字节，游离续字节开头）：头部修剪恢复
        data = "第一章\u3000序章\n夜色渐深。".encode("utf-8")[2:]
        r = detect_encoding(data)
        self.assertFalse(r["garbage"])
        self.assertTrue(r.get("head_trimmed"))
        text, _ = decode_with_report(data)
        self.assertEqual(text, "一章\u3000序章\n夜色渐深。")

    def test_random_corruption_repair(self):
        # 随机腐蚀 0.1% 字节：宽松替换解码兜底（损伤可控），不整本拒绝
        import random
        rng = random.Random(7)
        data = bytearray("人工智能的发展历程，包括机器学习与深度学习。" * 40 + "全书正文。" * 20, "utf-8")
        for pos in rng.sample(range(len(data)), max(1, int(len(data) * 0.001))):
            data[pos] ^= 0xFF
        r = detect_encoding(bytes(data))
        self.assertFalse(r["garbage"])
        self.assertTrue(r.get("lossy"))
        text, _ = decode_with_report(bytes(data))
        self.assertGreaterEqual(text.count("\ufffd"), 1)
        self.assertIn("机器学习", text)

    def test_nul_injection_repair(self):
        # 低密度 NUL 注入（每 500 字节一个）：NUL 剥离后还原，不整本拒绝
        base = "人工智能的发展历程。" * 100
        data = b""
        step = 0
        for ch in base.encode("utf-8"):
            data += bytes([ch])
            step += 1
            if step % 500 == 0:
                data += b"\x00"
        r = detect_encoding(data)
        self.assertFalse(r["garbage"])
        self.assertTrue(r.get("nul_stripped"))
        text, _ = decode_with_report(data)
        self.assertEqual(text, base)

    def test_large_input_sampled(self):
        # 大输入：检测在 2MB 采样上进行，结果正确且不慢
        big = ("人工智能的发展历程，" * 400000).encode("utf-8")
        self.assertGreater(len(big), 3 * 1024 * 1024)
        r = detect_encoding(big)
        self.assertEqual(r["encoding"], "utf-8")
        self.assertFalse(r["garbage"])

    def test_single_long_line_no_newline(self):
        # 超长单行（>2MB、无换行符）：检测不依赖 \n 统计
        line = ("ACGT" * 400000 + "中间中文段落" + "TGC" * 400000).encode("utf-8")
        self.assertGreater(len(line), 2 * 1024 * 1024)
        self.assertNotIn(b"\n", line)
        r = detect_encoding(line)
        self.assertEqual(r["encoding"], "utf-8")
        self.assertFalse(r["garbage"])
        text, _ = decode_with_report(line)
        self.assertIn("中间中文段落", text)

    def test_nul_byte_utf8(self):
        # NUL 混入：判垃圾拒绝（不静默截断 NUL 之后的内容）
        r = detect_encoding("你好\x00世界".encode("utf-8"))
        self.assertTrue(r["garbage"])

    def test_nul_byte_gb18030(self):
        r = detect_encoding("你好\x00世界".encode("gb18030"))
        self.assertTrue(r["garbage"])

    def test_utf16le_ascii_without_bom(self):
        # 纯英文 UTF-16LE 无 BOM（0x00 占比 50%）：不得误走"二进制/NUL 剥离"通道，
        # round-trip 字节级必须 100% 一致
        src = "The quick brown fox jumps over the lazy dog."
        data = src.encode("utf-16-le")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "utf-16-le")
        self.assertFalse(r["garbage"])
        text, _ = decode_with_report(data)
        self.assertEqual(text, src)
        out, _ = fix_to_utf8(data)
        self.assertEqual(out.decode("utf-8").encode("utf-16-le"), data)

    def test_all_spaces_no_newline(self):
        # 1024 个连续空格（无换行）：必须原样通过, 不得误判 UTF-16/GBK 或加 BOM
        data = b" " * 1024
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "utf-8")
        self.assertFalse(r["garbage"])
        out, _ = fix_to_utf8(data)
        self.assertEqual(out, data)

    def test_shiftjis_kana_detected(self):
        # 纯日文平假名（无 ASCII 锚点）：0x82A0 系字节在 GB18030 中是合法冷僻汉字,
        # 不得被误译为中文——须识别为 shift_jis
        jp = "これは日本語のテキストです。読みやすい文章を書いています。\n" * 50
        data = jp.encode("shift_jis")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "shift_jis", r["reasons"])
        self.assertFalse(r["garbage"])
        text, _ = decode_with_report(data)
        self.assertEqual(text, jp)

    def test_euckr_hangul_detected(self):
        ko = "이것은 한국어 텍스트입니다. 읽기 쉬운 문장을 쓰고 있습니다.\n" * 50
        data = ko.encode("euc_kr")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "euc_kr", r["reasons"])
        self.assertFalse(r["garbage"])
        text, _ = decode_with_report(data)
        self.assertEqual(text, ko)

    def test_latin1_western_precheck(self):
        # 西文 UTF-8 被逐字节按 Latin-1 误读后另存（Ã© 型）: 结构签名预检还原
        src = "café résumé déjà vu — naïve façade, coeur de la ville.\n" * 20
        data = src.encode("utf-8").decode("latin-1").encode("utf-8")
        r = detect_encoding(data)
        self.assertTrue(r["mojibake"], r["reasons"])
        text, _ = decode_with_report(data)
        self.assertEqual(text, src)
        out, _ = fix_to_utf8(data)
        self.assertEqual(out, src.encode("utf-8"))

    def test_irreversible_chain_refused(self):
        # GBK 系双层乱码: 还原链引入大量替换符, 字节级信息已毁 —— 必须标记 irreversible
        src = "第一章\u3000序章\n夜色渐深，他站在窗前。\n" * 300
        data = (src.encode("utf-8").decode("gb18030", errors="replace").encode("utf-8")
                .decode("gb18030", errors="replace").encode("utf-8"))
        r = detect_encoding(data)
        self.assertTrue(r.get("irreversible"), r["reasons"])

    def test_bom_mismatch_utf8bom_utf16_content(self):
        # UTF-8 BOM + UTF-16 内容: 不得按 utf-8-sig 错读全文, 应剥离 BOM 后识别 utf-16
        src = "第一章\u3000序章\n夜色渐深，他站在窗前。\n" * 200
        data = b"\xef\xbb\xbf" + src.encode("utf-16")
        r = detect_encoding(data)
        self.assertFalse(r["garbage"], r["reasons"])
        text, _ = decode_with_report(data)
        self.assertEqual(text, src)

    def test_bom_mismatch_utf16bom_utf8_content(self):
        # UTF-16 BOM + UTF-8 内容: 不得按 utf-16 错读成随机 CJK, 应剥离 BOM 后识别 utf-8
        src = "第一章\u3000序章\n夜色渐深，他站在窗前。\n" * 200
        data = b"\xff\xfe" + src.encode("utf-8")
        r = detect_encoding(data)
        self.assertFalse(r["garbage"], r["reasons"])
        text, _ = decode_with_report(data)
        self.assertEqual(text, src)

    def test_french_text_not_misjudged(self):
        # 合法西文（法语, 含重音）: é 等是合法字母, 不得被 GB18030 错解成汉字
        fr = "Voici un texte fran\u00e7ais avec des accents \u00e9 \u00e8 \u00ea \u00e0 \u00e7 \u00f9.\n" * 50
        data = fr.encode("utf-8")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "utf-8", r["reasons"])
        self.assertFalse(r["garbage"])
        text, _ = decode_with_report(data)
        self.assertEqual(text, fr)

    def test_french_accent_dense_not_rejected(self):
        # 重音密集西文: 不得因"乱码区字符占比高"被误判垃圾/多重误读拒修
        fr = ("\u00e9\u00e8\u00ea\u00e0\u00e7\u00f9\u00e9\u00e8\u00ea\u00e0\u00e7\u00f9 " * 200) + "\n"
        data = fr.encode("utf-8")
        r = detect_encoding(data)
        self.assertFalse(r["garbage"])
        self.assertFalse(r["unrecoverable"])
        text, _ = decode_with_report(data)
        self.assertEqual(text, fr)


class TestReplacementAndIrreversible(unittest.TestCase):
    """替换符统一口径：replacement_chars 全路径携带，irreversible 三路径同门槛。"""

    def test_clean_text_zero_replacement(self):
        r = detect_encoding(GBK_TEXT.encode("gb18030"))
        self.assertEqual(r["replacement_chars"], 0)
        self.assertFalse(r["irreversible"])

    def test_bom_with_minor_damage_tolerated(self):
        # BOM + 正文含少量坏字节（<5% 替换符）：按 BOM 直解放行，但必须带
        # replacement_chars 计数（前端/消息据此警示带损恢复），不标 irreversible
        rng = random.Random(42)
        body = bytearray(b"He said something about the river. " * 800)
        for pos in rng.sample(range(len(body)), 40):
            body[pos] = rng.randrange(0x80, 0xFF)
        data = b"\xef\xbb\xbf" + bytes(body)
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "utf-8-sig")
        self.assertFalse(r["garbage"])
        self.assertGreaterEqual(r["replacement_chars"], 20)
        self.assertFalse(r["irreversible"])
        text, _ = decode_with_report(data)
        self.assertEqual(text.count("\ufffd"), r["replacement_chars"])

    def test_bom_with_major_damage_irreversible(self):
        # BOM + 正文 ~3% 替换符（>=20 处）：自洽校验放行（<=5%），
        # 但统一 irreversible 门槛（>1% 且 >=20）必须拒绝修复
        # （腐蚀率 0.8%：每处坏字节产生 1~2 个替换符，实测 3.17% 落在窗口内）
        rng = random.Random(7)
        body = bytearray(GBK_TEXT.encode("utf-8") * 50)
        for pos in rng.sample(range(len(body)), int(len(body) * 0.008)):
            body[pos] = rng.randrange(0x80, 0xFF)
        data = b"\xef\xbb\xbf" + bytes(body)
        r = detect_encoding(data)
        self.assertFalse(r["garbage"])  # 自洽校验仍放行（替换符 <5%）
        self.assertTrue(r["irreversible"], r["reasons"])

    def test_lossy_minor_damage_tolerated(self):
        # 0.1% 字节腐蚀 → 有损兜底恢复：损伤 <1% 低于不可逆门槛，放行但带计数
        rng = random.Random(7)
        data = bytearray("人工智能的发展历程，包括机器学习与深度学习。" * 300, "utf-8")
        for pos in rng.sample(range(len(data)), max(1, int(len(data) * 0.001))):
            data[pos] ^= 0xFF
        text, r = decode_with_report(bytes(data))
        self.assertTrue(r.get("lossy"))
        self.assertFalse(r["irreversible"])
        self.assertGreaterEqual(r["replacement_chars"], 1)
        self.assertEqual(text.count("\ufffd"), r["replacement_chars"])

    def test_lossy_major_damage_irreversible(self):
        # 1% 字节腐蚀 → 有损兜底恢复出 ~5% 替换符：超不可逆门槛，fix() 必须拒绝
        rng = random.Random(7)
        data = bytearray("人工智能的发展历程，包括机器学习与深度学习。" * 300, "utf-8")
        for pos in rng.sample(range(len(data)), int(len(data) * 0.01)):
            data[pos] ^= 0xFF
        r = detect_encoding(bytes(data))
        self.assertTrue(r["irreversible"], r["reasons"])


class TestTypographyPunctuation(unittest.TestCase):
    """排版标点不参与乱码扣分：对话密集文本不得压分/误反转（N2 回归）。"""

    def test_punctuation_soup_not_reversed(self):
        # 极端标点汤（~35% 弯引号/破折号/省略号）：修复前会被误反转成 big5 乱码
        soup = "\u201c\u2026\u2026\u597d\u5427\u3002\u201d\u4ed6\u8bf4\uff1a\u201c\u8d70\u5427\u2014\u2014\u201d\n"
        text = soup * 500
        r = detect_encoding(text.encode("utf-8"))
        self.assertEqual(r["encoding"], "utf-8", r["reasons"])
        self.assertFalse(r["mojibake"], r["reasons"])
        self.assertGreaterEqual(r["confidence"], 0.95)
        out, _ = fix_to_utf8(text.encode("utf-8"))
        self.assertEqual(out.decode("utf-8"), text)

    def test_dialogue_chinese_stays_utf8(self):
        para = "夜色渐深，他站在窗前望着远处灯火阑珊的城市。"
        text = ("“%s”他说，“……走吧——”\n" % para) * 400
        r = detect_encoding(text.encode("utf-8"))
        self.assertEqual(r["encoding"], "utf-8")
        self.assertFalse(r["mojibake"])
        self.assertGreaterEqual(r["confidence"], 0.9)
        out, _ = fix_to_utf8(text.encode("utf-8"))
        self.assertEqual(out.decode("utf-8"), text)

    def test_curly_quote_english_confidence(self):
        text = "He said, “It’s a fine day — isn’t it?” She nodded… \n" * 500
        r = detect_encoding(text.encode("utf-8"))
        self.assertEqual(r["encoding"], "utf-8")
        self.assertFalse(r["mojibake"])
        self.assertGreaterEqual(r["confidence"], 0.95)


class TestMoreRecoveryPairs(unittest.TestCase):
    """补齐反转对覆盖：cp1252 系（结构预检）与 gb18030→big5（可 strict 构造）。

    ("big5","utf-8") / ("utf-8","gb18030") 两对要求字节流同时满足两种编码的
    strict 合法性——UTF-8 续字节 0x80-A0 不是合法 big5/gb 尾字节的场景占绝
    对多数，CJK 实际文本几乎无法构造，保留为启发式不作单测。
    """

    def test_cp1252_as_utf8_recovery(self):
        # 西文被按 cp1252 逐字节误读后另存（Ã© 型）：走 latin-1 西文结构预检还原
        src = "café — naïve ‘quo’té… déjà où\n" * 4
        data = src.encode("utf-8").decode("cp1252").encode("utf-8")
        r = detect_encoding(data)
        self.assertTrue(r["mojibake"], r["reasons"])
        text, _ = decode_with_report(data)
        self.assertEqual(text, src)

    def test_gb18030_as_big5_recovery(self):
        # gb 字节恰为合法 big5（“你好世界”的 GBK 编码在 big5 中逐对合法）
        src = "你好世界" * 3
        data = src.encode("gb18030").decode("big5").encode("utf-8")
        r = detect_encoding(data)
        self.assertTrue(r["mojibake"], r["reasons"])
        self.assertEqual(r["encoding"], "gb18030")
        text, _ = decode_with_report(data)
        self.assertEqual(text, src)


class TestFixToUtf8Garbage(unittest.TestCase):
    """fix_to_utf8 对垃圾输入的行为钉住：返回替换文本 + garbage 标记，不抛异常。"""

    def test_binary_garbage_returns_report(self):
        out, r = fix_to_utf8(bytes(range(256)) * 4)
        self.assertIsInstance(out, bytes)
        self.assertTrue(r["garbage"])
        self.assertEqual(r["confidence"], 0.0)

    def test_truncated_utf8_rejected(self):
        out, r = fix_to_utf8(b"\xf0\x9f\x98")
        self.assertTrue(r["garbage"])


class TestTailTruncation(unittest.TestCase):
    """尾部截断：analyze 只读 2MB 前缀，边界切断多字节字符不得误判垃圾（P0 回归）。

    候选阶段有 _strict_decode_tail（≤8 字节尾部回退）兜底，而全量解码阶段
    原本没有——2MB 边界切中字符时 analyze 会自相矛盾地报 garbage（fix 全量
    却正常）。修复后两阶段口径一致。
    """

    def test_utf8_prefix_truncated_mid_char(self):
        # 复刻 analyze()：2MB 前缀恰在 3 字节汉字中段截断
        text = "人工智能的发展历程。" * 300000  # 30 字节/重复
        data = text.encode("utf-8")[:2 * 1024 * 1024]
        self.assertEqual(len(data) % 30, 2)  # 边界确实切在字符中间
        r = detect_encoding(data)
        self.assertFalse(r["garbage"], r["reasons"])
        self.assertEqual(r["encoding"], "utf-8")
        out, _ = fix_to_utf8(data)
        self.assertEqual(out.decode("utf-8"), text[:len(data) // 3])

    def test_gb18030_prefix_truncated_mid_char(self):
        text = "人工智能的发展历程，包括机器学习与深度学习。" * 100000  # 44 字节/重复
        data = text.encode("gb18030")[:2 * 1024 * 1024 - 1]  # 奇数边界切断 2 字节字符
        self.assertEqual(len(data) % 2, 1)
        r = detect_encoding(data)
        self.assertFalse(r["garbage"], r["reasons"])
        self.assertEqual(r["encoding"], "gb18030")
        text_out, _ = decode_with_report(data)
        self.assertEqual(text_out, text[:len(data) // 2])

    def test_small_tail_truncation(self):
        # 与文件大小无关：任何尾部切断的多字节流都不再误判垃圾
        data = GBK_TEXT.encode("utf-8")[:-1]
        r = detect_encoding(data)
        self.assertFalse(r["garbage"], r["reasons"])
        out, _ = fix_to_utf8(data)
        self.assertEqual(out.decode("utf-8"), GBK_TEXT[:-1])

    def test_tail_damage_beyond_fallback_still_rejected(self):
        # 2MB 采样内干净、尾部 >8 字节垃圾：尾部回退救不了 → 维持垃圾判定
        data = ("人工智能的发展历程。" * 70000).encode("utf-8") + bytes([0xFF] * 9)
        r = detect_encoding(data)
        self.assertTrue(r["garbage"], r["reasons"])

    def test_tiny_fragment_still_rejected(self):
        # 超短残片（截断的 emoji）：尾部回退产物 <8 字符时编码判定不可信，维持垃圾
        data = b"\xf0\x9f\x98"
        r = detect_encoding(data)
        self.assertTrue(r["garbage"], r["reasons"])


if __name__ == "__main__":
    unittest.main()
