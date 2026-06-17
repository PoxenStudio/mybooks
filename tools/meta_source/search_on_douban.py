# 豆瓣书籍搜索与封面下载
#
# 搜索：
#   GET https://search.douban.com/book/subject_search?search_text=...&cat=1001
#   结果藏在页面 window.__DATA__（大写）的 JSON 中，items 数组含 title / abstract /
#   cover_url / url / rating 等字段，tpl_name != "search_subject" 的条目需过滤。
#
# 封面下载反爬处理：
#   豆瓣 CDN（img*.doubanio.com）对疑似爬虫请求返回 text/html JS 挑战页而非图片。
#   挑战页会通过 JS 计算并写入 __tst_status / EO_Bot_Ssid 两个 cookie 后重定向。
#   JS 中的数值均为硬编码，规律：__tst_status = WTKkN + bOYDu + wyeCN（三个常量求和）。
#   解决方案：收到 text/html 响应时用正则提取上述常量、计算 cookie 值，携带 cookie 重试即可。
#
# 请求头要点：
#   - Referer 封面请求须指向搜索页 URL（非书籍详情页），与浏览器行为一致。
#   - 需带齐 Sec-Fetch-* / Sec-Ch-Ua 等导航类请求头，缺少时更易触发反爬。
#   - User-Agent 使用 macOS Chrome（与 Windows UA 相比触发率更低）。

import json
import os
import re
import urllib.parse
import requests


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"

SEARCH_HEADERS = {
    "User-Agent": UA,
    "Referer": "https://book.douban.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 封面下载只需 UA + Referer（Referer 在调用时动态传入）
COVER_HEADERS = {"User-Agent": UA}


def _parse_js_challenge_cookies(html: str) -> dict:
    """从豆瓣 CDN 的 JS 反爬挑战页中提取所需 cookie。"""
    cookies = {}
    m_wt = re.search(r'WTKkN\s*:\s*(\d+)', html)
    m_bo = re.search(r'bOYDu\s*:\s*(\d+)', html)
    m_wy = re.search(r'wyeCN\s*:\s*(\d+)', html)
    if m_wt and m_bo and m_wy:
        cookies["__tst_status"] = str(int(m_wt.group(1)) + int(m_bo.group(1)) + int(m_wy.group(1)))
    m_eo = re.search(r'iTyzs\s*\([^,]+,\s*(\d+)\)', html)
    if m_eo:
        cookies["EO_Bot_Ssid"] = m_eo.group(1)
    return cookies


def download_cover(cover_url: str, search_url: str, out_dir: str = "out") -> str | None:
    """下载封面图片到 out_dir，返回保存路径，失败返回 None。"""
    os.makedirs(out_dir, exist_ok=True)
    cover_url = cover_url.replace("/m/", "/l/")  # 获取大图
    filename = cover_url.split("/")[-1]
    save_path = os.path.join(out_dir, filename)
    headers = {**COVER_HEADERS, "Referer": search_url}
    try:
        session = requests.Session()
        resp = session.get(cover_url, headers=headers, timeout=10)
        resp.raise_for_status()
        # CDN 返回 JS 反爬挑战时，解析 cookie 后重试
        if "text/html" in resp.headers.get("Content-Type", ""):
            cookies = _parse_js_challenge_cookies(resp.text)
            if cookies:
                resp = session.get(cover_url, headers=headers, cookies=cookies, timeout=10)
                resp.raise_for_status()
        if "image" not in resp.headers.get("Content-Type", ""):
            print(f"    封面下载失败: 响应非图片 ({resp.headers.get('Content-Type')})")
            return None
        with open(save_path, "wb") as f:
            f.write(resp.content)
        return save_path
    except requests.exceptions.RequestException as e:
        print(f"    封面下载失败: {e}")
        return None


def search_douban_books(book_name):
    # 1. URL 编码处理
    encoded_name = urllib.parse.quote(book_name)
    url = f"https://search.douban.com/book/subject_search?search_text={encoded_name}&cat=1001"

    try:
        # 2. 发送请求
        response = requests.get(url, headers=SEARCH_HEADERS, timeout=10)
        response.raise_for_status()
        html_content = response.text

        # 3. 使用正则表达式匹配 window.__DATA__ 的内容
        pattern = r"window\.__DATA__\s*=\s*({.*?});"
        match = re.search(pattern, html_content, re.DOTALL)

        if not match:
            print("未能匹配到书籍数据，可能是页面结构改变或被反爬。")
            with open("douban_search_debug.html", "w", encoding="utf-8") as f:
                f.write(html_content)
            return None

        # 4. 解析 JSON 数据
        json_str = match.group(1)
        data = json.loads(json_str)

        # 5. 提取并打印结果
        items = data.get("items", [])
        print(f"搜索词: {book_name}，共找到 {len(items)} 条结果：\n")

        cnt = 0
        for index, item in enumerate(items, 1):
            # 过滤掉非书籍类型的条目（如广告或特殊标签）
            if item.get("tpl_name") != "search_subject":
                continue
            cnt += 1
            if cnt > 3:
                break
            title = item.get("title")
            abstract = item.get("abstract", "")
            book_url = item.get("url")
            cover_url = item.get("cover_url", "")
            rating_info = item.get("rating", {})
            rating_val = rating_info.get("value", "暂无")
            rating_count = rating_info.get("count", 0)

            parts = [p.strip() for p in abstract.split(" / ")]
            author = parts[0] if len(parts) > 0 else ""
            publisher = parts[-3] if len(parts) > 1 else ""
            pub_date = parts[-2] if len(parts) > 2 else ""
            price = parts[-1] if len(parts) > 3 else ""

            print(f"[{index}] 书名: {title}")
            print(f"    作者: {author}")
            print(f"    出版社: {publisher}  出版日期: {pub_date}  定价: {price}")
            print(f"    评分: {rating_val} ({rating_count}人评价)")
            print(f"    链接: {book_url}")
            print(f"    封面: {cover_url}")
            if cover_url:
                saved = download_cover(cover_url, url)
                print(f"    封面: {saved or '下载失败'}")
            print("-" * 50)
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
    except json.JSONDecodeError:
        print("JSON 解析失败")


if __name__ == "__main__":
    # 测试搜索
    search_douban_books("亂馬1/2典藏版 6")
