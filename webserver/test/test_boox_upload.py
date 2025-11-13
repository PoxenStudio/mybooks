#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import os
import sys


class BooxUploader:
    """
    用于将文件上传到 BOOX 设备的类。
    """

    def __init__(self, file_path):
        """
        初始化 BooxUploader。

        :param file_path: 要上传的文件的路径。
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件未找到: {file_path}")
        self.file_path = file_path
        self.file_name = os.path.basename(file_path)

    def upload(self, host, port=8085):
        """
        执行文件上传。

        :param host: BOOX 设备的 IP 地址。
        :param port: BOOX 设备的端口号。
        :return: 服务器响应的 JSON 数据。
        """
        url = f"http://{host}:{port}/api/library/upload"

        # 根据请求体构造 multipart/form-data
        files = {
            'parent': (None, 'null'),
            'sender': (None, 'web'),
            'file': (self.file_name, open(self.file_path, 'rb'), 'application/epub+zip'),
        }

        response = requests.post(url, files=files)
        response.raise_for_status()  # 如果请求失败则抛出异常

        result = response.json()
        if result.get("code") != 0 or not result.get("successful"):
            raise Exception(f"上传失败: {result}")

        return result


def main():
    """主函数 - 处理命令行参数并上传文件"""
    if len(sys.argv) != 2:
        print("用法: python test_boox_upload.py <文件路径>")
        print("示例: python test_boox_upload.py /path/to/book.epub")
        return

    file_path = sys.argv[1]
    boox_host = "192.168.31.6"
    boox_port = 8085

    try:
        print(f"开始上传文件: {file_path} 到 BOOX 设备 {boox_host}:{boox_port}")
        uploader = BooxUploader(file_path)
        result = uploader.upload(boox_host, boox_port)

        print("上传成功!")
        print(result)

    except FileNotFoundError as e:
        print(f"错误: {e}")
    except requests.exceptions.RequestException as e:
        print(f"网络请求失败: {e}")
    except Exception as e:
        print(f"上传失败: {e}")


if __name__ == "__main__":
    main()
