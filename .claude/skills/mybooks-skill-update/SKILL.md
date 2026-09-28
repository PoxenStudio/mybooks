---
name: mybooks-skill-update
description: Update the distributable MyBooks agent skill in skills/mybooks/ (SKILL.md + scripts/mybooks_api.py) so its tools match the current MyBooks HTTP API as documented in document/WebAPI.md and implemented in webserver/handlers/. Adds new tools, updates parameters/behavior of existing ones, keeps the dispatcher list, docs, decision guide and safety rules consistent. Use when asked to update/sync/完善 the mybooks skill, add a tool to it, or after the API changed.
---

# 更新 MyBooks Skill（skills/mybooks）

同步链：`document/WebAPI.md`（接口事实）→ **本 skill** → `webserver/mcp/api_tools.py`（MCP）。
Skill 是对外分发的独立包：脚本只能依赖 Python 标准库 + `requests`，**不能** import `webserver` 下的任何代码。

## 0. 输入

1. 先确认 API 文档是最新的：接口有改动而文档未更新时，先执行 `mybooks-api-doc-update`。
2. 以代码为准：文档与 handler 代码冲突时，以 `webserver/handlers/` 为准，并顺手修正文档。
3. 列出现有工具：`skills/mybooks/scripts/mybooks_api.py` 中 `execute_tool()` 的 `available_tools`。

## 1. 决定要改什么

- **新增工具**：面向终端用户、适合由 AI 代劳的接口（查询、个人书架、书单、阅读记录、元数据维护等）。
  不要暴露：系统设置、用户管理、SSL、日志、批量删除、回收站等运维/高危管理接口，除非用户明确要求。
- **更新工具**：接口的参数、默认值、返回结构或权限变了（如 `search_books` 新增字段搜索）。
- **删除工具**：接口已下线。

## 2. 修改 scripts/mybooks_api.py

每个工具是 `MyBooksAPI` 上的一个方法，名称 = 工具名（snake_case），签名固定：

```python
def tool_name(self, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    一句话说明。

    Args:
        book_id (int, required): Book ID
        page (int, optional): Page number (default: 1)
    """
    book_id = args.get("book_id")
    if not book_id:
        return {"status": "error", "message": "book_id is required"}
    return self._call_with_auto_relogin("GET", f"/api/book/{book_id}", params={...})
```

约定：
- 一律通过 `_call_with_auto_relogin(method, path, params=/json=/data=/files=)` 调用；query 用
  `params=` 或 `urllib.parse.urlencode`，不要手拼未编码的字符串。
- 必填参数在客户端先校验，错误返回 `{"status": "error", "message": ...}`，不发请求。
- 分页统一对外暴露 `num` + `page`（从 1 开始），内部换算成接口需要的 `start`/`size`/`page_size`。
- 方法 docstring 的 `Args:` 与 SKILL.md 参数表保持一致——MCP 同步时以它为准。
- 把新工具名加入 `execute_tool()` 的 `available_tools` 列表（MCP 的一致性测试读取这个列表）。

**安全规则（不可省略）**：
- **破坏性操作两步确认**：删除/清空类工具必须带 `confirm` 参数；未传 `confirm: true` 时只返回预览
  + `err: "confirm.required"`，不执行（参考 `delete_booklist`、`delete_reading_time`）。
- **批量写入先 dry-run**：如 `push_notes` 默认 `dry_run: true`。
- **本地文件读取**只允许白名单扩展名（参考 `EBOOK_UPLOAD_EXTS`），并在 frontmatter 的
  `metadata.permissions.filesystem` 声明；**写本地文件**不得覆盖已有文件、限定扩展名。
- 不向非 `MYBOOKS_HOST` 的地址发送任何数据；不在输出里回显密码/API key。

## 3. 修改 SKILL.md

- 工具章节放在对应分组（基础 / 书单 / TTS …），章节间用 `---` 分隔，结构固定：

````markdown
### `tool_name` — 中文短标题

**使用场景**：
- 什么时候用；给出一两句典型用户说法，如 "有没有余华的书？"

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `book_id` | int | ✅ | — | 书籍 ID |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py tool_name '{"book_id":42}'
```

**响应示例**：
```json
{ "err": "ok", ... }
```
````

- 同步更新：
  - frontmatter `description`（新增能力要写进去，这是 skill 触发依据）和 `metadata.permissions`（涉及文件读写时）；
  - “使用场景决策指南”：新工具加入对应决策分支；
  - “错误处理规范”：新增的 `err` 码及处理方式；
  - 破坏性工具在说明里写明“先预览、用户同意后再 confirm”。
- 响应示例取自 API 文档/handler 的真实返回字段，不要编造字段。

## 4. 校验

```bash
python3 -m py_compile skills/mybooks/scripts/mybooks_api.py
flake8 skills/mybooks/scripts/mybooks_api.py --config .style.yapf
# 工具清单三方一致：available_tools / 方法定义 / SKILL.md 章节
python3 - <<'EOF'
import re
src = open("skills/mybooks/scripts/mybooks_api.py").read()
listed = set(re.findall(r'"(\w+)"', re.search(r"available_tools = \[(.*?)\]", src, re.S).group(1)))
defined = set(re.findall(r"^    def ([a-z]\w+)\(self, args", src, re.M))
doc = open("skills/mybooks/SKILL.md").read()
# 工具可写在 ### 标题里，或（成组的工具）写在表格首列
heads = "\n".join(l for l in doc.splitlines() if l.startswith("### "))
documented = set(re.findall(r"`(\w+)`", heads)) | set(re.findall(r"^\| `(\w+)` \|", doc, re.M))
print("listed-not-defined:", sorted(listed - defined))
print("defined-not-listed:", sorted(defined - listed))
print("not-documented:", sorted(listed - documented))
EOF
```

有可用的 MyBooks 实例时（`MYBOOKS_HOST/USER/PASSWORD` 已配置），对新增/改动的只读工具实际跑一次
`python3 skills/mybooks/scripts/mybooks_api.py <tool> '<json>'` 验证；写操作只在用户同意后测试。

## 5. 后续

Skill 工具有增删改时，**必须**接着执行 `mybooks-mcp-update`，否则 `tests/test_mcp_api_tools.py`
的一致性测试会失败。
