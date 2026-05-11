#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import datetime
import logging
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
import traceback
import uuid
from webserver.i18n import _, normalize_language
from sqlalchemy import func, extract

import tornado

from webserver import loader
from webserver.services.autofill import AutoFillService
from webserver.services.ai_fillinfo import AIFillInfoService
from webserver.services.batch_convert import BatchConvertService
from webserver.services.batch_title_sort import BatchTitleSortUpdateService
from webserver.services.metadata_update import MetaDataUpdateService
from webserver.services.batch_generate_cover import DynamicCoverUpdateService
from webserver.services.save_meta_to_files import SaveMetaToFilesService
from webserver.services.mail import MailService
from webserver.services.book_barn import BookBarnClient
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver.handlers.base import BaseHandler, auth, js, is_admin
from webserver.models import Reader, Item
from webserver.utils import SimpleBookFormatter
from webserver.base.trash_manager import TrashManager
from webserver.version import VERSION
from webserver.handlers.audio import AudioUtils
from webserver.constants import (
    CALIBRE_COLUMN_BOOK_TYPE,
    BOOK_TYPE_PHYSICAL,
    BOOK_TYPE_EBOOK,
    ENABLE_OPDS_SERVICE,
)
from webserver.i18n import apply_localized_default_settings

CONF = loader.get_settings()
USER_UPDATE_TS_MAP = {}
ENABLE_VIP_QUOTA_KEY = "ENABLE_VIP_QUOTA"
IMPORT_BY_INOTIFY = "IMPORT_BY_INOTIFY"
META_ALL_SOURCES = ["douban", "baidu", "google", "amazon", "xinhua", "youshu"]
DEFAULT_META_SOURCES = ["douban", "baidu", "xinhua"]
LOG_PATH = "/data/log/talebook.log"


class AdminUsers(BaseHandler):
    @js
    @auth
    def get(self):
        if not self.admin_user:
            return {"err": "permission.not_admin", "msg": _("当前用户非管理员")}

        num = max(10, int(self.get_argument("num", 20)))
        page = max(0, int(self.get_argument("page", 1)) - 1)
        sort = self.get_argument("sort", "access_time")
        desc = self.get_argument("desc", "desc")
        logging.debug("num=%d, page=%d, sort=%s, desc=%s" % (num, page, sort, desc))

        f = {
            "id": Reader.id,
            "access_time": Reader.access_time,
            "create_time": Reader.create_time,
            "update_time": Reader.update_time,
            "username": Reader.username,
        }.get(sort, Reader.id)
        if desc == "false":
            f = f.asc()
        else:
            f = f.desc()

        enable_vip_quota = CONF.get(ENABLE_VIP_QUOTA_KEY, False)
        query = self.sqlite_session.query(Reader).order_by(f)
        total = query.count()
        start = page * num
        items = []
        for user in query.limit(num).offset(start).all():
            has_social_account = (
                hasattr(user, "social_auth") and user.social_auth.count() > 0
            )
            user_provider = (
                user.social_auth[0].provider if has_social_account else "register"
            )
            d = {
                "id": user.id,
                "username": user.username,
                "name": user.name,
                "email": user.email,
                "avatar": user.avatar,
                "is_active": user.is_active(),
                "is_admin": user.is_admin(),
                "extra": dict(user.extra),
                "provider": user_provider,
                "create_time": (
                    user.create_time.strftime("%Y-%m-%d %H:%M:%S")
                    if user.create_time
                    else "N/A"
                ),
                "update_time": (
                    user.update_time.strftime("%Y-%m-%d %H:%M:%S")
                    if user.update_time
                    else "N/A"
                ),
                "access_time": (
                    user.access_time.strftime("%Y-%m-%d %H:%M:%S")
                    if user.access_time
                    else "N/A"
                ),
                "read_limit": user.read_limit or 0,
                "limit_categories": user.limit_categories or "",
                "limit_tags": user.limit_tags or "",
            }
            if enable_vip_quota:
                d["vipquota"] = user.vipquota or 0
                d["vip_expire"] = (
                    user.vipexpire.strftime("%Y-%m-%d") if user.vipexpire else ""
                )
            for attr in dir(user):
                if attr.startswith("can_"):
                    d[attr] = getattr(user, attr)()
            need_update = False
            ts = USER_UPDATE_TS_MAP.get(user.id, 0)
            if not ts or (datetime.datetime.now() - ts).total_seconds() > 3600:
                need_update = True
                USER_UPDATE_TS_MAP[user.id] = datetime.datetime.now()
            if need_update or "upload_history_count" not in user.extra:
                d["extra"]["upload_history_count"] = self.get_user_upload_cnt(user.id)
            else:
                d["extra"]["upload_history_count"] = user.extra.get(
                    "upload_history_count", 0
                )
            items.append(d)
            user_config = {}
            user_config["allow_read_range_setting"] = CONF.get(
                "ALLOW_READ_RANGE_SETTING", False
            )
        return {
            "err": "ok",
            "users": {"items": items, "total": total},
            "settings": user_config,
        }

    @js
    @auth
    def post(self):
        if not self.admin_user:
            return {"err": "permission.not_admin", "msg": _("当前用户非管理员")}
        data = tornado.escape.json_decode(self.request.body)
        uid = data.get("id", None)
        if not uid:
            return {"err": "params.invalid", "msg": _("参数错误")}
        del data["id"]
        if not data:
            return {"err": "params.fields.invalid", "msg": _("用户配置项参数错误")}
        user = self.sqlite_session.query(Reader).filter(Reader.id == uid).first()
        if not user:
            return {"err": "params.user.not_exist", "msg": _("用户ID错误")}
        if "active" in data:
            user.active = data["active"]

        if "admin" in data:
            user.admin = data["admin"]

        if user.admin is False and self.user_id() == user.id:
            return {
                "err": "params.user.invalid",
                "msg": _("不允许取消自己的管理员权限"),
            }

        if data.get("delete", "") == user.username:
            if self.user_id() == user.id:
                return {"err": "params.user.invalid", "msg": _("不允许删除自己")}

            self.sqlite_session.query(Reader).filter(Reader.id == user.id).delete()
            self.sqlite_session.commit()
            return {"err": "ok", "msg": _("删除成功")}

        if "read_limit" in data:
            rl = int(data["read_limit"])
            if rl not in (0, 1, 2):
                return {
                    "err": "params.read_limit.invalid",
                    "msg": _("阅读限制参数不对"),
                }
            user.read_limit = rl
        if "limit_categories" in data:
            user.limit_categories = data["limit_categories"]
        if "limit_tags" in data:
            user.limit_tags = data["limit_tags"]

        if "password" in data:
            new_password = (data["password"] or "").strip()
            if (
                len(new_password) < 6
                or len(new_password) > 20
                or not re.match(Reader.RE_PASSWORD, new_password)
            ):
                return {
                    "err": "params.password.invalid",
                    "msg": _("密码无效，长度须在6~20位之间"),
                }
            user.set_secure_password(new_password)

        p = data.get("permission", "")
        if not isinstance(p, str):
            return {"err": "params.permission.invalid", "msg": _("权限参数不对")}
        if p:
            user.set_permission(p)
        user.save()
        return {"err": "ok"}


