"""
EPUB 拆分引擎

按 TOC 导航点（含锚点）将 EPUB 拆分为若干"章节"，并支持从所选章节中
重新组装出一本新的 EPUB 文件。算法移植自 Calibre 插件 EpubSplit
（tools/epub/EpubSplit/epubsplit.py，GPL v3，作者 Jim Miller），
去除了字体解密、命令行等本项目不需要的部分，并改写为 Python3 风格。

@author: PoxenStudio, 2026
"""
import logging
import os
import re
import time
import io
from PIL import Image
from posixpath import normpath
from urllib.parse import unquote
from xml.dom.minidom import parseString, getDOMImplementation
from zipfile import ZipFile, ZIP_STORED, ZIP_DEFLATED
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

PARSER = "html.parser"


def get_path_part(href: str) -> str:
    relpath = os.path.dirname(href)
    return relpath + "/" if relpath else ""


def get_file_part(href: str) -> str:
    return os.path.basename(href)


def strip_html(html: str) -> str:
    """去除 HTML 标签，返回纯文本，供章节预览使用。"""
    if not html:
        return ""
    soup = BeautifulSoup(html, PARSER)
    text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def get_title_of_html(html: str) -> str:
    """从html中按序提取head/title及首个h1/h2/h3的信息，以空格拼接返回"""
    if not html:
        return ""
    soup = BeautifulSoup(html, PARSER)
    heading = soup.find(["h1", "h2", "h3"])
    if heading:
        text = heading.get_text(separator=" ").strip()
        if text:
            return text
    title = soup.find("title")
    if title and title.string:
        return title.string
    return ""


def split_html(data: str, tagid: str, before: bool = False) -> str:
    """以 id=tagid 的元素为界，丢弃其前面或后面的内容，返回剩余部分的 HTML。"""
    soup = BeautifulSoup(data, PARSER)
    splitpoint = soup.find(id=tagid)
    if splitpoint is None:
        return data

    if before:
        for n in splitpoint.find_next_siblings():
            n.extract()
        parent = splitpoint.parent
        while parent and parent.name != "body":
            for n in parent.find_next_siblings():
                n.extract()
            parent = parent.parent
        splitpoint.extract()
    else:
        for n in splitpoint.find_previous_siblings():
            n.extract()
        parent = splitpoint.parent
        while parent and parent.name != "body":
            for n in parent.find_previous_siblings():
                n.extract()
            parent = parent.parent

    return re.sub(r"( *\r?\n)+", "\r\n", str(soup))


def new_tag(dom, name, attrs=None, text=None):
    tag = dom.createElement(name)
    if attrs:
        for k, v in attrs.items():
            tag.setAttribute(k, v)
    if text is not None:
        tag.appendChild(dom.createTextNode(text))
    return tag


class FileCache:
    """跟踪拆分过程中文件改名、锚点重定位及关联文件（图片/CSS）。"""

    def __init__(self):
        self.oldnew = {}
        self.newold = {}
        self.anchors = {}
        self.linkedfiles = set()

    def fix_path(self, href: str) -> str:
        return normpath(unquote(href))

    def add_linked_file(self, href: str) -> None:
        self.linkedfiles.add(self.fix_path(href))

    def add_content_file(self, href: str, filedata: str) -> str:
        if href not in self.oldnew:
            self.oldnew[href] = []
            newfile = href
        else:
            newfile = "%s%d-%s" % (get_path_part(href), len(self.oldnew[href]), get_file_part(href))

        self.oldnew[href].append(newfile)
        self.newold[newfile] = href

        soup = BeautifulSoup(filedata, PARSER)
        for tag in soup.find_all():
            if tag.has_attr("id"):
                self.anchors[href + "#" + tag["id"]] = newfile + "#" + tag["id"]

        for img in soup.find_all("img") + soup.find_all("image"):
            src = img.get("src") or img.get("xlink:href")
            if src:
                self.add_linked_file(get_path_part(href) + src)

        return newfile


