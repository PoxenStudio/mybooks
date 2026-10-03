# -*- coding: utf-8 -*-
"""文本编码检测（TXT 编码修复 / 正文查找替换 两插件共用，不依赖 MyBooks）。

检测策略（按优先级）：
1. **BOM 优先**：UTF-8 BOM / UTF-16 BOM / UTF-32 BOM 直接判定；
2. **候选编码严格解码打分**：UTF-8 / GB18030 / BIG5 逐个 strict 解码，
   以可读性评分（中文字符占比、替换符、控制字符、常见乱码区）排序；
   无 BOM UTF-16LE/BE 通过"车道结构校验"（高字节车道集中于合法高字节集合）
   后参与竞争；
3. **chardet 三段采样**：开头 / 中间 / 结尾各取样本，chardet 可用时参与投票；
4. **mojibake 反转链**：对首选解码结果尝试常见乱码反转
   （``text.encode(误读编码).decode(真实编码)``），可读性显著提升时采纳，
   并标记 ``mojibake=True`` 供前端提示；覆盖 GBK/BIG5 系 + ANSI/Latin-1 系
   （含多层误读），过短文本（<8 字符）跳过反转防循环误判；
5. **可读性复检**：反转结果与直解结果比较后取最优；
6. **有损兜底**（仅在常规方案判垃圾时）：头部坏字节修剪 → NUL 剥离重检 →
   宽松替换解码（损伤可控才采纳），产出带 ``lossy / damage_ratio /
   head_trimmed / nul_stripped`` 标记的部分恢复文本。

对外主要接口：:func:`detect_encoding`（返回检测报告 dict）、
:func:`decode_with_report`（按报告解码出最终文本）。
"""

import re

try:
    import chardet
except ImportError:  # chardet 缺失时退化为纯规则检测
    chardet = None

# 参与候选打分的编码（strict 解码）。
# shift_jis / euc_kr 用于日韩书籍识别：其字节在 GB18030 中往往恰好构成合法
# 双字节序列（如 0x82A0 系平假名映射为冷僻汉字），若不入候选会被整体误译成
# 中文；识别依赖脚本一致性加分（见 _script_bonus），中文文件不受影响。
CANDIDATE_ENCODINGS = ("utf-8", "gb18030", "big5", "shift_jis", "euc_kr")
# BOM → 编码。UTF-16/32 按字节序精确报告（而非 BOM 自适应的 "utf-16"/"utf-32"）：
# 写回方（如 text_replace 原编码写回）需要据此还原 BOM 与字节序——用 "utf-16"
# encode 恒为本机字节序，会把 UTF-16BE 文件翻转成 LE；decode 侧对 -le/-be 变体
# 解出的行首 U+FEFF 由调用方 lstrip 剥离，行为不变。
_BOM_TABLE = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)

# 乱码反转链：对解码文本尝试 ``text.encode(中间编码).decode(真实编码)`` 组合，
# 可读性显著提升时采纳。常见场景：原编码字节被程序误读（如 BIG5 被按 GB18030 读）
# 后以另一种编码（多为 UTF-8）写盘。
# latin-1/cp1252 对置于最前：ANSI 误读（è…çš„ 型）的乱码文本全部字符 < U+0100，
# 只有它们能通过 ``encode('latin-1')``，正常中文文本必然编码失败自动跳过，零误伤。
_MOJIBAKE_PAIRS = (
    ("latin-1", "utf-8"),   # UTF-8 字节被按 ANSI/Latin-1 误读（è…çš„ 型）
    ("cp1252", "utf-8"),    # UTF-8 字节被按 Windows-1252 误读
    ("gb18030", "big5"),    # BIG5 字节被按 GBK/GB18030 误读
    ("gb18030", "utf-8"),   # UTF-8 字节被按 GBK/GB18030 误读
    ("big5", "utf-8"),      # UTF-8 字节被按 BIG5 误读
    ("big5", "gb18030"),    # GBK 字节被按 BIG5 误读
    ("utf-8", "gb18030"),   # GBK 字节被按 UTF-8 误读（存为乱码 UTF-8）
    ("utf-8", "big5"),      # BIG5 字节被按 UTF-8 误读
)

# 乱码反转的最小文本长度：过短文本（如单字）在任意双字节编码间几乎必然可逆，
# 会导致 A↔B 摇摆被误判为"多重误读循环"而拒绝整本书（合法单字文件被拒的 bug）。
MIN_MOJIBAKE_LEN = 8

