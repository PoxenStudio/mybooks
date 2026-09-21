#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import logging
from functools import cmp_to_key

import tornado.escape
import tornado.web

from webserver import utils
from webserver.base import folder_helper as fh
from webserver.constants import CALIBRE_COLUMN_FOLDER, COLUMN_FOLDER
from webserver.handlers.base import BaseHandler, ListHandler, auth, js
from webserver.i18n import _

CANDIDATE_LIMIT = 100


def _invalid_folder():
    return {"err": "params.folder.invalid", "msg": _("目录名无效：每级 1-%d 个字符，不含标点，最多 %d 级") % (fh.MAX_SEGMENT_LEN, fh.MAX_DEPTH)}


class BookFolder(BaseHandler):
    @js
    @auth
    def post(self, id):
        book_id = int(id)
        if not self.get_book(book_id, raise_exception=False):
            return {"err": "params.book.invalid", "msg": _("书籍不存在")}
        if not self.is_admin() and not self.is_book_owner(book_id, self.user_id()):
            return {"err": "user.no_permission", "msg": _("无权限")}

        data = tornado.escape.json_decode(self.request.body)
        try:
            folder = fh.normalize_folder(data.get(COLUMN_FOLDER, ""))
        except ValueError:
            return _invalid_folder()
        try:
            self.calibre_db_cache.set_field(CALIBRE_COLUMN_FOLDER, {book_id: folder})
            return {"err": "ok", "msg": _("目录更新成功")}
        except Exception as e:
            logging.error(f"Error updating folder for book {book_id}: {e}")
            return {"err": "internal", "msg": _("更新目录失败")}


class BookFolderBatch(BaseHandler):
    @js
    @auth
    def post(self):
        if not self.is_admin():
            return {"err": "user.no_permission", "msg": _("无权限")}

        data = tornado.escape.json_decode(self.request.body)
        try:
            ids = {int(i) for i in data.get("ids") or []}
            folder = fh.normalize_folder(data.get(COLUMN_FOLDER, ""))
        except (ValueError, TypeError):
            return _invalid_folder()
        if not ids:
            return {"err": "params.invalid", "msg": _("未选择书籍")}

        try:
            with self.db_lock:
                ids &= set(self.calibre_db_cache.all_book_ids())
                self.calibre_db_cache.set_field(CALIBRE_COLUMN_FOLDER, {i: folder for i in ids})
            return {"err": "ok", "msg": _("成功更新 %d 本书籍目录") % len(ids), "count": len(ids)}
        except Exception as e:
            logging.error(f"Error batch updating folder: {e}")
            return {"err": "internal", "msg": _("批量更新目录失败")}


class FolderList(BaseHandler):
    @js
    def get(self):
        if not self.current_user:
            return {"err": "ok", "folders": [], "root_count": 0, "max_depth": fh.MAX_DEPTH}
        with self.db_lock:
            counts = fh.folder_counts(self.calibre_db_cache)
            total = len(self.calibre_db_cache.all_book_ids())
        return {"err": "ok", "folders": fh.build_tree(counts), "root_count": max(0, total - sum(counts.values())), "max_depth": fh.MAX_DEPTH}


class FolderBooks(ListHandler):
    def _book_ids(self, path):
        table = fh.folder_table(self.calibre_db_cache)
        if table is None:
            return set()
        with self.db_lock:
            if path:
                ids = {i for i, v in table.id_map.items() if v == path}
                return set().union(*(table.col_book_map.get(i, ()) for i in ids))
            in_folder = set().union(*table.col_book_map.values()) if table.col_book_map else set()
            return set(self.calibre_db_cache.all_book_ids()) - in_folder

    @js
    def get(self):
        try:
            path = fh.normalize_folder(self.get_argument("path", ""))
        except ValueError:
            return _invalid_folder()
        books = self.load_books_by_ids(self._book_ids(path))
        books.sort(key=cmp_to_key(utils.compare_books_by_rating_or_id), reverse=True)
        return self.get_book_list(books, title=path or "/")


class FolderRename(BaseHandler):
    @js
    @auth
    def post(self):
        if not self.is_admin():
            return {"err": "user.no_permission", "msg": _("无权限")}

        data = tornado.escape.json_decode(self.request.body)
        try:
            path = fh.normalize_folder(data.get("path", ""))
            name = fh.normalize_segment(data.get("name", ""))
        except ValueError:
            return _invalid_folder()
        if not path:
            return _invalid_folder()

        table = fh.folder_table(self.calibre_db_cache)
        if table is None:
            return {"err": "params.folder.not_found", "msg": _("目录不存在")}
        with self.db_lock:
            id_of = {v: i for i, v in table.id_map.items()}
            plan = fh.plan_rename(id_of, path, name)
            if not plan:
                return {"err": "params.folder.not_found", "msg": _("目录不存在")}
            lower_ids = {v.lower(): i for v, i in id_of.items()}
            merged = [(old, new) for old, new in plan.items() if lower_ids.get(new.lower(), id_of[old]) != id_of[old]]
            count = sum(len(table.col_book_map.get(id_of[old], ())) for old, _new in merged)
            if merged and not data.get("merge"):
                return {"err": "folder.exists", "msg": _("目录已存在，合并后无法撤回"), "exists": True, "count": count, "target": merged[0][1]}
            try:
                self.calibre_db_cache.rename_items(CALIBRE_COLUMN_FOLDER, {id_of[old]: new for old, new in plan.items() if old != new})
            except Exception as e:
                logging.error(f"Error renaming folder {path} to {name}: {e}")
                return {"err": "internal", "msg": _("重命名目录失败")}
        return {"err": "ok", "msg": _("目录重命名成功"), "path": fh.FOLDER_SEP.join(path.split(fh.FOLDER_SEP)[:-1] + [name]), "merged": count}


class FolderCandidates(BaseHandler):
    @js
    @auth
    def get(self):
        try:
            level = int(self.get_argument("level", "1"))
            parent = fh.normalize_folder(self.get_argument("parent", ""))
        except ValueError:
            return _invalid_folder()
        parent_parts = fh.split_folder(parent)
        if not 1 <= level <= fh.MAX_DEPTH or len(parent_parts) != level - 1:
            return _invalid_folder()
        q = self.get_argument("q", "").strip().lower()

        with self.db_lock:
            counts = fh.folder_counts(self.calibre_db_cache)
        items = [{"name": n, "count": c} for n, c in fh.candidate_names(fh.build_tree(counts), parent_parts)]
        if q:
            items = [i for i in items if q in i["name"].lower()]
        return {"err": "ok", "items": items[:CANDIDATE_LIMIT], "max_depth": fh.MAX_DEPTH}


def routes():
    return [
        (r"/api/book/([0-9]+)/folder", BookFolder),
        (r"/api/book/folder", BookFolderBatch),
        (r"/api/folders", FolderList),
        (r"/api/folder/books", FolderBooks),
        (r"/api/folder/rename", FolderRename),
        (r"/api/folder/candidates", FolderCandidates),
    ]
