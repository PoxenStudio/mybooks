---
name: toolbox-tool-review
description: Review a MyBooks Toolbox tool's code (backend webserver/toolbox/<tool_id>.py + its routes in webserver/handlers/toolbox.py or manifest.json api_routes + frontend app/src/pages/toolbox/<tool_id>.vue) against the project's tool-authoring conventions — naming, dialog/UI scope, API completeness, API security, which MyBooks APIs it touches (flagging delete/modify), and file read/write hygiene. Use when asked to review, audit, or check a toolbox tool (built-in or external/dynamically-loaded) before merge or install.
---

# Toolbox 工具代码审核规范

审核对象：一个 Toolbox 工具的完整实现——后端 `webserver/toolbox/<tool_id>.py`（继承
`BaseTool`）、其路由（`webserver/handlers/toolbox.py` 里的 Handler，或外部工具
`manifest.json` 的 `api_routes` 动态挂载）、前端 `app/src/pages/toolbox/<tool_id>.vue`。

背景文档：[document/toolbox_design.md](../../../document/toolbox_design.md)、
[document/Toolbox_Dynamic_Design.md](../../../document/Toolbox_Dynamic_Design.md)、
[.claude/rules/ui.md](../../rules/ui.md)（对话框规范）、
`webserver/toolbox/core_api.py`（`CoreAPI` 命名空间：`calibre` / `db` / `tasks` /
`messages` / `storage` / `settings`）。

审核前先定位三份文件：
1. 后端工具类：`webserver/toolbox/<tool_id>.py`
2. 路由/Handler：`webserver/handlers/toolbox.py` 中对应类，或该工具 `manifest.json`
   的 `api_routes`
3. 前端页面：`app/src/pages/toolbox/<tool_id>.vue`（及其引用的子组件）

对外部/动态加载工具，额外检查 `manifest.json`（`tool_id`/`revision`/`entry_backend`/
`entry_frontend`/`core_api_version` 等必填字段，见 `toolbox_manager.validate_manifest`）。

逐项按 a-e 审核，每项给出「通过 / 有问题」判断，问题需附文件:行号引用。

---

## a. 代码问题与命名规范 + 前端页面范围

### 命名与结构
- `tool_id` 全小写下划线（snake_case），与文件名 `<tool_id>.py`、前端页面文件名
  `<tool_id>.vue`、图标文件名一致（见 toolbox_design.md 四、五节）
- 工具类名用 PascalCase，以 `Tool`/`Downloader` 等语义后缀结尾，继承 `BaseTool`
- `service_item_name` 必须设置，且经 `_()` i18n 包裹（不是硬编码中文/英文直出）
- `info()` 为 `staticmethod`，字段齐全：`tool_id`/`name`/`description`/`revision`/
  `author`/`publish_date`
- 入口方法（供 handler 调用的核心业务方法）标注 `@AsyncService.register_service`
  （toolbox_design.md 1.3 节要求所有工具入口都用这个装饰器，除非工具明确同步执行且
  耗时很短，如 `MergeFormatsTool.merge()`——这种例外要能在代码里看到合理理由）
- 工具类内部一律通过 `self.api.*`（`CoreAPI`）访问 Calibre / 应用数据库，不直接摸
  `self.db`/`self.session`（`base_tool.py`、`core_api.py` 是 Core API 的唯一实现来源，
  见 Toolbox_Dynamic_Design.md 第八节 M4 验收标准）——工具代码里出现裸的
  `self.db.new_api.*`/`self.session.query(...)` 是违规信号
- 不要在工具代码里 `import` webserver 内部未通过 `CoreAPI`/`utils` 暴露的私有实现
  细节；不要跨工具互相 import 对方的私有函数
- flake8（`.style.yapf` 配置，`column_limit=240`，`E501` 忽略）、无遗留 `print`/调试代码

### 前端对话框规范
逐条对照 [.claude/rules/ui.md](../../rules/ui.md)：
- 是否复用了 `AppDialog` 组件，而不是手写 `v-toolbar`/`v-card-actions`
- 只有一个取消/关闭入口，位置固定；footer 不与 toolbar 关闭重复
- footer 只有一个会产生后果的按钮，居中显示（不用 `v-spacer` 右对齐），除非落在
  ui.md 列出的「例外」名单（`dialog_audiolist`、`AppHeader.vue` 的 `ai_enabled`）
- 三种类型（action/confirm/progress）选型是否匹配场景，颜色语义是否对照 ui.md 的
  颜色表；非 7 个主题色（`primary`/`secondary`/`accent`/`error`/`info`/`success`/
  `warning`）之外的颜色（`orange`/`deep-orange`/`green`/`blue darken-4`……）是否补了
  `confirm-dark`
- Toolbar 之后无空 `v-card-title` 占位
- 文案 `common.close` vs `common.cancel` 用对场景

### 页面范围（不越界）
工具页面运行在 `/toolbox/<tool_id>` 下，审核是否存在越出自身职责范围的行为：
- 不修改全局导航/`AppHeader`/布局组件的状态或 DOM（除非该改动本就是被批准的公共
  组件改动，而不是工具页面顺手夹带的）
