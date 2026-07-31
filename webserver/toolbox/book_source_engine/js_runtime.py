"""
js_runtime — 受限的书源 JS 运行时。

基于 dukpy (Duktape) 引擎，只支持简单字段后处理：
  - result.replace(...)
  - 用户自定义函数（通过 jsLib 字段注册）
  - String 操作

不支持 java.ajax / java.getString / <js> 块等外部副作用操作。
"""
import base64 as _b64
import hashlib as _hl
import json
import logging
import re
import threading
from collections import OrderedDict
from urllib.parse import urlparse

try:
    import dukpy
    _HAS_DUKPY = True
except Exception:  # pragma: no cover - dukpy 无对应平台 wheel 时降级
    dukpy = None
    _HAS_DUKPY = False

logger = logging.getLogger(__name__)

_interp_cache: "OrderedDict[str, dukpy.JSInterpreter]" = OrderedDict()
_interp_cache_lock = threading.Lock()
_INTERP_CACHE_MAX = 32
_MAX_JS_LEN = 50000

# 常见无界循环模式（无法被打断，直接拒绝执行）
_RE_UNBOUNDED_LOOP = re.compile(
    r"\bwhile\s*\(\s*(?:true|1|'1'|\"1\"|1\s*=\s*1)\s*\)"
    r"|\bfor\s*\(\s*;\s*;\s*\)"
    r"|\bwhile\s*\(\s*(?:true|1)\s*\)\s*\{\s*\}",
    re.IGNORECASE,
)


class JsRuleUnsupported(Exception):
    """JS 规则不受支持（含 java.ajax 等外部副作用）。"""


def _build_globals_code(variables: dict, result: str = "", base_url: str = "") -> str:
    lines = []
    lines.append(f'var result = {json.dumps(result, ensure_ascii=False)};')
    if base_url:
        lines.append(f'var baseUrl = {json.dumps(base_url, ensure_ascii=False)};')
    for k, v in variables.items():
        if k in ('result', 'baseUrl'):
            continue
        lines.append(f'var {k} = {json.dumps(v, ensure_ascii=False)};')
    origin = ""
    parsed = urlparse(base_url or "")
    if parsed.scheme and parsed.netloc:
        origin = f"{parsed.scheme}://{parsed.netloc}"
    lines.append(f'var __origin = {json.dumps(origin, ensure_ascii=False)};')
    lines.append(r"""
var __javaStore = {};
var java = {
    get: function(key) { return __javaStore[key] || ""; },
    put: function(key, value) { __javaStore[key] = String(value); return value; },
    md5Encode: function(str) {
        var hash = dukpy_md5(String(str));
        return hash;
    },
    base64Encode: function(str) {
        var b = dukpy_b64(String(str));
        return b;
    },
    log: function(msg) { dukpy_log(String(msg)); return ""; },
    longToast: function() { return ""; },
    t2s: function(value) { return value == null ? "" : String(value); },
    s2t: function(value) { return value == null ? "" : String(value); },
    encodeURI: function(value) { return encodeURIComponent(String(value)); },
    getString: function() { throw new Error("java.getString not supported"); },
    ajax: function() { throw new Error("java.ajax not supported"); },
    post: function() { throw new Error("java.post not supported"); },
};
var book = Object.freeze({
    origin: __origin,
    name: "",
    author: ""
});
""")
    return "\n".join(lines)

def _dukpy_md5(s):
    return _hl.md5(s.encode()).hexdigest()

def _dukpy_b64(s):
    return _b64.b64encode(s.encode()).decode()

def _dukpy_log(msg):
    logger.info("[JS] %s", msg)


def _get_interp(js_lib: str = "") -> dukpy.JSInterpreter:
    """按 jsLib 内容缓存解释器，LRU 上限 _INTERP_CACHE_MAX。"""
    if not _HAS_DUKPY:
        raise JsRuleUnsupported("dukpy 未安装，无法执行 JS 规则")
    cache_key = js_lib or "__default__"
    with _interp_cache_lock:
        interp = _interp_cache.get(cache_key)
        if interp is not None:
            _interp_cache.move_to_end(cache_key)
            return interp
    interp = dukpy.JSInterpreter()
    if js_lib:
        try:
            interp.evaljs(js_lib)
        except Exception as exc:
            logger.warning("jsLib 加载失败: %s", exc)
    with _interp_cache_lock:
        _interp_cache[cache_key] = interp
        while len(_interp_cache) > _INTERP_CACHE_MAX:
            _interp_cache.popitem(last=False)
    return interp


def _detect_unsafe_js(code: str) -> bool:
    low = code.lower()
    unsafe_markers = [
        "java.ajax", "java.post", "java.getstring",
        "java.startbrowserawait", "java.getstring",
    ]
    if any(m in low for m in unsafe_markers):
        return True
    if _RE_UNBOUNDED_LOOP.search(code):
        return True
    return False


def run_js(code: str, result: str = "", variables: dict = None,
           base_url: str = "", js_lib: str = "") -> str:
    """执行一条 @js: 规则代码。"""
    code = (code or "").strip()
    if not code:
        return result

    if len(code) > _MAX_JS_LEN:
        raise JsRuleUnsupported(f"JS rule too long ({len(code)} > {_MAX_JS_LEN})")

    if _detect_unsafe_js(code):
        raise JsRuleUnsupported(code)

    globals_code = _build_globals_code(variables or {}, result, base_url)
    full_js = f"{globals_code}\n{code}"

    interp = _get_interp(js_lib)

    # Register native callback functions
    try:
        interp.export_function("dukpy_md5", _dukpy_md5)
        interp.export_function("dukpy_b64", _dukpy_b64)
        interp.export_function("dukpy_log", _dukpy_log)
    except Exception:
        pass

    try:
        value = interp.evaljs(full_js)
        if value is None:
            return result
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)
    except Exception as exc:
        err_msg = str(exc)
        if "java." in err_msg:
            raise JsRuleUnsupported(code) from exc
        logger.warning("JS 执行失败: %s — %s", code[:60], err_msg)
        raise JsRuleUnsupported(code) from exc
