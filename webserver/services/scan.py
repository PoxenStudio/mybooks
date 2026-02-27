#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import hashlib
import os
import logging
import time
import traceback

from gettext import gettext as _
from sqlalchemy.exc import IntegrityError

from webserver import utils
from webserver.models import Item, ScanFile
from webserver.services import AsyncService
from webserver.services.autofill import AutoFillService
from webserver.constants import CALIBRE_COLUMN_BOOK_TYPE, CALIBRE_ERROR_FLAG, BOOK_TYPE_EBOOK, BOOK_TYPE_PHYSICAL
from webserver.services.background_service import BackgroundService, BackgroundTask


SCAN_EXT = ["azw", "azw3", "epub", "mobi", "pdf", "txt"]


class ScanService(AsyncService):
    static_is_scanning = False
    static_is_importing = False

    @staticmethod
    def is_scanning():
        return ScanService.static_is_scanning

    @staticmethod
    def is_importing():
        return ScanService.static_is_importing

    def save_or_rollback(self, row):
        bid = "[ book-id=%s ]" % row.book_id if row.book_id else ""
        logging.info("update: status=%-5s, path=%s %s", row.status, row.path, bid)
        try:
            row.save()
            self.session.commit()
            return True
        except IntegrityError as err:
            logging.error("IntegrityError: Duplicate hash detected: %s, %s", row.hash, err)
        except Exception as err:
            logging.exception("save error: %s", err)
        self.session.rollback()
        return False

    def build_query(self, hashlist):
        query = self.session.query(ScanFile).filter(
            ScanFile.status == ScanFile.READY
        )  # .filter(ScanFile.import_id == 0)
        if isinstance(hashlist, (list, tuple)):
            query = query.filter(ScanFile.hash.in_(hashlist))
        elif isinstance(hashlist, str):
            query = query.filter(ScanFile.hash == hashlist)
        return query

    @AsyncService.register_service
    def do_scan(self, path_dir):
        if ScanService.static_is_scanning:
            logging.error("Scanning is running, please wait...")
            return

        ScanService.static_is_scanning = True

        # 创建后台任务
        task_id = None
        try:
            service_item = _("扫描导入目录")
            task = BackgroundService().update_task(
                service_type=BackgroundTask.SERVICE_TYPE_SCAN,
                service_item=service_item,
                progress=0,
                progress_data={"stage": "scanning", "path": path_dir}
            )
            task_id = task.id
        except Exception as e:
            logging.error(f"Failed to create background task: {e}")

        try:
            self.do_scan_internal(path_dir, task_id)
            if task_id:
                BackgroundService().complete_task(task_id=task_id)
            logging.info("Scanning completed")
        except Exception as err:
            if task_id:
                BackgroundService().complete_task(task_id=task_id, error_message=str(err))
            logging.error(f"Scanning failed: {err}")
            logging.error(traceback.format_exc())
        ScanService.static_is_scanning = False

    def do_scan_internal(self, path_dir, task_id=None):
        from calibre.ebooks.metadata.meta import get_metadata

        logging.info("<%s> we are: db=%s, session=%s", self, self.db, self.session)
        logging.info("start to scan %s", path_dir)

        # 生成任务（粗略扫描），前端可以调用API查询进展
        tasks = []
        for dirpath, __, filenames in os.walk(path_dir):
            for fname in filenames:
                fpath = os.path.join(dirpath, fname)
                if not os.path.isfile(fpath):
                    continue

                fmt = fpath.split(".")[-1].lower()
                if fmt not in SCAN_EXT:
                    # logging.debug("bad format: [%s] %s", fmt, fpath)
                    continue
                tasks.append((fname, fpath, fmt))

        # 生成任务ID
        scan_id = int(time.time())
        logging.info("========== start to check files size & name ============")

        rows = []
        inserted_hash = set()
        for fname, fpath, fmt in tasks:
            samefiles = self.session.query(ScanFile).filter(ScanFile.path == fpath)
            logging.debug("Checking same files for path: %s, return count:%d", fpath, samefiles.count())
            if samefiles.count() > 0:
                # 如果已经有相同的文件记录，则跳过
                found_book = False
                for row in samefiles:
                    if row.status == ScanFile.NEW:
                        logging.warning("Got same file path: %s, scan_id:%d, path:%s", fpath, row.scan_id, row.path)
                        found_book = True
                        # 将已存在记录的hash加入集合，避免后续被误删
                        if row.hash:
                            inserted_hash.add(row.hash)
                        rows.append(row)
                        break
                    elif row.status == ScanFile.IMPORTED and self.db.get_data_as_dict(ids=[row.book_id]):
                        logging.warning("File already exists in Scan & library: %s, status=%s", fpath, row.status)
                        found_book = True
                        break
                    else:
                        logging.warning("File already exists in Scan DB, but missed in library, try to import again")

                if found_book:
                    logging.warning("File already exists in Scan & Book DB: %s, status=%s", fpath, row.status)
                    continue

            # New record should be added
            logging.debug("Processing new file: %s", fpath)
            stat = os.stat(fpath)
            md5 = hashlib.md5(fname.encode("UTF-8")).hexdigest()
            hash = "fstat:%s/%s" % (stat.st_size, md5)
            if hash in inserted_hash:
                logging.error("Duplicated processing book, skip: %s", fpath)
                continue
            if self.session.query(ScanFile).filter(ScanFile.hash == hash).count() > 0:
                logging.error("maybe have same book, skip: %s, due to same hash", fpath)
                continue

            row = ScanFile(fpath, hash, scan_id)
            inserted_hash.add(hash)
            if not self.save_or_rollback(row):
                continue
            rows.append(row)
        # self.session.bulk_save_objects(rows)

        logging.info("========== start to check files hash & meta ============")
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
                        progress_data={"stage": "scanning", "path": path_dir}
                    )
                except Exception as e:
                    logging.error(f"Failed to update task progress: {e}")

            if row.status == ScanFile.DROP:
                continue

            fpath = row.path

            # 读取文件，计算哈希值
            sha256 = hashlib.sha256()
            try:
                with open(fpath, "rb") as f:
                    # Read and update hash string value in blocks of 4K
                    for byte_block in iter(lambda: f.read(4096), b""):
                        sha256.update(byte_block)
            except FileNotFoundError:
                row.status = ScanFile.MISSED
                logging.error("File not found when calculating hash: %s", fpath)
                if not self.save_or_rollback(row):
                    logging.error("Failed to save row status: %s", fpath)
                continue
            except PermissionError:
                row.status = ScanFile.PERMISSION
                logging.error("Permission denied when reading file: %s", fpath)
                if not self.save_or_rollback(row):
                    logging.error("Failed to save row status: %s", fpath)
                continue
            except Exception as e:
                row.status = ScanFile.DROP
                logging.error("Error reading file %s: %s", fpath, e)
                if not self.save_or_rollback(row):
                    logging.error("Failed to save row status: %s", fpath)
                continue

            hash = "sha256:" + sha256.hexdigest()
            should_drop = hash in inserted_hash
            if not should_drop:
                hash_rows = self.session.query(ScanFile).filter(ScanFile.hash == hash)
                should_drop = False
                for hash_row in hash_rows:
                    if hash_row.status == ScanFile.IMPORTED and self.db.get_data_as_dict(ids=[hash_row.book_id]):
                        should_drop = True
                        break
                if hash_rows.count() > 0 and not should_drop:
                    # 需要继续处理时，删除ScanDB中旧数据（排除当前记录）
                    self.session.query(ScanFile).filter(
                        ScanFile.hash == hash,
                        ScanFile.id != row.id
                    ).delete(synchronize_session=False)
            if should_drop:
                # 如果已经有相同的哈希值，则删掉本任务
                row.status = ScanFile.DROP
                logging.warning("Duplicate detected: %s, drop it.", hash)
            else:
                # 或者，更新为真实的哈希值
                row.hash = hash

            inserted_hash.add(hash)
            if not self.save_or_rollback(row):
                logging.error("Failed to save row: %s", fpath)
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
                logging.error("Error reading metadata from file %s: %s", fpath, e)
                continue

            if mi.title and mi.title == CALIBRE_ERROR_FLAG:
                logging.error("Failed to get metadata for %s, reason:%s", fpath, mi.comments)
                continue

            row.title = mi.title
            row.author = mi.authors[0] if mi.authors else mi.author_sort
            row.publisher = mi.publisher
            row.tags = ", ".join(mi.tags)
            row.status = ScanFile.READY  # 设置为可处理

            # TODO calibre提供的书籍重复接口只有对比title；应当提前对整个书库的文件做哈希，才能准确去重
            ids = self.db.books_with_same_title(mi)
            if ids:
                for bid in ids:
                    b = self.db.get_metadata(bid, index_is_id=True)
                    logging.info(f" book info: {b}")
                    # 如果是实体书，则跳过
                    if b.get(CALIBRE_COLUMN_BOOK_TYPE, BOOK_TYPE_EBOOK) == BOOK_TYPE_PHYSICAL:
                        continue
                    if b.formats and fmt and fmt.upper() in b.formats:
                        row.book_id = b.id
                        row.status = ScanFile.EXIST
                        break
            if not self.save_or_rollback(row):
                continue
            pass

        # 更新任务进度到100%
        if task_id:
            try:
                BackgroundService().update_progress(
                    task_id=task_id,
                    progress=100,
                    progress_data={"stage": "completed", "path": path_dir}
                )
            except Exception as e:
                logging.error(f"Failed to update task progress: {e}")

        ScanService.static_is_scanning = False
        logging.info("scan task %d completed.", scan_id)

    @AsyncService.register_service
    def do_import(self, hashlist, user_id):
        if ScanService.static_is_importing:
            logging.error("Importing is running, please wait...")
            return
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

        # 生成任务ID
        import_id = int(time.time())
        query = self.build_query(hashlist)
        query.update({ScanFile.import_id: import_id},
                     synchronize_session=False)
        self.session.commit()

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

            # 处理当前批次
            for row in batch_rows:
                fpath = row.path
                fname = os.path.basename(row.path)
                fmt = fpath.split(".")[-1].lower()

                if not os.path.exists(fpath):
                    row.status = ScanFile.MISSED
                    logging.error("file not exists: %s", fpath)
                    continue

                try:
                    with open(fpath, "rb") as stream:
                        mi = get_metadata(stream, stream_type=fmt,
                                          use_libprs_metadata=True)
                        mi.title = utils.super_strip(mi.title)
                        mi.authors = [utils.super_strip(s) for s in mi.authors]
                    if mi.title and mi.title == CALIBRE_ERROR_FLAG:
                        logging.error("Failed to get metadata for %s, reason:%s", fpath, mi.comments)
                        continue

                    # 非结构化的格式，calibre无法识别准确的信息，直接从文件名提取
                    if fmt == "txt":
                        mi.title = utils.remove_zlibrary_suffix(fname.replace("." + fmt, ""))
                        mi.authors = [_(u"佚名")]

                    if fmt == "pdf":
                        if mi.title is None or mi.title.strip() == "":
                            mi.title = utils.remove_zlibrary_suffix(fname.replace("." + fmt, ""))
                        if mi.authors is None or len(mi.authors) == 0 or mi.authors[0].lower() == "unknown":
                            mi.authors = [_(u"佚名")]

                    # 再次检查是否有重复书籍
                    ids = self.db.books_with_same_title(mi)
                    existed_ebook = False
                    logging.info(f"Found same title book ids: {ids} for file: {fpath}")
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
                            logging.info(
                                "import [%s] from %s with format %s", repr(mi.title), fpath, fmt)
                            self.db.add_format(row.book_id, fmt.upper(), fpath, True)
                            row.status = ScanFile.IMPORTED
                    if not existed_ebook:
                        # 未找到重复电子书时，导入新书
                        logging.info("import [%s] from %s", repr(mi.title), fpath)
                        row.book_id = self.db.import_book(mi, [fpath])
                        row.status = ScanFile.IMPORTED

                        # 添加关联表
                        item = Item()
                        item.book_id = row.book_id
                        item.collector_id = user_id
                        try:
                            item.save()
                            imported.append(row.book_id)
                        except Exception as err:
                            logging.error("save link error: %s", err)

                except Exception as err:
                    row.status = ScanFile.INVALID_ISBN
                    logging.error("Failed to process file %s: %s", fpath, err)

            # 批量提交当前批次的更改
            try:
                self.session.commit()
                logging.info("Batch committed: %d-%d", batch_start + 1, batch_end)
            except Exception as err:
                logging.error("Batch commit error: %s", err)
                self.session.rollback()

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
            self.session.commit()
            logging.info("Final commit completed")
        except Exception as err:
            logging.error("Final commit error: %s", err)
            self.session.rollback()

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
