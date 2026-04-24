#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import datetime
import logging
import re
import os
from webserver.i18n import _

import tornado.escape
from tornado import web
from webserver import loader
from webserver.services.mail import MailService
from webserver.handlers.base import BaseHandler, auth, js
from webserver.handlers.audio import AudioUtils
from webserver.models import Device, ExpectedItem, Message, Reader, StickyItem
from webserver.version import VERSION

CONF = loader.get_settings()
COOKIE_REDIRECT = "login_redirect"
ENABLE_VIP_QUOTA_KEY = "ENABLE_VIP_QUOTA"

# In-memory cache for user devices, keyed by user_id
_user_devices_cache = {}


class Done(BaseHandler):
    def update_userinfo(self):
        if int(CONF.get("auto_login", 0)):
            return

        user_id = self.get_secure_cookie("user_id")
        user = self.sqlite_session.query(Reader).get(int(user_id)) if user_id else None
        if not user:
            return
        socials = user.social_auth.all()
        if not socials:
            return

        si = socials[0]
        if not user.extra:
            logging.info("init new user %s, info=%s" % (user.username, si))
            user.init(si)

        user.check_and_update(si)
        return user

    def get(self):
        user = self.update_userinfo()
        if not user.can_login():
            raise web.HTTPError(403, log_message=_("无权登录"))
        self.login_user(user)
        url = self.get_secure_cookie(COOKIE_REDIRECT)
        self.clear_cookie(COOKIE_REDIRECT)
        if not url:
            url = "/"
        self.redirect(url)


class UserUpdate(BaseHandler):
    @js
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        user = self.current_user
        nickname = data.get("nickname", "")
        if nickname:
            nickname = nickname.strip()
            if len(nickname) > 0:
                if len(nickname) < 3:
                    return {"err": "params.nickname.invald", "msg": _("昵称无效")}
                user.name = nickname

        p0 = data.get("password0", "").strip()
        p1 = data.get("password1", "").strip()
        p2 = data.get("password2", "").strip()
        if len(p0) > 0:
            if user.get_secure_password(p0) != user.password:
                return {"err": "params.password.error", "msg": _("密码错误")}
            if (
                p1 != p2
                or len(p1) < 6
                or len(p1) > 20
                or not re.match(Reader.RE_PASSWORD, p1)
            ):
                return {"err": "params.password.invalid", "msg": _("密码无效")}
            user.set_secure_password(p1)

        ke = data.get("kindle_email", "").strip()
        if len(ke) > 0:
            if not re.match(Reader.RE_EMAIL, ke):
                return {"err": "params.email.invalid", "msg": _("Kindle地址无效")}
            user.extra["kindle_email"] = ke

        if "podcast_token" in data:
            user.podcast_token = data.get("podcast_token", "").strip()

        try:
            user.save()
            self.add_msg("success", _("Settings saved."))
            return {"err": "ok"}
        except:
            return {"err": "db.error", "msg": _("数据库操作异常，请重试")}


