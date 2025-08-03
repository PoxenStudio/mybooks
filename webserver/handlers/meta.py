#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import math
import sys
from functools import cmp_to_key
from gettext import gettext as _

from webserver import utils
from webserver.handlers.base import ListHandler, js


class LanguageNameUtil:
    """工具类，用于转换calibre language code to name and vice versa"""
    languages = {"英语": "eng",
                 "中文": "zho",
                 "法语": "fra",
                 "德语": "deu",
                 "西班牙语": "spa",
                 "俄语": "rus",
                 "日语": "jpn",
                 "意大利语": "ita",
                 "葡萄牙语": "por",
                 "韩语": "kor",
                 "荷兰语": "nld",
                 "阿拉伯语": "ara",
                 "印地语": "hin",
                 "土耳其语": "tur",
                 "越南语": "vie",
                 "泰语": "tha",
                 "希腊语": "ell",
                 "波兰语": "pol",
                 "捷克语": "ces",
                 "罗马尼亚语": "ron",
                 "瑞典语": "swe",
                 "芬兰语": "fin",
                 "丹麦语": "dan",
                 "匈牙利语": "hun",
                 "乌克兰语": "ukr",
                 "希伯来语": "heb",
                 "斯洛伐克语": "slk",
                 "塞尔维亚语": "srp",
                 "克罗地亚语": "hrv",
                 "保加利亚语": "bul",
                 "加泰罗尼亚语": "cat",
                 "印尼语": "ind",
                 "马来语": "msi",
                 "菲律宾语": "fil",
                 "挪威语": "nor",
                 "泰米尔语": "tam",
                 "孟加拉语": "ben",
                 "立陶宛语": "lit",
                 "爱沙尼亚语": "est",
                 "斯洛文尼亚语": "slv",
                 "加利西亚语": "glg",
                 "巴斯克语": "eus"}
    language_codes = {v: k for k, v in languages.items()}

    @staticmethod
    def get_language_name(code):
        """根据语言代码获取语言名称（中文）"""
        return LanguageNameUtil.language_codes.get(code, code)

    @staticmethod
    def get_language_code(name):
        """根据中文语言名称获取语言代码"""
        return LanguageNameUtil.languages.get(name, name)

    @staticmethod
    def get_language_list():
        """获取所有语言名称列表"""
        return list(LanguageNameUtil.languages.keys())


class AuthorBooksUpdate(ListHandler):
    def post(self, name):
        category = "authors"
        author_id = self.cache.get_item_id(category, name)
        ids = self.db.get_books_for_category(category, author_id)
        for book_id in list(ids)[:40]:
            self.do_book_update(book_id)
        self.redirect("/author/%s" % name, 302)


class PubBooksUpdate(ListHandler):
    def post(self, name):
        category = "publisher"
        publisher_id = self.cache.get_item_id(category, name)
        if publisher_id:
            ids = self.db.get_books_for_category(category, publisher_id)
        else:
            ids = self.cache.search_for_books("")
            books = self.db.get_data_as_dict(ids=ids)
            ids = [b["id"] for b in books if not b["publisher"]]
        for book_id in list(ids)[:40]:
            self.do_book_update(book_id)
        self.redirect("/publisher/%s" % name, 302)


class MetaList(ListHandler):
    @js
    def get(self, meta):
        SHOW_NUMBER = 300
        if self.get_argument("show", "") == "all":
            SHOW_NUMBER = sys.maxsize
        titles = {
            "tag": _(u"全部标签"),
            "author": _(u"全部作者"),
            "series": _(u"丛书列表"),
            "rating": _(u"全部评分"),
            "publisher": _(u"全部出版社"),
            "language": _(u"全部语言"),
        }
        title = titles.get(meta, _(u"未知")) % vars()
        # category = meta if meta in ["series", "publisher"] else meta + "s"
        items = self.get_category_with_count(meta)
        count = len(items)
        if items:
            if meta == "rating":
                items.sort(key=lambda x: x["name"], reverse=True)
            else:
                hotline = int(math.log10(count)) if count > SHOW_NUMBER else 0
                items = [v for v in items if v["count"] >= hotline]
                if meta == "language":
                    # convert the lang code to name
                    for item in items:
                        item["name"] = LanguageNameUtil.get_language_name(item["name"])
                items.sort(key=lambda x: x["count"], reverse=True)
        return {"meta": meta, "title": title, "items": items, "total": count}


class MetaBooks(ListHandler):
    def get(self, meta, name):
        titles = {
            "tag": _(u'含有"%(name)s"标签的书籍'),
            "author": _(u'"%(name)s"编著的书籍'),
            "series": _('"%(name)s"丛书包含的书籍'),
            "rating": _("评分为%(name)s星的书籍"),
            "publisher": _(u'"%(name)s"出版的书籍'),
            "language": _(u'"%(name)s"语言的书籍'),
        }
        title = titles.get(meta, _(u"未知")) % vars()  # noqa: F841
        category = meta + "s" if meta in ["tag", "author", "language"] else meta
        if meta in ["rating"]:
            name = int(name)
        elif meta == "language":
            name = LanguageNameUtil.get_language_code(name)
        books = self.get_item_books(category, name)
        books.sort(key=cmp_to_key(utils.compare_books_by_rating_or_id), reverse=True)
        return self.render_book_list(books, title=title)


def routes():
    return [
        (r"/api/(author|publisher|tag|rating|series|language)", MetaList),
        (r"/api/(author|publisher|tag|rating|series|language)/(.*)", MetaBooks),
        (r"/api/author/(.*)/update", AuthorBooksUpdate),
        (r"/api/publisher/(.*)/update", PubBooksUpdate),
    ]
