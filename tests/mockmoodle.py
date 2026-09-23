"""Local mock of a Moodle 4.5 site for the offline tests.

Serves the fixture scenario in tests/fixtures/<scenario>/ on 127.0.0.1 only (see its README.md).
Shapes follow the source-verified Moodle 4.5 spec with its errata applied: the session ajax endpoint
/lib/ajax/service.php (sesskey in the query, MoodleSession cookie, per-call {error, data|exception},
break on the first error, a single fatal_error object for an unknown methodname, HTTP 200 either
way), the no-login endpoint for tool_mobile_get_public_config, M.cfg in every page head
(json_encode with escaped slashes), 303 + X-Redirect-By for redirects, and the student pages the
tool reads (assignment, quiz, grade report, forum, course, folder, resource redirect, pluginfile).

    python tests/mockmoodle.py moodle_term [--port 8766] [--logged-out login|sso|guest]

Login is fake: GET /login/index.php hands out the session cookie (no password) and 303s to /my/.
The mock is read-only: POST is accepted only on the two ajax endpoints, and a known write
function there, any PUT/DELETE/PATCH, or a GET that would change something (logout, quiz start,
forum sort order, grade-report view preference, assignment actions) gets 405 and is logged.
"""
import argparse
import base64
import datetime as dt
import html
import json
import os
import random
import re
import string
import sys
import threading
import uuid
import zoneinfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, quote, unquote, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
TZDATA = os.path.join(HERE, "tzdata")
BASE_MARK = "{{BASE}}"
LOOPBACK = ("127.0.0.1", "::1")
UTC = dt.timezone.utc
IDP_URL = "https://idp.example/sso/login"
DOCS = "https://docs.moodle.org/405/en/error"
REV = "1727000000"
COURSE_IMAGE = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4="
PIXEL = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")
MODNAMES = {"assign": "Assignment", "quiz": "Quiz", "forum": "Forum", "resource": "File", "folder": "Folder",
            "page": "Page", "label": "Text and media area", "lti": "External tool", "url": "URL"}

# 会话 ajax 白名单里的读取函数（mock 实现了的）；公开配置不用登录
AJAX_READ = {"core_course_get_enrolled_courses_by_timeline_classification", "core_courseformat_get_state",
             "core_calendar_get_calendar_monthly_view", "core_calendar_get_action_events_by_timesort",
             "mod_forum_get_discussion_posts"}
PUBLIC = {"tool_mobile_get_public_config"}
# 真 Moodle 里存在、但不在白名单里的函数：一律 servicenotavailable（多数本来就只给 token 用）
KNOWN_OTHER = {"mod_assign_get_assignments", "mod_assign_get_submission_status", "mod_assign_get_submissions",
               "mod_forum_get_forum_discussions", "mod_forum_get_forums_by_courses", "mod_quiz_get_quizzes_by_courses",
               "mod_quiz_get_user_attempts", "gradereport_user_get_grade_items", "gradereport_user_get_grades_table",
               "core_webservice_get_site_info", "core_enrol_get_users_courses", "core_course_get_contents",
               "core_grades_get_gradeitems", "core_calendar_get_calendar_upcoming_view",
               "core_calendar_get_calendar_day_view", "core_calendar_get_action_events_by_course",
               "core_calendar_get_calendar_events", "core_user_get_users_by_field", "core_session_touch",
               "core_session_time_remaining"}
# 函数名第三段是这些动词的，当作写（mock 回 405，记进日志）
WRITE_VERBS = {"add", "create", "delete", "update", "save", "submit", "set", "edit", "mark", "remove", "toggle",
               "lock", "unlock", "start", "process", "send", "duplicate", "move", "import", "upload", "reset",
               "revert", "view", "change", "request", "accept", "decline", "block", "unblock", "confirm", "mute",
               "unmute", "star", "unstar", "enrol", "unenrol", "dismiss", "execute", "rate", "grade", "copy"}
WRITE_NAMES = {"core_update_inplace_editable", "core_session_touch"}  # 动词不在第三段的写函数
# 会改东西的 GET：登出、开始测验、改排序偏好等
WRITE_PATHS = re.compile(r"/(login/logout|mod/quiz/(startattempt|processattempt|attempt)|course/(mod|togglecompletion|"
                         r"changenumsections|rest)|calendar/(delete|event)|mod/forum/(post|subscribe|markposts)|"
                         r"user/(edit|preferences)|mod/assign/(action|gradingbatchoperations))\.php$")
ERRORS = {  # errorcode -> (模块, 英文 message)
    "servicerequireslogin": ("webservice", "Web service is not available. (The session has been logged out or has expired.)"),
    "servicenotavailable": ("webservice", "Web service is not available. (It doesn't exist or might be disabled.)"),
    "invalidsesskey": ("moodle", "Your session has most likely timed out. Please check if you are logged in or go back to the previous screen and reload the page."),
    "missingparam": ("moodle", "A required parameter (sesskey) was missing"),
    "invalidparameter": ("moodle", "Invalid parameter value detected"),
    "requireloginerror": ("moodle", "Course or activity not accessible. (Not enrolled)"),
    "generalexceptionmessage": ("moodle", "Exception - Moodle\\core_calendar\\calendar_information::create(): Argument #2 ($courseid) must be of type int, null given"),
    "nopermissions": ("moodle", "Sorry, but you do not currently have permissions to do that."),
    "invalidrecord": ("error", "Can't find data record in database table external_functions."),
}


class AjaxError(Exception):
    def __init__(self, code, message=None):
        super().__init__(code)
        self.code, self.message = code, message


# ---------------------------------------------------------------- 小工具
def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _ts(s):
    """ISO（…Z）→ unix 秒；空就是 None。"""
    if not s:
        return None
    t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return int((t if t.tzinfo else t.replace(tzinfo=UTC)).timestamp())


def _zone(name):
    """先用 tests/tzdata 里的时区文件，各平台一致；没有再找系统的。"""
    path = os.path.join(TZDATA, *name.split("/"))
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return zoneinfo.ZoneInfo.from_file(f, key=name)
    return zoneinfo.ZoneInfo(name)


def php_json(obj):
    """PHP json_encode 默认：非 ASCII 写成 \\uXXXX，斜杠写成 \\/。"""
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).replace("/", "\\/")


def fmt_string(s):
    """format_string：不是实体的 & 变 &amp;，尖括号转义。"""
    s = re.sub(r"&(?!(#\d+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);)", "&amp;", s or "")
    return s.replace("<", "&lt;").replace(">", "&gt;")


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def _hm(d):
    return f"{d.hour % 12 or 12}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"


def _span(secs):
    """format_time 的样子：16 days 9 hours / 3 hours 5 mins / 5 mins。"""
    secs = abs(int(secs))
    days, rest = divmod(secs, 86400)
    hours, rest = divmod(rest, 3600)
    mins = rest // 60
    unit = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"  # noqa: E731
    parts = [unit(days, "day")] if days else []
    if hours:
        parts.append(unit(hours, "hour"))
    if not days and mins:
        parts.append(unit(mins, "min"))
    return " ".join(parts) or "0 secs"


# ---------------------------------------------------------------- 场景
class Scenario:
    """一个场景的全部 fixture，只读一次。"""

    def __init__(self, name, root=FIXTURES):
        self.name = name
        self.dir = os.path.join(root, name)
        if not os.path.isfile(os.path.join(self.dir, "scenario.json")):
            raise ValueError(f"no such scenario: {name}")
        j = lambda *p: os.path.join(self.dir, *p)  # noqa: E731
        self.meta = _load(j("scenario.json"), {})
        self.tz = _zone(self.meta.get("timezone") or "UTC")
        self.now = _ts(self.meta.get("now")) or int(dt.datetime.now(UTC).timestamp())
        site = self.meta.get("site") or {}
        self.siteid, self.guest_id = site.get("siteid", 1), site.get("guest_id", 1)
        self.site_ctx, self.sitename = site.get("site_context", 2), site.get("sitename", "Moodle")
        self.user = self.meta.get("user") or {"id": 2, "fullname": "Student"}
        self.hidden = set((self.meta.get("calendar") or {}).get("hidden_courses") or [])
        self.courses = _load(j("courses.json"), [])
        self.course, self.cms = {}, {}
        for c in self.courses:
            cid = c["id"]
            data = {"meta": c, "structure": _load(j("courses", str(cid), "structure.json"), {"sections": [], "cms": []}),
                    "grades": _load(j("courses", str(cid), "grades.json"), None),
                    "forums": _load(j("courses", str(cid), "forums.json"), {})}
            self.course[cid] = data
            where = {m: s for s in data["structure"]["sections"] for m in s["cms"]}
            for cm in data["structure"]["cms"]:
                sec = where.get(cm["id"])
                self.cms[cm["id"]] = dict(cm, course=cid, section_id=sec and sec["id"], section_number=sec and sec["number"])
        self.events = [self._event(e) for e in _load(j("calendar_events.json"), [])]
        self.authors = self._author_ids()

    def _event(self, e):
        cm = self.cms.get(e.get("cmid")) if e.get("cmid") else None
        return dict(e, timestart=_ts(e["timestart"]), timeduration=e.get("timeduration", 0),
                    modulename=cm and cm["module"], cm=cm)

    def _author_ids(self):
        names = sorted({d.get("author") for c in self.course.values() for ds in c["forums"].values() for d in ds}
                       | {p.get("author") for c in self.course.values() for ds in c["forums"].values()
                          for d in ds for p in d["posts"]} - {None})
        ids = {n: 1200 + i for i, n in enumerate(names)}
        ids[self.user["fullname"]] = self.user["id"]
        return ids

    def local(self, ts):
        return dt.datetime.fromtimestamp(ts, UTC).astimezone(self.tz)

    def userdate(self, ts):
        """strftimedaydatetime：Friday, 9 October 2026, 11:59 PM。"""
        d = self.local(ts)
        return f"{DAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]} {d.year}, {_hm(d)}"

    def enrolled(self):
        return [c["id"] for c in self.courses]

    def discussion(self, did):
        for cid, data in self.course.items():
            for cmid, ds in data["forums"].items():
                for d in ds:
                    if d["id"] == did:
                        return cid, int(cmid), d
        return None, None, None

    def cm_events(self, cmid, kind):
        return next((e["timestart"] for e in self.events if e.get("cmid") == cmid and e["eventtype"] == kind), None)


