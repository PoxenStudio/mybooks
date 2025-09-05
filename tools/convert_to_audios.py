#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量EPUB转音频工具

用于批量将目录下的EPUB文件转换为音频文件。
支持指定声音、起始章节、输出目录等参数。

使用方法：
  python convert_to_audios.py /path/to/epub/dir --voice zh-CN-YunyangNeural --chapter-start 1 --output /path/to/output
"""

import os
import sys
import argparse
import logging
import subprocess
from pathlib import Path
from typing import List, Optional
import re

# 添加项目根目录到Python路径
script_dir = Path(__file__).parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from webserver.worker.epub2audio_worker import EpubToAudioWorker
from ebooklib import epub

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_epub_title(epub_path: str) -> str:
    """
    从EPUB文件中提取书名

    Args:
        epub_path: EPUB文件路径

    Returns:
        str: 书名，如果无法获取则返回文件名（不含扩展名）
    """
    try:
        book = epub.read_epub(epub_path)
        title = book.get_metadata('DC', 'title')
        if title:
            return title[0][0]  # 获取第一个标题
    except Exception as e:
        logger.warning(f"无法从 {epub_path} 获取书名: {e}")

    # 如果无法获取书名，使用文件名
    return Path(epub_path).stem


def sanitize_filename(filename: str) -> str:
    """
    清理文件名，移除不合法的字符

    Args:
        filename: 原始文件名

    Returns:
        str: 清理后的文件名
    """
    # 移除或替换不合法的文件名字符
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    filename = filename.strip()
    return filename


def find_epub_files(directory: str) -> List[str]:
    """
    在指定目录中查找所有EPUB文件

    Args:
        directory: 搜索目录

    Returns:
        List[str]: EPUB文件路径列表
    """
    epub_files = []
    directory_path = Path(directory)

    if directory_path.is_file() and directory_path.suffix.lower() == '.epub':
        # 如果输入的是单个EPUB文件
        epub_files.append(str(directory_path))
    elif directory_path.is_dir():
        # 如果输入的是目录，搜索所有EPUB文件
        for epub_file in directory_path.rglob('*.epub'):
            epub_files.append(str(epub_file))

    return epub_files


def convert_single_epub(epub_path: str, output_base_dir: str, voice_name: str,
                       chapter_start: int = 1, chapter_end: int = -1,
                       tts: str = "edge", language: str = "zh-CN",
                       worker_count: int = 2, **kwargs) -> bool:
    """
    转换单个EPUB文件为音频

    Args:
        epub_path: EPUB文件路径
        output_base_dir: 输出基础目录
        voice_name: 声音名称
        chapter_start: 起始章节
        chapter_end: 结束章节
        tts: TTS提供商
        language: 语言
        worker_count: 工作线程数
        **kwargs: 其他参数

    Returns:
        bool: 转换是否成功
    """
    try:
        # 获取书名
        book_title = get_epub_title(epub_path)
        book_title = sanitize_filename(book_title)

        # 创建输出目录：<输出目录>/<书名>/<声音名>/
        voice_clean = sanitize_filename(voice_name)
        output_dir = Path(output_base_dir) / book_title / voice_clean
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"开始转换: {epub_path}")
        logger.info(f"书名: {book_title}")
        logger.info(f"输出目录: {output_dir}")
        logger.info(f"声音: {voice_name}")
        logger.info(f"章节范围: {chapter_start} - {chapter_end if chapter_end != -1 else '最后'}")

        # 创建工作器
        worker = EpubToAudioWorker(main_py_path=str(project_root / "webserver/epub_to_audio/main.py"))

        # 设置转换参数
        conversion_kwargs = {
            'chapter_start': chapter_start,
            'chapter_end': chapter_end,
            **kwargs
        }

        # 执行转换
        result = worker.convert_epub_to_audio(
            epub_path=epub_path,
            output_dir=str(output_dir),
            tts=tts,
            language=language,
            worker_count=worker_count,
            voice_name=voice_name,
            no_prompt=True,
            show_output=True,
            **conversion_kwargs
        )

        if result.get("status") == EpubToAudioWorker.STATUS_CONVERTED:
            logger.info(f"✓ 转换成功: {book_title}")
            return True
        else:
            logger.error(f"✗ 转换失败: {book_title} - {result.get('error_message', '未知错误')}")
            return False

    except Exception as e:
        logger.error(f"✗ 转换 {epub_path} 时发生错误: {e}")
        return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="批量EPUB转音频工具")

    # 必需参数
    parser.add_argument("input_dir", help="EPUB文件目录或单个EPUB文件路径")
    parser.add_argument("--output", "-o", required=True, help="输出目录")
    parser.add_argument("--voice", "-v", required=True, help="声音名称 (如: zh-CN-YunyangNeural)")

    # 可选参数
    parser.add_argument("--chapter-start", "-s", type=int, default=1,
                       help="起始章节 (默认: 1)")
    parser.add_argument("--chapter-end", "-e", type=int, default=-1,
                       help="结束章节 (默认: -1, 表示最后一章)")
    parser.add_argument("--tts", default="edge",
                       choices=["edge", "azure", "openai", "piper"],
                       help="TTS提供商 (默认: edge)")
    parser.add_argument("--language", "-l", default="zh-CN",
                       help="语言代码 (默认: zh-CN)")
    parser.add_argument("--worker-count", "-w", type=int, default=2,
                       help="工作线程数 (默认: 2)")
    parser.add_argument("--dry-run", action="store_true",
                       help="试运行模式，只显示会处理的文件，不实际转换")

    # TTS特定参数
    parser.add_argument("--speed", type=float, default=1.0,
                       help="语音速度 (默认: 1.0, 范围: 0.25-4.0)")
    parser.add_argument("--voice-rate", help="语音速率 (edge TTS专用)")
    parser.add_argument("--output-format", help="输出音频格式")

    args = parser.parse_args()

    # 验证输入目录/文件
    input_path = Path(args.input_dir)
    if not input_path.exists():
        logger.error(f"输入路径不存在: {args.input_dir}")
        return 1

    # 创建输出目录
    output_path = Path(args.output)
    if not args.dry_run:
        output_path.mkdir(parents=True, exist_ok=True)

    # 查找EPUB文件
    epub_files = find_epub_files(args.input_dir)
    if not epub_files:
        logger.error(f"在 {args.input_dir} 中未找到EPUB文件")
        return 1

    logger.info(f"找到 {len(epub_files)} 个EPUB文件")

    if args.dry_run:
        logger.info("试运行模式 - 以下文件将被处理:")
        for epub_file in epub_files:
            book_title = get_epub_title(epub_file)
            book_title = sanitize_filename(book_title)
            voice_clean = sanitize_filename(args.voice)
            output_dir = output_path / book_title / voice_clean
            logger.info(f"  {epub_file} -> {output_dir}")
        return 0

    # 准备额外参数
    extra_kwargs = {}
    if args.speed != 1.0:
        extra_kwargs['speed'] = args.speed
    if args.voice_rate:
        extra_kwargs['voice_rate'] = args.voice_rate
    if args.output_format:
        extra_kwargs['output_format'] = args.output_format

    # 批量转换
    success_count = 0
    total_count = len(epub_files)

    for i, epub_file in enumerate(epub_files, 1):
        logger.info(f"\n[{i}/{total_count}] 处理文件: {epub_file}")

        success = convert_single_epub(
            epub_path=epub_file,
            output_base_dir=args.output,
            voice_name=args.voice,
            chapter_start=args.chapter_start,
            chapter_end=args.chapter_end,
            tts=args.tts,
            language=args.language,
            worker_count=args.worker_count,
            **extra_kwargs
        )

        if success:
            success_count += 1

    # 输出统计信息
    logger.info(f"\n转换完成!")
    logger.info(f"总文件数: {total_count}")
    logger.info(f"成功转换: {success_count}")
    logger.info(f"失败数量: {total_count - success_count}")

    return 0 if success_count == total_count else 1


if __name__ == "__main__":
    sys.exit(main())
