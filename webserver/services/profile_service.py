#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

"""
性能分析服务
- 定期收集内存使用情况
- 统计API接口调用次数、平均耗时、最大耗时
- 输出到 /data/logs/profiling.log
"""

import gc
import logging
import os
import psutil
import sys
import threading
from collections import defaultdict
from datetime import datetime
from typing import Dict, List

import tornado.ioloop

from webserver import loader
from webserver.constants import ENABLE_PROFILE, PROFILE_INTERVAL, PROFILE_OUTPUT_INTERVAL


CONF = loader.get_settings()


class APIStats:
    def __init__(self):
        self.count = 0              # 调用次数
        self.total_time = 0.0       # 总耗时
        self.max_time = 0.0         # 最大耗时
        self.min_time = float('inf')  # 最小耗时

    def add(self, duration: float):
        self.count += 1
        self.total_time += duration
        self.max_time = max(self.max_time, duration)
        self.min_time = min(self.min_time, duration)

    def get_avg_time(self) -> float:
        return self.total_time / self.count if self.count > 0 else 0.0

    def reset(self):
        self.count = 0
        self.total_time = 0.0
        self.max_time = 0.0
        self.min_time = float('inf')

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "avg_time": round(self.get_avg_time(), 4),
            "max_time": round(self.max_time, 4),
            "min_time": round(self.min_time, 4) if self.min_time != float('inf') else 0.0,
            "total_time": round(self.total_time, 4)
        }


