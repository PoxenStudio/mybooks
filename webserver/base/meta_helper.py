#!/usr/bin/env python3
"""书籍元数据处理工具：作者/译者解析、标题清洗等。"""
import re
from typing import List, Tuple


# 姓名前的地区/朝代标记，如 [明]、【美】、（清）、(英)、[唐] 等
_DYNASTY_REGION_PREFIX = re.compile(r'^[\[【\(（][^\]】\)）]*[\]】\)）]\s*')

# 姓名尾部的作者标识：空格/连字符 + 著/编/编著/author/editor；或括号包裹
_AUTHOR_SUFFIX = re.compile(
    r'(?:'
    r'\s+(?:著|编|编著)|\s*[-–]\s*(?:著|编|编著)|'
    r'\s+(?:author|Author|editor|Editor)|\s*[-–]\s*(?:author|Author|editor|Editor)|'
    r'\s*[\(\（]\s*(?:著|编|编著|author|Author|editor|Editor)\s*[\)\）]'
    r')$'
)

# 姓名尾部的译者标识：空格/连字符 + 译/translator；或括号包裹
_TRANSLATOR_SUFFIX = re.compile(
    r'(?:'
    r'\s+译|\s*[-–]\s*译|\s*[\(\（]\s*译\s*[\)\）]|'
    r'\s+(?:translator|Translator)|\s*[-–]\s*(?:translator|Translator)|'
    r'\s*[\(\（]\s*(?:translator|Translator)\s*[\)\）]'
    r')$'
)

# 多人分隔符：/ 、 , （英文逗号）
_MULTI_AUTHOR_SEP = re.compile(r'[/、,]')

# 末尾的英文译名括号，如（Jean-Michel Frodon）、(John Smith)
# 内容至少含一个英文字母，允许空格、连字符、·、.、' 等姓名常用符号
_ENGLISH_NAME_BRACKET = re.compile(
    r'\s*[\(\（]\s*[A-Za-z][A-Za-z\s\-·\'.]+\s*[\)\）]$'
)

# 需要过滤掉的无名氏标记
_ANONYMOUS_MARKERS = frozenset({'佚名', 'Unknown', 'unknown', '', None})


def normalize_author_name(value: str) -> str:
    """合并连续空白字符为单个空格，并去除首尾空白。"""
    if not value:
        return ''
    return ' '.join(value.split()).strip()


def guess_authors(authors: List[str]) -> Tuple[List[str], List[str]]:
    """解析原始作者字符串列表，返回 (作者列表, 译者列表)。
    返回的两个列表均已去重、过滤空值、去除首尾空白。
    """
    author_result: List[str] = []
    translator_result: List[str] = []

    for raw in authors or []:
        if raw is None:
            continue
        original = normalize_author_name(str(raw))
        if not original or original in _ANONYMOUS_MARKERS:
            continue

        # 1. 去除前导的地区/朝代标记
        name = _DYNASTY_REGION_PREFIX.sub('', original).strip()
        if not name or name in _ANONYMOUS_MARKERS:
            continue

        # 2. 判断尾部是译者还是作者标识（译者优先匹配，因为 "译" 短于 "translator"）
        is_translator = bool(_TRANSLATOR_SUFFIX.search(name))
        name = _TRANSLATOR_SUFFIX.sub('', name).strip()
        name = _AUTHOR_SUFFIX.sub('', name).strip()
        if not name or name in _ANONYMOUS_MARKERS:
            continue

        # 3. 去除末尾的英文译名括号（角色后缀已处理完，不会误伤 (译) / (editor) 等）
        name = _ENGLISH_NAME_BRACKET.sub('', name).strip()
        if not name or name in _ANONYMOUS_MARKERS:
            continue

        # 4. 按 / 、 , 分割多人
        parts = [normalize_author_name(p) for p in _MULTI_AUTHOR_SEP.split(name)]
        parts = [p for p in parts if p and p not in _ANONYMOUS_MARKERS]

        target = translator_result if is_translator else author_result
        for p in parts:
            cleaned = ''.join(c for c in p.strip() if c.isprintable())
            if cleaned and cleaned not in target:
                target.append(cleaned)

    return author_result, translator_result


