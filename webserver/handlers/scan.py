#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging
import os
import traceback
from sqlalchemy import func

from webserver.i18n import _
from webserver import constants
import tornado

from webserver import loader
from webserver.handlers.base import BaseHandler, auth, js, is_admin
from webserver.models import ScanFile
from webserver.services.scan_service import ScanService
from webserver.services.audios_import import AudioBookImporter

CONF = loader.get_settings()
SCAN_EXT = ["azw", "azw3", "epub", "mobi", "pdf", "txt"]
SCAN_DIR_PREFIX = "/data/"  # 限定扫描必须在/data/目录下，以防黑客扫描到其他系统目录

# 批量选择/批量删除允许的状态白名单（"todo" 单列；IMPORTED 无需再处理，永不放行）
SELECTOR_STATUSES = (
    ScanFile.NEW,
    ScanFile.READY,
    ScanFile.DROP,
    ScanFile.EXIST,
    ScanFile.INVALID,
    ScanFile.MISSED,
    ScanFile.PERMISSION,
)


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
        try:
            # 单次 GROUP BY 聚合取代三个 COUNT：本方法挂在轮询热路径上，
            # 无 status 索引时每个 COUNT 都是一次全表扫
            counts = dict(
                self.session.query(ScanFile.status, func.count(ScanFile.id))
                .group_by(ScanFile.status)
                .all()
            )
            total = sum(counts.values())
            done = counts.get(ScanFile.EXIST, 0) + counts.get(ScanFile.IMPORTED, 0)
            ready = counts.get(ScanFile.READY, 0)
            todo = total - done
        except Exception as e:
            logging.error(f"Error in summary: {e}")
            if self.cached_status:
                return self.cached_status
            return {"total": 0, "done": 0, "todo": 0, "ready": 0, "counts": {}}
        # counts：各状态原始计数（GROUP BY 顺带产出），供批量删除确认框显示条数
        self.cached_status = {"total": total, "done": done, "todo": todo, "ready": ready, "counts": counts}
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
        all_status_sum = sum(status.values())
        status["total"] = all_status_sum - status.get(ScanFile.IMPORTED, 0) - status.get(ScanFile.EXIST, 0)
        status["processed"] = all_status_sum - status.get(ScanFile.READY, 0)
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

            done_status = [ScanFile.IMPORTED]
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
        if ScanService.is_bulk_deleting():
            return {"err": "empty", "msg": _("已有批量删除任务正在运行，请稍后再试")}

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


def normalize_import_filelist(filelist):
    """归一化 ImportRun.filelist 参数，返回 (kind, value)，无法识别返回 None。

    兼容两种历史形态（"all"、手动勾选的路径数组），并新增服务端选择器——前端只传
    选择条件，由后端解析成路径/目录，避免大数据量时在前端与请求体里搬运百万级路径：
      ("all", None)            全量扫描 scan_upload_path
      ("paths", [path, ...])   手动勾选的路径数组（旧形态，force 语义不变）
      ("ready", None)          服务端选择器：全部 READY 记录
      ("dirs", [name, ...])    服务端选择器：扫描目录下的一级子目录名
      ("filter", "todo")       服务端选择器：当前待导入（非 IMPORTED）记录
      ("filter", "<status>")   服务端选择器：按状态批量（new/ready/drop/exist/invalid/missed/permission）
    """
    if filelist is None or filelist == "":
        return None
    if filelist == "all":
        return ("all", None)
    if filelist == "ready":
        return ("ready", None)
    if isinstance(filelist, dict):
        if "dirs" in filelist and "filter" not in filelist:
            dirs = filelist["dirs"]
            if isinstance(dirs, str):
                dirs = [dirs]
            if isinstance(dirs, list):
                return ("dirs", dirs)
            return None
        if "filter" in filelist and "dirs" not in filelist:
            f = filelist["filter"]
            # IMPORTED 无需再导入；白名单也挡掉任意字符串直达 SQL 等值过滤
            if f == "todo" or f in SELECTOR_STATUSES:
                return ("filter", f)
        return None
    if isinstance(filelist, list):
        return ("paths", list(filelist))
    return None


