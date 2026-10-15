"""Generate a sample MP3 with the project's Edge TTS provider for manual debugging.

Run from the repository root:
    python tests/edge_tts_debug.py --text "你好，这是语音测试。" --output /tmp/edge-test.mp3
"""

import argparse
import asyncio
from pathlib import Path
import sys

EPUB_TO_AUDIO_DIR = Path(__file__).resolve().parents[1] / "webserver" / "epub_to_audio"
sys.path.insert(0, str(EPUB_TO_AUDIO_DIR))

from audiobook_generator.tts_providers.edge_tts_provider import CommWithPauses  # noqa: E402


async def generate_audio(text: str, voice: str, output: Path) -> None:
    communicator = CommWithPauses(
        text=text,
        voice_name=voice,
        break_string=" @BRK#",
    )
    audio = await communicator.get_audio_stream()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(audio.getvalue())
    print(f"Generated {output} ({output.stat().st_size} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manually test Edge TTS audio generation.")
    parser.add_argument("--text", default="你好，这是 MyBooks 的 Edge TTS 测试。")
    parser.add_argument("--voice", default="zh-CN-YunxiNeural")
    parser.add_argument("--output", type=Path, default=Path("edge_tts_debug.mp3"))
    args = parser.parse_args()

    asyncio.run(generate_audio(args.text, args.voice, args.output))


if __name__ == "__main__":
    main()
