"""登录模式：学校不让学生生成 token（或学校用的是 Moodle）时，用本人在浏览器里的登录只读 Canvas / Moodle。

- login 弹出一个浏览器窗口（本机的 Edge 或 Chrome，用档案目录里一份单独的资料夹 browser/，和用户平时的浏览器分开）。
  账号密码、多重验证都是用户自己在窗口里输，AI 不经手。登好了写 login.json，窗口自己关。
- 之后 collect / radar / study / 下课件走和 token 版同一套 /api/v1 只读接口，身份换成这份登录，不开窗口。
- 学生最多输一次：窗口里登好以后，这份浏览器里全部网站的登录记录（Canvas、学校的统一登录、别的网站）都存下来，
  每次用完浏览器再存一遍最新的（学校会在用的时候续期）。登录过期 → 先在后台（不开窗口）走一遍学校登录，
  学校还记得就自己进去；学校要重新输密码，才报「重新登录」，这时再跑 login。
- 要学校账号的别的网站（Zoom 录像、选课系统……）：start_signin 开窗口打开那个网站，学生登一次；
  存下的学校登录对走同一个登录的网站都管用。token 方式也用这份浏览器读网页，一样受益。
- 只读：登录模式不代发帖、不代交作业（cc_write 拦住）。login --forget 删掉 browser/ 和 login.json，回到 token。
- Moodle 只有登录模式：login.json 的 lms 是 moodle，读数据走 moodle_api（同一个浏览器资料夹）。
- 窗口在另起的进程里等（最多 10 分钟），login 本身最多等 --wait 秒就返回，宿主的命令超时卡不住它。
"""
import atexit
import datetime as dt
import email.message
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse

import brand
from canvas_api import RETRY_CODES, Canvas, CanvasAuthError, CanvasError
from cc_store import jload, jsave

PROFILE = "browser"                  # 档案目录下：本工具专用的浏览器资料夹（登录状态在里面）
COOKIES = "canvas-cookies.json"      # 放在 PROFILE 里：各网站浏览器一关就会丢的登录记录（会话 cookie；名字是老的，照旧认）
MARKER = "login.json"                # {host, lms, name, user_id, at}：有它就是登录模式；没有 lms 的老文件是 Canvas
STATUS = "login-status.json"         # 登录窗口进程的状态和心跳
SIGNIN = "signin-status.json"        # 给别的网站登学校账号的窗口：状态和心跳
CHANNELS = ("msedge", "chrome", None)  # None = Playwright 自带的 Chromium（装过才有）
WINDOW_TIMEOUT = 600

ALT = ("学校不让学生生成 token（Approved Integrations 里没有 New Access Token，或者点了报错）就改用登录模式："
       "跑 login，用户在弹出的窗口里自己登录")
RELOGIN = ("登录过期了，后台重进也没成（学校要重新输密码）：跑 login，让用户在弹出的窗口里重新登录；"
           "看到 Keep me signed in / 保持登录就勾上，能撑更久")
READ_ONLY = "登录模式只能读，不替用户发帖、发站内信或交作业：把要发的内容给用户，让他在 Canvas 页面上自己发"
NEED_PLAYWRIGHT = "登录模式要用 playwright（python -m pip install playwright）；跑 login 会先自动装"

_OPEN = []


class LoginUnavailable(CanvasError):
    pass


def _p(home, name):
    return os.path.join(home, name)


def profile_dir(home):
    return _p(home, PROFILE)


def read_login(home):
    d = jload(_p(home, MARKER))
    return d if isinstance(d, dict) and d.get("host") else None


def has_login(home):
    return read_login(home) is not None


def login_lms(info):
    """login.json 记的是哪种平台；老文件没写就是 Canvas。"""
    return "moodle" if str((info or {}).get("lms") or "").lower() == "moodle" else "canvas"


def _label(lms):
    return "Moodle" if lms == "moodle" else "Canvas"


def forget(home):
    """删掉这份登录；删了返回 True，本来就没有返回 False。"""
    gone = False
    for name in (MARKER, STATUS):
        try:
            os.remove(_p(home, name))
            gone = True
        except FileNotFoundError:
            pass
    if os.path.isdir(profile_dir(home)):
        shutil.rmtree(profile_dir(home), ignore_errors=True)
        gone = True
    return gone