if __name__ == "__main__":
    # 测试 guess_authors
    print("=" * 60)
    print("=== guess_authors ===")
    author_tests = [
        # (输入, 期望作者列表, 期望译者列表, 说明)
        (["鲁迅"], ["鲁迅"], [], "单作者，无标记"),
        (["[明] 施耐庵 著"], ["施耐庵"], [], "朝代前缀 + 著"),
        (["【美】海明威"], ["海明威"], [], "地区前缀"),
        (["（清）曹雪芹 编著"], ["曹雪芹"], [], "朝代前缀 + 编著"),
        (["阿加莎·克里斯蒂 编"], ["阿加莎·克里斯蒂"], [], "编 标识"),
        (["佚名"], [], [], "佚名 过滤"),
        (["Unknown"], [], [], "Unknown 过滤"),
        ([""], [], [], "空字符串过滤"),
        (["译者A 译"], [], ["译者A"], "译者标记"),
        (["鲁迅", "周树人"], ["鲁迅", "周树人"], [], "多作者各自独立"),
        (["[清]蒲松龄 著", "老舍"], ["蒲松龄", "老舍"], [], "混合前缀和无前缀"),
        (["作者A / 作者B"], ["作者A", "作者B"], [], "斜杠分割多人"),
        (["张三、李四、王五"], ["张三", "李四", "王五"], [], "顿号分割多人"),
        (["John, Jane, Bob"], ["John", "Jane", "Bob"], [], "英文逗号分割多人"),
        (["鲁迅, 茅盾, 巴金"], ["鲁迅", "茅盾", "巴金"], [], "中文作者逗号分割多人"),
        (["作者A, 作者B 著"], ["作者A", "作者B"], [], "逗号分割多人+尾部著"),
        (["作者A 著", "译者B 译"], ["作者A"], ["译者B"], "作者+译者混合"),
        (["[法]加缪 著", "【美】史密斯 译"], ["加缪"], ["史密斯"], "带前缀的作者和译者"),
        (["鲁迅/茅盾 著"], ["鲁迅", "茅盾"], [], "斜杠+著 组合"),
        (["译者A、译者B 译"], [], ["译者A", "译者B"], "顿号+译 组合"),
        (["译者A/译者B 译"], [], ["译者A", "译者B"], "斜杠+译 组合"),
        (["[明]吴承恩", "[明]罗贯中"], ["吴承恩", "罗贯中"], [], "多朝代前缀"),
        (["  张三  ", "  李四  "], ["张三", "李四"], [], "首尾空格清理"),

        # --- 扩展：括号/连字符形式的角色后缀 ---
        (["译者A (译)"], [], ["译者A"], "英文括号 译"),
        (["译者A（译）"], [], ["译者A"], "中文括号 译"),
        (["译者A - 译"], [], ["译者A"], "连字符 译"),
        (["译者A (translator)"], [], ["译者A"], "英文括号 translator"),
        (["译者A - translator"], [], ["译者A"], "连字符 translator"),
        (["作者A (编)"], ["作者A"], [], "英文括号 编"),
        (["作者A (editor)"], ["作者A"], [], "英文括号 editor"),
        (["作者A - 编著"], ["作者A"], [], "连字符 编著"),
        (["作者A (author)"], ["作者A"], [], "英文括号 author"),
        (["鲁迅/茅盾 (编)"], ["鲁迅", "茅盾"], [], "斜杠+括号 editor"),
        (["  鲁迅    著  "], ["鲁迅"], [], "首尾+中间多余空格归一化"),
        (["译者A\t译"], [], ["译者A"], "制表符归一化"),
        (["张三  /  李四  著"], ["张三", "李四"], [], "斜杠两侧空格归一化"),
        (["[美]  海明威    (译)"], [], ["海明威"], "前缀+多余空格+括号译者"),

        # --- 扩展：末尾英文译名括号 ---
        (["让-米歇尔·付东（Jean-Michel Frodon）"], ["让-米歇尔·付东"], [], "中文姓名+法语译名括号"),
        (["鲁迅 (Lu Xun)"], ["鲁迅"], [], "中文姓名+英文译名括号"),
        (["老舍（Lao She）"], ["老舍"], [], "中文姓名+英式译名括号"),
        (["张三/李四（John Smith）"], ["张三", "李四"], [], "斜杠+英文译名括号仅在后者"),
        (["鲁迅（Lu Xun） 著"], ["鲁迅"], [], "译名括号+著"),
        (["译者A（John Doe） 译"], [], ["译者A"], "译者+译名括号+译"),
    ]
    all_pass = True
    for idx, (inp, exp_auth, exp_trans, desc) in enumerate(author_tests, 1):
        got_auth, got_trans = guess_authors(inp)
        ok_auth = got_auth == exp_auth
        ok_trans = got_trans == exp_trans
        ok = ok_auth and ok_trans
        all_pass = all_pass and ok
        status = "PASS" if ok else "FAIL"
        print(f"\n[{status}] #{idx} {desc}")
        print(f"  输入:       {inp}")
        if not ok_auth:
            print(f"  期望作者:   {exp_auth}")
            print(f"  实际作者:   {got_auth}")
        else:
            print(f"  作者:       {got_auth}  ✓")
        if not ok_trans:
            print(f"  期望译者:   {exp_trans}")
            print(f"  实际译者:   {got_trans}")
        else:
            print(f"  译者:       {got_trans}  ✓")

    print(f"\n{'=' * 60}")
    print(f"共 {len(author_tests)} 个测试，{'全部通过 ✓' if all_pass else '存在失败 ✗'}")
