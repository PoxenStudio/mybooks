---
name: mybooks
homepage: https://www.mybooks.top
allowed-tools: Bash(python3:*)
metadata: {"clawdbot":{},"openclaw":{"requires":{"bins":["python3"],"env":["MYBOOKS_HOST","MYBOOKS_USER","MYBOOKS_PASSWORD"]}}}
description: "MyBooks是个人书库管理系统，提供电子书及实体书管理，包括存储、分类、搜索和元数据管理功能。你可以帮助用户：查询书库统计信息和阅读统计,搜索/浏览书籍,获取书籍详情,更新书籍元数据（书名、作者、标签、分类、简介等）,自动联网填充书籍信息,发送书籍到邮箱或阅读器设备,上传电子书或通过ISBN添加实体书,管理阅读状态（想读/在读/已读/收藏）,查看作者信息和分类信息,导入第三方阅读App的划线与想法（如微信读书，需配合微信读书 skill 读取原始数据）,以及MiMo TTS有声书功能（配置TTS API、EPUB转有声书、查询转换进度、克隆音色与语音提示词管理，需管理员权限）等"
---

# MyBooks

## Requirements
```bash
# 需要配置以下三个环境变量后方可使用
export MYBOOKS_HOST="http://127.0.0.1:8082"
export MYBOOKS_USER="admin"
export MYBOOKS_PASSWORD="your_password"
export MYBOOKS_SSL_VERIFY="false"   # 如服务器使用自签名证书，设为 false

然后按如下方式执行：
<skill-installation-path>/scripts/mybooks_api.py <tool-name> '<json-args>'
```

> **安全提示**：请勿将凭据写入共享或全局配置文件（如 `~/.openclaw/.env`），以避免凭据被其他 agent 或进程意外读取。建议通过会话级环境变量或专用密钥管理工具传入凭据。

## 通用响应格式与认证方式

### 通用 JSON 响应结构
所有 API 均返回如下格式：
```json
{
  "err": "ok",       // "ok" 表示成功，其他字符串表示错误码
  "msg": "...",      // 可选，人类可读的成功/错误说明
  "data": { }        // 可选，具体响应数据（因接口而异）
}
```

常见错误码：
| `err` 值 | 含义 |
|----------|------|
| `"ok"` | 操作成功 |
| `"user.need_login"` | 未登录或登录态已过期 |
| `"permission"` | 无权限执行该操作 |
| `"params.invalid"` | 请求参数错误 |
| `"params.book.invalid"` | 书籍不存在或 ID 错误 |
| `"task.running"` | 后台任务正在进行中，稍后重试 |
| `"tts.converting"` | TTS 转换任务正在运行 |
| `"tts.no_config"` | 未配置 TTS API |
| `"clone.exists"` | 克隆音色名称已存在 |
| `"clone.not_found"` | 克隆音色不存在 |
| `"clone.too_large"` | 文件超过 7MB 限制 |
| `"clone.invalid_format"` | 仅支持 MP3/WAV 格式 |
| `"prompt.exists"` | 提示词名称已存在 |
| `"prompt.not_found"` | 提示词不存在 |

### 认证方式
- 脚本通过 `MYBOOKS_USER` / `MYBOOKS_PASSWORD` 环境变量自动调用 `/api/user/sign_in` 完成登录
- 服务端通过 **Secure Cookie**（`user_id` + `lt`）维持会话
- 若响应中出现 `err=user.need_login`，脚本会自动重新登录后重试一次；仍失败则报错退出
- **必须**在调用前配置 `MYBOOKS_HOST`、`MYBOOKS_USER`、`MYBOOKS_PASSWORD` 三个环境变量，否则脚本直接报错退出

---

## 工具列表

### `get_user_info` — 用户信息与系统统计

**使用场景**：获取当前登录用户信息，同时返回书库总体统计（书籍数、作者数等）

**参数**：无

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py get_user_info '{}'
```

**响应示例**：
```json
{
  "err": "ok",
  "user": { "is_login": true, "nickname": "管理员", "is_admin": true },
  "sys": { "books": 1280, "authors": 342, "tags": 86, "mtime": "2025-03-01" }
}
```

---

### `library_stats` — 书库统计

**使用场景**：获取书库详细统计，包括电子书/实体书数量及本月新增

**参数**：无

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py library_stats '{}'
```

**响应示例**：
```json
{
  "err": "ok",
  "stats": {
    "total_books": 1280,
    "ebook_count": 1210,
    "physical_count": 70,
    "month_ebook_count": 12,
    "month_physical_count": 3,
    "current_year": 2025,
    "current_month": 3
  }
}
```

---

### `reading_stats` — 阅读统计

**使用场景**：获取当前用户的阅读统计（在读/已读数量、本月数据）及当前在读书单

**参数**：无

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py reading_stats '{}'
```

**响应示例**：
```json
{
  "err": "ok",
  "stats": {
    "total_reading": 5,
    "total_read_done": 42,
    "month_reading": 2,
    "month_read_done": 3
  },
  "current_reading_books": [ /* 书籍对象列表 */ ],
  "month_read_done_books": [ /* 书籍对象列表 */ ]
}
```

---

### `search_books` — 搜索书籍

**使用场景**：
- 按书名或作者名搜索，支持简繁体自动转换
- "有没有余华的书？" / "找一下《三体》"

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `name` | string | ✅ | — | 搜索关键词（书名或作者名） |
| `num` | int | ❌ | 20 | 每页数量 |
| `page` | int | ❌ | 1 | 页码，从 1 开始 |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py search_books '{"name":"三体"}'
```

**响应示例**：
```json
{
  "err": "ok",
  "title": "搜索：三体",
  "total": 3,
  "books": [ /* 书籍对象列表 */ ]
}
```

---

### `search_by_category` — 按分类查询书籍