class AdminTestMail(BaseHandler):
    @js
    @auth
    def post(self):
        mail_enc = self.get_argument("smtp_encryption")
        mail_server = self.get_argument("smtp_server")
        mail_username = self.get_argument("smtp_username")
        mail_password = self.get_argument("smtp_password")

        mail_from = mail_username
        mail_to = mail_username
        mail_subject = _("Calibre功能验证邮件")
        mail_body = _("这是一封测试邮件，验证邮件参数是否配置正确。")

        try:
            MailService().do_send_mail(
                mail_from,
                mail_to,
                mail_subject,
                mail_body,
                relay=mail_server,
                username=mail_username,
                password=mail_password,
                encryption=mail_enc,
            )
            return {"err": "ok", "msg": _("发送成功")}
        except Exception as e:
            logging.error(traceback.format_exc())
            return {"err": "email.server_error", "msg": str(e)}


class AdminOwnerMode(BaseHandler):
    @auth
    def get(self):
        user_id = self.get_argument("user_id", None)
        if user_id and self.is_admin():
            self.set_secure_cookie("admin_id", self.user_id())
            self.set_secure_cookie("user_id", user_id)
        self.redirect("/", 302)


class SettingsSaverLogic:
    def restart_async(self):
        def _delayed_restart():
            try:
                # 留一点时间给当前请求把响应写回客户端
                time.sleep(0.3)
                logging.info("Triggering async restart by exiting current process")
            except Exception:
                logging.error(traceback.format_exc())
            finally:
                # 退出当前进程，由 supervisor/docker 的 autorestart 拉起新进程
                os._exit(0)

        threading.Thread(
            target=_delayed_restart, name="talebook-restart", daemon=True
        ).start()

    def update_nuxtjs_env(self):
        # update nuxtjs .env file
        nuxtjs_env = (
            """
TITLE="%(site_title)s"
TITLE_TEMPLATE="%%s | %(site_title)s"
"""
            % CONF
        )

        if len(CONF.get("google_analytics_id", "").strip()) > 0:
            logging.debug("google_analytics_id is %s" % CONF.get("google_analytics_id", ""))
            nuxtjs_env += "GOOGLE_ANALYTICS_ID=%s\n" % CONF["google_analytics_id"]

        with open(CONF["nuxt_env_path"], "w") as f:
            f.write(nuxtjs_env)

    def save_extra_settings(self, args):
        if args != CONF:
            CONF.update(args)

        try:
            self.update_nuxtjs_env()
        except:
            logging.error(traceback.format_exc())
            return {
                "err": "file.permission",
                "msg": _("更新配置文件失败！请确保文件的权限为可写入！"),
            }

        args["installed"] = True
        try:
            args.dumpfile()
        except:
            logging.error(traceback.format_exc())
            return {
                "err": "file.permission",
                "msg": _("更新磁盘配置文件失败！请确保配置文件的权限为可写入！"),
            }

        CONF["installed"] = True
        if CONF.get("autoreload", False):
            # 异步执行重启命令，避免阻塞当前请求
            self.restart_async()
            return {"err": "ok", "msg": _("保存成功！可能需要5~10秒钟生效！")}
        else:
            return {"err": "ok", "rsp": CONF, "msg": _("设置已保存，请重启服务生效！")}


