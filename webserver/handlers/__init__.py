#!/usr/bin/python
# -*- coding: UTF-8 -*-


def routes():
    from . import book
    from . import user
    from . import meta
    from . import files
    from . import opds
    from . import admin
    from . import scan
    from . import audio
    from . import mcp
    from . import barcode

    routes = []
    routes += mcp.routes()
    routes += admin.routes()
    routes += barcode.routes()
    routes += scan.routes()
    routes += opds.routes()
    routes += book.routes()
    routes += user.routes()
    routes += meta.routes()
    routes += audio.routes()
    routes += files.routes()
    return routes
