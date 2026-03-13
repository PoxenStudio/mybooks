# epubreader-js 项目设计文档

## 1. 技术栈与核心架构

`epubreader-js` 是一个基于 Web 的 EPUB 阅读器前端应用。它不依赖大型前端框架（如 Vue 或 React），而是完全采用 **原生 JavaScript (ES6 Modules)** 结合少量的 HTML 和纯 CSS 构建。

- **核心渲染引擎**: [ePub.js](https://github.com/futurepress/epub.js) (v0.3.93)。该库负责解析 EPUB 文件格式、分页计算、文本渲染以及基于 CFI (Canonical Fragment Identifier) 的定位功能。`epubreader-js` 本质上是对 ePub.js 的一个功能丰富、响应式且多主题的 UI 封装层。
- **构建工具**: Webpack。主要用于模块打包、压缩以及启动本地开发服务器。
- **本地存储**:
  - `IndexedDB`: 用于缓存用户上次打开的本地 EPUB 图书数据，以便刷新后能快速恢复阅读。
  - `localStorage`: 用于持久化保存阅读器的配置（字体、主题、阅读进度、书签、高亮等）。每本书的配置键名通过该书路径的 MD5 值生成（依赖 `js-md5` 库）。
- **UI 框架**: 项目内部在 `src/ui.js` 中实现了一套极其轻量级的面向对象 UI 组件拼接方案（类似早期的 Virtual DOM 思想封装）。

## 2. 代码结构与文件功能

所有源代码位于 `src/` 目录下。项目按功能划分为主要阅读器逻辑、通用 UI 层和侧边栏功能模块。

### 根核心文件 (`src/`)

- **`reader.js`**: 整个项目的**主入口和核心控制类**。它实例化 ePub.js 的 `Rendition` 对象，管理生命周期，分发全局事件（通过继承 EventEmitter），并负责全局样式的注入（包括动态字体加载和暗色/护眼主题切换逻辑）。所有的组件都在此初始化并持有 Reader 的引用。
- **`ui.js`**: UI 基础组件库。定义了 `UIElement`, `UIDiv`, `UISpan`, `UIInput`, `UIPanel`, `UITabbedPanel` 等基础类，大量封装了 DOM 的创建和操作方法。整个阅读器的界面元素都是由这些类通过 JavaScript 动态生成的。
- **`content.js`**: 阅读区主视图控制器。管理显示图书内容的 `#viewer` 容器，以及页面加载时的动画 (loader) 和左右翻页箭头（当配置为在内容区显示时）。
- **`toolbar.js`**: 阅读器顶部/底部的悬浮工具栏。提供打开/关闭侧边栏、上一页/下一页、本地文件上传 (Open book)、添加书签和全屏切换等快捷按钮的 UI 及事件绑定。
- **`sidebar.js`**: 侧边栏的容器类。基于 `UITabbedPanel` 实现了侧边栏的多标签页切换逻辑，将各个子面板拼接在一起。
- **`notedlg.js`**: 文本高亮及笔记弹窗。当用户在 iframe 内选中文本时，弹出的添加高亮和笔记的输入对话框。
- **`storage.js`**: IndexedDB 的简单封装，提供应用的本地图书缓存读写能力。
- **`strings.js`**: 国际化 (i18n) 字符串字典类。内置英文和简体中文，通过内部事件机制实现界面的无刷新语言切换。
- **`utils.js`**: 工具函数库。包含对象深度合并 (`extend`)、UUID 生成 (`uuid`) 以及移动设备检测 (`detectMobile`) 等帮助函数。

### 侧边栏面板文件 (`src/sidebar/`)

这些文件实现了侧边栏中各个具体选项卡的业务逻辑：

- **`toc.js` (目录)**: 监听 `navigation` 事件并递归解析 epub.js 返回的目录树，生成可折叠的目录列表。点击后通过 CFI 跳转定位。
- **`bookmarks.js` (书签)**: 管理用户手动添加的书签列表。将当前的 CFI 记录下来并在列表中显示，支持单条删除和清空。
- **`annotations.js` (笔记/高亮)**: 管理通过 `notedlg.js` 添加的高亮和笔记。与 ePub.js 的 `rendition.annotations` API 交互以在正文中渲染高亮色块。
- **`search.js` (搜索)**: 遍历 EPUB 的 `spine` (骨架) 并在全文中搜索关键字。支持显示搜索结果上下文及点击跳转。
- **`metadata.js` (元数据/信息)**: 展示图书的基本元数据，如标题、作者、出版社、语言、描述等。
- **`settings.js` (设置)**: 提供修改阅读器核心配置的相关控件。

## 3. Settings (设置面板) 功能实现详解

`sidebar/settings.js` 中包含的选项会直接影响 `reader.js` 以及界面的渲染方式：

1. **Language (语言)**:
   - 切换发出 `languagechanged` 事件，触发全局 UI 组件重绘自身文本。
2. **Theme (主题 - Light / Dark / Eye Care)**:
   - 触发 `themechanged` 事件。
   - `reader.js` 捕获后，一方面改变外层 `document.body.className` 调整 UI 皮肤，另一方面通过 epub.js 的 `rendition.themes.default(...)` 注入 CSS，修改内容区 iframe 的背景色、字体颜色（暗黑模式强行覆盖 a 标签颜色等）。
3. **Font (字体)**:
   - 发出 `styleschanged` 事件并携带 `font` 值。
   - 如果非默认字体，`reader.js` 会构造本地 `assets/font/` 下对应 `.ttf` 的 URL，动态创建 `<style>` 标签（包含 `@font-face` 声明），并借助 `injectFontWithRetry` 方法确保该 CSS 被成功注入到 epub.js 渲染生成的 iframe 内部文档的 `<head>` 中，最后应用 `font-family` 样式。
4. **Font Size (字体大小 %)**:
   - 通发出 `styleschanged` 事件，底层调用 ePub.js 的 `rendition.themes.fontSize(value + "%")` 完成缩放。
5. **Flow (排版模式 - Paginated / Scrolled)**:
   - 控制是左右翻页模式还是上下滚动模式。触发 `flowchanged`，并动态使 Spread 功能失效（因为滚动模式不支持双页）。
6. **Spread (双页布局 - None / Auto)**:
   - 控制是否在屏幕较宽时同时显示两页（类似实体书）。底层调用 ePub.js 的 `rendition.spread()` 设置。
7. **Minimum spread width (最小双页宽度)**:
   - 当屏幕宽度像素大于此值时，`Auto` 双页模式才会生效。

## 4. 调试方法

1. **本地开发服务器**:
   - 运行 `npm run serve`，Webpack Dev Server 默认会在 `http://localhost:8080/` 启动。修改代码后页面会实时热更新加载。
2. **配置重置与清理 (缓存机制)**:
   - 若遇到阅读页面卡死、样式不生效、或测试新书时出问题，可打开浏览器开发者工具 (F12) -> **Application** 面板。
   - **清除 localStorage**: 找到当前域名的 Local Storage，清除以当前测试电子书路径哈希值为 Key 的配置数据。可以在控制台执行 `localStorage.clear()` 重置阅读器所有用户设置。
   - **清除 IndexedDB**: 找到名为 `epubreader-js` 的数据库并删除，这会清除缓存的本地上传电子书文件。
3. **事件追踪**:
   - `Reader` 类是一个完善的事件总线。若需调试某些生命周期，可以在 `reader.js` 的 `init` 方法末尾临时增加类似 `this.on("layout", console.log)` 的代码以追踪 ePub.js 内部派发的事件（如 `selected`, `relocated`, `rendered`）。
4. **跨域或 iframe 内部调试**:
   - 因为电子书内容是渲染在一个或多个内部套嵌的 `iframe` 中的，要审查元素文本或通过控制台测试 DOM 获取，务必先在 DevTools 的 Context 下拉菜单中将当前执行环境从 `top` 切换为特定的 `iframe`。这在调试自定义注入字体或黑暗主题 CSS 特效时非常关键。
