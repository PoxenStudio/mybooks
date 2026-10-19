# 系统模式技术方案

> 关联文档：[System_Mode_Design.md](./System_Mode_Design.md)
>
> 适用版本：MyBooks 当前前端（Nuxt 2 / Vue 2）+ Tornado 后端
>
> 核心结论：**一份组合清单、一个配置键、一个前端能力快照、一个功能闸门**。后端只负责保存与下发原始配置，前端统一决定入口、路由、设置区块和首页板块的显隐；未登记的能力一律按「专业·高级」处理。

---

## 1. 目标与非目标

### 1.1 目标

1. **集中管理**：系统模式、功能组合、入口映射只维护在 `app/src/features/` 一处，页面和组件不再散落 `mode === 'personal'` 之类的判断。
2. **配置可保存、可恢复**：模式与用户调整结果落到站点配置文件 `auto.py` 的单一键 `SYSTEM_MODE_CONFIG`，重启、升级、备份后仍能恢复。
3. **以后端存储为边界**：后端只做配置的规范化、持久化和下发，不在各业务接口里新增「当前是什么模式」的判断。
4. **以组合为配置单位**：用户勾选的是「一组功能」（能力组合 Bundle），不是几十个零散功能点。
5. **默认高级**：新增页面、设置区块、导航项、首页板块如果没有登记，默认视为「专业·高级」，在个人/标准模式下自动隐藏，不需要维护一份不断增长的「高级功能清单」。
6. **与既有性能模式彻底区分**：本方案不使用 `lite`、`LITE_*`、`轻模式`、`P 模式` 指代个人/标准模式。`lite` 只属于 `PERFORMANCE_MODE='lite'` 的「极速模式」，是性能优化中的一个高级功能组合。

### 1.2 非目标

1. **不是权限系统**。系统模式控制的是「界面上出现什么」，不是「接口是否允许调用」。个人/标准模式下，直接构造请求访问被隐藏功能的 API，后端仍可能响应；这与现有大量「前端隐藏 + 后端开关」的实现一致。真正的安全边界仍由 `REQUIRE_LOGIN`、管理员校验、访客权限等既有机制负责。
2. **不自动改写既有设置开关**。系统模式不会因为关闭某个组合而把 `ENABLE_BOOK_REVIEW`、`ENABLE_PHYSICAL_BOOKS` 等既有开关写成 `False`，避免模式切换覆盖用户手工配置，也避免「关一次就丢配置」。
3. **不删除数据**。关闭组合只影响呈现与入口，已有评论、书单、留言、设备、统计等数据继续保留。
4. **不改造每一个后端接口**。本期不新增逐接口的能力判断；需要服务端强制的能力继续使用既有开关。
5. **不把外观组合做成功能组合**。个人/标准模式下的外观预设属于「呈现策略」，不是可勾选的能力组合，见第 6.8 节。

### 1.3 与产品方案的三通道关系

产品方案第 2.2 节要求「能力不开放、入口隐藏、设置不显示」三通道一致。本技术方案的分工是：

| 通道 | 实现位置 | 本方案做法 |
| --- | --- | --- |
| 能力不开放 | 既有后端开关 | 不新增模式判断；组合通过 `legacyFlags` 与既有开关组合。若既有开关本身关闭，入口自然消失 |
| 入口隐藏 | 前端 | `$features.enabled()` / 路由守卫 / 导航过滤 |
| 设置不显示 | 前端 | 设置页按组合过滤 section 与搜索索引 |

因此，**模式关闭一个组合时，前端保证「看不到、点不到」；后端是否拒绝直接调用，取决于该功能既有的服务端开关**。这是本期明确的边界，也是「后端只负责存储」的直接结果。

---

## 2. 术语与统一命名

### 2.1 术语表

| 术语 | 英文 / 标识 | 定义 |
| --- | --- | --- |
| 系统模式 | `SystemMode` / `systemMode` | 全局能力预设，取值 `personal`、`standard`、`pro`。它是「预设」，不是权限角色。 |
| 能力组合 | `CapabilityBundle` / `bundle` | **用户可勾选的最小单位**。一个组合代表一个使用场景下的一组入口、设置区块、页面和动作，例如「推送到阅读设备」「有声书」「评论与评分」。 |
| 能力点 | `Capability` / `capability` | 组合内部的一个具体入口、设置区块、导航项或动作。**能力点不单独出现在模式配置里**，只用于映射到组合。 |
| 组合清单 | `BundleRegistry` / `manifest` | 全部组合及能力点映射的唯一清单，位于 `app/src/features/manifest.js`。 |
| 能力快照 | `CapabilitySnapshot` | 前端根据 `sys.systemMode` + `sys.featureOverrides` + 组合清单计算出的只读结果，包含每个组合的 `modeAllows`、`scopeAllows` 与 `enabled`。 |
| 模式范围 | `modeAllows` | 当前模式允许的能力类别。个人/标准 = 核心 + 常用；专业 = 全部。不受用户勾选与既有开关影响。 |
| 启用范围 | `scopeAllows` | `modeAllows && selected`，用于路由守卫。表示「模式允许且用户勾选」。 |
| 模式预设 | `ModePreset` | 每个模式下各常用组合的默认勾选状态。切换模式时按预设重置。 |
| 覆盖项 | `Override` | 用户在当前模式预设之上做的显式调整，持久化在 `SYSTEM_MODE_CONFIG.overrides`。 |
| 支持组合 | `SupportBundle` | 不直接出现在勾选列表、由其它组合的依赖决定是否显示的组合，例如 SMTP 邮件服务。 |
| 兼容开关 | `LegacyFlag` | 既有的站点设置开关，例如 `ENABLE_BOOK_REVIEW`、`sys.allow.book_review`。组合可以声明依赖它们，用于「入口是否出现」的组合判断。 |
| 功能闸门 | `FeatureGate` | 前端统一入口：`$features` 插件、`<FeatureGate>` 组件、`feature-gate` 路由中间件。 |
| 默认高级 | `DEFAULT_TIER = pro_advanced` | 任何未登记的能力点默认归入「专业·高级」，个人/标准不可见。 |
| 极速模式 | `PERFORMANCE_MODE='lite'` | 既有性能优化功能，含 `LITE_GROUP_*`、`LITE_*` 等键。**与本方案的 `systemMode` 无关**。 |

### 2.2 命名禁用表

为避免再次出现「轻模式」与「极速模式」混淆，代码、文档、接口、翻译中统一遵守：

| 禁止用法 | 原因 | 正确用法 |
| --- | --- | --- |
| 用 `lite` / `light` / `轻模式` / `精简模式` 指代个人或标准模式 | `lite` 已被 `PERFORMANCE_MODE='lite'`（极速模式）占用 | `personal` / `standard` / `pro`，中文写「个人版本 / 标准版本 / 专业版本」 |
| 用 `P 模式` / `p` 指代个人模式 | `P` 容易与 performance、pro 混淆 | 写全 `personal` |
| 在业务组件里判断 `systemMode === 'personal'` | 形成散落判断 | 调用 `$features.modeAllows('bundle_id')`、`$features.scopeAllows('bundle_id')` 或 `$features.enabled('bundle_id')` |
| 把 `PERFORMANCE_MODE`、`LITE_GROUP_*` 放进系统模式配置 | 两套模型正交，混在一起会导致「关掉极速模式等于降档」的误解 | 极速模式只属于 `ops_performance` 这个专业·高级组合 |
| 用 `feature` 泛指一个页面/按钮 | 与「能力点」和「组合」混淆 | 页面/按钮叫「能力点」，可勾选的一组叫「组合」 |

### 2.3 三层模型

```text
SystemMode（预设）
   └── CapabilityBundle（可勾选的一组能力，配置单位）
          └── Capability（入口/设置区块/导航/首页板块/动作，不单独勾选）
```

举例：

- 用户看到的是「推送到阅读设备」一个勾选项（组合）。
- 这个组合内部包含：详情页推送按钮、`DEVICES` 设置区块、推送邮件模板、分享到邮箱、管理菜单中的发送到设备对话框（能力点）。
- 用户不会看到「推送按钮」「推送模板」「发送到设备对话框」三个独立开关。

---

## 3. 总体架构

### 3.1 组件关系

```text
┌──────────────────────────────┐
│ 安装配置引导 / 系统设置弹窗   │
│ 选择 mode + 勾选组合          │
└──────────────┬───────────────┘
               │ POST /api/admin/install
               │ POST /api/admin/system-mode
               ▼
┌──────────────────────────────┐
│ Tornado 后端                  │
│  - 只做 normalize / 持久化    │
│  - 写入 auto.py 的             │
│    SYSTEM_MODE_CONFIG         │
│  - 通过 /api/user/info 的 sys  │
│    下发原始 mode + overrides  │
└──────────────┬───────────────┘
               │ sys.systemMode
               │ sys.featureOverrides
               ▼
┌──────────────────────────────┐
│ 前端能力快照                  │
│ app/src/features/resolve.js   │
│  - modeAllows(bundle)         │
│  - scopeAllows(bundle)        │
│  - enabled(bundle)            │
│  - routeAllowed(path)         │
│  - sectionVisible(gid, sid)   │
│  - navVisible(item)           │
│  - homepageSectionEnabled()   │
└──────────────┬───────────────┘
               │
     ┌─────────┼──────────┬─────────────┬──────────────┐
     ▼         ▼          ▼             ▼              ▼
  路由守卫   AppHeader   设置页        首页          页面/组件
  feature-  导航过滤     section/搜索  首页板块       按钮/动作
  gate                  索引过滤      过滤           <FeatureGate>
```

### 3.2 职责边界

| 层 | 负责 | 不负责 |
| --- | --- | --- |
| 后端 `webserver/base/system_mode.py` | 配置结构校验、默认值、时间戳、读取 | 组合清单、模式预设、页面显隐 |
| 后端 handler | `GET/POST /api/admin/system-mode`、安装时写入、`sys` 下发 | 逐功能判断当前模式 |
| 前端 `app/src/features/manifest.js` | 组合定义、tier、默认值、能力点映射 | 保存配置 |
| 前端 `resolve.js` | 计算能力快照 | 读写后端 |
| 前端页面/组件 | 通过 `$features` 查询结果 | 直接读 `systemMode` 做业务判断 |
| 既有设置开关 | 继续控制具体行为 | 被系统模式自动改写 |

---

## 4. 配置模型与持久化

### 4.1 存储位置

系统模式配置是**站点级配置**，与站点标题、语言等一样保存在 `auto.py`：

- 文件：`CONF["settings_path"]/auto.py`（默认 `/data/books/settings/auto.py`）。
- 读取：`webserver/loader.py` 的 `SettingsLoader` 启动时加载 `auto.py`，合并到 `CONF`。
- 写入：`SettingsSaver.save_partial()` / `save_extra_settings()`，由 `SettingsLoader.dumpfile()` 整份写回。
- 备份：`auto.py` 已在现有备份/迁移范围内，无需单独备份接口。

**不要**把 `localStorage` 或浏览器存储当作真值；前端最多用它做首屏缓存/回退，服务端 `sys` 始终是唯一真值。

### 4.2 配置键与结构

统一使用一个键：

