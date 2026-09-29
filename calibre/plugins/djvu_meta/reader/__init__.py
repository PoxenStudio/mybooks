#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

from calibre.customize import MetadataReaderPlugin


class DjVuMetadataReader(MetadataReaderPlugin):
    name = "DjVu Metadata Reader (MyBooks)"
    description = "Read DjVu metadata and render the first page as cover via djvu-rs"
    author = "PoxenStudio"
    version = (1, 0, 0)
    file_types = {"djvu"}
    supported_platforms = ["windows", "osx", "linux"]
    minimum_calibre_version = (7, 0, 0)

    def get_metadata(self, stream, ftype):
        from calibre_plugins.djvu_meta_reader.core import read_metadata

        return read_metadata(stream, quick=getattr(self, "quick", False))
