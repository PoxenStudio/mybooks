# PoxenStudio/Talebook Python 后台 API 接口文档 (中文版)

本文档详细描述了 Talebook Python 后台 (`webserver`) 提供的 RESTful API 接口。这些接口被前端应用 (`app`) 调用以实现各种功能。

## 基础 URL

所有 API 接口均以 `/api` 为前缀。例如，用户登录的接口是 `/api/user/sign_in`。

## 认证方式

大部分涉及用户操作的接口（如上传书籍、编辑元数据、访问用户历史）都需要认证。认证通常通过登录成功后设置的安全 Cookie (`user_id`, `lt`) 来实现。部分接口（如通过 OPDS 下载书籍）也支持 Basic Authentication。

管理员接口需要用户已登录**并且**拥有管理员权限。

## 通用响应格式

除非另有说明，JSON API 的响应均遵循以下结构：
```json
{
  "err": "ok", // 或错误代码字符串
  "msg": "成功信息或错误描述", // 可选
  "data": { /* ... 具体响应数据 ... */ } // 可选
}
```
*   `err`: `"ok"` 表示请求成功。任何其他字符串均表示发生错误。
*   `msg`: 人类可读的信息，常用于错误提示或简单状态更新。
*   `data`: 包含主要的响应数据，其结构因接口而异。

---
## 用户管理

### `/api/user/info`
* **方法**: `GET`
* **描述**: 获取系统信息和当前用户信息。
* **参数**:
    * `detail` (string, 可选): 如果提供，则包含详细的用户历史记录。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "cdn": "http://localhost:8083",
      "sys": {
        "books": 150,
        "tags": 45,
        "authors": 60,
        "mtime": "2023-10-26",
        // ... 其他系统信息
      },
      "user": {
        "is_login": true,
        "nickname": "张三",
        "avatar": "http://localhost:8083/avatar/1.png",
        "extra": {
          // ... 用户额外信息，如历史记录（如果detail=1）
        }
        // ... 其他用户信息
      }
    }
    ```

### `/api/user/messages`
* **方法**: `GET`
* **描述**: 获取当前用户的未读消息。
* **认证**: 需要
* **响应示例**:
    ```json
    {
      "err": "ok",
      "messages": [
        {
          "id": 10,
          "title": "书籍推送成功",
          "status": "success",
          "create_time": "2023-10-26 10:00:00",
          "data": {}
        }
      ]
    }
    ```

### `/api/user/messages`
* **方法**: `POST`
* **描述**: 将指定消息标记为已读。
* **认证**: 需要
* **请求体**:
    ```json
    {
      "id": 10 // 消息ID
    }
    ```
* **响应示例**:
    ```json
    {
      "err": "ok"
    }
    ```

### `/api/user/sign_in`
* **方法**: `POST`
* **描述**: 用户登录认证。
* **请求体**:
    ```json
    {
      "username": "user123",
      "password": "password123"
    }
    ```
* **响应示例 (成功)**:
    ```json
    {
      "err": "ok",
      "msg": "ok"
    }
    ```
* **响应示例 (失败)**:
    ```json
    {
      "err": "params.invalid",
      "msg": "用户名或密码错误"
    }
    ```

### `/api/user/sign_up`
* **方法**: `POST`
* **描述**: 用户注册新账号。
* **请求体**:
    ```json
    {
      "email": "user@example.com",
      "nickname": "用户昵称",
      "username": "user123",
      "password": "password123"
    }
    ```
* **响应示例**:
    ```json
    {
      "err": "ok"
    }
    ```

### `/api/user/sign_out`
* **方法**: `GET`
* **描述**: 用户退出登录。
* **认证**: 需要
* **响应示例**:
    ```json
    {
      "err": "ok",
      "msg": "你已成功退出登录。"
    }
    ```

### `/api/user/update`
* **方法**: `POST`
* **描述**: 更新用户个人资料（昵称、密码、Kindle邮箱）。
* **认证**: 需要
* **请求体**:
    ```json
    {
      "nickname": "新昵称",
      "password0": "current_password", // 修改密码时必需
      "password1": "new_password",     // 修改密码时必需
      "password2": "new_password",     // 修改密码时必需
      "kindle_email": "kindle@example.com"
    }
    ```
* **响应示例**:
    ```json
    {
      "err": "ok"
    }
    ```

### `/api/user/reset`
* **方法**: `POST`
* **描述**: 请求重置密码。系统会将新密码发送到用户邮箱。
* **请求体**:
    ```json
    {
      "email": "user@example.com",
      "username": "user123"
    }
    ```
* **响应示例**:
    ```json
    {
      "err": "ok"
    }
    ```

### `/api/user/avatar`
* **方法**: `POST`
* **描述**: 上传用户头像。
* **认证**: 需要
* **请求体**: `multipart/form-data`，包含一个名为 `avatar` 的文件字段。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "avatar_url": "http://localhost:8083/avatar/1.png"
    }
    ```

