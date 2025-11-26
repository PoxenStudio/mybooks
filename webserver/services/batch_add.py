#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import csv
import codecs
import hashlib
import logging
import os
import tempfile
import requests
from gettext import gettext as _

from webserver import loader
from webserver.models import Item, ScanFile, BOOK_TYPE_PHYSICAL
from webserver.services import AsyncService
from webserver.plugins.meta import douban

CONF = loader.get_settings()


class BatchAddService(AsyncService):
    static_is_running = False
    static_status = {
        'total': 0,
        'processed': 0,
        'success': 0,
        'failed': 0,
        'invalid': 0
    }

    @staticmethod
    def is_running():
        return BatchAddService.static_is_running

    @staticmethod
    def get_status():
        return BatchAddService.static_status.copy()

    def save_or_rollback(self, row):
        try:
            row.save()
            self.session.commit()
            return True
        except Exception as err:
            logging.exception("save error: %s", err)
            self.session.rollback()
            return False

    @AsyncService.register_service
    def start_batch_add(self, csv_path, csv_filename, user_id):
        """启动批量添加任务"""
        if BatchAddService.static_is_running:
            logging.error("Batch adding is running, please wait...")
            return 0

        BatchAddService.static_is_running = True
        BatchAddService.static_status = {
            'total': 0,
            'processed': 0,
            'success': 0,
            'failed': 0,
            'invalid': 0
        }

        try:
            total = self.do_batch_add(csv_path, csv_filename, user_id)
            logging.info("Batch add completed, total: %d", total)
            return total
        except Exception as err:
            logging.error(f"Batch add failed: {err}")
            import traceback
            logging.error(traceback.format_exc())
            return 0
        finally:
            BatchAddService.static_is_running = False
            # 清理临时文件
            try:
                if os.path.exists(csv_path):
                    os.unlink(csv_path)
            except:
                pass

    def do_batch_add(self, csv_path, csv_filename, user_id):
        """执行批量添加"""
        logging.info("Start batch add from CSV: %s", csv_path)

        # 检测编码
        try:
            with open(csv_path, 'rb') as f:
                raw_data = f.read()
                try:
                    raw_data.decode('utf-8')
                    encoding = 'utf-8'
                except:
                    try:
                        raw_data.decode('gbk')
                        encoding = 'gbk'
                    except:
                        encoding = 'utf-8'
        except:
            encoding = 'utf-8'

        # 读取CSV文件
        rows = []
        with codecs.open(csv_path, 'r', encoding=encoding) as f:
            reader = csv.DictReader(f, delimiter='\t')
            rows = list(reader)

        BatchAddService.static_status['total'] = len(rows)
        logging.info("Total rows to process: %d", len(rows))

        # 处理每一行
        for idx, row in enumerate(rows):
            isbn = row.get('isbn', '').strip()
            title = row.get('title', '').strip()
            author = row.get('author', '').strip()
            cover_url = row.get('coverUrl', '').strip()

            logging.info("Processing row %d/%d: ISBN=%s, title=%s",
                        idx + 1, len(rows), isbn, title)

            if not isbn:
                # 没有ISBN，记录为无效
                self._record_invalid_isbn(csv_filename, "", title, author)
                BatchAddService.static_status['invalid'] += 1
                BatchAddService.static_status['processed'] += 1
                continue

            # 清理ISBN
            isbn = isbn.replace('-', '').replace(' ', '')

            # 检查ISBN是否已存在
            existing_books = self._find_books_by_isbn(isbn)

            if existing_books:
                # ISBN已存在，更新数量
                book_id = list(existing_books)[0]
                self._update_book_count(book_id, user_id, csv_filename, isbn, title, author)
                BatchAddService.static_status['success'] += 1
            else:
                # ISBN不存在，添加新书
                if title and author:
                    # 使用提供的信息添加
                    book_id = self._add_book_with_metadata(
                        isbn, title, author, cover_url, user_id, csv_filename
                    )
                else:
                    # 只有ISBN，从豆瓣获取信息
                    book_id = self._add_book_by_isbn(isbn, user_id, csv_filename, title, author)

                if book_id:
                    BatchAddService.static_status['success'] += 1
                else:
                    BatchAddService.static_status['failed'] += 1

            BatchAddService.static_status['processed'] += 1

        return len(rows)

    def _find_books_by_isbn(self, isbn):
        """查找ISBN对应的书籍"""
        try:
            # 使用calibre DB查找
            from calibre.utils.date import parse_date
            books = set()

            # 搜索ISBN
            ids = self.db.search(f'isbn:{isbn}', return_matches=True)
            if ids:
                books.update(ids)

            return books
        except Exception as e:
            logging.error("Error finding books by ISBN %s: %s", isbn, e)
            return set()

    def _update_book_count(self, book_id, user_id, csv_filename, isbn, title, author):
        """更新已存在书籍的数量"""
        try:
            existing_item = self.session.query(Item).filter(
                Item.book_id == book_id
            ).first()

            book_count = 1
            if existing_item:
                book_count = (existing_item.book_count or 0) + 1
                existing_item.book_count = book_count
                self.session.add(existing_item)
            else:
                item = Item()
                item.book_id = book_id
                item.collector_id = user_id
                item.book_type = BOOK_TYPE_PHYSICAL
                item.book_count = book_count
                self.session.add(item)

            self.session.commit()

            # 更新calibre custom data
            try:
                self.db.add_custom_book_data(book_id, "real_book_cnt", book_count)
            except:
                pass

            # 记录到ScanFile
            self._record_scan_file(csv_filename, isbn, title, author, ScanFile.EXIST, book_id)

            logging.info("Updated book count for ISBN %s, book_id=%d, count=%d",
                        isbn, book_id, book_count)
        except Exception as e:
            logging.error("Error updating book count: %s", e)
            self.session.rollback()

    def _add_book_by_isbn(self, isbn, user_id, csv_filename, title="", author=""):
        """通过ISBN从豆瓣获取信息并添加书籍"""
        try:
            api = douban.DoubanBookApi(
                CONF["douban_apikey"],
                CONF["douban_baseurl"],
                copy_image=True,
                maxCount=1
            )

            md = douban.SimpleMetaData(isbn=isbn)
            book_data = api.get_book(md)

            if not book_data:
                logging.error("No book data found for ISBN: %s", isbn)
                self._record_invalid_isbn(csv_filename, isbn, title, author)
                return None

            # 创建书籍
            book_id = self.db.create_book_entry(book_data)
            if book_id is None:
                logging.error("Failed to create book entry for ISBN: %s", isbn)
                self._record_invalid_isbn(csv_filename, isbn, title, author)
                return None

            # 添加自定义数据
            try:
                self.db.add_custom_book_data(book_id, "real_book_cnt", 1)
            except:
                pass

            # 创建Item记录
            item = Item()
            item.book_id = book_id
            item.collector_id = user_id
            item.book_type = BOOK_TYPE_PHYSICAL
            item.book_count = 1
            self.session.add(item)
            self.session.commit()

            # 记录到ScanFile
            book_title = book_data.title if hasattr(book_data, 'title') else title
            book_author = ', '.join(book_data.authors) if hasattr(book_data, 'authors') else author
            self._record_scan_file(csv_filename, isbn, book_title, book_author, ScanFile.IMPORTED, book_id)

            logging.info("Added book by ISBN %s, book_id=%d", isbn, book_id)
            return book_id

        except Exception as e:
            logging.error("Error adding book by ISBN %s: %s", isbn, e)
            import traceback
            logging.error(traceback.format_exc())
            self._record_invalid_isbn(csv_filename, isbn, title, author)
            return None

    def _add_book_with_metadata(self, isbn, title, author, cover_url, user_id, csv_filename):
        """使用提供的元数据添加书籍"""
        try:
            from calibre.ebooks.metadata.book.base import Metadata
            from calibre.utils.date import now as nowf

            # 创建metadata对象
            mi = Metadata(title, [author])
            mi.isbn = isbn
            mi.timestamp = nowf()

            # 如果提供了封面URL，下载封面
            if cover_url:
                try:
                    cover_data = self._download_cover(cover_url)
                    if cover_data:
                        # 检测图片格式
                        if cover_url.lower().endswith('.jpg') or cover_url.lower().endswith('.jpeg'):
                            fmt = 'jpg'
                        elif cover_url.lower().endswith('.png'):
                            fmt = 'png'
                        else:
                            fmt = 'jpg'
                        mi.cover_data = (fmt, cover_data)
                except Exception as e:
                    logging.error("Failed to download cover from %s: %s", cover_url, e)

            # 创建书籍
            book_id = self.db.create_book_entry(mi)
            if book_id is None:
                logging.error("Failed to create book entry for title: %s", title)
                self._record_invalid_isbn(csv_filename, isbn, title, author)
                return None

            # 添加自定义数据
            try:
                self.db.add_custom_book_data(book_id, "real_book_cnt", 1)
            except:
                pass

            # 创建Item记录
            item = Item()
            item.book_id = book_id
            item.collector_id = user_id
            item.book_type = BOOK_TYPE_PHYSICAL
            item.book_count = 1
            self.session.add(item)
            self.session.commit()

            # 记录到ScanFile
            self._record_scan_file(csv_filename, isbn, title, author, ScanFile.IMPORTED, book_id)

            logging.info("Added book with metadata: %s, book_id=%d", title, book_id)
            return book_id

        except Exception as e:
            logging.error("Error adding book with metadata: %s", e)
            import traceback
            logging.error(traceback.format_exc())
            self._record_invalid_isbn(csv_filename, isbn, title, author)
            return None

    def _download_cover(self, cover_url):
        """下载封面图片"""
        try:
            response = requests.get(cover_url, timeout=10)
            if response.status_code == 200:
                return response.content
            else:
                logging.error("Failed to download cover, status: %d", response.status_code)
                return None
        except Exception as e:
            logging.error("Error downloading cover: %s", e)
            return None

    def _record_scan_file(self, csv_filename, isbn, title, author, status, book_id=0):
        """记录到ScanFile表"""
        try:
            # 生成hash
            hash_str = f"{csv_filename}_{isbn}"
            hash_value = hashlib.md5(hash_str.encode('utf-8')).hexdigest()

            # 检查是否已存在
            existing = self.session.query(ScanFile).filter(ScanFile.hash == hash_value).first()
            if existing:
                existing.status = status
                existing.book_id = book_id
                if title:
                    existing.title = title
                if author:
                    existing.author = author
                self.session.add(existing)
            else:
                scan_file = ScanFile(csv_filename, hash_value, 0)
                scan_file.name = isbn
                scan_file.title = title
                scan_file.author = author
                scan_file.status = status
                scan_file.book_id = book_id
                self.session.add(scan_file)

            self.session.commit()
        except Exception as e:
            logging.error("Error recording scan file: %s", e)
            self.session.rollback()

    def _record_invalid_isbn(self, csv_filename, isbn, title, author):
        """记录无效的ISBN"""
        try:
            hash_str = f"{csv_filename}_{isbn}_{title}"
            hash_value = hashlib.md5(hash_str.encode('utf-8')).hexdigest()

            scan_file = ScanFile(csv_filename, hash_value, 0)
            scan_file.name = isbn if isbn else "NO_ISBN"
            scan_file.title = title
            scan_file.author = author
            scan_file.status = ScanFile.INVALID_ISBN
            scan_file.book_id = 0
            self.session.add(scan_file)
            self.session.commit()
        except Exception as e:
            logging.error("Error recording invalid ISBN: %s", e)
            self.session.rollback()
