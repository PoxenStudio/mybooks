import sys
from gettext import gettext as _
from tornado import web
from tornado.options import define, options


define("path-calibre", default="/usr/lib/calibre", type=str, help=_("Path to calibre package."))
define("path-resources", default="/usr/share/calibre", type=str, help=_("Path to calibre resources."))
define("path-plugins", default="/usr/lib/calibre/calibre/plugins", type=str, help=_("Path to calibre plugins."))
define("path-bin", default="/usr/bin", type=str, help=_("Path to calibre binary programs."))
define("file-path", default="", type=str, help=_("Path to the epub/mobi/pdf/txt file to extract metadata."))


def init_calibre():
    path = options.path_calibre
    if path not in sys.path:
        sys.path.insert(0, path)
    sys.resources_location = options.path_resources
    sys.extensions_location = options.path_plugins
    sys.executables_location = options.path_bin
    try:
        import calibre  # noqa: F401
    except Exception as e:
        import logging
        import traceback

        logging.error(traceback.format_exc())
        raise ImportError(_("Can not import calibre. Please set the corrent options.\n%s" % e))


def super_strip(s):
    # 删除掉所有不可见的字符
    # issue: https://github.com/talebook/talebook/issues/304
    return ''.join(c for c in s.strip() if c.isprintable())


if __name__ == "__main__":
    init_calibre()

    if len(sys.argv) != 2:
        print("用法: epub_meta.py <文件路径>")
        sys.exit(2)

    from calibre.ebooks.metadata.meta import get_metadata
    file_pdath = sys.argv[1]
    if not file_pdath:
        sys.exit(2)
    else:
        print("提取文件: " + file_pdath)
    with open(file_pdath, "rb") as stream:
        if file_pdath.lower().endswith(".epub"):
            fmt = "epub"
        elif file_pdath.lower().endswith(".mobi") or file_pdath.lower().endswith(".azw3"):
            fmt = "mobi"
        elif file_pdath.lower().endswith(".pdf"):
            fmt = "pdf"
        elif file_pdath.lower().endswith(".txt"):
            fmt = "txt"
        else:
            print(f"不支持的文件格式: {file_pdath}")
            sys.exit(1)
        mi = get_metadata(stream, stream_type=fmt, use_libprs_metadata=True)

        if mi.authors and len(mi.authors) > 0:
            author = super_strip(mi.authors[0])
        else:
            author = ""
        print(f"提取的元数据 ({file_pdath}), author is {author}")
        print(f"提取的元数据 ({file_pdath}), author is {super_strip(mi.author_sort)}")
        if mi.author_sort == "Unknown":
            print(f"提取的元数据 ({file_pdath}), author is not valid")
        # print(mi)

        # mi.print_all_attributes()