class AdminSettings(BaseHandler):
    @js
    @auth
    def get(self):
        if not self.admin_user:
            return {"err": "permission", "msg": _("无权访问此接口")}

        hour_ = int(CONF.get("BOOKBARN_COLLECTION_HOUR", 24))
        if hour_ >= 24 or hour_ < 0:
            CONF["BOOKBARN_COLLECTION_HOUR"] = 3
        if CONF.get("ENABLE_RECEIVING_BOOKS", None) is None:
            CONF["ENABLE_RECEIVING_BOOKS"] = CONF.get("ENABLE_BOOKBARN", False)
        if CONF.get("ENABLE_OPDS_SERVICE", None) is None:
            CONF["ENABLE_OPDS_SERVICE"] = True

        if CONF.get("MAIN_PAGE_RANDOM_COUNT", -1) == -1:
            CONF["MAIN_PAGE_RANDOM_COUNT"] = 12
        if CONF.get("MAIN_PAGE_RECENT_COUNT", -1) == -1:
            CONF["MAIN_PAGE_RECENT_COUNT"] = 12
        if CONF.get("INDEX_PAGE_TYPE", -1) == -1:
            CONF["INDEX_PAGE_TYPE"] = (
                "index"  # 默认首页, 可能的值包括index, all, categories三类
            )
        if CONF.get("DEFAULT_PAGE_SIZE", -1) == -1:
            CONF["DEFAULT_PAGE_SIZE"] = 60  # 默认每页显示60本书

        CONF["site_icon"] = "favicon_0"  # default icon, means use current favicon.ico
        CONF["META_ALL_SOURCES"] = META_ALL_SOURCES

        sns = [
            {"value": "qq", "text": "QQ", "link": "https://connect.qq.com/"},
            {
                "value": "github",
                "text": "Github",
                "link": "https://github.com/settings/applications/new",
            },
            {
                "value": "weibo",
                "text": "微博",
                "link": "http://open.weibo.com/developers",
            },
            {
                "value": "weixin",
                "text": "微信",
                "link": "https://developers.weixin.qq.com/doc/offiaccount/OA_Web_Apps/Wechat_webpage_authorization.html",
            },
        ]
        return {"err": "ok", "settings": CONF, "sns": sns, "site_url": self.site_url}

    @js
    @auth
    def post(self):
        if not self.admin_user:
            return {"err": "permission.not_admin", "msg": _("当前用户非管理员")}

        data = tornado.escape.json_decode(self.request.body)
        KEYS = [
            "ALLOW_GUEST_DOWNLOAD",
            "ALLOW_GUEST_PUSH",
            "ALLOW_GUEST_READ",
            "ALLOW_GUEST_UPLOAD",
            "ALLOW_REGISTER",
            "BOOK_NAMES_FORMAT",
            "BOOK_NAV",
            "EPUB_VIEWER",
            "FRIENDS",
            "FOOTER",
            "HEADER",
            "INVITE_CODE",
            "INVITE_MESSAGE",
            "INVITE_MODE",
            "MAX_UPLOAD_SIZE",
            "CHUNK_UPLOAD_SIZE",
            "RESET_MAIL_CONTENT",
            "RESET_MAIL_TITLE",
            "SIGNUP_MAIL_CONTENT",
            "SIGNUP_MAIL_TITLE",
            "SOCIALS",
            "autoreload",
            "cookie_secret",
            "scan_upload_path",
            "convert_timeout",
            "douban_apikey",
            "douban_baseurl",
            "douban_max_count",
            "auto_fill_meta",
            "push_title",
            "push_content",
            "site_title",
            "smtp_password",
            "smtp_server",
            "smtp_username",
            "smtp_encryption",
            "static_host",
            "xsrf_cookies",
            "settings_path",
            "avatar_service",
            "google_analytics_id",
            "site_language",
            "site_theme",
            "site_icon",
            "ENABLE_BOOKBARN",
            "ENABLE_PHYSICAL_BOOKS",
            "BOOKBARN_COLLECTION_HOUR",
            "BOOKBARN_TOKEN",
            "ENABLE_RECEIVING_BOOKS",
            "USE_BOOKBARN_PROXY",
            "BOOK2AUDIO_PROXY",
            "LAST_REVISION",
            "DEVICES",
            "AI_ENABLED",
            "AI_MODEL",
            "AI_MCP_TOKEN",
            "AI_DEEPSEEK_API_KEY",
            "AI_API_URL",
            "MAIN_PAGE_RANDOM_COUNT",
            "MAIN_PAGE_RECENT_COUNT",
            "INDEX_PAGE_TYPE",
            "DEFAULT_PAGE_SIZE",
            "ENABLE_WEBDAV_SERVICE",
            "WEBDAV_SYNC_FOLDER",
            "ENABLE_AUDIO_CONVERSION_LOG",
            "ENABLE_OPDS_SERVICE",
            "ENABLE_OPDS_AUTH",
            "ENABLE_PODCAST_SERVICE",
            "META_SELECTED_SOURCES",
            "PDF_TILE_WITH_FILE_NAME",
            "ALLOW_NEW_USER_MANAGE_BOOK",
            "ALLOW_NEW_USER_PUSH_BOOK",
            "ALLOW_READ_RANGE_SETTING",
            "IMPORT_BY_INOTIFY",
            "IMPORT_CATEGORY_WITH_FOLDER",
            "REMOVE_IMPORTED_FILE",
            "UPDATE_CATEGORY_WITH_FOLDER_RENAME",
            "LOG_LEVEL_DEBUG",
            "ENABLE_STAMP_FEATURE",
            "STAMP_POSITION",
            "ENABLE_TXT_TO_TXTZ_PLUGIN",
            "SEND_MAIL_FOR_NEW_BOOKS",
            "USE_DYNAMIC_COVER",
        ]

        current_icon = CONF.get(
            "site_icon", "favicon_0"
        )  # favicon_0 means use current icon
        current_vip_quota = CONF.get(ENABLE_VIP_QUOTA_KEY, False)
        args = loader.SettingsLoader()
        args.clear()

        for key, val in data.items():
            if key.startswith("SOCIAL_AUTH"):
                if key.endswith("_KEY") or key.endswith("_SECRET"):
                    if not re.match(r'^[A-Za-z0-9_]+$', key):
                        continue
                    args[key] = val
            elif key in KEYS:
                args[key] = val

        # Check and set the favicon
        if "site_icon" not in args or not args["site_icon"]:
            args["site_icon"] = "favicon_0"

        if ENABLE_VIP_QUOTA_KEY not in args:
            args[ENABLE_VIP_QUOTA_KEY] = current_vip_quota
        if ENABLE_OPDS_SERVICE not in args:
            args[ENABLE_OPDS_SERVICE] = CONF.get(ENABLE_OPDS_SERVICE, True)
        if args.get(IMPORT_BY_INOTIFY, False):
            # 如果启用基于 inotify 的文件导入，不能默认删除文件
            args["REMOVE_IMPORTED_FILE"] = False

        args["META_ALL_SOURCES"] = META_ALL_SOURCES
        if "META_SELECTED_SOURCES" not in args:
            args["META_SELECTED_SOURCES"] = DEFAULT_META_SOURCES

        if args["site_icon"] != "favicon_0" and args["site_icon"] != current_icon:
            new_icon_path = CONF["static_path"] + "/logo/" + args["site_icon"] + ".ico"
            logging.info(_("Set new favicon: %s") % new_icon_path)
            if os.path.exists(new_icon_path):
                # Copy the new icon to the static directory
                static_icon_path = CONF["static_path"] + "/logo/" + "/favicon.ico"
                try:
                    shutil.copy(new_icon_path, static_icon_path)
                except Exception as e:
                    logging.info("Error: %s", str(e))
        # Check the douban_apikey if only number, letters, _ or -, and length <=48
        if "douban_apikey" in args:
            apikey = args["douban_apikey"]
            if apikey and not re.match(r"^[a-zA-Z0-9_-]{1,48}$", apikey):
                return {
                    "err": "params.douban_apikey.invalid",
                    "msg": _(
                        "豆瓣API密钥无效, 只能包含数字、字母、下划线或短横线，且长度不能超过48个字符"
                    ),
                }

        logic = SettingsSaverLogic()
        return logic.save_extra_settings(args)