**使用场景**：查询指定分类下的所有书籍（基于自定义 `#category` 字段）

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `category` | string | ✅ | — | 分类名称，如 "科幻" |
| `num` | int | ❌ | 20 | 每页数量 |
| `page` | int | ❌ | 1 | 页码，从 1 开始 |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py search_by_category '{"category":"科幻"}'
```

---

### `get_book` — 书籍详情

**使用场景**：获取指定书籍的完整信息，包括元数据、可用格式、封面、阅读状态等

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `book_id` | int | ✅ | 书籍 ID |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py get_book '{"book_id":42}'
```

**响应示例**：
```json
{
  "err": "ok",
  "book": {
    "id": 42,
    "title": "活着",
    "authors": ["余华"],
    "tags": ["小说", "中国文学"],
    "publisher": "作家出版社",
    "isbn": "9787506365437",
    "pubdate": "2012-08-01",
    "rating": 9,
    "comments": "《活着》讲述了...",
    "category": "现代文学",
    "available_formats": ["epub", "pdf"],
    "files": [
      {
        "format": "EPUB",
        "size": 1330899,
        "href": "/api/book/42.EPUB"
      }
    ],
    "cover_url": "/get/cover/42",
    "series": "余华作品集",
    "series_index": 1,
    "state": {
      "favorite": 0,
      "wants": 0,
      "read_state": 1
    },
    "tags": ["小说", "中国文学"]
  },
  "kindle_sender": "sender@example.com"
}
```

---

### `edit_book` — 编辑书籍元数据

**使用场景**：
- 手动修改书名、作者、标签、分类等字段
- 修改实体书数量或类型

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `book_id` | int | ✅ | 书籍 ID |
| `title` | string | ❌ | 书名 |
| `authors` | array | ❌ | 作者列表，如 `["余华"]` |
| `tags` | array | ❌ | 标签列表，**替换**原有标签（想追加需先 `get_book` 获取现有标签再合并） |
| `publisher` | string | ❌ | 出版社 |
| `isbn` | string | ❌ | ISBN 编号 |
| `series` | string | ❌ | 系列/丛书名 |
| `series_index` | int | ❌ | 系列中的顺序号 |
| `rating` | number | ❌ | 评分（0–10） |
| `languages` | array | ❌ | 语言代码列表，如 `["zho"]`（中文）、`["eng"]`（英文）、`["zha"]`（繁体中文） |
| `pubdate` | string | ❌ | 出版日期，格式：`"2024-01-15"` / `"2024-01"` / `"2024"` |
| `comments` | string | ❌ | 书籍简介，支持 HTML，请勿将 `<>` 转义为 `&lt;&gt;` |
| `category` | string | ❌ | 自定义分类（最长 80 字符；传 `"清除"` 或 `"clear"` 清空分类） |
| `book_count` | int | ❌ | 实体书数量（需配合 `book_type: 1` 使用） |
| `book_type` | int | ❌ | 书籍类型：`0`=电子书，`1`=实体书 |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py edit_book '{"book_id":42,"tags":["小说","中国文学"],"category":"现代文学"}'
```

**响应示例**：
```json
{ "err": "ok", "msg": "更新成功", "books": [42] }
```

---

### `push_notes` — 导入第三方批注（微信读书等）

**使用场景**：把从其他阅读 App（目前是微信读书）读到的划线/想法，通过服务端全文检索定位到 MyBooks 书库里对应 EPUB 书籍的正文位置，写入这本书的阅读记录。详细方案见 `plan/WeChatReading_Annotation_Import_Plan.md`。

**前提**：目标书籍必须已经在 MyBooks 书库里，且**必须有 EPUB 格式**（定位算法依赖 EPUB 的正文结构，其它格式不支持）。

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `book_id` | int | ✅ | — | 书籍 ID（须为 EPUB 格式） |
| `anchors` | array | ✅ | — | 待导入的批注列表，见下 |
| `anchors[].id` | string | ✅ | — | 来源系统里的稳定 ID（如微信读书的 `bookmarkId`/`reviewId`），用于生成幂等的记录 ID——同样的 `anchors` 重复调用不会重复导入 |
| `anchors[].text` | string | ❌ | — | 划线/引用的原文，用于全文检索定位；不传则视为"无原文锚点"（章节点评/整本书评），会退化为"挂在章节开头"的书签 |
| `anchors[].chapterHint` | string | ❌ | — | 来源系统里的章节标题，`text` 未提供时用于定位章节起始位置 |
| `anchors[].note` | string | ❌ | — | 用户写的想法/点评正文 |
| `anchors[].color` | string | ❌ | `"yellow"` | 高亮颜色 |
| `anchors[].style` | string | ❌ | `"highlight"` | `highlight`/`underline`/`squiggly` |
| `anchors[].createdAt` | int | ❌ | 当前时间 | 来源系统里的创建时间（毫秒时间戳） |
| `anchors[].source` | string | ❌ | `"wxread"` | 来源标记 |
| `on_ambiguous` | string | ❌ | `"error"` | 原文在书里检索到多处命中时的处理：`"error"`=不写入、标记为歧义待复核；`"first_match"`=取第一个命中位置写入 |
| `dry_run` | bool | ❌ | `true` | `true`=只做检索定位、返回预览报告，不写入；`false`=同时写入。**务必先用 `dry_run:true` 看一遍报告、跟用户确认后再用 `dry_run:false` 提交，不要一步到位直接写入** |
| `force` | bool | ❌ | `false` | 重复导入默认会**自动判重**：某条 `anchors[].id` 如果 `text`/`chapterHint` 跟上次导入时一样，直接复用上次的定位结果，不会重新跑检索（响应里对应条目会带 `"reused": true`）。`force:true` 会跳过判重、强制重新定位所有条目——只有书籍文件本身被替换过这种场景才需要，**日常重复同步不要传这个参数**，判重本身就是为了处理"微信读书上有新批注后再次同步"这种情况设计的 |

**再次同步（判重）说明**：微信读书没有增量接口，每次都会拿到全量划线/想法列表。直接把全量列表再传一遍给 `push_notes` 是安全且推荐的做法——服务端会按 `anchors[].id` 匹配上次导入的记录，`text`/`chapterHint` 没变的条目不会重新定位（省时间，也避免同一条批注每次定位到略有不同的位置），只有新增的、或者原文本身变了的条目才会真正重新检索。如果只是想法/评论内容改了但划线原文没变，也会被识别为"位置没变、内容更新"，只更新想法文本，不重新定位。

**执行脚本**：
```bash
# 第一步：预览（默认 dry_run:true），不会写入任何数据
<skill-installation-path>/scripts/mybooks_api.py push_notes '{
  "book_id": 42,
  "anchors": [
    {"id": "wx-bm-1001", "text": "他手里拿着两大块磁铁", "note": "开篇的魔幻现实主义笔法"},
    {"id": "wx-review-2001", "chapterHint": "第一章"}
  ]
}'