```python
SYSTEM_MODE_CONFIG = {
    "version": 1,
    "mode": "personal",          # personal | standard | pro
    "overrides": {               # 仅记录「偏离当前模式预设」的组合
        "opds": True,
        "push_devices": True,
    },
    "updated_at": "2026-10-19T12:34:56+00:00",
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `version` | int | 配置结构版本，不是组合清单版本。当前固定为 `1`。 |
| `mode` | str | 三档之一。非法值回退 `pro`。 |
| `overrides` | dict[str, bool] | 组合 id → 是否启用。只保存与当前模式预设不同的项。 |
| `updated_at` | str | 后端写入时间，UTC ISO 8601，仅用于诊断，不参与判定。 |

### 4.3 为什么保存 overrides 而不是完整勾选列表

假设完整保存 `enabledBundles = [...]`，以后新增一个「标准默认开启」的组合时，老配置里没有这个 id，会被误判为关闭。保存 overrides 后：

- 新模式预设变化、新组合加入时，未显式覆盖的项自动采用当前预设。
- 用户只调整少数项时，配置很小。
- 删除的组合 id 留在 `overrides` 中也不会影响解析（前端查不到组合就忽略）。
- 代价：用户把某项显式设置成「恰好等于默认值」时不会记录；以后默认值变化，该项会跟随新默认。这是有意为之，换取组合清单的可演进性。

### 4.4 解析规则

前端 `resolve.js` 按以下顺序求值。先区分「模式是否允许这类能力」和「用户是否勾选」，否则「设置 section 可见」与「入口是否出现」会混在一起：

```text
1. mode = normalize(sys.systemMode)              // 非法/缺失 => pro
2. overrides = normalize(sys.featureOverrides)   // 只保留合法 id + bool
3. 对每个组合计算 modeAllows（只和模式、tier、可用性有关）：
   - kind === 'support'：modeAllows = visibleWhen 中任一组合 scopeAllows
   - mode === 'pro'：modeAllows = true
   - tier === 'core'：modeAllows = true
   - tier !== 'common'：modeAllows = false（仅专业）
   - tier === 'common'：modeAllows = bundle[mode].available !== false
   - `bundle[mode]` 缺失时按 `{ available: true, default: false }` 处理，避免清单漏写导致运行时异常
4. 计算 selected（用户是否勾选）：
   - tier === 'common'：selected = overrides[id] ?? bundle[mode].default ?? false
   - 其它：selected = true
5. scopeAllows = modeAllows && selected && requires.every(scopeAllows)
6. enabled = scopeAllows && legacyFlags.every(readPath(sys))
7. 未知组合 id / 未登记能力点：modeAllows = (mode === 'pro')，selected = true
```

实现时用 memo 按 id 计算，先算普通组合，再算 `support`（它的 `visibleWhen` 依赖普通组合的 `scopeAllows`）；发现 `requires` / `visibleWhen` 循环引用时按未启用处理，并在清单测试中报错。

关键点：

- **`modeAllows` 只回答「个人/标准/专业这个档位有没有这类能力」**。它决定设置 section 是否显示、模式配置弹窗里是否列出该组合、搜索索引是否包含该 section。常用组合被取消勾选后，它的设置 section 仍然可见，用户才能重新配置并回到模式弹窗勾选。
- **`scopeAllows` = `modeAllows && selected`**。它决定路由是否允许进入；个人/标准范围内但被取消勾选的组合，其页面同样不可访问。
- **`enabled` 在 `scopeAllows` 之上再叠加 `legacyFlags`**。它用于「入口、按钮、导航、首页板块是否出现」。
- **未知即高级**：没有登记的组合、路由、section、导航项、首页板块，一律 `mode === 'pro'` 才可见。
- `requires` 不参与 `modeAllows`，只参与 `scopeAllows`/`enabled`。这样依赖未满足时，设置 section 仍然显示，弹窗里可以说明「需要先开启某个组合」。

### 4.5 模式预设

已登记的常用组合与默认值如下。`🔒` 表示锁定开启，`✅` 表示默认开启但可调整，`➖` 表示默认关闭但可调整，`🚫` 表示当前模式不可用。

| 组合 id | tier | personal | standard | pro |
| --- | --- | --- | --- | --- |
| `core_library` | core | 🔒 | 🔒 | 🔒 |
| `core_reader` | core | 🔒 | 🔒 | 🔒 |
| `core_import_manage` | core | 🔒 | 🔒 | 🔒 |
| `core_reading_state` | core | 🔒 | 🔒 | 🔒 |
| `core_mynexus` | core | 🔒 | 🔒 | 🔒 |
| `core_system` | core | 🔒 | 🔒 | 🔒 |
| `reading_sync` | common | ✅ | ✅ | 🔒 |
| `reading_stats` | common | ✅ | ✅ | 🔒 |
| `shared_notes` | common | ➖ | ✅ | 🔒 |
| `push_devices` | common | ➖ | ✅ | 🔒 |
| `book_review` | common | ➖ | ✅ | 🔒 |
| `audio` | common | ➖ | ✅ | 🔒 |
| `physical_books` | common | ➖ | ➖ | 🔒 |
| `folder_browse` | common | ➖ | ✅ | 🔒 |
| `dictionary` | common | ➖ | ✅ | 🔒 |
| `opds` | common | ➖ | ➖ | 🔒 |
| `webdav` | common | ➖ | ➖ | 🔒 |
| `book_processing` | common | ➖ | ✅ | 🔒 |
| `account_management` | common | 🚫 | ✅ | 🔒 |
| `smtp` | support | 随依赖 | 随依赖 | 🔒 |
| 社区组合（第 5.7 节） | pro_community | 🚫 | 🚫 | 🔒 |
| 高级组合（第 5.7 节） | pro_advanced | 🚫 | 🚫 | 🔒 |

说明：

- 个人版本默认只开「阅读进度/数据同步」与「阅读统计/仪表盘」，其余常用组合默认关闭，用户可在个人模式范围内自行勾选。
- 标准版本默认开启常用组合，但 OPDS、WebDAV、实体书登记除外（默认关闭）。
- 专业版本全部锁定开启，不接受反选。
- `account_management` 在个人版本不可用（个人版本没有用户管理），所以是 `available: false`，不是普通默认关闭。
- `smtp` 是支持组合，不参与勾选；当 `push_devices` 或 `email_notifications` 任一已勾选/已启用时显示。

### 4.6 保存接口

新增管理接口，避免系统模式配置和「保存全部设置」互相覆盖：

#### `GET /api/admin/system-mode`

- 权限：管理员。
- 返回：

```json
{
  "err": "ok",
  "config": {
    "version": 1,
    "mode": "personal",
    "overrides": {"opds": true},
    "updated_at": "2026-10-19T12:34:56+00:00"
  }
}
```

#### `POST /api/admin/system-mode`

- 权限：管理员。
- 请求：

```json
{
  "mode": "personal",
  "overrides": {"opds": true, "push_devices": true}
}
```

- 服务端处理：
  1. 校验 `mode` 属于 `personal/standard/pro`，非法返回 `params.mode.invalid`。
  2. 用 `normalize_overrides` 清洗：key 必须匹配 `^[a-z][a-z0-9_]{0,63}$`，value 必须是 bool，最多 256 项。
  3. `pro` 强制清空 `overrides`。
  4. 生成 `updated_at`，调用 `SettingsSaver.save_partial({SYSTEM_MODE_CONFIG: config})`。
  5. 返回规范化后的 config。
- 服务端**不校验组合 id 是否存在于前端清单**。组合清单由前端维护，后端只做结构与数量校验；未知 id 前端会忽略。这样新增组合不需要改后端。

#### 保存语义

- `mode` 变化：等价于「重置为该模式预设」，前端在保存时把 `overrides` 设为 `{}`（或只保留用户在新模式下再次调整的项）。**模式切换与 overrides 清空必须在同一次 POST 中完成**，避免出现「新模式 + 旧覆盖」的中间态。
- `mode` 不变：只保存当前模式下与预设不同的项。
- 专业模式：`overrides` 永远为空，前端即使提交也会被后端清空。
- 保存成功后前端调用 `$resetSession()` + `$ensureSession({ force: true })` 刷新 `sys`；若当前页面在新模式下已不可见，跳转到 `/` 或 `/admin/settings`，必要时整页刷新，保证导航、设置、首页同时重算。

### 4.7 读取与下发

`GET /api/user/info` 的 `sys` 增加四个字段：

```json
{
  "sys": {
    "systemMode": "personal",
    "featureOverrides": {"opds": true},
    "featureConfigVersion": 1,
    "systemModeUpdatedAt": "2026-10-19T12:34:56+00:00"
  }
}
```

实现位置：`webserver/handlers/base.py` 的 `_sys_info_with()`，在现有 `info.update({...})` 中追加 `system_mode.sys_payload(CONF)`。

这样做的原因：

- 前端本来就会在 `AppHeader.mounted()` 和 `$ensureSession()` 中请求 `/api/user/info`，不需要新增首屏请求。
- 匿名用户也能拿到 `sys`，路由守卫在未登录时也能判断模式范围。
- 配置不是敏感信息，不需要单独鉴权接口。
- `$ensureSession()` 会缓存成功响应 60 秒；因此其他管理员修改模式后，已打开页面最多延迟 60 秒生效。模式保存者自己通过 `$ensureSession({ force: true })` 立即刷新，不受缓存影响。

### 4.8 安装时写入

安装配置引导在最后提交时，把第一页的访问控制和第二页的模式/组合一起写入：

```text
POST /api/admin/install
  username, password, email, title, language
  requireLogin=true|false
  systemMode=personal|standard|pro
  featureOverrides=<JSON 字符串>
  autoFillMeta=true|false
  metaSelectedSources=<JSON 字符串>
```

后端 `AdminInstall.post` 中：

```python
args["REQUIRE_LOGIN"] = self.get_argument("requireLogin", "false") == "true"
args["SYSTEM_MODE_CONFIG"] = system_mode.build_config(
    self.get_argument("systemMode", "pro"),
    parse_json_arg(self.get_argument("featureOverrides", "{}")),
)
```

兼容规则：

- 老安装客户端不传 `systemMode` 时默认 `pro`，保持既有行为。
- 老安装页的 `invite` / `code` 参数可以继续接受，但新引导第一页不再展示；私人图书馆访问码仍归专业·高级。
- 安装只会执行一次；`AdminInstall` 现有逻辑已经清空 `args`，所以不会与老配置合并，必须在 `save_extra_settings` 前显式写入 `SYSTEM_MODE_CONFIG`。

### 4.9 校验、迁移与兼容

| 场景 | 行为 |
| --- | --- |
| `SYSTEM_MODE_CONFIG` 不存在 | 视为 `{"version":1,"mode":"pro","overrides":{}}`，老实例升级后保持完整功能 |
| `mode` 非法/为空 | 回退 `pro` |
| `overrides` 不是 dict | 视为 `{}` |
| 单个 override key 非法 | 丢弃该 key |
| 单个 override value 不是 bool | 丢弃该 key |
| `overrides` 超过 256 项 | 只保留前 256 项，避免异常配置撑大 `auto.py` |
| `version` 未知 | 先按当前结构读取；未来在 `normalize_config` 中增加迁移分支 |
| 组合被重命名 | 在组合清单中用 `aliases: ['old_id']` 兼容旧 override；解析时先做别名映射 |
| 组合被删除 | 旧 override 保留但被忽略；下次保存时可清理 |
| 专业模式 | 强制清空 overrides，保证「专业 = 完整能力」 |
| 老实例升级 | 默认 `pro`，不改变既有行为；由用户主动降档 |

### 4.10 并发、原子性与备份

- 一次保存写一个完整的 `SYSTEM_MODE_CONFIG` 对象，不做字段级部分写。
- 使用 `SettingsSaver.save_partial()`，它会先以当前 `CONF` 中所有可持久化键为基线，再覆盖本次变更，避免把其它设置抹掉。
- 配置写入沿用现有 `auto.py` 整文件写入机制；并发保存是「后写覆盖先写」，与现有站点设置一致。
- `SYSTEM_MODE_CONFIG` 不加入 `SettingsSaver.RESTART_REQUIRED_KEYS`，保存后下一次 `/api/user/info` 即可读到新值，不需要重启。
- 多进程/多 Worker 部署下，配置生效沿用现有 `auto.py` 的加载机制；本方案不引入额外的一致性协议。
- `auto.py` 备份即配置备份；不需要单独的导出接口。

### 4.11 与通用设置保存的关系（必须处理）

`AdminSettings` 目前的保存方式是：新建 `SettingsLoader()`、`clear()`、只放白名单键，然后 `save_extra_settings(args)`。如果直接把 `SYSTEM_MODE_CONFIG` 加进 `ADMIN_SETTING_KEYS`，通用设置页会把模式配置当成普通字段提交；如果不加，它又会在整文件写回时被丢掉。

正确做法：

1. `SYSTEM_MODE_CONFIG` 加入 `PERSISTABLE_KEYS`，让 `save_partial()` 自动带上它。
2. **不加入** `ADMIN_SETTING_KEYS`，通用设置页不能直接写它。
3. 在 `AdminSettings.post()` 构造完 `args` 后、保存前显式补回：

```python
args["SYSTEM_MODE_CONFIG"] = system_mode.read_config(CONF)
```

4. 在 `AdminSettings.get()` 返回给设置页的 `settings` 中移除该键，避免设置页把它当成可编辑字段：

```python
settings = dict(CONF)
settings.pop("SYSTEM_MODE_CONFIG", None)
```

5. 增加回归测试：保存任意普通设置后，`SYSTEM_MODE_CONFIG` 仍存在且内容不变。

---

## 5. 组合清单（Bundle Registry）

### 5.1 文件结构

```text
app/src/features/
  tiers.js          # tier 常量、默认 tier、模式范围
  manifest.js       # 组合定义 + 能力点映射（唯一维护入口）
  resolve.js        # 能力快照解析
  runtime.js        # $features 注入的 API 实现
  presentation.js   # 外观预设等「呈现策略」
  index.js          # 统一导出
