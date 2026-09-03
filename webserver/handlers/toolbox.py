#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import logging
import os
import re
import tempfile
import time
import mimetypes
import tornado
from pathlib import Path
from urllib.parse import urlparse

from webserver.i18n import _
from webserver.loader import get_settings
from webserver.toolbox.toolset import ToolSet
from webserver.toolbox import toolbox_manager
from webserver.services.toolbox_store import ToolboxStoreClient, ToolboxStoreError, get_cached_index, find_in_index
from webserver.handlers.base import BaseHandler, js, is_admin
from webserver.toolbox.rare_book_downloader import RareBookDownloader
from webserver.toolbox.merge_formats_tool import MergeFormatsTool
from webserver.toolbox.review_book_language_tool import ReviewBookLanguageTool
from webserver.toolbox.minify_pdf import MinifyPdfTool
from webserver.toolbox.formats_pruning import FormatsPruningTool
from webserver.toolbox.epub_fixer import EpubFixerTool
from webserver.toolbox.epub_split import EpubSplitTool
from webserver.toolbox.author_clean_tool import AuthorCleanTool
from webserver.toolbox.mimo_tts import MimoTTSTool
from webserver.toolbox.text_replace import TextReplaceTool
from webserver.toolbox.txt_encoding_fixer import TxtEncodingFixerTool
from webserver.toolbox.chinese_converter_tool import ChineseConverterTool, DIRECTIONS
from webserver.toolbox.bookbarn_acceptor_tool import BookBarnAcceptorTool
from webserver.toolbox.epub_beautify import EpubBeautifyTool
from webserver.toolbox.utils.styles import TOC_STYLES as EB_TOC_STYLES, list_presets as eb_list_presets
from webserver.services.background_service import BackgroundTask

CONF = get_settings()


class AdminToolList(BaseHandler):
    @js
    @is_admin
    def get(self):
        # 注意：不在这里调用 ToolSet.collect_tools() —— 工具的注册（含外部工具、被更新覆盖
        # 的内置工具）只在进程启动时 toolbox_manager.load_all() 里发生一次（"重启生效"模型，
        # 见 document/Toolbox_Dynamic_Design.md 3.3.1 节）；每次请求都重新 collect_tools()
        # 会用仓库自带的 info() 把已加载的覆盖版本元数据冲掉。
        #
        # include_disabled=1：仅供 /admin/toolbox 管理页使用（同样要求 is_admin）——3.3.1
        # 节要求"禁用立即从可见列表消失"针对的是工具启动入口（普通工具墙/工具承载页），
        # 但管理页面需要能看到被禁用的工具才能把它重新启用，否则禁用会变成有去无回的单向操作。
        include_disabled = self.get_argument("include_disabled", "") == "1"
        tools = []
        for t in ToolSet.all_tools():
            state = toolbox_manager.tool_state(t.id)
            if state is None:
                # 外部工具已被卸载，但进程还没重启、ToolSet 里的静态注册还没清掉：
                # 直接跳过，不展示（3.3.1 节要求卸载后立即从列表消失）
                continue
            if state["type"] == "tool" and state["status"] == "disabled" and not include_disabled:
                # 禁用的外部工具立即从列表消失，无需重启（3.3.1 节）
                continue
            data = t.to_dict()
            data.update(state)
            tools.append(data)
        return {
            "err": "ok",
            "tools": tools,
            "dev_mode": bool(CONF.get("ENABLE_TOOLBOX_DEV_MODE", False)),
            "store_enabled": ToolboxStoreClient.enabled(),
        }


def _save_upload_to_tmpfile(file_meta) -> str:
    fd, path = tempfile.mkstemp(prefix="mybooks_tool_upload_", suffix=".zip")
    with os.fdopen(fd, "wb") as f:
        f.write(file_meta["body"])
    return path


class AdminToolInstallUpload(BaseHandler):
    """开发者模式：本地上传 zip 安装一个全新的外部工具。见 3.5 节。"""

    @js
    @is_admin
    def post(self):
        if not CONF.get("ENABLE_TOOLBOX_DEV_MODE"):
            self.set_status(403)
            return {"err": "dev_mode.disabled", "msg": _("开发者模式未开启，请先在系统设置中开启")}
        if not self.request.files or "file" not in self.request.files:
            return {"err": "params.missing", "msg": _("未上传文件")}

        tmp_path = _save_upload_to_tmpfile(self.request.files["file"][0])
        try:
            record = toolbox_manager.install_from_zip(
                tmp_path, is_update=False, installed_by=self.user_id(),
                source=toolbox_manager.InstalledTool.SOURCE_DEV,
            )
        except toolbox_manager.ToolValidationError as err:
            return {"err": "tool.invalid", "msg": str(err)}
        except toolbox_manager.ToolStateError as err:
            return {"err": "tool.state", "msg": str(err)}
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        return {"err": "ok", "msg": _("已安装，重启后生效"), "data": record.to_dict()}


class AdminToolUpdateUpload(BaseHandler):
    """开发者模式：本地上传 zip 更新一个已安装的工具（builtin 或 tool 均可）。见 3.5 节。"""

    @js
    @is_admin
    def post(self, tool_id):
        if not CONF.get("ENABLE_TOOLBOX_DEV_MODE"):
            self.set_status(403)
            return {"err": "dev_mode.disabled", "msg": _("开发者模式未开启，请先在系统设置中开启")}
        if not self.request.files or "file" not in self.request.files:
            return {"err": "params.missing", "msg": _("未上传文件")}

        tmp_path = _save_upload_to_tmpfile(self.request.files["file"][0])
        try:
            record = toolbox_manager.install_from_zip(
                tmp_path, is_update=True, expected_tool_id=tool_id, installed_by=self.user_id(),
                source=toolbox_manager.InstalledTool.SOURCE_DEV,
            )
        except toolbox_manager.ToolValidationError as err:
            return {"err": "tool.invalid", "msg": str(err)}
        except toolbox_manager.ToolStateError as err:
            return {"err": "tool.state", "msg": str(err)}
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        return {"err": "ok", "msg": _("已更新，重启后生效"), "data": record.to_dict()}