# 第二步：跟用户确认预览报告无误后，正式写入
<skill-installation-path>/scripts/mybooks_api.py push_notes '{
  "book_id": 42,
  "anchors": [
    {"id": "wx-bm-1001", "text": "他手里拿着两大块磁铁", "note": "开篇的魔幻现实主义笔法"},
    {"id": "wx-review-2001", "chapterHint": "第一章"}
  ],
  "dry_run": false
}'
```

**响应示例**（预览，`dry_run:true`）：
```json
{
  "err": "ok",
  "book_id": 42,
  "book_hash": "cloud-42-epub",
  "dry_run": true,
  "results": [
    { "id": "wx-bm-1001", "status": "ok", "cfi": "epubcfi(/6/10!/4/4/2,/19:17,/21:4)", "matchCount": 1 },
    { "id": "wx-review-2001", "status": "ok", "cfi": "epubcfi(/6/8!/4)", "degraded": "chapter_start" }
  ]
}
```

**响应示例**（提交，`dry_run:false`，额外带 `pushed`）：
```json
{
  "err": "ok",
  "book_id": 42,
  "book_hash": "cloud-42-epub",
  "dry_run": false,
  "results": [ /* 同上 */ ],
  "pushed": { "notes": [ /* 写入后的最终记录，字段与 GET /api/sync 一致 */ ] }
}
```

**`results[].status` 取值**：
| 值 | 含义 | 建议处理 |
|----|------|----------|
| `"ok"` | 定位成功，`cfi` 有值 | 展示给用户确认；`degraded:"chapter_start"` 表示这是退化的章节级书签，不是精确定位，需要提示用户区分 |
| `"no_match"` | 原文在书里没有检索到 | 大概率两边不是同一版本的书，或原文被来源系统二次编辑过；列入失败清单，不会写入 |
| `"ambiguous"` | 原文命中了多处（`matchCount` > 1），且 `on_ambiguous="error"` | 列入歧义清单，需要人工复核；不会写入 |
| `"error"` | 该条内部处理出错（如 CFI 生成失败） | 列入失败清单，不会写入 |

**常见错误**：
| `err` 值 | 含义 |
|----------|------|
| `"params.book.invalid"` | 书籍不存在 |
| `"book.no_epub"` | 书籍没有 EPUB 格式，或找不到 EPUB 文件 |
| `"sync.import.failed"` | 服务端批注定位流程整体失败（如 CFI 子进程异常）——不同于单条 `status:"error"`，这是整批请求都没有结果 |
| `"sync.disabled"` | 服务端数据同步功能未启用 |

---

### `get_notes` — 查询书籍批注

**使用场景**：查看某本书已有的划线/批注/书签（通过 `GET /api/sync` 实现，`type=notes`）。

- "这本书我都划了哪些线？" / "看看《活着》的批注"
- 确认 `push_notes` 导入结果，或在 `clear_imported_notes` 前先看一眼现有批注

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `book_id` | int | ❌ | — | 书籍 ID；与 `title` 二选一，优先生效 |
| `title` | string | ❌ | — | 书名；不传 `book_id` 时用于搜索定位书籍，仅精确匹配到唯一一本书才会继续查询——命中多本时返回 `candidates` 列表，需要调用方明确选择后改传 `book_id` |
| `own` | int | ❌ | `1` | `1`=只返回当前用户自己的批注；`0`=额外并入其他用户在这本书上共享的批注（受服务端 `ENABLE_SHARED_NOTES` 开关约束） |

**执行脚本**：
```bash
# 按 book_id 查询自己的批注
<skill-installation-path>/scripts/mybooks_api.py get_notes '{"book_id":42}'

