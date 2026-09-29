# MyBoooks 后台 API 接口文档
**最后更新时间**：2026-09-28

## 基础说明

- **基础 URL**：/api（除 OPDS/Podcast/静态资源等非 /api 路由）
- **认证方式**：登录后 Cookie（user_id 等）
- **管理员接口**：需登录且管理员权限
- **响应约定**：大多数 JSON 接口都有 err 字段，err = "ok" 表示成功

### 分页约定

- 图书列表类接口（搜索、最近、元数据下的书等，返回 `title`/`total`/`books`）统一用 `start`（偏移量）+ `size`（每页数量，默认 `DEFAULT_PAGE_SIZE`，最大 1000）分页；个别接口有固定页大小或不同上限，以各接口说明为准。
- 书单、评论、用户、留言等管理类列表使用 `page`（从 1 开始）+ `page_size`（或 `num`），以各接口说明为准。

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
  "folder": "文学.小说",
  "ext_link": "",
  "files": [
    {"format": "epub", "size": 123456}
  ],
  "dynamic_cover": 0
}
```

---

## 1. 用户与认证接口

### 1.1 使用访问码授权

- **路径**：`/api/access`
- **方法**：POST
- **参数**: JSON Body.
  - `invite_code` (string, 必填): 访问码
- **认证**：无需认证
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

### 1.5 获取当前用户信息，包含系统信息

- **路径**：`/api/user/info`
- **方法**：GET
- **认证**：无需登录（未安装时返回 `err=not_installed`）
- **参数**：
  - `detail` (string, 可选): 非空时不返回 `sys`，改为在 `user.extra` 中返回用户扩展数据（含 `*_history` 浏览历史，最多 12 本，带 `img`/`thumb`/`href`）
- **响应示例**：

```json
{
  "err": "ok",
  "sys": {
    "title": "MyBooks",
    "books": 10000,
    "version": "v3.41.0",
    "upgrable": "",
    "allow": {
      "register": false,
      "download": true,
      "push": true,
      "read": true,
      "physical_books": true,
      "folder": false,
      "download_quota": false,
      "upload": false,
      "sync": true,
      "book_review": true,
      "book_recommend": true,
      "shared_notes": true
    },
    "sidebar_items": ["audiobooks", "printbooks", "tags", "series", "memo"]
  },
  "user": {
    "id": 1,
    "username": "admin",
    "name": "管理员",
    "email": "admin@example.com",
    "avatar": "reader.svg",
    "is_admin": true,
    "show_home_recommendations": false,
    "show_other_annotations": false,
    "appearance": {
      "v": 1,
      "darkMode": true,
      "brandColor": null,
      "accent": "#1976D2",
      "radius": "4px",
      "background": "default",
      "sidebarIconMode": "multi",
      "sidebarIconColor": null
    }
  }
}
```
未登录时返回基础系统信息，用户信息中is_login为false，登录时会返回完整用户信息。
sys中为基础系统信息，title为网站标题, books为在库书籍数量，version为当前系统版本。其中upgrable代表是否有升级版本，如果为有值且与version不同代表有可升级版本。

`sys.allow` 为站点功能开关，前端据此决定相关入口/按钮是否展示，各字段均为 boolean：

| 字段 | 对应配置项 | 默认值 | 含义 |
|---|---|---|---|
| `register` | `ALLOW_REGISTER` | `false` | 是否开放用户注册（控制注册入口） |
| `download` | `ALLOW_GUEST_DOWNLOAD` | `true` | 是否允许访客（未登录）下载书籍 |
| `push` | `ALLOW_GUEST_PUSH` | `true` | 是否允许访客推送书籍到 Kindle 邮箱 |
| `read` | `ALLOW_GUEST_READ` | `true` | 是否允许访客在线阅读 |
| `physical_books` | `ENABLE_PHYSICAL_BOOKS` | `true` | 是否启用实体书功能（实体书信息、添加实体书等） |
| `folder` | `ENABLE_FOLDER_BROWSE` | `false` | 是否启用按文件夹浏览书库 |
| `download_quota` | `ENABLE_DOWNLOAD_QUOTA` | `false` | 是否启用每用户每日下载配额限制 |
| `upload` | `ALLOW_GUEST_UPLOAD` | `false` | 是否允许访客上传书籍 |
| `sync` | `ENABLE_DATA_SYNC` | `true` | 是否启用阅读数据同步（MyReader 同步） |
| `book_review` | `ENABLE_BOOK_REVIEW` | `true` | 是否允许用户对书籍进行评论及评分 |
| `book_recommend` | `ENABLE_BOOK_RECOMMEND_TO_OTHERS` | `true` | 评价是否计入推荐人数/首页推荐位 |
| `shared_notes` | `ENABLE_SHARED_NOTES` | `true` | 阅读时是否可查看其他用户的划线与笔记 |

`sys.sidebar_items`（string 数组，对应配置项 `SIDEBAR_ITEMS`，默认 `[]`）为管理员配置的侧边栏可选导航项白名单：**空数组表示全部显示**，非空时仅显示数组中列出的项。未列入可选范围的导航（首页、作者、所有图书、个人/管理/书单菜单等）始终显示。可取值如下：

| 值 | 侧边栏项 | 备注 |
|---|---|---|
| `audiobooks` | 有声书 | |
| `printbooks` | 实体书 | 还需 `sys.allow.physical_books` 为 true |
| `publishers` | 出版社 | |
| `folders` | 文件夹浏览 | 还需 `sys.allow.folder` 为 true |
| `categories` | 分类浏览 | |
| `tags` | 标签 | |
| `series` | 丛书 | |
| `languages` | 语言 | |
| `rating` | 评分 | |
| `memo` | 站内留言 | |

登录用户的 `user` 字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `is_login` | boolean | 是否已登录 |
| `is_guest` | boolean | 是否为访客（未登录但站点允许游客阅读） |
| `is_admin` | boolean | 是否为管理员 |
| `is_active` | boolean | 账号是否已激活 |
| `nickname` | string | 昵称 |
| `username` | string | 用户名 |
| `email` | string | 注册邮箱 |
| `avatar` | string | 头像完整 URL |
| `create_time` | string | 注册时间，格式 `YYYY-MM-DD HH:MM:SS` |
| `podcast_token` | string | Podcast 订阅 Token |
| `allow_statistic` | boolean | 用户是否参与阅读统计 |
| `allow_user_disable_statistic` | boolean | 系统是否允许用户关闭阅读统计（`ALLOW_USER_DISABLE_STATISTIC`） |
| `total_reading_seconds` | int | 累计阅读时长（秒） |
| `download_count` | int | 累计下载次数 |
| `show_home_recommendations` | boolean | 首页是否显示其他用户的推荐 |
| `allow_review` | boolean | 是否允许发表评论（用户未被管理员禁言且 `ENABLE_BOOK_REVIEW` 开启时为 true） |
| `show_other_annotations` | boolean | 阅读时是否显示其他用户的批注（默认 true） |
| `share_annotations` | boolean | 自己的批注是否对其他用户可见（默认 true） |
| `appearance` | object | 外观设置，见下方说明 |
| `kindle_email` | string | Kindle 推送邮箱 |
| `last_share_email` | string | 最近一次分享到邮箱的收件人，供分享对话框一键填入 |
| `extra` | object | 用户扩展数据，仅 `detail` 非空时有内容（含 `*_history` 浏览历史） |
| `vipquota` | int | VIP 额度，仅开启 VIP 额度时返回 |
| `vip_expire` | string | VIP 到期日 `YYYY-MM-DD`，仅开启 VIP 额度时返回 |

未登录且允许游客访问时 `is_guest=true`、`nickname="访客"`，只返回 `is_login`、`is_admin`、`is_active`、`is_guest`、`nickname`、`username`、`email`、`extra`、`appearance`、`create_time`、`podcast_token`。
user.appearance为外观设置（顶栏品牌色、侧栏图标配色、深浅色、圆角、背景图案），用户从未保存过时为空对象`{}`，由前端沿用「本地缓存 → 站点默认sys.theme → 内置默认」的回退顺序，保存入口见 1.9。


### 1.6 更新用户资料

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
  - `show_other_annotations` (boolean, 可选): 阅读时是否显示其他用户的批注
  - `share_annotations` (boolean, 可选): 是否允许自己的批注被其他用户看到（默认 true）
  - `allow_statistic` (boolean, 可选): 是否参与阅读统计；仅当系统允许用户关闭统计（`ALLOW_USER_DISABLE_STATISTIC`）时生效
  - `show_home_recommendations` (boolean, 可选): 首页是否显示其他用户的推荐
- **说明**：只修改传入的字段；修改密码需 `password0` 正确，新密码 6~20 位且两次一致。
- **响应**：`err`: `ok` / `params.nickname.invald` / `params.password.error`（当前密码错误）/ `params.password.invalid` / `params.email.invalid` / `db.error`
- **请求示例**:
```json
{
    "password0": "",
    "nickname": "admin",
    "kindle_email": "",
    "allow_sending_mail": false,
    "allow_statistic": true,
    "show_home_recommendations": true,
    "show_other_annotations": false
}
```
- **响应示例**：

```json
{
  "err": "ok"
}
```

### 1.7 重置密码

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

### 1.8 上传头像

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

### 1.9 保存 / 清空外观设置

- **路径**：`/api/user/appearance`
- **方法**：POST（保存）、DELETE（清空）
- **认证**：需要登录
- **说明**：补丁语义 —— 只提交改动过的键，未提交的键保持原值；未知键与非法值一律丢弃（不会用空值覆盖已有的合法值）。
  提交**完整对象**同样合法（幂等），前端就是把当前完整设置整份提交的。
  设置落在 `Reader.extra["appearance"]`，由 `/api/user/info` 的 `user.appearance`（见 1.5）下发前端。
  客户端声明的 `v` 比服务端新时返回 `appearance.version.unsupported`：老服务端不认识新客户端的键、会静默丢弃，宁可让客户端提示用户刷新。
- **参数**（JSON）：
  - `darkMode` (boolean, 可选): 深浅色主题
  - `accent` (string, 可选): 主色，`#RRGGBB`（不接受 `null`：主色有内置默认值，前端也只接受合法 hex）
  - `brandColor` (string|null, 可选): 顶栏品牌色，`#RRGGBB`；传 `null` 表示回到内置默认深蓝
  - `radius` (string, 可选): 圆角，`0px` / `4px` / `8px` / `16px`
  - `background` (string, 可选): 背景图案，见下方枚举
  - `sidebarIconMode` (string, 可选): 侧栏图标配色，`multi`（保持多彩，默认）/ `theme`（跟随主色）/ `custom`（统一自定义）
  - `sidebarIconColor` (string|null, 可选): `sidebarIconMode=custom` 时使用的图标色
- **请求示例**:
```json
{
  "darkMode": false,
  "brandColor": "#4c1d95",
  "sidebarIconMode": "theme"
}
```
- **响应示例**：

```json
{
  "err": "ok",
  "appearance": {
    "v": 1,
    "darkMode": false,
    "brandColor": "#4c1d95",
    "accent": "#1976D2",
    "radius": "4px",
    "background": "default",
    "sidebarIconMode": "theme",
    "sidebarIconColor": null
  },
  "dropped": []
}
```
- **清空（DELETE）**：删掉该账号已保存的外观设置，响应 `{"err": "ok", "appearance": {}}`。
  用于外观面板的「重置为默认」—— 语义是回到「从未保存过」，前端随即重新采用
  「本地缓存 → 站点默认 `sys.theme` → 内置默认」的回退顺序。
  刻意不做成「提交一份内置默认值」：那会把管理员设置的站点默认永久顶掉（站点默认只在本机没有
  外观缓存时才生效）。
- **错误码**：`params.invalid`（请求体不是合法 JSON 对象）、`appearance.version.unsupported`、`appearance.too_large`、`db.error`。
- `background` 枚举：`default`、`cross`、`left-diagonal`、`right-diagonal`、`aurora`、`horizon`、`glow`、`mesh`、`repeat-image-1` ~ `repeat-image-4`。

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

### 1.14 当前登录身份

- **路径**：`/api/user/whoami`
- **方法**：GET
- **认证**：无需认证（未登录且不允许游客阅读时返回 `user.need_login`）
- **参数**：无
- **响应**：
  - `err` (string): `ok` / `user.need_login`
  - `userId` (int): 用户ID；游客阅读模式下固定为 `999999`
  - `username` (string): 用户名（游客无此字段）
  - `canRead` (bool): 是否有在线阅读权限
  - `isActive` (bool): 账号是否已激活
  - `is_guest` (bool): 是否为游客（`ALLOW_GUEST_READ` 开启且未登录）
- **响应示例**：

```json
{
  "err": "ok",
  "userId": 3,
  "username": "reader",
  "canRead": true,
  "isActive": true,
  "is_guest": false
}
```

### 1.15 VIP 下载额度

- **路径**：`/api/user/vip`
- **方法**：GET
- **认证**：需要登录
- **参数**：无
- **响应**：
  - `vipquota` (int): VIP 额度；未开启 VIP 额度功能时为 `0`
  - `vip_expire` (string): 到期日期 `YYYY-MM-DD`，无则为空字符串
- **响应示例**：

```json
{
  "err": "ok",
  "vipquota": 20,
  "vip_expire": "2026-12-31"
}
```

### 1.16 在线阅读历史

- **路径**：`/api/user/history`
- **方法**：GET
- **认证**：需要登录
- **参数**：无
- **响应**：
  - `books` (array): 最近在线阅读的书籍（按最近阅读时间倒序，最多 12 本），字段同 Calibre 书籍数据，另含 `timestamp`（最近阅读时间，Unix 秒）、`img`、`thumb`、`href`
- **响应示例**：

```json
{
  "err": "ok",
  "books": [
    {"id": 42, "title": "三体", "timestamp": 1790000000, "img": "/get/cover/42.jpg?t=1790000000", "thumb": "...", "href": "/book/42"}
  ]
}
```

---

## 2. 用户消息、便签与设备

### 2.1 获取用户消息

- **路径**：`/api/user/messages`
- **方法**：GET
- **认证**：无需认证（未登录返回空列表）
- **参数**：无
- **说明**：只返回未读消息，按时间倒序；`status` 为消息级别（如 `success`、`error`）。
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
  - `value` (string, 必填): 作者名或标签名
- **响应**：`err`: `ok` / `params.invalid` / `already_pinned` / `limit_exceeded`（最多 50 个）/ `db.error`
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
  - `value` (string, 必填): 作者名或标签名
- **响应**：`err`: `ok` / `params.invalid` / `not_found` / `db.error`
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
- **说明**：该接口是“全量替换”模型——没有单个设备的 `id`，GET 返回当前用户的全部设备列表，POST 时必须提交完整的设备列表（包含要保留的所有设备），服务端会先清空该用户的所有设备记录再写入。要删除某个设备，只需在 POST 时省略它；要清空所有设备，POST 一个空数组。

支持的设备类型（`type` 字段）共 8 种，按数据模型可分为三组：

| 分组 | `type` 取值 | 额外字段 |
|---|---|---|
| Kindle 邮箱推送 | `kindle` | `mailbox` |
| WiFi 局域网传输（数据模型相同） | `duokan`（多看）、`ireader`（爱阅读）、`hanwang`（汉王）、`boox`（文石）、`dangdang`（当当）、`purelibro` | `ip`、`port`、`schema` |
| FTP 传输 | `ftp` | `ip`、`port`、`ftp_username`、`ftp_password`、`ftp_path` |

> 注：`type` 字段当前未做白名单校验（任意字符串都会被存储，省略时默认为 `duokan`）；类型校验仅在实际推送书籍的 `/api/book/<id>/send_to_device` 接口中执行。

#### GET 获取设备列表

- **参数**：无
- **响应**：`devices` 为数组，每个元素的字段取决于设备类型：
  - 所有类型通用：`name`、`type`、`ip`、`port`、`schema`、`mailbox`
  - 仅 `ftp` 类型额外返回：`ftp_username`、`ftp_password`、`ftp_path`（此时 `mailbox` 字段固定为空字符串）

**Kindle 设备响应示例**：

```json
{
  "err": "ok",
  "devices": [
    {
      "name": "我的Kindle",
      "type": "kindle",
      "ip": "",
      "port": 12121,
      "schema": "http",
      "mailbox": "user@kindle.com"
    }
  ]
}
```

**WiFi 传输设备响应示例**（duokan/ireader/hanwang/boox/dangdang/purelibro 共用此结构）：

```json
{
  "err": "ok",
  "devices": [
    {
      "name": "客厅的多看",
      "type": "duokan",
      "ip": "192.168.1.100",
      "port": 8080,
      "schema": "http",
      "mailbox": ""
    }
  ]
}
```

**FTP 设备响应示例**：

```json
{
  "err": "ok",
  "devices": [
    {
      "name": "NAS",
      "type": "ftp",
      "ip": "192.168.1.50",
      "port": 21,
      "schema": "http",
      "mailbox": "",
      "ftp_username": "admin",
      "ftp_password": "123456",
      "ftp_path": "/books"
    }
  ]
}
```

#### POST 保存设备列表（全量覆盖）

