import datetime
import requests
import logging
import os
import shutil
import time
import re

from urllib.parse import urlparse, unquote

from webserver.services import AsyncService
from webserver.services.autofill import AutoFillService
from webserver import loader, utils
from webserver.version import VERSION
from webserver.models import Reader, Item
from webserver.constants import AUTO_FILL_META
from gettext import gettext as _
import platform


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
    HOST_BASE = "http://43.138.200.142:8088/"
    # HOST_BASE = "http://127.0.0.1:8088/"
    CHECK_TOKEN_API = "bookbarn/check"
    APPLY_TOKEN_API = "bookbarn/token"
    CHECK_LATEST_RELEASE_API = "bookbarn/release/check"
    UPDATE_ACTION_API = "bookbarn/token/action"
    GET_BOOKS_API = "bookbarn/pubbooks"
    DOWNLOAD_API = "getfile"
    FILE_SAVE_PATH = "/tmp/bookbarn/"

    ACTION_NONE = 0
    ACTION_CHECKING = 1
    ACTION_DONE = 2

    def __init__(self):
        self.token = None
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0",
            "Referer": "https://mybooks.top/",
        }

    def checkToken(self, token):
        params = {
            "version": VERSION,
            "token": token
        }
        response = requests.get(self.HOST_BASE + self.CHECK_TOKEN_API, params=params, verify=False)
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
        response = requests.post(self.HOST_BASE + self.APPLY_TOKEN_API, json=data, verify=False)

        if response.status_code == 200:
            data = response.json().get("data")
            if data is not None:
                self.token = data.get("token")
            logging.info(f"[BARN]Token applied successfully: {self.token}")
            return self.token
        else:
            raise Exception(f"[BARN]Failed to apply token: {response.status_code} - {response.text}")

    def checkLatestRelease(self, token):
        params = {
            "version": VERSION,
            "token": token,
            "platform": get_os() + "-" + get_arch()
        }

        result = None
        try:
            response = requests.get(self.HOST_BASE + self.CHECK_LATEST_RELEASE_API, params=params, verify=False)
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
        except Exception as e:
            logging.error(f"Exception occurred while checking latest release: {str(e)}")
        return result

    def _updateAction(self, token, action):
        data = {
            "version": VERSION,
            "token": token,
            "action": action
        }
        response = requests.post(self.HOST_BASE + self.UPDATE_ACTION_API, json=data, verify=False)

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
        response = requests.get(self.HOST_BASE + self.GET_BOOKS_API, params=params, verify=False)

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
            with self.session.get(download_url, headers=self.headers, params=params, stream=True, verify=False) as r:
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
            except:
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
                if latest_release is not None:
                    logging.info(f"[BARN]New version available: {latest_release['rev']}, released on {latest_release['date']}")
                    if self.admin_uids is None or len(self.admin_uids) == 0:
                        admin_uids = self.get_admin_uids()
                    if len(admin_uids) > 0:
                        message = f"有新版本发布: {latest_release['rev']}，发布日期: {latest_release['date']}，\
                                    更新内容: {latest_release['notes']}，请重新构建容器以获取更新。"
                        for uid in admin_uids:
                            self.add_msg(uid, "info", message)

            if not CONF.get("ENABLE_BOOKBARN", False) or not CONF.get("ENABLE_RECEIVING_BOOKS", False):
                time.sleep(15 * 60)
                logging.info("[BARN]Daily books checking, not enabled")
                continue

            if self.checked_day is not None:
                today = datetime.datetime.now().strftime("%Y-%m-%d")
                if self.checked_day <= today:
                    # Has checked for today update
                    time.sleep(15 * 60)
                    continue

            current_token = CONF.get("BOOKBARN_TOKEN", "")
            if len(current_token) == 0:
                time.sleep(10 * 60)
                logging.info("[BARN]Daily books checking, not set token")
                continue
            if self.token != current_token:
                self.token = current_token

            hour = int(CONF.get("BOOKBARN_COLLECTION_HOUR", 3))
            current_hour = datetime.datetime.now().hour

            if current_hour != hour:
                if output_hour != current_hour:
                    logging.info(f"[BARN]Not target time {hour}, now is {current_hour}")
                    output_hour = current_hour
                time.sleep(5 * 60)
                continue

            ok, err = self.client.checkToken(self.token)
            if not ok:
                if not token_invalid_message:
                    token_invalid_message = True
                    if self.admin_uids is None or len(self.admin_uids) == 0:
                        admin_uids = self.get_admin_uids()
                    if len(admin_uids) > 0:
                        for uid in admin_uids:
                            self.add_msg(uid, "error", _(f"[书栈]书栈Token无效, 加入taleboook公众号私信管理员或者更新Token! 错误信息: {err}"))
                time.sleep(10 * 60)
                continue
            else:
                token_invalid_message = False

            book_list = self.client.getBookList(self.token)
            if book_list is None:
                self.client.resetChecking(self.token)
            else:
                self.client.setCheckingAction(self.token)
                self.process_daily_books(book_list)
                self.client.setCheckingDone(self.token)
                self.checked_day = datetime.datetime.now().strftime("%Y-%m-%d")
                time.sleep(10 * 60)

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
