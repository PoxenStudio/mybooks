import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
from typing import Dict, Optional


class XHSDBookApi:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': 'https://search.xhsd.com/'
        })
        self.base_search_url = 'https://search.xhsd.com/search'
        self.base_detail_url = 'https://item.xhsd.com'

    def get_book_by_isbn(self, isbn: str) -> Optional[Dict]:
        """根据ISBN查询图书信息（主入口）"""
        detail_url = self._get_detail_url_by_isbn(isbn)
        if not detail_url:
            print(f"未找到ISBN {isbn} 对应的图书")
            return None
        return self._parse_detail_page(detail_url, isbn)

    def _get_detail_url_by_isbn(self, isbn: str) -> Optional[str]:
        """搜索ISBN并获取详情页URL（验证策略改为页面内13位数字匹配）"""
        try:
            params = {'keyword': isbn}
            resp = self.session.get(self.base_search_url, params=params, timeout=10)
            resp.encoding = 'utf-8'
            soup = BeautifulSoup(resp.text, 'html.parser')

            for item in soup.find_all('li', class_='product'):
                desc_p = item.find('p', class_='product-desc')
                if not desc_p:
                    continue
                a_tag = desc_p.find('a')
                if not a_tag or not a_tag.get('href'):
                    continue

                relative_url = a_tag['href']
                detail_url = 'https:' + relative_url if relative_url.startswith('//') else urljoin(self.base_detail_url, relative_url)

                if self._isbn_exists_in_page(detail_url, isbn):
                    print(f"找到匹配ISBN的图书，详情页: {detail_url}")
                    return detail_url
            return None
        except Exception as e:
            print(f"搜索页处理异常: {e}")
            return None

    def _isbn_exists_in_page(self, detail_url: str, target_isbn: str) -> bool:
        """直接检查详情页HTML中是否包含目标ISBN的13位数字"""
        try:
            resp = self.session.get(detail_url, timeout=10)
            resp.encoding = 'utf-8'
            # 清洗ISBN，去掉连字符
            clean_isbn = target_isbn.replace('-', '')
            # 在页面源码中搜索13位连续数字
            if re.search(clean_isbn, resp.text):
                return True
            return False
        except:
            return False

    def _parse_detail_page(self, detail_url: str, isbn: str) -> Optional[Dict]:
        """详情页解析器（基于DOM属性中的JSON数据）"""
        try:
            resp = self.session.get(detail_url, timeout=15)
            resp.encoding = 'utf-8'
            soup = BeautifulSoup(resp.text, 'html.parser')

            # ---------- 1. 基础信息 (Title, Cover, Author, Publisher) ----------
            # 数据隐藏在 <div class="item-title" data-item="..."> 中
            item_title_div = soup.find('div', class_='item-title')
            if not item_title_div:
                print("未找到包含元数据的 item-title 元素")
                return None

            import json
            data_item_str = item_title_div.get('data-item')
            if not data_item_str:
                print("data-item 属性为空")
                return None

            data = json.loads(data_item_str)
            title = data.get('name')
            cover = data.get('mainImage')
            if cover and cover.startswith('//'):
                cover = 'https:' + cover
            author = None
            publisher = None
            attr_groups = data.get('otherAttributes') or data.get('otherAttrs') or []

            for group in attr_groups:
                if group.get('group') == 'BASIC':
                    for attr in group.get('otherAttributes', []):
                        key = attr.get('attrKey')
                        val = attr.get('attrVal')
                        if key == '作者':
                            author = val
                        elif key == '出版社':
                            publisher = val

            # 如果没找到，尝试从 extra 字段提取
            if not author or not publisher:
                extra = data.get('extra', {})
                if not author:
                    author = extra.get('author')

            # ---------- 2. 内容简介 ----------
            # 数据隐藏在 <div class="spu-tab-item-detail" data-detail="..."> 中
            introduction = ""
            spu_detail_div = soup.find('div', class_='spu-tab-item-detail')
            if spu_detail_div:
                data_detail_str = spu_detail_div.get('data-detail')
                if data_detail_str:
                    details = json.loads(data_detail_str)
                    for item in details:
                        if '内容' in item.get('title', ''):  # 匹配 "内容推荐", "内容简介"
                            html_content = item.get('content', '')
                            # 简单的去标签处理
                            intro_soup = BeautifulSoup(html_content, 'html.parser')
                            introduction = intro_soup.get_text(separator='\n', strip=True)

                            # 清理数据：去除首尾引号、空白、以及“【内容简介】：”前缀
                            introduction = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', introduction)
                            introduction = introduction.strip().strip('"').strip()
                            introduction = re.sub(r'^【内容简介】[：:]\s*', '', introduction)
                            introduction = introduction.strip()
                            break

            return {
                'cover': cover,
                'title': title,
                'publisher': publisher,
                'author': author,
                'introduction': introduction,
                'isbn': isbn
            }

        except Exception as e:
            print(f"详情页解析异常: {e}")
            import traceback
            traceback.print_exc()
            return None


# ============= 测试执行 =============
if __name__ == '__main__':
    test_isbn = '9787532763184'
    api = XHSDBookApi()
    book = api.get_book_by_isbn(test_isbn)

    if book:
        print("\n 图书信息查询成功 ==========")
        print(f"封面图片: {book['cover']}")
        print(f"书名: {book['title']}")
        print(f"出版社: {book['publisher']}")
        print(f"作者: {book['author']}")
        print(f"ISBN: {book['isbn']}")
        print(f"内容简介:\n{book['introduction']}")
        print("==============================\n")
    else:
        print(" 未查询到图书信息")
