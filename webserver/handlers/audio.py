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

from webserver import constants, loader
from webserver.handlers.base import BaseHandler, auth, js, is_admin
from webserver.worker.epub2audio_worker import EpubToAudioWorker

CONF = loader.get_settings()

# map of conversion workers, key is book id, value is instance of the worker
ConversionWorkerMap = {}
AUDIO_OUTPUT_FOLDER = CONF.get("audio_output_folder", "/data/books/audios/")


class AudioUtils:
    site_url = ""

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
            return {
                    "status": EpubToAudioWorker.STATUS_CONVERTED,
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
                        "status": "available",
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
                if progress and progress["status"] in [EpubToAudioWorker.STATUS_CONVERTED, EpubToAudioWorker.STATUS_COMPLETED]:
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
    def post(self, bid):
        try:
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
                try:
                    result = worker.convert_epub_to_audio(
                        epub_path=epub_path,
                        output_dir=output_dir,
                        voice_name=voice_name,
                        language=language,
                        tts="edge",
                        worker_count=2,
                        no_prompt=True,
                        show_output=False
                    )
                    if not result['success']:
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
                    return {"err": "server.error", "msg": f"Failed to delete audio files: {e}"}
            else:
                return {"err": "audio.not_found", "msg": _(u"未找到要删除的音频文件")}

        except ValueError:
            return {"err": "params.invalid", "msg": _(u"无效的书籍ID")}
        except Exception as e:
            logging.error(f"Error in AudioDelete.post: {e}")
            return {"err": "server.error", "msg": str(e)}


class AudioDownload(BaseHandler):
    @js
    def get(self, book_id, filename):
        # Download audio file for the book
        try:
            book_id = int(book_id)
            book = self.get_book(book_id)
            if not book:
                return {"err": "params.book.invalid", "msg": _(u"书籍未找到")}

            # Security check: ensure filename doesn't contain path traversal
            if ".." in filename or "/" in filename:
                return {"err": "params.invalid", "msg": _(u"无效的文件名")}

            audio_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
            file_path = os.path.join(audio_dir, filename)

            if not os.path.exists(file_path):
                return {"err": "audio.not_found", "msg": _(u"音频文件未找到")}

            # Set appropriate headers for audio file download
            self.set_header("Content-Type", "audio/mpeg")
            self.set_header("Content-Disposition", f"attachment; filename=\"{filename}\"")

            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)  # 1MB chunks
                    if not chunk:
                        break
                    self.write(chunk)

        except ValueError:
            return {"err": "params.invalid", "msg": _(u"无效的书籍ID")}
        except Exception as e:
            logging.error(f"Error in AudioDownload.get: {e}")
            return {"err": "server.error", "msg": str(e)}


def routes():
    return [
        (r"/api/audio/([0-9]+)", AudioDetail),
        (r"/api/audio/([0-9]+)/download/([^/]+)", AudioDownload),
        (r"/api/audio/([0-9]+)/conversion", AudioConversion),
        (r"/api/audio/([0-9]+)/cancel", AudioConversionCancel),
        (r"/api/audio/([0-9]+)/delete", AudioDelete)
    ]