app/src/plugins/features.js       # Nuxt 插件，inject('features')
app/src/middleware/feature-gate.js
app/src/components/FeatureGate.vue
app/src/components/SystemModeDialog.vue
```

### 5.2 组合描述结构

```js
// app/src/features/manifest.js
import { TIER } from './tiers';

export const BUNDLES = [
  {
    id: 'push_devices',
    kind: 'bundle',                    // bundle | support
    tier: TIER.COMMON,                 // core | common | pro_community | pro_advanced
    titleKey: 'systemMode.bundle.push_devices.title',
    descKey: 'systemMode.bundle.push_devices.desc',

    // 仅 common 需要：各模式是否可用、默认是否勾选
    personal: { available: true, default: false },
    standard: { available: true, default: true },

    requires: [],                      // 硬依赖的组合 id
    legacyFlags: [],                   // 既有运行时开关，例如 'allow.sync'

    routes: [],                        // 路由前缀/精确路径
    settings: ['push/push-tpl', 'push/push-devices'],
    nav: ['push'],
    homepage: [],
    options: [],                       // 字段选项映射，例如 SIDEBAR_ITEMS/audiobooks
    actions: ['book.detail.push', 'book.detail.emailShare', 'books.push'],
  },
  // ...
];
```

字段约定：

| 字段 | 说明 |
| --- | --- |
| `kind: 'bundle'` | 普通可勾选组合。 |
| `kind: 'support'` | 支持组合，不出现在勾选列表；用 `visibleWhen` 决定显示。 |
| `visibleWhen` | 仅 `support` 使用：依赖的组合 id 数组，任一 `scopeAllows` 为真即显示。 |
| `aliases` | 旧组合 id 数组；解析 overrides 时先做别名映射，用于组合改名后的兼容。 |
| `tier` | `core`、`common`、`pro_community`、`pro_advanced`。未登记的 id 等价于 `pro_advanced`。 |
| `personal` / `standard` | 仅 `common` 使用；`available: false` 表示该模式不可用；`default` 是默认勾选值。 |
| `requires` | 硬依赖；依赖未启用时本组合也被视为未启用。只用于「UI 会坏」的强依赖，不要滥用。 |
| `legacyFlags` | 既有运行时开关路径，例如 `allow.book_review`、`enable_opds_service`。用于 `enabled()`，不用于 `scopeAllows()`。 |
| `routes` | 精确路径（`/audiobooks`）或前缀（`/booklists/*`）。 |
| `settings` | 设置页 section 的 `gid/sid`，例如 `push/push-devices`。 |
| `nav` | 导航能力点 key，例如 `audiobooks`、`memo`。 |
| `homepage` | 首页板块 key，例如 `readingStats`、`index.booklistRecommendation`。 |
| `options` | 字段选项 key，例如 `SIDEBAR_ITEMS/audiobooks`。 |
| `actions` | 页面动作 key，例如 `book.detail.push`。动作 key 由页面约定，不需要后端知道。 |

### 5.3 默认高级规则

```js
export const DEFAULT_TIER = TIER.PRO_ADVANCED;

export function tierOf(bundleId) {
  const bundle = BUNDLE_BY_ID.get(bundleId);
  return bundle ? bundle.tier : DEFAULT_TIER;
}
```

因此：

- 新页面没有写进任何 `routes` → 个人/标准不可访问，专业可访问。
- 新设置 section 没有写进任何 `settings` → 个人/标准不显示，专业显示。
- 新导航项没有写进任何 `nav` → 个人/标准不显示，专业显示。
- 新首页板块没有写进任何 `homepage` → 个人/标准不显示，专业显示。
- 新按钮/动作调用 `$features.enabled('ai_assistant')`，即使 `ai_assistant` 没有登记，也会按「专业·高级」处理。

这就是「默认为高级，不需要在列表中」的实现方式：**清单只登记核心和常用；高级/社区不登记也安全**。

### 5.4 核心组合（所有模式锁定开启）

| id | 包含的能力 | 主要路由 | 设置区块 |
| --- | --- | --- | --- |
| `core_library` | 首页、全部书籍、搜索、作者/出版社/系列/语言/分类/标签/评分、书籍详情、内容推荐、同名图书、首页库统计/随机/最新/自定义卡片 | `/`、`/all`、`/search`、`/author`、`/publisher`、`/series`、`/language`、`/tag`、`/categories`、`/rating`、`/book/*` | `site/site-cats`；首页卡片编辑器 |
| `core_reader` | EPUB/PDF/DJVU/TXT/FB2/CBZ 阅读、阅读器、动态封面、作者信息 | 书籍详情/阅读器内部 | `reading/reader-core` |
| `core_import_manage` | 上传、扫描导入、元数据补全、换源、目录提取、书籍管理后台、封面/格式/删除 | `/admin/imports`、`/admin/books` | `import/imp-upload`、`import/imp-rules`、`import/imp-store`、`services/svc-meta` |
| `core_reading_state` | 在读/待读/读完/收藏/浏览历史/阅读记录 | `/reading`、`/wants`、`/read-done`、`/favorites`、`/history`、`/visits` | — |
| `core_mynexus` | MyNexus 解析、伴读问答、状态与重试 | 书籍详情/阅读器内部 | `services/svc-mynexus` |
| `core_system` | 登录/会话/用户偏好、站点标识、首页配置、设置页、安装、访问控制 `REQUIRE_LOGIN` | `/login`、`/logout`、`/user/usersettings`、`/admin/settings`、`/install`、`/starting`、`/welcome` | `site/site-id`、`site/site-home`、`site/site-home-cards`、`users/users-access` |

> `core_library` 不包含文件夹浏览、实体书、有声书等常用组合的入口；这些入口由各自的组合控制。
>
> `core_import_manage` 只包含核心导入与书籍管理。服务端目录导入、inotify 监控属于高级组合，见 5.7。

### 5.5 常用组合（个人/标准可调整）

| id | 包含的能力 | 默认 personal | 默认 standard | 主要设置区块 | 备注 |
| --- | --- | --- | --- | --- | --- |
| `reading_sync` | 数据同步、跨设备续读、同步存储路径 | ✅ | ✅ | `reading/reader-sync` | 个人多设备刚需 |
| `reading_stats` | 阅读统计、仪表盘、热力图、时长、书量、阅读时长补录、允许用户关闭统计 | ✅ | ✅ | `reading/reader-stats` | 个人默认开 |
| `shared_notes` | 共享划线/笔记 | ➖ | ✅ | `reading/reader-notes` | 个人单账号默认关 |
| `push_devices` | 推送设备、推送模板、分享到邮箱、发送到设备对话框 | ➖ | ✅ | `push/push-tpl`、`push/push-devices` | 启用后显示 `smtp` 支持组合 |
| `book_review` | 评分、评论、评论审核、管理员评论管理 | ➖ | ✅ | `reading/reader-review` | 一个组合同时管评分与评论 |
| `audio` | 有声书、音频播放、转有声书、字幕、播客订阅 | ➖ | ✅ | `reading/reader-audio`、`protocols/proto-podcast` | 播客随有声书 |
| `physical_books` | 实体书登记、册数、书架位置、ISBN、类型互转、封面图章 | ➖ | ➖ | `reading/reader-physical` | 标准默认也关 |
| `folder_browse` | 文件夹层级浏览、文件夹列、批量设置文件夹、详情页文件夹编辑 | ➖ | ✅ | `reading/reader-folder` | 标准默认开 |
| `dictionary` | MyBooks 词典、百度百科、MyDict 自部署词典 | ➖ | ✅ | `reading/reader-dict` | |
| `opds` | OPDS 目录、OPDS 认证、说明页、页脚入口 | ➖ | ➖ | `protocols/proto-opds` | 两种模式默认关 |
| `webdav` | WebDAV 服务、可写目录、说明页、页脚入口 | ➖ | ➖ | `protocols/proto-webdav` | 两种模式默认关 |
| `book_processing` | 保存元数据到文件、提取目录、转 EPUB、拼音排序、清理稀少标签、格式转换/拆分/转 PDF | ➖ | ✅ | 书籍管理/详情页动作 | 不加模式判断，按组合 gate |
| `account_management` | 用户管理、创建/停用账号、重置密码、权限/配额管理 | 🚫 | ✅ | `/admin/users` | 个人版本不可用 |

### 5.6 支持组合

| id | 显示条件 | 包含 | 说明 |
| --- | --- | --- | --- |
| `smtp` | `push_devices` 或 `email_notifications` 任一 `scopeAllows` 为真（常用组合的 `scopeAllows` 已包含勾选状态，因此等同于「已勾选/已启用」） | `push/push-smtp`：SMTP 服务器、账号、密码、加密方式、测试邮件 | 不出现在模式勾选列表；设备推送、邮箱分享、注册/通知邮件共用 |

> 不要把 `smtp` 写进 `push_devices.requires`：`smtp` 的 `visibleWhen` 又依赖 `push_devices`，会形成循环。支持组合只负责「跟着依赖显示」，不参与依赖方的启用判定。

### 5.7 专业·社区与专业·高级组合

以下组合只在专业版本出现。**它们不需要在清单里逐个登记**；未登记的能力点默认就是「专业·高级」。这里列出是为了产品盘点和后续维护时知道「哪些东西属于专业」。

#### 专业·社区（`pro_community`）

| id | 包含 |
| --- | --- |
| `memo` | 站内留言、留言板、留言管理 |
| `expected_books` | 缺书登记、缺书管理、缺书转图书 |
| `booklists` | 公共/收藏/我的书单、首页书单推荐、详情页加入书单 |
| `friend_links` | 友情链接、顶栏友链入口 |
| `social_login` | QQ/微信/微博/GitHub 第三方登录 |
| `self_registration` | 自助注册、注册激活邮件 |
| `crowd_recommendation` | 协同过滤、参考他人行为、评价计入他人推荐、首页推荐给他人 |
| `guest_access` | 访客阅读/下载/上传/推送 |
| `download_quota` | 下载配额、全局配额 |
| `new_user_policy` | 新用户默认权限、注册审批、阅读范围 |
| `book_sharing` | 分享管理、分享卡片、访客书单 |
| `private_books` | 私藏/公开、私藏徽标、按用户分组 |
| `email_notifications` | 注册激活、密码重置、新书邮件通知 |

#### 专业·高级（`pro_advanced`，默认）

| id | 包含 |
| --- | --- |
| `ops_performance` | 极速模式 `PERFORMANCE_MODE='lite'`、`LITE_GROUP_*`、缩略图/磁盘缓存 |
| `ops_logs` | 调试日志、有声书转换日志、自动重载、转换超时 |
| `ops_update` | 自动检查新版本 |
| `ops_toolbox` | 工具箱商店、开发者模式、资源页 |
| `ops_trash` | 回收站、磁盘清理 |
| `ops_network_ssl` | SSL 证书、CDN 域名、Cookie 密钥 |
| `server_import` | 服务端目录导入、inotify 监控、目录重命名更新分类 |
| `bookbarn` | BookBarn 外部书源、更新标签、接收推送 |
| `ai_assistant` | 联网 AI 助手、AI 更新元数据、AI 生成分类 |
| `invite_access` | 私人图书馆访问码/邀请 |
| `douban_advanced` | 豆瓣书源高级参数 |
| `recommend_tuning` | 推荐算法调参 |
| `deployment_params` | 部署路径、并发、缓存目录等 |
| `third_party_services` | Google Analytics、头像服务 |
| `bookbarn_receive` | 接收书栈推送 |
| `audio_proxy` | 有声书转语音代理 |
| `clean_invalid_records` | 清理无效图书记录 |

> 注意：`ops_performance` 只负责「极速模式」这个性能功能。它和 `systemMode` 是两套正交模型：`systemMode` 决定「个人/标准/专业」的呈现范围，`PERFORMANCE_MODE='lite'` 决定「是否启用极速性能策略」。按本方案的分级，极速模式属于专业·高级，个人/标准不可见；专业模式内部仍可通过 `PERFORMANCE_MODE` 单独开关极速策略，不能把 `PERFORMANCE_MODE='lite'` 当成系统模式档位。

### 5.8 能力点映射

#### 5.8.1 路由

| 路由 | 组合 | 说明 |
| --- | --- | --- |
| `/`、`/all`、`/search`、`/author`、`/publisher`、`/series`、`/language`、`/tag`、`/categories`、`/rating`、`/book/*` | `core_library` | 书库核心 |
| `/reading`、`/wants`、`/read-done`、`/favorites`、`/history`、`/visits` | `core_reading_state` | 个人阅读状态 |
| `/admin/settings`、`/user/usersettings`、`/starting`、`/welcome` | `core_system` | 设置与系统页 |
| `/admin/books`、`/admin/imports` | `core_import_manage` | 书籍管理与导入 |
| `/login`、`/logout`、`/active/*`、`/install` | 始终允许 | 登录/安装/激活，不做模式闸门 |
| `/audiobooks`、`/audio/*` | `audio` | 有声书 |
| `/printbooks` | `physical_books` | 实体书 |
| `/folder` | `folder_browse` | 文件夹浏览 |
| `/opds-readme` | `opds` | OPDS 说明页 |
| `/webdav-readme` | `webdav` | WebDAV 说明页 |
| `/admin/users` | `account_management` | 用户管理 |
| `/admin/book-reviews` | `book_review` | 评论管理 |
| `/memos`、`/admin/user-memos` | `memo` | 社区，默认高级 |
| `/expected`、`/admin/all-expected` | `expected_books` | 社区，默认高级 |
| `/booklists/*` | `booklists` | 社区，默认高级 |
| `/soledbooks` | `private_books` | 社区，默认高级 |
| `/admin/shares` | `book_sharing` | 社区，默认高级 |
| `/signup` | `self_registration` | 社区，默认高级 |
| `/s/*` | `book_sharing` | 访客分享链接，默认高级 |
| `/admin/syslog` | `ops_logs` | 高级，默认 |
| `/admin/toolbox`、`/toolbox/*`、`/admin/resources` | `ops_toolbox` | 高级，默认 |
| `/admin/trash` | `ops_trash` | 高级，默认 |

匹配规则：

- 精确路径直接相等；以 `*` 结尾表示前缀匹配（`/book/*` 匹配 `/book/123`，不匹配 `/books`）。
- 多个组合同时匹配时，以最长前缀为准，避免 `/book/*` 覆盖 `/booklists/*` 这类相邻路径。
- 未登记路径默认 `pro_advanced`；`ALWAYS_ALLOWED_PATHS`（`/login`、`/logout`、`/active/*`、`/install`）优先级最高，任何模式都放行。`/starting`、`/welcome` 归 `core_system`，因此同样在所有模式可见。

#### 5.8.2 设置 section

| section | 组合 | 说明 |
| --- | --- | --- |
| `site/site-id` | `core_system` | 站点标识 |
| `site/site-home` | `core_system` | 首页与列表（拆出 `site/site-crowd`） |
| `site/site-home-cards` | `core_system` | 首页卡片编辑器 |
| `site/site-cats` | `core_library` | 分类导航 |
| `reading/reader-core` | `core_reader` | 阅读引擎、动态封面、作者信息 |
| `reading/reader-sync` | `reading_sync` | 数据同步 |
| `reading/reader-stats` | `reading_stats` | 统计开关 |
| `reading/reader-notes` | `shared_notes` | 共享笔记 |
| `reading/reader-review` | `book_review` | 评分与评论（拆出 `reader-crowd`） |
| `reading/reader-physical` | `physical_books` | 实体书与图章 |
| `reading/reader-folder` | `folder_browse` | 文件夹浏览 |
| `reading/reader-audio` | `audio` | 有声书字幕等 |
| `reading/reader-dict` | `dictionary` | 词典 |
| `import/imp-upload` | `core_import_manage` | 上传 |
| `import/imp-rules` | `core_import_manage` | 导入规则（拆出 `imp-server`） |
| `import/imp-store` | `core_import_manage` | 存储布局 |
| `services/svc-meta` | `core_import_manage` | 元数据基础书源（拆出 `svc-douban`） |
| `services/svc-mynexus` | `core_mynexus` | MyNexus |
| `users/users-access` | `core_system` | `REQUIRE_LOGIN` |
| `push/push-smtp` | `smtp`（support） | 邮件服务 |
| `push/push-tpl` | `push_devices` | 推送模板（拆出 `push-notify`） |
| `push/push-devices` | `push_devices` | 推送设备 |
| `protocols/proto-webdav` | `webdav` | WebDAV |
| `protocols/proto-opds` | `opds` | OPDS |
| `protocols/proto-podcast` | `audio` | 播客 |

其余 section（`site/site-friends`、`users/users-guest`、`users/users-reset`、`users/users-register`、`users/users-default`、`users/users-social`、`import/imp-auto`、`services/svc-douban`、`services/svc-ai`、`services/svc-bookbarn`、`protocols/proto-net`、`ops/*` 等）不登记，个人/标准模式一律不可见。它们在产品分类上分属专业·社区或专业·高级，但两者对个人/标准的行为相同；如果希望清单自解释，可以在 `manifest.js` 里显式登记 tier，不登记也不影响显隐。

#### 5.8.3 导航

| 导航 key | 组合 |
| --- | --- |
| `home`、`authors`、`categories`、`tags`、`publishers`、`series`、`languages`、`rating`、`allBooks` | `core_library` |
| `readingInfo`、`favorites`、`wants`、`reading`、`readDone`、`history`、`visits` | `core_reading_state` |
| `user_setting`、`settings`、`feedback` | `core_system` |
| `imports`、`books` | `core_import_manage` |
| `audiobooks` | `audio` |
| `printbooks` | `physical_books` |
| `folders` | `folder_browse` |
| `booklists`、`publicBooklists`、`likedBooklists`、`myBooklists` | `booklists` |
| `memo` | `memo` |
| `friendLinks` | `friend_links` |
| `expected`、`allExpected` | `expected_books` |
| `soledBooks` | `private_books` |
| `users` | `account_management` |
| `shares` | `book_sharing` |
| `bookReviews` | `book_review` |
| `syslog` | `ops_logs` |
| `toolbox`、`resources` | `ops_toolbox` |
| `trash` | `ops_trash` |

`AppHeader` 中每一项都要带 `bundle` 字段；没有 `bundle` 的项被视为高级，在个人/标准模式下隐藏。

#### 5.8.4 首页板块

| 板块 key | 组合 |
| --- | --- |
| `libraryStats` | `core_library` |
| `readingStats` | `reading_stats` |
| `index.myReading` | `core_reading_state` |
| `index.randomRecommendation`、`index.newRecommendation` | `core_library` |
| `custom:*` | `core_library` |
| `index.socialRecommendation` | `crowd_recommendation` |
| `index.booklistRecommendation` | `booklists` |

匹配规则：

- `custom:*` 按前缀匹配，所有自定义卡片都属于 `core_library`。
- 板块 key 没有登记时按 `pro_advanced` 处理；但首页只渲染内置板块与 `custom:*`，未知 key 本来就不会出现。
- `homepageSectionEnabled` 必须同时接受字符串 key 和卡片对象；卡片对象先通过 `cardSectionKey(card)` 归一化，再查表。

#### 5.8.5 字段选项

| 字段 | 选项 | 组合 |
| --- | --- | --- |
| `SIDEBAR_ITEMS` | `publishers`、`categories`、`tags`、`series`、`languages`、`rating` | `core_library` |
| `SIDEBAR_ITEMS` | `audiobooks` | `audio` |
| `SIDEBAR_ITEMS` | `printbooks` | `physical_books` |
| `SIDEBAR_ITEMS` | `folders` | `folder_browse` |
| `SIDEBAR_ITEMS` | `memo` | `memo` |

未登记的选项默认高级，在个人/标准模式下不显示，避免用户勾选了一个永远不会出现的入口。

#### 5.8.6 页面动作（示例）

| 动作 key | 组合 | 位置 |
| --- | --- | --- |
| `book.detail.push`、`book.detail.emailShare`、`books.push` | `push_devices` | 书籍详情、书籍管理 |
| `book.detail.audio`、`imports.audioImport` | `audio` | 详情页、导入页 |
| `book.detail.review`、`books.reviewAdmin` | `book_review` | 详情页、评论管理 |
| `book.detail.booklist` | `booklists` | 详情页 |
| `book.detail.share`、`book.detail.shareCard` | `book_sharing` | 详情页 |
| `book.detail.private` | `private_books` | 详情页 |
| `book.detail.physical`、`books.physicalFilter`、`books.physicalColumns` | `physical_books` | 详情页、书籍管理 |
| `book.detail.folder`、`books.folderColumn`、`books.batchFolder` | `folder_browse` | 详情页、书籍管理 |
| `book.detail.mynexus` | `core_mynexus` | 详情页、阅读器 |
| `book.detail.ai`、`books.aiFill` | `ai_assistant`（未登记，默认高级） | 详情页、书籍管理 |
| `book.detail.bookbarn`、`books.bookbarnTags` | `bookbarn`（未登记，默认高级） | 详情页、书籍管理 |
| `books.cleanInvalid` | `clean_invalid_records`（未登记，默认高级） | 书籍管理 |
| `imports.serverImport` | `server_import`（未登记，默认高级） | 导入页 |
| `reader.sync` | `reading_sync` | 阅读器 |
| `reader.dict` | `dictionary` | 阅读器 |
| `reader.sharedNotes` | `shared_notes` | 阅读器 |
| `reader.audio` | `audio` | 阅读器 |

#### 5.8.7 兼容开关（`legacyFlags`）映射

组合只决定「当前模式允许看到什么」，既有开关继续决定「站点有没有启用这个功能」。两者是**与**关系：`enabled = scopeAllows && legacyFlags.every(readPath(sys))`。因此下表中的开关关闭时，入口应当消失，但设置 section 仍然可见（用 `modeAllows`），以便管理员重新打开。

| 组合 | `legacyFlags` | 对应配置键 / `sys` 字段 | 说明 |
| --- | --- | --- | --- |
| `reading_sync` | `['allow.sync']` | `ENABLE_DATA_SYNC` | 关闭时隐藏同步入口与续读提示 |
| `shared_notes` | `['allow.shared_notes']` | `ENABLE_SHARED_NOTES` | 关闭时阅读器不显示他人笔记 |
| `book_review` | `['allow.book_review']` | `ENABLE_BOOK_REVIEW` | 关闭时评分/评论/审核入口全部隐藏 |
| `physical_books` | `['allow.physical_books']` | `ENABLE_PHYSICAL_BOOKS` | 关闭时实体书登记与筛选列隐藏 |
| `folder_browse` | `['allow.folder']` | `ENABLE_FOLDER_BROWSE` | 关闭时文件夹浏览、文件夹列隐藏 |
| `opds` | `['enable_opds_service']` | `ENABLE_OPDS_SERVICE` | 关闭时页脚入口与首页说明入口隐藏，`/opds-readme` 仍可访问 |
| `webdav` | `['enable_webdav_service']` | `ENABLE_WEBDAV_SERVICE` | 同上 |
| `self_registration` | `['allow.register']` | `ALLOW_REGISTER` | 关闭时登录页注册按钮隐藏 |
| `download_quota` | `['allow.download_quota']` | `ENABLE_DOWNLOAD_QUOTA` | 配额相关入口与列 |
| `server_import` | `['allow.server_import']` | `ENABLE_SERVER_FILE_IMPORT` | 服务端目录导入入口 |
| `core_mynexus` | `['mynexus_enabled']` | `ENABLE_MYNEXUS` | MyNexus 解析与伴读入口 |
| `audio` | `[]` | — | `ENABLE_PODCAST_SERVICE` 只控制播客子入口，不能作为整个有声书组合的开关；播客入口在页面内单独判断 |
| `push_devices` | `[]` | — | SMTP 是否配置完整由设置页/发送动作自行校验，不是布尔开关 |
| `dictionary` | `[]` | — | 词典来源是配置项，不是启用开关 |
| `reading_stats` | `[]` | — | `ENABLE_HOMEPAGE_READING_STATS` 只影响首页统计卡片，映射到 `homepage`，不要写成组合开关 |
| `account_management` | `[]` | — | 个人版本由 `available: false` 控制，不叠加开关 |
| `book_processing` | `[]` | — | 各动作按自身前置条件校验，不设组合级开关 |
| `ops_performance` | `[]` | — | **禁止**把 `PERFORMANCE_MODE` 放进 `legacyFlags`；它是专业模式内部的普通设置项 |

补充规则：

- `legacyFlags` 只写 `sys` 中已经存在的布尔路径，不新增后端字段。需要的开关若尚未下发，先补进 `allow_flags()`，不要在页面里直接读 `settings`。
- `readPath(sys, 'allow.sync')` 在路径不存在或值不是布尔时返回 `true`（fail-open），避免后端字段尚未部署时把功能全部隐藏；拼写错误由清单测试兜底（用一份真实的 `sys` 快照校验每个路径都存在）。这与 `systemMode` 缺失回退 `pro` 的 fail-open 策略一致。
- 数组内是 **AND** 语义。确实需要「多个开关任一成立」时，不要扩展 `legacyFlags`，而是在组合里拆出子能力点，或在 `visibleWhen` 中显式表达。
- 路由判断不叠加 `legacyFlags`。否则 OPDS/WebDAV 关闭后，`/opds-readme` 也会被挡掉，管理员无法查看说明页。
- 既有开关不会因为模式切换被改写；模式只改变前端呈现，不写 `ENABLE_*`。
- 组合勾选**不等于**服务开关已开启。首次安装后，实际入口由「组合已勾选 + `legacyFlags` 对应开关为真」共同决定；例如 `ENABLE_FOLDER_BROWSE` 默认关闭，标准模式即使勾选了 `folder_browse`，文件夹入口仍不出现，需要管理员在设置页打开该开关。设置页应显示对应开关，模式弹窗只负责「这个能力类别是否属于当前档位」。
- `smtp` 这类支持组合没有自己的开关，`visibleWhen: ['push_devices', 'email_notifications']` 即可；SMTP 参数是否填写完整不属于能力范围判断。

### 5.9 维护流程

#### 新增一个常用组合

1. 在 `manifest.js` 的 `BUNDLES` 增加一个对象，`tier: TIER.COMMON`，填写 `personal` / `standard` 默认值。
2. 把它的路由、设置 section、导航 key、首页板块、字段选项、动作分别写进对应数组。
3. 如果是支持组合（如 SMTP），设 `kind: 'support'` 和 `visibleWhen`，不要写 `personal/standard` 默认值。
4. 补 3 种语言的翻译 key。
5. 不需要改后端；`overrides` 只认识字符串 id。

#### 把已有功能归入某个类别

- 核心：把能力点写进对应 `core_*` 组合的数组。
- 常用：把能力点写进对应 `common` 组合的数组；如果是新组合，再补默认值。
- 专业·社区 / 专业·高级：**什么都不用做**。未登记就是高级；如果希望代码可读，可以显式写一个 `tier: TIER.PRO_COMMUNITY` 的组合，但它不会出现在个人/标准配置里。

#### 新增一个页面

- 如果它是核心/常用：把路由写进相应组合的 `routes`。
- 如果它是专业功能：不写。默认高级，个人/标准直接跳回首页。
- 如果它是公共系统页（登录/安装/激活）：加入 `ALWAYS_ALLOWED_PATHS`。

#### 新增一个设置区块

- 如果它属于核心/常用：把 `gid/sid` 写进相应组合的 `settings`。
- 如果它属于专业：不写。默认高级。
- 如果一个 section 里混合了不同归属的字段：先拆分 section，不要在一个 section 上做字段级模式判断。

#### 新增一个动作

- 在页面里使用 `$features.enabled('bundle_id')` 或 `<FeatureGate bundle="bundle_id">`。
- 专业动作可以随便起一个 id（例如 `ai_assistant`），不需要登记；个人/标准会自动隐藏。

### 5.10 组合清单的单元测试

建议增加前端脚本 `app/scripts/check-feature-manifest.js`（或 Jest 测试）检查：

1. 组合 id 唯一，`tier` 合法，`common` 必须有 `personal/standard` 默认值。
2. `requires` / `visibleWhen` 引用的 id 都存在，且没有循环依赖。
3. 同一个路由/section/nav/homepage/option 没有被映射到两个组合。
4. `settings` 中的 `gid/sid` 都能在 `settings.vue` 的 `groups` 中找到（防止拼写错误导致永远不显示）。
5. `legacyFlags` 中的每个路径都能在测试用的 `sys` 快照中解析为布尔值（防止拼写错误导致永久 fail-open）。
6. `routes` 覆盖所有需要 core/common 的页面；未覆盖页面被明确标记为高级（可以通过白名单/注释）。
7. `systemMode` / `featureOverrides` 只允许在 `app/src/features/`、`SystemModeDialog.vue`、安装引导中出现，业务页面禁止直接读取。

---

## 6. 前端运行时

### 6.1 能力快照 API

`app/src/features/runtime.js` 导出 `createFeatureRuntime(getSys)`，`getSys` 每次调用都返回最新的 `sys`（不是一个固定快照）；底层解析在 `resolve.js`。返回：

| API | 用途 | 是否叠加 `legacyFlags` |
| --- | --- | --- |
| `mode` | 当前模式，仅用于模式配置弹窗/外观策略 | — |
| `modeAllows(bundleId)` | 当前模式是否包含该组合类别 | 否 |
| `scopeAllows(bundleId)` | 模式允许且用户已勾选（不看既有开关） | 否 |
| `enabled(bundleId)` | 组合是否真正可见/可用 | 是 |
| `sectionVisible(gid, sid)` | 设置 section 是否显示 | 否 |
| `routeAllowed(path)` | 路由是否允许进入 | 否（路由只看 `scopeAllows`） |
| `navVisible(item)` | 导航项是否显示 | 是 |
| `homepageSectionEnabled(section)` | 首页板块是否显示 | 是 |
| `fieldOptionVisible(fieldKey, value)` | 字段选项是否显示 | 是 |
| `hasOptionFilter(fieldKey)` | 该字段是否登记了选项过滤；未登记时返回原选项 | — |
| `visibleGroups(groups)` | 过滤设置页分组 | 否（只看 `modeAllows`） |
| `filterNav(items)` | 递归过滤导航 | 是 |
| `appearancePolicy()` | 外观呈现策略 | 不适用 |

为什么路由用 `scopeAllows` 而不是 `enabled`：如果 OPDS 服务开关（`ENABLE_OPDS_SERVICE`）暂时关闭，用户仍应能进入 `/opds-readme` 查看说明；入口是否显示由 `enabled` 决定。设置 section 则用 `modeAllows`：常用组合即使没勾选，也要能在设置页配置并重新开启。

为什么字段选项用 `enabled`：`SIDEBAR_ITEMS` 里的 `audiobooks`、`printbooks`、`folders` 只有在对应组合真正开启时才有意义，避免用户在个人模式里勾选一个永远不会出现的侧边栏入口。

### 6.2 插件与 Store

`app/src/plugins/features.js`：

```js
import { createFeatureRuntime } from '~/features/runtime';

export default ({ app }, inject) => {
  const runtime = createFeatureRuntime(() => app.store.state.sys || {});
  inject('features', runtime);
};
```

- 用 getter 读取 `app.store.state.sys`，不缓存快照，保证 `login` mutation 更新 `sys` 后立即生效。
- 在 `nuxt.config.js` 的 `plugins` 中注册，放在 `session` 之后。
- 不需要新增 Vuex 模块；`sys` 已经由 `login` mutation 写入。

`app/src/middleware/feature-gate.js`：

```js
export default async function ({ app, route, redirect }) {
  if (process.server) return;

  // 首屏/深链可能还没有 sys，先走会话接口的缓存拉取
  if (!app.store.state.sys || !app.store.state.sys.systemMode) {
    await app.$ensureSession();
  }

  if (app.$features.routeAllowed(route.path)) return;
  if (route.path === '/') return; // 首页始终允许，防止异常配置导致死循环

  return redirect('/');
}
```

`nuxt.config.js`：

```js
router: {
  middleware: ['require-login', 'feature-gate'],
},
```

注意事项：

- `require-login` 仍在前，负责登录跳转；`feature-gate` 只负责模式范围。
- 配置缺失/请求失败时，`normalizeMode(undefined)` 回退 `pro`，即 fail-open，避免后端暂时不可用时把用户锁在首页外。
- 重定向目标用 `/`，不要用 `/admin/settings`，因为普通用户可能没有管理权限。
- `feature-gate` 只在首次没有 `systemMode` 时拉取；正常跳转不应重复请求。

**对 `plugins/session.js` 的必要改动**：现有 `$ensureSession()` 在 `store.state.user.is_login === true` 时直接返回 store 里的旧 `sys`，`$resetSession()` 只清缓存、不清 `user`。因此模式保存后必须使用强制刷新：

```js
inject('ensureSession', function (options) {
  const force = !!(options && options.force);
  const user = app.store.state.user;
  if (!force && user && user.is_login) {
    return Promise.resolve({ err: 'ok', user, sys: app.store.state.sys });
  }
  if (!force && isFresh()) {
    return Promise.resolve(cached);
  }
  // 其余逻辑不变；force 时跳过上面两个短路，真正请求 /api/user/info
});
```

调用顺序固定为 `$resetSession()` → `$ensureSession({ force: true })`：前者递增 epoch 并丢弃在途的旧响应，后者绕过登录态短路并提交新的 `login` mutation。不要只调用 `$resetSession()`，也不要只调用 `$ensureSession()`。

### 6.3 导航过滤

`AppHeader.vue` 的 `items` 计算属性最后统一走：

```js
return this.$features.filterNav(rawItems);
```

`filterNav` 的规则：

1. 每个 item 必须带 `bundle`；没有 `bundle` 的按高级处理。
2. 叶子项：`enabled(item.bundle)` 为真才保留。
3. 带 `groups` 的父项：先递归过滤子项，**子项有剩余就保留父项**；子项全部被过滤掉时，再按父项自己的 `bundle` 判断。这样「用户中心」这种混合分组不会因为父项写了高级组合，把核心的「个人设置」一起隐藏。
4. 公共项（`/login`、`/`）必须显式写 `bundle: 'core_system'` / `bundle: 'core_library'`；混合分组（如用户中心）父项写 `core_system`，由子项各自 gate。
5. 保留原有 `showItem()`（`SIDEBAR_ITEMS` 站点偏好）逻辑，两者是「与」关系：
   - `showItem(key)` 控制管理员是否在站点设置里关掉了这个入口；
   - `$features.enabled(bundle)` 控制当前模式是否允许这个入口。
6. 迁移时删除 `this.sys.allow.folder`、`this.sys.allow.physical_books`、`this.sys.allow.book_review` 这类零散判断；它们已经通过 `legacyFlags` 合并进 `enabled()`。`AppHeader` 只保留登录态、管理员态和 `showItem()` 三类非模式判断。

示例：

```js
const adminLinks = [
  {
    bundle: 'core_system',
    icon: 'mdi-cog',
    text: 'appHeader.admin',
    groups: [
      { bundle: 'core_system', href: '/admin/settings', text: 'appHeader.systemSettings' },
      { bundle: 'account_management', href: '/admin/users', text: 'appHeader.userManagement' },
      { bundle: 'core_import_manage', href: '/admin/imports', text: 'appHeader.importBooks' },
      { bundle: 'core_import_manage', href: '/admin/books', text: 'appHeader.bookManagement' },
      { bundle: 'book_sharing', href: '/admin/shares', text: 'appHeader.shareManagement' },
      { bundle: 'memo', href: '/admin/user-memos', text: 'memos.pageTitle' },
      { bundle: 'book_review', href: '/admin/book-reviews', text: 'adminBookReviews.pageTitle' },
      { bundle: 'ops_logs', href: '/admin/syslog', text: 'appHeader.syslog' },
      { bundle: 'ops_toolbox', href: '/admin/toolbox', text: 'appHeader.toolbox' },
    ],
  },
];
```

### 6.4 设置页

#### 6.4.1 顶部入口

在 `settings.vue` 顶部操作行左侧增加「系统模式配置」按钮，与右侧的「社区」「使用手册」同一行：

```html
<div class="d-flex justify-space-between align-center flex-wrap mb-2" style="gap: 8px">
  <v-btn class="settings-hint-btn" @click="openSystemMode">
    <v-icon left>mdi-tune-variant</v-icon>
    {{ $t('settings.systemMode.entry') }}
  </v-btn>
  <div class="d-flex" style="gap: 8px">
    <!-- 现有社区/使用手册按钮 -->
  </div>
</div>
```

#### 6.4.2 过滤分组与搜索索引

把 `currentGroups` / `groups` / `flatIndex` 改为基于 `visibleGroups`：

> 过滤依据是 `modeAllows`，不是 `enabled`。常用组合即使当前没勾选（例如个人模式下的共享笔记），其 section 仍然显示，方便用户先在设置里配置、再回到模式弹窗开启；真正不该出现在个人/标准的设置（专业/社区/高级）才整块隐藏。

```js
computed: {
  visibleGroups() {
    return this.$features.visibleGroups(this.groups);
  },
  currentGroups() {
    return this.visibleGroups.filter((g) => g.id === this.activeGroup);
  },
  flatIndex() {
    const idx = [];
    // 只遍历 visibleGroups，hidden section 的字段不会进入搜索索引
    this.visibleGroups.forEach((g) => {
      g.sections.forEach((s) => {
        (s.fields || []).forEach((f) => push(f, g.id, s.id));
        (s.groups || []).forEach((grp) => {
          push(grp, g.id, s.id);
          (grp.fields || []).forEach((f) => push(f, g.id, s.id, this.$t(grp.label)));
        });
      });
    });
    SPECIAL_BLOCKS
      .filter((b) => this.$features.sectionVisible(b.gid, b.sid))
      .forEach((b) => idx.push(/* ... */));
    return idx;
  },
},
watch: {
  visibleGroups(groups) {
    if (groups.length > 0 && !groups.some((g) => g.id === this.activeGroup)) {
      this.activeGroup = groups[0].id;
    }
  },
},
```

模板中的分组 tab 也要从 `groups` 改为 `visibleGroups`。

#### 6.4.3 字段选项过滤

`SIDEBAR_ITEMS` 是 `checkbox_list`，其中 `memo`、`audiobooks`、`printbooks`、`folders` 属于不同组合。增加：

```js
methods: {
  fieldItems(field) {
    // 只有登记过 options 的字段才过滤；其它 checkbox_list 保持原样，
    // 避免把 META_SELECTED_SOURCES、DEVICES 等动态选项误判成高级
    if (!this.$features.hasOptionFilter(field.key)) return field.items || [];
    return (field.items || []).filter((opt) =>
      this.$features.fieldOptionVisible(field.key, opt.value)
    );
  },
}
```

模板：

```html
<v-col v-for="opt in fieldItems(f)" :key="...">
```

这样个人/标准模式下不会出现「站内留言」「未开启的有声书/实体书/文件夹」等无法生效的侧边栏选项；用户开启对应组合后，选项会随 `enabled` 自动出现。同时不会影响其它动态字段。

#### 6.4.4 系统模式配置弹窗

新增 `SystemModeDialog.vue`：

- 打开时 `GET /api/admin/system-mode`。
- 模式选择：个人 / 标准 / 专业三张卡片。
- 组合列表：
  - 核心组合：勾选且置灰。
  - 常用组合：按 `available` 与 `default` 渲染；当前模式不可用的组合不显示。
  - 专业模式：全部锁定勾选，显示「专业模式锁定全部能力」提示，不显示可编辑复选框。
- 依赖关系：`requires` 未满足时置灰并提示原因。
- 切换模式：清空 overrides，复选框回到新模式预设；如果当前有手工调整，弹确认框。
- 保存：只提交与当前模式预设不同的项；`POST /api/admin/system-mode`。
- 保存成功后：`$resetSession()` → `$ensureSession({ force: true })` → 关闭弹窗 → 如果当前路由不再允许，跳转 `/admin/settings`；否则刷新页面数据。

### 6.5 首页

`index.vue` 已经有一个统一入口 `isSectionEnabled(section)`。不要在每个板块里加模式判断，只改这一个方法：

```js
isSectionEnabled(section) {
  if (this.hiddenSections.has(section)) return false;
  return this.$features.homepageSectionEnabled(section);
}
```

这样：

- `HOMEPAGE_CONFIG.hidden` 仍然生效（站点偏好）。
- 组合关闭时，对应板块自动隐藏。
- `custom:*` 自定义卡片属于 `core_library`，不受影响。
- 首页卡片编辑器 `homepage-cards-editor` 也要用同一个 `homepageSectionEnabled` 过滤内置板块，避免用户在个人模式里配置一个永远不会显示的「推荐给他人」。

### 6.6 页面与动作

#### `<FeatureGate>` 组件

```vue
<template>
  <slot v-if="visible"></slot>
