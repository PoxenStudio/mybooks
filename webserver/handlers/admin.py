#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import datetime
import hashlib
import logging
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import traceback
import uuid
from gettext import gettext as _

import tornado

from webserver import loader
from webserver.services.autofill import AutoFillService
from webserver.services.ai_fillinfo import AIFillInfoService
from webserver.services.batch_convert import BatchConvertService
from webserver.services.mail import MailService
from webserver.services.book_barn import BookBarnClient
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver.handlers.base import BaseHandler, auth, js, is_admin
from webserver.models import Reader
from webserver.utils import SimpleBookFormatter
from webserver.version import VERSION
from webserver.handlers.audio import AudioUtils
from webserver.constants import CALIBRE_COLUMN_BOOK_TYPE, BOOK_TYPE_PHYSICAL, BOOK_TYPE_EBOOK, ENABLE_OPDS_SERVICE

CONF = loader.get_settings()
USER_UPDATE_TS_MAP = {}
ENABLE_VIP_QUOTA_KEY = "ENABLE_VIP_QUOTA"


class AdminUsers(BaseHandler):
    @js
    @auth
    def get(self):
        if not self.admin_user:
            return {"err": "permission.not_admin", "msg": _(u"当前用户非管理员")}

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
            has_social_account = hasattr(user, "social_auth") and user.social_auth.count() > 0
            user_provider = user.social_auth[0].provider if has_social_account else "register"
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
                "create_time": user.create_time.strftime("%Y-%m-%d %H:%M:%S") if user.create_time else "N/A",
                "update_time": user.update_time.strftime("%Y-%m-%d %H:%M:%S") if user.update_time else "N/A",
                "access_time": user.access_time.strftime("%Y-%m-%d %H:%M:%S") if user.access_time else "N/A",
            }

            if enable_vip_quota:
                d["vipquota"] = user.vipquota or 0
                d["vip_expire"] = user.vipexpire.strftime("%Y-%m-%d") if user.vipexpire else ""

            for attr in dir(user):
                if attr.startswith("can_"):
                    d[attr] = getattr(user, attr)()

            # Update the user statistic count
            need_update = False
            ts = USER_UPDATE_TS_MAP.get(user.id, 0)
            if not ts or (datetime.datetime.now() - ts).total_seconds() > 3600:
                need_update = True
                USER_UPDATE_TS_MAP[user.id] = datetime.datetime.now()
            if need_update or "upload_history_count" not in user.extra:
                d["extra"]["upload_history_count"] = self.get_user_upload_cnt(user.id)
            else:
                d["extra"]["upload_history_count"] = user.extra.get("upload_history_count", 0)
            items.append(d)
        return {"err": "ok", "users": {"items": items, "total": total}}

    @js
    @auth
    def post(self):
        if not self.admin_user:
            return {"err": "permission.not_admin", "msg": _(u"当前用户非管理员")}
        data = tornado.escape.json_decode(self.request.body)
        uid = data.get("id", None)
        if not uid:
            return {"err": "params.invalid", "msg": _(u"参数错误")}
        del data["id"]
        if not data:
            return {"err": "params.fields.invalid", "msg": _(u"用户配置项参数错误")}
        user = self.sqlite_session.query(Reader).filter(Reader.id == uid).first()
        if not user:
            return {"err": "params.user.not_exist", "msg": _(u"用户ID错误")}
        if "active" in data:
            user.active = data["active"]

        if "admin" in data:
            user.admin = data["admin"]

        if user.admin is False and self.user_id() == user.id:
            return {"err": "params.user.invalid", "msg": _("不允许取消自己的管理员权限")}

        if data.get("delete", "") == user.username:
            if self.user_id() == user.id:
                return {"err": "params.user.invalid", "msg": _("不允许删除自己")}

            self.sqlite_session.query(Reader).filter(Reader.id == user.id).delete()
            self.sqlite_session.commit()
            return {"err": "ok", "msg": _("删除成功")}

        p = data.get("permission", "")
        if not isinstance(p, str):
            return {"err": "params.permission.invalid", "msg": _(u"权限参数不对")}
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
        mail_subject = _(u"Calibre功能验证邮件")
        mail_body = _(u"这是一封测试邮件，验证邮件参数是否配置正确。")

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
            return {"err": "ok", "msg": _(u"发送成功")}
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
    def update_nuxtjs_env(self):
        # update nuxtjs .env file
        nuxtjs_env = """
TITLE="%(site_title)s"
TITLE_TEMPLATE="%%s | %(site_title)s"
""" % CONF
        logging.info("google_analytics_id is %s" % CONF.get("google_analytics_id", ""))
        if len(CONF.get("google_analytics_id", "").strip()) > 0:
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
            return {"err": "file.permission", "msg": _(u"更新nuxtjs配置文件失败！请确保文件的权限为可写入！")}

        # don't update running environment for now
        args["installed"] = True
        try:
            args.dumpfile()
        except:
            logging.error(traceback.format_exc())
            return {"err": "file.permission", "msg": _(u"更新磁盘配置文件失败！请确保配置文件的权限为可写入！")}

        # ok, it's safe to update current environment
        CONF["installed"] = True
        return {"err": "ok", "rsp": args}


