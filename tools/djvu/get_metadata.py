import argparse
import djvu_rs as djvu


parser = argparse.ArgumentParser(description="djvu metadata viewer")
parser.add_argument("input_file", help="Input DJVU path")

args = parser.parse_args()

doc = djvu.Document.open(args.input_file)

# 获取文档元数据
metadata = doc.metadata()

if metadata:
    print("文档元数据:")
    for key, value in metadata.items():
        print(f"  {key}: {value}")
else:
    print("该文档没有元数据信息。")
