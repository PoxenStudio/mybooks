"""
文字处理工具

将纯文本按空行拆分为段落并转换为 HTML，支持关键词规则（加粗/加大/高亮）
及书名号自动加粗，提供实时预览与 HTML 代码导出。所有处理均在前端完成，
本类仅提供工具元数据，供 ToolSet 注册与展示。

@author: PoxenStudio, 2026
"""
from webserver.toolbox.base_tool import BaseTool


class TextProcessor(BaseTool):
    service_item_name = ""

    @staticmethod
    def info():
        return {
            "tool_id": "text_processor",
            "name": "文本处理工具",
            "description": "将文本自动转换为带段落、关键词高亮和书名号加粗的 HTML，支持实时预览与代码导出",
            "revision": "0.1.0",
            "author": "OLShopping",
            "publish_date": "2026-06-08",
        }
