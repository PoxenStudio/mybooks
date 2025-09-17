#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import datetime
import logging
import os
import re
import shutil
import threading
import time
import traceback
import urllib.parse
import uuid
import zipfile
from gettext import gettext as _
from webserver.version import VERSION

import tornado
from tornado import web

from webserver import loader, utils
from webserver.handlers.base import BaseHandler, auth, js, is_admin
from webserver.models import BizKey, ReaderPaidBook, ReaderLog
from webserver.worker.epub2audio_worker import EpubToAudioWorker

CONF = loader.get_settings()
ENABLE_VIP_QUOTA_KEY = "ENABLE_VIP_QUOTA"

# map of conversion workers, key is book id, value is instance of the worker
ConversionWorkerMap = {}

# 每日下载记录，格式: {(user_id, book_id): datetime}
DailyDownloadMap = {}
ALLOW_MAX_RUNNING_WORKERS = CONF.get("BOOK2AUDIO_MAX_WORKERS", 2)
AUDIO_OUTPUT_FOLDER = CONF.get("audio_output_folder", "/data/books/audios/")
SKIP_FILE_PREFIX = "图书在版编目CIP数据"
MAX_FREE_AUDIO_FILES = 6


class AudioUtils:
    site_url = ""

    @staticmethod
    def get_running_worker_count():
        """Get the count of currently running audio conversion workers."""
        return sum(1 for worker in ConversionWorkerMap.values() if worker.is_running())

    @staticmethod
    def get_audio_books_count():
        """Get the total count of books with audio files."""
        if not os.path.exists(AUDIO_OUTPUT_FOLDER):
            return 0
        count = 0
        for item in os.listdir(AUDIO_OUTPUT_FOLDER):
            item_path = os.path.join(AUDIO_OUTPUT_FOLDER, item)
            if os.path.isdir(item_path) and item.isdigit():
                count += 1
        return count

    @staticmethod
    def get_audios(bid, uid=None):
        """Get audio files for a book."""
        if uid is None:
            return {"status": "unavailable", "msg": _(u"登录后才能查看音频"), "count": 0}

        if not AudioUtils.site_url:
            AudioUtils.site_url = BaseHandler.get_site_url()

        book_id = int(bid)
        audio_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
        if not os.path.exists(audio_dir):
            return {"status": "unavailable", "msg": _(u"没有发现音频文件目录"), "count": 0}

        worker = ConversionWorkerMap.get(book_id)
        audio_files = [f for f in os.listdir(audio_dir) if f.endswith(('.mp3', '.wav'))]
        if not audio_files:
            if worker:
                return {"status": worker.get_status(),
                        "progress": worker.get_progress(),
                        "audio_dir": audio_dir,
                        "audios": [],
                        "count": 0
                        }
            else:
                return {"status": "unavailable", "msg": _(u"没有发现音频文件"), "count": 0}

        file_urls = []
        for file in sorted(audio_files):
            file_path = os.path.join(audio_dir, file)
            file_size = os.path.getsize(file_path)
            if file_size <= 1024:  # Ignore files smaller than 1K
                continue
            file_urls.append({
                "filename": os.path.splitext(file)[0],
                "url": f"{AudioUtils.site_url}/api/audio/{book_id}/{file}",
                "size": file_size
            })

        if worker and not worker.is_completed():
            # If conversion is in progress, return worker status
            return {"status": worker.get_status(),
                    "progress": worker.get_progress(),
                    "audio_dir": audio_dir,
                    "audios": file_urls,
                    "count": len(file_urls)
                    }
        else:
            return {"status": EpubToAudioWorker.STATUS_CONVERTED,
                    "audio_dir": audio_dir,
                    "audios": file_urls,
                    "count": len(file_urls)
                    }


