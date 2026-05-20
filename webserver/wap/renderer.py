# -*- coding: UTF-8 -*-
"""
WAP Page Renderer (PoxenStudio)

Generates Kindle-compatible server-side rendered HTML pages.

Design principles:
- No JavaScript dependency for core navigation
- CSS2.1 block-based layout (no flexbox/grid) for old Kindle browsers
- All navigation via HTML links with GET parameters
- HTML forms for search and login actions
"""

from html import escape
from urllib.parse import urlencode


# Inline CSS optimised for Kindle compatibility (CSS 2.1, block layout)
WAP_CSS = """
body {
    font-family: serif;
    font-size: 30px;
    margin: 10px;
    padding: 8px;
    background: #fff;
    color: #000;
}
a { color: #00c; text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { font-size: 1.3em; margin: 0.4em 0; border-bottom: 1px solid #ccc; padding-bottom: 4px; }
h2 { font-size: 1.1em; margin: 0.4em 0; }
hr { border: none; border-top: 1px solid #ddd; margin: 8px 0; }

.wap-header { border-bottom: 2px solid #888; margin-bottom: 10px; padding-bottom: 6px; overflow: hidden; }
.wap-header strong { font-size: 1.1em; }
.wap-header a { margin-right: 10px; }
.wap-footer { border-top: 1px solid #ddd; margin-top: 12px; padding-top: 6px;
               font-size: 0.82em; color: #888; text-align: center; }

.search-form { margin: 8px 0; }
.search-form select { border: 1px solid #ccc; padding: 3px; font-size: 1em; }
.search-form input[type=text] { border: 1px solid #ccc; padding: 3px;
                                 font-size: 1em; width: 200px; }
.search-form input[type=submit] { padding: 3px 10px; }

.book-list { margin: 0; padding: 0; list-style: none; overflow: hidden; }
.book-item { float: left; -webkit-box-sizing: border-box; box-sizing: border-box;
             width: 49%; margin: 0 1% 8px 0; border: 1px solid #ddd; padding: 6px; overflow: hidden; }
.book-item img.cover { float: left; width: 72px; height: 128px; margin-right: 8px;
                        border: 1px solid #ccc; }
.book-info { overflow: hidden; }
.book-title a { font-weight: bold; font-size: 1em; }
.book-author { color: #555; font-size: 0.9em; margin-top: 2px; }
.book-formats { font-size: 0.82em; color: #888; margin-top: 2px; }
.clear { clear: both; }

.pagination { margin: 10px 0; text-align: center; }
.pagination a { border: 1px solid #aaa; padding: 2px 8px; margin: 0 3px; }
.pagination .cur { padding: 2px 8px; margin: 0 3px; font-weight: bold; }

.meta-list { margin: 8px 0; line-height: 1.9em; }
.meta-tag { border: 1px solid #bbb; padding: 1px 6px; margin: 2px;
            display: inline-block; font-size: 0.88em; }
.meta-tag.active { background: #333; color: #fff; border-color: #333; }

.login-form { max-width: 320px; margin: 20px auto; }
.login-form h2 { margin-bottom: 12px; }
.form-row { margin: 8px 0; }
.form-row label { display: block; margin-bottom: 3px; font-weight: bold; }
.form-row input[type=text],
.form-row input[type=password] { border: 1px solid #ccc; padding: 4px 6px;
                                   width: 100%; font-size: 1em; }
.form-actions { margin-top: 12px; }
.form-actions input[type=submit] { padding: 5px 18px; font-size: 1em; }

.alert { border: 1px solid #d88; background: #fff2f2; padding: 6px 8px;
          margin: 8px 0; font-size: 0.9em; }
.msg  { border: 1px solid #8a8; background: #f2fff2; padding: 6px 8px; margin: 8px 0; }
.empty { color: #888; font-style: italic; margin: 16px 0; }
"""


