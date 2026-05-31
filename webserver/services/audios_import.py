#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import hashlib
import logging
import os
import shutil
import subprocess
import time
import traceback

from webserver import loader, utils, constants
from webserver.i18n import _
from webserver.models import ScanFile, Item
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask

CONF = loader.get_settings()

AUDIO_IMPORT_DIR = os.path.join(CONF.get("scan_upload_path", "/data/books/imports/"), constants.AUDIO_BOOK_IMPORTS)
AUDIO_OUTPUT_DIR = CONF.get("audio_output_folder", "/data/books/audios/")

COVER_NAMES = {"cover.jpg", "cover.jpeg", "cover.png"}


def _find_cover(dir_path):
    try:
        for fname in os.listdir(dir_path):
            if fname.lower() in COVER_NAMES:
                return os.path.join(dir_path, fname)
    except OSError:
        pass
    return None


def _read_cover_data(cover_path):
    try:
        with open(cover_path, "rb") as f:
            data = f.read()
        ext = os.path.splitext(cover_path)[1].lstrip(".").lower()
        if ext in ("jpg", "jpeg"):
            ext = "jpeg"
        return ext, data
    except OSError:
        return None, None


def _get_dest_filename(filename):
    """Get the destination filename, converting .wma to .mp3 extension."""
    name, ext = os.path.splitext(filename)
    if ext.lower() == ".wma":
        return name + ".mp3"
    return filename


def _convert_wma_to_mp3(src_path, dst_path):
    """Convert a WMA file to MP3 using ffmpeg."""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", src_path, "-codec:a", "libmp3lame", "-q:a", "2", dst_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logging.info("[AUDIO_IMPORT] Converted WMA to MP3: %s -> %s", src_path, dst_path)
        return True
    except FileNotFoundError:
        logging.error("[AUDIO_IMPORT] ffmpeg not found. Please install ffmpeg to convert WMA files.")
        return False
    except subprocess.CalledProcessError as e:
        logging.error("[AUDIO_IMPORT] ffmpeg conversion failed for %s: %s", src_path, e)
        return False


def _copy_or_convert_file(src_path, dst_dir):
    """Copy a file to dst_dir. If it's a WMA file, convert to MP3 instead."""
    filename = os.path.basename(src_path)
    dest_filename = _get_dest_filename(filename)
    dst_path = os.path.join(dst_dir, dest_filename)

    if os.path.exists(dst_path):
        return

    if filename.lower().endswith(".wma"):
        # remove original wma file if existed
        try:
            dst_wma_file = os.path.join(dst_dir, filename)
            if os.path.exists(dst_wma_file):
                os.remove(dst_wma_file)
        except Exception:
            pass
        _convert_wma_to_mp3(src_path, dst_path)
    else:
        shutil.copy2(src_path, dst_path)


def _extract_audio_metadata(audio_path, fallback_title):
    try:
        import mutagen
        audio = mutagen.File(audio_path, easy=True)
        if audio is None:
            return fallback_title, None
        title = None
        author = None
        if hasattr(audio, "tags") and audio.tags:
            title_tag = audio.tags.get("album") or audio.tags.get("title")
            author_tag = audio.tags.get("artist") or audio.tags.get("albumartist")
            if title_tag:
                title = str(title_tag[0]).strip() if isinstance(title_tag, list) else str(title_tag).strip()
            if author_tag:
                author = str(author_tag[0]).strip() if isinstance(author_tag, list) else str(author_tag).strip()

        # Fallback for some m4b files (e.g. lavf) where easy=True doesn't map the tags
        if not title or not author:
            raw_audio = mutagen.File(audio_path, easy=False)
            if hasattr(raw_audio, "tags") and raw_audio.tags:
                if not title:
                    title_tag = raw_audio.tags.get("\x00\x00\x00\x01")
                    if title_tag:
                        title = str(title_tag[0]).strip() if isinstance(title_tag, list) else str(title_tag).strip()
                if not author:
                    author_tag = raw_audio.tags.get("\x00\x00\x00\x02")
                    if author_tag:
                        author = str(author_tag[0]).strip() if isinstance(author_tag, list) else str(author_tag).strip()

        logging.debug("[AUDIO_IMPORT] Extracted metadata from %s: title=%s, author=%s", audio_path, title, author)
        return title or fallback_title, author
    except Exception as e:
        logging.warning("[AUDIO_IMPORT] Failed to read audio metadata from %s: %s", audio_path, e)
        return fallback_title, None


