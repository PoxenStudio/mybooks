# Toolbox 工具箱系统设计说明

本文档说明 MyBooks 中 Toolbox（工具箱）功能的整体架构，涵盖后台功能实现、HTTP 路由与前端页面三个层次。

---

## 一、后台功能实现

### 1.1 整体层次结构

```
AsyncService
    └── BaseTool          # 工具基类（webserver/toolbox/base_tool.py）
            └── RareBookDownloader  # 具体工具（webserver/toolbox/rare_book_downloader.py）

ToolSet / Tool             # 工具注册与元数据管理（webserver/toolbox/toolset.py）
```

---

### 1.2 BaseTool — 工具基类

`BaseTool` 继承自 `AsyncService`，为所有工具提供通用的基础设施，让子类只需关注自身业务逻辑。

#### 子类必须实现的接口

| 成员 | 类型 | 说明 |
|---|---|---|
| `service_item_name` | `str` | 后台任务面板中显示的任务名称（会经过 i18n 处理） |
| `info()` | `staticmethod` | 返回工具元数据 dict（见下方格式） |

`info()` 返回格式：
```python
{
    "tool_id":      "my_tool",      # 唯一标识符
    "name":         "My Tool",      # 展示名称
    "description":  "...",
    "revision":     "1.0.0",
    "author":       "Author",
    "publish_date": "2025-01-01",
}
```

#### 工作目录管理

- `get_work_dir(unique_key)` — 在 `TOOL_DATA_ROOT/<tool_id>/<md5(unique_key)[:16]>` 下创建并返回任务专属工作目录
- `cleanup_work_dir(work_dir)` — 递归删除工作目录，失败时只记录警告，不向上抛异常

#### 后台任务生命周期

后台任务基于 `BackgroundService` 实现，流程如下：

```
create_task()  →  update_task_progress() × N  →  complete_task()
```

- `create_task(progress_data)` — 创建任务，返回 `task_id`
- `update_task_progress(task_id, progress, progress_data)` — 更新进度（0–100）
- `complete_task(task_id, error_message)` — 标记完成；`error_message` 非 None 时标记为失败
- `make_progress_callback(task_id, ...)` — 工厂方法，返回标准进度回调 `(int) -> None`，消除子类中的重复样板代码

#### 文件入库

`import_file(user_id, file_path, title, authors, ...)` 封装了完整的入库流程：

1. 校验文件格式是否在 `SUPPORTED_FORMATS`（epub / pdf / azw3 / mobi / txt）中
2. 用 Calibre 的 `get_metadata` 读取文件元数据
3. 用 `db.import_book()` 将文件导入 Calibre 书库
4. 创建 `Item` 数据库记录，关联 `collector_id`
5. 按 `delete_after_import` 标志决定是否删除源文件

---

### 1.3 RareBookDownloader — 古书下载工具

`RareBookDownloader` 是目前 Toolbox 中唯一的具体工具实现，演示了如何在 `BaseTool` 的基础上开发一个完整的工具。

```python
class RareBookDownloader(BaseTool):
    service_item_name = "古书下载"

    @staticmethod
    def info(): ...          # 返回工具元数据

    @AsyncService.register_service
    def download(self, url, user_id, callback=None): ...
```

`download()` 的执行步骤：

1. `create_task()` — 创建后台任务
2. `make_progress_callback()` — 构建进度回调
3. `_get_downloader(url)` — 根据 URL 选取对应的下载器（目前仅支持 `UsthkDownloader`）
4. `downloader.check_valid_url()` — 验证 URL 并取得书籍元数据
5. `get_work_dir(url)` — 创建工作目录
6. `downloader.download(work_dir, callback)` — 下载并转换为 PDF
7. `import_file()` — 将 PDF 导入书库
8. `complete_task()` + `cleanup_work_dir()` — 完成任务、清理临时文件

`@AsyncService.register_service` 装饰器使 `download()` 以异步方式运行，调用方立即返回，进度通过后台任务机制跟踪。

---

### 1.4 ToolSet / Tool — 工具注册与管理

`toolset.py` 提供两个类：

**`Tool`**：工具元数据的封装对象，字段包括 `id`、`name`、`description`、`revision`、`author`、`publish_date`、`page`，提供 `to_dict()` 供 API 序列化。

**`ToolSet`**：全局工具注册表（类级别 dict），主要方法：

| 方法 | 说明 |
|---|---|
| `collect_tools()` | 集中注册所有工具，在列表 API 中调用 |
| `register(info)` | 从 `info()` dict 创建 `Tool` 并存入注册表 |
| `all_tools()` | 返回全部已注册工具列表 |
| `get_tool(tool_id)` | 按 ID 查询单个工具 |

新增工具时只需在 `collect_tools()` 中加一行 `ToolSet.register(MyTool.info())`。

---

## 二、路由

路由定义在 `webserver/handlers/toolbox.py` 的 `routes()` 函数中，所有接口均需管理员权限（`@is_admin`）。

### 接口列表

| 方法 | 路径 | Handler | 说明 |
|---|---|---|---|
| GET | `/api/toolbox/list` | `AdminToolList` | 返回所有已注册工具的元数据列表 |
| POST | `/api/toolbox/rare_book_downloader` | `AdminRareBookDownloader` | 启动古书下载任务 |

### GET `/api/toolbox/list`

调用 `ToolSet.collect_tools()` 完成延迟注册，再通过 `ToolSet.all_tools()` 返回工具列表。

