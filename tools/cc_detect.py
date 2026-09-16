"""在浏览器痕迹里认学校的 Canvas 域名。

只做三件事：把浏览器的历史 / 书签数据库复制到临时目录只读打开；SQL 只取网址和访问次数；
只输出像 Canvas 的域名和分数。不读网页标题，不保留任何网址，临时副本用完即删。
"""
import glob
import json
import os
import plistlib
import re
import shutil
import sqlite3
import sys
import tempfile
import urllib.parse

DENY_HOSTS = ("coursera.org", "udemy.com", "github.com", "google.com", "edx.org", "canva.com", "canvasjs.com",
              "linkedin.com", "youtube.com", "microsoft.com", "apple.com", "instructure.com/",)
SQL_FILTER = ("url LIKE '%instructure.com%' OR url LIKE '%canvas%' OR url LIKE '%/login/canvas%' OR url LIKE '%/courses/%'")


def _home():
    return os.path.expanduser("~")


def browser_files():
    """(浏览器, 类型, 路径)。类型：chromium-history / chromium-bookmarks / firefox / safari-history / safari-bookmarks。"""
    h = _home()
    out = []
    if sys.platform == "win32":
        la = os.environ.get("LOCALAPPDATA", os.path.join(h, "AppData", "Local"))
        ra = os.environ.get("APPDATA", os.path.join(h, "AppData", "Roaming"))
        chromium = [("Chrome", os.path.join(la, "Google", "Chrome", "User Data")),
                    ("Edge", os.path.join(la, "Microsoft", "Edge", "User Data")),
                    ("Brave", os.path.join(la, "BraveSoftware", "Brave-Browser", "User Data")),
                    ("Chromium", os.path.join(la, "Chromium", "User Data"))]
        firefox = [os.path.join(ra, "Mozilla", "Firefox", "Profiles")]
        safari = []
    elif sys.platform == "darwin":
        asup = os.path.join(h, "Library", "Application Support")
        chromium = [("Chrome", os.path.join(asup, "Google", "Chrome")), ("Edge", os.path.join(asup, "Microsoft Edge")),
                    ("Brave", os.path.join(asup, "BraveSoftware", "Brave-Browser")), ("Arc", os.path.join(asup, "Arc", "User Data")),
                    ("Chromium", os.path.join(asup, "Chromium"))]
        firefox = [os.path.join(asup, "Firefox", "Profiles")]
        safari = [("Safari", "safari-history", os.path.join(h, "Library", "Safari", "History.db")),
                  ("Safari", "safari-bookmarks", os.path.join(h, "Library", "Safari", "Bookmarks.plist"))]
    else:
        cfgd = os.path.join(h, ".config")
        chromium = [("Chrome", os.path.join(cfgd, "google-chrome")), ("Edge", os.path.join(cfgd, "microsoft-edge")),
                    ("Brave", os.path.join(cfgd, "BraveSoftware", "Brave-Browser")), ("Chromium", os.path.join(cfgd, "chromium"))]
        firefox = [os.path.join(h, ".mozilla", "firefox")]
        safari = []
    for name, base in chromium:
        for prof in glob.glob(os.path.join(base, "Default")) + glob.glob(os.path.join(base, "Profile *")):
            for kind, fn in (("chromium-history", "History"), ("chromium-bookmarks", "Bookmarks")):
                p = os.path.join(prof, fn)
                if os.path.exists(p):
                    out.append((name, kind, p))
    for base in firefox:
        for p in glob.glob(os.path.join(base, "*", "places.sqlite")):
            out.append(("Firefox", "firefox", p))
    for name, kind, p in safari:
        if os.path.exists(p):
            out.append((name, kind, p))
    return out


def _ro_copy(path, tmpdir):
    dst = os.path.join(tmpdir, os.path.basename(path))
    shutil.copy2(path, dst)
    for suffix in ("-wal", "-journal", "-shm"):
        if os.path.exists(path + suffix):
            try:
                shutil.copy2(path + suffix, dst + suffix)
            except OSError:
                pass
    return dst


