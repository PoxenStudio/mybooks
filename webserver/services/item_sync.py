#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import datetime
import logging
import time

from webserver.services import AsyncService
from webserver.models import Item, BOOK_TYPE_EBOOK
from gettext import gettext as _


class ItemSyncService(AsyncService):
    """Items的create_time同步服务"""

    def __init__(self):
        super().__init__()

    @AsyncService.register_service
    def sync_item_create_time(self):
        """
        同步Items表中create_time为NULL的记录
        通过book_id查询calibre中的书籍信息，获取create_time并更新到对应的item上
        """
        logging.info("Start syncing item create_time")

        try:
            # 查询所有create_time为NULL的items
            items_to_sync = self.session.query(Item).filter(Item.create_time.is_(None)).all()

            if not items_to_sync:
                logging.info("No items with NULL create_time found, sync completed")
                return

            logging.info(f"Found {len(items_to_sync)} items with NULL create_time to sync")

            synced_count = 0
            failed_count = 0

            for item in items_to_sync:
                try:
                    # 通过book_id从calibre数据库获取书籍信息
                    book_metadata = self.db.get_metadata(item.book_id)

                    if book_metadata and hasattr(book_metadata, 'timestamp'):
                        # 获取书籍的timestamp并转换为datetime
                        book_timestamp = book_metadata.timestamp
                        if book_timestamp:
                            # calibre的timestamp是一个datetime对象
                            item.create_time = book_timestamp
                            synced_count += 1
                            logging.debug(f"Synced create_time for item book_id={item.book_id}, create_time={book_timestamp}")
                        else:
                            # 如果书籍没有timestamp，使用当前时间
                            item.create_time = datetime.datetime.now()
                            synced_count += 1
                            logging.debug(f"Set current time as create_time for item book_id={item.book_id}")
                    else:
                        # 如果无法获取书籍元数据，使用当前时间
                        item.create_time = datetime.datetime.now()
                        synced_count += 1
                        logging.warning(f"Could not get metadata for book_id={item.book_id}, using current time")

                except Exception as e:
                    failed_count += 1
                    logging.error(f"Failed to sync create_time for item book_id={item.book_id}: {str(e)}")

                # 每处理10个记录提交一次，避免长时间锁定
                if (synced_count + failed_count) % 10 == 0:
                    try:
                        self.session.commit()
                        logging.debug(f"Committed batch, synced: {synced_count}, failed: {failed_count}")
                    except Exception as e:
                        logging.error(f"Failed to commit batch: {str(e)}")
                        self.session.rollback()

                # 避免过度占用资源
                if (synced_count + failed_count) % 50 == 0:
                    time.sleep(0.1)

            # 最后提交剩余的更改
            try:
                self.session.commit()
                logging.info(f"Item create_time sync completed. Synced: {synced_count}, Failed: {failed_count}")
            except Exception as e:
                logging.error(f"Failed to commit final batch: {str(e)}")
                self.session.rollback()

        except Exception as e:
            logging.error(f"Error during item create_time sync: {str(e)}")
            if self.session:
                self.session.rollback()

        logging.info("Item create_time sync service finished")

    @AsyncService.register_function
    def check_sync_needed(self):
        """
        检查是否需要进行create_time同步
        返回需要同步的记录数量
        """
        try:
            count = self.session.query(Item).filter(Item.create_time.is_(None)).count()
            logging.info(f"Found {count} items with NULL create_time that need syncing")
            return count
        except Exception as e:
            logging.error(f"Error checking sync needed: {str(e)}")
            return 0
