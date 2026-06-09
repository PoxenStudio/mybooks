import requests
import os
import time
import random
import re
from urllib.parse import quote, urlparse, parse_qs, unquote


class CTFileDownloader:
    # 配置账号信息
    EMAIL = "test"  # 替换为您的城通网盘邮箱
    PASSWORD = "test"       # 替换为您的城通网盘密码
    COOKIES = "ct_uid=73027d8c914861e54704b58f344c1ee5f4; sessionid=1751475592497; PHPSESSID=k10g5mie2hcrd9om64bfarcorf; ct_popview_comp=1; pass_f1523604949=526663; ua_checkmutilogin=cuUuhAE8JB; pubcookie=XjwPNwE7UzUMMVAzAWdRPVsABTIPU1JtUm1XdlU0UClSRFJiDDIHZAMoAzQFPVVjVg1VFg85V3VTcAIjUW4GMF45DzwBOlM1DABQbAE5UXhbYgV8DxpSNFIwVzJVcVAzUmtSPgwJB2MDMQNiBWNVNlY1VWUPalc2UzsCWFE5BmBebg8-AW9TMgxvUDIBM1FrWz4FNQ9iUmdSNVc3VTxQYlIyUjYMZgdnA2QDbwU2VW1WMlUwD2xXMlMwAmQ"

    def __init__(self):
        self.session = requests.Session()
        self.email = self.EMAIL
        self.password = self.PASSWORD
        self.headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://www.ctfile.com/",
        }
        self.cookies = self.COOKIES
        self.logged_in = True if self.cookies else False
        self.base_url = "https://webapi.ctfile.com"

    def login(self, share_url):
        """登录城通网盘账号"""
        try:
            # 解析分享链接获取参数
            parsed = urlparse(share_url)
            query_params = parse_qs(parsed.query)
            passcode = query_params.get('p', [''])[0]

            # 构造登录URL
            encoded_ref = quote(share_url, safe='')
            login_url = f"https://www.ctfile.com/p/login?ref={encoded_ref}"

            # 准备登录数据
            login_data = {
                "ref": share_url,
                "action": "login",
                "task": "login",
                "email": self.email,
                "password": self.password
            }

            # 获取登录页面以获取必要的cookies
            self.session.get(login_url, headers=self.headers)

            # 执行登录
            login_response = self.session.post(
                login_url,
                data=login_data,
                headers=self.headers,
                allow_redirects=True
            )

            # 检查登录是否成功
            if "login-error" in login_response.text.lower():
                print("登录失败: 账号或密码错误, 请检查您的账号信息")
                return False
            elif "用户名或密码错误" in login_response.text:
                print("登录失败: 用户名或密码错误")
                return False
            elif "验证码" in login_response.text:
                print("登录失败: 需要验证码，目前脚本不支持验证码处理")
                return False
            elif "logout" in login_response.text.lower():
                print(f"登录成功! 欢迎 {self.email}")
                self.logged_in = True
                return True
            else:
                print("登录失败: 未知原因")
                return False

        except Exception as e:
            print(f"登录过程中出错: {str(e)}")
            return False

    def get_download_link(self, share_url):
        """通过API获取实际下载链接"""
        try:
            # 解析分享链接获取必要参数
            parsed = urlparse(share_url)
            query_params = parse_qs(parsed.query)
            passcode = query_params.get('p', [''])[0]
            file_key = parsed.path.split('/')[-1]

            # 构造API请求参数
            params = {
                "path": "f",
                "f": file_key,
                "passcode": passcode,
                "token": "0",
                "r": random.random(),  # 随机数防止缓存
                "ref": "https://www.iyd.wang/",
                "url": quote(share_url, safe='')
            }

            # 发送API请求
            api_url = f"{self.base_url}/getfile.php"

            # 添加cookies到请求头
            cookie_header = self.cookies  # "; ".join([f"{key}={value}" for key, value in self.cookies.items()])
            self.headers["Cookie"] = cookie_header
            response = self.session.get(api_url, params=params, headers=self.headers)
            response.raise_for_status()

            # 解析API响应
            json_data = response.json()
            if json_data.get("code") == 200:
                return json_data["file"]["vip_dx_url"]

            print(f"API请求失败: {json_data.get('message', '未知错误')}")
            return None

        except Exception as e:
            print(f"获取下载链接时出错: {str(e)}")
            return None

    def get_filename_from_url(self, url):
        """从URL中提取文件名"""
        # 尝试从URL路径获取文件名
        filename = os.path.basename(urlparse(url).path)

        # 如果文件名看起来像URL编码，尝试解码
        if '%' in filename:
            try:
                decoded = unquote(filename)
                # 如果解码后包含扩展名，使用解码后的名称
                if '.' in decoded and decoded.split('.')[-1].isalnum():
                    return decoded
            except:
                pass

        return filename

    def download_file(self, download_url, save_path=None, custom_filename=None):
        """下载文件到本地"""
        if not self.logged_in:
            print("请先登录账号")
            return False

        try:
            # 获取文件名 - 先尝试HEAD请求
            content_disposition = ""
            filename = ""
            try:
                # 尝试获取文件名
                head_response = self.session.head(download_url, headers=self.headers, allow_redirects=True)
                content_disposition = head_response.headers.get('Content-Disposition', '')
                if content_disposition and 'filename=' in content_disposition:
                    filename = re.findall('filename="?([^"]+)"?', content_disposition)[0]
                    # 处理URL编码的文件名
                    if '%' in filename:
                        filename = unquote(filename)
            except Exception as e:
                print(f"获取文件名时出错: {str(e)}")

            # 如果HEAD请求没获取到文件名，尝试从URL中提取
            if not filename:
                filename = self.get_filename_from_url(download_url)

            # 简单的有效性检查
            if not filename or len(filename) < 3 or '.' not in filename:
                filename = f"download_{int(time.time())}"

            # 如果有自定义文件名，使用它（不带扩展名）
            if custom_filename:
                # 保留原始文件的扩展名
                extension = os.path.splitext(filename)[1] if '.' in filename else ""
                filename = f"{custom_filename}{extension}"

            # 清理文件名中的非法字符
            filename = re.sub(r'[\\/*?:"<>|]', '_', filename)

            # 设置保存路径
            if not save_path:
                save_path = filename
            elif os.path.isdir(save_path):
                save_path = os.path.join(save_path, filename)

            # 确保目录存在
            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            # 开始下载文件
            print(f"开始下载: {filename}")
            with self.session.get(download_url, headers=self.headers, stream=True) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('content-length', 0))
                downloaded = 0

                with open(save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)

                            # 显示下载进度
                            if total_size > 0:
                                percent = (downloaded / total_size) * 100
                                print(f"\r下载进度: {percent:.2f}% ({downloaded}/{total_size} bytes)", end='')
                            else:
                                print(f"\r已下载: {downloaded} bytes", end='')

            print(f"\n文件已保存到: {save_path}")
            return True

        except Exception as e:
            print(f"\n下载文件时出错: {str(e)}")
            return False

    def download_from_share(self, share_url, save_path=None, custom_filename=None):
        """从分享链接下载文件"""
        # 登录账号
        if not self.logged_in and not self.login(share_url):
            return False

        # 通过API获取下载链接
        download_url = self.get_download_link(share_url)
        if not download_url:
            print("无法获取下载链接")
            return False

        print(f"获取到下载链接: {download_url}")
        return self.download_file(download_url, save_path, custom_filename)


if __name__ == "__main__":
    # 要下载的文件列表 (URL, 自定义文件名)
    # 自定义文件名可以不带扩展名，为空时自动从下载链接获取
    FILE_LIST = [
        ("https://url89.ctfile.com/f/31084289-1514487802-61521d?p=8866", ""),
        # 添加更多文件...
    ]

    # 保存目录 (可选)
    SAVE_DIR = "downloads"  # 可以替换为您想要的目录

    # 创建下载器实例
    downloader = CTFileDownloader()

    # 创建保存目录
    if SAVE_DIR and not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)

    # 下载所有文件
    for i, (share_url, custom_filename) in enumerate(FILE_LIST):
        print(f"\n处理文件 {i+1}/{len(FILE_LIST)}: {share_url}")
        print(f"自定义文件名: '{custom_filename}'" if custom_filename else "使用自动生成文件名")

        if downloader.download_from_share(share_url, SAVE_DIR, custom_filename):
            print(f"下载成功: {share_url}")
        else:
            print(f"下载失败: {share_url}")
        time.sleep(3)  # 在下载之间添加延迟

    print("\n所有文件下载完成!")