- **参数**（JSON）：
  - `devices` (array, 必填): 完整的设备列表，每个元素：
    - `type` (string, 选填): `kindle` / `duokan` / `ireader` / `hanwang` / `boox` / `dangdang` / `purelibro` / `ftp`，默认 `duokan`
    - `name` (string, 选填): 设备名称，默认空字符串
    - `mailbox` (string, 选填): 仅 `kindle` 类型使用，存放 Kindle 推送邮箱
    - `ip` (string, 选填): 仅 WiFi 传输类、`ftp` 类型使用，默认空字符串
    - `port` (int, 选填): 仅 WiFi 传输类、`ftp` 类型使用，默认 `12121`
    - `schema` (string, 选填): 仅 WiFi 传输类使用，`http`/`https`，默认 `http`
    - `ftp_username` (string, 选填): 仅 `ftp` 类型使用
    - `ftp_password` (string, 选填): 仅 `ftp` 类型使用
    - `ftp_path` (string, 选填): 仅 `ftp` 类型使用，序列化后的 FTP 配置总长度不可超过 2048 字符

**请求示例**（同时保留一个 Kindle、一个多看、一个 FTP 设备）：

```json
{
  "devices": [
    { "type": "kindle", "name": "我的Kindle", "mailbox": "user@kindle.com" },
    { "type": "duokan", "name": "客厅的多看", "ip": "192.168.1.100", "port": 8080, "schema": "http" },
    { "type": "ftp", "name": "NAS", "ip": "192.168.1.50", "port": 21, "ftp_username": "admin", "ftp_password": "123456", "ftp_path": "/books" }
  ]
}
```

- **响应示例**（成功时不返回 `devices`，需重新 GET 获取最新列表）：

```json
{
  "err": "ok",
  "msg": "设备保存成功"
}
```

- **错误响应**：
  - 请求体非合法 JSON 或 `devices` 不是数组：`{"err": "params.invalid", "msg": "参数无效"}`
  - FTP 配置序列化后超过 2048 字符：`{"err": "params.invalid", "msg": "FTP配置信息过长"}`
  - 数据库写入失败：`{"err": "db.error", "msg": "数据库操作异常，请重试"}`
  - 未登录：`{"err": "user.need_login", "msg": "请先登录"}`

### 2.7 期望获得的书籍（求书登记）

#### GET 获取登记列表

- **路径**：`/api/user/expected`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `user` (string, 可选, 仅管理员): 查看指定用户ID的登记；`0` 表示全部用户（同时返回用户名映射）
- **响应**：`data.items` (array): `{id, title, author, publisher, create_time, reader_id, reader_name}`（按登记时间倒序）；`data.is_admin` (bool)；`data.users` (object): `{reader_id: 用户名}`

#### POST 新增登记

- **路径**：`/api/user/expected`
- **方法**：POST
- **认证**：需要登录
- **参数**：JSON Body：`title` (string, 必填)、`author` (string, 可选)、`publisher` (string, 可选)
- **响应**：`err`: `ok` / `params.invalid` / `params.title.required` / `params.title.too_long` / `db.error`；成功时 `item` 为新登记项

#### DELETE 删除登记

- **路径**：`/api/user/expected`
- **方法**：DELETE
- **认证**：需要登录
- **参数**：JSON Body：`id` (int, 必填)
- **响应**：`err`: `ok` / `params.invalid` / `params.id.required` / `not_found` / `db.error`
- **响应示例**（GET）：

```json
{
  "err": "ok",
  "data": {
    "items": [{"id": 1, "title": "三体II", "author": "刘慈欣", "publisher": "", "create_time": "2026-05-11 10:00:00", "reader_id": 3, "reader_name": "3"}],
    "is_admin": false,
    "users": {}
  }
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

### 2.9 用户留言

用户给管理员的留言/反馈，管理员可回复并处理。`memo_type`: 0/1/2（留言类型）；`stage`: `new`（新留言）/ `suspend`（挂起）/ `done`（已处理）。

#### GET 留言列表

- **路径**：`/api/user/memo`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `user` (string, 可选, 仅管理员): 指定用户ID；`0` 表示全部用户
  - `page` (int, 可选): 默认 1
  - `page_size` (int, 可选): 默认 20，范围 1~100
- **响应**：`data.items` (array): `{id, reader_id, reader_name, memo, memo_type, reply, stage, create_date, update_date}`；`data.total`；`data.users`（管理员查看全部时的用户名映射）

#### POST 新增/修改/处理留言

- **路径**：`/api/user/memo`
- **方法**：POST
- **认证**：无需认证（游客也可留言，每日上限游客 20 条、登录用户 10 条）
- **参数**（JSON Body）：
  - 新增：`memo` (string, 必填，≤2048 字符)、`memo_type` (int, 可选, 0/1/2)
  - 修改：带 `id`，可改 `memo`、`memo_type`（留言者本人或管理员）
  - 处理（仅管理员）：带 `id` 与 `action`（`done` / `suspend`）及可选 `reply`（缺省为“完成”）；处理为 `done` 时会给留言用户发送站内消息
- **响应**：`err`: `ok` / `params.invalid` / `params.memo.required` / `params.memo.too_long` / `params.memo_type.invalid` / `limit.exceeded` / `not_found` / `param.invalid` / `permission.denied` / `db.error`；新增成功时 `data` 为新留言
- **响应示例**（GET）：

```json
{
  "err": "ok",
  "data": {
    "items": [{"id": 1, "reader_id": 3, "reader_name": "3", "memo": "希望增加……", "memo_type": 0, "reply": null, "stage": "new", "create_date": "2026-05-11 10:00:00", "update_date": ""}],
    "total": 1,
    "users": {}
  }
}
```

### 2.10 首页阅读统计

- **路径**：`/api/user/reading_stats`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `uid` (query, 可选，仅管理员可用): 指定要查看的用户ID。普通用户传此参数会返回 `permission denied`；不传则默认查询当前登录用户自己的统计数据
- **说明**：
  - 该接口是首页“阅读统计”Banner 的数据源（详见 `document/Reading_Dashboard_Design.md`）。功能受配置项 `ENABLE_HOMEPAGE_READING_STATS` 控制（默认开启），关闭时接口仍返回 200，但仅含 `enabled: false`，不含其余字段
  - `weekly` 中每周的起止按自然周（周一为一周起点）划分，历史（昨天及以前）数据按用户读取每日缓存文件聚合得出、每天最多重建一次；当天（今天）的数据始终来自实时查询，不做缓存
  - `totals` 中的三个字段是账号维度的累计计数器（存储在 `Reader` 表上），不受 `weekly` 时间窗口限制
  - `book_status` 为实时查询结果，不做缓存
- **响应示例（功能开启，正常返回）**：

```json
{
  "err": "ok",
  "enabled": true,
  "totals": {
    "total_reading_seconds": 123456,
    "download_count": 12,
    "push_count": 3
  },
  "weekly": [
    { "week_start": "2026-06-15", "reading_seconds": 5400, "download_count": 1, "push_count": 0 },
    { "week_start": "2026-06-22", "reading_seconds": 3200, "download_count": 0, "push_count": 2 },
    { "week_start": "2026-06-29", "reading_seconds": 0,    "download_count": 0, "push_count": 0 },
    { "week_start": "2026-07-06", "reading_seconds": 7100, "download_count": 2, "push_count": 0 },
    { "week_start": "2026-07-13", "reading_seconds": 4500, "download_count": 0, "push_count": 1 },
    { "week_start": "2026-07-20", "reading_seconds": 6300, "download_count": 1, "push_count": 0 },
    { "week_start": "2026-07-27", "reading_seconds": 2900, "download_count": 0, "push_count": 0 },
    { "week_start": "2026-08-03", "reading_seconds": 1200, "download_count": 0, "push_count": 0 }
  ],
  "book_status": {
    "reading": 3,
    "to_read": 12,
    "finished": 27
  }
}
```

**字段说明**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `err` | string | 固定为 `"ok"`（异常/无权限时见下方错误响应） |
| `enabled` | boolean | 阅读统计功能总开关（`ENABLE_HOMEPAGE_READING_STATS`）当前是否启用。为 `false` 时，响应中**不包含** `totals`/`weekly`/`book_status` 字段 |
| `totals` | object | 账号累计统计（读取自 `Reader` 表对应字段，与统计周期无关） |
| `totals.total_reading_seconds` | integer | 累计在线阅读时长，单位：秒 |
| `totals.download_count` | integer | 累计下载次数 |
| `totals.push_count` | integer | 累计推送次数（推送到设备/邮箱）。注意：该字段是后续版本新增的，历史数据未回填，仅统计功能上线后产生的推送 |
| `weekly` | array | 最近 8 个自然周的统计数据，按周一为起点、时间正序排列（最早的一周在前，最后一项为本周至今的数据） |
| `weekly[].week_start` | string (`YYYY-MM-DD`) | 该周的起始日期（周一） |
| `weekly[].reading_seconds` | integer | 该周阅读时长，单位：秒 |
| `weekly[].download_count` | integer | 该周下载次数 |
| `weekly[].push_count` | integer | 该周推送次数 |
| `book_status` | object | 当前图书状态分布（基于阅读状态表实时统计，不含缓存） |
| `book_status.reading` | integer | 「在读」图书数量 |
| `book_status.to_read` | integer | 「想读」图书数量（已标记 wants 但尚未开始/完成阅读） |
| `book_status.finished` | integer | 「已读完」图书数量 |

- **响应示例（功能关闭）**：

```json
{
  "err": "ok",
  "enabled": false
}
```

- **错误响应示例**：

```json
{ "err": "failed", "msg": "permission denied" }
```

```json
{ "err": "failed", "msg": "user not found" }
```

```json
{ "err": "user.need_login", "msg": "请先登录" }
```

### 2.11 获取资源站点图标

- **路径**：`/api/favicon/<filename>`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `filename` (path, 必填): 图标文件名，形如 `<域名>.ico` / `<域名>.svg`（不能包含 `/`、`\`、`..`）
- **响应**：图标文件（`Content-Type` 按扩展名，缓存 1 天）；文件不存在或为空返回 HTTP 404，非法文件名返回 HTTP 400。图标地址由 6.34 推荐资源站点接口返回。

---

## 3. 图书基础接口

### 3.1 首页图书列表

- **路径**：`/api/index`
- **方法**：GET
- **认证**：无需认证（登录后结果个性化）
- **参数**：
  - `random` (int, 可选): “随便看看”数量，默认且最大为 `MAIN_PAGE_RANDOM_COUNT`（12）
  - `recent` (int, 可选): “新书推荐”数量，默认 `MAIN_PAGE_RECENT_COUNT`（12），最大 200
  - `refresh` (string, 可选): `1` 表示用户主动换一批（不使用按时间段固定的种子）
  - `seed` (string, 可选): 指定推荐随机种子（复现同一批结果）
  - `exclude` (string, 可选): 逗号分隔的书籍ID，当前已展示的书，下一批尽量避开
  - `personalized` (string, 可选): `0` 关闭个性化推荐引擎，退化为随机选取
- **响应**：
  - `err` (string): `ok` / `nobooks`（书库为空）
  - `random_books` / `new_books` (array): 图书对象；由推荐引擎产生时带 `reason: {type, value}`（推荐理由）
  - `random_books_count` / `new_books_count` (int)
  - `social_recommend_books` (array): 其他用户最近 90 天推荐（评价）的书，带 `recommender: {nickname, avatar}`；游客或用户关闭“首页推荐”时为空
  - `seed` (string): 本次使用的推荐种子（未使用推荐引擎时为空）
- **响应示例**：

```json
{
  "err": "ok",
  "random_books_count": 12,
  "new_books_count": 12,
  "random_books": [{"id": 42, "title": "三体", "reason": {"type": "author", "value": "刘慈欣"}, "...": "..."}],
  "new_books": [...],
  "social_recommend_books": [],
  "seed": "1790000000000000000"
}
```

### 3.2 搜索图书

- **路径**：`/api/search`
- **方法**：GET
- **认证**：无需认证（结果会排除被其他用户标记为 sole 的书）
- **参数**（`name`、`title`、`author`、`isbn`、`publisher`、`series`、`tag` 至少一个）：
  - `name` (string, 可选): 搜索内容，后台自动识别三种形式：
    - 纯 ISBN（10/13 位，可含 `-`）→ 按 ISBN 精确查找
    - Calibre 条件表达式（含 `字段:`，字段为 Calibre 内置搜索字段或 `#` 开头的自定义列），如 `title:=三体`、`authors:余华 AND rating:>=4`、`#category:="小说"` → 原样交给 Calibre，并追加简繁体转换版本以 OR 合并
    - 其它 → 关键字，在所有字段中模糊搜索（含简繁体转换）
  - `title` (string, 可选): 书名精确匹配（单独使用时即"只按书名搜索"）
  - `author` / `publisher` / `series` / `tag` (string, 可选): 对应字段包含匹配
  - `isbn` (string, 可选): ISBN，可带 `-`
  - `exact` (int, 可选): `1` 时 author/publisher/series/tag 改为精确匹配，默认 `0`
  - `seg` (int, 可选): `1` 时对 `title` 做中文分词搜索（需 jieba），默认 `0`
  - `exclude` (int, 可选): 结果中排除的书籍 ID
  - `order` (string, 可选): 排序字段，如 `pubdate`、`rating`、`timestamp`
  - `start` (int, 可选): 偏移量，默认 0
  - `size` (int, 可选): 每页数量，默认 `DEFAULT_PAGE_SIZE`（至少 60），最大 1000
