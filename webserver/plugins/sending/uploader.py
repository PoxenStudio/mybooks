import os
from pathlib import Path
import requests

class BaseUploader:
    def __init__(self, file_path, timeout=60):
        self.file_path = Path(file_path)
        self.filename = self.file_path.name
        self.file_extension = self.file_path.suffix.lower()
        self.content_type = self._get_content_type()
        self.timeout = timeout
        self._check_file()

    def _check_file(self):
        if not self.file_path.exists():
            raise FileNotFoundError(f"文件不存在: {self.file_path}")
        if self.file_extension not in ['.epub', '.pdf']:
            raise ValueError(f"不支持的文件格式: {self.file_extension}, 只支持 .epub 和 .pdf 文件")

    def _get_content_type(self):
        if self.file_extension == '.epub':
            return 'application/epub+zip'
        elif self.file_extension == '.pdf':
            return 'application/pdf'
        return 'application/octet-stream'

    def handle_exception(self, e, server_url=None):
        # 统一异常处理，返回结构化错误信息
        if hasattr(e, 'response') and e.response is not None:
            # HTTP错误
            return {
                'success': False,
                'error_type': 'http',
                'status_code': e.response.status_code,
                'message': f"HTTP错误: {e.response.status_code}",
                'response_text': e.response.text
            }
        if isinstance(e, requests.exceptions.Timeout):
            return {
                'success': False,
                'error_type': 'timeout',
                'status_code': None,
                'message': f"上传超时: {self.file_path}",
                'response_text': str(e)
            }
        elif isinstance(e, requests.exceptions.ConnectionError):
            return {
                'success': False,
                'error_type': 'connection',
                'status_code': None,
                'message': f"连接服务器失败: {server_url}",
                'response_text': str(e)
            }
        else:
            return {
                'success': False,
                'error_type': 'other',
                'status_code': None,
                'message': f"上传失败: {str(e)}",
                'response_text': str(e)
            }

    def upload(self, server_url):
        raise NotImplementedError("子类需实现 upload 方法")


class DuokanUploader(BaseUploader):
    def upload(self, server_url):
        try:
            with open(self.file_path, 'rb') as file:
                files = {
                    'newfile': (self.filename, file, self.content_type)
                }
                response = requests.post(server_url, files=files, timeout=self.timeout)
                response.raise_for_status()
                try:
                    return {'success': True, 'data': response.json()}
                except Exception:
                    return {'success': True, 'data': response.text}
        except Exception as e:
            return self.handle_exception(e, server_url)


class HanwangUploader(BaseUploader):
    def upload(self, server_url):
        from urllib.parse import quote
        try:
            with open(self.file_path, 'rb') as file:
                files = {
                    'newfile': (self.filename, file, self.content_type)
                }
                data = {
                    'fileName': quote(self.filename)
                }
                response = requests.post(server_url, files=files, data=data, timeout=self.timeout)
                response.raise_for_status()
                try:
                    return {'success': True, 'data': response.json()}
                except Exception:
                    return {'success': True, 'data': response.text}
        except Exception as e:
            return self.handle_exception(e, server_url)


class IReaderUploader(BaseUploader):
    def upload(self, server_url):
        from requests_toolbelt.multipart.encoder import MultipartEncoder
        try:
            with open(self.file_path, 'rb') as file:
                m = MultipartEncoder(
                    fields={
                        'Filename': self.filename,
                        'Filedata': (self.filename, file, self.content_type),
                        'Upload': 'Submit Query'
                    }
                )
                headers = {'Content-Type': 'application/octet-stream'}
                response = requests.post(server_url, data=m, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                try:
                    return {'success': True, 'data': response.json()}
                except Exception:
                    return {'success': True, 'data': response.text}
        except Exception as e:
            return self.handle_exception(e, server_url)
