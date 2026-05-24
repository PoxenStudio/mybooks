#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
WAP handlers – server-side rendered HTML pages for Kindle browsers.

Each page handler extends WapBaseHandler, uses WapDataProvider to fetch data,
and WapRenderer to build the HTML response.  No JavaScript is required for
core navigation: all links use GET parameters, login uses a POST form.

Routes registered by routes() must be added to main.py BEFORE the static-files
catch-all so they take precedence over the Vue SPA assets at /wap/*.
"""

import math
from urllib.parse import quote_plus, unquote_plus

from webserver.handlers.base import BaseHandler
from webserver.models import Reader
from webserver.wap.data_provider import WapDataProvider, PAGE_SIZE
from webserver.wap.renderer import WapRenderer
from webserver import loader

CONF = loader.get_settings()

# Error-code → human-readable message used by the login page
_LOGIN_ERRORS = {
    "invalid": "用户名或密码错误",
    "nouser": "用户不存在",
    "inactive": "账号未激活，请先激活后登录",
    "noperm": "账号暂无登录权限，请联系管理员",
}


class WapBaseHandler(BaseHandler):
    """
    Shared base for all WAP page handlers.
    Provides write_page(), require_login(), get_page_num() and a lazy provider.
    """

    def write_page(self, title, body):
        """Render a complete HTML page and write it to the response."""
        site_title = CONF.get("site_title", "MyBooks")
        html = WapRenderer.render_page(
            title, body, user=self.current_user, site_title=site_title
        )
        self.set_header("Content-Type", "text/html; charset=UTF-8")
        self.set_header("Cache-Control", "no-cache, no-store")
        self.write(html)

    def require_login(self):
        """
        Redirect to the login page if the current user is not authenticated.
        Returns True when a redirect was issued so the caller can return early.
        """
        if not self.current_user:
            next_url = quote_plus(self.request.uri)
            self.redirect(f"/wap/login?next={next_url}")
            return True
        return False

    def get_page_num(self):
        """Return the current page number (1-based) from the ``page`` argument."""
        try:
            return max(1, int(self.get_argument("page", 1)))
        except (TypeError, ValueError):
            return 1

    @property
    def provider(self):
        """Lazy-instantiated WapDataProvider for this request."""
        if not hasattr(self, "_provider"):
            self._provider = WapDataProvider(self)
        return self._provider


# ======================================================================
# Page handlers
# ======================================================================

class WapIndex(WapBaseHandler):
    """Homepage: search form + recent books."""

    def get(self):
        site_title = CONF.get("site_title", "MyBooks")
        body = WapRenderer.render_search_form()
        body += "<h2>最新书籍</h2>\n"
        books = self.provider.get_recent_books(count=20)
        body += WapRenderer.render_book_list(books, self.cdn_url)
        self.write_page(f"{site_title} Kindle 版", body)


class WapSearch(WapBaseHandler):
    """Search results page."""

    # Maps WAP category selector values to calibre field prefixes
    _FIELD_PREFIX = {
        "title": "title",
        "author": "authors",
        "isbn": "isbn",
        "comments": "comments",
    }

    def get(self):
        raw_query = self.get_argument("q", "").strip()
        category = self.get_argument("cat", "all").strip()
        page = self.get_page_num()

        if not raw_query:
            self.redirect("/wap")
            return

        # Build calibre query
        if category in self._FIELD_PREFIX:
            field = self._FIELD_PREFIX[category]
            query = f'{field}:"{raw_query}"'
        else:
            query = raw_query

        books, total = self.provider.search_books(query, page, PAGE_SIZE)
        total_pages = max(1, math.ceil(total / PAGE_SIZE))

        body = WapRenderer.render_search_form(query=raw_query, category=category)
        body += f"<h2>搜索：{WapRenderer.esc(raw_query)} &nbsp;（共 {total} 本）</h2>\n"
        body += WapRenderer.render_book_list(books, self.cdn_url)
        body += WapRenderer.render_pagination(
            page, total_pages, "/wap/search",
            extra_params={"q": raw_query, "cat": category},
        )
        self.write_page(f"搜索：{raw_query}", body)


class WapCategories(WapBaseHandler):
    """Browse books by custom category."""

    def get(self):
        selected = self.get_argument("cat", "").strip()
        page = self.get_page_num()

        categories = self.provider.get_categories()
        body = "<h2>按分类浏览</h2>\n"
        body += WapRenderer.render_meta_tags(categories, selected, "/wap/categories", "cat")

        if selected:
            books, total = self.provider.get_books_by_category(selected, page, PAGE_SIZE)
            total_pages = max(1, math.ceil(total / PAGE_SIZE))
            body += f"<hr><h2>{WapRenderer.esc(selected)} &nbsp;（共 {total} 本）</h2>\n"
            body += WapRenderer.render_book_list(books, self.cdn_url)
            body += WapRenderer.render_pagination(
                page, total_pages, "/wap/categories", extra_params={"cat": selected}
            )

        self.write_page("按分类浏览", body)


class WapLanguages(WapBaseHandler):
    """Browse books by language."""

    def get(self):
        selected = self.get_argument("lang", "").strip()
        page = self.get_page_num()

        languages = self.provider.get_languages()
        # render_meta_tags expects {name, count}; use display name as the link value
        lang_items = [{"name": item["name"], "count": item["count"]} for item in languages]

        body = "<h2>按语言浏览</h2>\n"
        body += WapRenderer.render_meta_tags(lang_items, selected, "/wap/languages", "lang")

        if selected:
            books, total = self.provider.get_books_by_language(selected, page, PAGE_SIZE)
            total_pages = max(1, math.ceil(total / PAGE_SIZE))
            body += f"<hr><h2>{WapRenderer.esc(selected)} &nbsp;（共 {total} 本）</h2>\n"
            body += WapRenderer.render_book_list(books, self.cdn_url)
            body += WapRenderer.render_pagination(
                page, total_pages, "/wap/languages", extra_params={"lang": selected}
            )

        self.write_page("按语言浏览", body)


class WapAuthors(WapBaseHandler):
    """Browse books by author."""

    def get(self):
        selected = self.get_argument("author", "").strip()
        page = self.get_page_num()

        authors = self.provider.get_authors(limit=100)
        body = "<h2>按作者浏览</h2>\n"
        body += WapRenderer.render_meta_tags(authors, selected, "/wap/authors", "author")

        if selected:
            books, total = self.provider.get_books_by_author(selected, page, PAGE_SIZE)
            total_pages = max(1, math.ceil(total / PAGE_SIZE))
            body += f"<hr><h2>{WapRenderer.esc(selected)} &nbsp;（共 {total} 本）</h2>\n"
            body += WapRenderer.render_book_list(books, self.cdn_url)
            body += WapRenderer.render_pagination(
                page, total_pages, "/wap/authors", extra_params={"author": selected}
            )

        self.write_page("按作者浏览", body)


class WapReading(WapBaseHandler):
    """User's currently-reading list (login required)."""

    def get(self):
        if self.require_login():
            return
        page = self.get_page_num()
        books, total = self.provider.get_reading_books(self.user_id(), page, PAGE_SIZE)
        total_pages = max(1, math.ceil(total / PAGE_SIZE))
        body = f"<h2>在读书籍 &nbsp;（共 {total} 本）</h2>\n"
        body += WapRenderer.render_book_list(books, self.cdn_url)
        body += WapRenderer.render_pagination(page, total_pages, "/wap/reading")
        self.write_page("在读书籍", body)


class WapFavorites(WapBaseHandler):
    """User's favourite books (login required)."""

    def get(self):
        if self.require_login():
            return
        page = self.get_page_num()
        books, total = self.provider.get_favorite_books(self.user_id(), page, PAGE_SIZE)
        total_pages = max(1, math.ceil(total / PAGE_SIZE))
        body = f"<h2>我的收藏 &nbsp;（共 {total} 本）</h2>\n"
        body += WapRenderer.render_book_list(books, self.cdn_url)
        body += WapRenderer.render_pagination(page, total_pages, "/wap/favorites")
        self.write_page("我的收藏", body)


class WapWants(WapBaseHandler):
    """User's want-to-read list (login required)."""

    def get(self):
        if self.require_login():
            return
        page = self.get_page_num()
        books, total = self.provider.get_wants_books(self.user_id(), page, PAGE_SIZE)
        total_pages = max(1, math.ceil(total / PAGE_SIZE))
        body = f"<h2>待读清单 &nbsp;（共 {total} 本）</h2>\n"
        body += WapRenderer.render_book_list(books, self.cdn_url)
        body += WapRenderer.render_pagination(page, total_pages, "/wap/wants")
        self.write_page("待读清单", body)


class WapLogin(WapBaseHandler):
    """WAP login page – GET renders the form, POST processes credentials."""

    def get(self):
        if self.current_user:
            self.redirect(self._safe_next())
            return
        err_code = self.get_argument("err", "").strip()
        error_msg = _LOGIN_ERRORS.get(err_code, "")
        body = WapRenderer.render_login_form(error=error_msg, next_url=self._safe_next())
        self.write_page("登录", body)

    def post(self):
        username = self.get_argument("username", "").strip().lower()
        password = self.get_argument("password", "").strip()
        next_url = self._safe_next()
        next_enc = quote_plus(next_url)

        if not username or not password:
            self.redirect(f"/wap/login?err=invalid&next={next_enc}")
            return

        user = (
            self.sqlite_session.query(Reader)
            .filter(Reader.username == username)
            .first()
        )
        if not user:
            self.redirect(f"/wap/login?err=nouser&next={next_enc}")
            return
        if user.get_secure_password(password) != user.password:
            self.redirect(f"/wap/login?err=invalid&next={next_enc}")
            return
        if not user.is_active():
            self.redirect(f"/wap/login?err=inactive&next={next_enc}")
            return
        if not user.can_login():
            self.redirect(f"/wap/login?err=noperm&next={next_enc}")
            return

        self.login_user(user)
        self.redirect(next_url)

    def _safe_next(self):
        """
        Return a validated redirect destination from the ``next`` query param.
        Only paths that start with ``/`` (and not ``//``) are accepted to
        prevent open-redirect attacks.  Falls back to ``/wap``.
        """
        raw = self.get_argument("next", "/wap").strip()
        decoded = unquote_plus(raw)
        if decoded.startswith("/") and not decoded.startswith("//"):
            return decoded
        return "/wap"


class WapLogout(WapBaseHandler):
    """Clears session cookies and redirects to the WAP homepage."""

    def get(self):
        self.set_secure_cookie("user_id", "")
        self.set_secure_cookie("admin_id", "")
        self.redirect("/wap")


# ======================================================================
# Route table
# ======================================================================

def routes():
    return [
        (r"/wap/?", WapIndex),
        (r"/wap/search", WapSearch),
        (r"/wap/categories", WapCategories),
        (r"/wap/languages", WapLanguages),
        (r"/wap/authors", WapAuthors),
        (r"/wap/reading", WapReading),
        (r"/wap/favorites", WapFavorites),
        (r"/wap/wants", WapWants),
        (r"/wap/login", WapLogin),
        (r"/wap/logout", WapLogout),
    ]
