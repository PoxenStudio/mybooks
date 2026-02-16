#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
微信消息发送测试脚本
使用企业微信 API 实现消息发送功能（官方支持，稳定可靠）

使用说明：
1. 注册企业微信：https://work.weixin.qq.com/
2. 创建自建应用，获取以下信息：
   - corpid: 企业ID（在"我的企业"页面）
   - corpsecret: 应用的 Secret（在应用详情页）
   - agentid: 应用的 AgentId
3. 在应用中配置"可见范围"，添加需要接收消息的成员

安装方法：
pip install requests

环境变量配置：
export WEWORK_CORPID=your_corpid
export WEWORK_CORPSECRET=your_corpsecret
export WEWORK_AGENTID=your_agentid
"""

import os
import sys
import json
import requests
from typing import Optional, Dict, Any, List


class WeWorkAPI:
    """企业微信 API 封装类"""

    def __init__(self, corpid: str, corpsecret: str, agentid: int):
        """
        初始化企业微信 API

        Args:
            corpid: 企业ID
            corpsecret: 应用的Secret
            agentid: 应用的AgentId
        """
        self.corpid = corpid
        self.corpsecret = corpsecret
        self.agentid = agentid
        self.access_token: Optional[str] = None
        self.base_url = "https://qyapi.weixin.qq.com/cgi-bin"

    def get_access_token(self) -> str:
        """
        获取访问令牌

        Returns:
            access_token 字符串
        """
        url = f"{self.base_url}/gettoken"
        params = {
            "corpid": self.corpid,
            "corpsecret": self.corpsecret
        }

        response = requests.get(url, params=params)
        result = response.json()

        if result.get("errcode") != 0:
            raise Exception(f"获取 access_token 失败: {result.get('errmsg')}")

        self.access_token = result["access_token"]
        return self.access_token

    def send_text_message(self, content: str, touser: str = "@all") -> Dict[str, Any]:
        """
        发送文本消息

        Args:
            content: 消息内容
            touser: 接收人，多个用'|'分隔，@all 表示所有人

        Returns:
            API 响应结果
        """
        if not self.access_token:
            self.get_access_token()

        url = f"{self.base_url}/message/send"
        params = {"access_token": self.access_token}

        data = {
            "touser": touser,
            "msgtype": "text",
            "agentid": self.agentid,
            "text": {
                "content": content
            },
            "safe": 0
        }

        response = requests.post(url, params=params, json=data)
        result = response.json()

        if result.get("errcode") != 0:
            raise Exception(f"发送消息失败: {result.get('errmsg')}")

        return result

    def send_markdown_message(self, content: str, touser: str = "@all") -> Dict[str, Any]:
        """
        发送 Markdown 格式消息

        Args:
            content: Markdown 内容
            touser: 接收人

        Returns:
            API 响应结果
        """
        if not self.access_token:
            self.get_access_token()

        url = f"{self.base_url}/message/send"
        params = {"access_token": self.access_token}

        data = {
            "touser": touser,
            "msgtype": "markdown",
            "agentid": self.agentid,
            "markdown": {
                "content": content
            }
        }

        response = requests.post(url, params=params, json=data)
        result = response.json()

        if result.get("errcode") != 0:
            raise Exception(f"发送消息失败: {result.get('errmsg')}")

        return result

    def get_user_list(self, department_id: int = 1) -> List[Dict[str, Any]]:
        """
        获取部门成员列表

        Args:
            department_id: 部门ID，默认为根部门(1)

        Returns:
            用户列表
        """
        if not self.access_token:
            self.get_access_token()

        url = f"{self.base_url}/user/list"
        params = {
            "access_token": self.access_token,
            "department_id": department_id
        }

        response = requests.get(url, params=params)
        result = response.json()

        if result.get("errcode") != 0:
            raise Exception(f"获取用户列表失败: {result.get('errmsg')}")

        return result.get("userlist", [])

    def get_department_list(self) -> List[Dict[str, Any]]:
        """
        获取部门列表

        Returns:
            部门列表
        """
        if not self.access_token:
            self.get_access_token()

        url = f"{self.base_url}/department/list"
        params = {"access_token": self.access_token}

        response = requests.get(url, params=params)
        result = response.json()

        if result.get("errcode") != 0:
            raise Exception(f"获取部门列表失败: {result.get('errmsg')}")

        return result.get("department", [])


def list_users(api: WeWorkAPI):
    """列出所有用户"""
    try:
        users = api.get_user_list()

        if not users:
            print("没有找到任何用户")
            return

        print(f"\n共有 {len(users)} 位成员：")
        print("-" * 70)

        for i, user in enumerate(users, 1):
            userid = user.get('userid', '')
            name = user.get('name', '')
            department = user.get('department', [])
            mobile = user.get('mobile', '')

            print(f"{i}. {name} (UserID: {userid})")
            if mobile:
                print(f"   手机: {mobile}")
            print(f"   部门ID: {department}")

        print("-" * 70)

    except Exception as e:
        print(f"获取用户列表失败：{str(e)}")


def send_greeting_message(api: WeWorkAPI, userid: str = "@all"):
    """
    发送问候消息

    Args:
        api: WeWorkAPI 实例
        userid: 用户ID，默认 @all 发送给所有人
    """
    try:
        greeting = "你好！这是一条来自自动化脚本的问候消息 😊\n\n这是通过企业微信应用发送的测试消息。"

        result = api.send_text_message(greeting, touser=userid)

        print(f"\n✓ 消息发送成功！")
        print(f"发送给: {userid}")
        print(f"消息内容: {greeting}")

        # 显示发送结果详情
        if result.get('invaliduser'):
            print(f"⚠ 无效用户: {result['invaliduser']}")
        if result.get('invalidparty'):
            print(f"⚠ 无效部门: {result['invalidparty']}")

    except Exception as e:
        print(f"✗ 消息发送失败：{str(e)}")


def send_markdown_demo(api: WeWorkAPI, userid: str = "@all"):
    """发送 Markdown 格式的演示消息"""
    try:
        markdown_content = """
