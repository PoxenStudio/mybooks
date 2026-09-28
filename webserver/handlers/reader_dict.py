#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

"""
Site-level dictionaries for the embedded MyReader (web build only).

The admin configures them on the settings page (`READER_DICT_*` keys):
whether the MyBooks dictionary and Baidu Baike are enabled by default, and a
list of MyDict servers (`poxenstudio/mydict`) with their address and token.

The reader only ever sees the public view (`/api/reader/dict-config`): ids,
names and default-enable flags. Lookups against a site MyDict go through this
module (`/api/reader/dict/<id>/query`), so the server address and its token
never leave MyBooks. Entry resources (images, CSS, fonts, audio) are relayed
the same way, because the browser doesn't know which server to ask and an
HTTPS page can't load `http://` resources from a LAN MyDict anyway.

The admin's enable flags are defaults for the reader's dictionary list, not
access control: a disabled site MyDict still answers lookups, only a deleted
one 404s.
"""

import json
import logging
import posixpath
import re
import urllib.parse

import tornado.escape
from tornado.httpclient import AsyncHTTPClient, HTTPClientError, HTTPRequest

from webserver import loader
from webserver.handlers.base import BaseHandler, is_admin, js

CONF = loader.get_settings()

MYDICTS_KEY = "READER_MYDICTS"
MYBOOKS_ENABLED_KEY = "READER_DICT_MYBOOKS_ENABLED"
BAIKE_ENABLED_KEY = "READER_DICT_BAIKE_ENABLED"

DICT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
# Prefix the MyDict server puts on every entry resource URL.
ALLOWED_RES_PREFIX = "/dict-res/"
QUERY_TIMEOUT = 15.0
RES_TIMEOUT = 20.0
# Word looked up by the admin's "test" button when none is given.
TEST_WORD = "test"


def sanitize_mydicts(value):
    """Keep only well-formed site MyDict entries (used when the admin saves).

    Entries without a valid id or an http(s) url are dropped; duplicate ids
    keep the first occurrence."""
    if not isinstance(value, list):
        return []
    out, seen = [], set()
    for item in value:
        if not isinstance(item, dict):
            continue
        dict_id = str(item.get("id", "")).strip()
        url = str(item.get("url", "")).strip()
        if not DICT_ID_RE.match(dict_id) or dict_id in seen:
            continue
        if not re.match(r"^https?://[^/\s]+", url, re.I):
            continue
        seen.add(dict_id)
        out.append(
            {
                "id": dict_id,
                "name": str(item.get("name", "")).strip() or dict_id,
                "url": url,
                "token": str(item.get("token", "") or "").strip(),
                "enabled": bool(item.get("enabled", True)),
            }
        )
    return out


def site_mydicts():
    return sanitize_mydicts(CONF.get(MYDICTS_KEY, []))


def find_mydict(dict_id):
    for entry in site_mydicts():
        if entry["id"] == dict_id:
            return entry
    return None


def build_query_url(base_url, word):
    """Python twin of myreader's `buildMyDictQueryUrl` — keep the params in step."""
    base = base_url.strip().rstrip("/")
    if not base.endswith("/api/v1/query"):
        base += "/api/v1/query"
    params = urllib.parse.urlencode({"word": word, "full_style": "true", "all_langs": "true"})
    return f"{base}?{params}"


def mask_token(token):
    if not token:
        return "(none)"
    return f"{token[:6]}…{token[-4:]} (len={len(token)})" if len(token) > 12 else "***"


def describe_upstream(response):
    """`Server` header + a body snippet — tells a real MyDict (uvicorn) apart
    from whatever else happens to answer on that address."""
    if response is None:
        return "(no response)", ""
    server = response.headers.get("Server", "?") if response.headers else "?"
    body = (response.body or b"")[:300].decode("utf-8", "replace").replace("\n", " ")
    return server, body


def build_res_url(base_url, res_path):
    """Resources live at `<origin>/dict-res/…` regardless of any sub-path in the
    configured base (same rule as myreader's relay). Returns None when the
    normalised path escapes the `/dict-res/` prefix."""
    parts = urllib.parse.urlsplit(base_url.strip())
    path = posixpath.normpath("/" + res_path.lstrip("/"))
    if not path.startswith(ALLOWED_RES_PREFIX):
        return None
    quoted = urllib.parse.quote(path, safe="/")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, quoted, "", ""))


class ReaderDictBase(BaseHandler):
    def _authorized(self) -> bool:
        # Dictionary lookups are part of reading, so they follow the same
        # guest-access convention as the reader itself (see tts.EdgeTTSProxy).
        if CONF.get("ALLOW_GUEST_READ", False):
            return True
        return bool(self.current_user)

    def _error(self, status, message):
        self.set_status(status)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json.dumps({"error": message}))


class ReaderDictConfig(ReaderDictBase):
    """Public view of the site dictionaries — never includes urls or tokens."""

    def get(self):
        if not self._authorized():
            return self._error(403, "Not authenticated")
        self.set_header("Cache-Control", "no-store")
        self.write(
            {
                "mybooks": bool(CONF.get(MYBOOKS_ENABLED_KEY, True)),
                "baike": bool(CONF.get(BAIKE_ENABLED_KEY, True)),
                "mydicts": [
                    {"id": d["id"], "name": d["name"], "enabled": d["enabled"]}
                    for d in site_mydicts()
                ],
            }
        )


