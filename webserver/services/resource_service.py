#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
(PoxenStudio)资源服务，负责下载和管理好友链接及资源链接的 favicon
"""
import logging
import requests
import os
import time
from urllib.parse import urlparse
from webserver.services import AsyncService
from webserver.constants import CHROME_HEADERS

# Favicon 存储根目录
RESOURCES_DIR = "/data/books/resources"
FRIENDS_FAVICON_DIR = os.path.join(RESOURCES_DIR, "friends")


class ResourceService(AsyncService):
    _last_check_times = {}
    _checking = False

    def __init__(self):
        super().__init__()
        os.makedirs(FRIENDS_FAVICON_DIR, exist_ok=True)

    @staticmethod
    def get_favicon_path(domain):
        return os.path.join(FRIENDS_FAVICON_DIR, "%s.ico" % domain)

    @staticmethod
    def check_favicon(uri):
        if uri.startswith("http://") or uri.startswith("https://"):
            domain = urlparse(uri).netloc
        else:
            domain = uri
        path = ResourceService.get_favicon_path(domain)
        if not os.path.exists(path):
            return None
        if os.path.getsize(path) == 0:
            return ""
        return "/api/favicon/%s.ico" % domain

    @staticmethod
    def clear_favicons():
        for filename in os.listdir(FRIENDS_FAVICON_DIR):
            path = os.path.join(FRIENDS_FAVICON_DIR, filename)
            if os.path.isfile(path) and os.path.exists(path) and os.path.getsize(path) < 128:
                os.remove(path)

    @AsyncService.register_service
    def load_favicons(self, urls, flag=0):
        if self._checking:
            logging.info("Favicon check skipped due to checking in progress")
            return
        if flag not in self._last_check_times:
            self._last_check_times[flag] = 0

        if time.time() - self._last_check_times[flag] < 3600:
            logging.info("Favicon check skipped (checked recently)")
            return

        self._checking = True
        if time.time() - self._last_check_times[flag] >= 3600:
            ResourceService.clear_favicons()
        self._last_check_times[flag] = time.time()

        for url in urls:
            logging.info("Processing favicon URL: %s", url)
            domain = urlparse(url).netloc
            if not domain:
                logging.info("Invalid URL, skipping: %s", url)
                continue

            path = ResourceService.get_favicon_path(domain)
            if os.path.exists(path):
                continue

            if urlparse(url).path:
                favicon_url = url
            else:
                favicon_url = "https://%s/favicon.ico" % domain
            logging.info("Downloading favicon from: %s", favicon_url)
            try:
                resp = requests.get(
                    favicon_url,
                    timeout=10,
                    headers=CHROME_HEADERS,
                    allow_redirects=True,
                )
                if resp.status_code == 200 and len(resp.content) > 0:
                    with open(path, "wb") as f:
                        f.write(resp.content)
                    logging.info("Saved favicon for %s (%d bytes)", domain, len(resp.content))
                else:
                    with open(path, "wb") as f:
                        pass
                    logging.info("No favicon found for %s (status=%s), created empty marker", domain, resp.status_code)
            except Exception as e:
                logging.warning("Failed to download favicon for %s: %s", domain, e)
