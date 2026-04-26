#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging
import traceback
from webserver.i18n import _
import tornado

from webserver import loader
from webserver.handlers.base import BaseHandler, auth, js, is_admin
from webserver.models import ScanFile
from webserver.services.scan_service import ScanService

CONF = loader.get_settings()
SCAN_EXT = ["azw", "azw3", "epub", "mobi", "pdf", "txt"]
SCAN_DIR_PREFIX = "/data/"  # 限定扫描必须在/data/目录下，以防黑客扫描到其他系统目录


class Scanner:
    def __init__(self, calibre_db, ScopedSession, user_id=None):
        self.db = calibre_db
        self.user_id = user_id
        self.session = ScopedSession()
        self.cached_status = None

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
        try:
            query = self.session.query(ScanFile)
            total = query.count()
            done = query.filter(ScanFile.status.in_(done_status)).count()
            todo = total - done
        except Exception as e:
            logging.error(f"Error in summary: {e}")
            if self.cached_status:
                return self.cached_status
        self.cached_status = {"total": total, "done": done, "todo": todo}
        return self.cached_status

    def delete(self, hashlist):
        query = self.session.query(ScanFile)
        if isinstance(hashlist, (list, tuple)):
            query = query.filter(ScanFile.hash.in_(hashlist))
        elif isinstance(hashlist, str):
            query = query.filter(ScanFile.hash == hashlist)
        count = query.delete()
        self.session.commit()
        return count

    def import_status(self):
        import_id = ScanService.importing_id()
        status = ScanService.status_count()
        status["total"] = ScanService.total_files_in_task()
        return (import_id, status, ScanService.get_invalid_folders())

    def close(self):
        """主动关闭数据库会话"""
        if hasattr(self, 'session') and self.session:
            try:
                self.session.close()
                self.session = None
            except Exception as e:
                logging.error(f"Error closing session: {e}")


class ImportList(BaseHandler):
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
                "status": ScanFile.status,
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
                    "import_type": s.import_type if s.import_type is not None else 0,
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
                "scanning": ScanService.static_is_importing,
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


class ImportDelete(BaseHandler):
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


class ImportRun(BaseHandler):
    @js
    @is_admin
    def post(self):
        try:
            req = tornado.escape.json_decode(self.request.body)
            filelist = req.get("filelist", "all")
            if not filelist:
                return {"err": "params.error", "msg": _("参数错误")}
            if ScanService.is_importing():
                return {"err": "empty", "msg": _("没有等待导入书库的书籍！")}
            ScanService().do_import(filelist, self.user_id())
            return {"err": "ok", "msg": _("扫描成功")}
        except Exception as e:
            logging.error(f"ImportRun error: {e}")
            return {"err": "server.error", "msg": str(e)}


class ImportStatus(BaseHandler):
    @js
    @is_admin
    def get(self):
        scanner = None
        try:
            scanner = Scanner(self.calibre_db, self.settings["ScopedSession"], self.user_id())
            import_id, status, failed_path = scanner.import_status()
            summary = scanner.summary()
            return {
                "err": "ok", "msg": _("成功"),
                "task": import_id,
                "status": status,
                "summary": summary,
                "scanning": ScanService.static_is_importing,
                "ignored_errors": failed_path,
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
            scanner = Scanner(self.calibre_db, self.settings["ScopedSession"], self.user_id())
            service = BatchAddService()
            running = service.is_running()

            return {
                "err": "ok",
                "msg": _("成功"),
                "status": service.get_status() if running else {},
                "summary": scanner.summary() if running else {},
                "batch_adding": running
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


class AudioImportRun(BaseHandler):
    @js
    @is_admin
    def post(self):
        from webserver.services.audios_import import AudioBookImporter

        if AudioBookImporter.is_running():
            return {"err": "running", "msg": _("有声书导入任务正在运行中，请稍候")}

        AudioBookImporter().do_import(self.user_id())
        return {"err": "ok", "msg": _("有声书导入任务已启动")}


class AudioImportStatus(BaseHandler):
    @js
    @is_admin
    def get(self):
        from webserver.services.audios_import import AudioBookImporter

        scanner = None
        try:
            scanner = Scanner(self.calibre_db, self.settings["ScopedSession"])
            running = AudioBookImporter.is_running()
            return {
                "err": "ok",
                "msg": _("成功"),
                "status": AudioBookImporter.get_status() if running else {},
                "summary": scanner.summary() if running else {},
                "audio_importing": running,
            }
        except Exception as e:
            logging.error(f"AudioImportStatus error: {e}")
            return {"err": "server.error", "msg": str(e)}
        finally:
            if scanner:
                try:
                    scanner.close()
                except Exception as e:
                    logging.error(f"Error closing scanner: {e}")


def routes():
    return [
        (r"/api/admin/import/list", ImportList),
        (r"/api/admin/import/delete", ImportDelete),
        (r"/api/admin/import/run", ImportRun),
        (r"/api/admin/import/status", ImportStatus),
        (r"/api/admin/batch_add/run", BatchAddRun),
        (r"/api/admin/batch_add/status", BatchAddStatus),
        (r"/api/admin/audio_import/run", AudioImportRun),
        (r"/api/admin/audio_import/status", AudioImportStatus),
    ]