- **组合规则**：提供任一字段参数（author/isbn/publisher/series/tag）时进入组合模式，`name`、`title` 与各字段条件之间为 AND 关系。
- **响应**：标准图书列表（见[图书对象结构](#图书对象结构)）
  - `err` (string): `ok` 或 `params.invalid`（未提供任何搜索条件）
  - `title` (string): 结果标题，如 `搜索作者:余华 出版社:作家出版社`
  - `total` (int): 命中总数
  - `books` (array): 当前页图书对象

```json
{
  "err": "ok",
  "title": "搜索作者:余华",
  "total": 12,
  "books": [...]
}
```

### 3.3 最近添加的图书

- **路径**：`/api/recent`（`/api/all` 相同）
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `start` (int, 可选): 偏移量，默认 0
  - `size` (int, 可选): 每页数量，默认 `DEFAULT_PAGE_SIZE`（至少 60），最大 1000
- **响应**：标准图书列表：`title`、`total`、`books`（图书对象，见[图书对象结构](#图书对象结构)）；按书籍ID倒序
- **响应示例**：

```json
{
  "err": "ok",
  "title": "新书推荐",
  "total": 1000,
  "books": [...]
}
```

### 3.4 所有图书

- **路径**：`/api/all`
- **方法**：GET
- **认证**：无需认证
- **参数**：同 3.3
- **响应**：同 3.3

### 3.5 热门图书

- **路径**：`/api/hot`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `start` (int, 可选): 偏移量，默认 0（每页固定 60 本）
- **响应**：标准图书列表：`title`、`total`、`books`（图书对象，见[图书对象结构](#图书对象结构)）；按访问次数倒序，只包含访问次数 >1 的书

### 3.6 实体书列表

- **路径**：`/api/printbooks`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `start` (int, 可选): 偏移量，默认 0（每页 `DEFAULT_PAGE_SIZE` 本）
- **响应**：`title`、`total`、`books`；按添加时间倒序；`err` 出错时为 `internal`

### 3.7 我的私有书籍

- **路径**：`/api/soledbooks`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `start` (int, 可选): 偏移量，默认 0（每页固定 60 本）
- **说明**：返回当前用户上传并标记为私有（sole）的书籍。
- **响应**：`title`、`total`、`books`；`err` 出错时为 `internal`

### 3.8 图书导航信息

- **路径**：`/api/book/nav`
- **方法**：GET
- **认证**：无需认证
- **参数**：无
- **说明**：按系统设置 `BOOK_NAV`（每行 `分组=标签1/标签2`）组织标签导航，未归组的标签放入“其它”；只包含有书的标签。
- **响应**：`navs` (array): `{legend, tags: [{name, count}]}`
- **响应示例**：

```json
{
  "err": "ok",
  "navs": [
    {"legend": "文学", "tags": [{"name": "小说", "count": 120}]},
    {"legend": "其它", "tags": [{"name": "传记", "count": 8}]}
  ]
}
```

### 3.9 获取图书详情

- **路径**：`/api/book/<id>`
- **方法**：GET
- **认证**：无需认证（登录后返回当前用户的阅读状态与阅读统计）
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应**：
  - `err` (string): `ok` / `params.book.invalid`
  - `book` (object): 完整图书对象（含文件列表 `files` 与当前用户权限 `permissions` 等），见[图书对象结构](#图书对象结构)；另含 `state`（阅读状态）、`reading_stats`（当前用户分格式阅读统计，见 3.49，未登录为空数组）
  - `kindle_sender` (string): 推送 Kindle 时使用的发件邮箱（需加入 Kindle 信任列表）
  - `audios` (object): 有声书信息
- **响应示例**：

```json
{
  "err": "ok",
  "kindle_sender": "sender@example.com",
  "book": {"id": 42, "title": "三体", "state": {"read_state": 1, "...": "..."}, "reading_stats": [...], "...": "..."},
  "audios": {}
}
```

### 3.10 删除图书

- **路径**：`/api/book/<id>/delete`
- **方法**：POST
- **认证**：需要登录，且用户有编辑和删除权限，并且是管理员或书籍所有者
- **参数**：
  - `id` (path, 必填): 图书ID
- **说明**：同时清理该书的有声书文件；书籍进入 Calibre 回收站（可在 6.29 恢复）。
- **响应**：`err`: `ok` / `permission` / `fail`
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
- **认证**：同 3.10
- **参数**：
  - `id` (path, 必填): 图书ID
  - JSON Body：`format` (string, 必填): 格式，如 `epub`、`pdf`
- **响应**：`err`: `ok` / `params.book.invalid` / `permission` / `params.invalid` / `params.missing` / `format.not_found`（不含该格式）/ `last.format`（只剩一个格式，不能删除）/ `fail`
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "删除epub格式成功"
}
```

### 3.12 编辑图书元数据

- **路径**：`/api/book/<id>/edit`
- **方法**：POST
- **认证**：需要登录，且用户有编辑权限，并且是管理员或书籍所有者
- **参数**：
  - `id` (path, 必填): 图书ID
  - JSON Body（只修改传入的字段）：
    - `title` (string)、`authors` (array[string])、`comments` (string，非 HTML 时换行转为 `<br/>`)、`tags` (array[string]，空数组清空标签)、`publisher` (string)、`isbn` (string)、`series` (string)、`series_index` (number)、`rating` (number, 0~10)、`languages` (array[string])、`translators` (array[string])
    - `pubdate` (string): `2026-05-10` / `2026-05` / `2026年` / `2026`
    - `category` (string): 分类，<80 字符，`清除`/`clear` 表示清空
    - `ext_link` (string): 外部链接，<500 字符，须为 http(s) 或空
    - `location` (string): 实体书位置，<64 字符
    - `book_count` (int) + `book_type` (int): 同时传入时设置书籍类型（0=电子书，1=实体书）及实体书数量
    - `ids` (array[int], 可选): 批量编辑——当其中包含路径中的 `id` 时，把同样的修改应用到 `ids` 中的每本书
- **说明**：作者名中的 `.` 会替换为 `·`；开启动态封面且书名变化时自动重新生成封面。
- **响应**：
  - `err` (string): `ok` / `params.book.invalid` / `permission` / `params.pudate.invalid`（出版日期格式错误）
  - `books` (array[int]): 本次处理的书籍ID
  - 注意：保存失败时 `err` 仍为 `ok`，需看 `msg`（“更新失败…”）
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "更新成功",
  "books": [42]
}
```

### 3.13 下载图书文件

- **路径**：`/api/book/<id>.<ext>`
- **方法**：GET
- **认证**：`ALLOW_GUEST_DOWNLOAD` 关闭时需要登录（网页请求重定向到 `/login`；`from=opds` 时返回 HTTP 401 Basic 认证）；已登录用户需有下载权限且账号已激活
- **参数**：
  - `id` (path, 必填): 图书ID
  - `ext` (path, 必填): 文件格式，如 `epub`、`pdf`、`mobi`
  - `from` (string, 可选): `opds` 表示来自 OPDS 客户端
- **说明**：登录用户每次下载消耗一次当日下载配额（见 3.55），超限返回 HTTP 429；同时记录下载统计。
- **响应**：文件内容（二进制）；书籍或格式不存在返回 HTTP 404

### 3.14 联网元数据（候选与套用）

#### GET 联网搜索候选元数据

- **路径**：`/api/book/<id>/refer`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
  - `title` / `isbn` / `publisher` (string, 可选): 搜索条件；title 与 isbn 都不传时取书籍当前元数据
- **说明**：结果按搜索条件缓存；并发搜索受限，超时时间 `REFER_SEARCH_TIMEOUT`（默认 60 秒）。
- **响应**：
  - `err` (string): `ok` / `timeout` / `search.failed`（后两者会带回可用的缓存结果）
  - `books` (array): 候选元数据：`cover_url`、`source`、`website`、`title`、`authors`、`author_sort`、`publisher`、`comments`、`provider_key`、`provider_value`、`isbn`、`isbn13`、`language`、`identifiers`、`tags`、`series`、`rating`、`pubyear`、`pubdate`（空值字段会被省略）
  - `cached` (bool): 是否命中缓存
- **响应示例**：

```json
{
  "err": "ok",
  "books": [{"title": "三体", "authors": ["刘慈欣"], "publisher": "重庆出版社", "provider_key": "douban", "provider_value": "2567698", "pubdate": "2008-01-01", "pubyear": "2008", "...": "..."}]
}
```

#### POST 套用联网元数据

- **路径**：`/api/book/<id>/refer`
- **方法**：POST（参数为 query/表单）
- **认证**：需要登录，且用户有编辑权限，并且是管理员或书籍所有者
- **参数**：
  - `id` (path, 必填): 图书ID
  - `provider_key` (string, 必填): 数据源，取 GET 结果中的 `provider_key`
  - `provider_value` (string, 必填): 数据源中的ID，取 GET 结果中的 `provider_value`
  - `metadata` (string, 可选): GET 结果中某个候选的 JSON 字符串（非豆瓣源时直接使用）
  - `only_meta` / `only_cover` / `only_author_comments` (string, 可选): 取 `yes` 时只更新元数据（不含封面）/ 只更新封面 / 只更新作者与简介；三者最多一个为 `yes`
  - `reset` (string, 可选): `yes` 时忽略以上参数，改为从电子书文件内重新读取元数据
- **响应**：`err`: `ok` / `permission` / `user.no_permission` / `params.book.invalid` / `params.invalid`（metadata 不是合法 JSON）/ `params.provider_key.invalid` / `params.conflict` / `plugin.no_result` / `plugin.no_cover` / `plugin.fail`

### 3.15 推送图书到设备

- **路径**：`/api/book/<id>/send_to_device`
- **方法**：POST
- **认证**：`ALLOW_GUEST_PUSH` 关闭时需要登录，且有推送权限、账号已激活
- **参数**：
  - `id` (path, 必填): 图书ID
  - JSON Body：
    - `device_type` (string, 必填): `duokan`、`ireader`、`hanwang`、`boox`、`dangdang`、`kindle`、`purelibro`、`ftp`、`koreader`
    - `device_url` (string): 设备地址（IP/URL，未带协议时补 `http://`）；除 `kindle` 外必填，不允许 `127.` 开头的本机地址
    - `mailbox` (string): Kindle 接收邮箱，`kindle` 时必填
    - `ftp_path` (string): FTP 目录，`ftp` 时必填；`ftp_username`、`ftp_password` (string, 可选)
- **说明**：Kindle 通过邮件推送（优先 epub/pdf/txt，只有 azw3/mobi 时先转换）；其它设备按 epub → azw3 → pdf → txt 选择文件上传。
- **响应**：`err`: `ok` / `book.not_found` / `user.need_login` / `permission` / `params.invalid` / `params.missing` / `device.unsupported` / `format.not_supported` / `file.not_found` / `file.missing` / `connection.failed` / `upload.timeout` / `upload.failed` / `upload.error` / `ftp.auth_failed` / `ftp.path_not_found` / `ftp.upload_failed`
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "书籍发送成功"
}
```

### 3.16 发送图书到邮箱

- **路径**：`/api/book/<id>/mailto`
- **方法**：POST
- **认证**：`ALLOW_GUEST_PUSH` 关闭时需要登录，且有推送权限、账号已激活
- **参数**：
  - `id` (path, 必填): 图书ID
  - JSON Body：
    - `email` (string, 必填): 目标邮箱
    - `format` (string, 可选): `epub`/`azw3`/`pdf`/`mobi`/`txt`；不传时按此顺序选第一个存在的格式
- **说明**：附件不能超过 50MB；后台异步发送，并记住为用户的最近分享邮箱。
- **响应**：`err`: `ok` / `book.not_found` / `user.need_login` / `permission` / `params.invalid` / `params.missing` / `email.invalid` / `format.not_found` / `file.missing` / `file.too_large`
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "后台正在推送，稍后可以刷新页面，在通知消息中查看结果。"
}
```

### 3.17 在线阅读图书

#### GET 打开阅读器

- **路径**：`/api/book/<id>/read`（同 `/read/<id>`）
- **方法**：GET
- **认证**：`ALLOW_GUEST_READ` 关闭时需要登录；已登录用户需有阅读权限且账号已激活
- **参数**：
  - `id` (path, 必填): 图书ID
  - `format` (string, 可选): 指定阅读格式 `epub`/`pdf`/`mobi`/`azw`/`azw3`/`txt`；不传时按 epub → mobi → azw → azw3 → txt → pdf 优先级选择
- **响应**：HTML 阅读页面或重定向（非 JSON）：
  - 阅读器设置为 MyReader 且格式为 epub/pdf → 302 到 `/readerx/open?bookId=<id>&format=<fmt>`
  - pdf → 302 到 `PDF_VIEWER` 配置的阅读器；txt → 302 到 `/read/txt/<id>`
  - 非 epub 的 mobi/azw/azw3/txt 会在后台自动转换为 epub
  - 不支持的格式返回 HTTP 404；无权限返回 HTTP 403
  - 登录用户每次打开会记录一次阅读心跳（分格式阅读统计）

#### POST 检查阅读格式是否就绪

- **路径**：`/api/book/<id>/read`
- **方法**：POST
- **认证**：同上（以 JSON 错误码返回）
- **参数**：
  - `id` (path, 必填): 图书ID
  - JSON Body 或 query：`format` (string, 可选): 目标格式
- **响应**：
  - `err` (string): `ok` / `user.need_login` / `user.no_permission` / `params.book.invalid`
  - `data.status` (string): `ready`（可直接打开）/ `converting`（已启动或正在执行转换 epub 的任务）
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "正在执行转换任务，请稍候...",
  "data": {"status": "converting"}
}
```

### 3.18 在线阅读TXT内容

- **路径**：`/api/read/txt/<id>`
- **方法**：GET
- **认证**：需要登录（且有阅读权限、账号已激活）
- **参数**：
  - `id` (path, 必填): 图书ID（必须有 TXT 格式）
  - `start` (int, 可选): 起始字节偏移，默认 0
  - `end` (int, 可选): 结束字节偏移，默认 -1（读到文件末尾）
- **响应**：
  - `err` (string): `ok` / `params.book.invalid` / `format error`（非 TXT 书籍或空文件）/ `user.no_permission`
  - `content` (string): 自动识别编码后的文本，换行替换为 `<br>`
- **响应示例**：

```json
{
  "err": "ok",
  "content": "第一章 ……<br>正文……"
}
```

### 3.19 解析TXT目录

- **路径**：`/api/book/txt/parser`
- **方法**：GET
- **认证**：`ALLOW_GUEST_READ` 关闭时需要登录；已登录用户需有阅读权限
- **参数**：
  - `id` (int, 必填): 图书ID（必须有 TXT 格式）
  - `test` (string, 可选): 非 `"0"` 时只检查是否已解析，不触发解析；`"0"` 时未解析则加入解析队列
- **响应**：
  - 已解析：`msg="parsed"`，`data.content`（目录）、`data.encoding`（文件编码）、`data.name`（书名）
  - 未解析且 `test` 非 `0`：`msg="not parsed"`
  - 已加入队列：`data.wait`（预计等待秒数）、`data.name`、`data.path`、`data.que`（队列长度）
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "parsed",
  "data": {"content": [...], "encoding": "gb18030", "name": "某本书"}
}
```

### 3.20 转换图书格式

- **路径**：`/api/book/<id>/convert`
- **方法**：POST
- **认证**：需要登录；管理员或书籍所有者
- **参数**：
  - `id` (path, 必填): 图书ID
- **说明**：目标格式自动决定：首个格式为 epub 时转 azw3，否则转 epub；有 docx 时以 docx 为源。已同时有 EPUB 与 AZW3 时不转换。后台异步执行。
- **响应**：`err`: `ok` / `params.book.invalid`（书籍不存在或无需转换）/ `user.no_permission` / `params.book.converting`（正在转换中）
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
- **认证**：需要登录；管理员或书籍所有者
- **参数**：
  - `id` (path, 必填): 图书ID
- **说明**：按 epub → azw3 → mobi → azw → docx 选择源文件；已有 PDF 时不转换。后台异步执行。
- **响应**：`err`: `ok` / `params.book.invalid` / `user.no_permission` / `params.book.converting`

### 3.22 获取电子书文件路径

- **路径**：`/api/book/<id>/filepath`
- **方法**：GET
- **认证**：`ALLOW_GUEST_READ` 关闭时需要登录；已登录用户需有阅读权限且账号已激活
- **参数**：
  - `id` (path, 必填): 图书ID
  - `format` (string, 必填): `epub` 或 `pdf`
- **响应**：
  - `err` (string): `ok` / `params.format.invalid`（format 不是 epub/pdf）/ `params.format.unavailable`（该格式不存在）/ `params.book.invalid`
  - `data.path` (string): 该格式文件在服务器上的路径（供内嵌阅读器使用）
- **响应示例**：

```json
{
  "err": "ok",
  "data": {"path": "/data/books/library/刘慈欣/三体 (42)/三体 - 刘慈欣.epub"}
}
```

### 3.23 切换私有（sole）状态

- **路径**：`/api/book/<id>/setsole`
- **方法**：POST
- **认证**：需要登录，且用户有编辑权限，并且是管理员或书籍所有者
- **参数**：
  - `id` (path, 必填): 图书ID
- **说明**：在私有/公开之间切换（无需传值）。私有书籍对其他用户隐藏（搜索等列表中排除）。
- **响应**：`err`: `ok` / `params.book.invalid` / `permission` / `db.update.failed`
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "更新成功"
}
```

### 3.24 更新图书封面

- **路径**：`/api/book/<id>/cover`
- **方法**：POST（`multipart/form-data`）
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
  - 表单文件：`cover_data` (file, 可选): 封面图片（webp 自动转 jpeg）；**不传时按书名/作者生成默认封面**
- **说明**：封面图片的读取走 `/get/cover/<id>.jpg`、`/get/thumb_<w>_<h>/<id>.jpg` 静态路由。
- **响应**：`err`: `ok` / `params.book.invalid` / `params.cover.invalid` / `cover.generate_failed`

### 3.25 添加/取消收藏

- **路径**：`/api/book/<id>/favorite`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
  - JSON Body：`favorite` (bool, 可选): `true` 收藏 / `false` 取消收藏，缺省为 `false`
- **响应**：`err`: `ok` / `params.book.invalid`
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
  - JSON Body：`wants` (bool, 可选): `true` 标记待读 / `false` 取消，缺省为 `false`
- **响应**：`err`: `ok` / `params.book.invalid`

### 3.27 阅读状态

#### POST 设置阅读状态

- **路径**：`/api/book/<id>/readstate`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
  - JSON Body：
    - `read_state` (int, 可选): 0=未读，1=在读，2=已读完，缺省为 0
    - `online_read` (int/bool, 可选): 传入时一并更新“在线阅读过”标记
    - `download` (int/bool, 可选): 传入时一并更新“下载过”标记
- **响应**：`err`: `ok` / `params.book.invalid` / `params.invalid`（read_state 不在 0~2）
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "阅读状态已设置为：在读"
}
```

#### GET 获取阅读状态

- **路径**：`/api/book/<id>/readstate`
- **方法**：GET
- **认证**：需要登录
- **参数**：`id` (path, 必填): 图书ID
- **响应**：当前用户对该书的阅读状态（字段同[图书对象结构](#图书对象结构)中的 `state`）

### 3.28 我的收藏

- **路径**：`/api/favorites`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `start` (int, 可选): 偏移量，默认 0
  - `size` (int, 可选): 每页数量，默认 `DEFAULT_PAGE_SIZE`，最大 100
- **响应**：`title`、`total`、`books`（按收藏时间倒序，每本带 `state`）
- **响应示例**：

```json
{
  "err": "ok",
  "title": "我的收藏",
  "total": 50,
  "books": [{"id": 42, "title": "三体", "state": {"favorite": 1, "...": "..."}, "...": "..."}]
}
```

### 3.29 我的待读

- **路径**：`/api/wants`
- **方法**：GET
- **认证**：需要登录
- **参数**：同 3.28（`start`、`size`，最大 100）
- **响应**：`title`、`total`、`books`（按标记时间倒序，每本带 `state`）

### 3.30 在读书籍

- **路径**：`/api/reading`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `start` (int, 可选): 偏移量，默认 0
  - `size` (int, 可选): 每页数量，默认 `DEFAULT_PAGE_SIZE`，最大 100
  - `home` (string, 可选): `1` 表示首页请求；`ENABLE_HOMEPAGE_READING_BOOKS` 关闭时直接返回空列表
- **响应**：`title`、`total`、`books`（按最近阅读时间倒序，每本带 `state`）

### 3.31 已读书籍

- **路径**：`/api/read-done`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `start` (int, 可选): 偏移量，默认 0（每页 `DEFAULT_PAGE_SIZE` 本）
- **响应**：`title`、`total`、`books`（按读完时间倒序，每本带 `state`）

### 3.32 阅读统计

- **路径**：`/api/reading/stats`
- **方法**：GET
- **认证**：需要登录
- **参数**：无
- **响应**：
  - `stats.total_reading` / `stats.total_read_done` (int): 在读 / 已读完总数
  - `stats.month_reading` / `stats.month_read_done` (int): 本月在读 / 本月读完数
  - `stats.current_year` / `stats.current_month` (int)
  - `current_reading_books` (array): 最近在读的最多 12 本（带 `state`）
  - `month_read_done_books` (array): 本月读完的最多 12 本（带 `state`）
- **响应示例**：

```json
{
  "err": "ok",
  "stats": {"total_reading": 5, "total_read_done": 42, "month_reading": 2, "month_read_done": 3, "current_year": 2026, "current_month": 9},
  "current_reading_books": [...],
  "month_read_done_books": [...]
}
```

### 3.33 联网更新图书标签

- **路径**：`/api/book/<id>/tags`
- **方法**：POST
- **认证**：需要登录；管理员或书籍所有者
- **参数**：
  - `id` (path, 必填): 图书ID
- **说明**：通过书栈（BookBarn）标签服务按 ISBN/书名/作者获取标签并覆盖原标签。
- **响应**：`err`: `ok`（含“无需更新”）/ `params.book.invalid` / `user.no_permission` / `plugin.missing` / `internal`
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "标签更新成功"
}
```

### 3.34 AI 填充图书信息

- **路径**：`/api/book/<id>/aifill`
- **方法**：POST
- **认证**：需要登录；管理员或书籍所有者
- **参数**：
  - `id` (path, 必填): 图书ID
- **说明**：同步调用 AI 更新该书的分类、标签、简介和作者介绍（强制更新）。
- **响应**：
  - `err` (string): `ok` / `params.book.invalid` / `user.no_permission` / `ai.fill.failed`
  - `category` (string)、`tags` (array[string]): 更新后的分类与标签
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "AI 更新成功",
  "category": "科幻",
  "tags": ["科幻", "长篇"]
}
```

