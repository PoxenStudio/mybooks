"""
Book AI Client
~~~~~~~~~~~~~~
使用 DeepSeek API（OpenAI SDK）从书名、作者等基础信息中提取
结构化的书籍分类、标签、内容摘要和作者介绍。
"""

import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from openai import OpenAI
from webserver import loader
from webserver.constants import DEEPSEEK_API_BASE

CONF = loader.get_settings()


@dataclass
class AIBookInfo:
    category: str = ""
    tags: List[str] = field(default_factory=list)
    authors: List[str] = field(default_factory=list)
    summary: str = ""
    author_intro: str = ""

    @property
    def comments(self) -> str:
        parts = []
        if self.summary:
            parts.append(f"<p><b>内容简介</b></p><p>{self.summary}</p>")
        if self.author_intro:
            parts.append(f"<p><b>作者简介</b></p><p>{self.author_intro}</p>")
        return "\n".join(parts)

    def is_valid(self) -> bool:
        return bool(self.category or self.tags)


class BookAIClient:
    SYSTEM_PROMPT = (
        "你是一个专业的图书信息分析助手。"
        "根据提供的书名、作者等信息,生成书籍的分类、标签、内容摘要和作者介绍。其中作者和ISBN可能是错误的,只作为参考。不要依赖内部知识，尽可能进行联网搜索。\n"
        "书名中可能含一些不需要的字符如()【】等，需要自行去除。请严格按照 JSON 格式输出，不要添加任何额外内容。\n"
        "标签只需要保留2个。如果信息不足,无法准确确定一本书,或者无法返回指定信息,就留空。图书的作者可能是错误的，如果图书信息是确定的，可以更新作者信息。\n"
        "输出格式：\n"
        "{\n"
        '  "category": "书籍分类（单个，如：小说、历史、科技、文学、传记、哲学、艺术等）",\n'
        '  "tags": ["标签1", "标签2"],\n'
        '  "authors": ["作者1", "作者2"],\n'
        '  "summary": "书籍主要内容总结（800字以内）",\n'
        '  "author_intro": "作者介绍（200字以内，无充分信息时留空字符串）"\n'
        "}"
    )

    def __init__(self):
        api_key = CONF.get("AI_DEEPSEEK_API_KEY", "")
        if not api_key:
            raise ValueError("AI_DEEPSEEK_API_KEY is not configured")

        self.client = OpenAI(
            api_key=api_key,
            base_url=DEEPSEEK_API_BASE,
            timeout=30.0,
        )
        self.model = "deepseek-chat"

    @staticmethod
    def _is_valid_isbn(isbn: str) -> bool:
        """通过长度和首个数字判断 ISBN 是否合法。
        ISBN-10: 长度为 10，首位为数字。
        ISBN-13: 长度为 13，首位为 '9'（即以 978 或 979 开头）。
        """
        cleaned = isbn.replace("-", "").replace(" ", "")
        if not cleaned.isdigit():
            return False
        if len(cleaned) == 10:
            return cleaned[0].isdigit()
        if len(cleaned) == 13:
            return cleaned[0] == "9"
        return False

    def get_book_info(
        self,
        title: str,
        authors: List[str],
        isbn: str = ""
    ) -> Optional[AIBookInfo]:
        author_str = "、".join(authors) if authors else "未知"
        lines = [f"书名：{title}", f"作者：{author_str}"]
        if isbn and self._is_valid_isbn(isbn):
            lines.append(f"ISBN：{isbn}")
        user_prompt = "\n".join(lines)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=1500,
            )

            content = response.choices[0].message.content
            if not content:
                logging.warning("[BookAI] Empty response for book: %s", title)
                return None

            data = json.loads(content)
            info = AIBookInfo(
                category=str(data.get("category", "")).strip(),
                tags=[str(t).strip() for t in data.get("tags", []) if str(t).strip()],
                authors=[str(a).strip() for a in data.get("authors", []) if str(a).strip()],
                summary=str(data.get("summary", "")).strip(),
                author_intro=str(data.get("author_intro", "")).strip(),
            )
            logging.info(
                "[BookAI] Got info for '%s': category=%s, tags=%s, authors=%s",
                title,
                info.category,
                info.tags,
                info.authors
            )
            return info

        except json.JSONDecodeError as e:
            logging.error("[BookAI] JSON parse error for '%s': %s", title, e)
            return None
        except Exception as e:
            logging.error("[BookAI] API call failed for '%s': %s", title, e)
            return None
