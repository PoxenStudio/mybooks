# -*- coding: UTF-8 -*-
import os
import re
import logging
from urllib.parse import unquote
from wsgidav.dav_provider import DAVProvider, DAVCollection, DAVNonCollection
from wsgidav.dav_error import DAVError, HTTP_NOT_FOUND, HTTP_FORBIDDEN

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
        self.formats = ["epub", "azw3", "mobi", "pdf"]
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
        }
        return types.get(self.fmt, "application/octet-stream")

    def get_content(self):
        if self.file_path and os.path.exists(self.file_path):
            return open(self.file_path, "rb")
        return b""

    def support_etag(self):
        """Return True if this resource supports ETags"""
        return True

    def get_etag(self):
        """Return an ETag for this resource"""
        # Generate ETag based on file path and modification time
        if self.file_path and os.path.exists(self.file_path):
            try:
                stat = os.stat(self.file_path)
                # Use file size and modification time for ETag
                return f'"{self.id}-{stat.st_size}-{int(stat.st_mtime)}"'
            except:
                pass
        # Fallback: use book ID
        return f'"{self.id}"'

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
                    mi = self.provider.cache.get_metadata(book_id, get_cover=False)
                    if not mi:
                        continue

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
                    selected_fmt = None
                    if formats:
                        for fmt in formats:
                            fmt_lower = fmt.lower()
                            if fmt_lower in ['epub', 'azw3', 'mobi', 'pdf']:
                                # Get the absolute path to the format file
                                fmt_path = self.provider.cache.format_abspath(book_id, fmt)
                                if fmt_path:
                                    item[f'fmt_{fmt_lower}'] = fmt_path
                                    # Use first available format in priority order
                                    if not selected_fmt and fmt_lower in ['epub', 'azw3', 'mobi', 'pdf']:
                                        selected_fmt = fmt_lower

                    # Build filename with extension
                    base = self.path if self.path.endswith('/') else self.path + '/'
                    ext = selected_fmt if selected_fmt else 'txt'
                    book_name = f"{item['id']}.{safe_filename(item['title'])}.{ext}"
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

class LetterCollection(VirtualCollection):
    def __init__(self, path, environ, letter, provider):
        super(LetterCollection, self).__init__(path, environ, letter, provider)
        self.letter = letter.upper()

    def get_pinyin_initial(self, text):
        """Get pinyin initial from Chinese text"""
        import opencc

        # Simple pinyin initial mapping for common Chinese characters
        # This is a simplified approach. For production, consider using pypinyin library
        try:
            # Convert to simplified Chinese first
            converter = opencc.OpenCC('t2s')  # Traditional to Simplified
            text = converter.convert(text)

            # For basic implementation, just check first character
            if not text:
                return 'A'

            first_char = text[0].upper()
            # If it's already ASCII, return it
            if first_char.isalpha():
                return first_char

            # For Chinese characters, we need more sophisticated mapping
            # This is a placeholder - in production you'd use pypinyin
            # For now, return 'A' for non-ASCII
            return 'A'
        except:
            return 'A'

    def get_dynamic_members(self):
        # For better performance, we'll just search books with title_sort starting with the letter
        # title_sort is usually in ASCII format
        try:
            # Search by title_sort (which is ASCII)
            query = f'title_sort:~^{self.letter}'
            ids = self.provider.cache.search(query)

            # If no results and letter is valid, try all books and filter
            if not ids and len(self.letter) == 1 and self.letter.isalpha():
                # Get all books and filter by first letter of title_sort
                all_ids = list(self.provider.cache.all_book_ids())
                filtered_ids = []

                # Batch fetch to improve performance
                for book_id in all_ids[:1000]:  # Limit for performance
                    try:
                        title_sort = self.provider.cache.field_for('title_sort', book_id)
                        if title_sort and title_sort[0].upper() == self.letter:
                            filtered_ids.append(book_id)
                    except:
                        continue

                ids = filtered_ids

            return BooksCollection(self.path, self.environ, self.letter, self.provider, ids).get_dynamic_members()
        except Exception as e:
            logging.error(f"Error searching books for letter {self.letter}: {e}")
            return []


class TalebookProvider(DAVProvider):
    def __init__(self, cache):
        super(TalebookProvider, self).__init__()
        self.cache = cache
        self.sections = {
            "分类": "分类",
            "标签": "标签",
            "作者": "作者",
            "所有书籍": "所有书籍"
        }

    def get_resource_inst(self, path, environ):
        # Ensure path starts with /
        if not path.startswith("/"):
            path = "/" + path

        # Decode URL encoding
        path = unquote(path)

        # Strip trailing slashes but keep leading /
        path = path.rstrip("/")
        if not path:
            path = "/"

        if path == "/":
            return VirtualCollection("/", environ, "root", self, [
                VirtualCollection("/" + s, environ, s, self) for s in self.sections.keys()
            ])

        parts = path.lstrip("/").split("/")
        section = parts[0]

        if section == "分类":
            return self.handle_custom(path, environ, parts)
        elif section == "标签":
            return self.handle_tags(path, environ, parts)
        elif section == "作者":
            return self.handle_authors(path, environ, parts)
        elif section == "所有书籍":
            return self.handle_all(path, environ, parts)

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
                # In book.py: self.calibre_db.field_metadata['#category']
                cats = self.cache.get_categories()
                # cats is dict {field: values} or similar
                # actually cache.get_categories() returns keys of categories?
                # No, look at opds.py: categories = self.calibre_db.get_categories() -> dict of category items
                # But we want specific values for the '#category' field.
                # If '#category' is not in standard categories, we might need other way.
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
            cat_name = parts[1]
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
            # parts[2] is "ID. Title.ext"
            # We need to extract ID
            try:
                book_id = int(parts[2].split(".")[0])
                book = self.cache.get_data_as_dict(ids=[book_id])[0]
                return TalebookResource(path, environ, book, self.cache)
            except:
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
            tag_name = parts[1]
            try:
                ids = self.cache.search(f'tags:"={tag_name}"')
                return BooksCollection(path, environ, tag_name, self, ids)
            except:
                return None
        elif len(parts) == 3:
            try:
                book_id = int(parts[2].split(".")[0])
                book = self.cache.get_data_as_dict(ids=[book_id])[0]
                return TalebookResource(path, environ, book, self.cache)
            except:
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
            author_name = parts[1]
            try:
                ids = self.cache.search(f'authors:"={author_name}"')
                return BooksCollection(path, environ, author_name, self, ids)
            except:
                pass
        elif len(parts) == 3:
            try:
                book_id = int(parts[2].split(".")[0])
                book = self.cache.get_data_as_dict(ids=[book_id])[0]
                return TalebookResource(path, environ, book, self.cache)
            except:
                pass
        return None

    def handle_all(self, path, environ, parts):
        if len(parts) == 1:
            # A-Z
            import string
            letters = string.ascii_uppercase
            base = path if path.endswith('/') else path + '/'
            children = [VirtualCollection(base + l, environ, l, self) for l in letters]
            return VirtualCollection(path, environ, "所有书籍", self, children)
        elif len(parts) == 2:
            letter = parts[1]
            return LetterCollection(path, environ, letter, self)
        elif len(parts) == 3:
            try:
                book_id = int(parts[2].split(".")[0])
                book = self.cache.get_data_as_dict(ids=[book_id])[0]
                return TalebookResource(path, environ, book, self.cache)
            except:
                pass
        return None