### 3.35 按标签批量刷新标签

- **路径**：`/api/book/update_tags`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `tag` (string, 必填, query/表单): 标签名
- **说明**：对带有该标签的书（最多前 300 本）在后台联网重新获取标签。
- **响应**：
  - `err` (string): `ok` / `user.no_permission` / `params.invalid` / `internal`
  - `count` (int): 本次提交的书籍数；`total` (int): 找到的书籍总数
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "已提交 120 本书籍的标签更新任务，正在后台处理, 请稍后刷新查看结果",
  "count": 120,
  "total": 120
}
```

### 3.36 更新图书分类

- **路径**：`/api/book/<id>/category`
- **方法**：POST
- **认证**：需要登录；管理员或书籍所有者
- **参数**：
  - `id` (path, 必填): 图书ID
  - JSON Body：`category` (string, 必填): 分类名；`清除` 或 `clear` 表示清空
- **响应**：`err`: `ok` / `params.book.invalid` / `user.no_permission` / `internal`

### 3.37 批量更新分类

- **路径**：`/api/book/category`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - JSON Body：
    - `category` (string, 必填): 分类名
    - `author` / `tag` / `series` (string, 至少一个): 把该作者 / 标签 / 丛书下的全部书籍（精确匹配，多个条件取并集）设为此分类
- **响应**：
  - `err` (string): `ok` / `user.no_permission` / `params.category.empty` / `params.invalid` / `internal`
  - `count` (int): 更新的书籍数
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "成功更新 12 本书籍分类",
  "count": 12
}
```

### 3.38 获取所有分类

- **路径**：`/api/categories`
- **方法**：GET
- **认证**：无需认证
- **参数**：无
- **说明**：开启“阅读范围”设置时按当前用户的可读分类过滤（未登录返回空列表，管理员不过滤）。
- **响应**：`categories` (array): `{name, count}`，按书籍数降序；`err` 出错时为 `internal`
- **响应示例**：

```json
{
  "err": "ok",
  "categories": [{"name": "科幻", "count": 120}, {"name": "历史", "count": 80}]
}
```

### 3.39 标签自动完成

- **路径**：`/api/tags/search`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `q` (string, 可选): 标签名前缀；为空时返回书籍最多的标签
  - `limit` (int, 可选): 返回数量，默认 20，最大 50
- **响应**：`tags` (array): `{name, count}`，按书籍数降序
- **响应示例**：

```json
{
  "err": "ok",
  "tags": [{"name": "科幻", "count": 120}]
}
```

### 3.40 相关图书推荐

- **路径**：`/api/book/<id>/suggestion`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `id` (path, 必填): 图书ID
- **说明**：优先使用推荐引擎，无结果时退化为同标签/同作者的书。
- **响应**：`books` (array): 图书对象，带 `reason: {type, value}`（如 `same_tag`、`same_author`）
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "推荐成功",
  "books": [{"id": 43, "title": "球状闪电", "reason": {"type": "same_author", "value": "刘慈欣"}, "...": "..."}]
}
```

### 3.41 分离图书格式为新书

- **路径**：`/api/book/<id>/separate`
- **方法**：POST
- **认证**：需要登录，且用户有编辑权限，并且是管理员或书籍所有者
- **参数**：
  - `id` (path, 必填): 图书ID
  - JSON Body：`format` (string, 必填): 要分离出去的格式，如 `pdf`
- **说明**：把该格式从原书移出，按文件内元数据创建一本新书（原书至少要保留一个格式）。
- **响应**：
  - `err` (string): `ok` / `params.book.invalid` / `permission` / `params.invalid` / `params.missing` / `format.not_found` / `file.missing` / `last.format` / `book.invalid`（无法识别或 DRM）/ `book.create.failed` / `internal`
  - `original_book_id` (int)、`new_book_id` (int)
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "格式分离成功",
  "original_book_id": 42,
  "new_book_id": 1030
}
```

### 3.42 保存元数据到文件

- **路径**：`/api/book/<id>/savemeta`
- **方法**：POST
- **认证**：需要登录；管理员或书籍所有者
- **参数**：
  - `id` (path, 必填): 图书ID
  - `fmt` (string, 可选, query): 只处理某个格式 `epub`/`azw3`/`pdf`；不传时处理所有支持的格式
- **说明**：把书库中的元数据（书名、作者、封面等）写入电子书文件本身。
- **响应**：
  - `err` (string): `ok` / `user.no_permission` / `book.not_found` / `book.meta.not_found` / `format.not_supported`
  - `success_formats` / `failed_formats` (array[string]): 成功 / 失败的格式（大写）
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "...",
  "success_formats": ["EPUB"],
  "failed_formats": []
}
```

### 3.43 封面添加图章

- **路径**：`/api/book/<id>/addstamp`
- **方法**：POST
- **认证**：需要登录；管理员或书籍所有者；需开启图章功能（`ENABLE_STAMP_FEATURE`）并已上传图章图片（见 6.21）
- **参数**：
  - `id` (path, 必填): 图书ID
  - JSON Body：`position` (string, 可选): 图章位置，默认系统设置 `STAMP_POSITION`（`bottom-right`）
- **说明**：把图章叠加到封面，并尝试写回电子书文件（需要 EPUB/AZW3/PDF 格式）。
- **响应**：`err`: `ok`（部分格式写回失败时也为 ok，见 msg）/ `user.no_permission` / `feature.disabled` / `stamp.not_found` / `book.not_found` / `format.not_supported` / `cover.not_found` / `stamp.failed` / `error`

### 3.44 切换电子书/实体书类型

- **路径**：`/api/book/exchange_type`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - JSON Body：`idlist` (array[int], 必填): 书籍ID列表
- **说明**：逐本切换类型：电子书 → 实体书（要求有 ISBN 且没有电子书文件）；实体书 → 电子书。
- **响应**：
  - `err` (string): `ok` / `user.no_permission` / `params.invalid` / `db.error`
  - `success_count` / `skip_count` (int)
  - `results` (array): `{book_id, status, msg}`，`status` 为 `success` / `skip` / `not_found` / `error`
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "处理完成：成功 2 本，跳过 1 本",
  "success_count": 2,
  "skip_count": 1,
  "results": [{"book_id": 42, "status": "success", "msg": "已转为实体书"}]
}
```

### 3.45 清理稀有标签

- **路径**：`/api/clear_rare_tags`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：无
- **说明**：找出只有 1~2 本书使用的标签，对这些书在后台重新联网获取标签；书库少于 100 本时不处理。
- **响应**：
  - `err` (string): `ok` / `user.not_admin` / `error`
  - `book_count` (int)、`tag_count` (int): 涉及的书籍数与稀有标签数
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "开始更新 35 本书的标签，涉及 40 个稀少标签",
  "book_count": 35,
  "tag_count": 40
}
```

### 3.46 通过 ISBN 添加实体书

- **路径**：`/api/book/add`
- **方法**：POST
- **认证**：需要登录，且用户有上传权限
- **参数**：
  - JSON Body：`isbn` (string, 必填): ISBN
- **说明**：已存在该 ISBN 的实体书时数量 +1；否则联网查询元数据并创建实体书（需在系统设置中配置互联网信息源）。
- **响应**：
  - `err` (string): `ok` / `permission` / `params.invalid` / `book.notfound`（查不到该 ISBN）/ `book.duplicate` / `internal`
  - `book_id` (int)
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "图书添加成功",
  "book_id": 1024
}
```

### 3.47 上传图书

- **路径**：`/api/book/upload`
- **方法**：POST（`multipart/form-data`）
- **认证**：`ALLOW_GUEST_UPLOAD` 关闭时需要登录且有上传权限
- **参数**：
  - 表单文件：`ebook` (file, 必填): 电子书文件
  - `bid` (int, 可选, query/表单): 指定时把文件作为新格式添加到这本已有书籍（需管理员或书籍所有者）
  - `force` (string, 可选): 与 `bid` 同用，`1`/`true` 时覆盖已存在的同格式文件
  - `update_meta` (可选): 与 `bid` 同用；不传时用新文件的元数据更新书籍，**传入任意值即不更新**
- **响应**：
  - `err` (string): `ok` / `permission` / `params.filename` / `params.format.unsupported` / `book.invalid`（无法识别或 DRM）/ `samebook`（同名书已有该格式，带 `book_id`）/ `format.already_exists`（`bid` 模式下已有该格式，带 `book_id`）/ `book.not_found` / `user.no_permission` / `internal`
  - `book_id` (int)
- **响应示例**：

```json
{
  "err": "ok",
  "book_id": 1025
}
```

### 3.48 分块上传图书

- **路径**：`/api/book/upload/chunk`
- **方法**：POST（`multipart/form-data`）
- **认证**：同 3.47
- **参数**：
  - 表单文件：`chunk` (file, 必填): 当前分块数据
  - `filename` (string, 必填): 原始文件名（须含受支持的扩展名）
  - `chunk_index` (int, 必填): 分块序号，从 0 开始
  - `total_chunks` (int, 必填): 分块总数
  - `file_hash` (string, 必填): 文件哈希（8~128 位十六进制），用于归并同一文件的分块
- **说明**：文件超过系统设置 `CHUNK_UPLOAD_SIZE` 时前端改用分块上传；收齐所有分块后自动合并并导入。
- **响应**：
  - 未收齐：`{"err": "ok", "msg": "分块上传成功", "received_chunks": 3, "total_chunks": 10}`
  - 收齐并导入：同 3.47（`book_id` / `samebook` / `book.invalid` 等）
  - 其它错误：`params.filename` / `params.format.unsupported` / `params.hash` / `params.chunk` / `upload_error`

### 3.49 获取图书分格式阅读统计

- **路径**：`/api/book/<id>/reading_stats`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
  - `format` (query, 可选): 只查询指定格式（epub/pdf/mobi/azw3/txt 等，大小写不敏感，内部统一转小写）的统计数据；不传则返回该书籍下所有格式的统计
- **说明**：
  - 返回当前登录用户在该书籍下、按格式分别统计的阅读时长/进度/状态，与 `BookDetail` 接口内嵌的 `book["reading_stats"]` 同源
  - 只返回 `total_seconds > 10`（累计阅读时长超过10秒）的格式，按 `format` 字母序排列；从未产生有效阅读时长的格式不会出现在结果里。传了 `format` 但该格式尚无有效统计数据（或格式不存在）时，返回 `stats: []`，不会报错
  - 手动补记/纠正统计数据使用同路径的 POST 方法，见下方
- **响应示例**：

```json
{
  "err": "ok",
  "stats": [
    {
      "format": "epub",
      "state": 0,
      "total_seconds": 5460,
      "progress_current": 128,
      "progress_total": 320,
      "progress_percent": 40.0,
      "start_time": "2026-08-20T09:12:33Z",
      "finish_time": null,
      "start_count": 2,
      "update_time": "2026-08-30T13:05:11Z"
    },
    {
      "format": "pdf",
      "state": 1,
      "total_seconds": 9800,
      "progress_current": 200,
      "progress_total": 200,
      "progress_percent": 100.0,
      "start_time": "2026-07-01T02:00:00Z",
      "finish_time": "2026-07-10T11:30:00Z",
      "start_count": 1,
      "update_time": "2026-07-10T11:30:00Z"
    }
  ]
}
```

**字段说明**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `err` | string | 固定为 `"ok"` |
| `stats` | array | 按 `format` 字母序排列的分格式统计列表 |
| `stats[].format` | string | 书籍格式，统一小写（epub/pdf/mobi/azw3/txt 等） |
| `stats[].state` | integer | 阅读状态：`0`=在读，`1`=已完成 |
| `stats[].total_seconds` | integer | 该格式的累计阅读时长，单位：秒，跨轮次累加 |
| `stats[].progress_current` | integer \| null | 最近一次上报的阅读进度当前值（如当前页码），未上报过为 `null` |
| `stats[].progress_total` | integer \| null | 最近一次上报的阅读进度总量（如总页数），未上报过为 `null` |
| `stats[].progress_percent` | number \| null | 阅读进度百分比（0~100，两位小数）；`state` 为已完成（`1`）时固定返回 `100.0`，否则为最近一次上报换算得到的值，未上报过为 `null` |
| `stats[].start_time` | string (ISO8601, UTC, 以 `Z` 结尾) \| null | 当前/最近一轮阅读的开始时间；未开始过为 `null` |
| `stats[].finish_time` | string (ISO8601, UTC, 以 `Z` 结尾) \| null | 当前/最近一轮阅读的完成时间；重新开始阅读时会被清空为 `null` |
| `stats[].start_count` | integer | 开始阅读的次数（含首次） |
| `stats[].update_time` | string (ISO8601, UTC, 以 `Z` 结尾) | 该格式统计数据最后一次写入时间（心跳上报或手动更新） |

- **按格式过滤示例**（`GET /api/book/123/reading_stats?format=epub`，只返回 `stats` 中 `format` 为 `epub` 的一项，数组长度最多为 1）：

```json
{
  "err": "ok",
  "stats": [
    {
      "format": "epub",
      "state": 0,
      "total_seconds": 5460,
      "progress_current": 128,
      "progress_total": 320,
      "progress_percent": 40.0,
      "start_time": "2026-08-20T09:12:33Z",
      "finish_time": null,
      "start_count": 2,
      "update_time": "2026-08-30T13:05:11Z"
    }
  ]
}
```

- **错误响应示例**：

```json
{ "err": "user.need_login", "msg": "请先登录" }
```

#### POST 手动补记/纠正分格式阅读统计

- **路径**：`/api/book/<id>/reading_stats`
- **方法**：POST
- **认证**：需要登录（只作用于当前用户）
- **参数**：
  - `id` (path, 必填): 图书ID
  - JSON Body：
    - `format` (string, 必填): 格式，如 `epub`/`pdf`/`mobi`/`azw3`/`txt`
    - `duration_seconds` (int, 可选): **累加**到该格式累计阅读时长的秒数（不是绝对值）
    - `progress` (array[int], 可选): `[当前, 总数]`，总数须 >0；进度达到约 100% 时自动标记为读完
    - `start_time` (string|number, 可选): 开始新一轮阅读的时间；ISO8601 字符串，或数字形式的秒/毫秒时间戳（数字字符串不被接受）
    - `finish_time` (string|number, 可选): 标记本轮读完的时间，格式同上
    - `state` (int, 可选): `0`=在读，`1`=读完（可替代 finish_time）
- **响应**：
  - `err` (string): `ok` / `params.book.invalid` / `params.invalid`（缺少 format、progress 或 state 非法）；时间格式无效时返回 HTTP 400
  - `stats` (object): 更新后该格式的统计（字段同 GET 中 `stats` 的元素）
- **响应示例**：

```json
{
  "err": "ok",
  "stats": {"format": "epub", "state": 0, "total_seconds": 5400, "progress_current": 120, "progress_total": 488, "progress_percent": 24.6, "start_time": "2026-09-20T09:00:00Z", "finish_time": null, "start_count": 1, "update_time": "2026-09-28T10:00:00Z"}
}
```

---

### 3.50 目录（Folder）

目录基于自定义列 `#folder`，一本书只属于一个目录，最多 `MAX_DEPTH` 级（`webserver/base/folder_helper.py`，当前为 2），以 `.` 连接（如 `文学.小说`）；未设置表示根目录 `/`。

**目录名规则**：每级 1–24 个字符，只允许字母、数字、汉字，不允许标点、空白、下划线；超过最大层级或有空段返回 `params.folder.invalid`。设置时传空串、`清除` 或 `clear` 表示移出目录。

#### 3.50.1 设置图书目录

- **路径**：`/api/book/<id>/folder`
- **方法**：POST
- **认证**：需要管理员或书籍所有者权限
- **参数**：`folder` (string, 必填): 目录路径
- **响应示例**：`{"err": "ok", "msg": "目录更新成功"}`

