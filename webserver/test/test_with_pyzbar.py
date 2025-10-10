#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Barcode recognition using pyzbar.
Usage: python test_with_pyzbar.py <image_path>
"""

import sys
from pyzbar.pyzbar import decode
from PIL import Image


def main():
    if len(sys.argv) != 2:
        print("Usage: python test_with_pyzbar.py <image_path>")
        sys.exit(1)
    image_path = sys.argv[1]
    try:
        img = Image.open(image_path)
    except Exception as e:
        print(f"Failed to open image: {e}")
        sys.exit(1)

    decoded = decode(img)
    if not decoded:
        print("No barcode found.")
        return
    for obj in decoded:
        data = obj.data.decode('utf-8')
        print(f"Type: {obj.type}, Data: {data}")


if __name__ == '__main__':
    main()
