#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from uploader import PureLibroUploader


def main():
    """主函数 - 处理命令行参数并上传文件"""
    import sys

    if len(sys.argv) != 2:
        print("用法: python test_purelibro_upload.py <文件路径>")
        print("示例: python test_purelibro_upload.py /path/to/book.epub")
        return

    file_path = sys.argv[1]
    server_url = "http://10.42.0.1"

    try:
        print(f"开始上传文件: {file_path}")
        result = PureLibroUploader(file_path).upload(server_url)

        print("上传成功!")
        print(result)

    except Exception as e:
        print(f"上传失败: {e}")


if __name__ == "__main__":
    main()
