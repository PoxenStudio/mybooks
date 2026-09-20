## UI 规范（app/, Vue 2 + Vuetify 2）

全站视觉/交互约定的集中记录，目前先覆盖对话框；后续其它 UI 规范（按钮、图标、间距……）陆续补充到本文件对应小节。

### 对话框（v-dialog）

完整设计与迁移方案见 [document/Dialog_Standard_Design.md](../../document/Dialog_Standard_Design.md)（含现状盘点、待决问题的最终决策、分阶段实施步骤）。新增/修改对话框时遵守：

- **只有一个取消/关闭入口**，位置固定在右上角（`v-toolbar` 场景）或标题栏右上角（无 toolbar 场景）。禁止同时在标题栏放 `mdi-close` 图标按钮、又在 footer 放文字版"取消"按钮——这是重复入口，不是两个不同操作。
- **Footer 只放一个按钮**：那个会产生后果的操作按钮（"保存/上传/确认删除"等），**居中显示**（`v-card-actions class="justify-center"`，不用 `v-spacer` 右对齐）。取消/关闭不出现在 footer。
- 三种类型，按场景选：
  - **类型 A（功能操作）**：`v-toolbar`（品牌/语义色）+ 右上角取消或关闭 + footer 单个执行按钮。
  - **类型 B（提问确认）**：`v-toolbar`（风险语义色）+ 右上角取消 + footer 单个确认按钮（颜色与 toolbar 一致）。
  - **类型 C（进度反馈）**：不设 toolbar，footer 只保留一个"取消"按钮（若流程可中断）。
- Toolbar 之后不要输出空的 `<v-card-title></v-card-title>` 占位行，用 `v-card-text` 的 `class="pt-4"` 控制间距。
- Toolbar 标题用 `v-toolbar-title`，不要把文字直接塞进 `v-toolbar`。
- 文案：暂无待处理操作、纯粹关掉即可 → `common.close`；存在未提交的表单/操作 → `common.cancel`。
- 颜色语义（toolbar 与 footer 按钮保持一致）：

  | 语义 | 颜色 | 场景 |
  |---|---|---|
  | 中性操作 | `primary` | 常规功能对话框（主题色，footer 文字自动白，不用管） |
  | 新建/新增 | `green` + `confirm-dark` | 添加实体书、添加设备等（`green` 是 Material 调色板色，不是主题色，footer 按钮必须补 `confirm-dark`，见下方说明） |
  | 文件类操作 | `blue darken-4` + `confirm-dark` | 对话框专用，视觉上接近站点品牌深蓝 `#003153`；app bar/布局等站点品牌元素走 `--app-nav-bg`（默认 `#003153`，可由外观设置改成任意品牌色），与对话框这里的固定色互不影响。`blue darken-4` 同样不是主题色，footer 必须补 `confirm-dark` |
  | 提示/中性确认 | `primary` 或 `info` | 无风险但需要用户确认（都是主题色，footer 文字自动白，不用管） |
  | 有损/谨慎确认 | `orange` + `confirm-dark` | 会修改/清理数据但可恢复或影响有限（`orange` 不是主题色） |
  | 破坏性确认 | `deep-orange` + `confirm-dark` | 删除等不可逆操作（不用 `error`，容易被误读成"出错了"；`deep-orange` 也不是主题色） |

- 公共组件：[app/src/components/AppDialog.vue](../../app/src/components/AppDialog.vue) 封装了上述骨架，新对话框优先复用它，而不是手写 `v-toolbar`/`v-card-actions`（Nuxt `components: true` 自动注册，模板里直接 `<AppDialog>` 即可，无需 import）。核心用法：

  ```html
  <AppDialog
    v-model="dialog_xxx"
    type="action"                          <!-- action | confirm | progress -->
    :title="$t('book.uploadNewFormat')"
    icon="mdi-file-upload-outline"
    color="primary"
    :confirm-text="$t('book.upload')"
    :confirm-loading="submitting"
    :confirm-disabled="!valid"
    @confirm="confirmAction"
  >
    <!-- 表单内容，渲染进 v-card-text -->
  </AppDialog>
  ```

  - `dismiss-label` 不传时默认 `common.cancel`；语义是"关闭"（无待提交表单）时显式传 `dismiss-label="$t('common.close')"`。
  - `dismiss-icon` 传 `true` 时右上角用 `mdi-close` 图标按钮，否则用文字按钮。
  - `type="confirm"`：`color` 直接传风险语义色（见上面颜色表），`confirm-color` 不传时跟随 `color`。
  - **颜色对比度，容易踩的坑**：Vuetify 只有 7 个"主题色"——`primary`/`secondary`/`accent`/`error`/`info`/`success`/`warning`——会在运行时生成自动对比文字色（通常是白）。除此之外的所有颜色，包括 Material 调色板里的具名色（`orange`/`deep-orange`/`green`/`teal`/`blue`……以及它们的 `darken-N`/`lighten-N` 变体）和任意十六进制色，都**只设置背景色，不设置文字色**——即使色块看起来很深，按钮文字仍是默认深色，对比度会很差。上面颜色表里除了 `primary`/`info` 之外全部属于这一类，所以都带了 `confirm-dark`（映射到 `v-btn` 的 `dark`，强制走白字配色）。新增对话框选颜色时，只要不是那 7 个主题色之一，就默认加 `confirm-dark`，除非现场肉眼确认过对比度没问题。
  - `type="progress"`：不渲染 toolbar，`title` 可选（朴素文字），footer 只有一个取消按钮，`hide-footer-button` 可关掉它（纯阻塞流程）。
  - footer 按钮随状态变化、需要多个按钮（如 `dialog_audiolist`）：用 `actions` 具名插槽整体接管 footer。
- 例外（不套用以上规则，维持现状）：`book/_bookid.vue` 的 `dialog_audiolist`（footer 按钮随状态变化，用组件的 `actions` 插槽承接）、`AppHeader.vue` 的 `ai_enabled`（聊天式常驻界面，不是操作/确认对话框）。

### 其它 UI 规范

（待补充）
