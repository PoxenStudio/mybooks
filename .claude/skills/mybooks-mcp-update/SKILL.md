---
name: mybooks-mcp-update
description: Update the MyBooks MCP server (webserver/mcp/mcp_service.py + webserver/mcp/api_tools.py) so its tools stay aligned with the mybooks skill (skills/mybooks/scripts/mybooks_api.py) — same tool names, parameters, validation and behavior — and with the current HTTP API. Use when asked to update/sync/review the MCP service or MCP tools, after the mybooks skill gained or changed tools, or when tests/test_mcp_api_tools.py parity checks fail.
---

# 更新 MyBooks MCP 服务（webserver/mcp）

同步链：`document/WebAPI.md` → `skills/mybooks` → **MCP**。MCP 以 skill 为准：同名工具的参数、
校验、两步确认等行为必须与 `skills/mybooks/scripts/mybooks_api.py` 一致。

## 架构（改之前先理解）

| 文件 | 作用 |
|---|---|
| `webserver/mcp/api_tools.py` | 与 skill 对齐的工具表。每个工具 = `@tool(name, description, properties, required)` 装饰的 `async def f(call, args)`，函数体与 skill 同名方法一一对应，只是把 `self._call_with_auto_relogin(...)` 换成 `await call(...)` |
| `webserver/mcp/mcp_service.py` | JSON-RPC 处理、token 认证、`_native_tools()`（MCP 独有工具）、`_api_request()`（以 MCP 用户身份经本机回环 HTTP 调 `/api/...`，签名 cookie `user_id`/`lt`/`invited`，透传 `X-Forwarded-Host/Proto`）|
| `webserver/handlers/mcp.py` | `/api/mcp/stream` 路由；复用 `MCPService` 实例并每次刷新 `base_handler` |
| `tests/test_mcp_api_tools.py` | 工具集与 skill 一致性测试 + 回环调用测试 |

`call(method, path, params=None, json=None)` 返回接口 JSON；非 JSON 响应会被包装成
`{"err": "http.error", "code": ..., "msg": ...}`。

**刻意不暴露**（skill 有、MCP 没有）：`book_upload`、`tts_clone_upload`、`tts_clone_audio`——它们读写
*调用方*本地文件，在 MCP 里会变成读写*服务器*文件。维护在 `api_tools.py` 文件头注释和
`tests/test_mcp_api_tools.py` 的 `MCP_EXCLUDED` 中。skill 新增同类“本地文件”工具时同样排除，两处一起改。

**MCP 独有工具**（`_native_tools()`，进程内直接实现）：`login`、`logout`、`get_books_count`、`get_books`、
`update_book_info`、`query_book_metadata`、`auto_fill_book_info`（以及隐藏的 `upload_book`/`download_book`）。
不要把 skill 已有的工具再写一份 native 实现；已有 native 工具若与 skill 工具功能重复，优先让它走 `api_tools`。

## 1. 找差异

```bash
~/miniconda3/bin/python -m pytest tests/test_mcp_api_tools.py -q   # test_same_tools_as_skill 会列出差集
```

再逐个对比 skill 方法与 `api_tools.py` 同名函数：
- 参数（名称、类型、必填、默认值）——skill docstring `Args:` ↔ `properties`/`required`；
- 客户端校验与错误信息；
- 请求：HTTP 方法、路径、query/JSON body 的构造；
- 特殊流程：两步确认（`confirm`）、`dry_run`、先搜索再调用（`get_notes`）等。

也要检查接口实现本身的变化（对照 `document/WebAPI.md` 与 handler），比如某接口新增了参数而 skill 已跟进。

## 2. 修改 api_tools.py

```python
@tool("tool_name", "English description for the LLM: what it does, when to use, safety notes.",
      {"book_id": BOOK_ID, "page": PAGE, "mode": S("...", enum=["a", "b"], default="a")},
      ["book_id"])
async def tool_name(call, args):
    if not args.get("book_id"):
        return _err("book_id is required")
    return await call("GET", f"/api/book/{args['book_id']}/xxx", params={...})
```

- 属性构造器：`S`(string) `I`(integer) `N`(number) `B`(boolean) `A`(array, items)；公用常量 `BOOK_ID`、`BOOKLIST_ID`、`NUM`、`PAGE`。
- 描述用英文（MCP 客户端多为英文模型提示），写清破坏性操作的确认要求。
- `required` 中的每个字段都必须出现在 `properties` 中（测试会检查）。
- 放在对应分组注释下（User & statistics / Search & browse / Book detail & edit / Folders / Notes / Delivery /
  Personal shelves / Reading stats / Booklists / TTS）。
- 不需要改 `mcp_service.py`：`list_tools()` 和 `tools/call` 自动覆盖 `API_TOOLS` 中的所有工具，
  并在需要登录时自动给每个工具加 `token` 参数。

旧参数兼容：若修改让已有 MCP 客户端的调用方式失效（改名/删参数），在 `mcp_service.py` 中像
`_legacy_search_args` 一样做转换，而不是在 `api_tools.py` 里分叉逻辑。

## 3. 更新文档与测试

- `document/WebAPI.md` 的“13. MCP 接口”一节：工具集说明、排除列表、MCP 独有工具、兼容参数。
- `tests/test_mcp_api_tools.py`：新工具有特殊流程（两步确认、参数换算）时补一个 `TestToolRequests` 用例。

## 4. 校验

```bash
flake8 webserver/mcp webserver/handlers/mcp.py tests/test_mcp_api_tools.py --config .style.yapf
~/miniconda3/bin/python -m pytest tests/test_mcp_api_tools.py -q
```

有运行中的 MyBooks 时，可用 JSON-RPC 冒烟测试（`<token>` 为管理员设置的 `AI_MCP_TOKEN`）：

```bash
curl -s "http://127.0.0.1:8080/api/mcp/stream?token=<token>" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_books","arguments":{"author":"余华"}}}'
```