# 不可读字符（替换符 / 私用区 / 代理区）
_UNREADABLE_RE = re.compile(
    "[\ufffd\ufffe\uffff\ue000-\uf8ff\ud800-\udfff\ud7b0-\ud7ff]"
)
# 常见乱码字形区（GBK 误读 UTF-8 常落入拉丁-1 补充区等）。
# 两类合法排版字符必须剔除：全角标点区 \uff00-\uffef（正常中文标点）；
# U+2000-206F 中的弯引号/破折号/省略号/全角引号系等常用排版符号——
# 否则对话密集的合法文本被系统性压分，极端标点密度甚至会被误反转（实测复现）。
_MOJIBAKE_CHAR_RE = re.compile(
    "[\u0080-\u00ff\u0100-\u017f"
    "\u2000-\u2012\u2015-\u2017\u201b\u2023-\u2025\u2027-\u202f\u2031\u2034-\u2038\u203b-\u206f]"
)
# 控制字符（保留 \n \r \t）
_CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CJK_RE = re.compile("[\u3400-\u4dbf\u4e00-\u9fff]")
# 日文假名（平假名+片假名）与韩文谚文音节——用于日韩编码的脚本一致性加分
_KANA_RE = re.compile("[\u3040-\u30ff]")
_HANGUL_RE = re.compile("[\uac00-\ud7af]")

SAMPLE_CHARS = 800  # 报告中的可读性样本长度
SAMPLE_LIMIT = 2 * 1024 * 1024  # 检测采样上限：候选打分 / chardet / 反转链只在前缀上进行，
# 全量解码仅对最终方案执行一次，避免超大文件（数百 MB）多次全量解码导致 OOM

# 高频常用字（简繁混合，500+）：正常中文文本命中率高（>50%），
# 误读乱码字（鍙岄噸/浜哄伐/锛堥崣 类）几乎不命中，用于识别
# "字形全部合法、统计可读性满分"的语义级乱码（如 UTF-8 被按 GBK 误读）。
_COMMON_CHARS = frozenset(
    "的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高自二理起小物现实加量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那社义事平形相全表间样与关各重新线内数正心反你明看原又么利比或但质气第向道命此变条只没结解问意建月公无系军很情者最立代想已通并提直题党程展五果料象员革位入常文总次品式活设及管特件长求老头基资边流路级少图山统接知较将组见计别她手角期根论运农指几九区强放决西被干做必战先回则任取据处队南给色光门即保治北造百规热领七海口东导器压志世金增争济阶油思术极交受联什认六共权收证改清己美再采转更单风切打白教速花带安场身车例真务具万每目至达走积示议声报斗完类八离华名确才科张信马节话米整空元况今集温传土许步群广石记需段研界拉林律叫且究观越织装影算低持音众书布复容儿须际商非验连断深难近矿千周委素技备半办青省列习响约支般史感劳便团往酸历市克何除消构府称太准精值号率族维划选标写存候毛亲快效斯院查江型眼王按格养易置派层片始却专状育厂京识适属圆包火住调满县局照参红细引听该铁价严龙飞"
    "這為說時從們發頭國門長經還樣處對進級紅綠簡復書語話認識認真體紙間題問聞隊際陽陰險幾爾東樂習鄉歸開閉學黨興舉親觀覽馬魚鳥貝見車銀門電產業發展電腦軟體資訊網路臺灣機學習深度人工智慧書籍內容涵蓋作者"
)


def _common_ratio(text):
    """高频常用字占比：正常中文文本 >0.5，误读乱码文本通常 <0.1。"""
    if not text:
        return 0.0
    sample = text[:2000]
    if not sample:
        return 0.0
    return sum(1 for ch in sample if ch in _COMMON_CHARS) / len(sample)


def _script_bonus(enc, text):
    """编码-脚本一致性加分：shift_jis 解释按假名占比、euc_kr 解释按谚文占比
    给予最高 +25 的加成。GB18030 对日韩字节的误译结果是冷僻汉字（无假名/谚文），
    拿不到加分；真实日韩文本则借此在与中文候选同分时胜出。"""
    if enc not in ("shift_jis", "euc_kr"):
        return 0.0
    sample = text[:2000]
    n = len(sample)
    if not n:
        return 0.0
    if enc == "shift_jis":
        ratio = len(_KANA_RE.findall(sample)) / n
    else:
        ratio = len(_HANGUL_RE.findall(sample)) / n
    return min(25.0, ratio * 50.0)


def _plan_total(enc, text):
    """统一方案评分：可读性 + 常用字加成 + 编码-脚本一致性加分。"""
    return _score_total(text) + _script_bonus(enc, text)


def _score_total(text):
    """统一方案评分：可读性为主 + 常用字占比加成（识别语义级乱码）。"""
    return _readability_score(text) + min(30.0, _common_ratio(text) * 40.0)


