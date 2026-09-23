"""登录模式：学校不让学生生成 token（或学校用的是 Moodle）时，用本人在浏览器里的登录只读 Canvas / Moodle。

- login 弹出一个浏览器窗口（本机的 Edge 或 Chrome，用档案目录里一份单独的资料夹 browser/，和用户平时的浏览器分开）。
  账号密码、多重验证都是用户自己在窗口里输，AI 不经手。登好了写 login.json，窗口自己关。
- 之后 collect / radar / study / 下课件走和 token 版同一套 /api/v1 只读接口，身份换成这份登录，不开窗口。
- 登录过期（Canvas 回 401 unauthenticated）→ 再跑 login。学校那边还记得用户的话，窗口弹一下就自己关。
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
COOKIES = "canvas-cookies.json"      # 放在 PROFILE 里：浏览器一关，会话 cookie 就丢了，自己存一份
MARKER = "login.json"                # {host, lms, name, user_id, at}：有它就是登录模式；没有 lms 的老文件是 Canvas
STATUS = "login-status.json"         # 登录窗口进程的状态和心跳
CHANNELS = ("msedge", "chrome", None)  # None = Playwright 自带的 Chromium（装过才有）
WINDOW_TIMEOUT = 600

ALT = ("学校不让学生生成 token（Approved Integrations 里没有 New Access Token，或者点了报错）就改用登录模式："
       "跑 login，用户在弹出的窗口里自己登录")
RELOGIN = "登录过期了：跑 login，让用户在弹出的窗口里重新登录（学校还记得他的话，窗口会自己关）"
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


def _save_cookies(ctx, home, host):
    try:
        cookies = ctx.cookies([host])
    except Exception:  # noqa: BLE001
        return
    path = os.path.join(profile_dir(home), COOKIES)
    jsave(path, cookies)
    if os.name != "nt":
        os.chmod(path, 0o600)


def _restore_cookies(ctx, home):
    now = time.time()
    live = [c for c in jload(os.path.join(profile_dir(home), COOKIES), []) or []
            if isinstance(c, dict) and (c.get("expires", -1) < 0 or c["expires"] > now)]
    if live:
        try:
            ctx.add_cookies(live)
        except Exception:  # noqa: BLE001  存的格式和新版 Playwright 对不上就算了，重新登录一次即可
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
            _save_cookies(self._ctx, self.home, self.host)  # Canvas 会续期会话，关之前存下最新的
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
                            # Moodle 可能装在子目录里：按「站点根/」取 cookie，路径是 /moodle/ 的会话 cookie 才取得到
                            _save_cookies(ctx, home, host.rstrip("/") + "/" if lms == "moodle" else host)
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


def _spawn(home, host, lms="canvas"):
    os.makedirs(_p(home, "logs"), exist_ok=True)
    cmd = [sys.executable, "-u", os.path.join(os.path.dirname(os.path.abspath(__file__)), "coach.py"),
           "login", "--worker", "--host", host, "--home", home, "--lms", lms]
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
WAITING_MSG = ("登录窗口已经打开。跟用户说：「弹出了一个浏览器窗口（被挡住了就在任务栏找），在里面登录 Canvas，"
               "账号密码、验证码都是你自己输；登好它会自己关，这是正常的。登好了回我一句。」用户说登好了就跑 login --check。"
               "用户说没看到窗口：先让他看任务栏；还是没有，就按宿主的办法申请在沙盒外重跑 login。" + HOST_BROWSER)
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