# 按书名查询，并包含其他用户共享的批注
<skill-installation-path>/scripts/mybooks_api.py get_notes '{"title":"活着","own":0}'
```

**响应示例**：
```json
{
  "err": "ok",
  "book_id": 42,
  "book_hash": "cloud-42-epub",
  "books": null,
  "configs": null,
  "notes": [
    {
      "id": "wxread-wx-bm-1001",
      "book_hash": "cloud-42-epub",
      "type": "annotation",
      "cfi": "epubcfi(/6/10!/4/4/2,/19:17,/21:4)",
      "text": "他手里拿着两大块磁铁",
      "note": "开篇的魔幻现实主义笔法",
      "style": "highlight",
      "color": "yellow",
      "updated_at": 1755600000000,
      "deleted_at": null
    }
  ]
}
```
**`notes[]` 每条记录的字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 记录唯一 ID；`push_notes` 导入的批注固定带 `wxread-` 前缀 |
| `book_hash` | string | 所属书籍的 hash（云端书籍固定为 `cloud-<book_id>-epub`） |
| `type` | string | `"bookmark"`（书签）/ `"annotation"`（划线+想法）/ `"excerpt"`（摘录） |
| `cfi` | string | 该批注在 EPUB 正文里的定位（canonical CFI） |
| `text` | string | 划线/摘录的原文，书签类可能为空 |
| `note` | string | 用户写的想法/点评正文 |
| `style` | string | `"highlight"` / `"underline"` / `"squiggly"` |
| `color` | string | 高亮颜色，如 `"yellow"`，也可能是十六进制色值 |
| `global` | bool | 可选；为 `true` 表示对本章节内该 `text` 的所有出现位置生效 |
| `page` | number | 可选；分页/固定排版格式下的页码 |
| `updated_at` | number | 最近一次更新的毫秒时间戳，用于判断是否新增/变更 |
| `deleted_at` | number/null | 墓碑时间戳；非 `null` 表示该批注已被删除，仍会出现在结果里但应视为已删除 |

按书名查询时命中多本书会返回：
```json
{ "status": "error", "message": "Multiple books matched this title; specify book_id", "candidates": [ {"id": 42, "title": "活着", "authors": ["余华"]}, ... ] }
```

**常见错误**：
| `err` 值 | 含义 |
|----------|------|
| `"sync.disabled"` | 服务端数据同步功能未启用 |

---

### `clear_imported_notes` — 清空某本书已导入的批注（重置用，非日常操作）

**使用场景**：撤销/重置某本书通过 `push_notes` 导入的全部批注——比如导入用错了数据、或者 `on_ambiguous:"first_match"` 选错了位置，用户明确要求"重新导入一遍"。**不要**把这个当成处理"再次同步"的常规手段——`push_notes` 本身已经会自动判重（见上），日常重复同步应该直接再调一次 `push_notes`，不需要先清空。

**范围**：只会清除当前登录用户通过 `push_notes` 导入的批注（`id` 带 `wxread-` 前缀的），不影响这本书上其他人的批注，也不影响用户自己在 MyReader 里手动做的批注。

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `book_id` | int | ✅ | 书籍 ID |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py clear_imported_notes '{"book_id":42}'
```

**响应示例**：
```json
{ "err": "ok", "book_id": 42, "book_hash": "cloud-42-epub", "cleared": 5 }
```

**常见错误**：
| `err` 值 | 含义 |
|----------|------|
| `"params.book.invalid"` | 书籍不存在 |
| `"sync.disabled"` | 服务端数据同步功能未启用 |

---

### `book_fill` — 自动联网填充书籍信息

**使用场景**：
- "帮我更新《XX》的封面和简介"
- "书库里有很多书信息不完整，帮我补全"
- 批量补全多本书的封面、简介、出版社、出版日期、标签等

**权限**：需要管理员权限

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `idlist` | array 或 `"all"` | ✅ | 书籍 ID 数组，或 `"all"` 表示全库处理 |

**注意**：任务在后台异步执行，调用后立即返回；书名**默认保留原值不修改**（防止错误覆盖）

**执行脚本**：
```bash
# 更新单本书
<skill-installation-path>/scripts/mybooks_api.py book_fill '{"idlist":[42]}'

# 批量更新
<skill-installation-path>/scripts/mybooks_api.py book_fill '{"idlist":[42,43,44]}'
```

**响应示例**：
```json
{ "err": "ok", "msg": "任务启动成功！请耐心等待，稍后再来刷新页面" }
```

---

### `save_meta_to_file` — 将元数据保存到电子书文件

**使用场景**：
- 在书库中修改了书名/作者/简介/标签等元数据后，希望这些信息也写入电子书文件本身（而不只是存在书库数据库里）
- 仅支持 epub / azw3 / pdf 格式；其余格式（如 mobi、txt）不受影响

**权限**：需要登录，且为管理员或该书籍的所有者

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `book_id` | int | ✅ | 书籍 ID |
| `fmt` | string | ❌ | 仅同步指定格式（`epub`/`azw3`/`pdf`），省略则同步所有支持的格式 |

**执行脚本**：
```bash
# 同步所有支持的格式
<skill-installation-path>/scripts/mybooks_api.py save_meta_to_file '{"book_id":42}'

# 仅同步 epub
<skill-installation-path>/scripts/mybooks_api.py save_meta_to_file '{"book_id":42,"fmt":"epub"}'
```

**响应示例**：
```json
{ "err": "ok", "msg": "成功将元数据同步到文件：EPUB", "success_formats": ["EPUB"], "failed_formats": [] }
```

**常见错误**：
| `err` 值 | 含义 |
|----------|------|
| `"user.no_permission"` | 非管理员或非书籍所有者 |
| `"book.not_found"` | 书籍不存在 |
| `"format.not_supported"` | 书籍没有 epub/azw3/pdf 格式（或没有指定的 `fmt`） |
| `"book.meta.not_found"` | 无法获取书籍元数据 |
| `"save.failed"` | 所有格式均同步失败（返回中含 `failed_formats`） |

---

### `mailto` — 发送书籍到邮箱

**使用场景**：将书籍以附件形式发送到指定邮箱（如 Kindle 邮箱）

**格式优先级**：epub > azw3 > pdf > mobi > txt（取首个存在的格式）

