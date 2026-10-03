# -*- coding: utf-8 -*-

##########################################################
# Author: Yichen Huang (Eugene)
# GitHub: https://github.com/yichen0831/opencc-python
# January, 2016
##########################################################

##########################################################
# Revised by: Hopkins
# December, 2022
# Apache License Version 2.0, January 2004
# - Use a tree-like structure hold the result during conversion
# - Always choose the longest matching string from left to right in dictionary
#   by trying lookups in the dictionary rather than looping
# - Split the incoming string into smaller strings before processing to improve speed
# - Only match once per dictionary
# - If a dictionary is configured as part of a group, only match once per group
#   in order of the listed dictionaries
# - Cache the results of reading a dictionary in self.dict_cache
##########################################################

##########################################################
# 繁简转换工具移植说明（Apache License 2.0）
# - 从 Hopkins1/TradSimpChinese (calibre 插件) 中移植 opencc-python 引擎，
#   去掉 calibre 的资源加载抽象，改为直接读取本包 config/ 与 dictionary/ 目录。
# - 新增 extra_dicts 参数：将额外字典注入每个转换链 group 的“最前位置”，
#   用于“增强词表”（a5566123s 个人修正版）优先于 OpenCC 默认词表匹配。
# - 字典与配置数据来自 OpenCC (https://github.com/BYVoid/OpenCC)，Apache License 2.0。
# - 匹配算法对齐 OpenCC 官方 mmseg 语义：逐位置贪心最长匹配（组内词典
#   合并视图、键冲突按词典序先者胜），替代 Hopkins 版的“全局最长（先长度
#   后最左）”树匹配——后者会让位置靠后的长词条抢走位置靠前的词组命中
#   （如“陰沈詩任筆”中“沈詩任筆”抢掉“陰沈→阴沉”），且树递归深度随
#   段长线性增长（无标点长段会 RecursionError）。
##########################################################

import json
import os
import re

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(_PKG_DIR, "config")
DICT_DIR = os.path.join(_PKG_DIR, "dictionary")

# 支持的全部转换方向（与 config/ 下 json 文件名一致）
DIRECTIONS = ("hk2s", "hk2sp", "hk2t", "jp2t", "s2hk", "s2hkp", "s2t", "s2tw",
              "s2twp", "t2hk", "t2jp", "t2s", "t2tw", "tw2s", "tw2sp", "tw2t")
# 本工具实际内置的字典/配置（仅中文繁简相关）
BUILTIN_DIRECTIONS = ("t2s", "tw2s", "tw2sp", "s2t", "s2tw", "s2twp", "t2tw", "tw2t")

# 方向 → 展示文案（成功消息等场景使用，与 8 个内置方向一一对应）
DIRECTION_LABELS = {
    "t2s": "繁体→简体",
    "tw2s": "台湾繁体→简体",
    "tw2sp": "台湾繁体（含台湾用词）→简体",
    "s2t": "简体→繁体",
    "s2tw": "简体→台湾繁体",
    "s2twp": "简体→台湾繁体（含台湾用词）",
    "t2tw": "繁体→台湾繁体",
    "tw2t": "台湾繁体→繁体",
}


