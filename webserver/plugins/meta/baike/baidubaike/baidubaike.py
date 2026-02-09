#!/usr/bin/python
# -*- coding: UTF-8 -*-

import re
import logging
import requests
from bs4 import BeautifulSoup
from collections import OrderedDict

from webserver.constants import CHROME_MOBILE_HEADERS
from .baiduexception import PageError, DisambiguationError, VerifyError


CLASS_DISAMBIGUATION = ["nslog:519"]
CLASS_CREATOR = ["nslog:1022"]
CLASS_TAG = []
CLASS_CONTENT = {
    "lemmaTitleH1": "===== %(text)s ====\n\n",
    "headline-1": "\n== %(text)s ==\n",
    "headline-2": "\n* %(text)s *\n",
    "para": "%(text)s",
}
CLASS_SUMMARY = ["J-summary"]
CLASS_INFO = ["basicInfo"]
CLASS_SUMMARY_PIC = ["summary-img"]


class Page(object):
    def __init__(self, book_name, encoding="utf-8"):
        url = "https://baike.baidu.com/search/word"
        payload = None
        self.valid = False  # 标记请求是否成功

        # An url or a word to be Paged
        pattern = re.compile(r"^https?:\/\/baike\.baidu\.com\/.*", re.IGNORECASE)
        if re.match(pattern, book_name):
            url = book_name
        else:
            payload = {"pic": 1, "enc": encoding, "word": book_name}

        self.http = requests.get(url, timeout=10, headers=CHROME_MOBILE_HEADERS, params=payload)
        logging.debug(f"Fetching URL: {self.http.url}, Status: {self.http.status_code}")

        # 检查HTTP响应状态码
        if self.http.status_code != 200:
            logging.warning(f"HTTP request failed with status code: {self.http.status_code}")
            return

        # 检查响应URL是否包含/item/，如果不包含则尝试直接访问/item/路径
        if "/item/" not in self.http.url:
            logging.debug(f"No /item/ in URL, trying direct item URL")
            direct_url = f"https://baike.baidu.com/item/{book_name}"
            self.http = requests.get(direct_url, timeout=10, headers=CHROME_MOBILE_HEADERS)
            logging.debug(f"Fetching direct URL: {self.http.url}, Status: {self.http.status_code}")

            # 再次检查HTTP响应状态码
            if self.http.status_code != 200:
                logging.warning(f"Direct HTTP request failed with status code: {self.http.status_code}")
                return

        self.html = self.http.text
        self.soup = BeautifulSoup(self.html, "lxml")

        # Exceptions
        if self.soup.find(class_=CLASS_DISAMBIGUATION):
            raise DisambiguationError(book_name, self.get_inurls())
        if u"百度百科尚未收录词条" in self.html:
            raise PageError(book_name)
        if self.soup.find(id="vf"):
            raise VerifyError(book_name)

        self.valid = True  # 标记为成功

    def parse_basic_info(self):
        """Get basic info of a page"""
        if not self.valid:
            return {}
        divs = self.soup.find_all(class_=CLASS_INFO)
        info = {}
        for div in divs:
            # Find all list items containing info-title and info-content pairs
            list_items = div.find_all("li")
            for item in list_items:
                title_div = item.find(class_="info-title")
                content_div = item.find(class_="info-content")
                if title_div and content_div:
                    name = title_div.get_text(strip=True).replace(u"\xa0", "")
                    value = content_div.get_text(strip=True).replace(u"\xa0", "")
                    info[name] = value
        return info

    def get_info(self):
        """Get informations of the page"""
        if not self.valid:
            return {}

        info = self.parse_basic_info()
        title = self.soup.title.get_text()
        info["title"] = title[: title.rfind("_")]
        info["url"] = self.http.url

        try:
            info["page_view"] = self.soup.find(id="viewPV").get_text()
            info["last_modify_time"] = self.soup.find(id="lastModifyTime").get_text()
            info["creator"] = self.soup.find(class_=CLASS_CREATOR).get_text()
        finally:
            return info

    def get_image(self):
        if not self.valid:
            return ""
        url = ""
        divs = self.soup.find_all(class_=CLASS_SUMMARY_PIC)
        for div in divs:
            url = div.attrs.get("data-src", "")
            if not url:
                continue
            break
        return url

    def get_summary(self):
        """Get summary infomation of a page"""
        if not self.valid:
            return ""
        divs = self.soup.find_all(class_=CLASS_SUMMARY)
        summary_parts = []
        for div in divs:
            # Remove citation markers (sup tags) before extracting text
            for sup in div.find_all("sup"):
                sup.decompose()
            text = div.get_text(strip=True)
            if text:
                summary_parts.append(text)
        return "\n".join(summary_parts)

    def get_inurls(self):
        """Get links inside a page"""
        if not self.valid:
            return OrderedDict()
        inurls = OrderedDict()
        href = self.soup.find_all(href=re.compile(r"\/(sub)?view(\/[0-9]*)+.htm"))

        for url in href:
            inurls[url.get_text()] = "https://baike.baidu.com%s" % url.get("href")

        return inurls

    def get_tags(self):
        """Get tags of the page"""
        if not self.valid or len(CLASS_TAG) == 0:
            return []
        tags = []
        for tag in self.soup.find_all(class_=CLASS_TAG):
            tags.append(tag.get_text(strip=True))

        return tags

    def get_id(self):
        """Get unique identifier from URL"""
        if not self.valid:
            return ""
        # Extract item name from URL like https://baike.baidu.com/item/词条名
        url = self.http.url
        match = re.search(r'/item/([^/?]+)', url)
        if match:
            return match.group(1)
        return url


class Search(object):
    def __init__(self, word, results_n=10, page_n=1):
        # Generate searching URL
        url = "https://baike.baidu.com/search"
        pn = (page_n - 1) * results_n
        payload = {
            "type": 0,
            "submit": "search",
            "pn": pn,
            "rn": results_n,
            "word": word,
        }

        self.http = requests.get(url, timeout=10, headers=CHROME_HEADERS, params=payload)
        self.html = self.http.content
        self.soup = BeautifulSoup(self.html)

    def get_results(self):
        """Get searching results"""

        search_results = []
        items = self.soup.find_all(class_="f")  # get results items

        for item in items:
            result = {}
            a = item.find("a")
            title = a.get_text()  # get result title
            title = title[: title.rfind("_")]
            result["title"] = title
            result["url"] = a.get("href")  # get result links
            # get result discription
            result["discription"] = item.find(class_="abstract").get_text().strip()
            search_results.append(result)

        return search_results