def _query(dbpath, sql):
    con = sqlite3.connect(f"file:{dbpath}?mode=ro", uri=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def is_candidate(url):
    """像 Canvas 的网址 → (域名, 权重)；否则 None。"""
    try:
        p = urllib.parse.urlparse(url)
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    host = p.netloc.lower().split("@")[-1]
    if host.startswith("www."):
        host = host[4:]
    if any(host == d or host.endswith("." + d) for d in DENY_HOSTS if not d.endswith("/")):
        return None
    path = p.path or "/"
    w = 0
    if host.endswith(".instructure.com") and not host.startswith("community."):
        w += 30
        if host == "canvas.instructure.com":
            w -= 20
    if re.search(r"(^|[.-])canvas([.-]|$)", host):
        w += 20
    if path.startswith("/login/canvas") or path.startswith("/login/saml") and "canvas" in host:
        w += 40
    if re.match(r"^/courses/\d+", path):
        w += 10
        if re.search(r"/(modules|assignments|files|grades|announcements|discussion_topics|quizzes|pages)", path):
            w += 10
    if w <= 0:
        return None
    return host, w


def _walk_bookmarks(node, out):
    if isinstance(node, dict):
        if node.get("type") == "url" and node.get("url"):
            out.append(node["url"])
        for v in node.values():
            if isinstance(v, (dict, list)):
                _walk_bookmarks(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_bookmarks(v, out)


def scan(files=None, dry_run=False):
    """返回 {hosts: {host: {score, visits, bookmarks, browsers}}, files: [...], skipped: [...]}。"""
    files = files if files is not None else browser_files()
    result = {"hosts": {}, "files": [f"{b} {k}: {p}" for b, k, p in files], "scanned": [], "skipped": []}
    if dry_run:
        return result
    hosts = result["hosts"]

    def add(host, w, visits, browser, bookmark=False):
        e = hosts.setdefault(host, {"score": 0, "visits": 0, "bookmarks": 0, "browsers": set()})
        e["score"] += w + visits + (50 if bookmark else 0)
        e["visits"] += visits
        e["bookmarks"] += 1 if bookmark else 0
        e["browsers"].add(browser)

    tmp = tempfile.mkdtemp(prefix="cc-detect-")
    try:
        for browser, kind, path in files:
            try:
                if kind == "chromium-history":
                    rows = _query(_ro_copy(path, tmp), f"SELECT url, visit_count FROM urls WHERE visit_count>0 AND ({SQL_FILTER})")
                    for url, n in rows:
                        c = is_candidate(url)
                        if c:
                            add(c[0], c[1], int(n or 0), browser)
                elif kind == "chromium-bookmarks":
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                    urls = []
                    _walk_bookmarks(data.get("roots", {}), urls)
                    for url in urls:
                        c = is_candidate(url)
                        if c:
                            add(c[0], c[1], 0, browser, bookmark=True)
                elif kind == "firefox":
                    db = _ro_copy(path, tmp)
                    for url, n in _query(db, f"SELECT url, visit_count FROM moz_places WHERE ({SQL_FILTER})"):
                        c = is_candidate(url)
                        if c:
                            add(c[0], c[1], int(n or 0), browser)
                    for (url,) in _query(db, "SELECT p.url FROM moz_bookmarks b JOIN moz_places p ON p.id=b.fk WHERE p.url LIKE '%canvas%' OR p.url LIKE '%instructure%'"):
                        c = is_candidate(url)
                        if c:
                            add(c[0], c[1], 0, browser, bookmark=True)
                elif kind == "safari-history":
                    for url, n in _query(_ro_copy(path, tmp), f"SELECT url, visit_count FROM history_items WHERE ({SQL_FILTER})"):
                        c = is_candidate(url)
                        if c:
                            add(c[0], c[1], int(n or 0), browser)
                elif kind == "safari-bookmarks":
                    with open(path, "rb") as f:
                        data = plistlib.load(f)
                    urls = []

                    def walk(node):
                        if isinstance(node, dict):
                            u = node.get("URLString")
                            if u:
                                urls.append(u)
                            for v in node.values():
                                walk(v)
                        elif isinstance(node, list):
                            for v in node:
                                walk(v)
                    walk(data)
                    for url in urls:
                        c = is_candidate(url)
                        if c:
                            add(c[0], c[1], 0, browser, bookmark=True)
                result["scanned"].append(f"{browser} {kind}")
            except (OSError, sqlite3.Error, ValueError, plistlib.InvalidFileException) as e:
                why = "无权限（Safari 需要「完全磁盘访问」）" if isinstance(e, PermissionError) else f"读不了（{type(e).__name__}）"
                result["skipped"].append(f"{browser} {kind}：{why}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for e in hosts.values():
        e["browsers"] = sorted(e["browsers"])
    return result


def rank(hosts, limit=5):
    return sorted(({"host": h, **v} for h, v in hosts.items()), key=lambda x: -x["score"])[:limit]


def detect(tok=None, limit=5, dry_run=False):
    """扫描 + 探测 + （有 token 时）验证。返回 {candidates, found, me, files, skipped}。"""
    import cc_host
    res = scan(dry_run=dry_run)
    read_status = "readable" if res.get("scanned") else ("unreadable" if res.get("files") else "unavailable_or_absent")
    out = {"candidates": [], "found": None, "me": None, "files": res["files"], "scanned": res.get("scanned") or [],
           "skipped": res["skipped"], "read_status": read_status, "dry_run": dry_run}
    if dry_run:
        return out
    cands = rank(res["hosts"], limit)
    for c in cands:
        url = "https://" + c["host"]
        c["url"] = url
        c["is_canvas"] = cc_host.is_canvas(url)
        c["token_ok"] = None
    verified = [c for c in cands if c["is_canvas"]]
    if tok:
        for c in verified:
            try:
                import canvas_api
                me = canvas_api.Canvas(c["url"], tok, timeout=20, retries=0).get("/api/v1/users/self")
                c["token_ok"] = True
                out["found"], out["me"] = c["url"], me
                break
            except Exception:  # noqa: BLE001
                c["token_ok"] = False
    if not out["found"] and verified:
        top = verified[0]
        second = verified[1]["score"] if len(verified) > 1 else 0
        if len(verified) == 1 or top["score"] >= 3 * max(second, 1):
            out["found"] = top["url"]
    out["candidates"] = cands
    out["ambiguous"] = bool(not out["found"] and len(verified) > 1)
    out["validation_unavailable"] = bool(cands and not verified and any(c.get("is_canvas") is None for c in cands))
    return out


def to_text(res):
    L = []
    if res.get("dry_run"):
        L.append("会读这些文件（只取网址和访问次数）：")
        L += [f" - {f}" for f in res["files"]] or [" （当前没有枚举到浏览器记录文件；预演未读取内容）"]
        return "\n".join(L)
    if res["candidates"]:
        L.append("浏览器记录里像 Canvas 的站点：")
        for c in res["candidates"]:
            tag = "是 Canvas" if c["is_canvas"] else ("连不上（可能要校园网 / VPN）" if c["is_canvas"] is None else "不是 Canvas API")
            tok = "，token 能登上" if c.get("token_ok") else ("，token 登不上" if c.get("token_ok") is False else "")
            L.append(f" - {c['host']}：访问 {c['visits']} 次，书签 {c['bookmarks']}（{'、'.join(c['browsers'])}）· {tag}{tok}")
    else:
        if res.get("read_status") == "readable":
            L.append("已读取浏览器记录，但没找到像 Canvas 的站点。")
        elif res.get("read_status") == "unreadable":
            L.append("找到了浏览器记录文件，但都读不了；可能被系统权限或宿主沙盒拦住。")
        else:
            L.append("没有发现可读取的浏览器记录；可能确实没有记录，也可能被宿主沙盒隐藏。")
    if res.get("found"):
        L.append(f"认定：{res['found']}")
    elif res.get("ambiguous"):
        L.append("有不止一个候选，请用户说是哪个。")
    elif res.get("validation_unavailable"):
        L.append("找到了候选域名，但当前网络或沙盒使它无法验证为 Canvas。")
    for s in res["skipped"]:
        L.append(f" ! 跳过 {s}")
    L.append("只读了域名和访问次数；没有读网页标题或别的记录；临时副本已删除。")
    return "\n".join(L)
