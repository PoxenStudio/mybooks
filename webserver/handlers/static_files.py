#!/usr/bin/env python3
# -*- coding: UTF-8 -*-


import asyncio
import hashlib
import logging
import mimetypes
import os
import random
import re
import time
import urllib
import zipfile
from concurrent.futures import ThreadPoolExecutor
from webserver.i18n import _
from tornado import web
from tornado.httpclient import AsyncHTTPClient, HTTPRequest
from webserver import constants, loader, perf
from webserver.services.converter import ConverterService
from webserver.services.book_access_service import BookAccessService
from webserver.handlers.base import BaseHandler, js, is_admin
from webserver.base import accel
from webserver.base.image_generator import ImageGenerator
from webserver.base.thumbnail import DEFAULT_SIZES, ThumbCache, nearest_size, scale_cover


CONF = loader.get_settings()

# 创建线程池用于执行阻塞操作
_executor = ThreadPoolExecutor(max_workers=20)
LITE_THUMB_SIZES = [(120, 200), (240, 320)]


def get_author_hash(author):
    return hashlib.md5(author.encode('utf-8')).hexdigest()


class ImageHandler(BaseHandler):
    _cover_paths = {}
    _thumb_inflight = {}
    _thumb_slots = None
    _thumb_cache = None
    _thumb_cache_root = None

    def send_error_of_not_invited(self):
        self.set_header("WWW-Authenticate", "Basic")
        self.set_status(401)
        raise web.Finish()

    async def get(self, fmt, id, **kwargs):
        data = await self.get_data_async(fmt, id, **kwargs)
        if data is not None:
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
        known = ImageHandler._cover_paths.get(id)
        if not (known and known[1] and known[0] > time.time()):
            if not await asyncio.get_running_loop().run_in_executor(_executor, self.calibre_db.has_id, id):
                raise web.HTTPError(404, "id:%d does not exist in database" % id)
        if fmt == "thumb" or fmt.startswith("thumb_"):
            try:
                width, height = map(int, fmt.split("_")[1:])
            except Exception:
                width, height = 60, 80
            return await self.get_cover_async(id, thumbnail=True, thumb_width=width, thumb_height=height)
        if fmt == "cover":
            return await self.get_cover_async(id, thumbnail=False, thumb_width=600, thumb_height=800)
        if fmt == "opf":
            return await self.get_metadata_as_opf_async(id)
        raise web.HTTPError(404, "bad url")

    @classmethod
    def thumb_cache(cls):
        root = CONF.get("CACHE_DIR", "/data/cache")
        if not CONF.get("THUMB_CACHE", True) or not root:
            return None
        if cls._thumb_cache is None or cls._thumb_cache_root != root:
            cls._thumb_cache_root = root
            cls._thumb_cache = ThumbCache(root, perf.clamp_cache_mb(CONF.get("CACHE_MAX_MB", 200)) * 1024 * 1024)
        cls._thumb_cache.max_bytes = perf.clamp_cache_mb(CONF.get("CACHE_MAX_MB", 200)) * 1024 * 1024
        return cls._thumb_cache

    def library_root(self):
        return self.calibre_db_cache.backend.library_path

    def _lookup_cover_dir(self, book_id):
        return self.calibre_db_cache.field_for("path", book_id)

    async def _cover_file(self, book_id):
        loop = asyncio.get_running_loop()
        for attempt in (0, 1):
            hit = ImageHandler._cover_paths.get(book_id)
            if attempt == 1 or hit is None or hit[0] < time.time():
                rel = await loop.run_in_executor(_executor, self._lookup_cover_dir, book_id)
                if len(ImageHandler._cover_paths) > 4096:
                    ImageHandler._cover_paths.clear()
                hit = ImageHandler._cover_paths[book_id] = (time.time() + 60, rel)
            if not hit[1]:
                return None, None
            path = os.path.join(self.library_root(), hit[1], "cover.jpg")
            try:
                return path, os.stat(path)
            except OSError:
                continue
        return None, None

    def _not_modified(self, etag):
        self.set_header("Etag", etag)
        if self.check_etag_header():
            self.set_status(304)
            return True
        return False

    def _accel_redirect(self, uri):
        self.set_header("Content-Type", "image/jpeg")
        self.set_header("Cache-Control", "public, max-age=86400")
        self.set_header("X-Accel-Redirect", uri)

    def _read_default_or_dynamic(self, book_id, width, height):
        try:
            cover_data = self.default_cover
            if CONF.get("USE_DYNAMIC_COVER", False) and not perf.lite_on("LITE_NO_DYNAMIC_COVER"):
                with self.db_lock:
                    mi = self.calibre_db.get_metadata(book_id, index_is_id=True)
                author = mi.authors[0] if mi.authors else _("佚名")
                data = ImageGenerator.generate_cover(mi.title, author, width, height)
                if data:
                    cover_data = data
            return cover_data
        except Exception as err:
            logging.error(f"Failed to generate cover!! {err}")
            return self.default_cover

    @staticmethod
    def _read_file(path):
        with open(path, "rb") as f:
            return f.read()

    @staticmethod
    def _make_thumbnail(path, width, height, quality, use_pillow):
        data = ImageHandler._read_file(path)
        if use_pillow:
            try:
                return scale_cover(data, width, height, quality)
            except Exception as err:
                logging.warning("Pillow thumbnail failed (%s), fall back to calibre", err)
        from calibre.utils.magick.draw import thumbnail as generate_thumbnail

        return generate_thumbnail(data, width=width, height=height, compression_quality=quality)[-1]

    async def _generate_thumbnail(self, path, stamp, book_id, width, height):
        key = (book_id, stamp, width, height)
        inflight = ImageHandler._thumb_inflight.get(key)
        if inflight is not None:
            return await asyncio.shield(inflight)
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        ImageHandler._thumb_inflight[key] = future
        if ImageHandler._thumb_slots is None:
            ImageHandler._thumb_slots = asyncio.Semaphore(1 if perf.lite_on("LITE_POOLS_SMALL") else max(1, int(CONF.get("THUMB_CONCURRENCY", 2))))
        try:
            async with ImageHandler._thumb_slots:
                data = await loop.run_in_executor(
                    _executor, self._make_thumbnail, path, width, height, 70 if perf.lite_on("LITE_THUMB_CACHE_ONLY") else int(CONF.get("THUMB_JPEG_QUALITY", 83)), bool(CONF.get("THUMB_USE_PILLOW", True))
                )
            future.set_result(data)
            return data
        except BaseException as err:
            future.set_exception(err)
            future.exception()
            raise
        finally:
            ImageHandler._thumb_inflight.pop(key, None)

    async def get_cover_async(self, id, thumbnail=False, thumb_width=60, thumb_height=80):
        loop = asyncio.get_running_loop()
        try:
            path, st = await self._cover_file(id)
            if path is None:
                self.set_header("Content-Type", "image/jpeg")
                self.set_header("Last-Modified", self.last_modified(self.build_time))
                return await loop.run_in_executor(_executor, self._read_default_or_dynamic, id, thumb_width, thumb_height)

            stamp = st.st_mtime_ns
            use_accel = accel.enabled(self)
            if not thumbnail:
                if use_accel:
                    uri = accel.uri_for(accel.LIBRARY_PREFIX, self.library_root(), path)
                    if uri:
                        self._accel_redirect(uri)
                        return None
                if self._not_modified('"%d-%d"' % (stamp, st.st_size)):
                    return None
                self.set_header("Content-Type", "image/jpeg")
                self.set_header("Cache-Control", "public, max-age=86400")
                return await loop.run_in_executor(_executor, self._read_file, path)

            sizes = LITE_THUMB_SIZES if perf.lite_on("LITE_THUMB_CACHE_ONLY") else (CONF.get("THUMB_SIZES") or DEFAULT_SIZES)
            width, height = nearest_size(thumb_width, thumb_height, [tuple(s) for s in sizes])
            if not use_accel and self._not_modified('"%d-%d-%dx%d"' % (stamp, id, width, height)):
                return None
            cache = self.thumb_cache()
            cache_path = cache.path_for(id, stamp, width, height) if cache else None
            if cache_path and os.path.exists(cache_path):
                if use_accel:
                    uri = accel.uri_for(accel.CACHE_PREFIX, cache.root, cache_path)
                    if uri:
                        cache.hits += 1
                        self._accel_redirect(uri)
                        return None
                data = await loop.run_in_executor(_executor, cache.get, cache_path)
                if data is not None:
                    self.set_header("Content-Type", "image/jpeg")
                    self.set_header("Cache-Control", "public, max-age=86400")
                    return data
            data = await self._generate_thumbnail(path, stamp, id, width, height)
            if cache_path:
                cache.misses += 1
                await loop.run_in_executor(_executor, cache.put, cache_path, data)
            self.set_header("Content-Type", "image/jpeg")
            self.set_header("Cache-Control", "public, max-age=86400")
            return data
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
        whitelist = ["bcebos.com", "doubanio.com", "bdstatic.com", "amazon.com", "qpic.cn",
                     "youshu.me", "zongheng.com", "byteimg.com", "fanqienovel.com", "neodb.social",
                     "www.ujxsw.org"]
        for w in whitelist:
            if host.endswith(w):
                return True
        return False

    async def get(self):
        """使用异步 HTTP 客户端获取远程图片"""
        url = self.get_argument("url", None)

        # set the content-type according the extension of the url, default to image/jpeg
        ext = os.path.splitext(url)[1].lower() if url else ""
        content_type = (mimetypes.guess_type(ext)[0] if ext else None) or "image/jpeg"
        self.set_header("Content-Type", content_type)

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
        path = ConverterService().get_path_progress(book_id)
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
        if not self.current_user and not BookAccessService.guest_read_allowed(self, bid):
            return self.redirect("/login")

        if self.current_user and not BookAccessService.share_read_granted(self, bid):
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
                # 有些epub文件里路径忽略了大小写
                path_lower = path.lower()
                for name in zf.namelist():
                    if name.lower() == path_lower:
                        path = name
                        break
                if path not in zf.namelist():
                    raise web.HTTPError(404)

            content_type = mimetypes.guess_type(path)[0]
            if content_type:
                self.set_header("Content-Type", content_type)

            with zf.open(path) as f:
                self.write(f.read())


