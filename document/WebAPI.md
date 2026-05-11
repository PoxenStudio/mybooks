# Talebook Python 后台 API 接口文档
**最后更新时间**：2026-05-11

## 基础说明

- **基础 URL**：/api（除 OPDS/Podcast/静态资源等非 /api 路由）
- **认证方式**：登录后 Cookie（user_id 等）
- **管理员接口**：需登录且管理员权限
- **响应约定**：大多数 JSON 接口都有 err 字段，err = "ok" 表示成功

### 通用响应格式

成功响应：
```json
{
  "err": "ok",
  "msg": "success",
  "data": {}
}
```

错误响应：
```json
{
  "err": "error.code",
  "msg": "错误描述信息"
}
```

## 设备模型说明

系统设备分为两类：

- **用户设备**：reader_id > 0，绑定具体用户（如用户 Kindle 推送目标）
- **全局设备**：reader_id = 0 或空，系统级共享设备

客户端在展示设备列表时，应根据 reader_id 区分设备归属。

## 图书对象结构

完整的图书对象包含以下字段：

```json
{
  "id": 123,
  "title": "三体",
  "rating": 5,
  "timestamp": "2026-05-11",
  "pubdate": "2024-01-01",
  "author": "刘慈欣",
  "authors": ["刘慈欣"],
  "author_sort": "Liu Cixin",
  "tag": "科幻 / 长篇",
  "tags": ["科幻", "长篇"],
  "publisher": "重庆出版社",
  "comments": "暂无简介",
  "series": "三体系列",
  "series_index": 1,
  "languages": ["zho"],
  "isbn": "9787536692930",
  "img": "https://your.cdn/get/cover/123.jpg",
  "thumb": "https://your.cdn/get/thumb_240_320/123.jpg",
  "collector": "admin",
  "count_visit": 100,
  "count_download": 50,
  "sole": false,
  "has_audio": 0,
  "book_type": 0,
  "book_count": 1,
  "state": {
    "favorite": 1,
    "favorite_date": "2026-05-10T12:00:00",
    "wants": 0,
    "wants_date": null,
    "read_state": 2,
    "read_date": "2026-05-11T10:00:00",
    "online_read": 1,
    "download": 1
  },
  "category": "科幻",
  "ext_link": "",
  "files": [
    {"format": "epub", "size": 123456}
  ],
  "dynamic_cover": 0
}
```

---

## 1. 用户与认证接口

### 1.1 欢迎信息

- **路径**：`/api/welcome`
- **方法**：GET
- **认证**：无需认证
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "version": "v3.20.0"
}
```

### 1.2 用户注册

- **路径**：`/api/user/sign_up`
- **方法**：POST
- **认证**：无需认证（需要开启注册功能）
- **参数**：
  - `username` (string, 必填): 用户名，3-20位字符，仅字母数字下划线
  - `nickname` (string, 必填): 昵称
  - `email` (string, 必填): 邮箱地址
  - `password` (string, 必填): 密码，6-20位
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "注册成功，请查收激活邮件"
}
```

### 1.3 用户登录

- **路径**：`/api/user/sign_in`
- **方法**：POST
- **认证**：无需认证
- **参数**：
  - `username` (string, 必填): 用户名
  - `password` (string, 必填): 密码
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "ok"
}
```

### 1.4 用户登出

- **路径**：`/api/user/sign_out`
- **方法**：GET
- **认证**：需要登录
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "你已成功退出登录。"
}
```

### 1.5 获取当前用户信息

- **路径**：`/api/user/info`
- **方法**：GET
- **认证**：需要登录
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "user": {
    "id": 1,
    "username": "admin",
    "name": "管理员",
    "email": "admin@example.com",
    "avatar": "reader.svg",
    "is_admin": true
  }
}
```

### 1.6 获取VIP信息

- **路径**：`/api/user/vip`
- **方法**：GET
- **认证**：需要登录
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "vip": {
    "enabled": false,
    "quota": 0,
    "expire": null
  }
}
```

### 1.7 更新用户资料

- **路径**：`/api/user/update`
- **方法**：POST
- **认证**：需要登录
- **参数**（JSON）：
  - `nickname` (string, 可选): 新昵称
  - `password0` (string, 可选): 当前密码（修改密码时必填）
  - `password1` (string, 可选): 新密码
  - `password2` (string, 可选): 确认新密码
  - `kindle_email` (string, 可选): Kindle推送邮箱
  - `podcast_token` (string, 可选): Podcast订阅Token
  - `allow_sending_mail` (boolean, 可选): 是否允许发送邮件
- **响应示例**：

```json
{
  "err": "ok"
}
```

### 1.8 重置密码

- **路径**：`/api/user/reset`
- **方法**：POST
- **认证**：无需认证
- **参数**：
  - `username` (string, 必填): 用户名
  - `email` (string, 必填): 注册邮箱
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "密码重置邮件已发送"
}
```

### 1.9 上传头像

- **路径**：`/api/user/avatar`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - `avatar` (file, 必填): 头像图片文件
- **响应示例**：

```json
{
  "err": "ok",
  "avatar": "/get/avatar/user_123.jpg"
}
```

### 1.10 发送激活邮件

- **路径**：`/api/user/active/send`
- **方法**：GET/POST
- **认证**：需要登录
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok"
}
```

