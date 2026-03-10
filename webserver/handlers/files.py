#!/usr/bin/env python3
# -*- coding: UTF-8 -*-


import logging
import os
import re
import urllib
import zipfile
from concurrent.futures import ThreadPoolExecutor
from gettext import gettext as _
from tornado import web
from tornado.httpclient import AsyncHTTPClient, HTTPRequest
from webserver import constants, loader
from webserver.services.convert import ConvertService
from webserver.handlers.base import BaseHandler

CONF = loader.get_settings()

# 创建线程池用于执行阻塞操作
_executor = ThreadPoolExecutor(max_workers=20)


class ImageHandler(BaseHandler):
    def send_error_of_not_invited(self):
        self.set_header("WWW-Authenticate", "Basic")
        self.set_status(401)
        raise web.Finish()

    async def get(self, fmt, id, **kwargs):
        data = await self.get_data_async(fmt, id, **kwargs)
        self.write(data)

    async def get_data_async(self, fmt, id, **kwargs):
        "Serves files, covers, thumbnails, metadata from the calibre database"
        try:
            id = int(id)
        except ValueError:
            id = id.rpartition("_")[-1].partition(".")[0]
            match = re.search(r"\d+", id)
            if not match:
                raise web.HTTPError(404, "id:%s not an integer" % id)
            id = int(match.group())
        if not self.calibre_db.has_id(id):
            raise web.HTTPError(404, "id:%d does not exist in database" % id)
        if fmt == "thumb" or fmt.startswith("thumb_"):
            try:
                width, height = map(int, fmt.split("_")[1:])
            except:
                width, height = 60, 80
            return await self.get_cover_async(
                id, thumbnail=True, thumb_width=width, thumb_height=height
            )
        if fmt == "cover":
            return await self.get_cover_async(id)
        if fmt == "opf":
            return await self.get_metadata_as_opf_async(id)
        raise web.HTTPError(404, "bad url")

    # Actually get content from the database {{{
    async def get_cover_async(self, id, thumbnail=False, thumb_width=60, thumb_height=80):
        """异步获取封面，将阻塞操作放到线程池执行"""
        import asyncio
        from calibre.utils.magick.draw import thumbnail as generate_thumbnail

        def _get_cover_sync():
            try:
                # 快速访问数据库获取封面数据，锁住最小范围
                with self.db_lock:
                    cover = self.calibre_db.cover(id, index_is_id=True)
                    if cover is None:
                        cover_data = self.default_cover
                        updated = self.build_time
                    else:
                        cover_data = cover
                        updated = self.calibre_db.cover_last_modified(id, index_is_id=True)

                # 图片处理在锁外执行（CPU 密集型操作）
                if thumbnail and cover_data != self.default_cover:
                    cover_data = generate_thumbnail(
                        cover_data, width=thumb_width, height=thumb_height, compression_quality=83
                    )[-1]

                return cover_data, updated
            except Exception as err:
                import traceback
                logging.error("Failed to generate cover:")
                logging.error(traceback.format_exc())
                raise web.HTTPError(404, "Failed to generate cover: %r" % err)

        try:
            self.set_header("Content-Type", "image/jpeg")
            # 在线程池中执行阻塞操作
            cover, updated = await asyncio.get_event_loop().run_in_executor(
                _executor, _get_cover_sync
            )
            self.set_header("Last-Modified", self.last_modified(updated))
            return cover
        except web.HTTPError:
            raise
        except Exception as err:
            import traceback
            logging.error("Failed to get cover:")
            logging.error(traceback.format_exc())
            raise web.HTTPError(404, "Failed to get cover: %r" % err)

    async def get_metadata_as_opf_async(self, id_):
        """异步获取元数据"""
        import asyncio
        from calibre.ebooks.metadata.opf2 import metadata_to_opf

        def _get_metadata_sync():
            with self.db_lock:
                mi = self.calibre_db.get_metadata(id_, index_is_id=True)
                # 在锁内快速获取数据
                last_modified = mi.last_modified
            # 数据转换在锁外执行
            data = metadata_to_opf(mi)
            return data, last_modified

        self.set_header("Content-Type", "application/oebps-package+xml; charset=UTF-8")
        data, last_modified = await asyncio.get_event_loop().run_in_executor(
            _executor, _get_metadata_sync
        )
        self.set_header("Last-Modified", self.last_modified(last_modified))
        return data


class ProxyImageHandler(BaseHandler):
    def is_whitelist(self, host):
        whitelist = ["bcebos.com", "doubanio.com", "bdstatic.com", "amazon.com"]
        for w in whitelist:
            if host.endswith(w):
                return True
        return False

    async def get(self):
        """使用异步 HTTP 客户端获取远程图片"""
        url = self.get_argument("url", None)
        if not url:
            cover = self.default_cover
            self.write(cover)
            return

        p = urllib.parse.urlparse(url)
        if not self.is_whitelist(p.netloc):
            cover = self.default_cover
            self.write(cover)
            return

        # 使用 Tornado 的异步 HTTP 客户端
        http_client = AsyncHTTPClient()
        headers = dict(constants.CHROME_HEADERS)
        headers["Referer"] = url

        try:
            request = HTTPRequest(
                url=url,
                headers=headers,
                validate_cert=False,
                request_timeout=15.0,
                connect_timeout=10.0
            )
            response = await http_client.fetch(request)

            # 设置响应头
            for k, v in response.headers.items():
                if k.lower() not in ['content-length', 'content-encoding', 'transfer-encoding']:
                    self.set_header(k, v)
            self.write(response.body)
        except Exception as e:
            logging.error(f"Failed to fetch image from {url}: {e}")
            # 失败时返回默认封面
            self.write(self.default_cover)
        return


class ProgressHandler(BaseHandler):
    def get(self, id):
        book_id = int(id)
        path = ConvertService().get_path_progress(book_id)
        if not os.path.exists(path):
            raise web.HTTPError(404, log_message="nothing")
        txt = open(path).read()

        # erase all settings values from txt content
        for hidden in CONF.values():
            if isinstance(hidden, str):
                txt.replace(hidden, "XXX")
        self.write(txt)


class EpubReader(BaseHandler):
    def get(self, bid, path):
        if not CONF["ALLOW_GUEST_READ"] and not self.current_user:
            return self.redirect("/login")

        if self.current_user:
            if self.current_user.can_read():
                if not self.current_user.is_active():
                    raise web.HTTPError(403, reason=_(u"无权在线阅读，请先登录注册邮箱激活账号。"))
            else:
                raise web.HTTPError(403, reason=_(u"无权在线阅读"))

        book = self.get_book(bid)
        fpath = book.get("fmt_epub", None)
        if not fpath:
            raise web.HTTPError(404)

        with zipfile.ZipFile(fpath, 'r') as zf:
            if path not in zf.namelist():
                raise web.HTTPError(404)
            with zf.open(path) as f:
                self.write(f.read())


def routes():
    static_config = {"path": CONF["html_path"], "default_filename": "index.html"}
    return [
        (r"/get/pcover", ProxyImageHandler),
        (r"/get/progress/([0-9]+)", ProgressHandler),
        (r"/get/extract/([0-9]+)/(.*)", EpubReader),
        (r"/get/(.*)/(.*)", ImageHandler),
        (r"/(.*)", web.StaticFileHandler, static_config),
    ]