**权限**：需要登录，且账号需有推送权限（`can_push`）

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `book_id` | int | ✅ | 书籍 ID |
| `email` | string | ✅ | 目标邮箱地址（可以是 Kindle 邮箱） |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py mailto '{"book_id":42,"email":"user@kindle.com"}'
```

**响应示例**：
```json
{ "err": "ok", "msg": "后台正在推送，稍后可以刷新页面，在通知消息中查看结果。" }
```

---

### `send_to_device` — 发送书籍到阅读器设备

**使用场景**：通过 WiFi 将书籍直接推送到阅读器设备（仅支持当前网络内的临时设备）

**支持的设备类型（`device_type`）**：

| 类型 | 设备 | 传输方式 | `device_url` 说明 |
|------|------|----------|-------------------|
| `kindle` | Kindle 系列 | 邮件发送 | 不需填写，改用 `mailbox` 参数 |
| `duokan` | 多看阅读器 | HTTP WiFi 上传 | 设备局域网 IP，如 `192.168.1.100` |
| `ireader` | 掌阅 iReader | HTTP WiFi 上传 | 设备局域网 IP |
| `hanwang` | 汉王电纸书 | HTTP WiFi 上传 | 设备局域网 IP |
| `boox` | 文石 BOOX | HTTP WiFi 上传 | 设备局域网 IP |
| `dangdang` | 当当阅读器 | HTTP WiFi 上传 | 设备局域网 IP |

**WiFi 传输格式优先级**：epub > azw3 > pdf > txt

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `book_id` | int | ✅ | 书籍 ID |
| `device_type` | string | ✅ | 设备类型（见上表） |
| `device_url` | string | kindle 以外必填 | 设备局域网 IP 或地址（如 `"192.168.1.100"` 或 `"http://192.168.1.100:80"`） |
| `mailbox` | string | kindle 时必填 | Kindle 邮箱地址 |

**执行脚本**：
```bash
# 发送到多看设备
<skill-installation-path>/scripts/mybooks_api.py send_to_device \
  '{"book_id":42,"device_type":"duokan","device_url":"192.168.1.100"}'

# 发送到 Kindle（通过邮件）
<skill-installation-path>/scripts/mybooks_api.py send_to_device \
  '{"book_id":42,"device_type":"kindle","mailbox":"mykindle@kindle.cn"}'
```

**响应示例**：
```json
{ "err": "ok", "msg": "书籍发送成功" }
```

---

### `categories` — 查看分类信息

**使用场景**：获取当前书库中所有自定义分类及各分类下的书籍数量

**参数**：无

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py categories '{}'
```

**响应示例**：
```json
{
  "err": "ok",
  "categories": [
    { "name": "现代文学", "count": 128 },
    { "name": "科幻", "count": 56 }
  ]
}
```

---

### `list_authors` — 查看作者列表

**使用场景**：获取所有有在库书籍的作者及其书籍数量

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `show` | string | ❌ | 传 `"all"` 显示全部，否则返回前 N 条 |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py list_authors '{}'
```

**响应示例**：
```json
{
  "err": "ok",
  "meta": "author",
  "title": "全部作者",
  "items": [
    { "name": "余华", "count": 5 },
    { "name": "刘慈欣", "count": 8 }
  ],
  "total": 342
}
```

---

### `get_author_books` — 查询作者的在库书籍

**使用场景**：获取指定作者在书库中的所有书籍

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `author_name` | string | ✅ | — | 作者名 |
| `num` | int | ❌ | 20 | 每页数量 |
| `page` | int | ❌ | 1 | 页码，从 1 开始 |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py get_author_books '{"author_name":"余华"}'
```

---

### `book_upload` — 上传电子书

**使用场景**：上传本地电子书文件到书库，支持 epub/mobi/azw/azw3/pdf/txt/lrf/rtf/djvu/docx 等格式

**权限**：需要登录，且账号需有上传权限（`can_upload`）

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file_path` | string | ✅ | 本地文件的绝对路径 |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py book_upload '{"file_path":"/path/to/book.epub"}'
```

**响应示例**：
```json
{ "err": "ok", "book_id": 123 }
```

---

### `book_add_by_isbn` — 通过 ISBN 添加实体书

**使用场景**：
- 扫描实体书的 ISBN 条码后，将书入库
- 若该 ISBN 书籍已存在，则自动将实体书数量 +1

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `isbn` | string | ✅ | ISBN 编号，如 `"9787020024759"` |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py book_add_by_isbn '{"isbn":"9787020024759"}'
```

**响应示例**（新增）：
```json
{ "err": "ok", "msg": "图书添加成功", "book_id": 456 }
```

**响应示例**（已存在，更新数量）：
```json
{ "err": "ok", "msg": "实体书数量已更新，当前数量：2", "book_id": 123 }
```

---

### `wants` — 标记/取消想读

**使用场景**：将书籍加入/移出"想读（待读）"清单

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `book_id` | int | ✅ | — | 书籍 ID |
| `wants` | bool | ❌ | `true` | `true`=标记想读，`false`=取消 |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py wants '{"book_id":42}'
```

---

### `list_wants` — 想读清单

**使用场景**：获取当前用户的"想读（待读）"书籍列表

**参数**：无

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py list_wants '{}'
```

---

### `favorite` — 收藏/取消收藏

**使用场景**：收藏或取消收藏指定书籍

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `book_id` | int | ✅ | — | 书籍 ID |
| `favorite` | bool | ❌ | `true` | `true`=收藏，`false`=取消收藏 |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py favorite '{"book_id":42}'
```

---

### `list_favorites` — 收藏列表

**使用场景**：获取当前用户的所有收藏书籍

**参数**：无

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py list_favorites '{}'
```

---

### `reading` — 设置阅读状态

**使用场景**：标记某本书的阅读状态（未读/在读/已读完）

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `book_id` | int | ✅ | 书籍 ID |
| `read_state` | int | ✅ | 阅读状态：`0`=未读，`1`=在读，`2`=已读完 |

**执行脚本**：
```bash
# 标记为在读
<skill-installation-path>/scripts/mybooks_api.py reading '{"book_id":42,"read_state":1}'
```

---

### `list_reading` — 在读书单

**使用场景**：获取当前用户的"正在阅读"书籍列表

**参数**：无

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py list_reading '{}'
```