- 不写全局命名空间的 `localStorage`/`sessionStorage` key（应加 `<tool_id>` 前缀），
  不污染全局 Vuex store 的无关 module
- 不直接调用其它工具的私有 API（`/api/toolbox/<other_tool_id>/...`），确需复用应走
  `CoreAPI`/公共 utils
- 不引入影响其它页面渲染的全局 CSS（scoped style 或加前缀类名）
- 不在页面卸载时遗留全局事件监听/定时器（`beforeDestroy`/`destroyed` 里应清理）
- 图标资源、i18n key（前端 `mergeFormats` 式命名空间、后端 `webserver/i18n/`）按
  `<tool_id>` 或工具专属命名空间隔离，不占用通用 key 名

---

## b. 提供给前端的接口定义是否完整

对每个路由核对：
- 是否都在 `webserver/handlers/toolbox.py` 的 `routes()`（或 `manifest.json`
  `api_routes`）里注册，路径前缀 `/api/toolbox/...` 保持一致
- 是否都套了 `@js`（统一 JSON 编码/异常捕获/CORS）与 `@is_admin`（Toolbox 现状要求
  管理员权限，见下方 c 节）
- 请求参数：类型、是否必填、默认值，是否与前端实际传参一致（前端漏传的必填参数
  会在运行时才暴露，审核时应对照 `.vue` 里的请求 body 逐字段核对）
- 响应结构：是否稳定包含 `err` 字段；成功/失败路径的字段是否都在文档或代码注释里
  说明（参照 toolbox_design.md 的响应示例风格）
- `err` 错误码是否枚举完整、语义清晰（`xxx.invalid`/`xxx.not_found`/`xxx.failed` 之
  类），前端是否针对这些错误码都有对应处理分支，而不是只处理 `ok`
- 异步任务类接口：是否明确说明"立即返回 + 后台任务面板追踪进度"，前端是否正确
  处理立即返回后的 UI 状态（loading/禁用按钮防重复提交）
- 接口是否有对应的最小文档（哪怕只是 handler 里的 docstring/注释），供其它开发者
  和前端对接时查阅，不要求必须更新 toolbox_design.md 但新增独立路由的工具应补充

---

## c. 接口是否存在安全问题

- **鉴权**：Toolbox 全部接口默认要求管理员权限（`@is_admin`）——检查是否有遗漏；
  外部/动态工具通过 `manifest.json api_routes` 挂载的路由同样需要核实鉴权装饰器
  没有被绕过
- **输入校验**：
  - URL/域名类参数是否有白名单校验（参照 `RareBookDownloader` 的
    `hkust.edu.hk` 域名限制），避免 SSRF（工具向任意用户提供的 URL 发起服务端请求）
  - `book_id`/`task_id` 等 ID 参数是否校验存在性和归属，避免越权访问/操作他人数据
  - 文件路径参数（`file_path`）是否可能被用户完全控制并越权读写任意路径——服务端
    是否只接受工具自己生成的路径，不信任前端传入的任意绝对路径
  - Calibre 搜索语法拼接（`self.api.calibre.search_books(query)` 等）是否直接把用户
    输入拼进查询语法，是否有可能被用于非预期的过滤条件注入
- **文件上传**：
  - 大小限制（对照 mimo_tts 现有 7MB 限制类似的做法）、格式白名单校验（后缀 +
    实际内容校验，不能只信后缀名）
  - zip 安装包：是否校验 `sha256`（商店安装路径 `AdminToolStoreInstall` 已有）、
    解压是否存在 zip slip 风险（对照 `toolbox_manager._safe_extract` 的实现，新代码
    如果自己写了解压逻辑要复用/对齐这个防护，不能直接 `zf.extractall()`）
  - 临时文件命名是否可预测导致竞态/覆盖（`tempfile.mkstemp` 优先于自拼路径）
- **命令执行/反序列化**：是否存在拼接 shell 命令、`eval`/`pickle.loads` 等处理不可信
  输入的场景；子进程调用（如 PDF/EPUB 转换）是否用参数数组而非 shell 字符串拼接
- **密钥/敏感信息**：API Key 等凭据是否加密存储（对照 TTS 配置 PBKDF2-SHA256 +
  文件权限 `0o600` 的做法），是否被记入日志（`logging.info`/`error` 里打印了明文
  key/密码）
- **速率与资源限制**：耗时/资源密集操作（下载、转换）是否有并发限制或任务互斥
  （`task.running` 类错误码），避免被重复触发耗尽资源
- **CSRF/XSRF**：POST 接口是否遵循 Tornado 标准 xsrf 机制，没有为图方便关闭校验

---

## d. 使用了 MyBooks 的哪些接口/能力（分类列出，delete/modify 特别标注）

在工具代码中检索所有 `self.api.*`、`self.db.*`、`self.session.*`、`Item(...)`、
`BackgroundService()` 等调用，按下表分类列出（审核报告里需要输出这张表，不能只写
"用到了数据库操作"这种笼统结论）：

