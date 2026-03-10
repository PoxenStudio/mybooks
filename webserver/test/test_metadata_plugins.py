from io import BytesIO
from threading import Event

import sys
import os

# Setup Calibre paths
path = os.environ.get('CALIBRE_PYTHON_PATH', '/usr/lib/calibre')
if path not in sys.path:
    sys.path.insert(0, path)

sys.resources_location = os.environ.get('CALIBRE_RESOURCES_PATH', '/usr/share/calibre')
sys.extensions_location = os.environ.get('CALIBRE_EXTENSIONS_PATH', '/usr/lib/calibre/calibre/plugins')
sys.executables_location = os.environ.get('CALIBRE_EXECUTABLES_PATH', '/usr/bin')

from calibre.ebooks.metadata.sources.identify import identify
from calibre.ebooks.metadata.sources.covers import download_cover
from calibre.ebooks.metadata.sources.base import create_log
from calibre.ebooks.metadata.sources.update import patch_plugins
from calibre.customize.ui import metadata_plugins, all_metadata_plugins


def configure_amazon_plugin():
    """配置 Amazon 插件，将 server 选项设置为 'amazon'"""
    try:
        from calibre.customize.ui import metadata_plugins
        for plugin in metadata_plugins({'identify'}):
            if plugin.name == 'Amazon.com':
                if hasattr(plugin, 'server'):
                    print(f"plugin server is {plugin.server}")
                if hasattr(plugin, 'domain'):
                    print(f"plugin domain is {plugin.domain}")
                if hasattr(plugin, 'prefs'):
                    if 'server' in plugin.prefs:
                        plugin.prefs['server'] = 'amazon'
                        print("Amazon plugin server set to 'amazon'")
                    else:
                        plugin.prefs['server'] = 'amazon'
                        print("Amazon plugin does not have 'server' option in prefs")
                        print(f" prefs:{plugin.prefs}")
                break
    except Exception as e:
        print("配置 Amazon 插件失败: %s" % e)


def print_available_plugins():
    """打印当前 calibre 环境可用插件列表。"""
    all_plugins = list(all_metadata_plugins())
    all_plugin_names = sorted({p.name for p in all_plugins})

    identify_plugins = list(metadata_plugins({'identify'}))
    identify_plugin_names = sorted({p.name for p in identify_plugins})

    print("=== Calibre 可用插件（全部）===")
    print(f"总数: {len(all_plugin_names)}")
    for name in all_plugin_names:
        print(name)

    print("\n=== Calibre 可用插件（支持 identify）===")
    print(f"总数: {len(identify_plugin_names)}")
    for name in identify_plugin_names:
        print(name)


# 必须先调用 patch_plugins() 以加载最新插件补丁（来自 calibre 服务器）
patch_plugins()
print_available_plugins()

configure_amazon_plugin()

# 创建 log 对象（必须）
buf = BytesIO()
log = create_log(buf)

# 创建 abort 事件（用于中断）
abort = Event()

# ① 按 ISBN 查询
# results = identify(
#     log,
#     abort,
#     identifiers={'isbn': '9781473517714'},
#     allowed_plugins={'Amazon.com'},
#     timeout=30,
# )

# if results:
#     print("=== 查询结果(ISBN) ===")
#     print("结果数量:", len(results))
#     for result in results:
#         print(f"Title: {result.title}, Authors: {result.authors}, Publisher: {result.publisher}, PubDate: {result.pubdate}")
#         print(f"Identifiers: {result.identifiers}, Language: {result.language}")
#         print(f"Rating: {result.rating}, Tags: {result.tags}")
#         print(f"Comments: {result.comments[:100]}...")  # 只显示简介的前100字符
#         print(result.identifiers)
#         print(f"meta:{result}")
#         print("-" * 40)

# # ② 按书名+作者查询
# results = identify(
#     log,
#     abort,
#     title='流畅的 Python',
#     authors=['Luciano Ramalho'],
#     timeout=30,
# )

# ③ 限定只用 Google Books 和 Amazon
results = identify(
    log,
    abort,
    title='To Kill a Mockingbird',
    authors=None,
    allowed_plugins={'Amazon.com'},  # 插件名称需精确匹配
    timeout=30,
)

amazon_plugin = None
for plugin in metadata_plugins({'identify'}):
    if plugin.name == 'Amazon.com':
        amazon_plugin = plugin
        break

# results 是按相关性排序的 Metadata 对象列表（最佳结果在 results[0]）
if results:
    print("=== 查询结果 (Title & Author) ===")
    print("结果数量:", len(results))
    for result in results:
        print(f"Title: {result.title}, Authors: {result.authors}, Publisher: {result.publisher}, PubDate: {result.pubdate}")
        print(f"Identifiers: {result.identifiers}, Language: {result.language}")
        print(f"Rating: {result.rating}, Tags: {result.tags}")
        print(f"Comments: {result.comments[:100]}...")  # 只显示简介的前100字符
        if amazon_plugin and amazon_plugin.cached_cover_url_is_reliable:
            cover_url = amazon_plugin.get_cached_cover_url(result.identifiers)
            print(f"Cover URL: {cover_url}")
        print("-" * 40)

# Output the log
from calibre.prints import prints
prints(buf.getvalue(), file=sys.stderr)
