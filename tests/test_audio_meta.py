import sys
import mutagen
import logging


def _extract_audio_metadata(audio_path, fallback_title):
    try:
        audio = mutagen.File(audio_path, easy=True)
        if audio is None:
            logging.warning("Failed to open audio file")
            return fallback_title, None
        title = None
        author = None
        if hasattr(audio, "tags") and audio.tags:
            title_tag = audio.tags.get("album") or audio.tags.get("title")
            author_tag = audio.tags.get("artist") or audio.tags.get("albumartist")
            if title_tag:
                title = str(title_tag[0]).strip() if isinstance(title_tag, list) else str(title_tag).strip()
            if author_tag:
                author = str(author_tag[0]).strip() if isinstance(author_tag, list) else str(author_tag).strip()
        
        # Fallback for some m4b files (e.g. lavf) where easy=True doesn't map the tags
        if not title or not author:
            raw_audio = mutagen.File(audio_path, easy=False)
            if hasattr(raw_audio, "tags") and raw_audio.tags:
                if not title:
                    title_tag = raw_audio.tags.get("\x00\x00\x00\x01")
                    if title_tag:
                        title = str(title_tag[0]).strip() if isinstance(title_tag, list) else str(title_tag).strip()
                if not author:
                    author_tag = raw_audio.tags.get("\x00\x00\x00\x02")
                    if author_tag:
                        author = str(author_tag[0]).strip() if isinstance(author_tag, list) else str(author_tag).strip()

        if title or author:
            logging.info("[AUDIO_IMPORT] Extracted metadata from %s: title=%s, author=%s", audio_path, title, author)
        else:
            logging.warning("Not found any tags in %s", audio_path)
        return title or fallback_title, author
    except Exception as e:
        logging.warning("[AUDIO_IMPORT] Failed to read audio metadata from %s: %s", audio_path, e)
        return fallback_title, None


if __name__ == "__main__":
    audio_path = "/Volumes/data/workspace/talebook/data/books/imports/audiobooks/Atlas Shrugged/650-AtlasShrugged.m4b"
    if len(sys.argv) > 1:
        audio_path = sys.argv[1]
    title, author = _extract_audio_metadata(audio_path, "Atlas Shrugged")
    print(f"title: {title}")
    print(f"author: {author}")
