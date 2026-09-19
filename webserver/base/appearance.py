#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
外观设置（appearance）的白名单校验与归一化

前端「外观设置」面板（app/src/components/AppearanceMenu.vue）把深/浅色、主色、
顶栏品牌色、侧栏图标配色等偏好交给 ``POST /api/user/appearance`` 保存，落在
``Reader.extra["appearance"]``（见 webserver/models.py 的 Reader.extra），
再由 ``GET /api/user/info`` 以 ``user.appearance`` 下发给前端。

之所以不建表、不加列：``Reader.extra`` 已经是 per-user 的 JSON 字段，且已有
kindle_email / show_other_annotations / share_annotations 等同类偏好住在里面。

本模块只有纯函数：不碰 DB、不碰 web，方便单测。
@author: PoxenStudio, 2026-09
"""
import json
import logging
import re

APPEARANCE_KEY = "appearance"
APPEARANCE_VERSION = 1

# 归一化后 JSON 序列化的兜底上限（字节）。各字段本身都有界（十六进制色 / 布尔 / 枚举），
# 正常体量约 150 字节，这里只是防止未来有人往这个键里塞别的东西。
MAX_APPEARANCE_BYTES = 2048

HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")

# 以下三张白名单必须与前端保持一致：
#   半径 / 背景图案 → app/src/components/AppearanceMenu.vue + app/src/assets/css/appearance.css
#   侧栏图标配色   → app/src/components/AppHeader.vue 的 iconColor()
ALLOWED_RADII = frozenset({"0px", "4px", "8px", "16px"})
ALLOWED_BACKGROUNDS = frozenset({
    "default",
    "cross",
    "left-diagonal",
    "right-diagonal",
    "aurora",
    "horizon",
    "glow",
    "mesh",
    "repeat-image-1",
    "repeat-image-2",
    "repeat-image-3",
    "repeat-image-4",
})
ALLOWED_SIDEBAR_ICON_MODES = frozenset({"multi", "theme", "custom"})

# 前端内置默认值（仅作参考与文档用途）。
# 服务端**不**把默认值写进返回体：用户没保存过外观时 ``user.appearance`` 是 ``{}``，
# 由前端沿用「本地缓存 → 站点默认 sys.theme → 这套默认值」的既有回退顺序，
# 这样才不会把 site_theme（管理员全站默认）的既有行为顶掉。
DEFAULT_APPEARANCE = {
    "darkMode": True,
    "brandColor": None,
    "accent": "#1976D2",
    "radius": "4px",
    "background": "default",
    "sidebarIconMode": "multi",
    "sidebarIconColor": None,
}


class _Invalid(object):
    """哨兵对象：字段值不合法。

    用「丢弃该键」而不是「写入 None」来表示不合法，避免把用户已有的合法值
    用一个空值顶掉（补丁语义）。
    """

    def __repr__(self):
        return "<invalid>"


INVALID = _Invalid()


def _clean_bool(value):
    if isinstance(value, bool):
        return value
    # 兼容字符串形态（前端 localStorage 里历史值可能是 "true"/"false"）
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1"):
            return True
        if low in ("false", "0"):
            return False
    return INVALID


def _clean_color(value):
    if value is None or value == "":
        # 显式清空 → 回到内置默认品牌色（前端把 null 解释为「用默认」）
        return None
    if isinstance(value, str) and HEX_COLOR_PATTERN.match(value):
        return value.lower()
    return INVALID


def _enum_validator(allowed):
    def clean(value):
        if isinstance(value, str) and value in allowed:
            return value
        return INVALID

    return clean


_VALIDATORS = {
    "darkMode": _clean_bool,
    "brandColor": _clean_color,
    "accent": _clean_color,
    "radius": _enum_validator(ALLOWED_RADII),
    "background": _enum_validator(ALLOWED_BACKGROUNDS),
    "sidebarIconMode": _enum_validator(ALLOWED_SIDEBAR_ICON_MODES),
    "sidebarIconColor": _clean_color,
}


def normalize_appearance(raw, base=None):
    """按白名单校验并浅合并外观设置。

    :param raw:  客户端上传的补丁；读取历史值时传已落库的 dict。
    :param base: 合并基线（已保存的设置）。None/{} 表示「只保留 raw 里合法的键」。
    :return: ``(clean, dropped)`` —— ``clean`` 是可直接落库的 dict，
             ``dropped`` 是被丢弃的键名列表（未知键或非法值）。

    约定：
    * 未知键、非法值一律**丢弃该键**，不会用空值覆盖基线里已有的值。
    * 版本号 ``v`` 由服务端统一盖章，不接受客户端指定。
    * 结果为空 dict 表示「用户没有保存过任何外观设置」。
    """
    clean = dict(base or {})
    if raw is None:
        return clean, []
    if not isinstance(raw, dict):
        return clean, ["<payload>"]

    dropped = []
    for key, value in raw.items():
        if key == "v":
            continue
        validator = _VALIDATORS.get(key)
        if validator is None:
            dropped.append(key)
            continue
        cleaned = validator(value)
        if cleaned is INVALID:
            dropped.append(key)
            continue
        clean[key] = cleaned

    if clean:
        clean["v"] = APPEARANCE_VERSION
    if dropped:
        logging.info("appearance: dropped keys %s", sorted(dropped))
    return clean, dropped


def appearance_size(clean):
    """归一化结果的 JSON 字节数（用于兜底的大小校验）。"""
    return len(json.dumps(clean or {}, ensure_ascii=False).encode("utf-8"))


def is_appearance_too_large(clean):
    return appearance_size(clean) > MAX_APPEARANCE_BYTES


def is_client_too_new(raw):
    """客户端声明的 schema 版本比服务端新时返回 True。

    这种补丁不能应用：老服务端不认识新客户端的键，会把它们当未知键丢掉，
    新客户端下次读到就会以为「这些设置被清空了」。宁可让客户端提示刷新。
    """
    if not isinstance(raw, dict):
        return False
    version = raw.get("v")
    return isinstance(version, int) and not isinstance(version, bool) and version > APPEARANCE_VERSION


def read_appearance(user):
    """从 Reader 实例读出可直接下发的外观设置；没保存过则返回 {}。"""
    if user is None:
        return {}
    stored = (getattr(user, "extra", None) or {}).get(APPEARANCE_KEY) or {}
    return normalize_appearance(stored)[0]
