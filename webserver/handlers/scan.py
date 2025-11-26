#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging
import traceback
from gettext import gettext as _

import sqlalchemy
import tornado

from webserver import loader
from webserver.handlers.base import BaseHandler, auth, js, is_admin
from webserver.models import ScanFile
from webserver.services.scan import ScanService

CONF = loader.get_settings()
SCAN_EXT = ["azw", "azw3", "epub", "mobi", "pdf", "txt"]
SCAN_DIR_PREFIX = "/data/"  # 限定扫描必须在/data/目录下，以防黑客扫描到其他系统目录


class Scanner:
    def __init__(self, calibre_db, ScopedSession, user_id=None):
        self.db = calibre_db
        self.user_id = user_id
        self.session = ScopedSession()

    def __del__(self):
        # 确保在对象销毁时关闭数据库会话
        if hasattr(self, 'session') and self.session:
            try:
                self.session.close()
            except Exception:
                pass

    def save_or_rollback(self, row):
        try:
            row.save()
            self.session.commit()
            bid = "[ book-id=%s ]" % row.book_id
            logging.error(
                "update: status=%-5s, path=%s %s",
                row.status,
                row.path,
                bid if row.book_id > 0 else "",
            )
            return True
        except Exception as err:
            logging.error(traceback.format_exc())
            self.session.rollback()
            logging.error("save error: %s", err)
            return False

    def summary(self):
        done_status = [ScanFile.EXIST, ScanFile.IMPORTED]
        query = self.session.query(ScanFile)
        total = query.count()
        done = query.filter(ScanFile.status.in_(done_status)).count()
        todo = total - done
        return {"total": total, "done": done, "todo": todo}

    def run_scan(self, path_dir):
        ScanService().do_scan(path_dir)

    def delete(self, hashlist):
        query = self.session.query(ScanFile)
        if isinstance(hashlist, (list, tuple)):
            query = query.filter(ScanFile.hash.in_(hashlist))
        elif isinstance(hashlist, str):
            query = query.filter(ScanFile.hash == hashlist)
        count = query.delete()
        self.session.commit()
        return count

    def resume_last_import(self):
        # TODO
        return False

    def build_query(self, hashlist):
        query = self.session.query(ScanFile).filter(
            ScanFile.status == ScanFile.READY
        )  # .filter(ScanFile.import_id == 0)
        if isinstance(hashlist, (list, tuple)):
            query = query.filter(ScanFile.hash.in_(hashlist))
        elif isinstance(hashlist, str):
            query = query.filter(ScanFile.hash == hashlist)
        return query

    def run_import(self, hashlist):
        if self.resume_last_import():
            return 1

        total = self.build_query(hashlist).count()
        ScanService().do_import(hashlist, self.user_id)
        return total

    def import_status(self):
        import_id = self.session.query(sqlalchemy.func.max(ScanFile.import_id)).scalar()
        if import_id is None:
            return (0, {})
        query = self.session.query(ScanFile.status).filter(
            ScanFile.import_id == import_id
        )
        return (import_id, self.count(query))

    def scan_status(self):
        scan_id = self.session.query(sqlalchemy.func.max(ScanFile.scan_id)).scalar()
        if scan_id is None:
            return (0, {})
        query = self.session.query(ScanFile.status).filter(ScanFile.scan_id == scan_id)
        return (scan_id, self.count(query))

    def count(self, query):
        rows = query.all() if query else []
        count = {
            "total": len(rows),
            ScanFile.NEW: 0,
            ScanFile.DROP: 0,
            ScanFile.EXIST: 0,
            ScanFile.READY: 0,
            ScanFile.IMPORTED: 0,
        }
        for row in rows:
            if row.status not in count:
                count[row.status] = 0
            count[row.status] += 1
        return count

    def close(self):
        """主动关闭数据库会话"""
        if hasattr(self, 'session') and self.session:
            try:
                self.session.close()
                self.session = None
            except Exception as e:
                logging.error(f"Error closing session: {e}")


