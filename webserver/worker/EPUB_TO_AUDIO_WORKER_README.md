# EPUB to Audio Worker 使用说明

这个工具扩展了 `simple_worker.py`，添加了专门的 `EpubToAudioWorker` 类来处理 EPUB 转音频转换，并实时解析运行进度。

## 主要功能

1. **子进程调用**: 通过子进程调用 `epub_to_audio/main.py` 进行转换
2. **进度解析**: 实时解析 `[BOOKBARN]` 日志信息，跟踪转换进度
3. **JSON 输出**: 将进度信息格式化为 JSON 输出
4. **章节状态跟踪**: 跟踪每个章节的处理状态（处理中、已转换、失败）

## 日志解析

工具解析以下 `[BOOKBARN]` 日志格式：

- `[BOOKBARN]Chapters:{数量}` - 总章节数
- `[BOOKBARN]Processing:{序号},{标题}` - 正在处理的章节
- `[BOOKBARN]Converted:{序号},{标题}` - 已转换完成的章节
- `[BOOKBARN]Error:{序号},{错误信息}` - 处理失败的章节
- `[BOOKBARN]ConversionFailed:{失败数量}` - 整体任务失败
- `[BOOKBARN]ConversionSuccess:{输出目录}` - 整体任务成功

## 进度数据结构

```json
{
  "status": "idle|running|completed|failed",
  "total_chapters": 0,
  "processed_chapters": 0,
  "converted_chapters": 0,
  "failed_chapters": 0,
  "current_chapter": {
    "idx": 1,
    "title": "章节标题"
  },
  "chapters": {
    "1": {
      "title": "Chapter 1",
      "status": "converted|failed|processing",
      "error": "错误信息或null"
    }
  },
  "output_folder": "/path/to/output",
  "error_message": "错误信息或null",
  "start_time": 1234567890.123,
  "end_time": 1234567890.456,
  "execution_time": 123.45
}
```

## 使用方法

### 1. 命令行使用

```bash
# 基本转换
python3 worker/simple_worker.py epub_to_audio /path/to/book.epub /path/to/output

# 带参数的转换
python3 worker/simple_worker.py epub_to_audio /path/to/book.epub /path/to/output \
  --tts edge \
  --language zh-CN \
  --worker_count 2 \
  --voice_name zh-CN-YunyangNeural \
  --main_py_path epub_to_audio/main.py \
  --timeout 3600

# 只显示进度（每2秒更新）
python3 worker/simple_worker.py epub_to_audio /path/to/book.epub /path/to/output \
  --progress_only
```

### 2. Python 代码使用

```python
from worker.simple_worker import EpubToAudioWorker

# 创建工作器
worker = EpubToAudioWorker(
    main_py_path="epub_to_audio/main.py",
    timeout=3600  # 1小时超时
)

# 执行转换
result = worker.convert_epub_to_audio(
    epub_path="/path/to/book.epub",
    output_dir="/path/to/output",
    tts="edge",
    language="zh-CN",
    worker_count=2,
    voice_name="zh-CN-YunyangNeural",
    no_prompt=True
)

# 检查结果
if result['success']:
    print("转换成功!")
    print(f"输出目录: {result['progress']['output_folder']}")
    print(f"转换章节: {result['progress']['converted_chapters']}")
    print(f"失败章节: {result['progress']['failed_chapters']}")
else:
    print(f"转换失败: {result['error']}")

# 获取详细进度信息
progress_json = worker.get_progress_json()
print(progress_json)
```

### 3. 实时进度监控

```python
import threading
import time
import json

# 在后台线程中运行转换
def conversion_thread():
    return worker.convert_epub_to_audio(epub_path, output_dir, **options)

thread = threading.Thread(target=conversion_thread)
thread.daemon = True
thread.start()

# 监控进度
while thread.is_alive() or worker.is_running():
    progress = worker.get_progress()
    print(json.dumps(progress, indent=2, ensure_ascii=False))
    time.sleep(2)  # 每2秒更新
```

## 测试

运行测试脚本：

```bash
# 测试完整转换
python3 test_epub_worker.py --mode convert

# 测试进度监控
python3 test_epub_worker.py --mode monitor
```

## 注意事项

1. 确保 `epub_to_audio/main.py` 存在且可执行
2. 确保有足够的磁盘空间用于输出音频文件
3. 转换时间取决于书籍大小和 TTS 服务响应速度
4. 使用 `--timeout` 参数避免长时间等待
5. 使用 `--progress_only` 可以实时监控而不显示详细输出

## 错误处理

- 进程超时会自动终止并标记为失败
- 单个章节失败不会影响其他章节转换
- 所有错误信息都会记录在进度数据中
- 支持 Ctrl+C 中断转换过程
