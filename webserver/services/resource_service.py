#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging
import os
from urllib.parse import urlparse

import requests

from webserver.services import AsyncService

# Favicon 存储根目录
RESOURCES_DIR = "/data/books/resources"
FRIENDS_FAVICON_DIR = os.path.join(RESOURCES_DIR, "friends")


class ResourceService(AsyncService):
    def __init__(self):
        super().__init__()
        os.makedirs(FRIENDS_FAVICON_DIR, exist_ok=True)

    @staticmethod
    def get_favicon_path(domain):
        return os.path.join(FRIENDS_FAVICON_DIR, "%s.ico" % domain)

    @staticmethod
    def check_favicon(domain):
        path = ResourceService.get_favicon_path(domain)
        if not os.path.exists(path):
            return None
        if os.path.getsize(path) == 0:
            return ""
        return "/api/friends/favicon/%s.ico" % domain

    @AsyncService.register_service
    def load_friends_favicon(self, urls):
        for url in urls:
            domain = urlparse(url).netloc
            if not domain:
                continue

            path = ResourceService.get_favicon_path(domain)
            if os.path.exists(path):
                continue

            favicon_url = "https://%s/favicon.ico" % domain
            logging.info("Downloading favicon from: %s", favicon_url)
            try:
                resp = requests.get(
                    favicon_url,
                    timeout=10,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; TaleBook/1.0)"
                    },
                    allow_redirects=True,
                )
                if resp.status_code == 200 and len(resp.content) > 0:
                    with open(path, "wb") as f:
                        f.write(resp.content)
                    logging.info("Saved favicon for %s (%d bytes)", domain, len(resp.content))
                else:
                    open(path, "wb").close()
                    logging.info("No favicon found for %s (status=%s), created empty marker", domain, resp.status_code)
            except Exception as e:
                logging.warning("Failed to download favicon for %s: %s", domain, e)
