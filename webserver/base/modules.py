#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""功能模块开关（模块级）。

一个模块 = 一个勾选框 = 一条 ``ENABLE_MODULE_<ID>`` 配置。模块关闭时：

1. 把模块内的**主开关**写成安全默认值（``MODULE_OFF_SWITCHES``）；
2. 入口隐藏、接口拒绝；
3. 设置区块/字段不渲染。

模块从关到开时只恢复主功能开关（``MODULE_ON_SWITCHES``），不恢复访问控制类
（必须登录、访客权限、注册、分享链接），避免重开模块把私人站点重新暴露。

设计取舍：

- **未登记的模块一律视为开启**。新模块忘了登记时宁可多显示，也不要让整块功能
  凭空消失。
- **关闭不删数据**。模块关掉后重新勾选，音频文件、书单、留言都还在。
- **只写主开关**。子选项、密钥、列表数据、用户配置一律不改。
- 本模块只有纯函数与一个读设置的便捷入口：不碰 DB、不写配置，方便单测。
"""

import logging

import tornado.web as web

from webserver.i18n import _

MODULE_MULTIUSER = "multiuser"
MODULE_COMMUNITY = "community"
MODULE_SHARED_READING = "shared_reading"
MODULE_AUDIO = "audio"
MODULE_PHYSICAL = "physical"
MODULE_AI = "ai"

# 模块表：id -> {key, default, name}
# 新增模块时在这里登记，并把同名 key 加进 setting_saver.ADMIN_SETTING_KEYS
# （PERSISTABLE_KEYS 是它的超集，进前者即进后者）。漏加的话设置页保存时
# dumpfile() 整份覆盖会把开关静默抹回默认值。
MODULES = {
    MODULE_MULTIUSER: {
        "key": "ENABLE_MODULE_MULTIUSER",
        "default": True,
        "name": "多用户支持",
    },
    MODULE_COMMUNITY: {
        "key": "ENABLE_MODULE_COMMUNITY",
        "default": True,
        "name": "社区互动",
    },
    MODULE_SHARED_READING: {
        "key": "ENABLE_MODULE_SHARED_READING",
        "default": True,
        "name": "共享阅读",
    },
    MODULE_AUDIO: {
        "key": "ENABLE_MODULE_AUDIO",
        "default": True,
        "name": "有声书",
    },
    MODULE_PHYSICAL: {
        "key": "ENABLE_MODULE_PHYSICAL",
        "default": True,
        "name": "实体书",
    },
    MODULE_AI: {
        "key": "ENABLE_MODULE_AI",
        "default": True,
        "name": "AI",
    },
}

# 六个模块互不依赖，可单独启停。
MODULE_DEPENDENCIES = {}

# 模块关闭时写入的主开关。只放主开关：子选项、密钥、列表数据不在此表。
MODULE_OFF_SWITCHES = {
    MODULE_MULTIUSER: {
        # OPDS_ALLOW_ANONYMOUS 是设备协议级的独立开关，不随多用户关闭重置：
        # 个人模式常需要它给无法输入账号的阅读器留入口。
        "REQUIRE_LOGIN": True,
        "ALLOW_GUEST_READ": False,
        "ALLOW_GUEST_DOWNLOAD": False,
        "ALLOW_GUEST_UPLOAD": False,
        "ALLOW_GUEST_PUSH": False,
        "ALLOW_REGISTER": False,
        "INVITE_MODE": False,
    },
    MODULE_COMMUNITY: {
        "ENABLE_USER_MEMOS": False,
        "ENABLE_SHARE_LINK": False,
        "ENABLE_SHARED_NOTES": False,
    },
    MODULE_SHARED_READING: {
        "RECOMMEND_ENABLE": False,
        "ENABLE_BOOK_REVIEW": False,
    },
    # 有声书没有单一主开关：模块闸门负责入口与接口，播客/字幕等子开关保持原值。
    MODULE_AUDIO: {},
    MODULE_PHYSICAL: {
        "ENABLE_PHYSICAL_BOOKS": False,
    },
    MODULE_AI: {
        "AI_ENABLED": False,
        "ENABLE_MYNEXUS": False,
    },
}

# 模块从关到开时恢复的主功能开关。访问控制类（访客权限/注册/分享链接）有意不在此表：
# 重开模块不能把私人站点重新变成访客可读。唯一例外是 REQUIRE_LOGIN——开启多用户时把它
# 钉回 True（更安全的一侧），管理员想开访客阅读再手动取消勾选。
MODULE_ON_SWITCHES = {
    MODULE_MULTIUSER: {
        "REQUIRE_LOGIN": True,
    },
    MODULE_COMMUNITY: {
        "ENABLE_USER_MEMOS": True,
        "ENABLE_SHARED_NOTES": True,
    },
    MODULE_SHARED_READING: {
        "RECOMMEND_ENABLE": True,
        "ENABLE_BOOK_REVIEW": True,
    },
    MODULE_AUDIO: {},
    MODULE_PHYSICAL: {
        "ENABLE_PHYSICAL_BOOKS": True,
    },
    MODULE_AI: {
        "AI_ENABLED": True,
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


def _raw_enabled(module_id, conf):
    spec = MODULES.get(module_id)
    if spec is None:
        return DEFAULT_ENABLED
    return bool(conf.get(spec["key"], spec["default"]))


def _module_enabled(module_id, conf, seen):
    if module_id in seen:
        # 依赖表很小且是静态的；真出现环时按开启处理，避免死循环。
        return True
    seen.add(module_id)
    if not _raw_enabled(module_id, conf):
        return False
    for dependency in MODULE_DEPENDENCIES.get(module_id, ()):
        if not _module_enabled(dependency, conf, seen):
            return False
    return True


def module_enabled(module_id, settings=None):
    """模块是否有效开启：自身开关为真且所有依赖模块为真。"""
    return _module_enabled(module_id, _conf(settings), set())


def require_login_effective(settings=None):
    """站点级「必须登录」的有效值。

    多用户支持关闭后强制要求登录，作为运行期兜底；正常保存路径会同时把
    REQUIRE_LOGIN 写成 True，这里主要防手工改 auto.py 的绕过。
    """
    conf = _conf(settings)
    return bool(conf.get("REQUIRE_LOGIN", True)) or not module_enabled(
        MODULE_MULTIUSER, conf
    )


def opds_anonymous_allowed(settings=None):
    """OPDS 是否可以匿名访问。

    匿名开关优先于「必须登录」与 ``ENABLE_OPDS_AUTH``：阅读设备多数只能填订阅地址，
    给它一条显式的免登录通道是本开关存在的唯一理由，所以由它自己决定，不再被认证项压住。
    """
    conf = _conf(settings)
    return bool(conf.get("OPDS_ALLOW_ANONYMOUS", False))


def snapshot(settings=None):
    """下发给前端的模块**有效**状态，随 ``sys.modules`` 一起走。"""
    conf = _conf(settings)
    return {module_id: module_enabled(module_id, conf) for module_id in MODULES}


def stored_snapshot(settings=None):
    """模块自身开关的存储值（不做依赖折算），供设置页弹窗展示。"""
    conf = _conf(settings)
    return {module_id: _raw_enabled(module_id, conf) for module_id in MODULES}


def apply_module_switch_effects(args, old_settings=None):
    """按模块有效状态的旧/新变化，把主开关写进 ``args``。

    ``args`` 会被 dumpfile() 整份写回 auto.py，所以缺键等于抹掉。这里只写
    ``MODULE_OFF_SWITCHES`` / ``MODULE_ON_SWITCHES`` 里的主开关，不碰数据、密钥、
    子选项。

    - 安装场景 ``old_settings=None``：只对有效关闭的模块应用 off 效果；
    - 设置保存：旧开→新关写 off；旧关→新关重复写 off（幂等）；旧关→新开写 on；
      旧开→新开不动子开关。
    """
    if old_settings is None:
        for module_id in MODULES:
            if not module_enabled(module_id, args):
                args.update(MODULE_OFF_SWITCHES.get(module_id, {}))
        return args

    for module_id in MODULES:
        old_on = module_enabled(module_id, old_settings)
        new_on = module_enabled(module_id, args)
        if not new_on:
            args.update(MODULE_OFF_SWITCHES.get(module_id, {}))
        elif not old_on:
            args.update(MODULE_ON_SWITCHES.get(module_id, {}))
    return args


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

        class BookList(ModuleGateMixin, BaseHandler):
            module_id = MODULE_SHARED_READING

    - JSON 接口默认返回 ``{"err": "module.disabled"}``（200，沿用项目里 @js 的约定）；
    - 文件流/订阅源/分享页等非 JSON 响应把 ``module_gate_json`` 置 False，改成 404，
      避免把 HTML 错误页喂给播客客户端、音频播放器或分享访客。
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
