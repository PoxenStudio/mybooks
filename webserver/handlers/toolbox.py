#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import os
import time
import tornado

from webserver.i18n import _
from webserver.toolbox.toolset import ToolSet
from webserver.handlers.base import BaseHandler, js, is_admin
from urllib.parse import urlparse
from webserver.toolbox.rare_book_downloader import RareBookDownloader
from webserver.toolbox.merge_formats_tool import MergeFormatsTool
from webserver.toolbox.review_cht_books_tool import ReviewTraditionalChineseTool
from webserver.toolbox.minify_pdf import MinifyPdfTool
from pathlib import Path


class AdminToolList(BaseHandler):
    @js
    @is_admin
    def get(self):
        ToolSet.collect_tools()
        tools = [t.to_dict() for t in ToolSet.all_tools()]
        return {"err": "ok", "tools": tools}


class AdminRareBookDownloader(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        url = (data.get("url") or "").strip()
        if not url:
            return {"err": "params.url.missing", "msg": _("请提供URL参数")}

        host = urlparse(url).hostname or ""
        if host != "hkust.edu.hk" and not host.endswith(".hkust.edu.hk"):
            return {"err": "params.url.unsupported", "msg": _("不支持的URL，仅支持 hkust.edu.hk 及其子域名")}

        RareBookDownloader().download(url, self.user_id())
        return {"err": "ok", "msg": _("古书下载任务已启动，右上角可以查看进度")}


class AdminMergeFormatsMerge(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        source_id = data.get("source_id")
        target_id = data.get("target_id")

        if not source_id or not target_id:
            return {"err": "params.missing", "msg": _("请提供来源书籍ID和目标书籍ID")}

        try:
            result = MergeFormatsTool().merge(int(source_id), int(target_id))
        except RuntimeError as err:
            return {"err": "merge.failed", "msg": str(err)}

        return {
            "err": "ok",
            "msg": _("合并成功，已添加格式：%s") % "、".join(result["added_formats"]),
            "added_formats": result["added_formats"],
            "deleted_book_id": result["deleted_book_id"],
        }


class AdminReviewChtBooks(BaseHandler):
    @js
    @is_admin
    def post(self):
        ReviewTraditionalChineseTool().review(self.user_id())
        return {"err": "ok", "msg": _("繁体中文检测任务已启动，右上角可以查看进度")}


class AdminMinifyPdfUpload(BaseHandler):
    @js
    @is_admin
    def post(self):
        if not self.request.files or 'file' not in self.request.files:
            return {"err": "params.missing", "msg": _("未上传文件")}

        file_meta = self.request.files['file'][0]
        ext = os.path.splitext(file_meta['filename'])[1]

        tool = MinifyPdfTool()
        work_dir = tool.get_work_dir("")
        sources_dir = os.path.join(work_dir, "sources")
        os.makedirs(sources_dir, exist_ok=True)

        filename = f"{int(time.time())}{ext}"
        filepath = os.path.join(sources_dir, filename)

        with open(filepath, 'wb+') as f:
            f.write(file_meta['body'])

        pdf_info = MinifyPdfTool.get_pdf_info(filepath)
        data = {"filename": filename}
        data.update(pdf_info)

        # data中包含的信息：
        # page_count: 页数
        # file_size: 文件大小
        # page_width: 页宽
        # page_height: 页高
        return {"err": "ok", "data": data}


class AdminMinifyPdfProcess(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        filename = data.get("filename")
        if not filename:
            return {"err": "params.missing", "msg": _("请提供文件名")}

        tool = MinifyPdfTool()
        if tool.is_running():
            return {"err": "task.running", "msg": _("已有PDF瘦身任务正在运行，请稍后再试")}

        work_dir = tool.get_work_dir("")
        input_pdf = os.path.join(work_dir, "sources", filename)

        if not os.path.exists(input_pdf):
            return {"err": "file.not_found", "msg": _("未找到上传的文件")}

        # params 为参数字典，支持以下字段（类型 / 含义 / 默认值）：
        # - max_width: int值，页面渲染时的最大宽度（像素）。默认800。
        # - bw: bool，是否将页面转换为二值（黑白）图像（使用 Otsu 阈值）。默认 False；bw 优先于 gray。
        # - gray: bool，是否将页面转换为灰度图像（L 模式）。默认 False。
        # - auto: bool，是否对比度自动校正（基于直方图）。默认 False。
        # - skip_pages: str，逗号分隔的页码（以 1 为起点），支持负数从末尾索引。指定的页不会应用 bw/gray/auto/max_brightness 等处理，但仍保留在输出中。
        # - drop_pages: str，逗号分隔的页码（以 1 为起点），支持负数，从输出中完全删除这些页。
        # - qualify: int，JPEG 重编码质量（1-100），用于控制压缩质量，默认 75。
        # - max_brightness: int 或 None，0-255 范围，配合 gray 使用，将亮度高于该值的像素设为白色以去除背景噪点。默认 None（不处理）。
        # 示例：{"max_width":800, "bw":True, "qualify":60, "drop_pages":"1,3", "skip_pages":"5"}
        tool.minify(input_pdf, data.get("params", {}), self.user_id())
        return {"err": "ok", "msg": _("PDF瘦身任务已启动")}


class AdminMinifyPdfProgress(BaseHandler):
    @js
    @is_admin
    def get(self):
        filename = self.get_argument("filename", "")
        if not filename:
            return {"err": "params.missing", "msg": _("请提供文件名")}

        tool = MinifyPdfTool()
        work_dir = tool.get_work_dir("")
        input_pdf = os.path.join(work_dir, "sources", filename)

        task_info = tool.get_task_info(input_pdf)
        if task_info:
            if task_info.get("status") == "running":
                return {
                    "err": "ok",
                    "data": {
                        "progress": task_info.get("progress", 0),
                        "status": "running"
                    }
                }
            elif task_info.get("status") == "completed":
                return {
                    "err": "ok",
                    "msg": _("文件处理完成"),
                    "data": {
                        "progress": 100,
                        "status": "completed",
                        "download_url": f"/api/toolbox/minify_pdf/download?filename={filename}"
                    }
                }
            elif task_info.get("status") == "error":
                return {"err": "task.failed", "msg": task_info.get("message", _("处理失败"))}

        stem = Path(input_pdf).stem
        processed_pdf = os.path.join(work_dir, "processed", f"{stem}_minify.pdf")

        if os.path.exists(processed_pdf):
            return {
                "err": "ok",
                "msg": _("文件处理完成"),
                "data": {
                    "progress": 100,
                    "status": "completed",
                    "download_url": f"/api/toolbox/minify_pdf/download?filename={filename}"
                }
            }

        return {"err": "task.interrupted", "msg": _("任务已中断")}


class AdminMinifyPdfDownload(BaseHandler):
    @is_admin
    def get(self):
        from webserver.toolbox.minify_pdf import MinifyPdfTool
        import os
        from pathlib import Path

        filename = self.get_argument("filename", "")
        if not filename:
            self.set_status(400)
            self.write("Missing filename")
            return

        tool = MinifyPdfTool()
        work_dir = tool.get_work_dir("")
        stem = Path(filename).stem
        processed_pdf = os.path.join(work_dir, "processed", f"{stem}_minify.pdf")

        if not os.path.exists(processed_pdf):
            self.set_status(404)
            self.write("File not found")
            return

        self.set_header('Content-Type', 'application/pdf')
        self.set_header('Content-Disposition', f'attachment; filename="{stem}_minify.pdf"')
        with open(processed_pdf, 'rb') as f:
            self.write(f.read())


def routes():
    return [
        (r"/api/toolbox/list", AdminToolList),
        (r"/api/toolbox/rare_book_downloader", AdminRareBookDownloader),
        (r"/api/toolbox/merge_formats/merge", AdminMergeFormatsMerge),
        (r"/api/toolbox/review_cht_books", AdminReviewChtBooks),
        (r"/api/toolbox/minify_pdf/upload", AdminMinifyPdfUpload),
        (r"/api/toolbox/minify_pdf/process", AdminMinifyPdfProcess),
        (r"/api/toolbox/minify_pdf/progress", AdminMinifyPdfProgress),
        (r"/api/toolbox/minify_pdf/download", AdminMinifyPdfDownload),
    ]