class AudioDetail(BaseHandler):
    @js
    def get(self, book_id):
        # get the audio file path from the book id, if not found, check the book id in the worker map,
        # if found, return the worker status, otherwise return not found status.
        try:
            book_id = int(book_id)
            book = self.get_book(book_id)
            if not book:
                return {"err": "params.book.invalid", "msg": _(u"书籍未找到")}

            enable_vip_quota = CONF.get(ENABLE_VIP_QUOTA_KEY, False)

            # Check if audio file already exists
            audio_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
            if os.path.exists(audio_dir) and os.listdir(audio_dir):
                audio_files = [f for f in os.listdir(audio_dir) if f.endswith(('.mp3', '.wav', '.m4a', '.opus'))]
                if audio_files:
                    user = self.get_current_user()
                    is_paid = False
                    if user:
                        if enable_vip_quota:
                            # 检查用户是否已购买此书
                            paid_record = self.sqlite_session.query(ReaderPaidBook).filter_by(
                                reader_id=user.id,
                                book_id=book_id
                            ).first()
                            is_paid = paid_record is not None
                        else:
                            is_paid = True

                    # Generate download URLs for audio files
                    file_urls = []
                    for file in sorted(audio_files):
                        if file.find(SKIP_FILE_PREFIX) > 0:
                            continue
                        file_urls.append({
                            "filename": os.path.splitext(file)[0],
                            "url": f"{self.site_url}/api/audio/{book_id}/{file}",
                            "size": os.path.getsize(os.path.join(audio_dir, file))
                        })
                    return {
                        "err": "ok",
                        "audio_dir": audio_dir,
                        "audios": file_urls,
                        "total_files": len(audio_files),
                        "is_paid": is_paid
                    }

            # Check if conversion is in progress
            worker = ConversionWorkerMap.get(book_id)
            if worker:
                progress = worker.get_progress()
                return {"err": "ok", "msg": _(u"已经在生成音频中"), "data": progress}

            return {"err": "audio.not_found", "msg": _(u"没有发现音频文件")}

        except ValueError:
            return {"err": "params.invalid", "msg": _(u"无效的书籍ID")}
        except Exception as e:
            logging.error(f"Error in AudioDetail.get: {e}")
            return {"err": "server.error", "msg": str(e)}


class AudioBooks(BaseHandler):
    @js
    def get(self):
        """获取有音频的书籍列表"""
        try:
            # 获取启动参数
            start = self.get_argument_start()
            size = int(self.get_argument("size", 60))

            # 扫描音频目录，获取有音频文件的书籍ID
            audios_cnt_map = {}
            audio_book_ids = []
            if os.path.exists(AUDIO_OUTPUT_FOLDER):
                for item in os.listdir(AUDIO_OUTPUT_FOLDER):
                    item_path = os.path.join(AUDIO_OUTPUT_FOLDER, item)
                    if os.path.isdir(item_path) and item.isdigit():
                        book_id = int(item)
                        # 检查目录中是否有音频文件
                        audio_files = [f for f in os.listdir(item_path) if f.endswith(('.mp3', '.wav', '.m4a', '.opus'))]
                        if audio_files:
                            audio_book_ids.append(book_id)
                            audios_cnt_map[book_id] = len(audio_files)

            # 分页处理
            total = len(audio_book_ids)
            paginated_ids = audio_book_ids[start:start + size]

            # 获取书籍信息，参考 base.py 中的 get_books 函数进行权限过滤
            books = []
            if paginated_ids:
                books = self.get_books(ids=paginated_ids)

            # 按书籍ID倒排
            books.sort(key=lambda x: x['id'], reverse=True)

            books_result = []
            for book in books:
                book_data = utils.BookFormatter(self, book).format()
                book_data['has_audio'] = True
                book_data['audio_count'] = audios_cnt_map.get(book['id'], 0)
                books_result.append(book_data)

            return {
                "err": "ok",
                "title": _(u"有声书"),
                "books": books_result,
                "total": total
            }

        except Exception as e:
            logging.error(f"Error in AudioBooks.get: {e}")
            return {"err": "server.error", "msg": str(e)}