### 1.11 激活账户

- **路径**：`/api/active/<username>/<code>`
- **方法**：GET/POST
- **认证**：无需认证
- **参数**：
  - `username` (path, 必填): 用户名
  - `code` (path, 必填): 激活码
- **响应**：302重定向到激活成功页面

### 1.12 管理员创建用户

- **路径**：`/api/user/new`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `username` (string, 必填): 用户名
  - `nickname` (string, 必填): 昵称
  - `email` (string, 必填): 邮箱
  - `password` (string, 必填): 密码
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "用户添加成功"
}
```

### 1.13 OAuth登录完成回调

- **路径**：`/api/done/`
- **方法**：GET
- **认证**：无需认证（由OAuth流程调用）
- **参数**：无
- **响应**：302重定向到首页或指定页面

---

## 2. 用户消息、便签与设备

### 2.1 获取用户消息

- **路径**：`/api/user/messages`
- **方法**：GET
- **认证**：需要登录
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "messages": [
    {
      "id": 1,
      "title": "系统通知",
      "status": "unread",
      "create_time": "2026-05-11 10:00:00",
      "data": {}
    }
  ]
}
```

### 2.2 标记消息已读

- **路径**：`/api/user/messages`
- **方法**：POST
- **认证**：需要登录
- **参数**（JSON）：
  - `id` (int, 必填): 消息ID
- **响应示例**：

```json
{
  "err": "ok"
}
```

### 2.3 清空所有消息

- **路径**：`/api/user/messages/clear`
- **方法**：POST
- **认证**：需要登录
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok"
}
```

### 2.4 置顶作者/标签

- **路径**：`/api/user/pin`
- **方法**：POST
- **认证**：需要登录
- **参数**（JSON）：
  - `item_type` (int, 必填): 0=作者, 1=标签
  - `item` (string, 必填): 作者名或标签名
- **响应示例**：

```json
{
  "err": "ok"
}
```

### 2.5 取消置顶

- **路径**：`/api/user/unpin`
- **方法**：POST
- **认证**：需要登录
- **参数**（JSON）：
  - `item_type` (int, 必填): 0=作者, 1=标签
  - `item` (string, 必填): 作者名或标签名
- **响应示例**：

```json
{
  "err": "ok"
}
```

### 2.6 用户设备管理

- **路径**：`/api/user/devices`
- **方法**：GET/POST
- **认证**：需要登录
- **参数**：
  - GET: 无参数，获取设备列表
  - POST: 添加/更新/删除设备（JSON参数）
- **响应示例**：

```json
{
  "err": "ok",
  "devices": [
    {
      "id": 1,
      "name": "Kindle",
      "email": "user@kindle.com"
    }
  ]
}
```

### 2.7 期望获得的书籍

- **路径**：`/api/user/expected`
- **方法**：GET/POST
- **认证**：需要登录
- **参数**：
  - GET: 无参数，获取期望列表
  - POST: 添加/删除期望（JSON参数）
- **响应示例**：

```json
{
  "err": "ok",
  "items": [
    {
      "id": 1,
      "title": "三体II",
      "author": "刘慈欣"
    }
  ]
}
```

### 2.8 清空历史记录

- **路径**：`/api/user/history/clear`
- **方法**：POST
- **认证**：需要登录
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok"
}
```

### 2.9 用户便签

- **路径**：`/api/user/memo`
- **方法**：GET/POST
- **认证**：需要登录
- **参数**：
  - GET: 无参数，获取便签列表
  - POST: 添加/更新/删除便签（JSON参数）
- **响应示例**：

```json
{
  "err": "ok",
  "memos": [
    {
      "id": 1,
      "content": "便签内容",
      "create_time": "2026-05-11 10:00:00"
    }
  ]
}
```

### 2.10 获取社交网站图标

- **路径**：`/api/friends/favicon/<filename>`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `filename` (path, 必填): 图标文件名
- **响应**：返回图标文件（图片）

---

## 3. 图书基础接口

### 3.1 首页图书列表

- **路径**：`/api/index`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `random` (int, 可选): 随机书籍数量，默认12
  - `recent` (int, 可选): 最新书籍数量，默认12
- **响应示例**：

```json
{
  "err": "ok",
  "random_books_count": 12,
  "new_books_count": 12,
  "random_books": [...],
  "new_books": [...]
}
```

### 3.2 搜索图书

- **路径**：`/api/search`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `query` (string, 必填): 搜索关键词
  - `page` (int, 可选): 页码，默认1
  - `num` (int, 可选): 每页数量，默认20
- **响应示例**：

```json
{
  "err": "ok",
  "total": 100,
  "books": [...]
}
```

### 3.3 最近添加的图书

