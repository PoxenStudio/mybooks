#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import json
import logging
import re
import time

# 整本扫描是纯 Python 循环，几十万行的解析若一直占着 GIL，会把同进程里的
# Tornado IOLoop 饿住（实测接口延迟从 5ms 恶化到数秒）。正常路径由
# ExtractService 放到独立子进程里跑，这里定期让出只是给进程内调用兜底。
GIL_YIELD_EVERY_LINES = 200


def get_file_encoding(file):
    import chardet
    with open(file, 'rb') as f:
        c = chardet.detect(f.read(100))
        e = c['encoding']
        return 'GB18030' if e == 'GB2312' else e


def get_content_encoding(byte):
    import chardet
    return chardet.detect(byte)['encoding'] or 'GB2312'


# 与 calibre.utils.wordcount 一致的“字数”口径：ord > 0x3000 的字符逐字计，
# 其余按空白分词。用于 EPUB/TXT 共用，避免两种格式给出不同口径的数字。
ASIAN_CHARS_RE = re.compile(r'[^\u0000-\u3000]')


def count_words(text):
    asian = len(ASIAN_CHARS_RE.findall(text))
    non_asian = ASIAN_CHARS_RE.sub(' ', text)
    return asian + len(non_asian.split())


class TxtParser:
    # 目录解析规则
    TXT_CONTENT_RULES = [
        {
            "name": "目录(去空白)",
            "example": "第一章 假装第一章前面有空白但我不要",
            "rule": r"(?=[　\s])(?:序章|楔子|正文(?!完|结)|终章|后记|尾声|番外|第\s{0,4}[\d〇零一二两三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟]+?\s{0,4}(?:章|节(?!课)|卷|集(?![合和]))).{0,30}$"}, # noqa
        {
            "name": "目录",
            "example": "第一章 标准的粤语就是这样",
            "rule": r"^[ 　\t]{0,4}(?:序章|序言|楔子|正文(?!完|结)|终章|后记|尾声|番外|第\s{0,4}[\d〇零一二两三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟]+?\s{0,4}(?:章|节(?!课)|卷|集(?![合和])|部(?![分赛游])|篇(?!张))).{0,30}$"}, # noqa
        {
            "name": "数字 分隔符 标题名称",
            "example": "1、这个就是标题",
            "rule": r"^[ 　\t]{0,4}\d{1,5}[:：,.， 、_—\-].{1,30}$"},
        {
            "name": "大写数字 分隔符 标题名称",
            "example": "一、只有前面的数字有差别\n二十四章 我瞎编的标题",
            "rule": r"^[ 　\t]{0,4}(?:序章|楔子|正文(?!完|结)|终章|后记|尾声|番外|[零一二两三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟]{1,8}章?)[ 、_—\-].{1,30}$"},
        {
            "name": "正文 标题/序号",
            "example": "正文 我乃常山赵子龙",
            "rule": r"^[ 　\t]{0,4}正文[ 　]{1,4}.{0,20}$"},
        {
            "name": "Chapter/Section/Part/Episode 序号 标题",
            "example": "Chapter 1 MyGrandmaIsNB",
            "rule": r"^[ 　\t]{0,4}(?:[Cc]hapter|[Ss]ection|[Pp]art|ＰＡＲＴ|[Nn][oO][.、]|[Ee]pisode|(?:内容|文章)?简介|文案|前言|序章|楔子|正文(?!完|结)|终章|后记|尾声|番外)\s{0,4}\d{1,4}.{0,30}$"}, # noqa
        {
            "name": "特殊符号 序号 标题",
            "example": "【第一章 后面的符号可以没有",
            "rule": r"(?=[\s　])[【〔〖「『〈［\[](?:第|[Cc]hapter)[\d零一二两三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟]{1,10}[章节].{0,20}$"},
        {
            "name": "特殊符号 标题(成对)",
            "example": "『加个直角引号更专业』\n(11)我奶常山赵子聋",
            "rule": r"^(?=[\s　]{0,4})(?:[\[〈「『〖〔《（【\(].{1,30}[\)】）》〕〗』」〉\]]?|(?:内容|文章)?简介|文案|前言|序章|楔子|正文(?!完|结)|终章|后记|尾声|番外)[ 　]{0,4}$"}, # noqa
        {
            "name": "特殊符号 标题(单个)",
            "example": "☆、晋江作者最喜欢的格式",
            "rule": r"^(?=[\s　]{0,4})(?:[☆★✦✧].{1,30}|(?:内容|文章)?简介|文案|前言|序章|楔子|正文(?!完|结)|终章|后记|尾声|番外)[ 　]{0,4}$"},
        {
            "name": "章/卷 序号 标题",
            "example": "卷五 开源盛世",
            "rule": r"^[ \t　]{0,4}(?:(?:内容|文章)?简介|文案|前言|序章|楔子|正文(?!完|结)|终章|后记|尾声|番外|[卷章][\d零一二两三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟]{1,8})[ 　]{0,4}.{0,30}$"}, # noqa
        {
            "name": "书名 括号 序号",
            "example": "标题后面数字有括号(12)",
            "rule": r"^.{1,20}[(（][\d〇零一二两三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟]{1,8}[)）][ 　\\t]{0,4}$"},
        {
            "name": "书名 序号",
            "example": "标题后面数字没有括号124",
            "rule": r"^.{1,20}[\d〇零一二两三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟]{1,8}[ 　\\t]{0,4}$"},
        {
            "name": "字数分割 分节阅读",
            "example": "分节|分页|分段阅读\n第一页",
            "rule": r"(?=[ 　\t]{0,4})(?:.{0,15}分[页节章段]阅读[-_ ]|第\s{0,4}[\d零一二两三四五六七八九十百千万]{1,6}\s{0,4}[页节]).{0,30}$"
        }
    ]

    def parse(self, filepath):
        encoding = get_file_encoding(filepath)
        logging.info("encoding is [%s] from file [%s]", encoding, filepath)
        with open(filepath, 'r', encoding=encoding, errors='ignore', newline='\n') as fileobj:
            toc = self.parse_txt_book_toc(fileobj)
            return {"encoding": encoding, "toc": toc}

    def count_file(self, filepath):
        """只统计整本字数，不做目录正则扫描；供独立字数统计使用。"""
        encoding = get_file_encoding(filepath)
        total = 0
        scanned = 0
        with open(filepath, 'r', encoding=encoding, errors='ignore', newline='\n') as fileobj:
            for line in fileobj:
                total += count_words(line)
                scanned += 1
                if scanned % GIL_YIELD_EVERY_LINES == 0:
                    time.sleep(0)
        return {"encoding": encoding, "word_count": total}

    def parse_txt_book_toc(self, fileobj):
        # table of content
        toc = []
        idx = 1
        pre_chapter = None
        pre_seek = -1

        line = fileobj.readline()
        scanned = 0
        while line:
            # 获取当前文件指针的位置（seek位置）
            seek_position = fileobj.tell()
            for rule in self.TXT_CONTENT_RULES:
                try:
                    matches = re.findall(rule['rule'], line)
                except Exception as e:
                    logging.error("re.findall fail: err=%s, rule=%s", e, rule['rule'])
                    continue

                if len(matches) == 0:
                    continue

                if pre_chapter is not None:
                    # 此时引用的对象还是上一个章节的，设置结尾位置
                    pre_chapter["end"] = pre_seek

                pre_chapter = {
                    "id": idx,
                    "title": matches[0].strip(),
                    "start": seek_position,
                    "end": -1
                }
                toc.append(pre_chapter)
                idx += 1
                break
            pre_seek = seek_position
            scanned += 1
            if scanned % GIL_YIELD_EVERY_LINES == 0:
                time.sleep(0)
            line = fileobj.readline()
        if len(toc) == 0:
            toc = [{
                "id": 1,
                "title": "全部",
                "start": 0,
                "end": -1
            }]
        return toc


if __name__ == '__main__':
    import sys

    if len(sys.argv) == 1:
        print("%s FILE.TXT" % sys.argv[0])
    elif len(sys.argv) >= 3 and sys.argv[1] == '--count':
        result = TxtParser().count_file(sys.argv[2])
        print(json.dumps(result, ensure_ascii=False))
    else:
        toc = TxtParser().parse(sys.argv[1])
        print(json.dumps(toc, ensure_ascii=False, indent=2))