class AudioConversion(BaseHandler):
    @js
    def get(self, bid):
        # get the conversion status, check it in the worker map,
        # return the status json if found it in the map, otherwise, return not found status.
        try:
            book_id = int(bid)
            worker = ConversionWorkerMap.get(book_id)
            if worker:
                progress = worker.get_progress()
                if progress and progress["status"] == EpubToAudioWorker.STATUS_CONVERTED:
                    # remove the book id from ConversionWorkerMap
                    ConversionWorkerMap.pop(book_id, None)
                    return {"err": "ok", "msg": _(u"转换完成"), "data": progress}
                elif progress and progress["status"] == EpubToAudioWorker.STATUS_FAILED:
                    return {"err": "audio.conversion_failed", "msg": _(u"转换失败"), "data": progress}
                else:
                    return {"err": "ok", "msg": EpubToAudioWorker.STATUS_PROCESSING, "data": progress}
            else:
                return {"err": "audio.no_conversion", "msg": _(u"没有发现转换任务"), "data": None}
        except ValueError:
            return {"err": "params.invalid", "msg": _(u"无效的书籍ID")}
        except Exception as e:
            logging.error(f"Error in AudioConversion.get: {e}")
            return {"err": "server.error", "msg": str(e)}

    @js
    @is_admin
    def post(self, bid):
        if not self.is_admin():
            return {"err": "permission.not_admin", "msg": _(u"只有管理员可以进行有声书转换")}

        try:
            if AudioUtils.get_running_worker_count() >= ALLOW_MAX_RUNNING_WORKERS:
                return {"err": "audio.too_many_conversions", "msg": _(u"当前转换任务超过2项, 请稍后再试")}

            book_id = int(bid)
            req = tornado.escape.json_decode(self.request.body)
            voice_name = req.get("voice", "zh-CN-YunjianNeural")
            language = req.get("language", "zh-CN")

            logging.info(f"Starting audio conversion for book {book_id} with voice {voice_name} and language {language}")

            # Check if book exists
            book = self.get_book(book_id)
            if not book:
                return {"err": "params.book.invalid", "msg": _(u"书籍未找到")}

            # Check if conversion is already running
            if book_id in ConversionWorkerMap:
                worker = ConversionWorkerMap[book_id]
                if worker.is_running():
                    return {"err": "audio.already_converting", "msg": _(u"转换已经在进行中")}
                else:
                    # Remove stale worker
                    ConversionWorkerMap.pop(book_id, None)

            # Get EPUB file path
            epub_path = book.get("fmt_epub")
            if not epub_path:
                return {"err": "params.book.no_epub", "msg": _(u"书籍没有EPUB格式")}

            # Validate that the EPUB file actually exists
            if not os.path.exists(epub_path):
                return {"err": "params.book.epub_missing", "msg": _(u"未找到EPUB文件")}

            # Create output directory
            output_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
            os.makedirs(output_dir, exist_ok=True)

            # Create new worker and start conversion
            epub_to_audio_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "epub_to_audio", "main.py")
            worker = EpubToAudioWorker(main_py_path=epub_to_audio_path)
            ConversionWorkerMap[book_id] = worker

            # Start conversion in background thread
            def start_conversion():
                logging.info(f"Starting conversion for book {book_id} in background thread")
                logging.info(f"EPUB path: {epub_path}, Output dir: {output_dir}, Voice: {voice_name}, Language: {language}")
                proxy = CONF.get("BOOK2AUDIO_PROXY", None)
                try:
                    result = worker.convert_epub_to_audio(
                        epub_path=epub_path,
                        output_dir=output_dir,
                        voice_name=voice_name,
                        language=language,
                        tts="edge",
                        worker_count=2,
                        no_prompt=True,
                        show_output=False,
                        proxy=proxy
                    )
                    if result['success']:
                        worker.progress_data["status"] = EpubToAudioWorker.STATUS_PROCESSING
                    else:
                        logging.error(f"Conversion failed for book {book_id}: {result.get('error', 'Unknown error')}")
                        worker.progress_data["status"] = EpubToAudioWorker.STATUS_FAILED
                        worker.progress_data["error_message"] = result.get('error', 'Unknown error')
                except Exception as e:
                    logging.error(f"Exception during conversion for book {book_id}: {e}")
                    # Mark worker as failed and clean up
                    worker.progress_data["status"] = EpubToAudioWorker.STATUS_FAILED
                    worker.progress_data["error_message"] = str(e)
                finally:
                    # Clean up completed or failed workers after some time
                    def cleanup_worker():
                        time.sleep(60)  # Wait 1 minute before cleanup
                        if book_id in ConversionWorkerMap and not ConversionWorkerMap[book_id].is_running():
                            ConversionWorkerMap.pop(book_id, None)

                    cleanup_thread = threading.Thread(target=cleanup_worker)
                    cleanup_thread.daemon = True
                    cleanup_thread.start()

            thread = threading.Thread(target=start_conversion)
            thread.daemon = True
            thread.start()

            logging.info(f"Conversion started for book {book_id} in background thread")
            worker_checker = ConversionWorkerMap.get(book_id)
            if worker_checker:
                return {"err": "ok", "msg": _(u"开始转换"), "data": worker_checker.get_progress()}
            else:
                logging.error(f"Worker for book {book_id} not found after starting conversion")

            return {"err": "ok", "msg": _(u"开始转换")}

        except ValueError:
            return {"err": "params.invalid", "msg": _(u"无效的书籍ID")}
        except Exception as e:
            logging.error(f"Error in AudioConversion.post: {e}")
            return {"err": "server.error", "msg": str(e)}
        except ValueError:
            return {"err": "params.invalid", "msg": _(u"无效的书籍ID")}
        except Exception as e:
            logging.error(f"Error in AudioConversion.post: {e}")
            return {"err": "server.error", "msg": str(e)}