def _sync_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise LoginUnavailable(NEED_PLAYWRIGHT) from None
    return sync_playwright


def _first_line(e):
    return (str(e).strip().splitlines() or [type(e).__name__])[0][:200]


def _launch(pw, home, headless, wait_lock=60):
    """用本工具自己的资料夹起浏览器：先 Edge，再 Chrome，再 Playwright 自带的。
    资料夹被本工具的另一个进程占着（登录窗口没关、后台下载在跑）就等一会儿再试。"""
    d = profile_dir(home)
    os.makedirs(d, exist_ok=True)
    kw = {"headless": headless, "accept_downloads": False}
    if not headless:
        kw["no_viewport"] = True
    deadline = time.time() + wait_lock
    for ch in CHANNELS:
        while True:
            try:
                return pw.chromium.launch_persistent_context(d, channel=ch, **kw) if ch else \
                    pw.chromium.launch_persistent_context(d, **kw)
            except Exception as e:  # noqa: BLE001  Playwright 的错误类型不稳定，按文字判断
                msg = str(e)
                if any(k in msg for k in ("is not found", "Executable doesn't exist", "not installed")):
                    break  # 这台电脑没有这个浏览器，换下一个
                if any(k in msg for k in ("existing browser session", "already in use", "has been closed", "exitCode")) \
                        and time.time() < deadline:
                    time.sleep(3)
                    continue
                raise LoginUnavailable(f"浏览器起不来：{_first_line(e)}；登录窗口还开着的话先关掉再试") from None
    raise LoginUnavailable("这台电脑上没找到 Edge 或 Chrome：装一个，或者跑 python -m playwright install chromium")


def _live(cookies):
    now = time.time()
    return [c for c in cookies or [] if isinstance(c, dict) and c.get("name")
            and (c.get("expires", -1) < 0 or c["expires"] > now)]


def _key(c):
    return c.get("name"), (c.get("domain") or "").lstrip("."), c.get("path") or "/"


def _save_cookies(ctx, home, host=None):
    """存下浏览器一关就会丢的那部分登录记录（会话 cookie）：Canvas、学校的统一登录、别的网站，下次靠这份放回去，
    学生就不用再登。长期的 cookie 浏览器资料夹自己加密记着，不另存明文。每次用完浏览器都存一遍（学校会在用的时候续期）。
    host 是老调用留下的，不再用来筛。"""
    try:
        cookies = [c for c in _live(ctx.cookies()) if c.get("expires", -1) < 0]
    except Exception:  # noqa: BLE001  浏览器已经关了：这次不存，留着上次的
        return
    path = os.path.join(profile_dir(home), COOKIES)
    jsave(path, cookies)
    if os.name != "nt":
        os.chmod(path, 0o600)


def _restore_cookies(ctx, home):
    """把存下的登录记录放回浏览器。浏览器资料夹自己记着的（长期 cookie，可能比存的新）不覆盖；坏的一条跳过，不连累别的。"""
    saved = _live(jload(os.path.join(profile_dir(home), COOKIES), []))
    if not saved:
        return
    try:
        have = {_key(c) for c in ctx.cookies()}
    except Exception:  # noqa: BLE001
        have = set()
    todo = [c for c in saved if _key(c) not in have]
    if not todo:
        return
    try:
        ctx.add_cookies(todo)
    except Exception:  # noqa: BLE001  有一条格式对不上（比如新版 Playwright）：一条条放，放不进的跳过
        for c in todo:
            try:
                ctx.add_cookies([c])
            except Exception:  # noqa: BLE001
                pass


# 学校登录页上要学生动手的输入框（UniKey / 邮箱 / 密码）：后台重进碰到它就停，不替学生填
LOGIN_INPUTS = ("input[type=password], input[type=email], input[name=identifier], input[name=username], "
                "input[name=loginfmt], input[name=j_username]")


def _wants_input(page):
    try:
        return any(el.is_visible() for el in page.query_selector_all(LOGIN_INPUTS))
    except Exception:  # noqa: BLE001  页面正在跳：当没有
        return False


