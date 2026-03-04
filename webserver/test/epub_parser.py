from ebooklib import epub
from bs4 import BeautifulSoup
import ebooklib

import logging
import re
import os
from typing import List, Tuple

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(console_handler)


class EpubBookParser:
    def __init__(self, input_file):
        self.input_file = input_file
        self.newline_mode = "double"
        self.remove_endnotes = False
        self.remove_reference_numbers = False
        self.title_mode = "auto"
        self.search_and_replace_file = ""
        self.book = epub.read_epub(input_file, {"ignore_ncx": True})

    def print_toc(self, items=None, level=1):
        if not self.book or not self.book.toc:
            logger.warning("No TOC found in the EPUB book.")
            return
        if items is None:
            items = self.book.toc
        for item in items:
            if isinstance(item, epub.Link):
                logger.info('[LINK]' + ' ' * level + f'- {item.title} ({item.href})')
            elif isinstance(item, epub.Section):
                logger.info('[SECTION]' + ' ' * level + f'+ {item.title} ({item.href})')
                if item.children:
                    self.print_toc(item.children, level + 1)
            elif isinstance(item, tuple) and len(item) == 2:
                section, children = item
                if hasattr(section, 'title') and hasattr(section, 'href'):
                    logger.info('[LINK]' + ' ' * level + f'+ {section.title} ({section.href}) [section from tuple]')
                else:
                    logger.info('[SECTION]' + ' ' * level + f'? {section}')
                if children:
                    self.print_toc(children, level + 1)
            else:
                logger.info('[UNKNOWN]' + ' ' * level + f'? {item}')

    def get_book(self):
        return self.book

    def get_book_title(self) -> str:
        if self.book.get_metadata('DC', 'title'):
            return self.book.get_metadata("DC", "title")[0][0]
        return "Untitled"

    def get_book_author(self) -> str:
        if self.book.get_metadata('DC', 'creator'):
            return self.book.get_metadata("DC", "creator")[0][0]
        return "Unknown"

    def get_chapters(self, break_string) -> List[Tuple[str, str]]:
        chapters = []
        search_and_replaces = self.get_search_and_replaces()
        for item_id, linear in self.book.spine:
            if linear == 'no' and item_id != 'nav':
                continue

            # 通过 ID 从 manifest 获取实际 item
            item = self.book.get_item_with_id(item_id)
            if not item or item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue

            content = item.get_content()
            soup = BeautifulSoup(content, "lxml-xml")
            raw = soup.get_text(strip=False)
            # logger.debug(f"Raw text: <{raw[:]}>")

            # Replace excessive whitespaces and newline characters based on the mode
            if self.newline_mode == "single":
                cleaned_text = re.sub(r"[\n]+", break_string, raw.strip())
            elif self.newline_mode == "double":
                cleaned_text = re.sub(r"[\n]{2,}", break_string, raw.strip())
            elif self.newline_mode == "none":
                cleaned_text = re.sub(r"[\n]+", " ", raw.strip())
            else:
                raise ValueError(f"Invalid newline mode: {self.newline_mode}")

            logger.debug(f"Cleaned text step 1: <{cleaned_text[:]}>")
            cleaned_text = re.sub(r"\s+", " ", cleaned_text)
            logger.debug(f"Cleaned text step 2: <{cleaned_text[:100]}>")

            # Removes end-note numbers
            if self.remove_endnotes:
                cleaned_text = re.sub(r'(?<=[a-zA-Z.,!?;”")])\d+', "", cleaned_text)
                logger.debug(f"Cleaned text step 4: <{cleaned_text[:100]}>")

            # Removes references numbers like [1] or [2.3]
            if self.remove_reference_numbers:
                cleaned_text = re.sub(r'\[\d+(\.\d+)?\]', '', cleaned_text)
                logger.debug(f"Cleaned text step 4.1 (removed brackets): <{cleaned_text[:100]}>")

            # Does user defined search and replaces
            for search_and_replace in search_and_replaces:
                cleaned_text = re.sub(search_and_replace['search'], search_and_replace['replace'], cleaned_text)
            logger.debug(f"Cleaned text step 5: <{cleaned_text[:100]}>")

            # Get proper chapter title
            if self.title_mode == "auto":
                title = ""
                title_levels = ['title', 'h1', 'h2', 'h3']
                for level in title_levels:
                    if soup.find(level):
                        title = soup.find(level).text
                        break
                if title.strip() == "" or re.match(r'^\d{1,3}$',title) is not None:
                    title = cleaned_text[:60]
            elif self.title_mode == "tag_text":
                title = ""
                title_levels = ['title', 'h1', 'h2', 'h3']
                for level in title_levels:
                    if soup.find(level):
                        title = soup.find(level).text
                        break
                if title.strip() == "":
                    title = "<blank>"
            elif self.title_mode == "first_few":
                title = cleaned_text[:60]
            else:
                raise ValueError("Unsupported title_mode")
            logger.debug(f"Raw title: <{title}>")
            title = self._sanitize_title(title, break_string)
            logger.debug(f"Sanitized title: <{title}>")

            chapters.append((title, cleaned_text))
            soup.decompose()
        return chapters

    def get_search_and_replaces(self):
        search_and_replaces = []
        if self.search_and_replace_file:
            with open(self.search_and_replace_file) as fp:
                search_and_replace_content = fp.readlines()
                for search_and_replace in search_and_replace_content:
                    if '==' in search_and_replace and not search_and_replace.startswith('==') and not search_and_replace.endswith('==') and not search_and_replace.startswith('#'):
                        search_and_replaces = search_and_replaces + [ {'search': r"{}".format(search_and_replace.split('==')[0]), 'replace': r"{}".format(search_and_replace.split('==')[1][:-1])} ]
        return search_and_replaces

    @staticmethod
    def _sanitize_title(title, break_string) -> str:
        # replace MAGIC_BREAK_STRING with a blank space
        # strip incase leading bank is missing
        title = title.replace(break_string, " ")
        sanitized_title = re.sub(r"[^\w\s]", "", title, flags=re.UNICODE)
        sanitized_title = re.sub(r"\s+", "_", sanitized_title.strip())
        return sanitized_title


if __name__ == "__main__":
    # check the arguments to get the input file
    import argparse
    config = argparse.ArgumentParser(description="Test EpubBookParser")
    config.add_argument("input_file", help="Path to the EPUB file to test")
    args = config.parse_args()

    if not os.path.exists(args.input_file):
        logger.error(f"Input file does not exist: {args.input_file}")
        exit(1)
    logger.info(f"Testing EpubBookParser with file: {args.input_file}")

    parser = EpubBookParser(args.input_file)
    logger.info(f"Book title: {parser.get_book_title()}")
    logger.info(f"Book author: {parser.get_book_author()}")
    chapters = parser.get_chapters(break_string="MAGIC_BREAK_STRING")
    logger.info(f"Total chapters found: {len(chapters)}")
    for idx, (title, text) in enumerate(chapters, start=1):
        logger.info(f"Chapter {idx}: Title: {title}, Text length: {len(text)} characters")

    parser.print_toc()
