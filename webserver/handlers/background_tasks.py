#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging
from gettext import gettext as _

from webserver.handlers.base import BaseHandler, js, is_admin
from webserver.services.background_service import background_service


class BackgroundTasksHandler(BaseHandler):
    """后台任务列表接口"""

    @js
    @is_admin
    def get(self):
        """获取后台任务列表"""
        try:
            # 只有管理员可以查看后台任务
            if not self.is_admin():
                return {"err": "permission.denied", "msg": _("需要管理员权限")}

            # 获取分页参数
            limit = int(self.get_argument("limit", 50))

            # 获取任务列表
            tasks = background_service.get_running_tasks(limit=limit)

            return {
                "err": "ok",
                "tasks": tasks,
                "total": len(tasks)
            }
        except Exception as e:
            logging.error(f"Error in BackgroundTasksHandler.get: {e}")
            return {"err": "server.error", "msg": str(e)}


class BackgroundTaskDetailHandler(BaseHandler):
    """后台任务详情接口"""

    @js
    @is_admin
    def get(self, task_id):
        """获取后台任务详情"""
        try:
            # 只有管理员可以查看后台任务
            if not self.is_admin():
                return {"err": "permission.denied", "msg": _("需要管理员权限")}

            task_id = int(task_id)

            # 获取任务详情
            task = background_service.get_task(task_id)

            if not task:
                return {"err": "task.not_found", "msg": _("任务未找到")}

            return {
                "err": "ok",
                "task": task
            }
        except ValueError:
            return {"err": "params.invalid", "msg": _("无效的任务ID")}
        except Exception as e:
            logging.error(f"Error in BackgroundTaskDetailHandler.get: {e}")
            return {"err": "server.error", "msg": str(e)}


class BackgroundTaskCancelHandler(BaseHandler):
    """后台任务取消接口"""

    @js
    @is_admin
    def post(self, task_id):
        """取消后台任务"""
        try:
            # 只有管理员可以取消后台任务
            if not self.is_admin():
                return {"err": "permission.denied", "msg": _("需要管理员权限")}

            task_id = int(task_id)

            # 取消任务
            success = background_service.cancel_task(task_id)

            if not success:
                return {"err": "task.not_found", "msg": _("任务未找到")}

            return {
                "err": "ok",
                "msg": _("任务已取消")
            }
        except ValueError:
            return {"err": "params.invalid", "msg": _("无效的任务ID")}
        except Exception as e:
            logging.error(f"Error in BackgroundTaskCancelHandler.post: {e}")
            return {"err": "server.error", "msg": str(e)}


def routes():
    """返回路由配置"""
    return [
        (r"/api/background-tasks", BackgroundTasksHandler),
        (r"/api/background-tasks/([0-9]+)", BackgroundTaskDetailHandler),
        (r"/api/background-tasks/([0-9]+)/cancel", BackgroundTaskCancelHandler),
    ]