class AdminToolEnable(BaseHandler):
    @js
    @is_admin
    def post(self, tool_id):
        try:
            record = toolbox_manager.enable_tool(tool_id)
        except toolbox_manager.ToolStateError as err:
            return {"err": "tool.not_found", "msg": str(err)}
        except toolbox_manager.ToolPermissionError as err:
            self.set_status(403)
            return {"err": "tool.permission", "msg": str(err)}
        return {"err": "ok", "msg": _("已启用"), "data": record.to_dict()}


class AdminToolDisable(BaseHandler):
    @js
    @is_admin
    def post(self, tool_id):
        try:
            record = toolbox_manager.disable_tool(tool_id)
        except toolbox_manager.ToolStateError as err:
            return {"err": "tool.not_found", "msg": str(err)}
        except toolbox_manager.ToolPermissionError as err:
            self.set_status(403)
            return {"err": "tool.permission", "msg": str(err)}
        return {"err": "ok", "msg": _("已禁用"), "data": record.to_dict()}


class AdminToolUninstall(BaseHandler):
    @js
    @is_admin
    def delete(self, tool_id):
        try:
            toolbox_manager.uninstall_tool(tool_id)
        except toolbox_manager.ToolStateError as err:
            return {"err": "tool.not_found", "msg": str(err)}
        except toolbox_manager.ToolPermissionError as err:
            self.set_status(403)
            return {"err": "tool.permission", "msg": str(err)}
        return {"err": "ok", "msg": _("已卸载，重启后彻底生效")}


class AdminToolStoreIndex(BaseHandler):
    """商店可安装工具列表（3.4 节 `GET toolbox/index` 的内部代理，带 TTL 缓存）。

    `ENABLE_TOOLBOX_STORE=False`（默认）时 `get_cached_index()` 恒为空列表，接口照常返回
    `200`，前端商店面板展示"暂无可安装工具"而不是报错（3.4.1 节）。
    """

    @js
    @is_admin
    def get(self):
        force = self.get_argument("refresh", "") == "1"
        tools = []
        for entry in get_cached_index(force=force):
            tool_id = entry.get("tool_id")
            record = toolbox_manager.InstalledTool.get(tool_id) if tool_id else None
            data = dict(entry)
            data["installed"] = record is not None
            data["installed_revision"] = record.installed_revision if record else ""
            tools.append(data)
        return {"err": "ok", "enabled": ToolboxStoreClient.enabled(), "tools": tools}


class AdminToolStoreInstall(BaseHandler):
    """从商店安装/更新一个工具（3.4 节）。目标 tool_id 已安装时按更新语义处理，否则按安装。

    对应架构图里的 `POST /api/toolbox/{tool_id}/install`；`revision` 可选，缺省用商店索引里
    该工具的 `latest_revision`。下载后**必须**校验 `sha256`（3.4 节），不通过拒绝安装。
    """

    @js
    @is_admin
    def post(self, tool_id):
        if not ToolboxStoreClient.enabled():
            self.set_status(403)
            return {"err": "store.disabled", "msg": _("工具商店未开启")}

        entry = find_in_index(tool_id)
        if not entry:
            return {"err": "store.not_found", "msg": _("商店中未找到工具「%s」") % tool_id}

        # 索引目前只暴露 latest_revision 对应的下载地址（3.4 节）；如果未来商店支持安装/回退
        # 到历史版本，需要 index 结构先带上按版本分组的 download_url，这里再改为读请求体里的
        # revision 去查对应条目。
        download_url = entry.get("download_url")
        sha256 = entry.get("sha256")
        if not download_url:
            return {"err": "store.invalid", "msg": _("商店索引缺少下载地址")}

        is_update = toolbox_manager.InstalledTool.get(tool_id) is not None

        try:
            zip_path = ToolboxStoreClient().download(download_url, sha256)
        except ToolboxStoreError as err:
            return {"err": "store.download_failed", "msg": str(err)}

        try:
            record = toolbox_manager.install_from_zip(
                zip_path, is_update=is_update, expected_tool_id=tool_id if is_update else None,
                installed_by=self.user_id(), source=toolbox_manager.InstalledTool.SOURCE_STORE,
            )
        except toolbox_manager.ToolValidationError as err:
            return {"err": "tool.invalid", "msg": str(err)}
        except toolbox_manager.ToolStateError as err:
            return {"err": "tool.state", "msg": str(err)}
        finally:
            if os.path.exists(zip_path):
                os.remove(zip_path)

        msg = _("已更新，重启后生效") if is_update else _("已安装，重启后生效")
        return {"err": "ok", "msg": msg, "data": record.to_dict()}


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


class AdminReviewBookLanguage(BaseHandler):
    @js
    @is_admin
    def post(self):
        ReviewBookLanguageTool().review(self.user_id())
        return {"err": "ok", "msg": _("书名语言检测任务已启动，右上角可以查看进度")}


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


