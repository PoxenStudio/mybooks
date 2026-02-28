# 前端 UI 配色切换系统技术方案

> Talebook · Nuxt 2 + Vuetify 2 · 撰写日期：2026-02-28

---

## 一、背景与现状分析

### 技术栈

| 库 | 版本 |
|---|---|
| Nuxt | ^2.15.8 (Nuxt 2 / Vue 2) |
| Vuetify | ^2.6.10 |
| @nuxtjs/vuetify | ^1.12.3 |

### 现状问题

1. **无 Vuetify 主题自定义**：`nuxt.config.js` 中 `vuetify:` 块未声明任何 `theme:` 配置，`primary`、`secondary` 等语义色全部依赖 Vuetify 出厂默认值。

2. **`theme-custom.css` 覆盖层**：通过 `.theme--light` / `.theme--dark` 上的 `!important` 规则覆盖 Vuetify 默认样式，颜色值全部为硬编码 hex，与 Vuetify 主题系统脱节。

3. **硬编码颜色散落 12+ 文件**：包括 `#003153`（品牌导航色）在至少 4 处重复定义、`#2c2c2c`（播放器背景）、`background: white`（Loading 组件）等。

4. **主题切换逻辑分散**：`$vuetify.theme.dark =` 直接赋值散落在 `AppHeader.vue`、`admin/settings.vue`、`welcome.vue`、`login.vue` 四处；localStorage key 也不一致（`site_theme` 与 `darkMode` 混用）。

5. **死代码**：`src/plugins/dark-mode.js` 读取错误的 localStorage key（`darkMode` 而非 `site_theme`），操作无人使用的 HTML class，且未注册进 Nuxt，实为无效代码。

6. **首屏闪烁隐患**：主题在 `AppHeader.vue` 的 `mounted()` 中通过 API 请求结果设置，存在 API 返回前短暂显示错误主题的风险（FOUC）。

---

## 二、设计目标

| 目标 | 说明 |
|---|---|
| **单一数据源** | 所有颜色通过 CSS 自定义属性（Custom Properties）定义，YAML 文件为唯一颜色配置来源 |
| **可扩展** | 2 套内置主题（light / dark），YAML 结构支持未来低成本新增主题 |
| **权限分层** | 管理员设全站默认；用户可个人覆盖，偏好持久化到 localStorage |
| **零 FOUC** | 通过同步内联脚本在首屏绘制前注入主题，无需 SSR 改造 |
| **Vuetify 兼容** | 语义色（primary 等）同步写入 Vuetify theme 对象，内置组件色彩也统一受控 |

---

## 三、目录结构

```
app/
├── public/
│   └── themes/
│       ├── light.yaml          # 浅色主题配置（唯一颜色数据源）
│       ├── dark.yaml           # 深色主题配置
│       └── index.json          # 可用主题索引（构建产物，勿手动编辑）
├── scripts/
│   └── build-themes.js         # YAML → CSS 构建脚本
└── src/
    ├── app.html                # 注入防 FOUC 同步内联脚本
    ├── assets/
    │   └── css/
    │       ├── themes.css      # 构建产物：所有主题的 CSS 变量（勿手动编辑）
    │       └── theme-base.css  # 引用 CSS 变量的结构样式（替代 theme-custom.css）
    └── plugins/
        └── theme.js            # 主题切换插件，暴露 $setTheme() / $getTheme()
```

---

## 四、颜色 Token 规范

命名格式：`--tb-{category}-{role}`，下划线用连字符替代。

### 4.1 完整 Token 列表

