#!/usr/bin/env python3
import sys
import argparse
from mutagen.mp4 import MP4

def print_chapters(file_path):
    """
    Extracts and prints chapter information from an M4B file.
    """
    try:
        audio = MP4(file_path)
        if audio.chapters:
            print(f"Found {len(audio.chapters)} chapters in '{file_path}':")
            for i, chapter in enumerate(audio.chapters):
                title = getattr(chapter, 'title', f"Chapter {i+1}")
                start_seconds = getattr(chapter, 'start', 0)
                
                # Format time as HH:MM:SS
                hours = int(start_seconds // 3600)
                minutes = int((start_seconds % 3600) // 60)
                seconds = int(start_seconds % 60)
                
                if hours > 0:
                    start_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                else:
                    start_str = f"{minutes:02d}:{seconds:02d}"
                
                print(f"  [{start_str}] {title}")
        else:
            print(f"No chapters found in '{file_path}'.")
    except Exception as e:
        print(f"Error reading file '{file_path}': {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Extract chapters and manage playback position from an M4B file using mutagen.")
    parser.add_argument("audio_file", help="Path to the M4B audio file")
    
    args = parser.parse_args()
    print_chapters(args.audio_file)

if __name__ == "__main__":
    main()
