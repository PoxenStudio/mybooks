#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

from calibre.customize import MetadataWriterPlugin


class CbzMetadataWriter(MetadataWriterPlugin):
    name = "CBZ Metadata Writer (MyBooks)"
    description = "Write metadata into ComicInfo.xml of CBZ files (cover is not written)"
    author = "PoxenStudio"
    version = (1, 0, 0)
    file_types = {"cbz"}
    supported_platforms = ["windows", "osx", "linux"]
    minimum_calibre_version = (7, 0, 0)

    def set_metadata(self, stream, mi, ftype):
        from calibre_plugins.cbz_meta_writer.core import write_metadata

        write_metadata(stream, mi, apply_null=getattr(self, "apply_null", False))
