"""前端 locale 静态检查（app/locales/*.json）。

vue-i18n 8 用「.」把 key 当路径解析，因此**不能**把层级写成扁平的
``"op.remove_artifacts": "..."``——``$t('epubFixer.op.remove_artifacts')``
会先按 ``op`` / ``remove_artifacts`` 逐层查找，查不到就原样返回 key 字符串，
界面上直接显示 ``epubFixer.op.remove_artifacts``（EPUB 修复工具就踩过这个坑）。

这里只做两件轻量校验：
1. 任何层级的键名都不得含「.」；
2. EPUB 修复工具的 ``epubFixer`` 段在三份 locale 里键集合一致。
"""
import json
import os

import pytest

LOCALES = ("zh", "en", "zh-TW")
LOCALE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "locales")


def _load(locale):
    with open(os.path.join(LOCALE_DIR, "%s.json" % locale), encoding="utf-8") as fp:
        return json.load(fp)


def _dotted_keys(node, prefix=""):
    """返回所有「键名本身含点」的路径（不限层级）。"""
    found = []
    for key, value in node.items():
        path = "%s.%s" % (prefix, key) if prefix else key
        if "." in key:
            found.append(path)
        if isinstance(value, dict):
            found.extend(_dotted_keys(value, path))
    return found


def _leaf_keys(node, prefix=""):
    leaves = set()
    for key, value in node.items():
        path = "%s.%s" % (prefix, key) if prefix else key
        if isinstance(value, dict):
            leaves |= _leaf_keys(value, path)
        else:
            leaves.add(path)
    return leaves


@pytest.mark.parametrize("locale", LOCALES)
def test_no_flat_dotted_keys(locale):
    bad = _dotted_keys(_load(locale))
    assert not bad, (
        "%s.json 存在扁平的含点键，vue-i18n 按路径解析会取不到：%s" % (locale, bad))


def test_epub_fixer_keys_consistent_across_locales():
    keys = {
        locale: _leaf_keys(_load(locale).get("epubFixer") or {})
        for locale in LOCALES
    }
    union = set().union(*keys.values())
    assert union, "app/locales 缺少 epubFixer 段"
    for locale, got in keys.items():
        missing = sorted(union - got)
        assert not missing, "%s.json 的 epubFixer 段缺少这些键：%s" % (locale, missing)