#### 3.50.2 批量设置目录

- **路径**：`/api/book/folder`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `ids` (array, 必填): 图书ID列表
  - `folder` (string, 必填): 目录路径
- **响应示例**：`{"err": "ok", "msg": "成功更新 3 本书籍目录", "count": 3}`

#### 3.50.3 获取目录树

- **路径**：`/api/folders`
- **方法**：GET
- **认证**：需要登录（未登录返回空树）
- **响应示例**（`count` 含子目录的书；`root_count` 为未设置目录的书）：

```json
{
  "err": "ok",
  "folders": [
    {"name": "文学", "count": 12, "children": [{"name": "小说", "count": 8}]}
  ],
  "root_count": 5,
  "max_depth": 2
}
```

#### 3.50.4 获取目录下的图书

- **路径**：`/api/folder/books`
- **方法**：GET
- **认证**：同图书列表
- **参数**：
  - `path` (string, 可选): 目录路径，空为根目录；只返回**直属**该目录的书
  - `start` (int, 可选): 起始偏移，默认0
  - `size` (int, 可选): 每页数量
- **响应**：同图书列表（`err`、`title`、`total`、`books`）

#### 3.50.5 重命名目录

- **路径**：`/api/folder/rename`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `path` (string, 必填): 要改名的目录（非根）
  - `name` (string, 必填): 新的末段名称，只改最后一段，子目录同步改名
  - `merge` (bool, 可选): 默认 false；目标已存在时需传 true 确认合并（不可撤回）
- **目标已存在且未传 merge**：不修改任何数据，返回

```json
{"err": "folder.exists", "msg": "目录已存在，合并后无法撤回", "exists": true, "count": 3, "target": "读物"}
```

- **成功响应**：`{"err": "ok", "msg": "目录重命名成功", "path": "读物", "merged": 0}`（`merged` 为并入已有目录的书数）

#### 3.50.6 目录编辑候选

- **路径**：`/api/folder/candidates`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `level` (int, 可选): 1（默认）到最大层级
  - `parent` (string, level>1 时必填): 上级目录路径，如 `文学` 或 `文学.小说`（须恰好有 level-1 段）
  - `q` (string, 可选): 过滤关键词
- **说明**：只提示已有目录名，按书籍数量降序，最多100条。一级只返回已有一级目录；上级目录存在且有子目录时返回其子目录，否则返回该层级所有已使用的目录名
- **响应示例**：

```json
{
  "err": "ok",
  "items": [
    {"name": "文学", "count": 12},
    {"name": "历史", "count": 5}
  ]
}
```

### 3.51 手动添加实体书

- **路径**：`/api/book/add/manual`
- **方法**：POST
- **认证**：需要登录，且用户有上传权限
- **参数**：
  - JSON Body：
    - `title` (string, 必填): 书名，≤100 字符，不能含引号/控制字符
    - `author` (string, 可选): 作者，≤64 字符，多个作者用 `,` 或 `，` 分隔；为空时记为“佚名”
    - `isbn` (string, 可选): ISBN-10/13，可带 `-`/空格
- **说明**：创建实体书条目（`book_type=1`，数量 1），随后在后台强制联网刮削补全元数据。
- **响应**：
  - `err` (string): `ok` / `params.invalid`（书名为空/过长/非法字符、ISBN 无效）/ `book.duplicate`（该 ISBN 已存在）/ `permission` / `internal`
  - `book_id` (int): 新书籍ID
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "图书添加成功",
  "book_id": 1024
}
```

### 3.52 批量上传图书（多文件/目录）

- **路径**：`/api/book/upload/batch`
- **方法**：POST（`multipart/form-data`）
- **认证**：`ALLOW_GUEST_UPLOAD` 关闭时需要登录且有上传权限
- **参数**：
  - 表单文件：`ebooks` (file[], 必填): 一个或多个电子书文件，仅保留扫描导入支持的格式
  - 表单字段：`relative_paths` (string[], 可选): 与 `ebooks` 一一对应的相对路径（目录上传时的 `webkitRelativePath`）；含目录层级时以顶层目录名落地，便于按一级目录识别分类
- **说明**：文件暂存到 `scan_upload_path` 下的批次目录，交给扫描导入服务异步导入；进度用 3.53 轮询。
- **响应**：
  - `err` (string): `ok` / `permission` / `importing`（已有扫描任务在运行）/ `params.filename`（未选择文件）/ `params.format.unsupported`（没有可导入的格式）/ `server.error`（导入目录未配置）/ `internal`
  - `import_id` (int): 批次ID
  - `file_count` (int): 实际暂存的文件数
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "已开始导入",
  "import_id": 1790000000123,
  "file_count": 12
}
```

### 3.53 批量上传状态

- **路径**：`/api/book/upload/batch/status`
- **方法**：GET
- **认证**：仅批次发起者或管理员（进程重启后批次归属信息丢失）
- **参数**：
  - `import_id` (int, 必填): 3.52 返回的批次ID
  - `num` (int, 可选): 返回条数，默认 200，范围 1~500
- **响应**：
  - `err` (string): `ok` / `params.error` / `permission`
  - `items` (array): 每个文件的导入记录：`id`、`path`、`name`、`title`、`author`、`status`（`new`/`ready`/`exist`/`imported`/`invalid`/`drop`/`missed`/`permission`）、`book_id`（导入成功后的书籍ID）
  - `importing` (bool): 该批次是否仍在导入
- **响应示例**：

```json
{
  "err": "ok",
  "items": [
    {"id": 1, "path": "/data/.../三体.epub", "name": "三体.epub", "title": "三体", "author": "刘慈欣", "status": "imported", "book_id": 1025}
  ],
  "importing": false
}
```

### 3.54 取消批量上传

- **路径**：`/api/book/upload/batch/cancel`
- **方法**：POST
- **认证**：需要登录（批次发起者或管理员）
- **参数**：
  - JSON Body：`import_id` (int, 可选): 指定时仅当该批次正在运行才取消
- **响应**：
  - `err` (string): `ok` / `not_importing`（没有正在运行的任务）/ `permission`
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "正在取消任务, 请稍后查看状态"
}
```

### 3.55 查询今日下载配额

- **路径**：`/api/book/download_quota`
- **方法**：GET
- **认证**：需要登录
- **参数**：无
- **说明**：只查询、不消耗配额。未开启 `ENABLE_DOWNLOAD_QUOTA` 或管理员时总是允许，`quota=0` 表示不限。
- **响应**：
  - `err` (string): `ok` / `quota.exceeded`（今日已达上限）
  - `allowed` (bool): 是否还能下载
  - `used` (int): 今日已用次数
  - `quota` (int): 每日上限，0 表示不限
- **响应示例**：

```json
{
  "err": "ok",
  "allowed": true,
  "used": 3,
  "quota": 10
}
```

### 3.56 裁剪封面白边

- **路径**：`/api/book/crop_cover`
- **方法**：POST
- **认证**：需要登录；只处理管理员或书籍所有者的书籍（其余计入失败）
- **参数**（任选其一，JSON Body 优先，其次 query）：
  - `id` (int): 单本书籍ID
  - `ids` (array[int]): 多本书籍ID
- **响应**：
  - `err` (string): `ok` / `params.invalid`（未指定书籍）
  - `data.updated` (int): 成功裁剪数；`data.failed` (int): 跳过/失败数
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "处理完成，成功更新 2 本，跳过/失败 0 本。",
  "data": {"updated": 2, "failed": 0}
}
```

### 3.57 按日期补录阅读时间

对单本书某一天的“手工阅读时长”进行查询、新增/覆盖、删除；变更会同步到每日阅读统计、分格式阅读统计与用户总阅读时长。所有操作只作用于当前用户。

#### GET 查询

- **路径**：`/api/book/<id>/reading_time`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
  - `date` (string, 必填): 日期 `YYYY-MM-DD`
- **响应**：
  - `err` (string): `ok` / `params.invalid`（日期格式错误）
  - `entry` (object|null): 当天的手工记录：`date`、`format`、`start_time`、`end_time`、`duration_seconds`
  - `date_recorded_seconds` (int): 当天自动记录的阅读秒数
  - `manual_recorded_seconds` (int): 当天手工记录的秒数
  - `book_total_seconds` (int): 该书累计阅读秒数
- **响应示例**：

```json
{
  "err": "ok",
  "entry": {"date": "2026-09-27", "format": "epub", "start_time": "21:00", "end_time": "21:45", "duration_seconds": 2700},
  "date_recorded_seconds": 600,
  "manual_recorded_seconds": 2700,
  "book_total_seconds": 86400
}
```

#### POST 新增/覆盖

- **路径**：`/api/book/<id>/reading_time`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID（必须有可阅读的电子书格式）
  - JSON Body：
    - `date` (string, 必填): `YYYY-MM-DD`，不能是未来日期
    - `duration_seconds` (int, 必填): 0 ~ 64800（18 小时），覆盖当天已有的手工记录
    - `start_time` (string, 可选): 开始时间（自由文本）
    - `end_time` (string, 可选): 结束时间（自由文本）
- **响应**：
  - `err` (string): `ok` / `params.invalid`（日期/时长不合法、书籍没有电子书格式）/ `params.book.invalid`
  - `entry` (object): 保存后的记录
- **响应示例**：

```json
{
  "err": "ok",
  "entry": {"date": "2026-09-27", "format": "epub", "start_time": null, "end_time": null, "duration_seconds": 2700}
}
```

#### DELETE 删除

- **路径**：`/api/book/<id>/reading_time`
- **方法**：DELETE
- **认证**：需要登录
- **参数**：
  - `id` (path, 必填): 图书ID
  - `date` (string, 必填, query): `YYYY-MM-DD`
- **响应**：
  - `deleted` (bool): 是否删除了记录（当天无手工记录时为 false）
- **响应示例**：

```json
{
  "err": "ok",
  "deleted": true
}
```

### 3.58 批量清除书架状态

- **路径**：`/api/books/batch-remove-state`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - JSON Body：
    - `book_ids` (array[int], 必填): 书籍ID列表
    - `action` (string, 必填): `favorite`（取消收藏）/ `wants`（取消待读）/ `reading` 或 `read-done`（阅读状态重置为未读）
- **响应**：
  - `err` (string): `ok` / `params.invalid`
  - `count` (int): 实际处理的书籍数
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "已处理 3 本书籍",
  "count": 3
}
```

### 3.59 设置实体书存放位置

- **路径**：`/api/book/<id>/location`
- **方法**：POST
- **认证**：需要登录；管理员或书籍所有者
- **参数**：
  - `id` (path, 必填): 图书ID
  - JSON Body：`location` (string, 必填): 位置描述，≤20 字符；空字符串表示清除
- **响应**：
  - `err` (string): `ok` / `params.book.invalid` / `user.no_permission` / `params.location.invalid`（过长）/ `internal`
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "位置更新成功"
}
```

### 3.60 重新提取书籍目录

- **路径**：`/api/book/<id>/catalog`
- **方法**：POST
- **认证**：需要登录；管理员或书籍所有者
- **参数**：
  - `id` (path, 必填): 图书ID
- **说明**：同步执行，优先使用 EPUB，其次 PDF、TXT。
- **响应**：
  - `err` (string): `ok` / `params.book.invalid` / `user.no_permission` / 提取失败时的错误码
  - `catalog` (string): 提取到的目录文本
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "目录提取成功",
  "catalog": "第一部 ……\n第二部 ……"
}
```

### 3.61 批量提取书籍目录

- **路径**：`/api/book/catalog/batch`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - JSON Body：`idlist` (array[int], 可选): 指定书籍（强制重新提取）；不传或空数组时处理全部书籍（跳过已有目录的书）
- **说明**：后台任务，进度在右上角任务列表查看。
- **响应**：
  - `err` (string): `ok` / `user.no_permission` / `task.running`（已有目录提取任务）
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "目录提取任务已启动，共 120 本，右上角可以查看进度"
}
```

### 3.62 作者自动完成

- **路径**：`/api/authors/search`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `q` (string, 可选): 作者名前缀；为空时按藏书量返回前若干位作者
  - `limit` (int, 可选): 返回数量，默认 100，最大 100
- **响应**：
  - `authors` (array): `{name, count}`，按藏书量降序
- **响应示例**：

```json
{
  "err": "ok",
  "authors": [{"name": "刘慈欣", "count": 12}]
}
```

### 3.63 书籍社交统计

- **路径**：`/api/book/<id>/social-stats`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `id` (path, 必填): 图书ID
- **响应**：
  - `reading_count` (int): 在读人数
  - `finished_count` (int): 读完人数
  - `favorite_count` (int): 收藏人数
  - `recommend_count` (int): 推荐（评价）人数
- **响应示例**：

```json
{
  "err": "ok",
  "reading_count": 3,
  "finished_count": 10,
  "favorite_count": 5,
  "recommend_count": 4
}
```

### 3.64 我的书籍评价

评价对象（`review`）字段：`id`、`book_id`、`reader_id`、`nickname`、`avatar`、`rating`（0~10）、`comment`、`status`（`pending` 待审核 / `approved` 已通过 / `hidden` 已屏蔽）、`update_time`（ISO8601）、`is_own`（是否当前用户的评价）。

#### GET 获取我对该书的评价

- **路径**：`/api/book/<id>/review`
- **方法**：GET
- **认证**：需要登录
- **参数**：`id` (path, 必填): 图书ID
- **响应**：`review` (object|null): 我的评价，未评价时为 null

#### POST 提交/修改评价

- **路径**：`/api/book/<id>/review`
- **方法**：POST
- **认证**：需要登录（被禁言用户不可评价）
- **参数**：
  - `id` (path, 必填): 图书ID
  - JSON Body：
    - `rating` (int, 必填): 0~10
    - `comment` (string, 可选): 评价内容
- **响应**：
  - `err` (string): `ok` / `review.disabled`（评论功能未启用）/ `review.banned`（已被禁止评论）/ `params.book.invalid` / `params.invalid`（评分不合法）
  - `review` (object): 保存后的评价

#### DELETE 删除我的评价

- **路径**：`/api/book/<id>/review`
- **方法**：DELETE
- **认证**：需要登录
- **参数**：`id` (path, 必填): 图书ID
- **响应**：`err` 为 `ok`；没有可删除的评价时为 `params.invalid`

- **响应示例**（POST）：

```json
{
  "err": "ok",
  "msg": "评价已提交",
  "review": {"id": 8, "book_id": 42, "reader_id": 3, "nickname": "reader", "avatar": "", "rating": 9, "comment": "值得一读", "status": "approved", "update_time": "2026-09-27T21:00:00", "is_own": true}
}
```

### 3.65 书籍评价列表

- **路径**：`/api/book/<id>/reviews`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `id` (path, 必填): 图书ID
- **说明**：不分页，返回最近更新的最多 50 条，当前用户的评价置顶。
- **响应**：
  - `total` (int): 评价总数
  - `reviews` (array): 评价对象（见 3.64）
- **响应示例**：

```json
{
  "err": "ok",
  "total": 1,
  "reviews": [{"id": 8, "rating": 9, "comment": "值得一读", "nickname": "reader", "is_own": false, "...": "..."}]
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
  - `start` (int, 可选): 偏移量，默认 0
  - `size` (int, 可选): 每页数量，默认 `DEFAULT_PAGE_SIZE`（至少 60），最大 1000
- **说明**：`meta` 为 `author`/`publisher`/`tag`/`rating`/`series`/`language`；`rating` 的 name 为星级数字；`series` 结果按丛书序号排序。作者路由优先匹配 `/api/author/info` 等固定路径（见 4.5）。
- **响应示例**：

```json
{
  "err": "ok",
  "title": "\"刘慈欣\"编著的书籍",
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

### 4.5 获取作者信息

- **路径**：`/api/author/info`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `name` (string, 必填): 作者名
- **响应**：
  - `err` (string): `ok` / `params.error`（未传 name）
  - `author` (object|null): 作者资料（无记录时为 null）：`id`、`name`、`author_id`、`sort`、`bio`（简介）、`region`、`avatar`、`create_time`
- **响应示例**：

```json
{
  "err": "ok",
  "author": {"id": 5, "name": "刘慈欣", "author_id": 0, "sort": "", "bio": "中国科幻作家……", "region": "中国", "avatar": "", "create_time": "2026-05-01T10:00:00"}
}
```

### 4.6 保存作者简介

- **路径**：`/api/author/bio`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - JSON Body：
    - `name` (string, 必填): 作者名（不存在时自动创建作者资料）
    - `bio` (string, 可选): 简介，≤4096 字符
- **响应**：
  - `err` (string): `ok` / `params.error` / `params.bio.too_long`
  - `author` (object): 保存后的作者资料（字段同 4.5）
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "简介保存成功",
  "author": {"id": 5, "name": "刘慈欣", "bio": "……", "...": "..."}
}
```

### 4.7 从书栈更新作者资料

- **路径**：`/api/admin/update_author`
- **方法**：POST
- **认证**：需要管理员权限；需启用并配置书栈（`ENABLE_BOOKBARN` + `BOOKBARN_TOKEN`）
- **参数**：
  - JSON Body：`name` (string, 必填): 作者名
- **说明**：异步从书栈服务拉取作者资料，稍后刷新查看。
- **响应**：
  - `err` (string): `ok` / `params.error`（未配置书栈或未传 name）
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "已提交更新，请稍后刷新查看"
}
```

