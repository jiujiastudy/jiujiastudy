"""路径与宿主：程序在哪、资料夹和机器档案在哪、给宿主看的 python / coach 命令、宿主是谁。"""
import os
import re
import shlex
import sys

import brand
from cc_store import get_key


def tools_dir():
    return os.path.dirname(os.path.abspath(__file__))


def skill_dir():
    return os.path.dirname(tools_dir())


def fwd(p):
    return str(p).replace("\\", "/")


def python_cmd(shell=None):
    """Return the current interpreter, quoted for the host's displayed shell."""
    exe = sys.executable or ("python" if sys.platform == "win32" else "python3")
    if sys.platform == "win32":
        if shell is None:
            # A skill installed under .codex normally runs in PowerShell;
            # Claude/Git Bash and cmd can invoke the quoted path directly.
            shell = "portable" if agent_kind() == "claude" else "powershell"
        return f'& "{fwd(exe)}"' if shell == "powershell" else f'"{fwd(exe)}"'
    return shlex.quote(exe)


def coach_cmd(shell=None):
    return f'{python_cmd(shell)} "{fwd(os.path.join(tools_dir(), "coach.py"))}"'


ROOT_NAME = brand.NAME  # 桌面上的资料夹名
WEEK_PAGE = "本周清单.html"  # 资料夹根目录那张周页：产品叫什么是一回事，文件名要让人一眼看懂
LEGACY_HOME = os.path.join(os.path.expanduser("~"), brand.LEGACY_HOME_DIRNAME)  # 兼容旧版档案


def desktop_dir():
    """真正的桌面目录（Windows 可能在 OneDrive 里，从 User Shell Folders 读）；没有桌面就用 ~。"""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
                d = os.path.expandvars(winreg.QueryValueEx(k, "Desktop")[0])
            if os.path.isdir(d):
                return d
        except OSError:
            pass
    d = os.path.join(os.path.expanduser("~"), "Desktop")
    return d if os.path.isdir(d) else os.path.expanduser("~")


def default_root():
    return os.path.join(desktop_dir(), ROOT_NAME)


def root_dir(cfg=None):
    """给人看的资料夹：每门课一个文件夹（课件 / 产出），根目录放本周清单和 deadline 雷达。
    优先级：环境变量 brand.env_name("ROOT")（旧版的名字也认）→ config.root → 桌面上的 ROOT_NAME。"""
    r = brand.env("ROOT") or (cfg or {}).get("root") or default_root()
    return os.path.normpath(os.path.expanduser(r))


def home_dir(override=None):
    """机器档案（config / state / raw / plans / reports）。老用户仍在 LEGACY_HOME；新用户在资料夹里的 .coach。
    优先级：--home → 环境变量 brand.env_name("HOME")（旧版的名字也认）→ LEGACY_HOME（有 config.json 时）→ 资料夹/.coach。"""
    h = override or brand.env("HOME")
    if not h:
        h = LEGACY_HOME if os.path.exists(os.path.join(LEGACY_HOME, "config.json")) else os.path.join(default_root(), ".coach")
    return os.path.normpath(h)


def safe_name(s, limit=80):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", str(s or "")).strip()
    s = re.sub(r"\s+", " ", s).rstrip(". ")
    return s[:limit] or "未命名"


def rel_home(home, path):
    try:
        r = os.path.relpath(path, home)
    except ValueError:
        return fwd(path)
    return fwd(r) if not r.startswith("..") else fwd(path)


def agent_kind(cfg=None, override=None):
    """宿主是谁：显式参数 → config → 环境变量 → skill 目录位置 → other。"""
    if override and override != "auto":
        return override
    k = get_key(cfg or {}, "agent.kind")
    if k:
        return k
    env = os.environ
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude"
    if env.get("CODEX_HOME") or env.get("CODEX_CLI_PATH") or env.get("CODEX_SANDBOX"):
        return "codex"
    here = fwd(skill_dir()).lower()
    if "/.claude/" in here:
        return "claude"
    if "/.codex/" in here:
        return "codex"
    return "other"