- **路径**：`/api/recent`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `page` (int, 可选): 页码，默认1
  - `num` (int, 可选): 每页数量，默认20
- **响应示例**：

```json
{
  "err": "ok",
  "total": 100,
  "books": [...]
}
```

### 3.4 所有图书

- **路径**：`/api/all`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `page` (int, 可选): 页码
  - `num` (int, 可选): 每页数量
- **响应示例**：

```json
{
  "err": "ok",
  "total": 1000,
  "books": [...]
}
```

### 3.5 热门图书

- **路径**：`/api/hot`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `page` (int, 可选): 页码
  - `num` (int, 可选): 每页数量
- **响应示例**：

```json
{
  "err": "ok",
  "total": 50,
  "books": [...]
}
```

### 3.6 实体书列表

- **路径**：`/api/printbooks`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `page` (int, 可选): 页码
  - `num` (int, 可选): 每页数量
- **响应示例**：

```json
{
  "err": "ok",
  "total": 200,
  "books": [...]
}
```

### 3.7 已售出实体书

- **路径**：`/api/soledbooks`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `page` (int, 可选): 页码
  - `num` (int, 可选): 每页数量
- **响应示例**：

```json
{
  "err": "ok",
  "total": 20,
  "books": [...]
}
```

### 3.8 图书导航信息

- **路径**：`/api/book/nav`
- **方法**：GET
- **认证**：无需认证
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "nav": {
    "categories": [...],
    "tags": [...],
    "authors": [...]
  }
}
```

### 3.9 获取图书详情

- **路径**：`/api/book/<id>`
- **方法**：GET
- **认证**：无需认证（但登录后可获取阅读状态）
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "kindle_sender": "sender@example.com",
  "book": {...},
  "audios": {...}
}
```

### 3.10 删除图书

- **路径**：`/api/book/<id>/delete`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "删除成功"
}
```

### 3.11 删除图书格式

- **路径**：`/api/book/<id>/delete_format`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `id` (path, 必填): 图书ID
  - `format` (string, 必填): 格式名，如epub、pdf
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "格式删除成功"
}
```

### 3.12 编辑图书元数据

- **路径**：`/api/book/<id>/edit`
- **方法**：POST
- **认证**：需要管理员或书籍所有者权限
- **参数**：
  - `id` (path, 必填): 图书ID
  - JSON数据：包含title、authors、tags、publisher等字段
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "更新成功"
}
```

### 3.13 下载图书文件

- **路径**：`/api/book/<id>.<ext>`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
  - `ext` (path, 必填): 文件格式，如epub、pdf
- **响应**：返回文件下载

### 3.14 图书引用信息

- **路径**：`/api/book/<id>/refer`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "refer": {
    "douban": "https://book.douban.com/...",
    "amazon": "https://www.amazon.com/..."
  }
}
```

### 3.15 推送图书到设备

- **路径**：`/api/book/<id>/send_to_device`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
  - `device_id` (int, 必填): 设备ID
  - `format` (string, 可选): 格式，默认为mobi或epub
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "推送成功"
}
```

### 3.16 发送图书到邮箱

- **路径**：`/api/book/<id>/mailto`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
  - `email` (string, 必填): 目标邮箱
  - `format` (string, 可选): 格式
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "发送成功"
}
```

### 3.17 在线阅读图书

- **路径**：`/read/<id>`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应**：返回在线阅读页面（HTML）

### 3.18 在线阅读TXT

- **路径**：`/api/read/txt`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `book_id` (int, 必填): 图书ID
  - `chapter` (int, 可选): 章节号
- **响应示例**：

```json
{
  "err": "ok",
  "content": "章节内容...",
  "chapter": 1,
  "total_chapters": 10
}
```

### 3.19 初始化TXT阅读

- **路径**：`/api/book/txt/init`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `book_id` (int, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "chapters": [...],
  "total": 10
}
```

### 3.20 转换图书格式

- **路径**：`/api/book/<id>/convert`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
  - `format` (string, 可选): 目标格式
- **响应示例**：

```json
{
  "err": "ok",
  "content": "转换成功，请稍后刷新页面查看"
}
```

### 3.21 转换为PDF

- **路径**：`/api/book/<id>/topdf`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "content": "转换成功，请稍后刷新页面查看"
}
```

### 3.22 转换为TXT.ZIP

- **路径**：`/api/book/<id>/totxtz`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "转换成功"
}
```

### 3.23 设置售出状态

- **路径**：`/api/book/<id>/setsole`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `id` (path, 必填): 图书ID
  - `sole` (boolean, 必填): 是否已售出
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "设置成功"
}
```

### 3.24 获取图书封面

- **路径**：`/api/book/<id>/cover`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应**：返回图片文件

### 3.25 添加/取消收藏

- **路径**：`/api/book/<id>/favorite`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
  - `action` (string, 必填): "add" 或 "remove"
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "收藏成功"
}
```

### 3.26 添加/取消待读

- **路径**：`/api/book/<id>/wants`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
  - `action` (string, 必填): "add" 或 "remove"
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "添加成功"
}
```

