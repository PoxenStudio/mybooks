"""
格式合并工具

将两本书名相同但格式不同的书籍合并：把来源书籍的格式文件复制到目标书籍，
然后删除来源书籍。执行速度较快，不需要后台任务进度追踪。
"""
import logging

from webserver.i18n import _
from webserver.services import AsyncService
from webserver.toolbox.base_tool import BaseTool


class MergeFormatsTool(BaseTool):
    service_item_name = ""  # 不使用后台任务

    @staticmethod
    def info():
        return {
            "tool_id": "merge_formats_tool",
            "name": "格式合并",
            "description": "将两本书名相同但格式不同的书籍合并，把来源书的格式复制到目标书后删除来源书",
            "revision": "0.1.0",
            "author": "PoxenStudio",
            "publish_date": "2025-05-19",
        }

    @AsyncService.register_function
    def merge(self, source_book_id: int, target_book_id: int) -> dict:
        """合并 source 书籍的格式到 target 书籍，并删除 source 书籍。

        :param source_book_id: 来源书籍 ID（合并后删除）
        :param target_book_id: 目标书籍 ID（保留）
        :return: {"added_formats": [...], "deleted_book_id": int}
        :raises RuntimeError: 合并或删除失败时抛出
        """
        if source_book_id == target_book_id:
            raise RuntimeError(_("来源书籍和目标书籍不能相同"))

        added = self.merge_book_formats(source_book_id, target_book_id)

        if not added:
            raise RuntimeError(_("没有可合并的格式"))

        logging.info(
            "[MergeFormatsTool] Merged formats %s from book %d to %d; deleting source",
            added, source_book_id, target_book_id,
        )

        self.delete_book_by_id(source_book_id)

        return {
            "added_formats": added,
            "deleted_book_id": source_book_id,
        }
