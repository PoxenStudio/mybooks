"""书源引擎 — Legado 3.0 兼容规则解析与内容获取"""
from .book_source_model import BookSource, RuleSearch, RuleBookInfo, RuleToc, RuleContent, ReplaceRule
from .book_source_model import load_sources_from_json, dump_sources_to_json
from .rule_engine import search_books, fetch_book_info, fetch_toc, fetch_content
from .rule_engine import parse_explore_categories, fetch_explore
from .js_runtime import run_js, JsRuleUnsupported
from .search_task_service import SearchTaskService