class SplitEpub:
    """解析一本 EPUB 的章节结构，并支持按选定章节重新生成新的 EPUB。"""

    def __init__(self, fileobj):
        self.epub = ZipFile(fileobj, "r")
        self.content_dom = None
        self.content_relpath = None
        self.manifest_items = None
        self.guide_items = None
        self.toc_dom = None
        self.toc_relpath = None
        self.toc_map = None
        self.split_lines = None
        self.filecache = None
        self.orig_title = None
        self.orig_authors = []

    # -- 解析 OPF / NCX --------------------------------------------------

    def get_content_dom(self):
        if not self.content_dom:
            container = self.epub.read("META-INF/container.xml")
            container_dom = parseString(container)
            rootfile = container_dom.getElementsByTagName("rootfile")[0].getAttribute("full-path")
            self.content_dom = parseString(self.epub.read(rootfile))
            self.content_relpath = get_path_part(rootfile)
        return self.content_dom

    def get_content_relpath(self) -> str:
        if self.content_relpath is None:
            self.get_content_dom()
        return self.content_relpath

    def get_toc_relpath(self) -> str:
        if not self.toc_relpath:
            self.get_manifest_items()
        return self.toc_relpath or ""

    def get_manifest_items(self):
        if not self.manifest_items:
            self.manifest_items = {}
            for item in self.get_content_dom().getElementsByTagName("item"):
                fullhref = normpath(unquote(self.get_content_relpath() + item.getAttribute("href")))
                self.manifest_items["h:" + fullhref] = (item.getAttribute("id"), item.getAttribute("media-type"))
                self.manifest_items["i:" + item.getAttribute("id")] = (fullhref, item.getAttribute("media-type"))
                if item.getAttribute("media-type") == "application/x-dtbncx+xml":
                    self.toc_relpath = get_path_part(fullhref)
                    self.toc_dom = parseString(self.epub.read(fullhref))
        return self.manifest_items

    def get_guide_items(self):
        if not self.guide_items:
            self.guide_items = {}
            for item in self.get_content_dom().getElementsByTagName("reference"):
                fullhref = normpath(unquote(self.get_content_relpath() + item.getAttribute("href")))
                self.guide_items[fullhref] = (item.getAttribute("type"), item.getAttribute("title"))
        return self.guide_items

    def get_toc_dom(self):
        if not self.toc_dom:
            self.get_manifest_items()
        return self.toc_dom

    def get_toc_map(self):
        """href -> [(text, anchor), ...]，anchor 为 None 表示整章对应一个文件。"""
        if not self.toc_map:
            self.toc_map = {}
            for navpoint in self.get_toc_dom().getElementsByTagName("navPoint"):
                src = normpath(unquote(self.get_toc_relpath() + navpoint.getElementsByTagName("content")[0].getAttribute("src")))
                if "#" in src:
                    href, anchor = src.split("#", 1)
                else:
                    href, anchor = src, None

                try:
                    text = navpoint.getElementsByTagName("text")[0].firstChild.data
                except Exception:
                    text = ""

                self.toc_map.setdefault(href, [])
                if anchor is None:
                    idx = 0
                    while idx < len(self.toc_map[href]) and self.toc_map[href][idx][1] is None:
                        idx += 1
                    self.toc_map[href].insert(idx, (text, anchor))
                else:
                    self.toc_map[href].append((text, anchor))
        return self.toc_map

    # -- 章节（拆分点）列表 -------------------------------------------------

    def get_split_lines(self):
        """返回章节列表，每项为 dict：href/anchor/toc/id/type/num/sample。"""
        metadom = self.get_content_dom()
        try:
            self.orig_title = metadom.getElementsByTagName("dc:title")[0].firstChild.data
        except Exception:
            self.orig_title = "Untitled"

        for creator in metadom.getElementsByTagName("dc:creator"):
            try:
                if creator.getAttribute("opf:role") in ("aut", "") and creator.firstChild is not None:
                    if creator.firstChild.data not in self.orig_authors:
                        self.orig_authors.append(creator.firstChild.data)
            except Exception:
                pass
        if not self.orig_authors:
            self.orig_authors.append("Unknown")

        self.split_lines = []
        count = 0
        for itemref in metadom.getElementsByTagName("itemref"):
            idref = itemref.getAttribute("idref")
            href, mtype = self.get_manifest_items()["i:" + idref]

            current = {"href": href, "anchor": None, "toc": [], "id": idref, "type": mtype, "num": count}
            if href in self.get_guide_items():
                current["guide"] = self.get_guide_items()[href]
            raw = self.epub.read(href).decode("utf-8", errors="ignore")
            current["sample"] = raw[:1500]
            self.split_lines.append(current)
            count += 1

            if href in self.get_toc_map():
                for text, anchor in self.get_toc_map()[href]:
                    if anchor:
                        raw_anchor = split_html(raw, anchor, before=False)
                        current = {
                            "href": href, "anchor": anchor, "toc": [], "id": idref, "type": mtype,
                            "num": count, "sample": raw_anchor[:1500],
                        }
                        self.split_lines.append(current)
                        count += 1
                    current["toc"].append(text)
        return self.split_lines

    # -- 章节内容拆分及重组 -------------------------------------------------

    def get_split_files(self, linenums):
        """按所选行号拆出对应的 (filename, manifest_id, media_type, html) 列表。"""
        self.filecache = FileCache()
        if not self.split_lines:
            self.get_split_lines()
        lines = self.split_lines

        lines_set = {int(n) for n in linenums}
        for line in lines:
            line["include"] = line["num"] in lines_set

        outchunks = []
        inchunk = False
        currentfile = None
        start = None
        for line in lines:
            if line["include"]:
                if not inchunk:
                    inchunk = True
                    currentfile = line["href"]
                    start = line
                elif currentfile != line["href"]:
                    outchunks.append((currentfile, start, line))
                    currentfile = line["href"]
                    start = line
            elif inchunk:
                outchunks.append((currentfile, start, line))
                inchunk = False
        if inchunk:
            outchunks.append((currentfile, start, None))

        outfiles = []
        for href, start, end in outchunks:
            filedata = self.epub.read(href).decode("utf-8", errors="ignore")
            if start["anchor"] is not None:
                filedata = split_html(filedata, start["anchor"], before=False)
            if end is not None and end["anchor"] is not None and end["href"] == href:
                filedata = split_html(filedata, end["anchor"], before=True)

            filename = self.filecache.add_content_file(href, filedata)
            outfiles.append([filename, start["id"], start["type"], filedata])

        for fl in outfiles:
            soup = BeautifulSoup(fl[3], PARSER)
            changed = False
            for a in soup.find_all("a"):
                if a.has_attr("href"):
                    path = normpath(unquote("%s%s" % (get_path_part(fl[0]), a["href"])))
                    if path in self.filecache.anchors and self.filecache.anchors[path] != path:
                        a["href"] = self.filecache.anchors[path][len(get_path_part(fl[0])):]
                        changed = True
            if changed:
                fl[3] = str(soup)

        return outfiles

    def find_cover_candidate(self, linenums, min_width=400, min_height=600):
        """在所选章节范围内查找首张满足最小尺寸的图片，返回 (ext, bytes) 或 None。"""
        files = self.get_split_files(linenums)
        seen = set()
        for filename, _id, _type, filedata in files:
            soup = BeautifulSoup(filedata, PARSER)
            for img in soup.find_all("img") + soup.find_all("image"):
                src = img.get("src") or img.get("xlink:href")
                if not src:
                    continue
                orig_href = self.filecache.newold.get(filename, filename)
                img_path = normpath(unquote(get_path_part(orig_href) + src))
                if img_path in seen:
                    continue
                seen.add(img_path)
                try:
                    data = self.epub.read(img_path)
                    im = Image.open(io.BytesIO(data))
                    w, h = im.size
                    if w >= min_width and h >= min_height:
                        ext = (im.format or "JPEG").lower()
                        return ext, data
                except Exception as err:
                    logger.debug("find_cover_candidate: skip %s: %s", img_path, err)
        return None

    def write_split_epub(self, outputio, linenums, title, authors, tags=None, languages=None, description=None, cover_data=None):
        """将所选章节写为一本新的 EPUB。

        cover_data 为 (ext, bytes) 元组时，会将封面图片内嵌到 EPUB 的 manifest/guide/meta
        中（同时调用方仍可将其设置到 Calibre 的元数据上，二者互不冲突）。
        """
        tags = tags or []
        languages = languages or ["zho"]
        files = self.get_split_files(linenums)

        outputepub = ZipFile(outputio, "w", compression=ZIP_STORED)
        outputepub.writestr("mimetype", "application/epub+zip")
        outputepub.close()

        outputepub = ZipFile(outputio, "a", compression=ZIP_DEFLATED)

        container_dom = getDOMImplementation().createDocument(None, "container", None)
        top = container_dom.documentElement
        top.setAttribute("version", "1.0")
        top.setAttribute("xmlns", "urn:oasis:names:tc:opendocument:xmlns:container")
        rootfiles = container_dom.createElement("rootfiles")
        top.appendChild(rootfiles)
        rootfiles.appendChild(new_tag(container_dom, "rootfile", {"full-path": "content.opf", "media-type": "application/oebps-package+xml"}))
        outputepub.writestr("META-INF/container.xml", container_dom.toprettyxml(indent="   ", encoding="utf-8"))

        unique_id = "epubsplit-uid-%d" % time.time()
        content_dom = getDOMImplementation().createDocument(None, "package", None)
        package = content_dom.documentElement
        package.setAttribute("version", "2.0")
        package.setAttribute("xmlns", "http://www.idpf.org/2007/opf")
        package.setAttribute("unique-identifier", "epubsplit-id")

        metadata = new_tag(content_dom, "metadata", {"xmlns:dc": "http://purl.org/dc/elements/1.1/", "xmlns:opf": "http://www.idpf.org/2007/opf"})
        metadata.appendChild(new_tag(content_dom, "dc:identifier", text=unique_id, attrs={"id": "epubsplit-id"}))
        metadata.appendChild(new_tag(content_dom, "dc:title", text=title))
        for author in authors or self.orig_authors:
            metadata.appendChild(new_tag(content_dom, "dc:creator", attrs={"opf:role": "aut"}, text=author))
        metadata.appendChild(new_tag(content_dom, "dc:contributor", text="PoxenStudio/MyBooks(https://mybooks.top)", attrs={"opf:role": "bkp"}))
        for lang in languages:
            metadata.appendChild(new_tag(content_dom, "dc:language", text=lang))
        metadata.appendChild(new_tag(content_dom, "dc:description", text=description or ("Split from %s" % (self.orig_title or ""))))
        for tag in tags:
            metadata.appendChild(new_tag(content_dom, "dc:subject", text=tag))

        cover_filename = None
        if cover_data:
            ext, raw = cover_data
            ext = "jpg" if ext in ("jpg", "jpeg") else ext
            cover_media_type = "image/jpeg" if ext == "jpg" else "image/%s" % ext
            cover_filename = "cover.%s" % ext
            metadata.appendChild(new_tag(content_dom, "meta", attrs={"name": "cover", "content": "cover-image"}))
        package.appendChild(metadata)

        manifest = content_dom.createElement("manifest")
        package.appendChild(manifest)
        spine = new_tag(content_dom, "spine", attrs={"toc": "ncx"})
        package.appendChild(spine)
        manifest.appendChild(new_tag(content_dom, "item", attrs={"id": "ncx", "href": "toc.ncx", "media-type": "application/x-dtbncx+xml"}))

        if cover_filename:
            outputepub.writestr(cover_filename, raw)
            manifest.appendChild(
                new_tag(content_dom, "item", attrs={"id": "cover-image", "href": cover_filename, "media-type": cover_media_type, "properties": "cover-image"})
            )
            guide = new_tag(content_dom, "guide")
            guide.appendChild(new_tag(content_dom, "reference", attrs={"type": "cover", "title": "Cover", "href": cover_filename}))
            package.appendChild(guide)

        contentcount = 0
        for filename, _id, mtype, filedata in files:
            outputepub.writestr(filename, filedata.encode("utf-8"))
            item_id = "a%d" % contentcount
            contentcount += 1
            manifest.appendChild(new_tag(content_dom, "item", attrs={"id": item_id, "href": filename, "media-type": mtype}))
            spine.appendChild(new_tag(content_dom, "itemref", attrs={"idref": item_id, "linear": "yes"}))

        for linked in self.filecache.linkedfiles:
            mtype = "unknown"
            manifest_entry = self.get_manifest_items().get("h:" + linked)
            if manifest_entry:
                mtype = manifest_entry[1]
            try:
                outputepub.writestr(linked, self.epub.read(linked))
            except Exception as err:
                logger.warning("write_split_epub: skip linked file %s: %s", linked, err)
                continue
            item_id = "a%d" % contentcount
            contentcount += 1
            manifest.appendChild(new_tag(content_dom, "item", attrs={"id": item_id, "href": linked, "media-type": mtype}))

        outputepub.writestr("content.opf", content_dom.toprettyxml(indent="   "))

        toc_dom = getDOMImplementation().createDocument(None, "ncx", None)
        ncx = toc_dom.documentElement
        ncx.setAttribute("version", "2005-1")
        ncx.setAttribute("xmlns", "http://www.daisy.org/z3986/2005/ncx/")
        head = toc_dom.createElement("head")
        ncx.appendChild(head)
        head.appendChild(new_tag(toc_dom, "meta", attrs={"name": "dtb:uid", "content": unique_id}))
        head.appendChild(new_tag(toc_dom, "meta", attrs={"name": "dtb:depth", "content": "1"}))
        head.appendChild(new_tag(toc_dom, "meta", attrs={"name": "dtb:totalPageCount", "content": "0"}))
        head.appendChild(new_tag(toc_dom, "meta", attrs={"name": "dtb:maxPageNumber", "content": "0"}))

        doc_title = toc_dom.createElement("docTitle")
        doc_title.appendChild(new_tag(toc_dom, "text", text=strip_html(title)))
        ncx.appendChild(doc_title)

        nav_map = toc_dom.createElement("navMap")
        ncx.appendChild(nav_map)

        count = 1
        for line in self.split_lines:
            if not line["include"]:
                continue
            for nav_title in line["toc"] or [strip_html(title)]:
                navpoint = new_tag(toc_dom, "navPoint", {"id": "a%03d" % count, "playOrder": "%d" % count})
                count += 1
                nav_map.appendChild(navpoint)
                navlabel = toc_dom.createElement("navLabel")
                navpoint.appendChild(navlabel)
                navlabel.appendChild(new_tag(toc_dom, "text", text=strip_html(nav_title)))
                anchor_key = line["href"] + "#" + line["anchor"] if line["anchor"] else None
                src = self.filecache.anchors.get(anchor_key, line["href"]) if anchor_key else line["href"]
                navpoint.appendChild(new_tag(toc_dom, "content", {"src": src}))

        outputepub.writestr("toc.ncx", toc_dom.toprettyxml(indent="   ", encoding="utf-8"))
        for zf in outputepub.filelist:
            zf.create_system = 0
        outputepub.close()
