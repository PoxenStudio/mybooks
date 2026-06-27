import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from openai import OpenAI
from webserver import loader
from webserver.constants import DEEPSEEK_API_BASE
from webserver.services.book_search import BookSearch
from webserver.i18n import _

CONF = loader.get_settings()


@dataclass
class AIBookInfo:
    category: str = ""
    tags: List[str] = field(default_factory=list)
    authors: List[str] = field(default_factory=list)
    pubdate: str = ""
    summary: str = ""
    author_intro: str = ""

    @property
    def comments(self) -> str:
        parts = []
        if self.summary:
            parts.append(f"<p>{self.summary}</p>")
        if self.author_intro:
            parts.append(f"<p><b>作者简介</b></p><p>{self.author_intro}</p>")
        return "\n".join(parts)

    def is_valid(self) -> bool:
        return bool(self.category or self.tags)


class BookAIClient:
    SYSTEM_PROMPT = (
        "你是一个专业的图书信息分析助手。"
        "用户会提供书名、作者等基础信息，以及从互联网搜索到的参考信息（可能包含多个来源）。"
        "请综合所有参考信息，生成书籍的分类、标签、内容摘要和作者介绍。"
        "注意：原始书名中可能含多余字符如()【】等，需自行去除。作者和ISBN可能有误，以参考信息中的内容为准。"
        "标签只需要保留2个。如果信息不足，无法准确确定一本书，或无法返回指定信息，就留空。"
        "图书的作者可能是错误的，如果参考信息是确定的，请更新作者信息。"
        "请严格按照 JSON 格式输出，不要添加任何额外内容。"
        "输出格式："
        "{"
        '  "category": "书籍分类（单个，如：小说、历史、科技、文学、传记、哲学、艺术、经济等）",'
        '  "tags": ["标签1", "标签2"],'
        '  "authors": ["作者1", "作者2"],'
        '  "pubdate": "出版年月（如：2026-05或2026）",'
        '  "summary": "书籍主要内容总结（800字以内）",'
        '  "author_intro": "作者介绍（200字以内，无充分信息时留空字符串）"'
        "}"
    )

    def __init__(self, url: str = None, key: str = None, model: str = None):
        api_key = key if key else CONF.get("AI_DEEPSEEK_API_KEY", "")
        api_url = url if url else CONF.get("AI_API_URL", DEEPSEEK_API_BASE)
        if not api_key or not api_url:
            raise ValueError("API_KEY or API_URL is not configured")

        self.client = OpenAI(
            api_key=api_key,
            base_url=api_url,
            timeout=60.0,
        )
        self.model = model if model else CONF.get("AI_MODEL", "deepseek-chat")

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

    @staticmethod
    def _format_search_results(books) -> str:
        """将 BookSearch.search_books 的结果格式化为文本参考信息。"""
        parts = []
        for idx, book in enumerate(books[:3], 1):
            source = getattr(book, "source", "") or ""
            block = [f"【参考来源{idx}：{source}】"]
            result_title = getattr(book, "title", "") or ""
            if result_title:
                block.append(f"书名：{result_title}")
            result_authors = getattr(book, "authors", []) or []
            if result_authors:
                block.append(f"作者：{'、'.join(str(a) for a in result_authors)}")
            result_publisher = getattr(book, "publisher", "") or ""
            if result_publisher:
                block.append(f"出版社：{result_publisher}")
            result_tags = getattr(book, "tags", []) or []
            if result_tags:
                block.append(f"标签：{', '.join(str(t) for t in result_tags[:8])}")
            result_pub_date = getattr(book, "pubdate", None)
            if result_pub_date:
                try:
                    pub_date_str = result_pub_date.strftime("%Y-%m")
                except Exception:
                    pub_date_str = str(result_pub_date)[:7]
                block.append(f"出版日期：{pub_date_str}")
            result_comments = getattr(book, "comments", "") or ""
            if result_comments:
                block.append(f"简介：{result_comments[:500]}")
            result_author_intro = getattr(book, "douban_author_intro", "") or ""
            if result_author_intro:
                block.append(f"作者介绍：{result_author_intro[:300]}")
            parts.append("\n".join(block))
        return "\n\n".join(parts)

    def test_connection(self) -> tuple[bool, str]:
        try:
            logging.info("[BookAI] Testing connection to AI service at %s", self.client.base_url)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": "Check the connect, please answer with JSON format {\"response\": \"pong\"} if you can receive this message."}],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=200,
            )
            content = response.choices[0].message.content
            if not content:
                logging.warning("[BookAI] Empty response for testing connection")
                return False, _("AI服务返回了空响应")
            data = json.loads(content)
            matched = data.get("response", "").lower() == "pong"
            if matched:
                logging.info("[BookAI] Connection test successful")
                return True, ""
            logging.warning("[BookAI] Connection test failed, unexpected response: %s", content)
            return False, _("AI服务返回了意外的响应") + ": " + content
        except Exception as e:
            logging.error("[BookAI] Connection test failed: %s", e)
            return False, str(e)

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

        # 从网络搜索补充参考信息
        try:
            search_isbn = isbn if (isbn and self._is_valid_isbn(isbn)) else None
            search_results = BookSearch.search_books(title=title, isbn=search_isbn)
            if search_results:
                ref_text = self._format_search_results(search_results)
                lines.append("\n以下是从互联网搜索到的参考信息：")
                lines.append(ref_text)
                logging.info("[BookAI] Got %d search result(s) for '%s'", len(search_results), title)
        except Exception as e:
            logging.warning("[BookAI] BookSearch failed for '%s': %s", title, e)

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
                pubdate=str(data.get("pubdate", "")).strip(),
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