class ImportRun(BaseHandler):
    @js
    @is_admin
    def post(self):
        try:
            req = tornado.escape.json_decode(self.request.body)
            filelist = req.get("filelist", "all")
            skip_last_dirs = req.get("skip_last_dirs", 0)
            force = req.get("force", False)
            if not filelist:
                return {"err": "params.error", "msg": _("参数错误")}
            if ScanService.is_importing():
                return {"err": "empty", "msg": _("已有导入任务正在运行，请稍后再试")}
            if ScanService.is_bulk_deleting():
                return {"err": "empty", "msg": _("已有批量删除任务正在运行，请稍后再试")}
            normalized = normalize_import_filelist(filelist)
            if normalized is None:
                return {"err": "params.error", "msg": _("参数错误")}
            kind, value = normalized

            # 服务端选择器固定 force=False、skip_last_dirs=0：哈希复用是大数据量续导
            # 不重算哈希的前提，且选择目标已由用户明确指定，无需再按"已导入目录"缩小范围。
            # 注意 kinds 必须在此枚举完（normalize 只产这五种），"all" 必须走默认路径。
            selector = None
            paths = "all"
            if kind == "paths":
                paths = filelist
            elif kind == "dirs":
                # 纯文件系统操作（realpath/isdir），在 handler 里同步做以便即时报错
                paths = ScanService.resolve_dir_paths(CONF.get("scan_upload_path", ""), value)
                skip_last_dirs, force = 0, False
                if not paths:
                    return {"err": "params.error", "msg": _("未找到有效的分类目录")}
            elif kind in ("ready", "filter"):
                # ready/filter：只做轻量 COUNT 预检（不取实体——百万行表上全量 .all()
                # 会冻住 ioloop），实际解析放在 do_import 的后台服务线程里
                selector = (kind, value)
                skip_last_dirs, force = 0, False
                if kind == "ready":
                    query = ScanService.status_filter(
                        self.sqlite_session.query(ScanFile.id), ScanFile.READY
                    )
                else:
                    query = ScanService.status_filter(
                        self.sqlite_session.query(ScanFile.id), value
                    )
                if not query.count():
                    return {"err": "empty", "msg": _("没有可导入的文件")}

            ScanService().do_import(paths, self.user_id(), skip_last_dirs, force, selector=selector)
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
        if AudioBookImporter.is_running():
            return {"err": "running", "msg": _("有声书导入任务正在运行中，请稍候")}
        if ScanService.is_bulk_deleting():
            return {"err": "empty", "msg": _("已有批量删除任务正在运行，请稍后再试")}

        AudioBookImporter().do_import(self.user_id())
        return {"err": "ok", "msg": _("有声书导入任务已启动")}


class AudioImportStatus(BaseHandler):
    @js
    @is_admin
    def get(self):
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


class ImportCancel(BaseHandler):
    @js
    @is_admin
    def post(self):
        try:
            if not ScanService.is_importing():
                return {"err": "not_importing", "msg": _("当前没有正在运行的任务")}
            ScanService.cancel()
            return {"err": "ok", "msg": _("正在取消任务, 请稍后查看状态")}
        except Exception as e:
            logging.error(f"ImportCancel error: {e}")
            return {"err": "server.error", "msg": str(e)}


