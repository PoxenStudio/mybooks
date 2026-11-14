#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import json
import logging
import os
import sys
import traceback

from webserver import constants

DEFAULT_GOOGLE_ANALYTICS_ID = "G-LLF01B5ZZ8"


class SettingsLoader(dict):
    def __init__(self, *args, **kwargs):
        super(SettingsLoader, self).__init__(*args, **kwargs)
        self.loadfile()

    def clear(self):
        for key in list(self.keys()):
            self.pop(key)

    def set_store_path(self):
        p = self.get("settings_path", "").strip()
        if not os.path.isdir(p):
            p = os.path.dirname(__file__)
        if sys.path[0] != p:
            sys.path.insert(0, p)
        return p

    def loadfile(self):
        try:
            import webserver.settings

            self.update(webserver.settings.settings)
        except Exception:
            logging.error(traceback.format_exc())
            pass

        self.set_store_path()

        try:
            import auto
            self.update(auto.settings)
        except Exception:
            pass

        try:
            import manual
            self.update(manual.settings)
        except Exception:
            pass

    def dumpfile(self, filename="auto.py"):
        s = "\n".join("%-30s: %s," % (repr(k), repr(v)) for k, v in sorted(self.items()))
        code = (
            u"""#!/usr/bin/env python3
#-*- coding: UTF-8 -*-

import os
settings = {
"""
            + s
            + """
}
"""
        )

        d = self.set_store_path()
        py = os.path.join(d, filename)
        pyc = os.path.join(d, filename + "c")
        logging.info("saving settings file: %s" % py)
        with open(py, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            os.remove(pyc)
        except Exception:
            pass

    def loads(self, text):
        self.update(json.loads(text))

    def dumps(self):
        return json.dumps(self)


_settings = SettingsLoader()
CONF = _settings
if CONF.get("google_analytics_id", "").strip() == DEFAULT_GOOGLE_ANALYTICS_ID:
    CONF["google_analytics_id"] = ""  # disable it by default
if CONF.get("EPUB_VIEWER", "") not in [constants.EPUB_VIEWER_DEFAULT, constants.EPUB_VIEWER_MYREADADER]:
    CONF["EPUB_VIEWER"] = constants.EPUB_VIEWER_DEFAULT
if CONF.get("PDF_READER", "") not in [constants.PDF_READER_DEFAULT, constants.PDF_READER_MYREADADER]:
    CONF["PDF_READER"] = constants.PDF_READER_DEFAULT


def get_settings():
    CHECKING_KEYS = ("nuxt_env_path", "html_path", "i18n_path", "static_path", "resource_path")
    for key in CHECKING_KEYS:
        key_value = _settings.get(key, "")
        if key_value and key_value.startswith("/var/www/talebook/"):
            _settings[key] = key_value.replace("/var/www/talebook/", "/var/www/mybooks/")
    return _settings