</template>

<script>
export default {
  name: 'FeatureGate',
  props: {
    bundle: { type: String, required: true },
    // true = 只看模式范围（用于设置/配置类 UI）
    scopeOnly: { type: Boolean, default: false },
  },
  computed: {
    visible() {
      return this.scopeOnly
        ? this.$features.modeAllows(this.bundle)
        : this.$features.enabled(this.bundle);
    },
  },
};
</script>
```

使用：

```html
<FeatureGate bundle="push_devices">
  <v-btn @click="openPushDialog">{{ $t('book.push') }}</v-btn>
</FeatureGate>
```

#### 允许的写法

```js
this.$features.enabled('audio');
this.$features.modeAllows('book_review');
this.$features.scopeAllows('book_review');
this.$features.sectionVisible('reading', 'reader-audio');
this.$features.routeAllowed('/audiobooks');
```

#### 禁止的写法

```js
// 禁止：散落的模式判断
if (this.$store.state.sys.systemMode === 'personal') { ... }

// 禁止：自建第二份组合判断
if (this.mode !== 'pro' && feature === 'audio') { ... }

// 禁止：把模式配置写进 localStorage 当真值
localStorage.setItem('systemMode', 'personal');
```

允许直接读 `systemMode` 的地方只有：

1. `app/src/features/` 内部；
2. `SystemModeDialog.vue`（编辑模式）；
3. 安装配置引导（选择模式）；
4. `presentation.js`（外观策略）。

### 6.7 登录页与页脚

- 登录页：注册按钮只用 `$features.enabled('self_registration')`；它的 `legacyFlags: ['allow.register']` 已经包含现有 `ALLOW_REGISTER`。不要再写一遍 `sys.allow.register && ...`，否则同一个开关会在两处维护。第三方登录按钮只用 `$features.enabled('social_login')`。
- 页脚：OPDS / WebDAV 链接用 `$features.enabled('opds')`、`$features.enabled('webdav')`；它们已经通过 `legacyFlags` 包含 `sys.enable_opds_service` / `sys.enable_webdav_service`。播客链接用 `$features.enabled('audio') && sys.enable_podcast_service`，因为播客是 `audio` 组合下的子入口，不是组合级开关。
- 书籍详情：推送到设备、有声书、评论、书单、分享、私藏、实体书、文件夹、AI、BookBarn、MyNexus 等动作按 5.8.6 的 key 使用 `FeatureGate` 或 `$features.enabled`。
- 书籍管理：文件夹列、实体书筛选、AI 更新、BookBarn 更新标签、清理无效记录等动作按 5.8.6 处理。

### 6.8 外观呈现策略

个人/标准模式的外观面板默认折叠为三套组合，保留「高级」展开；专业模式保持现有细粒度项。这不是能力组合，不参与 `overrides` 持久化。

`app/src/features/presentation.js`：

```js
export function appearancePolicy(mode) {
  return {
    presetFirst: mode !== 'pro',
    presets: [
      { id: 'bright_minimal', light: true,  accent: 'blue',     background: 'default', radius: 4 },
      { id: 'dark_immersive', light: false, accent: 'bluegray', background: 'aurora',  radius: 8 },
      { id: 'warm_eye',       light: true,  accent: 'orange',   background: 'warm',    radius: 16 },
    ],
  };
}
```

`AppearanceMenu.vue` 只调用 `$features.appearancePolicy()`，不在组件里写 `mode === 'personal'`。

### 6.9 防止散落判断的工程约束

1. 业务组件只允许调用 `$features` 的公开 API，不直接读 `sys.systemMode` / `sys.featureOverrides`，也不复制已经登记在 `legacyFlags` 里的 `sys.allow.*` 判断；兼容开关只在 `manifest.js` 中出现。
2. 新增页面、section、导航、首页板块必须走组合清单；未登记即高级，这是安全默认。
3. 一个设置 section 只能属于一个组合；混合归属必须拆 section，不允许在模板里写 `v-if` 做字段级模式判断。
4. 字段选项（`SIDEBAR_ITEMS`、首页卡片）通过 `fieldOptionVisible` / `homepageSectionEnabled` 过滤，不在模板里逐个硬编码。
5. 代码评审检查：`grep -R "systemMode" app/src` 的命中只能出现在 `app/src/features/`、`SystemModeDialog.vue`、安装引导中。
6. 建议增加 `check-feature-manifest.js`，在 CI 中校验映射完整性（见 5.10）。

---

## 7. 后端实现

### 7.1 `webserver/base/system_mode.py`

只做配置结构，不包含组合清单：

```python
#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""系统模式配置的规范化与读取。

