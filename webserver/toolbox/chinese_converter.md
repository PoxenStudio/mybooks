# 繁简转换工具 — PR 审查文档

> 工具 ID：`chinese_converter`
> 版本：0.1.0
> 功能：对书库书籍执行简体↔繁体中文转换（EPUB / TXT）
> 使用：书库 → 工具箱 → 繁简转换 → 选择书籍、转换方向与输出方式 → 开始转换

---

## 一、功能设计

### 1. 转换引擎（移植 opencc-python，Apache 2.0）
- 移植 Hopkins1/TradSimpChinese（calibre 插件）内的 opencc-python 引擎：
  StringTree **最长匹配**、多字典 group 链、词典缓存
- 支持 8 个 OpenCC 标准方向：`t2s / tw2s / tw2sp / s2t / s2tw / s2twp / t2tw / tw2t`
  （`s2twp` / `tw2sp` 为含台湾地区用词的简↔台繁方向，词表为官方 OpenCC
  `TWPhrases.txt` / `TWPhrasesRev.txt`，如 `軟件→軟體`、`滑鼠→鼠標`）
- 字典与配置数据直接复制自 OpenCC（文件头保留 License 注释），**零新增依赖**
  （引擎仅用标准库，HTML 解析复用 mybooks 已有的 beautifulsoup4）

### 2. 增强词表（a5566123s 个人修正版）
- 解析 `a5566123s/Calibre-BIG5toGBK` 的 csr 查找替换表（繁→简，5032 条：
  1335 词组 + 3697 单字），生成 `a5_phrases.txt`
- 通过引擎新增的 `extra_dicts` 参数注入转换链 group **最前位置**，优先匹配
  （如 `幹麼→干嘛`、`達文西密碼→《达·芬奇密码》`）
- 仅对繁→简方向（t2s / tw2s）生效（Tool 层按方向过滤）

### 3. EPUB 无损转换
- zip 条目级处理：仅 `.html/.xhtml/.htm` 经 BeautifulSoup 转换文本节点
  （跳过 script/style/noscript 子树；CDATA 段整体原样保留——先占位摘出、转换后还原，
  不参与繁简转换）；`.opf/.ncx` 用 xml 解析转换标题类文本
  （可由用户关闭）；其余条目（CSS/图片/字体/NCX）**字节级原样保留**
- 重新打包符合 EPUB 规范：`mimetype` 置首且 `ZIP_STORED`，其余 `DEFLATED`
- 保留 XML 声明（转换前记录、序列化后补回）

### 4. TXT 转换
- 编码自动探测：UTF-8（含 BOM）→ GB18030 → UTF-8 兜底；输出统一 UTF-8

### 5. 输出方式（默认另存为新书）
- **另存为新书**：基于原书 `get_metadata`（含封面）深拷贝后 `import_book` 入库，
  完整继承标签、系列、评分、评论、语言、封面、MyBooks 自定义列（分类/外链/位置/动态封面）等元数据；
  标题加「（简体版）/（繁體版）」后缀，`convert_title` 开启时标题与作者文本一并转换；
  新书使用独立 UUID，语言设为 `zh`（简体）或 `zht`（繁体）；
  实体书类型/数量列不复制，避免新书（带格式文件）状态冲突
- **替换原书**：`add_format` 覆盖原格式（book_id 不变），可选备份原文件
  到 `get_work_dir()` 工作目录；`convert_title` 开启时同步更新库内
  标题/作者/语言字段，与转换后文件保持一致

### 6. 后台任务
- 与现有工具一致：`create_task` + 分阶段进度（reading → converting → saving，
  0-100）+ `add_msg` 完成/失败通知 + 并发锁防重入

## 二、改动文件

| 文件 | 类型 | 内容 |
|------|------|------|
| `webserver/toolbox/chinese_converter_tool.py` | 新增 | Tool 类（BaseTool） |
| `webserver/toolbox/chinese_converter/` | 新增 | 引擎 / EPUB 转换 / 词表 / 字典数据（standalone 包） |
| `webserver/toolbox/toolset.py` | 修改 | +1 import +1 register |
| `webserver/handlers/toolbox.py` | 修改 | +2 handler +2 路由 |
| `app/src/pages/toolbox/chinese_converter.vue` | 新增 | Vuetify 2 页面 |
| `app/locales/{en,zh,zh-TW}.json` | 修改 | +`chineseConverter` 块 |
| `tests/test_converter_core.py` | 新增 | 16 个单元测试（standalone） |

## 三、接口

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| POST | `/api/toolbox/chinese_converter/convert` | book_id, direction, mode, use_a5, convert_title, backup | `{err, msg}` |
| GET | `/api/toolbox/chinese_converter/progress` | - | `{err, data:{status, progress, stage, direction, book_id, new_book_id}}` |

## 四、Vue 页面（Vuetify 2.6 兼容性）

> MyBooks 为 **Nuxt 2.18.1 + Vue 2.6.14 + Vuetify 2.6.10**（见 app/package.json）。
> 页面严格使用 Vuetify 2 语法，与开发规范一致：

- `v-select` 用 `item-text` / `item-value`（**非** Vuetify 3 的 `item-title`）
- `outlined` / `dense` / `hide-details`（**非** `variant="outlined"` / `density="compact"`）
- 生命周期用 Vue 2 的 `beforeDestroy` 清理轮询定时器（**非** `onBeforeUnmount`）
- 选项式 API + `this.$backend()` + `$t('chineseConverter.*')`
- Nuxt 2 自动路由 `/toolbox/chinese_converter`（文件名即路由，无需配置）

## 五、安全与健壮性

- 无新增第三方依赖；转换在后台线程执行，不阻塞请求
- 工作目录按 `get_work_dir(str(book_id))` 隔离（`/data/toolbox/chinese_converter/<md5>`）
- 书籍 ID、方向、模式均在 handler 层校验；方向白名单校验
- EPUB 重打包仅改写文本条目，二进制条目原样透传，降低损坏风险
- 增强词表仅做文本匹配，无路径/执行类风险

## 六、测试

```bash
python tests/test_converter_core.py   # 20/20 passed
```

覆盖：8 方向转换（含 s2twp/tw2sp 台湾用词）、词组优先、标点保留、
a5 增强词表生效与方向隔离、
EPUB 无损（mimetype 顺序/STORED、script 保留、XML 声明保留、元数据开关）、
TXT UTF-8/GB18030 探测、非法方向报错。

## 七、已知限制

- s2t 多候选取词典第一个候选（与原版 opencc-python 行为一致）
- 台湾用词表（TWPhrases）随 OpenCC 上游数据版本更新，个别新词可能滞后
- OPF/NCX 重新打包时 lxml 序列化会重写 XML 声明，standalone 属性不保留（仅影响外部 DTD 依赖声明，阅读器实际解码不受影响）

## 八、许可

- 引擎与字典数据：Apache License 2.0（opencc-python / OpenCC，保留头部注释）
- 增强词表：a5566123s 个人修正版（来源注明）
- 工具集成代码：随 MyBooks 主仓分发（BSD 2-Clause，见仓库根 LICENSE）