| Token | 说明 | Light 值 | Dark 值 |
|---|---|---|---|
| `--tb-nav-bg` | 顶栏 / 底栏背景色 | `#003153` | `#1e1e1e` |
| `--tb-nav-drawer-bg` | 侧边导航栏背景 | `#002a45` | `#121212` |
| `--tb-nav-text` | 导航栏文字 / 图标色 | `rgba(255,255,255,0.87)` | `rgba(255,255,255,0.87)` |
| `--tb-nav-text-muted` | 导航栏次级文字 / 图标 | `rgba(255,255,255,0.70)` | `rgba(255,255,255,0.54)` |
| `--tb-nav-hover-bg` | 导航列表悬停背景 | `rgba(0,49,83,0.08)` | `rgba(255,255,255,0.08)` |
| `--tb-app-bg` | `<v-application>` 整体背景 | `#003153` | `#121212` |
| `--tb-main-bg` | `<v-main>` 内容区背景 | `#f5f5f5` | `#1e1e1e` |
| `--tb-surface` | 通用卡片 / 面板背景 | `#ffffff` | `#2d2d2d` |
| `--tb-divider` | 分割线颜色 | `rgba(0,0,0,0.12)` | `rgba(255,255,255,0.12)` |
| `--tb-text-primary` | 正文主色 | `rgba(0,0,0,0.87)` | `rgba(255,255,255,0.87)` |
| `--tb-text-secondary` | 正文次色 | `rgba(0,0,0,0.60)` | `rgba(255,255,255,0.60)` |
| `--tb-text-on-brand` | 品牌色背景上的文字 | `rgba(255,255,255,0.87)` | `rgba(255,255,255,0.87)` |
| `--tb-text-footer` | 页脚版本文字 | `#666666` | `#999999` |
| `--tb-color-primary` | 主操作色 | `#00539a` | `#2196F3` |
| `--tb-color-primary-hover` | 主操作色悬停 | `#0074B7` | `#42A5F5` |
| `--tb-color-secondary` | 次级操作色 | `#424242` | `#616161` |
| `--tb-color-accent` | 强调色 | `#82B1FF` | `#82B1FF` |
| `--tb-color-error` | 错误色 | `#FF5252` | `#FF5252` |
| `--tb-color-warning` | 警告色 | `#FFC107` | `#FFC107` |
| `--tb-color-info` | 信息色 | `#2196F3` | `#42A5F5` |
| `--tb-color-success` | 成功色 | `#4CAF50` | `#66BB6A` |
| `--tb-stats-bar-from` | 统计栏渐变起始色 | `#003153` | `#1e3a52` |
| `--tb-stats-bar-to` | 统计栏渐变结束色 | `#00539a` | `#2d5a7b` |
| `--tb-stats-card-1-from` | 统计卡片1渐变起 | `#1976d2` | `#1565c0` |
| `--tb-stats-card-1-to` | 统计卡片1渐变止 | `#42a5f5` | `#42a5f5` |
| `--tb-stats-card-2-from` | 统计卡片2渐变起 | `#388e3c` | `#2e7d32` |
| `--tb-stats-card-2-to` | 统计卡片2渐变止 | `#66bb6a` | `#66bb6a` |
| `--tb-stats-card-3-from` | 统计卡片3渐变起 | `#f57c00` | `#e65100` |
| `--tb-stats-card-3-to` | 统计卡片3渐变止 | `#ffa726` | `#ffa726` |
| `--tb-stats-card-4-from` | 统计卡片4渐变起 | `#7b1fa2` | `#6a1b9a` |
| `--tb-stats-card-4-to` | 统计卡片4渐变止 | `#ab47bc` | `#ab47bc` |
| `--tb-tab-bg` | 标签页背景 | `#f5f5f5` | `#2d2d2d` |
| `--tb-tab-border` | 标签页边框 | `#e0e0e0` | `#444444` |
| `--tb-tab-active` | 标签页激活色 | `#1976d2` | `#2196F3` |
| `--tb-tab-inactive-text` | 标签页未激活文字 | `#424242` | `#e0e0e0` |
| `--tb-player-bg` | 音频播放器外层背景 | `#f0f0f0` | `#2c2c2c` |
| `--tb-player-inner-bg` | 音频播放器内层背景 | `#e0e0e0` | `#1a1a1a` |
| `--tb-loading-bg` | 全屏 Loading 遮罩 | `#ffffff` | `#121212` |
| `--tb-login-overlay` | 登录页背景蒙层 | `rgba(0,0,0,0.5)` | `rgba(0,0,0,0.7)` |
| `--tb-author-badge` | 作者页徽章色 | `#299075` | `#4db88c` |

---

## 五、YAML 配置文件格式

