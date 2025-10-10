#!/usr/bin/env python3

"""
This is the standard runscript for all of calibre's tools.
Do not modify it unless you know what you are doing.
"""

import os
import sys
import argparse
from tornado.options import define, options

define("path-calibre", default="/usr/lib/calibre", type=str, help="Path to calibre package.")
define("path-resources", default="/usr/share/calibre", type=str, help="Path to calibre resources.")
define("path-plugins", default="/usr/lib/calibre/calibre/plugins", type=str, help="Path to calibre plugins.")
define("path-bin", default="/usr/bin", type=str, help="Path to calibre binary programs.")


def extract_epub_cover(epub_path):
    """
    Extract the cover image from an EPUB file using Calibre's API.

    :param epub_path: Path to the EPUB file.
    """
    from calibre.ebooks.metadata.meta import get_metadata

    if not os.path.exists(epub_path):
        raise FileNotFoundError(f"EPUB file not found: {epub_path}")

    fmt = os.path.splitext(epub_path)[1]
    fmt = fmt[1:] if fmt else None
    if not fmt:
        return {"err": "params.filename", "msg": u"文件名不合法"}
    fmt = fmt.lower()
    print(f"Extracting cover from EPUB file: {epub_path}, fmt:{fmt}")

    # Extract metadata, including the cover
    with open(epub_path, "rb") as stream:
        metadata = get_metadata(stream, stream_type=fmt, use_libprs_metadata=True, force_read_metadata=True)

    # Check if a cover exists
    if metadata.cover_data is None:
        print("No cover found in the EPUB file.")
        return

    # Save the cover image
    output_path = os.path.splitext(epub_path)[0] + "_cover.jpg"
    with open(output_path, "wb") as cover_file:
        # cover_data is tuple(format, data)
        if isinstance(metadata.cover_data, tuple):
            print(f"Cover data content: {metadata.cover_data[0]}")
            cover_data = metadata.cover_data[1]
        else:
            cover_data = metadata.cover_data
        print(f"Cover data content: {len(cover_data)} bytes")
        cover_file.write(cover_data)
    print(f"Cover extracted and saved to: {output_path}")


def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Extract cover page from an EPUB file.")
    parser.add_argument(
        "epub_path",
        type=str,
        help="Path to the EPUB file to process.",
    )
    args = parser.parse_args()

    print(f"EPUB file path: {args.epub_path}")
    try:
        extract_epub_cover(args.epub_path)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    path = options.path_calibre
    print(f"Using Calibre path: {path}")
    if path not in sys.path:
        sys.path.insert(0, path)
    sys.resources_location = options.path_resources
    sys.extensions_location = options.path_plugins
    sys.executables_location = options.path_bin
    main()
