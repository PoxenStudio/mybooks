import os
import urllib.parse

from webserver import loader

CONF = loader.get_settings()

LIBRARY_PREFIX = "/_lib/"
CACHE_PREFIX = "/_cache/"


def enabled(handler):
    return bool(CONF.get("USE_X_ACCEL", True)) and handler.request.headers.get("X-Accel-Support") == "1"


def uri_for(prefix, root, path):
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
    if rel.startswith(".."):
        return None
    return prefix + urllib.parse.quote(rel.replace(os.sep, "/"))
