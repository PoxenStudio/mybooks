import base64
import hashlib
import json
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
MIN_WAV_SIZE = 44
PBKDF2_ITER = 100000
CONFIG_FILE = "api_config.enc"
KEY_FILE = ".mimo_key"


class MimoTTSTool(BaseTool):
    service_item_name = "TTS有声书"

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
            "description": "通过 TTS API（支持 MiMo Chat / OpenAI TTS 格式）将 EPUB 书籍合成为有声书（WAV格式），目前仅支持 EPUB 格式，生成后可在线播放",
            "revision": "0.3.0",
            "author": "MyBooks",
            "publish_date": "2026-07-21",
        }

    # ── Encryption helpers ──────────────────────────────────────

    def _config_dir(self) -> str:
        return self.get_work_dir("")

    def _key_path(self) -> str:
        return os.path.join(self._config_dir(), KEY_FILE)

    def _config_path(self) -> str:
        return os.path.join(self._config_dir(), CONFIG_FILE)

    def _ensure_key(self) -> bytes:
        path = self._key_path()
        if os.path.exists(path) and os.path.getsize(path) == 32:
            with open(path, "rb") as f:
                return f.read()
        key = os.urandom(32)
        os.makedirs(self._config_dir(), exist_ok=True)
        with open(path, "wb") as f:
            f.write(key)
        return key

    @staticmethod
    def _derive_key(master: bytes, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", master, salt, PBKDF2_ITER, dklen=32)

    def _encrypt(self, data: bytes) -> str:
        master = self._ensure_key()
        salt = os.urandom(16)
        key = self._derive_key(master, salt)
        iv = os.urandom(16)
        keystream = b""
        pos = 0
        while len(keystream) < len(data):
            keystream += hashlib.sha256(key + iv + pos.to_bytes(4, "big")).digest()
            pos += 1
        cipher = bytes(a ^ b for a, b in zip(data, keystream[:len(data)]))
        return base64.b64encode(salt + iv + cipher).decode()

    def _decrypt(self, token: str) -> Optional[bytes]:
        master = self._ensure_key()
        raw = base64.b64decode(token)
        if len(raw) < 32:
            return None
        salt, iv, cipher = raw[:16], raw[16:32], raw[32:]
        key = self._derive_key(master, salt)
        keystream = b""
        pos = 0
        while len(keystream) < len(cipher):
            keystream += hashlib.sha256(key + iv + pos.to_bytes(4, "big")).digest()
            pos += 1
        return bytes(a ^ b for a, b in zip(cipher, keystream[:len(cipher)]))

    # ── Config persistence ──────────────────────────────────────

    def save_api_config(self, config: dict) -> None:
        token = self._encrypt(json.dumps(config).encode())
        with open(self._config_path(), "w") as f:
            f.write(token)

    def load_api_config(self) -> Optional[dict]:
        path = self._config_path()
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                token = f.read().strip()
            decrypted = self._decrypt(token)
            if decrypted is None:
                return None
            return json.loads(decrypted.decode())
        except Exception:
            return None

    def clear_api_config(self) -> None:
        path = self._config_path()
        if os.path.exists(path):
            os.remove(path)

    # ── Test connection ─────────────────────────────────────────

    def test_connection(self, api_key: str, voice_desc: str,
                        api_url: str, model_name: str, api_type: str,
                        voice_name: str, auth_type: str) -> tuple[bool, str]:
        try:
            self._synthesize("测试语音合成。这是一个测试。",
                             api_key, voice_desc,
                             api_url, model_name, api_type,
                             voice_name, auth_type)
            self.save_api_config({
                "api_key": api_key,
                "api_url": api_url,
                "model_name": model_name,
                "api_type": api_type,
                "voice_name": voice_name,
                "auth_type": auth_type,
                "voice_desc": voice_desc,
            })
            return True, ""
        except Exception as e:
            return False, str(e)

    # ── EPUB parsing ────────────────────────────────────────────

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

    # ── Text splitting ──────────────────────────────────────────

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

    # ── TTS synthesis ───────────────────────────────────────────

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

    # ── Convert (with resume) ───────────────────────────────────

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

            existing = set()
            if os.path.isdir(output_dir):
                for fname in os.listdir(output_dir):
                    fpath = os.path.join(output_dir, fname)
                    if fname.endswith(".wav") and os.path.isfile(fpath) and os.path.getsize(fpath) >= MIN_WAV_SIZE:
                        existing.add(fname)

            skipped = 0
            for idx, chapter in enumerate(chapters):
                text = chapter.get("text", "").strip()
                if not text:
                    continue

                parts = self._split_text(text)
                for pidx, part in enumerate(parts):
                    safe_title = re.sub(r'[<>:"/\\|?*]', '_', chapter.get("title", f"ch{idx+1}"))
                    suffix = f"_part{pidx}" if len(parts) > 1 else ""
                    filename = f"{idx+1:04d}_{safe_title}{suffix}.wav"

                    if filename in existing:
                        skipped += 1
                        continue

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

                chapters_done = sum(1 for i in range(idx + 1)
                                    if chapters[i].get("text", "").strip())
                progress = int(5 + (chapters_done / total_chapters) * 90)
                self.update_task_progress(task_id, min(progress, 95), {
                    "status": "running",
                    "stage": "converting",
                    "chapter": idx + 1,
                    "total": total_chapters,
                    "chapter_title": chapter.get("title", ""),
                })

            AudioBooksCache.async_update()

            self.update_task_progress(task_id, 100, {
                "status": "completed",
                "book_id": book_id,
                "total_chapters": total_chapters,
            })

            if skipped > 0:
                self.add_msg(user_id, "success",
                             _("《%s》的有声书转换已完成（续传跳过 %d 个已有文件），可在书籍详情页播放") % (book_title, skipped))
            else:
                self.add_msg(user_id, "success",
                             _("《%s》的有声书转换已完成，可在书籍详情页播放") % book_title)

        except Exception as err:
            error_message = str(err)
            self.add_msg(user_id, "danger", _("《%s》的有声书转换失败：%s") % (book_title, str(err)))
            logging.error("[MimoTTSTool] Convert failed for book_id=%d: %s", book_id, err)
            logging.error(traceback.format_exc())
        finally:
            self.complete_task(task_id, error_message=error_message)
            MimoTTSTool._convert_lock.release()