响应示例：
```json
{
  "err": "ok",
  "tools": [
    {
      "id": "rare_book_downloader",
      "name": "古书下载器",
      "description": "从书录古书的图书馆站点下载资源并导入到书库",
      "revision": "0.1.0",
      "author": "PoxenStudio",
      "publish_date": "2025-05-18",
      "page": ""
    }
  ]
}
```

### POST `/api/toolbox/rare_book_downloader`

请求体：
```json
{ "url": "https://lbezone.hkust.edu.hk/rse/..." }
```

Handler 在调用 `RareBookDownloader().download()` 前会校验：
- `url` 参数不能为空
- 域名必须是 `hkust.edu.hk` 或其子域名

任务以异步方式启动，接口立即返回成功消息，进度可通过后台任务面板查看。

响应示例：
```json
{ "err": "ok", "msg": "古书下载任务已启动，右上角可以查看进度" }
```

---

## 三、前端页面

前端由两个 Vue 页面组成，均使用 Vuetify 组件库。

### 3.1 工具列表页 — `admin/toolbox.vue`

路由：`/admin/toolbox`

页面通过 `asyncData` 在 SSR 阶段调用 `/toolbox/list` 获取工具列表，以卡片网格（每行最多 3 列）展示所有工具。

每张卡片包含：
- 工具图标（从 `/get/tool/{id}/icon` 加载，加载失败时显示默认图标 `mdi-tools`）
- 名称 + 版本 chip
- 描述文字
- 作者与发布日期

点击卡片后跳转到对应工具页面，路由为 `/toolbox/{tool.page || tool.id}`。

### 3.2 具体工具页 — `toolbox/rare_book_downloader.vue`

路由：`/toolbox/rare_book_downloader`

提供古书下载的操作界面：

- URL 输入框（支持回车触发）+ 下载按钮
- 按钮在请求进行中显示 spinner 并禁用，防止重复提交
- 请求完成后以 `v-alert` 展示成功/失败消息（带淡入动画）
- 页面底部附有指向 HKUST 线装书库的说明链接

核心逻辑在 `download()` 方法中：
1. 前端校验 URL 非空
2. 以 `POST` + JSON body 调用 `/toolbox/rare_book_downloader`
3. 根据响应的 `err` 字段决定展示成功还是错误样式

---

## 四、扩展新工具的步骤

1. 在 `webserver/toolbox/` 下新建 `<tool_id>.py`，继承 `BaseTool`，实现 `service_item_name`、`info()` 及核心业务方法
2. 在 `toolset.py` 的 `ToolSet.collect_tools()` 中注册新工具
3. 如需独立的路由，在 `webserver/handlers/toolbox.py` 的 `routes()` 中追加
4. 在 `app/src/pages/toolbox/` 下新建对应的 `.vue` 页面
5. 工具图标文件命名为 `<tool_id>` 同名，放置于对应静态资源目录下

---

## 五、MergeFormatsTool — 格式合并工具

### 5.1 设计背景

同一本书可能在不同时间以不同格式（如 EPUB 与 MOBI）导入，形成两条独立书籍记录。
`MergeFormatsTool` 用于将格式较少的"来源书籍"的格式文件合并到"目标书籍"，然后删除来源书籍，从而去除重复。

### 5.2 新增的 BaseTool 方法

| 方法 | 说明 |
|---|---|
| `search_books(query, max_results)` | 用 Calibre 的 `title:"~<query>"` 语法搜索书籍，返回包含 id/title/authors/formats/img 的列表 |
| `merge_book_formats(source_id, target_id)` | 将 source 书籍中 target 没有的格式文件复制过去，返回新增格式列表 |
| `delete_book_by_id(book_id)` | 删除 Item 记录及 Calibre 书籍数据 |

### 5.3 后台逻辑（`merge_formats_tool.py`）

`MergeFormatsTool` 继承 `BaseTool`，不使用后台任务（执行较快，同步返回结果）。

核心方法 `merge(source_book_id, target_book_id)`：

1. 校验 source ≠ target
2. 调用 `merge_book_formats()` 复制差异格式
3. 调用 `delete_book_by_id()` 删除来源书籍
4. 返回 `{"added_formats": [...], "deleted_book_id": int}`

### 5.4 路由

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/toolbox/merge_formats/search?q=<keyword>` | 按书名搜索，返回书籍列表 |
| POST | `/api/toolbox/merge_formats/merge` | 执行合并，body: `{"source_id": int, "target_id": int}` |

### 5.5 前端页面（`toolbox/merge_formats_tool.vue`）

页面分三个区域：

- **页头**：居中显示工具名称，右侧红底白字关闭按钮
- **书籍选择区**：左右两列对称布局
  - 每列包含按书名搜索框 + 书籍列表（`BookCards` 风格，带封面缩略图、格式 chips）
  - 点击卡片切换选中状态（再次点击取消）；选中书籍以高亮边框 + 勾选图标标识
- **合并操作区**：
  - 显示当前左右选中书名的摘要提示
  - 仅当左右均已选中且 ID 不同时，"合并"按钮才变为可用
  - 合并成功后清除选中状态，并从列表中移除已删除的来源书籍；以 `v-alert` 展示结果

### 5.6 i18n 覆盖

**后台**（`webserver/i18n/`）：新增 `格式合并`、错误消息等字符串的 `en.json` 和 `zh-TW.json` 翻译。

**前端**（`app/locales/`）：在 zh / en / zh-TW 三个文件中新增 `mergeFormats` 命名空间，覆盖页面所有文字。
