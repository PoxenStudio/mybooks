# 书源引擎（book_source_engine）

MyBooks Toolbox 的书源管理引擎：兼容 Legado 3.0 规则的解析与抓取、多书源异步搜索、
正文抓取与 EPUB 生成，内置反爬层与安全加固。

- 管理入口：工具箱页面 `/toolbox/book_source`（`app/src/pages/toolbox/book_source.vue`）
- 工具注册：`BookSourceTool`（`webserver/toolbox/book_source_tool.py`），由 `ToolSet.collect_tools()` 注册
- API 路由：`webserver/handlers/book_source_api.py`，14 条 `/api/toolbox/book_source/*`，全部管理员权限
- 测试：`tests/test_book_source_engine.py`（119 个用例，随 CI 的 `pytest tests/` 运行）

## 技术路径

1. **规则解析**（`rule_engine.py`）：Legado 3.0 兼容——`@css:` 前缀、JSONPath、
   XPath、Legado 简写（`class.xxx` / `id.xxx` / `tag.xxx` / `text.xxx`）、
   `||` / `&&` / `%%` 组合符、`@put:` / `@get:` 变量、多页目录 `nextTocUrl`、
   多页正文 `nextContentUrl`、Explore 分类浏览。
2. **JS 规则**（`js_runtime.py`）：经 **dukpy**（Duktape 引擎的 Python 绑定）在受限沙箱执行
   书源 `jsLib` / `result.replace` 等简单后处理；`java.ajax`、`java.getString` 等外部副作用
   与无界循环一律拒绝执行；规则长度上限 50KB，解释器 LRU 缓存 32 个。
3. **多源异步搜索**（`search_task_service.py`）：单例 + `ThreadPoolExecutor`（默认 10 线程），
   创建任务立即返回 `task_id`，快源先出、慢源不拖累，前端轮询 `search_status` 获取结果，
   任务 5 分钟 TTL 自动清理。
4. **下载与 EPUB**（`epub_helper.py`）：逐章抓取正文 → EbookLib 生成 EPUB（图片按章节唯一命名、
   封面不落盘），任务进度走后台任务面板，完成后可下载 `download_epub`。
5. **反爬层**：UA 轮换池、浏览器风格请求头（Sec-Fetch-*）、请求间隔抖动、
   状态感知重试（429 Retry-After / 403+5xx 退避换 UA）、代理支持（`MYBOOKS_PROXY`）、
   可选 `curl_cffi` Chrome TLS 指纹（`MYBOOKS_HTTP_BACKEND=curl_cffi`）、chardet 解码、零宽字符清洗。
6. **安全加固**：SSRF 防护（拒绝内网/回环 URL）、多用户任务隔离、书源文件读写锁、
   Legado 开区间索引越界防护、JS 长度与循环限制。

## 版权与归属（重要）

本引擎的设计与部分实现移植自 **[talebook](https://github.com/talebook/talebook)** 的书源模块：

- 多源异步搜索架构：Talebook `webserver/services/booksource/booksource_search.py`（BSD-2-Clause）
- Legado 选择器引擎：移植自 talebook 的 fork（`rule_engine.py` 中 `# 从 talebook fork 移植`）
- 正文清理思路：借鉴 talebook `webserver/services/booksource/cleaner.py`（零宽字符 U+200B/U+200C/U+200D/U+FEFF 等）

以上部分代码在 **BSD-2-Clause** 许可下使用，版权归其原作者所有。
详见 talebook 的 [LICENSE](https://github.com/talebook/talebook/blob/master/LICENSE)。

## 关于 dukpy 依赖（对 Docker 打包的影响）

- 仅当书源规则包含 JS（`jsLib` / `jsRule`）时才需要 dukpy；纯 CSS/JSONPath/XPath 规则不依赖它。
- `dukpy==0.6.0` 在 PyPI 提供 **cp39–cp314 全平台预编译 wheel**：
  manylinux2014/manylinux_2_17/manylinux_2_28（x86_64 与 aarch64）、musllinux、
  Windows（32/64 位）、macOS（x86_64/arm64）。
  因此 **不需要编译器**，不会影响 MyBooks 的多架构 Docker 构建（amd64/arm64 均直接安装 wheel）。
- 即使某个平台无法安装 dukpy，`js_runtime.py` 会检测到缺失并自动降级
  （`_HAS_DUKPY = False`）：引擎与其余书源功能完全正常，仅带 JS 规则的书源在运行时报错，
  对应测试用例自动跳过（`skipUnless`）。

## 部署与注册（本 PR 已包含的改动）

| 文件 | 改动 |
| --- | --- |
| `webserver/toolbox/toolset.py` | `collect_tools()` 中 import + `ToolSet.register(BookSourceTool.info())` |
| `webserver/handlers/toolbox.py` | import `BOOK_SOURCE_ROUTES`，`routes()` 末尾追加 |
| `requirements.txt` | 追加 `dukpy==0.6.0` |
| `app/locales/{zh,en,zh-TW}.json` | 顶层新增 `bookSource` 键 |

### API 路由表（`/api/toolbox/book_source/...`）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `list` | 书源列表 |
| POST | `save` | 新增/更新书源 |
| POST | `toggle` | 启用/停用 |
| POST | `delete` | 删除 |
| POST | `search_async` | 异步多源搜索 |
| GET | `search_status?task_id=` | 搜索进度与结果 |
| GET | `test?source=` | 单源连通性测试 |
| POST | `download` | 下载书籍 |
| POST | `generate_epub` | EPUB 生成任务 |
| POST | `cancel` | 取消后台任务 |
| GET | `progress` | 最近任务进度 |
| POST | `import_zip` | 上传 zip 导入书源 |
| POST | `import_url` | 从 URL 导入书源 |
| GET | `download_epub` | 下载最近生成的 EPUB |

## 环境变量

| 变量 | 作用 |
| --- | --- |
| `MYBOOKS_HTTP_BACKEND` | `curl_cffi`（Chrome TLS 指纹，需安装）或 `requests` |
| `MYBOOKS_PROXY` | HTTP(S) 代理地址 |
| `MYBOOKS_FETCH_DELAY` / `MYBOOKS_FETCH_JITTER` | 抓取间隔抖动（默认 0.3s / 0.5s） |
