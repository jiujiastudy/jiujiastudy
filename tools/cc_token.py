"""Canvas token：从哪读（环境变量 → 本机文件 → Windows 用户级注册表 → macOS 钥匙串），
以及让用户在对话之外粘 token 的小窗口。token 不打印、不进命令行参数、不进对话。
"""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import time

import brand
from canvas_api import CanvasAuthError

TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".config", brand.SLUG, "token")
TOKEN_FILE_SHOWN = f"~/.config/{brand.SLUG}/token"  # 提示文字里写的路径
TOOLS = os.path.dirname(os.path.abspath(__file__))


def token():
    """读取顺序：环境变量 → TOKEN_FILE（小窗口存的）→ Windows 用户级注册表 → macOS 钥匙串。都不用重启宿主。
    文件排在注册表和钥匙串前面：在小窗口里重新粘一次，就能换掉以前存在别处的旧 token。"""
    t = os.environ.get("CANVAS_TOKEN")
    if not t:
        try:
            with open(TOKEN_FILE, encoding="utf-8") as f:
                t = f.read().strip()
        except OSError:
            t = None
    if not t and sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                t = winreg.QueryValueEx(k, "CANVAS_TOKEN")[0]
        except OSError:
            t = None
    if not t and sys.platform == "darwin":
        try:
            r = subprocess.run(["security", "find-generic-password", "-s", brand.KEYCHAIN_SERVICE, "-w"],
                               capture_output=True, text=True, timeout=20)
            t = r.stdout.strip() if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            t = None
    if not t:
        raise CanvasAuthError("还没有 Canvas token（CANVAS_TOKEN）。让我弹出填学校和 token 的小窗口（doctor --token-window），不用重启。")
    return t.strip()


def token_problem(t):
    """粘进来的东西像不像 token；像就返回 None，不像返回一句给人看的原因。"""
    t = (t or "").strip()
    if not t:
        return "先把 token 粘进来"
    if re.search(r"\s", t) or len(t) < 20:
        return "这不像 token：token 是一整串没有空格的字母和数字，回 Canvas 重新复制一次"
    return None


def save_token(t):
    """原子写进 TOKEN_FILE；非 Windows 上文件权限 600、目录 700（Windows 的用户目录本来就只有本人能读）。"""
    t = t.strip()
    d = os.path.dirname(TOKEN_FILE)
    os.makedirs(d, exist_ok=True)
    if os.name != "nt":
        os.chmod(d, 0o700)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(t + "\n")
        os.replace(tmp, TOKEN_FILE)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return TOKEN_FILE


def _can_show_window():
    if importlib.util.find_spec("tkinter") is None:
        return False
    return sys.platform in ("win32", "darwin") or bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def open_token_window(home, wait=8.0):
    """弹「填学校 + 粘 token」的小窗口（tools/token_window.py，另起进程，命令立刻返回）。
    返回 "window"；这台电脑弹不了（没有 tkinter / 没有桌面 / 窗口起不来）就退回系统自带的办法：
    Windows「环境变量」窗口 → "env"，macOS 终端存钥匙串 → "keychain"；都不行返回 None。
    设了 NO_DIALOG 环境变量（brand.env）时什么都不弹（测试、无人值守）。"""
    if brand.env("NO_DIALOG"):
        return None
    if _can_show_window():
        ready = os.path.join(tempfile.gettempdir(), f"{brand.SLUG}-token-window-{os.getpid()}-{int(time.time())}.ready")
        exe = sys.executable
        kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
        if sys.platform == "win32":
            pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
            exe = pyw if os.path.exists(pyw) else exe
            kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP：对话命令结束了窗口也还在
        else:
            kw["start_new_session"] = True
        try:
            p = subprocess.Popen([exe, os.path.join(TOOLS, "token_window.py"), "--home", home, "--ready", ready], **kw)
            end = time.time() + wait
            while time.time() < end:
                if os.path.exists(ready):
                    try:
                        os.remove(ready)
                    except OSError:
                        pass
                    return "window"
                if p.poll() is not None:
                    break  # 窗口进程自己退了：多半 Tk 起不来，走下面的老办法
                time.sleep(0.1)
            else:
                return "window"  # 还在起（慢电脑），当它弹出来了
        except OSError:
            pass
    return _open_system_prompt()


def _open_system_prompt():
    """老办法：Windows 弹「环境变量」窗口；macOS 打开「终端」存进钥匙串。"""
    try:
        if sys.platform == "win32":
            subprocess.Popen(["rundll32", "sysdm.cpl,EditEnvironmentVariables"])
            return "env"
        if sys.platform == "darwin":
            cmd = ('security add-generic-password -a "$USER" -s ' + brand.KEYCHAIN_SERVICE + ' -U -w '
                   '&& echo "已存进钥匙串。回到对话说一句「好了」。"')
            osa = 'tell application "Terminal" to do script "' + cmd.replace("\\", "\\\\").replace('"', '\\"') + '"'
            subprocess.Popen(["osascript", "-e", 'tell application "Terminal" to activate', "-e", osa])
            return "keychain"
    except OSError:
        pass
    return None
