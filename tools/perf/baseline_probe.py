#!/usr/bin/env python3
"""（与 load_probe.py 放同一目录运行，仅依赖 Python3 标准库；--json-out/--compare 的路径以当前目录为准）
空闲基线与专项检查：顺序发请求（无并发），测各接口「没有别的负载时」的真实耗时，作为改造前后的验收基线。

用法: python3 baseline_probe.py --base http://nas:8083 [--token ... | --username admin --password ...] \
          [--repeat 5] [--search-term 书] [--book <已有书籍id，可省略自动挑选>] [--format EPUB] [--thumb-count 10] \
          [--with-upload [--epub 本地.epub] [--delete-with-data]] [--test-clear-messages] \
          [--json-out after.json] [--compare before.json]

默认只读。会写数据的检查都需显式开启：
  --with-upload          上传唯一标题的测试书再删除（见 load_probe.py 的安全说明），分别测纯删除与 --delete-with-data 带关联数据的删除
  --test-clear-messages  执行一次「清除消息」并计时（会把当前账号的未读消息标为已读）
重启服务后立即运行一次，每项的「首次」列即为冷启动耗时。
下载配额检查需要普通用户账号（管理员配额恒为 0，无法检测）。
"""
import argparse
import json
import os
import time
import urllib.parse
import uuid

import load_probe as lp

SEARCH_SHAPES = (
    ("search 无参数", "/api/search?name={q}"),
    ("search size=20", "/api/search?name={q}&start=0&size=20"),
    ("search size=1000", "/api/search?name={q}&start=0&size=1000"),
    ("search size=10000", "/api/search?name={q}&start=0&size=10000"),
    ("search 按书名排序 size=60", "/api/search?name={q}&start=0&size=60&order=title"),
    ("search 分词 seg=1", "/api/search?title={q}&seg=1&start=0&size=60"),
    ("search calibre 表达式 title:", "/api/search?name={tq}&start=0&size=60"),
)
READ_ENDPOINTS = (
    ("user/info", "/api/user/info"),
    ("tasks/running", "/api/admin/tasks/running"),
    ("user/messages", "/api/user/messages"),
    ("index", "/api/index?refresh=1"),
    ("categories", "/api/categories"),
    ("all", "/api/all"),
)


LIBRARY_BOOKS = [None]


class Recorder:
    def __init__(self):
        self.data = {}

    def add(self, name, ms, ok=True):
        entry = self.data.setdefault(name, {"values": [], "fail": 0})
        entry["values"].append(ms)
        if not ok:
            entry["fail"] += 1

    def table(self):
        lp.log("%-44s %4s %4s %8s %8s %8s %8s" % ("项目", "n", "失败", "首次ms", "p50", "p95", "max"))
        for name, entry in self.data.items():
            values = entry["values"]
            lp.log("%-44s %4d %4d %8.0f %8.0f %8.0f %8.0f" % (
                name[:44], len(values), entry["fail"], values[0], lp.percentile(values, 0.5), lp.percentile(values, 0.95), max(values)))

    def dump(self, path, args):
        meta = {"base": args.base, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "repeat": args.repeat, "library_books": LIBRARY_BOOKS[0]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"meta": meta, "results": self.data}, f, ensure_ascii=False, indent=1)
        lp.log("结果已写入 %s" % path)


def timed(rec, name, base, token, path, repeat, method="GET"):
    last = None
    for _ in range(repeat):
        status, ms, body = lp.fetch(base, path, token, method=method)
        rec.add(name, ms, status == 200)
        last = (status, body)
    return last


def parse_json(body):
    try:
        return json.loads(body)
    except ValueError:
        return {}


def run_reads(rec, args):
    q = urllib.parse.quote(args.search_term)
    for name, path in READ_ENDPOINTS:
        timed(rec, name, args.base, args.token, path, args.repeat)
    book_ids = []
    for name, template in SEARCH_SHAPES:
        path = template.format(q=q, tq=urllib.parse.quote("title:" + args.search_term))
        status, body = timed(rec, name, args.base, args.token, path, args.repeat)
        if not book_ids and status == 200:
            book_ids = [b["id"] for b in parse_json(body).get("books", []) if "id" in b]
    return book_ids


