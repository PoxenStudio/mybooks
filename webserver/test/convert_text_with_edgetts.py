#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import asyncio
import edge_tts
import os
import sys

async def convert_text_to_speech(text, output_file, voice="zh-CN-XiaoxiaoNeural", rate="+0%", volume="+0%"):
    """
    使用 EdgeTTS 将文本转换为语音

    Args:
        text (str): 要转换的文本
        output_file (str): 输出音频文件路径
        voice (str): 语音类型，默认为中文女声
        rate (str): 语速调节，默认为正常速度
        volume (str): 音量调节，默认为正常音量
    """
    try:
        # 创建 EdgeTTS 通信对象
        communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)

        # 保存音频文件
        await communicate.save(output_file)
        print(f"音频文件已保存到: {output_file}")
        return True
    except Exception as e:
        print(f"转换失败: {e}")
        return False

async def list_available_voices():
    """
    获取可用的语音列表
    """
    try:
        voices = await edge_tts.list_voices()
        print("可用的语音选项:")
        for voice in voices:
            if voice["Locale"].startswith("zh-"):  # 只显示中文语音
                print(f"- {voice['ShortName']}: {voice['FriendlyName']} ({voice['Gender']})")
    except Exception as e:
        print(f"获取语音列表失败: {e}")

async def main():
    """
    主测试函数
    """
    print("EdgeTTS 文本转语音测试")
    print("=" * 40)

    # 测试文本
    test_text = "欢迎使用TaleBook电子书管理系统。这是一个基于 EdgeTTS 的文本转语音测试。"

    # 输出文件路径
    output_dir = "/tmp"
    output_file = os.path.join(output_dir, "test_edgetts.mp3")

    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)

    print(f"测试文本: {test_text}")
    print(f"输出文件: {output_file}")
    print()

    # 列出可用语音
    await list_available_voices()
    print()

    # 测试不同的语音
    voices_to_test = [
        ("zh-CN-XiaoxiaoNeural", "晓晓 (女声)"),
        ("zh-CN-YunxiNeural", "云希 (男声)"),
        ("zh-CN-YunyangNeural", "云扬 (男声)"),
    ]

    for voice, description in voices_to_test:
        print(f"正在测试 {description}...")
        test_output = output_file.replace(".mp3", f"_{voice.split('-')[-1]}.mp3")

        success = await convert_text_to_speech(
            text=test_text,
            output_file=test_output,
            voice=voice,
            rate="+0%",  # 正常语速
            volume="+0%"  # 正常音量
        )

        if success and os.path.exists(test_output):
            file_size = os.path.getsize(test_output)
            print(f"✓ 成功生成音频文件，大小: {file_size} 字节")
        else:
            print("✗ 音频文件生成失败")
        print()


if __name__ == "__main__":
    # 检查是否安装了 edge-tts
    try:
        import edge_tts
    except ImportError:
        print("错误: 未安装 edge-tts 库")
        print("请运行: pip install edge-tts")
        sys.exit(1)

    # 运行测试
    asyncio.run(main())