```yaml
name: "light"             # 主题 ID，对应 data-theme attribute 值
label: "浅色"             # 显示名称（i18n 可用）
vuetify_dark: false       # 传入 $vuetify.theme.dark 的值
tokens:
  nav:
    bg: ""                # → --tb-nav-bg
    drawer_bg: ""         # → --tb-nav-drawer-bg
    text: ""              # → --tb-nav-text
    text_muted: ""        # → --tb-nav-text-muted
    hover_bg: ""          # → --tb-nav-hover-bg
  app:
    bg: ""                # → --tb-app-bg
    main_bg: ""           # → --tb-app-main-bg
    surface: ""           # → --tb-app-surface
    divider: ""           # → --tb-app-divider
  text:
    primary: ""           # → --tb-text-primary
    secondary: ""         # → --tb-text-secondary
    on_brand: ""          # → --tb-text-on-brand
    footer: ""            # → --tb-text-footer
  color:
    primary: ""           # → --tb-color-primary
    primary_hover: ""     # → --tb-color-primary-hover
    secondary: ""         # → --tb-color-secondary
    accent: ""            # → --tb-color-accent
    error: ""             # → --tb-color-error
    warning: ""           # → --tb-color-warning
    info: ""              # → --tb-color-info
    success: ""           # → --tb-color-success
  stats:
    bar_from: ""          # → --tb-stats-bar-from
    bar_to: ""            # → --tb-stats-bar-to
    card_1_from: ""       # → --tb-stats-card-1-from（下同）
    card_1_to: ""
    card_2_from: ""
    card_2_to: ""
    card_3_from: ""
    card_3_to: ""
    card_4_from: ""
    card_4_to: ""
  component:
    tab_bg: ""            # → --tb-component-tab-bg
    tab_border: ""
    tab_active: ""
    tab_inactive_text: ""
    player_bg: ""
    player_inner_bg: ""
    loading_bg: ""
    login_overlay: ""
    author_badge: ""
```

> **命名规则**：YAML 中的 `_` 在生成 CSS 变量时转换为 `-`，层级之间用 `-` 连接，前缀固定为 `--tb`。
>
> 例：`tokens.component.tab_bg` → `--tb-component-tab-bg`

---

## 六、实现步骤

### Step 1：安装依赖

```bash
cd app
npm install js-yaml --save-dev
```

### Step 2：创建 YAML 主题文件

在 `app/public/themes/` 目录下创建 `light.yaml` 和 `dark.yaml`（详见 `app/public/themes/` 目录）。

### Step 3：创建构建脚本

`app/scripts/build-themes.js` 负责将所有 YAML 文件转换为 CSS。
在 `app/package.json` 的 `scripts` 中添加钩子，确保每次构建 / 开发前自动运行：

```json
"prebuild": "node scripts/build-themes.js",
"predev": "node scripts/build-themes.js",
"build-themes": "node scripts/build-themes.js"
```

执行后生成两个产物：
- `app/src/assets/css/themes.css` — 被 Nuxt 打包进应用
- `app/public/themes/index.json` — 运行时主题列表API

### Step 4：修改 `app/src/app.html`

在 `<head>` 内 `{{ HEAD }}` 之**前**插入防 FOUC 同步脚本：

```html
<script>
  (function() {
    try {
      var t = localStorage.getItem('user_theme') ||
              localStorage.getItem('site_theme') ||
              'light';
      if (t !== 'light' && t !== 'dark') t = 'light';
      document.documentElement.setAttribute('data-theme', t);
    } catch(e) {
      document.documentElement.setAttribute('data-theme', 'light');
    }
  })();
</script>
```

### Step 5：修改 `nuxt.config.js`

```js
css: [
  // ...原有条目...
  '~/assets/css/themes.css',    // 构建产物：CSS 变量定义
  '~/assets/css/theme-base.css' // 结构样式：引用 CSS 变量
],
plugins: [
  // ...原有条目...
  { src: "~/plugins/theme.js", mode: "client" }
],
```

### Step 6：清理组件内硬编码颜色

