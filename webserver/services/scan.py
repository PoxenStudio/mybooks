#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import hashlib
import os
import logging
import time

from gettext import gettext as _
from sqlalchemy.exc import IntegrityError

from webserver import utils
from webserver.models import Item, ScanFile
from webserver.services import AsyncService
from webserver.services.autofill import AutoFillService

SCAN_EXT = ["azw", "azw3", "epub", "mobi", "pdf", "txt"]


class ScanService(AsyncService):
    def save_or_rollback(self, row):
        try:
            row.save()
            self.session.commit()
            bid = "[ book-id=%s ]" % row.book_id
            logging.info("update: status=%-5s, path=%s %s",
                         row.status, row.path, bid if row.book_id > 0 else "")
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
        from calibre.ebooks.metadata.meta import get_metadata

        logging.info("<%s> we are: db=%s, session=%s",
                     self, self.db, self.session)
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
            if samefiles.count() > 0:
                # 如果已经有相同的文件记录，则跳过
                found_book = False
                for row in samefiles:
                    if row.status == ScanFile.NEW:
                        logging.warning("Got same file path: %s, id:%d, path:%s", fpath, row.id, row.path)
                        found_book = True
                        row.status = ScanFile.NEW
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

            stat = os.stat(fpath)
            md5 = hashlib.md5(fname.encode("UTF-8")).hexdigest()
            hash = "fstat:%s/%s" % (stat.st_size, md5)
            if hash in inserted_hash:
                row.status = ScanFile.DROP
                logging.error("Duplicated processing book, skip: %s", fpath)
                continue
            if self.session.query(ScanFile).filter(ScanFile.hash == hash).count() > 0:
                row.status = ScanFile.DROP
                logging.error("maybe have same book, skip: %s, due to same hash", fpath)
                continue

            inserted_hash.add(hash)
            row = ScanFile(fpath, hash, scan_id)
            if not self.save_or_rollback(row):
                continue
            rows.append(row)
        # self.session.bulk_save_objects(rows)

        logging.info("========== start to check files hash & meta ============")
        # 检查文件哈希值，检查DB重复情况
        for row in rows:
            if row.status == ScanFile.DROP:
                continue

            fpath = row.path

            # 读取文件，计算哈希值
            sha256 = hashlib.sha256()
            with open(fpath, "rb") as f:
                # Read and update hash string value in blocks of 4K
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256.update(byte_block)

            hash = "sha256:" + sha256.hexdigest()
            should_drop = hash in inserted_hash
            if not should_drop:
                hash_rows = self.session.query(ScanFile).filter(ScanFile.hash == hash)
                should_drop = False
                for hash_row in hash_rows:
                    if hash_row.status == ScanFile.IMPORTED and self.db.get_data_as_dict(ids=[row.book_id]):
                        should_drop = True
                        break
                if hash_rows.count() > 0 and not should_drop:
                    # 需要继续处理时，删除ScanDB中旧数据
                    self.session.query(ScanFile).filter(ScanFile.hash == hash).delete()
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
            with open(fpath, "rb") as stream:
                mi = get_metadata(stream, stream_type=fmt,
                                  use_libprs_metadata=True)
                mi.title = utils.super_strip(mi.title)
                mi.authors = [utils.super_strip(s) for s in mi.authors]

            row.title = mi.title
            row.author = mi.author_sort
            row.publisher = mi.publisher
            row.tags = ", ".join(mi.tags)
            row.status = ScanFile.READY  # 设置为可处理

            # TODO calibre提供的书籍重复接口只有对比title；应当提前对整个书库的文件做哈希，才能准确去重
            ids = self.db.books_with_same_title(mi)
            if ids:
                for b in self.db.get_data_as_dict(ids=list(ids)):
                    if fmt.upper() in b.get("available_formats", ""):
                        row.book_id = b['id']
                        row.status = ScanFile.EXIST
                        break
            if not self.save_or_rollback(row):
                continue
            pass

    @AsyncService.register_service
    def do_import(self, hashlist, user_id):
        from calibre.ebooks.metadata.meta import get_metadata

        # 生成任务ID
        import_id = int(time.time())

        query = self.build_query(hashlist)
        query.update({ScanFile.import_id: import_id},
                     synchronize_session=False)
        self.session.commit()

        imported = []

        # 逐个处理
        for row in query.all():
            fpath = row.path
            fname = os.path.basename(row.path)
            fmt = fpath.split(".")[-1].lower()
            with open(fpath, "rb") as stream:
                mi = get_metadata(stream, stream_type=fmt,
                                  use_libprs_metadata=True)
                mi.title = utils.super_strip(mi.title)
                mi.authors = [utils.super_strip(s) for s in mi.authors]

            # 非结构化的格式，calibre无法识别准确的信息，直接从文件名提取
            if fmt in ["txt", "pdf"]:
                mi.title = fname.replace("." + fmt, "")
                mi.authors = [_(u"佚名")]

            # 再次检查是否有重复书籍
            ids = self.db.books_with_same_title(mi)
            if ids:
                row.book_id = ids.pop()
                for b in self.db.get_data_as_dict(ids=ids):
                    if fmt.upper() in b.get("available_formats", ""):
                        row.status = ScanFile.EXIST
                        break
                if row.status != ScanFile.EXIST:
                    logging.info(
                        "import [%s] from %s with format %s", repr(mi.title), fpath, fmt)
                    self.db.add_format(row.book_id, fmt.upper(), fpath, True)
                    row.status = ScanFile.IMPORTED
                self.save_or_rollback(row)
            else:
                logging.info("import [%s] from %s", repr(mi.title), fpath)
                row.book_id = self.db.import_book(mi, [fpath])
                row.status = ScanFile.IMPORTED
                self.save_or_rollback(row)

                # 添加关联表
                item = Item()
                item.book_id = row.book_id
                item.collector_id = user_id
                try:
                    item.save()
                    imported.append(row.book_id)
                except Exception as err:
                    self.session.rollback()
                    logging.error("save link error: %s", err)

        # 全部导入完毕后，开始拉取书籍信息
        AutoFillService().auto_fill_all(imported)