class ToolIconHandler(BaseHandler):
    def get(self, tool_id):
        from webserver.toolbox import toolbox_manager

        icon_path = None
        # 动态/外部工具（source 为 store/dev）的图标固定放在包根目录下的 icon.png，
        # 见 document/Toolbox_Dynamic_Design.md 三、工具包结构。
        dynamic_icon = os.path.join(toolbox_manager.tool_root(), tool_id, "icon.png")
        if os.path.exists(dynamic_icon):
            icon_path = dynamic_icon

        if icon_path is None:
            resource_path = CONF.get("resource_path", "")
            toolbox_dir = os.path.join(resource_path, "toolbox")
            for ext in ("jpg", "png"):
                candidate = os.path.join(toolbox_dir, f"{tool_id}.{ext}")
                if os.path.exists(candidate):
                    icon_path = candidate
                    break
            if icon_path is None:
                icon_path = os.path.join(toolbox_dir, "default_tool.png")

        if not os.path.exists(icon_path):
            raise web.HTTPError(404, "Tool icon not found")
        mime_type = mimetypes.guess_type(icon_path)[0] or "image/jpeg"
        self.set_header("Content-Type", mime_type)
        with open(icon_path, "rb") as f:
            self.write(f.read())


class ToolFrontendIndexHandler(BaseHandler):
    """工具前端入口页面，见 document/Toolbox_Dynamic_Design.md 4.4 节。

    只对 `source` 为 `store`/`dev` 的工具生效（即 TOOL_ROOT/<tool_id>/frontend/ 下有实际
    产物的工具，无论 type 是 builtin 还是 tool）；`source=bundled` 的内置工具没有独立的
    index.html，其 `.vue` 页面随核心 App 一起构建，走现状的 /toolbox/{page} 静态路由。
    """

    def get(self, tool_id):
        from webserver.toolbox import toolbox_manager

        if not toolbox_manager.is_tool_enabled(tool_id):
            raise web.HTTPError(404, "Tool not found or disabled")

        index_path = os.path.join(toolbox_manager.tool_root(), tool_id, "frontend", "index.html")
        if not os.path.exists(index_path):
            raise web.HTTPError(404, "Tool frontend not found")

        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.set_header("Cache-Control", "no-cache")
        with open(index_path, "rb") as f:
            self.write(f.read())


