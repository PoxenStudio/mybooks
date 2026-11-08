# Mimo TTS 有声书工具

> 工具 ID：`mimo_tts`
> 版本：0.4.1
> 功能：将 EPUB / TXT 电子书转换为有声书（TTS），支持 MiMo 与 OpenAI 兼容 API
> 使用：书库 → 工具箱 → Mimo TTS → 选择书籍、配置 API 与音色 → 开始转换 → `/audio/{book_id}` 播放

---

## 〇、0.4.1 变更

### 1. 修复「未从 EPUB 中提取到任何章节内容」
- 原实现只按 TOC 取章节，且 TOC 兜底扫描仅在 TOC 为空时触发：TOC 只登记
  纯图片扉页（calibre 转换无标题层级书的常见产物）而正文文档不在 TOC 里时，
  唯一章节被空文本过滤 → 报错
- 现改为：TOC 提取的章节**全部无正文文本**时，兜底扫描全部内容文档
  （跳过 nav/toc 导航页），正文不再丢失
- TOC href 与 manifest href 在百分号编码 / 目录前缀上不一致时逐级放宽匹配
  （精确 → URL 解码 → 唯一文件名），避免章节文本静默置空

### 2. 新增 TXT 支持
- 格式选择沿用 chinese_converter 惯例：优先 EPUB，无 EPUB 时回退 TXT
- TXT 编码自动探测（复用 `chinese_converter.epub_converter.detect_encoding`：
  UTF-16/32 BOM 与无 BOM → UTF-8 → GB18030 / BIG5 择优；本轮修复无 BOM UTF-32
  被 UTF-16 启发式误判的问题——严格解码先行区分）
- 按「第X章/节/卷/回/部/篇/集、Chapter N（大小写不敏感）、序章/楔子/引子/尾声/
  终章/后记/番外」行首标题切章（标题行 ≤60 字符、不含句末标点，防正文长句
  误切；特殊章节名需独立成行或后接空格/全角冒号+短标题）；识别不到标题时
  整本单章；首个标题前 ≥100 字符的开头段保留为「开头」一章；整文件解码前
  有 64MB 上限（全文解码/切章内存放大约 4~5 倍，防超大文件打挂服务）
- 章节提取逻辑抽到 `mimo_tts_lib.py`（webserver-free 纯逻辑库，可独立测试，
  同 `epub_split_lib` / `epub_merge_lib` 惯例），新增 `tests/test_mimo_tts_lib.py`
- Review 修复：`_soup_text` 只取 body（`<head><title>` 等非正文不参与
  「章节是否有正文」判定、不进 TTS——ebooklib 0.19/0.20 规整 XHTML 会丢 head，
  但 XML 解析失败走 raw 兜底时 head 仍在）；EPUB 兜底扫描按文件名（而非全
  路径）跳过 nav/toc 导航页（`OEBPS/nav.xhtml` 此前会漏）

### 已知限制
- 续传按「章节序号+标题」文件名匹配：源文件内容变化但章节名不变时，同名
  WAV 会被复用（0.3.x 起的既有设计；改为内容哈希会让存量音频全部失效、
  触发全量重转的 API 费用，保持现状）

---

## 一、本 PR 相对 v1（develop 现有版本）的新增功能

> 此文档用于辅助 PR 审查：v1（revision 0.3.x）已合入 develop，本 PR 为 v2 增量。除下述新增外，其余为 bug 修复与体验完善。

### 1. 预置音色 + 内置试听
- 内置 MiMo V2.5 官方 **9 个预置音色**（中文：MiMo-默认 / 冰糖 / 茉莉 / 苏打 / 白桦；英文：Mia / Chloe / Milo / Dean），带语言与性别标注
- 每个音色附带固定文本试听 WAV（`app/public/static/mimo_tts/samples/*.wav`），**无需 API Key** 即可对比试听
- 试听仅在「MiMo TTS」类型下显示与播放

### 2. 音频克隆音色库（v2 核心新增）
- 上传 MP3/WAV（≤7MB）音频样本，自动切换 `mimo-v2.5-tts-voiceclone` 模型，`audio.voice` 传 `data:{mime};base64,...` 实现听书克隆
- 大小限制依据：MiMo 官方文档规定 `audio.voice` 的 Base64 ≤10MB，原始文件限 7MB（base64 约 9.3MB）
- 支持保存多个命名克隆音色（如旁白/男主/女主），列表试听、删除、选择使用；上传前前端校验格式与大小