class AdminInstall(BaseHandler):
    def should_be_invited(self):
        pass

    def should_be_installed(self):
        pass

    @js
    def get(self):
        err = "installed" if CONF.get("installed", True) else "not_intalled"
        return {"err": err}

    @js
    def post(self):
        if CONF.get("installed", True):
            return {"err": "installed", "msg": _("不可重复执行安装操作")}

        code = self.get_argument("code", "").strip()
        email = self.get_argument("email", "").strip().lower()
        title = self.get_argument("title", "").strip()
        language = self.get_argument("language", "").strip().lower()
        invite = self.get_argument("invite", "").strip()
        username = self.get_argument("username", "").strip().lower()
        password = self.get_argument("password", "").strip()
        if not username or not password or not email or not title:
            return {"err": "params.invalid", "msg": _("填写的内容有误")}
        if not re.match(Reader.RE_EMAIL, email):
            return {"err": "params.email.invalid", "msg": _("Email无效")}
        if (
            len(username) < 3
            or len(username) > 20
            or not re.match(Reader.RE_USERNAME, username)
        ):
            return {"err": "params.username.invalid", "msg": _("用户名无效")}
        if (
            len(password) < 6
            or len(password) > 20
            or not re.match(Reader.RE_PASSWORD, password)
        ):
            return {"err": "params.password.invalid", "msg": _("密码无效")}

        # 避免重复创建
        user = (
            self.sqlite_session.query(Reader)
            .filter(Reader.username == username)
            .first()
        )
        if not user:
            user = Reader()
            user.username = username
            user.name = username
            user.create_time = datetime.datetime.now()

        # 设置admin user的信息
        user.permission = ""  # Full permission
        user.email = email
        user.avatar = "reader.svg"
        user.update_time = datetime.datetime.now()
        user.access_time = datetime.datetime.now()
        user.active = True
        user.admin = True
        user.extra = {"kindle_email": ""}
        user.set_secure_password(password)
        try:
            user.save()
        except:
            logging.error(traceback.format_exc())
            return {"err": "db.error", "msg": _("系统异常，请重试或更换注册信息")}

        args = loader.SettingsLoader()
        args.clear()

        # inherit the basic path from system's config
        args["settings_path"] = CONF["settings_path"]

        # set options for China user
        # TODO: maybe it should be provided as an install options
        args["avatar_service"] = "https://cravatar.cn"
        args["BOOK_NAMES_FORMAT"] = "utf8"

        # set a random secret
        args["cookie_secret"] = "%s" % uuid.uuid1()
        args["site_title"] = title
        lang = normalize_language(language)
        args["site_language"] = lang if lang in ("zh", "en") else "zh"
        if invite == "true" and code:
            args["INVITE_MODE"] = True
            args["INVITE_CODE"] = code
        else:
            args["INVITE_MODE"] = False

        apply_localized_default_settings(args, args["site_language"])

        logic = SettingsSaverLogic()
        return logic.save_extra_settings(args)


class SSLHandlerLogic:
    def check_ssl_chain(self, crt_body, key_body):
        """return None if ok, else Err"""
        with tempfile.NamedTemporaryFile() as crt_file, tempfile.NamedTemporaryFile() as key_file:
            crt_file.write(crt_body)
            key_file.write(key_body)
            crt_file.flush()
            key_file.flush()
            return self.check_ssl_chain_files(crt_file.name, key_file.name)

    def check_ssl_chain_files(self, crt_file, key_file):
        ctx = ssl.SSLContext()
        try:
            ctx.load_cert_chain(crt_file, key_file)
        except ssl.SSLError as err:
            return err
        return None

    def save_files(self, crt_body, key_body):
        with open(CONF["ssl_crt_file"], "w+b") as f:
            f.write(crt_body)

        with open(CONF["ssl_key_file"], "w+b") as f:
            f.write(key_body)

    def nginx_check(self):
        return subprocess.run(["nginx", "-t"], check=True)

    def nginx_reload(self):
        return subprocess.run(["service", "nginx", "reload"], check=True)

    def run(self, ssl_crt, ssl_key):
        err = self.check_ssl_chain(ssl_crt, ssl_key)
        if err is not None:
            return {"err": "params.ssl_error", "msg": _("证书或密钥校验失败: %s" % err)}

        try:
            self.save_files(ssl_crt, ssl_key)
        except Exception as err:
            import traceback

            logging.error(traceback.format_exc())
            return {
                "err": "internal.ssl_save_error",
                "msg": _("证书存储失败: %s" % err),
            }

        # testing nginx config
        try:
            self.nginx_check()
        except subprocess.CalledProcessError as err:
            return {
                "err": "internal.nginx_test_error",
                "msg": _("NGINX配置异常: %s") % err,
            }

        # reload nginx config
        try:
            self.nginx_reload()
        except subprocess.CalledProcessError as err:
            return {
                "err": "internal.nginx_reload_error",
                "msg": _("NGINX重新加载配置异常: %s") % err,
            }

        return {"err": "ok", "msg": _("成功")}


class AdminSSL(BaseHandler):
    def get_upload_file(self):
        # for unittest mock
        ssl_crt = self.request.files["ssl_crt"][0]
        ssl_key = self.request.files["ssl_key"][0]
        return (ssl_crt["body"], ssl_key["body"])

    # TODO:
    #   - add GET interface to show the hostname/outdate of certifacates

    @js
    @auth
    def post(self):
        logic = SSLHandlerLogic()

        logging.error("got request")
        if not self.is_admin():
            return {"err": "permission", "msg": _("无权操作")}

        ssl_crt, ssl_key = self.get_upload_file()
        return logic.run(ssl_crt, ssl_key)