### `/api/user/active/send`
* **方法**: `GET` / `POST`
* **描述**: 重新发送账户激活邮件。
* **认证**: 需要
* **响应示例**:
    ```json
    {
      "err": "ok"
    }
    ```

### `/api/active/<username>/<code>`
* **方法**: `GET` / `POST`
* **描述**: 使用提供的激活码激活用户账户。
* **参数**:
    * `username` (string): 用户名。
    * `code` (string): 激活码。
* **响应**: 成功后重定向，失败则显示错误。

### `/api/done/`
* **方法**: `GET`
* **描述**: 处理社交登录后的回调。更新用户信息并重定向。
* **响应**: 重定向到主页或之前存储的URL。

### `/api/welcome`
* **方法**: `GET`
* **描述**: 检查是否需要访问邀请码，并提供欢迎信息。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "welcome": "欢迎访问私人书库，请输入访问码。"
    }
    ```
    或
    ```json
    {
      "err": "free",
      "msg": "已输入访问码"
    }
    ```

### `/api/welcome`
* **方法**: `POST`
* **描述**: 验证并设置访问邀请码。
* **请求体**:
    ```json
    {
      "invite_code": "INVITE_CODE_HERE"
    }
    ```
* **响应示例 (成功)**:
    ```json
    {
      "err": "ok"
    }
    ```
* **响应示例 (失败)**:
    ```json
    {
      "err": "params.invalid",
      "msg": "访问码无效"
    }
    ```

---
## 书籍管理

### `/api/index`
* **方法**: `GET`
* **描述**: 获取首页数据，包括随机推荐和最新书籍。
* **参数**:
    * `random` (int, 可选): 随机书籍数量 (默认 8)。
    * `recent` (int, 可选): 最新书籍数量 (默认 10)。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "random_books_count": 8,
      "new_books_count": 10,
      "random_books": [ /* ... 格式化后的书籍对象列表 ... */ ],
      "new_books": [ /* ... 格式化后的书籍对象列表 ... */ ]
    }
    ```

### `/api/search`
* **方法**: `GET`
* **描述**: 根据书名、作者等搜索书籍。
* **参数**:
    * `name` (string, 必需): 搜索关键词。
* **响应**: 分页书籍列表 (使用 `ListHandler` 格式)。
    ```json
    {
      "err": "ok",
      "title": "搜索：科幻",
      "total": 25,
      "books": [ /* ... 格式化后的书籍对象列表 ... */ ]
    }
    ```

### `/api/recent`
* **方法**: `GET`
* **描述**: 列出最近添加的书籍。
* **响应**: 分页书籍列表 (使用 `ListHandler` 格式)。
    ```json
    {
      "err": "ok",
      "title": "新书推荐",
      "total": 150,
      "books": [ /* ... 格式化后的书籍对象列表 ... */ ]
    }
    ```

### `/api/hot`
* **方法**: `GET`
* **描述**: 列出根据热度（访问次数）排行的书籍。
* **响应**: 分页书籍列表 (使用 `ListHandler` 格式)。
    ```json
    {
      "err": "ok",
      "title": "热度榜单",
      "total": 150,
      "books": [ /* ... 格式化后的书籍对象列表 ... */ ]
    }
    ```

