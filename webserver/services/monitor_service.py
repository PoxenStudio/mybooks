#!/usr/bin/env python3
"""
导入目录监控服务: 自动触发扫描导入
监控方案使用了inotify, fanotify可以监控子目录，需要特殊权限，还是inotify简单稳定。
变更时不只是处理一个文件，而是以目录为单位，防止重复处理同一目录下的多个文件事件。
监控线程负责监听文件事件，调度线程负责防抖和触发导入任务，任务线程负责等待 ScanService 空闲并执行导入。
"""

import logging
import os
import threading
import time

from webserver import loader
from webserver.services.scan import ScanService

CONF = loader.get_settings()

# 防抖：最后一次文件事件后等待多长时间（秒）再触发导入
DEBOUNCE_SECONDS = 30

# ScanService 繁忙时的轮询间隔（秒）
POLL_INTERVAL = 10


class MonitorService:
    _instance: "MonitorService | None" = None
    _instance_lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "MonitorService":
        with cls._instance_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._initialized = False
                cls._instance = inst
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._inotify = None

        self._wd_lock = threading.Lock()
        self._wd_to_path: dict[int, str] = {}
        self._path_to_wd: dict[str, int] = {}

        self._state_lock = threading.Lock()
        self._pending_dirs: set[str] = set()
        self._merge_pending: set[str] = set()
        self._last_event_time: float = 0.0

        self._running = False
        self._monitor_thread: threading.Thread | None = None
        self._scheduler_thread: threading.Thread | None = None
        self._active_task_thread: threading.Thread | None = None

    def start(self) -> None:
        """启动监控（幂等，已运行则忽略）。"""
        if self._running:
            return

        try:
            import inotify_simple
        except ImportError:
            logging.error(
                "[Monitor] inotify_simple 未安装，自动监控不可用。"
            )
            return

        watch_path = CONF.get("scan_upload_path", "")
        if not watch_path:
            logging.error("[Monitor] scan_upload_path 未配置，跳过目录监控")
            return

        watch_path = os.path.realpath(watch_path)
        if not os.path.isdir(watch_path):
            logging.error("[Monitor] scan_upload_path 不存在或不是目录: %s", watch_path)
            return

        self._inotify = inotify_simple.INotify()
        self._running = True
        self._add_watch_recursive(watch_path)

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="MonitorService.inotify",
            daemon=True,
        )
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name="MonitorService.scheduler",
            daemon=True,
        )
        self._monitor_thread.start()
        self._scheduler_thread.start()

        logging.info("[Monitor] 已启动，监听目录: %s", watch_path)
        logging.info(
            "[Monitor] 注意: inotify 对 NFS/bind-mount 挂载点内部事件不可见，"
            "如有此类子目录请留意此限制。"
        )

    def stop(self) -> None:
        """停止监控（幂等）。"""
        self._running = False
        if self._inotify:
            try:
                self._inotify.close()
            except Exception:
                pass
        logging.info("[Monitor] 已停止")

    def _watch_flags(self) -> int:
        import inotify_simple

        return (
            inotify_simple.flags.CREATE
            | inotify_simple.flags.CLOSE_WRITE
            | inotify_simple.flags.DELETE_SELF
            | inotify_simple.flags.MOVE_SELF
            | inotify_simple.flags.MOVED_TO
        )

    def _add_watch(self, path: str) -> int | None:
        try:
            wd = self._inotify.add_watch(path, self._watch_flags())
            with self._wd_lock:
                old_wd = self._path_to_wd.pop(path, None)
                if old_wd is not None and old_wd != wd:
                    self._wd_to_path.pop(old_wd, None)
                self._wd_to_path[wd] = path
                self._path_to_wd[path] = wd
            logging.debug("[Monitor] watch+: wd=%d  %s", wd, path)
            return wd
        except OSError as e:
            logging.error("[Monitor] 无法监听目录 %s: %s", path, e)
            return None

    def _remove_wd(self, wd: int) -> None:
        with self._wd_lock:
            path = self._wd_to_path.pop(wd, None)
            if path:
                self._path_to_wd.pop(path, None)
        try:
            self._inotify.rm_watch(wd)
        except OSError:
            pass
        if path:
            logging.debug("[Monitor] watch-: wd=%d  %s", wd, path)

    def _add_watch_recursive(self, root: str) -> None:
        self._add_watch(root)
        try:
            with os.scandir(root) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        self._add_watch_recursive(entry.path)
        except PermissionError as e:
            logging.warning("[Monitor] 无权限扫描目录: %s", e)
        except OSError as e:
            logging.warning("[Monitor] 扫描子目录出错: %s", e)

    def _monitor_loop(self) -> None:
        import inotify_simple

        F = inotify_simple.flags
        IS_DIR_MASK = int(F.ISDIR)
        CREATE_MASK = int(F.CREATE)
        CLOSE_WRITE_MASK = int(F.CLOSE_WRITE)
        DELETE_SELF_MASK = int(F.DELETE_SELF)
        MOVE_SELF_MASK = int(F.MOVE_SELF)
        MOVED_TO_MASK = int(F.MOVED_TO)
        IGNORED_MASK = int(F.IGNORED)

        while self._running:
            try:
                events = self._inotify.read(timeout=1000)  # 1s 超时以便检查 _running
            except Exception as e:
                if self._running:
                    logging.error("[Monitor] inotify.read 异常: %s", e)
                break

            for event in events:
                mask = event.mask
                wd = event.wd
                name = event.name or ""

                # IN_IGNORED: 内核自动回收了该 wd（目录删除/卸载后）
                if mask & IGNORED_MASK:
                    with self._wd_lock:
                        path = self._wd_to_path.pop(wd, None)
                        if path:
                            self._path_to_wd.pop(path, None)
                    continue

                with self._wd_lock:
                    parent_path = self._wd_to_path.get(wd, "")
                if not parent_path:
                    continue

                full_path = os.path.join(parent_path, name) if name else parent_path

                # 被监听的目录自身被删除或移出，清理wd
                if mask & (DELETE_SELF_MASK | MOVE_SELF_MASK):
                    self._remove_wd(wd)
                    continue

                is_dir = bool(mask & IS_DIR_MASK)
                if is_dir and (mask & (CREATE_MASK | MOVED_TO_MASK)):
                    if os.path.isdir(full_path):
                        self._add_watch_recursive(full_path)
                    continue

                if (mask & (CREATE_MASK | CLOSE_WRITE_MASK)) and not is_dir:
                    self._on_file_event(parent_path)

        logging.info("[Monitor] inotify 监控线程退出")

    def _on_file_event(self, dir_path: str) -> None:
        with self._state_lock:
            self._pending_dirs.add(dir_path)
            self._last_event_time = time.monotonic()
        logging.debug("[Monitor] 文件变更记录: %s", dir_path)

    def _scheduler_loop(self) -> None:
        while self._running:
            time.sleep(1)
            with self._state_lock:
                if not self._pending_dirs:
                    continue
                if time.monotonic() - self._last_event_time < DEBOUNCE_SECONDS:
                    continue
                dirs = set(self._pending_dirs)
                self._pending_dirs.clear()

            logging.info("[Monitor] 准备触发导入，目录: %s", sorted(dirs))
            self._enqueue_import(dirs)

        logging.info("[Monitor] 调度线程退出")

    def _enqueue_import(self, dirs: set[str]) -> None:
        with self._state_lock:
            if self._active_task_thread and self._active_task_thread.is_alive():
                self._merge_pending.update(dirs)
                logging.info("[Monitor] 任务线程等待中，新目录合并至队列: %s", sorted(dirs))
                return

        t = threading.Thread(
            target=self._run_import_task,
            args=(dirs,),
            name="MonitorService.import",
            daemon=True,
        )
        with self._state_lock:
            self._active_task_thread = t
        t.start()

    def _run_import_task(self, dirs: set[str]) -> None:
        """
        等待ScanService空闲，轮询期间合并
        """
        while True:
            with self._state_lock:
                if self._merge_pending:
                    dirs |= self._merge_pending
                    self._merge_pending.clear()

            if ScanService.is_scanning() or ScanService.is_importing():
                logging.info(
                    "[Monitor] ScanService 繁忙，%ds 后重试（当前待导入 %d 个目录）",
                    POLL_INTERVAL,
                    len(dirs),
                )
                time.sleep(POLL_INTERVAL)
                continue

            break

        with self._state_lock:
            if self._merge_pending:
                dirs |= self._merge_pending
                self._merge_pending.clear()

        valid_dirs = sorted({d for d in dirs if os.path.isdir(d)})
        if not valid_dirs:
            logging.info("[Monitor] 所有待导入目录均不存在，本次跳过")
            return

        logging.info("[Monitor] 开始自动扫描导入，目录: %s", valid_dirs)
        ScanService().do_scan(valid_dirs)


def get_monitor_service() -> MonitorService:
    return MonitorService()