class SignUp(BaseHandler):
    def check_active_code(self, username, code):
        user = (
            self.sqlite_session.query(Reader)
            .filter(Reader.username == username)
            .first()
        )
        if not user or code != user.get_active_code():
            raise web.HTTPError(403, log_message=_("激活码无效"))
        user.active = True
        user.save()
        return self.redirect("/active/success")

    def send_active_email(self, user):
        code = user.get_active_code()
        link = "%s/api/active/%s/%s" % (self.site_url, user.username, code)
        args = {
            "site_title": CONF["site_title"],
            "username": user.username,
            "active_link": link,
        }
        mail_subject = CONF["SIGNUP_MAIL_TITLE"] % args
        mail_to = user.email
        mail_from = CONF["smtp_username"]
        mail_body = CONF["SIGNUP_MAIL_CONTENT"] % args
        MailService().send_mail(mail_from, mail_to, mail_subject, mail_body)

    @js
    def post(self):
        if not CONF.get("ALLOW_REGISTER", False):
            return {"err": "permission.denied", "msg": _("当前站点已关闭注册")}

        email = self.get_argument("email", "").strip()
        nickname = self.get_argument("nickname", "").strip()
        username = self.get_argument("username", "").strip().lower()
        password = self.get_argument("password", "").strip()
        if not nickname or not username or not password:
            return {"err": "params.invalid", "msg": _("用户名或密码无效")}

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

        user = (
            self.sqlite_session.query(Reader)
            .filter(Reader.username == username)
            .first()
        )
        if user:
            return {"err": "params.username.exist", "msg": _("用户名已被使用")}
        user = self.sqlite_session.query(Reader).filter(Reader.email == email).first()
        if user:
            return {"err": "params.email.exist", "msg": _("邮箱地址已被使用")}

        user = Reader()
        user.permission = Reader.DEFAULT_PERMISSION
        if not CONF.get("ALLOW_NEW_USER_MANAGE_BOOK", True):
            user.permission = user.permission + Reader.DISABLE_MANAGE
        if not CONF.get("ALLOW_NEW_USER_PUSH_BOOK", True):
            user.permission = user.permission + Reader.DISABLE_PUSH
        user.username = username
        user.name = nickname
        user.email = email
        user.avatar = "reader.svg"
        user.create_time = datetime.datetime.now()
        user.update_time = datetime.datetime.now()
        user.access_time = datetime.datetime.now()
        user.active = False
        user.extra = {"kindle_email": ""}
        user.set_secure_password(password)
        try:
            user.save()
        except:
            import traceback

            logging.error(traceback.format_exc())
            return {"err": "db.error", "msg": _("系统异常，请重试或更换注册信息")}
        self.send_active_email(user)
        return {"err": "ok"}


class UserNew(BaseHandler):
    @js
    @auth
    def post(self):
        if not self.admin_user:
            return {"err": "permission.not_admin", "msg": _("当前用户非管理员")}

        email = self.get_argument("email", "").strip()
        nickname = self.get_argument("nickname", "").strip()
        username = self.get_argument("username", "").strip().lower()
        password = self.get_argument("password", "").strip()
        if not nickname or not username or not password:
            return {"err": "params.invalid", "msg": _("用户名或密码无效")}

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

        user = (
            self.sqlite_session.query(Reader)
            .filter(Reader.username == username)
            .first()
        )
        if user:
            return {"err": "params.username.exist", "msg": _("用户名已被使用")}
        user = self.sqlite_session.query(Reader).filter(Reader.email == email).first()
        if user:
            return {"err": "params.email.exist", "msg": _("邮箱地址已被使用")}

        user = Reader()
        user.permission = Reader.DEFAULT_PERMISSION
        if not CONF.get("ALLOW_NEW_USER_MANAGE_BOOK", True):
            user.permission = user.permission + Reader.DISABLE_MANAGE
        if not CONF.get("ALLOW_NEW_USER_PUSH_BOOK", True):
            user.permission = user.permission + Reader.DISABLE_PUSH
        user.username = username
        user.name = nickname
        user.email = email
        user.avatar = "reader.svg"
        user.create_time = datetime.datetime.now()
        user.update_time = datetime.datetime.now()
        user.access_time = datetime.datetime.now()
        user.active = True  # 管理员添加的用户直接激活
        user.extra = {"kindle_email": ""}
        user.set_secure_password(password)
        try:
            user.save()
        except:
            import traceback

            logging.error(traceback.format_exc())
            return {"err": "db.error", "msg": _("系统异常，请重试或更换注册信息")}

        return {"err": "ok", "msg": _("用户添加成功")}


class UserSendActive(SignUp):
    @js
    @auth
    def get(self):
        self.send_active_email(self.current_user)
        return {"err": "ok"}

    def post(self):
        return self.get()


class UserActive(SignUp):
    def get(self, username, code):
        return self.check_active_code(username, code)

    def post(self, username, code):
        return self.check_active_code(username, code)