### 3.27 更新阅读状态

- **路径**：`/api/book/<id>/readstate`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
  - `state` (int, 必填): 阅读状态（0=未读，1=在读，2=已读）
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "状态更新成功"
}
```

### 3.28 我的收藏

- **路径**：`/api/favorites`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `page` (int, 可选): 页码
  - `num` (int, 可选): 每页数量
- **响应示例**：

```json
{
  "err": "ok",
  "total": 50,
  "books": [...]
}
```

### 3.29 我的待读

- **路径**：`/api/wants`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `page` (int, 可选): 页码
  - `num` (int, 可选): 每页数量
- **响应示例**：

```json
{
  "err": "ok",
  "total": 30,
  "books": [...]
}
```

### 3.30 在读书籍

- **路径**：`/api/reading`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `page` (int, 可选): 页码
  - `num` (int, 可选): 每页数量
- **响应示例**：

```json
{
  "err": "ok",
  "total": 10,
  "books": [...]
}
```

### 3.31 已读书籍

- **路径**：`/api/read-done`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `page` (int, 可选): 页码
  - `num` (int, 可选): 每页数量
- **响应示例**：

```json
{
  "err": "ok",
  "total": 100,
  "books": [...]
}
```

### 3.32 阅读统计

- **路径**：`/api/reading/stats`
- **方法**：GET
- **认证**：需要登录
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "stats": {
    "favorites": 50,
    "wants": 30,
    "reading": 10,
    "read_done": 100
  }
}
```

### 3.33 更新图书标签

- **路径**：`/api/book/<id>/tags`
- **方法**：POST
- **认证**：需要管理员或书籍所有者权限
- **参数**：
  - `id` (path, 必填): 图书ID
  - JSON数据：包含tags数组
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "标签更新成功"
}
```

### 3.34 AI填充图书标签

- **路径**：`/api/book/<id>/aifill`
- **方法**：POST
- **认证**：需要管理员或书籍所有者权限
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "AI更新成功",
  "category": "科幻",
  "tags": ["硬科幻", "太空歌剧"]
}
```

### 3.35 批量更新标签

- **路径**：`/api/book/update_tags`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `tag` (string, 必填): 标签名
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "已提交300本书籍的标签更新任务",
  "count": 300
}
```

### 3.36 更新图书分类

- **路径**：`/api/book/<id>/category`
- **方法**：POST
- **认证**：需要管理员或书籍所有者权限
- **参数**：
  - `id` (path, 必填): 图书ID
  - `category` (string, 必填): 分类名称
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "分类更新成功"
}
```

### 3.37 批量更新分类

- **路径**：`/api/book/category`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `category` (string, 必填): 分类名称
  - `author` (string, 可选): 作者名
  - `tag` (string, 可选): 标签名
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "成功更新100本书籍分类",
  "count": 100
}
```

### 3.38 获取所有分类

- **路径**：`/api/categories`
- **方法**：GET
- **认证**：无需认证
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "categories": [
    {"name": "科幻", "count": 100},
    {"name": "文学", "count": 200}
  ]
}
```

### 3.39 搜索标签

- **路径**：`/api/tags/search`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `q` (string, 必填): 搜索关键词
  - `limit` (int, 可选): 返回数量，默认20
- **响应示例**：

```json
{
  "err": "ok",
  "tags": [
    {"name": "科幻", "count": 100},
    {"name": "硬科幻", "count": 50}
  ]
}
```

### 3.40 图书推荐

- **路径**：`/api/book/<id>/suggestion`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "books": [...]
}
```

### 3.41 拆分图书

- **路径**：`/api/book/<id>/separate`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "拆分成功"
}
```

### 3.42 保存元数据到文件

- **路径**：`/api/book/<id>/savemeta`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "元数据已保存"
}
```

### 3.43 添加印章

- **路径**：`/api/book/<id>/addstamp`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `id` (path, 必填): 图书ID
  - `stamp_id` (int, 必填): 印章ID
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "印章添加成功"
}
```

### 3.44 交换书籍类型

- **路径**：`/api/book/exchange_type`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `id1` (int, 必填): 图书1的ID
  - `id2` (int, 必填): 图书2的ID
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "交换成功"
}
```

### 3.45 清理稀有标签

- **路径**：`/api/clear_rare_tags`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `threshold` (int, 可选): 阈值，默认为1
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "清理成功",
  "count": 50
}
```

### 3.46 添加图书

- **路径**：`/api/book/add`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - JSON数据：包含title、authors等信息
- **响应示例**：

```json
{
  "err": "ok",
  "book_id": 123
}
```

### 3.47 上传图书

- **路径**：`/api/book/upload`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - `file` (file, 必填): 图书文件
- **响应示例**：

```json
{
  "err": "ok",
  "book_id": 123
}
```

### 3.48 分块上传图书

