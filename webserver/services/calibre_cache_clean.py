#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

"""
Calibre缓存清理服务
- 定期清理calibre的各种缓存以释放内存
- 减少长时间运行后的内存占用增长
"""

import logging
import threading
from datetime import datetime

import tornado.ioloop

from webserver import loader


CONF = loader.get_settings()


class CalibreCacheCleanService:
    """Calibre缓存清理服务，定期清理calibre的各类缓存以优化内存使用"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(CalibreCacheCleanService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._cache = None
            self._periodic_callback = None
            self._initialized = True
            self._last_clean_time = None
            logging.info("CalibreCacheCleanService initialized")

    def setup(self, calibre_cache):
        """设置calibre cache引用"""
        self._cache = calibre_cache
        logging.info("CalibreCacheCleanService setup completed")

    def clear_calibre_cache(self):
        """清理calibre的各种缓存"""
        if self._cache is None:
            logging.warning("Calibre cache not set, skipping cache clean")
            return

        try:
            cleared_items = []

            # 1. 清理格式元数据缓存
            if hasattr(self._cache, 'format_metadata_cache'):
                count = len(self._cache.format_metadata_cache)
                if count > 0:
                    self._cache.format_metadata_cache.clear()
                    cleared_items.append(f"format_metadata_cache({count} items)")

            # 2. 清理模板缓存
            if hasattr(self._cache, 'formatter_template_cache'):
                count = len(self._cache.formatter_template_cache)
                if count > 0:
                    self._cache.formatter_template_cache.clear()
                    cleared_items.append(f"formatter_template_cache({count} items)")

            # 3. 清理额外文件缓存
            if hasattr(self._cache, 'extra_files_cache'):
                count = len(self._cache.extra_files_cache)
                if count > 0:
                    self._cache.extra_files_cache.clear()
                    cleared_items.append(f"extra_files_cache({count} items)")

            # 4. 清理脏数据缓存
            if hasattr(self._cache, 'dirtied_cache'):
                count = len(self._cache.dirtied_cache)
                if count > 0:
                    self._cache.dirtied_cache.clear()
                    cleared_items.append(f"dirtied_cache({count} items)")

            # 5. 清理链接映射缓存
            if hasattr(self._cache, 'link_maps_cache'):
                count = len(self._cache.link_maps_cache)
                if count > 0:
                    self._cache.link_maps_cache.clear()
                    cleared_items.append(f"link_maps_cache({count} items)")

            # 6. 清理封面缓存
            if hasattr(self._cache, 'cover_caches'):
                cover_cache_count = len(self._cache.cover_caches)
                if cover_cache_count > 0:
                    for cover_cache in self._cache.cover_caches:
                        if hasattr(cover_cache, 'clear'):
                            cover_cache.clear()
                    cleared_items.append(f"cover_caches({cover_cache_count} caches)")

            # 7. 清理虚拟库缓存
            if hasattr(self._cache, 'vls_for_books_cache'):
                if self._cache.vls_for_books_cache is not None:
                    self._cache.vls_for_books_cache = None
                    cleared_items.append("vls_for_books_cache")

            self._last_clean_time = datetime.now()

            if cleared_items:
                logging.info(f"Calibre cache cleaned successfully: {', '.join(cleared_items)}")
            else:
                logging.info("Calibre cache clean completed (no items to clear)")

        except Exception as e:
            logging.error(f"Error clearing calibre cache: {e}", exc_info=True)

    def get_cache_stats(self):
        """获取当前缓存统计信息"""
        if self._cache is None:
            return {}

        stats = {}
        try:
            if hasattr(self._cache, 'format_metadata_cache'):
                stats['format_metadata_cache'] = len(self._cache.format_metadata_cache)
            if hasattr(self._cache, 'formatter_template_cache'):
                stats['formatter_template_cache'] = len(self._cache.formatter_template_cache)
            if hasattr(self._cache, 'extra_files_cache'):
                stats['extra_files_cache'] = len(self._cache.extra_files_cache)
            if hasattr(self._cache, 'dirtied_cache'):
                stats['dirtied_cache'] = len(self._cache.dirtied_cache)
            if hasattr(self._cache, 'link_maps_cache'):
                stats['link_maps_cache'] = len(self._cache.link_maps_cache)
            if hasattr(self._cache, 'cover_caches'):
                stats['cover_caches_count'] = len(self._cache.cover_caches)
        except Exception as e:
            logging.error(f"Error getting cache stats: {e}")

        return stats

    def start(self):
        """启动缓存清理服务"""
        if not CONF.get("CALIBRE_CACHE_CLEAN_ENABLED", True):
            logging.info("Calibre cache clean service is disabled")
            return

        if self._cache is None:
            logging.error("Cannot start CalibreCacheCleanService: calibre cache not set")
            return

        logging.info("Starting Calibre Cache Clean Service...")

        # 获取清理间隔（秒），默认30分钟
        interval_seconds = CONF.get("CALIBRE_CACHE_CLEAN_INTERVAL", 1800)
        interval_ms = interval_seconds * 1000  # 转换为毫秒

        # 使用Tornado的PeriodicCallback定期执行
        self._periodic_callback = tornado.ioloop.PeriodicCallback(
            self.clear_calibre_cache,
            interval_ms
        )
        self._periodic_callback.start()

        # 记录初始缓存状态
        initial_stats = self.get_cache_stats()
        if initial_stats:
            stats_str = ", ".join(f"{k}={v}" for k, v in initial_stats.items())
            logging.info(f"Initial cache stats: {stats_str}")

        logging.info(f"CalibreCacheCleanService started, cleaning every {interval_seconds} seconds ({interval_seconds//60} minutes)")

    def stop(self):
        """停止缓存清理服务"""
        if self._periodic_callback:
            self._periodic_callback.stop()
            logging.info("CalibreCacheCleanService stopped")


# 全局实例
_cache_clean_service = CalibreCacheCleanService()


def get_cache_clean_service() -> CalibreCacheCleanService:
    """获取全局缓存清理服务实例"""
    return _cache_clean_service