def silent_relogin(ctx, home, host, lms="canvas", timeout=20):
    """会话过期时先在后台（不开窗口）走一遍学校登录：学校还记得就自己跳回来、登好，返回 True（顺手存下新的登录记录）；
    学校要输账号密码（页面上出现输入框）、出错或超时，返回 False，交给登录窗口。不填表、不点按钮。"""
    page = None
    try:
        page = ctx.new_page()
        resp = page.goto(host.rstrip("/") + ("/my/" if lms == "moodle" else "/login"), wait_until="domcontentloaded",
                         timeout=timeout * 1000)
        if resp is not None and resp.status >= 400 and not _on_site(page.url, host, lms):
            return False
        deadline = time.time() + timeout
        asked = 0
        while time.time() < deadline:
            if _on_site(page.url, host, lms):
                me = _whoami_moodle(ctx, host, home) if lms == "moodle" else _whoami(ctx.request, host)
                if me:
                    _save_cookies(ctx, home)
                    return True
            elif _wants_input(page):
                asked += 1
                if asked >= 2:  # 连着两次都停在要输入的页面：学校要学生自己登
                    return False
            page.wait_for_timeout(700)
        return False
    except Exception:  # noqa: BLE001  打不开、跳转出错：交给登录窗口
        return False
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass


def _strip_guard(body):
    """Canvas 给用登录（不是 token）拿的 JSON 可能加 while(1); 前缀。"""
    return body[9:] if body[:9] == b"while(1);" else body


def _on_canvas(url, host):
    p = urllib.parse.urlparse(url or "")
    return f"{p.scheme}://{p.netloc}" == host and not p.path.startswith(("/login", "/api/"))


def _on_moodle(url, host):
    """页面在这个 Moodle 站点里（站点根可能带子目录），而且不在登录页。"""
    u = (url or "").split("#")[0].split("?")[0]
    base = host.rstrip("/")
    if not (u.lower() == base.lower() or u.lower().startswith(base.lower() + "/")):
        return False
    return not u[len(base):].startswith("/login/")


def _on_site(url, host, lms):
    return _on_moodle(url, host) if lms == "moodle" else _on_canvas(url, host)


def _whoami_moodle(ctx, host, home):
    """用登录窗口这个浏览器的会话问一次 Moodle：登好了返回 {id, name}，没登好（或还是访客）返回 None。
    问的请求走 context.request（和窗口同一份 cookie），不动用户正在看的页面。"""
    try:
        import moodle_api
        me = moodle_api.MoodleClient(host, home, transport=moodle_api.PlaywrightTransport(context=ctx)).whoami()
    except Exception:  # noqa: BLE001  没登录、会话还没建好、页面在跳：下一轮再看
        return None
    return me if isinstance(me, dict) else None  # whoami 不报错就是登好了；老版本 Moodle 可能没有 id