# ---------------------------------------------------------------- 请求处理
class _Handler(BaseHTTPRequestHandler):
    server_version = "MockMoodle/1"

    def log_message(self, fmt, *args):
        if os.environ.get("STC_MOCK_VERBOSE"):
            sys.stderr.write("mockmoodle: " + fmt % args + "\n")

    @property
    def mock(self):
        return self.server.mock

    @property
    def sc(self):
        return self.server.mock.scenario

    # ---- 收发
    def _send(self, status, body=b"", ctype="text/html; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.replace(BASE_MARK, self.mock.base_url).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.mock._log(self.command, self._path, self._query, status, self._matched, self._methods)

    def _redirect(self, location, headers=None):
        h = {"Location": location.replace(BASE_MARK, self.mock.base_url), "X-Redirect-By": "Moodle"}
        h.update(headers or {})
        return self._send(303, f'<html><body>This page should automatically redirect. <a href="{esc(h["Location"])}">Continue</a></body></html>', headers=h)

    def _json(self, obj):
        text = php_json(obj).replace(BASE_MARK, self.mock.base_url.replace("/", "\\/"))
        return self._send(200, text.encode("utf-8"), "application/json; charset=utf-8")

    def _q(self, key, default=None):
        return next((v for k, v in self._query if k == key), default)

    def _qint(self, key):
        try:
            return int(self._q(key))
        except (TypeError, ValueError):
            return None

    def _parse(self):
        parts = urlsplit(self.path)
        self._path, self._query = parts.path, parse_qsl(parts.query, keep_blank_values=True)
        self._target = self._path + ("?" + parts.query if parts.query else "")
        self._matched, self._methods = True, None

    def _logged_in(self):
        m = self.mock
        return f"{m.cookie_name}={m.session_cookie}" in (self.headers.get("Cookie") or "")

    def _refuse(self):
        self._matched = False
        return self._send(405, "<html><body>mockmoodle is read-only</body></html>")

    def _fatal(self, status, code, module="moodle", message=None):
        """core_renderer::fatal_error 的错误页（没权限、找不到等）：HTTP 404，data-rel=fatalerror。"""
        msg = message or code
        body = (f'<div class="box py-3 errorbox alert alert-danger" data-rel="fatalerror"><p class="errormessage">{esc(msg)}</p>'
                f'<p class="errorcode"><a href="{DOCS}/{module}/{code}">More information about this error</a></p></div>')
        uid = self.sc.user["id"] if self._logged_in() else None
        return self._send(status, self._page("Error", "page-", "", body, uid=uid))

    # ---- 入口
    def do_GET(self):
        self._parse()
        forced = self.mock._forced(self._target)
        if forced:
            return self._send(forced, f"<html><body>forced {forced} by the test</body></html>")
        if self._write_get():
            return self._refuse()
        for rx, name in _GET_ROUTES:
            m = re.fullmatch(rx, self._path)
            if m:
                return getattr(self, "g_" + name)(*m.groups())
        self._matched = False
        return self._fatal(404, "invalidurl", message="Invalid URL")

    do_HEAD = do_GET

    def do_POST(self):
        self._parse()
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        forced = self.mock._forced(self._target)
        if forced:
            return self._send(forced, b"", "application/json; charset=utf-8")
        if self._path in ("/lib/ajax/service.php", "/lib/ajax/service-nologin.php"):
            return self._ajax(raw, nologin=self._path.endswith("nologin.php"))
        return self._refuse()

    def _other(self):
        self._parse()
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        return self._refuse()

    do_PUT = do_DELETE = do_PATCH = _other

    def _write_get(self):
        """会改东西的 GET：mock 一律 405（真站会照做，这里是为了抓出越界的请求）。"""
        if WRITE_PATHS.search(self._path):
            return True
        if self._path == "/mod/forum/view.php" and self._q("o") is not None:
            return True  # o= 会写排序偏好
        if self._path == "/grade/report/user/index.php" and self._q("userview") not in (None, "", "0"):
            return True  # userview 会写用户偏好
        return self._path == "/mod/assign/view.php" and self._q("action") not in (None, "", "view")

    # ---- 登录与权限
    def _require_login(self, cid=None, cm=None):
        """返回用户 id；不行就已经回了重定向，返回 None。"""
        sc, mode = self.sc, self.mock.logged_out
        if self._logged_in():
            uid = sc.user["id"]
        elif mode == "guest":
            uid = sc.guest_id  # 站点开了 autologinguests：失效会话被自动登录成访客
        else:
            self._redirect(IDP_URL + "?SAMLRequest=mock" if mode == "sso" else BASE_MARK + "/login/index.php")
            return None
        if cid is not None and (cid not in sc.course or uid == sc.guest_id):
            self._redirect(f"{BASE_MARK}/enrol/index.php?id={cid}")
            return None
        if cm is not None and cm.get("uservisible", True) is False:
            self._redirect(f"{BASE_MARK}/course/view.php?id={cid}")
            return None
        return uid

    def _cm_or_404(self, module=None):
        cmid = self._qint("id")
        if cmid is None:
            self._fatal(404, "missingparam", message="A required parameter (id) was missing")
            return None
        cm = self.sc.cms.get(cmid)
        if cm is None or (module and cm["module"] != module):
            self._fatal(404, "invalidcoursemodule", message="Invalid course module ID")
            return None
        return cm

    # ---- 页面外壳
    def _mcfg(self, uid, cid=None, cm=None):
        sc = self.sc
        sesskey = self.mock.sesskey if uid == sc.user["id"] else ("GuestSess0" if uid == sc.guest_id else "AnonSess00")
        cctx = 20000 + cid if cid else sc.site_ctx
        cfg = {"wwwroot": BASE_MARK, "apibase": BASE_MARK + "/r.php/api", "homeurl": {}, "sesskey": sesskey,
               "sessiontimeout": "28800", "sessiontimeoutwarning": "1200", "themerev": REV,
               "slasharguments": self.mock.slasharguments,
               "theme": "boost", "iconsystemmodule": "core/icon_system_fontawesome", "jsrev": REV, "admin": "admin",
               "svgicons": True, "usertimezone": sc.meta.get("usertimezone") or sc.meta.get("timezone"),
               "language": sc.meta.get("language") or "en", "courseId": cid or sc.siteid, "courseContextId": cctx,
               "contextid": 10000 + cm["id"] if cm else cctx, "contextInstanceId": cm["id"] if cm else (cid or 0),
               "langrev": REV, "templaterev": REV, "siteId": sc.siteid, "userId": uid or 0}
        if self.mock.release == "4.4":  # 4.4 及更早：M.cfg 没有 apibase 和 userId
            del cfg["apibase"], cfg["userId"]
        return cfg

    def _page(self, title, body_id, classes, content, uid, cid=None, cm=None):
        cfg = php_json(self._mcfg(uid, cid, cm)).replace(BASE_MARK, self.mock.base_url.replace("/", "\\/"))
        logged = uid == self.sc.user["id"]
        cls = (classes + " " if classes else "") + ("" if uid else "notloggedin ") + "dir-ltr lang-en yui-skin-sam"
        if logged:
            who = (f'<div class="usermenu"><span class="userbutton"><span class="usertext me-1">{esc(self.sc.user["fullname"])}</span></span>'
                   f'<a class="dropdown-item" href="{BASE_MARK}/login/logout.php?sesskey={self.mock.sesskey}">Log out</a></div>')
        elif uid:
            who = f'<div class="usermenu"><span class="login">You are currently using guest access (<a href="{BASE_MARK}/login/index.php">Log in</a>)</span></div>'
        else:
            who = f'<div class="usermenu"><span class="login">You are not logged in. (<a href="{BASE_MARK}/login/index.php">Log in</a>)</span></div>'
        return ("<!DOCTYPE html>\n<html dir=\"ltr\" lang=\"en\" xml:lang=\"en\">\n<head>\n"
                f"<title>{esc(title)} | {esc(self.sc.sitename)}</title>\n<script>\n//<![CDATA[\nvar M = {{}}; M.yui = {{}};\n"
                f"M.pageloadstarttime = new Date();\nM.cfg = {cfg};M.yui.loader = {{modules: {{}}}};\n//]]>\n</script>\n</head>\n"
                f'<body id="{body_id}" class="{cls}">\n<nav class="navbar">{who}</nav>\n'
                f'<div id="page"><div id="region-main"><span id="maincontent" tabindex="-1"></span>\n{content}\n</div></div>\n</body>\n</html>\n')

    def _course_classes(self, cid, cm=None, extra=""):
        fmt = self.sc.course[cid]["meta"].get("format", "topics")
        path = f"path-mod path-mod-{cm['module']}" if cm else "path-course path-course-view"
        ctx = f"context-{10000 + cm['id']} cmid-{cm['id']}" if cm else f"context-{20000 + cid}"
        return f"format-{fmt} {path} chrome pagelayout-incourse course-{cid} {ctx} category-1 {extra}".strip()

    # ---- 路由：首页、登录、仪表盘
    def g_front(self):
        uid = self.sc.user["id"] if self._logged_in() else (self.sc.guest_id if self.mock.logged_out == "guest" else None)
        return self._send(200, self._page(self.sc.sitename, "page-site-index", "pagelayout-frontpage course-1",
                                          f"<h2>{esc(self.sc.sitename)}</h2>", uid))

    def g_login(self):
        m = self.mock
        if m.logged_out == "sso":
            return self._redirect(IDP_URL + "?SAMLRequest=mock")
        m.logins += 1
        return self._redirect(BASE_MARK + "/my/", {"Set-Cookie": f"{m.cookie_name}={m.session_cookie}; path=/; HttpOnly"})

    def g_my(self, page=None):
        uid = self._require_login()
        if uid is None:
            return None
        body_id = "page-my-courses" if page == "courses.php" else "page-my-index"
        links = "".join(f'<li><a href="{BASE_MARK}/course/view.php?id={c["id"]}">{fmt_string(c["fullname"])}</a></li>'
                        for c in self.sc.courses) if uid == self.sc.user["id"] else ""
        return self._send(200, self._page("Dashboard", body_id, "limitedwidth path-my pagelayout-mydashboard course-1",
                                          f"<h2>Dashboard</h2><ul class=\"mycourses\">{links}</ul>", uid))

    def g_enrol(self):
        uid = self._require_login()
        if uid is None:
            return None
        cid = self._qint("id")
        return self._send(200, self._page("Enrolment options", "page-enrol-index", "path-enrol",
                                          f"<h2>Enrolment options</h2><p>You cannot enrol yourself in this course (id {cid}).</p>", uid))

    # ---- 课程页
    def g_course(self):
        cid = self._qint("id")
        if cid is None or cid not in self.sc.course:
            return self._fatal(404, "invalidcourseid", message="You are trying to use an invalid course ID")
        uid = self._require_login(cid)
        if uid is None:
            return None
        data = self.sc.course[cid]
        fmt = data["meta"].get("format", "topics")
        secs = "".join(self._course_section(cid, s) for s in data["structure"]["sections"])
        content = (f'<h1 class="h2">{fmt_string(data["meta"]["fullname"])}</h1>\n<div class="course-content">'
                   f'<ul class="{fmt}" data-for="course_sectionlist">{secs}</ul></div>')
        return self._send(200, self._page(data["meta"]["fullname"], f"page-course-view-{fmt}", self._course_classes(cid), content, uid, cid))

    def _course_section(self, cid, s):
        n, sid = s["number"], s["id"]
        title = fmt_string(s["name"]) if s.get("name") else self._default_title(cid, n)
        cms = "".join(self._course_cm(self.sc.cms[m]) for m in s["cms"])
        summary = f'<div class="summarytext"><div class="no-overflow">{s["summary"]}</div></div>' if s.get("summary") else ""
        return (f'\n<li id="section-{n}" class="section course-section main clearfix" data-sectionid="{n}" data-for="section" '
                f'data-id="{sid}" data-number="{n}"><div class="course-section-header d-flex" data-for="section_title" data-id="{sid}" '
                f'data-number="{n}"><h3 id="section-{n}-title" class="h4 sectionname course-content-item"><a href="{BASE_MARK}/course/section.php?id={sid}">'
                f'{title}</a></h3></div><div id="coursecontentcollapse{n}" class="content course-content-item-content">{summary}'
                f'<ul class="section m-0 p-0 img-text d-block" data-for="cmlist">{cms}</ul></div></li>')

    def _course_cm(self, cm):
        mod, cmid, name = cm["module"], cm["id"], fmt_string(cm["name"])
        head = f'\n<li class="activity activity-wrapper {mod} modtype_{mod}" id="module-{cmid}" data-for="cmitem" data-id="{cmid}">'
        if mod == "label":
            return (head + f'<div class="activity-item focus-control activityinline" data-activityname="{name}" data-region="activity-card">'
                    f'<div class="activity-altcontent d-flex"><div class="no-overflow"><div class="no-overflow">{cm.get("text", "")}</div></div></div></div></li>')
        restrict = ('<div class="description"><div data-region="availabilityinfo" class="availabilityinfo">Not available unless: '
                    'you complete an earlier activity</div></div>' if cm.get("hascmrestrictions") else "")
        link = (f'<a href="{BASE_MARK}/mod/{mod}/view.php?id={cmid}" class=" aalink stretched-link"><span class="instancename">{name} '
                f'<span class="accesshide "> {MODNAMES.get(mod, mod)}</span></span></a>' if cm.get("uservisible", True)
                else f'<span class="instancename">{name}</span>')
        return (head + f'<div class="activity-item focus-control" data-activityname="{name}" data-region="activity-card">'
                f'<div class="activityname">{link}</div>{restrict}</div></li>')

    def _default_title(self, cid, n):
        """没命名的节：第 0 节 General；weeks 格式是日期区间（本地化文字），其它格式 New section。"""
        if n == 0:
            return "General"
        meta = self.sc.course[cid]["meta"]
        if meta.get("format") != "weeks":
            return "New section"
        d1 = self.sc.local(_ts(meta["startdate"])).date() + dt.timedelta(days=7 * (n - 1))
        d2 = d1 + dt.timedelta(days=6)
        return f"{d1.day} {MONTHS[d1.month - 1]} - {d2.day} {MONTHS[d2.month - 1]}"

    # ---- 作业页
    def g_assign(self):
        cm = self._cm_or_404("assign")
        if cm is None:
            return None
        cid = cm["course"]
        uid = self._require_login(cid, cm)
        if uid is None:
            return None
        sc, a = self.sc, cm.get("assign") or {}
        dates = self._dates_block(cm, [("Opened:" if (a.get("allow_from") and _ts(a["allow_from"]) <= sc.now) else "Opens:",
                                        _ts(a.get("allow_from"))), ("Due:", sc.cm_events(cm["id"], "due"))])
        body = [f"<h2>{fmt_string(cm['name'])}</h2>", dates]
        if uid == sc.user["id"]:  # 访客看不到提交状态表
            body += [self._assign_actions(cm, a), self._assign_status(cm, a), self._assign_feedback(a)]
        return self._send(200, self._page(cm["name"], "page-mod-assign-view", self._course_classes(cid, cm), "\n".join(body), uid, cid, cm))

    def _dates_block(self, cm, pairs):
        rows = "".join(f"\n      <div><strong>{label}</strong> {self.sc.userdate(ts)}</div>" for label, ts in pairs if ts)
        intro = (cm.get("assign") or {}).get("intro") or ""
        desc = (f'\n  <div class="activity-description" id="intro"><div class="box py-3 generalbox boxaligncenter">{intro}</div></div>'
                if intro else "")
        return (f'<div class="activity-header" data-for="page-activity-header">\n  <div data-region="activity-information" '
                f'data-activityname="{fmt_string(cm["name"])}" class="activity-information">\n    <div data-region="activity-dates" '
                f'class="activity-dates">{rows}\n    </div>\n  </div>{desc}\n</div>')

    def _button(self, cmid, action, label, n):
        return (f'<div class="col-xs-6 me-3"><div class="singlebutton"><form method="get" action="{BASE_MARK}/mod/assign/view.php">'
                f'<input type="hidden" name="id" value="{cmid}"><input type="hidden" name="action" value="{action}">'
                f'<button type="submit" class="btn btn-secondary" id="single_button68f1c2a3b4d5e{n}">{label}</button></form></div></div>')

    def _assign_actions(self, cm, a):
        status, cmid = a.get("status", "new"), cm["id"]
        if a.get("submissionsenabled", True) is False or a.get("graded"):
            buttons = []
        elif status == "new" and a.get("timelimit"):  # 限时作业还没开始：是链接，不是表单
            buttons = [f'<div class="col-xs-6 me-3"><a class="btn btn-primary" href="{BASE_MARK}/mod/assign/view.php?id={cmid}'
                       f'&amp;action=editsubmission&amp;begin=1">Begin assignment</a></div>']
        elif status in ("new", "reopened"):
            buttons = [self._button(cmid, "editsubmission", "Add submission", 1)]
        else:
            buttons = [self._button(cmid, "editsubmission", "Edit submission", 1),
                       self._button(cmid, "removesubmissionconfirm", "Remove submission", 2)]
            if status == "draft":
                buttons.append(self._button(cmid, "submit", "Submit assignment", 3))
        return f'<div class="container-fluid mb-4"><div class="row">{"".join(buttons)}</div></div>' if buttons else ""

    def _assign_status(self, cm, a):
        sc = self.sc
        status, enabled = a.get("status", "new"), a.get("submissionsenabled", True)
        texts = {"submitted": ("submissionstatussubmitted", "Submitted for grading"),
                 "draft": ("submissionstatusdraft", "Draft (not submitted)"),
                 "reopened": ("submissionstatusreopened", "Reopened")}
        cls, text = texts.get(status, ("", "No submissions have been made yet" if enabled
                                       else "This assignment does not require you to submit anything online"))
        rows = [("Submission status", cls, text),
                ("Grading status", "submissiongraded" if a.get("graded") else "submissionnotgraded",
                 "Graded" if a.get("graded") else "Not graded")]
        ext = _ts(a.get("extension"))
        if ext:
            rows.append(("Extension due date", "", sc.userdate(ext)))
        rows.append(self._time_remaining(cm, a, ext))
        if status != "new" or a.get("last_modified") or a.get("submitted_at"):
            last = _ts(a.get("last_modified") or a.get("submitted_at"))
            rows.append(("Last modified", "", sc.userdate(last) if last else "-"))
        if enabled:
            rows.append(("File submissions", "", "-" if status == "new" else '<div class="fileuploadsubmission">submission.pdf</div>'))
        rows = [r for r in rows if r]
        trs = "".join(f'\n<tr class="{"lastrow" if i == len(rows) - 1 else ""}">\n<th class="cell c0" style="" scope="row">{t}</th>\n'
                      f'<td class="{(c + " ") if c else ""}cell c1 lastcol" style="">{v}</td>\n</tr>' for i, (t, c, v) in enumerate(rows))
        return (f'<div class="submissionstatustable"><h3>Submission status</h3><div class="box py-3 boxaligncenter submissionsummarytable">'
                f'<div class="table-responsive"><table class="generaltable table-bordered">\n<caption class="accesshide">Submission status</caption>'
                f'\n<tbody>{trs}\n</tbody>\n</table>\n</div></div></div>')

    def _time_remaining(self, cm, a, ext):
        """剩余时间行：交了是 early/late；没交且过了 max(截止, 延期) 是 overdue；否则 timeremaining。"""
        sc = self.sc
        due = sc.cm_events(cm["id"], "due")
        if not due:
            return None
        eff = max(due, ext or 0)
        if a.get("status") == "submitted":
            at = _ts(a.get("submitted_at")) or eff
            early = at <= eff
            return ("Time remaining", "earlysubmission" if early else "latesubmission",
                    f"Assignment was submitted {_span(eff - at)} {'early' if early else 'late'}")
        if sc.now > eff:
            text = f"Assignment is overdue by: {_span(sc.now - eff)}" if a.get("submissionsenabled", True) else "Due date has passed"
            return ("Time remaining", "overdue", text)
        return ("Time remaining", "timeremaining", f"{_span(eff - sc.now)} remaining")

    def _assign_feedback(self, a):
        if not a.get("graded"):
            return ""
        return ('<div class="feedback"><h3>Feedback</h3><div class="box py-3 boxaligncenter feedbacktable"><table class="generaltable">'
                f'<tbody><tr class=""><th class="cell c0" scope="row">Grade</th><td class="cell c1 lastcol">{esc(a.get("grade", "-"))}</td></tr>'
                '</tbody></table></div></div>')

    # ---- 测验页
    def g_quiz(self):
        cm = self._cm_or_404("quiz")
        if cm is None:
            return None
        cid = cm["course"]
        uid = self._require_login(cid, cm)
        if uid is None:
            return None
        sc, q = self.sc, cm.get("quiz") or {}
        opens, closes = sc.cm_events(cm["id"], "open"), sc.cm_events(cm["id"], "close")
        body = [f"<h2>{fmt_string(cm['name'])}</h2>",
                self._dates_block(cm, [("Opened:" if opens and opens <= sc.now else "Opens:", opens),
                                       ("Closed:" if closes and closes <= sc.now else "Closes:", closes)])]
        attempts = q.get("attempts") or []
        allowed = q.get("attempts_allowed", 0)
        reason = self._quiz_blocked(opens, closes, allowed, attempts)
        if reason is None:
            label = "Re-attempt quiz" if attempts else "Attempt quiz"
            body.append(f'<div class="container-fluid tertiary-navigation"><div class="row"><div class="singlebutton quizstartbuttondiv">'
                        f'<form method="post" action="{BASE_MARK}/mod/quiz/startattempt.php"><input type="hidden" name="cmid" value="{cm["id"]}">'
                        f'<input type="hidden" name="sesskey" value="{self.mock.sesskey}"><button type="submit" class="btn btn-primary" '
                        f'id="single_button68f1c2a3b4d5e9">{label}</button></form></div></div></div>')
        info = (f'<p class="text-start">Attempts allowed: {allowed}</p>' if allowed else "") + \
               f'<p class="text-start">Grading method: {esc(q.get("grading", "Highest grade"))}</p>'
        body.append(f'<div class="box py-3 quizinfo">{info}</div>')
        if attempts:
            best = max(attempts, key=lambda t: float(t["grade"]))
            body.append(f'<div id="feedback" class="box py-3 generalbox"><h3>{esc(q.get("grading", "Highest grade"))}: '
                        f'{best["grade"]} / {q.get("grademax", "10.00")}.</h3></div>')
            body.append(self._quiz_attempts(cm, q, attempts))
        why = "" if reason is None else f'<p class="text-start">{reason}</p>'
        body.append(f'<div class="box py-3 quizattempt">{why}</div>')
        return self._send(200, self._page(cm["name"], "page-mod-quiz-view", self._course_classes(cid, cm, "limitedwidth"),
                                          "\n".join(body), uid, cid, cm))

    def _quiz_blocked(self, opens, closes, allowed, attempts):
        now = self.sc.now
        if opens and now < opens:
            return f"This quiz will not be available until {self.sc.userdate(opens)}"
        if closes and now >= closes:
            return f"This quiz closed on {self.sc.userdate(closes)}"
        if allowed and len(attempts) >= allowed:
            return "No more attempts are allowed"
        return None

    def _quiz_attempts(self, cm, q, attempts):
        cards = []
        for n, t in sorted(enumerate(attempts, 1), reverse=True):  # 最新在前
            rows = [("Status", "Finished"), ("Started", self.sc.userdate(_ts(t["started"]))),
                    ("Completed", self.sc.userdate(_ts(t["finished"]))),
                    ("Duration", _span(_ts(t["finished"]) - _ts(t["started"]))),
                    ("Grade", f'<b>{t["grade"]}</b> out of {q.get("grademax", "10.00")} (<b>{t["percent"]}</b>%)')]
            trs = "".join(f'\n        <tr><th class="cell" scope="row">{k}</th><td class="cell">{v}</td></tr>' for k, v in rows)
            if q.get("review") == "popup":
                review = (f'<div class="singlebutton"><form method="post" action="{BASE_MARK}/mod/quiz/review.php">'
                          f'<input type="hidden" name="attempt" value="{t["id"]}"><input type="hidden" name="cmid" value="{cm["id"]}">'
                          f'<input type="hidden" name="sesskey" value="{self.mock.sesskey}"><button type="submit" class="btn btn-secondary">'
                          f'Review</button></form></div>')
            else:
                review = (f'<a title="Review your responses to this attempt" href="{BASE_MARK}/mod/quiz/review.php?'
                          f'attempt={t["id"]}&amp;cmid={cm["id"]}">Review</a>')
            cards.append(f'\n<li class="col ps-0 pe-2 mb-2">\n    <div class="card h-100">\n        <div class="card-header py-2 border-bottom-0">'
                         f'\n            <h4 class="card-title my-0">Attempt {n}</h4>\n        </div>\n<table class="generaltable generalbox '
                         f'quizreviewsummary mb-0">\n    <caption class="sr-only">Attempt {n} summary</caption>\n    <tbody>{trs}\n    </tbody>'
                         f'\n</table>\n        <div class="card-body py-2">\n            <div>{review}</div>\n        </div>\n    </div>\n</li>')
        return f'<h3>Your attempts</h3>\n<ul class="list-unstyled row row-cols-1 row-cols-md-2 g-0">{"".join(cards)}\n</ul>'

    # ---- 成绩页
    def g_grades(self):
        cid = self._qint("id")
        if cid is None or cid not in self.sc.course:
            return self._fatal(404, "invalidcourseid", message="You are trying to use an invalid course ID")
        uid = self._require_login(cid)
        if uid is None:
            return None
        if self._qint("userid") not in (None, uid):
            return self._fatal(404, "nopermissiontoviewgrades", message="Cannot view grades.")
        g = self.sc.course[cid]["grades"]
        if g is None or cid in self.mock.regrading:  # 正在重算：200，但没有成绩表
            content = ('<h2>Recalculating grades</h2><div class="singlebutton"><form method="get" action="">'
                       '<button type="submit" class="btn btn-primary">Continue</button></form></div>')
        else:
            content = self._grade_table(cid, g, uid)
        return self._send(200, self._page("User report", "page-grade-report-user-index", "path-grade path-grade-report "
                                          f"path-grade-report-user course-{cid} context-{20000 + cid}", content, uid, cid))

    def _grade_table(self, cid, g, uid):
        cols = ["itemname"] + (["weight"] if g.get("showweight", True) else []) + \
               ["grade", "range", "percentage", "feedback", "contributiontocoursetotal"]
        heads = {"itemname": "Grade item", "weight": "Calculated weight", "grade": "Grade", "range": "Range",
                 "percentage": "Percentage", "feedback": "Feedback", "contributiontocoursetotal": "Contribution to course total"}
        span = ' colspan="2"'
        th = "".join(f'\n<th class="header column-{c} header c{i}{" lastcol" if i == len(cols) - 1 else ""}" id="{c}{uid}" style=""'
                     f'{span if c == "itemname" else ""} scope="col">{heads[c]}</th>' for i, c in enumerate(cols))
        cat = g["category"]
        rows = [f'<tr class="" data-hidden="false">\n<th class="level1 d1 b1b b1t category column-itemname cell c0 lastcol" style="" '
                f'colspan="{len(cols) + 1}" id="cat_{cat["id"]}_{uid}" scope="row"><div class="d-flex category-content">\n    '
                f'<a aria-expanded="true" role="button" data-categoryid={cat["id"]} data-target=".cat_{cat["id"]}[data-hidden=\'false\']" '
                f'class="btn btn-icon me-1 toggle-category" href="#"></a>\n    <span>{fmt_string(cat["name"])}</span>\n</div></th>\n</tr>',
                f'<tr class="cat_{cat["id"]} spacer" data-hidden="false">\n<td class="level1 d1 b1t b2b b1l cell c0 lastcol" style="" '
                f'rowspan="{len(g["items"]) + 1}"></td>\n</tr>']
        items = g["items"]
        for n, it in enumerate(items):
            last = " lastrow" if n == len(items) - 1 else ""
            if it.get("hidden"):  # 隐藏项：没有单元格的空行
                rows.append(f'<tr class="cat_{cat["id"]}{last}" data-hidden="false"></tr>')
                continue
            rows.append(self._grade_row(it, cols, cat["id"], uid, last))
        return (f'<div class="user-report-container" id="user-report-{uid}"><div class="table-responsive">'
                f'<table class="generaltable boxaligncenter user-grade">\n<thead>\n<tr>{th}\n</tr>\n</thead>\n<tbody>'
                + "\n".join(rows) + '\n</tbody>\n</table>\n</div></div>')

    def _grade_row(self, it, cols, catid, uid, last):
        kind = it.get("type", "item")
        cm = self.sc.cms.get(it.get("cmid")) if it.get("cmid") else None
        rid = f"row_{it['id']}_{uid}"
        if cm:
            mod, name = cm["module"], fmt_string(cm["name"])
            icon = f'<img class="icon itemicon" src="{BASE_MARK}/theme/image.php/boost/{mod}/{REV}/monologo" alt="{MODNAMES.get(mod, mod)}" />'
            label = MODNAMES.get(mod, mod)
            head = (f'<a title="{label} activity {name}" class="gradeitemheader " href="{BASE_MARK}/mod/{mod}/view.php?id={cm["id"]}">'
                    f'{name}</a>')
        else:
            name = fmt_string(it.get("name", ""))
            label = "Aggregation" if kind == "courseitem" else "Manual item"
            icon = f'<i class="icon fa fa-{"calculator" if kind == "courseitem" else "square-o"} fa-fw icon itemicon" title="{label}" role="img"></i>'
            head = f'<span class="gradeitemheader " title="{name}" tabindex="0">{name}</span>'
        level = "level1 d1 baggt b2b" if kind == "courseitem" else "level2 item b1b"
        cells = [f'<th class="{level} column-itemname cell c0" style="" colspan="1" id="{rid}" scope="row"><div class="{kind} d-flex '
                 f'align-items-center"><div class="me-1">{icon}</div><div><span class="d-block text-uppercase small " title="{label}">'
                 f'{label}</span><div class="rowtitle">{head}</div></div></div></th>']
        for i, c in enumerate(cols[1:], 1):
            val = {"feedback": "&nbsp;"}.get(c) or str(it.get(c.replace("contributiontocoursetotal", "contribution"), "-"))
            val = val.replace("–", "&ndash;")
            kindcls = "feedbacktext" if c == "feedback" else "itemcenter "
            cells.append(f'<td class="{level} {kindcls} column-{c} cell c{i}{" lastcol" if i == len(cols) - 1 else ""}" '
                         f'headers="cat_{catid}_{uid} {rid} {c}{uid}" style="">{val}</td>')
        return f'<tr class="cat_{catid}{last}" data-hidden="false">\n' + "\n".join(cells) + "\n</tr>"

    # ---- 论坛
    def g_forum(self):
        cm = self._cm_or_404("forum")
        if cm is None:
            return None
        cid = cm["course"]
        uid = self._require_login(cid, cm)
        if uid is None:
            return None
        kind = (cm.get("forum") or {}).get("type", "general")
        ds = self.sc.course[cid]["forums"].get(str(cm["id"])) or []
        if (self._qint("p") or 0) > 0:
            ds = []
        name = fmt_string(cm["name"])
        inner = self._discussion_table(ds) if ds else ('<div class="forumnodiscuss alert alert-info">'
                                                       + ("(No announcements have been posted yet.)" if kind == "news"
                                                          else "(There are no discussion topics yet in this forum)") + '</div>')
        content = (f"<h2>{name}</h2>\n<div id=\"discussion-list-68f1a2b3c4d5e1\" data-contextid=\"{10000 + cm['id']}\" "
                   f"data-cmid=\"{cm['id']}\" data-name=\"{name}\" data-group=\"\" data-grading-component=\"\" "
                   f"data-grading-component-subtype=\"\" data-gradable-itemtype=\"forum\" data-initialuserid=\"{uid}\">\n"
                   f"  <div class=\"py-3\"></div>\n{inner}\n</div>")
        return self._send(200, self._page(cm["name"], "page-mod-forum-view",
                                          self._course_classes(cid, cm, f"forumtype-{kind}"), content, uid, cid, cm))

    def _discussion_table(self, ds):
        def last_post(d):
            return max(d["posts"], key=lambda p: _ts(p["created"]))
        ordered = sorted(ds, key=lambda d: (not d.get("pinned"), -_ts(last_post(d)["created"])))
        rows = []
        for d in ordered:
            first, last = d["posts"][0], last_post(d)
            cls = "discussion" + (" pinned" if d.get("pinned") else "") + " subscribed"
            subject = fmt_string(d["subject"])
            rows.append(
                f'\n          <tr class="{cls}" data-region="discussion-list-item" data-discussionid="{d["id"]}" data-forumid="">'
                f'\n            <td class="p-0 text-center align-middle icon-no-margin" style="width: 1px;"></td>'
                f'\n            <th scope="row" class="topic p-0 align-middle"><div class="p-3 ps-0"><div class="d-flex">'
                f'<a class="w-100 h-100 d-block" href="{BASE_MARK}/mod/forum/discuss.php?d={d["id"]}" title="{subject}" '
                f'aria-label="{subject}">{subject[:100]}</a></div></div></th>'
                f'\n            <td class="author align-middle fit-content limit-width px-3"><div class="d-flex"><div class="author-info '
                f'align-middle"><div class="mb-1 line-height-3 text-truncate">{esc(d.get("author", ""))}</div><div class="line-height-3">'
                f'<time id="time-created-{d["id"]}" class="" datetime="" data-timestamp="{_ts(first["created"])}" '
                f'data-datetimeformat="%Y-%m-%dT%H:%M%z">{self._abbr(_ts(first["created"]))}</time></div></div></div></td>'
                f'\n            <td class="text-start align-middle fit-content limit-width px-3"><div class="d-flex"><div class="author-info '
                f'align-middle"><div class="mb-1 line-height-3 text-truncate">{esc(last.get("author") or d.get("author", ""))}</div>'
                f'<div class="line-height-3"><a href="{BASE_MARK}/mod/forum/discuss.php?d={d["id"]}&parent={last["id"]}">'
                f'<time id="time-modified-{d["id"]}" class="" datetime="" data-timestamp="{_ts(last["created"])}" '
                f'data-datetimeformat="%Y-%m-%dT%H:%M%z">{self._abbr(_ts(last["created"]))}</time></a></div></div></div></td>'
                f'\n            <td class="p-0 text-center align-middle fit-content px-2"><span>{len(d["posts"]) - 1}</span></td>'
                f'\n            <td class="p-0 align-middle fit-content" data-container="discussion-summary-actions"></td>\n          </tr>')
        return ('  <div class="position-relative">\n    <div class="no-overflow">\n      <table class="table discussion-list generaltable">'
                f'\n        <caption class="sr-only">Showing {len(ds)} of {len(ds)} discussions</caption>'
                '\n        <thead><tr><th scope="col"><span class="accesshide">Status</span></th><th scope="col" class="ps-0">Discussion</th>'
                '<th scope="col" class="author px-3">Started by</th><th scope="col" class="lastpost px-3">Last post</th>'
                '<th scope="col" class="text-center px-2">Replies</th><th scope="col"></th></tr></thead>'
                f'\n        <tbody>{"".join(rows)}\n        </tbody>\n      </table>\n    </div>\n  </div>')

    def _abbr(self, ts):
        d = self.sc.local(ts)
        return f"{d.day:02d} {MONTHS[d.month - 1][:3]} {d.year}"

    def g_discuss(self):
        did = self._qint("d")
        cid, cmid, d = self.sc.discussion(did) if did else (None, None, None)
        if d is None:
            return self._fatal(404, "invalidrecord", message="Can't find data record in database table forum_discussions.")
        cm = self.sc.cms[cmid]
        uid = self._require_login(cid, cm)
        if uid is None:
            return None
        posts = "".join(f'<article id="p{p["id"]}" data-post-id="{p["id"]}" data-region="post" class="forum-post-container">'
                        f'<div class="post-content-container">{p["message"]}</div></article>' for p in d["posts"])
        return self._send(200, self._page(d["subject"], "page-mod-forum-discuss", self._course_classes(cid, cm),
                                          f"<h3 class=\"discussionname\">{fmt_string(d['subject'])}</h3>{posts}", uid, cid, cm))

    # ---- 课件：folder、resource、pluginfile
    def g_folder(self):
        cm = self._cm_or_404("folder")
        if cm is None:
            return None
        cid = cm["course"]
        uid = self._require_login(cid, cm)
        if uid is None:
            return None
        lis = "".join(f'<li><span class="fp-filename-icon"><a href="{esc(self._file_url(cm, f["filename"], forcedownload=True))}">'
                      f'<span class="fp-icon"><img class="icon" alt="" src="{BASE_MARK}/theme/image.php/boost/core/{REV}/f/pdf"></span>'
                      f'<span class="fp-filename">{esc(f["filename"])}</span></a></span></li>'
                      for f in (cm.get("folder") or {}).get("files", []))
        content = (f"<h2>{fmt_string(cm['name'])}</h2>\n<div class=\"box generalbox foldertree py-3\"><div id=\"folder_tree0\" "
                   f"class=\"filemanager\"><ul><li><div class=\"fp-filename-icon\"><span class=\"fp-filename\">{fmt_string(cm['name'])}"
                   f"</span></div><ul>{lis}</ul></li></ul></div></div>")
        return self._send(200, self._page(cm["name"], "page-mod-folder-view", self._course_classes(cid, cm), content, uid, cid, cm))

    def _file_url(self, cm, filename, forcedownload=False):
        """pluginfile 地址；站点关了 slasharguments 时文件路径放在 ?file= 里（moodle_url::make_file_url）。"""
        area = "mod_folder/content/0" if cm["module"] == "folder" else "mod_resource/content/1"
        path = f"/{10000 + cm['id']}/{area}/{quote(filename, safe='')}"
        if not self.mock.slasharguments:
            url = f"{BASE_MARK}/pluginfile.php?file={quote(unquote(path), safe='')}"
            return url + ("&forcedownload=1" if forcedownload else "")
        return f"{BASE_MARK}/pluginfile.php{path}" + ("?forcedownload=1" if forcedownload else "")

    def g_pluginfile_q(self):
        """slasharguments 关掉时的 /pluginfile.php?file=/ctx/组件/…。"""
        m = re.fullmatch(r"/(\d+)/(mod_resource|mod_folder|mod_forum)/(.+)", self._q("file") or "")
        if not m:
            return self._send(404, "<html><body>Sorry, the requested file could not be found</body></html>")
        return self.g_pluginfile(m.group(1), m.group(2), quote(m.group(3)))

    def g_resource(self):
        cm = self._cm_or_404("resource")
        if cm is None:
            return None
        cid = cm["course"]
        uid = self._require_login(cid, cm)
        if uid is None:
            return None
        url = self._file_url(cm, cm["resource"]["filename"])
        if self._q("redirect") == "1":
            return self._redirect(url)
        content = (f"<h2>{fmt_string(cm['name'])}</h2>\n<div class=\"resourceworkaround\">Click <a href=\"{url}\" "
                   f"onclick=\"this.target='_blank';\">{esc(cm['resource']['filename'])}</a> link to view the file.</div>")
        return self._send(200, self._page(cm["name"], "page-mod-resource-view", self._course_classes(cid, cm), content, uid, cid, cm))

    def g_pluginfile(self, ctx, component, rest):
        cm = self.sc.cms.get(int(ctx) - 10000)
        if cm is None:
            return self._send(404, "<html><body>Sorry, the requested file could not be found</body></html>")
        if self._require_login(cm["course"], cm) is None:
            return None
        body, ctype, name = self._file_body(cm, component, rest)
        if body is None:
            return self._send(404, "<html><body>Sorry, the requested file could not be found</body></html>")
        disp = "attachment" if self._q("forcedownload") == "1" else "inline"
        return self._send(200, body, ctype, {"Content-Disposition": f"{disp}; filename=\"{quote(name)}\"; filename*=UTF-8''{quote(name)}",
                                             "Cache-Control": "private, max-age=10, no-transform"})

    def _file_body(self, cm, component, rest):
        parts = [unquote(p) for p in rest.split("/")]
        if component == "mod_forum" and len(parts) == 3 and parts[0] == "post":
            return PIXEL, "image/png", parts[-1]
        if component == "mod_resource" and cm["module"] == "resource" and parts[-1] == cm["resource"]["filename"]:
            f = cm["resource"]
        elif component == "mod_folder" and cm["module"] == "folder":
            f = next((x for x in cm["folder"]["files"] if x["filename"] == parts[-1]), None)
        else:
            f = None
        if f is None:
            return None, None, None
        return (f.get("body") or "").encode("utf-8"), f.get("mimetype") or "application/octet-stream", f["filename"]

    def g_module(self, mod):
        """别的活动（page、url、lti、label…）：只给一个简单页面。"""
        cm = self._cm_or_404(mod)
        if cm is None:
            return None
        cid = cm["course"]
        uid = self._require_login(cid, cm)
        if uid is None:
            return None
        extra = "<p>Launching the external tool…</p>" if mod == "lti" else ""
        return self._send(200, self._page(cm["name"], f"page-mod-{mod}-view", self._course_classes(cid, cm),
                                          f"<h2>{fmt_string(cm['name'])}</h2>{extra}", uid, cid, cm))

    def g_nologin_get(self):
        """service-nologin.php 也接受 GET ?args=<JSON>。"""
        return self._ajax((self._q("args") or "").encode("utf-8"), nologin=True)

    def g_ajax_get(self):
        return self._ajax(b"", nologin=False)

    # ---- ajax
    def _ajax(self, raw, nologin):
        mock = self.mock
        try:
            reqs = json.loads(raw.decode("utf-8"))
            if not isinstance(reqs, list):
                raise ValueError
        except ValueError:
            return self._json(self._fatal_obj("codingerror", "Coding error detected, it must be fixed by a programmer: Invalid json in request: Syntax error"))
        if not all(isinstance(r, dict) for r in reqs):
            return self._json(self._fatal_obj("codingerror", "Coding error detected, it must be fixed by a programmer: Invalid request"))
        self._methods = [str(r.get("methodname")) for r in reqs]
        if any(self._is_write(m) for m in self._methods):
            return self._refuse()
        out = {}
        for r in reqs:
            name = r.get("methodname")
            try:
                index = int(r.get("index") or 0)  # PARAM_INT：缺了就是 0
            except (TypeError, ValueError):
                index = 0
            if name not in AJAX_READ | PUBLIC | KNOWN_OTHER:
                return self._json(self._fatal_obj("invalidrecord", ERRORS["invalidrecord"][1]))
            try:
                data = self._call(name, r.get("args") or {}, nologin)
                out[index] = {"error": False, "data": data}
            except AjaxError as e:
                out[index] = self._err_obj(e.code, e.message)
                if not nologin:
                    break
        keys = list(out)
        return self._json([out[k] for k in keys] if keys == list(range(len(keys))) else {str(k): v for k, v in out.items()})

    @staticmethod
    def _is_write(name):
        parts = name.split("_")
        return name in WRITE_NAMES or (len(parts) > 2 and parts[2] in WRITE_VERBS)

    def _call(self, name, args, nologin):
        forced = self.mock._ajax_forced(name)
        if forced:
            raise AjaxError(forced)
        if name in KNOWN_OTHER:
            raise AjaxError("servicenotavailable")
        if name not in PUBLIC:  # 要登录：先看登没登录，再看 sesskey
            if nologin or not self._logged_in():
                raise AjaxError("servicerequireslogin")
            key = self._q("sesskey")
            if not key:
                raise AjaxError("missingparam")
            if key != self.mock.sesskey:
                raise AjaxError("invalidsesskey")
        return getattr(self, "a_" + name)(args)

    def _err_obj(self, code, message=None):
        module, text = ERRORS.get(code, ("moodle", code))
        return {"error": True, "exception": {"message": message or text, "errorcode": code, "link": BASE_MARK + "/",
                                              "moreinfourl": f"{DOCS}/{module}/{code}"}}

    @staticmethod
    def _fatal_obj(code, message):
        return {"error": message, "errorcode": code, "stacktrace": None, "debuginfo": None, "reproductionlink": None}

    # ---- ajax 函数
    def a_tool_mobile_get_public_config(self, args):
        sc = self.sc
        cfg = {"wwwroot": BASE_MARK, "httpswwwroot": BASE_MARK, "sitename": sc.sitename, "guestlogin": 0,
               "rememberusername": 2, "authloginviaemail": 0, "registerauth": "", "forgottenpasswordurl": "",
               "authinstructions": "", "authnoneenabled": 0, "enablewebservices": 1, "enablemobilewebservice": 1,
               "maintenanceenabled": 0, "maintenancemessage": "", "typeoflogin": 2,
               "launchurl": BASE_MARK + "/admin/tool/mobile/launch.php", "mobilecssurl": "", "tool_mobile_disabledfeatures": ""}
        if self.mock.logged_out == "sso":
            cfg["identityproviders"] = [{"name": "Example SSO", "iconurl": "", "url": IDP_URL + "?SAMLRequest=mock"}]
        cfg.update({"country": "AU", "agedigitalconsentverification": False, "supportpage": "", "supportavailability": 1,
                    "autolang": 1, "lang": "en", "langmenu": 1, "langlist": "", "locale": "", "tool_mobile_minimumversion": "",
                    "tool_mobile_iosappid": "633359593", "tool_mobile_androidappid": "com.moodle.moodlemobile",
                    "tool_mobile_setuplink": "https://download.moodle.org/mobile", "tool_mobile_qrcodetype": 2, "warnings": [],
                    "showloginform": 0 if self.mock.logged_out == "sso" else 1})
        return cfg

    def _course_summary(self, c):
        return {"id": c["id"], "fullname": fmt_string(c["fullname"]), "shortname": fmt_string(c["shortname"]),
                "idnumber": c.get("idnumber", ""), "summary": c.get("summary", ""), "summaryformat": 1 if c.get("summary") else 0,
                "startdate": _ts(c["startdate"]) or 0, "enddate": _ts(c.get("enddate")) or 0, "visible": True,
                "showactivitydates": True, "showcompletionconditions": True, "pdfexportfont": "",
                "fullnamedisplay": fmt_string(c["fullname"]), "viewurl": f"{BASE_MARK}/course/view.php?id={c['id']}",
                "courseimage": COURSE_IMAGE, "progress": 0, "hasprogress": False, "isfavourite": bool(c.get("isfavourite")),
                "hidden": False, "showshortname": False, "coursecategory": fmt_string(c.get("category", ""))}

    def _classify(self, c):
        now, start, end = self.sc.now, _ts(c["startdate"]) or 0, _ts(c.get("enddate")) or 0
        if end and end < now:
            return "past"
        return "future" if start and start > now else "inprogress"

    def a_core_course_get_enrolled_courses_by_timeline_classification(self, args):
        kind = args.get("classification")
        valid = ("allincludinghidden", "all", "past", "inprogress", "future", "favourites", "hidden", "search", "customfield")
        if kind not in valid:
            raise AjaxError("invalidparameter", "Invalid parameter value detected (Invalid classification)")
        courses, hidden = self.sc.courses, self.mock.dashboard_hidden
        shown = [c for c in courses if c["id"] not in hidden]  # 除 allincludinghidden / hidden / search 外都在 SQL 层排除隐藏课
        if kind in ("past", "inprogress", "future"):
            keep = [c for c in shown if self._classify(c) == kind]
        elif kind == "favourites":
            keep = [c for c in shown if c.get("isfavourite")]
        elif kind == "hidden":
            keep = [c for c in courses if c["id"] in hidden]
        elif kind == "customfield":
            keep = []
        elif kind == "all":
            keep = list(shown)
        elif kind == "search":
            v = (args.get("searchvalue") or "").lower()
            keep = [c for c in courses if v in c["fullname"].lower() or v in c["shortname"].lower()]
        else:
            keep = list(courses)
        sort = (args.get("sort") or "").strip().lower()
        if sort in ("fullname", "shortname"):
            keep.sort(key=lambda c: c[sort].lower())
        offset, limit = int(args.get("offset") or 0), int(args.get("limit") or 0)
        keep = [c for c in keep if courses.index(c) >= offset]
        if limit:
            keep = keep[:limit]
        out = [self._course_summary(c) for c in keep]
        if kind in ("allincludinghidden", "hidden"):
            for s in out:
                s["hidden"] = s["id"] in hidden
        return {"courses": out, "nextoffset": len(courses)}

    def a_core_courseformat_get_state(self, args):
        try:
            cid = int(args["courseid"])
        except (KeyError, TypeError, ValueError):
            raise AjaxError("invalidparameter") from None
        if cid not in self.sc.course:
            raise AjaxError("requireloginerror")
        # data 是 JSON 字符串，要再 parse 一次；里层的斜杠也转义
        return php_json(self._state(cid)).replace(BASE_MARK, self.mock.base_url.replace("/", "\\/"))

    def _state(self, cid):
        data = self.sc.course[cid]
        st, meta = data["structure"], data["meta"]
        idv = str if st.get("ids_as", "string") == "string" else int
        indent = "0" if st.get("indent_as") == "string" else 0
        weeks = meta.get("format") == "weeks"
        secs = st["sections"]
        course = {"id": idv(cid), "numsections": max((s["number"] for s in secs), default=0),
                  "sectionlist": [idv(s["id"]) for s in secs], "editmode": False,
                  "highlighted": "Current week" if weeks else "Highlighted", "maxsections": "52",
                  "baseurl": f"{BASE_MARK}/course/view.php?id={cid}", "statekey": f"{REV}_{cid}", "maxbytes": 104857600,
                  "maxbytestext": "100 MB"}
        sections = [self._state_section(cid, s, idv, weeks) for s in secs]
        cms = [self._state_cm(self.sc.cms[m], idv, indent) for s in secs for m in s["cms"]]
        return {"course": course, "section": sections, "cm": cms}

    def _state_section(self, cid, s, idv, weeks):
        n = s["number"]
        current = False
        if weeks and n:
            start = self.sc.local(_ts(self.sc.course[cid]["meta"]["startdate"])).date() + dt.timedelta(days=7 * (n - 1))
            current = start <= self.sc.local(self.sc.now).date() < start + dt.timedelta(days=7)
        return {"id": idv(s["id"]), "section": n, "number": n,
                "title": fmt_string(s["name"]) if s.get("name") else self._default_title(cid, n),
                "hassummary": bool(s.get("summary")), "rawtitle": s.get("name"), "cmlist": [idv(m) for m in s["cms"]],
                "visible": True, "sectionurl": f"{BASE_MARK}/course/section.php?id={s['id']}", "current": current,
                "indexcollapsed": False, "contentcollapsed": False, "hasrestrictions": False, "bulkeditable": n > 0,
                "component": None, "itemid": None, "parentsectionid": None}

    def _state_cm(self, cm, idv, indent):
        mod = cm["module"]
        out = {"id": idv(cm["id"]), "anchor": f"module-{cm['id']}", "name": fmt_string(cm["name"]), "visible": True,
               "stealth": False, "sectionid": idv(cm["section_id"]), "sectionnumber": cm["section_number"],
               "uservisible": cm.get("uservisible", True), "hascmrestrictions": cm.get("hascmrestrictions", False),
               "modname": MODNAMES.get(mod, mod.title()), "indent": indent, "groupmode": "0", "module": mod,
               "plugin": "mod_" + mod, "hasdelegatedsection": False, "accessvisible": cm.get("accessvisible", True)}
        if mod != "label":
            out["url"] = f"{BASE_MARK}/mod/{mod}/view.php?id={cm['id']}"
        out["istrackeduser"] = True
        if "completion" in cm:
            out["completionstate"] = cm["completion"]
            out["isoverallcomplete"] = cm["completion"] in (1, 2)
        out["allowstealth"] = False
        return out

    # ---- 日历
    def _visible_events(self, courseid=None):
        """这个学生日历里看得见的事件：被过滤的课、看不到的活动、gradingdue 都不给。"""
        sc = self.sc
        out = []
        for e in sc.events:
            cid = e.get("course")
            if cid is not None and (cid not in sc.course or cid in sc.hidden):
                continue
            if e.get("cm") and e["cm"].get("uservisible", True) is False or e["eventtype"] == "gradingdue":
                continue
            if courseid not in (None, sc.siteid) and cid != courseid and e["eventtype"] not in ("site", "user"):
                continue
            out.append(e)
        return out

    def _action(self, e):
        """事件的 action（交没交的信号）；None 表示没有待办。"""
        cm, now = e.get("cm"), self.sc.now
        if not cm or cm.get("completion") in (1, 2, 3):
            return None
        cmid, url = cm["id"], f"{BASE_MARK}/mod/{cm['module']}/view.php?id={cm['id']}"
        if cm["module"] == "assign" and e["eventtype"] in ("due", "extension"):
            a = cm.get("assign") or {}
            if a.get("status") == "submitted":
                return None
            return {"name": "Add submission", "url": f"{url}&action=editsubmission", "itemcount": 1,
                    "actionable": a.get("submissionsenabled", True) is not False, "showitemcount": False}
        if cm["module"] == "quiz" and e["eventtype"] in ("open", "close"):
            closes, opens = self.sc.cm_events(cmid, "close"), self.sc.cm_events(cmid, "open")
            if e["eventtype"] == "open" and closes:
                return None  # 设了关闭时间，open 事件是 STANDARD，没有 action
            if (cm.get("quiz") or {}).get("attempts") or (closes and closes <= now):
                return None
            return {"name": "Attempt quiz now", "url": url, "itemcount": 1, "actionable": not opens or opens <= now,
                    "showitemcount": False}
        return None

    def _event_obj(self, e, month_view=True):
        sc, cm, cid, kind = self.sc, e.get("cm"), e.get("course"), e["eventtype"]
        ts, dur = e["timestart"], e["timeduration"]
        mod = cm and cm["module"]
        name = e.get("name") or self._event_name(e)
        mid = int(sc.local(ts).replace(hour=0, minute=0, second=0).timestamp())
        norm = "course" if (cm or kind == "course") else kind
        out = {"id": e["id"], "name": name, "description": e.get("description") or (cm and (cm.get(mod) or {}).get("intro")) or "",
               "descriptionformat": 1, "location": e.get("location", ""), "categoryid": None, "groupid": None,
               "userid": sc.user["id"] if e.get("user") else None, "repeatid": None, "eventcount": None,
               "component": f"mod_{mod}" if mod else None, "modulename": mod, "activityname": cm and fmt_string(cm["name"]),
               "activitystr": cm and self._activitystr(mod, kind), "instance": cm and cm["id"], "eventtype": kind,
               "timestart": ts, "timeduration": dur, "timesort": ts, "timeusermidnight": mid, "visible": 1,
               "timemodified": sc.now - 30 * 86400, "overdue": ts < sc.now, "icon": self._icon(mod, kind)}
        if cid is not None:
            out["course"] = self._course_summary(sc.course[cid]["meta"])
        view = f"{BASE_MARK}/calendar/view.php?view=day" + (f"&course={cid}" if cid else "") + f"&time={ts}#event_{e['id']}"
        out.update({"subscription": {"displayeventsource": False}, "canedit": kind == "user", "candelete": kind == "user",
                    "deleteurl": f"{BASE_MARK}/calendar/delete.php?id={e['id']}&course={cid or sc.siteid}",
                    "editurl": (f"{BASE_MARK}/course/mod.php?update={cm['id']}&return=1&sesskey={self.mock.sesskey}" if cm
                                else f"{BASE_MARK}/calendar/event.php?action=edit&id={e['id']}&course={cid or sc.siteid}"),
                    "viewurl": view, "formattedtime": self._formattedtime(ts, dur), "formattedlocation": e.get("location", ""),
                    "isactionevent": bool(cm), "iscourseevent": kind == "course", "iscategoryevent": False, "groupname": None,
                    "normalisedeventtype": norm, "normalisedeventtypetext": f"{norm.title()} event"})
        action = self._action(e)
        if action:
            out["action"] = action
        out.update({"purpose": "assessment" if mod in ("assign", "quiz") else ("other" if mod else "none"), "branded": False,
                    "url": f"{BASE_MARK}/mod/{mod}/view.php?id={cm['id']}" if cm else
                    (f"{BASE_MARK}/course/view.php?id={cid}" if cid else view)})
        if month_view:
            prefix = f"{fmt_string(sc.course[cid]['meta']['shortname'])}: " if cid else ""
            out.update({"islastday": False, "popupname": prefix + name, "draggable": False})
        return out

    def _event_name(self, e):
        cm = e["cm"]
        suffix = {"due": "is due", "open": "opens", "close": "closes", "extension": "extended due date"}.get(e["eventtype"], "")
        return f"{fmt_string(cm['name'])} {suffix}".strip()

    @staticmethod
    def _activitystr(mod, kind):
        return {("assign", "due"): "Assignment is due", ("assign", "extension"): "Assignment extended due date",
                ("quiz", "open"): "Quiz opens", ("quiz", "close"): "Quiz closes"}.get((mod, kind))

    def _icon(self, mod, kind):
        if mod:
            return {"key": "monologo", "component": mod, "alttext": "Activity event",
                    "iconurl": f"{BASE_MARK}/theme/image.php/boost/{mod}/{REV}/monologo?filtericon=1", "iconclass": ""}
        return {"key": f"i/{kind}event", "component": "core", "alttext": f"{kind.title()} event", "iconurl": "", "iconclass": ""}

    def _formattedtime(self, ts, dur):
        """4.5：只有时间；同一天有时长是「起 » 止」；跨天带日期链接；过期了包 dimmed_text。"""
        sc = self.sc
        a, b = sc.local(ts), sc.local(ts + dur)
        if not dur:
            text = _hm(a)
        elif a.date() == b.date():
            text = f"{_hm(a)} <strong>&raquo;</strong> {_hm(b)}"
        else:
            link = lambda d, t: (f'<a href="{BASE_MARK}/calendar/view.php?view=day&amp;time={t}">'  # noqa: E731
                                 f'{DAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]}</a>, {_hm(d)}')
            text = f"{link(a, ts)} <strong>&raquo;</strong> {link(b, ts + dur)}"
        return f'<span class="dimmed_text">{text}</span>' if ts + dur < sc.now else text

    def a_core_calendar_get_calendar_monthly_view(self, args):
        try:
            year, month = int(args["year"]), int(args["month"])
        except (KeyError, TypeError, ValueError):
            raise AjaxError("invalidparameter") from None
        if "courseid" in args and args["courseid"] is None:
            raise AjaxError("generalexceptionmessage")  # PHP 8：显式传 null 会 TypeError
        courseid = int(args.get("courseid") or self.sc.siteid)
        if courseid != self.sc.siteid and courseid not in self.sc.course:
            raise AjaxError("requireloginerror")
        view = args.get("view") or ("mini" if args.get("mini") else "month")
        return self._month(year, month, courseid, args.get("includenavigation", True), view)

    def _month(self, year, month, courseid, nav, view):
        sc, tz = self.sc, self.sc.tz
        first = dt.datetime(year, month, 1, tzinfo=tz)
        nxt = dt.datetime(year + month // 12, month % 12 + 1, 1, tzinfo=tz)
        t0, t1 = int(first.timestamp()), int(nxt.timestamp()) - 1
        events = [e for e in self._visible_events(courseid)
                  if e["timestart"] <= t1 and (e["timestart"] >= t0 or e["timestart"] + e["timeduration"] > t0)]
        events.sort(key=lambda e: (e["timestart"], e["id"]))
        objs = {e["id"]: self._event_obj(e) for e in events}
        days, d = [], first
        while d < nxt:
            days.append(self._day(d, events, objs))
            d = dt.datetime.combine(d.date() + dt.timedelta(days=1), dt.time(), tzinfo=tz)
        weeks, week = [], []
        for day in days:
            week.append(day)
            if day["wday"] == 0:
                weeks.append(week)
                week = []
        if week:
            weeks.append(week)
        wk = [{"prepadding": list(range((w[0]["wday"] - 1) % 7)) if i == 0 else [],
               "postpadding": list(range((7 - w[-1]["wday"]) % 7)) if i == len(weeks) - 1 else [], "days": w}
              for i, w in enumerate(weeks)]
        prev = dt.datetime(year - (month == 1), (month - 2) % 12 + 1, 1, tzinfo=tz)
        out = {"url": f"{BASE_MARK}/calendar/view.php?view=month&time={t0}", "courseid": courseid, "categoryid": 0}
        if view in ("month", "monthblock"):
            opts = "".join(f'<option value="{c["id"]}">{fmt_string(c["fullname"])}</option>' for c in sc.courses)
            out["filter_selector"] = (f'<label for="calendar-course-filter-1" class="sr-only">List of courses</label><select name="course" '
                                      f'id="calendar-course-filter-1" class="select custom-select cal_courses_flt ms-1 me-auto me-2 mb-2">'
                                      f'<option value="{sc.siteid}" selected>All courses</option>{opts}</select>')
        out.update({"weeks": wk, "daynames": [{"dayno": (i + 1) % 7, "shortname": n[:3], "fullname": n} for i, n in enumerate(DAYS)],
                    "view": view, "date": self._date(first), "periodname": f"{MONTHS[month - 1]} {year}",
                    "includenavigation": bool(nav), "initialeventsloaded": True, "previousperiod": self._date(prev),
                    "previousperiodlink": f"{BASE_MARK}/calendar/view.php?view=month&time={int(prev.timestamp())}",
                    "previousperiodname": MONTHS[prev.month - 1], "nextperiod": self._date(nxt), "nextperiodname": MONTHS[nxt.month - 1],
                    "nextperiodlink": f"{BASE_MARK}/calendar/view.php?view=month&time={int(nxt.timestamp())}", "larrow": "&#x25C4;",
                    "rarrow": "&#x25BA;", "defaulteventcontext": sc.site_ctx if courseid == sc.siteid else 20000 + courseid,
                    "calendarinstanceid": 1, "viewingmonth": True, "showviewselector": True, "viewinginblock": False})
        return out

    @staticmethod
    def _date(d):
        return {"seconds": 0, "minutes": 0, "hours": 0, "mday": d.day, "wday": (d.weekday() + 1) % 7, "mon": d.month,
                "year": d.year, "yday": d.timetuple().tm_yday - 1, "weekday": DAYS[d.weekday()], "month": MONTHS[d.month - 1],
                "timestamp": int(d.timestamp())}

    def _day(self, d, events, objs):
        """一个日格：跨天事件在覆盖到的每一天都出现一次（所以要按 id 去重）。"""
        sc = self.sc
        date = d.date()
        todays = []
        for e in events:
            a = sc.local(e["timestart"]).date()
            b = sc.local(e["timestart"] + e["timeduration"]).date()
            if a <= date <= b:
                todays.append(dict(objs[e["id"]], islastday=(b == date and e["timeduration"] > 0)))
        ts = int(d.timestamp())
        label = f"{DAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]}"
        now_local = sc.local(sc.now)
        today = date == now_local.date()
        count = f"{len(todays)} event{'' if len(todays) == 1 else 's'}" if todays else "No events"
        out = {"seconds": 0, "minutes": 0, "hours": 0, "mday": d.day, "wday": (d.weekday() + 1) % 7, "year": d.year,
               "yday": d.timetuple().tm_yday - 1, "istoday": today, "isweekend": d.weekday() >= 5, "timestamp": ts,
               "neweventtimestamp": ts + now_local.hour * 3600, "viewdaylink": f"{BASE_MARK}/calendar/view.php?view=day&time={ts}"}
        if today or todays:
            out["viewdaylinktitle"] = f"Today {label}" if today else f"{label} events"
        out.update({"events": todays, "hasevents": bool(todays),
                    "calendareventtypes": sorted({o["normalisedeventtype"] for o in todays}), "previousperiod": ts - 86400,
                    "nextperiod": ts + 86400, "haslastdayofevent": any(o["islastday"] for o in todays),
                    "popovertitle": out.get("viewdaylinktitle", ""), "daytitle": f"{count}, {label}"})
        return out

    def a_core_calendar_get_action_events_by_timesort(self, args):
        try:
            since = int(args.get("timesortfrom") or 0)
            until = None if args.get("timesortto") is None else int(args["timesortto"])
            after, limit = int(args.get("aftereventid") or 0), int(args.get("limitnum", 20) or 20)
        except (TypeError, ValueError):
            raise AjaxError("invalidparameter") from None
        if args.get("userid") not in (None, 0, self.sc.user["id"]):
            raise AjaxError("nopermissions")
        evs = sorted((e for e in self._visible_events() if self._action(e) and e["timestart"] >= since
                      and (until is None or e["timestart"] <= until)), key=lambda e: (e["timestart"], e["id"]))
        if after:
            ref = next((e for e in evs if e["id"] == after), None)
            evs = [e for e in evs if ref and (e["timestart"], e["id"]) > (ref["timestart"], ref["id"])]
        evs = evs[:limit]
        objs = [self._event_obj(e, month_view=False) for e in evs]
        return {"events": objs, "firstid": objs[0]["id"] if objs else 0, "lastid": objs[-1]["id"] if objs else 0}

    # ---- 公告正文
    def a_mod_forum_get_discussion_posts(self, args):
        try:
            did = int(args["discussionid"])
        except (KeyError, TypeError, ValueError):
            raise AjaxError("invalidparameter") from None
        sortby, direction = args.get("sortby", "created"), args.get("sortdirection", "DESC")
        if sortby not in ("id", "created", "modified") or direction not in ("ASC", "DESC"):
            raise AjaxError("invalidparameter")
        cid, cmid, d = self.sc.discussion(did)
        if d is None:
            raise AjaxError("generalexceptionmessage", "Exception - Call to a member function get_forum_id() on null")
        cm = self.sc.cms[cmid]
        posts = [self._post(cid, cm, d, p) for p in d["posts"]]
        key = "id" if sortby == "id" else "timecreated"
        posts.sort(key=lambda p: (p[key], p["id"]), reverse=direction == "DESC")
        return {"posts": posts, "forumid": cm["forum"]["id"], "courseid": cid,
                "ratinginfo": {"contextid": 10000 + cmid, "component": "mod_forum", "ratingarea": "post", "canviewall": None,
                               "canviewany": None, "scales": [], "ratings": []}, "warnings": []}

    def _post(self, cid, cm, d, p):
        author = p.get("author") or d.get("author", "")
        aid = self.sc.authors.get(author)
        first = not p.get("parent")
        subject = fmt_string(d["subject"] if first else "Re: " + d["subject"])
        ts, did = _ts(p["created"]), d["id"]
        disc = f"{BASE_MARK}/mod/forum/discuss.php?d={did}"
        return {"id": p["id"], "subject": subject, "replysubject": subject if subject.startswith("Re: ") else "Re: " + subject,
                "label": f"{subject} by {author}", "message": p["message"], "messageformat": 1,
                "author": {"id": aid, "fullname": author, "isdeleted": False, "groups": [],
                           "urls": {"profile": f"{BASE_MARK}/user/view.php?id={aid}&course={cid}",
                                    "profileimage": f"{BASE_MARK}/pluginfile.php/{5000 + (aid or 0)}/user/icon/boost/f1?rev=12345"}},
                "discussionid": did, "hasparent": not first, "parentid": p.get("parent"), "timecreated": ts, "timemodified": ts,
                "unread": None, "isdeleted": False, "isprivatereply": False, "haswordcount": False, "wordcount": None,
                "charcount": None,
                "capabilities": {"view": True, "edit": False, "delete": False, "split": False, "reply": False, "selfenrol": False,
                                 "export": False, "controlreadstatus": False, "canreplyprivately": False},
                "urls": {"view": f"{disc}#p{p['id']}", "viewisolated": f"{disc}&parent={p['id']}",
                         "viewparent": f"{disc}#p{p['parent']}" if p.get("parent") else None, "edit": None, "delete": None,
                         "split": None, "reply": None, "export": None, "markasread": None, "markasunread": None, "discuss": disc},
                "attachments": [], "messageinlinefiles": [], "tags": [], "html": None}


_GET_ROUTES = [
    (r"/(?:index\.php)?", "front"),
    (r"/login/index\.php", "login"),
    (r"/my/(?:(index\.php|courses\.php))?", "my"),
    (r"/enrol/index\.php", "enrol"),
    (r"/course/view\.php", "course"),
    (r"/mod/assign/view\.php", "assign"),
    (r"/mod/quiz/view\.php", "quiz"),
    (r"/mod/forum/view\.php", "forum"),
    (r"/mod/forum/discuss\.php", "discuss"),
    (r"/mod/folder/view\.php", "folder"),
    (r"/mod/resource/view\.php", "resource"),
    (r"/mod/(page|url|lti|label|book|workshop|h5pactivity|scorm|lesson)/view\.php", "module"),
    (r"/grade/report/user/index\.php", "grades"),
    (r"/pluginfile\.php/(\d+)/(mod_resource|mod_folder|mod_forum)/(.+)", "pluginfile"),
    (r"/pluginfile\.php", "pluginfile_q"),
    (r"/lib/ajax/service-nologin\.php", "nologin_get"),
    (r"/lib/ajax/service\.php", "ajax_get"),
]


class MockMoodle:
    """with MockMoodle("moodle_term") as mock: ... mock.base_url ... mock.requests()

    logged_out：没登录（或会话过期）时的样子。"login" 303 到 /login/index.php；"sso" 303 到外部 IdP
    （登录页也转去 IdP，拿不到 cookie）；"guest" 站点开了访客自动登录：页面以访客身份 200，课程页 303 到 enrol。"""

    def __init__(self, scenario, host="127.0.0.1", port=0, logged_out="login", cookie_suffix=""):
        if host not in LOOPBACK:
            raise ValueError("mockmoodle only binds to loopback")
        if logged_out not in ("login", "sso", "guest"):
            raise ValueError("logged_out must be login, sso or guest")
        self.scenario = scenario if isinstance(scenario, Scenario) else Scenario(scenario)
        self.logged_out = logged_out
        self.cookie_name = "MoodleSession" + cookie_suffix
        self.session_cookie = uuid.uuid4().hex
        self.sesskey = self._new_key()
        self.logins = 0
        self.regrading = set()  # 这些课的成绩页显示「正在重算」
        self.slasharguments = 1  # 0：pluginfile 地址写成 /pluginfile.php?file=…
        self.release = "4.5"     # "4.4"：M.cfg 没有 userId / apibase（访客只能看用户菜单认）
        self.dashboard_hidden = set()  # 学生在仪表盘上「从视图中移除」的课：只有 allincludinghidden / hidden 里有
        self.host, self.port = host, port
        self._lock = threading.Lock()
        self._log_entries = []
        self._force, self._ajax_force = [], []
        self.httpd = None
        self.thread = None

    @staticmethod
    def _new_key():
        return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(10))

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
        """登录过期：之前发的 cookie 全都不认了，sesskey 也换了（新会话）。"""
        self.session_cookie = uuid.uuid4().hex
        self.sesskey = self._new_key()

    def new_sesskey(self):
        """会话还在，但手里的 sesskey 不对了（测 invalidsesskey 后重取一次）。"""
        self.sesskey = self._new_key()

    def cookie_header(self):
        return f"{self.cookie_name}={self.session_cookie}"

    def playwright_cookies(self):
        """Playwright context.cookies() 的形状，给测试直接写进 canvas-cookies.json。"""
        return [{"name": self.cookie_name, "value": self.session_cookie, "domain": self.host, "path": "/", "expires": -1,
                 "httpOnly": True, "secure": False, "sameSite": "Lax"}]

    def force_status(self, path_regex, status):
        """匹配的请求（路径加查询串）直接回这个 HTTP 状态码（测失败用）。"""
        self._force.append((re.compile(path_regex), status))

    def force_ajax_error(self, method_regex, errorcode):
        """匹配的 ajax 函数回 {error:true, exception:{errorcode}}（HTTP 仍是 200，同真站）。"""
        self._ajax_force.append((re.compile(method_regex), errorcode))

    def _forced(self, target):
        return next((st for rx, st in self._force if rx.search(target)), None)

    def _ajax_forced(self, name):
        return next((code for rx, code in self._ajax_force if rx.search(name)), None)

    def _log(self, method, path, query, status, matched, methods=None):
        with self._lock:
            self._log_entries.append({"method": method, "path": path, "query": list(query), "status": status,
                                      "matched": matched, "methods": methods})

    def requests(self, clear=False):
        with self._lock:
            out = list(self._log_entries)
            if clear:
                self._log_entries.clear()
        return out

    def writes(self):
        """被拒的写请求（405）；只读的工具应该一条都没有。"""
        return [r for r in self.requests() if r["status"] == 405]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Serve one fixture scenario as a mock Moodle on 127.0.0.1.")
    ap.add_argument("scenario")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--logged-out", default="login", choices=("login", "sso", "guest"))
    args = ap.parse_args(argv)
    mock = MockMoodle(args.scenario, port=args.port, logged_out=args.logged_out).start()
    print(f"mock Moodle for {args.scenario} at {mock.base_url} (log in: {mock.base_url}/login/index.php); Ctrl+C to stop",
          flush=True)
    try:
        mock.thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        mock.stop()


if __name__ == "__main__":
    main()