### 4.8 上传作者头像

- **路径**：`/api/author_avatar`
- **方法**：POST（`multipart/form-data`）
- **认证**：需要管理员权限
- **参数**：
  - `author` (string, 必填, query/表单): 作者名（可 URL 编码）
  - 表单文件：`avatar_data` (file, 必填): JPEG/PNG/WEBP 图片，会覆盖该作者已有头像
- **说明**：头像通过 `/get/author/avatar/<name>` 访问。
- **响应**：
  - `err` (string): `ok` / `failed`（缺少作者名/文件，或格式不支持）
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "Avatar uploaded successfully"
}
```

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

### 5.2 有声书转换（Edge TTS）

#### GET 查询转换进度

- **路径**：`/api/audio/<id>/conversion`
- **方法**：GET
- **认证**：无需认证
- **参数**：`id` (path, 必填): 图书ID
- **响应**：
  - `err` (string): `ok` / `audio.conversion_failed` / `audio.no_conversion`（没有进行中的任务）/ `params.invalid` / `server.error`
  - `data` (object|null): 转换进度（含 `status` 等）；转换完成后该任务从进度表移除

#### POST 启动转换

- **路径**：`/api/audio/<id>/conversion`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `id` (path, 必填): 图书ID（必须有 EPUB 格式）
  - JSON Body：`voice` (string, 可选): 音色，默认 `zh-CN-YunjianNeural`；`language` (string, 可选): 默认 `zh-CN`
- **说明**：同时最多运行 2 个转换任务。
- **响应**：
  - `err` (string): `ok` / `permission.not_admin` / `audio.too_many_conversions` / `params.book.invalid` / `params.book.no_epub` / `params.book.epub_missing` / `params.invalid` / `server.error`
  - `task_id` (string): 任务ID
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "开始转换",
  "task_id": "..."
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
  - `start` (int, 可选): 偏移量，默认 0
  - `size` (int, 可选): 每页数量，默认 60
- **响应**：`title`、`total`、`books`（图书对象，另含 `has_audio`、`audio_count`）；`err` 出错时为 `server.error`
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

### 5.8 生成音频合集下载链接

- **路径**：`/api/audios/<id>/collection`
- **方法**：GET
- **认证**：需要登录
- **参数**：`id` (path, 必填): 图书ID
- **说明**：把该书全部音频打包为 ZIP，并生成 24 小时有效的下载 key。开启 VIP 额度时需已购买（见 5.5），且同一合集每天只能下载一次。
- **响应**：
  - `err` (string): `ok` / `auth.required` / `book.not_found` / `not.purchased` / `daily.limit.exceeded` / `audio.not_found` / `params.invalid` / `server.error`
  - `download_url` (string): `/api/audios/<id>/collection/download?key=<key>`
- **响应示例**：

```json
{
  "err": "ok",
  "download_url": "/api/audios/42/collection/download?key=0f1e2d...",
  "message": "下载链接已生成"
}
```

### 5.9 下载音频合集

- **路径**：`/api/audios/<id>/collection/download`
- **方法**：GET
- **认证**：凭 `key` 下载（无需 Cookie）
- **参数**：
  - `id` (path, 必填): 图书ID
  - `key` (string, 必填): 5.8 返回的下载 key
- **响应**：ZIP 文件（二进制）；key 无效或过期时返回错误

### 5.10 Edge TTS 朗读代理

供 MyReader 朗读功能使用的 Microsoft Edge TTS 代理（与 Next.js 版本路由形状一致），不是 `/api` 通用 JSON 响应格式。

- **认证**：`ALLOW_GUEST_READ` 开启时无需认证，否则需要登录（未登录返回 HTTP 403 `{"error": "Not authenticated"}`）

#### GET 获取音色列表

- **路径**：`/api/tts/edge`
- **方法**：GET
- **参数**：
  - `lang` (string, 可选): 按 Locale 子串过滤，如 `zh-cn`
- **响应**：`voices` (array): `{id, name, language}`
- **响应示例**：

```json
{
  "voices": [{"id": "zh-CN-XiaoxiaoNeural", "name": "Microsoft Xiaoxiao Online (Natural) - Chinese (Mainland)", "language": "zh-CN"}]
}
```

#### POST 合成语音

- **路径**：`/api/tts/edge`
- **方法**：POST
- **参数**：
  - JSON Body：
    - `input` (string, 必填): 待朗读文本
    - `voice` (string, 必填): 音色ID（GET 返回的 `id`）
    - `rate` (number, 可选): 语速倍率，1.0 为正常、0.5 为半速、2.0 为两倍速
    - `lang` (string, 可选): 语言，缺省时从 voice 推断
- **响应**：成功时为 `audio/mpeg` 音频二进制；响应头 `X-TTS-Word-Boundaries` 为 URL 编码的 JSON 数组 `[{offset, duration, text}]`（超过 8192 字节时省略）。失败时 HTTP 400/500，body 为 `{"error": {"message": "...", "type": "invalid_request_error|internal_error"}}`。

---

## 6. 管理员接口

### 6.1 上传 SSL 证书

- **路径**：`/api/admin/ssl`
- **方法**：POST（`multipart/form-data`）
- **认证**：需要管理员权限
- **参数**：
  - 表单文件：`ssl_crt` (file, 必填): 证书（含证书链）
  - 表单文件：`ssl_key` (file, 必填): 私钥
- **说明**：校验证书与私钥匹配后保存，并执行 `nginx -t` 与 `nginx reload`（Docker 部署环境）。
- **响应**：`err`: `ok` / `permission` / `params.ssl_error`（校验失败）/ `internal.ssl_save_error` / `internal.nginx_test_error` / `internal.nginx_reload_error`
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "成功"
}
```

### 6.2 用户管理

#### GET 用户列表

- **路径**：`/api/admin/users`
- **方法**：GET
- **认证**：需要管理员权限
- **参数**：
  - `page` (int, 可选): 页码，默认 1
  - `num` (int, 可选): 每页数量，默认 20，最小 10
  - `sort` (string, 可选): `access_time`（默认）/ `id` / `create_time` / `update_time` / `username` / `total_reading_seconds` / `download_count` / `push_count`
  - `desc` (string, 可选): 默认降序，`false` 为升序
- **响应**：
  - `users.items` (array): `id`、`username`、`name`、`email`、`avatar`、`is_active`、`is_admin`、`extra`、`provider`（第三方登录来源）、`create_time`、`update_time`、`access_time`、`read_limit`、`limit_categories`、`limit_tags`、`read_count`、`push_count`、`download_count`、`total_reading_seconds`、`allow_review` 等
  - `users.total` (int)
  - `settings` (object): 相关系统开关（如 `allow_read_range_setting`、`enable_download_quota`）

#### POST 修改用户

- **路径**：`/api/admin/users`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**（JSON Body，除 `id` 外只修改传入的字段）：
  - `id` (int, 必填): 用户ID
  - `active` (bool): 是否激活；`admin` (bool): 是否管理员（不能取消自己的管理员权限）
  - `allow_review` (bool): 是否允许发表评论
  - `permission` (string): 权限变更串，字母 `d`(删除) `e`(编辑) `l`(登录) `p`(推送) `r`(在线阅读) `s`(下载) `u`(上传) `v`(浏览)，小写=授予、大写=禁止，如 `"uD"`
  - `read_limit` (int): 阅读范围 0=不限，1=仅限 `limit_categories`/`limit_tags`，2=排除它们；`limit_categories`、`limit_tags` (string): 逗号分隔
  - `download_daily_quota` (int): 每日下载上限，-1=跟随全局设置，0~1000
  - `password` (string): 重置密码（6~20 位）
  - `delete` (string): 传入该用户的用户名表示删除该用户（不能删除自己）
- **响应**：`err`: `ok` / `params.invalid` / `params.fields.invalid` / `params.user.not_exist` / `params.user.invalid` / `params.read_limit.invalid` / `params.download_daily_quota.invalid` / `params.password.invalid` / `params.permission.invalid`
- **响应示例**：

```json
{
  "err": "ok",
  "users": {"items": [...], "total": 100},
  "settings": {...}
}
```

### 6.3 初始化安装

#### GET 查询安装状态

- **路径**：`/api/admin/install`
- **方法**：GET
- **认证**：无需认证
- **响应**：`err`: `installed` / `not_intalled`（原文拼写如此）；`installed` (bool)

#### POST 执行安装

- **路径**：`/api/admin/install`
- **方法**：POST（query/表单参数）
- **认证**：无需认证（仅在未安装时可用，已安装返回 `err=installed`）
- **参数**：
  - `username` (string, 必填): 管理员用户名（3~20 位）
  - `password` (string, 必填): 管理员密码
  - `email` (string, 必填): 管理员邮箱
  - `title` (string, 必填): 站点标题
  - `language` (string, 可选): 站点语言，`zh`（默认）/ `en`
  - `invite` (string, 可选): `true` 时开启邀请码模式，需同时提供 `code`
  - `code` (string, 可选): 访问邀请码
- **响应**：`err`: `ok` / `installed` / `params.invalid` / `params.email.invalid` / `params.username.invalid` / `params.password.invalid` / `db.error` / `file.permission`（配置文件无法写入）
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "设置已保存！"
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
  - `page` (int, 可选): 页码，从 1 开始，默认 1
  - `num` (int, 可选): 每页数量，默认 20，最小 10
  - `sort` (string, 可选): 排序字段，默认 `id`
  - `desc` (string, 可选): `true` 时降序；**不传时为升序**
  - `search` (string, 可选): Calibre 搜索表达式
  - `type` (int, 可选): `0` 只看电子书，`1` 只看实体书，默认全部
- **响应**：
  - `items` (array): 精简图书对象
  - `total` (int): 匹配总数
- **响应示例**：

```json
{
  "err": "ok",
  "items": [{"id": 42, "title": "三体", "...": "..."}],
  "total": 1200
}
```

### 6.7 自动填充图书信息

- **路径**：`/api/admin/book/fill`
- **方法**：GET/POST
- **认证**：需要管理员权限
- **参数**： GET 无参数；POST:
  - JSON Body：`idlist` (array[int] 或 `"all"`, 必填): 书籍ID列表；`"all"` 表示全部书籍
- **说明**：POST 后台联网刮削元数据；指定 ID 列表时强制更新，`all` 时跳过已刮削过的书。
- **POST 响应**：`err`: `ok` / `params.error` / `params.error.idlist` / `task.running`
- **GET 响应**：`status`: `{total, skip, done, fail, running}` 当前批处理任务进度
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "任务启动成功！请耐心等待，稍后再来刷新页面"
}
```

### 6.8 AI填充图书信息

- **路径**：`/api/admin/book/aifill`
- **方法**：GET/POST
- **认证**：需要管理员权限
- **参数**： GET 无参数；POST:
  - JSON Body：`idlist` (array[int] 或 `"all"`, 必填): 书籍ID列表；`"all"` 表示全部书籍
- **说明**：POST 后台用 AI 填充分类/标签/简介。
- **POST 响应**：`err`: `ok` / `params.error` / `params.error.idlist` / `task.running`
- **GET 响应**：`status`: `{total, skip, done, fail, running}` 当前批处理任务进度
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "AI填充成功"
}
```

### 6.9 转换出epub格式

- **路径**：`/api/admin/book/epubconvert`
- **方法**：GET/POST
- **认证**：需要管理员权限
- **参数**： GET 无参数；POST:
  - JSON Body：`idlist` (array[int], 可选): 书籍ID列表；不传或为空时处理全部书籍
- **说明**：POST 后台把 Kindle 格式（azw3/mobi）转换为 EPUB。
- **POST 响应**：`err`: `ok` / `params.error.idlist` / `task.running`
- **GET 响应**：`status`: `{total, skip, done, fail, running}` 当前批处理任务进度
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
- **参数**： GET 无参数；POST:
  - JSON Body：`idlist` (array[int], 可选): 书籍ID列表；不传或为空时处理全部书籍
- **POST 响应**：`err`: `ok` / `params.error.idlist` / `task.running`
- **GET 响应**：`status`: `{total, skip, done, fail, running}` 当前批处理任务进度
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
- **参数**：无
- **响应**：`err`: `ok` / `params.error`（申请失败）；成功时 `token` 为申请到的 Token
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "Token申请成功",
  "token": "..."
}
```

### 6.12 批量删除图书

- **路径**：`/api/admin/books/delete`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - JSON Body：`idlist` (array[int], 必填): 书籍ID列表
- **说明**：逐本删除（同时清理有声书文件），书籍进入回收站；单本失败不影响其他书。
- **响应**：`err`: `ok` / `params.error`
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
  - JSON Body：`idlist` (array[int], 必填): 书籍ID列表
- **说明**：后台把元数据批量写入电子书文件（同 3.42）。
- **响应**：`err`: `ok` / `params.error` / `params.error.idlist`
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

### 6.15 测试 EdgeTTS 连接

- **路径**：`/api/admin/audio/test`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - JSON Body：
    - `proxy` (string, 可选): 代理地址
    - `use_bookbarn_proxy` (bool, 可选): 是否使用书栈提供的代理
- **说明**：通过获取 EdgeTTS 音色列表测试连通性。
- **响应**：`err`: `ok` / `params.error.proxy`（代理地址无效）/ `error`
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "EdgeTTS 连接测试成功"
}
```

### 6.16 发布说明

- **路径**：`/api/admin/release/notes`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `force` (string, 可选): `true` 时总是返回发布说明
- **说明**：版本升级后的第一次请求返回 `release_notes.txt` 内容，并记录已读版本；之后返回空字符串（除非 `force=true`）。
- **响应**：`msg` (string): 发布说明文本，或空字符串
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "v4.4.0\n- 新增……"
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

### 6.21 图章管理

#### GET 查询图章

- **路径**：`/api/admin/stamp`
- **方法**：GET
- **认证**：需要管理员权限
- **参数**：无
- **响应**：`err`: `ok` / `permission.not_admin` / `feature.disabled`（未开启 `ENABLE_STAMP_FEATURE`）；`exists` (bool): 是否已上传图章

#### POST 上传图章

- **路径**：`/api/admin/stamp`
- **方法**：POST（`multipart/form-data`）
- **认证**：需要管理员权限
- **参数**：表单文件 `file` (file, 必填): PNG 图片，≤128KB，尺寸不超过 480×480
- **响应**：成功时 `data.url` 为图章地址；失败时 HTTP 400/403/500，`err` 为 `permission.not_admin` / `params.missing` / `file.invalid_format` / `file.too_large` / `file.dimension_too_large` / `file.invalid` / `file.save_failed`
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "图章图片上传成功",
  "data": {"url": "/static/logo/stamp.png"}
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
- **参数**：无
- **响应**：
  - `lines` (array[string]): 日志最后 1500 行
  - `href` (string): 完整日志下载地址（见 6.27）
  - `err` 读取失败时为 `failed`
- **响应示例**：

```json
{
  "err": "ok",
  "lines": ["2026-09-28 10:00:00 INFO ..."],
  "href": "/api/admin/syslog/download"
}
```

### 6.24 批量更新所有元数据

- **路径**：`/api/admin/book/update_all_meta`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**： 无（处理全部书籍）
- **响应**：`err`: `ok` / `task.running`
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
- **参数**：
  - JSON Body：`idlist` (array[int] 或 `"all"`, 必填): 书籍ID列表；`"all"` 表示全部书籍
- **说明**：为书籍重新生成动态封面（书名+作者）。
- **响应**：`err`: `ok` / `params.error` / `params.error.idlist` / `task.running`
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
  - JSON Body：`idlist` (array[int] 或 `"all"`, 必填): 书籍ID列表；`"all"` 表示全部书籍
- **说明**：从电子书文件重新提取封面（不使用动态封面）。
- **响应**：`err`: `ok` / `params.error` / `params.error.idlist` / `task.running`
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

### 6.28 用户评论管理

#### GET 评论列表

- **路径**：`/api/admin/book-reviews`
- **方法**：GET
- **认证**：需要管理员权限
- **参数**：
  - `status` (string, 可选): `pending` / `approved` / `hidden`，不传为全部
  - `page` (int, 可选): 默认 1
  - `page_size` (int, 可选): 默认 20，范围 1~100
- **响应**：
  - `total`、`page`、`page_size`
  - `reviews` (array): `id`、`book_id`、`book_title`、`reader_id`、`username`、`rating`、`comment`、`status`、`update_time`（`YYYY-MM-DD HH:MM:SS`）

#### POST 审核操作

- **路径**：`/api/admin/book-reviews`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - JSON Body：
    - `id` (int, 必填): 评论ID
    - `action` (string, 必填): `approve`（通过）/ `hide`（屏蔽）/ `restore`（恢复到屏蔽前状态）/ `delete`（物理删除，不可恢复）
- **响应**：`err` 为 `ok`；参数错误或评论不存在时为 `params.invalid`
- **响应示例**：

```json
{
  "err": "ok",
  "total": 1,
  "page": 1,
  "page_size": 20,
  "reviews": [{"id": 8, "book_id": 42, "book_title": "三体", "reader_id": 3, "username": "reader", "rating": 9, "comment": "值得一读", "status": "approved", "update_time": "2026-09-27 21:00:00"}]
}
```