### `/api/book/nav`
* **方法**: `GET`
* **描述**: 获取由 `BOOK_NAV` 配置定义的标签导航结构。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "navs": [
        {
          "legend": "文学",
          "tags": [
            {"name": "小说", "count": 30},
            {"name": "散文", "count": 15}
          ]
        }
      ]
    }
    ```

### `/api/book/upload`
* **方法**: `POST`
* **描述**: 上传一本新的电子书。
* **认证**: 需要
* **请求体**: `multipart/form-data`，包含一个名为 `ebook` 的文件字段。
* **响应示例 (成功)**:
    ```json
    {
      "err": "ok",
      "book_id": 123
    }
    ```

### `/api/book/<id>`
* **方法**: `GET`
* **描述**: 获取指定书籍的详细信息。
* **参数**:
    * `id` (int): 书籍ID。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "kindle_sender": "sender@example.com",
      "book": {
        "id": 123,
        "title": "书籍标题",
        "authors": ["作者A"],
        "tags": ["标签1", "标签2"],
        // ... 其他书籍详细信息
      },
      "audios": {
        "status": "converted",
        "audios": [
          {"filename": "Chapter_001", "url": "/audios/123/Chapter_001.mp3", "size": 1024000}
        ],
        "count": 1
      }
    }
    ```

### `/api/book/<id>/delete`
* **方法**: `POST`
* **描述**: 从书库中删除一本书。
* **认证**: 需要
* **参数**:
    * `id` (int): 书籍ID。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "msg": "删除成功"
    }
    ```

### `/api/book/<id>/edit`
* **方法**: `POST`
* **描述**: 编辑书籍元数据（书名、作者、标签等）。
* **认证**: 需要
* **参数**:
    * `id` (int): 书籍ID。
* **请求体**:
    ```json
    {
      "title": "新书名",
      "authors": ["新作者"],
      "tags": ["tag1", "tag2"],
      "publisher": "新出版社",
      "isbn": "1234567890",
      "series": "新丛书",
      "rating": 5,
      "languages": ["eng"],
      "pubdate": "2023-10-27" // 或 "2023-10" 或 "2023"
    }
    ```
* **响应示例**:
    ```json
    {
      "err": "ok",
      "msg": "更新成功"
    }
    ```

### `/api/book/<id>.<format>`
* **方法**: `GET`
* **描述**: 下载书籍的指定格式文件。
* **认证**: 需要 (除非允许访客下载)
* **参数**:
    * `id` (int): 书籍ID。
    * `format` (string): 文件格式 (如 `epub`, `mobi`, `pdf`)。
* **响应**: 书籍文件作为附件下载。

### `/api/book/<id>/push`
* **方法**: `POST`
* **描述**: 将书籍推送到 Kindle 邮箱。
* **认证**: 需要 (除非允许访客推送)
* **参数**:
    * `id` (int): 书籍ID。
* **请求体**:
    ```json
    {
      "mail_to": "kindle@example.com"
    }
    ```
* **响应示例**:
    ```json
    {
      "err": "ok",
      "msg": "服务器后台正在推送了。您可关闭此窗口，继续浏览其他书籍。"
    }
    ```

### `/api/book/<id>/refer`
* **方法**: `GET`
* **描述**: 为一本书搜索外部元数据（豆瓣、百度百科、优书网）。
* **认证**: 需要
* **参数**:
    * `id` (int): 书籍ID。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "books": [
        {
          "cover_url": "http://example.com/cover.jpg",
          "source": "douban",
          "title": "匹配的书名",
          "author_sort": "匹配的作者",
          // ... 其他元数据
        }
      ]
    }
    ```

### `/api/book/<id>/refer`
* **方法**: `POST`
* **描述**: 应用外部元数据或重置书籍元数据。
* **认证**: 需要
* **参数**:
    * `id` (int): 书籍ID。
* **请求体**:
    ```json
    {
      "reset": "yes", // 可选: 重置为文件元数据
      // OR
      "provider_key": "douban", // 元数据来源 (douban, baike, youshu)
      "provider_value": "douban_book_id_or_title", // 提供者的标识符
      "only_meta": "yes", // 可选: 仅应用元数据，不覆盖封面
      "only_cover": "yes" // 可选: 仅应用封面，不覆盖元数据 (与only_meta冲突)
    }
    ```
* **响应示例**:
    ```json
    {
      "err": "ok"
    }
    ```