- **路径**：`/api/book/upload/chunk`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - `chunk` (file, 必填): 分块数据
  - `chunkIndex` (int, 必填): 分块索引
  - `totalChunks` (int, 必填): 总分块数
  - `filename` (string, 必填): 文件名
- **响应示例**：

```json
{
  "err": "ok",
  "completed": false
}
```

---

## 4. 元数据接口（作者、出版社、标签等）

### 4.1 获取元数据列表

- **路径**：`/api/<meta>`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `meta` (path, 必填): 类型，可选值：author、publisher、tag、rating、series、language
  - `show` (string, 可选): "all" 显示全部
- **响应示例**：

```json
{
  "err": "ok",
  "meta": "author",
  "title": "全部作者",
  "items": [
    {"name": "刘慈欣", "count": 10},
    {"name": "金庸", "count": 20}
  ],
  "total": 100,
  "pins": [...]
}
```

### 4.2 获取元数据下的图书

- **路径**：`/api/<meta>/<name>`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `meta` (path, 必填): 类型
  - `name` (path, 必填): 元数据名称
  - `page` (int, 可选): 页码
  - `num` (int, 可选): 每页数量
- **响应示例**：

```json
{
  "err": "ok",
  "total": 50,
  "books": [...]
}
```

### 4.3 更新作者信息

- **路径**：`/api/author/<name>/update`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `name` (path, 必填): 作者名
- **响应**：302重定向

### 4.4 更新出版社信息

- **路径**：`/api/publisher/<name>/update`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `name` (path, 必填): 出版社名
- **响应**：302重定向

---

## 5. 音频图书接口

### 5.1 获取音频详情

- **路径**：`/api/audio/<id>`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "audio_dir": "/data/books/audios/123",
  "audios": [
    {
      "filename": "第1章",
      "url": "/api/audio/123/chapter01.mp3",
      "size": 1024000
    }
  ],
  "total_files": 10,
  "is_paid": true
}
```

### 5.2 获取音频转换状态

- **路径**：`/api/audio/<id>/conversion`
- **方法**：GET/POST
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
  - POST: 启动音频转换
- **响应示例**：

```json
{
  "err": "ok",
  "status": "converting",
  "progress": 50
}
```

### 5.3 取消音频转换

- **路径**：`/api/audio/<id>/cancel`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "转换已取消"
}
```

### 5.4 删除音频文件

- **路径**：`/api/audio/<id>/delete`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "音频文件删除成功"
}
```

### 5.5 购买音频

- **路径**：`/api/audio/<id>/purchase`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "购买成功"
}
```

### 5.6 获取所有音频图书

- **路径**：`/api/audiobooks`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `page` (int, 可选): 页码
  - `num` (int, 可选): 每页数量
- **响应示例**：

```json
{
  "err": "ok",
  "total": 50,
  "books": [...]
}
```

### 5.7 下载音频文件

- **路径**：`/api/audio/<id>/<filename>`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
  - `filename` (path, 必填): 音频文件名
- **响应**：返回音频文件

### 5.8 获取音频合集

- **路径**：`/api/audios/<id>/collection`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "files": [...]
}
```

### 5.9 下载音频合集

- **路径**：`/api/audios/<id>/collection/download`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应**：返回ZIP文件

---

## 6. 管理员接口

### 6.1 SSL证书管理

- **路径**：`/api/admin/ssl`
- **方法**：GET/POST
- **认证**：需要管理员权限
- **参数**：
  - GET: 获取SSL证书信息
  - POST: 上传SSL证书（JSON）
- **响应示例**：

```json
{
  "err": "ok",
  "ssl": {
    "enabled": true,
    "expire_date": "2027-05-11"
  }
}
```

### 6.2 用户管理

- **路径**：`/api/admin/users`
- **方法**：GET/POST
- **认证**：需要管理员权限
- **参数**：
  - GET: 获取用户列表
    - `page` (int, 可选): 页码，默认1
    - `num` (int, 可选): 每页数量，默认20
    - `sort` (string, 可选): 排序字段
    - `desc` (string, 可选): 是否降序
  - POST: 更新用户信息（JSON）
- **响应示例**：

```json
{
  "err": "ok",
  "users": {
    "items": [...],
    "total": 100
  },
  "settings": {...}
}
```

### 6.3 初始化安装

- **路径**：`/api/admin/install`
- **方法**：GET/POST
- **认证**：无需认证（仅在未安装时可用）
- **参数**：
  - POST: 安装参数（JSON）
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "安装成功"
}
```

### 6.4 系统设置

- **路径**：`/api/admin/settings`
- **方法**：GET/POST
- **认证**：需要管理员权限
- **参数**：
  - GET: 获取系统设置
  - POST: 更新系统设置（JSON）
- **响应示例**：

```json
{
  "err": "ok",
  "settings": {...}
}
```

### 6.5 测试邮件发送

