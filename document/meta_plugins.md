# 图书元数据信息源插件重构方案

## 1. 设计目标

1. 为信息源插件定义统一基类 `MetaSourcePlugin`，明确：
   - 该插件对应哪些 `META_SELECTED_SOURCES` 取值（`SOURCE_KEYS`），并把"是否启用"的判断封装到插件内部 `is_enabled()`；
   - 统一的检索接口：`search`（多结果聚合搜索）、`search_best`（按本插件規則返回单一最佳匹配）、`get_metadata_by_provider`（依据 provider_value 拉取详情）、`get_cover`（按 URL 拉取封面）。
2. `BookSearch` 成为所有“信息源检索”操作的唯一对外入口，新增接口覆盖目前分散在 `autofill.py` / `handlers/book.py` / `batch_add.py` 中的直接插件调用，调用方不再 import 具体信息源模块。
3. `BookSearch.search_books`（聚合搜索）按 `META_SELECTED_SOURCES` 为每个**已启用**的信息源各自分配一个 worker 并行执行，未选中的信息源不创建 worker、不发请求。
4. **不改变现有业务逻辑**：聚合搜索结果的内容/顺序、自动刮削时“按优先级顺序找到第一个可用结果即返回”的短路行为、ISBN 实体书添加时“先豆瓣后新华书店（不受 META_SELECTED_SOURCES 限制）”的兜底策略均保持不变。

> 关于本次决策已与用户确认：
> - `xhsd`（新华书店）继续作为 ISBN 实体书添加的固定兜底，不纳入 `META_SELECTED_SOURCES` 判断；
> - 仅 `search_books`（聚合搜索/候选列表）改为并行；`search_best`（自动刮削按优先级取首个命中）继续保持顺序执行+短路，避免对低优先级信息源发起不必要的请求。

## 2. 插件基类设计

新增 `webserver/plugins/meta/base.py`：

```python
class MetaSourcePlugin(ABC):
    """图书元数据信息源插件基类"""

    # 本插件关联的 META_SELECTED_SOURCES 取值集合（可能不止一个，如 calibre 同时覆盖 google/amazon）
    SOURCE_KEYS: frozenset = frozenset()

    def __init__(self, conf):
        self.conf = conf

    def is_enabled(self, sources=None):
        """该插件是否应该参与本次检索（由 META_SELECTED_SOURCES 决定）"""
        if sources is None:
            sources = self.conf.get(META_SELECTED_SOURCES, [])
        return bool(self.SOURCE_KEYS & set(sources))

    # ---- 多结果聚合搜索：用于 BookRefer 候选列表展示 ----
    def search(self, title=None, isbn=None, publisher=None):
        """返回 list[Metadata]，找不到时返回 []。子类按需覆盖，默认空实现。"""
        return []

    # ---- 单一最佳匹配：用于自动刮削（按优先级短路） ----
    def search_best(self, title=None, isbn=None, author=None, publisher=None):
        """返回单个 Metadata 或 None。默认退化为 search() 的首个结果。"""
        books = self.search(title=title, isbn=isbn, publisher=publisher)
        return books[0] if books else None

    # ---- 依据已知 provider_value 获取详情（用户在候选列表中选中后刷新整本书） ----
    def get_metadata_by_provider(self, provider_value, mi=None):
        return None

    # ---- 按封面 URL 拉取封面数据 ----
    def get_cover(self, cover_url):
        return None

    @property
    def name(self):
        return type(self).__name__
```

设计要点：

- `SOURCE_KEYS` 用 `frozenset` 是因为 Calibre 插件同时对应 `google`、`amazon` 两个选项；其余插件只有一个值。
- `is_enabled()` 把"该不该跑"封装到插件内部，调用方只需 `if plugin.is_enabled(): ...`，不再需要知道 `META_SOURCE_XXX` 常量。
- 默认方法返回空结果/None，子类只需覆盖自己支持的能力（例如 `xhsd` 当前只在 ISBN 兜底场景使用，不参与聚合搜索/自动刮削，可以不覆盖 `search`/`search_best`）。
- 异常处理：基类不吞异常，由各子类在内部捕获网络异常并记录日志（与现状一致——现状中各 `except` 分支的中文日志措辞需要保留），`BookSearch` 侧再做一层兜底防护。