class OpenCC:
    """OpenCC 纯 Python 实现（无第三方依赖）。

    :param conversion: 转换方向，如 't2s' / 's2t' / 'tw2s' / 's2tw' / 'tw2sp' /
        's2twp' / 't2tw' / 'tw2t'
    :param extra_dicts: 可选，附加字典的绝对路径列表；每个字典按
        OpenCC 字典格式（``key\\tvalue``）组织，会被注入各转换链
        group 的最前位置（优先匹配，同名键覆盖默认词表）。
    """

    # 类级字典缓存：多实例共享，避免重复读取大字典
    _class_dict_cache = {}

    def __init__(self, conversion=None, extra_dicts=None):
        self.conversion_name = ""
        self.conversion = conversion
        self._dict_init_done = False
        self._dict_chain_data = list()
        # 统一为绝对路径，避免被当作 dictionary/ 目录下的相对文件名
        self.extra_dicts = [os.path.abspath(d) for d in (extra_dicts or [])]
        # List of sentence separators from OpenCC PhraseExtract.cpp. None of
        # these separators are allowed as part of a dictionary entry
        self.split_chars_re = re.compile(
            r'(\s+|-|,|\.|\?|!|\*|　|，|。|、|；|：|？|！|…|“|”|‘|’|『|』|「|」|﹁|﹂|—|－|（|）|《|》|〈|〉|～|．|／|＼|︒|︑|︔|︓|︿|﹀|︹|︺|︙|︐|［|﹇|］|﹈|︕|︖|︰|︳|︴|︽|︾|︵|︶|｛|︷|｝|︸|﹃|﹄|【|︻|】|︼|—|， |： |︲|～)')
        if self.conversion is not None:
            self._init_dict()

    def convert(self, string):
        """将字符串从源语种转换为目标语种。"""
        if self.conversion == "no_conversion":
            return string

        if not self._dict_init_done:
            self._init_dict()
            self._dict_init_done = True

        result = []
        # Separate string using the list of separators in a regular expression
        split_string_list = self.split_chars_re.split(string)
        for i in range(0, len(split_string_list)):
            if i % 2 == 0:
                # Work with the text string
                result.append(self._convert(split_string_list[i], self._dict_chain_data))
            else:
                # Work with the separator
                result.append(split_string_list[i])
        return "".join(result)

    def _convert(self, string, dictionary=()):
        """按字典链转换：链上级联（上一本输出作为下一本输入）。

        group 已在 :meth:`_add_dictionaries` 阶段合并为单个 ``(max_len,
        map_dict)`` 视图（官方 mmseg 语义：组内词典合并匹配、键冲突按
        词典序先者胜），因此链上元素均为单词典元组。
        """
        result = string
        for entry in dictionary:
            result = self._apply_dict(result, entry)
        return result

    @staticmethod
    def _apply_dict(string, test_dict):
        """官方 mmseg 逐位置贪心最长匹配：每个位置取该处能命中的最长
        词条，命中跳到词尾，否则单字符原样保留。线性扫描、无递归。"""
        max_len, map_dict = test_dict
        out = []
        i = 0
        n = len(string)
        while i < n:
            for length in range(min(max_len, n - i), 0, -1):
                value = map_dict.get(string[i:i + length])
                if value is not None:
                    if len(value.split(" ")) > 1:
                        # multiple mapping, use the first one for now
                        value = value.split(" ")[0]
                    out.append(value)
                    i += length
                    break
            else:
                out.append(string[i])
                i += 1
        return "".join(out)

    def _init_dict(self):
        if self.conversion is None:
            raise ValueError("conversion is not set")

        config_path = os.path.join(CONFIG_DIR, self.conversion + ".json")
        if not os.path.isfile(config_path):
            raise IOError("unable to open opencc config file: %s" % config_path)
        with open(config_path, encoding="utf-8") as f:
            setting_json = json.load(f)

        self.conversion_name = setting_json.get("name")

        dict_chain = []
        for chain in setting_json.get("conversion_chain"):
            self._add_dict_chain(dict_chain, chain.get("dict"))

        # 注入增强词表：在每个 group 的最前位置插入 extra 字典
        if self.extra_dicts:
            dict_chain = self._inject_extra_dicts(dict_chain)

        self._dict_chain_data = []
        self._add_dictionaries(dict_chain, self._dict_chain_data)
        self._dict_init_done = True

    def _inject_extra_dicts(self, chain_list):
        """把 extra_dicts 递归插入所有 group 开头；非 group 的字典项包成单元素 group。"""
        result = []
        for item in chain_list:
            if isinstance(item, list):
                result.append(self.extra_dicts + item)
            else:
                result.append(self.extra_dicts + [item])
        return result

    def _add_dictionaries(self, chain_list, chain_data):
        for item in chain_list:
            if isinstance(item, list):
                chain = []
                self._add_dictionaries(item, chain)
                # 官方 mmseg 语义：组内词典合并为一个匹配视图，键冲突按
                # 词典序先者胜（extra_dicts 注入在组前，故其键覆盖默认词表）
                merged = {}
                max_len = 1
                for member_len, member_dict in chain:
                    for key, value in member_dict.items():
                        if key not in merged:
                            merged[key] = value
                    if member_len > max_len:
                        max_len = member_len
                chain_data.append((max_len, merged))
            else:
                if isinstance(item, str) and os.path.isabs(item):
                    cache_key = item
                    file_path = item
                else:
                    cache_key = item
                    file_path = os.path.join(DICT_DIR, item)
                if cache_key not in self._class_dict_cache:
                    map_dict = {}
                    max_len = 1
                    with open(file_path, encoding="utf-8") as f:
                        for line in f:
                            line = line.rstrip("\n").rstrip("\r")
                            if (len(line) == 0) or (line[0] == "#"):
                                continue
                            if "\t" not in line:
                                continue
                            key, value = line.split("\t", 1)
                            key = key.strip()
                            value = value.strip()
                            if not key or not value:
                                continue
                            map_dict[key] = value
                            if len(key) > max_len:
                                max_len = len(key)
                    chain_data.append((max_len, map_dict))
                    self._class_dict_cache[cache_key] = (max_len, map_dict)
                else:
                    chain_data.append(self._class_dict_cache[cache_key])

    def _add_dict_chain(self, dict_chain, dict_dict):
        if dict_dict.get("type") == "group":
            chain = []
            for dict_item in dict_dict.get("dicts"):
                self._add_dict_chain(chain, dict_item)
            dict_chain.append(chain)
        elif dict_dict.get("type") == "txt":
            dict_chain.append(dict_dict.get("file"))

    def set_conversion(self, conversion):
        """运行时切换转换方向；'no_conversion' 表示原样输出。"""
        if self.conversion == conversion:
            return
        elif conversion == "no_conversion":
            self.conversion = conversion
        else:
            self._dict_init_done = False
            self.conversion = conversion
