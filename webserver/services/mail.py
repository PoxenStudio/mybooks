#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import hashlib
import html
import logging
import traceback
import threading
import urllib.parse

from webserver.i18n import _

from webserver import loader
from webserver.services import AsyncService

CONF = loader.get_settings()
MAIL_SENDING_INTERVAL = 15 * 60  # 15 minutes


class MailService(AsyncService):
    _new_books_queue: list[str] = []
    _new_books_timer = None
    _new_books_lock = threading.Lock()
    _emails_to_notify: set[str] = set()
    _new_books_site_url = ""

    @staticmethod
    def _normalize_site_url(site_url: str) -> str:
        if not site_url:
            return ""
        try:
            parsed = urllib.parse.urlsplit(site_url.strip())
            if not parsed.scheme or not parsed.netloc:
                return ""
            return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        except Exception:
            return ""

    def _resolve_site_url(self, site_url: str = "") -> str:
        # Prefer URL from request context; fallback to optional config keys.
        for candidate in (site_url, CONF.get("site_url", ""), ""):
            normalized = self._normalize_site_url(candidate)
            if normalized:
                return normalized
        return ""

    # 其它模块调用这个方法，内部进行防抖处理。最后只会在 15 分钟后发送
    def send_new_book_notification(self, emails, book_names, site_url=""):
        if not CONF.get("SEND_MAIL_FOR_NEW_BOOKS", False):
            return
        if len(emails) == 0 or len(book_names) == 0:
            return
        with self._new_books_lock:
            for name in book_names:
                if len(self._new_books_queue) < 100 and name not in self._new_books_queue:
                    self._new_books_queue.append(name)
            for email in emails:
                self._emails_to_notify.add(email)

            normalized_site_url = self._resolve_site_url(site_url)
            if normalized_site_url:
                self._new_books_site_url = normalized_site_url

            if self._new_books_timer:
                self._new_books_timer.cancel()

            logging.info(f"[MAIL]Scheduled new book notification for {len(self._new_books_queue)} books to {len(self._emails_to_notify)} emails in {MAIL_SENDING_INTERVAL} seconds")
            self._new_books_timer = threading.Timer(MAIL_SENDING_INTERVAL, self._trigger_new_books_notification_async)
            self._new_books_timer.start()

    def _trigger_new_books_notification_async(self):
        with self._new_books_lock:
            books_to_send = list(self._new_books_queue)
            emails_to_send = list(self._emails_to_notify)
            site_url = self._new_books_site_url
            self._new_books_queue.clear()
            self._emails_to_notify.clear()
            self._new_books_site_url = ""
            self._new_books_timer = None

        if books_to_send and emails_to_send:
            self.do_send_new_book_notification(emails_to_send, books_to_send, site_url=site_url)

    @AsyncService.register_service
    def do_send_new_book_notification(self, emails, book_names, site_url=""):
        if not CONF.get("SEND_MAIL_FOR_NEW_BOOKS", False):
            return

        logging.info(f"[MAIL]Preparing to send new book notification to {len(emails)} emails for {len(book_names)} new books")
        site_url = self._resolve_site_url(site_url)
        mail_args = {
            "site_title": CONF.get("site_title", "书屋"),
        }
        mail_from = CONF.get("smtp_username", "")
        if not mail_from:
            logging.warning("[MAIL]SMTP username is not configured, cannot send new book notification emails")
            return

        mail_subject = _("%(site_title)s新书入库提醒") % mail_args
        safe_book_names = [name for name in book_names if name]
        book_list_str = "、".join(safe_book_names)
        mail_body = _("我们新入库以下新书，欢迎阅览：") + book_list_str
        if site_url:
            mail_body += "\n" + _("访问网址：") + site_url

        book_items_html = "".join(
            f"<li style=\"margin:0 0 8px 0;color:#1f2937;\">{html.escape(name)}</li>"
            for name in safe_book_names
        )
        site_link_html = ""
        if site_url:
            escaped_site_url = html.escape(site_url)
            site_link_html = (
                f"<p style=\"margin:16px 0 8px;color:#374151;\">"
                f"{html.escape(_('访问网址：'))} "
                f"<a href=\"{escaped_site_url}\" style=\"color:#0b57d0;text-decoration:none;\">{escaped_site_url}</a></p>"
            )
        mail_body_html = (
            '<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;'
            'background:#f4f6fb;padding:24px;color:#111827;line-height:1.6;">'
            '<div style="max-width:680px;margin:0 auto;background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;padding:24px;">'
            f'<h2 style="margin:0 0 12px 0;font-size:20px;color:#111827;">{html.escape(mail_subject)}</h2>'
            f'<p style="margin:0 0 16px 0;color:#374151;">{html.escape(_("我们新入库以下新书，欢迎阅览："))}</p>'
            f'<ul style="padding-left:20px;margin:0 0 16px 0;">{book_items_html}</ul>'
            f'{site_link_html}'
            '<p style="margin:20px 0 0 0;color:#6b7280;font-size:12px;">Talebook Notification</p>'
            '</div></div>'
        )

        sent_mails = set()
        for mail_to in emails:
            if mail_to in sent_mails:
                continue
            try:
                self.do_send_mail(mail_from, mail_to, mail_subject, mail_body, body_html=mail_body_html)
                sent_mails.add(mail_to)
            except Exception as e:
                logging.error("[MAIL]Failed to send new book notification to email: %s, exception:%s" % (mail_to, e))
        logging.info(f"[MAIL]Finished sending new book notifications to {len(sent_mails)} emails")

    def create_mail(self, sender, to, subject, body, attachment_data=None, attachment_name=None, body_html=None):
        from email.header import Header
        from email.mime.application import MIMEApplication
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.utils import formatdate

        mail = MIMEMultipart("mixed")
        mail["From"] = sender
        mail["To"] = to
        mail["Subject"] = Header(subject, "utf-8")
        mail["Date"] = formatdate(localtime=True)
        mail["Message-ID"] = "<tencent_%s@qq.com>" % hashlib.md5(mail.as_string().encode("UTF-8")).hexdigest()
        mail.preamble = "You will not see this in a MIME-aware mail reader.\n"

        if body is not None or body_html is not None:
            if body is not None and body_html is not None:
                msg = MIMEMultipart("alternative")
                msg.attach(MIMEText(body, "plain", "utf-8"))
                msg.attach(MIMEText(body_html, "html", "utf-8"))
                mail.attach(msg)
            elif body_html is not None:
                mail.attach(MIMEText(body_html, "html", "utf-8"))
            else:
                mail.attach(MIMEText(body, "plain", "utf-8"))

        if attachment_data is not None:
            name = Header(attachment_name, "utf-8").encode()
            msg = MIMEApplication(attachment_data, "octet-stream", charset="utf-8", name=name)
            msg.add_header("Content-Disposition", "attachment", filename=name)
            mail.attach(msg)
        return mail.as_string()

    # 系统配置时需要以阻塞模式测试邮件功能
    def do_send_mail(self, sender, to, subject, body, attachment_data=None, attachment_name=None, **kwargs):
        from calibre.utils.smtp import sendmail

        smtp_port = 465
        relay = kwargs.get("relay", CONF.get("smtp_server", ""))
        if relay and ":" in relay:
            host, _, port = relay.rpartition(":")
            if port.isdigit() and (not relay.startswith("[") or host.endswith("]")):
                relay = host
                smtp_port = int(port)
        username = kwargs.get("username", CONF["smtp_username"])
        password = kwargs.get("password", CONF["smtp_password"])
        enc = kwargs.get("encryption", CONF["smtp_encryption"])
        body_html = kwargs.get("body_html")
        mail = self.create_mail(sender, to, subject, body, attachment_data, attachment_name, body_html=body_html)
        sendmail(
            mail,
            from_=sender,
            to=[to],
            timeout=20,
            port=int(smtp_port),
            encryption=enc,
            relay=relay,
            username=username,
            password=password,
        )

    @AsyncService.register_service
    def send_mail(self, sender, to, subject, body, attachment_data=None, attachment_name=None, **kwargs):
        return self.do_send_mail(sender, to, subject, body, attachment_data, attachment_name, **kwargs)

    @AsyncService.register_service
    def send_book(self, user_id: int, site_url: str, book: dict, mail_to: str, fmt: str, fpath: str):
        from calibre.ebooks.metadata import authors_to_string

        logging.info(f"Preparing to send book {book['id']} to email {mail_to}")
        # read meta info
        author = authors_to_string(book["authors"] if book["authors"] else [_(u"佚名")])
        title = book["title"] if book["title"] else _(u"无名书籍")
        fname = u"%s - %s.%s" % (title, author, fmt)
        with open(fpath, "rb") as f:
            fdata = f.read()

        logging.info(f"Book {book['id']} read successfully, preparing email content")
        mail_args = {
            "title": title,
            "site_url": site_url,
            "site_title": CONF["site_title"],
        }
        mail_from = CONF["smtp_username"]
        mail_subject = _(CONF["push_title"]) % mail_args
        mail_body = _(CONF["push_content"]) % mail_args
        status = msg = ""
        try:
            logging.info("send %(title)s to %(mail_to)s" % vars())
            self.do_send_mail(mail_from, mail_to, mail_subject, mail_body, fdata, fname)
            status = "success"
            msg = _("[%(title)s] 已成功发送至邮箱 [%(mail_to)s] !!") % vars()
            logging.info(msg)
        except Exception as e:
            logging.error("Failed to send to email: %s, exception:%s" % (mail_to, e))
            logging.error(traceback.format_exc())
            status = "danger"
            msg = "[%(title)s] 发送至邮箱 [%(mail_to)s] 失败,请检查系统设置中的邮箱设置是否正确!" % {"title": title, "mail_to": mail_to}
        self.add_msg(user_id, status, msg)
        return
