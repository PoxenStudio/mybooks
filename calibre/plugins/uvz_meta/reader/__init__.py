#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

from calibre.customize import MetadataReaderPlugin


class UvzMetadataReader(MetadataReaderPlugin):
    name = "UVZ Metadata Reader (MyBooks)"
    description = "Read bookinfo.dat metadata and cover page from SuperStar UVZ files"
    author = "PoxenStudio"
    version = (1, 0, 0)
    file_types = {"uvz"}
    supported_platforms = ["windows", "osx", "linux"]
    minimum_calibre_version = (7, 0, 0)

    def get_metadata(self, stream, ftype):
        from calibre_plugins.uvz_meta_reader.core import read_metadata

        return read_metadata(stream, quick=getattr(self, "quick", False))
