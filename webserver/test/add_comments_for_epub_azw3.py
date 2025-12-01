#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import sys
import os
import shutil
import argparse

# Setup Calibre paths
path = os.environ.get('CALIBRE_PYTHON_PATH', '/Applications/calibre.app/Contents/MacOS/app/lib')
if path not in sys.path:
    sys.path.insert(0, path)

sys.resources_location = os.environ.get('CALIBRE_RESOURCES_PATH', '/Applications/calibre.app/Contents/Resources/resources')
sys.extensions_location = os.environ.get('CALIBRE_EXTENSIONS_PATH', '/Applications/calibre.app/Contents/Resources/app/plugins')
sys.executables_location = os.environ.get('CALIBRE_EXECUTABLES_PATH', '/Applications/calibre.app/Contents/MacOS')

try:
    from calibre.ebooks.metadata.meta import get_metadata, set_metadata
except ImportError:
    # Fallback for linux/other paths if the above mac-specific ones fail or if run in a different env
    # Try to find where calibre is
    try:
        import calibre
    except ImportError:
        print("Error: Could not import calibre. Please ensure you are running this with calibre-debug or have calibre in PYTHONPATH.")
        sys.exit(1)
    from calibre.ebooks.metadata.meta import get_metadata, set_metadata


class AddComment:
    def process(self, source_path, target_path, content):
        """
        Reads metadata from source_path, prepends content to comments,
        and saves the file to target_path with updated metadata.
        """
        if not os.path.exists(source_path):
            print(f"Error: Source file '{source_path}' does not exist.")
            return False

        # Determine file type
        ext = os.path.splitext(source_path)[1].lower().replace('.', '')
        if ext not in ['epub', 'azw3']:
            print(f"Error: Unsupported file format '{ext}'. Only epub and azw3 are supported.")
            return False

        try:
            # Copy source to target first
            shutil.copy2(source_path, target_path)

            # Open target file to read/write metadata
            # We need to open it in a way that set_metadata can use.
            # set_metadata usually expects a stream or path depending on implementation,
            # but based on 'check_calibre_meta.py' and general usage, passing a stream is safer for 'set_metadata'.
            # However, get_metadata also needs a stream.

            with open(target_path, 'r+b') as stream:
                # Read metadata
                mi = get_metadata(stream, stream_type=ext)

                # Prepare new comment
                original_comments = mi.comments if mi.comments else ""
                new_comments = f"<p>{content}</p><p>{original_comments}</p>"
                mi.comments = new_comments

                # Write metadata back
                # Note: set_metadata might seek to 0 or need stream at 0
                stream.seek(0)
                set_metadata(stream, mi, stream_type=ext)

            print(f"Successfully added comment to '{target_path}'")
            return True

        except Exception as e:
            print(f"Error processing file: {e}")
            if os.path.exists(target_path):
                os.remove(target_path)
            return False

def main():
    parser = argparse.ArgumentParser(description="Add content to the description of an epub or azw3 file.")
    parser.add_argument("source_file", help="Path to the source epub/azw3 file")
    parser.add_argument("target_file", help="Path to the output file")
    parser.add_argument("content", help="Content to add to the description")

    args = parser.parse_args()

    adder = AddComment()
    adder.process(args.source_file, args.target_file, args.content)

if __name__ == "__main__":
    main()
