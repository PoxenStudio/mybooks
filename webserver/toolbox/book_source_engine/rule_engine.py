"""
书源规则引擎 — 支持 CSS 选择器 / JSONPath / 正则 / URL 模板 / Legado 选择器

解析 Legado 兼容的规则字符串，从 HTML 或 JSON 中提取结构化数据。
集成 JS 运行时（dukpy）和 content fallback 机制。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import deque
from itertools import zip_longest
from typing import Any, Optional
from urllib.parse import urljoin, urlparse, quote as _urlquote

# keep module-level import for backward compat
import urllib.parse

try:
    from .js_runtime import run_js, JsRuleUnsupported as _JsRuleUnsupported
except ImportError:  # standalone 运行（CLI / PyInstaller）
    from js_runtime import run_js, JsRuleUnsupported as _JsRuleUnsupported

logger = logging.getLogger(__name__)

# =============================================================================
# 选择器解析
# =============================================================================

_RE_ATTR_SUFFIX = re.compile(r'^(?P<selector>.+?)@(?P<attr>\w+)(?:\.(?P<index>\d+))?$')
_RE_JSONPATH = re.compile(r'^\$[.\[]')


def parse_selector(rule: str) -> dict:
    """解析规则字符串，返回类型和参数。"""
    if not rule or not rule.strip():
        return {"type": "skip", "reason": "empty"}
    rule = rule.strip()
    # @css: 显式前缀
    if rule.startswith("@css:"):
        inner = rule[5:].strip()
        m = _RE_ATTR_SUFFIX.match(inner)
        if m:
            return {"type": "css", "selector": m.group("selector").strip(),
                    "attr": m.group("attr"), "index": int(m.group("index")) if m.group("index") else None}
        return {"type": "css", "selector": inner, "attr": "text", "index": None}
    if _RE_JSONPATH.match(rule):
        return {"type": "jsonpath", "path": rule}
    if rule.startswith("{{") and rule.endswith("}}") and "{{{" not in rule:
        inner = rule[2:-2].strip()
        if not re.search(r'@@|@\w+@|##', inner):
            return {"type": "js", "code": inner}
    if rule.startswith(("//", "xpath:")):
        return {"type": "xpath", "expr": rule}
    if rule.startswith("/") and rule.endswith("/") and len(rule) > 2:
        return {"type": "regex", "pattern": rule[1:-1]}
    if re.match(r'^(class|id|tag|text)\.', rule):
        return {"type": "legado", "rule": rule}
    if rule.count("@") >= 2:
        return {"type": "legado", "rule": rule}
    # @attr (e.g. @text, @href) is Legado-style attribute extraction
    if re.match(r'^@[a-zA-Z][\w-]*$', rule):
        return {"type": "legado", "rule": rule}
    m = _RE_ATTR_SUFFIX.match(rule)
    if m:
        return {"type": "css", "selector": m.group("selector").strip(),
                "attr": m.group("attr"), "index": int(m.group("index")) if m.group("index") else None}
    return {"type": "css", "selector": rule, "attr": "text", "index": None}


def is_json_content(text: str) -> bool:
    text = text.strip()
    return text.startswith("{") or text.startswith("[")


def guess_response_type(text: str) -> str:
    if is_json_content(text):
        return "json"
    return "html"


# =============================================================================
# CSS 选择器引擎（基于 bs4 + lxml）
# =============================================================================

from bs4 import BeautifulSoup, Tag, NavigableString


def _resolve_css_attr(tag: Tag, attr: str, index: Optional[int] = None) -> str:
    attr = attr.lower()
    if attr == "text":
        text = tag.get_text(separator=" ", strip=True)
        return re.sub(r'\s+', ' ', text).strip()
    elif attr == "html":
        return "".join(str(c) for c in tag.children).strip()
    elif attr == "textnodes":
        parts = [str(c).strip() for c in tag.children if isinstance(c, NavigableString) and str(c).strip()]
        return "".join(parts)
    elif attr == "href":
        return str(tag.get("href", "")).strip()
    elif attr == "src":
        return str(tag.get("src", "")).strip()
    elif attr == "alt":
        return str(tag.get("alt", "")).strip()
    elif attr == "title":
        return str(tag.get("title", "")).strip()
    elif attr == "class":
        val = tag.get("class", [])
        return " ".join(val) if isinstance(val, list) else str(val).strip()
    elif attr == "style":
        return str(tag.get("style", "")).strip()
    else:
        return str(tag.get(attr, "")).strip()


def css_select_one(rule: str, html: str) -> Optional[str]:
    parsed = parse_selector(rule)
    if parsed["type"] != "css":
        return None
    soup = BeautifulSoup(html, "lxml")
    selector, attr, index = parsed["selector"], parsed["attr"], parsed["index"]
    try:
        tags = soup.select(selector)
    except Exception as exc:
        logger.warning("CSS selector failed: %s — %s", selector, exc)
        return None
    if not tags:
        return None
    target = tags[index] if index is not None and index < len(tags) else tags[0]
    return _resolve_css_attr(target, attr)


def css_select_all(rule: str, html: str) -> list[dict[str, str]]:
    parsed = parse_selector(rule)
    if parsed["type"] != "css":
        return []
    soup = BeautifulSoup(html, "lxml")
    try:
        tags = soup.select(parsed["selector"])
    except Exception as exc:
        logger.warning("CSS select_all failed: %s — %s", parsed["selector"], exc)
        return []
    return [{"_tag": str(t), "_element": t} for t in tags]


def css_extract_from_element(element: Tag, rule: str, base_url: str = "") -> Optional[str]:
    parsed = parse_selector(rule)
    if parsed["type"] != "css":
        return None
    selector, attr, index = parsed["selector"], parsed["attr"], parsed["index"]
    try:
        tags = element.select(selector)
    except Exception as exc:
        logger.warning("Sub-selector failed: %s — %s", selector, exc)
        return None
    if not tags:
        return None
    target = tags[index] if index is not None and index < len(tags) else tags[0]
    value = _resolve_css_attr(target, attr)
    if attr in ("href", "src") and base_url and value and not value.startswith(("http://", "https://", "//")):
        value = urllib.parse.urljoin(base_url, value)
    return value


# =============================================================================
# Header 解析
# =============================================================================

def parse_source_header(header) -> dict:
    if not header:
        return {}
    if isinstance(header, dict):
        return {str(k): str(v) for k, v in header.items()}
    if isinstance(header, str):
        text = header.strip()
        if text.startswith("@js:") or text.startswith("<js>"):
            return {}
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except (ValueError, TypeError):
            pass
    return {}


# =============================================================================
# Legado jsoup 选择器引擎（从 talebook fork 移植）
# =============================================================================

_ATTR_TEXT = {"text", "textnodes", "owntext"}
_ATTR_HTML = {"html", "outerhtml", "innerhtml", "all"}
_KNOWN_ATTRS = _ATTR_TEXT | _ATTR_HTML | {"href", "src", "title", "alt", "value", "content", "data-src", "data-original"}

_INDEX_LEGACY_RE = re.compile(r"^(.+?)([.!])(-?\d+(?::-?\d+)*)$")
_INDEX_BRACKET_RE = re.compile(r"\[(!?)\s*([\d\s:,-]*)\]$")


def _is_attr_token(token):
    key = token.lower()
    return key in _KNOWN_ATTRS or bool(re.match(r"^data-[\w-]+$", key))


def _split_index_spec(step):
    s = step.strip()
    m = _INDEX_BRACKET_RE.search(s)
    if m and re.search(r"\d", m.group(2)):
        items = _parse_bracket_items(m.group(2))
        if items is not None:
            return s[:m.start()].strip(), ("!" if m.group(1) else "."), items
    m = _INDEX_LEGACY_RE.match(s)
    if m:
        items = [int(x) for x in m.group(3).split(":")]
        return m.group(1).strip(), m.group(2), items
    return s, "", []


def _parse_bracket_items(content):
    items = []
    for part in content.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split(":")
        try:
            if len(bits) == 1:
                items.append(int(bits[0]))
            elif len(bits) <= 3:
                start = int(bits[0]) if bits[0].strip() else None
                end = int(bits[1]) if bits[1].strip() else None
                step = int(bits[2]) if len(bits) == 3 and bits[2].strip() else 1
                items.append((start, end, step))
            else:
                return None
        except ValueError:
            return None
    return items or None


def _expand_indexes(items, length):
    out = []
    seen = set()
    def add(i):
        if i not in seen:
            seen.add(i)
            out.append(i)
    for item in items:
        if isinstance(item, int):
            if 0 <= item < length:
                add(item)
            elif item < 0 and length >= -item:
                add(item + length)
            continue
        start, end, step = item
        start = 0 if start is None else (start + length if start < 0 else start)
        end = (length - 1) if end is None else (end + length if end < 0 else end)
        if (start < 0 and end < 0) or (start >= length and end >= length):
            continue
        start = min(max(start, 0), length - 1)
        end = min(max(end, 0), length - 1)
        if start == end or step >= length:
            add(start)
            continue
        step = step if step > 0 else (step + length if -step < length else 1)
        rng = range(start, end + 1, step) if end > start else range(start, end - 1, -step)
        for i in rng:
            add(i)
    return out


def _apply_index_filter(found, mode, items):
    if not items or mode not in (".", "!"):
        return found
    if not found:
        return []
    idxs = _expand_indexes(items, len(found))
    if mode == "!":
        excluded = set(idxs)
        return [el for i, el in enumerate(found) if i not in excluded]
    return [found[i] for i in idxs]


def _legado_own_text(tag):
    return " ".join(s for s in (str(c).strip() for c in tag.children if isinstance(c, NavigableString)) if s)


def _resolve_step_nodes(node, before):
    if not isinstance(node, Tag):
        return []
    if not before or before == "children":
        return [c for c in node.children if isinstance(c, Tag)]
    head, _, rest = before.partition(".")
    name = rest.split(".")[0].strip() if rest else ""
    if head == "class" and name:
        return node.find_all(class_=name)
    if head == "id" and name:
        return node.find_all(id=name)
    if head == "tag" and name:
        return node.find_all(name)
    if head == "text" and name:
        return [el for el in node.find_all(True) if name in _legado_own_text(el)]
    try:
        return node.select(before)
    except Exception:
        return []


def legado_select(node, rule):
    """Legado jsoup 风格的节点选择，返回 (节点列表, 属性名)。"""
    soup = to_soup(node)
    steps = [s for s in rule.split("@") if s != ""]
    if not steps:
        return [soup], ""
    attr = ""
    last = steps[-1]
    if "." not in last and _is_attr_token(last):
        attr = last
        steps = steps[:-1]
    current = [soup]
    for step in steps:
        before, mode, items = _split_index_spec(step)
        nxt = []
        for n in current:
            found = _resolve_step_nodes(n, before)
            nxt.extend(_apply_index_filter(found, mode, items))
        current = nxt
        if not current:
            break
    return current, attr


def to_soup(html):
    if isinstance(html, (Tag, BeautifulSoup)):
        return html
    return BeautifulSoup(html or "", "html.parser")


def _legado_extract_attr(node, attr):
    if node is None:
        return ""
    if isinstance(node, NavigableString):
        return str(node)
    if not attr:
        return node.get_text("\n", strip=True) if isinstance(node, Tag) else str(node)
    key = attr.lower()
    if key == "textnodes" and isinstance(node, Tag):
        parts = [str(c).strip() for c in node.children if isinstance(c, NavigableString)]
        return "\n".join(p for p in parts if p)
    if key == "owntext" and isinstance(node, Tag):
        parts = [str(c).strip() for c in node.children if isinstance(c, NavigableString)]
        return " ".join(p for p in parts if p)
    if key in _ATTR_TEXT:
        return node.get_text("\n", strip=True) if isinstance(node, Tag) else str(node)
    if key in _ATTR_HTML:
        return node.decode_contents() if isinstance(node, Tag) else str(node)
    if isinstance(node, Tag):
        val = node.get(attr)
        if val is None:
            return ""
        if isinstance(val, (list, tuple)):
            return " ".join(val)
        return str(val)
    return str(node)


def _apply_tail_regex(value: str, rule: str) -> str:
    if "##" not in rule:
        return value
    parts = rule.split("##")
    if len(parts) < 2:
        return value
    pattern = parts[1]
    replacement = parts[2] if len(parts) > 2 else ""
    replace_first = len(parts) > 3
    if not pattern:
        return value
    replacement = re.sub(r"\$(\d{1,2})", r"\\\1", replacement or "")
    try:
        if replace_first:
            m = re.search(pattern, value)
            if not m:
                return value
            return re.sub(pattern, replacement, m.group(0), count=1)
        return re.sub(pattern, replacement, value)
    except re.error:
        return value


def legado_extract_one(rule: str, html: str, base_url: str = "",
                       js_lib: str = "", variables: dict = None) -> Optional[str]:
    if rule.startswith("@js:") or rule.startswith("@js:\n"):
        js_code = rule[4:].strip()
        try:
            return run_js(js_code, result="", variables=variables or {},
                          base_url=base_url, js_lib=js_lib)
        except _JsRuleUnsupported as exc:
            logger.debug("JS rule unsupported: %s — %s", rule[:60], exc)
            return None
    js_code = ""
    if "@js:" in rule:
        parts = rule.split("@js:", 1)
        rule = parts[0].strip()
        js_code = parts[1].strip()
    tail_regex = ""
    if "##" in rule:
        idx = rule.find("##")
        tail_regex = rule[idx:]
        rule = rule[:idx].strip()
    nodes, attr = legado_select(html, rule)
    if not nodes:
        return None
    node = nodes[0]
    value = _legado_extract_attr(node, attr)
    if attr in ("href", "src") and base_url and value and not value.startswith(("http://", "https://", "//")):
        value = urllib.parse.urljoin(base_url, value)
    if js_code:
        try:
            result_val = run_js(js_code, result=value, variables=variables or {},
                                base_url=base_url, js_lib=js_lib)
            value = result_val
        except _JsRuleUnsupported as exc:
            logger.debug("JS rule unsupported (kept raw value): %s — %s", js_code[:60], exc)
    if tail_regex:
        value = _apply_tail_regex(value, tail_regex)
    return value.strip() if value else ""


def legado_extract_from_element(element: Tag, rule: str, base_url: str = "",
                                js_lib: str = "", variables: dict = None) -> Optional[str]:
    js_code = ""
    if "@js:" in rule:
        parts = rule.split("@js:", 1)
        rule = parts[0].strip()
        js_code = parts[1].strip()
    tail_regex = ""
    if "##" in rule:
        idx = rule.find("##")
        tail_regex = rule[idx:]
        rule = rule[:idx].strip()
    nodes, attr = legado_select(element, rule)
    if not nodes:
        return None
    node = nodes[0]
    value = _legado_extract_attr(node, attr)
    if attr in ("href", "src") and base_url and value and not value.startswith(("http://", "https://", "//")):
        value = urllib.parse.urljoin(base_url, value)
    if js_code:
        try:
            result_val = run_js(js_code, result=value, variables=variables or {},
                                base_url=base_url, js_lib=js_lib)
            value = result_val
        except _JsRuleUnsupported as exc:
            logger.debug("JS rule unsupported (kept raw value): %s — %s", js_code[:60], exc)
    if tail_regex:
        value = _apply_tail_regex(value, tail_regex)
    return value.strip() if value else ""


def legado_extract_list(list_rule: str, item_rules: dict[str, str], html: str,
                        base_url: str = "", js_lib: str = "",
                        variables: dict = None) -> list[dict[str, str]]:
    nodes, _attr = legado_select(html, list_rule)
    if not nodes:
        return []
    results = []
    for container in nodes:
        item = {}
        for field, sub_rule in item_rules.items():
            val = legado_extract_from_element(container, sub_rule, base_url, js_lib=js_lib, variables=variables)
            item[field] = (val or "").strip()
        results.append(item)
    return results


# =============================================================================
# JSONPath 轻量引擎
# =============================================================================

class JsonPathEngine:
    """轻量 JSONPath 实现，支持过滤器 [?(@.field == value)] 子集。"""

    _OP_RE = re.compile(r"\s*(==|!=|>=|<=|>|<)\s*")

    @staticmethod
    def parse(path: str) -> list:
        path = path.strip()
        if not path.startswith("$"):
            raise ValueError(f"JSONPath must start with '$': {path}")
        rest = path[1:]
        tokens = []
        pattern = re.compile(
            r"""\.(?P<dot_key>[a-zA-Z_][a-zA-Z0-9_]*)
            |\['(?P<sq_key>[^']+)'\]
            |\[(?P<idx>-?\d+)\]
            |\[(?P<slice>-?\d*:-?\d*)\]
            |\[(?P<star>\*)\]
            |\.\.(?P<deep>[a-zA-Z_][a-zA-Z0-9_]*)
            |\.(?P<num>\d+)""",
            re.VERBOSE,
        )
        pos = 0
        while pos < len(rest):
            m = pattern.match(rest, pos)
            if not m:
                if rest[pos] in (" ", "\t"):
                    pos += 1
                    continue
                if rest[pos] == "[":
                    end = rest.find("]", pos)
                    if end == -1:
                        raise ValueError(f"Unclosed bracket in JSONPath: {path}")
                    content = rest[pos + 1:end]
                    if content.startswith("?") or content.startswith("? "):
                        tokens.append(("filter", content[1:].strip()))
                    elif ":" in content:
                        tokens.append(("slice", content))
                    elif content == "*":
                        tokens.append(("wildcard",))
                    else:
                        tokens.append(("index", int(content)))
                    pos = end + 1
                    continue
                raise ValueError(f"Unexpected char at {pos} in JSONPath: {path}")
            if m.group("dot_key"):
                tokens.append(("key", m.group("dot_key")))
            elif m.group("sq_key"):
                tokens.append(("key", m.group("sq_key")))
            elif m.group("idx"):
                tokens.append(("index", int(m.group("idx"))))
            elif m.group("slice"):
                tokens.append(("slice", m.group("slice")))
            elif m.group("star"):
                tokens.append(("wildcard",))
            elif m.group("deep"):
                tokens.append(("deep", m.group("deep")))
            elif m.group("num"):
                tokens.append(("key", m.group("num")))
            pos = m.end()
        return tokens

    @staticmethod
    def _lookup(item, expr: str):
        """按 @.a.b / @['a'] / @ 语法从 item 取值。"""
        expr = expr.strip()
        if not expr or expr == "@":
            return item
        rest = expr
        if rest.startswith("@"):
            rest = rest[1:]
        cur = item
        while rest:
            rest = rest.strip()
            if rest.startswith("."):
                m = re.match(r"\.([A-Za-z_][\w]*)", rest)
                if not m:
                    return None
                key = m.group(1)
                rest = rest[m.end():]
            elif rest.startswith("['") or rest.startswith('["'):
                quote = rest[1]
                end = rest.find(quote, 2)
                if end == -1:
                    return None
                key = rest[2:end]
                rest = rest[end + 2:]
            else:
                return None
            if isinstance(cur, dict):
                cur = cur.get(key)
            else:
                return None
        return cur

    @staticmethod
    def _eval_filter(item, expr: str) -> bool:
        """求值过滤器表达式：支持 == != >= <= > <、&& ||、字符串/数字/布尔/null 字面量。"""
        expr = expr.strip()
        if not expr:
            return False
        # 剥掉 [?()] 语法带来的外层括号
        while expr.startswith("(") and expr.endswith(")"):
            expr = expr[1:-1].strip()

        # 先按 || 拆（取任一为真）
        for or_part in expr.split("||"):
            or_part = or_part.strip()
            if not or_part:
                continue
            # 再按 && 拆（全部为真）
            and_parts = or_part.split("&&")
            ok = True
            for part in and_parts:
                part = part.strip()
                if not part:
                    ok = False
                    break
                m = JsonPathEngine._OP_RE.search(part)
                if not m:
                    ok = False
                    break
                op = m.group(1)
                left = part[:m.start()].strip()
                right = part[m.end():].strip()
                lv = JsonPathEngine._lookup(item, left)
                rv = JsonPathEngine._parse_literal(right)
                if not JsonPathEngine._compare(lv, rv, op):
                    ok = False
                    break
            if ok:
                return True
        return False

    @staticmethod
    def _parse_literal(text: str):
        text = text.strip()
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
            return text[1:-1]
        low = text.lower()
        if low == "true":
            return True
        if low == "false":
            return False
        if low == "null":
            return None
        try:
            if re.fullmatch(r"-?\d+", text):
                return int(text)
            if re.fullmatch(r"-?\d+\.\d+", text):
                return float(text)
        except ValueError:
            pass
        return text

    @staticmethod
    def _compare(lv, rv, op: str) -> bool:
        try:
            if op == "==":
                return lv == rv
            if op == "!=":
                return lv != rv
            if lv is None or rv is None:
                return False
            if op == ">":
                return lv > rv
            if op == "<":
                return lv < rv
            if op == ">=":
                return lv >= rv
            if op == "<=":
                return lv <= rv
        except TypeError:
            return False
        return False

    @staticmethod
    def query(obj: Any, path: str) -> list:
        tokens = JsonPathEngine.parse(path)
        results = JsonPathEngine._eval(obj, tokens, 0)
        return [json.dumps(r, ensure_ascii=False) if not isinstance(r, str) else r for r in results]

    @staticmethod
    def query_first(obj: Any, path: str) -> Optional[str]:
        results = JsonPathEngine.query(obj, path)
        return results[0] if results else None

    @staticmethod
    def _eval(obj: Any, tokens: list, pos: int) -> list:
        if pos >= len(tokens):
            return [obj] if obj is not None else []
        token = tokens[pos]
        kind = token[0]
        if kind == "key":
            key = token[1]
            if isinstance(obj, dict):
                val = obj.get(key)
                return JsonPathEngine._eval(val, tokens, pos + 1) if val is not None else []
            return []
        elif kind == "index":
            idx = token[1]
            if isinstance(obj, (list, tuple)):
                try:
                    val = obj[idx]
                except IndexError:
                    return []
                return JsonPathEngine._eval(val, tokens, pos + 1)
            return []
        elif kind == "slice":
            parts = token[1].split(":")
            start = int(parts[0]) if parts[0] else None
            end = int(parts[1]) if len(parts) > 1 and parts[1] else None
            if isinstance(obj, (list, tuple)):
                sliced = obj[start:end]
                results = []
                for item in sliced:
                    results.extend(JsonPathEngine._eval(item, tokens, pos + 1))
                return results
            return []
        elif kind == "wildcard":
            if isinstance(obj, (list, tuple)):
                results = []
                for item in obj:
                    results.extend(JsonPathEngine._eval(item, tokens, pos + 1))
                return results
            elif isinstance(obj, dict):
                results = []
                for val in obj.values():
                    results.extend(JsonPathEngine._eval(val, tokens, pos + 1))
                return results
            return []
        elif kind == "filter":
            expr = token[1]
            if isinstance(obj, (list, tuple)):
                results = []
                for item in obj:
                    if JsonPathEngine._eval_filter(item, expr):
                        results.extend(JsonPathEngine._eval(item, tokens, pos + 1))
                return results
            return []
        elif kind == "deep":
            key = token[1]
            results = []
            JsonPathEngine._deep_search(obj, key, tokens, pos + 1, results)
            return results
        return []

    @staticmethod
    def _deep_search(obj: Any, key: str, tokens: list, pos: int, results: list):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == key:
                    results.extend(JsonPathEngine._eval(v, tokens, pos))
                else:
                    JsonPathEngine._deep_search(v, key, tokens, pos, results)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                JsonPathEngine._deep_search(item, key, tokens, pos, results)


# =============================================================================
# URL 模板引擎
# =============================================================================

_RE_URL_TEMPLATE = re.compile(r'\{\{(?P<var>\w+)\}\}')


def render_url_template(template: str, **kwargs) -> str:
    def replacer(m: re.Match) -> str:
        var = m.group("var")
        if var in kwargs:
            val = kwargs[var]
            if var == "key":
                return urllib.parse.quote(str(val), safe="")
            return str(val)
        return m.group(0)
    return _RE_URL_TEMPLATE.sub(replacer, template)


# =============================================================================
# 组合符辅助
# =============================================================================

_GET_RE = re.compile(r"@get:\{([^}]+)\}")
_PUT_RE = re.compile(r"@put:\{([^:]+):([^}]+)\}")
_TEMPLATE_RE = re.compile(r"\{\{([^{}]+)\}\}")


def _interleave(groups):
    """交错合并多组元素列表。"""
    out = []
    if not groups:
        return out
    for items in zip_longest(*groups, fillvalue=None):
        out.extend(item for item in items if item is not None)
    return out


def _is_put_get_rule(rule):
    return rule.startswith("@put:{") or rule.startswith("@get:")


def _eval_put_get(rule, doc, base_url, js_lib, variables):
    """处理 @put: / @get: 规则，返回 (value, changed_variables) 或 None。"""
    put = _PUT_RE.match(rule)
    if put:
        key, inner = put.group(1).strip(), put.group(2).strip()
        val = _eval_single_rule(inner, doc, base_url, js_lib, variables)
        variables[key] = val or ""
        return "", variables
    if rule.startswith("@get:"):
        m = _GET_RE.match(rule)
        if m:
            return str(variables.get(m.group(1).strip(), "")), variables
    return None, variables


def _eval_single_rule(rule, content, base_url="", js_lib="", variables=None):
    """对单条规则（不含组合符）求值的核心逻辑。"""
    if not rule:
        return None

    # @js:
    if rule.startswith("@js:") or rule.startswith("@js:\n"):
        js_code = rule[4:].strip()
        try:
            return run_js(js_code, result="", variables=variables or {},
                          base_url=base_url, js_lib=js_lib)
        except _JsRuleUnsupported as exc:
            logger.debug("JS rule unsupported: %s — %s", rule[:60], exc)
            return None

    # {{result.fieldName}} — 直接 JSON 字段提取
    if rule.startswith("{{") and rule.endswith("}}") and "{{{" not in rule:
        m = re.match(r'^\{\{\s*result\.(\w+)\s*\}\}$', rule)
        if m:
            field_name = m.group(1)
            try:
                data = json.loads(content) if isinstance(content, str) else content
                if isinstance(data, dict) and field_name in data:
                    return str(data[field_name])
            except (json.JSONDecodeError, TypeError):
                pass

    parsed = parse_selector(rule)
    kind = parsed["type"]
    if kind == "skip":
        return None
    elif kind == "css":
        return css_select_one(rule, content)
    elif kind == "legado":
        return legado_extract_one(rule, content, base_url, js_lib=js_lib, variables=variables)
    elif kind == "xpath":
        try:
            from lxml import html as lxml_html
            tree = lxml_html.fromstring(content)
            results = tree.xpath(parsed["expr"])
            texts = []
            for r in results:
                if isinstance(r, str):
                    texts.append(r)
                else:
                    texts.append(r.text_content() if hasattr(r, 'text_content') else (r.text or ''))
            return '\n'.join(t.strip() for t in texts if t and t.strip())
        except Exception as exc:
            logger.warning("XPath failed: %s — %s", parsed["expr"], exc)
            return None
    elif kind == "jsonpath":
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return None
        return JsonPathEngine.query_first(data, parsed["path"])
    elif kind == "js":
        logger.warning("JS rule not supported (MVP): %s", rule[:50])
        return None
    elif kind == "regex":
        m = re.search(parsed["pattern"], content)
        return m.group(1) if m and m.lastindex else (m.group(0) if m else None)
    return None


def extract_single(rule: str, content: str, base_url: str = "",
                   js_lib: str = "", variables: dict = None) -> Optional[str]:
    """统一规则入口，支持 || / && 组合符及 @put:/@get: 变量存取。"""
    if not rule:
        return None
    if variables is None:
        variables = {}
    rule = rule.strip()

    # @put: / @get: 单独处理（仅当规则不含 ||）
    if "||" not in rule and _is_put_get_rule(rule):
        result, _ = _eval_put_get(rule, content, base_url, js_lib, variables)
        return result

    # || 取首个非空
    for alt in rule.split("||"):
        alt = alt.strip()
        if not alt:
            continue
        # 每个 alt 内：@put: 副作用的处理
        if _is_put_get_rule(alt):
            result, _ = _eval_put_get(alt, content, base_url, js_lib, variables)
            if result:
                return result
            continue
        # && 拼接分片
        parts = []
        for part in alt.split("&&"):
            part = part.strip()
            if not part:
                continue
            if _is_put_get_rule(part):
                result, _ = _eval_put_get(part, content, base_url, js_lib, variables)
                if result:
                    parts.append(result)
                continue
            val = _eval_single_rule(part, content, base_url, js_lib, variables)
            if val:
                parts.append(val)
        if parts:
            return "".join(p for p in parts if p)
    return None


def _extract_list_single(list_rule: str, item_rules: dict, content: str,
                         base_url: str = "", js_lib: str = "",
                         variables: dict = None) -> list[dict[str, str]]:
    """单条 list_rule（不含组合符）的提取逻辑。"""
    parsed = parse_selector(list_rule)
    if parsed["type"] == "legado":
        return legado_extract_list(list_rule, item_rules, content, base_url, js_lib=js_lib, variables=variables)
    if parsed["type"] != "css":
        # JSONPath list
        if parsed["type"] == "jsonpath":
            try:
                data = json.loads(content) if isinstance(content, str) else content
            except json.JSONDecodeError:
                return []
            items = JsonPathEngine.query(data, parsed["path"])
            results = []
            for item_str in items:
                try:
                    item_data = json.loads(item_str)
                except json.JSONDecodeError:
                    continue
                row = {}
                for field, sub_rule in item_rules.items():
                    val = None
                    if sub_rule.startswith("$"):
                        val = JsonPathEngine.query_first(item_data, sub_rule)
                    elif sub_rule in item_data:
                        val = str(item_data.get(sub_rule, ""))
                    else:
                        val = extract_single(sub_rule, json.dumps(item_data, ensure_ascii=False),
                                             base_url, js_lib, variables)
                    row[field] = (val or "").strip()
                if row.get("name") or row.get("bookUrl") or row.get("chapterName") or row.get("chapterUrl"):
                    results.append(row)
            return results
        return []
    soup = BeautifulSoup(content, "lxml") if isinstance(content, str) else content
    try:
        containers = soup.select(parsed["selector"])
    except Exception as exc:
        logger.warning("extract_list CSS failed: %s — %s", parsed["selector"], exc)
        return []
    results = []
    for container in containers:
        item = {}
        for field, sub_rule in item_rules.items():
            sub_parsed = parse_selector(sub_rule)
            if sub_parsed["type"] == "skip":
                continue
            if sub_parsed["type"] == "css":
                    val = css_extract_from_element(container, sub_rule, base_url)
            elif sub_parsed["type"] == "legado":
                val = legado_extract_from_element(container, sub_rule, base_url, js_lib=js_lib, variables=variables)
            elif sub_parsed["type"] == "regex":
                m = re.search(sub_parsed["pattern"], str(container))
                val = m.group(1) if m else None
            elif sub_parsed["type"] == "js":
                val = extract_single(sub_rule, str(container), base_url, js_lib, variables)
            else:
                val = None
            item[field] = (val or "").strip()
        results.append(item)
    return results


def extract_list(list_rule: str, item_rules: dict[str, str], content: str,
                 base_url: str = "", js_lib: str = "",
                 variables: dict = None) -> list[dict[str, str]]:
    """统一列表提取入口，支持 || / %% 组合符。"""
    if not list_rule:
        return []
    # || 取首个非空
    for alt in list_rule.split("||"):
        alt = alt.strip()
        if not alt:
            continue
        # %% 交错
        if "%%" in alt:
            groups = []
            for part in alt.split("%%"):
                part = part.strip()
                if part:
                    groups.append(_extract_list_single(part, item_rules, content, base_url, js_lib, variables))
            result = _interleave(groups)
        else:
            result = _extract_list_single(alt, item_rules, content, base_url, js_lib, variables)
        if result:
            return result
    return []


# =============================================================================
# 内容净化 (replaceRegex)
# =============================================================================

def apply_replace_rules(text: str, rules: list) -> str:
    for rule in rules:
        if isinstance(rule, dict):
            pattern = rule.get("pattern", "")
            replacement = rule.get("replacement", "")
            is_regex = rule.get("isRegex", False)
        else:
            pattern = rule.pattern
            replacement = rule.replacement
            is_regex = rule.isRegex
        if not pattern:
            continue
        try:
            if is_regex:
                text = re.sub(pattern, replacement, text)
            else:
                text = text.replace(pattern, replacement)
        except re.error as exc:
            logger.warning("replace rule regex error: %s — %s", pattern, exc)
    return text


# 零宽字符清理（借鉴 talebook cleaner.py：去除 U+200B/U+200C/U+200D/U+FEFF 等隐形字符）
_ZERO_WIDTH_RE = re.compile("[\u200b\u200c\u200d\ufeff]")
_MULTI_BLANK_LINES_RE = re.compile(r"\n{3,}")


def normalize_content_text(text: str) -> str:
    """规整正文文本：去零宽字符、统一换行、去行首尾空白、折叠多空行。

    借鉴 talebook `webserver/services/booksource/cleaner.py` 的 cleaner 思路。
    """
    if not text:
        return ""
    text = _ZERO_WIDTH_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _MULTI_BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


# =============================================================================
# 辅助函数
# =============================================================================


def _dedupe_chapters(chapters):
    """章节去重，重复项保留靠后出现的一项。"""
    last_index = {}
    for i, ch in enumerate(chapters):
        name = ch.get("chapterName", ch.get("name", ""))
        url = ch.get("chapterUrl", ch.get("url", ""))
        last_index[(name, url)] = i
    keep = set(last_index.values())
    return [ch for i, ch in enumerate(chapters) if i in keep]


def _resolve_url(url, base=None):
    if not url:
        return ""
    if url.startswith(("http://", "https://", "//")):
        return url
    if base:
        return urljoin(base, url)
    return url


def _safe_filename(name):
    name = re.sub(r"[\\/:*?\"<>|\r\n\t]", "_", name or "online")
    return name.strip()[:80] or "online"


def make_doc(text, rule_hint=""):
    """根据规则提示把响应文本解析为 JSON 对象或 BeautifulSoup。"""
    hint = (rule_hint or "").strip()
    if hint.startswith("$") or hint.startswith("@json:"):
        try:
            return json.loads(text), "json"
        except ValueError:
            pass
    stripped = text.lstrip()
    if stripped[:1] in ("{", "["):
        try:
            return json.loads(text), "json"
        except ValueError:
            pass
    from bs4 import BeautifulSoup
    return BeautifulSoup(text or "", "html.parser"), "html"


# =============================================================================
# 完整抓取流程（搜索→详情→目录→正文）
# =============================================================================

import random as _random
import requests as req_lib

try:
    import chardet as _chardet
    _HAS_CHARDET = True
except ImportError:  # pragma: no cover - chardet 通常随 requests 安装
    _chardet = None
    _HAS_CHARDET = False

# 浏览器 UA 池：会话级随机轮换，避免单一 UA 指纹被锁定
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

# 浏览器风格默认请求头（含 Sec-Fetch-* 等真实浏览器字段）
_DEFAULT_HEADERS = {
    "User-Agent": _UA_POOL[0],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# 抓取节流与重试（可用环境变量覆盖）
FETCH_DELAY_SECONDS = float(os.environ.get("MYBOOKS_FETCH_DELAY", "0.2"))
FETCH_JITTER_SECONDS = float(os.environ.get("MYBOOKS_FETCH_JITTER", "0.15"))
FETCH_RETRIES = int(os.environ.get("MYBOOKS_FETCH_RETRIES", "2"))
FETCH_RETRY_BACKOFF = 1.0
HTTP_TIMEOUT = float(os.environ.get("MYBOOKS_HTTP_TIMEOUT", "30"))


def _pick_ua() -> str:
    """从 UA 池随机取一个 UA。"""
    try:
        return _random.choice(_UA_POOL)
    except Exception:  # pragma: no cover
        return _UA_POOL[0]


def _session_headers() -> dict:
    """构造带随机 UA 的浏览器风格请求头。"""
    headers = dict(_DEFAULT_HEADERS)
    headers["User-Agent"] = _pick_ua()
    return headers


def _new_session():
    """创建底层 HTTP 会话：优先 curl_cffi（Chrome TLS 指纹），否则 requests。

    可用 MYBOOKS_HTTP_BACKEND=requests 强制退回纯 requests，
    MYBOOKS_HTTP_BACKEND=curl_cffi 强制使用 curl_cffi。
    """
    backend = os.environ.get("MYBOOKS_HTTP_BACKEND", "auto").lower()
    if backend in ("auto", "curl_cffi", "cffi", "curl"):
        try:
            from curl_cffi import requests as _cffi_requests
            sess = _cffi_requests.Session(impersonate="chrome")
            logger.info("HTTP backend: curl_cffi (Chrome TLS 指纹)")
            return sess
        except Exception as exc:
            logger.warning("curl_cffi 不可用，退回 requests: %s", exc)
    logger.info("HTTP backend: requests")
    return req_lib.Session()


def build_source_session(source=None):
    """根据书源创建一个带默认头（随机 UA）的 HTTP 会话。"""
    session = _new_session()
    headers = _session_headers()
    if source is not None:
        hdr = parse_source_header(getattr(source, "header", None))
        headers.update(hdr)
        source_url = getattr(source, "bookSourceUrl", None) or getattr(source, "book_source_url", None)
        if source_url:
            headers.setdefault("Referer", source_url)
    session.headers.update(headers)
    proxy = os.environ.get("MYBOOKS_PROXY", "").strip()
    if proxy:
        try:
            session.proxies.update({"http": proxy, "https": proxy})
        except Exception as exc:  # pragma: no cover
            logger.warning("代理设置失败 %s: %s", proxy, exc)
    return session


def _retry_after(resp) -> float:
    """从响应头读取 Retry-After（秒），失败返回 0。上限 60s，防异常站点无限等待。"""
    try:
        headers = getattr(resp, "headers", None)
        if not headers:
            return 0.0
        val = headers.get("Retry-After")
        if val:
            return min(float(val), 60.0)
    except Exception:
        pass
    return 0.0


def _rotate_ua(session):
    """换一个 UA 写入会话，用于 403/429 规避。"""
    try:
        session.headers["User-Agent"] = _pick_ua()
    except Exception:
        pass


def _do_http(session, method: str, url: str, timeout: float = HTTP_TIMEOUT, **kwargs):
    """带状态感知重试的请求执行器。

    - 连接异常 / 5xx：指数退避重试
    - 429：优先按 Retry-After 等待，其次退避
    - 403：换 UA 后重试
    """
    fn = session.post if method.upper() == "POST" else session.get
    last_exc = None
    for attempt in range(FETCH_RETRIES + 1):
        try:
            resp = fn(url, timeout=timeout, **kwargs)
        except Exception as exc:
            last_exc = exc
            logger.error("HTTP %s failed: %s — %s (attempt %d/%d)",
                         method, url, exc, attempt + 1, FETCH_RETRIES + 1)
            if attempt < FETCH_RETRIES:
                _rotate_ua(session)
                time.sleep(FETCH_RETRY_BACKOFF * (2 ** attempt))
                continue
            raise last_exc
        code = int(getattr(resp, "status_code", 0) or 0)
        if code == 429:
            wait = _retry_after(resp) or (FETCH_RETRY_BACKOFF * (2 ** attempt))
            logger.warning("HTTP 429 (%s): %s — 等待 %.1fs 重试", method, url, wait)
            if attempt < FETCH_RETRIES:
                time.sleep(wait)
                continue
        elif code in (403, 500, 502, 503, 504):
            logger.warning("HTTP %d (%s): %s — 重试", code, method, url)
            if attempt < FETCH_RETRIES:
                _rotate_ua(session)
                time.sleep(FETCH_RETRY_BACKOFF * (2 ** attempt))
                continue
        resp.raise_for_status()
        return resp
    raise last_exc or RuntimeError("HTTP request failed: %s" % url)


def _response_text(resp, encoding: str = "") -> str:
    """统一取响应文本：优先书源声明编码，其次 chardet 探测，再退回 utf-8。

    兼容 requests（有 apparent_encoding）与 curl_cffi（无该属性）两类响应对象。
    """
    if encoding:
        try:
            resp.encoding = encoding
        except Exception:
            pass
    elif not getattr(resp, "encoding", None) or str(resp.encoding).lower() in ("iso-8859-1", "iso8859-1"):
        # 服务端未声明 charset 才探测，避免覆盖已声明编码
        guessed = getattr(resp, "apparent_encoding", "") or ""
        if not guessed and _HAS_CHARDET:
            try:
                guessed = _chardet.detect(resp.content).get("encoding") or "utf-8"
            except Exception:
                guessed = "utf-8"
        try:
            resp.encoding = guessed or "utf-8"
        except Exception:
            pass
    return resp.text


def fetch_url(url: str, session=None, source=None, encoding: str = "") -> str:
    if session is None:
        session = build_source_session(source)
    hdrs = parse_source_header(getattr(source, "header", None) if source else None)

    # Ensure URL is ASCII-safe (percent-encode non-ASCII chars)
    try:
        url.encode("ascii")
    except UnicodeEncodeError:
        parsed = urllib.parse.urlparse(url)
        safe_path = urllib.parse.quote(parsed.path, safe="/%")
        safe_query = urllib.parse.quote(parsed.query, safe="=&%")
        safe_fragment = urllib.parse.quote(parsed.fragment, safe="")
        url = urllib.parse.urlunparse((
            parsed.scheme, parsed.netloc, safe_path,
            parsed.params, safe_query, safe_fragment,
        ))

    # 节流：随机抖动，避免固定间隔指纹（可用 MYBOOKS_FETCH_DELAY/JITTER 覆盖）
    if FETCH_DELAY_SECONDS > 0:
        time.sleep(FETCH_DELAY_SECONDS + _random.uniform(0, FETCH_JITTER_SECONDS))

    resp = _do_http(session, "GET", url, headers=hdrs or None)
    return _response_text(resp, encoding)


def _parse_search_url(search_url_str: str, base_url: str = ""):
    """解析 searchUrl + 选项（兼容 JSON 和 Legado Python 风格 dict）"""
    rule = (search_url_str or "").strip()
    if not rule:
        return "", {}
    idx = rule.find(",{")
    while idx != -1:
        candidate = rule[idx + 1:].strip()
        try:
            opts = json.loads(candidate)
            if isinstance(opts, dict):
                return rule[:idx].strip(), opts
        except ValueError:
            pass
        # Try Legado-style with single quotes / Python bools
        try:
            fixed = candidate.replace("'", '"')
            fixed = re.sub(r'(?<![:\w])True(?![:\w])', 'true', fixed)
            fixed = re.sub(r'(?<![:\w])False(?![:\w])', 'false', fixed)
            fixed = re.sub(r'(?<![:\w])None(?![:\w])', 'null', fixed)
            opts = json.loads(fixed)
            if isinstance(opts, dict):
                return rule[:idx].strip(), opts
        except (ValueError, KeyError):
            pass
        idx = rule.find(",{", idx + 1)
    return rule, {}


def search_books(source, keyword: str, session=None, page: int = 1) -> list[dict[str, str]]:
    if session is None:
        session = build_source_session(source)

    # ── 1. 解析 searchUrl（支持 @js: 前缀） ──
    raw_search_url = source.searchUrl or source.bookSourceUrl
    url_part, options = _parse_search_url(raw_search_url)
    search_url = render_url_template(url_part, key=keyword, page=page, baseUrl=source.bookSourceUrl)

    # Handle @js: searchUrl — evaluate JS to get actual URL
    if search_url.startswith("@js:") or search_url.startswith("@js:\n"):
        try:
            variables = {"key": keyword, "page": page, "baseUrl": source.bookSourceUrl}
            evaled = extract_single(search_url, "", base_url=source.bookSourceUrl,
                                    js_lib=source.jsLib, variables=variables)
            if evaled:
                search_url = evaled.strip()
        except Exception as exc:
            logger.warning("JS searchUrl eval failed [%s]: %s", source.bookSourceName, exc)
            return []

    # Resolve relative URLs against bookSourceUrl
    if search_url and not search_url.startswith(("http://", "https://", "@")):
        resolved = _resolve_url(search_url, source.bookSourceUrl)
        if resolved != search_url:
            search_url = resolved

    # Replace Python template placeholders {{source.xxx}}
    if "{{source." in search_url:
        for key in ("bookSourceUrl", "bookSourceName", "bookSourceGroup"):
            placeholder = "{{source." + key + "}}"
            if placeholder in search_url:
                val = getattr(source, key, "") or ""
                search_url = search_url.replace(placeholder, val)

    if not search_url:
        logger.warning("searchUrl empty [%s]", source.bookSourceName)
        return []

    charset = options.get("charset", "")
    method = str(options.get("method", "GET")).upper()

    if method == "POST":
        body = render_url_template(str(options.get("body", "")), key=keyword, page=page)
        try:
            data = body.encode(charset) if charset else body.encode("utf-8")
            resp = _do_http(session, "POST", search_url, data=data)
        except Exception as exc:
            logger.error("HTTP POST failed: %s — %s", search_url, exc)
            raise
        html = _response_text(resp, charset)
    else:
        html = fetch_url(search_url, session=session, encoding=charset)

    variables = {"key": keyword, "page": page, "baseUrl": source.bookSourceUrl}
    rule = source.ruleSearch
    init_rule = rule.init if hasattr(rule, "init") else ""

    # init 规则缩小上下文，共享 variables（@put: 注入全局可见）
    content_for_rules = html
    if init_rule:
        init_val = extract_single(init_rule, html, source.bookSourceUrl, source.jsLib, variables)
        if init_val:
            content_for_rules = init_val

    content_type = guess_response_type(html)
    if content_type == "json":
        data = json.loads(html)
        results = []
        try:
            items = JsonPathEngine.query(data, rule.bookList)
            for item_str in items:
                try:
                    item_data = json.loads(item_str)
                except json.JSONDecodeError:
                    continue
                book = {}
                for field in ("name", "author", "kind", "wordCount",
                             "lastChapter", "intro", "coverUrl", "bookUrl"):
                    rule_val = getattr(rule, field, "")
                    if not rule_val:
                        continue
                    val = extract_single(rule_val, json.dumps(item_data, ensure_ascii=False),
                                         source.bookSourceUrl, source.jsLib, variables)
                    book[field] = (val or "").strip()
                if book.get("name") or book.get("bookUrl"):
                    results.append(book)
        except Exception as exc:
            logger.error("JSON search parse failed: %s", exc)
        return results
    else:
        item_rules = {}
        for field in ("name", "author", "kind", "wordCount",
                     "lastChapter", "intro", "coverUrl", "bookUrl"):
            val = getattr(rule, field, "")
            if val:
                item_rules[field] = val
        return extract_list(rule.bookList, item_rules, content_for_rules,
                           base_url=source.bookSourceUrl, js_lib=source.jsLib,
                           variables=variables)


def fetch_book_info(source, book_url: str, session=None) -> dict[str, str]:
    if session is None:
        session = build_source_session(source)
    info_url = _resolve_url(book_url, source.bookSourceUrl)
    html = fetch_url(info_url, session=session)
    variables = {"baseUrl": source.bookSourceUrl}
    rule = source.ruleBookInfo
    init_rule = rule.init if hasattr(rule, "init") else ""

    content_for_rules = html
    if init_rule:
        init_val = extract_single(init_rule, html, source.bookSourceUrl, source.jsLib, variables)
        if init_val:
            content_for_rules = init_val

    result = {}
    for field in ("name", "author", "kind", "wordCount",
                   "lastChapter", "intro", "coverUrl", "tocUrl"):
        rule_val = getattr(rule, field, "")
        if not rule_val:
            continue
        val = extract_single(rule_val, content_for_rules, source.bookSourceUrl, js_lib=source.jsLib, variables=variables)
        result[field] = (val or "").strip()
    result["bookUrl"] = book_url
    return result


def fetch_toc(source, toc_url: str, session=None, max_pages: int = 1000) -> list[dict[str, str]]:
    if session is None:
        session = build_source_session(source)
    rule = source.ruleToc
    chapter_list_rule = (rule.chapterList or "").strip()
    reverse = chapter_list_rule.startswith("-")
    if chapter_list_rule[:1] in ("-", "+"):
        chapter_list_rule = chapter_list_rule[1:]
    next_rule = rule.nextTocUrl if hasattr(rule, "nextTocUrl") else ""
    init_rule = rule.init if hasattr(rule, "init") else ""

    variables = {"baseUrl": source.bookSourceUrl}

    queue = deque([_resolve_url(toc_url, source.bookSourceUrl)])
    seen_urls = set()
    chapters = []
    pages = 0

    while queue and pages < max_pages:
        url = queue.popleft()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        pages += 1

        html = fetch_url(url, session=session)

        content_for_rules = html
        if init_rule:
            init_val = extract_single(init_rule, html, source.bookSourceUrl, source.jsLib, variables)
            if init_val:
                content_for_rules = init_val

        content_type = guess_response_type(html)

        if content_type == "json":
            try:
                data = json.loads(html)
                items = JsonPathEngine.query(data, chapter_list_rule) if chapter_list_rule else []
                for item_str in items:
                    try:
                        item_data = json.loads(item_str)
                    except json.JSONDecodeError:
                        continue
                    ch = {}
                    for field in ("chapterName", "chapterUrl", "isVolume", "updateTime"):
                        rv = getattr(rule, field, "")
                        if not rv:
                            continue
                        val = extract_single(rv, json.dumps(item_data, ensure_ascii=False),
                                             source.bookSourceUrl, source.jsLib, variables)
                        ch[field] = (val or "").strip()
                    if ch.get("chapterName") or ch.get("chapterUrl"):
                        chapters.append(ch)
            except Exception as exc:
                logger.error("JSON toc parse failed: %s", exc)
        else:
            item_rules = {}
            for field in ("chapterName", "chapterUrl", "isVolume", "updateTime"):
                rv = getattr(rule, field, "")
                if rv:
                    item_rules[field] = rv
            page_chapters = extract_list(chapter_list_rule, item_rules, content_for_rules,
                                         base_url=source.bookSourceUrl, js_lib=source.jsLib,
                                         variables=variables)
            chapters.extend(page_chapters)

        # 翻页
        if next_rule:
            try:
                import re as _re
                from bs4 import BeautifulSoup as _BS
                soup = _BS(html, "html.parser")
                parsed = parse_selector(next_rule)
                if parsed["type"] == "css":
                    tags = soup.select(parsed["selector"])
                    for tag in tags:
                        val = _resolve_css_attr(tag, parsed.get("attr", "href"))
                        if val and val not in seen_urls:
                            queue.append(_resolve_url(val, url))
                elif parsed["type"] == "legado":
                    nodes, attr = legado_select(soup, next_rule)
                    for node in nodes:
                        val = _legado_extract_attr(node, attr or "href")
                        if val and val not in seen_urls:
                            queue.append(_resolve_url(val, url))
            except Exception as exc:
                logger.warning("nextTocUrl parse failed: %s — %s", next_rule, exc)

    if reverse:
        chapters.reverse()

    chapters = _dedupe_chapters(chapters)
    for i, ch in enumerate(chapters, 1):
        ch["index"] = i
    return chapters


def fetch_content(source, chapter_url: str, session=None, max_pages: int = 20) -> str:
    """获取正文内容，支持多页（nextContentUrl）和 content fallback 机制。"""
    if session is None:
        session = build_source_session(source)
    rule = source.ruleContent
    content_rule = rule.content
    next_rule = rule.nextContentUrl if hasattr(rule, "nextContentUrl") else ""
    init_rule = rule.init if hasattr(rule, "init") else ""

    variables = {"baseUrl": source.bookSourceUrl}

    queue = deque([_resolve_url(chapter_url, source.bookSourceUrl)])
    seen_urls = set()
    parts = []
    pages = 0

    while queue and pages < max_pages:
        url = queue.popleft()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        pages += 1

        html = fetch_url(url, session=session)

        # sourceRegex: 先按正则从页面源码中截取正文片段（Legado 兼容）
        if rule.sourceRegex:
            try:
                m = re.search(rule.sourceRegex, html)
                if m:
                    matched = m.group(1) if m.lastindex else m.group(0)
                    if matched:
                        html = matched
            except re.error as exc:
                logger.warning("sourceRegex error: %s — %s", rule.sourceRegex, exc)

        content_for_rules = html
        if init_rule:
            init_val = extract_single(init_rule, html, source.bookSourceUrl, source.jsLib, variables)
            if init_val:
                content_for_rules = init_val

        text = extract_single(content_rule, content_for_rules,
                              source.bookSourceUrl, js_lib=source.jsLib, variables=variables)
        if text:
            parts.append(text)
        elif content_rule and ('@js:' in content_rule or '<js>' in content_rule):
            try:
                from .content_fallbacks import try_fetch_content
            except ImportError:
                from content_fallbacks import try_fetch_content
            try:
                fallback = try_fetch_content(url, source)
                if fallback:
                    parts.append(fallback)
            except Exception as exc:
                logger.warning("content fallback failed: %s — %s", url, exc)

        # 翻页
        if next_rule:
            try:
                from bs4 import BeautifulSoup as _BS
                soup = _BS(html, "html.parser")
                parsed = parse_selector(next_rule)
                if parsed["type"] == "css":
                    tags = soup.select(parsed["selector"])
                    for tag in tags:
                        val = _resolve_css_attr(tag, parsed.get("attr", "href"))
                        if val and val not in seen_urls:
                            queue.append(_resolve_url(val, url))
                elif parsed["type"] == "legado":
                    nodes, attr = legado_select(soup, next_rule)
                    for node in nodes:
                        val = _legado_extract_attr(node, attr or "href")
                        if val and val not in seen_urls:
                            queue.append(_resolve_url(val, url))
            except Exception as exc:
                logger.warning("nextContentUrl parse failed: %s — %s", next_rule, exc)

    content = "\n".join(p for p in parts if p)
    content = apply_replace_rules(content, rule.replaceRegex)
    content = normalize_content_text(content)
    return content


# =============================================================================
# Explore / 分类浏览
# =============================================================================


def parse_explore_categories(explore_url: str) -> list[dict]:
    """解析 exploreUrl 为分类列表。

    兼容两种 Legado 格式：
      1. 换行分隔的 `name::url` 文本
      2. JSON 数组 [{title|name, url}, ...]
    含 @js: 的条目会被跳过。
    """
    if not explore_url:
        return []
    text = explore_url.strip()
    if text.startswith("["):
        try:
            arr = json.loads(text)
            out = []
            if isinstance(arr, list):
                for item in arr:
                    if not isinstance(item, dict):
                        continue
                    name = (item.get("title") or item.get("name") or "").strip()
                    url = (item.get("url") or "").strip()
                    if name and url and "@js:" not in url and "<js>" not in url:
                        out.append({"name": name, "url": url})
            return out
        except (ValueError, TypeError):
            pass
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "@js:" in line or "<js>" in line:
            continue
        parts = line.split("::", 1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            out.append({"name": parts[0].strip(), "url": parts[1].strip()})
    return out


def fetch_explore(source, url: str, session=None, max_pages: int = 50) -> list[dict[str, str]]:
    """从分类 URL 获取书籍列表，使用 ruleExplore（fallback 到 ruleSearch），支持 nextExploreUrl 分页。"""
    if session is None:
        session = build_source_session(source)
    variables = {"baseUrl": source.bookSourceUrl, "page": 1}

    # ruleExplore 作为列表规则，ruleSearch 作为字段规则 fallback
    explore_raw = getattr(source, "ruleExplore", {}) or {}
    search_raw = source.ruleSearch
    list_rule = (explore_raw.get("bookList") if isinstance(explore_raw, dict) else None) or search_raw.bookList
    next_rule = (explore_raw.get("nextExploreUrl") or "") if isinstance(explore_raw, dict) else ""
    item_rules = {}
    if isinstance(explore_raw, dict):
        for field in ("name", "author", "kind", "wordCount", "lastChapter", "intro", "coverUrl", "bookUrl"):
            rv = explore_raw.get(field) or getattr(search_raw, field, "")
            if rv:
                item_rules[field] = rv
    else:
        for field in ("name", "author", "kind", "wordCount", "lastChapter", "intro", "coverUrl", "bookUrl"):
            rv = getattr(search_raw, field, "")
            if rv:
                item_rules[field] = rv

    books = []
    seen_urls = set()
    queue = deque([_resolve_url(url, source.bookSourceUrl)])
    pages = 0
    while queue and pages < max_pages:
        target_url = queue.popleft()
        if not target_url or target_url in seen_urls:
            continue
        seen_urls.add(target_url)
        pages += 1
        try:
            html = fetch_url(target_url, session=session)
        except Exception as exc:
            logger.error("fetch_explore HTTP failed: %s — %s", target_url, exc)
            continue

        page_books = extract_list(list_rule, item_rules, html,
                                  base_url=source.bookSourceUrl, js_lib=source.jsLib,
                                  variables=variables)
        books.extend(page_books)

        if next_rule:
            try:
                from bs4 import BeautifulSoup as _BS
                soup = _BS(html, "html.parser")
                parsed = parse_selector(next_rule)
                if parsed["type"] == "css":
                    for tag in soup.select(parsed["selector"]):
                        val = _resolve_css_attr(tag, parsed.get("attr", "href"))
                        if val and val not in seen_urls:
                            queue.append(_resolve_url(val, target_url))
                elif parsed["type"] == "legado":
                    nodes, attr = legado_select(soup, next_rule)
                    for node in nodes:
                        val = _legado_extract_attr(node, attr or "href")
                        if val and val not in seen_urls:
                            queue.append(_resolve_url(val, target_url))
            except Exception as exc:
                logger.warning("nextExploreUrl parse failed: %s — %s", next_rule, exc)
    return books
