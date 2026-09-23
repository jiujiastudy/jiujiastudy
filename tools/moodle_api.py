"""Moodle 客户端（只读）：用学生自己在登录窗口里的登录，读他本来就能看到的数据。

- ajax：只调 AJAX_READ 白名单里的读取函数（POST /lib/ajax/service.php?sesskey=…）；其它一律拒绝。
- 页面：只 GET 本站（host 前缀）的页面和 pluginfile 文件；跳转只在本站内跟，绝不去别的网站。
- 没登录 / 会话过期 / 被转去学校登录（SSO）/ 访客身份 → CanvasAuthError(cc_session.RELOGIN)。
- 传输层可替换：默认 PlaywrightTransport（复用登录窗口那份浏览器资料夹）；
  环境变量 {PREFIX}_MOODLE_TRANSPORT=urllib 时用 UrllibTransport（离线测试对着本机假 Moodle）。
"""
import email.message
import http.cookiejar
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import brand
from canvas_api import RETRY_CODES, CanvasAuthError, CanvasError

UA = f"{brand.SLUG}/2 (read-only; login)"
REDIRECTS = {301, 302, 303, 307, 308}
MAX_HOPS = 6
GUEST_MAX_ID = 1   # 访客账号的 id：安装时第一个建，通常是 1（源码没核实 siteguest 的值，按 ≤1 算访客）

# 只读 ajax 白名单：都在 services.php 里标了 type read + ajax=>true（见 specs_moodle.json）
AJAX_READ = frozenset({
    "core_calendar_get_calendar_monthly_view",
    "core_calendar_get_action_events_by_timesort",
    "core_course_get_enrolled_courses_by_timeline_classification",
    "core_courseformat_get_state",
    "mod_forum_get_discussion_posts",
})


class MoodleError(CanvasError):
    """Moodle 返回的错误；errorcode 是 Moodle 的错误码（没有就是 None）。"""

    def __init__(self, msg, errorcode=None):
        super().__init__(msg)
        self.errorcode = errorcode


def _relogin():
    import cc_session
    return CanvasAuthError(cc_session.RELOGIN)


def normalize_host(host):
    """补 https://、去掉末尾的 /。"""
    host = (host or "").strip().rstrip("/")
    if host and not host.lower().startswith(("http://", "https://")):
        host = "https://" + host
    return host


# ---------------------------------------------------------------- 页面里的信号
def _mcfg(html):
    """页面 <head> 里的 M.cfg = {...}（json_encode 出来的，要按 JSON 解析）；没有返回 None。"""
    m = re.search(r"M\.cfg\s*=\s*\{", html or "")
    if not m:
        return None
    try:
        cfg, _ = json.JSONDecoder().raw_decode(html, m.end() - 1)
    except ValueError:
        return None
    return cfg if isinstance(cfg, dict) else None


def _user_id(cfg):
    """M.cfg.userId（4.5 起才有）：int 或 None。"""
    try:
        return int((cfg or {}).get("userId"))
    except (TypeError, ValueError):
        return None


def _login_state(html):
    """看页面像不像「没登录」：'login'（登录页 / 没登录）、'guest'（访客）或 None（看不出问题）。"""
    body = re.search(r"<body\b[^>]*\bclass\s*=\s*[\"']([^\"']*)", html or "", re.I)
    if body and "notloggedin" in body.group(1).split():
        return "login"
    if re.search(r"<form\b[^>]*\bid\s*=\s*[\"']login[\"']", html or "", re.I) and "logintoken" in html:
        return "login"
    if re.search(r"http-equiv\s*=\s*[\"']refresh[\"'][^>]*/login/index\.php", html or "", re.I):
        return "login"  # 调试站点关了 303，改用延时跳转页
    cfg = _mcfg(html)
    uid = _user_id(cfg)
    if uid is not None and uid <= GUEST_MAX_ID:
        return "guest"
    if cfg is not None and "userId" not in cfg and _guest_menu(html):
        return "guest"  # 4.4 及更早的 M.cfg 没有 userId：看用户菜单里访客才有的「登录」链接
    return None


