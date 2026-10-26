# -*- coding: utf-8 -*-
"""Offline tests for the whole-library tools in ``skills/mybooks/scripts/mybooks_api.py``.

These cover the pure decision logic (audit rules, sharding, author normalization,
plan diffing, dry-run defaults) with a stubbed library snapshot, so they need no
MyBooks server. Only ``wuming_*`` tools touch the network, and they are not
exercised here.

Run with:
    pytest skills/mybooks/tests/test_mybooks_api_offline.py -v
"""

import importlib.util
import os
import sys

import pytest

urllib3 = pytest.importorskip("urllib3")

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "scripts", "mybooks_api.py")


@pytest.fixture(scope="module")
def mb():
    os.environ.setdefault("MYBOOKS_HOST", "http://127.0.0.1:9")
    os.environ.setdefault("MYBOOKS_USER", "tester")
    os.environ.setdefault("MYBOOKS_PASSWORD", "tester")
    spec = importlib.util.spec_from_file_location("mybooks_api_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BOOKS = [
    {"id": 1, "title": "三体", "authors": ["刘慈欣"], "isbn": "9787536692930",
     "publisher": "重庆出版社", "pubdate": "2007-12-31", "category": "小说",
     "tags": ["科幻"], "comments": "简介"},
    {"id": 2, "title": "诛仙", "authors": ["箫鼎"], "isbn": "", "publisher": "Unknown",
     "pubdate": "0101-01-01", "category": "", "tags": [], "comments": ""},
    {"id": 3, "title": "深度学习之美", "authors": ["【美】特伦斯·谢诺夫斯基 著"], "isbn": "",
     "publisher": "中信出版社2019", "pubdate": "", "category": "科技", "tags": ["AI"],
     "comments": ""},
    {"id": 4, "title": "合著之书", "authors": ["张三, 李四"], "isbn": "", "publisher": "",
     "pubdate": "", "category": "", "tags": [], "comments": ""},
    {"id": 5, "title": "水印之书", "authors": ["王五（ePUBw.COM）"], "isbn": "", "publisher": "",
     "pubdate": "", "category": "", "tags": [], "comments": ""},
]


@pytest.fixture
def api(mb):
    """A client whose library snapshot is the fixed BOOKS list (no network at all)."""
    client = mb.MyBooksAPI(os.environ["MYBOOKS_HOST"], "tester", "tester")
    client._fetch_library = lambda page_size=100, workers=3: ([dict(b) for b in BOOKS], len(BOOKS))
    client._read_book = lambda book_id: next((b for b in BOOKS if b["id"] == int(book_id)), {})
    client.written = []
    client._write_book = lambda book_id, fields: client.written.append((book_id, fields)) or {"err": "ok"}
    return client


# ---------------------------------------------------------------- library_audit


def test_audit_counts_each_rule(api):
    metrics = api.library_audit({})["metrics"]
    assert metrics == {"isbn": 4, "publisher": 3, "publisher_year": 1, "pubdate": 4,
                       "category": 3, "tags": 3, "authors": 1, "comments": 4}


def test_audit_reports_book_detail_not_just_counts(api):
    report = api.library_audit({"rules": ["isbn"]})
    assert report["total"] == 5
    assert [b["id"] for b in report["isbn"]] == [2, 3, 4, 5]
    assert report["complete"] == 1


def test_audit_rejects_unknown_rule(api):
    assert api.library_audit({"rules": ["nope"]})["status"] == "error"


def test_audit_hydrates_fields_the_list_payload_omits(api):
    """The list endpoint returns comments="" even when a book has one.

    Without hydration every book would be reported as missing a description, and a
    later fill would be free to overwrite real text.
    """
    api._fetch_library = lambda page_size=100, workers=3: (
        [{**book, "comments": ""} for book in BOOKS], len(BOOKS))
    api._read_book = lambda book_id: {"id": int(book_id), "comments": "详情简介"}

    report = api.library_audit({"rules": ["comments"]})
    assert report["hydrated_fields"] == ["comments"]
    assert report["metrics"]["comments"] == 0


