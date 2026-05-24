"""
古书下载导入工具
"""
import logging
import os
from typing import Callable, Optional

from webserver.services import AsyncService
from webserver.toolbox.base_tool import BaseTool


class RareBookDownloader(BaseTool):
    # 后台任务面板中显示的任务名称
    service_item_name = "古书下载"

    @staticmethod
    def info():
        return {
            "tool_id": "rare_book_downloader",
            "name": "古书下载器",
            "description": "从收录古书的图书馆站点下载资源并导入到书库",
            "revision": "0.1.0",
            "author": "PoxenStudio",
            "publish_date": "2025-05-18",
        }

    @staticmethod
    def _get_downloader(url: str):
        from webserver.toolbox.downloader.usthk_downloader import UsthkDownloader
        if UsthkDownloader.is_supported_url(url):
            return UsthkDownloader(url)
        raise ValueError(f"不支持的URL: {url}")

    @AsyncService.register_service
    def download(self, url: str, user_id, callback: Optional[Callable[[int], None]] = None) -> Optional[dict]:
        """异步下载古书并转换为 PDF。

        :param url:      古书页面 URL
        :param user_id:  入库操作关联的用户 ID
        :param callback: 进度回调，参数为 0-100 的整数进度值
        :return: {"title": str, "authors": list, "pdf_path": str, "book_id": int}；
                 异步模式下返回 None
        """
        task_id = self.create_task(progress_data={"url": url})
        progress_callback = self.make_progress_callback(
            task_id,
            progress_data_factory=lambda p: {"url": url},
            outer_callback=callback,
        )

        try:
            downloader = self._get_downloader(url)
            meta = downloader.check_valid_url()

            work_dir = self.get_work_dir(url)
            logging.info("[RareBookDownloader] start download: %s -> %s", url, work_dir)
            os.makedirs(work_dir, exist_ok=True)

            pdf_path = downloader.download(work_dir, callback=progress_callback)

            book_id = self.import_file(
                user_id,
                pdf_path,
                title=meta.get("title", ""),
                authors=meta.get("authors", []),
            )

            self.complete_task(task_id)
            self.cleanup_work_dir(work_dir)

            return {
                "title": meta.get("title", ""),
                "authors": meta.get("authors", []),
                "pdf_path": pdf_path,
                "book_id": book_id,
            }
        except Exception as err:
            logging.error("[RareBookDownloader] download failed: %s", err)
            self.complete_task(task_id, error_message=str(err))
            raise
