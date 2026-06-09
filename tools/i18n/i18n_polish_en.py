#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import json
import re

PATH = "webserver/i18n/en.json"

ph_key_re = re.compile(r"%(?:\([^)]+\))?[#0\- +]?\d*(?:\.\d+)?[a-zA-Z]")
ph_token_re = re.compile(r"__\s*PH_(\d+)\s*__")

KEY_BASED_POLISH = {
    "\"%(name)s\"丛书包含的书籍": "Books in the \"%(name)s\" series",
    "\"%(name)s\"出版的书籍": "Books published by \"%(name)s\"",
    "\"%(name)s\"编著的书籍": "Books by \"%(name)s\"",
    "\"%(name)s\"语言的书籍": "Books in %(name)s",
    "%s成功": "%s succeeded",
    "AI 助手未启用，需要到系统设置中启用": "AI Assistant is disabled. Enable it in System Settings.",
    "AI 更新": "AI update",
    "AI 更新失败": "AI update failed",
    "AI 更新成功": "AI update succeeded",
    "AI 未能返回有效信息": "AI did not return valid information",
    "BookBarn Tags插件未安装": "BookBarn Tags plugin is not installed",
    "CSV文件中没有数据": "CSV file contains no data",
    "CSV文件必须包含isbn字段": "CSV file must include an isbn field",
    "CalibreMetadataApi ISBN 查询失败 isbn=%s: %s": "CalibreMetadataApi ISBN query failed, isbn=%s: %s",
    "CalibreMetadataApi 书名查询失败 title=%s: %s": "CalibreMetadataApi title query failed, title=%s: %s",
    "ID不能为空": "ID cannot be empty",
    "ID错误": "Invalid ID",
    "Kindle格式转EPUB": "Convert Kindle format to EPUB",
    "Kindle转EPUB任务已启动": "Kindle-to-EPUB task started",
    "Kindle转EPUB任务已结束，未找到需要转换的书籍": "Kindle-to-EPUB task finished: no books need conversion",
    "[%(title)s] 已成功发送至邮箱 [%(mail_to)s] !!": "[%(title)s] was successfully sent to [%(mail_to)s]!!",
    "baidu 接口查询 %s 失败": "Baidu API query failed: %s",
    "bookbarn_tags 接口查询 %s 失败": "bookbarn_tags API query failed: %s",
    "bookbarn_tags 接口查询 %s 失败: %s": "bookbarn_tags API query failed: %s, %s",
    "calibre 插件 ISBN 查询 %s 失败": "Calibre plugin ISBN query failed: %s",
    "calibre 插件书名查询 %s 失败": "Calibre plugin title query failed: %s",
    "calibre 插件书名查询 %s 失败: %s": "Calibre plugin title query failed: %s, %s",
    "douban 接口查询 %s 失败": "Douban API query failed: %s",
    "idlist参数错误": "Invalid idlist parameter",
    "上传失败 (HTTP %d)。请查看日志获取详细信息": "Upload failed (HTTP %d). See logs for details",
    "上传超时。请检查网络连接和设备状态": "Upload timed out. Check network and device status",
    "上传过程出错: %s。请查看日志获取详细信息": "Upload error: %s. See logs for details",
    "下载工具": "Download tools",
    "丛书列表": "Series list",
    "书籍只有一个格式，无法分离": "This book has only one format and cannot be split",
    "书籍只有一个格式，无法刪除": "This book has only one format and cannot be deleted",
    "书籍数量较少，无需清理标签": "Too few books; tag cleanup is not required",
    "书籍没有指定的格式：%s": "Book does not have format: %s",
    "书籍没有支持的文件格式（EPUB/AZW3/PDF/MOBI/TXT）": "Book has no supported formats (EPUB/AZW3/PDF/MOBI/TXT)",
    "书籍没有支持的文件格式（epub/azw3/pdf/txt）": "Book has no supported formats (epub/azw3/pdf/txt)",
    "优书网查询失败": "Youshu query failed",
    "作者信息不完整，可能导致信息错误，跳过更新": "Author information is incomplete; skipped to avoid incorrect updates",
    "使用 Calibre Metadata API 搜索图书，title: %s, isbn: %s, sources: %s": "Search books via Calibre Metadata API, title=%s, isbn=%s, sources=%s",
    "值不能为空": "Value cannot be empty",
    "全部作者": "All authors",
    "全部出版社": "All publishers",
    "全部标签": "All tags",
    "全部评分": "All ratings",
    "全部语言": "All languages",
    "内部处理错误": "Internal processing error",
    "出版日期参数错误，格式应为 2026-05-10或2026-05或2026年或2026": "Invalid publication date. Expected 2026-05-10, 2026-05, 2026年, or 2026",
    "分类不能为空": "Category cannot be empty",
    "删除书籍《%s》": "Delete book: %s",
    "删除书籍《%s》的%s格式": "Delete format %s from book: %s",
    "参数冲突": "Parameter conflict",
    "参数无效": "Invalid parameter",
    "参数错误, id列表中包含无效的id": "Invalid parameter: id list contains invalid IDs",
    "参数错误, 未指定正确的id列表": "Invalid parameter: incorrect id list",
    "取消置顶成功": "Unpinned successfully",
    "同名书籍《%s》已存在这一图书格式 %s": "Book \"%s\" already has format %s",
    "后台正在推送，稍后可以刷新页面，在通知消息中查看结果。": "Push task is running in the background. Refresh later and check notifications for results.",
    "图书信息刮削": "Metadata scraping",
    "在读书籍": "Currently reading",
    "处理完成：成功 %d 本，跳过 %d 本": "Processing complete: %d succeeded, %d skipped",
    "实体书": "Physical book",
    "实体书数量已更新，当前数量：%d": "Physical book count updated. Current count: %d",
    "导入图书": "Import books",
    "已开始推送《%(title)s》到%(email)s": "Started pushing \"%(title)s\" to %(email)s",
    "已提交 %d 本书籍的标签更新任务，正在后台处理, 请稍后刷新查看结果": "Submitted tag update task for %d books. Processing in background; refresh later for results",
    "已经在生成音频中": "Audio is already being generated",
    "已读完书籍": "Finished reading",
    "已转为实体书": "Converted to physical book",
    "开始扫描了": "Scan started",
    "开始批量添加实体书": "Started bulk adding physical books",
    "开始搜索图书，title: %s, isbn: %s, publisher: %s, sources: %s": "Start searching books, title=%s, isbn=%s, publisher=%s, sources=%s",
    "开始更新 %d 本书的标签，涉及 %d 个稀少标签": "Start updating tags for %d books, involving %d rare tags",
    "开始自动填充书籍 id=%d 的元数据，title=%s": "Start autofilling metadata for book id=%d, title=%s",
    "开始转换": "Conversion started",
    "当前转换任务超过2项, 请稍后再试": "More than 2 conversion tasks are running. Please try again later",
    "待读清单": "To-read list",
    "忽略更新书籍 id=%d : 无法获取信息": "Skip updating book id=%d: failed to fetch information",
    "忽略更新书籍 id=%d : 无法获取封面": "Skip updating book id=%d: failed to fetch cover",
    "忽略更新书籍 id=%d : 无法获取标签, title=%s": "Skip updating book id=%d: failed to fetch tags, title=%s",
    "忽略更新书籍 id=%d : 无需更新": "Skip updating book id=%d: no update needed",
    "忽略获取标签书籍 id=%d : 无有效数据": "Skip fetching tag for book id=%d: no valid data",
    "成功将 %s 格式分离为新书籍": "Successfully split %s format into a new book",
    "成功更新 %d 本书籍分类": "Successfully updated categories for %d books",
    "我的收藏": "My favorites",
    "扫描导入目录": "Scan import directory",
    "扫描并导入文件": "Scan and import files",
    "找不到对应的上传器: %s": "No uploader found for: %s",
    "拉取图书信息异常，请重试": "Failed to fetch book information. Please try again",
    "推荐成功": "Recommended successfully",
    "搜索作者书籍失败": "Failed to search books by author",
    "搜索完成，找到 %d 本书": "Search completed: found %d books",
    "搜索标签书籍失败": "Failed to search books by tag",
    "搜索：%(name)s": "Search: %(name)s",
    "数据库操作异常，请重试": "Database operation failed. Please try again",
    "文件hash不能为空": "File hash cannot be empty",
    "文件格式转换失败，请到公众号上私信联系": "File format conversion failed. Please contact support via the official account",
    "新书推荐": "New book recommendations",
    "无ISBN，跳过": "No ISBN; skipped",
    "无名书籍": "Untitled book",
    "无权在线阅读": "No permission to read online",
    "无权在线阅读PDF类书籍": "No permission to read PDF books online",
    "无权登录": "No permission to sign in",
    "无权限": "No permission",
    "无权限，非管理员或书籍所有者无法操作": "No permission. Only admins or book owners can perform this action",
    "无法连接到设备。请确认IP地址正确，且设备已开启WiFi上传功能": "Unable to connect to device. Ensure IP is correct and Wi-Fi upload is enabled on the device",
    "无详细介绍": "No description",
    "暂无简介": "No summary",
    "更新书名信息": "Update title sort",
    "更新书名信息任务已启动": "Title-sort update task started",
    "更新书籍元数据失败 id=%d: %s": "Failed to update book metadata, id=%d: %s",
    "更新分类失败": "Failed to update category",
    "更新失败，请稍后再试": "Update failed. Please try again later",
    "更新成功": "Updated successfully",
    "有声书": "Audiobooks",
    "服务器后台正在推送。您可关闭此窗口，继续浏览其他书籍。": "Push task is running in the background. You can close this window and continue browsing",
    "服务器正在推送《%(title)s》到%(email)s": "Server is pushing \"%(title)s\" to %(email)s",
    "服务器正在转换格式，稍后将自动推送。您可关闭此窗口，继续浏览其他书籍。": "Server is converting formats and will push automatically later. You can close this window and continue browsing",
    "未找到封面信息": "Cover not found",
    "未找到该登记项": "Record not found",
    "未知": "Unknown",
    "未知类型": "Unknown type",
    "本书不支持转换，仅支持EPUB及Kindle使用的格式转换为PDF": "This book cannot be converted. Only EPUB/Kindle formats can be converted to PDF",
    "查询ISBN失败，请在系统设置中配置互联网信息源中插件地址。如http://douban-rs-api:80/。": "ISBN query failed. Configure plugin endpoint in System Settings, e.g. http://douban-rs-api:80/",
    "标签已是最新，无需更新": "Tags are already up to date",
    "没有找到书籍": "No books found",
    "添加失败": "Add failed",
    "添加成功": "Added successfully",
    "激活码无效": "Invalid activation code",
    "热度榜单": "Trending list",
    "用户名或密码错误": "Incorrect username or password",
    "用户添加成功": "User added successfully",
    "目前无权登录！请联系管理员在用户管理中检查登录权限": "You are not allowed to sign in now. Contact an admin to check login permissions",
    "目录中没有找到符合要求的书籍文件！": "No eligible book files were found in the directory",
    "系统繁忙": "System is busy",
    "置顶失败": "Pin failed",
    "置顶成功": "Pinned successfully",
    "自动填充元数据时出错 id=%d: %s": "Error autofilling metadata, id=%d: %s",
    "自动更新书籍 id=[%d] 的信息，title=%s": "Auto-updating book info, id=[%d], title=%s",
    "自动更新书籍 id=[%d] 的标签，title=%s": "Auto-updating book tags, id=[%d], title=%s",
    "获取书籍信息失败 id=%d: %s": "Failed to fetch book information, id=%d: %s",
    "获取实体书失败": "Failed to fetch physical books",
    "评分为%(name)s星的书籍": "Books rated %(name)s stars",
    "该图书已存在或创建失败": "Book already exists or failed to create",
    "请求参数格式错误": "Invalid request parameter format",
    "请求参数错误": "Invalid request parameters",
    "请输入搜索关键字": "Please enter search keywords",
    "请选择CSV文件": "Please select a CSV file",
    "读取书籍元数据失败 id=%d: %s": "Failed to read book metadata, id=%d: %s",
    "调用 bookbarn_tags 接口查询 %s, %s, %s": "Calling bookbarn_tags API query: %s, %s, %s",
    "购买成功": "Purchase succeeded",
    "转换失败": "Conversion failed",
    "转换完成": "Conversion completed",
    "转换成功，请稍后刷新页面查看": "Conversion succeeded. Please refresh the page later",
    "邮箱地址不能为空": "Email address cannot be empty",
    "邮箱地址格式不正确": "Invalid email address format",
    "阅读状态参数错误": "Invalid reading status parameter",
    "阅读状态已设置为：%s": "Reading status set to: %s",
    "附件过大（%.1fMB），邮件附件大小不能超过50MB": "Attachment too large (%.1fMB). Email attachments must be <= 50MB",
    "默认用户": "Default user",
    "（共找到 %d 本，仅处理前 300 本）": "(%d found in total; only first 300 processed)",
    "；失败：%s": "; failed: %s",
}


def restore_placeholders_from_key(key: str, value: str) -> str:
    placeholders = ph_key_re.findall(key)
    if not placeholders:
        return value

    def repl(m):
        idx = int(m.group(1))
        if 0 <= idx < len(placeholders):
            return placeholders[idx]
        return m.group(0)

    value = ph_token_re.sub(repl, value)

    # Fix occasional token spacing variants left by translators.
    for idx, ph in enumerate(placeholders):
        value = value.replace(f"__ PH_{idx} __", ph)
        value = value.replace(f"__PH_{idx}__", ph)
    return value


def main():
    with open(PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    changed = 0
    for k, v in list(data.items()):
        if isinstance(v, str):
            nv = restore_placeholders_from_key(k, v)
            if nv != v:
                data[k] = nv
                changed += 1

    for k, nv in KEY_BASED_POLISH.items():
        if data.get(k) != nv:
            data[k] = nv
            changed += 1

    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")

    print(f"polished_changes={changed}")


if __name__ == "__main__":
    main()
