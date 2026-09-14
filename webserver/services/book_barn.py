#!/usr/bin/env python3
import datetime
import requests
import logging
import json
import os
import platform
import shutil
import time
import re

from urllib.parse import urlparse, unquote

from webserver.services import AsyncService
from webserver.services.autofill import AutoFillService
from webserver.services.resource_service import AUTHOR_AVATAR_DIR
from webserver import loader, utils
from webserver.version import VERSION
from webserver.models import Reader, Item, Authors
from webserver.constants import AUTO_FILL_META
from webserver.i18n import _
from webserver.constants import UPGRABLE_REVISION
from webserver.handlers.static_files import get_author_hash

# 设置 requests 库的日志级别为 ERROR，减少冗余日志
logging.getLogger("requests").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)


def get_os():
    """Return the operating system name in lowercase."""
    try:
        return platform.system().lower()
    except Exception:
        return ""


def get_arch():
    """Return the machine architecture in lowercase."""
    try:
        arch = platform.machine().lower()
        # Map common architecture names to desired values
        if arch in ("x86_64", "amd64"):
            return "amd64"
        if arch in ("aarch64", "arm64"):
            return "arm64"
        return arch
    except Exception:
        return ""


CONF = loader.get_settings()


class BookBarnClient:
    HOST_BASE = "https://mybooks.top/api/"
    # HOST_BASE = "http://127.0.0.1:8088/"
    CHECK_TOKEN_API = "bookbarn/check"
    APPLY_TOKEN_API = "bookbarn/token"
    CHECK_LATEST_RELEASE_API = "bookbarn/release/check"
    UPDATE_ACTION_API = "bookbarn/token/action"
    GET_CONFIG_API = "bookbarn/config"
    GET_BOOKS_API = "bookbarn/pubbooks"
    DOWNLOAD_API = "getfile"
    FILE_SAVE_PATH = "/tmp/bookbarn/"
    AUTHOR_API = "bookbarn/author"
    IMAGE_API = "getimage"

    ACTION_NONE = 0
    ACTION_CHECKING = 1
    ACTION_DONE = 2

    def __init__(self):
        self.token = None
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0",
            "Referer": "https://mybooks.top/",
            "MyBooks-Client": f"MyBooks/{VERSION}"
        }

    def checkToken(self, token):
        params = {
            "version": VERSION,
            "token": token
        }
        response = requests.get(self.HOST_BASE + self.CHECK_TOKEN_API,
                                headers=self.headers,
                                timeout=30,
                                params=params, verify=True)
        if response.status_code == 200:
            data = response.json().get("data")
            if data is not None:
                self.token = data.get("token")
                logging.info(f"[BARN]Token is valid: {self.token}")
                return True, ""
            else:
                msg = response.json().get("msg", "")
                logging.warning(f"[BARN]Invalid Token: {msg}")
                return False, msg
        else:
            data = response.json().get("data")
            logging.error(f"[BARN]Failed to check token: {response.status_code} - {response.text}")
            return False, response.text

    def applyToken(self, os=None):
        # send post request with APPLY_TOKEN_API, json data with client_revision and os
        data = {
            "version": VERSION,
            "os": os
        }
        response = requests.post(self.HOST_BASE + self.APPLY_TOKEN_API,
                                 headers=self.headers,
                                 timeout=30,
                                 json=data, verify=True)

        if response.status_code == 200:
            data = response.json().get("data")
            if data is not None:
                self.token = data.get("token")
            logging.info(f"[BARN]Token applied successfully: {self.token}")
            return self.token
        else:
            raise Exception(f"[BARN]Failed to apply token: {response.status_code} - {response.text}")

    def checkLatestRelease(self, token):
        if not CONF.get("AUTO_CHECKING_NEW_VERSION", True):
            logging.debug("Auto checking new version is disabled, skip checking latest release.")
            return None
        if VERSION == "v0.0.1":
            logging.info("Current version is v0.0.1, skip checking latest release for development version.")
            return None
        params = {
            "version": VERSION,
            "token": token,
            "platform": get_os() + "-" + get_arch()
        }
        result = None
        try:
            response = requests.get(self.HOST_BASE + self.CHECK_LATEST_RELEASE_API,
                                    headers=self.headers,
                                    params=params,
                                    timeout=30,
                                    verify=True)
            if response.status_code == 200:
                data = response.json().get("data")
                if data is not None:
                    latest_version = data.get("rev")
                    if latest_version is not None and latest_version != VERSION:
                        logging.info("New release found: %s", latest_version)
                        result = {
                            "rev": latest_version,
                            "notes": data.get("notes", ""),
                            "date": data.get("releaseDate", "")
                        }
                    else:
                        logging.info("Current version is up-to-date.")
                else:
                    logging.info(f"Current version is up-to-date, no release found for the platform {get_os()}-{get_arch()}")
            else:
                logging.error(f"Failed to get latest release, status code {response.status_code}")
        except Exception:
            logging.error("Exception occurred while checking latest release.")
        return result

    def _updateAction(self, token, action):
        data = {
            "version": VERSION,
            "token": token,
            "action": action
        }
        response = requests.post(self.HOST_BASE + self.UPDATE_ACTION_API,
                                 headers=self.headers,
                                 timeout=30,
                                 json=data, verify=True)

        if response.status_code == 200:
            return True
        else:
            logging.error(f"Failed to update action: {response.status_code} - {response.text}")
            return False

    def setCheckingAction(self, token):
        return self._updateAction(token, BookBarnClient.ACTION_CHECKING)

    def resetChecking(self, token):
        return self._updateAction(token, BookBarnClient.ACTION_NONE)

    def setCheckingDone(self, token):
        return self._updateAction(token, BookBarnClient.ACTION_DONE)

    def getBookList(self, token):
        # request GET_BOOKS_API with token & version as query string
        params = {
            "token": token,
            "version": VERSION
        }
        response = requests.get(self.HOST_BASE + self.GET_BOOKS_API,
                                headers=self.headers,
                                params=params,
                                timeout=30,
                                verify=True)

        if response.status_code == 200:
            data = response.json().get("data")
            if data is not None:
                return data  # Return the list of books
            else:
                logging.warning("No data found in the response.")
                return []
        else:
            logging.error(f"Failed to get book list: {response.status_code} - {response.text}")
            return None

    def getResourceList(self, token):
        params = {
            "version": VERSION,
            "token": token,
            "configKey": "resources"
        }
        try:
            response = requests.get(self.HOST_BASE + self.GET_CONFIG_API,
                                    headers=self.headers,
                                    params=params,
                                    timeout=30,
                                    verify=True)
        except Exception as e:
            logging.error(f"Exception occurred while getting resource list: {str(e)}")
            return None

        if response.status_code == 200:
            data = response.json().get("data")
            if data:
                try:
                    array_data = json.loads(data)
                    if isinstance(array_data, list):
                        data = array_data
                except Exception as e:
                    logging.error(f"Failed to parse resource list: {str(e)}")
            if data is not None:
                return data
            else:
                logging.warning("No data found in the response.")
                return None
        else:
            logging.error(f"Failed to get resource list: {response.status_code} - {response.text}")
            return None

    def downloadFile(self, token, download_url, book_id, filename, filesize):
        try:
            save_path = self.FILE_SAVE_PATH
            params = {
                "token": token,
                "version": VERSION
            }

            if filename is None:
                filename = self._get_filename_from_url(download_url)

            if download_url is None or len(download_url) == 0:
                download_url = f"{self.HOST_BASE}{self.DOWNLOAD_API}"
                params["id"] = book_id

            if not filename or len(filename) < 3 or '.' not in filename:
                filename = f"download_{int(time.time())}"
            else:
                filename = re.sub(r'[\\/*?:"<>|]', '_', filename)

            os.makedirs(self.FILE_SAVE_PATH, exist_ok=True)
            save_path = os.path.join(save_path, filename)
            if os.path.exists(save_path):
                os.remove(save_path)

            logging.info(f"[BARN]Start to download: {filename} from {download_url}")
            with self.session.get(download_url, headers=self.headers, params=params, stream=True, verify=True) as r:
                r.raise_for_status()
                downloaded = 0

                with open(save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)

            if filesize == 0 or downloaded == filesize:
                logging.info(f"[BARN]: saved {save_path}")
                return save_path
            else:
                logging.info(f"[BARN]Invalid file size of {filename}, expected {filesize} but got {downloaded}.")
                os.remove(save_path)
                return None

        except Exception as e:
            logging.error(f"[BARN] Failed to download file, {str(e)}")
            return None

    def download_image(self, token, image_url, target_file_path):
        if image_url is None or len(image_url) == 0:
            return None

        try:
            save_path = self.FILE_SAVE_PATH
            params = {
                "token": token,
                "version": VERSION
            }

            if not image_url.startswith("http"):
                params["filename"] = image_url
                image_url = f"{self.HOST_BASE}{self.IMAGE_API}"

            filename = self._get_filename_from_url(image_url)
            if filename is None:
                filename = f"download_{int(time.time())}"

            os.makedirs(self.FILE_SAVE_PATH, exist_ok=True)
            save_path = os.path.join(save_path, filename)
            if os.path.exists(save_path):
                os.remove(save_path)

            with self.session.get(image_url, headers=self.headers, params=params, stream=True, verify=True) as r:
                r.raise_for_status()
                downloaded = 0

                with open(save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)

            if target_file_path is not None:
                # move the file to target path
                shutil.move(save_path, target_file_path)
            return target_file_path
        except Exception as e:
            logging.error(f"[BARN] Failed to download image file, {str(e)}")
            return None

    def get_author(self, token, author_name):
        params = {
            "token": token,
            "version": VERSION,
            "name": author_name
        }
        response = requests.get(self.HOST_BASE + self.AUTHOR_API,
                                headers=self.headers,
                                params=params,
                                timeout=30,
                                verify=True)

        if response.status_code == 200:
            data = response.json().get("data")
            if data is not None:
                if len(data) > 0:
                    return data[0]
                else:
                    logging.debug(f"[BARN]No author found with name {author_name}")
                    return None
            else:
                logging.warning("No data found in the response.")
                return None
        else:
            logging.error(f"Failed to get author: {response.status_code} - {response.text}")
            return None

    def _get_filename_from_url(self, url):
        """从URL中提取文件名"""
        # 尝试从URL路径获取文件名
        filename = os.path.basename(urlparse(url).path)

        # 如果文件名看起来像URL编码，尝试解码
        if '%' in filename:
            try:
                decoded = unquote(filename)
                # 如果解码后包含扩展名，使用解码后的名称
                if '.' in decoded and decoded.split('.')[-1].isalnum():
                    return decoded
            except Exception:
                pass

        return filename


