# NeoDB 书籍搜索
#
# 搜索：
#   GET https://neodb.social/search?q=<book title>&c=book
#   响应页面中 class 为 item-card 的 article 元素代表一个结果，
#   包含评分、作者、出版社、出版年份、简介和封面路径。
#
# 请求头要点：
#   - 使用标准浏览器 User-Agent，NeoDB 无严格反爬机制
#   - 封面为相对路径（/m/...），需拼接 https://neodb.social 前缀

import os
import urllib.parse
import requests
from bs4 import BeautifulSoup


BASE_URL = "https://neodb.social"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"

HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def download_cover(cover_url: str, out_dir: str = "out") -> str | None:
    """下载封面图片到 out_dir，返回保存路径，失败返回 None。"""
    os.makedirs(out_dir, exist_ok=True)
    filename = cover_url.rstrip("/").split("/")[-1]
    save_path = os.path.join(out_dir, filename)
    try:
        resp = requests.get(cover_url, headers=HEADERS, timeout=10)
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


def _parse_item_card(article) -> dict:
    """从 item-card article 元素中提取书籍信息。"""
    result = {}

    # 封面
    cover_img = article.select_one("div.cover img")
    cover_path = cover_img["src"] if cover_img else ""
    result["cover_path"] = cover_path
    result["cover_url"] = BASE_URL + cover_path if cover_path.startswith("/") else cover_path

    # 书名与条目链接
    title_link = article.select_one("hgroup h5 a")
    if title_link:
        result["title"] = title_link.get_text(strip=True)
        href = title_link.get("href", "")
        result["url"] = BASE_URL + href if href.startswith("/") else href
    else:
        result["title"] = ""
        result["url"] = ""

    # 评分：span.solo-hidden 格式如 "8.6 (236 个评分)"
    rating_span = article.select_one("div.multi-fields span.solo-hidden")
    result["rating"] = rating_span.get_text(separator=" ", strip=True) if rating_span else ""

    # 作者、出版社、出版年份均在 div.multi-fields 的直接子 span 中
    multi_fields = article.select_one("div.multi-fields")
    result["author"] = ""
    result["publisher"] = ""
    result["pub_year"] = ""

    if multi_fields:
        for span in multi_fields.find_all("span", recursive=False):
            if "solo-hidden" in span.get("class", []):
                continue  # 跳过评分 span
            text = span.get_text(separator=" ", strip=True)
            if "作者:" in text or "作者：" in text:
                inner = span.find("span") or span.find("a")
                result["author"] = inner.get_text(strip=True) if inner else text.split(":", 1)[-1].strip()
            elif "publishing house:" in text:
                inner = span.find("span")
                result["publisher"] = inner.get_text(strip=True) if inner else text.split(":", 1)[-1].strip()
            else:
                # 年份 span：纯文本，格式如 "1997" 或 "2012 - 9"
                first_token = text.split()[0] if text else ""
                if first_token.isdigit() and len(first_token) == 4:
                    result["pub_year"] = first_token

    # 简介
    desc_div = article.select_one("div.full div")
    result["description"] = desc_div.get_text(separator=" ", strip=True) if desc_div else ""

    return result


def search_neodb_books(book_name: str):
    encoded_name = urllib.parse.quote(book_name)
    url = f"{BASE_URL}/search?q={encoded_name}&c=book"

    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return

    soup = BeautifulSoup(response.text, "html.parser")
    article = soup.select_one("article.item-card")
    if not article:
        print("未找到结果")
        return

    info = _parse_item_card(article)
    print(f"搜索词: {book_name}\n")
    print(f"书名: {info['title']}")
    print(f"作者: {info['author']}")
    print(f"出版社: {info['publisher']}  出版年份: {info['pub_year']}")
    print(f"评分: {info['rating']}")
    print(f"链接: {info['url']}")
    print(f"封面路径: {info['cover_path']}")
    if info["description"]:
        desc = info["description"][:120] + "…" if len(info["description"]) > 120 else info["description"]
        print(f"简介: {desc}")
    if info["cover_url"]:
        saved = download_cover(info["cover_url"])
        print(f"封面已保存: {saved or '下载失败'}")


if __name__ == "__main__":
    search_neodb_books("白鹿原")
