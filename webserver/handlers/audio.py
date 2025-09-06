#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging
import os
import re
import shutil
import threading
import time
from gettext import gettext as _

import tornado
from tornado import web

from webserver import loader
from webserver.handlers.base import BaseHandler, auth, js
from webserver.worker.epub2audio_worker import EpubToAudioWorker

CONF = loader.get_settings()

# map of conversion workers, key is book id, value is instance of the worker
ConversionWorkerMap = {}
ALLOW_MAX_RUNNING_WORKERS = CONF.get("BOOK2AUDIO_MAX_WORKERS", 2)
# 获取项目根目录
import inspect
current_file = inspect.getfile(inspect.currentframe())
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
default_audio_path = os.path.join(project_root, "tests", "audios")
AUDIO_OUTPUT_FOLDER = CONF.get("audio_output_folder", default_audio_path)


class AudioUtils:
    site_url = ""

    @staticmethod
    def get_running_worker_count():
        """Get the count of currently running audio conversion workers."""
        return sum(1 for worker in ConversionWorkerMap.values() if worker.is_running())

    @staticmethod
    def get_audios(bid):
        """Get audio files for a book."""
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
                "url": f"{AudioUtils.site_url}/audios/{book_id}/{file}",
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

            # Check if audio file already exists
            audio_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
            if os.path.exists(audio_dir) and os.listdir(audio_dir):
                audio_files = [f for f in os.listdir(audio_dir) if f.endswith(('.mp3', '.wav', '.m4a', '.opus'))]
                if audio_files:
                    # Generate download URLs for audio files
                    file_urls = []
                    for file in sorted(audio_files):
                        file_urls.append({
                            "filename": os.path.splitext(file)[0],
                            "url": f"{self.site_url}/audios/{book_id}/{file}",
                            "size": os.path.getsize(os.path.join(audio_dir, file))
                        })
                    return {
                        "err": "ok",
                        "audio_dir": audio_dir,
                        "audios": file_urls,
                        "status": EpubToAudioWorker.STATUS_COMPLETED,
                        "total_files": len(audio_files)
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
            audio_book_ids = []
            if os.path.exists(AUDIO_OUTPUT_FOLDER):
                for item in os.listdir(AUDIO_OUTPUT_FOLDER):
                    item_path = os.path.join(AUDIO_OUTPUT_FOLDER, item)
                    if os.path.isdir(item_path) and item.isdigit():
                        book_id = int(item)
                        # 检查目录中是否有音频文件
                        audio_files = [f for f in os.listdir(item_path)
                                      if f.endswith(('.mp3', '.wav', '.m4a', '.opus'))]
                        if audio_files:
                            audio_book_ids.append(book_id)

            # 按书籍ID倒序排序（新的在前）
            audio_book_ids.sort(reverse=True)

            # 分页处理
            total = len(audio_book_ids)
            paginated_ids = audio_book_ids[start:start + size]

            # 获取书籍信息，参考 base.py 中的 get_books 函数进行权限过滤
            books = []
            if paginated_ids:
                books = self.get_books(ids=paginated_ids)

            return {
                "err": "ok",
                "title": _(u"有声书"),
                "books": books,
                "total": total
            }

        except Exception as e:
            logging.error(f"Error in AudioBooks.get: {e}")
            return {"err": "server.error", "msg": str(e)}


class AudioConversion(BaseHandler):
    @js
    @auth
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
    @auth
    def post(self, bid):
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
    @auth
    def post(self, book_id):
        # cancel the conversion for the book id, if the worker exists, stop it and remove it from the map.
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
    @auth
    def post(self, book_id):
        # delete the audio file for the book id, if the file exists, remove it.
        # if not found, return not found status.
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
    def get(self, book_id, filename):
        """提供音频文件的静态文件服务"""
        try:
            book_id = int(book_id)

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
            raise web.HTTPError(500, "Internal server error")


def routes():
    return [
        (r"/api/audio/([0-9]+)", AudioDetail),
        (r"/api/audio/([0-9]+)/conversion", AudioConversion),
        (r"/api/audio/([0-9]+)/cancel", AudioConversionCancel),
        (r"/api/audio/([0-9]+)/delete", AudioDelete),
        (r"/audios", AudioBooks),  # 音频书籍列表
        # 音频文件服务
        (r"/audios/([0-9]+)/([^/]+)", AudioFile),
    ]