def _readability_score(text):
    """0~100 可读性评分：中文书籍文本得分应显著高于乱码结果。

    西文豁免：合法西文文本（ASCII 字母 + éèñ 等 U+00C0-U+00FF 字母为主，
    由 :func:`_western_like` 判定）的拉丁补充区是正常字母，不得按乱码扣分——
    否则法语等合法文本的 utf-8 直解会被 GB18030 错解（凭 CJK 加分）反超成
    汉字垃圾。误读型乱码（Ã© 型，含大量 U+0080-U+00BF 符号）特征不满足，
    不受豁免影响。
    """
    if not text:
        return 0.0
    sample = text[:2000]
    n = len(sample)
    if n == 0:
        return 0.0

    western = _western_like(text)
    replace_count = len(_UNREADABLE_RE.findall(sample))
    control_count = len(_CONTROL_RE.findall(sample))
    cjk_count = len(_CJK_RE.findall(sample))
    mojibake_count = 0 if western else len(_MOJIBAKE_CHAR_RE.findall(sample))

    # 可读字符 = 常规字符（非替换/非控制/非乱码字形）
    readable = n - replace_count - control_count - mojibake_count
    score = 100.0 * readable / n

    # 中文书籍文本 CJK 占比应较高，加权；纯英文书亦应可读（CJK 为 0 时不惩罚）
    cjk_ratio = cjk_count / n
    if cjk_ratio > 0.1:
        score += min(15.0, cjk_ratio * 40.0)

    # 替换符密集 = 强乱码信号
    score -= min(60.0, replace_count / max(n, 1) * 500.0)
    # 控制字符（非换行制表）几乎必为乱码/二进制
    score -= min(80.0, control_count / max(n, 1) * 1000.0)
    return max(0.0, min(100.0, score))


def _strict_decode(data, encoding):
    try:
        return data.decode(encoding, errors="strict")
    except (UnicodeDecodeError, LookupError):
        return None


def _sample_segments(data, size=2048, count=3):
    """取开头 / 中间 / 结尾三段样本字节。"""
    if len(data) <= size:
        return [data]
    segs = [data[:size]]
    mid = len(data) // 2
    segs.append(data[mid:mid + size])
    segs.append(data[-size:])
    return segs


def _chardet_vote(data):
    """chardet 三段采样投票；返回 (encoding, confidence) 或 None。"""
    if chardet is None:
        return None
    segs = _sample_segments(data)
    votes = {}
    voted = 0
    for seg in segs:
        try:
            guess = chardet.detect(seg)
        except Exception:
            continue
        enc = (guess.get("encoding") or "").lower()
        conf = guess.get("confidence") or 0.0
        if enc and conf > 0.3:
            votes[enc] = votes.get(enc, 0.0) + conf
            voted += 1
    if not votes:
        return None
    best = max(votes.items(), key=lambda kv: kv[1])
    # 分母只计实际投票的段：未过 0.3 门槛 / 采样异常的段不稀释置信度
    return (best[0], best[1] / voted)


def _decode_candidates(data):
    """对候选编码逐个 strict 解码（尾部截断自动回退），返回 [(encoding, text, score)] 按得分降序。

    无 BOM UTF-16LE/BE 仅在通过"车道结构校验"时参与竞争：Python 的 UTF-16
    strict 解码对任意偶数长字节流都不会报错，若不设门槛会把 GBK/BIG5 等
    正常文件误判成"可读"的错位 UTF-16 文本。
    """
    results = []
    for enc in CANDIDATE_ENCODINGS:
        text = _strict_decode_tail(data, enc)
        if text is None:
            continue
        # shift_jis 含半角片假名单字节区（0xA1-0xDF），任意孤立高字节都"可解码"；
        # 过短文本（如截断的 GBK 首字节 0xC4）会被误判为半个假名——要求至少 4 字符
        if enc in ("shift_jis", "euc_kr") and len(text) < 4:
            continue
        results.append((enc, text, _readability_score(text)))
    for enc in ("utf-16-le", "utf-16-be"):
        if _utf16_lane_ok(data, enc):
            text = _strict_decode_tail(data, enc)
            if text is not None:
                results.append((enc, text, _readability_score(text)))
    results.sort(key=lambda r: r[2], reverse=True)
    return results