def run_book_endpoints(rec, args, book_ids):
    book = args.book or (book_ids[0] if book_ids else 0)
    if not book:
        lp.log("!! 没有可用的书籍 id，跳过详情检查（用 --book 指定）")
        return
    timed(rec, "book 详情", args.base, args.token, "/api/book/%d" % book, args.repeat)
    timed(rec, "book 相关推荐 suggestion", args.base, args.token, "/api/book/%d/suggestion" % book, args.repeat)


def choose_download_book(args):
    if args.book:
        return args.book
    book, size = lp.pick_download_book(args.base, args.token, args.format, args.search_term)
    if book:
        lp.log("下载检查自动选中书籍 id=%d（%s，%d KB）" % (book, args.format.upper(), size // 1024))
    else:
        lp.log("!! 没有找到带 %s 格式的现有书籍，跳过下载检查（用 --book/--format 指定）" % args.format)
    return book


def run_thumbs(rec, args, book_ids):
    ids = book_ids[:args.thumb_count]
    if not ids:
        lp.log("!! 搜索结果为空，跳过缩略图检查")
        return
    for size in ("150_200", "240_320"):
        for round_name in ("首次命中", "重复命中"):
            for book in ids:
                status, ms, _ = lp.fetch(args.base, "/get/thumb_%s/%d.jpg?t=%d" % (size, book, int(time.time())), args.token)
                rec.add("thumb_%s %s" % (size, round_name), ms, status == 200)
    for book in ids:
        status, ms, _ = lp.fetch(args.base, "/get/cover/%d.jpg" % book, args.token)
        rec.add("cover 原图", ms, status == 200)


def quota_used(args):
    status, _, body = lp.fetch(args.base, "/api/book/download_quota", args.token)
    info = parse_json(body)
    return info.get("used"), info.get("quota")


def run_download(rec, args, book):
    if not book:
        return
    path = "/api/book/%d.%s" % (book, args.format.upper())
    used_before, quota = quota_used(args)
    segments = 0
    for _ in range(max(1, args.repeat // 2)):
        def record(status, ms):
            rec.add("download 单个 Range 分段(%dKB)" % args.range_kb, ms, status in (200, 206))
        count, ms, size = lp.ranged_download(args.base, args.token, path, args.range_kb, record)
        rec.add("download 整本(分段)", ms, size > 0)
        segments += count
        lp.log("DOWNLOAD %s %d 段 %.0fms %dKB" % (path, count, ms, size // 1024))
    used_after, _ = quota_used(args)
    downloads = max(1, args.repeat // 2)
    if not quota:
        lp.log("配额检查：配额为 0（管理员账号或未启用配额），无法判断分段是否重复扣减；请用普通用户账号运行")
    elif used_before is not None and used_after is not None:
        delta = used_after - used_before
        verdict = "正常（每次完整下载 +1）" if delta == downloads else ("**异常：疑似每个 Range 分段都扣一次**" if delta >= segments > downloads else "需人工核对")
        lp.log("配额检查：完整下载 %d 次、共 %d 个分段，配额 used %s -> %s（+%d）%s" % (downloads, segments, used_before, used_after, delta, verdict))


def run_upload(rec, args):
    results = []
    for with_data in ([False, True] if args.delete_with_data else [False]):
        for _ in range(args.repeat):
            lp.upload_cycle(args.base, args.token, args, results, with_data)
    for name, status, ms in results:
        rec.add(name, ms, status == 200)


def run_messages(rec, args):
    status, ms, body = lp.fetch(args.base, "/api/user/messages", args.token)
    unread = len(parse_json(body).get("messages", []))
    lp.log("当前账号未读消息 %d 条" % unread)
    if args.test_clear_messages:
        status, ms, body = lp.fetch(args.base, "/api/user/messages/clear", args.token, method="POST")
        rec.add("messages/clear (未读 %d 条)" % unread, ms, status == 200 and parse_json(body).get("err") == "ok")


def print_server(args):
    status, _, body = lp.fetch(args.base, "/api/admin/perf", args.token)
    perf = parse_json(body).get("perf") if status == 200 else None
    if not perf:
        return
    LIBRARY_BOOKS[0] = perf.get("library_books")
    lp.log("服务端：书库共 %s 本书；%s" % (perf.get("library_books"), json.dumps(perf.get("system"), ensure_ascii=False)))
    lp.log("服务端：ioloop 滞后 %s，停滞 %s 次，calibre 池 %s" % (perf["loop_lag_ms"], perf["stall_total"], json.dumps(perf["calibre"], ensure_ascii=False)))
    if perf.get("stages"):
        lp.log("服务端：分段耗时 %s" % json.dumps(perf["stages"], ensure_ascii=False))
    profile = perf.get("profile") or {}
    if profile.get("samples"):
        lp.log("服务端：空闲基线期间仍有 %s 次停滞采样（间隔 %sms），按应用代码行：" % (profile["samples"], profile["interval_ms"]))
        for row in profile.get("app", [])[:8]:
            lp.log("   %5.1f%% %s" % (row["pct"], row["name"]))


def compare(path, rec):
    with open(path, encoding="utf-8") as f:
        old = json.load(f)["results"]
    lp.log("===== 对比 %s（p50，ms）=====" % path)
    lp.log("%-44s %9s %9s %8s" % ("项目", "之前", "现在", "倍数"))
    for name, entry in rec.data.items():
        if name not in old:
            continue
        before = lp.percentile(old[name]["values"], 0.5)
        after = lp.percentile(entry["values"], 0.5)
        ratio = "x%.1f" % (before / after) if after else "-"
        lp.log("%-44s %9.0f %9.0f %8s" % (name[:44], before, after, ratio))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--token", default="")
    ap.add_argument("--cookie", default="")
    ap.add_argument("--username", default="")
    ap.add_argument("--password", default=os.environ.get("MYBOOKS_PASSWORD", ""))
    ap.add_argument("--repeat", type=int, default=5, help="每项重复次数")
    ap.add_argument("--search-term", default="书")
    ap.add_argument("--book", type=int, default=0, help="详情与下载使用的已有书籍 id；0（默认）自动挑选：详情取搜索结果第一本，下载取有 --format 格式且 1MB–50MB 的书")
    ap.add_argument("--format", default="EPUB")
    ap.add_argument("--range-kb", type=int, default=256)
    ap.add_argument("--thumb-count", type=int, default=10)
    ap.add_argument("--with-upload", action="store_true")
    ap.add_argument("--epub", default="")
    ap.add_argument("--epub-size-kb", type=int, default=300)
    ap.add_argument("--delete-with-data", action="store_true")
    ap.add_argument("--upload-gap", type=float, default=0)
    ap.add_argument("--test-clear-messages", action="store_true")
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--json-out", default="")
    ap.add_argument("--compare", default="")
    args = ap.parse_args()
    lp.DEFAULT_TIMEOUT[0] = args.timeout

    if args.username:
        if not args.password:
            raise SystemExit("指定了 --username 但没有密码（--password 或环境变量 MYBOOKS_PASSWORD）")
        args.cookie = lp.sign_in(args.base, args.username, args.password)
        lp.log("已用账号 %s 登录" % args.username)
    if not args.cookie and not args.token:
        raise SystemExit("需要 --token、--cookie 或 --username/--password 之一")
    if args.cookie:
        lp.AUTH["Cookie"] = args.cookie

    lp.fetch(args.base, "/api/admin/perf", args.token, method="POST")
    rec = Recorder()
    lp.log("===== 空闲基线开始（每项 %d 次，顺序执行；run id %s）=====" % (args.repeat, uuid.uuid4().hex[:6]))
    book_ids = run_reads(rec, args)
    run_book_endpoints(rec, args, book_ids)
    run_thumbs(rec, args, book_ids)
    run_download(rec, args, choose_download_book(args))
    run_messages(rec, args)
    if args.with_upload:
        run_upload(rec, args)
    lp.log("===== 结果 =====")
    rec.table()
    print_server(args)
    if args.json_out:
        rec.dump(args.json_out, args)
    if args.compare:
        compare(args.compare, rec)


if __name__ == "__main__":
    main()