class ToolFrontendAssetHandler(BaseHandler):
    """工具前端引用的其它静态资源（JS/CSS/图片/字体等），见 4.4 节。"""

    def get(self, tool_id, asset_path):
        from webserver.toolbox import toolbox_manager

        if not toolbox_manager.is_tool_enabled(tool_id):
            raise web.HTTPError(404, "Tool not found or disabled")

        frontend_dir = os.path.abspath(os.path.join(toolbox_manager.tool_root(), tool_id, "frontend"))
        target_path = os.path.abspath(os.path.join(frontend_dir, asset_path))
        # 防止 ../ 路径穿越读到 frontend/ 目录之外的文件
        if not target_path.startswith(frontend_dir + os.sep):
            raise web.HTTPError(403, "Forbidden")
        if not os.path.isfile(target_path):
            raise web.HTTPError(404, "Asset not found")

        mime_type = mimetypes.guess_type(target_path)[0] or "application/octet-stream"
        self.set_header("Content-Type", mime_type)
        with open(target_path, "rb") as f:
            self.write(f.read())


class FaviconHandler(BaseHandler):
    """提供友情链接及资源 favicon 文件的 HTTP 访问"""

    def prepare(self):
        # 跳过 BaseHandler 的登录检查等，favicon 无需认证
        self.set_hosts()

    def get(self, filename):
        from webserver.services.resource_service import FRIENDS_FAVICON_DIR

        # 安全检查：只允许简单文件名
        if "/" in filename or "\\" in filename or ".." in filename:
            raise web.HTTPError(400, "Invalid filename")

        filepath = os.path.join(FRIENDS_FAVICON_DIR, filename)
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            raise web.HTTPError(404)

        content_type = mimetypes.guess_type(filename)[0] or "image/x-icon"
        self.set_header("Content-Type", content_type)
        self.set_header("Cache-Control", "public, max-age=86400")
        with open(filepath, "rb") as f:
            self.write(f.read())


