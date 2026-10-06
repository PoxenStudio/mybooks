#!/usr/bin/env python3
"""（脚本可拷到目标设备，与 baseline_probe.py 放同一目录，仅依赖 Python3 标准库；所有文件都以当前目录为准）
并发压测 + ioloop 探针：后台打重请求，前台持续测 /api/user/info 延迟，每轮结束后拉 /api/admin/perf。

用法: python3 load_probe.py --base http://nas:8083 [--token <管理员 podcast token> | --username admin --password ...] \
          [--scenario search,download,index,thumb] [--duration 60] [--rounds 3] [--book 2063] [--thumb-base 30000] [--quiet] \
          [--poll-interval 10] [--cookie "user_id=...; lt=..."] [--epub 本地.epub] [--epub-size-kb 300] [--timeout 5]

场景（--scenario，逗号分隔）：search（1000 条与按书名排序两种）、search10k（size=10000）、searchseg（分词搜索）、
index（首页+分类+全部）、thumb、download（按 Range 分段完整下载 --book 的 --format 格式）、upload（见下）。
--timeout 5 可模拟 MyReader 的 5 秒超时（超时计为失败）。空闲基线、真实删除成本、下载配额、消息清除等专项检查见 baseline_probe.py。

--scenario 加入 upload 会循环「上传 epub → 校验 → 删除」，会真实写入并删除书库数据：
  每次上传都使用唯一标题（PerfProbe-xxxx）与作者，避免与现有书籍同名合并；
  只有校验到标题与本次生成的一致才会删除，否则报警并跳过，绝不删除其它书籍。
  --epub 指定本地文件时，会在内存里把其 OPF 的标题/作者改成唯一值再上传（不修改原文件）；
  不指定则合成一个约 --epub-size-kb 大小的 epub。

认证三选一：
  --token                  走 X-MYBOOKS-TOKEN，服务端每次请求都会 login_user 并提交一次 SQLite 事务；
  --cookie                 传浏览器登录后的 Cookie 串，走普通会话认证；
  --username/--password    脚本启动时调用 /api/user/sign_in 登录一次并自动保存 cookie（密码也可用环境变量
                           MYBOOKS_PASSWORD 提供，避免进入 shell 历史）。
会话认证与 token 认证对比，可看出 token 认证的额外开销。上传、删除、读 /api/admin/perf 需要相应权限（建议管理员）。
"""
import argparse
import http.cookiejar
import io
import json
import os
import re
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

POLL_PATHS = ("/api/admin/tasks/running", "/api/user/messages")
AUTH = {}
DEFAULT_TIMEOUT = [60]
PRINT_LOCK = threading.Lock()
T0 = time.time()


def log(msg):
    with PRINT_LOCK:
        print("[%6.1fs] %s" % (time.time() - T0, msg), flush=True)


def sign_in(base, username, password):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    data = urllib.parse.urlencode({"username": username, "password": password}).encode()
    with opener.open(urllib.request.Request(base + "/api/user/sign_in", data=data, method="POST"), timeout=30) as rsp:
        result = json.loads(rsp.read())
    if result.get("err") != "ok":
        raise SystemExit("登录失败: %s" % result)
    cookie = "; ".join("%s=%s" % (c.name, c.value) for c in jar)
    if not cookie:
        raise SystemExit("登录成功但没有收到 cookie")
    return cookie


def fetch(base, path, token, timeout=None, method="GET", extra_headers=None, data=None, with_headers=False):
    if data is None and method == "POST":
        data = b""
    headers = dict(AUTH) if AUTH else {"X-MYBOOKS-TOKEN": token}
    headers.update(extra_headers or {})
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    start = time.perf_counter()
    status = 0
    body = b""
    rsp_headers = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout or DEFAULT_TIMEOUT[0]) as rsp:
            status = rsp.status
            rsp_headers = dict(rsp.headers)
            body = rsp.read()
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception:
        status = -1
    ms = (time.perf_counter() - start) * 1000.0
    return (status, ms, body, rsp_headers) if with_headers else (status, ms, body)