def test_audit_without_omitted_fields_does_not_hydrate(api):
    assert api.library_audit({"rules": ["isbn"]})["hydrated_fields"] == []


# ----------------------------------------------------------- library_research_todo


def test_shards_cover_every_id_once(api):
    todo = api.library_research_todo({"rules": ["isbn"], "shard_size": 2})
    flat = sorted(book_id for shard in todo["shards"] for book_id in shard)
    assert flat == [2, 3, 4, 5]
    assert len(flat) == len(set(flat))
    assert todo["todo_count"] == 4


def test_todo_marks_needed_rules(api):
    todo = {t["id"]: t for t in api.library_research_todo({"rules": ["isbn", "tags"]})["todo"]}
    assert set(todo[2]["need"]) == {"isbn", "tags"}
    assert todo[3]["need"] == ["isbn"]


# ------------------------------------------------------------ authors_normalize


def test_authors_normalize_splits_cleans_and_applies_canon(api):
    plan = {item["book_id"]: item for item in
            api.authors_normalize({"canon": {"箫鼎": "萧鼎"}})["plan"]}

    assert sorted(plan) == [2, 3, 4, 5]
    assert plan[2]["after"] == ["萧鼎"]                              # canon
    assert plan[3]["after"] == ["(美)特伦斯·谢诺夫斯基"]              # 前缀保留 + 去角色后缀
    assert plan[4]["after"] == ["张三", "李四"]                       # 拆分分隔符
    assert plan[5]["after"] == ["王五"]                               # 去水印不留空括号


def test_authors_normalize_never_writes(api):
    result = api.authors_normalize({})
    assert result["read_only"] is True
    assert api.written == []


# ------------------------------------------------------------------- batch_edit


def test_batch_edit_dry_run_writes_nothing_and_diffs(api):
    result = api.batch_edit({"items": [{"book_id": 2, "category": "小说"},
                                       {"book_id": 1, "category": "小说"}], "dry_run": True})
    by_id = {r["book_id"]: r for r in result["results"]}
    assert api.written == []
    assert by_id[2]["diff"]["category"] == {"before": "", "after": "小说"}
    assert by_id[1]["skipped"] is True
    assert (result["skipped"], result["changed"]) == (1, 1)


def test_batch_edit_rejects_non_editable_field(api):
    result = api.batch_edit({"items": [{"book_id": 2, "bogus": 1}]})
    assert result["status"] == "error"
    assert api.written == []


def test_batch_edit_writes_when_dry_run_is_false(api):
    result = api.batch_edit({"items": [{"book_id": 2, "category": "小说"}],
                             "dry_run": False, "verify": False})
    assert api.written == [(2, {"category": "小说"})]
    assert result["ok"] == 1


# ------------------------------------------------------------- library_enrich_apply


def test_apply_plan_dry_run_skips_unchanged(api):
    result = api._apply_plan([{"book_id": 2, "publisher": "百花文艺出版社"},
                              {"book_id": 1, "publisher": "重庆出版社"}], dry_run=True)
    assert api.written == []
    assert (result["skipped"], result["changed"]) == (1, 1)


def test_apply_plan_rejects_non_editable_field(api):
    assert api._apply_plan([{"book_id": 2, "nope": 1}], dry_run=True)["failed"] == 1


# ---------------------------------------------------------------- safety defaults


def test_research_todo_is_read_only(api):
    assert api.library_research_todo({"rules": ["isbn"]})["status"] == "ok"
    assert api.written == []


def test_wuming_tools_are_credential_free_and_validate_args(mb):
    # These handlers take only the args dict, so they can run with no MyBooks client
    assert set(mb.AUTH_FREE_TOOLS) == {"wuming_search", "wuming_toplist", "wuming_recent_hot",
                                       "wuming_detail", "wuming_guide", "wuming_tags"}
    # Argument validation happens before any request, so these stay offline
    assert mb.AUTH_FREE_TOOLS["wuming_search"]({})["status"] == "error"
    assert mb.AUTH_FREE_TOOLS["wuming_detail"]({})["status"] == "error"
    assert mb.AUTH_FREE_TOOLS["wuming_guide"]({})["status"] == "error"