### `/api/book/<id>/convert`
* **方法**: `POST`
* **描述**: 在 EPUB 和 AZW3 格式之间转换书籍。
* **认证**: 需要
* **参数**:
    * `id` (int): 书籍ID。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "content": "转换成功，请稍后刷新页面查看"
    }
    ```

### `/api/book/<id>/setsole`
* **方法**: `POST`
* **描述**: 切换书籍的“私藏”状态（仅上传者可见）。
* **认证**: 需要
* **参数**:
    * `id` (int): 书籍ID。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "msg": "更新成功"
    }
    ```

### `/read/<id>`
* **方法**: `GET`
* **描述**: 重定向到书籍的在线阅读器。
* **认证**: 需要 (除非允许访客阅读)
* **参数**:
    * `id` (int): 书籍ID。

### `/api/read/txt`
* **方法**: `GET`
* **描述**: 读取 TXT 书籍的部分内容。
* **认证**: 需要
* **参数**:
    * `id` (string): 书籍ID。
    * `start` (int): 开始字节位置 (默认 0)。
    * `end` (int): 结束字节位置 (默认 -1, 表示到文件末尾)。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "content": "书籍内容的第一部分...<br>下一行内容..."
    }
    ```

### `/api/book/txt/init`
* **方法**: `GET`
* **描述**: 初始化或检查 TXT 内容解析状态（用于生成目录导航）。
* **参数**:
    * `id` (string): 书籍ID。
    * `test` (string): 如果为 "0"，则强制初始化 (默认检查状态)。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "msg": "已解析",
      "data": {
        "content": [ /* ... 解析出的目录结构 ... */ ],
        "encoding": "utf-8",
        "name": "书籍标题"
      }
    }
    ```

---
## 音频 (EPUB 转音频)

### `/api/audio/<book_id>`
* **方法**: `GET`
* **描述**: 获取一本书的音频文件状态和列表。
* **参数**:
    * `book_id` (int): 书籍ID。
* **响应示例**:
    ```json
    {
      "status": "converted",
      "audios": [
        {"filename": "Chapter_001", "url": "/audios/123/Chapter_001.mp3", "size": 1024000}
      ],
      "count": 1
    }
    ```

### `/api/audio/<book_id>/download/<filename>`
* **方法**: `GET`
* **描述**: 下载指定的音频文件。
* **参数**:
    * `book_id` (int): 书籍ID。
    * `filename` (string): 音频文件名。
* **响应**: 音频文件。

### `/api/audio/<book_id>/conversion`
* **方法**: `GET`
* **描述**: 获取正在进行的音频转换状态。
* **认证**: 需要
* **参数**:
    * `book_id` (int): 书籍ID。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "msg": "转换中",
      "data": {
        "status": "processing",
        "progress": "50%",
        "current_file": "Chapter_002.xhtml"
      }
    }
    ```

### `/api/audio/<book_id>/conversion`
* **方法**: `POST`
* **描述**: 开始将 EPUB 书籍转换为音频。
* **认证**: 需要
* **参数**:
    * `book_id` (int): 书籍ID。
* **请求体**:
    ```json
    {
      "voice": "zh-CN-YunjianNeural", // 可选: TTS 语音
      "language": "zh-CN"             // 可选: 语言代码
    }
    ```
* **响应示例**:
    ```json
    {
      "err": "ok",
      "msg": "开始转换",
      "data": {
        "status": "started"
      }
    }
    ```

### `/api/audio/<book_id>/cancel`
* **方法**: `POST`
* **描述**: 取消正在进行的音频转换。
* **认证**: 需要
* **参数**:
    * `book_id` (int): 书籍ID。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "msg": "转换已取消"
    }
    ```

### `/api/audio/<book_id>/delete`
* **方法**: `POST`
* **描述**: 删除为书籍生成的音频文件。
* **认证**: 需要
* **参数**:
    * `book_id` (int): 书籍ID。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "msg": "音频文件删除成功"
    }
    ```

---
## 元数据分类 (标签, 作者等)

### `/api/<meta>`
* **方法**: `GET`
* **描述**: 获取特定元数据分类的条目列表。
* **参数**:
    * `meta` (string): 元数据类型 (`tag`, `author`, `series`, `rating`, `publisher`, `language`)。
    * `show` (string, 可选): 如果为 "all"，则显示所有条目，不受数量限制。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "meta": "tag",
      "title": "全部标签",
      "items": [
        {"name": "科幻", "count": 20},
        {"name": "历史", "count": 15}
      ],
      "total": 45
    }
    ```