def _utf16_lane_ok(data, enc):
    """无 BOM UTF-16 车道结构校验：文本型 UTF-16 的高字节车道应集中在
    ASCII 高位(0x00) / 通用标点(0x20) / CJK 符号区(0x30-0x3F) /
    CJK 汉字(0x4E-0x9F) / 全角区(0xFF) 等合法高字节集合。

    正常 UTF-8 / GBK / BIG5 字节流的车道字节落在该集合的比例远低于
    阈值（UTF-8 仅 ~20-30%），真实中文/ASCII 文本的 UTF-16 则达 90%+。

    编码结构特征在文件头即完备，车道统计在采样前缀上进行，避免对
    数十 MB 文件做纯 Python 全量逐字节扫描。
    """
    data = data[:SAMPLE_LIMIT]
    lane = data[1::2] if enc == "utf-16-le" else data[0::2]
    if len(lane) < 4:
        return False
    good = sum(
        1 for b in lane
        if b == 0x00 or b == 0x20 or 0x30 <= b <= 0x3F or 0x4E <= b <= 0x9F or b == 0xFF)
    return good / len(lane) >= 0.85


def _strict_decode_tail(data, enc):
    """对（可能尾部截断的）前缀严格解码：失败时回退至多 8 字节再试。

    采样截断可能切断多字节字符（UTF-8 3/4 字节、GBK/BIG5 双字节），
    直接 strict 解码会误报"无法解码"；回退尾部字节可恢复对齐。
    """
    for cut in range(9):
        chunk = data if cut == 0 else data[:-cut]
        if not chunk:
            continue  # 回退到空串不算有效解码（避免 1 字节截断文件被当成候选）
        try:
            return chunk.decode(enc, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
    return None


def _is_latin1_intermediate(text):
    """是否为纯 latin-1 区间文本（全部字符 < U+0100）。

    ANSI 误读的乱码文本全部由 latin-1 字符构成（含大量 C1 控制符，可读性仅 ~35，
    过不了 60 分的单步门槛）；这类中间态允许继续反转，最终结果仍需可读性达标才采纳。
    正常中文/英文文本（含任意 CJK 或 >U+00FF 字符）不满足，不会被误放行。
    """
    if not text:
        return False
    return all(ord(ch) < 0x100 for ch in text[:2000])


def _try_mojibake_recovery(text, max_rounds=3):
    """迭代乱码反转：每轮尝试 ``text.encode(中间编码).decode(真实编码)`` 组合，
    对结果继续反转（支持双重/多重误读）；``visited`` 防止 A→B→A 式循环。

    单步门槛：可读性 >= 60 视为可信出口；纯 latin-1 中间态（ANSI 误读层）允许过渡，
    不当作出口采纳。过短文本（< MIN_MOJIBAKE_LEN）直接跳过反转——单字在任意
    双字节编码间几乎必然可逆，强行反转会摇摆成环被误判为深度误读。

    :return: ((recovered_text, mid_enc, real_enc, score, chain) | None, cycle)
        chain 为按序应用的 (mid_enc, real_enc) 步骤列表（供全量解码逐层重放，
        支持多层反转链——单层假设会在 ANSI 双层等场景断链）。
        cycle=True 表示检测到反转循环（深度误读，最终结果不可信）。
    """
    if len(text) < MIN_MOJIBAKE_LEN:
        return None, False
    best = None  # (recovered_text, mid_enc, real_enc, score, chain)
    cycle = False
    current = text
    chain = []
    visited = {text}
    for _ in range(max_rounds):
        found = None
        found_total = None
        for mid_enc, real_enc in _MOJIBAKE_PAIRS:
            try:
                raw = current.encode(mid_enc)
            except (UnicodeEncodeError, LookupError):
                continue
            recovered = _strict_decode_tail(raw, real_enc)
            if recovered is None or recovered == current:
                continue  # 解码失败或无变化（纯 ASCII 在任意编码下等价）
            score = _readability_score(recovered)
            if score >= 60:
                # 真出口：扫完全部组合取总分最优——首个过线的可能只是次优链路
                total = _score_total(recovered)
                if found is None or total > found_total:
                    found = (recovered, mid_enc, real_enc, score)
                    found_total = total
                continue
            if _is_latin1_intermediate(recovered):
                # latin-1 中间态（ANSI 误读层的结构信号）：按组合顺序立即采纳
                # 并继续反转，不得与同轮"高分的语义级乱码假出口"（如 utf-8→gb18030
                # 对字形合法但语义全无的文本打出 100 分）竞争评分
                found = (recovered, mid_enc, real_enc, score)
                break
        if found is None:
            break
        rec_text, mid_enc, real_enc, rec_score = found
        if rec_text in visited:
            cycle = True
            # 循环无出口：仅当存在"显著更优"的中间态（可读性+常用字）才视为可信，
            # 否则判定深度误读（返回 None 由调用方标记 unrecoverable）
            if best is not None and _score_total(best[0]) > _score_total(text) + 10:
                return best, True
            return None, True
        visited.add(rec_text)
        chain.append((mid_enc, real_enc))
        current = rec_text
        # 高可读性 + 常用字占比显著 → 可信出口，立即停止
        if rec_score >= 90 and _common_ratio(rec_text) > 0.3:
            return (rec_text, mid_enc, real_enc, rec_score, list(chain)), False
        best = rec_text, mid_enc, real_enc, rec_score, list(chain)
    return best, cycle


def _western_like(text):
    """西文特征判定：非空白字符中"ASCII 字母 + U+00C0-U+00FF"占比 >= 0.8。

    用于区分"还原后的西文文本"（éèñ/café 型，合法西文字母）与"仍带乱码的
    latin-1 中间层"（中文 UTF-8 的 latin-1 显示含大量 U+0080-U+00BF 符号/控制符，
    字母占比极低）。空白/标点不计入分母（正常西文文本空格标点占 ~20%）。"""
    sample = text[:2000]
    n = len(sample)
    if n < 16:
        return False
    letters = sum(1 for ch in sample
                  if ("a" <= ch <= "z") or ("A" <= ch <= "Z") or 0x00C0 <= ord(ch) <= 0x00FF)
    non_ws = sum(1 for ch in sample if not ch.isspace())
    if not non_ws:
        return False
    return letters / non_ws >= 0.8


def _latin1_western_precheck(data):
    """西文 latin-1 误读预检（B9）：纯结构信号，不依赖中文可读性评分。

    UTF-8 双字节字符的首字节是 0xC2-0xDF，被按 Latin-1 误读后显示为
    U+00C2-U+00DF（Ã/Â 型）；因此 "UTF-8 字节流被按 latin-1 逐字节解码再
    以 UTF-8 存盘" 的文件，解码后文本中 U+00C0-U+00DF 占比显著（通常 >30%），
    而正常西文（éèñ = U+00E0-U+00FF）或中文文本几乎不出现该区间。

    还原按 fixpoint 迭代（支持多层误读），最终结果须呈西文特征
    （_western_like），防止把中文类乱码的中间层误采纳。

    :return: 还原后的文本；非西文误读场景返回 None。
    """
    try:
        head = _strict_decode_tail(data[:SAMPLE_LIMIT], "utf-8")
    except Exception:
        head = None
    if not head:
        return None
    sample = head[:2000]
    n = len(sample)
    if n < 16:
        return None
    lead_display = sum(1 for ch in sample if 0x00C0 <= ord(ch) <= 0x00DF)
    if lead_display / n < 0.04:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    rec = text
    for _ in range(5):
        try:
            nxt = rec.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break  # 已还原到含非 latin-1 字符的真实文本（如 — 或中文），停止迭代
        if nxt == rec:
            break
        rec = nxt
    if rec == text or not _western_like(rec):
        return None
    return rec


def _try_lossy_recovery(data):
    """有损兜底：常规方案判垃圾 / 无候选时启用，依次尝试三种部分恢复。

    1. 头部坏字节修剪（无损）：丢弃开头 1..8 字节后重新严格解码——文件头被
       截断/损坏（游离续字节、半截 BOM）时，正文仍可无损还原；
    2. NUL 剥离后重检（无损）：低密度 NUL（<=5%）视为传输污染，剥离后内容
       往往是完整原文；
    3. 宽松替换解码（有损）：utf-8 / gb18030 以 errors='replace' 解码，仅当
       损伤可控（替换符占比 <=5%、控制符占比 <=2%、可读性 >=70）才采纳，
       用于随机字节损坏但正文完好的文件。

    :return: (text, report) 或 None（三者均不满足 → 维持垃圾判定拒绝）。
    """
    # 1) 头部修剪（无损 strict）
    #    门槛：可读性 >=80 且 常用字占比 >=0.25 且 修剪量 <=1% 数据。
    #    GBK/BIG5 无自同步结构，剪掉头部字节后错位配对可能拼出"统计可读"的
    #    CJK 垃圾（浣犲ソ 型），常用字占比可将其排除；修剪量限制防止把
    #    完好的小文件（如含 NUL 的短文本）误判成头部损坏。
    max_cut = max(1, int(len(data) * 0.01))
    for cut in range(1, min(9, max_cut) + 1):
        for enc in CANDIDATE_ENCODINGS:
            try:
                text = _strict_decode_tail(data[cut:], enc)
            except Exception:
                continue
            if text is None:
                continue
            score = _readability_score(text)
            if score >= 80 and _common_ratio(text) >= 0.25:
                return _lossy_report(
                    text, encoding=enc, head_trimmed=True, head_cut=cut,
                    reason="头部损坏：丢弃前 %d 字节后按 %s 解码（可读性 %.0f/100）"
                    % (cut, enc, score))
    # 2) NUL 剥离后重检（低密度 NUL 视为污染，剥离即还原）
    if b"\x00" in data and data.count(b"\x00") / max(1, len(data)) <= 0.05:
        cleaned = data.replace(b"\x00", b"")
        if cleaned:
            try:
                sub_text, sub_rep = _analyze(cleaned)
            except Exception:
                sub_rep = None
            if sub_rep and not sub_rep["garbage"] and sub_rep["confidence"] >= 0.8:
                sub_rep["nul_stripped"] = True
                sub_rep["reasons"] = [
                    "剥离 %d 个 NUL 字节后重新检测：%s" % (data.count(b"\x00"), sub_rep["encoding"])
                ] + sub_rep["reasons"]
                return sub_text, sub_rep
    # 3) 宽松替换解码（有损，损伤可控才采纳）
    #    门槛：替换符占比 <=5% 且 控制符占比 <=2% 且 可读性 >=70 且 常用字占比 >=0.15。
    #    常用字门槛排除"错位配对型垃圾"（锟斤拷/莽聸聴 类字形合法但语义全无，
    #    统计可读性虚高，而真实中文文本常用字命中率 >40%）。
    for enc in ("utf-8", "gb18030"):
        try:
            text = data.decode(enc, errors="replace")
        except Exception:
            continue
        if not text:
            continue
        sample_n = min(2000, len(text))
        if sample_n == 0:
            continue
        ratio = text.count("\ufffd") / len(text)
        score = _readability_score(text)
        control = len(_CONTROL_RE.findall(text[:2000])) / sample_n
        if ratio <= 0.05 and score >= 70 and control <= 0.02 and _common_ratio(text) >= 0.15:
            return _lossy_report(
                text, encoding=enc, lossy=True, damage_ratio=round(ratio, 4),
                reason="有损解码兜底：按 %s 替换解码，损伤 %.2f%%（替换符 %d 处）"
                % (enc, ratio * 100, text.count("\ufffd")))
    return None


def _lossy_report(text, encoding, reason, **flags):
    """构造有损恢复的报告（garbage=False，附损伤依据）。"""
    score = _readability_score(text)
    return text, {
        "encoding": encoding,
        "confidence": round(min(1.0, score / 100.0), 2),
        "mojibake": False,
        "garbage": False,
        "unrecoverable": False,
        "sample": text[:SAMPLE_CHARS],
        "reasons": [reason],
        **flags,
    }


# 不可逆门槛：替换符同时超数量与占比才判不可逆
# （少量洞可容忍，带损部分恢复仍优于拒修；BOM 直解 / 有损兜底 / 常规解码三路径同口径）
IRREVERSIBLE_MIN_COUNT = 20


def _finalize_report(text, report):
    """统一收尾：所有产出路径补 ``replacement_chars`` 并按同一门槛判 ``irreversible``。

    替换符 = 上游 errors=replace 误读 / 宽松兜底留下的"洞"，字节级信息已毁。
    数量 >=20 且占比 >1% 时标记 irreversible（fix() 据此拒绝修复，避免产出
    带洞的乱码新书）；低于门槛时保留 replacement_chars 供前端警示"带损恢复"。
    """
    fffd = text.count("\ufffd")
    report["replacement_chars"] = fffd
    if fffd >= IRREVERSIBLE_MIN_COUNT and fffd > max(1, len(text) // 100):
        report["irreversible"] = True
        reasons = report.setdefault("reasons", [])
        if not any("不可逆" in r for r in reasons):
            reasons.append("最终文本含 %d 个替换符(%.1f%%)，字节级信息不可逆，拒绝修复"
                           % (fffd, 100.0 * fffd / max(1, len(text))))
    else:
        report["irreversible"] = False
    return text, report


def _analyze(data):
    """内部完整分析：返回 (text, report)。

    检测阶段（候选打分 / chardet / mojibake 反转）全部在前缀采样上进行，
    最终方案才全量解码一次（防大文件多轮全量解码导致 OOM）；
    ``text`` 是检测 / 恢复后的全文文本（BOM 剥离、mojibake 反转恢复均已应用），
    供修复链路直接使用；``report`` 即 :func:`detect_encoding` 的报告结构。
    """
    reasons = []

    if isinstance(data, str):
        data = data.encode("utf-8")

    if not data:
        return _finalize_report("", {"encoding": "utf-8", "confidence": 0.0, "mojibake": False,
                                     "garbage": False, "unrecoverable": False,
                                     "sample": "", "reasons": ["空文件"]})

    # 1. BOM 优先（文件头字节，全量数据上判定）
    for bom, enc in _BOM_TABLE:
        if data.startswith(bom):
            text = data.decode(enc, errors="replace").lstrip("\ufeff")
            # BOM 内容自洽性校验: 若按 BOM 声称的编码解码产生大量替换符，或解读出的
            # 文本既无常用中文又非西文（错配 BOM 常把 utf-8 内容错读成随机 CJK 垃圾，
            # 替换符反而极少，如 UTF-16 BOM + UTF-8 内容），说明 BOM 与字节流错配
            # （如 UTF-8 BOM + UTF-16 内容 / UTF-16 BOM + UTF-8 内容）。
            # 此时剥离该 BOM 前缀后继续检测，避免全文错位且误报"修复成功"。
            fffd_ratio = text.count("\ufffd") / max(1, len(text))
            coherent = (fffd_ratio <= 0.05
                        and (_common_ratio(text) >= 0.15 or _western_like(text)))
            if coherent:
                reasons.append("检测到 BOM，编码确定为 %s" % enc)
                return _finalize_report(text, {
                    "encoding": enc, "confidence": 1.0, "mojibake": False,
                    "garbage": False, "unrecoverable": False,
                    "sample": text[:SAMPLE_CHARS], "reasons": reasons})
            reasons.append("检测到 %s BOM 但内容不自洽（替换符 %.1f%%），剥离该 BOM 前缀后继续"
                           % (enc, fffd_ratio * 100))
            data = data[len(bom):]

    sample = data[:SAMPLE_LIMIT]

    # 1.5 西文 latin-1 误读预检（Ã© 型结构签名, 先于候选打分, 不依赖中文评分）
    western = _latin1_western_precheck(data)
    if western is not None:
        reasons.append("检测到西文 latin-1 误读（Ã© 型签名），已按 UTF-8 还原")
        w_score = _readability_score(western)
        return _finalize_report(western, {
            "encoding": "utf-8", "confidence": round(min(1.0, w_score / 100.0), 2),
            "mojibake": True, "garbage": False, "unrecoverable": False,
            "sample": western[:SAMPLE_CHARS], "reasons": reasons})

    # 2. 候选编码 strict 解码打分（采样上，尾部截断自动回退）
    candidates = _decode_candidates(sample)
    if not candidates:
        reasons.append("所有候选编码均无法严格解码，疑似二进制或混用编码")
        recovered = _try_lossy_recovery(data)
        if recovered:
            text, rep = recovered
            rep["reasons"] = reasons + rep["reasons"]
            return _finalize_report(text, rep)
        return _finalize_report(data.decode("utf-8", errors="replace"), {
            "encoding": "utf-8", "confidence": 0.0, "mojibake": False,
            "garbage": True, "unrecoverable": False,
            "sample": "", "reasons": reasons})

    # 3. chardet 投票（作为参考依据，不覆盖 strict 打分）
    chardet_guess = _chardet_vote(sample)
    if chardet_guess:
        c_enc, c_conf = chardet_guess
        reasons.append("chardet 投票：%s（%.0f%%）" % (c_enc, c_conf * 100))

    # 4. 对每个候选解码结果尝试乱码反转（无条件），全局选最优方案。
    #    反转起点必须覆盖所有候选：误读文件常以 UTF-8 存盘（直解 utf-8 是
    #    乱码），但其分数可能低于 gb18030 候选的错解，只反转 candidates[0]
    #    会漏掉正确的恢复路径。
    options = []  # (enc, text, mojibake, mid, real, orig_cand_enc, chain)
    cycle_any = False
    for cand_enc, cand_text, cand_score in candidates:
        options.append((cand_enc, cand_text, False, None, None, cand_enc, []))
        recovered, cycle = _try_mojibake_recovery(cand_text)
        if recovered is not None:
            rt, mid, real, rs, chain = recovered
            options.append((real, rt, True, mid, real, cand_enc, chain))
        cycle_any = cycle_any or cycle

    # 方案选择：受保护门槛——若 UTF-8 直解可信（readability >= 60），说明文件
    # 是"无辜的正常 UTF-8"，非 UTF-8 方案（其他编码直解 / 反转）必须显著胜出
    # （total 超出 +10）才可采纳，防僻字/低熵文本被误判为 GBK/BIG5 乱码；
    # 若 UTF-8 直解不可信（误读文本可读性差，如锟斤拷场景），则正常竞争不设门槛。
    # 总分打平时直解优先（保守）。
    utf8_direct = next((o for o in options if o[0] == "utf-8" and not o[2]), None)
    if utf8_direct is not None and _readability_score(utf8_direct[1]) >= 60:
        floor = _plan_total("utf-8", utf8_direct[1]) + 10.0

        def _eff(o):
            if o[0] == "utf-8" and not o[2]:
                return _plan_total(o[0], o[1])
            t = _plan_total(o[0], o[1])
            # 非 UTF-8 方案：总分未显著超过 UTF-8 直解（+10）即视为无效
            return t if t >= floor else -1.0

        best_opt = max(options, key=lambda o: (_eff(o), 1 if not o[2] else 0))
        enc, text, mojibake, mid_enc, real_enc, cand_enc, chain = best_opt
    else:
        best_opt = max(options, key=lambda o: (_plan_total(o[0], o[1]), 1 if not o[2] else 0))
        enc, text, mojibake, mid_enc, real_enc, cand_enc, chain = best_opt
    score = _readability_score(text)
    reasons.append("候选解码：%s（可读性 %.0f/100）" % (cand_enc, score))
    if mojibake:
        reasons.append("乱码反转恢复：按 %s 重读后为 %s（可读性 %.0f/100）"
                       % (mid_enc, real_enc, score))
    elif cycle_any:
        # 反转候选可达但构成循环（A→B→A）：仅当文件本身呈现乱码特征时判不可恢复，
        # 正常文本的候选环不构成拒绝理由（见下方 unrecoverable 门槛）
        reasons.append("检测到乱码反转候选循环（疑似多重误读，视可读性判定是否拒绝）")

    # 5. 全量解码最终方案（仅一次）；反转链按序逐层重放（支持多层误读）
    try:
        if mojibake:
            full_text = data.decode(cand_enc)
            for mid, real in chain:
                full_text = full_text.encode(mid).decode(real)
            score = _readability_score(full_text)
        else:
            full_text = data.decode(enc)
            score = _readability_score(full_text)
    except (UnicodeDecodeError, UnicodeEncodeError):
        # 采样与全量不一致（尾部截断 / 混用编码 / 采样外字符无法往返）：
        # 按 UTF-8 替换解码输出并标记垃圾，拒绝修复而非崩溃
        reasons.append("全量解码失败，疑似尾部截断或混用编码")
        return _finalize_report(data.decode("utf-8", errors="replace"), {
            "encoding": "utf-8", "confidence": 0.0, "mojibake": False,
            "garbage": True, "unrecoverable": False,
            "sample": "", "reasons": reasons})

    confidence = min(1.0, score / 100.0)

    # 循环判定只应作用于"看起来像乱码"的文件：可读性差，或 CJK 密集但常用字极少
    # （语义级乱码特征，如 鍙岄噸 类字形全合法但语义全无）。
    # 正常文本（ASCII 为主 / 中英混合）即使反转候选恰好构成 A↔B 环也不得误拒——
    # 否则合法小文件（如含少量中文的 ASCII 文本）会被误判"多重误读"整体拒绝。
    full_sample = full_text[:2000]
    cjk_ratio = len(_CJK_RE.findall(full_sample)) / max(1, len(full_sample))
    mojibake_ish = score < 60 or (cjk_ratio > 0.3 and _common_ratio(full_text) < 0.15)
    unrecoverable = bool(cycle_any) and not mojibake and mojibake_ish

    # 6. 有损兜底：常规方案判垃圾（可读性 < 30）时尝试部分恢复，
    #    仍无法恢复才维持垃圾判定（由 fix() 拒绝，绝不产出整篇乱码）
    if score < 30:
        recovered = _try_lossy_recovery(data)
        if recovered:
            text, rep = recovered
            rep["reasons"] = reasons + rep["reasons"]
            return _finalize_report(text, rep)

    return _finalize_report(full_text, {
        "encoding": enc,
        "confidence": round(confidence, 2),
        "mojibake": mojibake,
        "garbage": score < 30,
        "unrecoverable": unrecoverable,
        "sample": full_text[:SAMPLE_CHARS],
        "reasons": reasons,
    })


def detect_encoding(data):
    """检测字节流的编码并返回报告。

    :param data: 文件原始字节（str 输入会先按 UTF-8 编码）
    :return dict: ``encoding``（建议解码编码）、``confidence``（0~1）、
        ``mojibake``（是否发生乱码反转恢复）、``garbage``（疑似非文本）、
        ``sample``（可读性最好的解码文本片段）、``reasons``（检测依据列表）。
    """
    return _analyze(data)[1]


def decode_with_report(data):
    """按检测报告解码文本；返回 (text, report)。

    ``text`` 与检测阶段完全一致（BOM 剥离 / mojibake 反转恢复均已应用），
    可直接用于后续处理。
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return _analyze(data)


def fix_to_utf8(data):
    """修复入口：检测并转换为 UTF-8（无 BOM）字节流。

    :return: (utf8_bytes, report)
    """
    text, report = decode_with_report(data)
    return text.encode("utf-8"), report