class ScanList(BaseHandler):
    @js
    @auth
    def get(self):
        if not self.admin_user:
            return {"err": "permission.not_admin", "msg": _("当前用户非管理员")}

        scanner = None
        try:
            num = max(10, int(self.get_argument("num", 20)))
            page = max(0, int(self.get_argument("page", 1)) - 1)
            sort = self.get_argument("sort", "create_time")
            desc = self.get_argument("desc", "true")
            filter = self.get_argument("filter", "all")
            logging.debug("num=%d, page=%d, sort=%s, desc=%s" % (num, page, sort, desc))

            # get order by query args
            order = {
                "id": ScanFile.id,
                "path": ScanFile.path,
                "name": ScanFile.name,
                "create_time": ScanFile.create_time,
                "update_time": ScanFile.update_time,
            }.get(sort, ScanFile.create_time)
            order = order.asc() if desc == "false" else order.desc()
            query = self.sqlite_session.query(ScanFile).order_by(order)

            done_status = [ScanFile.EXIST, ScanFile.IMPORTED]
            if filter == "todo":
                query = query.filter(ScanFile.status.not_in(done_status))
            elif filter == "done":
                query = query.filter(ScanFile.status.in_(done_status))
            total = query.count()

            start = page * num
            response = []
            for s in query.limit(num).offset(start).all():
                d = {
                    "id": s.id,
                    "path": s.path,
                    "hash": s.hash,
                    "title": s.title,
                    "author": s.author,
                    "publisher": s.publisher,
                    "tags": s.tags,
                    "status": s.status,
                    "book_id": s.book_id,
                    "create_time": (
                        s.create_time.strftime("%Y-%m-%d %H:%M:%S")
                        if s.create_time
                        else "N/A"
                    ),
                    "update_time": (
                        s.update_time.strftime("%Y-%m-%d %H:%M:%S")
                        if s.update_time
                        else "N/A"
                    ),
                }
                response.append(d)

            scanner = Scanner(self.calibre_db, self.settings["ScopedSession"])
            summary = scanner.summary()

            return {
                "err": "ok",
                "items": response,
                "total": total,
                "scanning": ScanService.static_is_scanning,
                "importing": ScanService.static_is_importing,
                "summary": summary,
                "scan_dir": CONF["scan_upload_path"],
            }
        finally:
            if scanner:
                try:
                    scanner.close()
                except Exception as e:
                    logging.error(f"Error closing scanner: {e}")


class ScanMark(BaseHandler):
    @js
    @is_admin
    def post(self):
        return {"err": "ok", "msg": _("发送成功")}


class ScanRun(BaseHandler):
    @js
    @is_admin
    def post(self):
        path = CONF["scan_upload_path"]
        if not path.startswith(SCAN_DIR_PREFIX):
            return {
                "err": "params.error",
                "msg": _("书籍导入目录必须是%s的子目录") % SCAN_DIR_PREFIX,
            }

        scanner = None
        try:
            scanner = Scanner(self.calibre_db, self.settings["ScopedSession"])
            total = scanner.run_scan(path)
            if total == 0:
                return {"err": "empty", "msg": _("目录中没有找到符合要求的书籍文件！")}
            return {"err": "ok", "msg": _("开始扫描了"), "total": total}
        finally:
            if scanner:
                try:
                    scanner.close()
                except Exception as e:
                    logging.error(f"Error closing scanner: {e}")


class ScanDelete(BaseHandler):
    @js
    @is_admin
    def post(self):
        req = tornado.escape.json_decode(self.request.body)
        hashlist = req["hashlist"]
        if not hashlist:
            return {"err": "params.error", "msg": _("参数错误")}
        if hashlist == "all":
            hashlist = None

        scanner = None
        try:
            scanner = Scanner(self.calibre_db, self.settings["ScopedSession"])
            count = scanner.delete(hashlist)
            return {"err": "ok", "msg": _("删除成功"), "count": count}
        finally:
            if scanner:
                try:
                    scanner.close()
                except Exception as e:
                    logging.error(f"Error closing scanner: {e}")


class ScanStatus(BaseHandler):
    @js
    @is_admin
    def get(self):
        scanner = None
        try:
            scanner = Scanner(self.calibre_db, self.settings["ScopedSession"])
            status = scanner.scan_status()[1]
            summary = scanner.summary()
            return {
                "err": "ok",
                "msg": _("成功"),
                "status": status,
                "summary": summary,
                "scanning": ScanService.static_is_scanning,
                "importing": ScanService.static_is_importing,
            }
        finally:
            if scanner:
                try:
                    scanner.close()
                except Exception as e:
                    logging.error(f"Error closing scanner: {e}")


class ImportRun(BaseHandler):
    @js
    @is_admin
    def post(self):
        scanner = None
        try:
            req = tornado.escape.json_decode(self.request.body)
            hashlist = req["hashlist"]
            if not hashlist:
                return {"err": "params.error", "msg": _("参数错误")}
            if hashlist == "all":
                hashlist = None

            scanner = Scanner(self.calibre_db, self.settings["ScopedSession"], self.user_id())
            total = scanner.run_import(hashlist)
            if total == 0:
                return {"err": "empty", "msg": _("没有等待导入书库的书籍！")}
            return {"err": "ok", "msg": _("扫描成功")}
        except Exception as e:
            logging.error(f"ImportRun error: {e}")
            return {"err": "server.error", "msg": str(e)}
        finally:
            # 确保 Scanner 对象被正确清理
            if scanner:
                try:
                    scanner.close()
                except Exception as e:
                    logging.error(f"Error closing scanner: {e}")