def _whoami(request, host):
    try:
        r = request.get(host + "/api/v1/users/self", headers={"Accept": "application/json"},
                        fail_on_status_code=False, max_redirects=0, timeout=20000)
        if r.status != 200:
            return None
        me = json.loads(_strip_guard(r.body()).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return me if isinstance(me, dict) and me.get("id") else None


class SessionCanvas(Canvas):
    """和 Canvas 一样的只读客户端，身份用 login 存下的登录。第一次请求时在后台起浏览器（不开窗口）。"""
    mode = "session"

    def __init__(self, host, home, **kw):
        super().__init__(host, None, **kw)
        self.home = home
        self._pw = self._ctx = self._broken = None
        self._relogged = False  # 后台重进过一次了：再过期就直接报「重新登录」，不来回试

    def _request(self):
        if self._broken:  # 起过一次没起来：后面的请求直接报同一个错，不再一遍遍起浏览器
            raise self._broken
        if self._ctx is None:
            try:
                self._pw = _sync_playwright()().start()
                self._ctx = _launch(self._pw, self.home, headless=True)
                _restore_cookies(self._ctx, self.home)
            except Exception as e:  # noqa: BLE001
                if self._pw is not None:
                    try:
                        self._pw.stop()
                    except Exception:  # noqa: BLE001
                        pass
                    self._pw = None
                self._broken = e if isinstance(e, CanvasError) else LoginUnavailable(f"浏览器起不来：{_first_line(e)}")
                raise self._broken from None
            _OPEN.append(self)
        return self._ctx.request

    def close(self):
        if self._ctx is not None:
            _save_cookies(self._ctx, self.home)  # Canvas 和学校登录会续期，关之前存下最新的
            try:
                self._ctx.close()
            except Exception:  # noqa: BLE001
                pass
            self._ctx = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            self._pw = None

    def fetch(self, url, accept="application/json"):
        try:
            return self._fetch(url, accept)
        except CanvasAuthError:
            if self._relogged or self._ctx is None:
                raise
            self._relogged = True  # 会话过期：先在后台走一遍学校登录，学校还记得就接着读，学生什么都不用做
            if not silent_relogin(self._ctx, self.home, self.host):
                raise
            return self._fetch(url, accept)

    def _fetch(self, url, accept):
        headers = {"Accept": accept, "User-Agent": f"{brand.SLUG}/2 (read-only; login)"}
        req = self._request()  # 浏览器起不来是另一回事，不当网络错误重试
        delay = 2
        for attempt in range(self.retries + 1):
            try:
                r = req.get(url, headers=headers, timeout=self.timeout * 1000, fail_on_status_code=False)
                status, body = r.status, r.body()
            except Exception as e:  # noqa: BLE001  网络错误：和 token 版一样当 URLError
                if attempt == self.retries:
                    raise urllib.error.URLError(_first_line(e)) from None
                time.sleep(delay)
                delay *= 3
                continue
            hdrs = email.message.Message()  # 和 urllib 一样按名字取、不分大小写（翻页要读 Link）
            ha = r.headers_array
            for h in (ha() if callable(ha) else ha):  # 有的版本是方法，有的是属性
                hdrs[h["name"]] = h["value"]
            if status < 400:
                final = urllib.parse.urlparse(r.url)
                if f"{final.scheme}://{final.netloc}" == self.host and final.path.startswith("/login"):
                    raise CanvasAuthError(RELOGIN)  # 下载链接被转到登录页：会话没了
                return hdrs, _strip_guard(body)
            if status == 401 and b"unauthenticated" in body:
                raise CanvasAuthError(RELOGIN)  # 没登录；别的 401 是「没有权限」，照 token 版的 HTTPError 处理
            if status not in RETRY_CODES or attempt == self.retries:
                raise urllib.error.HTTPError(url, status, r.status_text, hdrs, io.BytesIO(body))
            ra = hdrs.get("Retry-After")
            time.sleep(min(float(ra), 30) if ra and str(ra).replace(".", "", 1).isdigit() else delay)
            delay *= 3
        raise CanvasError("unreachable")


def close_all():
    while _OPEN:
        _OPEN.pop().close()


atexit.register(close_all)


# ---------------------------------------------------------------- login window
def _status(home):
    return jload(_p(home, STATUS), {}) or {}


def _set_status(home, host, state, message="", lms=None):
    s = {"state": state, "host": host, "message": message, "pid": os.getpid(), "at": time.time()}
    if lms:
        s["lms"] = lms
    jsave(_p(home, STATUS), s)


def _window_alive(s):
    """登录窗口进程还在：状态是 starting / waiting，而且心跳没断（起浏览器可能要等占用，给久一点）。"""
    age = time.time() - float(s.get("at") or 0)
    return (s.get("state") == "starting" and age < 90) or (s.get("state") == "waiting" and age < 20)


def worker(home, host, timeout=WINDOW_TIMEOUT, lms="canvas"):
    """另起的进程里跑：开窗口、等用户登录、登好写 login.json、关窗口。每 2 秒写一次心跳。
    「登好了」= 有页面在本站、不在登录页，而且用这份会话问得到本人（Canvas：/users/self；Moodle：moodle_api 的 whoami）。"""
    def st(state, message=""):  # 心跳里带上平台，check 按它说话
        _set_status(home, host, state, message, lms)

    st("starting")
    try:
        with _sync_playwright()() as pw:
            ctx = _launch(pw, home, headless=False)
            try:
                _restore_cookies(ctx, home)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                start = host + ("/my/" if lms == "moodle" else "/")  # Moodle 首页可能不用登录；/my/ 没登录会转去登录页
                try:
                    page.goto(start, wait_until="domcontentloaded", timeout=60000)
                except Exception:  # noqa: BLE001  学校登录页跳得慢、或者用户点得快，下面照样等
                    pass
                deadline = time.time() + timeout
                while time.time() < deadline:
                    pages = [p for p in ctx.pages if not p.is_closed()]
                    if not pages:
                        st("closed", "登录窗口被关掉了，还没登好；要登就再跑 login")
                        return 1
                    if any(_on_site(p.url, host, lms) for p in pages):
                        me = _whoami_moodle(ctx, host, home) if lms == "moodle" else _whoami(ctx.request, host)
                        if me:
                            _save_cookies(ctx, home)  # Canvas / Moodle 的登录连同学校统一登录一起存：以后过期了能在后台自己重进
                            now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
                            jsave(_p(home, MARKER), {"host": host, "lms": lms, "name": me.get("name"), "user_id": me.get("id"), "at": now})
                            st("done", f"登好了：{me.get('name') or '你的账号'}")
                            return 0
                    st("waiting", "登录窗口开着，等用户登录")
                    try:
                        pages[0].wait_for_timeout(2000)
                    except Exception:  # noqa: BLE001  等的时候页面被关了
                        time.sleep(0.5)
                st("timeout", f"{timeout // 60} 分钟没登好，窗口先关了；要登就再跑 login")
                return 1
            finally:
                try:
                    ctx.close()
                except Exception:  # noqa: BLE001
                    pass
    except CanvasError as e:
        st("failed", str(e))
        return 2
    except Exception as e:  # noqa: BLE001
        st("failed", f"登录窗口出错：{_first_line(e)}")
        return 2


def _spawn(home, host, lms="canvas", site=None):
    os.makedirs(_p(home, "logs"), exist_ok=True)
    what = ["--site", site] if site else ["--host", host, "--lms", lms]  # site：给别的网站登学校账号的窗口
    cmd = [sys.executable, "-u", os.path.join(os.path.dirname(os.path.abspath(__file__)), "coach.py"),
           "login", "--worker", "--home", home] + what
    log = open(_p(home, os.path.join("logs", "login.log")), "a", encoding="utf-8")
    kw = {"stdin": subprocess.DEVNULL, "stdout": log, "stderr": subprocess.STDOUT, "close_fds": True}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    else:
        kw["start_new_session"] = True
    try:
        subprocess.Popen(cmd, **kw)
    finally:
        log.close()


HOST_BROWSER = f"不要改用宿主自带的浏览器让用户登录：{brand.NAME}读不到那里的登录，用户会白登一次"
KEEP = ("看到 Keep me signed in / 保持登录就勾上，手机验证那步有『这台设备一段时间内不用再验证』也勾上，"
        "以后就不用再登")
WAITING_MSG = ("登录窗口已经打开。跟用户说：「弹出了一个浏览器窗口（被挡住了就在任务栏找），在里面登录 Canvas，"
               f"账号密码、验证码都是你自己输；{KEEP}。登好它会自己关，这是正常的。登好了回我一句。」用户说登好了就跑 login --check。"
               "用户说没看到窗口：先请对方看任务栏；还是没有，就按宿主的办法申请在沙盒外重跑 login。" + HOST_BROWSER)
SIGNIN_WAITING = ("登录窗口已经打开。跟学生说：「弹出了一个浏览器窗口（被挡住了就在任务栏找），在里面用学校账号登一次，"
                  f"账号密码、手机验证都是你自己来；{KEEP}。登好它会自己关，以后这个网站和走同一个学校登录的网站都不用再登。"
                  "登好了回我一句。」学生说登好了，就再跑一次 browse 这个网址（不带 --sign-in）。" + HOST_BROWSER)
NO_WINDOW = ("这条命令跑在用户看不到的桌面上（多半是宿主在沙盒里运行命令），这里弹出的登录窗口用户看不见，所以没有开。"
             "按宿主的办法申请在沙盒外运行这条 login（Codex：申请提升权限，让用户批准一次），再跑一次。" + HOST_BROWSER)


def waiting_msg(lms="canvas"):
    return WAITING_MSG if lms != "moodle" else WAITING_MSG.replace("登录 Canvas", "登录 Moodle")


def visible_desktop():
    """这个进程在不在用户看得见的桌面上。Windows 上交互式的是窗口站 WinSta0 + 桌面 Default；
    沙盒、服务、别的用户身份下开的窗口，用户看不到。认不出就当看得见，不挡人。"""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetProcessWindowStation.restype = wintypes.HANDLE
        user32.GetThreadDesktop.restype = wintypes.HANDLE
        user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
        user32.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                                     ctypes.POINTER(wintypes.DWORD)]

        def name(h):
            buf, need = ctypes.create_unicode_buffer(256), wintypes.DWORD()
            ok = h and user32.GetUserObjectInformationW(h, 2, buf, ctypes.sizeof(buf), ctypes.byref(need))  # 2 = UOI_NAME
            return buf.value if ok else None

        station = name(user32.GetProcessWindowStation())
        desk = name(user32.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId()))
    except Exception:  # noqa: BLE001
        return True
    if not station or not desk:
        return True
    return station.lower() == "winsta0" and desk.lower() == "default"


