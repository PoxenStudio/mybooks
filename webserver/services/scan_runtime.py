#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""扫描导入的文件级运行时工具：文件签名与元数据缓存。

本模块只做文件 stat/IO 与纯内存操作，不触碰 ORM 会话与书库——所有函数都可以
安全地在预取线程里运行；跨线程只传递路径与解析结果，数据库读写全部留在消费线程。
"""

import copy
import os
import threading
from collections import OrderedDict


def file_signature(path):
    """文件的稳定性指纹：dev/ino/size/mtime_ns/ctime_ns 全部一致才视为"未变过"。

    ctime_ns 能捕捉"同 inode 原地覆盖"之外的替换（rename 盖写会动 ctime），
    mtime_ns 捕捉原地改写。返回 None 表示无法可靠判定（符号链接、文件消失、
    stat 失败）——调用方一律按"不可校验"处理，退回重读重算，绝不把 None 当命中。
    """
    try:
        if os.path.islink(path):
            return None
        stat = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def clone_prepared(value):
    """深拷贝缓存条目，返回与缓存内容完全独立的副本。

    calibre Metadata 自带兼容其字段结构的 deepcopy 方法，优先用它；
    普通 copy.deepcopy 对 Metadata 的嵌套代理字段不安全。
    """
    cloned = {}
    for key, item in value.items():
        if key == "metadata" and item is not None and hasattr(item, "deepcopy"):
            cloned[key] = item.deepcopy()
        else:
            cloned[key] = copy.deepcopy(item)
    return cloned


class MetadataCache:
    """进程内 LRU 元数据缓存：条目数与估算字节双上限。

    键为路径，命中前提是文件签名与存入时一致，不一致即失效剔除；get/put 返回
    与缓存完全独立的副本，调用方对元数据的任何改写（super_strip、补封面等）
    都不会污染缓存条目。字节估算用 repr 的保守近似（封面字节会转义膨胀，
    宁可高估不低估），超过单条上限的条目直接不缓存。
    """

    def __init__(self, capacity=128, byte_limit=32 * 1024 * 1024):
        self.capacity = capacity
        self.byte_limit = byte_limit
        self.entries = OrderedDict()
        self.size = 0
        self.lock = threading.Lock()

    def get(self, path, signature):
        with self.lock:
            entry = self.entries.get(path)
            if entry is None:
                return None
            if entry[0] != list(signature):
                self._remove(path)
                return None
            self.entries.move_to_end(path)
            return clone_prepared(entry[1])

    def _remove(self, path):
        self.size -= self.entries.pop(path)[2]

    def put(self, path, signature, value):
        size = len(repr(value).encode("utf-8"))
        mi = value.get("metadata")
        if mi is not None and not isinstance(mi, (str, bytes)):
            size += len(repr(getattr(mi, "__dict__", mi)).encode("utf-8"))
        with self.lock:
            if path in self.entries:
                self._remove(path)
            if size > self.byte_limit:
                return
            self.entries[path] = (list(signature), clone_prepared(value), size)
            self.size += size
            while len(self.entries) > self.capacity or self.size > self.byte_limit:
                self._remove(next(iter(self.entries)))
