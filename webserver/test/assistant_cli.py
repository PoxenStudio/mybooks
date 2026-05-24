#!/usr/bin/env python3
"""
CLI interface for DeepSeek + MCP interactive chat
Supports continuous keyboard input and tool calling
"""

import sys
import asyncio
import signal
from datetime import datetime

from webserver.assistant.ai_assistant_agent import AIAssistantMCPAgent


def print_banner():
    """打印欢迎横幅"""
    print("\n" + "=" * 70)
    print("DeepSeek + MyBooks MCP 会话式代理")
    print("=" * 70)
    print("指令：")
    print("  - 输入问题开始对话")
    print("  - 输入 '退出', 'exit', 'quit' 结束会话")
    print("  - 输入 '历史', 'history' 查看对话历史")
    print("  - 输入 '工具', 'tools' 查看可用工具")
    print("  - 输入 '清除', 'clear' 清除对话历史")
    print("=" * 70 + "\n")


async def main():
    """主会话循环"""
    # 设置信号处理（Ctrl+C优雅退出）
    def signal_handler(sig, frame):
        print("\n\n接收到中断信号，正在退出...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # 打印欢迎信息
    print_banner()

    # 初始化代理
    agent = AIAssistantMCPAgent()
    await agent.initialize()

    # 获取可用工具
    tools = await agent.mcp_client.list_tools()
    print(f"  可用的工具 ({len(tools)}个):")
    for i, tool in enumerate(tools, 1):
        print(f"  {i}. {tool['name']}: {tool.get('description', '无描述')}")
    print()

    # 主对话循环
    while agent.session_active:
        try:
            # 获取用户输入
            user_input = input(" 请输入: ").strip()

            if not user_input:
                continue

            # 检查特殊命令
            if user_input.lower() in ['退出', 'exit', 'quit', 'q']:
                print(" 感谢使用，再见！")
                break

            elif user_input.lower() in ['历史', 'history']:
                summary = agent.get_conversation_summary()
                print(f" {summary}")
                continue

            elif user_input.lower() in ['工具', 'tools']:
                tools = await agent.mcp_client.list_tools()
                print("  可用工具：")
                for tool in tools:
                    print(f"  - {tool['name']}: {tool.get('description', '无描述')}")
                continue

            elif user_input.lower() in ['清除', 'clear']:
                agent.conversation_history = []
                print("对话历史已清除")
                continue

            elif user_input.lower() in ['帮助', 'help']:
                print_banner()
                continue

            # 处理用户查询
            print("\n" + "-" * 70)
            start_time = datetime.now()

            response = await agent.process_user_input(user_input)

            elapsed = (datetime.now() - start_time).total_seconds()
            print(f"\n 回答 (耗时: {elapsed:.2f}秒):")
            print("-" * 70)
            print(response)
            print("-" * 70 + "\n")

        except KeyboardInterrupt:
            print("\n\n接收到中断信号...")
            continue
        except Exception as e:
            print(f" 发生错误: {e}")
            continue

    # 清理资源
    await agent.close()
    print("资源已清理，程序退出")


def run_simple_demo():
    """运行简单演示（无需真实API）"""
    print("简单演示模式")
    print("=" * 50)

    # 模拟对话
    demo_conversation = [
        ("书库中有多少本书？",
         "根据书库统计，共有156本书。\n分类统计：\n  - 文学小说: 67本\n  - 科学技术: 35本\n  - 历史人文: 42本\n  - 艺术设计: 12本"),
        ("科技类书籍有多少？",
         "科技类书籍共有35本，涵盖计算机科学、工程技术、自然科学等多个领域。"),
        ("搜索Python编程书籍",
         "找到3本Python编程相关书籍：\n1. 《Python编程：从入门到实践》\n2. 《流畅的Python》\n3. 《Python数据科学手册》")
    ]

    for question, answer in demo_conversation:
        print(f"\n 用户: {question}")
        input("按Enter键查看回答...")
        print(f" 助手: {answer}")
        print("-" * 50)

    print("\n演示结束。")


if __name__ == "__main__":
    # 检查参数
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        run_simple_demo()
    else:
        # 运行完整会话
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("\n\n程序被用户中断。")
        except Exception as e:
            print(f"程序异常退出: {e}")
