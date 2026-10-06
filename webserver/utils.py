#!/usr/bin/env python3
import asyncio
import contextvars
import datetime
import functools
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from webserver import constants, loader

# 联网任务线程池：信息源插件搜索、AI 请求等长任务（单次可达分钟级）放这里执行。
# tornado 是单线程事件循环，在 handler 里同步等一次网络请求会把全站请求（包括不碰
# 数据库的 /api/user/info）一起冻住。
blocking_pool = ThreadPoolExecutor(max_workers=int(loader.get_settings().get("BLOCKING_POOL_SIZE", 20)), thread_name_prefix="mybooks-blocking")

# calibre 查询专用池：与联网长任务隔离。若混用一池，20 个并发联网搜索打满时，
# 阅读链路的毫秒级 calibre 查询（get_book_async）要排在网络任务后面，最坏等分钟级。
calibre_pool = ThreadPoolExecutor(max_workers=int(loader.get_settings().get("CALIBRE_POOL_SIZE", 4)), thread_name_prefix="mybooks-calibre")


def bind_threadpool_call(func, *args, **kwargs):
    """把「提交时刻的 contextvars 快照」绑定到调用上，返回可直接交给 run_in_executor 的
    无参 callable。

    ``loop.run_in_executor()`` **不会**把 contextvars 带进工作线程。mybooks 里依赖它的有
    ``webserver/i18n.py`` 的 ``_current_language``（请求语言）：不带过去的话，线程池里调
    ``_()`` 会退回 ``DEFAULT_LANGUAGE``，返回给客户端的消息就变成另一种语言（站点语言设为
    en 而系统默认 zh 时尤其明显）。每个调用都取一份新快照，用完即弃，不会污染池线程。
    """
    ctx = contextvars.copy_context()
    call = functools.partial(func, *args, **kwargs)
    return lambda: ctx.run(call)