class WapRenderer:
    """
    Generates Kindle-compatible HTML for the WAP module.
    All public methods return HTML strings.
    """

    @staticmethod
    def esc(text):
        """HTML-escape a value to a string."""
        if text is None:
            return ""
        return escape(str(text))

    # ------------------------------------------------------------------
    # Page skeleton
    # ------------------------------------------------------------------

    @classmethod
    def render_page(cls, title, body, user=None, site_title="Talebook"):
        """Wrap *body* HTML in a complete standalone HTML page."""
        t = cls.esc(title)
        st = cls.esc(site_title)
        user_links = cls._user_nav(user)
        return (
            '<!DOCTYPE html>\n'
            '<html lang="zh">\n'
            '<head>\n'
            '<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width">\n'
            f'<title>{t} - {st}</title>\n'
            f'<style>\n{WAP_CSS}</style>\n'
            '</head>\n'
            '<body>\n'
            f'<div class="wap-header">'
            f'<strong><a href="/wap">{st}</a></strong>'
            f' &nbsp; <a href="/wap/categories">分类</a>'
            f' <a href="/wap/languages">语言</a>'
            f' <a href="/wap/authors">作者</a>'
            f'{user_links}'
            f'</div>\n'
            f'{body}\n'
            f'<div class="wap-footer">PoxenStudio/Talebook &mdash; Kindle版</div>\n'
            '</body>\n'
            '</html>\n'
        )

    @classmethod
    def _user_nav(cls, user):
        if user:
            return (
                ' &nbsp; <a href="/wap/reading">在读</a>'
                ' <a href="/wap/favorites">收藏</a>'
                ' <a href="/wap/wants">待读</a>'
                ' <a href="/wap/logout">退出</a>'
            )
        return ' &nbsp; <a href="/wap/login">登录</a>'

    # ------------------------------------------------------------------
    # Search form
    # ------------------------------------------------------------------

    @classmethod
    def render_search_form(cls, query="", category="all"):
        """Render the search form with category selector."""
        cats = [
            ("all", "综合"),
            ("title", "书名"),
            ("author", "作者"),
            ("isbn", "ISBN"),
            ("comments", "简介"),
        ]
        opts = "".join(
            f'<option value="{v}"{" selected" if v == category else ""}>{cls.esc(l)}</option>'
            for v, l in cats
        )
        q = cls.esc(query)
        return (
            f'<form class="search-form" action="/wap/search" method="get">'
            f'<select name="cat">{opts}</select> '
            f'<input type="text" name="q" value="{q}" placeholder="搜索书籍...">'
            f' <input type="submit" value="搜索">'
            f'</form>\n'
        )

    # ------------------------------------------------------------------
    # Book list
    # ------------------------------------------------------------------

    @classmethod
    def render_book_list(cls, books, cdn_url=""):
        """Render a list of books."""
        if not books:
            return '<p class="empty">没有找到书籍。</p>\n'
        items = "".join(cls._book_card(b, cdn_url) for b in books)
        return f'<ul class="book-list">\n{items}</ul>\n'

    @classmethod
    def _book_card(cls, book, cdn_url=""):
        book_id = book.get("id", 0)
        raw_title = book.get("title") or "未知书名"
        if len(raw_title) > 20:
            raw_title = raw_title[:20] + "…"
        title = cls.esc(raw_title)
        authors = book.get("authors") or []
        author = cls.esc(", ".join(authors) if authors else "佚名")

        fmt_links = " / ".join(
            f'<a href="/api/book/{book_id}.{fmt.upper()}">{fmt.upper()}</a>'
            for fmt in ("epub", "azw3", "mobi", "pdf", "txt")
            if book.get(f"fmt_{fmt}")
        ) or "无文件"

        ts = book.get("ts", 0)
        cover = f"{cdn_url}/get/thumb_240_320/{book_id}.jpg?t={ts}&size=240x320"

        return (
            f'<li class="book-item">\n'
            f'<img class="cover" src="{cover}" alt="" width="72" height="128">\n'
            f'<div class="book-info">\n'
            f'<div class="book-title">{title}</div>\n'
            f'<div class="book-author">{author}</div>\n'
            f'<div class="book-formats">{fmt_links}</div>\n'
            f'</div>\n'
            f'<div class="clear"></div>\n'
            f'</li>\n'
        )

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    @classmethod
    def render_pagination(cls, page, total_pages, base_url, extra_params=None):
        """Render previous/current/next page navigation."""
        if total_pages <= 1:
            return ""

        qs = ""
        if extra_params:
            qs = "&" + urlencode(extra_params)

        parts = []
        if page > 1:
            parts.append(f'<a href="{base_url}?page={page - 1}{qs}">&laquo; 上一页</a>')
        parts.append(f'<span class="cur">{page}&nbsp;/&nbsp;{total_pages}</span>')
        if page < total_pages:
            parts.append(f'<a href="{base_url}?page={page + 1}{qs}">下一页 &raquo;</a>')

        return f'<div class="pagination">{" &nbsp; ".join(parts)}</div>\n'

    # ------------------------------------------------------------------
    # Meta tag cloud (categories / authors / languages)
    # ------------------------------------------------------------------

    @classmethod
    def render_meta_tags(cls, items, selected, base_url, param_name):
        """
        Render a clickable tag cloud for browsing by category/author/language.

        Args:
            items:      list of dicts with ``name`` and ``count`` keys.
            selected:   the currently-selected name (empty string if none).
            base_url:   URL prefix (e.g. '/wap/categories').
            param_name: query parameter name (e.g. 'cat').
        """
        if not items:
            return '<p class="empty">暂无数据。</p>\n'

        tags = []
        for item in items:
            name = item.get("name") or ""
            count = item.get("count", 0)
            active = " active" if name == selected else ""
            params = urlencode({param_name: name})
            tags.append(
                f'<a class="meta-tag{active}" href="{base_url}?{params}">'
                f'{cls.esc(name)}&nbsp;({count})</a>'
            )

        return f'<div class="meta-list">\n{"".join(tags)}\n</div>\n'

    # ------------------------------------------------------------------
    # Login form
    # ------------------------------------------------------------------

    @classmethod
    def render_login_form(cls, error="", next_url="/wap"):
        """Render the HTML login form."""
        error_html = (
            f'<div class="alert">{cls.esc(error)}</div>\n' if error else ""
        )
        next_val = cls.esc(next_url)
        return (
            f'<div class="login-form">\n'
            f'<h2>登录</h2>\n'
            f'{error_html}'
            f'<form method="post" action="/wap/login">\n'
            f'<input type="hidden" name="next" value="{next_val}">\n'
            f'<div class="form-row">\n'
            f'<label for="wap-user">用户名</label>\n'
            f'<input id="wap-user" type="text" name="username" autocomplete="username">\n'
            f'</div>\n'
            f'<div class="form-row">\n'
            f'<label for="wap-pass">密码</label>\n'
            f'<input id="wap-pass" type="password" name="password" autocomplete="current-password">\n'
            f'</div>\n'
            f'<div class="form-actions">\n'
            f'<input type="submit" value="登录">\n'
            f'</div>\n'
            f'</form>\n'
            f'<p><a href="/wap">&laquo; 返回首页</a></p>\n'
            f'</div>\n'
        )