---

### `read_done` — 标记已读完

**使用场景**：快捷将某本书标记为已读完（即 `reading` 工具中 `read_state=2` 的简化版）

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `book_id` | int | ✅ | 书籍 ID |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py read_done '{"book_id":42}'
```

---

### `list_read_done` — 已读清单

**使用场景**：获取当前用户的"已读完"书籍列表

**参数**：无

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py list_read_done '{}'
```

---

## TTS 有声书工具列表（MiMo TTS，需管理员权限）

> 将 EPUB 电子书转换为有声书。所有 TTS 接口均需要**管理员权限**。

### `tts_save_config` — 保存 TTS API 配置

**使用场景**：配置 TTS API 的连接参数（API URL、模型、密钥、类型等），保存后服务端加密存储

**权限**：管理员

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `api_url` | string | ✅ | API 地址，如 `https://api.xiaomimimo.com/v1/chat/completions` |
| `model_name` | string | ✅ | 模型 ID，MiMo TTS 类型固定为 `mimo-v2.5-tts` |
| `api_type` | string | ✅ | API 类型：`chat_completions`（MiMo TTS）/ `audio_speech`（OpenAI 兼容）/ `custom` |
| `api_key` | string | ✅ | API 密钥 |
| `auth_type` | string | ❌ | 认证类型：`bearer`（默认）/ `basic` / `custom` |
| `voice_name` | string | ❌ | 预置音色 ID（`api_type=chat_completions` 且 `voiceType=preset` 时）或 `audio_speech` 的音色名 |
| `voice_desc` | string | ❌ | 自定义音色描述（`voiceType=custom` 时） |
| `clone_voice` | string | ❌ | 克隆音色名称（`voiceType=clone` 时） |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py tts_save_config '{"api_url":"https://api.xiaomimimo.com/v1/chat/completions","model_name":"mimo-v2.5-tts","api_type":"chat_completions","api_key":"sk-xxx","voice_name":"mimo_default"}'
```

**响应示例**：
```json
{
  "err": "ok",
  "msg": "配置已保存"
}
```

---

### `tts_test_connection` — 测试 API 连接

**使用场景**：使用当前保存的配置发送一次测试请求，验证 API Key 和端点是否可用

**权限**：管理员

**参数**：无（使用已保存的配置）

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py tts_test_connection '{}'
```

**响应示例**：
```json
{
  "err": "ok",
  "msg": "连接成功"
}
```

**常见错误**：
| `err` 值 | 含义 |
|----------|------|
| `"tts.no_config"` | 未保存配置，请先调用 `tts_save_config` |
| `"tts.connection_failed"` | 无法连接到 API 服务器 |
| `"tts.invalid_key"` | API Key 无效 |

---

### `tts_convert` — 开始 EPUB 转有声书

**使用场景**：将指定 EPUB 电子书转换为有声书，后台逐章合成 WAV 音频

**权限**：管理员

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `book_id` | int | ✅ | 书籍 ID |
| `api_url` | string | ✅ | API 地址 |
| `model_name` | string | ✅ | 模型 ID |
| `api_type` | string | ✅ | API 类型：`chat_completions` / `audio_speech` / `custom` |
| `api_key` | string | ✅ | API 密钥 |
| `auth_type` | string | ❌ | 认证类型（默认 `bearer`） |
| `voice_name` | string | ❌ | 预置音色 ID 或 `audio_speech` 音色名 |
| `voice_desc` | string | ❌ | 自定义音色描述 |
| `clone_voice` | string | ❌ | 克隆音色名称 |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py tts_convert '{"book_id":42,"api_url":"https://api.xiaomimimo.com/v1/chat/completions","model_name":"mimo-v2.5-tts","api_type":"chat_completions","api_key":"sk-xxx","voice_name":"mimo_default"}'
```

**响应示例**：
```json
{
  "err": "ok",
  "msg": "转换任务已启动"
}
```

**常见错误**：
| `err` 值 | 含义 |
|----------|------|
| `"params.book.invalid"` | 书籍不存在 |
| `"tts.converting"` | 已有转换任务在运行 |
| `"book.no_epub"` | 书籍没有 EPUB 格式 |

---

### `tts_progress` — 查询转换进度

**使用场景**：查询当前 TTS 转换任务的进度、阶段和章节信息

**权限**：管理员

**参数**：无

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py tts_progress '{}'
```

**响应示例**：
```json
{
  "err": "ok",
  "status": "running",
  "progress": 35,
  "stage": "converting",
  "current_chapter": 7,
  "total_chapters": 20,
  "current_title": "第七章 归途",
  "book_id": 42
}
```

**status 值**：
| 值 | 含义 |
|----|------|
| `"idle"` | 无任务运行 |
| `"running"` | 转换进行中 |
| `"completed"` | 转换已完成 |
| `"failed"` | 转换失败 |

---

### `tts_clone_upload` — 上传克隆音色

**使用场景**：上传 MP3/WAV 音频样本作为克隆音色，上传后自动切换到 `mimo-v2.5-tts-voiceclone` 模型

**权限**：管理员

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `voice_name` | string | ✅ | 克隆音色名称（如"旁白"、"男主"） |
| `file_path` | string | ✅ | 本地音频文件的绝对路径（MP3/WAV，≤7MB） |

**限制**：
- 格式：仅支持 `.mp3` 和 `.wav`
- 大小：原始文件 ≤ 7MB（Base64 编码后约 9.3MB，MiMo 官方限制 Base64 ≤ 10MB）

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py tts_clone_upload '{"voice_name":"旁白","file_path":"/path/to/sample.mp3"}'
```

**响应示例**：
```json
{
  "err": "ok",
  "msg": "克隆音色上传成功",
  "data": { "name": "旁白", "ext": "mp3", "size": 1048576 }
}
```

**常见错误**：
| `err` 值 | 含义 |
|----------|------|
| `"clone.exists"` | 音色名称已存在 |
| `"clone.too_large"` | 文件超过 7MB |
| `"clone.invalid_format"` | 格式不支持 |

---

### `tts_clone_list` — 克隆音色列表

**使用场景**：获取所有已上传的克隆音色列表

**权限**：管理员

**参数**：无

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py tts_clone_list '{}'
```