class ReaderDictQuery(ReaderDictBase):
    """`GET /api/reader/dict/<id>/query?word=` — relays one lookup to a site MyDict."""

    async def get(self, dict_id):
        if not self._authorized():
            return self._error(403, "Not authenticated")
        entry = find_mydict(dict_id)
        if not entry:
            return self._error(404, "Dictionary not found")
        word = self.get_argument("word", "").strip()
        if not word:
            return self._error(400, "Missing word")

        headers = {"Accept": "application/json"}
        if entry["token"]:
            headers["Authorization"] = "Bearer " + entry["token"]
        target = build_query_url(entry["url"], word)
        logging.debug("Site MyDict %s: GET %s token=%s", dict_id, target, mask_token(entry["token"]))
        request = HTTPRequest(
            url=target,
            headers=headers,
            validate_cert=False,  # self-signed certs are the norm on a home server
            request_timeout=QUERY_TIMEOUT,
            connect_timeout=10.0,
        )
        try:
            response = await AsyncHTTPClient().fetch(request)
        except HTTPClientError as e:
            server, body = describe_upstream(e.response)
            logging.warning("Site MyDict %s query failed: HTTP %s from %s server=%s body=%s", dict_id, e.code, target, server, body)
            return self._error(e.code if 400 <= e.code < 500 else 502, f"HTTP {e.code}")
        except Exception as e:
            logging.error("Site MyDict %s unreachable: %s", dict_id, e)
            return self._error(502, str(e))

        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.set_header("Cache-Control", "no-store")
        self.write(response.body)


class ReaderDictResource(ReaderDictBase):
    """`GET /api/reader/dict/<id>/res/dict-res/…` — relays an entry resource.

    The URL mirrors the upstream path so relative `url(…)` references inside a
    dictionary's CSS keep resolving to their siblings."""

    async def get(self, dict_id, res_path):
        if not self._authorized():
            return self._error(403, "Not authenticated")
        entry = find_mydict(dict_id)
        if not entry:
            return self._error(404, "Dictionary not found")
        # Tornado already percent-decodes path arguments.
        target = build_res_url(entry["url"], res_path)
        if not target:
            return self._error(400, "Only dictionary resources are relayed")

        request = HTTPRequest(
            url=target,
            headers={"Accept": "*/*"},
            validate_cert=False,
            request_timeout=RES_TIMEOUT,
            connect_timeout=10.0,
        )
        try:
            response = await AsyncHTTPClient().fetch(request)
        except HTTPClientError as e:
            # A dictionary that never shipped the file its CSS asks for is a
            # 404, not a relay failure.
            return self._error(e.code if 400 <= e.code < 500 else 502, f"HTTP {e.code}")
        except Exception as e:
            logging.error("Site MyDict %s resource %s failed: %s", dict_id, target, e)
            return self._error(502, str(e))

        self.set_header(
            "Content-Type", response.headers.get("Content-Type", "application/octet-stream")
        )
        self.set_header(
            "Cache-Control", response.headers.get("Cache-Control", "public, max-age=86400")
        )
        self.set_header("X-Content-Type-Options", "nosniff")
        self.write(response.body)


class ReaderDictTest(BaseHandler):
    """`POST /api/admin/reader/dict/test` — tries one lookup against a MyDict
    address/token straight from the settings form, so the admin can check it
    before saving. Admin-only: it fetches an arbitrary URL on their behalf."""

    @js
    @is_admin
    async def post(self):
        data = tornado.escape.json_decode(self.request.body or b"{}")
        url = str(data.get("url", "") or "").strip()
        token = str(data.get("token", "") or "").strip()
        word = str(data.get("word", "") or "").strip() or TEST_WORD
        if not re.match(r"^https?://[^/\s]+", url, re.I):
            return {"err": "params.invalid", "msg": "Invalid URL"}

        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        target = build_query_url(url, word)
        logging.info("MyDict test: GET %s token=%s", target, mask_token(token))
        request = HTTPRequest(
            url=target,
            headers=headers,
            validate_cert=False,
            request_timeout=QUERY_TIMEOUT,
            connect_timeout=10.0,
        )
        try:
            response = await AsyncHTTPClient().fetch(request)
            server, body = describe_upstream(response)
            logging.info("MyDict test: HTTP %s from %s server=%s body=%s", response.code, target, server, body)
        except HTTPClientError as e:
            server, body = describe_upstream(e.response)
            logging.warning("MyDict test: HTTP %s from %s server=%s body=%s", e.code, target, server, body)
            # 404: the address answers but has no MyDict query API — usually
            # the MyBooks address itself or a wrong port. 401/403: bad token.
            if e.code == 404:
                err = "dict.not_mydict"
            elif e.code in (401, 403):
                err = "dict.unauthorized"
            else:
                err = "dict.http_error"
            return {"err": err, "msg": f"HTTP {e.code} (Server: {server})", "code": e.code, "target": target, "server": server}
        except Exception as e:
            logging.warning("MyDict test: %s unreachable: %s", target, e)
            return {"err": "dict.unreachable", "msg": str(e), "target": target}

        try:
            body = json.loads(response.body)
        except ValueError:
            return {"err": "dict.bad_response", "msg": "Response is not JSON"}
        results = body.get("results") if isinstance(body, dict) else None
        return {"err": "ok", "word": word, "count": len(results) if isinstance(results, list) else None}


def routes():
    return [
        (r"/api/admin/reader/dict/test", ReaderDictTest),
        (r"/api/reader/dict-config", ReaderDictConfig),
        (r"/api/reader/dict/([A-Za-z0-9_-]{1,32})/query", ReaderDictQuery),
        (r"/api/reader/dict/([A-Za-z0-9_-]{1,32})/res/(.+)", ReaderDictResource),
    ]