## 📢 系统通知

这是一条 **Markdown 格式** 的测试消息

### 功能特性：
- 支持文本消息
- 支持 Markdown 格式
- 支持图片、文件、卡片等多种消息类型

> 测试时间: 现在

[查看文档](https://developer.work.weixin.qq.com/document/path/90236)
"""

        result = api.send_markdown_message(markdown_content, touser=userid)

        print(f"\n✓ Markdown 消息发送成功！")
        print(f"发送给: {userid}")

    except Exception as e:
        print(f"✗ Markdown 消息发送失败：{str(e)}")


def main():
    """主函数"""
    print("=" * 70)
    print("企业微信消息发送测试脚本")
    print("=" * 70)

    # 从环境变量获取配置
    corpid = os.environ.get('WEWORK_CORPID', '')
    corpsecret = os.environ.get('WEWORK_CORPSECRET', '')
    agentid = os.environ.get('WEWORK_AGENTID', '')

    # 如果环境变量未设置，提示用户输入
    if not corpid:
        print("\n⚠ 未设置 WEWORK_CORPID 环境变量")
        print("\n配置方法：")
        print("1. 访问 https://work.weixin.qq.com/")
        print("2. 登录企业微信管理后台")
        print("3. 进入"我的企业"页面，查看"企业ID"")
        print("4. 进入"应用管理"，创建自建应用")
        print("5. 在应用详情页获取 AgentId 和 Secret")
        print("\n设置环境变量：")
        print("export WEWORK_CORPID=your_corpid")
        print("export WEWORK_CORPSECRET=your_corpsecret")
        print("export WEWORK_AGENTID=your_agentid")
        print("=" * 70)

        # 交互式输入（用于测试）
        use_input = input("\n是否手动输入配置进行测试？(y/n): ").strip().lower()
        if use_input == 'y':
            corpid = input("请输入企业ID (corpid): ").strip()
            corpsecret = input("请输入应用Secret (corpsecret): ").strip()
            agentid = input("请输入应用AgentId (agentid): ").strip()
        else:
            print("\n已取消")
            return

    if not corpid or not corpsecret or not agentid:
        print("\n✗ 配置信息不完整，无法继续")
        return

    try:
        # 转换 agentid 为整数
        agentid = int(agentid)
    except ValueError:
        print(f"✗ AgentId 必须是数字: {agentid}")
        return

    try:
        # 创建 API 实例
        print("\n正在连接企业微信 API...")
        api = WeWorkAPI(corpid, corpsecret, agentid)

        # 获取 access_token
        api.get_access_token()
        print("✓ 连接成功！")

        # 列出所有用户
        list_users(api)

        # 询问是否发送消息
        print("\n" + "=" * 70)
        send_choice = input("是否发送测试消息？(y/n): ").strip().lower()

        if send_choice == 'y':
            userid = input("请输入接收人的 UserID（@all 表示所有人，多个用'|'分隔）: ").strip()
            if not userid:
                userid = "@all"

            # 发送文本消息
            send_greeting_message(api, userid)

            # 询问是否发送 Markdown 消息
            md_choice = input("\n是否发送 Markdown 格式消息？(y/n): ").strip().lower()
            if md_choice == 'y':
                send_markdown_demo(api, userid)
        else:
            print("跳过发送消息")

        print("\n" + "=" * 70)
        print("测试完成！")
        print("=" * 70)

    except Exception as e:
        print(f"\n✗ 发生错误：{str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n程序已退出")
    except Exception as e:
        print(f"\n发生错误：{str(e)}")
