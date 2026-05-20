"""
繁体中文书籍检测工具

遍历所有书籍，检测 title 字段是否为繁体中文，若是则将书籍的 languages 字段设置为 "zha"。

繁体中文检测逻辑：
1. 跳过纯 ASCII 标题（不含中文字符）。
2. 使用 OpenCC (t2s 模式) 将 title 从繁体转为简体：
   若转换后与原文不同，说明原文含有繁体中文字符。
3. 若 OpenCC 不可用，则回退至字符集范围检测：
   检查 title 是否含有仅属于繁体的常见 Unicode 字符。
"""
import logging
import traceback
from typing import Callable, Optional

from webserver.services import AsyncService
from webserver.toolbox.base_tool import BaseTool

TRADITIONAL_CHINESE_CODE = "zha"


def _is_traditional_chinese(text: str) -> bool:
    """判断文本中是否含有繁体中文字符。

    优先使用 OpenCC t2s 转换；不可用时回退到字符集区间检测。
    """
    if not text:
        return False
    # 若全为 ASCII，直接跳过
    if all(ord(c) < 128 for c in text):
        return False

    try:
        import opencc
        converter = opencc.OpenCC("t2s")
        converted = converter.convert(text)
        return converted != text
    except Exception as exc:
        logging.debug("[review_cht] OpenCC unavailable (%s), using fallback", exc)
        return _fallback_has_traditional(text)


# 常见繁体中文专有字符（在 Simplified 中对应不同字形），用于 fallback 检测
_TRADITIONAL_ONLY_CHARS = frozenset(
    "書電來說話這個時會對學問國務現實際應當來們點進開關處還"
    "歡樂體動設計資訊傳說標準環境網絡變換預算發展運動認識"
    "義務條件結構機制選擇統計監督繼續識別溝通維護數據處理"
    "歷史文化藝術哲學經濟組織機構協議協作協調決策執行方針"
    "與並從內外長短廣狹強弱快慢遠近輕重高低深淺寬窄早晚"
    "後前左右東西南北上下中外新舊多少大小"
    # 常見繁體字
    "與與來來說說國國時時個個會對對學問問處還還變發電書樂"
)


def _fallback_has_traditional(text: str) -> bool:
    """回退方案：检测文本是否含有繁体专有常用字。"""
    return any(c in _TRADITIONAL_ONLY_CHARS for c in text)


class ReviewTraditionalChineseTool(BaseTool):
    """遍历所有书籍，将繁体中文书名的书籍语言设置为 zha。"""

    service_item_name = "繁体中文检测"

    @staticmethod
    def info() -> dict:
        return {
            "tool_id": "review_cht_books",
            "name": "繁体中文检测",
            "description": "遍历所有书籍，检测书名是否为繁体中文，并将对应书籍的语言字段设置为繁体",
            "revision": "0.1.0",
            "author": "PoxenStudio",
            "publish_date": "2026-05-20",
        }

    @AsyncService.register_service
    def review(
        self,
        user_id,
        callback: Optional[Callable[[int], None]] = None,
    ) -> Optional[dict]:
        """异步遍历所有书籍，检测繁体中文书名并更新 languages 字段。

        :param user_id:  操作关联的用户 ID（保留字段，目前仅记录日志）。
        :param callback: 进度回调，参数为 0-100 的整数进度值。
        :return:         同步模式下返回统计 dict；异步模式下返回 None。
        """
        task_id = self.create_task(progress_data={"status": "starting"})
        total_checked = 0
        total_updated = 0
        error_message = None

        try:
            book_ids = self.get_all_book_ids()
            total = len(book_ids)
            logging.info("[ReviewTraditionalChineseTool] Total books to check: %d [uid:%d]", total, user_id)

            self.update_task_progress(
                task_id, 0,
                {"status": "running", "total": total, "checked": 0, "updated": 0},
            )

            for idx, book_id in enumerate(book_ids, start=1):
                try:
                    mi = self.get_book_metadata(book_id)
                    title = (mi.title or "").strip()

                    if _is_traditional_chinese(title) and (not mi.languages or mi.languages[0] != TRADITIONAL_CHINESE_CODE):
                        self.set_book_language(book_id, TRADITIONAL_CHINESE_CODE)
                        total_updated += 1
                        logging.info(
                            "[ReviewTraditionalChineseTool] book_id=%d title=%r → language=zha",
                            book_id, title,
                        )
                except Exception as err:
                    logging.warning(
                        "[ReviewTraditionalChineseTool] Failed to process book_id=%d: %s",
                        book_id, err,
                    )

                total_checked += 1
                progress = int(idx * 100 / total) if total else 100
                if total_checked % 20 == 0:
                    self.update_task_progress(
                        task_id, progress,
                        {
                            "status": "running",
                            "total": total,
                            "checked": total_checked,
                            "updated": total_updated,
                        },
                    )

        except Exception as err:
            logging.error("[ReviewTraditionalChineseTool] review failed: %s", err)
            error_message = str(err)
            logging.error(traceback.format_exc())

        self.complete_task(
            task_id,
            error_message=error_message,
        )

        return {
            "total": len(book_ids) if error_message is None else total_checked,
            "checked": total_checked,
            "updated": total_updated,
        }
