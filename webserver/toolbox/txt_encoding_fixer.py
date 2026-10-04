# -*- coding: utf-8 -*-
"""TXT 编码修复工具

检测 TXT 电子书的编码（BOM / 候选编码打分 / chardet 投票 / mojibake 反转链），
解码为正确的 UTF-8（无 BOM）文本，并以「生成新书」模式入库，原书零改动。

对外接口：
- :meth:`analyze` 同步检测，返回检测报告 + 修复后预览（供前端展示）；
- :meth:`fix` 后台任务，解码修复 → UTF-8 无 BOM 写出 → 新书入库。

@author: 黏菌, 2026
"""
import logging
import os
import threading
import time
import traceback
from typing import Optional

from webserver.i18n import _
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver.toolbox.base_tool import BaseTool

from webserver.toolbox.utils import book_utils
from webserver.toolbox.utils import encoding_detect

PREVIEW_CHARS = 500  # analyze 报告中的修复预览长度
ANALYZE_LIMIT = 2 * 1024 * 1024  # analyze 检测读取上限（编码检测取前缀即可，防大文件阻塞请求线程）
WRITE_CHUNK_CHARS = 1 << 20  # fix 分块写出的字符数（压低「文本+编码字节」同时在内存的峰值）


class TxtEncodingFixerTool(BaseTool):
    """对指定书籍的 TXT 格式执行编码检测与修复。"""

    service_item_name = "TXT编码修复"

    _fix_lock = threading.Lock()
    _last_task_id: Optional[int] = None

    @classmethod
    def is_running(cls) -> bool:
        task = cls.get_last_task()
        return bool(task and task.get("status") == BackgroundTask.STATUS_RUNNING)

    @classmethod
    def get_last_task(cls) -> Optional[dict]:
        if cls._last_task_id is None:
            return None
        return BackgroundService().get_task(cls._last_task_id)

    @staticmethod
    def info() -> dict:
        return {
            "tool_id": "txt_encoding_fixer",
            "name": "TXT编码修复",
            "description": "检测 TXT 电子书编码（含乱码反转恢复），修复为 UTF-8 并另存为新书",
            "revision": "0.1.1",
            "author": "黏菌",
            "publish_date": "2026-08-09",
        }

    @AsyncService.register_function
    def analyze(self, book_id: int) -> dict:
        """同步检测书籍 TXT 文件的编码，返回报告 + 修复后预览。

        :param book_id: Calibre 书籍 ID。
        :return dict: ``encoding`` / ``confidence`` / ``mojibake`` / ``garbage`` /
            ``sample``（原始可读性样本）/ ``preview``（修复后预览）/
            ``reasons``（检测依据列表）。
        :raises RuntimeError: 书籍不存在 / 无 TXT 格式 / 文件缺失。
        """
        txt_path = book_utils.get_book_file(self, book_id, "TXT")
        with open(txt_path, "rb") as f:
            data = f.read(ANALYZE_LIMIT)

        text, report = encoding_detect.decode_with_report(data)
        if os.path.getsize(txt_path) > ANALYZE_LIMIT:
            report["reasons"].append(
                "文件超过 2MB，本次检测基于前 2MB 采样（执行修复时按全量解码）")
        report["preview"] = text[:PREVIEW_CHARS]
        report["book_id"] = book_id
        return report

    @AsyncService.register_service
    def fix(self, book_id: int, user_id: int) -> None:
        """后台执行编码修复：解码 → UTF-8 无 BOM 写出 → 新书入库。

        :param book_id: Calibre 书籍 ID。
        :param user_id: 操作用户 ID（记录日志 / 创建 Item 记录）。
        """
        if not TxtEncodingFixerTool._fix_lock.acquire(blocking=False):
            # 正常情况下 AsyncService 对同一服务函数串行执行，此分支几乎不可达；
            # 一旦命中必须让用户可见：建一个失败任务供前端轮询，而不是静默跳过
            # 让用户拿着「任务已启动」的回执干等
            logging.warning(
                "[TxtEncodingFixerTool] Already running, rejecting fix for book_id=%d [uid:%d]",
                book_id, user_id,
            )
            reject_task_id = self.create_task(progress_data={"status": "failed", "book_id": book_id})
            TxtEncodingFixerTool._last_task_id = reject_task_id
            self.complete_task(reject_task_id, error_message=_("已有 TXT 编码修复任务正在执行，请稍后再试"))
            return

        # create_task 等全部放入 try：若中途抛异常，finally 仍会释放锁，
        # 避免锁永久泄漏导致工具不可用（需重启服务才能恢复）
        task_id = None
        error_message = None
        book_title = "Unknown"
        replacement_chars = 0
        work_dir = None

        try:
            task_id = self.create_task(progress_data={"status": "starting", "book_id": book_id})
            TxtEncodingFixerTool._last_task_id = task_id

            # 与 analyze 共用同一校验入口（错误消息一致，且多含普通文件/可读性检查）
            try:
                txt_path = book_utils.get_book_file(self, book_id, "TXT")
            except RuntimeError as err:
                error_message = str(err)
                self.update_task_progress(task_id, 0, {"status": "failed", "stage": "failed", "book_id": book_id})
                logging.error("[TxtEncodingFixerTool] Validate book_id=%d failed: %s", book_id, err)
                return

            books = self.api.calibre.get_data_as_dict([book_id])
            book_title = books[0].get("title", "Unknown") if books else "Unknown"

            self.update_task_progress(task_id, 10, {"status": "running", "stage": "reading", "book_id": book_id})

            with open(txt_path, "rb") as f:
                data = f.read()

            self.update_task_progress(task_id, 40, {"status": "running", "stage": "detecting", "book_id": book_id})

            text, report = encoding_detect.decode_with_report(data)
            replacement_chars = int(report.get("replacement_chars") or 0)
            if not text.strip():
                error_message = _("TXT 文件为空或仅含空白字符，无需修复")
                self.update_task_progress(task_id, 0, {"status": "failed", "stage": "failed", "book_id": book_id})
                logging.error("[TxtEncodingFixerTool] Empty text for book_id=%d [uid:%d]", book_id, user_id)
                return
            if report.get("irreversible"):
                error_message = _("乱码链路不可逆（字节级信息已毁），无法自动修复")
                self.update_task_progress(task_id, 0, {"status": "failed", "stage": "failed", "book_id": book_id})
                logging.error("[TxtEncodingFixerTool] Irreversible encoding chain for book_id=%d", book_id)
                return
            if report["unrecoverable"]:
                error_message = _("文件疑似多重误读乱码（反转循环），无法自动修复")
                self.update_task_progress(task_id, 0, {"status": "failed", "stage": "failed", "book_id": book_id})
                logging.error("[TxtEncodingFixerTool] Unrecoverable mojibake cycle for book_id=%d", book_id)
                return
            if report["garbage"]:
                error_message = _("文件疑似二进制或混用编码，无法安全修复（编码：%s）") % report["encoding"]
                self.update_task_progress(task_id, 0, {"status": "failed", "stage": "failed", "book_id": book_id})
                logging.error("[TxtEncodingFixerTool] Garbage content for book_id=%d: %s", book_id, report["encoding"])
                return

            self.update_task_progress(task_id, 70, {"status": "running", "stage": "saving", "book_id": book_id})
            del data  # 解码完成后原始字节不再需要，先释放（大文件内存峰值 ~2× 而非 3×）

            work_dir = self.get_work_dir(str(book_id))
            out_path = os.path.join(work_dir, "fixed_%d.txt" % int(time.time()))
            with open(out_path, "wb") as f:
                for i in range(0, len(text), WRITE_CHUNK_CHARS):
                    # UTF-8 无 BOM；分块编码写出，避免整本再复制一份 bytes
                    f.write(text[i:i + WRITE_CHUNK_CHARS].encode("utf-8"))

            new_book_id = book_utils.import_as_new_book(
                self, book_id, out_path, _("（编码修复版）"), user_id,
            )
            logging.info(
                "[TxtEncodingFixerTool] Fixed book_id=%d (%s) -> new book_id=%d [uid:%d]",
                book_id, report["encoding"], new_book_id, user_id,
            )

            if replacement_chars:
                self.add_msg(
                    user_id, "success",
                    _(u"书籍 [%s] TXT 编码修复完成！已生成新书（编码：%s），但输出含 %d 处无法还原的替换符，建议检查新书内容")
                    % (book_title, report["encoding"], replacement_chars),
                )
            else:
                self.add_msg(
                    user_id, "success",
                    _(u"书籍 [%s] TXT 编码修复成功！已生成新书（编码：%s）") % (book_title, report["encoding"]),
                )

        except Exception as err:
            error_message = str(err)
            self.add_msg(user_id, "danger", _(u"书籍 [%s] TXT 编码修复失败！") % book_title)
            logging.error("[TxtEncodingFixerTool] Unexpected error for book_id=%d: %s", book_id, err)
            logging.error(traceback.format_exc())
        finally:
            # 锁必须最先释放：complete_task / update_task_progress 走数据库可能抛异常，
            # 若它们在 release 之前抛出，锁将永久泄漏（工具卡死到重启）
            TxtEncodingFixerTool._fix_lock.release()
            if work_dir is not None:
                self.cleanup_work_dir(work_dir)
            # create_task 失败时 task_id 为 None，跳过任务收尾
            if task_id is not None:
                self.complete_task(task_id, error_message=error_message)
                if error_message is None:
                    self.update_task_progress(
                        task_id, 100,
                        {"status": "completed", "book_id": book_id,
                         "replacement_chars": replacement_chars},
                    )