- **路径**：`/api/admin/testmail`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `smtp_server` (string, 必填): SMTP服务器
  - `smtp_username` (string, 必填): SMTP用户名
  - `smtp_password` (string, 必填): SMTP密码
  - `smtp_encryption` (string, 必填): 加密方式
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "发送成功"
}
```

### 6.6 图书列表（管理）

- **路径**：`/api/admin/book/list`
- **方法**：GET
- **认证**：需要管理员权限
- **参数**：
  - `page` (int, 可选): 页码
  - `num` (int, 可选): 每页数量
- **响应示例**：

```json
{
  "err": "ok",
  "total": 1000,
  "books": [...]
}
```

### 6.7 自动填充图书信息

- **路径**：`/api/admin/book/fill`
- **方法**：GET/POST
- **认证**：需要管理员权限
- **参数**：
  - `book_id` (int, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "填充成功"
}
```

### 6.8 AI填充图书信息

- **路径**：`/api/admin/book/aifill`
- **方法**：GET/POST
- **认证**：需要管理员权限
- **参数**：
  - `book_id` (int, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "AI填充成功"
}
```

### 6.9 Kindle格式转换

- **路径**：`/api/admin/book/kindleconvert`
- **方法**：GET/POST
- **认证**：需要管理员权限
- **参数**：
  - `book_id` (int, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "转换已启动"
}
```

### 6.10 更新标题排序

- **路径**：`/api/admin/book/update_title_sort`
- **方法**：GET/POST
- **认证**：需要管理员权限
- **参数**：无或book_id
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "更新成功"
}
```

### 6.11 申请BookBarn Token

- **路径**：`/api/admin/bookbarn/token/apply`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `email` (string, 必填): 邮箱
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "申请成功"
}
```

### 6.12 批量删除图书

- **路径**：`/api/admin/books/delete`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `book_ids` (array, 必填): 图书ID数组
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "删除成功",
  "count": 10
}
```

### 6.13 保存图书元数据

- **路径**：`/api/admin/books/save_meta`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `book_ids` (array, 必填): 图书ID数组
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "保存成功"
}
```

### 6.14 清理无效项目

- **路径**：`/api/admin/clear/invalid/items`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "清理成功",
  "count": 50
}
```

### 6.15 测试音频转换

- **路径**：`/api/admin/audio/test`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `text` (string, 必填): 测试文本
- **响应示例**：

```json
{
  "err": "ok",
  "audio_url": "/path/to/test.mp3"
}
```

### 6.16 发布说明

- **路径**：`/api/admin/release/notes`
- **方法**：GET
- **认证**：需要管理员权限
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "notes": "版本更新说明..."
}
```

### 6.17 获取管理Token

- **路径**：`/api/admin/token`
- **方法**：GET
- **认证**：需要管理员权限
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "token": "admin-token-here"
}
```

### 6.18 正在运行的任务

- **路径**：`/api/admin/tasks/running`
- **方法**：GET
- **认证**：需要管理员权限
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "tasks": [
    {
      "id": "task-123",
      "type": "convert",
      "status": "running",
      "progress": 50
    }
  ]
}
```

### 6.19 回收站大小

- **路径**：`/api/admin/trash/size`
- **方法**：GET
- **认证**：需要管理员权限
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "size": 1024000000
}
```

### 6.20 清空回收站

- **路径**：`/api/admin/trash/clear`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "清空成功"
}
```

### 6.21 印章管理

- **路径**：`/api/admin/stamp`
- **方法**：GET/POST
- **认证**：需要管理员权限
- **参数**：
  - GET: 获取印章列表
  - POST: 添加/更新/删除印章
- **响应示例**：

```json
{
  "err": "ok",
  "stamps": [...]
}
```

### 6.22 图书馆统计

- **路径**：`/api/library/stats`
- **方法**：GET
- **认证**：需要管理员权限
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "stats": {
    "total_books": 1000,
    "total_authors": 200,
    "total_publishers": 100,
    "total_users": 50
  }
}
```

### 6.23 系统日志

- **路径**：`/api/admin/syslog`
- **方法**：GET
- **认证**：需要管理员权限
- **参数**：
  - `lines` (int, 可选): 显示行数，默认100
- **响应示例**：

```json
{
  "err": "ok",
  "log": "系统日志内容..."
}
```

### 6.24 批量更新所有元数据

- **路径**：`/api/admin/book/update_all_meta`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "批量更新已启动"
}
```

### 6.25 批量更新动态封面

- **路径**：`/api/admin/book/update_all_dynamic_cover`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "批量更新已启动"
}
```

### 6.26 重置封面

- **路径**：`/api/admin/book/reset_cover`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `book_id` (int, 必填): 图书ID
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "重置成功"
}
```

### 6.27 下载系统日志

- **路径**：`/api/admin/syslog/download`
- **方法**：GET
- **认证**：需要管理员权限
- **参数**：无
- **响应**：返回日志文件下载

---

## 7. 条形码识别接口

### 7.1 识别条形码

- **路径**：`/api/admin/barcode`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - `barcode_image` (file, 必填): 条形码图片
- **响应示例**：

```json
{
  "err": "ok",
  "isbn": "9787536692930"
}
```

---

## 8. 扫描与导入接口

