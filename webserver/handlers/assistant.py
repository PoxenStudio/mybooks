#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import json
import logging
import tornado.websocket
from webserver.assistant.ai_assistant_agent import AIAssistantMCPAgent


class AssistantWebSocketHandler(tornado.websocket.WebSocketHandler):
    # 保存连接的实例，以便后台服务管理
    clients = set()

    def get_current_user(self):
        """从secure cookie获取当前用户"""
        user_id = self.get_secure_cookie("user_id")
        if not user_id:
            logging.error("No user found in secure cookie")
            return None
        # 这里只需要验证用户是否登录，不需要完整的用户对象
        return user_id

    def check_origin(self, origin):
        logging.info(f"WebSocket check_origin called from: {origin}")
        return True

    async def open(self):
        logging.info(f"WebSocket open called, user: {self.get_current_user()}")
        if not self.get_current_user():
            logging.warning("WebSocket connection attempt without login.")
            self.close(code=4003, reason="Authentication required")
            return

        try:
            logging.info("WebSocket assistant connection accepted")
            self.clients.add(self)

            # 获取当前请求的 cookies
            cookies = {}
            for cookie_name in self.request.cookies:
                cookie = self.request.cookies[cookie_name]
                cookies[cookie_name] = cookie.value

            logging.info(f"WebSocket cookies: {list(cookies.keys())}")

            # 为每个连接创建独立的 Agent 实例
            self.agent = AIAssistantMCPAgent(cookies=cookies)
            await self.agent.initialize()

            self.write_message(json.dumps({"type": "status", "content": "AI助手连接成功"}))
        except Exception as e:
            logging.error(f"Failed to initialize AI agent: {e}")
            self.close(code=5000, reason="Agent initialization failed")
            return

    async def on_message(self, message):
        try:
            data = json.loads(message)
            user_input = data.get("content", "")
            if not user_input:
                return

            logging.info(f"AI Assistant Task: {user_input}")

            # 开启处理
            self.write_message(json.dumps({"type": "start"}))

            async for chunk in self.agent.process_user_input(user_input):
                self.write_message(json.dumps(chunk))

            # 处理完成
            self.write_message(json.dumps({"type": "end"}))

        except Exception as e:
            logging.error(f"Error processing AI message: {e}")
            self.write_message(json.dumps({"type": "error", "content": str(e)}))

    async def on_close(self):
        logging.info("WebSocket assistant closed")
        self.clients.discard(self)
        if hasattr(self, 'agent'):
            await self.agent.close()


def routes():
    return [
        (r"/api/assistant/ws", AssistantWebSocketHandler),
    ]
