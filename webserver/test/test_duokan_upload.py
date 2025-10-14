#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from uploader import DuokanUploader


def main():
    """主函数 - 处理命令行参数并上传文件"""
    import sys

    if len(sys.argv) != 2:
        print("用法: python test_duokan_upload.py <文件路径>")
        print("示例: python test_duokan_upload.py /path/to/book.epub")
        return

    file_path = sys.argv[1]
    server_url = "http://192.168.31.179:12121/files"

    try:
        print(f"开始上传文件: {file_path}")
        result = DuokanUploader(file_path).upload(server_url)

        print("上传成功!")
        print(result)

    except Exception as e:
        print(f"上传失败: {e}")


if __name__ == "__main__":
    main()
