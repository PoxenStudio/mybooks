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
from webserver.services.scan import ScanService, SCAN_EXT

CONF = loader.get_settings()

# 防抖：最后一次文件事件后等待多长时间（秒）再触发导入
DEBOUNCE_SECONDS = 3

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
        self._pending_files: set[str] = set()

        # 任务线程运行时新来的文件事件合并到这个集合，避免重复触发多个导入任务
        self._merge_pending: set[str] = set()
        self._last_event_time: float = 0.0

        # 目录重命名 cookie 跟踪：cookie -> (old_path, timestamp)
        self._move_lock = threading.Lock()
        self._pending_moves: dict[int, tuple[str, float]] = {}

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

        self._monitor_thread = threading.Thread(target=self._monitor_loop,
                                                name="MonitorService.inotify",
                                                daemon=True)
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop,
                                                  name="MonitorService.scheduler",
                                                  daemon=True)
        self._monitor_thread.start()
        self._scheduler_thread.start()

        logging.info("[Monitor] started，target folder: %s", watch_path)
        logging.info(
            "[Monitor] Noted: inotify 对 NFS/bind-mount 挂载点内部事件不可见，"
            "如有此类子目录请 留意此限制。"
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
            | inotify_simple.flags.MOVED_FROM
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
            logging.info("[Monitor] watch+: wd=%d  %s", wd, path)
            return wd
        except OSError as e:
            logging.error("[Monitor] Failed to add watch for %s: %s", path, e)
            return None

    def _remove_watch_with_path(self, path) -> None:
        wd = self._path_to_wd.get(path, None)
        if not wd:
            logging.info("[Monitor]remove watch, not found wd for path:%s", path)
            return
        self._remove_wd(wd)

    def _remove_wd(self, wd: int) -> None:
        with self._wd_lock:
            path = self._wd_to_path.pop(wd, None)
            if path:
                self._path_to_wd.pop(path, None)
        try:
            self._inotify.rm_watch(wd)
        except OSError as e:
            logging.info("Failed to remove watch: %s", e)
        if path:
            logging.info("[Monitor] watch-: wd=%d  %s", wd, path)
        else:
            logging.info("[Monitor] watch-: failed, not found the recorded path, %s", path)

    def _add_watch_recursive(self, root: str) -> None:
        self._add_watch(root)
        if not os.path.isdir(root):
            return
        try:
            with os.scandir(root) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        base_name = os.path.basename(entry.path)
                        if base_name.startswith(".") or base_name.startswith("~"):
                            logging.info("[Monitor] Skipping hidden/temp folder: %s", entry.path)
                            continue
                        self._add_watch_recursive(entry.path)
        except PermissionError as e:
            logging.warning("[Monitor] No permission to scan directory: %s", e)
        except OSError as e:
            logging.warning("[Monitor] Failded to scan subfolder: %s", e)

    def _add_watch_and_scan_files(self, root: str) -> None:
        """添加递归监听，同时扫描目录内已有书籍文件并加入待导入队列。

        解决竞态窗口问题：新目录创建/移入后，在 inotify watch 建立之前就已写入的
        文件不会产生事件，需主动扫描一次。
        """
        logging.info("[Monitor]Add watch for %s", root)
        self._add_watch_recursive(root)
        try:
            for dirpath, _dirnames, filenames in os.walk(root):
                for fname in filenames:
                    self._on_file_event(os.path.join(dirpath, fname))
        except OSError as e:
            logging.warning("[Monitor] Error scanning existing files: %s", e)

    def _monitor_loop(self) -> None:
        import inotify_simple

        F = inotify_simple.flags
        IS_DIR_MASK = int(F.ISDIR)  # 1073741824 (0x40000000)
        CREATE_MASK = int(F.CREATE)  # 256 (0x00000100)
        CLOSE_WRITE_MASK = int(F.CLOSE_WRITE)  # 8 (0x00000008)
        DELETE_SELF_MASK = int(F.DELETE_SELF)  # 1024 (0x00000400)
        MOVE_SELF_MASK = int(F.MOVE_SELF)  # 2048 (0x00000800)
        MOVED_FROM_MASK = int(F.MOVED_FROM)  # 64 (0x00000040)
        MOVED_TO_MASK = int(F.MOVED_TO)  # 128 (0x00000080)
        IGNORED_MASK = int(F.IGNORED)  # 32768 (0x00008000)

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

                logging.info("[Monitor] Event: wd=%d mask=%d name=%s cookie=%d", wd, mask, name, event.cookie)

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
                is_dir = bool(mask & IS_DIR_MASK)
                if not is_dir:
                    is_dir = os.path.isdir(full_path) if os.path.exists(full_path) else False

                if not is_dir:
                    # Remove unsupported files according to file extension
                    ext = full_path.rsplit(".", 1)[-1].lower() if "." in full_path else ""
                    if ext not in SCAN_EXT:
                        logging.info("[Monitor] Ignoring non-book file event: %s", full_path)
                        continue

                # 被监听的目录自身被删除或移出，清理wd
                if mask & (DELETE_SELF_MASK | MOVE_SELF_MASK | MOVED_FROM_MASK):
                    logging.info("Watched folder was removed!! %s", full_path)
                    if mask & MOVED_FROM_MASK:
                        self._remove_watch_with_path(full_path)
                    else:
                        self._remove_wd(wd)

                # 目录被移走（MOVED_FROM）：记录旧路径等待匹配 MOVED_TO cookie
                # 排除非目录的 MOVED_FROM（文件移走不涉及分类更新）
                if mask & (MOVED_FROM_MASK | DELETE_SELF_MASK):
                    logging.info("[Monitor] Folder: Moved/DeleteSelf %s", full_path)
                    if (event.cookie and mask & MOVED_FROM_MASK) or mask & DELETE_SELF_MASK:
                        with self._move_lock:
                            self._pending_moves[event.cookie] = (full_path, time.monotonic())
                    continue

                if mask & (CREATE_MASK | MOVED_TO_MASK):
                    file_type = "Directory" if is_dir else "File"
                    event_type = "Created" if mask & CREATE_MASK else "Moved"
                    logging.info("[Monitor] %s: %s  %s", file_type, event_type, full_path)
                    if os.path.isdir(full_path):
                        # 添加监听的同时扫描已有文件，避免竞态窗口内的文件被漏掉
                        self._add_watch_and_scan_files(full_path)
                    # MOVED_TO：尝试匹配 MOVED_FROM cookie
                    # 匹配成功 → 目录在监控树内重命名/移动（非新建、非从外部移入）
                    if (event.cookie and mask & MOVED_TO_MASK) or mask & CREATE_MASK:
                        with self._move_lock:
                            old_entry = self._pending_moves.pop(event.cookie, None)
                            # 顺带清理超时 cookie（>0.15s 无匹配视为移出监控树）
                            now = time.monotonic()
                            stale = [c for c, (_, t) in self._pending_moves.items() if now - t > 0.15]
                            for c in stale:
                                self._pending_moves.pop(c, None)
                        if old_entry:
                            logging.info("[Monitor] %s renamed/moved within tree: %s -> %s", file_type, old_entry[0], full_path)
                            self._on_moved(old_entry[0], full_path, is_dir)
                            # Try to add watch again
                            logging.info("[Monitor] add watch for %s", full_path)
                            if os.path.isdir(full_path):
                                self._add_watch_recursive(full_path)
                    if not is_dir and (mask & CREATE_MASK):
                        self._on_file_event(full_path)
                    continue

                if (mask & (CREATE_MASK | CLOSE_WRITE_MASK)) and not is_dir:
                    self._on_file_event(full_path)

        logging.info("[Monitor] inotify monitor thread exiting")

    def _on_file_event(self, file_path) -> None:
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        if ext not in SCAN_EXT:
            logging.info("[Monitor] Ignoring non-book file: %s", file_path)
            return
        with self._state_lock:
            self._pending_files.add(file_path)
            self._last_event_time = time.monotonic()
        logging.info("[Monitor] New file event: %s", file_path)

    def _on_moved(self, old_path, new_path, is_dir=True) -> None:
        """目录在监控树内重命名/移动时调用，按配置更新受影响书籍的分类。"""
        if not CONF.get("UPDATE_CATEGORY_WITH_FOLDER_RENAME", False):
            logging.info("[Monitor] Not config updaing with folder renameing, skip category update.")
            return
        scan_upload_path = os.path.realpath(CONF.get("scan_upload_path", ""))
        logging.info("[Monitor] Renamed: %s -> %s", old_path, new_path)

        # 清理pending_files中新目录下的文件
        new_path_prefix = new_path.rstrip(os.sep) + os.sep
        with self._state_lock:
            self._pending_files = {file_path for file_path in self._pending_files if not file_path.startswith(new_path_prefix)}
        if is_dir:
            ScanService().do_rename_category(old_path, new_path, scan_upload_path)
        else:
            ScanService().do_moved_file(old_path, new_path, scan_upload_path)

    def _scheduler_loop(self) -> None:
        while self._running:
            time.sleep(1)
            with self._state_lock:
                if not self._pending_files:
                    continue
                if time.monotonic() - self._last_event_time < DEBOUNCE_SECONDS:
                    continue
                files = set(self._pending_files)
                self._pending_files.clear()

            logging.info("[Monitor] Preparing to trigger import, number of files: %d", len(files))
            self._enqueue_import(files)

        logging.info("[Monitor] Scheduler thread exiting")

    def _enqueue_import(self, files: set[str]) -> None:
        with self._state_lock:
            if self._active_task_thread and self._active_task_thread.is_alive():
                self._merge_pending.update(files)
                logging.info("[Monitor] Task thread waiting, new files merged into queue: %d", len(files))
                return

        t = threading.Thread(
            target=self._run_import_task,
            args=(files,),
            name="MonitorService.import",
            daemon=True,
        )
        with self._state_lock:
            self._active_task_thread = t
        t.start()

    def _run_import_task(self, files: set[str]) -> None:
        """
        等待ScanService空闲，轮询期间合并新文件
        """
        while True:
            with self._state_lock:
                if self._merge_pending:
                    files |= self._merge_pending
                    self._merge_pending.clear()

            if ScanService.is_scanning() or ScanService.is_importing():
                logging.info(
                    "[Monitor] ScanService busy, retrying in %ds (current pending files: %d)",
                    POLL_INTERVAL,
                    len(files),
                )
                time.sleep(POLL_INTERVAL)
                continue

            break

        with self._state_lock:
            if self._merge_pending:
                files |= self._merge_pending
                self._merge_pending.clear()

        logging.info("[Monitor] Starting automatic scan and import, number of files: %d", len(files))
        user_id = CONF.get("ADMIN_ID", 1)
        ScanService().do_scan_import_files(files, user_id)


def get_monitor_service() -> MonitorService:
    return MonitorService()
