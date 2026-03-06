# Talebook 电子书管理 Skill

## 概述
Talebook 是一个个人电子书库管理系统，提供书籍的存储、分类、搜索和元数据管理功能。通过 MCP 接口，你可以帮助用户：
- 查询书库中书籍总量和统计信息
- 浏览书库中的书籍列表
- 搜索特定书籍
- 更新书籍的元数据（书名、作者、标签、分类等）
- 从豆瓣、百科等在线来源查询书籍信息
- 对书库中书籍进行自动元数据填充（封面、简介、标签等）
**MCP Server 名称**：`talebook`（已通过 mcporter 配置，token 已内嵌于连接地址，无需额外登录），用户也可能会使用书库或Talebook来称呼此服务。


## 工具说明

### 1. `get_books_count` — 获取书库统计

**使用场景**：
- 用户询问"我的书库有多少本书？"
- 需要了解书库规模时作为第一步查询

**参数**：无

**返回示例**：
```json
{
  "status": "success",
  "data": { "books": 1280, "authors": 342 },
  "message": "Total 1280 books, and 342 authors."
}
```

---

### 2. `get_books` — 分页浏览书籍列表

**使用场景**：
- 用户想浏览书库里有哪些书
- 需要获取最近添加的书籍（使用 `desc: true`）
- 遍历所有书籍时逐页获取

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `page` | number | ✅ | — | 页码，从 1 开始 |
| `page_size` | number | ❌ | 10 | 每页数量，范围 10–20 |
| `desc` | boolean | ❌ | — | 是否按 ID 倒序（true = 最新在前） |
| `include_comments` | boolean | ❌ | false | 是否包含书籍简介（会增加 token 消耗） |

**使用建议**：
- 通常先调用 `get_books_count` 了解总量，再分页获取
- 如只关心最新书籍，设 `desc: true`，只取第 1 页
- 不需要展示简介时，保持 `include_comments: false` 以减少 token 消耗

---

### 3. `search_books` — 搜索书籍

**使用场景**：
- 用户询问"有没有余华的书？"→ 用 `name` 参数
- 用户想找高评分书籍 →用 `rating` 参数
- 用户按标签分类找书，例如"科幻类" → 用 `tags` 参数
- 用户提供 ISBN 编号查书 → 用 `isbn` 参数
- 用户想找某个时间段添加的书 → 用 `create_time` 参数

**参数**（至少提供其中一个）：

| 参数 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `name` | string | 按书名或作者名搜索，支持简繁体自动转换 | `"活着"` / `"余华"` |
| `rating` | string | 评分条件查询 | `">=4"` / `"5"` |
| `tags` | string | 标签搜索，多个标签用英文逗号分隔（取交集） | `"小说,中国"` |
| `isbn` | string | ISBN 编号精确匹配 | `"9787020024759"` |
| `create_time` | string | 添加时间范围查询 | `">2024-01-01"` |
| `include_comments` | boolean | 是否包含书籍简介，默认 false | — |

**返回说明**：
- `data.list`：书籍列表，每本书包含：`id`、`title`、`author`、`tags`、`category`、`rating`、`publisher`、`pubdate`（以及可选的 `comments`）
- `data.total`：匹配的书籍总数（最多返回 20 条，但 `total` 反映实际命中数）

**注意**：`name` 搜索时系统会自动尝试简繁体转换，中文书名两种写法均可命中。

---

### 4. `update_book_info` — 更新书籍元数据

**使用场景**：
- 用户说"帮我把《XX》的作者改成YY"
- 用户要为书籍添加或修改标签、分类
- 用户需要手动修正书名、ISBN 或简介
- 通过 `query_book_metadata` 查到正确信息后，回填到书库

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `book_id` | string/integer | ✅ | 书籍 ID |
| `title` | string | ❌ | 书名 |
| `authors` | string/array | ❌ | 作者，可以是字符串或字符串数组 |
| `isbn` | string | ❌ | ISBN 编号 |
| `comments` | string | ❌ | 书籍简介（支持 HTML，**不要**将 `<>` 转义为 `&lt;&gt;`） |
| `tags` | string/array | ❌ | 标签，可以是字符串或字符串数组 |
| `category` | string | ❌ | 分类，自由文本字段，可用于任意分类目的 |

**注意事项**：
- 只传入需要修改的字段，未传入的字段保持不变
- `comments` 如包含 HTML 标签请保留原始格式，不要转义
- 操作需要当前用户对该书有编辑权限（需为管理员或书籍拥有者）

**返回示例**：
```json
{
  "status": "success",
  "message": "Successfully updated book (ID: 42)",
  "updated_fields": ["title: 活着", "authors: ['余华']"],
  "updated_by": "admin"
}
```

---

### 5. `query_book_metadata` — 在线查询书籍元数据

**使用场景**：
- 用户询问"帮我查一下《三体》的出版信息"
- 在更新书库前，先从网上查询准确元数据
- 用户提供 ISBN，需要获取书籍详细信息

**参数**（至少提供其中一个）：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `title` | string | 二选一 | 书名关键词 |
| `isbn` | string | 二选一 | ISBN 编号 |

**返回字段**（每本书）：