### `/api/<meta>/<name>`
* **方法**: `GET`
* **描述**: 获取与特定元数据条目相关的书籍列表。
* **参数**:
    * `meta` (string): 元数据类型 (`tag`, `author`, `series`, `rating`, `publisher`, `language`)。
    * `name` (string): 元数据条目名称 (如需要，应进行 URL 编码)。
* **响应**: 分页书籍列表 (使用 `ListHandler` 格式)。
    ```json
    {
      "err": "ok",
      "title": "含有\"科幻\"标签的书籍",
      "total": 20,
      "books": [ /* ... 格式化后的书籍对象列表 ... */ ]
    }
    ```

---
## 管理后台 (需要管理员权限)

### `/api/admin/users`
* **方法**: `GET`
* **描述**: 列出用户。
* **参数**:
    * `num` (int, 可选): 每页用户数 (默认 20)。
    * `page` (int, 可选): 页码 (默认 1)。
    * `sort` (string, 可选): 排序字段 (默认 `access_time`)。
    * `desc` (string, 可选): 是否降序 (`true`/`false`, 默认 `true`)。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "users": {
        "items": [
          {
            "id": 1,
            "username": "admin",
            "name": "管理员",
            "email": "admin@example.com",
            "is_active": true,
            "is_admin": true,
            // ... 其他用户信息和权限
          }
        ],
        "total": 5
      }
    }
    ```

### `/api/admin/users`
* **方法**: `POST`
* **描述**: 修改用户（激活、设为管理员、删除、设置权限）。
* **请求体**:
    ```json
    {
      "id": 123, // 用户ID
      "active": true, // 可选
      "admin": false, // 可选
      "delete": "username_to_delete", // 可选: 用于确认删除的用户名
      "permission": "read,write,..." // 可选: 权限字符串
    }
    ```
* **响应示例**:
    ```json
    {
      "err": "ok"
    }
    ```

### `/api/admin/install`
* **方法**: `GET`
* **描述**: 检查系统是否已完成初始安装。
* **响应示例**:
    ```json
    {"err": "installed"}
    ```
    或
    ```json
    {"err": "not_intalled"}
    ```

### `/api/admin/install`
* **方法**: `POST`
* **描述**: 执行系统的初始安装。
* **请求体**:
    ```json
    {
      "code": "INVITE_CODE",
      "email": "admin@example.com",
      "title": "我的书库",
      "invite": "true", // 或 "false"
      "username": "admin",
      "password": "admin_password"
    }
    ```
* **响应示例**:
    ```json
    {
      "err": "ok"
    }
    ```

### `/api/admin/settings`
* **方法**: `GET`
* **描述**: 获取当前系统设置。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "settings": {
        "site_title": "我的书库",
        "ALLOW_GUEST_DOWNLOAD": false,
        // ... 其他设置项
      },
      "sns": [ /* ... 可用的社交登录提供商 ... */ ],
      "site_url": "http://localhost:8083"
    }
    ```

### `/api/admin/settings`
* **方法**: `POST`
* **描述**: 更新系统设置。
* **请求体**:
    ```json
    {
      // 各种设置键值对
      "site_title": "新书库标题",
      "ALLOW_GUEST_DOWNLOAD": true,
      // ... 其他设置
    }
    ```
* **响应示例**:
    ```json
    {
      "err": "ok"
    }
    ```

### `/api/admin/testmail`
* **方法**: `POST`
* **描述**: 测试邮件配置，发送一封测试邮件。
* **请求体**:
    ```json
    {
      "smtp_encryption": "TLS",
      "smtp_server": "smtp.example.com",
      "smtp_username": "user@example.com",
      "smtp_password": "password"
    }
    ```
* **响应示例 (成功)**:
    ```json
    {
      "err": "ok",
      "msg": "发送成功"
    }
    ```

### `/api/admin/book/list`
* **方法**: `GET`
* **描述**: 列出书籍（管理员视图）。
* **参数**:
    * `num`, `page`, `sort`, `desc`, `search`: 与用户端列表接口类似。
* **响应**: 分页书籍列表，包含额外管理员信息。