class AdminBookList(BaseHandler):
    @js
    @is_admin
    def get(self):
        if not self.admin_user:
            return {"err": "permission.not_admin", "msg": _("当前用户非管理员")}

        num = max(10, int(self.get_argument("num", 20)))
        page = max(0, int(self.get_argument("page", 1)) - 1)
        sort = self.get_argument("sort", "id")
        desc = self.get_argument("desc", "desc") == "true"
        search = self.get_argument("search", "").strip()
        book_type = int(self.get_argument("type", -1))
        logging.debug(
            "num=%d, page=%d, sort=%s, desc=%s, book_type=%d"
            % (num, page, sort, desc, book_type)
        )
        if book_type >= 0 and book_type <= BOOK_TYPE_PHYSICAL:
            book_type_query = f"{"not" if book_type == BOOK_TYPE_EBOOK else ""} {CALIBRE_COLUMN_BOOK_TYPE}:={BOOK_TYPE_PHYSICAL}"
            if search:
                search = f"({search}) AND {book_type_query}"
            else:
                search = book_type_query
            logging.debug("Adjusted search query: %s" % search)
        self.calibre_db.sort(field=sort, ascending=(not desc))
        start = page * num
        end = start + num
        all_ids = list(self.calibre_db_cache.search(search))
        total = len(all_ids)

        # sort by id
        if sort == "id":
            all_ids.sort(reverse=desc)

        books = []
        page_ids = all_ids[start:end]
        if page_ids:
            books = [
                SimpleBookFormatter(b, self.cdn_url).format()
                for b in self.get_books(ids=page_ids)
            ]

        return {"err": "ok", "items": books, "total": total}


class AdminBookFill(BaseHandler):
    @js
    @is_admin
    def get(self):
        s = AutoFillService()
        status = s.status()
        return {
            "err": "ok",
            "msg": _("ok"),
            "status": {
                "total": status["count_total"],
                "skip": status["count_skip"],
                "done": status["count_done"],
                "fail": status["count_fail"],
                "running": status["is_running"],
            },
        }

    @js
    @is_admin
    def post(self):
        req = tornado.escape.json_decode(self.request.body)
        idlist = req["idlist"]
        if not idlist:
            return {"err": "params.error", "msg": _("参数错误")}

        # 检查是否有正在运行的任务
        filling_status = AutoFillService().status()
        if filling_status["is_running"]:
            return {"err": "task.running", "msg": _("有任务正在运行中，请稍后再试")}

        force = False
        if idlist == "all":
            idlist = list(self.calibre_db_cache.all_book_ids())
        elif isinstance(idlist, list):
            for bid in idlist:
                if not isinstance(bid, int):
                    return {"err": "params.error.idlist", "msg": _("idlist参数错误")}
            force = True
        else:
            return {"err": "params.error.idlist", "msg": _("idlist参数错误")}

        AutoFillService().auto_fill_all(idlist, force=force)
        return {"err": "ok", "msg": _("任务启动成功！请耐心等待，稍后再来刷新页面")}


class AdminBookAIFill(BaseHandler):
    """Admin API: 批量使用 AI 更新指定书籍的信息"""

    @js
    @is_admin
    def get(self):
        status = AIFillInfoService().status()
        return {
            "err": "ok",
            "status": {
                "total": status["count_total"],
                "skip": status["count_skip"],
                "done": status["count_done"],
                "fail": status["count_fail"],
                "running": status["is_running"],
            },
        }

    @js
    @is_admin
    def post(self):
        req = tornado.escape.json_decode(self.request.body)
        idlist = req.get("idlist", [])
        if not idlist:
            return {"err": "params.error", "msg": _("参数错误")}

        filling_status = AIFillInfoService().status()
        if filling_status["is_running"]:
            return {"err": "task.running", "msg": _("有 AI 任务正在运行中，请稍后再试")}

        if idlist == "all":
            idlist = list(self.calibre_db_cache.all_book_ids())
        elif isinstance(idlist, list):
            for bid in idlist:
                if not isinstance(bid, int):
                    return {"err": "params.error.idlist", "msg": _("参数错误")}
        else:
            return {"err": "params.error.idlist", "msg": _("参数错误")}

        AIFillInfoService().fill_all(idlist)
        return {"err": "ok", "msg": _("AI 更新任务已启动，请耐心等待")}


class AdminUpdateAllMeta(BaseHandler):
    """Admin API: 批量更新所有书籍的元信息"""
    @js
    @is_admin
    def post(self):
        update_status = MetaDataUpdateService().status()
        if update_status["is_running"]:
            return {"err": "task.running", "msg": _("有更新任务正在运行中，请稍后再试")}

        idlist = list(self.calibre_db_cache.all_book_ids())
        MetaDataUpdateService().update_metadata(self.current_user.id, idlist)
        return {"err": "ok", "msg": _("批量更新书籍元信息任务已启动，右上角可以查看进度")}


class AdminUpdateDynamicCover(BaseHandler):
    """Admin API: 批量更新所有书籍的动态封面"""

    @js
    @is_admin
    def post(self):
        update_status = DynamicCoverUpdateService().status()
        if update_status["is_running"]:
            return {"err": "task.running", "msg": _("有更新任务正在运行中，请稍后再试")}

        req = tornado.escape.json_decode(self.request.body)
        idlist = req["idlist"]
        if not idlist:
            return {"err": "params.error", "msg": _("参数错误")}

        if idlist == "all":
            idlist = list(self.calibre_db_cache.all_book_ids())
        elif isinstance(idlist, list):
            for bid in idlist:
                if not isinstance(bid, int):
                    return {"err": "params.error.idlist", "msg": _("idlist参数错误")}

        DynamicCoverUpdateService().update_cover(self.current_user.id, idlist, dynamic_cover=True)
        return {"err": "ok", "msg": _("批量更新书籍动态封面任务已启动，右上角可以查看进度")}