| 文件 | 操作 |
|---|---|
| `src/pages/categories.vue` | 删除 `.theme--light`/`.theme--dark` scoped 块，改用 `var(--tb-component-tab-*)` |
| `src/pages/index.vue` | `color='#003153'` 改用 CSS 变量；`.library-stats-bar` 渐变由 `theme-base.css` 控制 |
| `src/pages/user/history.vue` | 4 组 stat card gradient 改用 `var(--tb-stats-card-*-from/to)` |
| `src/pages/audio/_id.vue` | player 背景改用 `var(--tb-component-player-bg/inner-bg)` |
| `src/components/BookCards.vue` | `#2196F3` → `var(--tb-color-info)`；`#9C27B0` → `var(--tb-color-accent)` |
| `src/components/AppFooter.vue` | `color: #666` → `color: var(--tb-text-footer)` |
| `src/components/Loading.vue` | `background: white` → `background: var(--tb-component-loading-bg)` |
| `src/assets/css/background.css` | `rgba(0,0,0,0.5)` → `var(--tb-component-login-overlay)` |
| `src/pages/author.vue` | `#299075` → `var(--tb-component-author-badge)` |
| `src/pages/webdav-readme.vue`、`opds-readme.vue`、`user/usersettings.vue` | `#f5f5f5` → `var(--tb-app-main-bg)` |

### Step 7：统一主题切换调用

将所有分散的 `this.$vuetify.theme.dark =` 替换为统一调用：

| 文件 | 原代码 | 新代码 |
|---|---|---|
| `AppHeader.vue` mounted | `this.$vuetify.theme.dark = rsp.sys.theme === 'dark'` | `this.$setSiteDefaultTheme(rsp.sys.theme)` |
| `admin/settings.vue` 保存时 | `this.$vuetify.theme.dark = ... === 'dark'` | `this.$setSiteDefaultTheme(this.settings.site_theme)` |
| `welcome.vue` created | 读 localStorage + `this.$vuetify.theme.dark =` | `this.$setTheme(localStorage.getItem('user_theme') \|\| localStorage.getItem('site_theme') \|\| 'light', false)` |
| `login.vue` created | 同上 | 同上 |

### Step 8：删除死代码

删除 `src/plugins/dark-mode.js`（未注册、读取错误 key、无实际效果）。

---

## 七、防 FOUC 原理

```
浏览器解析 HTML
  └─ 执行 <head> 内联脚本（同步阻塞）
       └─ 读 localStorage → 设置 html[data-theme="light|dark"]
  └─ 加载 themes.css
       └─ :root[data-theme="light"] { --tb-nav-bg: #003153; ... }
            ← attribute 已存在 → CSS 变量立刻生效
  └─ 首屏绘制（颜色正确）✓
```

> **关键**：内联脚本**不能**加 `defer` 或 `async`，必须同步执行，确保 CSSOM 构建时 attribute 已存在。此方案与 `next-themes`、`nuxt-color-mode` 采用相同机制。

---

## 八、LocalStorage 键规范

| Key | 写入方 | 读取优先级 | 说明 |
|---|---|---|---|
| `user_theme` | `$setTheme()` 方法（用户主动操作） | **1（最高）** | 用户个人偏好 |
| `site_theme` | `$setSiteDefaultTheme()`（Admin API 下发） | **2** | 全站管理员默认 |
| _(无值)_ | — | **3（最低）** | 回退到 `'light'` |

---

## 九、扩展新主题

1. 在 `app/public/themes/` 新增 `ocean.yaml`，填充所有 token 值。
2. 执行 `npm run build-themes` 重新生成 `themes.css` 和 `index.json`。
3. **无需修改任何 Vue 组件或 CSS 结构文件。**

---

## 十、数据流总览

```
public/themes/*.yaml
        │
        │  node scripts/build-themes.js
        ▼
src/assets/css/themes.css          ← Nuxt 打包，随页面加载
public/themes/index.json           ← 运行时主题列表（fetch）
        │
        │  app.html 内联脚本（同步）
        ▼
html[data-theme="light|dark"]      ← CSS 变量立刻激活
        │
        │  $setTheme(name) / $setSiteDefaultTheme(name)
        ▼
$vuetify.theme.dark = true|false   ← Vuetify 内置组件配色同步
CSS 变量更新（data-theme attribute 切换）
```