class SignIn(BaseHandler):
    @js
    def post(self):
        username = self.get_argument("username", "").strip().lower()
        password = self.get_argument("password", "").strip()
        if not username or not password:
            return {"err": "params.invalid", "msg": _("用户名或密码错误")}
        user = (
            self.sqlite_session.query(Reader)
            .filter(Reader.username == username)
            .first()
        )
        if not user:
            return {"err": "params.no_user", "msg": _("无此用户")}
        if user.get_secure_password(password) != user.password:
            return {"err": "params.invalid", "msg": _("用户名或密码错误")}
        if not user.is_active():
            return {
                "err": "permission.inactive",
                "msg": _(
                    "用户未激活！请检查注册邮箱以完成激活或者联系管理员在用户管理中激活"
                ),
            }
        if not user.can_login():
            return {
                "err": "permission",
                "msg": _("目前无权登录！请联系管理员在用户管理中检查登录权限"),
            }
        logging.debug("PERM = %s", user.permission)

        self.login_user(user)
        return {"err": "ok", "msg": _("ok")}


class UserReset(BaseHandler):
    @js
    def post(self):
        email = self.get_argument("email", "").strip().lower()
        username = self.get_argument("username", "").strip().lower()
        if not username or not email:
            return {"err": "params.invalid", "msg": _("用户名或邮箱错误")}
        user = (
            self.sqlite_session.query(Reader)
            .filter(Reader.username == username, Reader.email == email)
            .first()
        )
        if not user:
            return {"err": "params.no_user", "msg": _("无此用户")}
        p = user.reset_password()

        # send notice email
        args = {
            "site_title": CONF["site_title"],
            "username": user.username,
            "password": p,
        }
        mail_subject = CONF["RESET_MAIL_TITLE"] % args
        mail_to = user.email
        mail_from = CONF["smtp_username"]
        mail_body = CONF["RESET_MAIL_CONTENT"] % args
        MailService().send_mail(mail_from, mail_to, mail_subject, mail_body)

        # do save into db
        try:
            user.save()
            self.add_msg("success", _("你刚刚重置了密码"))
            return {"err": "ok"}
        except:
            return {"err": "db.error", "msg": _("系统繁忙")}


class SignOut(BaseHandler):
    @js
    @auth
    def get(self):
        self.set_secure_cookie("user_id", "")
        self.set_secure_cookie("admin_id", "")
        return {"err": "ok", "msg": _("你已成功退出登录。")}


class UserMessages(BaseHandler):
    @js
    def get(self):
        user = self.current_user
        rsp = {
            "err": "ok",
            "messages": [],
        }

        if user and user.messages is not None:
            messages = user.messages
            messages.sort(key=lambda x: x.create_time, reverse=True)
            if messages is None:
                return rsp
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
                rsp["messages"].append(m)
        return rsp

    @js
    @auth
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        if "id" not in data:
            return {"err": "params.invalid", "msg": _("ID错误")}
        msg = (
            self.sqlite_session.query(Message).filter(Message.id == data["id"]).first()
        )
        if not msg:
            # 消息不存在，可能已经被删除了，直接返回成功
            return {"err": "ok"}

        try:
            msg = self.sqlite_session.merge(msg)
            msg.unread = False
            msg.update_time = datetime.datetime.now()
            msg.save()
        except Exception as e:
            logging.error("Mark message as read failed: %s", e)
        return {"err": "ok"}


class UserMessagesClear(BaseHandler):
    @js
    @auth
    def post(self):
        user = self.current_user
        if not user or not user.messages:
            return {"err": "ok"}
        for msg in user.messages:
            # Ensure msg is in the current session to avoid "already attached to session" error
            msg = self.sqlite_session.merge(msg)
            msg.unread = False
            msg.update_time = datetime.datetime.now()
            msg.save()
        return {"err": "ok"}


