#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

"""
性能分析服务
- 定期收集内存使用情况
- 统计API接口调用次数、平均耗时、最大耗时
- 输出到 /data/logs/profiling.log
"""

import logging
import os
import psutil
import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, List

import tornado.ioloop

from webserver import loader


CONF = loader.get_settings()


class APIStats:
    """API统计信息"""
    def __init__(self):
        self.count = 0              # 调用次数
        self.total_time = 0.0       # 总耗时
        self.max_time = 0.0         # 最大耗时
        self.min_time = float('inf')  # 最小耗时

    def add(self, duration: float):
        """添加一次调用记录"""
        self.count += 1
        self.total_time += duration
        self.max_time = max(self.max_time, duration)
        self.min_time = min(self.min_time, duration)

    def get_avg_time(self) -> float:
        """获取平均耗时"""
        return self.total_time / self.count if self.count > 0 else 0.0

    def reset(self):
        """重置统计数据"""
        self.count = 0
        self.total_time = 0.0
        self.max_time = 0.0
        self.min_time = float('inf')

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "count": self.count,
            "avg_time": round(self.get_avg_time(), 4),
            "max_time": round(self.max_time, 4),
            "min_time": round(self.min_time, 4) if self.min_time != float('inf') else 0.0,
            "total_time": round(self.total_time, 4)
        }


class ProfileService:
    """性能分析服务（单例）"""
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

            # 确保日志目录存在
            log_dir = "/data/logs"
            if not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)

    def record_request(self, endpoint: str, method: str, duration: float):
        """
        记录一次API请求

        Args:
            endpoint: 请求路径
            method: HTTP方法
            duration: 请求耗时(秒)
        """
        key = f"{method} {endpoint}"
        with self._stats_lock:
            self._api_stats[key].add(duration)

    def get_memory_info(self) -> Dict:
        """获取当前内存使用情况"""
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

    def _get_stats_snapshot(self) -> Dict:
        """获取统计数据快照并重置计数器"""
        with self._stats_lock:
            snapshot = {}
            for endpoint, stats in self._api_stats.items():
                if stats.count > 0:
                    snapshot[endpoint] = stats.to_dict()
                    stats.reset()
            return snapshot

    def _write_profiling_log(self):
        """定期写入性能分析日志"""
        try:
            from webserver.constants import PROFILE_LOG_PATH

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 获取内存信息
            memory_info = self.get_memory_info()

            # 获取API统计快照
            api_stats = self._get_stats_snapshot()

            # 运行时长
            uptime = datetime.now() - self._start_time
            uptime_str = str(uptime).split('.')[0]  # 去掉微秒

            # 构建日志内容
            log_lines = []
            log_lines.append("=" * 80)
            log_lines.append(f"Profiling Report - {timestamp}")
            log_lines.append(f"Uptime: {uptime_str}")
            log_lines.append("=" * 80)

            # 内存信息
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

            # API统计信息
            log_lines.append("\n[API Statistics]")
            if api_stats:
                # 按调用次数排序
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

                # 统计摘要
                total_requests = sum(s['count'] for s in api_stats.values())
                log_lines.append("  " + "-" * 100)
                log_lines.append(f"  Total Requests: {total_requests}")
            else:
                log_lines.append("  (No API calls in this period)")

            log_lines.append("\n")

            # 写入日志文件
            log_content = "\n".join(log_lines)
            log_file_path = PROFILE_LOG_PATH

            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(log_content)

            logging.info(f"Profiling report written to {log_file_path}")

        except Exception as e:
            logging.error(f"Failed to write profiling log: {e}", exc_info=True)

    def start(self):
        """启动性能分析服务"""
        from webserver.constants import ENABLE_PROFILE, PROFILE_OUTPUT_INTERVAL

        if not CONF.get(ENABLE_PROFILE, False):
            logging.info("Performance profiling is disabled")
            return

        logging.info("Starting ProfileService...")

        # 记录启动信息
        self._start_time = datetime.now()
        initial_memory = self.get_memory_info()
        logging.info(f"Initial memory: RSS={initial_memory.get('rss', 0):.2f}MB, "
                    f"Percent={initial_memory.get('percent', 0)}%")

        # 使用Tornado的PeriodicCallback定期执行
        interval_ms = PROFILE_OUTPUT_INTERVAL * 1000  # 转换为毫秒
        self._periodic_callback = tornado.ioloop.PeriodicCallback(
            self._write_profiling_log,
            interval_ms
        )
        self._periodic_callback.start()

        logging.info(f"ProfileService started, reporting every {PROFILE_OUTPUT_INTERVAL} seconds")

    def stop(self):
        """停止性能分析服务"""
        if self._periodic_callback:
            self._periodic_callback.stop()
            logging.info("ProfileService stopped")


# 全局实例
_profile_service = ProfileService()


def get_profile_service() -> ProfileService:
    """获取性能分析服务实例"""
    return _profile_service