class ImportDirs(BaseHandler):
    @js
    @is_admin
    def get(self):
        """列出扫描导入目录下的一级子目录，供"按分类导入"选择。

        只返回目录名不统计文件数——在百万级文件树上递归计数本身就是一次全量遍历，
        正是本功能要避免的开销。注意本接口按"分类子目录"布局设计：扫描目录若被
        塞成扁平百万文件布局，scandir 一级枚举本身也会在 ioloop 上阻塞数秒。
        """
        scan_upload_path = CONF.get("scan_upload_path", "")
        names = []
        if scan_upload_path and os.path.isdir(scan_upload_path):
            try:
                with os.scandir(scan_upload_path) as it:
                    for entry in it:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        name = entry.name
                        if name.startswith((".", "~")) or name.lower() == constants.AUDIO_BOOK_IMPORTS:
                            continue
                        names.append(name)
            except OSError as e:
                logging.error("[IMPORT] Failed to list scan dirs: %s", e)
        names.sort()
        return {"err": "ok", "dirs": names, "scan_dir": scan_upload_path}


class ImportBulkDelete(BaseHandler):
    @js
    @is_admin
    def post(self):
        """批量删除指定状态的全部记录（可选连同扫描导入目录内的源文件一起真删）。

        实际删除在 ScanService.do_bulk_delete 的独立服务线程里执行，这里只做参数校验、
        互斥检查与 COUNT 预检（空集直接拒绝，避免空跑一趟后台任务）。
        """
        try:
            req = tornado.escape.json_decode(self.request.body)
            status = req.get("status")
        except Exception:
            return {"err": "params.error", "msg": _("参数错误")}
        raw = req.get("delete_files", True)
        if isinstance(raw, bool):
            delete_files = raw
        elif isinstance(raw, str):
            # 容忍表单/查询串风格的布尔；未知字符串一律拒绝，"false" 决不能被当成真删
            raw = raw.strip().lower()
            if raw in ("true", "1", "yes"):
                delete_files = True
            elif raw in ("false", "0", "no", ""):
                delete_files = False
            else:
                return {"err": "params.error", "msg": _("参数错误")}
        else:
            return {"err": "params.error", "msg": _("参数错误")}
        if status != "todo" and status not in SELECTOR_STATUSES:
            return {"err": "params.error", "msg": _("参数错误")}
        if ScanService.is_importing():
            return {"err": "empty", "msg": _("已有导入任务正在运行，请稍后再试")}
        if ScanService.is_bulk_deleting():
            return {"err": "empty", "msg": _("已有批量删除任务正在运行，请稍后再试")}
        if AudioBookImporter.is_running():
            return {"err": "empty", "msg": _("有声书导入任务正在运行，请稍后再试")}
        query = self.sqlite_session.query(ScanFile.id)
        if status == "todo":
            query = query.filter(ScanFile.status.not_in([ScanFile.IMPORTED]))
        else:
            query = query.filter(ScanFile.status == status)
        total = query.count()
        if not total:
            return {"err": "empty", "msg": _("没有可删除的记录")}
        ScanService().do_bulk_delete(self.user_id(), status, delete_files)
        return {"err": "ok", "msg": _("批量删除任务已启动"), "total": total}


class ImportBulkDeleteStatus(BaseHandler):
    @js
    @is_admin
    def get(self):
        return {
            "err": "ok",
            "state": ScanService.bulk_delete_state(),
            "bulk_deleting": ScanService.is_bulk_deleting(),
            "importing": ScanService.is_importing(),
        }


def routes():
    return [
        (r"/api/admin/import/list", ImportList),
        (r"/api/admin/import/delete", ImportDelete),
        (r"/api/admin/import/run", ImportRun),
        (r"/api/admin/import/status", ImportStatus),
        (r"/api/admin/import/dirs", ImportDirs),
        (r"/api/admin/import/bulk_delete", ImportBulkDelete),
        (r"/api/admin/import/bulk_delete/status", ImportBulkDeleteStatus),
        (r"/api/admin/batch_add/run", BatchAddRun),
        (r"/api/admin/batch_add/status", BatchAddStatus),
        (r"/api/admin/audio_import/run", AudioImportRun),
        (r"/api/admin/audio_import/status", AudioImportStatus),
        (r"/api/admin/import/cancel", ImportCancel),
    ]