class ProfileService:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(ProfileService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._api_stats = defaultdict(APIStats)  # endpoint -> APIStats
            self._stats_lock = threading.Lock()
            self._periodic_callback = None
            self._process = psutil.Process()
            self._log_file = None
            self._initialized = True
            self._start_time = datetime.now()

            log_dir = "/data/logs"
            if not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)

    def record_request(self, endpoint: str, method: str, duration: float):
        key = f"{method} {endpoint}"
        with self._stats_lock:
            self._api_stats[key].add(duration)

    def get_memory_info(self) -> Dict:
        try:
            memory_info = self._process.memory_info()
            memory_percent = self._process.memory_percent()

            return {
                "rss": memory_info.rss / (1024 * 1024),  # MB
                "vms": memory_info.vms / (1024 * 1024),  # MB
                "percent": round(memory_percent, 2),
                "num_threads": self._process.num_threads(),
                "num_fds": self._process.num_fds() if hasattr(self._process, 'num_fds') else 0
            }
        except Exception as e:
            logging.error(f"Failed to get memory info: {e}")
            return {}

    def get_top_memory_types(self, top_n: int = 10) -> List[Dict]:
        try:
            gc.collect()
            type_stats = defaultdict(lambda: {"count": 0, "total_size": 0})

            for obj in gc.get_objects():
                try:
                    obj_type = type(obj).__name__
                    obj_size = sys.getsizeof(obj)
                    type_stats[obj_type]["count"] += 1
                    type_stats[obj_type]["total_size"] += obj_size
                except Exception:
                    continue

            result = []
            for type_name, stats in type_stats.items():
                result.append({
                    "type_name": type_name,
                    "count": stats["count"],
                    "total_size": stats["total_size"] / (1024 * 1024),  # 转换为 MB
                    "avg_size": stats["total_size"] / stats["count"] if stats["count"] > 0 else 0
                })

            result.sort(key=lambda x: x["total_size"], reverse=True)
            return result[:top_n]

        except Exception as e:
            logging.error(f"Failed to get top memory types: {e}", exc_info=True)
            return []

    def get_top_memory_classnames(self, top_n: int = 10) -> List[Dict]:
        try:
            gc.collect()
            class_stats = defaultdict(lambda: {"count": 0, "total_size": 0})
            for obj in gc.get_objects():
                try:
                    cls = type(obj)
                    class_name = f"{cls.__module__}.{cls.__name__}"
                    obj_size = sys.getsizeof(obj)
                    class_stats[class_name]["count"] += 1
                    class_stats[class_name]["total_size"] += obj_size
                except Exception:
                    continue
            result = []
            for class_name, stats in class_stats.items():
                result.append({
                    "class_name": class_name,
                    "count": stats["count"],
                    "total_size": stats["total_size"] / (1024 * 1024),
                    "avg_size": stats["total_size"] / stats["count"] if stats["count"] > 0 else 0
                })
            result.sort(key=lambda x: x["total_size"], reverse=True)
            return result[:top_n]
        except Exception as e:
            logging.error(f"Failed to get top memory classnames: {e}", exc_info=True)
            return []

    def _get_stats_snapshot(self) -> Dict:
        with self._stats_lock:
            snapshot = {}
            for endpoint, stats in self._api_stats.items():
                if stats.count > 0:
                    snapshot[endpoint] = stats.to_dict()
                    stats.reset()
            return snapshot

    def _write_profiling_log(self):
        try:
            from webserver.constants import PROFILE_LOG_PATH

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            memory_info = self.get_memory_info()
            api_stats = self._get_stats_snapshot()
            uptime = datetime.now() - self._start_time
            uptime_str = str(uptime).split('.')[0]

            log_lines = []
            log_lines.append("=" * 80)
            log_lines.append(f"Profiling Report - {timestamp}")
            log_lines.append(f"Uptime: {uptime_str}")
            log_lines.append("=" * 80)

            log_lines.append("\n[Memory Usage]")
            if memory_info:
                log_lines.append(f"  RSS: {memory_info['rss']:.2f} MB")
                log_lines.append(f"  VMS: {memory_info['vms']:.2f} MB")
                log_lines.append(f"  Memory Percent: {memory_info['percent']}%")
                log_lines.append(f"  Threads: {memory_info['num_threads']}")
                if memory_info['num_fds'] > 0:
                    log_lines.append(f"  File Descriptors: {memory_info['num_fds']}")
            else:
                log_lines.append("  (Failed to collect memory info)")

            log_lines.append("\n[Top 10 Memory-Consuming Types]")
            try:
                top_types = self.get_top_memory_types(10)
                if top_types:
                    log_lines.append(f"  {'Type':<30} {'Count':>12} {'Total(MB)':>15} {'Avg(Bytes)':>15}")
                    log_lines.append("  " + "-" * 75)
                    for item in top_types:
                        log_lines.append(
                            f"  {item['type_name']:<30} "
                            f"{item['count']:>12,} "
                            f"{item['total_size']:>15.2f} "
                            f"{item['avg_size']:>15.2f}"
                        )
                else:
                    log_lines.append("  (Failed to collect type statistics)")
            except Exception as e:
                log_lines.append(f"  (Error collecting type statistics: {e})")

            log_lines.append("\n[Top 10 Memory-Consuming Classes]")
            try:
                top_classes = self.get_top_memory_classnames(10)
                if top_classes:
                    log_lines.append(f"  {'Class':<50} {'Count':>12} {'Total(MB)':>15} {'Avg(Bytes)':>15}")
                    log_lines.append("  " + "-" * 95)
                    for item in top_classes:
                        log_lines.append(
                            f"  {item['class_name']:<50} "
                            f"{item['count']:>12,} "
                            f"{item['total_size']:>15.2f} "
                            f"{item['avg_size']:>15.2f}"
                        )
                else:
                    log_lines.append("  (Failed to collect class statistics)")
            except Exception as e:
                log_lines.append(f"  (Error collecting class statistics: {e})")

            # API统计信息
            log_lines.append("\n[API Statistics]")
            if api_stats:
                sorted_stats = sorted(api_stats.items(),
                                      key=lambda x: x[1]['count'],
                                      reverse=True)

                log_lines.append(f"  {'Endpoint':<60} {'Count':>8} {'Avg(s)':>10} {'Max(s)':>10} {'Total(s)':>10}")
                log_lines.append("  " + "-" * 100)

                for endpoint, stats in sorted_stats:
                    log_lines.append(
                        f"  {endpoint:<60} "
                        f"{stats['count']:>8} "
                        f"{stats['avg_time']:>10.4f} "
                        f"{stats['max_time']:>10.4f} "
                        f"{stats['total_time']:>10.4f}"
                    )

                total_requests = sum(s['count'] for s in api_stats.values())
                log_lines.append("  " + "-" * 100)
                log_lines.append(f"  Total Requests: {total_requests}")
            else:
                log_lines.append("  (No API calls in this period)")

            log_lines.append("\n")
            log_content = "\n".join(log_lines)
            log_file_path = PROFILE_LOG_PATH

            with open(log_file_path, "w", encoding="utf-8") as f:
                f.write(log_content)

            logging.info(f"Profiling report written to {log_file_path}")

        except Exception as e:
            logging.error(f"Failed to write profiling log: {e}", exc_info=True)

    def start(self):
        """启动性能分析服务"""
        if not CONF.get(ENABLE_PROFILE, False):
            logging.info("Performance profiling is disabled")
            return

        logging.info("Starting Profile Service...")
        self._start_time = datetime.now()
        initial_memory = self.get_memory_info()
        logging.info(f"Initial memory: RSS={initial_memory.get('rss', 0):.2f}MB, "
                     f"Percent={initial_memory.get('percent', 0)}%")

        # 使用Tornado的PeriodicCallback定期执行
        interval_ms = CONF.get(PROFILE_INTERVAL, PROFILE_OUTPUT_INTERVAL) * 1000  # 转换为毫秒
        self._periodic_callback = tornado.ioloop.PeriodicCallback(
            self._write_profiling_log,
            interval_ms
        )
        self._periodic_callback.start()

        logging.info(f"ProfileService started, reporting every {CONF.get(PROFILE_INTERVAL, PROFILE_OUTPUT_INTERVAL)} seconds")

    def stop(self):
        if self._periodic_callback:
            self._periodic_callback.stop()
            logging.info("ProfileService stopped")


# 全局实例
_profile_service = ProfileService()


def get_profile_service() -> ProfileService:
    return _profile_service