class UserInfo(BaseHandler):
    def get_sys_info(self):
        from sqlalchemy import func

        db = self.calibre_db
        last_week = datetime.datetime.now() - datetime.timedelta(days=7)
        count_all_users = self.sqlite_session.query(func.count(Reader.id)).scalar()
        count_hot_users = (
            self.sqlite_session.query(func.count(Reader.id))
            .filter(Reader.access_time > last_week)
            .scalar()
        )

        audio_book_cnt = AudioUtils.get_audio_books_count()
        physical_book_cnt = self.get_physical_books_count()

        return {
            "books": db.count(),
            "tags": len(db.all_tags()),
            "authors": len(db.all_authors()),
            "audiobooks": audio_book_cnt,
            "publishers": len(db.all_publishers()),
            "series": len(db.all_series()),
            "physicals": physical_book_cnt,
            "mtime": db.last_modified().strftime("%Y-%m-%d"),
            "users": count_all_users,
            "active": count_hot_users,
            "version": VERSION,
            "title": CONF["site_title"] if "site_title" in CONF else "TaleBook",
            "language": CONF["site_language"] if "site_language" in CONF else "",
            "theme": CONF["site_theme"] if "site_theme" in CONF else "light",
            "maxUploadSize": (
                CONF["MAX_UPLOAD_SIZE"] if "MAX_UPLOAD_SIZE" in CONF else "100MB"
            ),
            "chunkUploadSize": (
                CONF["CHUNK_UPLOAD_SIZE"] if "CHUNK_UPLOAD_SIZE" in CONF else "0MB"
            ),
            "icon": CONF["site_icon"] if "site_icon" in CONF else "favicon_1",
            "socials": CONF["SOCIALS"],
            "friends": CONF["FRIENDS"],
            "footer": CONF["FOOTER"] if "FOOTER" in CONF else "",
            "header": CONF["HEADER"] if "HEADER" in CONF else "",
            "allow": {
                "register": CONF["ALLOW_REGISTER"],
                "download": CONF["ALLOW_GUEST_DOWNLOAD"],
                "push": CONF["ALLOW_GUEST_PUSH"],
                "read": CONF["ALLOW_GUEST_READ"],
                "physical_books": CONF.get("ENABLE_PHYSICAL_BOOKS", True),
                "upload": CONF.get("ALLOW_GUEST_UPLOAD", False),
            },
            "indexPage": CONF.get("INDEX_PAGE_TYPE", "index"),
            "defaultPageSize": CONF.get("DEFAULT_PAGE_SIZE", 60),
            "aiEnabled": CONF.get("AI_ENABLED", False),
        }

    def get_user_info(self, detail):
        enable_vip_quota = CONF.get(ENABLE_VIP_QUOTA_KEY, False)
        if enable_vip_quota:
            user = self.get_current_user_sync()
        else:
            user = self.get_current_user()
        d = {
            "avatar": "https://tva1.sinaimg.cn/default/images/default_avatar_male_50.gif",
            "is_login": False,
            "is_admin": False,
            "nickname": "",
            "email": "",
            "kindle_email": "",
            "extra": {},
        }

        if not user:
            return d

        d.update(
            {
                "is_login": True,
                "is_admin": user.is_admin(),
                "is_active": user.is_active(),
                "nickname": user.name or "",
                "username": user.username,
                "email": user.email,
                "extra": {},
                "create_time": user.create_time.strftime("%Y-%m-%d %H:%M:%S"),
                "podcast_token": user.podcast_token or "",
            }
        )
        if enable_vip_quota:
            d["vipquota"] = user.vipquota or 0
            d["vip_expire"] = (
                user.vipexpire.strftime("%Y-%m-%d") if user.vipexpire else ""
            )

        if user.avatar:
            if user.avatar.startswith("http"):
                gravatar_url = "https://www.gravatar.com"
                d["avatar"] = user.avatar.replace("http://", "https://").replace(
                    gravatar_url, CONF["avatar_service"]
                )
            else:
                d["avatar"] = self.site_url + "/avatar/%s" % user.avatar
        if user.extra:
            d["kindle_email"] = user.extra.get("kindle_email", "")
            if detail:
                for k, v in user.extra.items():
                    if k.endswith("_history"):
                        ids = [b["id"] for b in v][:24]
                        books = self.calibre_db.get_data_as_dict(ids=ids)
                        show = set([b["id"] for b in books])
                        n = []
                        for b in v:
                            if b["id"] not in show:
                                continue
                            b["img"] = (
                                self.cdn_url
                                + "/get/cover/%(id)s.jpg?t=%(timestamp)s" % b
                            )
                            b["href"] = "/book/%(id)s" % b
                            b["thumb"] = (
                                self.cdn_url
                                + "/get/thumb_240_320/%(id)s.jpg?t=%(timestamp)s&size=240x320"
                                % b
                            )
                            n.append(b)
                        v = n[:12]

                    d["extra"][k] = v

        return d

    @js
    def get(self):
        if CONF.get("installed", None) is False:
            return {"err": "not_installed"}

        detail = self.get_argument("detail", "")
        rsp = {
            "err": "ok",
            "cdn": self.cdn_url,
            "sys": self.get_sys_info() if not detail else {},
            "user": self.get_user_info(detail),
        }
        return rsp


