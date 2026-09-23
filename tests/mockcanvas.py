"""Local mock of the Canvas REST API for the offline tests.

Serves the JSON fixtures in tests/fixtures/<scenario>/ on 127.0.0.1 only.
Behaves like Canvas where the tool depends on it: Bearer token required,
Link-header paging (per_page capped per scenario), include[]=submission,
include[]=items (omitted when a module has too many items; items_url still
works), include[]=content_details, announcements filtered by context_codes and
start_date/end_date (end defaults to start + 28 days), UTC "Z" timestamps.

    python tests/mockcanvas.py au_semester [--port 8765]

Writes are not supported: any POST/PUT/DELETE gets 405 and is logged.
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlencode, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
BASE_MARK = "{{BASE}}"
LOOPBACK = ("127.0.0.1", "::1")
UTC = dt.timezone.utc


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _ts(s):
    if not s:
        return None
    t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _bound(s, end=False):
    """Canvas accepts a date or an ISO time; a bare end date means the end of that day."""
    if not s:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        d = dt.datetime.fromisoformat(s).replace(tzinfo=UTC)
        return d + dt.timedelta(days=1) - dt.timedelta(seconds=1) if end else d
    return _ts(s)


def _public(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}


class Scenario:
    """The fixture files of one scenario, loaded once."""

    def __init__(self, name, root=FIXTURES):
        self.name = name
        self.dir = os.path.join(root, name)
        if not os.path.isfile(os.path.join(self.dir, "scenario.json")):
            raise ValueError(f"no such scenario: {name}")
        j = lambda *p: os.path.join(self.dir, *p)  # noqa: E731
        self.meta = _load(j("scenario.json"), {})
        self.user = _load(j("users_self.json"), {})
        self.courses = _load(j("courses.json"), [])
        self.course = {}
        for c in self.courses:
            cid = c["id"]
            self.course[cid] = {k: _load(j("courses", str(cid), k + ".json"), [])
                                for k in ("assignments", "assignment_groups", "modules", "files", "discussion_topics")}
        self.announcements = _load(j("announcements.json"), [])
        self.conversations = _load(j("conversations.json"), [])
        self.calendar_events = _load(j("calendar_events.json"), [])
        self.planner_items = _load(j("planner_items.json"), [])
        opts = {"max_per_page": 100, "default_per_page": 10, "inline_items_max": 100}
        opts.update(self.meta.get("mock") or {})
        self.opts = opts
        self.token = self.meta.get("token", "dummy")
        self.now = _ts(self.meta.get("now")) or dt.datetime.now(UTC)

    def file(self, fid):
        for data in self.course.values():
            for f in data["files"]:
                if f["id"] == fid:
                    return f
        return None


class _Handler(BaseHTTPRequestHandler):
    server_version = "MockCanvas/1"

    def log_message(self, fmt, *args):
        if os.environ.get("STC_MOCK_VERBOSE"):
            sys.stderr.write("mockcanvas: " + fmt % args + "\n")

    # ---- plumbing
    def _send(self, status, payload, headers=None, raw=None, ctype="application/json; charset=utf-8"):
        mock = self.server.mock
        body = raw if raw is not None else json.dumps(payload, ensure_ascii=False).replace(BASE_MARK, mock.base_url).encode("utf-8")
        if raw is None and getattr(self, "_session_auth", False) and "application/json" not in (self.headers.get("Accept") or ""):
            body = b"while(1);" + body  # Canvas 给登录（不是 token）拿的 JSON 加这个前缀，除非请求说了要 JSON
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)
        mock._log(self.command, self._path, self._query, status, self._matched)

    def _cookie_ok(self):
        mock = self.server.mock
        return bool(mock.session_cookie) and f"canvas_session={mock.session_cookie}" in (self.headers.get("Cookie") or "")

    def _error(self, status, message, headers=None):
        self._send(status, {"errors": [{"message": message}]}, headers)

    def _q(self, key):
        return [v for k, v in self._query if k == key]

    def _q1(self, key, default=None):
        v = self._q(key)
        return v[0] if v else default

    def _page(self, items):
        opts = self.server.mock.scenario.opts
        try:
            per = int(self._q1("per_page") or opts["default_per_page"])
            page = int(self._q1("page") or 1)
        except ValueError:
            return self._error(400, "invalid page parameters")
        per = max(1, min(per, opts["max_per_page"]))
        page = max(1, page)
        last = max(1, math.ceil(len(items) / per))
        keep = [(k, v) for k, v in self._query if k not in ("page", "per_page")]

        def url(n):
            return f"{self.server.mock.base_url}{self._path}?" + urlencode(keep + [("page", n), ("per_page", per)])
        links = [(url(page), "current")]
        if page < last:
            links.append((url(page + 1), "next"))
        if page > 1:
            links.append((url(page - 1), "prev"))
        links += [(url(1), "first"), (url(last), "last")]
        header = ",".join(f'<{u}>; rel="{r}"' for u, r in links)
        return self._send(200, items[(page - 1) * per: page * per], {"Link": header})

    # ---- entry points
    def do_GET(self):
        mock = self.server.mock
        parts = urlsplit(self.path)
        self._path, self._query, self._matched = parts.path, parse_qsl(parts.query, keep_blank_values=True), True
        self._session_auth = False
        if mock.session:
            if self._path == "/login/canvas":  # 登录页：直接发会话 cookie（不带过期时间，浏览器一关就丢）
                mock.logins += 1
                return self._send(302, None, {"Location": "/?login_success=1",
                                              "Set-Cookie": f"canvas_session={mock.session_cookie}; Path=/; HttpOnly"},
                                  raw=b"", ctype="text/html")
            if self._path == "/":
                if not self._cookie_ok():
                    return self._send(302, None, {"Location": "/login/canvas"}, raw=b"", ctype="text/html")
                return self._send(200, None, raw=b"<!doctype html><title>Dashboard</title><h1>Dashboard</h1>", ctype="text/html")
        m = re.fullmatch(r"/files/(\d+)/download", self._path)
        if m:
            if mock.session and not self.headers.get("Authorization") and not self._cookie_ok():
                return self._send(302, None, {"Location": "/login/canvas"}, raw=b"", ctype="text/html")
            return self._download(int(m.group(1)))
        if not self._path.startswith("/api/v1/"):
            self._matched = False
            return self._error(404, "The specified resource does not exist.")
        forced = mock._forced(self._path)
        if forced:
            return self._error(forced, f"forced {forced} by the test")
        auth = self.headers.get("Authorization") or ""
        if not auth and mock.session and self._cookie_ok():
            self._session_auth = True  # 用浏览器登录（没有 token）访问 API
        elif not auth:
            return self._send(401, {"status": "unauthenticated", "errors": [{"message": "user authorization required"}]},
                              {"WWW-Authenticate": 'Bearer realm="canvas-lms"'})
        elif auth != f"Bearer {mock.scenario.token}":
            return self._error(401, "Invalid access token.", {"WWW-Authenticate": 'Bearer realm="canvas-lms"'})
        for rx, name in _ROUTES:
            m = re.fullmatch(rx, self._path)
            if m:
                return getattr(self, "r_" + name)(*[int(g) for g in m.groups()])
        self._matched = False
        return self._error(404, "The specified resource does not exist.")

    def _refuse_write(self):
        parts = urlsplit(self.path)
        self._path, self._query, self._matched = parts.path, parse_qsl(parts.query, keep_blank_values=True), False
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        return self._error(405, "mockcanvas is read-only")

    do_POST = do_PUT = do_DELETE = do_PATCH = _refuse_write

    # ---- routes
    def _course_or_404(self, cid):
        data = self.server.mock.scenario.course.get(cid)
        if data is None:
            self._error(404, "The specified resource does not exist.")
        return data

    def r_user_self(self):
        return self._send(200, self.server.mock.scenario.user)

    def r_user_profile(self):
        u = self.server.mock.scenario.user
        return self._send(200, {"id": u.get("id"), "name": u.get("name"), "short_name": u.get("short_name"),
                                "sortable_name": u.get("sortable_name"), "time_zone": u.get("time_zone"),
                                "locale": u.get("locale")})

    def r_courses(self):
        sc = self.server.mock.scenario
        state = self._q1("enrollment_state")
        include = self._q("include[]")
        out = []
        for c in sc.courses:
            if state == "active" and not c.get("_active", True):
                continue
            pc = _public(c)
            if "term" not in include:
                pc.pop("term", None)
            out.append(pc)
        return self._page(out)

    def r_course(self, cid):
        sc = self.server.mock.scenario
        c = next((x for x in sc.courses if x["id"] == cid), None)
        return self._send(200, _public(c)) if c else self._error(404, "The specified resource does not exist.")

    def _assignment_view(self, a):
        a = _public(a)
        if "submission" not in self._q("include[]"):
            a.pop("submission", None)
        return a

    def r_assignments(self, cid):
        data = self._course_or_404(cid)
        if data is not None:
            return self._page([self._assignment_view(a) for a in data["assignments"]])

    def r_assignment(self, cid, aid):
        data = self._course_or_404(cid)
        if data is None:
            return None
        a = next((x for x in data["assignments"] if x["id"] == aid), None)
        return self._send(200, self._assignment_view(a)) if a else self._error(404, "The specified resource does not exist.")

    def r_submission_self(self, cid, aid):
        data = self._course_or_404(cid)
        if data is None:
            return None
        a = next((x for x in data["assignments"] if x["id"] == aid), None)
        return self._send(200, a["submission"]) if a else self._error(404, "The specified resource does not exist.")

    def r_assignment_groups(self, cid):
        data = self._course_or_404(cid)
        if data is None:
            return None
        groups = [dict(g) for g in data["assignment_groups"]]
        if "assignments" in self._q("include[]"):
            for g in groups:
                g["assignments"] = [self._assignment_view(a) for a in data["assignments"] if a.get("assignment_group_id") == g["id"]]
        return self._page(groups)

    def _item_view(self, it):
        it = dict(it)
        if "content_details" not in self._q("include[]"):
            it.pop("content_details", None)
        return it

    def _module_view(self, cid, m):
        opts = self.server.mock.scenario.opts
        out = {k: v for k, v in m.items() if k != "items"}
        items = m.get("items") or []
        out["items_count"] = len(items)
        out["items_url"] = f"{BASE_MARK}/api/v1/courses/{cid}/modules/{m['id']}/items"
        if "items" in self._q("include[]") and len(items) <= opts["inline_items_max"]:
            out["items"] = [self._item_view(it) for it in items]
        return out

    def r_modules(self, cid):
        data = self._course_or_404(cid)
        if data is not None:
            return self._page([self._module_view(cid, m) for m in data["modules"]])

    def r_module(self, cid, mid):
        data = self._course_or_404(cid)
        if data is None:
            return None
        m = next((x for x in data["modules"] if x["id"] == mid), None)
        return self._send(200, self._module_view(cid, m)) if m else self._error(404, "The specified resource does not exist.")

    def r_module_items(self, cid, mid):
        data = self._course_or_404(cid)
        if data is None:
            return None
        m = next((x for x in data["modules"] if x["id"] == mid), None)
        if m is None:
            return self._error(404, "The specified resource does not exist.")
        return self._page([self._item_view(it) for it in m.get("items") or []])

    def r_course_files(self, cid):
        data = self._course_or_404(cid)
        if data is not None:
            return self._page([_public(f) for f in data["files"]])

    def r_course_file(self, cid, fid):
        return self.r_file(fid)

    def r_file(self, fid):
        f = self.server.mock.scenario.file(fid)
        return self._send(200, _public(f)) if f else self._error(404, "The specified resource does not exist.")

    def _download(self, fid):
        f = self.server.mock.scenario.file(fid)
        if not f or f.get("locked_for_user"):
            return self._error(404 if not f else 403, "file not available")
        return self._send(200, None, raw=(f.get("_body") or "").encode("utf-8"), ctype=f.get("content-type") or "application/octet-stream")

    def r_discussion_topics(self, cid):
        data = self._course_or_404(cid)
        if data is not None:
            return self._page(data["discussion_topics"])

    def r_discussion_topic(self, cid, tid):
        data = self._course_or_404(cid)
        if data is None:
            return None
        t = next((x for x in data["discussion_topics"] if x["id"] == tid), None)
        return self._send(200, t) if t else self._error(404, "The specified resource does not exist.")

    def r_announcements(self):
        sc = self.server.mock.scenario
        codes = self._q("context_codes[]")
        if not codes:
            return self._error(400, "context_codes is required")
        start = _bound(self._q1("start_date")) or (sc.now - dt.timedelta(days=14))
        end = _bound(self._q1("end_date"), end=True) or (start + dt.timedelta(days=28))
        out = [a for a in sc.announcements if a.get("context_code") in codes and start <= _ts(a["posted_at"]) <= end]
        out.sort(key=lambda a: a["posted_at"], reverse=True)
        return self._page(out)

    def r_conversations(self):
        sc = self.server.mock.scenario
        scope = self._q1("scope") or "inbox"
        out = [c for c in sc.conversations
               if (scope == "unread" and c.get("workflow_state") == "unread")
               or (scope == "archived" and c.get("workflow_state") == "archived")
               or (scope in ("inbox", "sent", "starred") and c.get("workflow_state") != "archived")]
        out.sort(key=lambda c: c.get("last_message_at") or "", reverse=True)
        return self._page(out)

    def r_calendar_events(self):
        sc = self.server.mock.scenario
        kind = self._q1("type") or "event"
        codes = self._q("context_codes[]")
        out = [e for e in sc.calendar_events if e.get("type") == kind and (not codes or e.get("context_code") in codes)]
        if (self._q1("all_events") or "").lower() not in ("1", "true"):
            start = _bound(self._q1("start_date")) or sc.now.replace(hour=0, minute=0, second=0)
            end = _bound(self._q1("end_date"), end=True) or (start + dt.timedelta(days=1))
            out = [e for e in out if start <= _ts(e["start_at"]) <= end]
        return self._page(sorted(out, key=lambda e: (e["start_at"], str(e["id"]))))

    def r_planner_items(self):
        sc = self.server.mock.scenario
        codes = self._q("context_codes[]")
        start, end = _bound(self._q1("start_date")), _bound(self._q1("end_date"), end=True)
        out = [p for p in sc.planner_items
               if (not codes or f"course_{p.get('course_id')}" in codes)
               and (start is None or _ts(p["plannable_date"]) >= start)
               and (end is None or _ts(p["plannable_date"]) <= end)]
        return self._page(out)


_ROUTES = [
    (r"/api/v1/users/self", "user_self"),
    (r"/api/v1/users/self/profile", "user_profile"),
    (r"/api/v1/courses", "courses"),
    (r"/api/v1/courses/(\d+)", "course"),
    (r"/api/v1/courses/(\d+)/assignments", "assignments"),
    (r"/api/v1/courses/(\d+)/assignments/(\d+)", "assignment"),
    (r"/api/v1/courses/(\d+)/assignments/(\d+)/submissions/self", "submission_self"),
    (r"/api/v1/courses/(\d+)/assignment_groups", "assignment_groups"),
    (r"/api/v1/courses/(\d+)/modules", "modules"),
    (r"/api/v1/courses/(\d+)/modules/(\d+)", "module"),
    (r"/api/v1/courses/(\d+)/modules/(\d+)/items", "module_items"),
    (r"/api/v1/courses/(\d+)/files", "course_files"),
    (r"/api/v1/courses/(\d+)/files/(\d+)", "course_file"),
    (r"/api/v1/courses/(\d+)/discussion_topics", "discussion_topics"),
    (r"/api/v1/courses/(\d+)/discussion_topics/(\d+)", "discussion_topic"),
    (r"/api/v1/files/(\d+)", "file"),
    (r"/api/v1/announcements", "announcements"),
    (r"/api/v1/conversations", "conversations"),
    (r"/api/v1/calendar_events", "calendar_events"),
    (r"/api/v1/planner/items", "planner_items"),
]


class MockCanvas:
    """with MockCanvas("au_semester") as mock: ... mock.base_url ... mock.requests()"""

    def __init__(self, scenario, host="127.0.0.1", port=0, session=False):
        if host not in LOOPBACK:
            raise ValueError("mockcanvas only binds to loopback")
        self.session = session  # True：另外接受浏览器登录（/login/canvas 发 cookie），测登录模式用
        self.session_cookie = uuid.uuid4().hex if session else None
        self.logins = 0
        self.scenario = scenario if isinstance(scenario, Scenario) else Scenario(scenario)
        self.host, self.port = host, port
        self._lock = threading.Lock()
        self._log_entries = []
        self._force = []
        self.httpd = None
        self.thread = None

    @property
    def base_url(self):
        return f"http://{self.host}:{self.port}"

    def start(self):
        self.httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.mock = self
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.thread.join(5)
            self.httpd = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def expire_session(self):
        """登录过期：之前发的 cookie 全都不认了。"""
        self.session_cookie = uuid.uuid4().hex

    def force_status(self, path_regex, status):
        """Make matching API paths answer with an HTTP error (for failure tests)."""
        self._force.append((re.compile(path_regex), status))

    def _forced(self, path):
        return next((st for rx, st in self._force if rx.search(path)), None)

    def _log(self, method, path, query, status, matched):
        with self._lock:
            self._log_entries.append({"method": method, "path": path, "query": list(query), "status": status,
                                      "matched": matched})

    def requests(self, clear=False):
        with self._lock:
            out = list(self._log_entries)
            if clear:
                self._log_entries.clear()
        return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Serve one fixture scenario as a mock Canvas on 127.0.0.1.")
    ap.add_argument("scenario")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args(argv)
    mock = MockCanvas(args.scenario, port=args.port).start()
    print(f"mock Canvas for {args.scenario} at {mock.base_url} (token: {mock.scenario.token}); Ctrl+C to stop", flush=True)
    try:
        mock.thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        mock.stop()


if __name__ == "__main__":
    main()
