#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import errno
import hashlib
import os
import logging
import time
import traceback

from webserver.i18n import _
from sqlalchemy.exc import IntegrityError

from webserver import utils
from webserver.models import Item, ScanFile
from webserver.services import AsyncService
from webserver.services.autofill import AutoFillService
from webserver.constants import CALIBRE_COLUMN_BOOK_TYPE, CALIBRE_COLUMN_CATEGORY, CALIBRE_ERROR_FLAG
from webserver.constants import BOOK_TYPE_EBOOK, BOOK_TYPE_PHYSICAL, AUDIO_BOOK_IMPORTS
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver import loader

SCAN_EXT = ["azw", "azw3", "epub", "mobi", "pdf", "txt"]
CONF = loader.get_settings()


class ScanService(AsyncService):
    static_is_scanning = False
    static_is_importing = False
    invalid_folder: set[str] = set()

    @staticmethod
    def is_scanning():
        return ScanService.static_is_scanning

    @staticmethod
    def is_importing():
        return ScanService.static_is_importing

    @staticmethod
    def get_invalid_folders():
        if ScanService.invalid_folder:
            logging.info(f"Invalid folders#0: {ScanService.invalid_folder}")
        return list(ScanService.invalid_folder)

    @staticmethod
    def os_walk_error_handler(e):
        if e.errno == errno.EACCES:
            logging.error(f"[SCAN]权限不足，跳过目录: {e.filename}")
            ScanService.invalid_folder.add(e.filename)
        elif e.errno == errno.ENOENT:
            logging.error(f"[SCAN]目录消失: {e.filename}")
        else:
            ScanService.invalid_folder.add(e.filename)
            logging.error(f"[SCAN]访问目录时发生错误: {e.filename}, 错误码: {e.errno}")

    def save_or_rollback(self, row, session=None):
        session = session or self.session
        bid = "[ book-id=%s ]" % row.book_id if row.book_id else ""
        logging.info("update: status=%-5s, path=%s %s", row.status, row.path, bid)
        try:
            row.save()
            session.commit()
            return True
        except IntegrityError as err:
            logging.error("IntegrityError: Duplicate hash detected: %s, %s", row.hash, err)
        except Exception as err:
            logging.exception("save error: %s", err)
        session.rollback()
        return False

    def build_query(self, hashlist, session=None):
        session = session or self.session
        query = session.query(ScanFile).filter(
            ScanFile.status == ScanFile.READY
        )  # .filter(ScanFile.import_id == 0)
        if isinstance(hashlist, (list, tuple)):
            query = query.filter(ScanFile.hash.in_(hashlist))
        elif isinstance(hashlist, str):
            query = query.filter(ScanFile.hash == hashlist)
        return query

    @AsyncService.register_service
    def do_scan(self, path_dirs):
        if ScanService.static_is_scanning:
            logging.error("Scanning is running, please wait...")
            return

        # 统一为列表，过滤不存在的目录
        if isinstance(path_dirs, str):
            path_dirs = [path_dirs]
        valid_dirs = [d for d in path_dirs if os.path.isdir(d)]
        if not valid_dirs:
            logging.error("[SCAN] 所有指定目录均不存在: %s", path_dirs)
            return

        ScanService.invalid_folder.clear()
        ScanService.static_is_scanning = True

        # 创建后台任务
        task_id = None
        try:
            service_item = _("扫描导入目录")
            task = BackgroundService().update_task(
                service_type=BackgroundTask.SERVICE_TYPE_SCAN,
                service_item=service_item,
                progress=0,
                progress_data={"stage": "scanning", "dirs": valid_dirs}
            )
            task_id = task.id
        except Exception as e:
            logging.error(f"Failed to create background task: {e}")

        try:
            self.do_scan_internal(valid_dirs, task_id)
            if task_id:
                BackgroundService().complete_task(task_id=task_id)
            logging.info("Scanning completed")
        except Exception as err:
            if task_id:
                BackgroundService().complete_task(task_id=task_id, error_message=str(err))
            logging.error(f"Scanning failed: {err}")
            logging.error(traceback.format_exc())
        ScanService.static_is_scanning = False

    def do_scan_internal(self, path_dirs, task_id=None):
        from calibre.ebooks.metadata.meta import get_metadata

        session = self.session
        logging.info("[SCAN]<%s> we are: db=%s, session=%s", self, self.db, session)
        logging.info("[SCAN]start to scan dirs: %s", path_dirs)

        # 生成任务（粗略扫描），前端可以调用API查询进展
        tasks = []
        for path_dir in path_dirs:
            if not os.path.isdir(path_dir):
                logging.warning("[SCAN] 目录不存在，跳过: %s", path_dir)
                continue
            for dirpath, __, filenames in os.walk(path_dir, onerror=ScanService.os_walk_error_handler):
                for fname in filenames:
                    fmt = fname.split(".")[-1].lower()
                    if not fmt or fmt not in SCAN_EXT or fmt[0] == '.':
                        logging.info("[SCAN]Ignore: [%s] %s", fmt, fname)
                        continue
                    fpath = os.path.join(dirpath, fname)
                    if not os.path.isfile(fpath):
                        logging.info("[SCAN]not a file, skip: %s", fpath)
                        continue
                    tasks.append((fname, fpath, fmt))

        # 生成任务ID
        scan_id = int(time.time())
        logging.info("[SCAN]========== start to check files size & name ============")

        rows = []
        inserted_hash = set()
        for fname, fpath, fmt in tasks:
            samefiles = session.query(ScanFile).filter(ScanFile.path == fpath)
            logging.info("[SCAN]Checking same files for path: %s (fname:%s), return count:%d", fpath, fname, samefiles.count())
            if samefiles.count() > 0:
                # 如果已经有相同的文件记录，则跳过
                found_book = False
                for row in samefiles:
                    if row.status == ScanFile.NEW:
                        logging.warning("[SCAN]Got same file path: %s, scan_id:%d, path:%s", fpath, row.scan_id, row.path)
                        found_book = True
                        # 将已存在记录的hash加入集合，避免后续被误删
                        if row.hash:
                            inserted_hash.add(row.hash)
                        rows.append(row)
                        break
                    elif row.status == ScanFile.IMPORTED and self.db.get_data_as_dict(ids=[row.book_id]):
                        logging.warning("[SCAN]File already exists in Scan & library: %s, status=%s", fpath, row.status)
                        found_book = True
                        break
                    else:
                        logging.warning("[SCAN]File already exists in Scan DB, but missed in library, try to import again")

                if found_book:
                    logging.warning("[SCAN]File already exists in Scan & Book DB: %s, status=%s", fpath, row.status)
                    continue

            # New record should be added
            logging.info("[SCAN]Processing new file: %s", fpath)
            stat = os.stat(fpath)
            md5 = hashlib.md5(fname.encode("UTF-8")).hexdigest()
            hash = "fstat:%s/%s" % (stat.st_size, md5)
            if hash in inserted_hash:
                logging.error("[SCAN]Duplicated processing book, skip: %s", fpath)
                continue
            if session.query(ScanFile).filter(ScanFile.hash == hash).count() > 0:
                logging.error("[SCAN]maybe have same book, skip: %s, due to same hash", fpath)
                continue

            row = ScanFile(fpath, hash, scan_id)
            inserted_hash.add(hash)
            if not self.save_or_rollback(row, session):
                continue
            rows.append(row)

        logging.info("[SCAN]========== start to check files hash & meta ============")
        # 检查文件哈希值，检查DB重复情况
        scanning_index = 0
        for row in rows:
            scanning_index += 1
            # 更新任务进度数据
            if task_id:
                try:
                    progress = int(scanning_index * 100 / len(rows))
                    BackgroundService().update_progress(
                        task_id=task_id,
                        progress=progress,
                        progress_data={"stage": "scanning", "dirs": path_dirs}
                    )
                except Exception as e:
                    logging.error("[SCAN]Failed to update task progress: %s", e)

            if row.status == ScanFile.DROP:
                continue

            fpath = row.path
            fname = os.path.basename(row.path)

            # 读取文件，计算哈希值
            sha256 = hashlib.sha256()
            try:
                with open(fpath, "rb") as f:
                    # Read and update hash string value in blocks of 4K
                    for byte_block in iter(lambda: f.read(4096), b""):
                        sha256.update(byte_block)
            except FileNotFoundError:
                row.status = ScanFile.MISSED
                logging.error("[SCAN]File not found when calculating hash: %s", fpath)
                if not self.save_or_rollback(row, session):
                    logging.error("[SCAN]Failed to save row status: %s", fpath)
                continue
            except PermissionError:
                row.status = ScanFile.PERMISSION
                logging.error("[SCAN]Permission denied when reading file: %s", fpath)
                if not self.save_or_rollback(row, session):
                    logging.error("[SCAN]Failed to save row status: %s", fpath)
                continue
            except Exception as e:
                row.status = ScanFile.DROP
                logging.error("[SCAN]Error reading file %s: %s", fpath, e)
                if not self.save_or_rollback(row, session):
                    logging.error("[SCAN]Failed to save row status: %s", fpath)
                continue

            hash = "sha256:" + sha256.hexdigest()
            should_drop = hash in inserted_hash
            if not should_drop:
                hash_rows = session.query(ScanFile).filter(ScanFile.hash == hash)
                should_drop = False
                for hash_row in hash_rows:
                    if hash_row.status == ScanFile.IMPORTED and self.db.get_data_as_dict(ids=[hash_row.book_id]):
                        should_drop = True
                        break
                if hash_rows.count() > 0 and not should_drop:
                    # 需要继续处理时，删除ScanDB中旧数据（排除当前记录）
                    session.query(ScanFile).filter(
                        ScanFile.hash == hash,
                        ScanFile.id != row.id
                    ).delete(synchronize_session=False)
            if should_drop:
                # 如果已经有相同的哈希值，则删掉本任务
                row.status = ScanFile.DROP
                logging.warning("[SCAN]Duplicate detected: %s, drop it.", hash)
            else:
                # 或者，更新为真实的哈希值
                row.hash = hash

            inserted_hash.add(hash)
            if not self.save_or_rollback(row, session):
                logging.error("[SCAN]Failed to save row: %s", fpath)
                continue

            if row.status == ScanFile.DROP:
                continue

            # 尝试解析metadata
            fmt = fpath.split(".")[-1].lower()
            try:
                with open(fpath, "rb") as stream:
                    mi = get_metadata(stream, stream_type=fmt,
                                      use_libprs_metadata=True)
                    mi.title = utils.super_strip(mi.title)
                    mi.authors = [utils.super_strip(s) for s in mi.authors]
            except Exception as e:
                logging.error("[SCAN]Error reading metadata from file %s: %s", fpath, e)
                continue

            row.status = ScanFile.READY
            if mi.title and mi.title == CALIBRE_ERROR_FLAG:
                logging.error("[SCAN]Failed to get metadata for %s, reason:%s", fpath, mi.comments)
                row.status = ScanFile.INVALID
                row.title = None
                if not self.save_or_rollback(row, session):
                    logging.error("[SCAN]Failed to save row status: %s", fpath)
                logging.info("[SCAN]Failed to get metadata for file %s, mark as invalid", fpath)
                continue

            if fmt == "txt":
                mi.title = utils.remove_zlibrary_suffix(fname.replace("." + fmt, ""))
                mi.authors = [_(u"佚名")]
                logging.info("[SCAN]Parsed metadata for txt file %s: title=%s", fpath, mi.title)
            elif fmt == "pdf":
                if CONF.get("PDF_TILE_WITH_FILE_NAME", False):
                    mi.title = utils.remove_zlibrary_suffix(fname.replace("." + fmt, ""))
                else:
                    title_ = mi.title.strip() if mi.title else ""
                    if not title_ or title_.find(_(u"下载工具")) >= 0 or title_ == "SSReader Print.":
                        mi.title = utils.remove_zlibrary_suffix(fname.replace("." + fmt, ""))
                    else:
                        mi.title = title_
                if mi.authors is None or len(mi.authors) == 0 or mi.authors[0].lower() == "unknown":
                    mi.authors = [_(u"佚名")]

            row.title = mi.title
            row.author = mi.authors[0] if mi.authors else mi.author_sort
            row.publisher = mi.publisher
            row.tags = ", ".join(mi.tags)

            # TODO calibre提供的书籍重复接口只有对比title；应当提前对整个书库的文件做哈希，才能准确去重
            ids = self.db.books_with_same_title(mi)
            if ids:
                for bid in ids:
                    b = self.db.get_metadata(bid, index_is_id=True)
                    logging.info("[SCAN] book info: %s", b)
                    # 如果是实体书，则跳过
                    if b.get(CALIBRE_COLUMN_BOOK_TYPE, BOOK_TYPE_EBOOK) == BOOK_TYPE_PHYSICAL:
                        continue
                    if b.formats and fmt and fmt.upper() in b.formats:
                        row.book_id = b.id
                        row.status = ScanFile.EXIST
                        break
            if not self.save_or_rollback(row, session):
                continue
            pass

        # 更新任务进度到100%
        if task_id:
            try:
                BackgroundService().update_progress(
                    task_id=task_id,
                    progress=100,
                    progress_data={"stage": "completed", "dirs": path_dirs}
                )
            except Exception as e:
                logging.error("[SCAN]Failed to update task progress: %s", e)

        ScanService.static_is_scanning = False
        logging.info("[SCAN] scan task %d completed.", scan_id)

    @AsyncService.register_service
    def do_import(self, hashlist, user_id):
        if ScanService.static_is_importing:
            logging.error("Importing is running, please wait...")
            return

        ScanService.invalid_folder.clear()
        ScanService.static_is_importing = True

        task_id = None
        try:
            service_item = _("导入图书")
            task = BackgroundService().update_task(
                service_type=BackgroundTask.SERVICE_TYPE_SCAN,
                service_item=service_item,
                progress=0,
                progress_data={"stage": "importing", "total": 0, "imported": 0}
            )
            task_id = task.id
        except Exception as e:
            logging.error(f"Failed to create background task: {e}")

        try:
            self.do_import_internal(hashlist, user_id, task_id)
            if task_id:
                BackgroundService().complete_task(task_id=task_id)
            logging.info("Importing completed")
        except Exception as err:
            if task_id:
                BackgroundService().complete_task(task_id=task_id, error_message=str(err))
            logging.error(f"Importing failed: {err}")
        ScanService.static_is_importing = False

    def do_import_internal(self, hashlist, user_id, task_id=None):
        from calibre.ebooks.metadata.meta import get_metadata

        session = self.session
        # 生成任务ID
        import_id = int(time.time())
        query = self.build_query(hashlist, session)
        query.update({ScanFile.import_id: import_id},
                     synchronize_session=False)
        session.commit()

        imported = []
        batch_size = 20  # 每批处理的文件数量

        # 获取所有待处理的记录
        all_rows = query.all()
        total_count = len(all_rows)
        logging.info("Total files to import: %d", total_count)

        # 更新任务进度数据
        if task_id:
            try:
                BackgroundService().update_progress(
                    task_id=task_id,
                    progress=0,
                    progress_data={"stage": "importing", "total": total_count, "imported": 0}
                )
            except Exception as e:
                logging.error(f"Failed to update task progress: {e}")

        # 分批处理，避免长时间持有数据库连接
        for batch_start in range(0, total_count, batch_size):
            batch_end = min(batch_start + batch_size, total_count)
            batch_rows = all_rows[batch_start:batch_end]

            logging.info("Processing batch: %d-%d / %d", batch_start + 1, batch_end, total_count)
            scan_upload_path = os.path.realpath(CONF.get("scan_upload_path", ""))

            # 处理当前批次
            for row in batch_rows:
                start_time = time.time()
                fpath = row.path
                fname = os.path.basename(row.path)
                fmt = fpath.split(".")[-1].lower()

                if not os.path.exists(fpath):
                    row.status = ScanFile.MISSED
                    logging.error("[IMPORT]file not exists: %s", fpath)
                    continue

                logging.info("[IMPORT]Processing file: %s", fpath)

                try:
                    with open(fpath, "rb") as stream:
                        mi = get_metadata(stream, stream_type=fmt,
                                          use_libprs_metadata=True)
                        mi.title = utils.super_strip(mi.title)
                        mi.authors = [utils.super_strip(s) for s in mi.authors]
                    if mi.title and mi.title == CALIBRE_ERROR_FLAG:
                        logging.error("[IMPORT]Failed to get metadata for %s, reason:%s", fpath, mi.comments)
                        continue

                    logging.info("[IMPORT]Parsed metadata for file %s: title=%s", fpath, mi.title)
                    # 非结构化的格式，calibre无法识别准确的信息，直接从文件名提取
                    if fmt == "txt":
                        mi.title = utils.remove_zlibrary_suffix(fname.replace("." + fmt, ""))
                        mi.authors = [_(u"佚名")]

                    if fmt == "pdf":
                        if CONF["PDF_TILE_WITH_FILE_NAME"]:
                            mi.title = utils.remove_zlibrary_suffix(fname.replace("." + fmt, ""))
                        else:
                            title_ = mi.title.strip() if mi.title else ""
                            if not title_ or title_.find(_(u"下载工具")) >= 0 or title_ == "SSReader Print.":
                                mi.title = utils.remove_zlibrary_suffix(fname.replace("." + fmt, ""))
                            else:
                                mi.title = title_
                        if mi.authors is None or len(mi.authors) == 0 or mi.authors[0].lower() == "unknown":
                            mi.authors = [_(u"佚名")]

                    # 再次检查是否有重复书籍
                    ids = self.db.books_with_same_title(mi)
                    existed_ebook = False
                    logging.info(f"[IMPORT]Found same title book ids: {ids} for file: {fpath}")
                    if ids:
                        row.book_id = 0
                        for bid in ids:
                            b = self.db.get_metadata(bid, index_is_id=True)
                            # 如果是实体书，则跳过
                            if b.get(CALIBRE_COLUMN_BOOK_TYPE, BOOK_TYPE_EBOOK) == BOOK_TYPE_PHYSICAL:
                                continue
                            existed_ebook = True
                            row.book_id = bid
                            if fmt.upper() in b.formats:
                                row.status = ScanFile.EXIST
                                break
                        if existed_ebook and row.status != ScanFile.EXIST:
                            # 找到电子书，但没有当前格式，添加格式
                            logging.info("[IMPORT]import [%s] from %s with format %s", repr(mi.title), fpath, fmt)
                            self.db.add_format(row.book_id, fmt.upper(), fpath, True)
                            row.status = ScanFile.IMPORTED
                    if not existed_ebook:
                        # 未找到重复电子书时，导入新书
                        logging.info("[IMPORT]import [%s] from %s [cost:%.3f]", repr(mi.title), fpath, time.time() - start_time)
                        mi.title_sort = utils.get_title_sort(mi.title)
                        row.book_id = self.db.import_book(mi, [fpath])
                        row.status = ScanFile.IMPORTED
                        logging.info("[IMPORT]imported [%s] from %s success, book_id=%d [cost:%.3f]", repr(mi.title), fpath, row.book_id, time.time() - start_time)

                        # 添加关联表
                        item = Item()
                        item.book_id = row.book_id
                        item.collector_id = user_id
                        item.src_path = fpath
                        try:
                            item.save()
                            imported.append(row.book_id)
                        except Exception as err:
                            logging.error("[IMPORT] save link error: %s", err)
                        logging.info("[IMPORT] saved item for book_id=%d, user_id=%d [cost:%.3f]", row.book_id, user_id, time.time() - start_time)

                        # 如果settings中IMPORT_CATEGORY_WITH_FOLDER开启，则使用当前文件在scan_upload_path目录下的第一级目录名作为书籍的自定义分类
                        # 如果目录名含有特殊字符，如,:等，则跳过分类设置，避免calibre库出问题
                        if CONF.get("IMPORT_CATEGORY_WITH_FOLDER", False):
                            rel = os.path.relpath(os.path.realpath(fpath), scan_upload_path)
                            first_dir = rel.split(os.sep)[0] if os.sep in rel else ""
                            if first_dir and len(first_dir) < 10 and not any(c in first_dir for c in ',:;|/\\\'"\t '):
                                try:
                                    self.db.new_api.set_field(CALIBRE_COLUMN_CATEGORY, {row.book_id: first_dir})
                                    logging.info("[IMPORT] Set category '%s' for book_id=%d", first_dir, row.book_id)
                                except Exception as cat_err:
                                    logging.warning("[IMPORT] Failed to set category for book_id=%d: %s", row.book_id, cat_err)
                            else:
                                logging.warning("[IMPORT] Skipping category setting for file %s due to invalid directory name: '%s'", fpath, first_dir)
                except Exception as err:
                    row.status = ScanFile.INVALID
                    logging.error("[IMPORT] Failed to process file %s: %s", fpath, err)
                    logging.error(traceback.format_exc())

            # 批量提交当前批次的更改
            try:
                session.commit()
                logging.info("[IMPORT] Batch committed: %d-%d", batch_start + 1, batch_end)
            except Exception as err:
                logging.error("[IMPORT] Batch commit error: %s", err)
                session.rollback()

            # 更新任务进度
            if task_id:
                try:
                    progress = int(batch_end * 100 / total_count)
                    BackgroundService().update_progress(
                        task_id=task_id,
                        progress=progress,
                        progress_data={"stage": "importing", "total": total_count, "imported": len(imported)}
                    )
                except Exception as e:
                    logging.error(f"Failed to update task progress: {e}")

            # 批次之间短暂休息，让其他进程有机会访问数据库
            if batch_end < total_count:
                time.sleep(0.3)

        # 最终提交，确保所有更改已保存
        try:
            session.commit()
            logging.info("[IMPORT] Final commit completed")
        except Exception as err:
            logging.error("[IMPORT] Final commit error: %s", err)
            session.rollback()

        ScanService.static_is_importing = False
        if task_id:
            try:
                BackgroundService().update_progress(
                    task_id=task_id,
                    progress=100,
                    progress_data={"stage": "completed", "total": total_count, "imported": len(imported)}
                )
            except Exception as e:
                logging.error(f"Failed to update task progress: {e}")

        # 全部导入完毕后，开始拉取书籍信息
        # 这个操作可能需要很长时间，在此之前已经释放了数据库连接
        if imported:
            logging.info("Starting auto-fill for %d imported books", len(imported))
            AutoFillService().auto_fill_all(imported)

    @AsyncService.register_service
    def do_scan_import_files(self, filelist, user_id):
        ScanService.static_is_importing = True

        task_id = None
        try:
            service_item = _("扫描并导入文件")
            task = BackgroundService().update_task(
                service_type=BackgroundTask.SERVICE_TYPE_SCAN,
                service_item=service_item,
                progress=0,
                progress_data={"stage": "importing", "total": len(filelist), "imported": 0}
            )
            task_id = task.id
        except Exception as e:
            logging.error(f"[SCAN_IMPORT] Failed to create background task: {e}")

        logging.info("[SCAN_IMPORT] task %d started.", task_id)

        try:
            self.do_scan_import_internal(filelist, user_id, task_id)
            if task_id:
                BackgroundService().complete_task(task_id=task_id)
            logging.info("[SCAN_IMPORT] Completed")
        except Exception as err:
            if task_id:
                BackgroundService().complete_task(task_id=task_id, error_message=str(err))
            logging.error(f"[SCAN_IMPORT] Failed: {err}")
            logging.error(traceback.format_exc())

        ScanService.static_is_importing = False
        logging.info("[SCAN_IMPORT] task %d completed.", task_id)

    def do_scan_import_internal(self, filelist, user_id, task_id=None):
        from calibre.ebooks.metadata.meta import get_metadata

        session = self.session
        import_id = int(time.time())
        scan_upload_path = os.path.realpath(CONF.get("scan_upload_path", ""))
        total_count = len(filelist)
        imported = []

        logging.info("[SCAN_IMPORT] Start processing %d files", total_count)

        for index, fpath in enumerate(filelist):
            logging.info("[SCAN_IMPORT] Processing file %d/%d: %s", index + 1, total_count, fpath)
            if task_id and total_count > 0:
                try:
                    BackgroundService().update_progress(
                        task_id=task_id,
                        progress=int(index * 100 / total_count),
                        progress_data={"stage": "importing", "total": total_count, "imported": len(imported)}
                    )
                except Exception as e:
                    logging.error("[SCAN_IMPORT] Failed to update progress: %s", e)

            if not os.path.isfile(fpath) or not os.path.exists(fpath):
                logging.warning("[SCAN_IMPORT] Not a valid file, skip: %s", fpath)
                continue

            fname = os.path.basename(fpath)
            if fname == AUDIO_BOOK_IMPORTS:
                logging.info("[SCAN_IMPORT] Skipping audiobook import file: %s", fpath)
                continue
            fmt = fpath.split(".")[-1].lower()
            if not fmt or fmt not in SCAN_EXT:
                logging.info("[SCAN_IMPORT] Unsupported format [%s], skip: %s", fmt, fpath)
                continue

            # Step 1: 检查同路径文件是否已导入
            same_path_rows = session.query(ScanFile).filter(ScanFile.path == fpath).all()
            already_done = False
            for r in same_path_rows:
                if r.status == ScanFile.IMPORTED and self.db.get_data_as_dict(ids=[r.book_id]):
                    logging.info("[SCAN_IMPORT] Already imported by path: %s", fpath)
                    already_done = True
                    break
            if already_done:
                continue

            # Step 2: 计算 sha256 哈希
            sha256 = hashlib.sha256()
            bad_reason = ScanFile.READY
            try:
                with open(fpath, "rb") as f:
                    for byte_block in iter(lambda: f.read(4096), b""):
                        sha256.update(byte_block)
            except FileNotFoundError:
                logging.error("[SCAN_IMPORT] File not found: %s", fpath)
                bad_reason = ScanFile.MISSED
            except PermissionError:
                logging.error("[SCAN_IMPORT] Permission denied: %s", fpath)
                bad_reason = ScanFile.PERMISSION
            except Exception as e:
                logging.error("[SCAN_IMPORT] Error reading file %s: %s", fpath, e)
                bad_reason = ScanFile.INVALID

            if bad_reason != ScanFile.READY:
                # 保留一条记录，方便在导入列表中展示错误状态
                row = ScanFile(fpath, "", import_id)
                row.status = bad_reason
                self.save_or_rollback(row, session)
                continue

            hash_val = "sha256:" + sha256.hexdigest()

            # Step 3: 检查同 sha256 文件是否已导入
            for hash_row in session.query(ScanFile).filter(ScanFile.hash == hash_val):
                if hash_row.status == ScanFile.IMPORTED and self.db.get_data_as_dict(ids=[hash_row.book_id]):
                    logging.info("[SCAN_IMPORT] Already imported by hash: %s", fpath)
                    already_done = True
                    break
            if already_done:
                continue

            # Step 4: 复用已有记录或创建新的 ScanFile
            if same_path_rows:
                row = same_path_rows[0]
                row.hash = hash_val
            else:
                # 删除同 hash 的旧记录（未导入），避免 unique 冲突
                session.query(ScanFile).filter(ScanFile.hash == hash_val).delete(synchronize_session=False)
                session.flush()
                row = ScanFile(fpath, hash_val, import_id)

            # Step 5: 解析元数据
            try:
                with open(fpath, "rb") as stream:
                    mi = get_metadata(stream, stream_type=fmt, use_libprs_metadata=True)
                    mi.title = utils.super_strip(mi.title)
                    mi.authors = [utils.super_strip(s) for s in mi.authors]
            except Exception as e:
                logging.error("[SCAN_IMPORT] Error reading metadata from %s: %s", fpath, e)
                row.status = ScanFile.INVALID
                self.save_or_rollback(row, session)
                continue

            if mi.title and mi.title == CALIBRE_ERROR_FLAG:
                logging.error("[SCAN_IMPORT] Failed to get metadata for %s", fpath)
                row.status = ScanFile.INVALID
                row.title = None
                self.save_or_rollback(row, session)
                continue

            if fmt == "txt":
                mi.title = utils.remove_zlibrary_suffix(fname.replace("." + fmt, ""))
                mi.authors = [_(u"佚名")]
            elif fmt == "pdf":
                if CONF.get("PDF_TILE_WITH_FILE_NAME", False):
                    mi.title = utils.remove_zlibrary_suffix(fname.replace("." + fmt, ""))
                else:
                    title_ = mi.title.strip() if mi.title else ""
                    if not title_ or title_.find(_(u"下载工具")) >= 0 or title_ == "SSReader Print.":
                        mi.title = utils.remove_zlibrary_suffix(fname.replace("." + fmt, ""))
                    else:
                        mi.title = title_
                if mi.authors is None or len(mi.authors) == 0 or mi.authors[0].lower() == "unknown":
                    mi.authors = [_(u"佚名")]

            row.title = mi.title
            row.author = mi.authors[0] if mi.authors else mi.author_sort
            row.publisher = mi.publisher
            row.tags = ", ".join(mi.tags)

            # Step 6: 验重并导入
            try:
                ids = self.db.books_with_same_title(mi)
                existed_ebook = False
                if ids:
                    row.book_id = 0
                    for bid in ids:
                        b = self.db.get_metadata(bid, index_is_id=True)
                        if b.get(CALIBRE_COLUMN_BOOK_TYPE, BOOK_TYPE_EBOOK) == BOOK_TYPE_PHYSICAL:
                            continue
                        existed_ebook = True
                        row.book_id = bid
                        if fmt.upper() in b.formats:
                            row.status = ScanFile.EXIST
                            break
                    if existed_ebook and row.status != ScanFile.EXIST:
                        logging.info("[SCAN_IMPORT] Adding format %s to existing book %d", fmt, row.book_id)
                        self.db.add_format(row.book_id, fmt.upper(), fpath, True)
                        row.status = ScanFile.IMPORTED
                if not existed_ebook:
                    logging.info("[SCAN_IMPORT] Importing new book [%s] from %s", repr(mi.title), fpath)
                    mi.title_sort = utils.get_title_sort(mi.title)
                    row.book_id = self.db.import_book(mi, [fpath])
                    row.status = ScanFile.IMPORTED

                    item = Item()
                    item.book_id = row.book_id
                    item.collector_id = user_id
                    item.src_path = fpath
                    try:
                        item.save()
                        imported.append(row.book_id)
                    except Exception as err:
                        logging.error("[SCAN_IMPORT] save link error: %s", err)

                    if CONF.get("IMPORT_CATEGORY_WITH_FOLDER", False):
                        rel = os.path.relpath(os.path.realpath(fpath), scan_upload_path)
                        first_dir = rel.split(os.sep)[0] if os.sep in rel else ""
                        if first_dir and len(first_dir) < 10 and not any(c in first_dir for c in ',:;|/\\\'"\t '):
                            try:
                                self.db.new_api.set_field(CALIBRE_COLUMN_CATEGORY, {row.book_id: first_dir})
                                logging.info("[SCAN_IMPORT] Set category '%s' for book_id=%d", first_dir, row.book_id)
                            except Exception as cat_err:
                                logging.warning("[SCAN_IMPORT] Failed to set category for book_id=%d: %s", row.book_id, cat_err)
            except Exception as err:
                row.status = ScanFile.INVALID
                logging.error("[SCAN_IMPORT] Failed to process file %s: %s", fpath, err)

            self.save_or_rollback(row, session)

        if task_id:
            try:
                BackgroundService().update_progress(
                    task_id=task_id,
                    progress=100,
                    progress_data={"stage": "completed", "total": total_count, "imported": len(imported)}
                )
            except Exception as e:
                logging.error(f"[SCAN_IMPORT] Failed to update final progress: {e}")

        logging.info("[SCAN_IMPORT] Done. Total: %d, Imported: %d", total_count, len(imported))

        if imported:
            logging.info("[SCAN_IMPORT] Starting auto-fill for %d imported books", len(imported))
            AutoFillService().auto_fill_all(imported)

    @AsyncService.register_service
    def do_rename_category(self, old_dir_path, new_dir_path, scan_upload_path):
        """目录重命名/移动后，将 src_path 在旧目录下的书籍分类更新为新目录对应的一级子目录名"""
        old_dir_path = os.path.realpath(old_dir_path)
        new_dir_path = os.path.realpath(new_dir_path)
        scan_upload_path = os.path.realpath(scan_upload_path)

        # 计算新分类名：新路径在 scan_upload_path 下的第一级子目录名
        try:
            rel = os.path.relpath(new_dir_path, scan_upload_path)
        except ValueError:
            logging.warning("[RENAME DIR] 新目录不在 scan_upload_path 下: %s", new_dir_path)
            return

        parts = rel.split(os.sep)
        new_category = parts[0] if parts else ""

        if not new_category or new_category in ('.', '..'):
            logging.warning("[RENAME DIR] 无效的分类名: %s", new_category)
            return
        if len(new_category) >= 10 or any(c in new_category for c in ',:;|/\'"\t '):
            logging.warning("[RENAME DIR] 分类名含非法字符或过长，跳过: '%s'", new_category)
            return

        # 查找 src_path 在旧目录下的所有 Item
        sep = os.sep
        session = self.session
        all_items = session.query(Item).all()
        affected = [
            item for item in all_items
            if item.src_path and (
                os.path.realpath(item.src_path) == old_dir_path or os.path.realpath(item.src_path).startswith(old_dir_path + sep)
            )
        ]

        if not affected:
            logging.info("[RENAME DIR] Not found books which src_path in '%s', no need to update", old_dir_path)
            return

        logging.info("[RENAME DIR] Found %d books，update category to '%s'", len(affected), new_category)
        for item in affected:
            try:
                self.db.new_api.set_field(CALIBRE_COLUMN_CATEGORY, {item.book_id: new_category})
                # 同步更新 src_path 为新路径，方便后续重命名链式追踪
                suffix = os.path.realpath(item.src_path)[len(old_dir_path):]
                item.src_path = new_dir_path + suffix
                logging.info("[RENAME DIR] book_id=%d category->%s, src_path->%s",
                             item.book_id, new_category, item.src_path)
            except Exception as e:
                logging.error("[RENAME DIR] Failed to update book_id=%d,: %s", item.book_id, e)

        try:
            session.commit()
            logging.info("[RENAME DIR] category updated successfully")
        except Exception as e:
            logging.error("[RENAME DIR] Failed to commit: %s", e)
            session.rollback()

    @AsyncService.register_service
    def do_moved_file(self, old_file_path, new_file_path, scan_upload_path):
        """文件重命名/移动后，将 src_path 在旧目录下的书籍分类更新为新目录对应的一级子目录名"""
        old_file_path = os.path.realpath(old_file_path)
        new_file_path = os.path.realpath(new_file_path)
        scan_upload_path = os.path.realpath(scan_upload_path)

        if os.path.isdir(new_file_path):
            logging.warning("[RENAME FILE] 路径是目录，跳过: %s", new_file_path)
            return

        # 计算新分类名：新路径在 scan_upload_path 下的第一级子目录名
        try:
            rel = os.path.relpath(new_file_path, scan_upload_path)
        except ValueError:
            logging.warning("[RENAME FILE] 新目录不在 scan_upload_path 下: %s", new_file_path)
            return

        parts = rel.split(os.sep)
        new_category = parts[0] if parts else ""

        if not new_category or new_category in ('.', '..'):
            logging.warning("[RENAME FILE] 无效的分类名: %s", new_category)
            return
        if len(new_category) > 10 or any(c in new_category for c in ',:;|/\'"\t '):
            logging.warning("[RENAME FILE] 分类名含非法字符或过长，跳过: '%s'", new_category)
            return

        session = self.session
        affected = session.query(Item).filter(Item.src_path == old_file_path).all()
        if not affected:
            # 尝试使用ScanFile表中的路径进行匹配，兼容之前未设置src_path的情况
            logging.info("[RENAME FILE] 在 Item 表中未找到 src_path 为 '%s' 的书籍，尝试在 ScanFile 表中查找", old_file_path)
            scan_files = session.query(ScanFile).filter(ScanFile.path == old_file_path).all()
            if scan_files:
                book_ids = [sf.book_id for sf in scan_files if sf.book_id]
                affected = session.query(Item).filter(Item.book_id.in_(book_ids)).all()
        if not affected:
            logging.info("[RENAME FILE] 未找到 src_path 为 '%s' 的书籍，无需更新", old_file_path)
            return

        logging.info("[RENAME FILE] Found %d books，update category to '%s'", len(affected), new_category)
        for item in affected:
            try:
                self.db.new_api.set_field(CALIBRE_COLUMN_CATEGORY, {item.book_id: new_category})
                item.src_path = new_file_path
                logging.info("[RENAME FILE] book_id=%d category->%s, src_path->%s", item.book_id, new_category, item.src_path)
            except Exception as e:
                logging.error("[RENAME FILE] Failed to update book_id=%d, %s", item.book_id, e)

        try:
            session.commit()
            logging.info("[RENAME FILE] Succeed to update categories")
        except Exception as e:
            logging.error("[RENAME FILE] Failed to commit: %s", e)
            session.rollback()