class UserVipInfo(BaseHandler):
    @js
    @auth
    def get(self):
        enable_vip_quota = CONF.get(ENABLE_VIP_QUOTA_KEY, False)
        if not enable_vip_quota:
            return {
                "err": "ok",
                "vipquota": 0,
                "vip_expire": "",
            }

        user = self.get_current_user_sync()
        return {
            "err": "ok",
            "vipquota": user.vipquota or 0,
            "vip_expire": user.vipexpire.strftime("%Y-%m-%d") if user.vipexpire else "",
        }


class Welcome(BaseHandler):
    def should_be_invited(self):
        pass

    @js
    def get(self):
        if not self.need_invited():
            return {"err": "free", "msg": _("无需访问码")}
        if self.invited_code_is_ok():
            return {"err": "free", "msg": _("已输入访问码")}
        return {"err": "ok", "msg": "", "welcome": CONF["INVITE_MESSAGE"]}

    @js
    def post(self):
        code = self.get_argument("invite_code", None)
        if not code or code != CONF["INVITE_CODE"]:
            return {"err": "params.invalid", "msg": _("访问码无效")}
        self.mark_invited()
        return {"err": "ok", "msg": ""}


class UserAvatar(BaseHandler):
    @js
    @auth
    def post(self):
        user = self.current_user
        if not user:
            raise web.HTTPError(403, reason="请先登录")
        fileinfo = self.request.files.get("avatar")
        if not fileinfo:
            return {"err": "params.invalid", "msg": _("未上传头像文件")}
        fileinfo = fileinfo[0]
        avatar_dir = os.path.join(CONF["static_path"], "avatar")
        os.makedirs(avatar_dir, exist_ok=True)

        avatar_file = f"{user.id}.png"
        avatar_path = os.path.join(avatar_dir, avatar_file)
        full_avatar_uri = self.site_url + "/avatar/%s" % avatar_file
        with open(avatar_path, "wb+") as f:
            f.write(fileinfo["body"])
        if user.avatar == avatar_file:
            return {"err": "ok", "msg": "", "avatar_url": full_avatar_uri}
        user.avatar = avatar_file
        try:
            user.save()
            return {
                "err": "ok",
                "msg": "",
                "avatar_url": self.site_url + "/avatar/%s" % user.avatar,
            }
        except:
            return {"err": "db.error", "msg": _("数据库操作异常，请重试")}