class AdminResetCover(BaseHandler):
    """Admin API: 批量重置所有书籍的动态封面"""

    @js
    @is_admin
    def post(self):
        update_status = DynamicCoverUpdateService().status()
        if update_status["is_running"]:
            return {"err": "task.running", "msg": _("有更新任务正在运行中，请稍后再试")}

        req = tornado.escape.json_decode(self.request.body)
        idlist = req["idlist"]
        if not idlist:
            return {"err": "params.error", "msg": _("参数错误")}

        if idlist == "all":
            idlist = list(self.calibre_db_cache.all_book_ids())
        elif isinstance(idlist, list):
            for bid in idlist:
                if not isinstance(bid, int):
                    return {"err": "params.error.idlist", "msg": _("idlist参数错误")}

        DynamicCoverUpdateService().update_cover(self.current_user.id, idlist, dynamic_cover=False)
        return {"err": "ok", "msg": _("批量更新书籍动态封面任务已启动，右上角可以查看进度")}


class AdminBookConvert(BaseHandler):
    """Admin API: 批量转换Kindle格式为EPUB"""

    @js
    @is_admin
    def get(self):
        status = BatchConvertService().status()
        return {
            "err": "ok",
            "status": {
                "total": status["count_total"],
                "skip": status["count_skip"],
                "done": status["count_done"],
                "fail": status["count_fail"],
                "running": status["is_running"],
            },
        }

    @js
    @is_admin
    def post(self):
        req = tornado.escape.json_decode(self.request.body)
        idlist = req.get("idlist", [])
        convert_status = BatchConvertService().status()
        if convert_status["is_running"]:
            return {"err": "task.running", "msg": _("有转换任务正在运行中，请稍后再试")}

        if idlist:
            if not isinstance(idlist, list):
                return {
                    "err": "params.error.idlist",
                    "msg": _("参数错误, 未指定正确的id列表"),
                }
            for bid in idlist:
                if not isinstance(bid, int):
                    return {
                        "err": "params.error.idlist",
                        "msg": _("参数错误, id列表中包含无效的id"),
                    }

        if not idlist:
            idlist = list(self.calibre_db_cache.all_book_ids())

        BatchConvertService().convert_all(self.current_user.id, idlist)
        return {"err": "ok", "msg": _("Kindle转EPUB任务已启动，右上角可以查看进度")}


class AdminBookUpdateTitleSort(BaseHandler):
    """Admin API: 批量更新title_sort为拼音排序"""

    @js
    @is_admin
    def get(self):
        status = BatchTitleSortUpdateService().status()
        return {
            "err": "ok",
            "status": {
                "total": status["count_total"],
                "skip": status["count_skip"],
                "done": status["count_done"],
                "fail": status["count_fail"],
                "running": status["is_running"],
            },
        }

    @js
    @is_admin
    def post(self):
        req = tornado.escape.json_decode(self.request.body)
        idlist = req.get("idlist", [])
        update_status = BatchTitleSortUpdateService().status()
        if update_status["is_running"]:
            return {"err": "task.running", "msg": _("有更新任务正在运行中，请稍后再试")}

        if idlist:
            if not isinstance(idlist, list):
                return {
                    "err": "params.error.idlist",
                    "msg": _("参数错误, 未指定正确的id列表"),
                }
            for bid in idlist:
                if not isinstance(bid, int):
                    return {
                        "err": "params.error.idlist",
                        "msg": _("参数错误, id列表中包含无效的id"),
                    }

        if not idlist:
            idlist = list(self.calibre_db_cache.all_book_ids())

        BatchTitleSortUpdateService().update_all(self.current_user.id, idlist)
        return {"err": "ok", "msg": _("更新书名信息任务已启动，右上角可以查看进度")}


class AdminBookbarnTokenApply(BaseHandler):
    @js
    @is_admin
    def post(self):
        bookbarn = BookBarnClient()
        try:
            token = bookbarn.applyToken(os=self.get_os())
            return {"err": "ok", "msg": _("Token申请成功"), "token": token}
        except Exception as e:
            logging.error(traceback.format_exc())
            return {"err": "params.error", "msg": _("Token申请失败: %s") % str(e)}


class AdminDeleteBooks(BaseHandler):
    @js
    @is_admin
    def post(self):
        req = tornado.escape.json_decode(self.request.body)
        idlist = req.get("idlist", [])
        if not idlist:
            return {"err": "params.error", "msg": _("参数错误")}

        for book_id in idlist:
            try:
                AudioUtils.clear_audio(book_id)
                book = self.get_book(book_id)
                book_id = book["id"]
                self.calibre_db.delete_book(book_id)
            except Exception as err:
                logging.error(_("执行异常: %s"), err)

        # Delete all Items whose id in idList
        try:
            items = self.sqlite_session.query(Item).filter(Item.book_id.in_(idlist)).all()
            for item in items:
                self.sqlite_session.delete(item)
            self.sqlite_session.commit()
        except Exception as e:
            logging.error(f"删除书籍的Item记录失败: {e}")

        return {"err": "ok", "msg": _("删除成功")}


class AdminSaveMeta(BaseHandler):
    @js
    @is_admin
    def post(self):
        req = tornado.escape.json_decode(self.request.body)
        idlist = req.get("idlist", [])
        if not idlist:
            return {"err": "params.error", "msg": _("参数错误")}

        for bid in idlist:
            if not isinstance(bid, int):
                return {"err": "params.error.idlist", "msg": _("idlist参数错误")}

        SaveMetaToFilesService().save_metadata(self.current_user.id, idlist)
        return {"err": "ok", "msg": _("同步元数据到文件的任务已经开始执行，在右上角可以查看进度")}


class ClearInvalidItems(BaseHandler):
    """Admin API: 清理在Calibre中已不存在的无效Items记录"""

    @js
    @is_admin
    def post(self):
        try:
            all_calibre_ids = set(self.calibre_db_cache.all_book_ids())
            items = self.sqlite_session.query(Item).all()
            invalid_items = [item for item in items if item.book_id not in all_calibre_ids]
            count = len(invalid_items)
            for item in invalid_items:
                logging.info("[CLEAR]Invalid item with book_id=%s", item.book_id)
                self.sqlite_session.delete(item)
            self.sqlite_session.commit()
            return {"err": "ok", "msg": _("已清理 %d 条无效图书记录") % count, "count": count}
        except Exception as e:
            logging.error("[CLEAR]Failed to clear invalid items: %s", e)
            return {"err": "error", "msg": _("清理失败: %s") % str(e)}


