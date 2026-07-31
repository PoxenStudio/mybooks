"""search_task_service — 异步多书源并发搜索

与 Talebook booksource_search.py 同架构：
- 单例管理搜索任务
- ThreadPoolExecutor 并发执行各源
- 创建任务立即返回 task_id，快源先出、慢源不拖累
- 前端/调用方轮询 get_status 逐步获取结果
"""

import concurrent.futures
import logging
import threading
import time
import uuid

try:
    from .rule_engine import search_books
except ImportError:  # standalone 运行（CLI / PyInstaller）
    from rule_engine import search_books

logger = logging.getLogger(__name__)

TASK_TTL = 300  # 任务保留时长（秒）


class SearchTaskService:
    """单例：管理搜索任务，后台线程池并发执行。"""

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._init()
                    cls._instance = instance
        return cls._instance

    def _init(self):
        self._tasks = {}
        self._lock = threading.Lock()
        self._executor = None
        self._max_workers = 10

    def configure(self, max_workers: int):
        self._max_workers = max(1, int(max_workers))

    def _ensure_executor(self):
        if self._executor is None:
            self._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="mybooks_search",
            )
        return self._executor

    def create_task(self, keyword: str, sources: list[dict]) -> dict:
        """创建搜索任务，各源提交到后台线程池，立即返回 task_id。

        sources: [{"name": ..., "source": BookSource}, ...]
        """
        self._cleanup()
        task_id = uuid.uuid4().hex
        src_map = {}
        for item in sources:
            sid = item["name"]
            src_map[sid] = {
                "source_id": sid,
                "source_name": sid,
                "state": "pending",
                "books": [],
                "error": "",
            }
        task = {
            "task_id": task_id,
            "keyword": keyword,
            "created_at": time.time(),
            "total": len(sources),
            "done": 0,
            "sources": src_map,
        }
        with self._lock:
            self._tasks[task_id] = task

        executor = self._ensure_executor()
        for item in sources:
            executor.submit(self._run_one, task_id, keyword, item)
        return {"task_id": task_id, "total": task["total"]}

    def _run_one(self, task_id: str, keyword: str, item: dict):
        sid = item["name"]
        source = item["source"]
        state, books, error = "done", [], ""
        try:
            results = search_books(source, keyword)
            books = [
                {
                    "name": r.get("name", ""),
                    "author": r.get("author", ""),
                    "kind": r.get("kind", ""),
                    "wordCount": r.get("wordCount", ""),
                    "lastChapter": r.get("lastChapter", ""),
                    "intro": r.get("intro", ""),
                    "coverUrl": r.get("coverUrl", ""),
                    "bookUrl": r.get("bookUrl", ""),
                }
                for r in results
            ]
        except Exception as e:
            logger.info("search [%s] failed: %s", sid, e)
            state, error = "failed", str(e)[:100]

        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            src = task["sources"].get(sid)
            if not src or src["state"] != "pending":
                return
            src["state"] = state
            src["books"] = books
            src["error"] = error
            task["done"] += 1

    def get_status(self, task_id: str) -> dict | None:
        """返回任务进度快照；任务不存在返回 None。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            results, partial, pending = [], [], []
            for src in task["sources"].values():
                if src["state"] == "done":
                    if src["books"]:
                        results.append({
                            "source_id": src["source_id"],
                            "source_name": src["source_name"],
                            "books": src["books"],
                        })
                elif src["state"] == "failed":
                    partial.append({
                        "source_id": src["source_id"],
                        "source_name": src["source_name"],
                        "error": src["error"],
                    })
                else:
                    pending.append({
                        "source_id": src["source_id"],
                        "source_name": src["source_name"],
                    })
            return {
                "task_id": task_id,
                "total": task["total"],
                "done": task["done"],
                "finished": task["done"] >= task["total"],
                "results": results,
                "partial": partial,
                "pending": pending,
            }

    def _cleanup(self):
        now = time.time()
        with self._lock:
            expired = [tid for tid, t in self._tasks.items() if now - t["created_at"] > TASK_TTL]
            for tid in expired:
                self._tasks.pop(tid, None)
