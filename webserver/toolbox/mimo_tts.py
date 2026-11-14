import base64
import hashlib
import json
import logging
import os
import re
import stat
import threading
import traceback
from pathlib import Path
from typing import Optional

import requests

from webserver.handlers.audio import AudioBooksCache
from webserver.i18n import _
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver.toolbox import mimo_tts_lib
from webserver.toolbox.base_tool import BaseTool

DEFAULT_AUDIO_OUTPUT_FOLDER = "/data/books/audios/"
DEFAULT_CHAT_URL = "https://api.xiaomimimo.com/v1/chat/completions"
DEFAULT_CHAT_MODEL = "mimo-v2.5-tts"
VOICE_CLONE_MODEL = "mimo-v2.5-tts-voiceclone"
MAX_CHUNK_CHARS = 2000
MIN_WAV_SIZE = 44
PBKDF2_ITER = 100000
CONFIG_FILE = "api_config.enc"
KEY_FILE = ".mimo_key"
MAX_FILENAME_LEN = 120
MAX_CLONE_SIZE = 7 * 1024 * 1024  # 文档要求 base64 <= 10MB，原始文件限 7MB
CLONE_ALLOWED_EXT = (".mp3", ".wav")
CLONE_DIR_NAME = "clones"
PROMPT_FILE_NAME = "voice_prompts.json"
MAX_PROMPT_DESC_LEN = 2000
# 本轮生成的文件清单（隐藏文件）：续传/清理用——只认自己写过的文件，
# 绝不删用户放进音频目录的其它内容
AUDIO_MANIFEST_NAME = ".mimo_tts_manifest.json"

PRESET_VOICES = [
    {"id": "mimo_default", "name": "MiMo-默认", "lang": "zh", "gender": "female", "sample": "mimo_default.wav"},
    {"id": "冰糖", "name": "冰糖", "lang": "zh", "gender": "female", "sample": "bingtang.wav"},
    {"id": "茉莉", "name": "茉莉", "lang": "zh", "gender": "female", "sample": "moli.wav"},
    {"id": "苏打", "name": "苏打", "lang": "zh", "gender": "male", "sample": "souda.wav"},
    {"id": "白桦", "name": "白桦", "lang": "zh", "gender": "male", "sample": "baihua.wav"},
    {"id": "Mia", "name": "Mia", "lang": "en", "gender": "female", "sample": "Mia.wav"},
    {"id": "Chloe", "name": "Chloe", "lang": "en", "gender": "female", "sample": "Chloe.wav"},
    {"id": "Milo", "name": "Milo", "lang": "en", "gender": "male", "sample": "Milo.wav"},
    {"id": "Dean", "name": "Dean", "lang": "en", "gender": "male", "sample": "Dean.wav"},
]