def candidate_book_ids(base, token, term="书", limit=60):
    status, _, body = fetch(base, "/api/search?name=%s&start=0&size=%d" % (urllib.parse.quote(term), limit), token)
    ids = []
    try:
        ids = [b["id"] for b in json.loads(body).get("books", []) if "id" in b] if status == 200 else []
    except ValueError:
        pass
    if not ids:
        status, _, body = fetch(base, "/api/index", token)
        try:
            data = json.loads(body) if status == 200 else {}
        except ValueError:
            data = {}
        ids = [b["id"] for key in ("new_books", "random_books") for b in data.get(key, []) if "id" in b]
    return ids


def pick_download_book(base, token, fmt, term="书", min_kb=1024, max_mb=50, tries=30):
    """从现有书里自动挑一本有指定格式、大小适中的书，用于下载测试；返回 (book_id, size_bytes)，找不到返回 (0, 0)。"""
    fallback = (0, 0)
    for book_id in candidate_book_ids(base, token, term)[:tries]:
        status, _, body = fetch(base, "/api/book/%d" % book_id, token)
        if status != 200:
            continue
        try:
            files = json.loads(body).get("book", {}).get("files", [])
        except ValueError:
            continue
        for item in files:
            if str(item.get("format", "")).upper() != fmt.upper():
                continue
            size = int(item.get("size") or 0)
            if min_kb * 1024 <= size <= max_mb * 1024 * 1024:
                return book_id, size
            if not fallback[0]:
                fallback = (book_id, size)
    return fallback


def ranged_download(base, token, path, segment_kb, on_segment=None):
    """按 Range 分段完整下载，返回 (分段数, 总耗时ms, 总字节)；每段回调 on_segment(status, ms)。"""
    start = time.perf_counter()
    offset = 0
    total = None
    segments = 0
    size = segment_kb * 1024
    while total is None or offset < total:
        status, ms, body, headers = fetch(base, path, token, extra_headers={"Range": "bytes=%d-%d" % (offset, offset + size - 1)}, with_headers=True)
        segments += 1
        if on_segment:
            on_segment(status, ms)
        if status not in (200, 206):
            break
        content_range = headers.get("Content-Range", "")
        if status == 200 or "/" not in content_range:
            offset += len(body)
            break
        total = int(content_range.rsplit("/", 1)[1])
        offset += len(body)
    return segments, (time.perf_counter() - start) * 1000.0, offset


def scenario_paths(name, book, thumb_base):
    if name == "search":
        q = urllib.parse.quote("书 OR 書")
        return ["/api/search?name=%s&start=0&size=1000" % q, "/api/search?name=%s&start=0&size=60&order=title" % q]
    if name == "search10k":
        return ["/api/search?name=%s&start=0&size=10000" % urllib.parse.quote("书 OR 書")]
    if name == "searchseg":
        return ["/api/search?title=%s&seg=1&start=0&size=60" % urllib.parse.quote("赛博朋克二零七七")]
    if name == "index":
        return ["/api/index?refresh=1", "/api/categories", "/api/all"]
    if name == "thumb":
        return ["/get/thumb_150_200/%d.jpg?t=%d" % (i + thumb_base, time.time()) for i in range(1, 41)]
    raise SystemExit("unknown scenario: " + name)


def label_for(path):
    parsed = urllib.parse.urlparse(path)
    params = urllib.parse.parse_qs(parsed.query)
    shape = "&".join("%s=%s" % (k, params[k][0]) for k in ("size", "order", "seg") if k in params)
    label = re.sub(r"/\d+\.jpg", "/N.jpg", parsed.path)
    return label + ("?" + shape if shape else "")


def worker(base, token, paths, stop, results, verbose, tag):
    i = 0
    while not stop.is_set():
        path = paths[i % len(paths)]
        i += 1
        status, ms, _ = fetch(base, path, token)
        label = label_for(path)
        results.append((label, status, ms))
        if verbose:
            log("  load[%s] %-3s %7.0fms %s" % (tag, status, ms, label[:60]))


