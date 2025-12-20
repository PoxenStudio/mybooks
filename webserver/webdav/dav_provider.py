# -*- coding: UTF-8 -*-
import os
import re
import logging
import time
from io import BytesIO
from urllib.parse import unquote
from wsgidav.dav_provider import DAVProvider, DAVCollection, DAVNonCollection


SUPPORTED_FORMATS = ["epub", "azw3", "mobi", "pdf", "txt"]


def safe_filename(filename):
    """Make filename safe for filesystem by removing/replacing special characters"""
    # Replace various problematic characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove control characters
    filename = ''.join(c for c in filename if ord(c) >= 32)
    # Limit length
    if len(filename) > 200:
        filename = filename[:200]
    return filename.strip()


class TalebookResource(DAVNonCollection):
    def __init__(self, path, environ, book, cache):
        super(TalebookResource, self).__init__(path, environ)
        self.book = book
        self.cache = cache
        self.formats = SUPPORTED_FORMATS
        self.fmt = None
        self.file_path = None

        for f in self.formats:
            key = "fmt_%s" % f
            if self.book.get(key):
                self.fmt = f
                self.file_path = self.book[key]
                break

        # If no format found, but book exists, maybe just list it?
        # But for download, we need a file.
        self.title = safe_filename(self.book.get('title', 'Unknown'))
        self.id = self.book['id']
        self.ext = self.fmt or "txt"
        logging.info(f"Initialized TalebookResource for book ID {self.id}, title: {self.title}, format: {self.fmt}, path: {self.file_path}")

    def get_display_name(self):
        # Format: ID.书名.ext
        name = "%d.%s.%s" % (self.id, self.title, self.ext)
        logging.info(f"****** Getting display name: {name}")
        return name

    def get_content_length(self):
        if self.file_path and os.path.exists(self.file_path):
            return os.path.getsize(self.file_path)
        return 0

    def get_content_type(self):
        types = {
            "epub": "application/epub+zip",
            "azw3": "application/x-mobi8-ebook",
            "mobi": "application/x-mobipocket-ebook",
            "pdf": "application/pdf",
            "txt": "text/plain",
        }
        result = types.get(self.fmt, "application/octet-stream")
        logging.info(f"****** Getting content type for format {self.fmt}: {result} for source path: {self.file_path}")
        return result

    def get_content(self):
        logging.info(f"****** Getting content for book ID {self.id}, path: {self.file_path}")
        if self.file_path and os.path.exists(self.file_path):
            return open(self.file_path, "rb")
        # Return an empty BytesIO object instead of raw bytes
        return BytesIO(b"")

    def support_etag(self):
        """Return True if this resource supports ETags"""
        return True

    def get_etag(self):
        """Return an ETag for this resource"""
        # Generate ETag based on file path and modification time
        if self.file_path and os.path.exists(self.file_path):
            try:
                stat = os.stat(self.file_path)
                # Use file size and modification time for ETag (WsgiDAV will add quotes)
                return f"{self.id}-{stat.st_size}-{int(stat.st_mtime)}"
            except:
                pass
        # Fallback: use book ID
        return f"{self.id}"

    def get_last_modified(self):
        """Return last modified time"""
        if self.file_path and os.path.exists(self.file_path):
            try:
                return os.path.getmtime(self.file_path)
            except:
                pass
        return None


class VirtualCollection(DAVCollection):
    def __init__(self, path, environ, title, provider, children=None):
        super(VirtualCollection, self).__init__(path, environ)
        self.title = title
        self.provider = provider
        self.fixed_children = children  # List of DAVResource objects

    def get_display_name(self):
        return self.title

    def get_member_list(self):
        if self.fixed_children is not None:
            return self.fixed_children
        return self.get_dynamic_members()

    def get_member_names(self):
        """Return list of (direct) collection member names (utf-8 byte strings)."""
        members = self.get_member_list()
        names = []
        for m in members:
            # Extract the name from the path (last component)
            if hasattr(m, 'path') and m.path:
                name = m.path.rstrip('/').split('/')[-1]
                names.append(name)
            elif hasattr(m, 'name'):
                names.append(m.name)
            elif hasattr(m, 'get_display_name'):
                names.append(m.get_display_name())
        return names

    def get_dynamic_members(self):
        return []

    def get_creation_date(self):
        """Return creation date as Unix timestamp (current time for virtual collections)"""
        return time.time()

    def get_last_modified(self):
        """Return last modified time as Unix timestamp (current time for virtual collections)"""
        return time.time()


