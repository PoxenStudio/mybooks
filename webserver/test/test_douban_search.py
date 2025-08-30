#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
简单的图书信息请求程序
参考 douban.py 的 get_book_by_isbn 方法实现
"""

import json
import logging
import requests
import sys

# 常量定义
API_KEY = "054022eaeae0b00e0fc068c0c0a2102a"
BASE_URL = "http://127.0.0.1:8085"

# Chrome浏览器头部信息
CHROME_HEADERS = {
    "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko)"
    + "Chrome/66.0.3359.139 Safari/537.36",
}


class DoubanApi:
    """简单的图书API类"""

    def __init__(self, apikey=API_KEY, base_url=BASE_URL):
        self.apikey = apikey
        self.base_url = base_url

    def request(self, url, params=None):
        """发送HTTP请求"""
        if params is None:
            params = {}

        if self.apikey:
            params["apikey"] = self.apikey

        try:
            response = requests.get(url, timeout=10, headers=CHROME_HEADERS, params=params)
        except Exception as e:
            logging.error("请求异常: %s", str(e))
            return None

        if response.status_code != 200:
            logging.error("HTTP状态码异常: %s", response.status_code)
            return None

        try:
            data = response.json()
        except json.JSONDecodeError:
            logging.error("JSON解码失败，响应内容: %s", response.content)
            return None

        if "code" in data and data["code"] != 0:
            logging.error("API返回错误: code=%d, msg=%s", data["code"], data.get("msg", ""))
            return None
        logging.info("API请求成功: %s, result: %s", url, data)
        return data

    def get_book_by_isbn(self, isbn):
        """根据ISBN获取图书信息"""
        if not isbn:
            logging.error("ISBN不能为空")
            return None

        url = f"{self.base_url}/v2/book/isbn/{isbn}"
        return self.request(url)

    def get_book_by_id(self, book_id):
        """根据图书ID获取图书信息"""
        if not book_id:
            logging.error("图书ID不能为空")
            return None

        url = f"{self.base_url}/v2/book/id/{book_id}"
        return self.request(url)

    def search_books(self, title, author=None, count=5):
        """搜索图书"""
        if not title:
            logging.error("标题不能为空")
            return None

        url = f"{self.base_url}/v2/book/search"
        query = f"{title} {author}" if author else title
        params = {
            "q": query.encode("UTF-8"),
            "count": count
        }

        result = self.request(url, params)
        return result.get("books", []) if result else []


def print_book_info(book_data):
    """格式化打印图书信息"""
    if not book_data:
        print("未找到图书信息")
        return

    print("=" * 50)
    print(f"标题: {book_data.get('title', 'N/A')}")
    print(f"副标题: {book_data.get('subtitle', 'N/A')}")
    print(f"作者: {', '.join(book_data.get('author', []))}")
    print(f"译者: {', '.join(book_data.get('translators', []))}")
    print(f"出版社: {book_data.get('publisher', 'N/A')}")
    print(f"出版日期: {book_data.get('pubdate', 'N/A')}")
    print(f"ISBN13: {book_data.get('isbn13', 'N/A')}")
    print(f"页数: {book_data.get('pages', 'N/A')}")
    print(f"价格: {book_data.get('price', 'N/A')}")
    print(f"评分: {book_data.get('rating', {}).get('average', 'N/A')}")
    print(f"简介: {book_data.get('summary', 'N/A')[:200]}...")
    print(f"豆瓣ID: {book_data.get('id', 'N/A')}")
    print("=" * 50)


def main():
    """主函数"""
    # 设置日志级别
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # 创建API实例
    api = DoubanApi()

    # 命令行参数处理
    if len(sys.argv) < 3:
        print("使用方法:")
        print(f"  {sys.argv[0]} isbn <ISBN号, 如9787532641420>")
        print(f"  {sys.argv[0]} id <图书ID>")
        print(f"  {sys.argv[0]} search <标题> [作者]")
        print("\n示例:")
        print(f"  {sys.argv[0]} isbn 9787570220601")
        print(f"  {sys.argv[0]} id 35737227")
        print(f"  {sys.argv[0]} search 动物志")
        print(f"  {sys.argv[0]} search 动物志 马修·卡拉柯")
        return

    command = sys.argv[1].lower()

    if command == "isbn":
        isbn = sys.argv[2]
        print(f"正在查询ISBN: {isbn}")
        book = api.get_book_by_isbn(isbn)
        print_book_info(book)

    elif command == "id":
        book_id = sys.argv[2]
        print(f"正在查询图书ID: {book_id}")
        book = api.get_book_by_id(book_id)
        print_book_info(book)

    elif command == "search":
        title = sys.argv[2]
        author = sys.argv[3] if len(sys.argv) > 3 else None
        print(f"正在搜索: 标题={title}, 作者={author}")
        books = api.search_books(title, author)

        if books:
            print(f"找到 {len(books)} 本图书:")
            for i, book in enumerate(books, 1):
                print(f"\n--- 第 {i} 本 ---")
                print_book_info(book)
        else:
            print("未找到相关图书")

    else:
        print(f"未知命令: {command}")
        print("支持的命令: isbn, id, search")


if __name__ == "__main__":
    main()