def _guest_menu(html):
    """用户菜单是 span.login 里带 /login/index.php 链接（访客 / 没登录的样子），且页面上没有退出链接。"""
    if re.search(r"/login/logout\.php\?sesskey=", html or ""):
        return False
    return bool(re.search(r"<span\b[^>]*\bclass\s*=\s*[\"'](?:[^\"']*\s)?login(?:\s[^\"']*)?[\"'][^>]*>(?:(?!</span>).)*?"
                          r"/login/index\.php", html or "", re.I | re.S))


def _user_name(html):
    """用户菜单里的名字（老主题的 span.usertext）；取不到返回 None。"""
    m = re.search(r"<span\b[^>]*\bclass\s*=\s*[\"'][^\"']*\busertext\b[^\"']*[\"'][^>]*>\s*([^<]+?)\s*<", html or "")
    return m.group(1).strip() if m else None


def _pluginfile(rel):
    """站内地址（/pluginfile.php/… 或站点关了 slasharguments 时的 /pluginfile.php?file=…）
    → 文件路径各段（已解码，最后一段是文件名）；不是 pluginfile 返回 None。"""
    p = urllib.parse.urlparse(rel or "")
    if p.path.startswith("/pluginfile.php/"):
        segs = [urllib.parse.unquote(s) for s in p.path[len("/pluginfile.php/"):].split("/")]
    elif p.path == "/pluginfile.php":
        segs = (urllib.parse.parse_qs(p.query).get("file") or [""])[0].strip("/").split("/")
    else:
        return None
    return segs if segs[-1] else None


def _is_html(headers, body):
    ctype = (headers or {}).get("content-type") or ""
    return "html" in ctype.lower() or (not ctype and body[:200].lstrip()[:1] == b"<")


def _unpack(payload):
    """ajax 的返回 → (errorcode, message, data)；成功时 errorcode 是 None。"""
    if isinstance(payload, dict):  # 整个请求级别的错（methodname 不存在、JSON 不对）：单个对象
        msg = payload.get("error") if isinstance(payload.get("error"), str) else payload.get("message")
        return payload.get("errorcode") or "unknown", msg, None
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise MoodleError("ajax 没有返回结果（missing response）")
    item = payload[0]
    if item.get("error") is False or (not item.get("error") and "data" in item):
        return None, None, item.get("data")
    exc = item.get("exception") if isinstance(item.get("exception"), dict) else {}
    return exc.get("errorcode") or "unknown", exc.get("message"), None


def _message(headers):
    m = email.message.Message()  # 和 urllib 一样按名字取、不分大小写
    for k, v in (headers or {}).items():
        m[k] = v
    return m


# ---------------------------------------------------------------- 传输层
class UrllibTransport:
    """标准库传输层：cookie 从 cc_session 存的 browser/canvas-cookies.json 读（或直接给 cookies）。"""

    def __init__(self, home=None, cookies=None, timeout=60):
        self.timeout = timeout
        self.host = None
        self.jar = http.cookiejar.CookieJar()
        if cookies is None and home:
            cookies = self._saved(home)
        for c in cookies or []:
            self._add(c)
        self._follow = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self._stay = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), _NoRedirect())

    @staticmethod
    def _saved(home):
        import cc_session
        from cc_store import jload
        return jload(os.path.join(cc_session.profile_dir(home), cc_session.COOKIES), []) or []

    def _add(self, c):
        """Playwright 存的 cookie（name/value/domain/path/expires/secure）放进 CookieJar。"""
        if not isinstance(c, dict) or not c.get("name"):
            return
        domain = c.get("domain") or ""
        if domain.lstrip(".") == "localhost":
            domain = "localhost.local"  # CookieJar 把不带点的主机名当 xxx.local
        exp = c.get("expires", -1)
        expires = int(exp) if isinstance(exp, (int, float)) and exp > 0 else None
        if expires is not None and expires < time.time():
            return
        self.jar.set_cookie(http.cookiejar.Cookie(
            0, c["name"], str(c.get("value", "")), None, False, domain, domain.startswith("."),
            domain.startswith("."), c.get("path") or "/", True, bool(c.get("secure")), expires,
            expires is None, None, None, {}))

    def _open(self, req, follow):
        opener = self._follow if follow else self._stay
        try:
            with opener.open(req, timeout=self.timeout) as r:
                return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(), r.geturl()
        except urllib.error.HTTPError as e:  # 3xx（不跟）和 4xx/5xx：照样返回，交给客户端判断
            hdrs = {k.lower(): v for k, v in (e.headers or {}).items()}
            return e.code, hdrs, e.read() if e.fp else b"", e.geturl() or req.full_url

    def get(self, url, headers=None, follow=True):
        return self._open(urllib.request.Request(url, headers=headers or {}), follow)

    def post(self, url, body, headers=None):
        return self._open(urllib.request.Request(url, data=body, headers=headers or {}, method="POST"), False)

    def close(self):
        pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # 不跟：3xx 当 HTTPError 交回去