### 8.1 导入列表

- **路径**：`/api/admin/import/list`
- **方法**：GET
- **认证**：需要管理员权限
- **参数**：
  - `page` (int, 可选): 页码
  - `num` (int, 可选): 每页数量
  - `sort` (string, 可选): 排序字段
  - `desc` (string, 可选): 是否降序
  - `filter` (string, 可选): 过滤条件（all/todo/done）
- **响应示例**：

```json
{
  "err": "ok",
  "items": [...],
  "total": 100,
  "scanning": false,
  "importing": false,
  "summary": {
    "total": 100,
    "done": 50,
    "todo": 50
  },
  "scan_dir": "/data/books/import"
}
```

### 8.2 删除导入项

- **路径**：`/api/admin/import/delete`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `hashlist` (array/string, 必填): 文件hash列表或"all"
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "删除成功",
  "count": 10
}
```

### 8.3 执行导入

- **路径**：`/api/admin/import/run`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `filelist` (array/string, 必填): 文件列表或"all"
  - `skip_last_dirs` (int, 可选): 跳过最后几级目录
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "扫描成功"
}
```

### 8.4 导入状态

- **路径**：`/api/admin/import/status`
- **方法**：GET
- **认证**：需要管理员权限
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "task": "task-id",
  "status": {
    "ready": 10,
    "importing": 5,
    "imported": 50,
    "exist": 30,
    "total": 100,
    "processed": 85
  },
  "summary": {...},
  "scanning": false,
  "ignored_errors": [],
  "importing": true
}
```

### 8.5 批量添加实体书

- **路径**：`/api/admin/batch_add/run`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `csv_file` (file, 必填): CSV文件
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "批量添加已启动"
}
```

### 8.6 批量添加状态

- **路径**：`/api/admin/batch_add/status`
- **方法**：GET
- **认证**：需要管理员权限
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "status": "running",
  "progress": 50,
  "total": 100
}
```

### 8.7 音频导入

- **路径**：`/api/admin/audio_import/run`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `audio_files` (array, 必填): 音频文件列表
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "音频导入已启动"
}
```

### 8.8 音频导入状态

- **路径**：`/api/admin/audio_import/status`
- **方法**：GET
- **认证**：需要管理员权限
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "status": "running",
  "progress": 30
}
```

### 8.9 取消导入

- **路径**：`/api/admin/import/cancel`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "导入已取消"
}
```

---

## 9. OPDS接口

OPDS（Open Publication Distribution System）接口用于提供标准化的图书目录服务，兼容各种OPDS客户端。

### 9.1 OPDS根目录

- **路径**：`/opds/`
- **方法**：GET
- **认证**：无需认证
- **参数**：无
- **响应**：返回OPDS Feed（XML）

### 9.2 OPDS导航目录

- **路径**：`/opds/nav/<which>`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `which` (path, 必填): 导航类型
  - `offset` (int, 可选): 偏移量
- **响应**：返回OPDS Feed（XML）

### 9.3 OPDS分类目录

- **路径**：`/opds/category/<category>/<which>`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `category` (path, 必填): 分类名
  - `which` (path, 必填): 子分类
  - `offset` (int, 可选): 偏移量
- **响应**：返回OPDS Feed（XML）

### 9.4 OPDS分类组目录

- **路径**：`/opds/categorygroup/<category>/<which>`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `category` (path, 必填): 分类组名
  - `which` (path, 必填): 子分类
- **响应**：返回OPDS Feed（XML）

### 9.5 OPDS搜索

- **路径**：`/opds/search/<query>`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `query` (path, 必填): 搜索关键词
  - `offset` (int, 可选): 偏移量
- **响应**：返回OPDS Feed（XML）

---

## 10. 静态文件接口

### 10.1 获取代理封面

- **路径**：`/get/pcover`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `url` (string, 必填): 原始图片URL
- **响应**：返回图片文件

### 10.2 获取进度信息

- **路径**：`/get/progress/<id>`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `id` (path, 必填): 任务ID
- **响应**：返回进度文本

### 10.3 提取EPUB内容

- **路径**：`/get/extract/<book_id>/<path>`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `book_id` (path, 必填): 图书ID
  - `path` (path, 必填): 内部路径
- **响应**：返回提取的文件内容

### 10.4 获取资源文件

- **路径**：`/get/<type>/<name>`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `type` (path, 必填): 资源类型（cover/thumb_*等）
  - `name` (path, 必填): 资源名称
- **响应**：返回资源文件

### 10.5 静态文件服务

- **路径**：`/<path>`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `path` (path, 必填): 文件路径
- **响应**：返回静态文件

---

## 11. Podcast接口

Podcast接口用于提供RSS订阅服务，支持播客客户端订阅有声书。

### 11.1 Podcast首页

- **路径**：`/podcast/`
- **方法**：GET
- **认证**：无需认证（部分功能需要Token）
- **参数**：无
- **响应**：返回Podcast首页（HTML）

### 11.2 所有有声书

