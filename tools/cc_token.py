"""Canvas token：用户直接发到对话里，`token set` 从标准输入读进来，存进本机文件（只有本人能读）。

读取顺序：本机文件 → 环境变量 → Windows 用户级注册表 → macOS 钥匙串（后三个是老版本存的，照样认）。
文件排第一：用户再发一个新 token，就换掉以前不管存在哪儿的旧的。token 不打印、不进命令行参数、不写进别的文件。
"""
import os
import re
import subprocess
import sys
import tempfile
import threading

import brand
from canvas_api import CanvasAuthError

TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".config", brand.SLUG, "token")
TOKEN_FILE_SHOWN = f"~/.config/{brand.SLUG}/token"  # 提示文字里写的路径
TOKEN_LIKE = re.compile(r"(?<![A-Za-z0-9~])\d+~[A-Za-z0-9]{20,}(?![A-Za-z0-9~])")  # Canvas token：数字~一长串字母数字
ASK = (f"让用户去 Canvas → Account → Settings → Approved Integrations → New Access Token（Purpose 填 {brand.NAME}，"
       "Expires 设学期最后一天），整段复制，直接发到对话里；收到后跑 token set 存好")
HOW_TO_PASS = "token 从标准输入传进去（Bash 用 <<'EOF'，PowerShell 用管道），不放进命令参数"


def token():
    """读取顺序：TOKEN_FILE → 环境变量 → Windows 用户级注册表 → macOS 钥匙串。都不用重启宿主。"""
    t = None
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            t = f.read().strip()
    except OSError:
        t = None
    t = t or os.environ.get("CANVAS_TOKEN")
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
        raise CanvasAuthError(f"还没有 Canvas token（CANVAS_TOKEN）：{ASK}，不用重启。")
    return t.strip()


def read_stdin(timeout=5.0):
    """读标准输入；没人往里写（宿主没接管道、也没关掉）就等 timeout 秒当作空，不卡住。"""
    if sys.stdin is None:
        return ""
    got = []

    def work():
        try:
            got.append(sys.stdin.read())
        except (OSError, ValueError):
            got.append("")

    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(timeout)
    return got[0] if got else ""


def pick_token(raw):
    """用户发来的那段话 → token；认不出返回 None。整段只有 token 就原样用；夹着别的字，就挑唯一一个长得像 Canvas token 的。"""
    t = (raw or "").strip().strip("`'\"").strip()
    if not t:
        return None
    if not re.search(r"\s", t):
        return t
    hits = set(TOKEN_LIKE.findall(t))
    return hits.pop() if len(hits) == 1 else None


def save_token(t):
    """原子写进 TOKEN_FILE；Mac / Linux 上文件 600、目录 700（Windows 的用户目录本来就只有本人能读）。"""
    d = os.path.dirname(TOKEN_FILE)
    os.makedirs(d, exist_ok=True)
    if os.name != "nt":
        os.chmod(d, 0o700)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(t.strip() + "\n")
        os.replace(tmp, TOKEN_FILE)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return TOKEN_FILE


def forget_token():
    """删掉本机存的 token；删了返回 True，本来就没有返回 False。"""
    try:
        os.remove(TOKEN_FILE)
        return True
    except FileNotFoundError:
        return False
