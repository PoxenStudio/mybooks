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
    @staticmethod
    def get_audios(book_id):
        """Get audio files for a book."""
        audio_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
        if not os.path.exists(audio_dir):
            return {"status": "unavailable", "msg": "No audio files found", "count": 0}

        audio_files = [f for f in os.listdir(audio_dir) if f.endswith(('.mp3', '.wav'))]
        if not audio_files:
            return {"status": "unavailable", "msg": "No audio files found", "count": 0}

        file_urls = []
        for file in sorted(audio_files):
            file_path = os.path.join(audio_dir, file)
            file_urls.append({
                "filename": file,
                "url": f"/api/audio/{book_id}/download/{file}",
                "size": os.path.getsize(file_path)
            })

        worker = ConversionWorkerMap.get(book_id)
        if worker and not worker.is_completed():
            # If conversion is in progress, return worker status
            return {"status": worker.get_status(),
                    "progress": worker.get_progress(),
                    "audio_dir": audio_dir,
                    "files": file_urls,
                    "count": len(audio_files)
                }

        return {
            "status": "available",
            "msg": "ok",
            "audio_dir": audio_dir,
            "files": file_urls,
            "count": len(audio_files)
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
                return {"err": "params.book.invalid", "msg": "Book not found"}

            # Check if audio file already exists
            audio_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
            if os.path.exists(audio_dir) and os.listdir(audio_dir):
                audio_files = [f for f in os.listdir(audio_dir) if f.endswith(('.mp3', '.wav', '.m4a', '.opus'))]
                if audio_files:
                    # Generate download URLs for audio files
                    file_urls = []
                    for file in sorted(audio_files):
                        file_urls.append({
                            "filename": file,
                            "url": f"/api/audio/{book_id}/download/{file}",
                            "size": os.path.getsize(os.path.join(audio_dir, file))
                        })

                    return {
                        "err": "ok",
                        "msg": "Audio files found",
                        "data": {
                            "status": "available",
                            "audio_dir": audio_dir,
                            "files": file_urls,
                            "total_files": len(audio_files)
                        }
                    }

            # Check if conversion is in progress
            worker = ConversionWorkerMap.get(book_id)
            if worker:
                progress = worker.get_progress()
                return {"err": "ok", "msg": "Conversion in progress", "data": progress}

            return {"err": "audio.not_found", "msg": "No audio files found"}

        except ValueError:
            return {"err": "params.invalid", "msg": "Invalid book ID"}
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
                    return {"err": "ok", "msg":"Conversion completed", "data": progress}
                elif progress and progress["status"] == EpubToAudioWorker.STATUS_FAILED:
                    return {"err": "audio.conversion_failed", "msg": "Conversion failed", "data": progress}
                else:
                    return {"err": "ok", "msg":"processing", "data": progress}
            else:
                return {"err": "audio.no_conversion", "msg":"No conversion"}
        except ValueError:
            return {"err": "params.invalid", "msg": "Invalid book ID"}
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
                return {"err": "params.book.invalid", "msg": "Book not found"}

            # Check if conversion is already running
            if book_id in ConversionWorkerMap:
                worker = ConversionWorkerMap[book_id]
                if worker.is_running():
                    return {"err": "audio.already_converting", "msg": "Conversion already in progress"}
                else:
                    # Remove stale worker
                    ConversionWorkerMap.pop(book_id, None)

            # Get EPUB file path
            epub_path = book.get("fmt_epub")
            if not epub_path:
                return {"err": "params.book.no_epub", "msg": "Book does not have EPUB format"}

            # Validate that the EPUB file actually exists
            if not os.path.exists(epub_path):
                return {"err": "params.book.epub_missing", "msg": "EPUB file not found on disk"}

            # Create output directory
            output_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
            os.makedirs(output_dir, exist_ok=True)

            # Create new worker and start conversion
            worker = EpubToAudioWorker()
            ConversionWorkerMap[book_id] = worker

            # Start conversion in background thread
            def start_conversion():
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
                        # Mark worker as failed and clean up
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

            return {"err": "ok", "msg": "开始转换"}

        except ValueError:
            return {"err": "params.invalid", "msg": "Invalid book ID"}
        except Exception as e:
            logging.error(f"Error in AudioConversion.post: {e}")
            return {"err": "server.error", "msg": str(e)}

            return {"err": "ok", "msg": "开始转换"}

        except ValueError:
            return {"err": "params.invalid", "msg": "Invalid book ID"}
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
                return {"err": "ok", "msg": "Conversion cancelled"}
            else:
                return {"err": "audio.no_conversion", "msg": "No conversion to cancel"}
        except ValueError:
            return {"err": "params.invalid", "msg": "Invalid book ID"}
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
                    return {"err": "audio.conversion_running", "msg": "Cannot delete while conversion is running"}
                ConversionWorkerMap.pop(book_id, None)

            # Delete audio directory
            audio_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
            if os.path.exists(audio_dir):
                try:
                    shutil.rmtree(audio_dir)
                    return {"err": "ok", "msg": "Audio files deleted successfully"}
                except OSError as e:
                    logging.error(f"Error deleting audio directory {audio_dir}: {e}")
                    return {"err": "server.error", "msg": f"Failed to delete audio files: {e}"}
            else:
                return {"err": "audio.not_found", "msg": "No audio files found to delete"}

        except ValueError:
            return {"err": "params.invalid", "msg": "Invalid book ID"}
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
                raise tornado.web.HTTPError(404, "Book not found")

            # Security check: ensure filename doesn't contain path traversal
            if ".." in filename or "/" in filename:
                raise tornado.web.HTTPError(400, "Invalid filename")

            audio_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
            file_path = os.path.join(audio_dir, filename)

            if not os.path.exists(file_path):
                raise tornado.web.HTTPError(404, "Audio file not found")

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
            raise tornado.web.HTTPError(400, "Invalid book ID")
        except Exception as e:
            logging.error(f"Error in AudioDownload.get: {e}")
            raise tornado.web.HTTPError(500, "Server error")


def routes():
    return [
        (r"/api/audio/([0-9]+)", AudioDetail),
        (r"/api/audio/([0-9]+)/download/([^/]+)", AudioDownload),
        (r"/api/audio/([0-9]+)/conversion", AudioConversion),
        (r"/api/audio/([0-9]+)/cancel", AudioConversionCancel),
        (r"/api/audio/([0-9]+)/delete", AudioDelete)
    ]