class AudioTestConnection(BaseHandler):
    @js
    @auth
    async def post(self):
        try:
            data = tornado.escape.json_decode(self.request.body)
            proxy = data.get("proxy", None)
            use_bookbarn_proxy = data.get("use_bookbarn_proxy", False)
            if use_bookbarn_proxy:
                return {"err": "ok", "msg": _("EdgeTTS 连接测试成功")}

            if not proxy:
                proxy = None
            else:
                if not re.match(r"^https?://", proxy, re.IGNORECASE) or len(proxy) < 10:
                    return {"err": "params.error.proxy", "msg": _("无效的代理地址")}

            import edge_tts

            voices = await edge_tts.list_voices(proxy=proxy)
            if not voices:
                return {"err": "error", "msg": _("无法获得可用的语音选项")}
            return {"err": "ok", "msg": _("EdgeTTS 连接测试成功")}
        except Exception as e:
            logging.error(f"EdgeTTS 连接测试失败: {e}")
            return {"err": "error", "msg": _("EdgeTTS 连接测试失败: %s") % str(e)}


class ReleaseNotes(BaseHandler):
    @js
    def get(self):
        last_revsion = CONF.get("LAST_REVISION", "")
        force = self.get_argument("force", "false") == "true"
        logging.info("Current version: %s, Last revision: %s", VERSION, last_revsion)
        if last_revsion != VERSION:
            args = loader.SettingsLoader()
            args["LAST_REVISION"] = VERSION
            logic = SettingsSaverLogic()
            logic.save_extra_settings(args)

        if last_revsion != VERSION or force:
            # Load the release notes from the public folder
            release_note_path = CONF["static_path"] + "/static/release_notes.txt"
            notes = ""
            if os.path.exists(release_note_path):
                with open(release_note_path, "r", encoding="utf-8") as f:
                    notes = f.read()
            else:
                logging.error("Release note file not found")
            return {"err": "ok", "msg": notes}
        else:
            return {"err": "ok", "msg": ""}


class AdminTokenHandler(BaseHandler):
    @js
    @auth
    def get(self):
        """Generate and return a new MCP token"""
        if not self.admin_user:
            return {"err": "permission.not_admin", "msg": _("当前用户非管理员")}

        # Generate a random 32-character token using secure random
        import secrets
        import string

        chars = string.ascii_letters + string.digits
        token = "".join(secrets.choice(chars) for _ in range(32))

        return {"err": "ok", "token": token}


class AdminRunningTasks(BaseHandler):
    @js
    def get(self):
        if not self.current_user:
            return {"err": "ok", "tasks": [], "msg": _("未登录")}

        # If not admin user, return empty list
        if not self.admin_user:
            return {"err": "ok", "tasks": [], "msg": _("非管理员用户")}

        # Get all running tasks
        all_tasks = BackgroundService().get_running_tasks()
        running_tasks = [
            task
            for task in all_tasks
            if task["status"] == BackgroundTask.STATUS_RUNNING
        ]

        # 一起返回user messages, 可以及时显示到前端
        messages = self.current_user.messages
        rsp_messages = []
        if messages:
            messages.sort(key=lambda x: x.create_time, reverse=True)
            for msg in messages:
                if not msg.unread:
                    continue
                m = {
                    "id": msg.id,
                    "title": msg.title,
                    "status": msg.status,
                    "create_time": msg.create_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "data": msg.data,
                }
                rsp_messages.append(m)
        return {"err": "ok", "tasks": running_tasks, "messages": rsp_messages}


class AdminTrashSize(BaseHandler):
    @js
    @auth
    def get(self):
        if not self.admin_user:
            return {"err": "ok", "sizes": {}, "msg": _("非管理员用户")}
        sizes = TrashManager.get_trash_sizes()
        return {"err": "ok", "sizes": sizes}


class AdminTrashClear(BaseHandler):
    @js
    @auth
    def post(self):
        if not self.admin_user:
            return {
                "err": "permission.not_admin",
                "msg": _("当前用户非管理员, 无权操作"),
            }
        errors = TrashManager.clear_trashs()
        if errors:
            return {"err": "error", "msg": _("清理失败: %s") % "; ".join(errors)}
        return {"err": "ok", "msg": _("已清理Calibre回收站及上传目录")}


class AdminStamp(BaseHandler):
    @js
    @auth
    def get(self):
        """获取图章图片"""
        if not self.admin_user:
            return {"err": "permission.not_admin", "msg": _("当前用户非管理员, 无权操作")}

        if not CONF.get("ENABLE_STAMP_FEATURE", False):
            return {"err": "feature.disabled", "msg": _("图章功能未启用")}

        stamp_path = os.path.join(CONF["static_path"], "logo", "stamp.png")
        if os.path.exists(stamp_path):
            return {"err": "ok", "exists": True}
        return {"err": "ok", "exists": False}

    @auth
    def post(self):
        """上传图章图片"""
        if not self.admin_user:
            self.set_status(403)
            return self.write({"err": "permission.not_admin", "msg": _("当前用户非管理员, 无权操作")})

        if 'file' not in self.request.files:
            self.set_status(400)
            return self.write({"err": "params.missing", "msg": _("未找到上传的文件")})

        file_info = self.request.files['file'][0]
        filename = file_info['filename']
        content = file_info['body']

        # 验证文件格式
        if not filename.lower().endswith('.png'):
            self.set_status(400)
            return self.write({"err": "file.invalid_format", "msg": _("只支持PNG格式的图片")})

        # 验证文件大小
        max_size = 128 * 1024  # 128KB
        if len(content) > max_size:
            self.set_status(400)
            return self.write({"err": "file.too_large", "msg": _("图片文件大小不能超过128KB")})

        # 验证图片尺寸
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(content))
            if img.width > 480 or img.height > 480:
                self.set_status(400)
                return self.write({"err": "file.dimension_too_large", "msg": _("图片尺寸不能超过480x480像素")})
        except Exception as e:
            logging.error(f"Failed to validate image: {e}")
            self.set_status(400)
            return self.write({"err": "file.invalid", "msg": _("无效的图片文件")})

        # 保存图片
        try:
            logo_dir = os.path.join(CONF["static_path"], "logo")
            os.makedirs(logo_dir, exist_ok=True)
            stamp_path = os.path.join(logo_dir, "stamp.png")
            stamp_path_abs = os.path.abspath(stamp_path)
            with open(stamp_path_abs, 'wb+') as f:
                f.write(content)
            self.write({"err": "ok", "msg": _("图章图片上传成功"), "data": {"url": self.cdn_url + "/static/logo/stamp.png"}})
        except Exception as e:
            logging.error(f"Failed to save stamp image: {e}")
            self.set_status(500)
            self.write({"err": "file.save_failed", "msg": _("保存图片失败: %s") % str(e)})