async def run_in_threadpool(func, *args, **kwargs):
    """把联网等长阻塞任务丢到 blocking_pool 执行并返回结果。

    calibre 数据库调用走 BaseHandler.run_calibre_async（calibre_pool），不与本池混跑。
    注意：工作线程里绝不能触碰 handler 的 sqlite_session——SQLAlchemy scoped_session
    是线程本地的，mybooks 自身的 sqlite 查询必须留在 ioloop 线程；本池里的 calibre
    调用不持 db_lock，正确性由 calibre Cache 自带的读写锁保证。
    请求上下文（contextvars，含 i18n 请求语言）由 bind_threadpool_call 显式带进线程。
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        blocking_pool, bind_threadpool_call(func, *args, **kwargs)
    )


# 匹配包含z-library的括号内容，例如 (z-library.sk, 1lib.sk, z-lib.sk)
ZLIBRARY_PATTERN = re.compile(r'\([^)]*?(?:z-?lib(?:rary)?|1lib)[^)]*?\)', re.IGNORECASE)

# 日文假名 Unicode 区间：平假名 U+3040-309F，片假名 U+30A0-30FF
_KANA_PATTERN = re.compile(r'[぀-ヿ]')

# CJK 汉字区间：基本区 U+4E00-9FFF，扩展 A 区 U+3400-4DBF
_HAN_PATTERN = re.compile(r'[一-鿿㐀-䶿]')


def parse_date(date_str):
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y年%m月%d日", "%Y年%m月", "%Y年", "%Y"):
        try:
            return datetime.datetime.strptime(date_str, fmt).replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    return None


def meta_writable_formats():
    """可回写元数据的格式；DJVU 依赖 djvu_meta 插件，未加载时自动排除。"""
    from calibre.customize.ui import can_set_metadata

    return [f for f in constants.META_WRITABLE_FORMATS if can_set_metadata(f)]


def remove_zlibrary_suffix(text):
    """移除文件名中包含z-library的括号内容"""
    if not text:
        return text
    return ZLIBRARY_PATTERN.sub('', text).strip()


def guess_title_author_from_filename(name):
    if not name:
        return name, None
    title = name.strip()
    author = None
    if "作者" in title:
        parts = re.split(r"作者[:：]", title, maxsplit=1)
        if len(parts) >= 2:
            title = parts[0].strip()
            author = parts[1].strip()
            # 去除title尾部的([（，【四种符号，author尾部的）】]四种符号
            title = re.sub(r'[\s\(\[【（，,、]+$', '', title)
            if title.startswith('《') and title.endswith('》'):
                title = title[1:-1]
            author = re.sub(r'[\s\)\]】）]+$', '', author)
    return title, author


def ascii_text(orig):
    from calibre.utils.localization import get_udc
    from calibre.constants import preferred_encoding
    udc = get_udc()
    try:
        ascii = udc.decode(orig)
    except Exception:
        if isinstance(orig, str):
            orig = orig.encode('ascii', 'replace')
        ascii = orig.decode(preferred_encoding, 'replace')
    if isinstance(ascii, bytes):
        ascii = ascii.decode('ascii', 'replace')
    return ascii.strip()


def get_title_sort(title):
    if not title:
        return title
    try:
        return ascii_text(title).lower()
    except Exception as e:
        logging.error(f"Error converting title to ASCII for sorting: {e}")
        return title


# 常见繁体中文专有字符（在 Simplified 中对应不同字形），用于 fallback 检测
_TRADITIONAL_ONLY_CHARS = frozenset(
    "書電來說話這個時會對學問國務現實際應當來們點進開關處還"
    "歡樂體動設計資訊傳說標準環境網絡變換預算發展運動認識"
    "義務條件結構機制選擇統計監督繼續識別溝通維護數據處理"
    "歷史文化藝術哲學經濟組織機構協議協作協調決策執行方針"
    "與並從內外長短廣狹強弱快慢遠近輕重高低深淺寬窄早晚"
    "後前左右東西南北上下中外新舊多少大小"
    # 常見繁體字
    "與與來來說說國國時時個個會對對學問問處還還變發電書樂"
)


@functools.lru_cache(maxsize=8)
def get_opencc(profile):
    import opencc
    return opencc.OpenCC(profile)


def _fallback_has_traditional(text: str) -> bool:
    return any(c in _TRADITIONAL_ONLY_CHARS for c in text)


def is_traditional_chinese(text: str) -> bool:
    if not text:
        return False
    # 若全为 ASCII，直接跳过
    if all(ord(c) < 128 for c in text):
        return False

    try:
        converted = get_opencc("t2s").convert(text)
        return converted != text
    except Exception as exc:
        logging.debug("[review_cht] OpenCC unavailable (%s), using fallback", exc)
        return _fallback_has_traditional(text)


def detect_title_language(text: str) -> Optional[str]:
    """检测书名文本对应的语言代码（简体中文/繁体中文/日文）。

    判定顺序：繁体中文 > 简体中文 > 日文 > 简繁同形兜底。中文的判定优先于
    日文，是因为日文汉字与繁/简体中文汉字大量重叠，若假名检测放在最前，
    会让本应识别为中文的书名（尤其是含少量假名标点的情况）被误判，因此
    仅在确认不含中文特征后才回退到假名检测。

    若标题中的汉字在简繁转换前后完全一致（即该标题不含任何简繁差异字，
    如"九命"），繁简双向转换都无法区分，此时只要标题含汉字且不含假名，
    按约定优先判定为简体中文，而非放弃判定。

    :param text: 书名文本。
    :return: `constants.TRADITIONAL_CHINESE_CODE` / `constants.DEFAULT_LANGUAGE_CODE`
             / `constants.JAPANESE_CODE`，无法判定时返回 None。
    """
    if not text:
        return None
    if all(ord(c) < 128 for c in text):
        return None

    if is_traditional_chinese(text):
        return constants.TRADITIONAL_CHINESE_CODE

    try:
        if get_opencc("s2t").convert(text) != text:
            return constants.DEFAULT_LANGUAGE_CODE
    except Exception as exc:
        logging.debug("[detect_title_language] OpenCC unavailable (%s), skip simplified check", exc)

    if _KANA_PATTERN.search(text):
        return constants.JAPANESE_CODE

    if _HAN_PATTERN.search(text):
        return constants.DEFAULT_LANGUAGE_CODE

    return None


def compare_books_by_rating_or_id(x, y):
    a = x.get("rating", 0) or 0
    b = y.get("rating", 0) or 0

    if a != b:
        return 1 if a > b else -1
    return 1 if x["id"] > y["id"] else -1


def compare_books_by_series_index_or_name(x, y):
    x_index = x.get("series_index", 0) or 0
    y_index = y.get("series_index", 0) or 0

    if x_index != y_index:
        return 1 if x_index > y_index else -1

    x_title_sort = x.get("sort", "") or ""
    y_title_sort = y.get("sort", "") or ""
    result = 1 if x_title_sort > y_title_sort else -1
    return result


def super_strip(s):
    return ''.join(c for c in s.strip() if c.isprintable())


# 为保持向后兼容，从新位置重新导出
from webserver.base.formatter import SimpleBookFormatter, MCPBookFormatter, BookFormatter, ReadingStateFormatter

__all__ = ["SimpleBookFormatter", "MCPBookFormatter", "BookFormatter", "ReadingStateFormatter"]


if __name__ == "__main__":
    # 测试_guess_title_author_from_filename
    test_cases = [
        "《宝鉴》（校对版全本）作者：打眼",
        "《三体》作者：刘慈欣",
        "《平凡的世界（》作者：路遥",
        "《无人生还》(作者：阿加莎·克里斯蒂)",
        "《通天之路》（校对版全本）作者：无罪"
    ]
    for filename in test_cases:
        title, author = guess_title_author_from_filename(filename)
        print(f"Filename: {filename}\n  Title: {title}\n  Author: {author}\n")
