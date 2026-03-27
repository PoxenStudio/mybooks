#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import sys
import os

# Setup Calibre paths
path = os.environ.get('CALIBRE_PYTHON_PATH', '/usr/lib/calibre')
if path not in sys.path:
    sys.path.insert(0, path)

sys.resources_location = os.environ.get('CALIBRE_RESOURCES_PATH', '/usr/share/calibre')
sys.extensions_location = os.environ.get('CALIBRE_EXTENSIONS_PATH', '/usr/lib/calibre/calibre/plugins')
sys.executables_location = os.environ.get('CALIBRE_EXECUTABLES_PATH', '/usr/bin')


try:
    from calibre.db.legacy import LibraryDatabase
except ImportError:
    print("Error: Could not import calibre. Please ensure you are running this in an environment with calibre installed.")
    sys.exit(1)

def ascii_text(orig):
    from calibre.utils.localization import _, get_udc
    udc = get_udc()
    try:
        ascii = udc.decode(orig)
    except Exception:
        if isinstance(orig, str):
            orig = orig.encode('ascii', 'replace')
        ascii = orig.decode(preferred_encoding, 'replace')
    if isinstance(ascii, bytes):
        ascii = ascii.decode('ascii', 'replace')
    return ascii

def main():
    print("Testing ASCII conversion...")
    test_strings = [
        "不太多，不太少"
    ]
    for s in test_strings:
        ascii = ascii_text(s)
        print(f"Original: {s} -> ASCII: {ascii}")


if __name__ == "__main__":
    main()