class AudioConversionCancel(BaseHandler):
    @js
    @is_admin
    def post(self, book_id):
        # cancel the conversion for the book id, if the worker exists, stop it and remove it from the map.
        if not self.is_admin():
            return {"err": "permission.not_admin", "msg": _(u"只有管理员可以取消有声书转换")}

        try:
            book_id = int(book_id)
            worker = ConversionWorkerMap.get(book_id)
            if worker:
                worker.stop()
                ConversionWorkerMap.pop(book_id, None)

                time.sleep(1)  # Give some time for the worker to stop

                audio_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
                if os.path.exists(audio_dir):
                    try:
                        shutil.rmtree(audio_dir)
                        return {"err": "ok", "msg": _(u"转换已取消, 生成的音频文件已删除成功")}
                    except OSError as e:
                        logging.error(f"Error deleting audio directory {audio_dir}: {e}")
                        return {"err": "server.error", "msg": f"转换已取消，清理音频文件遇到错误: {e}"}

                return {"err": "ok", "msg": _(u"转换已取消")}
            else:
                return {"err": "audio.no_conversion", "msg": _(u"没有发现转换任务"), "data": None}
        except ValueError:
            return {"err": "params.invalid", "msg": _(u"无效的书籍ID")}
        except Exception as e:
            logging.error(f"Error in AudioConversionCancel.post: {e}")
            return {"err": "server.error", "msg": str(e)}


class AudioDelete(BaseHandler):
    @js
    @is_admin
    def post(self, book_id):
        # delete the audio file for the book id, if the file exists, remove it.
        # if not found, return not found status.
        if not self.is_admin():
            return {"err": "permission.not_admin", "msg": _(u"只有管理员可以删除音频文件")}

        try:
            book_id = int(book_id)

            # Check if conversion is running and stop it first
            worker = ConversionWorkerMap.get(book_id)
            if worker:
                if worker.is_running():
                    return {"err": "audio.conversion_running", "msg": _(u"无法在转换进行时删除")}
                ConversionWorkerMap.pop(book_id, None)

            # Delete audio directory
            audio_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
            if os.path.exists(audio_dir):
                try:
                    shutil.rmtree(audio_dir)
                    return {"err": "ok", "msg": _(u"音频文件删除成功")}
                except OSError as e:
                    logging.error(f"Error deleting audio directory {audio_dir}: {e}")
                    return {"err": "server.error", "msg": f"清理音频文件遇到错误: {e}"}
            else:
                return {"err": "audio.not_found", "msg": _(u"未找到要删除的音频文件")}

        except ValueError:
            return {"err": "params.invalid", "msg": _(u"无效的书籍ID")}
        except Exception as e:
            logging.error(f"Error in AudioDelete.post: {e}")
            return {"err": "server.error", "msg": str(e)}