def start_login(home, host, wait=90, lms="canvas"):
    """开登录窗口（已经开着就不重复开），最多等 wait 秒。返回 {state, message, ...}。
    这个进程在用户看不到的桌面上（沙盒）就不开：开了用户也看不见，AI 还会以为窗口在等人。"""
    if not visible_desktop():
        return {"state": "no_window", "host": host, "message": NO_WINDOW}
    s = _status(home)
    if not (_window_alive(s) and s.get("host") == host):
        _set_status(home, host, "starting", lms=lms)
        _spawn(home, host, lms)
    t0 = time.time()
    while True:
        s = _status(home)
        state = s.get("state")
        if state == "done":
            info = read_login(home) or {}
            return {"state": "done", "host": host, "name": info.get("name"),
                    "message": f"登好了（{info.get('name') or '你的账号'} @ {host}）。之后读 {_label(lms)} 都用这份登录，不用 token"}
        if state in ("closed", "timeout", "failed"):
            return {"state": state, "host": host, "message": s.get("message") or state}
        if not _window_alive(s):
            return {"state": "failed", "host": host, "message": f"登录窗口没起来，看 {_p(home, os.path.join('logs', 'login.log'))}"}
        if time.time() - t0 >= wait:
            return {"state": "waiting", "host": host, "message": waiting_msg(lms)}
        time.sleep(1)