class AdminSettings(BaseHandler):
    @js
    @auth
    def get(self):
        if not self.admin_user:
            return {"err": "permission", "msg": _(u"无权访问此接口")}

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
            CONF["INDEX_PAGE_TYPE"] = "index"  # 默认首页, 可能的值包括index, all, categories三类
        if CONF.get("DEFAULT_PAGE_SIZE", -1) == -1:
            CONF["DEFAULT_PAGE_SIZE"] = 60  # 默认每页显示60本书

        CONF["site_icon"] = "favicon_0"  # default icon, means use current favicon.ico

        sns = [
            {"value": "qq", "text": "QQ", "link": "https://connect.qq.com/"},
            {
                "value": "amazon",
                "text": "Amazon",
                "link": "https://developer.amazon.com/zh/docs/login-with-amazon/web-docs.html",
            },
            {
                "value": "github",
                "text": "Github",
                "link": "https://github.com/settings/applications/new",
            },
            {
                "value": "weibo",
                "text": u"微博",
                "link": "http://open.weibo.com/developers",
            },
            {
                "value": "wechat",
                "text": u"微信",
                "link": "https://developers.weixin.qq.com/doc/offiaccount/OA_Web_Apps/Wechat_webpage_authorization.html",
            },
        ]
        return {"err": "ok", "settings": CONF, "sns": sns, "site_url": self.site_url}

    @js
    @auth
    def post(self):
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
            "MAIN_PAGE_RANDOM_COUNT",
            "MAIN_PAGE_RECENT_COUNT",
            "INDEX_PAGE_TYPE",
            "DEFAULT_PAGE_SIZE",
            "WEBDAV_SYNC_FOLDER",
            "ENABLE_AUDIO_CONVERSION_LOG",
            "ENABLE_OPDS_SERVICE"
        ]

        current_icon = CONF.get("site_icon", "favicon_0")  # favicon_0 means use current icon
        current_vip_quota = CONF.get(ENABLE_VIP_QUOTA_KEY, False)
        args = loader.SettingsLoader()
        args.clear()

        for key, val in data.items():
            if key.startswith("SOCIAL_AUTH"):
                if key.endswith("_KEY") or key.endswith("_SECRET"):
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
                return {"err": "params.douban_apikey.invalid", "msg": _(u"豆瓣API密钥无效, 只能包含数字、字母、下划线或短横线，且长度不能超过48个字符")}

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
            return {"err": "installed", "msg": _(u"不可重复执行安装操作")}

        code = self.get_argument("code", "").strip()
        email = self.get_argument("email", "").strip().lower()
        title = self.get_argument("title", "").strip()
        invite = self.get_argument("invite", "").strip()
        username = self.get_argument("username", "").strip().lower()
        password = self.get_argument("password", "").strip()
        if not username or not password or not email or not title:
            return {"err": "params.invalid", "msg": _(u"填写的内容有误")}
        if not re.match(Reader.RE_EMAIL, email):
            return {"err": "params.email.invalid", "msg": _(u"Email无效")}
        if len(username) < 3 or len(username) > 20 or not re.match(Reader.RE_USERNAME, username):
            return {"err": "params.username.invalid", "msg": _(u"用户名无效")}
        if len(password) < 6 or len(password) > 20 or not re.match(Reader.RE_PASSWORD, password):
            return {"err": "params.password.invalid", "msg": _(u"密码无效")}

        # 避免重复创建
        user = self.sqlite_session.query(Reader).filter(Reader.username == username).first()
        if not user:
            user = Reader()
            user.username = username
            user.name = username
            user.create_time = datetime.datetime.now()

        # 设置admin user的信息
        user.email = email
        user.avatar = CONF["avatar_service"] + "/avatar/" + hashlib.md5(email.encode("UTF-8")).hexdigest()
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
            return {"err": "db.error", "msg": _(u"系统异常，请重试或更换注册信息")}

        args = loader.SettingsLoader()
        args.clear()

        # inherit the basic path from system's config
        args["settings_path"] = CONF["settings_path"]

        # set options for China user
        # TODO: maybe it should be provided as an install options
        args["avatar_service"] = "https://cravatar.cn"
        args["BOOK_NAMES_FORMAT"] = "utf8"

        # set a random secret
        args["cookie_secret"] = u"%s" % uuid.uuid1()
        args["site_title"] = title
        if invite == "true" and code:
            args["INVITE_MODE"] = True
            args["INVITE_CODE"] = code
        else:
            args["INVITE_MODE"] = False

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
            return {"err": "params.ssl_error", "msg": _(u"证书或密钥校验失败: %s" % err)}

        try:
            self.save_files(ssl_crt, ssl_key)
        except Exception as err:
            import traceback

            logging.error(traceback.format_exc())
            return {"err": "internal.ssl_save_error", "msg": _(u"证书存储失败: %s" % err)}

        # testing nginx config
        try:
            self.nginx_check()
        except subprocess.CalledProcessError as err:
            return {"err": "internal.nginx_test_error", "msg": _(u"NGINX配置异常: %s") % err}

        # reload nginx config
        try:
            self.nginx_reload()
        except subprocess.CalledProcessError as err:
            return {"err": "internal.nginx_reload_error", "msg": _(u"NGINX重新加载配置异常: %s") % err}

        return {"err": "ok", "msg": "Succeed"}


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
            return {"err": "permission", "msg": _(u"无权操作")}

        ssl_crt, ssl_key = self.get_upload_file()
        return logic.run(ssl_crt, ssl_key)


