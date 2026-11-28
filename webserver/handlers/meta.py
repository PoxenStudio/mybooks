#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import logging
import math
import random
import re
import sys
from webserver.i18n import _

from webserver.handlers.base import ListHandler, js
from webserver.models import StickyItem
from webserver.base.homepage import MAX_VALUE_LEN
from webserver import loader, constants, utils

CONF = loader.get_settings()

KEYWORD_SPLIT_RE = re.compile(r'"([^"]+)"|([^\s,，、;；]+)', re.UNICODE)
MAX_KEYWORDS = 8


# Calibre 的 _matchkind 会把查询词首字符 = ~ ^ \ 当成精确/正则/忽略重音等特殊语义
# （~ 甚至会把用户输入当正则执行）。关键词必须按字面"包含"匹配，补一个反斜杠让
# Calibre 退回普通包含匹配；反斜杠本身也会由 _quote_search_value 正常转义。
LITERAL_QUERY_PREFIXES = ("\\", "=", "~", "^")


def _quote_search_value(value):
    """Calibre 搜索词转义，规则与 SearchBook._quote 保持一致。"""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _has_searchable_char(word):
    """至少含一个字母/数字（含 CJK）：纯标点词在 Calibre 标题匹配里会被忽略成空串。"""
    return any(ch.isalnum() for ch in word)


def split_keywords(value):
    """按空白/中英文逗号/顿号/分号切分关键词，英文双引号内保留空格。

    空词、纯标点词直接丢弃：Calibre 的标题"包含"匹配会忽略标点，这类词会退化成
    空查询命中整库（实测 title:"-" 返回全部书籍），与"书名包含关键词"的语义相悖。
    """
    words = []
    for match in KEYWORD_SPLIT_RE.finditer(value or ""):
        word = (match.group(1) or match.group(2) or "").strip()
        if word and word not in words and _has_searchable_char(word):
            words.append(word)
    return words[:MAX_KEYWORDS]


def _title_clause(word):
    """单个关键词 -> "title 包含" 子句；简繁变体在关键词内部取 OR。"""
    variants = [word]
    for profile in ("s2t", "t2s"):
        converted = utils.get_opencc(profile).convert(word)
        if converted not in variants:
            variants.append(converted)
    terms = []
    for variant in variants:
        if variant[:1] in LITERAL_QUERY_PREFIXES:
            variant = "\\" + variant
        terms.append("title:" + _quote_search_value(variant))
    return "(" + " OR ".join(terms) + ")"


def build_keyword_query(value, match="any"):
    """构造只匹配书名的 Calibre 搜索表达式，简繁变体在关键词内部取 OR。"""
    words = split_keywords(value)
    if not words:
        return ""
    groups = [_title_clause(word) for word in words]
    return (" AND " if match == "all" else " OR ").join(groups)


def sort_book_ids(cache, ids, meta, sort=None):
    ids = list(ids)
    if not sort:
        if meta == "keyword":
            sort = "new"
        else:
            sort = "series" if meta == "series" else "rating"
    if sort == "random":
        random.shuffle(ids)
        return ids
    if sort == "new":
        return sorted(ids, reverse=True)
    if sort == "title":
        title_sort = cache.all_field_for("sort", ids, "")
        return sorted(ids, key=lambda i: title_sort.get(i) or "")
    if sort == "series":
        index = cache.all_field_for("series_index", ids, 0)
        title_sort = cache.all_field_for("sort", ids, "")
        return sorted(ids, key=lambda i: (index.get(i) or 0, title_sort.get(i) or ""))
    rating = cache.all_field_for("rating", ids, 0)
    return sorted(ids, key=lambda i: (rating.get(i) or 0, i), reverse=True)