- **路径**：`/podcast/all`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `token` (string, 可选): 用户Token
- **响应**：返回RSS Feed（XML）

### 11.3 单本书的Podcast

- **路径**：`/podcast/book/<id>`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `id` (path, 必填): 图书ID
  - `token` (string, 可选): 用户Token
- **响应**：返回RSS Feed（XML）

### 11.4 单本书的OPML

- **路径**：`/podcast/book/<id>/opml`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应**：返回OPML（XML）

### 11.5 分类Podcast

- **路径**：`/podcast/category/<name>`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `name` (path, 必填): 分类名
  - `token` (string, 可选): 用户Token
- **响应**：返回HTML页面列出该分类下的有声书

### 11.6 标签Podcast

- **路径**：`/podcast/tag/<name>`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `name` (path, 必填): 标签名
  - `token` (string, 可选): 用户Token
- **响应**：返回HTML页面列出该标签下的有声书

### 11.7 作者Podcast

- **路径**：`/podcast/author/<name>`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `name` (path, 必填): 作者名
  - `token` (string, 可选): 用户Token
- **响应**：返回HTML页面列出该作者的有声书

### 11.8 个人订阅Podcast（需Token）

- **路径**：`/podcast/<token>/book/<id>`
- **方法**：GET
- **认证**：通过Token认证
- **参数**：
  - `token` (path, 必填): 用户Podcast Token
  - `id` (path, 必填): 图书ID
- **响应**：返回RSS Feed（XML）

### 11.9 个人订阅首页

- **路径**：`/podcast/<token>/`
- **方法**：GET
- **认证**：通过Token认证
- **参数**：
  - `token` (path, 必填): 用户Podcast Token
- **响应**：返回HTML页面列出个人订阅

### 11.10 Podcast音频文件

- **路径**：`/podcast/audio/<book_id>/<token>/<filename>`
- **方法**：GET
- **认证**：通过Token认证
- **参数**：
  - `book_id` (path, 必填): 图书ID
  - `token` (path, 必填): 访问Token
  - `filename` (path, 必填): 音频文件名
- **响应**：返回音频文件

---

## 12. AI助手接口

### 12.1 AI助手WebSocket

- **路径**：`/api/assistant/ws`
- **方法**：WebSocket
- **认证**：需要登录
- **参数**：
  - WebSocket消息（JSON）：
    - `content` (string, 必填): 用户输入内容
- **响应**：
  - 流式返回AI助手响应（JSON chunks）
  - 消息类型：
    - `{"type": "status", "content": "..."}`
    - `{"type": "start"}`
    - `{"type": "data", "content": "..."}`
    - `{"type": "end"}`
    - `{"type": "error", "content": "..."}`

---

## 13. MCP（Model Context Protocol）接口

### 13.1 MCP流式请求

- **路径**：`/api/mcp/stream`
- **方法**：GET/POST
- **认证**：可选（支持Token参数）
- **参数**：
  - GET: 获取MCP服务信息
  - POST: 发送MCP请求（JSON-RPC格式）
    - `token` (query, 可选): 访问Token
- **响应示例**：

GET响应：
```json
{
  "err": "ok",
  "version": "v3.20.0",
  "settings": {
    "base_url": "https://your.site",
    "mcp_version": "v3.20.0"
  },
  "timestamp": "2026-05-11T10:00:00"
}
```

POST响应：
```json
{
  "err": "ok",
  "jsonrpc": "2.0",
  "result": {...}
}
```

### 13.2 MCP健康检查

- **路径**：`/api/mcp/health`
- **方法**：GET
- **认证**：无需认证
- **参数**：无
- **响应示例**：

```json
{
  "err": "ok",
  "status": "healthy",
  "server": "talebook-mcp"
}
```

---

## 附录A：错误代码说明

常见错误代码：

- `ok`: 请求成功
- `params.invalid`: 参数无效
- `params.book.invalid`: 图书不存在
- `params.user.not_exist`: 用户不存在
- `permission.not_admin`: 非管理员无权限
- `permission.denied`: 权限不足
- `permission.inactive`: 用户未激活
- `user.no_permission`: 无权限操作
- `db.error`: 数据库错误
- `email.server_error`: 邮件服务器错误
- `internal`: 内部错误

## 附录B：阅读状态说明

阅读状态字段（`read_state`）：

- `0`: 未读
- `1`: 在读
- `2`: 已读

收藏/待读状态：

- `favorite`: 1=已收藏，0=未收藏
- `wants`: 1=想读，0=不想读

## 附录C：图书类型说明

图书类型字段（`book_type`）：

- `0`: 电子书
- `1`: 实体书

## 附录D：认证说明

### Cookie认证

大部分API使用Cookie进行认证，登录后会设置以下Cookie：

- `user_id`: 用户ID（加密）
- `admin_id`: 管理员ID（管理员切换用户时使用）

### Token认证

部分API支持Token认证：

- Podcast订阅：使用`podcast_token`参数
- MCP服务：使用`token`查询参数
- 音频访问：使用Token进行权限验证

