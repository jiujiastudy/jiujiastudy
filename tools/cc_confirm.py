"""往 Canvas 写东西之前的最后一道闸：弹一个系统确认窗口，只有用户本人点「确定」才放行。

AI 看得到命令输出，但点不了这个窗口；窗口弹不出来（没有桌面、沙盒拦截）就一律不放行。
默认按钮是「取消」，误按回车不会发出去。窗口 110 秒没人点就自动关闭（也不发），赶在宿主的命令超时之前。
ask() 返回 "ok" / "cancel" / "timeout" / "unavailable"。
"""
import os
import shutil
import subprocess
import sys

import brand

TITLE = f"{brand.NAME} · 请确认"


def _secs(default=110):
    try:
        return max(3, int(brand.env("CONFIRM_TIMEOUT") or default))
    except ValueError:
        return default


def _win(text, title, secs):
    import ctypes
    u = ctypes.windll.user32
    flags = 0x1 | 0x20 | 0x100 | 0x10000 | 0x40000  # 确定/取消 · 问号 · 默认按钮是取消 · 抢前台 · 置顶
    f = getattr(u, "MessageBoxTimeoutW", None)
    if f is not None:
        f.restype = ctypes.c_int
        f.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_ushort, ctypes.c_uint]
        r = f(None, text, title, flags, 0, secs * 1000)
    else:
        r = u.MessageBoxW(None, text, title, flags)
    return {1: "ok", 2: "cancel", 32000: "timeout"}.get(r, "unavailable")


def _mac(text, title, secs):
    def q(s):
        return s.replace("\\", "\\\\").replace('"', '\\"')
    script = (f'display dialog "{q(text)}" with title "{q(title)}" buttons {{"取消", "确认发送"}} '
              f'default button "取消" cancel button "取消" with icon caution giving up after {secs}')
    try:
        p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=secs + 15)
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    if p.returncode != 0:
        return "cancel" if "-128" in (p.stderr or "") else "unavailable"
    out = p.stdout or ""
    if "gave up:true" in out:
        return "timeout"
    return "ok" if "确认发送" in out else "cancel"


def _linux(text, title, secs):
    if not shutil.which("zenity") or not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return "unavailable"
    try:
        p = subprocess.run(["zenity", "--question", f"--title={title}", f"--text={text}", "--ok-label=确认发送",
                            "--cancel-label=取消", f"--timeout={secs}", "--no-markup"], capture_output=True, timeout=secs + 15)
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    return {0: "ok", 1: "cancel", 5: "timeout"}.get(p.returncode, "unavailable")


def ask(text, title=TITLE, secs=None):
    if brand.env("NO_DIALOG"):
        return "unavailable"
    secs = secs or _secs()
    try:
        if sys.platform == "win32":
            return _win(text, title, secs)
        if sys.platform == "darwin":
            return _mac(text, title, secs)
        return _linux(text, title, secs)
    except Exception:  # noqa: BLE001
        return "unavailable"