class AudioFile(BaseHandler):
    @auth
    def get(self, book_id, filename):
        """提供音频文件的静态文件服务"""
        logging.info(f"AudioFile requested: book_id={book_id}, filename={filename}")
        try:
            book_id = int(book_id)

            # URL解码文件名
            filename = urllib.parse.unquote(filename)

            enable_vip_quota = CONF.get(ENABLE_VIP_QUOTA_KEY, False)
            if enable_vip_quota:
                user = self.get_current_user_sync()
            else:
                user = self.get_current_user()

            if enable_vip_quota:
                # 检查当前用户是否已购买此书
                paid_record = self.sqlite_session.query(ReaderPaidBook).filter_by(
                    reader_id=user.id,
                    book_id=book_id
                ).first()

                # 如果未购买，检查是否为免费音频
                if not paid_record:
                    try:
                        # 从文件名中提取序号，文件名格式为0000_xxxxxx, 前四个是序号
                        serial_number = int(filename.split("_")[0])
                        if serial_number > MAX_FREE_AUDIO_FILES:
                            raise web.HTTPError(403, "未购买音频，无法播放此章节")
                    except (ValueError, IndexError):
                        # 如果无法解析序号，则不允许播放
                        raise web.HTTPError(403, "无效的音频文件格式")

            # 安全检查: 确保文件名不包含路径遍历
            if ".." in filename or "/" in filename:
                raise web.HTTPError(403, "Invalid filename")

            audio_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
            file_path = os.path.join(audio_dir, filename)

            if not os.path.exists(file_path):
                raise web.HTTPError(404, "Audio file not found")

            # 设置适当的Content-Type
            if filename.endswith('.mp3'):
                self.set_header("Content-Type", "audio/mpeg")
            elif filename.endswith('.wav'):
                self.set_header("Content-Type", "audio/wav")
            elif filename.endswith('.m4a'):
                self.set_header("Content-Type", "audio/mp4")
            elif filename.endswith('.opus'):
                self.set_header("Content-Type", "audio/opus")
            else:
                self.set_header("Content-Type", "audio/mpeg")

            # 支持范围请求 (Range requests) 用于音频播放
            self.set_header("Accept-Ranges", "bytes")

            # 获取文件大小
            file_size = os.path.getsize(file_path)

            # 处理范围请求
            range_header = self.request.headers.get("Range")
            if range_header:
                range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
                if range_match:
                    start = int(range_match.group(1))
                    end = int(range_match.group(2)) if range_match.group(2) else file_size - 1

                    if start >= file_size:
                        self.set_status(416)  # Range Not Satisfiable
                        return

                    self.set_status(206)  # Partial Content
                    self.set_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                    self.set_header("Content-Length", str(end - start + 1))

                    with open(file_path, "rb") as f:
                        f.seek(start)
                        remaining = end - start + 1
                        while remaining > 0:
                            chunk_size = min(8192, remaining)
                            chunk = f.read(chunk_size)
                            if not chunk:
                                break
                            self.write(chunk)
                            remaining -= len(chunk)
                    return

            # 正常文件传输
            self.set_header("Content-Length", str(file_size))
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    self.write(chunk)

        except ValueError:
            raise web.HTTPError(400, "Invalid book ID")
        except Exception as e:
            logging.error(f"Error in AudioFile.get: {e}")
            raise web.HTTPError(500, "内部错误")


