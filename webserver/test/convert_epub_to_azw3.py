#!/bin/python3
import os
import subprocess

current_dir = os.getcwd()

for filename in os.listdir(current_dir):
    if filename.lower().endswith('.epub'):
        epub_path = os.path.join(current_dir, filename)
        azw3_filename = os.path.splitext(filename)[0] + '.azw3'
        azw3_path = os.path.join(current_dir, azw3_filename)

        try:
            subprocess.run([
                'ebook-convert', epub_path, azw3_path,
                '--output-profile=kindle',
                '--embed-font-family=Lato',
                '--enable-heuristics'
            ], check=True)
            print(f"Conversion successful: {azw3_path}")
        except subprocess.CalledProcessError as e:
            print(f"Conversion failed: {epub_path}", e)