| 字段 | 说明 |
|------|------|
| `title` | 书名 |
| `authors` | 作者列表 |
| `publisher` | 出版社 |
| `isbn` / `isbn13` | ISBN 编号 |
| `comments` | 书籍简介 |
| `tags` | 标签列表 |
| `rating` | 评分（0–10） |
| `pubdate` | 出版日期 |
| `cover_url` | 封面图片链接 |
| `source` | 数据来源（`douban` / `baike` / `youshu` 等） |
| `provider_key` / `provider_value` | 数据源标识符（可用于后续精确匹配） |

**典型工作流**：
1. `query_book_metadata` 查询在线信息，确认结果
2. 展示给用户确认
3. 调用 `update_book_info` 将选定数据写入书库

---

### 6. `auto_fill_book_info` — 自动填充书籍信息

**使用场景**：
- 用户说"帮我更新《XX》的封面和简介"
- 用户说"书库里有很多书信息不完整，帮我补全"
- 用户想批量给书籍打上标签
- 这是**更新书库中现有书籍**的首选工具（比手动 `query + update` 更便捷）

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `book_ids` | array/integer/string | 二选一 | — | 书籍 ID 或 ID 数组 |
| `title` | string | 二选一 | — | 书名关键词。匹配唯一书籍时自动更新；匹配多本时返回列表供选择 |
| `only_tags` | boolean | ❌ | false | 为 `true` 时仅更新标签，不修改其他元数据 |

**两种调用模式**：

**模式 A：通过 `title` 查找并更新**
```
用户说："帮我更新《活着》的信息"
→ 调用 auto_fill_book_info(title="活着")
→ 若仅匹配一本：直接更新，返回成功
→ 若匹配多本：返回书籍列表，提示用户选择具体 book_id
```

**模式 B：通过 `book_ids` 直接更新**
```
用户说："帮我更新 ID 为 42、43 的书"
→ 调用 auto_fill_book_info(book_ids=[42, 43])
→ 返回每本书的处理结果
```

**返回结果格式**：

当 `title` 匹配多本书时，返回：
```json
{
  "status": "multiple_found",
  "message": "Found 3 books with title '活着'. Please specify book_ids to update.",
  "books": [
    { "id": 42, "title": "活着", "authors": ["余华"], "publisher": "..." },
    ...
  ],
  "total": 3
}
```

更新完成后，返回：
```json
{
  "status": "completed",
  "summary": { "total": 2, "success": 2, "failed": 0, "skipped": 0 },
  "results": [
    { "book_id": 42, "title": "活着", "status": "success", "message": "Book information updated successfully" }
  ],
  "updated_by": "admin"
}
```

**auto_fill 会同步更新的内容包括**：封面图片、书籍简介（comments）、出版社、出版日期、作者、标签（tags）。书名默认**保留原值不修改**（防止错误覆盖）。

---

## 使用场景决策指南

```
用户请求
│
├─ "有多少书？" / "统计书库" → get_books_count
│
├─ "列出书籍" / "浏览书库" → get_books（分页）
│
├─ "找 XX 书" / "搜索 YY 作者" → search_books
│
├─ "查一下 XX 的出版信息"（不修改书库）→ query_book_metadata
│
├─ "更新 XX 的信息" / "补全封面简介"（修改书库）→ auto_fill_book_info
│   │
│   └─ 若返回 multiple_found → 展示列表 → 用户确认 → 再次调用 auto_fill_book_info(book_ids=...)
│
└─ "手动修改某字段"（如改标签、改分类）→ update_book_info
    │（可先用 search_books 找到 book_id，再调用 update_book_info）
```

---

## 错误处理规范

| `status` 值 | 含义 | 建议处理 |
|-------------|------|----------|
| `"success"` / `"completed"` | 操作成功 | 展示结果 |
| `"multiple_found"` | 搜索到多本匹配书籍（`auto_fill_book_info` 专用） | 展示书籍列表，请用户指定 |
| `"error"` | 操作失败，见 `message` 字段 | 向用户说明原因 |
| `"failed"` | 单本书处理失败（批量操作中） | 汇报具体失败原因 |

常见错误提示：
- `"Authentication required"` — token 配置有误，检查 MCP 连接配置
- `"Permission denied"` — 当前用户无权限操作该书籍
- `"Book not found"` — 书籍 ID 不存在，可先通过 `search_books` 确认
- `"No books found"` — 搜索无结果，建议尝试其他关键词或简繁体转换

---

## 注意事项

1. **无需登录**：MCP token 已通过 mcporter 内嵌在连接地址中，所有工具调用均已自动鉴权。
2. **书籍 ID**：`book_id` 是书库中的唯一整数标识符，可通过 `search_books` 或 `get_books` 获取。
3. **批量操作**：`auto_fill_book_info` 支持传入 ID 数组，适合批量更新，但建议每批不超过 10 本，避免请求超时。
4. **在线数据源**：`auto_fill_book_info` 和 `query_book_metadata` 依赖豆瓣（douban）、百科（baike）等在线源，网络不可用或书籍较冷门时可能无法获取数据。
5. **标签操作**：修改标签时，`update_book_info` 的 `tags` 参数会**替换**原有标签，若只想追加，需先通过 `search_books` 或 `get_books` 获取现有标签再合并后传入。
