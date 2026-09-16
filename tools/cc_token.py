"""Canvas token：从哪读（环境变量 → Windows 用户级注册表 → macOS 钥匙串 → 本机文件），
以及让用户在对话之外粘 token 的窗口。token 不打印、不写盘、不进命令行参数。
"""
import os
import subprocess
import sys

import brand
from canvas_api import CanvasAuthError

TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".config", brand.SLUG, "token")
TOKEN_FILE_SHOWN = f"~/.config/{brand.SLUG}/token"  # 提示文字里写的路径


def token():
    """读取顺序：环境变量 → Windows 用户级注册表 → macOS 钥匙串 → TOKEN_FILE。都不用重启宿主。"""
    t = os.environ.get("CANVAS_TOKEN")
    if not t and sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                t = winreg.QueryValueEx(k, "CANVAS_TOKEN")[0]
        except OSError:
            t = None
    if not t and sys.platform == "darwin":
        try:
            import subprocess
            r = subprocess.run(["security", "find-generic-password", "-s", brand.KEYCHAIN_SERVICE, "-w"],
                               capture_output=True, text=True, timeout=20)
            t = r.stdout.strip() if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            t = None
    if not t:
        try:
            with open(TOKEN_FILE, encoding="utf-8") as f:
                t = f.read().strip()
        except OSError:
            t = None
    if not t:
        hint = {"win32": "让我弹出「环境变量」窗口（doctor --env-dialog），新建 CANVAS_TOKEN 粘进去，不用重启。",
                "darwin": "让我打开「终端」把 token 存进钥匙串（doctor --env-dialog），不用重启；或在 ~/.zshrc 加 export CANVAS_TOKEN=… 后重开对话所在的应用。"
                }.get(sys.platform, f"export CANVAS_TOKEN=…，或把 token 写进 {TOKEN_FILE_SHOWN}。")
        raise CanvasAuthError("CANVAS_TOKEN 未设置。" + hint)
    return t.strip()


def open_token_prompt():
    """让用户在对话之外粘 token：Windows 弹「环境变量」窗口；macOS 打开「终端」存进钥匙串。"""
    if sys.platform == "win32":
        subprocess.Popen(["rundll32", "sysdm.cpl,EditEnvironmentVariables"])
        return "win"
    if sys.platform == "darwin":
        cmd = ('security add-generic-password -a "$USER" -s ' + brand.KEYCHAIN_SERVICE + ' -U -w '
               '&& echo "已存进钥匙串。回到对话再说一次「体检」。"')
        osa = 'tell application "Terminal" to do script "' + cmd.replace("\\", "\\\\").replace('"', '\\"') + '"'
        subprocess.Popen(["osascript", "-e", 'tell application "Terminal" to activate', "-e", osa])
        return "mac"
    return None