class PlaywrightTransport:
    """浏览器传输层：给了 context 就包装它（登录窗口里用，不关它）；否则按需在后台起一个（不开窗口）。"""

    def __init__(self, home=None, context=None, timeout=60):
        self.home, self.timeout = home, timeout
        self.host = None  # MoodleClient 填：关的时候按它存 cookie
        self._ctx, self._own = context, context is None
        self._pw = self._broken = None

    def _request(self):
        if self._broken:  # 起过一次没起来：后面直接报同一个错，不再一遍遍起浏览器
            raise self._broken
        if self._ctx is None:
            import cc_session
            try:
                self._pw = cc_session._sync_playwright()().start()
                self._ctx = cc_session._launch(self._pw, self.home, headless=True)
                cc_session._restore_cookies(self._ctx, self.home)
            except Exception as e:  # noqa: BLE001
                self._stop()
                self._broken = e if isinstance(e, CanvasError) else \
                    cc_session.LoginUnavailable(f"浏览器起不来：{cc_session._first_line(e)}")
                raise self._broken from None
            cc_session._OPEN.append(self)  # 进程退出时关掉
        return self._ctx.request

    def _call(self, fn, url, **kw):
        r = fn(url, fail_on_status_code=False, timeout=self.timeout * 1000, **kw)
        try:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.body(), r.url
        finally:
            try:
                r.dispose()
            except Exception:  # noqa: BLE001
                pass

    def get(self, url, headers=None, follow=True):
        kw = {} if follow else {"max_redirects": 0}
        return self._call(self._request().get, url, headers=headers or {}, **kw)

    def post(self, url, body, headers=None):
        return self._call(self._request().post, url, headers=headers or {}, data=body, max_redirects=0)

    def _stop(self):
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            self._pw = None

    def close(self):
        if not self._own:  # 别人的浏览器上下文：不关、不存
            return
        if self._ctx is not None:
            import cc_session
            if self.host and self.home:  # 按「站点根/」取：装在子目录里时会话 cookie 的路径是 /moodle/
                cc_session._save_cookies(self._ctx, self.home, self.host.rstrip("/") + "/")
            try:
                self._ctx.close()
            except Exception:  # noqa: BLE001
                pass
            self._ctx = None
        self._stop()


def default_transport(home, timeout=60):
    if (brand.env("MOODLE_TRANSPORT") or "").strip().lower() == "urllib":
        return UrllibTransport(home=home, timeout=timeout)
    return PlaywrightTransport(home=home, timeout=timeout)


