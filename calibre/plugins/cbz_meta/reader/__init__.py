#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

from calibre.customize import MetadataReaderPlugin


class CbzMetadataReader(MetadataReaderPlugin):
    name = "CBZ Metadata Reader (MyBooks)"
    description = "Read ComicInfo.xml (or ComicBookInfo) metadata and cover from CBZ files"
    author = "PoxenStudio"
    version = (1, 0, 0)
    file_types = {"cbz"}
    supported_platforms = ["windows", "osx", "linux"]
    minimum_calibre_version = (7, 0, 0)

    def get_metadata(self, stream, ftype):
        from calibre_plugins.cbz_meta_reader.core import read_metadata

        return read_metadata(stream, quick=getattr(self, "quick", False))