class LanguageNameUtil:
    """工具类，用于转换calibre language code to name and vice versa"""
    languages = {"English": "eng",
                 "中文": "zho",
                 "繁體中文": "zha",
                 "French": "fra",
                 "German": "deu",
                 "Spanish": "spa",
                 "Russian": "rus",
                 "Japanese": "jpn",
                 "Italian": "ita",
                 "Portuguese": "por",
                 "Korean": "kor",
                 "Dutch": "nld",
                 "Arabic": "ara",
                 "Mongolian": "mon",
                 "满文": "mnc",
                 "Tibetan": "bod",
                 "Hindi": "hin",
                 "Turkish": "tur",
                 "Vietnamese": "vie",
                 "Thai": "tha",
                 "Greek": "ell",
                 "Polish": "pol",
                 "Czech": "ces",
                 "Romanian": "ron",
                 "Swedish": "swe",
                 "Finnish": "fin",
                 "Danish": "dan",
                 "Hungarian": "hun",
                 "Ukrainian": "ukr",
                 "Hebrew": "heb",
                 "Slovak": "slk",
                 "Serbian": "srp",
                 "Croatian": "hrv",
                 "Bulgarian": "bul",
                 "Catalan": "cat",
                 "Indonesian": "ind",
                 "Malay": "msi",
                 "Filipino": "fil",
                 "Norwegian": "nor",
                 "Tamil": "tam",
                 "Bengali": "ben",
                 "Lithuanian": "lit",
                 "Estonian": "est",
                 "Slovenian": "slv",
                 "Galician": "glg",
                 "Basque": "eus"
                 }
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
        author_id = self.calibre_db_cache.get_item_id(category, name)
        ids = self.calibre_db.get_books_for_category(category, author_id)
        for book_id in list(ids)[:40]:
            self.do_book_update(book_id)
        self.redirect("/author/%s" % name, 302)


class PubBooksUpdate(ListHandler):
    def post(self, name):
        category = "publisher"
        publisher_id = self.calibre_db_cache.get_item_id(category, name)
        if publisher_id:
            ids = self.calibre_db.get_books_for_category(category, publisher_id)
        else:
            ids = self.calibre_db_cache.search_for_books("")
            books = self.calibre_db.get_data_as_dict(ids=ids)
            ids = [b["id"] for b in books if not b["publisher"]]
        for book_id in list(ids)[:40]:
            self.do_book_update(book_id)
        self.redirect("/publisher/%s" % name, 302)


class MetaList(ListHandler):
    @staticmethod
    def _get_sticky_values(session, reader_id, item_type):
        return [
            item.value
            for item in session.query(StickyItem).filter(
                StickyItem.reader_id == reader_id,
                StickyItem.item_type == item_type
            ).all()
        ]

    def _filter_tags(self, tag_list):
        if not self.current_user:
            return []
        read_limit = getattr(self.current_user, 'read_limit', 0) or 0
        if read_limit == 0:
            return tag_list
        limit_tags = set(filter(None, (self.current_user.limit_tags or "").split(',')))
        if not limit_tags:
            return tag_list
        if read_limit == 1:
            return [t for t in tag_list if t["name"] in limit_tags]
        return [t for t in tag_list if t["name"] not in limit_tags]

    @js
    async def get(self, meta):
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
        items = await self.get_category_with_count_async(meta)
        # if meta == "author":
        #     # 将自定义字段#translators中的译者也作为作者处理，与真实作者按书籍去重合并统计
        #     author_books = self.get_authors_book_ids_map()
        #     for book_id, translators in self.get_translators_map().items():
        #         for translator in translators:
        #             author_books.setdefault(translator, set()).add(book_id)
        #     items = [{"id": None, "name": name, "count": len(book_ids)} for name, book_ids in author_books.items()]
        # else:
        #     items = self.get_category_with_count(meta)
        count = len(items)

        # 获取置顶项目
        pins = []
        if self.current_user and meta in ["tag", "author"]:
            # 0:作者, 1:Tag
            item_type = 0 if meta == "author" else 1
            sticky_values = await self.run_sqlite_async(
                self._get_sticky_values, self.user_id(), item_type
            )

            # 为每个置顶项查找对应的count
            items_dict = {item["name"]: item for item in items}
            for value in sticky_values:
                if value in items_dict:
                    # 从items中找到并移除
                    item = items_dict[value]
                    pins.append({"name": item["name"], "count": item["count"]})
                    items.remove(item)
                else:
                    # 如果items中没有，count为0
                    pins.append({"name": value, "count": 0})

        if CONF.get(constants.ALLOW_READ_RANGE_SETTING, False) and meta == "tag":
            # 如果启用了阅读范围设置，过滤掉用户不可见的标签, 包括items & pins
            items = self._filter_tags(items)
            pins = self._filter_tags(pins)

        if items:
            if meta == "rating":
                # Calibre 内部按 0-10 分制存储评分（每 0.5 星 1 个单位），前台按 5 星整数展示，
                # 因此需要把原始分值合并到对应的星级桶里，例如 1/2 分都归入 1 星。
                buckets = {}
                for item in items:
                    raw = item["name"]
                    if raw is None:
                        continue
                    star = (int(raw) + 1) // 2
                    if star <= 0:
                        continue
                    bucket = buckets.setdefault(star, {"id": None, "name": star, "count": 0})
                    bucket["count"] += item["count"]
                items = list(buckets.values())
                items.sort(key=lambda x: x["name"], reverse=True)
                count = len(items)
            else:
                hotline = int(math.log10(count)) if count > SHOW_NUMBER else 0
                items = [v for v in items if v["count"] >= hotline]
                if meta == "language":
                    # convert the lang code to name
                    for item in items:
                        item["name"] = LanguageNameUtil.get_language_name(item["name"])
                items.sort(key=lambda x: x["count"], reverse=True)
        return {"err": "ok", "meta": meta, "title": title, "items": items, "total": count, "pins": pins}


