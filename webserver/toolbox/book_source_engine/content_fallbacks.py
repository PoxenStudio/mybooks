"""
content_fallbacks — 站点级内容获取回退处理器。

当 @js: 规则失败（含 java.ajax 等不受支持的操作）时，
自动按域名查找已注册的 Python 处理器，模拟 HTTP 请求链获取内容。

使用 @register(domain_pattern) 装饰器注册新处理器。
"""

import logging
import re
import time
import html as html_mod

import requests

try:
    from .rule_engine import build_source_session
except ImportError:  # standalone 运行（CLI / PyInstaller）
    try:
        from rule_engine import build_source_session
    except ImportError:
        build_source_session = None

logger = logging.getLogger(__name__)

# =============================================================================
# 处理器注册表
# =============================================================================

_fallback_registry: dict[re.Pattern, callable] = {}


def register(domain_pattern: str):
    """注册一个站点级内容获取处理器。

    Args:
        domain_pattern: 域名正则，如 r'deqixs\.com'

    处理器函数签名：
        (url: str, session: requests.Session) -> str | None
    """
    def wrapper(func):
        _fallback_registry[re.compile(domain_pattern, re.IGNORECASE)] = func
        logger.debug("已注册 content fallback: %s <- %s", domain_pattern, func.__name__)
        return func
    return wrapper


def find_handler(url: str):
    """根据 URL 查找匹配的处理器。"""
    for pattern, handler in _fallback_registry.items():
        if pattern.search(url):
            return handler
    return None


def fetch_content(url: str, session: requests.Session = None) -> str | None:
    """尝试通过 fallback 处理器获取内容。

    Args:
        url: 章节 URL
        session: 可复用的 requests.Session

    Returns:
        章节 HTML 文本，或 None
    """
    handler = find_handler(url)
    if handler is None:
        return None

    logger.info("使用 fallback 处理器获取: %s", url)
    if session is None:
        session = requests.Session()
    try:
        result = handler(url, session)
        if result:
            logger.info("Fallback 成功: %s (%d chars)", url, len(result))
        else:
            logger.warning("Fallback 返回空内容: %s", url)
        return result
    except Exception as exc:
        logger.error("Fallback 异常: %s — %s", url, exc, exc_info=True)
        return None


# =============================================================================
# 得奇小说 (deqixs.com / deqixs.cc) — JS 令牌链模拟
# =============================================================================

@register(r'deqixs\.(com|cc)')
def deqixs_fetch(url: str, session: requests.Session) -> str | None:
    """得奇小说内容获取。

    该站点在 `java.ajax()` 中执行 JS 令牌生成 + POST 请求。
    我们用 Python 模拟整个链：
      1. 访问首页获取 cookies
      2. GET chapter.js.php 获取签名令牌
      3. POST ajax2.php 获取正文内容
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.deqixs.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    session.headers.update(headers)

    # Step 1: 访问首页获取 cookies
    try:
        resp = session.get("https://www.deqixs.com/", timeout=15)
        resp.encoding = "utf-8"
    except requests.RequestException as exc:
        logger.warning("deqixs: 首页访问失败: %s", exc)
        return None

    # Step 2: GET chapter.js.php 获取令牌
    js_url = "https://www.deqixs.com/chapter/js_chapterjs_chapter.php"
    if "/book/" in url:
        # 从章节 URL 提取 book_id
        m = re.search(r'/book/(\d+)', url)
        if m:
            js_url = f"https://www.deqixs.com/chapter/{m.group(1)}/chapter.js.php"
    try:
        js_resp = session.get(js_url, timeout=15)
        js_resp.encoding = "utf-8"
    except requests.RequestException as exc:
        logger.warning("deqixs: JS 令牌获取失败: %s", exc)
        return None

    # 从 JS 响应中提取 chapter_id 和 sign
    js_text = js_resp.text
    cid_match = re.search(r'chapter_id\s*[:=]\s*["\']?(\d+)', js_text)
    sign_match = re.search(r'["\']sign["\']\s*[:=]\s*["\']([^"\']+)', js_text)
    if not cid_match or not sign_match:
        logger.warning("deqixs: 无法从 JS 响应中提取令牌: %s..%s",
                       js_text[:100], js_text[-100:])
        return None

    chapter_id = cid_match.group(1)
    sign = sign_match.group(1)
    logger.debug("deqixs: 令牌提取成功: chapter_id=%s, sign=%s", chapter_id, sign[:16])

    # Step 3: POST ajax2.php 获取正文
    ajax_url = "https://www.deqixs.com/php/ajax2.php"
    post_data = {
        "chapter_id": chapter_id,
        "sign": sign,
        "_": str(int(time.time() * 1000)),
    }
    ajax_headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": url,
        "Origin": "https://www.deqixs.com",
    }
    try:
        ajax_resp = session.post(ajax_url, data=post_data, headers=ajax_headers, timeout=15)
        ajax_resp.encoding = "utf-8"
    except requests.RequestException as exc:
        logger.warning("deqixs: AJAX 请求失败: %s", exc)
        return None

    # 解析响应
    data = ajax_resp.text.strip()
    if not data:
        logger.warning("deqixs: AJAX 响应为空")
        return None

    # 尝试 JSON 解析
    try:
        import json
        obj = json.loads(data)
        html_text = obj.get("html", obj.get("content", data))
    except (ValueError, TypeError):
        html_text = data

    # 清理 HTML
    # 移除 XML 声明（lxml HTML parser 无法处理 Unicode 字符串中的 XML 声明）
    html_text = re.sub(r'^<\?xml[^>]*\?>', '', html_text).strip()

    # 解码 HTML 实体
    html_text = html_mod.unescape(html_text)

    return html_text


def try_fetch_content(url: str, source=None) -> str | None:
    """兼容接口 — 从书源对象或 URL 获取 fallback 内容。

    由 rule_engine.fetch_content 在 @js: 规则失败时调用。
    """
    session = None
    if build_source_session is not None:
        try:
            session = build_source_session(source)
        except Exception:
            session = None
    if session is None:
        session = requests.Session()
    if source:
        headers = source.header if isinstance(source.header, dict) else {}
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/125.0.0.0 Safari/537.36",
            "Referer": source.bookSourceUrl,
        })
        if headers:
            session.headers.update(headers)
    return fetch_content(url, session)