class PinItem(BaseHandler):
    """置顶作者或标签"""

    @js
    @auth
    def post(self):
        if not self.current_user:
            return {"err": "permission.not_login", "msg": _("请先登录")}

        data = tornado.escape.json_decode(self.request.body)
        item_type = data.get("item_type")  # 0:作者, 1:Tag
        value = data.get("value", "").strip()

        if item_type not in [0, 1]:
            return {"err": "params.invalid", "msg": _("类型参数无效")}

        if not value:
            return {"err": "params.invalid", "msg": _("值不能为空")}

        user_id = self.user_id()

        # 检查是否已经置顶
        existing = (
            self.sqlite_session.query(StickyItem)
            .filter(
                StickyItem.reader_id == user_id,
                StickyItem.item_type == item_type,
                StickyItem.value == value,
            )
            .first()
        )

        if existing:
            return {"err": "already_pinned", "msg": _("已经置顶过了")}

        # 检查该类型的置顶数量是否超过限制
        count = (
            self.sqlite_session.query(StickyItem)
            .filter(StickyItem.reader_id == user_id, StickyItem.item_type == item_type)
            .count()
        )

        if count >= 50:
            return {"err": "limit_exceeded", "msg": _("置顶数量已达上限(50个)")}

        # 创建置顶项
        sticky_item = StickyItem(reader_id=user_id, item_type=item_type, value=value)
        self.sqlite_session.add(sticky_item)

        try:
            self.sqlite_session.commit()
            return {"err": "ok", "msg": _("置顶成功")}
        except Exception as e:
            logging.error("Pin item failed: %s", e)
            self.sqlite_session.rollback()
            return {"err": "db.error", "msg": _("置顶失败")}


class UserDevices(BaseHandler):
    """管理当前用户的阅读设备"""

    @js
    @auth
    def get(self):
        user_id = self.user_id()
        if user_id in _user_devices_cache:
            return {"err": "ok", "devices": _user_devices_cache[user_id]}
        devices = (
            self.sqlite_session.query(Device).filter(Device.reader_id == user_id).all()
        )
        result = [d.to_dict() for d in devices]
        _user_devices_cache[user_id] = result
        return {"err": "ok", "devices": result}

    @js
    @auth
    def post(self):
        user_id = self.user_id()
        try:
            data = tornado.escape.json_decode(self.request.body)
        except Exception:
            return {"err": "params.invalid", "msg": _("参数无效")}

        devices_data = data.get("devices", [])
        if not isinstance(devices_data, list):
            return {"err": "params.invalid", "msg": _("参数无效")}

        # Replace all existing devices for this user
        self.sqlite_session.query(Device).filter(Device.reader_id == user_id).delete()
        result = []
        for d in devices_data:
            device = Device(
                reader_id=user_id,
                name=d.get("name", ""),
                device_type=d.get("type", "duokan"),
                ip=d.get("ip", ""),
                port=int(d.get("port", 12121)),
                schema=d.get("schema", "http"),
                mailbox=d.get("mailbox", ""),
            )
            self.sqlite_session.add(device)
            result.append(device.to_dict())
        try:
            self.sqlite_session.commit()
            # Refresh cache
            _user_devices_cache[user_id] = result
            return {"err": "ok", "msg": _("设备保存成功")}
        except Exception as e:
            logging.error("Save user devices failed: %s", e)
            self.sqlite_session.rollback()
            return {"err": "db.error", "msg": _("数据库操作异常，请重试")}


class UnpinItem(BaseHandler):
    """取消置顶作者或标签"""

    @js
    @auth
    def post(self):
        if not self.current_user:
            return {"err": "permission.not_login", "msg": _("请先登录")}

        data = tornado.escape.json_decode(self.request.body)
        item_type = data.get("item_type")  # 0:作者, 1:Tag
        value = data.get("value", "").strip()

        if item_type not in [0, 1]:
            return {"err": "params.invalid", "msg": _("类型参数无效")}

        if not value:
            return {"err": "params.invalid", "msg": _("值不能为空")}

        user_id = self.user_id()

        # 查找并删除置顶项
        sticky_item = (
            self.sqlite_session.query(StickyItem)
            .filter(
                StickyItem.reader_id == user_id,
                StickyItem.item_type == item_type,
                StickyItem.value == value,
            )
            .first()
        )

        if not sticky_item:
            return {"err": "not_found", "msg": _("未找到置顶项")}

        try:
            self.sqlite_session.delete(sticky_item)
            self.sqlite_session.commit()
            return {"err": "ok", "msg": _("取消置顶成功")}
        except Exception as e:
            logging.error("Unpin item failed: %s", e)
            self.sqlite_session.rollback()
            return {"err": "db.error", "msg": _("取消置顶失败")}