### `/api/admin/book/fill`
* **方法**: `GET`
* **描述**: 获取自动填充元数据任务的状态。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "status": {
        "total": 100,
        "skip": 10,
        "done": 85,
        "fail": 5
      }
    }
    ```

### `/api/admin/book/fill`
* **方法**: `POST`
* **描述**: 为指定书籍启动自动填充元数据任务。
* **请求体**:
    ```json
    {
      "idlist": "all" // 或 [1, 2, 3] // 书籍ID列表或 "all"
    }
    ```
* **响应示例**:
    ```json
    {
      "err": "ok",
      "msg": "任务启动成功！请耐心等待，稍后再来刷新页面"
    }
    ```

### `/api/admin/books/delete`
* **方法**: `POST`
* **描述**: 批量删除书籍。
* **请求体**:
    ```json
    {
      "idlist": [1, 2, 3] // 书籍ID列表
    }
    ```
* **响应示例**:
    ```json
    {
      "err": "ok",
      "msg": "删除成功"
    }
    ```

### `/api/admin/scan/list`
* **方法**: `GET`
* **描述**: 列出已扫描的文件。
* **参数**:
    * `num`, `page`, `sort`, `desc`, `filter` (`all`/`todo`/`done`)。
* **响应**: 分页的扫描文件列表和摘要。

### `/api/admin/scan/run`
* **方法**: `POST`
* **描述**: 启动扫描上传目录以发现新文件。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "msg": "开始扫描了",
      "total": 5
    }
    ```

### `/api/admin/scan/delete`
* **方法**: `POST`
* **描述**: 删除扫描文件记录。
* **请求体**:
    ```json
    {
      "hashlist": "all" // 或 ["hash1", "hash2"]
    }
    ```
* **响应示例**:
    ```json
    {
      "err": "ok",
      "msg": "删除成功",
      "count": 3
    }
    ```

### `/api/admin/scan/status`
* **方法**: `GET`
* **描述**: 获取上次扫描操作的状态。
* **响应**: 扫描状态计数和摘要。

### `/api/admin/import/run`
* **方法**: `POST`
* **描述**: 启动将扫描到的文件导入书库。
* **请求体**:
    ```json
    {
      "hashlist": "all" // 或 ["hash1", "hash2"]
    }
    ```
* **响应示例**:
    ```json
    {
      "err": "ok",
      "msg": "扫描成功"
    }
    ```

### `/api/admin/import/status`
* **方法**: `GET`
* **描述**: 获取上次导入操作的状态。
* **响应**: 导入状态计数和摘要。

### `/api/admin/ssl`
* **方法**: `POST`
* **描述**: 上传并应用 SSL 证书和密钥（需要重启 Nginx）。
* **请求体**: `multipart/form-data`，包含 `ssl_crt` 和 `ssl_key` 文件字段。
* **响应示例**:
    ```json
    {
      "err": "ok",
      "msg": "Succeed"
    }
    ```

---
## OPDS 书库目录

OPDS 端点位于 `/opds` 下，提供基于 Atom 的书库 Feed，适用于 OPDS 阅读器。

* `/opds/` - 主目录
* `/opds/nav/<which>` - 导航 Feed
* `/opds/category/<category>/<which>` - 分类 Feed
* `/opds/categorygroup/<category>/<which>` - 分类组 Feed
* `/opds/search/<query>` - 搜索 Feed

这些端点返回符合 OPDS 规范的 XML 数据。

---
## 静态文件服务 & 工具

### `/get/(cover|thumb|opf)/<id>`
* **方法**: `GET`
* **描述**: 提供书籍封面、缩略图或元数据 (OPF)。
* **参数**:
    * `id` (int 或 string): 书籍ID。
    * 对于 `thumb`: 可选的宽高，如 `thumb_60_80`。

### `/get/progress/<id>`
* **方法**: `GET`
* **描述**: 显示书籍格式转换的进度。
* **参数**:
    * `id` (int): 书籍ID。

### `/get/extract/<book_id>/<path>`
* **方法**: `GET`
* **描述**: 为在线阅读器提供解压后的 EPUB 内部文件。
* **参数**:
    * `book_id` (int): 书籍ID。
    * `path` (string): EPUB 内的文件路径。

### `/get/pcover`
* **方法**: `GET`
* **描述**: 代理来自白名单外部 URL 的图片。
* **参数**:
    * `url` (string): 外部图片 URL。
  
  