# ---------------------------------------------------------------- 客户端
class MoodleClient:
    """Moodle 只读客户端，形状尽量和 canvas_api.Canvas 一样（fetch / file_meta / download / close）。"""
    mode = "moodle"

    def __init__(self, host, home, transport=None, timeout=60, retries=2):
        self.host = normalize_host(host)
        if not self.host:
            raise MoodleError("没有 Moodle 网址")
        p = urllib.parse.urlparse(self.host)
        self.netloc = p.netloc
        self._origin, self._base = f"{p.scheme}://{p.netloc}".lower(), p.path.rstrip("/")
        self.home, self.timeout, self.retries = home, timeout, retries
        self.transport = transport or default_transport(home, timeout)
        if getattr(self.transport, "host", "") is None:
            self.transport.host = self.host
        self.site = None       # 上次读到的 M.cfg
        self._sesskey = None

    # ---- 地址
    def _rel(self, url):
        """本站地址 → 站内路径（带查询串）；别的网站返回 None。"""
        p = urllib.parse.urlparse(url or "")
        if f"{p.scheme}://{p.netloc}".lower() != self._origin:
            return None
        if self._base and not (p.path == self._base or p.path.startswith(self._base + "/")):
            return None
        rel = p.path[len(self._base):] or "/"
        return rel + ("?" + p.query if p.query else "")

    def _url(self, path_or_url):
        url = path_or_url if str(path_or_url).startswith("http") else \
            self.host + "/" + str(path_or_url).lstrip("/")
        if self._rel(url) is None:
            raise MoodleError(f"只访问本站，不访问别的网站：{url.split('?')[0]}")
        return url

    # ---- 发请求
    def _send(self, method, url, body=None, headers=None):
        """发一次（网络错误、429/5xx 有限重试）→ (status, headers, body, final_url)。不跟跳转。"""
        h = {"User-Agent": UA}
        h.update(headers or {})
        delay = 2
        for attempt in range(self.retries + 1):
            try:
                if method == "POST":
                    res = self.transport.post(url, body, h)
                else:
                    res = self.transport.get(url, h, follow=False)
            except CanvasError:
                raise  # 浏览器起不来之类：不当网络错误重试
            except Exception as e:  # noqa: BLE001  网络错误：和 Canvas 版一样当 URLError
                if attempt == self.retries:
                    raise urllib.error.URLError((str(e).strip().splitlines() or [type(e).__name__])[0][:200]) from None
                time.sleep(delay)
                delay *= 3
                continue
            status, hdrs = res[0], res[1]
            if status not in RETRY_CODES or attempt == self.retries:
                return res
            ra = hdrs.get("retry-after")
            time.sleep(min(float(ra), 30) if ra and str(ra).replace(".", "", 1).isdigit() else delay)
            delay *= 3
        raise MoodleError("unreachable")

    @staticmethod
    def _http_error(url, status, hdrs, body):
        return urllib.error.HTTPError(url, status, f"HTTP {status}", _message(hdrs), io.BytesIO(body))

    def _redirect(self, url, hdrs, probe):
        """3xx 的去向：本站内的普通地址返回它；登录页 / 别的网站 / 选课页 → 抛错。"""
        loc = urllib.parse.urljoin(url, hdrs.get("location") or "")
        rel = self._rel(loc)
        if rel is not None and rel.startswith("/login/"):
            raise _relogin()
        if rel is None or rel.startswith("/enrol/index.php"):
            if not probe or not self._logged_in():
                raise _relogin()  # SSO、访客进不了课：都要重新登录
            where = "别的网站" if rel is None else "选课页（没有这门课的访问权限）"
            raise MoodleError(f"{self._rel(url) or url} 被转到{where}，没有跟过去")
        return loc

    def _walk(self, url, accept, probe=True):
        """GET，只在本站内跟跳转 → (headers, body, final_url)；HTML 登录页 / 访客页抛 CanvasAuthError。"""
        for _ in range(MAX_HOPS):
            status, hdrs, body, _final = self._send("GET", url, headers={"Accept": accept})
            if status in REDIRECTS:
                url = self._redirect(url, hdrs, probe)
                continue
            if status >= 400:
                raise self._http_error(url, status, hdrs, body)
            if _is_html(hdrs, body) and _login_state(body.decode("utf-8", "replace")):
                raise _relogin()
            return hdrs, body, url
        raise MoodleError(f"跳转太多次：{self._rel(url) or url}")

    # ---- 登录状态和 sesskey
    def _load_cfg(self):
        """读一个已登录页面的 M.cfg（顺便缓存 sesskey）→ (cfg, html)。"""
        for path in ("/my/courses.php", "/"):
            try:
                _, body, _ = self._walk(self.host + path, "text/html", probe=False)
            except urllib.error.HTTPError as e:
                if e.code == 404 and path != "/":
                    continue
                raise
            html = body.decode("utf-8", "replace")
            cfg = _mcfg(html)
            if cfg and cfg.get("sesskey"):
                self.site, self._sesskey = cfg, str(cfg["sesskey"])
                return cfg, html
        raise MoodleError("已登录的页面里找不到 M.cfg.sesskey（学校的页面结构不认识）")

    def _logged_in(self):
        """探一下：还登录着返回 True；登录没了返回 False；探不出来按登录着算（原来的错照报）。"""
        try:
            self._load_cfg()
        except CanvasAuthError:
            self._sesskey = None
            return False
        except Exception:  # noqa: BLE001
            return True
        return True

    def sesskey(self):
        if not self._sesskey:
            self._load_cfg()
        return self._sesskey

    def whoami(self):
        """当前登录的人 → {"id", "name"}；id 在 4.5 以前的 Moodle 没有（None），name 取不到也是 None。"""
        cfg, html = self._load_cfg()
        return {"id": _user_id(cfg), "name": _user_name(html)}

    # ---- ajax
    def ajax(self, method, args=None):
        """调一个白名单里的只读函数，返回 data。"""
        if method not in AJAX_READ:
            raise MoodleError(f"不在只读白名单里，不调：{method}")
        body = json.dumps([{"index": 0, "methodname": method, "args": args or {}}]).encode("utf-8")
        for attempt in range(2):
            url = (f"{self.host}/lib/ajax/service.php?sesskey={urllib.parse.quote(self.sesskey())}"
                   f"&info={urllib.parse.quote(method)}")
            status, hdrs, raw, _ = self._send("POST", url, body, {
                "Content-Type": "application/json", "Accept": "application/json"})
            payload = self._ajax_payload(url, status, hdrs, raw)
            code, msg, data = _unpack(payload)
            if code is None:
                return data
            if code in ("invalidsesskey", "missingparam") and attempt == 0:
                self._sesskey = None  # sesskey 过期：重取一次
                continue
            raise self._ajax_error(method, code, msg)
        raise _relogin()  # 重取 sesskey 之后还是不对：会话坏了

    def _ajax_payload(self, url, status, hdrs, raw):
        if status in REDIRECTS:
            self._redirect(url, hdrs, probe=False)  # 登录页 / 别的网站 → 重新登录
            raise MoodleError("ajax 被转走了")
        if status >= 400:
            raise self._http_error(url.split("?")[0], status, hdrs, raw)
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            if _login_state(raw.decode("utf-8", "replace")):
                raise _relogin() from None
            raise MoodleError("ajax 返回的不是 JSON（学校的网关挡住了，或不是 Moodle）") from None

    def _ajax_error(self, method, code, msg):
        if code == "servicerequireslogin":
            return _relogin()
        if code == "requireloginerror" and not self._logged_in():
            return _relogin()  # 没选这门课也是这个码：先确认是不是真的掉线了
        return MoodleError(f"{method}: {code}" + (f"（{msg}）" if msg else ""), errorcode=code)

    # ---- 页面和文件
    def page(self, path_or_url):
        """GET 本站页面，返回 HTML 文本。"""
        _, body, _ = self._walk(self._url(path_or_url), "text/html,application/xhtml+xml")
        return body.decode("utf-8", "replace")

    def fetch(self, url, accept="*/*"):
        """下载本站文件（pluginfile）→ (headers, body)。"""
        hdrs, body, _ = self._walk(self._url(url), accept)
        return _message(hdrs), body

    def file_meta(self, x):
        """课件信息（Canvas 形状）。x 是 cmid（resource）或 pluginfile 地址（folder 里的文件）。"""
        x = str(x)
        if x.startswith("http"):
            return self._meta(x, self._url(x))
        if not x.isdigit():
            raise MoodleError(f"认不出的课件编号：{x}")
        url = f"{self.host}/mod/resource/view.php?id={x}&redirect=1"
        status, hdrs, body, _ = self._send("GET", url, headers={"Accept": "text/html"})
        if status in REDIRECTS:
            loc = self._redirect(url, hdrs, probe=True)
            if _pluginfile(self._rel(loc)):
                return self._meta(x, loc)
            return self._meta(x, None)  # 转回课程页之类：有访问限制，看不到
        if status in RETRY_CODES:
            raise self._http_error(url, status, hdrs, body)
        if status < 400 and _is_html(hdrs, body) and _login_state(body.decode("utf-8", "replace")):
            raise _relogin()
        return self._meta(x, None)  # 200 的说明页、403/404：看不到

    @staticmethod
    def _meta(x, url):
        name = None
        if url:
            p = urllib.parse.urlparse(url)
            at = p.path.find("/pluginfile.php")
            segs = _pluginfile(p.path[at:] + ("?" + p.query if p.query else "")) if at >= 0 else None
            name = (segs[-1] if segs else urllib.parse.unquote(p.path.rsplit("/", 1)[-1])) or None
        return {"id": x, "display_name": name, "filename": name, "url": url, "size": None,
                "locked_for_user": not url, "unlock_at": None, "updated_at": None,
                "lock_explanation": None if url else "打不开这个文件（可能有访问限制，或已被隐藏）"}

    def download(self, cmid, dest_dir, max_bytes=None):
        """和 Canvas.download 同样的返回形状：saved/name/bytes/updated_at，或 locked / skipped。"""
        meta = self.file_meta(cmid)
        name = meta.get("display_name") or meta.get("filename") or str(cmid)
        if meta.get("locked_for_user") or not meta.get("url"):
            return {"locked": True, "name": name, "unlock_at": meta.get("unlock_at"),
                    "lock_explanation": meta.get("lock_explanation")}
        import cc_downloads  # 文件名只当名字用，且必须落在 dest_dir 里
        _, body = self.fetch(meta["url"])
        if max_bytes and len(body) > max_bytes:  # Moodle 不先给大小：下完才知道，超了就不落盘
            return {"skipped": f"{len(body) / 1e6:.0f}MB", "name": name}
        os.makedirs(dest_dir, exist_ok=True)
        dest = cc_downloads.safe_dest(dest_dir, name)
        with open(dest, "wb") as f:
            f.write(body)
        return {"saved": dest, "name": name, "bytes": len(body), "updated_at": meta.get("updated_at")}

    def get(self, path, max_pages=None):
        raise MoodleError(f"这是 Moodle，没有 Canvas 接口：{str(path).split('?')[0]}")

    def close(self):
        self.transport.close()