class LibraryStats(BaseHandler):
    _cache_data = None
    _cache_time = 0

    def _get_stats(self):
        # 获取当前月份和年份
        now = datetime.datetime.now()
        current_year = now.year
        current_month = now.month

        all_book_ids = list(self.calibre_db_cache.all_book_ids())
        total_books = len(all_book_ids)
        ebook_count = 0
        physical_count = 0
        month_ebook_count = 0
        month_physical_count = 0

        if all_book_ids:
            physical_count = self.get_physical_books_count()
            ebook_count = total_books - physical_count

            month_ebook_count = (
                self.sqlite_session.query(Item)
                .filter(
                    Item.book_type == 0,
                    extract("year", Item.create_time) == current_year,
                    extract("month", Item.create_time) == current_month,
                )
                .count()
            )

            # 本月新增实体书数量 (加总book_count)
            month_physical_books = (
                self.sqlite_session.query(func.sum(Item.book_count))
                .filter(
                    Item.book_type == 1,
                    extract("year", Item.create_time) == current_year,
                    extract("month", Item.create_time) == current_month,
                )
                .scalar()
            )
            month_physical_count = month_physical_books if month_physical_books else 0

        return {
            "total_books": total_books,
            "ebook_count": ebook_count,
            "physical_count": physical_count,
            "month_ebook_count": month_ebook_count,
            "month_physical_count": month_physical_count,
        }

    @js
    def get(self):
        """获取书库统计信息"""
        now = datetime.datetime.now()
        current_year = now.year
        current_month = now.month

        stats = None
        # check cache
        if time.time() - LibraryStats._cache_time < 30 and LibraryStats._cache_data:
            stats = LibraryStats._cache_data
        else:
            try:
                stats = self._get_stats()
                LibraryStats._cache_data = stats
                LibraryStats._cache_time = time.time()
            except Exception as e:
                logging.error("Failed to get library stats: %s", e)
                if LibraryStats._cache_data:
                    stats = LibraryStats._cache_data
                else:
                    # fallback to empty stats
                    stats = {
                        "total_books": 0,
                        "ebook_count": 0,
                        "physical_count": 0,
                        "month_ebook_count": 0,
                        "month_physical_count": 0,
                    }

        stats["current_year"] = current_year
        stats["current_month"] = current_month
        return {"err": "ok", "stats": stats}


class AdminSyslog(BaseHandler):
    MAX_LINES = 1500

    @js
    @is_admin
    def get(self):
        try:
            if not os.path.exists(LOG_PATH):
                return {"err": "ok", "lines": []}
            with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            return {
                "err": "ok",
                "lines": [line.rstrip("\n") for line in lines[-self.MAX_LINES :]],
                "href": self.cdn_url + "/api/admin/syslog/download",
            }
        except Exception as e:
            logging.error("Failed to read syslog: %s", e)
            return {"err": "failed", "msg": str(e)}


class AdminSyslogDownload(BaseHandler):
    @is_admin
    def get(self):
        today = datetime.datetime.now().strftime("%Y_%m_%d")
        filename = f"talebook_log_{today}.log"
        try:
            if not os.path.exists(LOG_PATH):
                content = b""
            else:
                with open(LOG_PATH, "rb") as f:
                    content = f.read()
        except Exception as e:
            logging.error("Failed to read syslog for download: %s", e)
            self.set_status(500)
            self.finish(str(e))
            return
        self.set_header("Content-Type", "text/plain; charset=utf-8")
        self.set_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.set_header("Content-Length", len(content))
        self.finish(content)


def routes():
    return [
        (r"/api/admin/ssl", AdminSSL),
        (r"/api/admin/users", AdminUsers),
        (r"/api/admin/install", AdminInstall),
        (r"/api/admin/settings", AdminSettings),
        (r"/api/admin/testmail", AdminTestMail),
        (r"/api/admin/book/list", AdminBookList),
        (r"/api/admin/book/fill", AdminBookFill),
        (r"/api/admin/book/aifill", AdminBookAIFill),
        (r"/api/admin/book/kindleconvert", AdminBookConvert),
        (r"/api/admin/book/update_title_sort", AdminBookUpdateTitleSort),
        (r"/api/admin/bookbarn/token/apply", AdminBookbarnTokenApply),
        (r"/api/admin/books/delete", AdminDeleteBooks),
        (r"/api/admin/books/save_meta", AdminSaveMeta),
        (r"/api/admin/clear/invalid/items", ClearInvalidItems),
        (r"/api/admin/audio/test", AudioTestConnection),
        (r"/api/admin/release/notes", ReleaseNotes),
        (r"/api/admin/token", AdminTokenHandler),
        (r"/api/admin/tasks/running", AdminRunningTasks),
        (r"/api/admin/trash/size", AdminTrashSize),
        (r"/api/admin/trash/clear", AdminTrashClear),
        (r"/api/admin/stamp", AdminStamp),
        (r"/api/library/stats", LibraryStats),
        (r"/api/admin/syslog", AdminSyslog),
        (r"/api/admin/book/update_all_meta", AdminUpdateAllMeta),
        (r"/api/admin/book/update_all_dynamic_cover", AdminUpdateDynamicCover),
        (r"/api/admin/book/reset_cover", AdminResetCover),
        (r"/api/admin/syslog/download", AdminSyslogDownload),
    ]