class BookBarnService(AsyncService):
    def __init__(self):
        self.client = BookBarnClient()
        self.os = "Linux"
        self.token = ""
        self.checked_day = None
        self.checked_release_time = None
        self.admin_uids = None

    @AsyncService.register_service
    def get_daily_books(self):
        logging.info("Start daily books checking")
        token_invalid_message = False
        output_hour = 0
        while True:
            if self.checked_release_time is None or self.checked_release_time < time.time():
                self.checked_release_time = time.time() + 8 * 60 * 60
                latest_release = self.client.checkLatestRelease(self.token)
                CONF[UPGRABLE_REVISION] = ""
                if latest_release is not None:
                    logging.info(f"[BARN]New version available: {latest_release['rev']}, released on {latest_release['date']}")
                    if self.admin_uids is None or len(self.admin_uids) == 0:
                        self.get_admin_uids()
                    CONF[UPGRABLE_REVISION] = latest_release.get("rev", "")
                    if len(self.admin_uids) > 0:
                        message = f"有新版本发布: {latest_release['rev']}，发布日期: {latest_release['date']}，\
                                    更新内容: {latest_release['notes']}，请重新构建容器以获取更新。"
                        for uid in self.admin_uids:
                            self.add_msg(uid, "info", message)

            if not CONF.get("ENABLE_BOOKBARN", False) or not CONF.get("ENABLE_RECEIVING_BOOKS", False):
                time.sleep(30 * 60)
                continue

            if self.checked_day is not None:
                today = datetime.datetime.now().strftime("%Y-%m-%d")
                if self.checked_day == today:
                    # Has checked for today update
                    logging.info(f"[BARN] skip, had been checked today: {today}")
                    time.sleep(30 * 60)
                    continue

            current_token = CONF.get("BOOKBARN_TOKEN", "")
            if len(current_token) == 0:
                logging.info("[BARN]Daily books checking, not set token")
                time.sleep(30 * 60)
                continue
            if self.token != current_token:
                self.token = current_token

            hour = int(CONF.get("BOOKBARN_COLLECTION_HOUR", 3))
            current_hour = datetime.datetime.now().hour

            if current_hour != hour:
                if output_hour != current_hour:
                    logging.info(f"[BARN]Not target time {hour}, now is {current_hour}")
                    output_hour = current_hour
                time.sleep(30 * 60)
                continue

            ok, err = self.client.checkToken(self.token)
            if not ok:
                if not token_invalid_message:
                    token_invalid_message = True
                    if self.admin_uids is None or len(self.admin_uids) == 0:
                        self.get_admin_uids()
                    if len(self.admin_uids) > 0:
                        for uid in self.admin_uids:
                            self.add_msg(uid, "error", _(f"[书栈]书栈Token无效, 加入taleboook公众号私信管理员或者更新Token! 错误信息: {err}"))
                logging.info(f"[BARN] Failed to check the token, result: {err}")
                time.sleep(30 * 60)
                continue

            token_invalid_message = False
            book_list = self.client.getBookList(self.token)
            if book_list is None:
                self.client.resetChecking(self.token)
                logging.info("[BARN] Not received any book, reset the checking")
            else:
                logging.info(f"[BARN] Received {len(book_list)} books")
                self.client.setCheckingAction(self.token)
                self.process_daily_books(book_list)
                self.client.setCheckingDone(self.token)
                self.checked_day = datetime.datetime.now().strftime("%Y-%m-%d")
                time.sleep(30 * 60)
        logging.info("Exit the daily books checking")

    def process_daily_books(self, book_list):
        logging.info(f"[BARN]Processing {len(book_list)} books ...")
        count = 0
        if len(book_list) == 0:
            logging.info("[BARN]No books to process today.")
            return

        if os.path.exists(self.client.FILE_SAVE_PATH):
            shutil.rmtree(self.client.FILE_SAVE_PATH)

        # Get admin uids
        admin_uids = self.get_admin_uids()
        if len(admin_uids) == 0:
            logging.warning("[BARN]No admin users found, cannot send notifications.")
            return

        for book in book_list:
            count += 1
            if count % 2 == 0:
                self.client.setCheckingAction(self.token)

            book_id = book.get("id")
            download_link = book.get("downloadLink")
            book_size = book.get("bookSize", 0)
            autoScrape = book.get("autoScrape", 0)
            if not book_id:
                logging.warning("Book ID is missing in the book data: %s", book)
                continue

            # Here you would typically process the book, e.g., download it or update your database
            logging.info(f"[BARN]Processing book ID: {book_id}, {download_link}")

            filename = None
            if download_link.startswith("http://") or download_link.startswith("https://"):
                filename = None
            else:
                filename = download_link
                download_link = None

            # Download the book with download api
            saved_file = self.client.downloadFile(self.token, download_link, book_id, filename, book_size)
            if saved_file is None:
                logging.error(f"[BARN]Failed to download book ID {book_id}")
                continue

            # Import it to db
            fmt = os.path.splitext(saved_file)[1]
            fmt = fmt[1:] if fmt else None
            if not fmt:
                return {"err": "params.filename", "msg": _(u"文件名不合法")}
            fmt = fmt.lower()

            from calibre.ebooks.metadata.meta import get_metadata
            with open(saved_file, "rb") as stream:
                mi = get_metadata(stream, stream_type=fmt, use_libprs_metadata=True)
                mi.title = utils.super_strip(mi.title)
                mi.authors = [utils.super_strip(mi.author_sort)]

            logging.info("[BARN]upload mi.title = " + repr(mi.title))
            books = self.db.books_with_same_title(mi)
            if books:
                book_id = None
                ignore = False
                for b in self.db.get_data_as_dict(ids=books):
                    if book_id is None:
                        book_id = b.get("id")
                    if fmt.upper() in b.get("available_formats", ""):
                        ignore = True
                        break
                if ignore:
                    for uid in admin_uids:
                        self.add_msg(uid, "warning", _(f"[书栈]已存在书籍{mi.title},忽略！"))
                    logging.info("[BARN]Ignore [%s] due to existed same book and same format", repr(mi.title))
                    continue
                else:
                    self.db.add_format(book_id, fmt.upper(), saved_file, True)
                    logging.info("[BARN]import [%s] from %s with format %s", repr(mi.title), saved_file, fmt)
            else:
                fpaths = [saved_file]
                book_id = self.db.import_book(mi, fpaths)
                item = Item()
                item.book_id = book_id
                item.collector_id = admin_uids[0]
                item.save()

            for uid in admin_uids:
                self.add_msg(uid, "success", _(f"[书栈]导入书籍{mi.title}成功！"))
            if autoScrape == 1 and CONF.get(AUTO_FILL_META, False):
                AutoFillService().auto_fill(book_id)
            time.sleep(1)
        logging.info("[BARN]Processed done!")

    def get_admin_uids(self):
        # get all admin users for message notification
        admin_uids = []
        users = self.session.query(Reader).filter(Reader.admin).all()
        for user in users:
            admin_uids.append(user.id)

        self.admin_uids = admin_uids
        return admin_uids

    def _download_author_avatar(self, author_name, avatar):
        if not avatar:
            return
        try:
            author_hash = get_author_hash(author_name)
            ext = os.path.splitext(avatar)[1]
            if not ext:
                ext = ".jpg"
            for existing_ext in (".jpg", ".png", ".webp"):
                existing_file = os.path.join(AUTHOR_AVATAR_DIR, f"{author_hash}{existing_ext}")
                os.makedirs(AUTHOR_AVATAR_DIR, exist_ok=True)
                if os.path.exists(existing_file):
                    os.remove(existing_file)
            target_path = os.path.join(AUTHOR_AVATAR_DIR, f"{author_hash}{ext}")
            self.client.download_image(self.token, avatar, target_path)
        except Exception as e:
            logging.error(f"[BARN] Failed to download avatar for author {author_name}: {str(e)}")

    def sync_author(self, author_name, force=False):
        """从书栈拉取单个作者信息并写入本地 Authors 表，返回写入的 Authors 记录"""
        if not CONF.get("ENABLE_BOOKBARN", False):
            logging.info("[BARN] sync_author skipped, bookbarn is not enabled")
            return None
        if not CONF.get("ENABLE_AUTHOR_INFO", False):
            logging.info("[BARN] not enable the author info feature")
            return None

        current_token = CONF.get("BOOKBARN_TOKEN", "")
        if not current_token:
            logging.info("[BARN] sync_author skipped, bookbarn token is not set")
            return None
        self.token = current_token

        author = self.session.query(Authors).filter(Authors.name == author_name).first()
        if author is not None and not force:
            return author

        try:
            data = self.client.get_author(self.token, author_name)
            if data is None:
                logging.info(f"[BARN] no author info found for {author_name}")
                return None

            if author is None:
                author = Authors(name=author_name, sort=data.get("sort", ""))
                self.session.add(author)
            author.author_id = data.get("id", 0) or 0
            author.sort = data.get("sort", "")
            author.bio = data.get("bio", "")
            author.region = data.get("region", "")
            author.avatar = data.get("avatar", "")
            self.session.commit()

            self._download_author_avatar(author_name, data.get("avatar", ""))
            return author
        except Exception as e:
            logging.error(f"[BARN] Failed to sync author {author_name}: {str(e)}")
            self.session.rollback()
            return None

    @AsyncService.register_service
    def sync_author_list(self):
        """遍历 author_list.txt，为本地缺失的作者从书栈拉取信息（启动后延迟触发一次）"""
        if not CONF.get("ENABLE_BOOKBARN", False) or not CONF.get("BOOKBARN_TOKEN", ""):
            logging.info("[BARN] author list sync skipped, bookbarn not enabled/configured")
            return

        path = os.path.join(CONF.get("resource_path", ""), "authors", "author_list.txt")
        if not os.path.exists(path):
            logging.info(f"[BARN] author list file not found: {path}")
            return

        time.sleep(10.0)

        try:
            with open(path, "r", encoding="utf-8") as f:
                names = [line.strip() for line in f if line.strip()]
        except Exception:
            names = []

        logging.info(f"[BARN] start checking {len(names)} authors from BookBarn, if not found in local, will sync it")
        for name in names:
            self.sync_author(name, force=False)
            time.sleep(1)
        logging.info("[BARN] author list check done")

    @AsyncService.register_service
    def update_author_async(self, author_name, admin_uid=None, force=True):
        """单作者信息更新，后台线程执行避免阻塞请求；force=True（默认，管理员手动触发场景）强制联网更新，force=False 时本地已有该作者信息则跳过"""
        author = self.sync_author(author_name, force=force)
        if admin_uid:
            status = "success" if author else "error"
            template = _("作者 %(name)s 信息更新成功") if author else _("作者 %(name)s 信息更新失败")
            self.add_msg(admin_uid, status, template % {"name": author_name})