class AudioBookImporter(AsyncService):
    static_is_running = False
    static_status = {
        "total": 0,
        "imported": 0,
        "exist": 0,
        "skipped": 0,
    }

    @staticmethod
    def is_running():
        return AudioBookImporter.static_is_running

    @staticmethod
    def get_status():
        return AudioBookImporter.static_status.copy()

    def save_or_rollback(self, row):
        try:
            row.save()
            self.session.commit()
            return True
        except Exception as err:
            logging.error("[AUDIO_IMPORT] save error: %s", err)
            self.session.rollback()
            return False

    def _add_new_book(self, user_id, mi, cover_path):
        logging.debug("[AUDIO_IMPORT] Adding new book: title=%s, author=%s", mi.title, mi.authors[0] if mi.authors else "N/A")
        book_id = None
        try:
            if cover_path:
                ext, cover_data = _read_cover_data(cover_path)
                if cover_data:
                    mi.cover_data = (ext, cover_data)
            book_id = self.db.create_book_entry(mi)
        except Exception as err:
            logging.error("[AUDIO_IMPORT] error creating book entry for %s: %s", mi.title, err)
            logging.error(traceback.format_exc())
            return None

        if not book_id:
            return None

        # Add a Item record
        try:
            item = Item()
            item.book_id = book_id
            item.collector_id = user_id
            item.save()
        except Exception as err:
            logging.error("[AUDIO_IMPORT] error updating book_type for book_id %s: %s", book_id, err)
            logging.error(traceback.format_exc())
            self.db.session.rollback()

        return book_id

    def _check_audio_exists(self, book_id):
        audio_dir = os.path.join(AUDIO_OUTPUT_DIR, str(book_id))
        if not os.path.isdir(audio_dir):
            return False
        audio_files = [f for f in os.listdir(audio_dir) if f.lower().endswith(tuple(constants.SUPPORTED_AUDIO_FORMATS))]
        if audio_files:
            return True
        return False

    def _synch_audio_files(self, src_dir, dest_dir):
        logging.debug(f"[AUDIO_IMPORT] Synchronizing audio files from {src_dir} to {dest_dir}")
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
        for fname in os.listdir(src_dir):
            src = os.path.join(src_dir, fname)
            if os.path.isfile(src):
                _copy_or_convert_file(src, dest_dir)

    @AsyncService.register_service
    def do_import(self, user_id):
        if AudioBookImporter.static_is_running:
            logging.error("[AUDIO_IMPORT] already running, skip")
            return

        AudioBookImporter.static_is_running = True
        AudioBookImporter.static_status = {
            "total": 0,
            "imported": 0,
            "exist": 0,
            "skipped": 0,
        }

        task_id = None
        try:
            task = BackgroundService().update_task(
                service_type=BackgroundTask.SERVICE_TYPE_AUDIO_IMPORT,
                service_item=_("导入有声书"),
                progress=0,
                progress_data={"total": 0, "imported": 0, "exist": 0},
            )
            task_id = task.id
        except Exception as e:
            logging.error("[AUDIO_IMPORT] Failed to create background task: %s", e)

        try:
            self._do_import_internal(user_id, task_id)
            if task_id:
                BackgroundService().complete_task(task_id=task_id)
            logging.info("[AUDIO_IMPORT] completed")
        except Exception as err:
            logging.error("[AUDIO_IMPORT] failed: %s", err)
            logging.error(traceback.format_exc())
            if task_id:
                BackgroundService().complete_task(task_id=task_id, error_message=str(err))
        finally:
            AudioBookImporter.static_is_running = False

    def _do_import_internal(self, user_id, task_id=None):
        from calibre.ebooks.metadata.book.base import Metadata
        import_dir = AUDIO_IMPORT_DIR
        output_dir = AUDIO_OUTPUT_DIR

        if not os.path.isdir(import_dir):
            logging.warning("[AUDIO_IMPORT] import dir does not exist: %s", import_dir)
            return

        subdirs = sorted([
            d for d in os.listdir(import_dir)
            if os.path.isdir(os.path.join(import_dir, d))
        ])

        total = len(subdirs)
        AudioBookImporter.static_status["total"] = total
        imported_ids = []
        imported_without_cover = []

        for idx, dir_name in enumerate(subdirs):
            dir_path = os.path.join(import_dir, dir_name)
            dir_hash = "audiodir:" + hashlib.md5(dir_path.encode("utf-8")).hexdigest()
            logging.info("[AUDIO_IMPORT] Processing directory %d/%d: %s", idx + 1, total, dir_path)

            existing = self.session.query(ScanFile).filter(ScanFile.hash == dir_hash).first()
            if existing and existing.status in (ScanFile.IMPORTED, ScanFile.EXIST):
                # 存在已导入有声书时，检查当前音频目录中相对对应的有声书目录(/data/books/audios/<book_id>)是否有新增的音频文件
                if existing.status == ScanFile.IMPORTED:
                    book_id = existing.book_id
                    if book_id and self._check_audio_exists(book_id):
                        self._synch_audio_files(dir_path, os.path.join(output_dir, str(book_id)))

                AudioBookImporter.static_status["skipped"] += 1
                self._update_progress(task_id, idx + 1, total)
                continue

            logging.info("[AUDIO_IMPORT] new record for %s, will attempt to import", dir_path)
            audio_files = sorted([
                f for f in os.listdir(dir_path) if f.lower().endswith(tuple(constants.SUPPORTED_AUDIO_FORMATS))
            ])
            if not audio_files:
                logging.info("[AUDIO_IMPORT] no audio files in %s, skipping", dir_path)
                AudioBookImporter.static_status["skipped"] += 1
                self._update_progress(task_id, idx + 1, total)
                continue

            first_audio = os.path.join(dir_path, audio_files[0])
            title, author = _extract_audio_metadata(first_audio, dir_name)
            if not author:
                author = _("佚名")
            title = utils.super_strip(title) if title else dir_name
            author = utils.super_strip(author) if author else _("佚名")

            cover_path = _find_cover(dir_path)
            has_cover = cover_path is not None

            row = existing or ScanFile(dir_path, dir_hash, 0)
            row.import_type = constants.IMPORT_TYPE_AUDIOBOOK
            row.title = title
            row.author = author

            mi = Metadata(title, [author])
            mi.title_sort = utils.get_title_sort(title)

            try:
                ids = self.db.books_with_same_title(mi)
                book_id = None
                status = ScanFile.IMPORTED
                audio_exists = False
                if ids:
                    for bid in ids:
                        audio_exists = self._check_audio_exists(bid)
                        if audio_exists:
                            book_id = bid
                            status = ScanFile.EXIST
                            break
                    logging.debug("[AUDIO_IMPORT] found existing books with same title '%s': %s, has_audio=%s, selected_book_id=%s",
                                  title, ids, audio_exists, book_id)
                if not audio_exists:
                    # 没有找到已有的同名有声书，创建新书籍记录
                    book_id = self._add_new_book(user_id, mi, cover_path)
                    if book_id is None:
                        logging.error("[AUDIO_IMPORT] failed to create book entry for %s", title)
                        row.status = ScanFile.INVALID
                        self.save_or_rollback(row)
                        self._update_progress(task_id, idx + 1, total)
                        continue

                if status == ScanFile.IMPORTED:
                    dest_dir = os.path.join(output_dir, str(book_id))
                    if not os.path.exists(dest_dir):
                        os.makedirs(dest_dir)
                    for fname in os.listdir(dir_path):
                        src = os.path.join(dir_path, fname)
                        if os.path.isfile(src):
                            _copy_or_convert_file(src, dest_dir)
                    imported_ids.append(book_id)
                    if not has_cover:
                        imported_without_cover.append(book_id)
                    AudioBookImporter.static_status["imported"] += 1
                else:
                    AudioBookImporter.static_status["exist"] += 1

                row.book_id = book_id
                row.status = status
            except Exception as err:
                logging.error("[AUDIO_IMPORT] error processing %s: %s", dir_path, err)
                logging.error(traceback.format_exc())
                row.status = ScanFile.INVALID

            self.save_or_rollback(row)
            self._update_progress(task_id, idx + 1, total)
            time.sleep(0.1)

        if imported_without_cover:
            logging.info("[AUDIO_IMPORT] triggering autofill for %d books without cover", len(imported_without_cover))
            from webserver.services.autofill import AutoFillService
            AutoFillService().auto_fill_all(imported_without_cover)

    def _update_progress(self, task_id, done, total):
        if not task_id:
            return
        try:
            status = AudioBookImporter.static_status
            progress = int(done * 100 / total) if total else 100
            BackgroundService().update_progress(
                task_id=task_id,
                progress=progress,
                progress_data={
                    "total": status["total"],
                    "imported": status["imported"],
                    "exist": status["exist"],
                },
            )
        except Exception as e:
            logging.error("[AUDIO_IMPORT] failed to update progress: %s", e)
