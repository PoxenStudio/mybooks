# Toolbox 工具箱系统设计说明

本文档说明 Talebook 中 Toolbox（工具箱）功能的整体架构，涵盖后台功能实现、HTTP 路由与前端页面三个层次。

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