# ---------------------------------------------------------------- 认学校（不登录）
def public_config(host, timeout=15):
    """不带任何凭据调 tool_mobile_get_public_config；是 Moodle 返回 data（含 wwwroot），否则 None。"""
    url = normalize_host(host)
    if not url:
        return None
    url += "/lib/ajax/service-nologin.php?info=tool_mobile_get_public_config"
    body = json.dumps([{"index": 0, "methodname": "tool_mobile_get_public_config", "args": {}}]).encode("utf-8")
    opener = urllib.request.build_opener(_NoRedirect())
    for _ in range(3):  # http→https、换主机名：跟着 POST 过去（只认同一个接口地址）
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA})
        try:
            with opener.open(req, timeout=timeout) as r:
                raw = r.read()
            break
        except urllib.error.HTTPError as e:
            loc = urllib.parse.urljoin(url, (e.headers or {}).get("Location") or "")
            if e.code not in REDIRECTS or "/lib/ajax/service-nologin.php" not in loc:
                return None
            url = loc
        except Exception:  # noqa: BLE001  连不上、超时：当不是 Moodle
            return None
    else:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except ValueError:
        return None
    if not (isinstance(payload, list) and payload and isinstance(payload[0], dict)
            and payload[0].get("error") is False and isinstance(payload[0].get("data"), dict)):
        return None
    data = payload[0]["data"]
    return data if data.get("wwwroot") else None
