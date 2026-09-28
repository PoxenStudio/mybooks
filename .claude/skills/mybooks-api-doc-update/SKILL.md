---
name: mybooks-api-doc-update
description: Update document/WebAPI.md — the MyBooks HTTP API reference — so it matches the current route table and handler code under webserver/handlers/. Finds undocumented or stale /api routes with a scanner script, reads each handler to extract path, method, auth level, parameters (query/path/JSON body/form/file) and response fields, and writes entries in the doc's fixed format. Use when asked to update/refresh/sync/补全 the API doc (API 文档), after adding or changing /api endpoints, or as the first step before updating the mybooks skill or MCP service.
---

# 更新 MyBooks API 文档（document/WebAPI.md）

`document/WebAPI.md` 是 MyBooks HTTP API 的唯一参考文档，也是下游两个同步任务的输入：
**本文档 → `mybooks-skill-update`（skills/mybooks）→ `mybooks-mcp-update`（webserver/mcp）**。
文档写错会一路传到 skill 和 MCP，所以每个字段都要以代码为准，不要凭印象或旧文档推断。

## 1. 找出差异

在仓库根目录运行扫描脚本（纯静态分析，无需 Calibre/启动服务）：

```bash
python3 .claude/skills/mybooks-api-doc-update/scripts/list_routes.py --missing   # 有路由、文档里没有
python3 .claude/skills/mybooks-api-doc-update/scripts/list_routes.py --stale     # 文档里有、路由已不存在
python3 .claude/skills/mybooks-api-doc-update/scripts/list_routes.py             # 全量，✗ 标记未文档化
```

每行输出：路径正则、Handler 类、模块、实现的 HTTP 方法及其装饰器（`auth`/`is_admin`/`js`）。

除了新增/删除，还要检查**已有条目是否过时**——参数改名、新增参数、返回字段变化。
用户点名某个接口，或 `git log -p -- webserver/handlers/<module>.py` 显示近期有改动时，
逐条对照代码复核对应章节。

## 2. 从代码提取接口信息

对每个要写的路由，打开 Handler 类，**逐项核对**：

| 信息 | 在代码里看哪里 |
|---|---|
| 路径 | `routes()` 里的正则；捕获组写成占位符：`([0-9]+)` → `<id>`（或更具语义的 `<book_id>`），`(.*)` → `<name>` |
| 方法 | 类里实现的 `get/post/put/delete`；同一路径多个方法分别写 `#### GET …` / `#### POST …` 小节 |
| 认证 | `@is_admin` → 需要管理员；`@auth` → 需要登录；都没有 → 无需认证（再看方法体里是否手动检查 `self.current_user` / `is_admin()` / 书籍 owner）|
| query 参数 | `self.get_argument("x", default)`、`get_argument_start()`（`start`）、`self.get_arguments` |
| 路径参数 | `def get(self, id)` 等方法签名 |
| JSON body | `tornado.escape.json_decode(self.request.body)` / `json.loads(self.request.body)` 之后读取的 key |
| 表单/文件 | `self.request.files["xxx"]`、`self.get_body_argument` |
| 返回 | 所有 `return {...}` / `self.write(...)` 分支：成功时的字段 + 各种 `err` 码；列表类接口经 `render_book_list` 返回标准图书列表 |
| 默认值/范围 | `int(...)`、`min/max` 截断、枚举校验 |

Toolbox 工具路由（`/api/toolbox/<tool_id>/...`）归到“Toolbox 工具接口”一章，按工具分小节；
工具的设计见 [document/toolbox_design.md](../../../document/toolbox_design.md)。

## 3. 书写格式（必须遵守）

沿用文档现有结构：`## N. 分组` → `### N.M 接口名`，同一资源多个方法用 `####`。每个接口：

````markdown
### 3.2 搜索图书

- **路径**：`/api/search`
- **方法**：GET
- **认证**：无需认证 | 需要登录 | 需要管理员权限 | 需要管理员或书籍所有者权限
- **参数**：
  - `name` (string, 可选): 说明；默认值、取值范围、枚举含义都写清楚
  - `id` (path, 必填): 图书ID
  - JSON Body：
    - `title` (string, 可选): …
    - `authors` (array[string], 可选): …
  - 表单文件：`ebook` (file, 必填): …
- **响应**：
  - `err` (string): `ok` / `params.invalid`（原因）/ `permission.not_admin` …
  - `total` (int): …
  - `books` (array): 图书对象，见[图书对象结构](#图书对象结构)
- **响应示例**：

```json
{
  "err": "ok",
  "total": 12,
  "books": [...]
}
```
````

规则：
- 参数一律写 `(类型, 必填|可选)`，类型用 `string/int/number/bool/array[...]/object/path/file`。
- 无参数写 `- **参数**：无`。
- **响应**要列字段含义和可能的 `err` 码；示例 JSON 用真实感的值，省略的部分用 `...`。
- 与“通用响应格式”/“图书对象结构”重复的内容用链接引用，不要复制。
- 新错误码补进“附录A：错误代码说明”。
- 章节编号保持连续；插入新接口后顺延后续编号。
- 修改完成后更新文件头的 `**最后更新时间**：YYYY-MM-DD`。

## 4. 校验

```bash
python3 .claude/skills/mybooks-api-doc-update/scripts/list_routes.py --missing   # 应为空（或只剩刻意不写的内部接口）
python3 .claude/skills/mybooks-api-doc-update/scripts/list_routes.py --stale     # 应为空
```

刻意不写进文档的内部接口（如仅供前端页面内部轮询的静态资源），在汇报里列出并说明原因。

参数级核对（启发式，噪声较多——按 class 而非按方法取参数，响应字段也会被当成"文档参数"）：

```bash
python3 .claude/skills/mybooks-api-doc-update/scripts/audit_params.py
```

逐行看：`doc-only` 常意味着参数已改名/删除，`code-only` 常意味着漏写参数。
每一条都要回到 handler 代码确认，不能只凭脚本输出改文档。
常见坑：列表接口分页是 `start` + `size`（不是 `page`/`num`）；管理员批处理接口的书籍列表参数叫 `idlist`。

## 5. 后续

文档更新涉及 skill 已暴露的接口（或新增了适合暴露给 AI 的接口）时，提示用户接着运行
`mybooks-skill-update`，再运行 `mybooks-mcp-update`。