class AuthorAvatarHandler(BaseHandler):
    def get(self, author):
        from webserver.services.resource_service import AUTHOR_AVATAR_DIR

        author = urllib.parse.unquote(author)
        author_hash = get_author_hash(author)
        existing_files = [
            os.path.join(AUTHOR_AVATAR_DIR, f"{author_hash}.jpg"),
            os.path.join(AUTHOR_AVATAR_DIR, f"{author_hash}.png"),
            os.path.join(AUTHOR_AVATAR_DIR, f"{author_hash}.webp"),
        ]
        for existing_file in existing_files:
            if os.path.exists(existing_file) and os.path.getsize(existing_file) > 0:
                filepath = existing_file
                break
            filepath = None

        if filepath is None:
            default_name = random.choice(["default_1.jpg", "default_2.jpg", "default_3.jpg"])
            filepath = os.path.join(CONF.get("resource_path", ""), "authors", default_name)

        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            raise web.HTTPError(404, "Author avatar not found")

        content_type = mimetypes.guess_type(filepath)[0] or "image/jpeg"
        self.set_header("Content-Type", content_type)
        self.set_header("Cache-Control", "public, max-age=86400")
        with open(filepath, "rb") as f:
            self.write(f.read())


class AuthorAvatarUploadHandler(BaseHandler):
    @js
    @is_admin
    def post(self):
        from webserver.services.resource_service import AUTHOR_AVATAR_DIR

        author = self.get_argument('author', None)
        if not author:
            return {'err': 'failed', 'msg': 'Author name is required'}

        author = urllib.parse.unquote(author)

        if 'avatar_data' not in self.request.files:
            return {'err': 'failed', 'msg': 'No avatar file uploaded'}

        file_info = self.request.files['avatar_data'][0]
        content_type = file_info['content_type']

        if content_type not in ['image/jpeg', 'image/png', 'image/webp']:
            return {'err': 'failed', 'msg': _('只支持上传JPEG、PNG和WEBP格式的图片文件')}

        ext = '.jpg' if content_type == 'image/jpeg' else '.png' if content_type == 'image/png' else '.webp'
        author_hash = get_author_hash(author)
        logging.info(f"Uploading avatar for author {author} to {author_hash}{ext}")
        new_filepath = os.path.join(AUTHOR_AVATAR_DIR, f"{author_hash}{ext}")

        existing_files = [
            os.path.join(AUTHOR_AVATAR_DIR, f"{author_hash}.jpg"),
            os.path.join(AUTHOR_AVATAR_DIR, f"{author_hash}.png"),
            os.path.join(AUTHOR_AVATAR_DIR, f"{author_hash}.webp"),
        ]
        for existing_file in existing_files:
            if os.path.exists(existing_file):
                os.remove(existing_file)

        with open(new_filepath, 'wb') as f:
            f.write(file_info['body'])

        return {'err': 'ok', 'msg': 'Avatar uploaded successfully'}


class SpaStaticHandler(web.StaticFileHandler):
    def set_extra_headers(self, path):
        if path.startswith("_nuxt/"):
            self.set_header("Cache-Control", "public, max-age=31536000, immutable")


def routes():
    static_config = {"path": CONF["html_path"], "default_filename": "index.html"}
    return [
        (r"/get/tool/([^/]+)/icon", ToolIconHandler),
        (r"/get/tool/([a-z0-9_]+)/index\.html", ToolFrontendIndexHandler),
        (r"/get/tool/([a-z0-9_]+)/(.+)", ToolFrontendAssetHandler),
        (r"/get/progress/([0-9]+)", ProgressHandler),
        (r"/get/extract/([0-9]+)/(.*)", EpubReader),
        (r"/get/pcover", ProxyImageHandler),
        (r"/get/author/avatar/(.*)", AuthorAvatarHandler),
        (r"/api/author_avatar", AuthorAvatarUploadHandler),
        (r"/get/(.*)/(.*)", ImageHandler),
        (r"/api/favicon/(.*)", FaviconHandler),
        (r"/(.*)", SpaStaticHandler, static_config),
    ]