class UserExpectedItems(BaseHandler):
    """缺书登记管理"""

    @js
    @auth
    def get(self):
        user_id = self.user_id()
        items = (
            self.sqlite_session.query(ExpectedItem)
            .filter(ExpectedItem.reader_id == user_id)
            .order_by(ExpectedItem.create_time.desc())
            .all()
        )
        result = []
        for item in items:
            result.append(
                {
                    "id": item.id,
                    "title": item.title,
                    "author": item.author or "",
                    "publisher": item.publisher or "",
                    "create_time": (
                        item.create_time.strftime("%Y-%m-%d")
                        if item.create_time
                        else ""
                    ),
                }
            )
        return {"err": "ok", "items": result}

    @js
    @auth
    def post(self):
        user_id = self.user_id()
        try:
            data = tornado.escape.json_decode(self.request.body)
        except Exception:
            return {"err": "params.invalid", "msg": _("参数无效")}

        title = data.get("title", "").strip()
        if not title:
            return {"err": "params.title.required", "msg": _("书名不能为空")}
        if len(title) > 256:
            return {"err": "params.title.too_long", "msg": _("书名过长")}

        author = data.get("author", "").strip()
        publisher = data.get("publisher", "").strip()

        item = ExpectedItem(
            reader_id=user_id,
            title=title,
            author=author,
            publisher=publisher,
        )
        self.sqlite_session.add(item)
        try:
            self.sqlite_session.commit()
            return {
                "err": "ok",
                "msg": _("添加成功"),
                "item": {
                    "id": item.id,
                    "title": item.title,
                    "author": item.author or "",
                    "publisher": item.publisher or "",
                    "create_time": (
                        item.create_time.strftime("%Y-%m-%d")
                        if item.create_time
                        else ""
                    ),
                },
            }
        except Exception as e:
            logging.error("Add expected item failed: %s", e)
            self.sqlite_session.rollback()
            return {"err": "db.error", "msg": _("添加失败")}

    @js
    @auth
    def delete(self):
        user_id = self.user_id()
        try:
            data = tornado.escape.json_decode(self.request.body)
        except Exception:
            return {"err": "params.invalid", "msg": _("参数无效")}

        item_id = data.get("id")
        if not item_id:
            return {"err": "params.id.required", "msg": _("ID不能为空")}

        item = (
            self.sqlite_session.query(ExpectedItem)
            .filter(
                ExpectedItem.id == item_id,
                ExpectedItem.reader_id == user_id,
            )
            .first()
        )
        if not item:
            return {"err": "not_found", "msg": _("未找到该登记项")}

        try:
            self.sqlite_session.delete(item)
            self.sqlite_session.commit()
            return {"err": "ok", "msg": _("删除成功")}
        except Exception as e:
            logging.error("Delete expected item failed: %s", e)
            self.sqlite_session.rollback()
            return {"err": "db.error", "msg": _("删除失败")}


def routes():
    return [
        (r"/api/welcome", Welcome),
        (r"/api/user/info", UserInfo),
        (r"/api/user/vip", UserVipInfo),
        (r"/api/user/messages", UserMessages),
        (r"/api/user/messages/clear", UserMessagesClear),
        (r"/api/user/sign_in", SignIn),
        (r"/api/user/sign_up", SignUp),
        (r"/api/user/new", UserNew),
        (r"/api/user/sign_out", SignOut),
        (r"/api/user/update", UserUpdate),
        (r"/api/user/reset", UserReset),
        (r"/api/user/avatar", UserAvatar),
        (r"/api/user/active/send", UserSendActive),
        (r"/api/active/(.*)/(.*)", UserActive),
        (r"/api/done/", Done),
        (r"/api/user/pin", PinItem),
        (r"/api/user/unpin", UnpinItem),
        (r"/api/user/devices", UserDevices),
        (r"/api/user/expected", UserExpectedItems),
    ]