def build_epub(title, author, size_kb):
    uid = uuid.uuid4().hex
    body = "".join("<p>%s</p>" % os.urandom(64).hex() for _ in range(max(1, size_kb * 1024 * 2 // 140)))
    container = ('<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                 '<rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
    opf = ('<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>%s</dc:title><dc:creator>%s</dc:creator>'
           '<dc:language>en</dc:language><dc:identifier id="id">urn:uuid:%s</dc:identifier></metadata>'
           '<manifest><item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
           '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>'
           '<spine toc="ncx"><itemref idref="ch1"/></spine></package>') % (title, author, uid)
    ncx = ('<?xml version="1.0" encoding="utf-8"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head>'
           '<meta name="dtb:uid" content="urn:uuid:%s"/></head><docTitle><text>%s</text></docTitle><navMap>'
           '<navPoint id="n1" playOrder="1"><navLabel><text>Chapter</text></navLabel><content src="ch1.xhtml"/></navPoint></navMap></ncx>') % (uid, title)
    chapter = ('<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>%s</title></head>'
               '<body><h1>%s</h1>%s</body></html>') % (title, title, body)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name, content in (("META-INF/container.xml", container), ("content.opf", opf), ("toc.ncx", ncx), ("ch1.xhtml", chapter)):
            zf.writestr(name, content, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def retitle_epub(data, title, author):
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    changed = False
    with zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            content = src.read(info.filename)
            if info.filename.lower().endswith(".opf"):
                text = content.decode("utf-8", "ignore")
                text, n = re.subn(r"<dc:title[^>]*>.*?</dc:title>", "<dc:title>%s</dc:title>" % title, text, count=1, flags=re.S)
                text = re.sub(r"<dc:creator[^>]*>.*?</dc:creator>", "", text, flags=re.S)
                text = text.replace("</metadata>", "<dc:creator>%s</dc:creator></metadata>" % author, 1)
                content = text.encode("utf-8")
                changed = changed or n > 0
            dst.writestr(info, content)
    if not changed:
        raise SystemExit("--epub 文件里没有找到 OPF 的 dc:title，无法保证标题唯一，已放弃")
    return out.getvalue()


def multipart(field, filename, data):
    boundary = "----perfprobe" + uuid.uuid4().hex
    head = ('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\nContent-Type: application/epub+zip\r\n\r\n'
            % (boundary, field, filename)).encode()
    return head + data + ("\r\n--%s--\r\n" % boundary).encode(), "multipart/form-data; boundary=" + boundary


def post_upload(base, token, filename, data, timeout=300, query=""):
    body, ctype = multipart("ebook", filename, data)
    headers = dict(AUTH) if AUTH else {"X-MYBOOKS-TOKEN": token}
    headers["Content-Type"] = ctype
    req = urllib.request.Request(base + "/api/book/upload" + query, data=body, method="POST", headers=headers)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as rsp:
            raw = rsp.read()
    except Exception as e:
        return -1, (time.perf_counter() - start) * 1000.0, {"err": "http", "msg": str(e)}
    ms = (time.perf_counter() - start) * 1000.0
    try:
        return 200, ms, json.loads(raw)
    except ValueError:
        return -1, ms, {"err": "bad_json", "msg": raw[:100].decode("utf-8", "ignore")}


def attach_related_data(base, token, book_id, title, results):
    status, ms, _ = fetch(base, "/api/book/%d/readstate" % book_id, token, method="POST", data=b'{"read_state": 1, "online_read": 1, "download": 1}')
    results.append(("POST /api/book/N/readstate", 200 if status == 200 else -2, ms))
    text = ("PerfProbe text for %s\n" % title).encode() * 200
    status, ms, rsp = post_upload(base, token, title + ".txt", text, query="?bid=%d" % book_id)
    ok = status == 200 and rsp.get("err") == "ok"
    results.append(("POST /api/book/upload?bid (add format)", 200 if ok else -2, ms))
    log("  已附加阅读状态与 txt 格式 -> %s" % ("ok" if ok else rsp))


def upload_cycle(base, token, args, results, with_data=False):
    title = "PerfProbe-" + uuid.uuid4().hex[:8]
    author = "PerfProbe"
    if args.epub:
        with open(args.epub, "rb") as f:
            data = retitle_epub(f.read(), title, author)
    else:
        data = build_epub(title, author, args.epub_size_kb)
    status, ms, rsp = post_upload(base, token, title + ".epub", data)
    ok = status == 200 and rsp.get("err") == "ok" and rsp.get("book_id")
    results.append(("POST /api/book/upload", 200 if ok else -2, ms))
    log("UPLOAD %7.0fms size=%dKB title=%s -> %s" % (ms, len(data) // 1024, title, ("book_id=%s" % rsp.get("book_id")) if ok else rsp))
    if not ok:
        return
    book_id = int(rsp["book_id"])
    status, ms, body = fetch(base, "/api/book/%d" % book_id, token)
    verified = status == 200 and title.encode() in body
    results.append(("GET /api/book/N (verify)", 200 if verified else -2, ms))
    if not verified:
        log("!! 校验失败：book_id=%d 的标题与本次上传不一致（可能并入了已有书籍），为安全起见不删除，请人工确认" % book_id)
        return
    if with_data:
        attach_related_data(base, token, book_id, title, results)
    status, ms, body = fetch(base, "/api/book/%d/delete" % book_id, token, method="POST")
    try:
        deleted = status == 200 and json.loads(body).get("err") == "ok"
    except ValueError:
        deleted = False
    results.append(("POST /api/book/N/delete" + (" (with data)" if with_data else ""), 200 if deleted else -2, ms))
    log("DELETE %7.0fms book_id=%d -> %s" % (ms, book_id, "ok" if deleted else body[:120]))
    if not deleted:
        log("!! 删除失败，测试书籍残留：搜索标题 %s 手动清理" % title)


def uploader(base, token, args, stop, results):
    while not stop.is_set():
        upload_cycle(base, token, args, results, args.delete_with_data)
        stop.wait(args.upload_gap)


def downloader(base, token, args, stop, results):
    path = "/api/book/%d.%s" % (args.book, args.format.upper())
    while not stop.is_set():
        def record(status, ms):
            results.append(("GET %s (range %dKB)" % (path, args.range_kb), status, ms))
        segments, ms, size = ranged_download(base, token, path, args.range_kb, record)
        log("DOWNLOAD %s %d 段 %.0fms %dKB" % (path, segments, ms, size // 1024))
        stop.wait(args.download_gap)


def poller(base, token, interval, stop, results, verbose):
    while not stop.is_set():
        for path in POLL_PATHS:
            status, ms, _ = fetch(base, path, token)
            results.append((path, status, ms))
            if verbose:
                log("  poll %-3s %7.0fms %s" % (status, ms, path))
        stop.wait(interval)


def percentile(values, pct):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * pct))] if ordered else 0.0


def stat_line(values):
    if not values:
        return "n=0"
    return "n=%d p50=%.0f p95=%.0f max=%.0f mean=%.0f" % (len(values), percentile(values, 0.5), percentile(values, 0.95), max(values), statistics.mean(values))


def server_cpu(args):
    status, _, body = fetch(args.base, "/api/admin/perf", args.token)
    if status != 200:
        return None
    system = json.loads(body)["perf"].get("system", {})
    return time.time(), system.get("cpu_user_s", 0.0) + system.get("cpu_sys_s", 0.0)


def run_round(args, number):
    cpu_before = server_cpu(args)
    fetch(args.base, "/api/admin/perf", args.token, method="POST")
    log("===== 第 %d/%d 轮开始，时长 %ds，场景 %s，每场景并发 %d =====" % (number, args.rounds, args.duration, args.scenario, args.concurrency))

    stop = threading.Event()
    results = []
    threads = []
    for name in args.scenario.split(","):
        name = name.strip()
        if name == "download":
            for _ in range(args.concurrency):
                t = threading.Thread(target=downloader, args=(args.base, args.token, args, stop, results), daemon=True)
                t.start()
                threads.append(t)
            continue
        if name == "upload":
            for _ in range(args.upload_concurrency):
                t = threading.Thread(target=uploader, args=(args.base, args.token, args, stop, results), daemon=True)
                t.start()
                threads.append(t)
            continue
        paths = scenario_paths(name, args.book, args.thumb_base)
        for k in range(args.concurrency):
            t = threading.Thread(target=worker, args=(args.base, args.token, paths, stop, results, not args.quiet, "%s#%d" % (name, k)), daemon=True)
            t.start()
            threads.append(t)

    polls = []
    poll_thread = threading.Thread(target=poller, args=(args.base, args.token, args.poll_interval, stop, polls, not args.quiet), daemon=True)
    if args.poll_interval > 0:
        poll_thread.start()

    probe = []
    probe_fail = [0]
    started = time.time()
    next_summary = started + args.summary_interval
    while time.time() - started < args.duration:
        status, ms, _ = fetch(args.base, "/api/user/info", args.token)
        probe.append(ms)
        if status != 200:
            probe_fail[0] += 1
        log("PROBE /api/user/info %-3s %7.0fms" % (status, ms))
        if time.time() >= next_summary:
            errs = sum(1 for _, s, _ in results if s not in (200, 206))
            log("--- 进度 %ds/%ds：负载完成 %d（失败 %d），探针 %s ---" % (time.time() - started, args.duration, len(results), errs, stat_line(probe)))
            next_summary += args.summary_interval
        time.sleep(args.probe_interval)
    stop.set()
    log("时长到，等待在途请求结束…")
    for t in threads:
        t.join(timeout=70)
    if poll_thread.is_alive():
        poll_thread.join(timeout=70)

    by_path = {}
    for path, status, ms in results:
        by_path.setdefault(path, []).append((status, ms))
    log("-- 第 %d 轮 探针 /api/user/info: %s fail=%d" % (number, stat_line(probe), probe_fail[0]))
    for path, rows in sorted(by_path.items()):
        errs = sum(1 for s, _ in rows if s not in (200, 206))
        log("-- 负载 %-40s err=%-3d %s" % (path[:40], errs, stat_line([m for _, m in rows])))

    poll_by_path = {}
    for path, status, ms in polls:
        poll_by_path.setdefault(path, []).append(ms)
    for path, values in sorted(poll_by_path.items()):
        log("-- 轮询 %-40s %s" % (path, stat_line(values)))

    status, _, body = fetch(args.base, "/api/admin/perf", args.token)
    perf = json.loads(body)["perf"] if status == 200 else None
    if perf:
        print_perf(number, perf)
        system = perf.get("system", {})
        if cpu_before:
            wall = time.time() - cpu_before[0]
            used = system.get("cpu_user_s", 0.0) + system.get("cpu_sys_s", 0.0) - cpu_before[1]
            log("-- 第 %d 轮 服务端进程 CPU：平均 %.2f 核（共 %s 核），loadavg=%s，RSS=%.0fMB，线程数=%s" % (
                number, used / wall if wall else 0, system.get("cpu_count"), system.get("loadavg"), system.get("max_rss_kb", 0) / 1024.0, system.get("threads")))
    return probe, results, polls, perf


def print_perf(number, perf):
    log("-- 第 %d 轮 服务端 书库=%s 本 loop_lag_ms=%s stall_total=%s calibre=%s" % (number, perf.get("library_books"), perf["loop_lag_ms"], perf["stall_total"], json.dumps(perf["calibre"], ensure_ascii=False)))
    if perf.get("stages"):
        log("-- 第 %d 轮 分段耗时 %s" % (number, json.dumps(perf["stages"], ensure_ascii=False)))
    if perf.get("thumb_cache"):
        log("-- 第 %d 轮 缩略图缓存 %s" % (number, json.dumps(perf["thumb_cache"], ensure_ascii=False)))
    profile = perf.get("profile") or {}
    log("-- 采样 %s 次（间隔 %sms，仅统计 ioloop 停滞期间）" % (profile.get("samples"), profile.get("interval_ms")))
    for key, title in (("layer", "按层"), ("entry", "按入口(handler)"), ("app", "按应用代码行"), ("leaf", "按最内层函数")):
        log("   [%s]" % title)
        for row in profile.get(key, []):
            log("     %5.1f%% %5d  %s" % (row["pct"], row["count"], row["name"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--token", default="", help="管理员 podcast token（X-MYBOOKS-TOKEN）")
    ap.add_argument("--scenario", default="search,index,thumb")
    ap.add_argument("--duration", type=int, default=60, help="每轮时长（秒）")
    ap.add_argument("--rounds", type=int, default=1, help="执行轮数，每轮开始前会重置服务端统计")
    ap.add_argument("--concurrency", type=int, default=2, help="每个场景的并发数")
    ap.add_argument("--book", type=int, default=0, help="download 场景使用的已有书籍 id；0（默认）自动挑选一本有 --format 格式、1MB–50MB 的书")
    ap.add_argument("--search-term", default="书", help="自动挑书时使用的搜索词")
    ap.add_argument("--thumb-base", type=int, default=30000, help="thumb 场景的书 id 起点，需在测试库中存在")
    ap.add_argument("--probe-interval", type=float, default=0.5)
    ap.add_argument("--summary-interval", type=int, default=10, help="进度汇总间隔（秒）")
    ap.add_argument("--poll-interval", type=float, default=10, help="模拟前端轮询 tasks/running 与 user/messages 的间隔（秒），0 关闭")
    ap.add_argument("--cookie", default="", help="浏览器登录后的 Cookie 串；指定后用会话认证代替 token")
    ap.add_argument("--username", default="", help="用户名；与 --password 一起使用，启动时登录一次获取 cookie")
    ap.add_argument("--password", default=os.environ.get("MYBOOKS_PASSWORD", ""))
    ap.add_argument("--epub", default="", help="upload 场景使用的本地 epub；不指定则合成")
    ap.add_argument("--epub-size-kb", type=int, default=300, help="合成 epub 的大致大小")
    ap.add_argument("--upload-concurrency", type=int, default=1)
    ap.add_argument("--delete-with-data", action="store_true", help="upload 场景删除前先给测试书附加阅读状态与 txt 格式，更接近真实书籍的删除成本")
    ap.add_argument("--upload-gap", type=float, default=2, help="两次上传循环之间的间隔（秒）")
    ap.add_argument("--timeout", type=float, default=60, help="单请求超时秒数；MyReader 为 5，超时计为失败")
    ap.add_argument("--format", default="EPUB", help="download 场景下载的格式，需是 --book 书籍已有的格式")
    ap.add_argument("--range-kb", type=int, default=256, help="download 场景每个 Range 分段大小")
    ap.add_argument("--download-gap", type=float, default=1)
    ap.add_argument("--quiet", action="store_true", help="不逐条打印负载请求")
    args = ap.parse_args()
    DEFAULT_TIMEOUT[0] = args.timeout

    if args.username:
        if not args.password:
            raise SystemExit("指定了 --username 但没有密码（--password 或环境变量 MYBOOKS_PASSWORD）")
        args.cookie = sign_in(args.base, args.username, args.password)
        log("已用账号 %s 登录，获得 cookie" % args.username)
    if not args.cookie and not args.token:
        raise SystemExit("需要 --token、--cookie 或 --username/--password 之一")
    if args.cookie:
        AUTH["Cookie"] = args.cookie
    if "download" in [x.strip() for x in args.scenario.split(",")] and not args.book:
        args.book, size = pick_download_book(args.base, args.token, args.format, args.search_term)
        if not args.book:
            raise SystemExit("没有找到带 %s 格式的现有书籍，无法运行 download 场景；用 --book/--format 指定" % args.format)
        log("download 场景自动选中书籍 id=%d（%s，%d KB）" % (args.book, args.format.upper(), size // 1024))
    log("目标 %s，认证 %s，共 %d 轮" % (args.base, "cookie" if args.cookie else "token", args.rounds))
    all_probe = []
    all_results = []
    all_polls = []
    for number in range(1, args.rounds + 1):
        probe, results, polls, _ = run_round(args, number)
        all_probe.extend(probe)
        all_results.extend(results)
        all_polls.extend(polls)

    log("===== 全部 %d 轮汇总 =====" % args.rounds)
    log("探针 /api/user/info: %s" % stat_line(all_probe))
    by_path = {}
    for path, status, ms in all_results:
        by_path.setdefault(path, []).append(ms)
    for path, values in sorted(by_path.items()):
        log("负载 %-40s %s" % (path[:40], stat_line(values)))
    poll_by_path = {}
    for path, _, ms in all_polls:
        poll_by_path.setdefault(path, []).append(ms)
    for path, values in sorted(poll_by_path.items()):
        log("轮询 %-40s %s" % (path[:40], stat_line(values)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