class BooksCollection(VirtualCollection):
    def __init__(self, path, environ, title, provider, book_ids):
        super(BooksCollection, self).__init__(path, environ, title, provider)
        self.book_ids = book_ids

    def get_dynamic_members(self):
        books = []
        # Use cache.get_metadata() to fetch each book's metadata
        # Note: this is less efficient than batch fetch but cache API doesn't have batch method
        # The cache should have internal optimization

        try:
            for book_id in self.book_ids:
                try:
                    # Get metadata for this book
                    mi = self.provider.cache.get_metadata(book_id, get_cover=False, get_user_categories=False)
                    if not mi or mi.is_null('title'):
                        continue

                    logging.info(f"Fetching book ID {book_id}, title: {mi.title}, id:{mi.id}")
                    # Convert Metadata object to dict-like structure
                    item = {
                        'id': book_id,
                        'title': mi.title or 'Unknown',
                        'authors': mi.authors or [],
                        'fmt_epub': None,
                        'fmt_azw3': None,
                        'fmt_mobi': None,
                        'fmt_pdf': None,
                    }

                    # Get format information
                    formats = self.provider.cache.formats(book_id, verify_formats=False)
                    if formats:
                        for fmt in formats:
                            fmt_lower = fmt.lower()
                            if fmt_lower in SUPPORTED_FORMATS:
                                # Get the absolute path to the format file
                                fmt_path = self.provider.cache.format_abspath(book_id, fmt)
                                if fmt_path:
                                    item[f'fmt_{fmt_lower}'] = fmt_path
                    # Choose selected_fmt using SUPPORTED_FORMATS priority so
                    # display name extension and TalebookResource selection match.
                    selected_fmt = None
                    for f in SUPPORTED_FORMATS:
                        if item.get(f'fmt_{f}'):
                            selected_fmt = f
                            break

                    if not selected_fmt:
                        # No supported format found, skip this book
                        logging.info(f"No supported format found for book ID {book_id}, skipping")
                        continue
                    # Build filename with extension
                    base = self.path if self.path.endswith('/') else self.path + '/'
                    ext = selected_fmt if selected_fmt else 'txt'
                    book_name = f"{item['id']}.{safe_filename(item['title'])}.{ext}"
                    logging.info(f"Adding book resource: {book_name}")
                    books.append(TalebookResource(
                        base + book_name,
                        self.environ,
                        item,
                        self.provider.cache
                    ))
                except Exception as e:
                    logging.error(f"Error fetching book {book_id}: {e}")
                    continue

        except Exception as e:
            logging.error(f"Error fetching books for {self.path}: {e}")

        return books


