"""本机假的学校统一登录（IdP）和两个要学校账号的网站，测「学生最多输一次」。

主机名用 *.localhost（浏览器自己解析到本机；cookie 按主机分开，像真的几个不同网站）：
- idp.localhost：学校登录页。登过（idp_sid 还有效）就直接带一张票跳回去；没登过给表单（UniKey + 密码 + Keep me signed in）。
  勾了 Keep me signed in 的 cookie 带过期时间（浏览器关了还在）；没勾的是会话 cookie（浏览器一关就丢，只能靠救驾自己存的那份）。
- site.localhost、site2.localhost：两个走学校登录的网站（像选课系统、Zoom 录像）。没登过就转去 idp，带票回来发自己的 cookie。
计数：form_logins = 学生在表单里登了几次（就是「输了几次」）；silent = 学校还记得、直接带票跳回去了几次。
MockCanvas(session=True, sso=这个) 的 Canvas 登录也走这里。
"""
import html
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

USER, PASSWORD = "student1", "pw-for-tests-only"
SITES = ("site", "site2")


def _with(url, **params):
    p = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qsl(p.query, keep_blank_values=True) + list(params.items())
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q), ""))


def _form(back, error=False):
    action = html.escape("/sso?" + urllib.parse.urlencode({"return": back}))
    oops = "<p class=err>Wrong UniKey or password.</p>" if error else ""
    return ("<!doctype html><title>The University - Sign In</title><h1>Sign In</h1>" + oops +
            f'<form method="post" action="{action}"><label>Username (UniKey) <input name="username"></label>'
            '<label>Password <input type="password" name="password"></label>'
            '<label><input type="checkbox" name="rememberMe" value="1"> Keep me signed in</label>'
            '<button type="submit">Sign in</button></form>').encode("utf-8")


def _page(name, path):
    return (f"<!doctype html><title>{name} timetable</title><h1>{name}: your timetable</h1>"
            f"<p>{html.escape(path)}: Week 9, Tuesday 4 pm MECO6941 class in room 224; the recording is posted after class.</p>"
            ).encode("utf-8")


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _host(self):
        return (self.headers.get("Host") or "").split(":")[0].lower()

    def _cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return None

    def _send(self, status, body=b"", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _go(self, where, cookie=None):
        self._send(302, b"", {"Location": where, **({"Set-Cookie": cookie} if cookie else {})})

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def _route(self, method):
        m = self.server.mock
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        host = self._host()
        if host == "idp.localhost" and u.path == "/sso":
            back = q.get("return") or "/"
            if method == "POST":
                n = int(self.headers.get("Content-Length") or 0)
                form = dict(urllib.parse.parse_qsl(self.rfile.read(n).decode("utf-8")))
                if form.get("username") == USER and form.get("password") == PASSWORD:
                    return self._signed(back, keep=bool(form.get("rememberMe")))
                return self._send(200, _form(back, error=True))
            sid = self._cookie("idp_sid")
            if sid and sid in m.idp_sessions:
                m.silent += 1  # 学校还记得：不出表单，直接带票跳回去
                return self._go(_with(back, ticket=m.ticket()))
            if m.auto_accept:  # 当学生已经在窗口里登好了（测登录窗口用）
                return self._signed(back, keep=False)
            return self._send(200, _form(back))
        name = host.split(".")[0]
        if host.endswith(".localhost") and name in SITES:
            if u.path == "/acs":
                nxt = q.get("next") or "/"
                if m.redeem(q.get("ticket")):
                    sid = uuid.uuid4().hex
                    m.site_sessions[name].add(sid)
                    return self._go(nxt, f"{name}_sid={sid}; Path=/; HttpOnly")
                return self._go(m.login_url(m.url(name, "/acs?" + urllib.parse.urlencode({"next": nxt}))))
            sid = self._cookie(f"{name}_sid")
            if sid and sid in m.site_sessions[name]:
                return self._send(200, _page(name, u.path))
            return self._go(m.login_url(m.url(name, "/acs?" + urllib.parse.urlencode({"next": self.path}))))
        return self._send(404, b"not found")

    def _signed(self, back, keep):
        m = self.server.mock
        sid = uuid.uuid4().hex
        m.idp_sessions.add(sid)
        m.form_logins += 1
        cookie = f"idp_sid={sid}; Path=/; HttpOnly" + ("; Max-Age=2592000" if keep else "")
        return self._go(_with(back, ticket=m.ticket()), cookie)


class MockSSO:
    """with MockSSO() as sso: sso.url("site", "/timetable") …"""

    def __init__(self):
        self.port = 0
        self.idp_sessions = set()
        self.site_sessions = {h: set() for h in SITES}
        self.tickets = {}
        self.form_logins = 0
        self.silent = 0
        self.auto_accept = False
        self._lock = threading.Lock()
        self.httpd = self.thread = None

    def url(self, host, path="/"):
        return f"http://{host}.localhost:{self.port}{path}"

    def login_url(self, back):
        return self.url("idp", "/sso?" + urllib.parse.urlencode({"return": back}))

    def ticket(self):
        t = uuid.uuid4().hex
        with self._lock:
            self.tickets[t] = USER
        return t

    def redeem(self, t):
        with self._lock:
            return self.tickets.pop(t or "", None) is not None

    def expire_idp(self):
        """学校的登录过期了（要重新输密码）。"""
        self.idp_sessions.clear()

    def expire_site(self, name="site"):
        """这个网站自己的登录过期了（学校的还在）。"""
        self.site_sessions[name].clear()

    def start(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
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