**响应示例**：
```json
{
  "err": "ok",
  "clones": [
    { "name": "旁白", "ext": "mp3", "size": 1048576 },
    { "name": "男主", "ext": "wav", "size": 2097152 }
  ]
}
```

---

### `tts_clone_delete` — 删除克隆音色

**使用场景**：删除指定的克隆音色

**权限**：管理员

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `voice_name` | string | ✅ | 要删除的克隆音色名称 |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py tts_clone_delete '{"voice_name":"旁白"}'
```

**响应示例**：
```json
{
  "err": "ok",
  "msg": "克隆音色已删除"
}
```

---

### `tts_clone_audio` — 下载克隆音频

**使用场景**：下载/试听指定的克隆音色原始音频文件（返回二进制 WAV 数据）

**权限**：管理员

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `voice_name` | string | ✅ | 克隆音色名称 |
| `save_to` | string | ❌ | 保存到本地路径（不传则返回 base64） |

**执行脚本**：
```bash
# 保存到文件
<skill-installation-path>/scripts/mybooks_api.py tts_clone_audio '{"voice_name":"旁白","save_to":"/tmp/clone_preview.wav"}'

# 返回 base64（小文件）
<skill-installation-path>/scripts/mybooks_api.py tts_clone_audio '{"voice_name":"旁白"}'
```

**响应示例**（保存到文件）：
```json
{
  "err": "ok",
  "msg": "音频已保存",
  "path": "/tmp/clone_preview.wav",
  "size": 1048576
}
```

---

### `tts_prompt_list` — 提示词列表

**使用场景**：获取所有已保存的自定义语音提示词

**权限**：管理员

**参数**：无

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py tts_prompt_list '{}'
```

**响应示例**：
```json
{
  "err": "ok",
  "prompts": [
    { "name": "温柔女声", "desc": "温柔细腻的语调，语速偏慢，咬字清晰" },
    { "name": "沉稳男声", "desc": "沉稳厚重的语调，语速适中偏低" }
  ]
}
```

---

### `tts_prompt_save` — 保存提示词

**使用场景**：将自定义音色描述保存为提示词（同名覆盖），存储于服务端 `voice_prompts.json`

**权限**：管理员

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 提示词名称 |
| `desc` | string | ✅ | 音色描述（自然语言描述语音特征） |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py tts_prompt_save '{"name":"温柔女声","desc":"温柔细腻的语调，语速偏慢，咬字清晰，富有亲和力"}'
```

**响应示例**：
```json
{
  "err": "ok",
  "msg": "提示词已保存"
}
```

---

### `tts_prompt_delete` — 删除提示词

**使用场景**：删除指定的语音提示词

**权限**：管理员

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 要删除的提示词名称 |

**执行脚本**：
```bash
<skill-installation-path>/scripts/mybooks_api.py tts_prompt_delete '{"name":"温柔女声"}'
```

**响应示例**：
```json
{
  "err": "ok",
  "msg": "提示词已删除"
}
```

---

## 使用场景决策指南

```
用户请求
│
├─ "书库有多少书？" / "统计书库"
│   → library_stats（详细分类统计）
│   → 或 get_user_info（快速总数）
│
├─ "我读了多少书？" / "阅读情况"
│   → reading_stats
│
├─ "找一下 XX 书" / "搜索 YY 作者"
│   → search_books（按关键词）
│
├─ "找 XX 分类下的书"
│   → search_by_category
│
├─ "查看书籍详情"
│   → get_book
│
├─ "这本书我都划了哪些线？" / "看看《XX》的批注/书签"
│   → get_notes（传 book_id 或 title；own:0 可连他人共享的批注一起看）
│
├─ "更新/补全《XX》的封面、简介、标签信息"（自动从网上获取）
│   → book_fill（需要管理员权限，传入 book_id 数组）
│
├─ "手动修改《XX》的标签/分类/书名等字段"
│   → 先 search_books 确认 book_id → 再 edit_book
│
├─ "把修改后的元数据也写入电子书文件本身" / "同步元数据到文件"
│   → save_meta_to_file（仅 epub/azw3/pdf，需管理员或书籍所有者权限）
│
├─ "把我在微信读书上的划线/想法导入这本书" / "导入第三方批注"
│   → 先确认目标书是 EPUB 格式，再用 push_notes（先 dry_run:true 预览，用户确认后再 dry_run:false 提交）
│   → 微信读书上有新批注后再次同步：直接把全量列表再传一遍 push_notes 即可，会自动判重，不用先清空
│
├─ "撤销/重置这本书导入的批注" / "刚才导入错了，重新来一遍"
│   → clear_imported_notes（只影响当前用户自己通过 push_notes 导入的批注），然后重新调 push_notes
│

├─ "把书发给我的 Kindle / 发到邮箱"
│   → mailto（发邮箱附件）
│
├─ "把书发到我的多看/掌阅/BOOX 设备"
│   → send_to_device（需设备在同一局域网并开启 WiFi 接收）
│
├─ "上传这本书" / "添加实体书"
│   → book_upload（电子书文件）
│   → book_add_by_isbn（实体书 ISBN）
│
├─ "这本书想读" / "加入待读清单"
│   → wants
│
├─ "收藏这本书"
│   → favorite
│
├─ "标记正在读" / "标记已读完"
│   → reading（read_state: 1 或 2）
│   → read_done（快捷标记已读完）
│
└─ "有哪些分类？" / "XX 作者有哪些书？"
    → categories / list_authors / get_author_books