### 3. 自定义提示词库
- 将自定义音色描述命名保存为提示词，多槽位存储于 `{tool_work_dir}/voice_prompts.json`（服务端，不依赖浏览器）
- 列表应用 / 删除，选择即填入并切换自定义模式

### 4. API 类型与模型调整
- 「MiMo Chat」改名为「MiMo TTS」
- 选中「MiMo TTS」时模型 ID **固定为 `mimo-v2.5-tts`**（前后端强制，不可编辑），默认自动填充 API URL：`https://api.xiaomimimo.com/v1/chat/completions`
- 「OpenAI 兼容」（audio_speech）与「自定义」类型下模型 ID 可自由修改

### 5. 其他修复
- 修复 `pathlib.Path` 未导入导致的崩溃（无目录 EPUB 解析标题分支 NameError）
- 未新增 Anthropic 格式：MiMo 官方 Anthropic 兼容端点仅覆盖纯 LLM 模型，不含 TTS 模型，第三方 TTS 均走 OpenAI 兼容格式

---

## 二、API 支持格式

| 类型 | 载荷 | 响应 |
|------|------|------|
| chat_completions（MiMo 等） | `messages` + `audio` 字段 | JSON → Base64 WAV |
| audio_speech（OpenAI TTS、Azure 等） | `{model, input, voice}` | 二进制 WAV |

无 `speed` 参数——通过音色描述的自然语言控制语速（MiMo）。

## 三、工作流

1. 从书库选择一本 EPUB 电子书
2. 配置 TTS API（MiMo 或 OpenAI 兼容）与音色
3. 后台任务逐章拆分文本、调用 TTS 合成、输出 WAV
4. 音频输出到 `AUDIO_OUTPUT_FOLDER/{book_id}/*.wav`，完成后自动刷新 `AudioBooksCache`，可在 `/audio/{book_id}` 页面播放

## 四、配置与安全

- 实例隔离：每个书籍按 `get_work_dir()` 生成独立工作目录
- 加密存储：API Key 经 PBKDF2-SHA256（100k 迭代）+ SHA-256 流加密保存至 `{tool_work_dir}/api_config.enc`，密钥存于 `.mimo_key`（权限 0o600），测试连接成功后自动保存、页面打开自动加载
- 断点续传：重复运行自动跳过已存在 WAV（≥44 字节），中断后可继续
- 文件名清洗：`_sanitize_filename` 清理非法字符、限长 120，防路径穿越；克隆/提示词名称同样清洗
- 实时进度：前端轮询 `/progress`，展示任务进度、阶段、章节与章节标题
- 交付物中不含任何 API Key

## 五、API 一览（前缀 `/api/toolbox/mimo_tts/`）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `convert` | 开始转换 |
| POST | `config` | 保存配置 |
| POST | `test` | 测试连接 |
| GET | `progress` | 查询任务进度 |
| POST | `clone/upload` | multipart 上传克隆音色（`voice_name` + `file`） |
| GET | `clone/list` | 克隆音色列表 |
| POST | `clone/delete` | 删除克隆音色 |
| GET | `clone/audio` | 试听克隆音频（管理员） |
| GET | `prompt/list` | 提示词列表 |
| POST | `prompt/save` | 保存提示词（同名覆盖） |
| POST | `prompt/delete` | 删除提示词 |

## 六、本 PR 涉及文件

| 文件 | 说明 |
|------|------|
| `webserver/toolbox/mimo_tts.py` | 工具类（BaseTool）：核心转换 / 加密 / 续传 / 预置音色 / 克隆 / 提示词库 |
| `webserver/toolbox/toolset.py` | 注册入口（develop 已含，本 PR 无改动） |
| `webserver/handlers/toolbox.py` | API Handler 与路由（新增 clone/prompt/progress 等） |
| `app/src/pages/toolbox/mimo_tts.vue` | 前端页面（三模式音色：预置/自定义/克隆；试听；提示词库；模型锁定；上传校验） |
| `app/public/static/mimo_tts/samples/*.wav` | 9 个预置音色试听音频 |
| `app/locales/{en,zh,zh-TW}.json` | 本地化文本（`mimoTts` 块） |

## 七、测试建议

1. 使用真实 MiMo API Key 完成一次完整 EPUB 转换，验证音频生成与播放
2. 切换 `audio_speech` 类型，验证 OpenAI TTS 格式
3. 中断转换后重跑，验证续传跳过已有文件
4. 克隆音色：上传 7MB 内样本试听；提示词库：保存/删除/应用全流程
5. 切换英文 / 繁体显示，检查翻译覆盖