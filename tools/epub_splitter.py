#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EPUB图书合集拆分工具

用于将包含多本图书的解压后EPUB目录拆分为独立的EPUB文件。
每遇到一个title为"封面"的页面代表新书的开始。
"""

import os
import sys
import re
import argparse
import logging
from pathlib import Path
import tempfile
import shutil
import zipfile
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional, Tuple
from datetime import datetime

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

# 配置常量
DEFAULT_CATEGORY = "小学语文阅读推荐"  # 默认分类，可根据需要修改
SKIP_TITLES = ["封面", "前折页", "后折页"]  # 需要跳过的页面标题

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class EPUBDirectorySplitter:
    def __init__(self, source_dir: str, output_dir: str, category: str = DEFAULT_CATEGORY):
        """
        初始化EPUB目录拆分器

        Args:
            source_dir: 解压后的EPUB目录路径
            output_dir: 输出目录
            category: 图书分类
        """
        self.source_dir = Path(source_dir)
        self.output_dir = Path(output_dir)
        self.category = category
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 验证输入目录
        if not self.source_dir.exists():
            raise FileNotFoundError(f"源目录不存在: {source_dir}")

        # 查找EPUB结构
        self.content_opf_path = self._find_content_opf()
        self.html_files = self._get_html_files()

        logger.info(f"成功加载EPUB目录: {source_dir}")
        logger.info(f"找到 {len(self.html_files)} 个HTML文件")

    def _find_content_opf(self) -> Optional[Path]:
        """查找content.opf文件"""
        # 查找META-INF/container.xml
        container_xml = self.source_dir / "META-INF" / "container.xml"
        if container_xml.exists():
            try:
                tree = ET.parse(container_xml)
                root = tree.getroot()
                # 查找rootfile元素
                for rootfile in root.iter():
                    if rootfile.tag.endswith('rootfile'):
                        full_path = rootfile.get('full-path')
                        if full_path:
                            return self.source_dir / full_path
            except Exception as e:
                logger.warning(f"解析container.xml失败: {e}")

        # 备用方案：直接查找content.opf
        for opf_file in self.source_dir.rglob("*.opf"):
            return opf_file

        logger.warning("未找到content.opf文件")
        return None

    def _get_html_files(self) -> List[Path]:
        """获取所有HTML文件，按spine顺序排列"""
        html_files = []

        # 如果有content.opf，按spine顺序获取
        if self.content_opf_path and self.content_opf_path.exists():
            try:
                html_files = self._get_files_from_spine()
                if html_files:
                    return html_files
            except Exception as e:
                logger.warning(f"从spine获取文件列表失败: {e}")

        # 备用方案：扫描所有HTML/XHTML文件
        text_dir = self.source_dir / "Text"
        if text_dir.exists():
            html_files = sorted(text_dir.glob("*.html")) + sorted(text_dir.glob("*.xhtml"))
        else:
            # 在整个目录中查找
            html_files = sorted(self.source_dir.rglob("*.html")) + sorted(self.source_dir.rglob("*.xhtml"))

        return html_files

    def _get_files_from_spine(self) -> List[Path]:
        """从content.opf的spine中获取文件列表"""
        html_files = []

        try:
            tree = ET.parse(self.content_opf_path)
            root = tree.getroot()

            # 建立manifest映射
            manifest = {}
            for item in root.iter():
                if item.tag.endswith('item'):
                    item_id = item.get('id')
                    href = item.get('href')
                    if item_id and href:
                        manifest[item_id] = href

            # 按spine顺序获取文件
            for itemref in root.iter():
                if itemref.tag.endswith('itemref'):
                    idref = itemref.get('idref')
                    if idref in manifest:
                        href = manifest[idref]
                        # 相对于content.opf的路径
                        file_path = self.content_opf_path.parent / href
                        if file_path.exists():
                            html_files.append(file_path)

        except Exception as e:
            logger.warning(f"解析spine失败: {e}")

        return html_files

    def find_cover_pages(self) -> List[Tuple[str, Path]]:
        """
        查找所有标题为"封面"的页面，这些页面标志着新书的开始

        Returns:
            封面页面列表，每个元素包含(相对路径, 文件路径对象)
        """
        cover_pages = []

        for html_file in self.html_files:
            try:
                with open(html_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                # 使用xml解析器处理XHTML内容
                soup = BeautifulSoup(content, 'xml')
                if not soup.find('title'):
                    # 如果XML解析器没找到title，尝试html解析器
                    soup = BeautifulSoup(content, 'html.parser')

                # 查找title标签
                title_tag = soup.find('title')
                if title_tag:
                    title_text = title_tag.get_text(strip=True)
                    logger.debug(f"页面 {html_file.name} 标题: '{title_text}'")
                    if title_text == "封面":
                        relative_path = html_file.relative_to(self.source_dir)
                        cover_pages.append((str(relative_path), html_file))
                        logger.info(f"找到封面页面: {relative_path}")
                else:
                    logger.debug(f"页面 {html_file.name} 没有title标签")

            except Exception as e:
                logger.warning(f"处理页面 {html_file} 时出错: {e}")
                continue

        return cover_pages

    def list_all_page_titles(self) -> None:
        """
        列出所有页面的标题，用于调试
        """
        logger.info("=== 所有页面标题列表 ===")
        for i, html_file in enumerate(self.html_files):
            try:
                with open(html_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                # 尝试XML解析器
                soup = BeautifulSoup(content, 'xml')
                title_tag = soup.find('title')
                if not title_tag:
                    # 如果XML解析器没找到title，尝试html解析器
                    soup = BeautifulSoup(content, 'html.parser')
                    title_tag = soup.find('title')

                if title_tag:
                    title_text = title_tag.get_text(strip=True)
                    relative_path = html_file.relative_to(self.source_dir)
                    logger.info(f"{i+1:3d}. {relative_path} - '{title_text}'")
                else:
                    relative_path = html_file.relative_to(self.source_dir)
                    logger.info(f"{i+1:3d}. {relative_path} - [无title标签]")

            except Exception as e:
                relative_path = html_file.relative_to(self.source_dir) if html_file.exists() else html_file.name
                logger.info(f"{i+1:3d}. {relative_path} - [解析错误: {e}]")
        logger.info("=== 页面标题列表结束 ===")

    def extract_cover_image(self, cover_page_path: Path) -> Optional[str]:
        """
        从封面页面提取封面图片路径

        Args:
            cover_page_path: 封面页面文件路径

        Returns:
            封面图片的相对路径，如果未找到则返回None
        """
        try:
            with open(cover_page_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # 尝试用XML解析器处理
            soup = BeautifulSoup(content, 'xml')
            img_tag = soup.find('img')

            # 如果XML解析器没找到img标签，尝试html解析器
            if not img_tag:
                soup = BeautifulSoup(content, 'html.parser')
                img_tag = soup.find('img')

            if img_tag and img_tag.get('src'):
                src = img_tag.get('src')
                # 移除 "../" 前缀，转换为相对路径
                if src.startswith('../'):
                    src = src[3:]
                logger.info(f"提取到封面图片路径: {src}")
                return src

        except Exception as e:
            logger.warning(f"提取封面图片失败: {e}")

        return None

    def extract_metadata_from_copyright_page(self, page_files: List[Path]) -> Dict[str, str]:
        """
        从版权页提取图书元数据

        Args:
            page_files: 页面文件列表

        Returns:
            包含书名、ISBN、出版社等信息的字典
        """
        metadata = {
            'title': '',
            'author': '',
            'translator': '',
            'series': '',
            'isbn': '',
            'publisher': '',
            'date': '',
            'category': self.category
        }

        for page_file in page_files:
            try:
                with open(page_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                # 尝试XML解析器
                soup = BeautifulSoup(content, 'xml')
                title_tag = soup.find('title')
                if not title_tag:
                    # 如果XML解析器没找到title，尝试html解析器
                    soup = BeautifulSoup(content, 'html.parser')
                    title_tag = soup.find('title')

                # 检查是否是版权页或包含版权信息的页面
                title_text = title_tag.get_text() if title_tag else ''
                text_content = soup.get_text()

                # 扩展版权页检测逻辑
                is_copyright_page = (
                    (title_tag and ('版权' in title_text or '出版说明' in title_text)) or
                    '版权所有' in text_content or
                    'ISBN' in text_content or
                    ('图书在版编目' in text_content) or
                    ('CIP数据' in text_content) or
                    (('出版社' in text_content or '出版发行' in text_content) and
                     ('著' in text_content or '作者' in text_content) and
                     ('印刷' in text_content or '定价' in text_content))
                )

                if is_copyright_page:
                    logger.info(f"找到版权页: {page_file.name}, 标题: '{title_text}'")
                    logger.info(f"版权页完整内容:\n{content}")  # 显示完整的HTML内容

                    # 如果已经从更好的版权页面提取了标题，则跳过一般性的版权页面
                    if metadata.get('title') and title_text in ['知识链接', '学习思考', '延伸阅读']:
                        logger.info(f"跳过非主要版权页面: {title_text}")
                        continue

                    # 查找包含书名、作者、译者信息的p标签和其他元素
                    # 支持多种格式：
                    # 格式1：秘密花园/（美）弗朗西丝·伯内特著；黄健人译.—北京：人民文学出版社，2018
                    # 格式2：书名: 小王子
                    # 格式3：直接文本中的模式匹配

                    # 先尝试从整个文本内容中提取信息
                    self._extract_from_full_text(text_content, metadata)

                    # 然后逐个检查p标签
                    for p_tag in soup.find_all('p'):
                        p_text = p_tag.get_text(strip=True)
                        logger.info(f"检查p标签内容: {p_text}")

                        # 格式1：查找包含"/"和相关角色标识符且包含中文的行（优先处理）
                        if ('/' in p_text and
                            re.search(r'[\u4e00-\u9fff]', p_text) and
                            re.search(r'[著译编选注]', p_text)):
                            logger.info(f"找到斜杠格式，调用_extract_from_slash_format: {p_text}")
                            self._extract_from_slash_format(p_text, metadata)
                            break  # 找到一行有效信息就退出

                        # 格式2：键值对格式 "书名: XXX"
                        elif ':' in p_text or '：' in p_text:
                            self._extract_from_colon_format(p_text, metadata)

                    # 最后检查其他元素（如div、span等）
                    if not metadata['title']:
                        for element in soup.find_all(['div', 'span', 'h1', 'h2', 'h3']):
                            element_text = element.get_text(strip=True)
                            if element_text and len(element_text) < 100:  # 避免处理太长的文本
                                self._try_extract_title_from_text(element_text, metadata)
                                if metadata['title']:
                                    break

                    # 提取ISBN（如果上面没有提取到其他信息，继续查找）
                    if not metadata['isbn']:
                        isbn_match = re.search(r'ISBN\s*[：:]?\s*([\d\-]+)', text_content)
                        if isbn_match:
                            metadata['isbn'] = isbn_match.group(1)
                            logger.info(f"提取ISBN: '{metadata['isbn']}'")

                    # 提取丛书信息
                    if not metadata['series']:
                        series_match = re.search(r'（([^）]*丛书[^）]*)）', text_content)
                        if series_match:
                            metadata['series'] = series_match.group(1)
                            logger.info(f"提取丛书: '{metadata['series']}'")

                    # 如果找到了版权页且提取了信息，就跳出循环
                    if metadata['title']:
                        break

            except Exception as e:
                logger.warning(f"处理版权页 {page_file} 时出错: {e}")
                continue

        logger.info(f"提取的元数据: {metadata}")
        return metadata

    def should_skip_page(self, page_file: Path) -> bool:
        """
        判断是否应该跳过某个页面

        Args:
            page_file: 页面文件路径

        Returns:
            如果应该跳过则返回True
        """
        try:
            with open(page_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # 尝试XML解析器
            soup = BeautifulSoup(content, 'xml')
            title_tag = soup.find('title')
            if not title_tag:
                # 如果XML解析器没找到title，尝试html解析器
                soup = BeautifulSoup(content, 'html.parser')
                title_tag = soup.find('title')

            if title_tag:
                title_text = title_tag.get_text(strip=True)
                skip = title_text in SKIP_TITLES
                if skip:
                    logger.debug(f"跳过页面 {page_file.name}，标题: '{title_text}'")
                return skip
            else:
                # 如果没有title标签，不跳过（可能是内容页）
                logger.debug(f"页面 {page_file.name} 没有title标签，保留")
                return False
        except Exception as e:
            logger.debug(f"处理页面 {page_file.name} 时出错: {e}，保留")
            pass

        return False

    def create_epub_from_files(self, page_files: List[Path], metadata: Dict[str, str],
                             cover_image_path: Optional[str] = None) -> epub.EpubBook:
        """
        从页面文件列表创建新的EPUB图书

        Args:
            page_files: 页面文件列表
            metadata: 图书元数据
            cover_image_path: 封面图片路径

        Returns:
            创建的EPUB图书对象
        """
        book = epub.EpubBook()

        # 设置元数据
        book.set_identifier(metadata.get('isbn', f"unknown-{datetime.now().strftime('%Y%m%d%H%M%S')}"))
        book.set_title(metadata.get('title', '未知书名'))
        book.set_language('zh-CN')

        # 添加作者信息
        if metadata.get('author'):
            book.add_author(metadata['author'])

        # 添加其他元数据
        if metadata.get('publisher'):
            book.add_metadata('DC', 'publisher', metadata['publisher'])
        if metadata.get('date'):
            book.add_metadata('DC', 'date', metadata['date'])
        if metadata.get('series'):
            book.add_metadata('DC', 'relation', metadata['series'])
        if metadata.get('translator'):
            book.add_metadata('DC', 'contributor', metadata['translator'], {'role': 'translator'})

        book.add_metadata('DC', 'subject', metadata.get('category', self.category))

        # 添加封面图片
        if cover_image_path:
            try:
                image_file = self.source_dir / cover_image_path
                if image_file.exists():
                    with open(image_file, 'rb') as f:
                        image_data = f.read()

                    # 确定图片文件扩展名
                    image_ext = image_file.suffix.lower()
                    if image_ext == '.jpeg':
                        image_ext = '.jpg'

                    cover_img = epub.EpubImage()
                    cover_img.id = 'cover_image'
                    cover_img.file_name = f"Images/cover{image_ext}"
                    cover_img.media_type = f"image/{image_ext[1:]}"
                    cover_img.content = image_data
                    book.add_item(cover_img)

                    # 设置封面
                    book.set_cover(cover_img.file_name, image_data)
                    logger.info(f"成功设置封面图片: {cover_image_path}")
                else:
                    logger.warning(f"封面图片文件不存在: {image_file}")
            except Exception as e:
                logger.warning(f"添加封面图片失败: {e}")

        # 添加样式文件
        styles_dir = self.source_dir / "Styles"
        if styles_dir.exists():
            for style_file in styles_dir.glob("*.css"):
                try:
                    with open(style_file, 'r', encoding='utf-8') as f:
                        style_content = f.read()

                    style = epub.EpubItem()
                    style.id = style_file.stem  # 直接设置id属性
                    style.file_name = f"Styles/{style_file.name}"
                    style.media_type = "text/css"
                    style.content = style_content  # 直接设置content属性
                    book.add_item(style)
                except Exception as e:
                    logger.warning(f"添加样式文件 {style_file} 失败: {e}")

        # 添加图片资源
        images_dir = self.source_dir / "Images"
        if images_dir.exists():
            for img_file in images_dir.glob("*"):
                if img_file.is_file() and img_file.suffix.lower() in ['.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp']:
                    try:
                        with open(img_file, 'rb') as f:
                            img_data = f.read()

                        img = epub.EpubImage()
                        img.id = img_file.stem  # 直接设置id属性
                        img.file_name = f"Images/{img_file.name}"  # 保持原始路径结构

                        # 根据文件扩展名设置正确的媒体类型
                        ext = img_file.suffix.lower()
                        if ext == '.jpg' or ext == '.jpeg':
                            img.media_type = "image/jpeg"
                        elif ext == '.png':
                            img.media_type = "image/png"
                        elif ext == '.gif':
                            img.media_type = "image/gif"
                        elif ext == '.svg':
                            img.media_type = "image/svg+xml"
                        elif ext == '.webp':
                            img.media_type = "image/webp"
                        else:
                            img.media_type = f"image/{ext[1:]}"

                        img.content = img_data  # 直接设置content属性
                        book.add_item(img)
                        logger.debug(f"添加图片: {img_file.name}")
                    except Exception as e:
                        logger.warning(f"添加图片文件 {img_file} 失败: {e}")

        # 添加页面内容（跳过需要排除的页面）
        chapters = []
        skipped_count = 0
        added_count = 0
        for i, page_file in enumerate(page_files):
            if self.should_skip_page(page_file):
                logger.debug(f"跳过页面: {page_file.name}")
                skipped_count += 1
                continue

            try:
                with open(page_file, 'r', encoding='utf-8', errors='ignore') as f:
                    page_content = f.read()

                # 检查页面内容是否为空或无效
                if not page_content.strip():
                    logger.warning(f"页面 {page_file.name} 内容为空，跳过")
                    continue

                # 解析HTML内容，提取body部分并修复图片路径
                soup = BeautifulSoup(page_content, 'html.parser')

                # 修复所有图片的src路径
                for img_tag in soup.find_all('img'):
                    src = img_tag.get('src')
                    if src:
                        # 将相对路径 ../Images/xxx.jpg 转换为 Images/xxx.jpg
                        if src.startswith('../Images/'):
                            new_src = src[3:]  # 移除 "../"
                            img_tag['src'] = new_src
                            logger.debug(f"修复图片路径: {src} -> {new_src}")
                        elif src.startswith('../'):
                            # 处理其他可能的相对路径
                            new_src = src[3:]
                            img_tag['src'] = new_src
                            logger.debug(f"修复路径: {src} -> {new_src}")

                # 尝试提取body内容
                body_tag = soup.find('body')
                if body_tag:
                    # 获取body内的内容
                    body_content = str(body_tag)
                else:
                    # 如果没有body标签，使用整个修复后的内容
                    body_content = str(soup)

                # 确保内容不为空
                if not body_content.strip():
                    logger.warning(f"页面 {page_file.name} body内容为空，跳过")
                    continue

                chapter = epub.EpubHtml()
                chapter.id = f"chapter_{i}"  # 直接设置id属性
                chapter.file_name = f"Text/{page_file.name}"
                chapter.media_type = "application/xhtml+xml"  # 设置媒体类型
                chapter.content = body_content  # 设置body内容
                book.add_item(chapter)
                chapters.append(chapter)
                added_count += 1
                logger.debug(f"成功添加章节: {page_file.name}")
            except Exception as e:
                logger.warning(f"添加章节 {page_file.name} 失败: {e}")
                continue

        logger.info(f"页面处理完成: 总数 {len(page_files)}, 跳过 {skipped_count}, 添加 {added_count}")

        # 检查是否有有效的章节
        if not chapters:
            logger.error("没有有效的章节内容，无法创建EPUB")
            raise ValueError("没有有效的章节内容")

        logger.info(f"准备创建EPUB：包含 {len(chapters)} 个章节")

        # 设置spine（阅读顺序），不包含导航页面
        book.spine = chapters

        # 不添加目录导航文件，保持简洁
        # book.add_item(epub.EpubNcx())
        # book.add_item(epub.EpubNav())

        item_count = len(list(book.get_items()))
        logger.debug(f"EPUB创建完成，包含项目数量: {item_count}")
        return book

    def split_epub(self) -> List[str]:
        """
        执行EPUB拆分操作

        Returns:
            生成的EPUB文件路径列表
        """
        logger.info("开始分析EPUB目录结构...")

        logger.info(f"总HTML文件数: {len(self.html_files)}")

        # 在调试模式下列出所有页面标题
        if logger.isEnabledFor(logging.DEBUG):
            self.list_all_page_titles()

        # 查找封面页面
        cover_pages = self.find_cover_pages()
        logger.info(f"找到 {len(cover_pages)} 个封面页面")

        if len(cover_pages) == 0:
            logger.warning("未找到封面页面，显示所有页面标题以供调试:")
            self.list_all_page_titles()
            return []

        # 创建页面索引映射
        page_index = {str(page_file.relative_to(self.source_dir)): i
                     for i, page_file in enumerate(self.html_files)}

        generated_files = []

        # 为每本书创建EPUB
        for i, (cover_relative_path, cover_page_file) in enumerate(cover_pages):
            logger.info(f"处理第 {i+1} 本书，封面页面: {cover_relative_path}")

            # 确定这本书的页面范围
            start_index = page_index[cover_relative_path]

            if i + 1 < len(cover_pages):
                next_cover_relative_path = cover_pages[i + 1][0]
                end_index = page_index[next_cover_relative_path]
            else:
                end_index = len(self.html_files)

            book_page_files = self.html_files[start_index:end_index]
            logger.info(f"书籍页面范围: {start_index} - {end_index-1} (共 {len(book_page_files)} 页)")

            # 提取封面图片
            cover_image_path = self.extract_cover_image(cover_page_file)

            # 提取元数据
            metadata = self.extract_metadata_from_copyright_page(book_page_files)
            logger.info(f"提取的元数据: {metadata}")

            # 创建新的EPUB
            try:
                new_book = self.create_epub_from_files(book_page_files, metadata, cover_image_path)

                # 生成文件名
                title = metadata.get('title', '').strip()
                if not title:  # 如果title为空或只有空白字符
                    title = f'book_{i+1}'
                    logger.warning(f"第 {i+1} 本书未能提取到书名，使用默认名称: {title}")

                safe_title = re.sub(r'[<>:"|?*]', '_', title).replace('/', '_').replace('\\', '_')
                epub_filename = f"{safe_title}.epub"
                epub_path = self.output_dir / epub_filename

                # 确保文件名唯一
                counter = 1
                while epub_path.exists():
                    epub_filename = f"{safe_title}_{counter}.epub"
                    epub_path = self.output_dir / epub_filename
                    counter += 1

                # 保存EPUB文件
                logger.info(f"准备保存EPUB: {epub_path}")
                chapter_count = len(list(new_book.get_items_of_type(epub.EpubHtml)))
                logger.debug(f"EPUB图书对象章节数: {chapter_count}")
                epub.write_epub(str(epub_path), new_book)
                generated_files.append(str(epub_path))
                logger.info(f"成功创建: {epub_path}")

            except Exception as e:
                import traceback
                logger.error(f"创建第 {i+1} 本书时出错: {e}")
                logger.debug(f"错误详情: {traceback.format_exc()}")
                continue

        return generated_files

    def _extract_from_full_text(self, text_content: str, metadata: Dict[str, str]) -> None:
        """从完整文本中提取元数据"""
        # 常见的书名模式
        title_patterns = [
            r'书\s*名[:：]\s*([^\n\r]+)',
            r'图书名称[:：]\s*([^\n\r]+)',
            r'作品名称[:：]\s*([^\n\r]+)',
        ]

        for pattern in title_patterns:
            match = re.search(pattern, text_content)
            if match and not metadata['title']:
                title = match.group(1).strip()
                if title and re.search(r'[\u4e00-\u9fff]', title):
                    metadata['title'] = title
                    logger.info(f"从全文提取书名: '{title}'")
                    break

        # 出版社模式
        publisher_patterns = [
            r'出版社[:：]\s*([^\n\r]+?出版社)',
            r'([^\n\r]*?出版社)出版',
            r'出版[:：]\s*([^\n\r]+?出版社)',
        ]

        for pattern in publisher_patterns:
            match = re.search(pattern, text_content)
            if match and not metadata['publisher']:
                publisher = match.group(1).strip()
                if publisher and '出版社' in publisher:
                    metadata['publisher'] = publisher
                    logger.info(f"从全文提取出版社: '{publisher}'")
                    break

    def _extract_from_colon_format(self, p_text: str, metadata: Dict[str, str]) -> None:
        """从冒号格式的文本中提取元数据"""
        # 统一使用中文冒号
        p_text_normalized = p_text.replace(':', '：')

        if p_text_normalized.startswith('书名：'):
            title_value = p_text_normalized.replace('书名：', '').strip()
            if title_value and re.search(r'[\u4e00-\u9fff]', title_value):
                metadata['title'] = title_value
                logger.info(f"提取书名: '{title_value}'")

        elif p_text_normalized.startswith('作者：'):
            author_value = p_text_normalized.replace('作者：', '').strip()
            if author_value:
                metadata['author'] = author_value
                logger.info(f"提取作者: '{author_value}'")

        elif p_text_normalized.startswith('译者：'):
            translator_value = p_text_normalized.replace('译者：', '').strip()
            if translator_value:
                metadata['translator'] = translator_value
                logger.info(f"提取译者: '{translator_value}'")

        elif p_text_normalized.startswith('出版社：'):
            publisher_value = p_text_normalized.replace('出版社：', '').strip()
            if publisher_value:
                metadata['publisher'] = publisher_value
                logger.info(f"提取出版社: '{publisher_value}'")

        elif p_text_normalized.startswith('ISBN：'):
            isbn_value = p_text_normalized.replace('ISBN：', '').strip()
            if isbn_value:
                metadata['isbn'] = isbn_value
                logger.info(f"提取ISBN: '{isbn_value}'")

    def _extract_from_slash_format(self, p_text: str, metadata: Dict[str, str]) -> None:
        """从斜杠格式的文本中提取元数据"""
        logger.info(f"进入_extract_from_slash_format方法，处理文本: {p_text}")
        logger.info(f"找到书籍信息行: {p_text}")

        # 按"/"分割，第一部分是书名
        parts = p_text.split('/', 1)
        logger.info(f"分割结果: {parts}, 长度: {len(parts)}")
        if len(parts) >= 2:
            title_part = parts[0].strip()
            author_part = parts[1].strip()

            # 提取书名
            if title_part and re.search(r'[\u4e00-\u9fff]', title_part):
                # 去除可能的编号或特殊字符
                title_clean = re.sub(r'^[\d\s\.\-\—\*]+', '', title_part).strip()
                if title_clean:
                    metadata['title'] = title_clean
                    logger.info(f"提取书名: '{title_clean}'")

            # 提取作者信息
            # 格式：（美）弗朗西丝·伯内特著；黄健人译
            if author_part:
                # 提取作者（著前的内容）
                author_match = re.search(r'([^著]+)著', author_part)
                if author_match:
                    author_info = author_match.group(1).strip()
                    # 处理国籍信息：（美）作者名
                    nationality_match = re.search(r'（([^）]+)）(.+)', author_info)
                    if nationality_match:
                        nationality = nationality_match.group(1)
                        author_name = nationality_match.group(2).strip()
                        metadata['author'] = f"{author_name}（{nationality}）"
                    else:
                        metadata['author'] = author_info
                    logger.info(f"提取作者: '{metadata['author']}'")

                # 提取译者（译前的内容，通常在；后面）
                translator_match = re.search(r'；([^译]+)译', author_part)
                if translator_match:
                    translator_name = translator_match.group(1).strip()
                    metadata['translator'] = translator_name
                    logger.info(f"提取译者: '{translator_name}'")

                # 如果没有找到"著"字，但有"译"字，将译者作为作者
                elif not author_match:
                    # 查找译者信息（可能不在分号后）
                    translator_match = re.search(r'([^译]+)译', author_part)
                    if translator_match:
                        translator_info = translator_match.group(1).strip()
                        # 处理国籍信息：（美）译者名
                        nationality_match = re.search(r'（([^）]+)）(.+)', translator_info)
                        if nationality_match:
                            nationality = nationality_match.group(1)
                            translator_name = nationality_match.group(2).strip()
                            metadata['author'] = f"{translator_name}（{nationality}）"
                        else:
                            metadata['author'] = translator_info
                        logger.info(f"未找到著者，将译者作为作者: '{metadata['author']}'")
                    else:
                        # 查找编译、选注等其他角色
                        editor_patterns = [r'([^编]+)编译', r'([^选]+)选注', r'([^注]+)注释']
                        for pattern in editor_patterns:
                            editor_match = re.search(pattern, author_part)
                            if editor_match:
                                editor_info = editor_match.group(1).strip()
                                # 处理多个编者的情况（用逗号分隔）
                                if '，' in editor_info:
                                    editor_info = editor_info.replace('，', '、')
                                metadata['author'] = editor_info
                                logger.info(f"未找到著者和译者，将编者作为作者: '{metadata['author']}'")
                                break

                # 提取出版社和日期信息
                # 格式：.—北京：人民文学出版社，2018
                pub_match = re.search(r'[.—]+([^：]+)：([^，]+)，?(\d{4})', author_part)
                if pub_match:
                    location = pub_match.group(1).strip()
                    publisher = pub_match.group(2).strip()
                    year = pub_match.group(3)
                    metadata['publisher'] = f"{location}：{publisher}"
                    metadata['date'] = year
                    logger.info(f"提取出版信息: {metadata['publisher']}, {year}")

    def _try_extract_title_from_text(self, text: str, metadata: Dict[str, str]) -> None:
        """尝试从任意文本中提取书名"""
        # 如果已经有书名了，不要覆盖
        if metadata.get('title'):
            return

        # 过滤掉明显不是书名的内容
        if any(word in text for word in ['版权', 'ISBN', '出版社', '著', '译', '©', 'Copyright', '出版说明', '前言', '导读', '目录', '封面', '书名页']):
            return

        # 检查是否是合理的书名
        if (re.search(r'[\u4e00-\u9fff]', text) and  # 包含中文
            len(text) > 1 and len(text) < 50 and    # 长度合理
            not re.search(r'[\d]{4}', text)):       # 不包含年份

            metadata['title'] = text.strip()
            logger.info(f"从元素文本提取书名: '{text.strip()}'")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='EPUB图书合集拆分工具')
    parser.add_argument('source_dir', help='解压后的EPUB目录路径')
    parser.add_argument('output_dir', nargs='?', help='输出目录')
    parser.add_argument('--category', default=DEFAULT_CATEGORY, help=f'图书分类 (默认: {DEFAULT_CATEGORY})')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细输出')
    parser.add_argument('--list-titles', action='store_true', help='仅列出所有页面标题，不进行拆分')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 检查输入目录
    if not os.path.exists(args.source_dir):
        logger.error(f"源目录不存在: {args.source_dir}")
        sys.exit(1)

    if not os.path.isdir(args.source_dir):
        logger.error(f"输入路径不是目录: {args.source_dir}")
        sys.exit(1)

    try:
        # 如果只是列出标题
        if args.list_titles:
            # 创建一个临时输出目录参数
            splitter = EPUBDirectorySplitter(args.source_dir, "/tmp", args.category)
            splitter.list_all_page_titles()
            return

        # 检查输出目录参数
        if not args.output_dir:
            logger.error("输出目录参数是必需的（除非使用 --list-titles 选项）")
            sys.exit(1)

        # 创建拆分器并执行拆分
        splitter = EPUBDirectorySplitter(args.source_dir, args.output_dir, args.category)
        generated_files = splitter.split_epub()

        logger.info(f"拆分完成！共生成 {len(generated_files)} 个EPUB文件:")
        for file_path in generated_files:
            logger.info(f"  - {file_path}")

    except Exception as e:
        logger.error(f"拆分过程中发生错误: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