class AdminFormatsPruningStart(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        delete = data.get("delete")
        if not isinstance(delete, list) or not delete:
            return {"err": "params.missing", "msg": _("请至少选择一种需要删除的格式")}

        valid_keys = set(FormatsPruningTool.FORMAT_GROUPS.keys())
        delete_keys = [k for k in delete if k in valid_keys]
        if not delete_keys:
            return {"err": "params.invalid", "msg": _("无效的格式选项")}

        if len(set(delete_keys)) >= len(valid_keys):
            return {"err": "params.invalid", "msg": _("不能选择全部格式，请至少取消勾选一项以便保留")}

        tool = FormatsPruningTool()
        if tool.is_running():
            return {"err": "task.running", "msg": _("已有格式精简任务正在运行，请稍后再试")}

        tool.prune(delete_keys, self.user_id())
        return {"err": "ok", "msg": _("格式精简任务已启动，右上角可以查看进度")}


class AdminFormatsPruningProgress(BaseHandler):
    @js
    @is_admin
    def get(self):
        task = FormatsPruningTool.get_last_task()
        if not task:
            return {"err": "task.not_found", "msg": _("尚未启动格式精简任务")}

        progress_data = task.get("progress_data") or {}
        result = {
            "status": task.get("status"),
            "progress": task.get("progress", 0),
            "total": progress_data.get("total", 0),
            "checked": progress_data.get("checked", 0),
            "pruned_books": progress_data.get("pruned_books", 0),
            "pruned_formats": progress_data.get("pruned_formats", 0),
        }

        if task.get("status") == BackgroundTask.STATUS_FAILED:
            return {"err": "task.failed", "msg": task.get("error_message") or _("处理失败"), "data": result}

        if task.get("status") == BackgroundTask.STATUS_COMPLETED:
            return {"err": "ok", "msg": _("格式精简任务已完成"), "data": result}

        return {"err": "ok", "data": result}


class AdminEpubFixerFix(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        book_id = data.get("book_id")
        backup = bool(data.get("backup", False))

        if not book_id:
            return {"err": "params.missing", "msg": _("请提供书籍ID")}

        tool = EpubFixerTool()
        if tool.is_running():
            return {"err": "task.running", "msg": _("已有 EPUB 修复任务正在执行，请稍后再试")}

        tool.fix(int(book_id), backup, self.user_id())
        return {"err": "ok", "msg": _("EPUB修复任务已启动,不要重复执行,注意查看消息通知中的处理结果")}


class AdminEpubSplitChapters(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        book_id = data.get("book_id")
        if not book_id:
            return {"err": "params.missing", "msg": _("请提供书籍ID")}

        try:
            result = EpubSplitTool().list_chapters(int(book_id))
        except RuntimeError as err:
            return {"err": "epub_split.failed", "msg": str(err)}

        return {"err": "ok", "data": result}


class AdminEpubSplitGenerate(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        book_id = data.get("book_id")
        linenums = data.get("chapters")
        use_first_chapter_cover = bool(data.get("use_first_chapter_cover", False))

        if not book_id:
            return {"err": "params.missing", "msg": _("请提供书籍ID")}
        if not isinstance(linenums, list) or not linenums:
            return {"err": "params.missing", "msg": _("请至少选择一个章节")}

        try:
            result = EpubSplitTool().split(int(book_id), linenums, use_first_chapter_cover, self.user_id())
        except RuntimeError as err:
            return {"err": "epub_split.failed", "msg": str(err)}

        return {"err": "ok", "msg": _("新书生成成功"), "data": result}


class AdminAuthorClean(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        action = (data.get("action") or "").strip()
        author_name = (data.get("author_name") or "").strip()
        new_author_name = (data.get("new_author_name") or "").strip()

        if not author_name:
            return {"err": "params.author_name.missing", "msg": _("请提供现有作者名称")}

        if action == "clean":
            AuthorCleanTool().clean(author_name, self.user_id())
            return {"err": "ok", "msg": _("作者清理任务已启动，右上角可以查看进度")}
        elif action == "replace":
            if not new_author_name:
                return {"err": "params.new_author_name.missing", "msg": _("请提供新的作者名称")}
            if not AuthorCleanTool.validate_new_author_name(new_author_name):
                return {
                    "err": "params.new_author_name.invalid",
                    "msg": _("新作者名称仅允许使用字母、数字、“.”和“·”，不能包含空格、引号等其他符号"),
                }
            AuthorCleanTool().replace(author_name, new_author_name, self.user_id())
            return {"err": "ok", "msg": _("作者替换任务已启动，右上角可以查看进度")}
        else:
            return {"err": "params.action.invalid", "msg": _("无效的操作类型")}


class AdminMimoTTSConvert(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        book_id = data.get("book_id")
        api_key = (data.get("api_key") or "").strip()
        voice_desc = (data.get("voice_desc") or "").strip()
        api_url = (data.get("api_url") or "").strip()
        model_name = (data.get("model_name") or "").strip()
        api_type = (data.get("api_type") or "chat_completions").strip()
        voice_name = (data.get("voice_name") or "").strip()
        auth_type = (data.get("auth_type") or "api-key").strip()
        clone_voice = (data.get("clone_voice") or "").strip()

        if not book_id:
            return {"err": "params.missing", "msg": _("请提供书籍ID")}
        if not api_key:
            return {"err": "params.missing", "msg": _("请提供 API Key")}
        if not api_url:
            if api_type == "custom":
                return {"err": "params.missing", "msg": _("自定义类型请填写 API URL")}
            api_url = "https://api.openai.com/v1/audio/speech" if api_type == "audio_speech" else "https://api.xiaomimimo.com/v1/chat/completions"
        if not model_name:
            if api_type == "custom":
                return {"err": "params.missing", "msg": _("自定义类型请填写模型名称")}
            if api_type == "audio_speech":
                model_name = "tts-1"
            else:
                model_name = "mimo-v2.5-tts"
        if api_type == "chat_completions":
            model_name = "mimo-v2.5-tts"
        if clone_voice:
            if api_type != "chat_completions":
                return {"err": "params.invalid", "msg": _("音色克隆仅支持 MiMo TTS 类型 API")}
            if not MimoTTSTool().get_clone_voice_path(clone_voice):
                return {"err": "clone.not_found", "msg": _("克隆音色「%s」不存在，请重新上传") % clone_voice}
            model_name = "mimo-v2.5-tts-voiceclone"
        if api_type == "chat_completions" and not voice_desc:
            voice_desc = "自然平和的语调，语速适中，咬字清晰"
        if api_type == "audio_speech" and not voice_name:
            voice_name = "alloy"

        tool = MimoTTSTool()
        if tool.is_running():
            return {"err": "task.running", "msg": _("已有 TTS 转换任务正在运行，请稍后再试")}

        # audio_speech 模式下 voice_desc 无意义，传空字符串避免混淆
        effective_voice_desc = voice_desc if api_type in ("chat_completions", "custom") else ""
        tool.convert(int(book_id), api_key, effective_voice_desc, self.user_id(),
                     api_url, model_name, api_type, voice_name, auth_type,
                     clone_voice)
        return {"err": "ok", "msg": _("TTS 转换任务已启动，右上角可以查看进度")}


class AdminMimoTTSConfig(BaseHandler):
    @js
    @is_admin
    def get(self):
        config = MimoTTSTool().load_api_config()
        if config:
            return {"err": "ok", "config": config}
        return {"err": "ok", "config": None}

    @js
    @is_admin
    def delete(self):
        MimoTTSTool().clear_api_config()
        return {"err": "ok", "msg": _("已清除已保存的配置")}


class AdminMimoTTSProgress(BaseHandler):
    @js
    @is_admin
    def get(self):
        task = MimoTTSTool.get_last_task()
        if not task:
            return {"err": "task.not_found", "msg": _("尚未启动 TTS 转换任务")}

        progress_data = task.get("progress_data") or {}
        result = {
            "status": task.get("status"),
            "progress": task.get("progress", 0),
            "book_id": progress_data.get("book_id", 0),
            "stage": progress_data.get("stage", ""),
            "chapter": progress_data.get("chapter", 0),
            "total": progress_data.get("total", 0),
            "chapter_title": progress_data.get("chapter_title", ""),
        }

        if task.get("status") == BackgroundTask.STATUS_FAILED:
            return {"err": "task.failed", "msg": task.get("error_message") or _("处理失败"), "data": result}

        if task.get("status") == BackgroundTask.STATUS_COMPLETED:
            return {"err": "ok", "msg": _("TTS 转换任务已完成"), "data": result}

        return {"err": "ok", "data": result}


class AdminMimoTTSTest(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        api_key = (data.get("api_key") or "").strip()
        voice_desc = (data.get("voice_desc") or "").strip()
        api_url = (data.get("api_url") or "").strip()
        model_name = (data.get("model_name") or "").strip()
        api_type = (data.get("api_type") or "chat_completions").strip()
        voice_name = (data.get("voice_name") or "").strip()
        auth_type = (data.get("auth_type") or "api-key").strip()
        clone_voice = (data.get("clone_voice") or "").strip()

        if not api_key:
            return {"err": "params.missing", "msg": _("请提供 API Key")}
        if not api_url:
            return {"err": "params.missing", "msg": _("请填写 API URL")}
        if not model_name:
            return {"err": "params.missing", "msg": _("请填写模型名称")}
        if api_type == "chat_completions":
            model_name = "mimo-v2.5-tts"
        if clone_voice:
            if not MimoTTSTool().get_clone_voice_path(clone_voice):
                return {"err": "clone.not_found", "msg": _("克隆音色「%s」不存在，请重新上传") % clone_voice}
            model_name = "mimo-v2.5-tts-voiceclone"
        if api_type == "chat_completions" and not voice_desc:
            voice_desc = "自然平和的语调，语速适中，咬字清晰"
        if api_type == "audio_speech" and not voice_name:
            voice_name = "alloy"

        ok, err_msg = MimoTTSTool().test_connection(
            api_key, voice_desc, api_url, model_name, api_type, voice_name, auth_type,
            clone_voice)
        if ok:
            return {"err": "ok", "msg": _("连接成功，配置已保存")}
        return {"err": "test.failed", "msg": _("连接失败：%s") % err_msg}


class AdminMimoTTSCloneUpload(BaseHandler):
    @js
    @is_admin
    def post(self):
        if not self.request.files or 'file' not in self.request.files:
            return {"err": "params.missing", "msg": _("未上传文件")}

        file_meta = self.request.files['file'][0]
        voice_name = (self.get_body_argument("voice_name", "") or "").strip()
        ext = os.path.splitext(file_meta['filename'])[1].lower()

        tool = MimoTTSTool()
        try:
            name = tool.save_clone_voice(voice_name, ext, file_meta['body'])
        except ValueError as err:
            return {"err": "params.invalid", "msg": str(err)}

        return {"err": "ok", "msg": _("克隆音色「%s」上传成功") % name, "data": {"name": name}}


class AdminMimoTTSCloneList(BaseHandler):
    @js
    @is_admin
    def get(self):
        clones = MimoTTSTool().list_clone_voices()
        return {"err": "ok", "clones": clones}


class AdminMimoTTSCloneDelete(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        voice_name = (data.get("voice_name") or "").strip()
        if not voice_name:
            return {"err": "params.missing", "msg": _("请提供克隆音色名称")}

        if MimoTTSTool().delete_clone_voice(voice_name):
            return {"err": "ok", "msg": _("克隆音色「%s」已删除") % voice_name}
        return {"err": "clone.not_found", "msg": _("克隆音色「%s」不存在") % voice_name}


class AdminMimoTTSCloneAudio(BaseHandler):
    @is_admin
    def get(self):
        voice_name = self.get_argument("voice_name", "").strip()
        path = MimoTTSTool().get_clone_voice_path(voice_name)
        if not path:
            self.set_status(404)
            self.write("Clone voice not found")
            return

        mime = mimetypes.guess_type(path)[0] or "audio/wav"
        self.set_header("Content-Type", mime)
        self.set_header("Cache-Control", "no-store")
        with open(path, "rb") as f:
            self.write(f.read())


class AdminMimoTTSPromptList(BaseHandler):
    @js
    @is_admin
    def get(self):
        prompts = MimoTTSTool().list_voice_prompts()
        return {"err": "ok", "prompts": prompts}


class AdminMimoTTSPromptSave(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        name = (data.get("name") or "").strip()
        desc = (data.get("desc") or "").strip()
        if not name or not desc:
            return {"err": "params.missing", "msg": _("请填写提示词名称和内容")}

        try:
            saved = MimoTTSTool().save_voice_prompt(name, desc)
        except ValueError as err:
            return {"err": "params.invalid", "msg": str(err)}
        return {"err": "ok", "msg": _("提示词「%s」已保存") % saved, "data": {"name": saved}}


class AdminMimoTTSPromptDelete(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        name = (data.get("name") or "").strip()
        if not name:
            return {"err": "params.missing", "msg": _("请提供提示词名称")}

        if MimoTTSTool().delete_voice_prompt(name):
            return {"err": "ok", "msg": _("提示词「%s」已删除") % name}
        return {"err": "prompt.not_found", "msg": _("提示词「%s」不存在") % name}


class AdminBookBarnAcceptorStatus(BaseHandler):
    @js
    @is_admin
    def get(self):
        return {"err": "ok", "data": BookBarnAcceptorTool().get_status()}


class AdminBookBarnAcceptorToggle(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        enabled = bool(data.get("enabled", False))

        result = BookBarnAcceptorTool().set_receiving_books(enabled)
        if result.get("err") != "ok":
            return result

        return {"err": "ok", "msg": result.get("msg"), "data": BookBarnAcceptorTool().get_status()}


class AdminBookBarnAcceptorApplyToken(BaseHandler):
    @js
    @is_admin
    def post(self):
        try:
            token = BookBarnAcceptorTool().apply_token(self.get_os())
        except Exception as err:
            return {"err": "params.error", "msg": _("Token申请失败: %s") % str(err)}
        return {"err": "ok", "msg": _("Token申请成功"), "token": token}


class AdminBookBarnAcceptorSetCollectionHour(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        hour = data.get("hour")

        try:
            hour = int(hour)
        except (TypeError, ValueError):
            return {"err": "params.missing", "msg": _("未提供有效的小时数")}

        try:
            result = BookBarnAcceptorTool().set_collection_hour(hour)
        except ValueError:
            return {"err": "params.invalid", "msg": _("小时数应为0-23之间的整数")}

        if result.get("err") != "ok":
            return result

        return {"err": "ok", "msg": result.get("msg"), "data": BookBarnAcceptorTool().get_status()}


class AdminChineseConverterConvert(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        book_id = data.get("book_id")
        direction = (data.get("direction") or "t2s").strip()
        mode = (data.get("mode") or "book").strip()
        convert_title = bool(data.get("convert_title", True))
        use_a5 = bool(data.get("use_a5", False))
        backup = bool(data.get("backup", False))

        if not book_id:
            return {"err": "params.missing", "msg": _("请提供书籍ID")}
        if direction not in DIRECTIONS:
            return {"err": "params.direction.invalid", "msg": _("不支持的转换方向")}
        if mode not in ("book", "replace"):
            return {"err": "params.mode.invalid", "msg": _("无效的输出方式")}

        tool = ChineseConverterTool()
        if tool.is_running():
            return {"err": "task.running", "msg": _("已有繁简转换任务正在运行，请稍后再试")}

        tool.convert(int(book_id), direction, mode, use_a5, convert_title, backup, self.user_id())
        return {"err": "ok", "msg": _("繁简转换任务已启动，右上角可以查看进度")}


class AdminChineseConverterProgress(BaseHandler):
    @js
    @is_admin
    def get(self):
        task = ChineseConverterTool.get_last_task()
        if not task:
            return {"err": "task.not_found", "msg": _("尚未启动繁简转换任务")}

        progress_data = task.get("progress_data") or {}
        result = {
            "status": task.get("status"),
            "progress": task.get("progress", 0),
            "book_id": progress_data.get("book_id", 0),
            "new_book_id": progress_data.get("new_book_id", 0),
            "direction": progress_data.get("direction", ""),
            "stage": progress_data.get("stage", ""),
        }

        if task.get("status") == BackgroundTask.STATUS_FAILED:
            return {"err": "task.failed", "msg": task.get("error_message") or _("处理失败"), "data": result}

        if task.get("status") == BackgroundTask.STATUS_COMPLETED:
            return {"err": "ok", "msg": _("繁简转换任务已完成"), "data": result}

        return {"err": "ok", "data": result}


class AdminTxtEncodingFixerAnalyze(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        book_id = data.get("book_id")
        if not book_id:
            return {"err": "params.missing", "msg": _("请提供书籍ID")}

        try:
            report = TxtEncodingFixerTool().analyze(int(book_id))
        except RuntimeError as err:
            return {"err": "txt_encoding_fixer.analyze_failed", "msg": str(err)}

        return {"err": "ok", "data": report}


class AdminTxtEncodingFixerFix(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        book_id = data.get("book_id")
        if not book_id:
            return {"err": "params.missing", "msg": _("请提供书籍ID")}

        tool = TxtEncodingFixerTool()
        if tool.is_running():
            return {"err": "task.running", "msg": _("已有 TXT 编码修复任务正在执行，请稍后再试")}

        tool.fix(int(book_id), self.user_id())
        return {"err": "ok", "msg": _("TXT 编码修复任务已启动，注意查看消息通知中的处理结果")}


class AdminTxtEncodingFixerProgress(BaseHandler):
    @js
    @is_admin
    def get(self):
        task = TxtEncodingFixerTool.get_last_task()
        if not task:
            return {"err": "task.not_found", "msg": _("尚未启动 TXT 编码修复任务")}

        progress_data = task.get("progress_data") or {}
        result = {
            "status": task.get("status"),
            "progress": task.get("progress", 0),
            "book_id": progress_data.get("book_id", 0),
            "stage": progress_data.get("stage", ""),
        }

        if task.get("status") == BackgroundTask.STATUS_FAILED:
            return {"err": "task.failed", "msg": task.get("error_message") or _("处理失败"), "data": result}

        if task.get("status") == BackgroundTask.STATUS_COMPLETED:
            return {"err": "ok", "msg": _("TXT 编码修复任务已完成"), "data": result}

        return {"err": "ok", "data": result}


class AdminTextReplacePreview(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        book_id = data.get("book_id")
        pattern = (data.get("pattern") or "").strip()
        replacement = data.get("replacement") or ""
        use_regex = bool(data.get("use_regex", False))
        fmt = (data.get("format") or "").strip().upper()

        if not book_id:
            return {"err": "params.missing", "msg": _("请提供书籍ID")}

        try:
            result = TextReplaceTool().preview(int(book_id), pattern, replacement, use_regex, fmt)
        except RuntimeError as err:
            return {"err": "text_replace.preview_failed", "msg": str(err)}

        return {"err": "ok", "data": result}


class AdminTextReplaceRun(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        book_id = data.get("book_id")
        pattern = (data.get("pattern") or "").strip()
        replacement = data.get("replacement") or ""
        use_regex = bool(data.get("use_regex", False))
        # P7：防超长串落库（前端 v-model counter 同限 30）
        suffix = (data.get("suffix") or "").strip()[:30]
        fmt = (data.get("format") or "").strip().upper()

        if not book_id:
            return {"err": "params.missing", "msg": _("请提供书籍ID")}
        if not pattern:
            return {"err": "params.missing", "msg": _("查找内容不能为空")}

        tool = TextReplaceTool()
        if tool.is_running():
            return {"err": "task.running", "msg": _("已有正文替换任务正在执行，请稍后再试")}

        tool.run(int(book_id), pattern, replacement, use_regex, suffix, self.user_id(), fmt)
        return {"err": "ok", "msg": _("正文替换任务已启动，注意查看消息通知中的处理结果")}


class AdminTextReplaceProgress(BaseHandler):
    @js
    @is_admin
    def get(self):
        task = TextReplaceTool.get_last_task()
        if not task:
            return {"err": "task.not_found", "msg": _("尚未启动正文替换任务")}

        progress_data = task.get("progress_data") or {}
        result = {
            "status": task.get("status"),
            "progress": task.get("progress", 0),
            "book_id": progress_data.get("book_id", 0),
            "stage": progress_data.get("stage", ""),
        }

        if task.get("status") == BackgroundTask.STATUS_FAILED:
            return {"err": "task.failed", "msg": task.get("error_message") or _("处理失败"), "data": result}

        if task.get("status") == BackgroundTask.STATUS_COMPLETED:
            return {"err": "ok", "msg": _("正文替换任务已完成"), "data": result}

        return {"err": "ok", "data": result}


class AdminEpubBeautifyPreview(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        book_id = data.get("book_id")
        if not book_id:
            return {"err": "params.missing", "msg": _("请提供书籍ID")}
        try:
            book_id = int(book_id)
        except (TypeError, ValueError):
            return {"err": "params.invalid", "msg": _("书籍 ID 不合法")}
        try:
            result = EpubBeautifyTool().preview(book_id)
        except RuntimeError as err:
            return {"err": "preview.failed", "msg": str(err)}
        except Exception as err:
            # 畸形 OPF/NCX（ET.ParseError 等）不应 500，转为友好业务错误
            logging.warning("[EpubBeautifyPreview] book_id=%s analyze failed: %s", book_id, err)
            return {"err": "preview.failed", "msg": _("EPUB 解析失败，文件可能已损坏：%s") % str(err)[:200]}
        return {"err": "ok", "data": result}


class AdminEpubBeautifyRun(BaseHandler):
    @js
    @is_admin
    def post(self):
        data = tornado.escape.json_decode(self.request.body)
        # 批量优先：book_ids 列表；回落单本 book_id（兼容旧前端）
        raw_ids = data.get("book_ids") or ([data.get("book_id")] if data.get("book_id") else [])
        try:
            book_ids = [int(x) for x in raw_ids if str(x).strip()]
        except (TypeError, ValueError):
            return {"err": "params.invalid", "msg": _("书籍 ID 不合法")}
        book_ids = list(dict.fromkeys(book_ids))
        if not book_ids:
            return {"err": "params.missing", "msg": _("请提供书籍ID")}
        if len(book_ids) > 100:
            return {"err": "params.invalid", "msg": _("单次最多支持 100 本书籍批量处理")}
        preset = (data.get("preset") or "classic").strip()
        toc_style = (data.get("toc_style") or "elegant").strip()
        # 前置校验：非法 preset/toc_style 即时拒绝，不等后台任务失败
        if preset not in eb_list_presets():
            return {"err": "params.invalid", "msg": _("未知风格预设：%s") % preset}
        if toc_style not in EB_TOC_STYLES:
            return {"err": "params.invalid", "msg": _("未知目录形式：%s") % toc_style}
        use_system_fonts = data.get("use_system_fonts", True)
        # 兼容：前端可能传 string/bool
        if isinstance(use_system_fonts, str):
            use_system_fonts = use_system_fonts.lower() not in ("false", "0", "no", "")
        else:
            use_system_fonts = bool(use_system_fonts)
        # P7：防超长串落库（前端 v-model counter 同限 30）
        suffix = (data.get("suffix") or "").strip()[:30]
        font_overrides = data.get("font_overrides")
        # 兼容细粒度单独键
        if font_overrides is None:
            _ov = {}
            for _k in ("body", "head", "kai", "code"):
                _key = "font_%s" % _k
                if _key in data:
                    _ov[_k] = bool(data.get(_key))
            if _ov:
                font_overrides = _ov
        # 目录层级深度（None=全部）
        toc_depth = data.get("toc_depth")
        try:
            toc_depth = int(toc_depth) if toc_depth else None
        except (TypeError, ValueError):
            toc_depth = None
        if toc_depth is not None and not 1 <= toc_depth <= 6:
            toc_depth = None
        # 内容清理开关（后端有默认值，仅透传合法键）
        cleanup_raw = data.get("cleanup")
        cleanup = None
        if isinstance(cleanup_raw, dict):
            cleanup = {k: bool(cleanup_raw[k]) for k in ("leading", "empty", "meta", "toc_blank") if k in cleanup_raw}
        # 自定义配色（校验键与 hex 格式，非法直接报参数错误；兼容 hexa 8位自动截断为 6位）
        palette_raw = data.get("palette_overrides")
        palette_overrides = None
        if isinstance(palette_raw, dict) and palette_raw:
            _hex_re = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
            palette_overrides = {}
            for k, v in palette_raw.items():
                if k not in ("accent", "accent_light", "accent_dark", "muted", "border", "quote_bg", "code_bg", "toc_gradient"):
                    continue
                if not isinstance(v, str):
                    return {"err": "params.invalid", "msg": _("配色值不合法：%s=%s") % (k, v)}
                vv = v.strip()[:7]
                if not _hex_re.match(vv):
                    return {"err": "params.invalid", "msg": _("配色值不合法：%s=%s") % (k, v)}
                palette_overrides[k] = vv
        # 全书主题底色三态：True/False/'auto'
        page_tint = data.get("page_tint", None)
        if isinstance(page_tint, str):
            page_tint = {"on": True, "true": True, "off": False, "false": False}.get(page_tint.lower(), None)
        # 对话行点缀开关（默认关）
        dialogue = bool(data.get("dialogue", False))
        # 双行排版开关（默认关）
        title_split = bool(data.get("title_split", False))
        # 段落排版：首行缩进独立开关 + 段间距数值（em）；兼容旧 para_mode
        para_mode = data.get("para_mode")
        if para_mode not in (None, "", "indent", "spacing"):
            return {"err": "params.invalid", "msg": _("未知段距模式：%s") % para_mode}
        if "para_indent" in data:
            para_indent = bool(data.get("para_indent"))
        elif para_mode == "spacing":
            para_indent = False
        else:
            para_indent = None  # 默认跟随预设（缩进制）
        para_gap = data.get("para_gap")
        try:
            para_gap = round(float(para_gap), 3) if para_gap not in (None, "", 0) else 0.0
        except (TypeError, ValueError):
            return {"err": "params.invalid", "msg": _("段间距数值不合法：%s") % data.get("para_gap")}
        if not 0 <= para_gap <= 3:
            para_gap = max(0.0, min(3.0, para_gap))
        # 目录双栏开关（默认关，仅作用于生成的目录页）
        toc_columns = bool(data.get("toc_columns", False))
        # 弹注/标注美化（默认关）+ 标注样式（orig/sym/num/svg:<模板>）
        notes_on = bool(data.get("notes", False))
        note_mark = data.get("note_mark") or "orig"
        _svg_ok = note_mark.startswith("svg:") and len(note_mark) > 4
        if note_mark != "orig" and note_mark not in ("sym", "num") and not _svg_ok:
            return {"err": "params.invalid", "msg": _("未知标注样式：%s") % note_mark}
        # 背景图片开关（与前端 bg_image 一致）
        bg_image = bool(data.get("bg_image", False))

        tool = EpubBeautifyTool()
        if tool.is_running():
            return {"err": "task.running", "msg": _("已有美化任务正在运行，请稍后再试")}

        kwargs = {}
        if font_overrides is not None:
            kwargs["font_overrides"] = font_overrides
        if toc_depth is not None:
            kwargs["toc_depth"] = toc_depth
        if cleanup is not None:
            kwargs["cleanup"] = cleanup
        if palette_overrides:
            kwargs["palette_overrides"] = palette_overrides
        if page_tint is not None:
            kwargs["page_tint"] = bool(page_tint)
        kwargs["dialogue"] = dialogue
        kwargs["title_split"] = title_split
        if para_indent is not None:
            kwargs["para_indent"] = para_indent
        if para_gap:
            kwargs["para_gap"] = para_gap
        if toc_columns:
            kwargs["toc_columns"] = True
        if notes_on:
            kwargs["notes"] = True
            if note_mark != "orig":
                kwargs["note_mark"] = note_mark
        if bg_image:
            kwargs["bg_image"] = True
        tool.run(book_ids=book_ids, preset=preset, use_system_fonts=use_system_fonts,
                 toc_style=toc_style, suffix=suffix, user_id=self.user_id(), **kwargs)
        return {"err": "ok", "msg": _("美化任务已启动，右上角可以查看进度")}


class AdminEpubBeautifyBgUpload(BaseHandler):
    @js
    @is_admin
    def post(self):
        builtin_id = (self.get_body_argument("builtin_id", "") or "").strip()
        tool = EpubBeautifyTool()
        try:
            if builtin_id:
                info = tool.save_bg_image(b"", "", builtin_id=builtin_id)
            else:
                if not self.request.files or "file" not in self.request.files:
                    return {"err": "params.missing", "msg": _("未上传文件")}
                fm = self.request.files["file"][0]
                info = tool.save_bg_image(fm["body"], fm["filename"])
        except ValueError as err:
            return {"err": "params.invalid", "msg": str(err)}
        except RuntimeError as err:
            return {"err": "bg.failed", "msg": str(err)}
        return {"err": "ok", "msg": _("背景图已保存"), "data": info}


class AdminEpubBeautifyBgMeta(BaseHandler):
    @js
    @is_admin
    def get(self):
        p = EpubBeautifyTool().bg_image_path()
        if not os.path.exists(p):
            return {"err": "ok", "data": {"has": False}}
        st = os.stat(p)
        return {"err": "ok", "data": {
            "has": True, "bytes": st.st_size, "mtime": int(st.st_mtime),
        }}


class AdminEpubBeautifyBgRaw(BaseHandler):
    def get(self):
        # 手动鉴权（无 @js 时需显式 finish）
        if not self.current_user:
            self.set_status(401)
            self.finish({"err": "user.need_login", "msg": _("请先登录")})
            return
        if not self.admin_user:
            self.set_status(403)
            self.finish({"err": "permission.not_admin", "msg": _("当前用户非管理员, 无权限操作")})
            return
        p = EpubBeautifyTool().bg_image_path()
        if not os.path.exists(p):
            self.set_status(404)
            self.finish("Background image not found")
            return
        # 依实际文件类型返回正确 MIME
        import mimetypes
        mime = mimetypes.guess_type(p)[0] or "image/jpeg"
        self.set_header("Content-Type", mime)
        self.set_header("Cache-Control", "no-store")
        with open(p, "rb") as f:
            self.write(f.read())
        self.finish()


class AdminEpubBeautifyBgDelete(BaseHandler):
    @js
    @is_admin
    def post(self):
        ok = EpubBeautifyTool().delete_bg_image()
        if not ok:
            return {"err": "bg.not_found", "msg": _("尚未上传背景图")}
        return {"err": "ok", "msg": _("背景图已删除")}


class AdminEpubBeautifyProgress(BaseHandler):
    @js
    @is_admin
    def get(self):
        task = EpubBeautifyTool.get_last_task()
        if not task:
            return {"err": "task.not_found", "msg": _("尚未启动美化任务")}

        progress_data = task.get("progress_data") or {}
        result = {
            "status": task.get("status"),
            "progress": task.get("progress", 0),
            "book_id": progress_data.get("book_id", 0),
            "new_book_id": progress_data.get("new_book_id", 0),
            "stage": progress_data.get("stage", ""),
            "book_index": progress_data.get("book_index", 0),
            "book_total": progress_data.get("book_total", 0),
            "current_title": progress_data.get("current_title", ""),
            "results": progress_data.get("results", []),
        }

        if task.get("status") == BackgroundTask.STATUS_FAILED:
            return {"err": "task.failed", "msg": task.get("error_message") or _("美化失败"), "data": result}
        if task.get("status") == BackgroundTask.STATUS_COMPLETED:
            return {"err": "ok", "msg": _("美化已完成"), "data": result}
        return {"err": "ok", "data": result}


def routes():
    # 动态 import 外部工具 / 被更新覆盖的内置工具，只在这里（进程启动、路由拼接时）跑一次，
    # 对应 document/Toolbox_Dynamic_Design.md 3.3.1 节确认的"重启生效"模型。
    toolbox_manager.load_all()

    return [
                (r"/api/toolbox/list", AdminToolList),
                (r"/api/toolbox/store/index", AdminToolStoreIndex),
                (r"/api/toolbox/([a-z0-9_]+)/install", AdminToolStoreInstall),
                (r"/api/toolbox/install/upload", AdminToolInstallUpload),
                (r"/api/toolbox/([a-z0-9_]+)/update/upload", AdminToolUpdateUpload),
                (r"/api/toolbox/([a-z0-9_]+)/enable", AdminToolEnable),
                (r"/api/toolbox/([a-z0-9_]+)/disable", AdminToolDisable),
                (r"/api/toolbox/rare_book_downloader", AdminRareBookDownloader),
                (r"/api/toolbox/merge_formats/merge", AdminMergeFormatsMerge),
                (r"/api/toolbox/review_book_language", AdminReviewBookLanguage),
                (r"/api/toolbox/minify_pdf/upload", AdminMinifyPdfUpload),
                (r"/api/toolbox/minify_pdf/process", AdminMinifyPdfProcess),
                (r"/api/toolbox/minify_pdf/progress", AdminMinifyPdfProgress),
                (r"/api/toolbox/minify_pdf/download", AdminMinifyPdfDownload),
                (r"/api/toolbox/formats_pruning/start", AdminFormatsPruningStart),
                (r"/api/toolbox/formats_pruning/progress", AdminFormatsPruningProgress),
                (r"/api/toolbox/epub_fixer/fix", AdminEpubFixerFix),
                (r"/api/toolbox/epub_split/chapters", AdminEpubSplitChapters),
                (r"/api/toolbox/epub_split/generate", AdminEpubSplitGenerate),
                (r"/api/toolbox/author_clean", AdminAuthorClean),
                (r"/api/toolbox/bookbarn_acceptor/status", AdminBookBarnAcceptorStatus),
                (r"/api/toolbox/bookbarn_acceptor/toggle", AdminBookBarnAcceptorToggle),
                (r"/api/toolbox/bookbarn_acceptor/apply_token", AdminBookBarnAcceptorApplyToken),
                (r"/api/toolbox/bookbarn_acceptor/set_collection_hour", AdminBookBarnAcceptorSetCollectionHour),
                (r"/api/toolbox/mimo_tts/convert", AdminMimoTTSConvert),
                (r"/api/toolbox/mimo_tts/progress", AdminMimoTTSProgress),
                (r"/api/toolbox/mimo_tts/config", AdminMimoTTSConfig),
                (r"/api/toolbox/mimo_tts/test", AdminMimoTTSTest),
                (r"/api/toolbox/mimo_tts/clone/upload", AdminMimoTTSCloneUpload),
                (r"/api/toolbox/mimo_tts/clone/list", AdminMimoTTSCloneList),
                (r"/api/toolbox/mimo_tts/clone/delete", AdminMimoTTSCloneDelete),
                (r"/api/toolbox/mimo_tts/clone/audio", AdminMimoTTSCloneAudio),
                (r"/api/toolbox/mimo_tts/prompt/list", AdminMimoTTSPromptList),
                (r"/api/toolbox/mimo_tts/prompt/save", AdminMimoTTSPromptSave),
                (r"/api/toolbox/mimo_tts/prompt/delete", AdminMimoTTSPromptDelete),
                (r"/api/toolbox/text_replace/preview", AdminTextReplacePreview),
                (r"/api/toolbox/text_replace/run", AdminTextReplaceRun),
                (r"/api/toolbox/text_replace/progress", AdminTextReplaceProgress),
                (r"/api/toolbox/txt_encoding_fixer/analyze", AdminTxtEncodingFixerAnalyze),
                (r"/api/toolbox/txt_encoding_fixer/fix", AdminTxtEncodingFixerFix),
                (r"/api/toolbox/txt_encoding_fixer/progress", AdminTxtEncodingFixerProgress),
                (r"/api/toolbox/chinese_converter/convert", AdminChineseConverterConvert),
                (r"/api/toolbox/chinese_converter/progress", AdminChineseConverterProgress),
                (r"/api/toolbox/epub_beautify/preview", AdminEpubBeautifyPreview),
                (r"/api/toolbox/epub_beautify/run", AdminEpubBeautifyRun),
                (r"/api/toolbox/epub_beautify/progress", AdminEpubBeautifyProgress),
                (r"/api/toolbox/epub_beautify/bg_upload", AdminEpubBeautifyBgUpload),
                (r"/api/toolbox/epub_beautify/bg_meta", AdminEpubBeautifyBgMeta),
                (r"/api/toolbox/epub_beautify/bg_raw", AdminEpubBeautifyBgRaw),
                (r"/api/toolbox/epub_beautify/bg_delete", AdminEpubBeautifyBgDelete),
    ] + toolbox_manager.collect_tool_routes() + [
                # 必须放在整个列表最后：这是个不加区分的单段路径通配（DELETE 卸载），
                # 排在前面会抢先匹配到上面所有单段路径的工具路由（如
                # /api/toolbox/rare_book_downloader、/api/toolbox/author_clean），
                # Tornado 是按 URLSpec 顺序找第一个正则匹配的路径、与 HTTP method 无关。
                (r"/api/toolbox/([a-z0-9_]+)", AdminToolUninstall),
    ]
