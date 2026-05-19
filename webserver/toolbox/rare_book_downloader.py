"""
古书下载导入工具
"""
import hashlib
import logging
import os
from typing import Callable, Optional, List

from webserver.i18n import _
from webserver.models import Item
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask


DOWNLOAD_DIR = "/data/temp"


class RareBookDownloader(AsyncService):
    @staticmethod
    def info():
        return {
            "tool_id": "rare_book_downloader",
            "name": "古书下载器",
            "description": "从书录古书的图书馆站点下载资源并导入到书库",
            "revision": "0.1.0",
            "author": "PoxenStudio",
            "publish_date": "2025-05-18"
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
        :param callback: 进度回调，参数为 0-100 的整数进度值
        :return: {"title": str, "author": str, "pdf_path": str}；异步模式下返回 None
        """
        task = BackgroundService().update_task(
            service_type=BackgroundTask.SERVICE_TYPE_OTHER,
            service_item=_("古书下载"),
            progress=0,
            progress_data={"url": url},
        )
        task_id = task.id

        def _progress_callback(progress: int) -> None:
            BackgroundService().update_progress(
                task_id=task_id,
                progress=progress,
                progress_data={"url": url},
            )
            if callback:
                callback(progress)

        try:
            downloader = self._get_downloader(url)
            meta = downloader.check_valid_url()

            url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
            output_dir = os.path.join(DOWNLOAD_DIR, url_hash)
            os.makedirs(output_dir, exist_ok=True)

            logging.info("[RareBookDownloader] start download: %s -> %s", url, output_dir)
            pdf_path = downloader.download(output_dir, callback=_progress_callback)

            book_id = self._import_pdf(user_id, pdf_path, meta.get("title", ""), meta.get("authors", []))
            BackgroundService().complete_task(task_id)

            try:
                os.removedirs(output_dir)
            except Exception:
                logging.error("[RareBookDownloader]Failed to remove output dir.")

            return {
                "title": meta.get("title", ""),
                "authors": meta.get("authors", []),
                "pdf_path": pdf_path,
                "book_id": book_id,
            }
        except Exception as err:
            logging.error("[RareBookDownloader] download failed: %s", err)
            BackgroundService().complete_task(task_id, error_message=str(err))
            raise

    def _import_pdf(self, user_id, pdf_path: str, title: str, authors: List[str]) -> int:
        """将下载好的 PDF 导入 Calibre，成功后删除源文件，失败则保留。"""
        from calibre.ebooks.metadata.meta import get_metadata
        from calibre.ebooks.metadata.book.base import Metadata
        from webserver import utils

        fmt = pdf_path.split(".")[-1].lower()
        if fmt not in ['epub', 'pdf', 'azw3']:
            raise RuntimeError("Unsupport file format!")

        try:
            with open(pdf_path, "rb") as stream:
                mi = get_metadata(stream, stream_type=fmt, use_libprs_metadata=True)
                mi.title = utils.super_strip(mi.title)
                mi.authors = [utils.super_strip(s) for s in authors]
        except Exception as e:
            mi = Metadata(title, authors)
            logging.error("[IMPORT] Error reading metadata from %s: %s", pdf_path, e)

        mi.title_sort = utils.get_title_sort(title)

        logging.info("[RareBookDownloader] importing PDF: %s", pdf_path)
        try:
            book_id = self.db.import_book(mi, [pdf_path])
        except Exception as err:
            logging.error("[RareBookDownloader] %s: %s", _("导入PDF失败，保留原文件"), err)
            raise

        if book_id is None:
            logging.error("[RareBookDownloader] import_book returned None for %s", pdf_path)
            raise RuntimeError(_("导入PDF失败，Calibre未返回书籍ID"))

        try:
            item = Item()
            item.book_id = book_id
            item.collector_id = user_id  # system/admin user
            item.save()
        except Exception as err:
            logging.error("[RareBookDownloader] failed to create Item record: %s", err)

        try:
            os.remove(pdf_path)
            logging.info("[RareBookDownloader] deleted source PDF: %s", pdf_path)
        except Exception as err:
            logging.warning("[RareBookDownloader] failed to delete source PDF %s: %s", pdf_path, err)

        return book_id