| 类别 | 命名空间/方法 | 操作类型 | 说明 |
|---|---|---|---|
| Calibre 书库 | `CoreAPI.calibre.search_books` / `get_metadata` / `get_data_as_dict` / `cover` / `all_book_ids` / `format_abspath` / `get_custom` | 读 | |
| Calibre 书库 | `CoreAPI.calibre.import_book` / `import_file` / `add_format` / `set_metadata` / `set_custom` / `set_language` / `merge_formats` | ⚠️ 写/改 | 会修改书籍元数据或新增格式文件 |
| Calibre 书库 | `CoreAPI.calibre.delete_book` / `remove_formats` | ⚠️⚠️ 删除 | 删除书籍记录或格式文件，不可逆 |
| 应用数据库(Reader/Item) | `CoreAPI.db.get_item_by_book_id` / `get_reader` | 读 | |
| 应用数据库(Reader/Item) | `CoreAPI.db.create_item` | ⚠️ 写 | 新建 Item 记录 |
| 应用数据库(Reader/Item) | `CoreAPI.db.delete_item_by_book_id` | ⚠️⚠️ 删除 | |
| 后台任务 | `CoreAPI.tasks.*` / `create_task`/`update_task_progress`/`complete_task` | 状态变更 | 影响任务面板展示，非数据删改 |
| 站内消息 | `CoreAPI.messages.*` | 写 | |
| 工具数据/配置 | `CoreAPI.storage.*` | 写（工具专属目录内） | 见 e 节工作目录范围要求 |
| 系统配置 | `CoreAPI.settings.*`（白名单只读，`SettingsAPI.ALLOWED_KEYS`） | 读 | 确认读取的 key 在白名单内 |

审核输出要求：
1. 列出该工具**实际调用到**的每一个方法（不是把上表原样抄一遍），标注文件:行号
2. 所有标 ⚠️/⚠️⚠️ 的删除、修改类操作，在审核结论里单独汇总一节「数据变更操作」，
   说明触发条件、是否有二次确认（前端 confirm 对话框）、是否有权限/归属校验、
   是否可逆（比如 `MergeFormatsTool` 删除来源书籍前是否已确认格式合并成功）
3. 如果工具绕开 `CoreAPI` 直接操作 `self.db`/`self.session`，视为 a 节命名规范问题，
   同时在这里额外标注——因为这类调用未经封装，更容易遗漏必要的校验

---

## e. 文件读写：是否存在循环写入问题、是否限制在工作目录、有无清理逻辑

- **工作目录范围**：所有临时/中间文件是否都写在 `self.get_work_dir(unique_key)` 返回
  的 `TOOL_DATA_ROOT/<tool_id>/<hash>` 路径下（或 `CoreAPI.storage` 提供的工具专属
  目录），不要出现拼接绝对路径写到 `/tmp`、用户提供的任意路径、或其它工具的工作
  目录下的情况
- **路径穿越**：文件名（下载文件名、zip 内条目名、用户上传的文件名）在拼接进
  工作目录路径前是否做了净化（禁止 `../`、绝对路径、特殊字符），防止写出工作
  目录之外
- **循环写入/无界增长**：
  - 下载/转换类循环（分页下载、逐章节转换写 WAV/图片等）是否有明确的终止条件和
    最大次数/总大小上限，避免死循环或恶意响应导致无限写入耗尽磁盘
  - 断点续传/跳过已存在文件的逻辑（参照 TTS 工具"文件 ≥44 字节视为已完成，跳过"
    的做法）是否会在异常文件（0 字节、损坏文件）情况下反复重试写入同一文件
  - 是否对单文件大小、总下载大小有上限校验
- **清理逻辑**：
  - 成功路径调用 `cleanup_work_dir(work_dir)`；失败/异常路径是否也清理（`finally`
    块或显式 `except` 分支），避免任务失败后残留文件堆积
  - `cleanup_work_dir` 失败只记警告不抛异常（`base_tool.py` 已有实现，工具代码不应
    自己重复实现一套更脆弱的清理逻辑）
  - 使用 `tempfile.mkstemp`/`NamedTemporaryFile` 产生的临时文件（如
    `_save_upload_to_tmpfile`）是否在 `finally` 里 `os.remove`
  - 长期驻留的产物（导入书库后的源文件、按 `delete_after_import` 决定是否删除）
    行为是否符合预期，默认值是否安全（`import_file` 默认 `delete_after_import=True`，
    工具如果覆盖为 `False` 需要有明确理由，否则源文件会在工作目录里累积）

---

## f. 数据安全
- **数据提交**: 工具不能出现任何数据采集的操作，所有涉及HTTP POST的请求需要列出URL和数据内容进行Review。

---



## 输出格式

审核结论按 a-e 五节输出，每节：
- 「通过」或列出问题项，问题项格式：`file:line — 问题描述 — 建议修复`
- d 节额外附「使用的 MyBooks 接口一览」表 + 「数据变更操作」汇总
- 结尾给出总体结论：可以合并 / 需要修改后重新审核 / 存在阻断性安全问题需立即修复
