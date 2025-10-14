#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import requests
from pathlib import Path
from requests_toolbelt.multipart.encoder import MultipartEncoder


def upload_file_to_ireader(file_path, server_url="http://192.168.31.179:10123/?action=addBook"):
    """
    上传文件到iReader服务器

    Args:
        file_path (str): 要上传的文件路径
        server_url (str): 服务器URL

    Returns:
        dict: 包含上传结果的字典

    Raises:
        ValueError: 当文件扩展名不是epub或pdf时
        FileNotFoundError: 当文件不存在时
        requests.exceptions.RequestException: 当网络请求失败时
    """
    # 检查文件是否存在
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    file_path = Path(file_path)
    file_extension = file_path.suffix.lower()
    filename = file_path.name

    if file_extension not in ['.epub', '.pdf']:
        raise ValueError(f"不支持的文件格式: {file_extension}, 只支持 .epub 和 .pdf 文件")

    if file_extension == '.epub':
        content_type = 'application/epub+zip'
    elif file_extension == '.pdf':
        content_type = 'application/pdf'

    try:
        with open(file_path, 'rb') as f:
            m = MultipartEncoder(
                fields={
                    'Filename': filename,
                    'Filedata': (filename, f, content_type),
                    'Upload': 'Submit Query'
                }
            )
            headers = {'Content-Type': 'application/octet-stream'}
            response = requests.post(
                server_url,
                data=m,
                headers=headers,
                timeout=60
            )
            response.raise_for_status()
            result = {
                'success': True,
                'status_code': response.status_code,
                'filename': filename,
                'file_size': file_path.stat().st_size,
                'content_type': content_type
            }
            try:
                result['response_data'] = response.json()
            except Exception:
                result['response_text'] = response.text
            return result
    except requests.exceptions.Timeout as e:
        print(f"上传超时: {file_path}\n详细信息: {e}")
        raise requests.exceptions.RequestException(f"上传超时: {file_path}\n详细信息: {e}")
    except requests.exceptions.ConnectionError as e:
        print(f"连接服务器失败: {server_url}\n详细信息: {e}")
        raise requests.exceptions.RequestException(f"连接服务器失败: {server_url}\n详细信息: {e}")
    except requests.exceptions.HTTPError as e:
        print(f"HTTP错误: {e.response.status_code} - {e.response.text}")
        raise requests.exceptions.RequestException(f"HTTP错误: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        print(f"上传失败: {str(e)}")
        raise requests.exceptions.RequestException(f"上传失败: {str(e)}")


def main():
    """主函数 - 处理命令行参数并上传文件"""
    import sys
    if len(sys.argv) != 2:
        print("用法: python test_ireader_upload.py <文件路径>")
        print("示例: python test_ireader_upload.py /path/to/book.epub")
        return
    file_path = sys.argv[1]
    try:
        print(f"开始上传文件: {file_path}")
        result = upload_file_to_ireader(file_path)
        print("上传成功!")
        print(f"文件名: {result['filename']}")
        print(f"文件大小: {result['file_size']} bytes")
        print(f"Content-Type: {result['content_type']}")
        print(f"HTTP状态码: {result['status_code']}")
        if 'response_data' in result:
            print(f"服务器响应: {result['response_data']}")
        elif 'response_text' in result:
            print(f"服务器响应: {result['response_text']}")
    except ValueError as e:
        print(f"参数错误: {e}")
    except FileNotFoundError as e:
        print(f"文件错误: {e}")
    except requests.exceptions.RequestException as e:
        print(f"网络错误: {e}")
    except Exception as e:
        print(f"未知错误: {e}")


if __name__ == "__main__":
    main()