```

### TTS 场景

```
用户请求
│
├─ "配置 TTS API" / "设置 MiMo API Key"
│   → tts_save_config
│
├─ "测试 API 能不能用" / "连接正常吗"
│   → tts_test_connection
│
├─ "把这本书转成有声书" / "开始转换"
│   → tts_convert（需先有配置或直接传参）
│
├─ "转换到哪了" / "进度怎么样"
│   → tts_progress
│
├─ "上传克隆音色" / "我想用自己的声音"
│   → tts_clone_upload
│
├─ "有哪些克隆音色" / "看看上传的音色"
│   → tts_clone_list
│
├─ "删除克隆音色" / "不要这个音色了"
│   → tts_clone_delete
│
├─ "试听克隆音色" / "下载克隆音频"
│   → tts_clone_audio
│
├─ "有哪些提示词" / "保存的音色描述"
│   → tts_prompt_list
│
├─ "保存这个音色描述" / "存一个提示词"
│   → tts_prompt_save
│
└─ "删除提示词" / "不要这个描述了"
    → tts_prompt_delete
```

---

## 预置音色参考

MiMo TTS 类型（`api_type=chat_completions`）内置 9 个预置音色：

| ID | 名称 | 语言 | 性别 |
|----|------|------|------|
| `mimo_default` | MiMo-默认 | 中文 | 女 |
| `冰糖` | 冰糖 | 中文 | 女 |
| `茉莉` | 茉莉 | 中文 | 女 |
| `苏打` | 苏打 | 中文 | 男 |
| `白桦` | 白桦 | 中文 | 男 |
| `Mia` | Mia | 英文 | 女 |
| `Chloe` | Chloe | 英文 | 女 |
| `Milo` | Milo | 英文 | 男 |
| `Dean` | Dean | 英文 | 男 |

---

## 错误处理规范

| `err` 值 | 含义 | 建议处理 |
|----------|------|----------|
| `"ok"` | 操作成功 | 展示结果 |
| `"user.need_login"` | 未登录或登录态过期 | 脚本自动重登录，仍失败则检查环境变量 |
| `"permission"` | 无权限 | 说明当前账号权限不足，需管理员协助 |
| `"params.book.invalid"` | 书籍不存在 | 建议用 `search_books` 重新确认 book_id |
| `"book.no_epub"` | 书籍没有 EPUB 格式（或找不到 EPUB 文件） | `push_notes` 专属：提示用户该书无法导入批注，仅支持 EPUB |
| `"sync.import.failed"` | `push_notes` 批注定位流程整体失败 | 与单条 `results[].status:"error"` 不同，是整批请求都没有结果，稍后重试或检查书籍文件是否损坏 |
| `"task.running"` | 后台有任务在运行 | 等待当前任务完成后重试 |
| `"book.notfound"` | ISBN 对应的书籍未在网上找到 | 换其他数据源或手动添加 |
| `"connection.failed"` | 无法连接到设备 | 检查设备 IP 和 WiFi 接收功能是否开启 |
| `"format.not_supported"` | 书籍没有 epub/azw3/pdf 格式 | 提示用户该书无法同步元数据到文件 |
| `"tts.converting"` | TTS 转换任务进行中 | 等待完成后重试 |
| `"tts.no_config"` | 未配置 TTS API | 先调用 `tts_save_config` |
| `"clone.too_large"` | 克隆音色文件超限 | 提示用户裁剪音频至 7MB 内 |
| `"clone.invalid_format"` | 克隆音色格式不支持 | 仅支持 MP3/WAV |
| `"clone.exists"` | 克隆音色名称重复 | 换名或先删除旧的 |

---

## 注意事项

1. **认证**：每次调用前脚本会自动登录，无需手动管理 Cookie；若未配置环境变量，脚本立即报错退出。
2. **book_id**：书籍的唯一整数标识符，可通过 `search_books` 或 `get_book` 获取。
3. **book_fill 异步性**：联网填充任务在后台运行，调用后立即返回；可通过 `get_book` 查看更新结果。
4. **edit_book 标签替换**：`tags` 参数会**完整替换**原有标签，如需追加请先 `get_book` 获取现有标签再合并传入。
5. **send_to_device 限制**：仅支持本地临时推送，不支持通过服务器中转到远程设备。
6. **在线数据源**：`book_fill` 依赖豆瓣（douban）、百科（baike）等在线源，网络不可用或书籍较冷门时可能无结果。
7. **批量 book_fill**：建议每批不超过 10 本，避免触发后台任务冲突（`task.running` 错误）。
8. **TTS 管理员权限**：所有 TTS 接口均需要管理员权限，普通用户无法使用。
9. **TTS 异步转换**：`tts_convert` 启动后台任务后立即返回，需用 `tts_progress` 轮询进度。
10. **TTS 断点续传**：重复转换同一本书时，自动跳过已存在的 WAV 文件（≥44 字节），中断后可继续。
11. **TTS 音频输出**：转换完成后，音频输出到 `/audio/{book_id}` 页面播放，也可通过 Web 界面访问。
12. **TTS 克隆音色限制**：MP3/WAV ≤ 7MB；上传后自动切换 `mimo-v2.5-tts-voiceclone` 模型。
13. **TTS 提示词存储**：提示词保存在服务端 `voice_prompts.json`，跨浏览器共享，不依赖本地存储。
14. **TTS API Key 加密**：API Key 经 PBKDF2-SHA256 + 流加密保存，密钥文件权限 0o600。
15. **TTS 模型锁定**：MiMo TTS 类型下模型 ID 固定为 `mimo-v2.5-tts`，不可修改；`audio_speech` 和 `custom` 类型可自由修改。