class MetaBooks(ListHandler):
    def _book_ids(self, meta, name):
        category = meta + "s" if meta in ["tag", "author", "language"] else meta
        extra_ids = None
        if meta == "rating":
            # 公开路由，name 来自 URL/自定义卡片配置：非 1-5 的整数直接视为无匹配，
            # 不能让 int() 的 ValueError 冒泡到 @js（会把 traceback 回显给游客）。
            # 不能用 isdigit() 预判：'²'.isdigit() 为 True，但 int('²') 会抛 ValueError。
            try:
                star = int(name)
            except (TypeError, ValueError):
                star = 0
            if not 1 <= star <= 5:
                logging.info(f"Ignore invalid rating: {name}")
                return set()
            raw_values = (star * 2 - 1, star * 2)
            ids = set()
            rows = self.calibre_db_cache.backend.conn.get(
                "SELECT id FROM ratings WHERE rating IN (?, ?)", raw_values
            )
            for row in rows:
                ids |= set(self.calibre_db.get_books_for_category("rating", row[0]))
            logging.info(f"Get meta {meta} books of {name}")
            return ids
        if meta == "language":
            name = LanguageNameUtil.get_language_code(name)
        elif meta == "author":
            extra_ids = self.get_translator_book_ids(name)
        logging.info(f"Get meta {meta} books of {name}")
        item_id = self.calibre_db_cache.get_item_id(category, name)
        ids = set(self.calibre_db.get_books_for_category(category, item_id)) if item_id else set()
        if extra_ids:
            ids |= set(extra_ids)
        return ids

    def _sorted_ids(self, ids, meta, sort=None):
        return sort_book_ids(self.calibre_db_cache, ids, meta, sort)

    @js
    async def get(self, meta, name):
        titles = {
            "tag": _(u'含有"%(name)s"标签的书籍'),
            "author": _(u'"%(name)s"编著的书籍'),
            "series": _('"%(name)s"丛书包含的书籍'),
            "rating": _("评分为%(name)s星的书籍"),
            "publisher": _(u'"%(name)s"出版的书籍'),
            "language": _(u'"%(name)s"语言的书籍'),
        }
        title = titles.get(meta, _(u"未知")) % vars()  # noqa: F841
        sort = (self.get_argument("sort", "") or "").strip().lower()
        cover = self.get_argument("cover", "0") == "1"
        ids = await self.run_calibre_async(self._book_ids, meta, name)
        ids = await self.run_calibre_read_async(self._sorted_ids, ids, meta, sort)
        return await self.get_book_list([], ids=ids, title=title, include_comments=not cover)


class KeywordBooks(ListHandler):
    def _sorted_keyword_ids(self, ids, sort):
        return sort_book_ids(self.calibre_db_cache, ids, "keyword", sort)

    @js
    async def get(self, value):
        value = (value or "").strip()[:MAX_VALUE_LEN]
        match = (self.get_argument("match", "any") or "").strip().lower()
        if match not in ("any", "all"):
            match = "any"
        sort = (self.get_argument("sort", "") or "").strip().lower()
        if sort not in ("new", "title", "rating", "random"):
            sort = "new"
        cover = self.get_argument("cover", "0") == "1"

        title = _('书名含有"%(name)s"的书籍') % {"name": value}
        ids = []
        try:
            # 公开接口：查询构造失败（如 opencc 不可用）与查询执行失败一样
            # 只降级为空列表，不把 traceback 回显给游客
            query = build_keyword_query(value, match)
            if query:
                ids = await self.cached_search_async(query)
        except Exception:
            logging.exception("Keyword title search failed: %r", value)
        ids = await self.run_calibre_read_async(self._sorted_keyword_ids, ids, sort)
        return await self.get_book_list(
            [], ids=ids, title=title, include_comments=not cover
        )


def routes():
    return [
        (r"/api/(author|publisher|tag|rating|series|language)", MetaList),
        (r"/api/(author|publisher|tag|rating|series|language)/(.*)", MetaBooks),
        (r"/api/keyword/(.*)", KeywordBooks),
        (r"/api/author/(.*)/update", AuthorBooksUpdate),
        (r"/api/publisher/(.*)/update", PubBooksUpdate),
    ]