# ---------------------------------------------------------------- 给别的网站登学校账号的窗口
def _site_host(url):
    h = (urllib.parse.urlparse(url or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _signed_in_on(page, target):
    """窗口停在要读的那个网站上（不在登录页），页面上也没有登录框了：算登好。"""
    u = urllib.parse.urlparse(page.url or "")
    host = _site_host(page.url)
    if not host or not (host == target or host.endswith("." + target)):
        return False
    if re.search(r"(?i)/(log-?in|sign-?in|sso|saml2?|cas|auth|oauth2?)(/|$)", u.path or ""):
        return False
    return not _wants_input(page)


def signin_worker(home, url, timeout=WINDOW_TIMEOUT, headless=False):
    """另起的进程里跑：开窗口打开要读的网站，学生自己登学校账号（AI 不经手）。窗口回到这个网站、没有登录框了，
    就把这份浏览器里全部网站的登录记录存下来，关窗口。每秒写一次心跳（signin-status.json）。headless 只给测试用。"""
    target = _site_host(url)

    def st(state, message=""):
        jsave(_p(home, SIGNIN), {"state": state, "url": url, "message": message, "pid": os.getpid(), "at": time.time()})

    st("starting")
    try:
        with _sync_playwright()() as pw:
            ctx = _launch(pw, home, headless=headless)
            try:
                _restore_cookies(ctx, home)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                except Exception:  # noqa: BLE001  学校登录页跳得慢，下面照样等
                    pass
                deadline = time.time() + timeout
                ok = 0
                while time.time() < deadline:
                    pages = [p for p in ctx.pages if not p.is_closed()]
                    if not pages:
                        _save_cookies(ctx, home)  # 学生自己关了窗口：登好了的也照样存下
                        st("closed", "登录窗口被关掉了。登好了的话再读一次就行；还没登好、要登，就再跑 browse 网址 --sign-in")
                        return 1
                    ok = ok + 1 if any(_signed_in_on(p, target) for p in pages) else 0
                    if ok >= 2:  # 连着两次都在这个网站上、没有登录框：登好了（单点登录中途会路过一下）
                        _save_cookies(ctx, home)
                        st("done", f"登好了：{target}")
                        return 0
                    st("waiting", "登录窗口开着，等学生登录")
                    try:
                        pages[0].wait_for_timeout(1000)
                    except Exception:  # noqa: BLE001  等的时候页面被关了
                        time.sleep(0.5)
                st("timeout", f"{timeout // 60} 分钟没登好，窗口先关了；要登就再跑 browse 网址 --sign-in")
                return 1
            finally:
                try:
                    ctx.close()
                except Exception:  # noqa: BLE001
                    pass
    except CanvasError as e:
        st("failed", str(e))
        return 2
    except Exception as e:  # noqa: BLE001
        st("failed", f"登录窗口出错：{_first_line(e)}")
        return 2


def start_signin(home, url, wait=90):
    """给要登录的网站开窗口（同一个网址的窗口已经开着就不重复开），最多等 wait 秒。返回 {state, url, message}。
    这个进程在用户看不到的桌面上（沙盒）就不开。"""
    if not visible_desktop():
        return {"state": "no_window", "url": url, "message": NO_WINDOW.replace("这条 login", "这条 browse --sign-in")}
    s = jload(_p(home, SIGNIN), {}) or {}
    if not (_window_alive(s) and s.get("url") == url):
        jsave(_p(home, SIGNIN), {"state": "starting", "url": url, "pid": os.getpid(), "at": time.time()})
        _spawn(home, None, site=url)
    t0 = time.time()
    while True:
        s = jload(_p(home, SIGNIN), {}) or {}
        state = s.get("state")
        if state == "done":
            return {"state": "done", "url": url, "message": s.get("message") or "登好了"}
        if state in ("closed", "timeout", "failed"):
            return {"state": state, "url": url, "message": s.get("message") or state}
        if not _window_alive(s):
            return {"state": "failed", "url": url, "message": f"登录窗口没起来，看 {_p(home, os.path.join('logs', 'login.log'))}"}
        if time.time() - t0 >= wait:
            return {"state": "waiting", "url": url, "message": SIGNIN_WAITING}
        time.sleep(1)


def check(home, host=None):
    """不开窗口：看登录窗口还在不在等，或者用存下的登录问一次本人（Canvas：/users/self；Moodle：whoami）。"""
    s = _status(home)
    if _window_alive(s):
        return {"state": "waiting", "host": s.get("host"), "message": waiting_msg(s.get("lms")).split("。")[0] + "，还没登好"}
    info = read_login(home)
    if not info:
        msg = s.get("message") if s.get("state") in ("closed", "timeout", "failed") else "还没有登录过（跑 login）"
        return {"state": "none", "host": host, "message": msg}
    if login_lms(info) == "moodle":
        return _check_moodle(home, info)
    api = SessionCanvas(host or info["host"], home, timeout=30, retries=0)
    try:
        me = api.get("/api/v1/users/self")
    except CanvasAuthError as e:
        return {"state": "expired", "host": api.host, "message": str(e)}
    finally:
        api.close()
    return {"state": "ok", "host": api.host, "name": (me or {}).get("name"),
            "message": f"登录有效：{(me or {}).get('name') or '你的账号'} @ {api.host}"}


def _check_moodle(home, info):
    """Moodle 的登录还有没有效：用存下的登录问一次 whoami。站点根以 login.json 为准（可能带子目录）。"""
    import moodle_api
    host = info["host"]
    api = moodle_api.MoodleClient(host, home, timeout=30, retries=0)
    try:
        me = api.whoami()
    except CanvasAuthError as e:
        return {"state": "expired", "host": host, "lms": "moodle", "message": str(e)}
    finally:
        api.close()
    return {"state": "ok", "host": host, "lms": "moodle", "name": (me or {}).get("name"),
            "message": f"登录有效：{(me or {}).get('name') or '你的账号'} @ {host}（Moodle）"}
