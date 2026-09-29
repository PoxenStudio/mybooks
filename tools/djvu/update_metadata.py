import argparse
import djvu_rs as djvu


parser = argparse.ArgumentParser(description="djvu metadata viewer")
parser.add_argument("input_file", help="Input DJVU path")

args = parser.parse_args()

editor = djvu.Editor.open(args.input_file)

# 设置或更新元数据
editor.set_metadata({
    'title': 'New Title',
    'author': 'PoxenStudio',
    'extra': [('isbn', '978-0-123456-78-9')]
})

# 保存修改（会原子性地替换原文件）
editor.save(args.input_file)