class AudioCollection(BaseHandler):
    def create_biz_key(self):
        user = self.get_current_user()
        # 生成32位随机key
        download_key = uuid.uuid4().hex
        # 保存key到BizKey表，设置过期时间为24小时
        expire_time = datetime.datetime.now() + datetime.timedelta(hours=24)
        biz_key = BizKey(user.id, key=download_key, expire=expire_time, type=BizKey.TYPE_DOWNLOAD)
        try:
            biz_key.save()
        except Exception as e:
            logging.error(f"Error saving BizKey: {e}")
            return None
        return download_key

    @js
    @auth
    def get(self, book_id):
        """音频合集下载接口"""
        try:
            book_id = int(book_id)

            # 获取当前用户
            user = self.get_current_user()
            if not user:
                return {"err": "auth.required", "msg": _("需要登录")}

            db_log = ReaderLog(user.id, ReaderLog.ACTION_COLLECTION_DOWNLOAD, user.id, revision=VERSION)
            db_log.set_extra('book_id', book_id)

            # 检查书籍是否存在
            book = self.get_book(book_id)
            if not book:
                db_log.set_extra('result', -1)
                db_log.set_extra('reason', "book.not_found")
                db_log.save()
                return {"err": "book.not_found", "msg": _("书籍未找到")}

            enable_vip_quota = CONF.get(ENABLE_VIP_QUOTA_KEY, False)
            if enable_vip_quota:
                # 检查用户是否已购买此书
                paid_record = self.sqlite_session.query(ReaderPaidBook).filter_by(
                    reader_id=user.id,
                    book_id=book_id
                ).first()

                if not paid_record:
                    db_log.set_extra('result', -1)
                    db_log.set_extra('reason', "not.purchased")
                    db_log.save()
                    return {"err": "not.purchased", "msg": _("您还未购买此音频，请先购买")}

                # 检查每日下载限制
                download_key = (user.id, book_id)
                today = datetime.datetime.now().date()

                if download_key in DailyDownloadMap:
                    last_download = DailyDownloadMap[download_key]
                    if last_download.date() == today:
                        db_log.set_extra('result', -1)
                        db_log.set_extra('reason', "daily.limit.exceeded")
                        db_log.save()
                        return {"err": "daily.limit.exceeded", "msg": _("今日已下载过此音频合集，请明天再试")}

            # 检查音频目录
            audio_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
            if not os.path.exists(audio_dir):
                logging.error(f"Audio directory does not exist: {audio_dir}")
                return {"err": "audio.not_found", "msg": _("音频文件不存在")}

            audio_files = [f for f in os.listdir(audio_dir) if f.endswith(('.mp3', '.wav', '.m4a', '.opus'))]
            if not audio_files:
                return {"err": "audio.not_found", "msg": _("音频文件不存在")}

            # 检查zip文件是否已存在
            zip_filename = f"audio_collection_{book_id}.zip"
            zip_path = os.path.join(audio_dir, zip_filename)

            # 如果zip不存在，创建它
            if not os.path.exists(zip_path):
                try:
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for audio_file in sorted(audio_files):
                            if audio_file.find(SKIP_FILE_PREFIX) > 0:
                                continue
                            file_path = os.path.join(audio_dir, audio_file)
                            zipf.write(file_path, audio_file)
                except Exception as e:
                    logging.error(f"Error creating zip file: {e}")
                    return {"err": "server.error", "msg": _("创建压缩文件失败")}

            # 查询是否已有未过期的下载key
            existing_key = self.sqlite_session.query(BizKey).filter_by(
                reader_id=user.id,
                type=BizKey.TYPE_DOWNLOAD
            ).filter(BizKey.expire > datetime.datetime.now()).first()
            if existing_key:
                download_key = existing_key.key
            else:
                # 创建下载key，不需要扣减VIP配额
                download_key = self.create_biz_key()

            if not download_key:
                return {"err": "server.error", "msg": _("内部处理错误")}

            # 记录下载时间
            DailyDownloadMap[(user.id, book_id)] = datetime.datetime.now()

            # 生成下载链接
            download_url = f"{self.get_site_url()}/api/audios/{book_id}/collection/download?key={download_key}"

            # 保存日志
            db_log.set_extra('result', 0)
            db_log.set_extra('reason', "success")
            db_log.save()

            return {
                "err": "ok",
                "download_url": download_url,
                "message": "下载链接已生成"
            }
        except ValueError:
            return {"err": "params.invalid", "msg": _("无效的书籍ID")}
        except Exception as e:
            logging.error(f"Error in AudioCollectionDownload.get: {e}")
            logging.error(f"Stack trace: {traceback.format_exc()}")

            return {"err": "server.error", "msg": str(e)}


