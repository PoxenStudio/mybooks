import base64
import logging
import os
import re
import threading
import traceback
from typing import Optional

import ebooklib
import requests
from bs4 import BeautifulSoup
from ebooklib import epub

from webserver.handlers.audio import AudioBooksCache
from webserver.i18n import _
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver.toolbox.base_tool import BaseTool
from webserver import loader

CONF = loader.get_settings()
AUDIO_OUTPUT_FOLDER = CONF.get("audio_output_folder", "/data/books/audios/")
DEFAULT_CHAT_URL = "https://api.xiaomimimo.com/v1/chat/completions"
DEFAULT_CHAT_MODEL = "mimo-v2.5-tts"
MAX_CHUNK_CHARS = 2000


class MimoTTSTool(BaseTool):
    service_item_name = "MiMo TTS有声书"

    _convert_lock = threading.Lock()
    _last_task_id: Optional[int] = None

    @classmethod
    def is_running(cls) -> bool:
        task = cls.get_last_task()
        return bool(task and task.get("status") == BackgroundTask.STATUS_RUNNING)

    @classmethod
    def get_last_task(cls) -> Optional[dict]:
        if cls._last_task_id is None:
            return None
        return BackgroundService().get_task(cls._last_task_id)

    @staticmethod
    def info() -> dict:
        return {
            "tool_id": "mimo_tts",
            "name": "TTS有声书",
            "description": "通过 TTS API（支持 MiMo Chat / OpenAI TTS 格式）将 EPUB 书籍合成为有声书（WAV格式），生成后可在线播放",
            "revision": "0.2.0",
            "author": "MyBooks",
            "publish_date": "2026-07-21",
        }

    @staticmethod
    def _extract_chapters(epub_path: str) -> list[dict]:
        book = epub.read_epub(epub_path)
        spine_items = {}
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                spine_items[item.get_name()] = item

        chapters = []
        seen = set()
        def resolve_toc(toc_items, depth=0):
            for entry in toc_items:
                if isinstance(entry, tuple):
                    link, sub = entry
                    if hasattr(link, 'href') and link.href:
                        href = link.href.split('#')[0]
                        title = link.title or ""
                        if href not in seen:
                            seen.add(href)
                            chapters.append({"title": title, "href": href})
                    if sub:
                        resolve_toc(sub, depth + 1)
                elif hasattr(entry, 'href') and entry.href:
                    href = entry.href.split('#')[0]
                    title = getattr(entry, 'title', '') or ''
                    if href not in seen:
                        seen.add(href)
                        chapters.append({"title": title, "href": href})

        resolve_toc(book.toc)

        if not chapters:
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    chapters.append({"title": "", "href": item.get_name()})

        for ch in chapters:
            href = ch["href"]
            item = spine_items.get(href)
            if item:
                soup = BeautifulSoup(item.get_content(), "html.parser")
                for tag in soup(["script", "style", "nav"]):
                    tag.decompose()
                text = soup.get_text(separator="\n")
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                ch["text"] = "\n".join(lines)
            else:
                ch["text"] = ""

        return chapters

    @staticmethod
    def _split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
        if len(text) <= max_chars:
            return [text.strip()]
        sentences = re.split(r"(?<=[。！？.!?\n])", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        chunks = []
        current = ""
        for sentence in sentences:
            if len(current) + len(sentence) <= max_chars:
                current += sentence
            else:
                if current:
                    chunks.append(current.strip())
                if len(sentence) > max_chars:
                    while len(sentence) > max_chars:
                        chunks.append(sentence[:max_chars])
                        sentence = sentence[max_chars:]
                    current = sentence
                else:
                    current = sentence
        if current:
            chunks.append(current.strip())
        return chunks

    @staticmethod
    def _synthesize(text: str, api_key: str, voice_desc: str,
                    api_url: str, model_name: str, api_type: str,
                    voice_name: str, auth_type: str) -> bytes:
        headers = {"Content-Type": "application/json"}
        if auth_type == "api-key":
            headers["api-key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"

        if api_type == "audio_speech":
            payload = {
                "model": model_name,
                "input": text,
                "voice": voice_name or "alloy",
                "response_format": "wav",
            }
            resp = requests.post(api_url, headers=headers, json=payload, timeout=120)
            resp.raise_for_status()
            return resp.content

        payload = {
            "model": model_name,
            "messages": [
                {"role": "user", "content": voice_desc},
                {"role": "assistant", "content": text},
            ],
            "audio": {
                "format": "wav",
                "voice": voice_name or "mimo_default",
            },
        }
        resp = requests.post(api_url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        audio_data = data["choices"][0]["message"]["audio"]["data"]
        return base64.b64decode(audio_data)

    @AsyncService.register_service
    def convert(self, book_id: int, api_key: str, voice_desc: str, user_id: int,
                api_url: str = DEFAULT_CHAT_URL,
                model_name: str = DEFAULT_CHAT_MODEL,
                api_type: str = "chat_completions",
                voice_name: str = "",
                auth_type: str = "api-key") -> None:
        if not MimoTTSTool._convert_lock.acquire(blocking=False):
            logging.warning("[MimoTTSTool] Already running, skipping convert for book_id=%d", book_id)
            return

        task_id = self.create_task(progress_data={"status": "starting", "book_id": book_id})
        MimoTTSTool._last_task_id = task_id
        error_message = None
        book_title = "Unknown"

        try:
            books = self.db.get_data_as_dict(ids=[book_id])
            if not books:
                error_message = _("书籍不存在：ID=%d") % book_id
                return

            book = books[0]
            book_title = book.get("title", "Unknown")
            fmts = [f.upper() for f in (book.get("available_formats") or [])]
            if "EPUB" not in fmts:
                error_message = _("该书籍没有 EPUB 格式，无法转换")
                return

            epub_path = self.db.format_abspath(book_id, "EPUB", index_is_id=True)
            if not epub_path or not os.path.exists(epub_path):
                error_message = _("找不到 EPUB 文件")
                return

            self.update_task_progress(task_id, 5, {"status": "running", "stage": "parsing"})

            chapters = self._extract_chapters(epub_path)
            chapters = [ch for ch in chapters if ch.get("text", "").strip()]
            total_chapters = len(chapters)

            if total_chapters == 0:
                error_message = _("未从 EPUB 中提取到任何章节内容")
                return

            output_dir = os.path.join(AUDIO_OUTPUT_FOLDER, str(book_id))
            os.makedirs(output_dir, exist_ok=True)

            for idx, chapter in enumerate(chapters):
                progress = int(5 + (idx / total_chapters) * 90)
                self.update_task_progress(task_id, progress, {
                    "status": "running",
                    "stage": "converting",
                    "chapter": idx + 1,
                    "total": total_chapters,
                    "chapter_title": chapter.get("title", ""),
                })

                text = chapter.get("text", "").strip()
                if not text:
                    continue

                parts = self._split_text(text)
                for pidx, part in enumerate(parts):
                    safe_title = re.sub(r'[<>:"/\\|?*]', '_', chapter.get("title", f"ch{idx+1}"))
                    suffix = f"_part{pidx}" if len(parts) > 1 else ""
                    filename = f"{idx+1:04d}_{safe_title}{suffix}.wav"

                    try:
                        wav_data = self._synthesize(part, api_key, voice_desc,
                                                    api_url, model_name, api_type,
                                                    voice_name, auth_type)
                    except Exception as e:
                        logging.error("[MimoTTSTool] TTS failed for chapter %d part %d: %s", idx+1, pidx, e)
                        continue

                    filepath = os.path.join(output_dir, filename)
                    with open(filepath, "wb") as f:
                        f.write(wav_data)

            AudioBooksCache.async_update()

            self.update_task_progress(task_id, 100, {
                "status": "completed",
                "book_id": book_id,
                "total_chapters": total_chapters,
            })
            self.add_msg(user_id, "success", _("《%s》的有声书转换已完成，可在书籍详情页播放") % book_title)

        except Exception as err:
            error_message = str(err)
            self.add_msg(user_id, "danger", _("《%s》的有声书转换失败：%s") % (book_title, str(err)))
            logging.error("[MimoTTSTool] Convert failed for book_id=%d: %s", book_id, err)
            logging.error(traceback.format_exc())
        finally:
            self.complete_task(task_id, error_message=error_message)
            MimoTTSTool._convert_lock.release()