class ImportStatus(BaseHandler):
    @js
    @is_admin
    def get(self):
        scanner = None
        try:
            scanner = Scanner(self.calibre_db, self.settings["ScopedSession"])
            status = scanner.import_status()[1]
            summary = scanner.summary()
            return {
                "err": "ok", "msg": _("成功"),
                "status": status,
                "summary": summary,
                "scanning": ScanService.static_is_scanning,
                "importing": ScanService.static_is_importing
            }
        finally:
            if scanner:
                try:
                    scanner.close()
                except Exception as e:
                    logging.error(f"Error closing scanner: {e}")


class BatchAddRun(BaseHandler):
    @js
    @is_admin
    def post(self):
        """批量添加实体书 - 从CSV文件导入"""
        from webserver.services.batch_add import BatchAddService

        # 检查是否上传了文件
        if "csv_file" not in self.request.files:
            return {"err": "params.error", "msg": _("请选择CSV文件")}

        fileinfo = self.request.files["csv_file"][0]
        filename = fileinfo["filename"]
        csv_data = fileinfo["body"]

        # 检查文件扩展名
        if not filename.lower().endswith('.csv'):
            return {"err": "params.error", "msg": _("文件格式错误，请上传CSV文件")}

        try:
            # 保存临时文件
            import tempfile
            with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.csv') as tmp_file:
                tmp_file.write(csv_data)
                csv_path = tmp_file.name

            # 验证CSV文件格式
            import csv
            import codecs

            # 尝试检测编码
            try:
                with open(csv_path, 'rb') as f:
                    raw_data = f.read()
                    # 尝试UTF-8
                    try:
                        raw_data.decode('utf-8')
                        encoding = 'utf-8'
                    except:
                        # 尝试GBK
                        try:
                            raw_data.decode('gbk')
                            encoding = 'gbk'
                        except:
                            encoding = 'utf-8'
            except:
                encoding = 'utf-8'

            with codecs.open(csv_path, 'r', encoding=encoding) as f:
                # 使用Tab作为分隔符
                reader = csv.DictReader(f, delimiter='\t')

                # 检查是否有isbn字段
                if 'isbn' not in reader.fieldnames:
                    import os
                    os.unlink(csv_path)
                    return {"err": "params.error", "msg": _("CSV文件必须包含isbn字段")}

                # 读取所有行
                rows = list(reader)
                if len(rows) == 0:
                    import os
                    os.unlink(csv_path)
                    return {"err": "params.error", "msg": _("CSV文件中没有数据")}

            # 启动批量添加服务
            service = BatchAddService()
            total = service.start_batch_add(csv_path, filename, self.user_id())

            return {"err": "ok", "msg": _("开始批量添加实体书"), "total": total}

        except Exception as e:
            logging.error(f"BatchAddRun error: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return {"err": "server.error", "msg": str(e)}


class BatchAddStatus(BaseHandler):
    @js
    @is_admin
    def get(self):
        """获取批量添加状态"""
        from webserver.services.batch_add import BatchAddService

        scanner = None
        try:
            scanner = Scanner(self.calibre_db, self.settings["ScopedSession"])
            summary = scanner.summary()

            service = BatchAddService()
            status = service.get_status()

            return {
                "err": "ok",
                "msg": _("成功"),
                "status": status,
                "summary": summary,
                "batch_adding": service.is_running()
            }
        except Exception as e:
            logging.error(f"BatchAddStatus error: {e}")
            return {"err": "server.error", "msg": str(e)}
        finally:
            if scanner:
                try:
                    scanner.close()
                except Exception as e:
                    logging.error(f"Error closing scanner: {e}")


def routes():
    return [
        (r"/api/admin/scan/list", ScanList),
        (r"/api/admin/scan/run", ScanRun),
        (r"/api/admin/scan/status", ScanStatus),
        (r"/api/admin/scan/delete", ScanDelete),
        (r"/api/admin/scan/mark", ScanMark),
        (r"/api/admin/import/run", ImportRun),
        (r"/api/admin/import/status", ImportStatus),
        (r"/api/admin/batch_add/run", BatchAddRun),
        (r"/api/admin/batch_add/status", BatchAddStatus),
    ]
