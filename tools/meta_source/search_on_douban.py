import json
import re
import urllib.parse
import requests


def search_douban_books(book_name):
    # 1. URL 编码处理
    encoded_name = urllib.parse.quote(book_name)
    url = f"https://search.douban.com/book/subject_search?search_text={encoded_name}&cat=1001"

    # 2. 定义请求头 (Windows Chrome UA 和 Referer)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://book.douban.com/",
    }

    try:
        # 3. 发送请求
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        html_content = response.text

        # 4. 使用正则表达式匹配 window.__data__ 的内容
        # 匹配 window.__data__ = 到下一个分号或闭合标签前的内容
        pattern = r"window\.__data__\s*=\s*({.*?});"
        match = re.search(pattern, html_content, re.DOTALL)

        if not match:
            print("未能匹配到书籍数据，可能是页面结构改变或被反爬。")
            return None

        # 5. 解析 JSON 数据
        json_str = match.group(1)
        data = json.loads(json_str)

        # 6. 提取并打印结果
        items = data.get("items", [])
        print(f"搜索词: {book_name}，共找到 {len(items)} 条结果：\n")

        for index, item in enumerate(items, 1):
            # 过滤掉非书籍类型的条目（如广告或特殊标签）
            if item.get("tpl_name") != "search_subject":
                continue

            title = item.get("title")
            abstract = item.get("abstract")
            book_url = item.get("url")
            rating_info = item.get("rating", {})
            rating_val = rating_info.get("value", "暂无")
            rating_count = rating_info.get("count", 0)

            print(f"[{index}] 书名: {title}")
            print(f"    基本信息: {abstract}")
            print(f"    评分: {rating_val} ({rating_count}人评价)")
            print(f"    链接: {book_url}")
            print("-" * 50)

    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
    except json.JSONDecodeError:
        print("JSON 解析失败")


if __name__ == "__main__":
    # 测试搜索
    search_douban_books("双天至尊")
