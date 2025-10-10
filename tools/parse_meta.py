import os
import re
import argparse
import logging
from pathlib import Path
from typing import List, Dict
from bs4 import BeautifulSoup

# 配置常量
DEFAULT_CATEGORY = "小学语文阅读推荐"  # 默认分类，可根据需要修改

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class EPUBDirectorySplitter:
    def __init__(self, category: str = DEFAULT_CATEGORY):
        self.category = category

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从EPUB文件中提取元数据")
    parser.add_argument("epub_path", type=str, help="EPUB文件路径")
    args = parser.parse_args()

    epub_path = args.epub_path

    epub_splitter = EPUBDirectorySplitter()
    # List all files in the target path, and call the meta extraction function one by one
    for root, dirs, files in os.walk(epub_path):
        for file in files:
            file_path = os.path.join(root, file)
            metadata = epub_splitter.extract_metadata_from_copyright_page([Path(file_path)])
            print(f"提取的元数据 ({file}):")
            for key, value in metadata.items():
                print(f"{key}: {value}")
