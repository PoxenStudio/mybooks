import os
import sys
from ebooklib import epub
from pathlib import Path
import zipfile
import tempfile
import shutil

def extract_cover_image_robust(epub_path):
    """
    从EPUB文件中提取封面图片（增强容错版本）

    Args:
        epub_path: EPUB文件路径
    """
    # 检查文件是否存在
    if not os.path.exists(epub_path):
        print(f"错误: 文件 '{epub_path}' 不存在")
        return False

    try:
        # 方法1: 使用ebooklib的容错模式
        try:
            print("尝试使用ebooklib读取...")
            # 使用allow_failure=True可以跳过某些错误
            book = epub.read_epub(epub_path, {'skip_metadata': True})

            # 遍历所有items，查找id为cover.jpg（不区分大小写）
            cover_item = None
            for item in book.get_items():
                if item.get_name() and item.get_name().lower() == 'cover.jpg':
                    cover_item = item
                    break

            if cover_item:
                # 获取图片数据
                image_data = cover_item.get_content()
                if image_data:
                    return save_image(image_data, epub_path)

        except Exception as e:
            print(f"ebooklib读取失败: {e}")
            print("尝试使用备用方法...")

        # 方法2: 直接解析ZIP文件
        return extract_from_zip(epub_path)

    except Exception as e:
        print(f"处理EPUB文件时出错: {e}")
        return False

def extract_from_zip(epub_path):
    """
    直接从ZIP文件中提取封面图片（备用方法）
    """
    try:
        with zipfile.ZipFile(epub_path, 'r') as zip_file:
            # 获取所有文件名
            file_list = zip_file.namelist()

            # 查找cover.jpg（不区分大小写）
            cover_filename = None
            for filename in file_list:
                # 检查文件名是否以cover.jpg结尾（不区分大小写）
                if filename.lower().endswith('cover.jpg') or filename.lower().endswith('cover.jpeg'):
                    cover_filename = filename
                    break
                # 也检查路径中是否包含cover.jpg
                if 'cover.jpg' in filename.lower() or 'cover.jpeg' in filename.lower():
                    cover_filename = filename
                    break

            if not cover_filename:
                print("未找到cover.jpg文件")
                return False

            # 读取图片数据
            image_data = zip_file.read(cover_filename)
            if not image_data:
                print("图片数据为空")
                return False

            return save_image(image_data, epub_path, cover_filename)

    except zipfile.BadZipFile as e:
        print(f"ZIP文件损坏: {e}")
        return False
    except Exception as e:
        print(f"ZIP解析失败: {e}")
        return False

def save_image(image_data, epub_path, original_name=None):
    """
    保存图片到当前目录
    """
    # 生成输出文件名
    base_name = Path(epub_path).stem
    if original_name:
        # 从原始文件名中提取扩展名
        ext = Path(original_name).suffix
        if not ext:
            ext = '.jpg'
    else:
        ext = '.jpg'

    output_filename = f"cover_{base_name}{ext}"
    output_path = os.path.join(os.getcwd(), output_filename)

    # 如果文件已存在，添加序号避免覆盖
    counter = 1
    while os.path.exists(output_path):
        output_filename = f"cover_{base_name}_{counter}{ext}"
        output_path = os.path.join(os.getcwd(), output_filename)
        counter += 1

    # 写入文件
    try:
        with open(output_path, 'wb') as f:
            f.write(image_data)

        print(f"封面图片已保存: {output_path}")
        print(f"文件大小: {len(image_data)} 字节")
        return True
    except Exception as e:
        print(f"保存文件失败: {e}")
        return False

def main():
    # 检查命令行参数
    if len(sys.argv) < 2:
        print("用法: python extract_cover_robust.py <epub文件路径>")
        print("示例: python extract_cover_robust.py book.epub")
        print("支持: 单个文件或通配符 (如 *.epub)")
        sys.exit(1)

    # 支持通配符
    import glob
    epub_files = []
    for pattern in sys.argv[1:]:
        matched = glob.glob(pattern)
        if matched:
            epub_files.extend(matched)
        else:
            epub_files.append(pattern)

    if not epub_files:
        print("未找到匹配的EPUB文件")
        sys.exit(1)

    success_count = 0
    total_count = len(epub_files)

    for epub_file in epub_files:
        print(f"\n{'='*50}")
        print(f"处理文件 {epub_files.index(epub_file) + 1}/{total_count}: {epub_file}")
        print(f"{'='*50}")

        if extract_cover_image_robust(epub_file):
            success_count += 1
        else:
            print(f"文件 {epub_file} 提取失败")

    print(f"\n处理完成! 成功: {success_count}/{total_count}")


if __name__ == "__main__":
    main()