### 6.29 回收站书籍

#### GET 列出回收站书籍

- **路径**：`/api/admin/trash/books`
- **方法**：GET
- **认证**：需要管理员权限
- **参数**：无
- **响应**：`books` (array): `book_id`、`title`、`author`、`deleted_at`（删除时间）等

#### POST 恢复书籍

- **路径**：`/api/admin/trash/books/restore`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - JSON Body：`book_ids` (array[int], 必填)
- **说明**：恢复后补建书籍归属记录；开启 `AUTO_FILL_META` 时会触发元数据刮削。
- **响应**：
  - `err` (string): `ok` / `partial`（部分失败）/ `error`（全部失败）/ `params.error`
  - `restored` (array[int]): 成功恢复的ID；`failed` (object): `{book_id: 错误信息}`

#### POST 彻底删除

- **路径**：`/api/admin/trash/books/purge`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - JSON Body：`book_ids` (array[int], 必填)
- **响应**：
  - `err` (string): `ok` / `partial` / `error` / `params.error`
  - `purged` (array[int]): 已删除的ID；`failed` (object): `{book_id: 错误信息}`
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "已恢复选中的书籍",
  "restored": [101, 102]
}
```

### 6.30 重启服务

- **路径**：`/api/admin/restart`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：无
- **说明**：1 秒后退出进程，由 supervisor 自动拉起。
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "服务正在重启，请稍后刷新页面"
}
```

### 6.31 书库概览看板数据

- **路径**：`/api/library/stats/<kind>`
- **方法**：GET
- **认证**：无需认证（`tags` 按当前用户的阅读范围过滤）
- **参数**：
  - `kind` (path, 必填):
    - `size`：书库目录占用字节数（`data` 为 int，缓存 10 分钟）
    - `monthly`：按月新增数，`data` 为 `[{month: "YYYY-MM", ebook, physical}]`，按月份倒序
    - `tags`：热门标签前 50，`data` 为 `[{name, count}]`
    - `categories`：分类分布，`data` 为 `{items: [{name, count}], uncategorized}`
- **说明**：结果缓存（size 600 秒，其余 60 秒），过期后先返回旧数据并在后台刷新。
- **响应**：
  - `err` (string): `ok` / `params.invalid`（未知 kind）/ `stats.failed`
- **响应示例**：

```json
{
  "err": "ok",
  "data": [{"month": "2026-09", "ebook": 42, "physical": 3}]
}
```

### 6.32 系统信息

- **路径**：`/api/sysinfo`
- **方法**：GET
- **认证**：无需认证
- **参数**：无
- **响应**：
  - `err` (string): `ok` / `not_installed`
  - `data` (object): `books`、`tags`、`authors`、`audiobooks`、`publishers`、`series`、`categories`、`folders`、`physicals`、`mtime`、`users`、`version`、`active`、`installed`、`upgrable` 等
- **响应示例**：

```json
{
  "err": "ok",
  "data": {"books": 1200, "authors": 530, "physicals": 80, "version": "v4.4.0", "...": "..."}
}
```

### 6.33 致谢名单

- **路径**：`/api/admin/thanks/notes`
- **方法**：GET
- **认证**：无需认证
- **参数**：无
- **响应**：`names` (array[string]): 致谢名单（读取静态文件 `thanks_to.txt`，逗号分隔）
- **响应示例**：

```json
{
  "err": "ok",
  "names": ["Alice", "Bob"]
}
```

### 6.34 推荐资源站点

- **路径**：`/api/admin/resources`
- **方法**：GET
- **认证**：需要管理员权限
- **参数**：无
- **说明**：从书栈获取资源站点列表（失败时使用内置默认列表），缓存 2 小时；图标经 `/api/favicon/<filename>` 本地缓存。
- **响应**：`resources` (array): `{icon, title, link}`；`icon` 为本地缓存地址 `/api/favicon/<域名>.ico|svg`，尚未缓存时为 null，抓取失败时为空字符串
- **响应示例**：

```json
{
  "err": "ok",
  "resources": [{"icon": "/api/favicon/dushupai.com.ico", "title": "读书派", "link": "https://dushupai.com/"}]
}
```

### 6.35 测试 AI 服务连接

- **路径**：`/api/admin/ai/test`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - JSON Body：
    - `api_url` (string, 必填): API 地址
    - `api_key` (string, 必填): API Key
    - `api_model` (string, 必填): 模型名
- **响应**：
  - `err` (string): `ok` / `params.error`（参数缺失）/ `error`（连接失败，`msg` 含原因）
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "AI服务连接测试成功"
}
```

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
  - `force` (bool, 可选): 强制导入（默认 false）
- **说明**：已有导入任务运行时返回 `err=empty`；出错时 `server.error`。
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
- **参数**：无（扫描有声书导入目录，按目录与书库书籍匹配后导入）
- **响应**：`err`: `ok` / `running`（已有导入任务）
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "有声书导入任务已启动"
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
  - `offset` (int, 可选): 分页偏移量，默认 0
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
- **认证**：`token` 查询参数（管理员在设置中配置的 `AI_MCP_TOKEN`），或调用 `login` 工具取得的 token（此时每个工具调用都需带 `token` 参数）
- **参数**：
  - GET: 获取MCP服务信息
  - POST: JSON-RPC 2.0 请求，支持 `initialize`、`tools/list`、`tools/call`
    - `token` (query, 可选): 访问Token
- **工具集**：
  - 与 MyBooks skill（`skills/mybooks`）同名同参的工具，定义在 `webserver/mcp/api_tools.py`。由 MCP 以已认证用户身份通过本机回环 HTTP 调用本文档中的 `/api/...` 接口，返回值即对应接口的 JSON。不含 `book_upload`、`tts_clone_upload`、`tts_clone_audio`（它们读写调用方本地文件）。
  - MCP 独有工具：`login`、`logout`、`get_books_count`、`get_books`、`update_book_info`、`query_book_metadata`、`auto_fill_book_info`。
  - `search_books` 仍兼容旧参数 `rating`、`tags`（逗号分隔）、`create_time`，会转换为 Calibre 表达式。
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

POST `tools/call` 响应（`text` 为工具结果的 JSON 字符串）：
```json
{
  "err": "ok",
  "jsonrpc": "2.0",
  "id": 1,
  "result": {"content": [{"type": "text", "text": "{\"err\": \"ok\", ...}"}]}
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
  "server": "mybooks-mcp"
}
```

---

## 14. 书单接口

书单（booklist）是用户自建的书籍集合，每人最多 20 个，可设为公开供他人浏览、点赞。

**书单对象**字段：`id`、`name`、`description`、`color`、`is_public`、`is_sticky`（管理员置顶）、`view_count`、`like_count`、`book_count`、`create_time`、`update_time`（ISO8601）、`owner`（`{id, username, avatar}`）、`is_owner`、`liked_by_me`；列表接口另带 `cover_books`（最近加入的最多 12 本：`{book_id, title, img, thumb, href}`）。

**通用错误码**：`booklist.not_found`（书单不存在）、`permission.denied`（非所有者/管理员，或访问他人私有书单）、`params.invalid`（请求体不是合法 JSON 等）。

### 14.1 我的书单

- **路径**：`/api/booklists/mine`
- **方法**：GET
- **认证**：需要登录
- **参数**：无
- **响应**：`booklists` (array): 书单对象
- **响应示例**：

```json
{
  "err": "ok",
  "booklists": [{"id": 7, "name": "2026 科幻必读", "is_public": true, "book_count": 12, "cover_books": [...], "...": "..."}]
}
```

### 14.2 公开书单

- **路径**：`/api/booklists/public`
- **方法**：GET
- **认证**：无需认证
- **参数**：
  - `page` (int, 可选): 默认 1
  - `page_size` (int, 可选): 默认 20，最大 50
- **响应**：`total`、`page`、`page_size`、`booklists`
- **响应示例**：

```json
{
  "err": "ok",
  "total": 35,
  "page": 1,
  "page_size": 20,
  "booklists": [...]
}
```

### 14.3 我点赞的书单

- **路径**：`/api/booklists/liked`
- **方法**：GET
- **认证**：需要登录
- **参数**：无
- **响应**：`booklists` (array): 书单对象

### 14.4 首页展示书单

- **路径**：`/api/booklists/homepage`
- **方法**：GET
- **认证**：无需认证
- **参数**：无
- **说明**：最多返回 2 个书单；`ENABLE_HOMEPAGE_BOOKLISTS` 关闭时返回空数组。
- **响应**：`booklists` (array): 书单对象

### 14.5 创建书单

- **路径**：`/api/booklist/create`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - JSON Body：
    - `name` (string, 必填): 书单名称
    - `description` (string, 可选): 简介，超过 500 字符截断
    - `color` (string, 可选): 书单颜色
    - `is_public` (bool, 可选): 是否公开，默认 false
- **响应**：
  - `err` (string): `ok` / `params.invalid`（名称为空）/ `booklist.limit_exceeded`（超过每人 20 个上限）
  - `booklist` (object): 新书单
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "创建成功",
  "booklist": {"id": 7, "name": "2026 科幻必读", "...": "..."}
}
```

### 14.6 书单详情 / 修改书单

#### GET 书单详情

- **路径**：`/api/booklist/<id>`
- **方法**：GET
- **认证**：公开书单无需认证；私有书单仅所有者或管理员
- **参数**：
  - `id` (path, 必填): 书单ID
  - `order` (string, 可选): `desc`（默认，最近加入在前）/ `asc`
  - `page` (int, 可选): 默认 1
  - `page_size` (int, 可选): 默认 24，最大 60
- **响应**：`booklist` (object): 书单对象（不含 `cover_books`），另含 `books`（当前页书籍卡片 `{book_id, title, img, thumb, href}`）、`books_total`、`page`、`page_size`
- **响应示例**：

```json
{
  "err": "ok",
  "booklist": {"id": 7, "name": "2026 科幻必读", "books": [{"book_id": 42, "title": "三体", "img": "...", "thumb": "...", "href": "/book/42"}], "books_total": 12, "page": 1, "page_size": 24, "...": "..."}
}
```

#### POST 修改书单

- **路径**：`/api/booklist/<id>/update`（`POST /api/booklist/<id>` 等价）
- **方法**：POST
- **认证**：需要登录；所有者或管理员
- **参数**：
  - `id` (path, 必填): 书单ID
  - JSON Body（只修改传入的字段）：`name`（不能为空串）、`description`（≤500 字符）、`color`、`is_public`
- **响应**：`booklist` (object): 修改后的书单

### 14.7 删除书单

