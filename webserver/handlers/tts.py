#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

"""
Server-side HTTPS proxy for Edge (Microsoft) TTS.

Mirrors the myreader client's own `/api/tts/edge` route: the browser can't
set the Origin/User-Agent/Sec-MS-GEC headers that speech.platform.bing.com's
wss endpoint expects (native WebSocket doesn't allow overriding them), so
Microsoft's server frequently blocks direct browser connections. Running the
`edge_tts` client here (already a dependency of epub_to_audio) avoids that:
this handler does the real wss call server-side and streams the resulting
MP3 back over plain HTTPS, carrying word-boundary timings in a response
header for read-aloud highlighting.
"""

import json
import logging
import re

import tornado

from webserver import loader
from webserver.handlers.base import BaseHandler

CONF = loader.get_settings()

# Keep in sync with WORD_BOUNDARIES_HEADER in myreader's src/libs/edgeTTS.ts.
WORD_BOUNDARIES_HEADER = "X-TTS-Word-Boundaries"
# Same cap as the Next.js route: oversized header values get dropped by
# proxies, so skip it rather than risk breaking delivery.
MAX_BOUNDARIES_HEADER_LEN = 8192


def _rate_to_percent(rate) -> str:
    """myreader sends `rate` as an SSML prosody-style multiplier (1.0 =
    normal, 0.5 = half speed, 2.0 = double speed); edge_tts.Communicate wants
    a '+N%'/'-N%' delta string instead."""
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        rate = 1.0
    percent = round((rate - 1.0) * 100)
    return f"{percent:+d}%"


def _lang_from_voice(voice: str) -> str:
    match = re.match(r"^([a-z]{2}-[A-Z]{2})", voice)
    return match.group(1) if match else "en-US"


class EdgeTTSProxy(BaseHandler):
    """Handles both the voice listing (GET) and the synthesis request (POST)
    at the single `/api/tts/edge` path, matching the Next.js route's shape."""

    def _authorized(self) -> bool:
        # Same guest-access convention as AudioFile: TTS is treated as read
        # access to the book's content, so it follows ALLOW_GUEST_READ too.
        if CONF.get("ALLOW_GUEST_READ", False):
            return True
        return bool(self.current_user)

    async def get(self):
        if not self._authorized():
            self.set_status(403)
            self.write({"error": "Not authenticated"})
            return

        try:
            import edge_tts

            lang = (self.get_argument("lang", "") or "").lower()
            proxy = CONF.get("BOOK2AUDIO_PROXY", None)
            voices = await edge_tts.list_voices(proxy=proxy)
            if lang:
                voices = [v for v in voices if lang in v["Locale"].lower()]

            self.write(
                {
                    "voices": [
                        {
                            "id": v["ShortName"],
                            "name": v["FriendlyName"],
                            "language": v["Locale"],
                        }
                        for v in voices
                    ]
                }
            )
        except Exception as e:
            logging.error("Failed to list Edge TTS voices: %s", e)
            self.set_status(500)
            self.write(
                {"error": {"message": "Failed to list voices", "type": "internal_error"}}
            )

    async def post(self):
        if not self._authorized():
            self.set_status(403)
            self.write({"error": "Not authenticated"})
            return

        try:
            body = tornado.escape.json_decode(self.request.body)
        except Exception:
            self.set_status(400)
            self.write(
                {"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}}
            )
            return

        text = body.get("input")
        voice = body.get("voice")
        rate = body.get("rate")
        lang = body.get("lang")

        if not text or not isinstance(text, str):
            self.set_status(400)
            self.write(
                {
                    "error": {
                        "message": 'Missing or invalid "input" field',
                        "type": "invalid_request_error",
                    }
                }
            )
            return
        if not voice or not isinstance(voice, str):
            self.set_status(400)
            self.write(
                {
                    "error": {
                        "message": 'Missing or invalid "voice" field',
                        "type": "invalid_request_error",
                    }
                }
            )
            return

        lang = lang or _lang_from_voice(voice)
        rate_str = _rate_to_percent(rate if rate is not None else 1.0)

        try:
            import edge_tts

            proxy = CONF.get("BOOK2AUDIO_PROXY", None)
            communicate = edge_tts.Communicate(
                text,
                voice,
                rate=rate_str,
                boundary="WordBoundary",
                proxy=proxy,
            )

            audio_chunks = []
            boundaries = []
            async for message in communicate.stream():
                if message["type"] == "audio":
                    audio_chunks.append(message["data"])
                elif message["type"] == "WordBoundary":
                    boundaries.append(
                        {
                            "offset": message["offset"],
                            "duration": message["duration"],
                            "text": message["text"],
                        }
                    )

            audio_bytes = b"".join(audio_chunks)
            if not audio_bytes:
                raise RuntimeError("No audio data received from Edge TTS")

            self.set_header("Content-Type", "audio/mpeg")
            self.set_header("Content-Length", str(len(audio_bytes)))

            # Percent-encode so the header stays ASCII-safe (boundary `text`
            # can be any script); the client reverses it with
            # decodeURIComponent, which only cares about %XX sequences, so it
            # doesn't matter that Python's quote() escapes a slightly
            # different character set than JS's encodeURIComponent. Use
            # compact separators and plus=False so spaces become %20 rather
            # than '+' (decodeURIComponent would leave a literal '+' alone).
            compact_json = json.dumps(boundaries, ensure_ascii=False, separators=(",", ":"))
            serialized = tornado.escape.url_escape(compact_json, plus=False)
            if len(serialized) <= MAX_BOUNDARIES_HEADER_LEN:
                self.set_header(WORD_BOUNDARIES_HEADER, serialized)

            self.write(audio_bytes)
        except Exception as e:
            logging.error("Edge TTS proxy failed: %s", e)
            self.set_status(500)
            self.write(
                {"error": {"message": str(e), "type": "internal_error"}}
            )


def routes():
    return [
        (r"/api/tts/edge", EdgeTTSProxy),
    ]