class AdminBookList(BaseHandler):
    @js
    @is_admin
    def get(self):
        if not self.admin_user:
            return {"err": "permission.not_admin", "msg": _(u"当前用户非管理员")}

        num = max(10, int(self.get_argument("num", 20)))
        page = max(0, int(self.get_argument("page", 1)) - 1)
        sort = self.get_argument("sort", "id")
        desc = self.get_argument("desc", "desc") == "true"
        search = self.get_argument("search", "").strip()
        book_type = int(self.get_argument("type", -1))
        logging.debug("num=%d, page=%d, sort=%s, desc=%s, book_type=%d" % (num, page, sort, desc, book_type))
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
            books = [SimpleBookFormatter(b, self.cdn_url).format() for b in self.get_books(ids=page_ids)]

        return {"err": "ok", "items": books, "total": total}


class AdminBookFill(BaseHandler):
    @js
    @is_admin
    def get(self):
        s = AutoFillService()
        status = s.status()
        return {
            "err": "ok",
            "msg": "ok",
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
            return {"err": "params.error", "msg": _(u"参数错误")}

        # 检查是否有正在运行的任务
        filling_status = AutoFillService().status()
        if filling_status["is_running"]:
            return {"err": "task.running", "msg": _(u"有任务正在运行中，请稍后再试")}

        if idlist == "all":
            idlist = list(self.calibre_db_cache.all_book_ids())
        elif isinstance(idlist, list):
            for bid in idlist:
                if not isinstance(bid, int):
                    return {"err": "params.error.idlist", "msg": _(u"idlist参数错误")}
        else:
            return {"err": "params.error.idlist", "msg": _(u"idlist参数错误")}

        AutoFillService().auto_fill_all(idlist)
        return {"err": "ok", "msg": _(u"任务启动成功！请耐心等待，稍后再来刷新页面")}


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
            return {"err": "params.error", "msg": _(u"参数错误")}

        filling_status = AIFillInfoService().status()
        if filling_status["is_running"]:
            return {"err": "task.running", "msg": _(u"有 AI 任务正在运行中，请稍后再试")}

        if idlist == "all":
            idlist = list(self.calibre_db_cache.all_book_ids())
        elif isinstance(idlist, list):
            for bid in idlist:
                if not isinstance(bid, int):
                    return {"err": "params.error.idlist", "msg": _(u"参数错误")}
        else:
            return {"err": "params.error.idlist", "msg": _(u"参数错误")}

        AIFillInfoService().fill_all(idlist)
        return {"err": "ok", "msg": _(u"AI 更新任务已启动，请耐心等待")}


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
            return {"err": "task.running", "msg": _(u"有转换任务正在运行中，请稍后再试")}

        if idlist:
            if not isinstance(idlist, list):
                return {"err": "params.error.idlist", "msg": _(u"参数错误, 未指定正确的id列表")}
            for bid in idlist:
                if not isinstance(bid, int):
                    return {"err": "params.error.idlist", "msg": _(u"参数错误, id列表中包含无效的id")}

        if not idlist:
            idlist = list(self.calibre_db_cache.all_book_ids())

        BatchConvertService().convert_all(self.current_user.id, idlist)
        return {"err": "ok", "msg": _(u"Kindle转EPUB任务已启动，左上角可以查看进度")}


class AdminBookbarnTokenApply(BaseHandler):
    @js
    @is_admin
    def post(self):
        bookbarn = BookBarnClient()
        try:
            token = bookbarn.applyToken(os=self.get_os())
            return {"err": "ok", "msg": _(u"Token申请成功"), "token": token}
        except Exception as e:
            logging.error(traceback.format_exc())
            return {"err": "params.error", "msg": _(u"Token申请失败: %s") % str(e)}


class AdminDeleteBooks(BaseHandler):
    @js
    @is_admin
    def post(self):
        req = tornado.escape.json_decode(self.request.body)
        idlist = req.get("idlist", [])
        if not idlist:
            return {"err": "params.error", "msg": _(u"参数错误")}

        for book_id in idlist:
            try:
                AudioUtils.clear_audio(book_id)
                book = self.get_book(book_id)
                book_id = book["id"]
                self.calibre_db.delete_book(book_id)
            except Exception as err:
                logging.error(_("执行异常: %s"), err)
        return {"err": "ok", "msg": _(u"删除成功")}


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
                    return {"err": "params.error.proxy", "msg": _(u"无效的代理地址")}

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
        logging.error("Current version: %s, Last revision: %s", VERSION, last_revsion)
        if last_revsion != VERSION:
            args = loader.SettingsLoader()
            args["LAST_REVISION"] = VERSION
            logic = SettingsSaverLogic()
            logic.save_extra_settings(args)

            # Load the release notes from the public folder
            release_note_path = CONF["static_path"] + "/static/release_notes.txt"
            logging.error("Release note path: %s", release_note_path)
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
        token = ''.join(secrets.choice(chars) for _ in range(32))

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
        running_tasks = [task for task in all_tasks if task["status"] == BackgroundTask.STATUS_RUNNING]
        return {"err": "ok", "tasks": running_tasks}


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
        (r"/api/admin/bookbarn/token/apply", AdminBookbarnTokenApply),
        (r"/api/admin/books/delete", AdminDeleteBooks),
        (r"/api/admin/audio/test", AudioTestConnection),
        (r"/api/admin/release/notes", ReleaseNotes),
        (r"/api/admin/token", AdminTokenHandler),
        (r"/api/admin/tasks/running", AdminRunningTasks),
    ]