这里刻意不包含任何组合 id 白名单：组合清单由前端维护，后端只负责
存储 mode + overrides，保证新增组合不需要改后端。
"""

import datetime
import re

CONFIG_KEY = "SYSTEM_MODE_CONFIG"
CONFIG_VERSION = 1
MODES = ("personal", "standard", "pro")
DEFAULT_MODE = "pro"
MAX_OVERRIDES = 256

_RE_BUNDLE_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def default_config():
    return {
        "version": CONFIG_VERSION,
        "mode": DEFAULT_MODE,
        "overrides": {},
        "updated_at": "",
    }


def normalize_overrides(raw):
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, value in list(raw.items())[:MAX_OVERRIDES]:
        if isinstance(key, str) and _RE_BUNDLE_ID.match(key) and isinstance(value, bool):
            out[key] = value
    return out


def normalize_config(raw):
    if not isinstance(raw, dict):
        return default_config()

    mode = str(raw.get("mode") or DEFAULT_MODE).strip().lower()
    if mode not in MODES:
        mode = DEFAULT_MODE

    # 未来结构升级在这里做分支迁移；未知版本先按当前结构读取
    version = raw.get("version", CONFIG_VERSION)
    if version != CONFIG_VERSION:
        version = CONFIG_VERSION

    overrides = normalize_overrides(raw.get("overrides"))
    if mode == "pro":
        overrides = {}

    return {
        "version": CONFIG_VERSION,
        "mode": mode,
        "overrides": overrides,
        "updated_at": str(raw.get("updated_at") or ""),
    }


def build_config(mode, overrides):
    cfg = normalize_config({"mode": mode, "overrides": overrides})
    cfg["updated_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat(timespec="seconds")
    return cfg


def read_config(conf):
    return normalize_config(conf.get(CONFIG_KEY))


def sys_payload(conf):
    cfg = read_config(conf)
    return {
        "systemMode": cfg["mode"],
        "featureOverrides": dict(cfg["overrides"]),
        "featureConfigVersion": cfg["version"],
        "systemModeUpdatedAt": cfg["updated_at"],
    }
```

### 7.2 管理接口

在 `webserver/handlers/admin.py` 增加：

```python
class AdminSystemMode(BaseHandler):
    @js
    @auth
    def get(self):
        if not self.admin_user:
            return {"err": "permission.not_admin", "msg": _("当前用户非管理员")}
        return {"err": "ok", "config": system_mode.read_config(CONF)}

    @js
    @auth
    def post(self):
        if not self.admin_user:
            return {"err": "permission.not_admin", "msg": _("当前用户非管理员")}

        try:
            data = tornado.escape.json_decode(self.request.body)
        except Exception:
            return {"err": "params.invalid", "msg": _("参数无效")}
        if not isinstance(data, dict):
            return {"err": "params.invalid", "msg": _("参数无效")}

        mode = str(data.get("mode") or "").strip().lower()
        if mode not in system_mode.MODES:
            return {"err": "params.mode.invalid", "msg": _("系统模式无效")}

        cfg = system_mode.build_config(mode, data.get("overrides"))
        result = SettingsSaver().save_partial({system_mode.CONFIG_KEY: cfg})
        if result.get("err") != "ok":
            return result
        return {"err": "ok", "config": cfg}
```

路由表增加：

```python
(r"/api/admin/system-mode", AdminSystemMode),
```

### 7.3 `sys` 下发

`webserver/handlers/base.py` 的 `_sys_info_with()`：

```python
info.update({
    # ... 现有字段
})
info.update(system_mode.sys_payload(CONF))
return info
```

### 7.4 `SettingsSaver` 与 `AdminSettings`

1. `webserver/base/setting_saver.py`：

```python
PERSISTABLE_KEYS = frozenset(ADMIN_SETTING_KEYS) | frozenset({
    # ...
    "SYSTEM_MODE_CONFIG",
})
```

2. `AdminSettings.get()`：

```python
settings = dict(CONF)
settings.pop("SYSTEM_MODE_CONFIG", None)  # 由 /api/admin/system-mode 单独管理
```

3. `AdminSettings.post()`，在 `save_extra_settings(args)` 前：

```python
# 这个接口用 clear() 重建 args；不补回就会在整文件写回时丢掉模式配置
args["SYSTEM_MODE_CONFIG"] = system_mode.read_config(CONF)
```

4. 不加进 `ADMIN_SETTING_KEYS`，防止通用设置 POST 直接写模式配置。

### 7.5 安装接口

`AdminInstall.post()` 增加：

```python
mode = self.get_argument("systemMode", "pro")
overrides = parse_json_arg(self.get_argument("featureOverrides", "{}"))
require_login = self.get_argument("requireLogin", "false") == "true"

args["REQUIRE_LOGIN"] = require_login
args["SYSTEM_MODE_CONFIG"] = system_mode.build_config(mode, overrides)
```

其中 `parse_json_arg` 做容错：解析失败返回 `{}`，不因为一个坏字段让整个安装失败。写入位置必须在 `apply_localized_default_settings(args, ...)` **之后**，否则会被本地化默认值覆盖。

### 7.6 后端不做的事

明确禁止在业务 handler 中新增：

```python
# 禁止：散落的模式判断
if CONF.get("SYSTEM_MODE_CONFIG", {}).get("mode") == "personal":
    return {"err": "feature.disabled"}
```

原因：

- 组合清单在前端，后端不知道组合语义；
- 逐接口判断会形成第二份真值，新增功能必然漏；
- 模式切换不应导致后端行为突变或数据不可访问；
- 需要安全强制的场景使用既有 `REQUIRE_LOGIN`、管理员权限、访客权限等机制。

如果未来产品要求「服务端硬关闭」，应作为独立阶段：由同一份组合清单生成服务端映射，在一个统一的 API 中间件里判断，而不是散落到各 handler。

---

## 8. 关键流程

### 8.1 安装配置引导

```text
第 1 页：站点基础与管理员账号
  - site_title、site_language
  - 管理员用户名/密码/邮箱
  - REQUIRE_LOGIN
  ↓
第 2 页：系统模式与功能项
  - 选择 personal / standard / pro
  - 核心组合锁定
  - 常用组合按模式预设勾选
  - 专业组合不出现
  ↓
第 3 页：刮削信息（可跳过）
  - auto_fill_meta
  - META_SELECTED_SOURCES
  ↓
POST /api/admin/install
  → 创建管理员
  → 写入 REQUIRE_LOGIN + SYSTEM_MODE_CONFIG
  → 写入刮削设置
  → 跳转首次进入检查
```

交互规则：

- 第 1、2 页不可跳过；第 3 页可跳过（使用默认值）。
- 第 2 页不重复显示用户名/强制登录（已在第 1 页）。
- 个人版本：核心锁定；只默认勾选同步 + 阅读统计；其余常用可勾选，`account_management` 不出现。
- 标准版本：核心锁定；常用默认开启（OPDS/WebDAV/实体书除外）；`account_management` 出现并默认开启。
- 专业版本：全部锁定勾选，不可反选。

### 8.2 系统设置中的模式配置

```text
Admin 打开 /admin/settings
  → 点击「系统模式配置」
  → GET /api/admin/system-mode
  → 渲染模式卡片 + 组合列表
  → 用户切换模式：清空 overrides，恢复该模式预设
  → 用户微调常用组合
  → POST /api/admin/system-mode {mode, overrides}
  → 后端 normalize + 写 auto.py
  → 前端 resetSession / ensureSession({force:true})
  → 关闭弹窗，刷新页面数据
```

### 8.3 模式切换

| 从 → 到 | 行为 |
| --- | --- |
| 个人 → 标准 | 清空 overrides；标准预设生效；用户管理出现；社区/高级仍隐藏 |
| 标准 → 个人 | 清空 overrides；个人预设生效；用户管理消失；常用组合回到「只开同步+统计」 |
| 个人/标准 → 专业 | 清空 overrides；全部组合锁定开启；所有入口/设置出现 |
| 专业 → 个人/标准 | 清空 overrides；目标模式预设生效；专业入口/设置隐藏；数据保留 |

切换不会：

- 删除任何数据；
- 改写 `ENABLE_BOOK_REVIEW`、`ENABLE_PHYSICAL_BOOKS` 等既有设置；
- 影响 `PERFORMANCE_MODE='lite'` 的极速模式状态（它只是专业·高级里的一个普通设置项，由用户在专业模式里另行配置）。

### 8.4 老实例升级

1. `auto.py` 没有 `SYSTEM_MODE_CONFIG` → `normalize_config` 返回 `pro`。
2. 前端 `sys.systemMode = 'pro'` → 所有组合 `modeAllows` / `scopeAllows` 均为 true，行为与升级前一致。
3. 管理员可主动在设置中选择个人/标准，触发降档。
4. 升级不要求重启；首次请求 `/api/user/info` 即生效。

---

## 9. 现有设置区块拆分清单

现有 `settings.vue` 有些 section 混合了不同归属的字段。直接给 section 指定一个组合会导致「该显示的没显示、该隐藏的没隐藏」。实施时必须先拆分：

| 现有 section | 问题 | 拆分建议 | 归属 |
| --- | --- | --- | --- |
| `site/site-home` | `RECOMMEND_USE_CROWD` 是社区能力，和核心首页设置混在一起 | `site/site-home` + `site/site-crowd` | 前者 `core_system`，后者默认高级 |
| `reading/reader-core` | `EPUB_VIEWER` 核心；`ENABLE_DATA_SYNC`、`ALLOW_USER_DISABLE_STATISTIC`、`ENABLE_SHARED_NOTES` 常用 | `reader-core`、`reader-sync`、`reader-stats`、`reader-notes` | `core_reader`、`reading_sync`、`reading_stats`、`shared_notes` |
| `reading/reader-review` | `ENABLE_BOOK_RECOMMEND_TO_OTHERS` 是社区能力 | `reader-review` + `reader-crowd` | 前者 `book_review`，后者默认高级 |
| `reading/reader-physical` | `ENABLE_FOLDER_BROWSE` 属于文件夹组合 | `reader-physical` + `reader-folder` | `physical_books`、`folder_browse` |
| `users/users-guest` | `REQUIRE_LOGIN` 是核心访问控制，和社区访客权限混在一起 | `users/users-access` + `users/users-guest` | 前者 `core_system`，后者默认高级 |
| `users/users-reg` | 重置邮件、邀请、注册、审批混在一起 | `users/users-reset`、`users/users-invite`、`users/users-register` | 前两者默认高级/社区，注册默认高级 |
| `import/imp-rules` | `ENABLE_SERVER_FILE_IMPORT` 是高级能力 | `imp-rules` + `imp-server` | 前者 `core_import_manage`，后者默认高级 |
| `services/svc-meta` | 豆瓣高级参数和基础书源混在一起 | `svc-meta` + `svc-douban` | 前者 `core_import_manage`，后者默认高级 |
| `services/svc-ai` | MyNexus 核心与 AI 助手高级混在一起 | `svc-mynexus` + `svc-ai` | 前者 `core_mynexus`，后者默认高级 |
| `push/push-tpl` | `SEND_MAIL_FOR_NEW_BOOKS` 是社区邮件通知 | `push-tpl` + `push-notify` | 前者 `push_devices`，后者默认高级 |
| `ops/ops-log` | `ENABLE_AUDIO_SUBTITLE` 属于有声书组合 | `ops-log` + `reader-audio` | 前者默认高级，后者 `audio` |

拆分原则：

1. 一个 section 只属于一个组合。
2. 如果两个字段的可见性不同，就拆成两个 section，而不是在模板里写 `v-if`。
3. 拆分后保持原有字段 key 不变，只改变渲染位置，不影响 `settings` 保存。
4. 搜索别名 `SEARCH_ALIASES` 和 `SPECIAL_BLOCKS` 要同步更新到新 section id。
5. 拆分后检查 `flatIndex` 的 `gid/sid` 是否仍然指向存在的 section。

---

## 10. 测试与验收

### 10.1 后端单元测试

1. `normalize_config`：
   - 缺失 → `pro`
   - 非法 mode → `pro`
   - 非法 overrides key/value 被丢弃
   - `pro` 强制清空 overrides
   - 超过 256 项截断
2. `sys_payload`：
   - 返回四个字段
   - 不泄露 `updated_at` 以外的内部结构（可接受）
3. `AdminSystemMode`：
   - 非管理员 403/permission
   - 非法 mode 返回错误
   - 保存后 `CONF["SYSTEM_MODE_CONFIG"]` 更新
4. `AdminSettings.post` 回归：
   - 保存普通设置后 `SYSTEM_MODE_CONFIG` 仍在
   - 通用设置 POST 不能写入 `SYSTEM_MODE_CONFIG`
5. `AdminInstall`：
   - 不传 mode → `pro`
   - 传 personal + overrides → 正确写入
   - `requireLogin` 正确写入

### 10.2 前端单元测试（建议）

1. `normalizeMode`：未知/空 → `pro`。
2. `resolveSnapshot`：
   - personal 默认：core + reading_sync + reading_stats；其余 common 关闭；community/advanced 关闭。
   - standard 默认：core + 全部 common，但 opds/webdav/physical 关闭；account_management 开启。
   - pro：全部 true。
   - overrides 覆盖默认值。
   - `account_management` 在 personal 即使 override=true 也不可用。
   - `requires` 未满足 → 子组合关闭。
   - 未知组合 id → 仅 pro 为 true。
   - support `smtp` 依赖 push/email notifications。
   - 常用组合被 override 关闭时：`modeAllows` 仍为 true，`scopeAllows`/`enabled` 为 false；`sectionVisible` 仍为 true。
3. `routeAllowed`：
   - 未知路由 → personal/standard false，pro true。
   - `ALWAYS_ALLOWED` 始终 true。
   - 常用组合被取消勾选 → 对应路由 false。
4. `sectionVisible` / `visibleGroups`：
   - 未登记 section → 仅 pro。
   - 常用组合被取消勾选 → section 仍可见。
5. `filterNav`：
   - 子项全部隐藏时父组消失。
   - 父项 bundle 关闭但仍有核心子项时，父组保留。
6. `homepageSectionEnabled`：
   - `custom:*` 始终 true。
   - `readingStats` 随 `reading_stats`。
7. `fieldOptionVisible`：
   - `SIDEBAR_ITEMS/memo` 在 personal/standard false。
   - `SIDEBAR_ITEMS/audiobooks` 在 audio 未勾选时 false，勾选后 true。

### 10.3 手工/E2E 验收

| 场景 | 期望 |
| --- | --- |
| 全新安装，选择个人版本 | 登录后无用户管理、无留言/书单/缺书/友链/社交登录；设置页保留核心与个人可用的常用 section（未勾选的常用组合也可配置），隐藏社区/高级 section；首页无书单推荐/推荐给他人 |
| 全新安装，选择标准版本 | 有用户管理；无自助注册；有声书/评论/推送等组合已勾选；文件夹/实体书是否显示还取决于 `ENABLE_FOLDER_BROWSE` / `ENABLE_PHYSICAL_BOOKS` 的既有开关；OPDS/WebDAV 组合默认关闭但设置可见 |
| 专业版本 | 所有入口、设置、首页板块可见；模式弹窗全部锁定 |
| 个人模式直接访问 `/admin/users` | 跳回首页 |
| 个人模式直接访问 `/booklists/publics` | 跳回首页 |
| 个人模式设置页搜索「留言」 | 无结果 |
| 个人模式设置页搜索「同步」 | 能搜到 |
| 个人模式首页卡片编辑器 | 不出现「推荐给他人」「书单推荐」 |
| 个人模式侧边栏设置 | 不出现「站内留言」「有声书」「实体书」「文件夹」选项 |
| 标准模式打开 OPDS 设置 | 可见，可手动开启；开启后页脚/说明页入口出现 |
| 标准模式关闭评论组合 | 详情页评分/评论、管理菜单评论管理同时消失 |
| 切换到专业模式 | 所有入口立即恢复；数据仍在 |
| 切回个人模式 | 入口再次隐藏；数据不丢 |
| 保存普通设置后刷新 | 模式配置不变 |
| 老实例升级 | 默认专业，行为不变 |
| 极速模式 | `PERFORMANCE_MODE='lite'` 仍只在专业模式出现；个人/标准不因系统模式变化而改变该设置 |

### 10.4 回归检查

- `REQUIRE_LOGIN` 在个人/标准模式下仍可在设置中修改，且登录守卫正常。
- `ENABLE_OPDS_SERVICE` / `ENABLE_WEBDAV_SERVICE` 的现有行为不变。
- `ENABLE_BOOK_REVIEW` 关闭时，即使组合开启，评论/评分也不显示。
- `ENABLE_PHYSICAL_BOOKS` 关闭时，即使组合开启，实体书入口不显示。
- `ENABLE_FOLDER_BROWSE` 关闭时，即使组合开启，文件夹入口不显示。
- 设置的保存、重启提示、自动重载逻辑不受影响。

---

## 11. 实施计划

### 11.1 阶段

| 阶段 | 内容 | 产出 |
| --- | --- | --- |
| P0 | 组合清单 + 解析器 + 单元测试 | `features/` 目录、`resolve.js`、测试；默认 pro，无行为变化 |
| P1 | 后端配置存储 + `sys` 下发 + 管理接口 + 安装参数 | `system_mode.py`、`AdminSystemMode`、`save_partial` 兼容 |
| P2 | 模式配置弹窗 + 安装引导第二页 | `SystemModeDialog.vue`、`install.vue` |
| P3 | 路由守卫 + 导航过滤 + 设置页过滤/搜索 + 首页过滤 | `feature-gate.js`、`AppHeader`、`settings.vue`、`index.vue` |
| P4 | 页面/动作级 gate + 登录页/页脚 + 外观预设 | 详情页、书籍管理、导入页、`AppearanceMenu` |
| P5 | section 拆分 + 选项过滤 + 回归测试 | 第 9 节拆分、`fieldItems`、E2E |

### 11.2 文件变更清单

| 文件 | 变更 |
| --- | --- |
| `app/src/features/tiers.js` | 新增 tier 常量、默认高级 |
| `app/src/features/manifest.js` | 新增组合清单与映射 |
| `app/src/features/resolve.js` | 新增快照解析 |
| `app/src/features/runtime.js` | 新增 `$features` API |
| `app/src/features/presentation.js` | 新增外观策略 |
| `app/src/plugins/features.js` | 注入 `$features` |
| `app/src/plugins/session.js` | `$ensureSession({ force })`，供模式保存后强制刷新 `sys` |
| `app/src/middleware/feature-gate.js` | 路由守卫 |
| `app/src/components/FeatureGate.vue` | 功能闸门组件 |
| `app/src/components/SystemModeDialog.vue` | 模式配置弹窗 |
| `app/src/components/AppHeader.vue` | 导航项加 `bundle`，末尾 `filterNav` |
| `app/src/components/AppFooter.vue` | OPDS/WebDAV/播客 gate |
| `app/src/pages/admin/settings.vue` | 顶部入口、`visibleGroups`、搜索索引、字段选项 |
| `app/src/pages/index.vue` | `isSectionEnabled` 接入 `homepageSectionEnabled` |
| `app/src/pages/install.vue` | 三步引导、模式/组合提交 |
| `app/src/pages/login.vue` | 注册/社交登录 gate |
| `app/src/pages/book/_bookid.vue` | 动作级 gate |
| `app/src/pages/admin/books.vue` | 列/动作级 gate |
| `app/src/pages/admin/imports.vue` | 服务端导入/有声书导入 gate |
| `app/src/components/AppearanceMenu.vue` | 个人/标准预设优先，保留高级展开 |
| `app/nuxt.config.js` | 注册插件与 `feature-gate` 中间件 |
| `app/locales/zh.json`、`zh-TW.json`、`en.json` | 新增模式/组合/提示文案 |
| `webserver/base/system_mode.py` | 新增配置规范化模块 |
| `webserver/base/setting_saver.py` | `PERSISTABLE_KEYS` 加配置键 |
| `webserver/handlers/admin.py` | `AdminSystemMode`、`AdminSettings` 保留配置、`AdminInstall` 参数 |
| `webserver/handlers/base.py` | `_sys_info_with` 下发配置 |
| `document/WebAPI.md` | 记录新接口与 `sys` 字段 |

### 11.3 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 忘记登记核心/常用能力点 | 个人/标准下错误隐藏 | 默认高级是安全方向；增加清单测试和评审检查 |
| section 混合归属 | 该显示的字段被隐藏 | 按第 9 节拆分；一个 section 一个组合 |
| 通用设置保存抹掉模式配置 | 模式丢失 | `AdminSettings.post` 显式补回 + 回归测试 |
| 保存后前端快照陈旧 | 导航/设置不同步 | `$resetSession()` + `$ensureSession({ force: true })`；必要时整页刷新 |
| 直接访问隐藏 API | 偏离「能力不开放」 | 明确非目标；安全能力仍由既有后端机制负责 |
| 多 Worker 配置不同步 | 各进程读到不同模式 | 沿用现有 `auto.py` 加载机制；必要时重启 |
| `lite` 命名混淆 | 维护者误解 | 2.2 命名禁用表；`ops_performance` 单独组合 |
| 专业模式被误降档 | 功能突然消失 | 模式切换确认；数据保留；可随时切回 |

---

## 12. 决策记录

| # | 决策 | 结论 |
| --- | --- | --- |
| D1 | 配置存储 | 单一键 `SYSTEM_MODE_CONFIG`，存 `mode + overrides + version + updated_at` |
| D2 | overrides 语义 | 只保存与当前模式预设不同的项；新模式/新组合自动继承预设 |
| D3 | 后端职责 | 只做规范化、持久化、下发；不新增逐功能模式判断 |
| D4 | 配置单位 | 以能力组合（Bundle）为可勾选单位；能力点不单独配置 |
| D5 | 默认分类 | 未登记的能力点默认 `pro_advanced`，个人/标准自动隐藏 |
| D6 | 未知路由/设置/导航/首页 | 一律按高级处理，`mode === 'pro'` 才可见 |
| D7 | 支持组合 | SMTP 用 `kind: 'support'` + `visibleWhen`，不进入勾选列表 |
| D8 | section 粒度 | 一个 section 只能属于一个组合；混合归属必须拆分 |
| D9 | 专业模式 | 全部锁定开启；`overrides` 强制为空 |
| D10 | 老实例升级 | 缺失配置视为 `pro`，不改变既有行为 |
| D11 | 运行时开关组合 | `modeAllows` 只看模式；`scopeAllows` 再叠加勾选；`enabled` 再加 `legacyFlags` |
| D12 | 失败回退 | 配置缺失/请求失败回退 `pro`（fail-open），避免锁死用户 |
| D13 | 命名 | `lite` 只用于 `PERFORMANCE_MODE='lite'` 极速模式；个人/标准/专业统一用 `personal/standard/pro` |
| D14 | 能力强制 | 本期不做服务端硬关闭；如需，后续用统一中间件而不是散落判断 |

---

## 附录 A：最小落地检查表

- [ ] `SYSTEM_MODE_CONFIG` 已加入 `PERSISTABLE_KEYS`，未加入 `ADMIN_SETTING_KEYS`。
- [ ] `AdminSettings.post` 已补回 `SYSTEM_MODE_CONFIG`。
- [ ] `/api/user/info` 的 `sys` 已包含 `systemMode`、`featureOverrides`、`featureConfigVersion`。
- [ ] `/api/admin/system-mode` GET/POST 已注册并校验管理员。
- [ ] 安装接口支持 `systemMode`、`featureOverrides`、`requireLogin`。
- [ ] `manifest.js` 覆盖全部核心/常用路由、section、导航、首页板块、选项。
- [ ] `feature-gate` 已加入 `nuxt.config.js` 中间件，顺序在 `require-login` 之后。
- [ ] `settings.vue` 的 tab、`currentGroups`、`flatIndex`、`SPECIAL_BLOCKS` 都已改为 `modeAllows` 可见集合。
- [ ] `fieldItems` 已用 `$features.enabled()` 过滤 `SIDEBAR_ITEMS`，未登记字段保持原样。
- [ ] `plugins/session.js` 的 `$ensureSession` 支持 `{ force: true }`，模式保存后能刷新已登录用户的 `sys`。
- [ ] `index.vue` 的 `isSectionEnabled` 已接入 `homepageSectionEnabled`。
- [ ] `AppHeader.items` 已统一走 `filterNav`。
- [ ] 登录页注册/社交登录、页脚 OPDS/WebDAV/播客已 gate。
- [ ] 详情页/书籍管理/导入页的动作已按组合 gate。
- [ ] 第 9 节 section 拆分完成，搜索别名同步更新。
- [ ] `systemMode` 没有出现在 `app/src/features/`、模式弹窗、安装引导之外。
- [ ] 老实例升级测试：缺失配置 → 专业，行为不变。
- [ ] 极速模式回归：`PERFORMANCE_MODE='lite'` 不受系统模式影响。

## 附录 B：模式配置弹窗文案建议

| 文案 key | 中文 |
| --- | --- |
| `systemMode.entry` | 系统模式配置 |
| `systemMode.title` | 系统模式与功能组合 |
| `systemMode.desc` | 选择适合当前站点的使用场景。切换模式会按预设重置功能组合，已有数据不会删除。 |
| `systemMode.mode.personal` | 个人版本 |
| `systemMode.mode.personal.desc` | 单用户、无注册、无用户管理；只保留个人常用的阅读能力。 |
| `systemMode.mode.standard` | 标准版本 |
| `systemMode.mode.standard.desc` | 家庭或小团队，少量账号由管理员创建；保留常用功能。 |
| `systemMode.mode.pro` | 专业版本 |
| `systemMode.mode.pro.desc` | 完整能力；全部功能锁定开启，适合社区或多用户站点。 |
| `systemMode.locked` | 专业版本锁定全部能力，不可反选。 |
| `systemMode.resetConfirm` | 切换模式会重置当前功能勾选，是否继续？ |
| `systemMode.saveSuccess` | 系统模式已保存，页面将刷新以应用新配置。 |
| `systemMode.core` | 核心能力（始终开启） |
| `systemMode.common` | 常用功能 |
| `systemMode.support` | 依赖服务 |
| `systemMode.requires` | 需要先开启：{bundles} |
