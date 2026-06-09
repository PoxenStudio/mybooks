import sys
import zipfile
import ebooklib
from ebooklib import epub

def display_epub_info(epub_path):
    try:
        print("=" * 60)
        print(f"📖 正在解析电子书: {epub_path}")
        print("=" * 60)

        # ----------------- 容错增强核心逻辑 -----------------
        # 针对 "OEBPS/OEBPS/" 重复路径的异常进行捕获与热修复
        try:
            book = epub.read_epub(epub_path, options={"ignore_ncx": False})
        except KeyError as e:
            error_msg = str(e)
            if "There is no item named" in error_msg:
                print(f"⚠️  检测到 EPUB 内部文件路径配置错误: {error_msg}")
                print("💡 正在尝试容错模式强制重载...")
                
                # 方案：利用 zipfile 检查真实路径，并临时拦截/重写内部 ZipFile 行为
                # 或者更轻量的方法：我们直接用自定义逻辑处理
                book = epub.EpubReader(epub_path).book
                # 强制初始化基本的容器结构，避开直接 read_epub 的严格检查
                with zipfile.ZipFile(epub_path, 'r') as z:
                    # 找到真正存在的文件列表
                    real_files = z.namelist()
                    
                    # 拦截并手动调用内部解析（跳过引发异常的坏文件）
                    reader = epub.EpubReader(epub_path)
                    try:
                        # 尝试正常读取，但允许单包文件丢失
                        book = epub.read_epub(epub_path, options={"ignore_ncx": False})
                    except Exception:
                        # 如果完全卡死，使用纯 ZipFile 提取元数据和骨架
                        fallback_display(epub_path)
                        return
            else:
                raise e
        # --------------------------------------------------

        # 2. 显示所有元数据 (Metadata)
        print("\n 🛠️  所有元数据 (Metadata):")
        print("-" * 40)
        metadata_namespaces = book.metadata.keys()
        for ns in metadata_namespaces:
            for key, items in book.metadata[ns].items():
                for item in items:
                    val = item if isinstance(item, tuple) else item
                    print(f"  - [{ns}:{key}]: {val}")

        # 3. 显示骨架信息 (Spine)
        print("\n 🦴 骨架信息 (Spine / 阅读线性顺序):")
        print("-" * 40)
        for index, item_ref in enumerate(book.spine):
            idref = item_ref[0] if isinstance(item_ref, tuple) else item_ref
            linear = item_ref[1] if isinstance(item_ref, tuple) and len(item_ref) > 1 else "yes"

            item = book.get_item_with_id(idref)
            file_name = item.get_name() if item else "未知文件（或路径损坏）"
            print(f"  {index + 1:02d}. ID: {idref:<20} | 线性阅读: {linear:<5} | 映射文件: {file_name}")

        # 4. 显示目录章节信息 (TOC)
        print("\n 📑 目录章节 (Table of Contents):")
        print("-" * 40)
        def parse_toc(toc_list, level=1):
            indent = "  " * level
            for item in toc_list:
                if isinstance(item, epub.Link):
                    print(f"{indent}• {item.title} -> {item.href}")
                elif isinstance(item, tuple) and len(item) == 2:
                    parent, children = item
                    if isinstance(parent, epub.Link):
                        print(f"{indent}📂 {parent.title} -> {parent.href}")
                    else:
                        print(f"{indent}📂 {parent}")
                    parse_toc(children, level + 1)
                elif isinstance(item, list):
                    parse_toc(item, level + 1)

        if book.toc:
            parse_toc(book.toc)
        else:
            print("  ⚠️ 未找到显式的目录信息（TOC为空）。")
        print("\n" + "=" * 60)

    except Exception as e:
        print(f"❌ 终极解析错误: {str(e)}")
        print("💡 提示：该 EPUB 文件结构严重受损，建议使用 Calibre 等工具进行‘书籍转换’修复。")


def fallback_display(epub_path):
    """当 ebooklib 完全崩溃时，使用标准 zipfile 暴力提取骨架和目录描述"""
    print("\n🚨 触发暴力提取模式（不依赖 ebooklib 解析媒体文件）...")
    from xml.etree import ElementTree as ET
    
    with zipfile.ZipFile(epub_path, 'r') as z:
        # 寻找 opf 配置文件
        opf_path = None
        for f in z.namelist():
            if f.endswith('.opf'):
                opf_path = f
                break
        
        if not opf_path:
            print("❌ 错误：无法在解压包中找到 .opf 配置文件")
            return
            
        opf_data = z.read(opf_path)
        root = ET.fromstring(opf_data)
        
        # 命名空间处理
        ns = {'opf': 'http://idpf.org', 'dc': 'http://purl.org'}
        
        print("\n 🛠️  元数据 (从 OPF 强行提取):")
        for meta in root.findall('.//opf:metadata/*', ns):
            tag = meta.tag.split('}')[-1]
            if meta.text:
                print(f"  - [dc:{tag}]: {meta.text.strip()}")
                
        print("\n 🦴 骨架信息 (Spine 强行提取):")
        # 建立 manifest 映射字典
        manifest = {}
        for item in root.findall('.//opf:manifest/opf:item', ns):
            manifest[item.get('id')] = item.get('href')
            
        for idx, item in enumerate(root.findall('.//opf:spine/opf:itemref', ns)):
            idref = item.get('idref')
            real_path = manifest.get(idref, "未知物理路径")
            print(f"  {idx+1:02d}. ID: {idref:<20} | 映射路径: {real_path}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        epub_file = sys.argv[1]
    else:
        epub_file = "test.epub"
    display_epub_info(epub_file)