- **路径**：`/api/booklist/<id>/delete`
- **方法**：POST
- **认证**：需要登录；所有者或管理员
- **参数**：`id` (path, 必填): 书单ID
- **说明**：只删除书单，不删除书籍本身。
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "已删除"
}
```

### 14.8 置顶书单

- **路径**：`/api/booklist/<id>/sticky`
- **方法**：POST
- **认证**：需要管理员权限
- **参数**：
  - `id` (path, 必填): 书单ID
  - JSON Body：
    - `is_sticky` (bool, 可选): 不传时切换当前状态
    - `sticky_order` (int, 可选): 置顶排序
- **响应**：`booklist` (object): 修改后的书单

### 14.9 点赞/取消点赞

- **路径**：`/api/booklist/<id>/like`
- **方法**：POST
- **认证**：需要登录；私有书单不能点赞
- **参数**：`id` (path, 必填): 书单ID
- **响应**：`liked` (bool): 操作后是否处于点赞状态
- **响应示例**：

```json
{
  "err": "ok",
  "liked": true
}
```

### 14.10 记录浏览

- **路径**：`/api/booklist/<id>/view`
- **方法**：POST
- **认证**：公开书单无需认证；私有书单仅所有者或管理员
- **参数**：`id` (path, 必填): 书单ID
- **说明**：浏览数 +1。
- **响应示例**：`{"err": "ok"}`

### 14.11 向书单加书

- **路径**：`/api/booklist/<id>/books/add`
- **方法**：POST
- **认证**：需要登录；所有者或管理员
- **参数**：
  - `id` (path, 必填): 书单ID
  - JSON Body：`book_ids` (array[int]) 或 `book_id` (int)，二选一必填；不存在的书自动忽略
- **响应**：
  - `err` (string): `ok` / `params.invalid` / `params.book.invalid`（全部书籍都不存在）
  - `added` (int): 新加入的数量（已在书单中的不重复计数）
  - `book_count` (int): 书单当前书籍数
- **响应示例**：

```json
{
  "err": "ok",
  "msg": "已加入书单",
  "added": 2,
  "book_count": 14
}
```

### 14.12 从书单移出书籍

- **路径**：`/api/booklist/<id>/books/remove`
- **方法**：POST
- **认证**：需要登录；所有者或管理员
- **参数**：
  - `id` (path, 必填): 书单ID
  - JSON Body：`book_id` (int, 必填)
- **响应**：
  - `err` (string): `ok` / `params.invalid`（未指定书籍或书籍不在书单中）
  - `book_count` (int): 书单当前书籍数

### 14.13 书籍所在书单

- **路径**：`/api/book/<id>/booklists`
- **方法**：GET
- **认证**：需要登录
- **参数**：`id` (path, 必填): 图书ID
- **说明**：列出当前用户自己的书单，并标记哪些已包含该书（用于“加入书单”面板）。
- **响应**：`booklists` (array): `{id, name, color, is_public, contains_book}`
- **响应示例**：

```json
{
  "err": "ok",
  "booklists": [{"id": 7, "name": "2026 科幻必读", "color": "#3f51b5", "is_public": true, "contains_book": true}]
}
```

---

## 15. 阅读数据同步接口

供 MyReader 等客户端同步书籍/批注/阅读配置，以及导入第三方批注。所有接口需开启同步功能，否则返回 `sync.disabled`。

### 15.1 同步记录

#### GET 拉取增量

- **路径**：`/api/sync`
- **方法**：GET
- **认证**：需要登录
- **参数**：
  - `since` (int, 必填): Unix 毫秒时间戳，返回此后更新/删除的记录
  - `type` (string, 可选): `books` / `configs` / `notes`，不传返回全部
  - `book` (string, 可选): 只返回某本书（`book_hash`）；MyBooks 书库书籍的 `book_hash` 为 `cloud-<book_id>-<format>`，如 `cloud-42-epub`
  - `own` (int, 可选): `1`（默认）只返回自己的记录；`0` 额外包含其他用户共享的批注（受 `ENABLE_SHARED_NOTES` 与 `book` 参数约束）
- **响应**：`books` / `notes` / `configs` (array|null)，记录格式见 Sync 文档
- **响应示例**：

```json
{
  "books": null,
  "notes": [{"id": "...", "book_hash": "cloud-42-epub", "type": "annotation", "cfi": "epubcfi(...)", "text": "……", "note": "", "updated_at": 1790000000000}],
  "configs": null
}
```

#### POST 推送变更

- **路径**：`/api/sync`
- **方法**：POST
- **认证**：需要登录
- **参数**：JSON Body：`{books?: [], notes?: [], configs?: []}`，按 `updated_at` 最后写入者胜出合并
- **响应**：合并后的结果，格式同 GET；请求体非法时 `err=params.invalid`

### 15.2 导入第三方批注

- **路径**：`/api/sync/import`
- **方法**：POST
- **认证**：需要登录
- **参数**：
  - JSON Body：
    - `book_id` (int, 必填): 书籍ID（必须有 EPUB 格式）
    - `anchors` (array[object], 必填): 待导入批注，每项：
      - `id` (string, 必填): 来源系统中的稳定ID（用于幂等去重）
      - `text` (string, 可选): 划线原文，用于全文定位；省略时退化为章节开头书签
      - `chapterHint` (string, 可选): 章节标题，辅助定位
      - `note` (string, 可选): 想法/评论
      - `color` (string, 可选): 高亮颜色，默认 `yellow`
      - `style` (string, 可选): `highlight` / `underline` / `squiggly`
      - `createdAt` (int, 可选): 毫秒时间戳
      - `source` (string, 可选): 来源标记，默认 `wxread`
    - `on_ambiguous` (string, 可选): 原文多处匹配时 `error`（默认）/ `first_match`
    - `dry_run` (bool, 可选): 默认 true，只返回定位报告不写入；false 时写入
    - `force` (bool, 可选): 默认 false；true 时忽略去重，全部重新定位（EPUB 文件被替换时使用）
- **说明**：再次导入会自动去重——`text`/`chapterHint` 未变化的批注直接复用上次的 CFI（结果项带 `reused: true`）。
- **响应**：
  - `err`（仅出错时）：`sync.disabled` / `params.invalid` / `params.book.invalid` / `book.no_epub` / `sync.import.failed`
  - `book_id`、`book_hash`、`dry_run`
  - `results` (array): 每项 `{id, status, cfi?, reused?, degraded?, matchCount?}`；`status` 为 `ok` / `ambiguous` / `no_match`，`degraded="chapter_start"` 表示退化为章节开头书签
  - `pushed` (object): 仅 `dry_run=false` 时返回，写入后的 notes（格式同 GET /api/sync）
- **响应示例**：

```json
{
  "book_id": 42,
  "book_hash": "cloud-42-epub",
  "dry_run": true,
  "results": [
    {"id": "wxread-123", "status": "ok", "cfi": "epubcfi(/6/8!/4/2/1:0)"},
    {"id": "wxread-124", "status": "ambiguous", "matchCount": 3},
    {"id": "wxread-125", "status": "no_match"}
  ]
}
```

### 15.3 清除已导入的批注

- **路径**：`/api/sync/import/clear`
- **方法**：POST
- **认证**：需要登录
- **参数**：JSON Body：`book_id` (int, 必填)
- **说明**：删除（墓碑化）当前用户通过 15.2 导入到该书的全部批注，不影响其他批注和其他用户。用于“重来”，日常重复同步无需调用（15.2 已自动去重）。
- **响应**：`book_id`、`book_hash`、`cleared`（清除条数）
- **响应示例**：

```json
{
  "book_id": 42,
  "book_hash": "cloud-42-epub",
  "cleared": 18
}
```

### 15.4 同步变更通知（WebSocket）

- **路径**：`/api/sync/events`
- **方法**：WebSocket
- **认证**：需要登录（Cookie）；未登录关闭码 4003，同步未开启关闭码 4004
- **消息**：客户端发送 `{"type": "ping"}`，服务端回复 `{"type": "pong"}`；有其他设备推送变更时服务端主动下发通知，客户端据此调用 GET /api/sync 拉取。

---

## 16. Toolbox 工具接口

工具箱接口均需**管理员权限**（`bg_raw`、`texture_raw` 两个图片资源接口除外）。长任务类工具的通用模式：`POST` 启动任务 → 返回 `{"err": "ok", "msg": "...已启动..."}`；同一工具同时只能运行一个任务（否则 `task.running`）；`GET .../progress` 轮询，返回 `data`（含 `status`: `running`/`completed`/`failed`/`cancelled`、`progress` 百分比及工具特定字段），失败时 `err=task.failed`，从未启动时 `err=task.not_found`。

### 16.1 工具管理

#### GET 工具列表

- **路径**：`/api/toolbox/list`
- **参数**：`include_disabled` (string, 可选): `1` 时包含已禁用的外部工具（管理页使用）
- **响应**：
  - `tools` (array): `id`、`name`、`description`、`revision`、`author`、`publish_date`、`page`、`repo_url`、`type`（`builtin`/`tool`）、`source`、`status`（`enabled`/`disabled`）、`pending_restart`
  - `dev_mode` (bool): 是否开启开发者模式（允许上传安装）
  - `store_enabled` (bool): 是否开启工具商店

#### GET 工具商店索引

- **路径**：`/api/toolbox/store/index`
- **参数**：`refresh` (string, 可选): `1` 时强制刷新
- **响应**：`enabled` (bool)、`tools` (array): 商店工具列表

#### POST 从商店安装/更新

- **路径**：`/api/toolbox/<tool_id>/install`
- **响应**：`err`: `ok` / `store.disabled` / `store.not_found` / `store.invalid` / `store.download_failed` / `tool.invalid` / `tool.state`；成功时 `data` 为安装记录。重启后生效。

#### POST 上传安装包

- **路径**：`/api/toolbox/install/upload`（新安装）、`/api/toolbox/<tool_id>/update/upload`（更新）
- **参数**：表单文件 `file` (file, 必填): `.zip` / `.7z` 工具包
- **说明**：需开启开发者模式，否则 `dev_mode.disabled`；重启后生效。
- **响应**：`err`: `ok` / `dev_mode.disabled` / `params.missing` / `tool.invalid` / `tool.state`；成功时 `data` 为安装记录

#### POST 启用 / 禁用

- **路径**：`/api/toolbox/<tool_id>/enable`、`/api/toolbox/<tool_id>/disable`
- **响应**：`err`: `ok` / `tool.not_found` / `tool.permission`；`data` 为安装记录

#### DELETE 卸载

- **路径**：`/api/toolbox/<tool_id>`
- **方法**：DELETE
- **响应**：`err`: `ok` / `tool.not_found` / `tool.permission`；重启后彻底生效

### 16.2 MiMo TTS 有声书（mimo_tts）

EPUB 转有声书（WAV），支持 MiMo TTS / OpenAI TTS 兼容接口。公共 API 参数：

| 参数 | 说明 |
|---|---|
| `api_key` | API Key（必填） |
| `api_url` | API 地址 |
| `model_name` | 模型名；`api_type=chat_completions` 时固定为 `mimo-v2.5-tts`，使用克隆音色时为 `mimo-v2.5-tts-voiceclone` |
| `api_type` | `chat_completions`（默认，MiMo）/ `audio_speech`（OpenAI 格式）/ 其它自定义 |
| `auth_type` | `api-key`（默认，请求头 `api-key`）/ 其它值（请求头 `Authorization: Bearer`） |
| `voice_desc` | 音色描述（chat_completions），为空时使用默认描述 |
| `voice_name` | 预置音色（audio_speech 默认 `alloy`） |
| `clone_voice` | 克隆音色名称（仅 MiMo 类型） |

#### POST 测试连接并保存配置

- **路径**：`/api/toolbox/mimo_tts/test`
- **参数**：JSON Body：上表参数，`api_key`、`api_url`、`model_name` 必填
- **说明**：用一句测试文本实际合成；**成功后将配置加密保存**（没有单独的“保存配置”接口）。
- **响应**：`err`: `ok`（“连接成功，配置已保存”）/ `params.missing` / `clone.not_found` / `test.failed`

#### GET / DELETE 已保存的配置

- **路径**：`/api/toolbox/mimo_tts/config`
- **方法**：GET 返回 `config`（上表字段，含 `api_key` 明文；未保存时为 null）；DELETE 清除配置

#### POST 开始转换

- **路径**：`/api/toolbox/mimo_tts/convert`
- **参数**：JSON Body：`book_id` (int, 必填) + 上表参数（`api_key` 必填；非 `chat_completions` 类型需 `api_url`、`model_name`）
- **响应**：`err`: `ok` / `params.missing` / `params.invalid`（克隆音色仅支持 MiMo 类型）/ `clone.not_found` / `task.running`

#### GET 转换进度

- **路径**：`/api/toolbox/mimo_tts/progress`
- **响应**：`data`: `status`、`progress`、`book_id`、`stage`、`chapter`、`total`、`chapter_title`

#### 克隆音色

- `POST /api/toolbox/mimo_tts/clone/upload`：表单文件 `file`（MP3/WAV，≤7MB）+ 表单字段 `voice_name`（中英文、数字、下划线、连字符）；同名覆盖。返回 `data.name`；`err` 可能为 `params.missing` / `params.invalid`
- `GET /api/toolbox/mimo_tts/clone/list`：`clones` (array): `{name, ext, size, mtime}`
- `POST /api/toolbox/mimo_tts/clone/delete`：JSON `voice_name` (必填)；`err` 可能为 `clone.not_found`
- `GET /api/toolbox/mimo_tts/clone/audio?voice_name=<name>`：返回音频二进制（非 JSON）

#### 音色提示词

- `GET /api/toolbox/mimo_tts/prompt/list`：`prompts` (array): `{name, desc}`
- `POST /api/toolbox/mimo_tts/prompt/save`：JSON `name`、`desc`（均必填，同名覆盖），返回 `data.name`
- `POST /api/toolbox/mimo_tts/prompt/delete`：JSON `name` (必填)；`err` 可能为 `prompt.not_found`

### 16.3 EPUB 美化（epub_beautify）

#### POST 预览

- **路径**：`/api/toolbox/epub_beautify/preview`
- **参数**：JSON `book_id` (int, 必填)
- **响应**：`data`: 预览信息；`err` 可能为 `params.missing` / `params.invalid` / `preview.failed`

#### POST 执行美化

- **路径**：`/api/toolbox/epub_beautify/run`
- **参数**（JSON）：
  - `book_ids` (array[int]) 或 `book_id` (int): 必填，单次最多 100 本
  - `preset` (string): 风格预设，默认 `classic`；可选 `classic`、`modern`、`webnovel`、`classical`、`youth`、`children`、`refined`、`xuanzhi`、`inkstone`、`voyage`、`navy`、`vertclassical`
  - `toc_style` (string): `elegant`（默认）/ `cool` / `seal` / `minimal`
  - `toc_depth` (int): 目录层级 1~6，不传为全部；`toc_columns` (bool): 目录双栏
  - `use_system_fonts` (bool): 默认 true；`font_overrides` (object): `{body, head, kai, code}` 布尔
  - `cleanup` (object): `{leading, empty, meta, toc_blank}` 布尔开关
  - `palette_overrides` (object): 自定义配色，键 `accent`/`accent_light`/`accent_dark`/`muted`/`border`/`quote_bg`/`code_bg`/`toc_gradient`，值为 `#RGB`/`#RRGGBB`
  - `page_tint` (bool|"on"|"off"): 全书主题底色；`bg_image` (bool): 使用上传的背景图
  - `dialogue` (bool): 对话行点缀；`title_split` (bool): 标题双行排版
  - `para_indent` (bool): 首行缩进；`para_gap` (number): 段间距 0~3em；`para_mode` (string, 兼容旧参数): `indent`/`spacing`
  - `notes` (bool): 注释美化；`note_mark` (string): `orig`（默认）/ `sym` / `num` / `zhu` / `svg:<模板>`
  - `suffix` (string): 输出文件名后缀，≤30 字符
- **响应**：`err`: `ok` / `params.missing` / `params.invalid` / `task.running`

#### GET 进度

- **路径**：`/api/toolbox/epub_beautify/progress`

#### 背景图与纹理

- `POST /api/toolbox/epub_beautify/bg_upload`：表单文件 `file`，返回 `data`（背景图信息）；`err` 可能为 `params.invalid` / `bg.failed`
- `GET /api/toolbox/epub_beautify/bg_meta`：`data.has` 是否已上传及图片信息
- `POST /api/toolbox/epub_beautify/bg_delete`：`err` 可能为 `bg.not_found`
- `GET /api/toolbox/epub_beautify/bg_raw`：背景图二进制（无需认证）
- `GET /api/toolbox/epub_beautify/texture_raw?builtin_id=<id>`：内置纹理图片二进制（无需认证）

### 16.4 EPUB 合集（epub_merge）

- `POST /api/toolbox/epub_merge/preview`：JSON `book_ids` (array[int], 必填)，返回 `data`（合并预览）；`err` 可能为 `epub_merge.preview_failed`
- `POST /api/toolbox/epub_merge/merge`：JSON 参数：
  - `book_ids` (array[int], 必填): 2~20 本
  - `title` (string, 必填): 合集标题（≤100）
  - `authors` (array[string])、`description` (string)、`isbns` (array[string])、`tags` (array[string])、`publisher` (string)、`language` (string)
  - `divider` (bool): 书间分隔页，默认 true；`delete_source` (bool): 合并后删除源书，默认 false
  - `cover` (object): `{"type": "first"}`（默认，首本有封面的书）/ `{"type": "book:<book_id>"}` / `{"type": "upload:<token>"}`（token 来自 cover_upload）
- `GET /api/toolbox/epub_merge/progress`：合并进度
- `POST /api/toolbox/epub_merge/cancel`：请求取消（当前书籍处理完后停止）；无任务时 `task.not_found`
- `POST /api/toolbox/epub_merge/cover_upload`：表单文件 `file`，返回 `data`（含封面 token）；`err` 可能为 `epub_merge.cover_invalid`

### 16.5 EPUB 拆分（epub_split）

- `POST /api/toolbox/epub_split/chapters`：JSON `book_id` (必填)，返回 `data`（章节列表）
- `POST /api/toolbox/epub_split/generate`：JSON `book_id` (必填)、`chapters` (array, 必填，选中章节)、`use_first_chapter_cover` (bool)；成功返回 `data`（新书信息）；失败 `epub_split.failed`

### 16.6 EPUB 修复（epub_fixer）

- `POST /api/toolbox/epub_fixer/fix`：JSON `book_id` (必填)、`backup` (bool, 默认 false)；后台执行，结果见消息通知

### 16.7 正文替换（text_replace）

- `POST /api/toolbox/text_replace/preview`：JSON `book_id` (必填)、`pattern`、`replacement`、`use_regex` (bool)、`format`（如 `EPUB`/`TXT`），返回 `data`（匹配预览）；失败 `text_replace.preview_failed`
- `POST /api/toolbox/text_replace/run`：同上参数，另有 `suffix`（≤30）；`pattern` 不能为空
- `GET /api/toolbox/text_replace/progress`：进度

### 16.8 TXT 编码修复（txt_encoding_fixer）

- `POST /api/toolbox/txt_encoding_fixer/analyze`：JSON `book_id` (必填)，返回 `data`（编码分析报告）；失败 `txt_encoding_fixer.analyze_failed`
- `POST /api/toolbox/txt_encoding_fixer/fix`：JSON `book_id` (必填)
- `GET /api/toolbox/txt_encoding_fixer/progress`：进度

### 16.9 繁简转换（chinese_converter）

- `POST /api/toolbox/chinese_converter/convert`：JSON：
  - `book_id` (必填)
  - `direction` (string): `t2s`（默认）/ `tw2s` / `tw2sp` / `s2t` / `s2tw` / `s2twp` / `t2tw` / `tw2t`
  - `mode` (string): `book`（默认，生成新书）/ `replace`（替换原文件）
  - `convert_title` (bool, 默认 true)、`use_a5` (bool, 默认 false)、`backup` (bool, 默认 false)
  - `err` 可能为 `params.direction.invalid` / `params.mode.invalid` / `task.running`
- `GET /api/toolbox/chinese_converter/progress`：进度

### 16.10 PDF 瘦身（minify_pdf）

- `POST /api/toolbox/minify_pdf/upload`：表单文件 `file`，返回 `data`: `filename`（服务器暂存名）、`page_count`、`file_size`、`page_width`、`page_height`
- `POST /api/toolbox/minify_pdf/process`：JSON `filename` (必填)、`params` (object)：`max_width`（默认 800）、`bw`、`gray`、`auto`（bool）、`skip_pages`、`drop_pages`（逗号分隔页码，支持负数）、`qualify`（JPEG 质量 1~100，默认 75）、`max_brightness`（0~255）；`err` 可能为 `file.not_found` / `task.running`
- `GET /api/toolbox/minify_pdf/progress?filename=<name>`：`data`: `status`（`running`/`completed`）、`progress`、`download_url`（完成时）；`err` 可能为 `task.failed` / `task.interrupted`
- `GET /api/toolbox/minify_pdf/download?filename=<name>`：下载处理后的 PDF（二进制）

### 16.11 格式精简（formats_pruning）

- `POST /api/toolbox/formats_pruning/start`：JSON `delete` (array, 必填): 要删除的格式组，取值 `pdf` / `epub` / `azw3_mobi` / `txt` / `docx`，不能全选
- `GET /api/toolbox/formats_pruning/progress`：进度

### 16.12 其它书库维护工具

- `POST /api/toolbox/merge_formats/merge`：合并两本书的格式。JSON `source_id`、`target_id`（均必填）；把来源书的格式并入目标书并删除来源书。返回 `added_formats` (array)、`deleted_book_id`；失败 `merge.failed`
- `POST /api/toolbox/author_clean`：作者清理/替换。JSON `action`（`clean` / `replace`）、`author_name`（必填）、`new_author_name`（`replace` 时必填，仅允许字母、数字、`.`、`·`）；`err` 可能为 `params.author_name.missing` / `params.new_author_name.missing` / `params.new_author_name.invalid` / `params.action.invalid`
- `POST /api/toolbox/review_book_language`：启动书名语言检测任务，无参数
- `POST /api/toolbox/rare_book_downloader`：古籍下载。JSON `url` (必填，仅支持 `hkust.edu.hk` 及其子域名)；`err` 可能为 `params.url.missing` / `params.url.unsupported`

### 16.13 书栈接收器（bookbarn_acceptor）

- `GET /api/toolbox/bookbarn_acceptor/status`：`data` 为接收器状态
- `POST /api/toolbox/bookbarn_acceptor/toggle`：JSON `enabled` (bool)，返回最新状态
- `POST /api/toolbox/bookbarn_acceptor/apply_token`：申请书栈 Token，返回 `token`；失败 `params.error`
- `POST /api/toolbox/bookbarn_acceptor/set_collection_hour`：JSON `hour` (int, 0~23)；`err` 可能为 `params.missing` / `params.invalid`

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
- `permission`: 无权操作（权限位不足，或非管理员/书籍所有者）
- `user.need_login`: 需要登录
- `user.no_permission`: 非管理员或书籍所有者
- `params.error` / `params.missing`: 缺少必填参数
- `params.error.idlist`: `idlist` 参数格式错误
- `task.running`: 同类后台任务正在运行
- `task.not_found` / `task.failed`: 后台任务不存在 / 执行失败
- `quota.exceeded`: 今日下载次数已达上限
- `book.duplicate`: 图书已存在
- `samebook`: 同名书籍已存在该格式
- `format.not_found` / `format.not_supported`: 书籍不含 / 不支持该格式
- `booklist.not_found` / `booklist.limit_exceeded`: 书单不存在 / 超过数量上限
- `review.disabled` / `review.banned`: 评论功能未启用 / 用户被禁止评论
- `sync.disabled`: 数据同步功能未启用
- `book.no_epub`: 书籍没有 EPUB 格式
- `confirm.required`: skill/MCP 客户端的删除类工具未确认（服务端接口不返回此码）

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