class TalebookProvider(DAVProvider):
    def __init__(self, cache, get_session_func=None):
        super(TalebookProvider, self).__init__()
        self.cache = cache
        self.get_session_func = get_session_func
        self.sections = {
            "分类": "分类",
            "标签": "标签",
            "作者": "作者",
            "我的收藏": "我的收藏",
            "我的待读": "我的待读",
            "我的在读": "我的在读",
            "我的已读": "我的已读"
        }

    def _parse_book_id_from_filename(self, filename):
        """从文件名中解析book ID，过滤macOS隐藏文件"""
        # 忽略以.开头的文件（macOS隐藏文件如._filename）
        if filename.startswith('.'):
            return None

        try:
            # 文件名格式: ID.Title.ext
            book_id_str = filename.split('.')[0]
            if not book_id_str:  # 空字符串
                return None
            return int(book_id_str)
        except (ValueError, IndexError):
            return None

    def get_resource_inst(self, path, environ):
        # Log the original path for debugging
        original_path = path

        # Ensure path starts with /
        if not path.startswith("/"):
            path = "/" + path

        # Decode URL encoding (some clients may double-encode)
        path = unquote(path)
        # Handle potential double encoding
        if '%' in path:
            path = unquote(path)

        # Strip trailing slashes but keep leading /
        path = path.rstrip("/")
        if not path:
            path = "/"

        # Log the decoded path for debugging
        if original_path != path:
            logging.info(f"Path decoded: '{original_path}' -> '{path}'")

        if path == "/":
            return VirtualCollection("/", environ, "root", self, [
                VirtualCollection("/" + s, environ, s, self) for s in self.sections.keys()
            ])

        parts = path.lstrip("/").split("/")
        section = parts[0]
        logging.debug(f"Processing path: {path}, section: {section}, parts: {parts}")

        if section == "分类":
            return self.handle_custom(path, environ, parts)
        elif section == "标签":
            return self.handle_tags(path, environ, parts)
        elif section == "作者":
            return self.handle_authors(path, environ, parts)
        elif section == "我的收藏":
            return self.handle_favorite(path, environ, parts)
        elif section == "我的待读":
            return self.handle_wants(path, environ, parts)
        elif section == "我的在读":
            return self.handle_reading(path, environ, parts)
        elif section == "我的已读":
            return self.handle_read_done(path, environ, parts)

        return None

    def handle_custom(self, path, environ, parts):
        # Custom Categories generally refers to User Categories (tags) or #category column
        # The prompt says: "From custom category... show system category list... click to show books"
        # Since 'category' is a custom column usually in Talebook (#category)
        if len(parts) == 1:
            # List categories
            # Metadata for #category
            try:
                # We need to find if #category exists and list values.
                # cache.get_categories() returns a dict of categories.
                # Custom columns are usually keys like '#category'
                # In helper: self.calibre_db_cache.get_field_unique_values('#category')? Wait, check methods.
                pass
            except:
                pass

            # For now, let's assume we use what OPDS does or similar.
            # But specific Requirement: "Custom Category" -> "Classification List"
            # It implies the '#category' user column.

            # Let's try to get all values for '#category'.
            # cache.get_categories() should contain it if it's a category.
            # or getAllCategories()

            children = []
            try:
                # Check if #category exists
                if '#category' in self.cache.field_metadata:
                    # Retrieve values.
                    # cache.get_categories() returns a dict of categories.
                    # Custom columns are usually keys like '#category'
                    all_cats = self.cache.get_categories()
                    if '#category' in all_cats:
                        for cat in all_cats['#category']:
                            # cat is a Tag object usually, with .name
                            name = cat.name if hasattr(cat, 'name') else str(cat)
                            child_path = path if path.endswith('/') else path + '/'
                            child_path = child_path + name
                            children.append(VirtualCollection(child_path, environ, name, self))
            except Exception as e:
                logging.error(f"Error getting categories: {e}")
                import traceback
                logging.error(traceback.format_exc())

            return VirtualCollection(path, environ, "分类", self, children)

        elif len(parts) == 2:
            # List books in category
            cat_name = unquote(parts[1])  # Ensure decoded
            try:
                # ids = cache.get_books_for_category('#category', cat_name)
                # But 'get_books_for_category' might expect query name?
                # Alternative: search(f'#category:"={cat_name}"')
                ids = self.cache.search(f'#category:"={cat_name}"')
                return BooksCollection(path, environ, cat_name, self, ids)
            except Exception as e:
                logging.error(f"Error searching category {cat_name}: {e}")
                return None

        elif len(parts) == 3:
            # Book file
            # parts[2] is "ID.Title.ext"
            # We need to extract ID
            try:
                filename = unquote(parts[2])  # Ensure decoded
                book_id = self._parse_book_id_from_filename(filename)
                if book_id is None:
                    return None
                mi = self.cache.get_metadata(book_id, get_cover=False)
                if not mi:
                    return None

                item = self._build_book_item(book_id, mi)
                return TalebookResource(path, environ, item, self.cache)
            except Exception as e:
                logging.error(f"Error getting book {parts[2]}: {e}")
                return None

        return None

    def handle_tags(self, path, environ, parts):
        if len(parts) == 1:
            children = []
            try:
                for tag in self.cache.all_field_names('tags'):
                    child_path = path if path.endswith('/') else path + '/'
                    child_path = child_path + str(tag)
                    children.append(VirtualCollection(child_path, environ, str(tag), self))
            except Exception as e:
                logging.error(f"Error getting tags: {e}")
                pass
            return VirtualCollection(path, environ, "标签", self, children)
        elif len(parts) == 2:
            tag_name = unquote(parts[1])  # Ensure decoded
            try:
                ids = self.cache.search(f'tags:"={tag_name}"')
                return BooksCollection(path, environ, tag_name, self, ids)
            except:
                return None
        elif len(parts) == 3:
            try:
                filename = unquote(parts[2])  # Ensure decoded
                book_id = self._parse_book_id_from_filename(filename)
                if book_id is None:
                    return None
                mi = self.cache.get_metadata(book_id, get_cover=False)
                if not mi:
                    return None

                item = self._build_book_item(book_id, mi)
                return TalebookResource(path, environ, item, self.cache)
            except Exception as e:
                logging.error(f"Error getting book {parts[2]}: {e}")
                return None
        return None

    def handle_authors(self, path, environ, parts):
        if len(parts) == 1:
            children = []
            try:
                for author in self.cache.all_field_names('authors'):
                    # Author should be string
                    child_path = path if path.endswith('/') else path + '/'
                    child_path = child_path + str(author)
                    children.append(VirtualCollection(child_path, environ, str(author), self))
            except Exception as e:
                logging.error(f"Error getting authors: {e}")
                pass
            return VirtualCollection(path, environ, "作者", self, children)
        elif len(parts) == 2:
            author_name = unquote(parts[1])  # Ensure decoded
            try:
                ids = self.cache.search(f'authors:"={author_name}"')
                return BooksCollection(path, environ, author_name, self, ids)
            except:
                pass
        elif len(parts) == 3:
            try:
                filename = unquote(parts[2])  # Ensure decoded
                book_id = self._parse_book_id_from_filename(filename)
                if book_id is None:
                    return None
                mi = self.cache.get_metadata(book_id, get_cover=False)
                if not mi:
                    return None

                item = self._build_book_item(book_id, mi)
                return TalebookResource(path, environ, item, self.cache)
            except Exception as e:
                logging.error(f"Error getting book {parts[2]}: {e}")
                return None
        return None

    def _get_user_id_from_environ(self, environ):
        """从environ中获取用户ID"""
        # WebDAV认证后，用户信息应该在environ中
        # 这需要与auth.py中的认证逻辑配合
        username = environ.get('wsgidav.auth.user_name', None)
        if not username or not self.get_session_func:
            return None

        try:
            # 获取数据库session
            from webserver.models import Reader
            session = self.get_session_func()
            user = session.query(Reader).filter(Reader.username == username).first()
            return user.id if user else None
        except Exception as e:
            logging.error(f"Error getting user ID: {e}")
            return None

    def _get_reading_state_books(self, environ, filter_func, title):
        """获取符合条件的阅读状态书籍"""
        user_id = self._get_user_id_from_environ(environ)
        if not user_id:
            logging.warning("No user ID found in environ for reading state")
            return []

        try:
            from webserver.models import ReadingState
            session = self.get_session_func()
            reading_states = session.query(ReadingState).filter(
                ReadingState.reader_id == user_id
            ).all()

            # 应用过滤条件
            filtered_states = [state for state in reading_states if filter_func(state)]
            book_ids = [state.book_id for state in filtered_states]

            return book_ids
        except Exception as e:
            logging.error(f"Error getting reading state books: {e}")
            return []

    def handle_favorite(self, path, environ, parts):
        """处理收藏书籍"""
        if len(parts) == 1:
            # 列出收藏的书籍
            book_ids = self._get_reading_state_books(
                environ,
                lambda state: state.favorite == 1,
                "我的收藏"
            )
            return BooksCollection(path, environ, "我的收藏", self, book_ids)
        elif len(parts) == 2:
            # 直接是书籍文件
            try:
                filename = unquote(parts[1])  # Ensure decoded
                book_id = self._parse_book_id_from_filename(filename)
                if book_id is None:
                    return None
                mi = self.cache.get_metadata(book_id, get_cover=False)
                if not mi:
                    return None

                item = self._build_book_item(book_id, mi)
                return TalebookResource(path, environ, item, self.cache)
            except Exception as e:
                logging.error(f"Error getting book {parts[1]}: {e}")
                return None
        return None

    def handle_wants(self, path, environ, parts):
        """处理待读书籍"""
        if len(parts) == 1:
            book_ids = self._get_reading_state_books(
                environ,
                lambda state: state.wants == 1,
                "我的待读"
            )
            return BooksCollection(path, environ, "我的待读", self, book_ids)
        elif len(parts) == 2:
            try:
                filename = unquote(parts[1])  # Ensure decoded
                book_id = self._parse_book_id_from_filename(filename)
                if book_id is None:
                    return None
                mi = self.cache.get_metadata(book_id, get_cover=False)
                if not mi:
                    return None

                item = self._build_book_item(book_id, mi)
                return TalebookResource(path, environ, item, self.cache)
            except Exception as e:
                logging.error(f"Error getting book {parts[1]}: {e}")
                return None
        return None

    def handle_reading(self, path, environ, parts):
        """处理在读书籍"""
        if len(parts) == 1:
            book_ids = self._get_reading_state_books(
                environ,
                lambda state: state.read_state == 1,  # 在读状态
                "我的在读"
            )
            logging.info(f"Handling '在读' books, ids: {book_ids}")
            return BooksCollection(path, environ, "我的在读", self, book_ids)
        elif len(parts) == 2:
            try:
                filename = unquote(parts[1])  # Ensure decoded
                book_id = self._parse_book_id_from_filename(filename)
                if book_id is None:
                    return None
                mi = self.cache.get_metadata(book_id, get_cover=False)
                if not mi:
                    return None

                item = self._build_book_item(book_id, mi)
                return TalebookResource(path, environ, item, self.cache)
            except Exception as e:
                logging.error(f"Error getting book {parts[1]}: {e}")
                return None
        return None

    def handle_read_done(self, path, environ, parts):
        """处理已读完书籍"""
        if len(parts) == 1:
            book_ids = self._get_reading_state_books(
                environ,
                lambda state: state.read_state == 2,  # 已读完状态
                "我的已读"
            )
            return BooksCollection(path, environ, "我的已读", self, book_ids)
        elif len(parts) == 2:
            try:
                filename = unquote(parts[1])  # Ensure decoded
                book_id = self._parse_book_id_from_filename(filename)
                if book_id is None:
                    return None
                mi = self.cache.get_metadata(book_id, get_cover=False)
                if not mi:
                    return None

                item = self._build_book_item(book_id, mi)
                return TalebookResource(path, environ, item, self.cache)
            except Exception as e:
                logging.error(f"Error getting book {parts[1]}: {e}")
                return None
        return None

    def _build_book_item(self, book_id, mi):
        """从Metadata对象构建book item字典"""
        item = {
            'id': book_id,
            'title': mi.title or 'Unknown',
            'authors': mi.authors or [],
            'fmt_epub': None,
            'fmt_azw3': None,
            'fmt_mobi': None,
            'fmt_pdf': None,
        }

        # Get format information
        formats = self.cache.formats(book_id, verify_formats=False)
        if formats:
            for fmt in formats:
                fmt_lower = fmt.lower()
                if fmt_lower in SUPPORTED_FORMATS:
                    fmt_path = self.cache.format_abspath(book_id, fmt)
                    if fmt_path:
                        item[f'fmt_{fmt_lower}'] = fmt_path

        return item