class MimoTTSTool(BaseTool):
    service_item_name = "Mimo-TTS有声书"

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
            "name": "Mimo-TTS有声书",
            "description": "通过 TTS API（支持 MiMo TTS / OpenAI TTS 格式）将 EPUB / TXT 书籍合成为有声书（WAV格式），生成后可在线播放",
            "revision": "0.4.1",
            "author": "黏菌",
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
        # 设置密钥文件权限为仅所有者可读写 (0o600)
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass
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
                        voice_name: str, auth_type: str,
                        clone_voice: str = "") -> tuple[bool, str]:
        try:
            self._synthesize("测试语音合成。这是一个测试。",
                             api_key, voice_desc,
                             api_url, model_name, api_type,
                             voice_name, auth_type,
                             clone_voice=clone_voice)
            self.save_api_config({
                "api_key": api_key,
                "api_url": api_url,
                "model_name": model_name,
                "api_type": api_type,
                "voice_name": voice_name,
                "auth_type": auth_type,
                "voice_desc": voice_desc,
                "clone_voice": clone_voice,
            })
            return True, ""
        except Exception as e:
            return False, str(e)

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
                    voice_name: str, auth_type: str,
                    clone_voice: str = "") -> bytes:
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
            # 校验响应格式是否为音频
            content_type = resp.headers.get("Content-Type", "").lower()
            if content_type and not any(ct in content_type for ct in ["audio", "wav", "octet-stream", "mpeg"]):
                raise RuntimeError(_("API 返回非音频格式: %s") % content_type)
            return resp.content

        if clone_voice:
            voice_data = MimoTTSTool().build_clone_data_uri(clone_voice)
            if not voice_data:
                raise RuntimeError(_("克隆音色「%s」不存在，请重新上传") % clone_voice)
            model_name = VOICE_CLONE_MODEL
            voice = voice_data
        else:
            voice = voice_name or "mimo_default"

        payload = {
            "model": model_name,
            "messages": [
                {"role": "user", "content": voice_desc},
                {"role": "assistant", "content": text},
            ],
            "audio": {
                "format": "wav",
                "voice": voice,
            },
        }
        resp = requests.post(api_url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        audio_data = data["choices"][0]["message"]["audio"]["data"]
        return base64.b64decode(audio_data)

    # ── Filename sanitization ───────────────────────────────────

    @staticmethod
    def _sanitize_filename(title: str, fallback: str) -> str:
        if not title or not title.strip():
            title = fallback
        # 替换换行、制表符为空格
        title = re.sub(r'[\r\n\t]+', ' ', title)
        # 替换 Windows / Unix 非法字符
        title = re.sub(r'[<>:"/\\|?*]', '_', title)
        # 替换连续空格/下划线为单个
        title = re.sub(r'[ _]+', '_', title)
        # 去除首尾空格和下划线
        title = title.strip().strip('_')
        # 限制长度
        if len(title) > MAX_FILENAME_LEN:
            title = title[:MAX_FILENAME_LEN].rsplit('_', 1)[0]
        return title or fallback

    @classmethod
    def _chapter_filename(cls, index: int, title: str, part_index: int, part_count: int) -> str:
        """章节音频文件名：``0001_标题.wav``（长文再带 ``_partNNN``）。

        计划阶段与合成阶段共用同一函数，避免清理时算出的名字和实际写盘的
        名字不一致（不一致会误删刚生成的文件）。
        """
        safe_title = cls._sanitize_filename(title, f"ch{index + 1}")
        suffix = f"_part{part_index + 1:03d}" if part_count > 1 else ""
        return f"{index + 1:04d}_{safe_title}{suffix}.wav"

    # ── Audio manifest (resume / prune) ────────────────────────

    @staticmethod
    def _manifest_path(output_dir: str) -> str:
        return os.path.join(output_dir, AUDIO_MANIFEST_NAME)

    @classmethod
    def _read_manifest_files(cls, output_dir: str) -> Optional[set]:
        """读上一轮生成的文件清单；没有清单（0.4.0 及更早的目录）返回 None。"""
        try:
            with open(cls._manifest_path(output_dir), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        files = data.get("files") if isinstance(data, dict) else None
        if not isinstance(files, list):
            return None
        return {f for f in files if isinstance(f, str) and f}

    @classmethod
    def _write_manifest(cls, output_dir: str, fmt: str, files: set,
                        verify: bool = True) -> None:
        """把文件清单落盘：并入旧记录，可选校验文件是否真的存在。

        - 并入旧记录：本轮有分片失败时不清理旧音频，若清单只写本轮计划，
          这些旧文件的记录就永远丢失，之后再改名也删不掉（孤儿）。
        - ``verify=True``（收尾）时只留磁盘上真实存在的文件，避免「计划里有、
          实际没生成 / 已被清理」的名字留在册里；转换过程中的中途落盘传
          ``False``，省掉对整份清单的 stat。
        """
        previous = cls._read_manifest_files(output_dir) or set()
        merged = previous | set(files)
        if verify:
            merged = {f for f in merged if os.path.isfile(os.path.join(output_dir, f))}
        data = {"format": fmt, "files": sorted(merged)}
        tmp = cls._manifest_path(output_dir) + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, cls._manifest_path(output_dir))
        except OSError as e:
            logging.warning("[MimoTTSTool] 写入音频清单失败 %s: %s", output_dir, e)

    @classmethod
    def _prune_stale_audio(cls, output_dir: str, expected: set) -> int:
        """删掉上一轮生成、本轮计划外的音频（源格式切换 / 章节增删改名）。

        只删清单里记录过的文件——用户自己放进音频目录的文件不在清单内，不会
        被误删。返回删除数量。
        """
        previous = cls._read_manifest_files(output_dir)
        if previous is None:
            return 0
        removed = 0
        for fname in sorted(previous - expected):
            # 只处理同层文件名，防止清单被篡改成 ../ 之类的越界路径
            if os.path.basename(fname) != fname or fname.startswith("."):
                continue
            path = os.path.join(output_dir, fname)
            if not os.path.isfile(path):
                continue
            try:
                os.remove(path)
                removed += 1
            except OSError as e:
                logging.warning("[MimoTTSTool] 删除旧音频失败 %s: %s", path, e)
        if removed:
            logging.info("[MimoTTSTool] 清理 %d 个本轮计划外的旧音频：%s", removed, output_dir)
        return removed

    @staticmethod
    def _drop_audio_zip(output_dir: str) -> None:
        """删掉打包下载的缓存 zip：音频集合变了让它重建。

        ``AudioCollection`` 是「zip 存在就复用」，不删的话新增/改名的章节
        不会出现在打包下载里。删失败只记日志（Windows 上可能被占用）。
        """
        try:
            names = os.listdir(output_dir)
        except OSError as e:
            logging.warning("[MimoTTSTool] 列举音频目录失败 %s: %s", output_dir, e)
            return
        for fname in names:
            if fname.startswith("audio_collection_") and fname.endswith(".zip"):
                try:
                    os.remove(os.path.join(output_dir, fname))
                except OSError as e:
                    logging.warning("[MimoTTSTool] 删除过期音频包失败 %s: %s", fname, e)

    @staticmethod
    def _clean_partial_files(output_dir: str) -> None:
        """清掉上一轮中断留下的 ``*.wav.part``（全局转换锁保证没有并发写）。"""
        try:
            names = os.listdir(output_dir)
        except OSError:
            return
        for fname in names:
            if fname.endswith(".wav.part"):
                try:
                    os.remove(os.path.join(output_dir, fname))
                except OSError:
                    pass

    # ── Voice clone storage ────────────────────────────────────

    def _clones_dir(self) -> str:
        d = os.path.join(self.get_work_dir(""), CLONE_DIR_NAME)
        os.makedirs(d, exist_ok=True)
        return d

    @staticmethod
    def _sanitize_clone_name(name: str) -> str:
        name = re.sub(r'[^\w\u4e00-\u9fff\-]', '', name.strip()) if name else ""
        if len(name) > 50:
            name = name[:50]
        return name

    def save_clone_voice(self, name: str, ext: str, data: bytes,
                         overwrite: bool = True) -> Optional[str]:
        name = self._sanitize_clone_name(name)
        if not name:
            raise ValueError(_("克隆音色名称不能为空，且只能包含中英文、数字、下划线和连字符"))
        ext = ext.lower()
        if ext not in CLONE_ALLOWED_EXT:
            raise ValueError(_("仅支持 MP3 / WAV 格式"))
        if len(data) > MAX_CLONE_SIZE:
            raise ValueError(_("音频文件过大（上限 7MB）"))
        path = os.path.join(self._clones_dir(), f"{name}{ext}")
        if os.path.exists(path) and not overwrite:
            raise ValueError(_("同名克隆音色已存在：%s") % name)
        with open(path, "wb") as f:
            f.write(data)
        return name

    def list_clone_voices(self) -> list[dict]:
        d = self._clones_dir()
        clones = []
        for fname in sorted(os.listdir(d)):
            fpath = os.path.join(d, fname)
            if not os.path.isfile(fpath):
                continue
            stem, ext = os.path.splitext(fname)
            if ext.lower() not in CLONE_ALLOWED_EXT:
                continue
            st = os.stat(fpath)
            clones.append({
                "name": stem,
                "ext": ext.lower().lstrip("."),
                "size": st.st_size,
                "mtime": st.st_mtime,
            })
        return clones

    def get_clone_voice_path(self, name: str) -> Optional[str]:
        name = self._sanitize_clone_name(name)
        if not name:
            return None
        candidates = os.path.join(self._clones_dir(), name)
        for ext in CLONE_ALLOWED_EXT:
            p = candidates + ext
            if os.path.isfile(p):
                return p
        return None

    def delete_clone_voice(self, name: str) -> bool:
        path = self.get_clone_voice_path(name)
        if not path:
            return False
        try:
            os.remove(path)
            return True
        except OSError:
            return False

    def build_clone_data_uri(self, name: str) -> Optional[str]:
        path = self.get_clone_voice_path(name)
        if not path:
            return None
        ext = Path(path).suffix.lower()
        mime = "audio/mpeg" if ext == ".mp3" else "audio/wav"
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime};base64,{b64}"

    # ── Voice prompt library ───────────────────────────────────

    def _prompts_path(self) -> str:
        return os.path.join(self.get_work_dir(""), PROMPT_FILE_NAME)

    def _load_prompts(self) -> dict:
        path = self._prompts_path()
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_prompts(self, data: dict) -> None:
        path = self._prompts_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def list_voice_prompts(self) -> list[dict]:
        data = self._load_prompts()
        prompts = []
        for name, desc in data.items():
            if isinstance(desc, str) and desc.strip():
                prompts.append({"name": name, "desc": desc})
        prompts.sort(key=lambda x: x["name"].lower())
        return prompts

    def save_voice_prompt(self, name: str, desc: str,
                          overwrite: bool = True) -> str:
        name = self._sanitize_clone_name(name)
        if not name:
            raise ValueError(_("提示词名称不能为空，且只能包含中英文、数字、下划线和连字符"))
        desc = (desc or "").strip()
        if not desc:
            raise ValueError(_("提示词内容不能为空"))
        if len(desc) > MAX_PROMPT_DESC_LEN:
            raise ValueError(_("提示词内容过长（上限 %d 字）") % MAX_PROMPT_DESC_LEN)
        data = self._load_prompts()
        if name in data and not overwrite:
            raise ValueError(_("同名提示词已存在：%s") % name)
        data[name] = desc
        self._save_prompts(data)
        return name

    def delete_voice_prompt(self, name: str) -> bool:
        name = self._sanitize_clone_name(name)
        if not name:
            return False
        data = self._load_prompts()
        if name not in data:
            return False
        del data[name]
        self._save_prompts(data)
        return True

    # ── Convert (with resume) ───────────────────────────────────

    @AsyncService.register_service
    def convert(self, book_id: int, api_key: str, voice_desc: str, user_id: int,
                api_url: str = DEFAULT_CHAT_URL,
                model_name: str = DEFAULT_CHAT_MODEL,
                api_type: str = "chat_completions",
                voice_name: str = "",
                auth_type: str = "api-key",
                clone_voice: str = "") -> None:
        if not MimoTTSTool._convert_lock.acquire(blocking=False):
            logging.warning("[MimoTTSTool] Already running, skipping convert for book_id=%d", book_id)
            return

        task_id = self.create_task(progress_data={"status": "starting", "book_id": book_id})
        MimoTTSTool._last_task_id = task_id
        error_message = None
        book_title = "Unknown"

        try:
            books = self.api.calibre.get_data_as_dict([book_id])
            if not books:
                raise RuntimeError(_("书籍不存在：ID=%d") % book_id)

            book = books[0]
            book_title = book.get("title", "Unknown")
            fmts = [f.upper() for f in (book.get("available_formats") or [])]
            fmt = next((f for f in ("EPUB", "TXT") if f in fmts), None)
            if fmt is None:
                raise RuntimeError(_("该书籍没有 EPUB / TXT 格式，无法转换"))

            src_path = self.api.calibre.format_abspath(book_id, fmt)
            if not src_path or not os.path.exists(src_path):
                raise RuntimeError(_("找不到 %s 文件，可能已被移除") % fmt)
            logging.info("[MimoTTSTool] Converting book_id=%d fmt=%s", book_id, fmt)

            self.update_task_progress(task_id, 5, {"status": "running", "stage": "parsing"})

            if fmt == "EPUB":
                chapters = mimo_tts_lib.extract_epub_chapters(src_path)
            else:
                chapters = mimo_tts_lib.extract_txt_chapters(src_path)
            chapters = [ch for ch in chapters if ch.get("text", "").strip()]
            total_chapters = len(chapters)

            if total_chapters == 0:
                raise RuntimeError(_("未从书籍中提取到任何章节内容"))

            audio_output_folder = self.api.settings.get("audio_output_folder", DEFAULT_AUDIO_OUTPUT_FOLDER)
            output_dir = os.path.join(audio_output_folder, str(book_id))
            os.makedirs(output_dir, exist_ok=True)

            # Save the cover image to the output dir
            try:
                cover_data = self.api.calibre.cover(book_id)
                if cover_data:
                    cover_path = os.path.join(output_dir, "cover.jpg")
                    with open(cover_path, "wb") as f:
                        f.write(cover_data)
                    logging.info(f"[MimoTTSTool]Saved cover image for book {book_id} to {cover_path}")
            except Exception as e:
                logging.error(f"[MimoTTSTool]Failed to save cover image for book {book_id}: {e}")

            existing = set()
            try:
                for fname in os.listdir(output_dir):
                    fpath = os.path.join(output_dir, fname)
                    if fname.endswith(".wav") and os.path.isfile(fpath) and os.path.getsize(fpath) >= MIN_WAV_SIZE:
                        existing.add(fname)
            except OSError as e:
                logging.warning("[MimoTTSTool] 列举音频目录失败 %s: %s", output_dir, e)

            self._clean_partial_files(output_dir)
            previous_files = self._read_manifest_files(output_dir)

            # 先按「本轮计划」算出每个分片的文件名：用于清理旧音频（源格式从
            # EPUB 换成 TXT、章节增删改名后，旧文件会和新文件并存，播放列表
            # 按目录全量列举 → 章节重复/混杂），也顺带得到总片数
            plans = []
            expected_files = set()
            for idx, chapter in enumerate(chapters):
                text = chapter.get("text", "").strip()
                if not text:
                    continue
                parts = self._split_text(text)
                names = [self._chapter_filename(idx, chapter.get("title", ""), pidx, len(parts))
                         for pidx in range(len(parts))]
                expected_files.update(names)
                plans.append((idx, chapter, parts, names))

            skipped = 0
            failed_parts = 0
            total_parts_all = sum(len(parts) for _, _, parts, _ in plans)
            completed_parts = 0
            written = set()

            for idx, chapter, parts, names in plans:
                chapter_written = set()
                for pidx, (part, filename) in enumerate(zip(parts, names)):
                    if filename in existing:
                        skipped += 1
                        completed_parts += 1
                        continue

                    try:
                        wav_data = self._synthesize(part, api_key, voice_desc,
                                                    api_url, model_name, api_type,
                                                    voice_name, auth_type,
                                                    clone_voice=clone_voice)
                    except Exception as e:
                        logging.error("[MimoTTSTool] TTS failed for chapter %d part %d: %s", idx+1, pidx+1, e)
                        failed_parts += 1
                        continue

                    filepath = os.path.join(output_dir, filename)
                    # 先写 .part 再原子改名：中途失败（磁盘满 / 进程被杀）不会留下
                    # 一个 >= MIN_WAV_SIZE 的半截文件被下一轮当成「已完成」复用
                    tmp_path = filepath + ".part"
                    with open(tmp_path, "wb") as f:
                        f.write(wav_data)
                    os.replace(tmp_path, filepath)
                    written.add(filename)
                    chapter_written.add(filename)
                    completed_parts += 1

                # 按已完成 part 数 / 总 part 数 计算进度
                progress = int(5 + (completed_parts / max(total_parts_all, 1)) * 90)
                self.update_task_progress(task_id, min(progress, 95), {
                    "status": "running",
                    "stage": "converting",
                    "chapter": idx + 1,
                    "total": total_chapters,
                    "chapter_title": chapter.get("title", ""),
                })
                # 每章结束都把已写出的文件记进清单（不校验存在性，省 stat）：
                # 进程被杀时这一轮写出的文件也在册，下一轮才清得掉
                if chapter_written:
                    self._write_manifest(output_dir, fmt, chapter_written, verify=False)

            # 全部成功后才清理旧音频：本轮有失败时保留旧文件，别让用户两头落空
            if failed_parts == 0:
                self._prune_stale_audio(output_dir, expected_files)
            # 音频集合变了（新增/改名/删除）就让打包下载的缓存 zip 重建
            if previous_files != expected_files:
                self._drop_audio_zip(output_dir)
            self._write_manifest(output_dir, fmt, written | (expected_files & existing))

            AudioBooksCache.async_update()

            self.update_task_progress(task_id, 100, {
                "status": "completed",
                "book_id": book_id,
                "total_chapters": total_chapters,
            })

            if failed_parts > 0:
                self.add_msg(user_id, "warning",
                             _("《%s》的有声书转换已完成（%d 个片段失败），可在书籍详情页查看") % (book_title, failed_parts))
            elif skipped > 0:
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


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python -m webserver.toolbox.mimo_tts <epub_or_txt_path>")
        sys.exit(1)

    src_path = sys.argv[1]
    if src_path.lower().endswith(".txt"):
        chapters = mimo_tts_lib.extract_txt_chapters(src_path)
    else:
        chapters = mimo_tts_lib.extract_epub_chapters(src_path)
    print(f"Extracted {len(chapters)} chapters from {src_path}")
    for i, ch in enumerate(chapters):
        print(f"[{i}] {ch['title']!r} ({len(ch['text'])} chars)")