class AudioCollectionDownloadFile(BaseHandler):
    def get(self, book_id):
        """音频合集文件下载接口"""
        try:
            logging.info(f"AudioCollectionDownloadFile called for book_id: {book_id}")
            book_id = int(book_id)
            download_key = self.get_argument("key", "")

            if not download_key:
                raise web.HTTPError(400, "Missing download key")

            # 验证下载key
            biz_key = self.sqlite_session.query(BizKey).filter_by(key=download_key, type=BizKey.TYPE_DOWNLOAD).first()
            if not biz_key:
                raise web.HTTPError(403, "Invalid download key")

            if biz_key.expire < datetime.datetime.now():
                # 清理过期的key
                biz_key.delete()
                raise web.HTTPError(403, "Download key expired")

            # 检查zip文件
            audio_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
            zip_filename = f"audio_collection_{book_id}.zip"
            zip_path = os.path.join(audio_dir, zip_filename)
            uid = biz_key.reader_id

            db_log = ReaderLog(uid, ReaderLog.ACTION_COLLECTION_DOWNLOAD_START, uid, revision=VERSION)
            db_log.set_extra('book_id', book_id)
            db_log.save()

            if not os.path.exists(zip_path):
                raise web.HTTPError(404, "合集文件不存在")

            # 获取书籍信息用于文件名
            book = self.get_book(book_id)
            safe_title = "".join(c for c in (book.get('title', f'book_{book_id}') if book else f'book_{book_id}')
                                 if c.isalnum() or c in (' ', '-', '_')).rstrip()

            # 构建文件名，处理中文字符
            filename_base = f"{safe_title}_音频合集.zip"
            # URL编码文件名以支持中文
            encoded_filename = urllib.parse.quote(filename_base.encode('utf-8'))

            # 设置响应头
            self.set_header("Content-Type", "application/zip")
            # 使用 RFC 5987 标准来支持非ASCII字符的文件名
            self.set_header("Content-Disposition", f"attachment; filename*=UTF-8''{encoded_filename}")

            # 获取文件大小
            file_size = os.path.getsize(zip_path)
            self.set_header("Content-Length", str(file_size))

            # 传输文件
            start = time.time()
            chunk_size = 2 * 1024 * 1024  # 2MB
            with open(zip_path, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    self.write(chunk)
            duration = int(time.time() - start)

            try:
                db_log = ReaderLog(uid, ReaderLog.ACTION_COLLECTION_DOWNLOAD_FINISHED, uid, revision=VERSION)
                db_log.set_extra('book_id', book_id)
                db_log.set_extra('duration', duration)
                db_log.save()
                # 删除使用过的key
                self.sqlite_session.delete(biz_key)
                self.sqlite_session.commit()
            except Exception as e:
                logging.error(f"Error deleting BizKey after download: {e}")
        except ValueError:
            raise web.HTTPError(400, "Invalid book ID")
        except Exception as e:
            logging.error(f"Error in AudioCollectionDownloadFile.get: {e}")
            raise web.HTTPError(500, "Internal server error")


class AudioPurchase(BaseHandler):
    @js
    @auth
    def post(self, book_id):
        """音频购买接口"""
        try:
            book_id = int(book_id)

            # 获取当前用户
            user = self.get_current_user_sync()
            if not user:
                return {"err": "auth.required", "msg": _("需要登录")}

            # 检查书籍是否存在
            book = self.get_book(book_id)
            if not book:
                return {"err": "book.not_found", "msg": _("书籍未找到")}

            # 检查是否启用VIP配额功能
            enable_vip_quota = CONF.get(ENABLE_VIP_QUOTA_KEY, False)

            if enable_vip_quota:
                # 检查VIP是否过期
                if not user.vipexpire or user.vipexpire < datetime.datetime.now():
                    # 读取VIP说明文件
                    vip_notes_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                                  "app", "public", "vip_notes.txt")
                    vip_notes = ""
                    try:
                        if os.path.exists(vip_notes_path):
                            with open(vip_notes_path, 'r', encoding='utf-8') as f:
                                vip_notes = f.read()
                    except Exception as e:
                        logging.error(f"Error reading vip_notes.txt: {e}")
                        vip_notes = "无法读取VIP说明文件"

                    return {
                        "err": "vip.expired",
                        "msg": "非VIP用户或VIP已过期，无法购买音频",
                        "vipexpired": user.vipexpire.strftime("%Y-%m-%d %H:%M:%S") if user.vipexpire else "",
                        "notes": vip_notes
                    }

                # 检查VIP配额
                if user.vipquota <= 0:
                    # 读取VIP说明文件
                    vip_notes_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                                  "app", "public", "vip_notes.txt")
                    vip_notes = ""
                    try:
                        if os.path.exists(vip_notes_path):
                            with open(vip_notes_path, 'r', encoding='utf-8') as f:
                                vip_notes = f.read()
                    except Exception as e:
                        logging.error(f"Error reading vip_notes.txt: {e}")
                        vip_notes = "无法读取VIP说明文件"

                    return {
                        "err": "vip.quota_insufficient",
                        "msg": "购买的额度不足",
                        "notes": vip_notes
                    }

            # 检查是否已经购买过
            existing_purchase = self.sqlite_session.query(ReaderPaidBook).filter_by(
                reader_id=user.id,
                book_id=book_id
            ).first()

            if existing_purchase:
                return {"err": "already.purchased", "msg": _("您已经购买过此音频")}

            # 检查音频是否存在
            audio_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
            if not os.path.exists(audio_dir):
                return {"err": "audio.not_found", "msg": _("音频文件不存在")}

            audio_files = [f for f in os.listdir(audio_dir) if f.endswith(('.mp3', '.wav', '.m4a', '.opus'))]
            if not audio_files:
                return {"err": "audio.not_found", "msg": _("音频文件不存在")}

            # 创建购买记录
            # 生成订单ID
            import uuid
            order_id = uuid.uuid4().hex

            # 这里可以设置音频的价格，暂时设为1（可以从配置或书籍信息中获取）
            price = CONF.get("audio_price", 1)

            paid_book = ReaderPaidBook(
                reader_id=user.id,
                book_id=book_id,
                order_id=order_id,
                price=price
            )

            try:
                paid_book.save()

                # 如果启用VIP配额功能，则扣减用户VIP配额
                if enable_vip_quota:
                    try:
                        user.vipquota -= 1
                        user.save()
                    except Exception as e:
                        logging.error(f"Error updating user quota after purchase: {e}")
                        # 如果配额扣减失败，回滚购买记录
                        try:
                            self.sqlite_session.delete(paid_book)
                            self.sqlite_session.commit()
                        except:
                            pass
                        return {"err": "server.error", "msg": _("购买失败，配额扣减出错")}

                # 记录购买日志
                log = ReaderLog(user.id, ReaderLog.ACTION_PURCHASE, user.id)
                log.set_extra("book_id", book_id)
                log.set_extra("order_id", order_id)
                log.set_extra("price", price)
                log.save()

                return {
                    "err": "ok",
                    "msg": _("购买成功"),
                    "order_id": order_id
                }
            except Exception as e:
                logging.error(f"Error saving purchase record: {e}")
                return {"err": "server.error", "msg": _("购买失败，请稍后重试")}

        except ValueError:
            return {"err": "params.invalid", "msg": _("无效的书籍ID")}
        except Exception as e:
            logging.error(f"Error in AudioPurchase.post: {e}")
            return {"err": "server.error", "msg": str(e)}


def routes():
    return [
        (r"/api/audio/([0-9]+)", AudioDetail),
        (r"/api/audio/([0-9]+)/conversion", AudioConversion),
        (r"/api/audio/([0-9]+)/cancel", AudioConversionCancel),
        (r"/api/audio/([0-9]+)/delete", AudioDelete),
        (r"/api/audio/([0-9]+)/purchase", AudioPurchase),  # 音频购买接口
        (r"/api/audiobooks", AudioBooks),  # 音频书籍列表
        (r"/api/audio/([0-9]+)/([^/]+)", AudioFile),
        (r"/api/audios/([0-9]+)/collection", AudioCollection),  # 音频合集下载接口
        (r"/api/audios/([0-9]+)/collection/download", AudioCollectionDownloadFile),  # 音频合集文件下载
    ]
