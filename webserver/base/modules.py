#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""功能模块开关（模块级）。

一个模块 = 一个勾选框 = 一条 ``ENABLE_MODULE_<ID>`` 配置。模块内部的细分设置项
保持原样，只随模块开关显隐；模块关闭时三件事一起做：

1. **能力不开放**：接口/服务拒绝（``ModuleGateMixin`` 或服务层 ``module_enabled``）；
2. **入口隐藏**：导航、菜单、页面、首页板块不再出现；
3. **设置不显示**：该模块的设置区块/字段不渲染，也不进设置搜索索引。

设计取舍：

- **未登记的模块一律视为开启**。新模块忘了登记时宁可多显示，也不要让整块功能
  凭空消失（与「默认高级」那种以隐藏为安全侧的设计相反，这里没有模式概念）。
- **关闭只隐藏，不删数据**。模块关掉后重新勾选，音频文件、书单、留言都还在。
- 本模块只有纯函数与一个读设置的便捷入口：不碰 DB、不写配置，方便单测。
"""

import logging

import tornado.web as web

from webserver.i18n import _

MODULE_AUDIO = "audio"

# 模块表：id -> {key, default, name}
# 新增模块时在这里登记，并把同名 key 加进 setting_saver.ADMIN_SETTING_KEYS
# （PERSISTABLE_KEYS 是它的超集，进前者即进后者）。漏加的话设置页保存时
# dumpfile() 整份覆盖会把开关静默抹回默认值。
MODULES = {
    MODULE_AUDIO: {
        "key": "ENABLE_MODULE_AUDIO",
        "default": True,
        "name": "有声书",
    },
}

# 未登记的模块按开启处理，避免新功能因漏登记而整体消失。
DEFAULT_ENABLED = True


def _conf(settings=None):
    if settings is not None:
        return settings
    # 延迟导入：handlers/base.py 在模块导入期就 get_settings()，这里再 import 会成环。
    from webserver import loader

    return loader.get_settings()


def setting_key(module_id):
    """返回模块对应的配置键；未登记返回 None。"""
    spec = MODULES.get(module_id)
    return spec["key"] if spec else None


def is_known(module_id):
    return module_id in MODULES


def module_enabled(module_id, settings=None):
    """模块是否开启。未登记的模块恒为 True（见模块文档字符串）。"""
    spec = MODULES.get(module_id)
    if spec is None:
        return DEFAULT_ENABLED
    conf = _conf(settings)
    return bool(conf.get(spec["key"], spec["default"]))


def snapshot(settings=None):
    """下发给前端的模块快照，随 ``sys.modules`` 一起走。"""
    conf = _conf(settings)
    return {
        module_id: bool(conf.get(spec["key"], spec["default"]))
        for module_id, spec in MODULES.items()
    }


def module_disabled_error(module_id):
    """JSON 接口的统一拒绝体（沿用 koreader_service.disabled_error 的形状）。"""
    spec = MODULES.get(module_id) or {}
    name = spec.get("name", module_id)
    return {"err": "module.disabled", "msg": _("「%s」功能已关闭") % name}


def log_disabled_hit(module_id, handler):
    """模块关闭时记一条 debug 日志，方便排查「为什么这个接口 404 了」。"""
    logging.debug(
        "module '%s' disabled, request rejected: %s %s",
        module_id,
        getattr(handler, "request", None) and handler.request.method,
        getattr(handler, "request", None) and handler.request.uri,
    )


class ModuleGateMixin:
    """放在 BaseHandler 前面，在原有登录/邀请闸之后再过一道模块闸。

    用法::

        class AudioDetail(ModuleGateMixin, BaseHandler):
            module_id = MODULE_AUDIO

    - JSON 接口默认返回 ``{"err": "module.disabled"}``（200，沿用项目里 @js 的约定）；
    - 文件流/订阅源等非 JSON 响应把 ``module_gate_json`` 置 False，改成 404，
      避免把 HTML 错误页喂给播客客户端或音频播放器。
    """

    module_id = None
    module_gate_json = True

    def prepare(self):
        super().prepare()
        module_id = self.module_id
        if not module_id:
            # 挂了 Mixin 却漏写 module_id 等于没挂，而且不会有任何症状。
            # 这里直接炸开，让「忘写」在第一次请求时就暴露，而不是静默放行。
            raise RuntimeError(
                "%s 使用了 ModuleGateMixin 但未设置 module_id"
                % type(self).__name__
            )
        if module_enabled(module_id):
            return
        log_disabled_hit(module_id, self)
        if self.module_gate_json:
            self.finish(module_disabled_error(module_id))
        else:
            raise web.HTTPError(404, reason="Not Found")
