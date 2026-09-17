"""宿主权限：Claude Code 全局 settings.json 需要的规则（检查、合并写入）和 Codex 的 config.toml 片段。"""
import json
import os
import shutil
import sys
import time

from cc_config import CoachError
from cc_paths import fwd, skill_dir
from cc_store import jload


def claude_settings_path():
    return os.path.join(os.path.expanduser("~"), ".claude", "settings.json")


def perm_rules(home, sdir=None, platform=None, root=None):
    """Claude Code 全局 settings.json 需要的规则。Bash 用 `前缀:*` 形式，前缀 = 完整脚本路径。home = 机器档案，root = 资料夹。"""
    platform = platform or sys.platform
    sdir = sdir or skill_dir()
    h, s = fwd(home), fwd(sdir)
    r = fwd(root) if root else None
    up = fwd(os.path.expanduser("~"))
    allow = []
    writable = [b for b in (h, r) if b]
    if r and r.lower().startswith(h.lower() + "/"):
        writable = [h]
    elif r and h.lower().startswith(r.lower() + "/"):
        writable = [r]
    for base in writable + [s]:
        if base.lower().startswith(up.lower() + "/"):
            rel = base[len(up) + 1:]
            allow.append(f"Read(~/{rel}/**)")
            if base != s:
                allow.append(f"Edit(~/{rel}/**)")
        absr = "//" + base.lstrip("/")
        allow.append(f"Read({absr}/**)")
        if base != s:
            allow.append(f"Edit({absr}/**)")
    pys = ["python"] if platform == "win32" else ["python3", "python"]
    current = fwd(sys.executable or "")
    if current:
        quoted = f'"{current}"'
        if quoted not in pys:
            pys.append(quoted)
    for name in ("coach.py", "canvas_api.py"):
        sc = f"{s}/tools/{name}"
        for py in pys:
            allow += [f'Bash({py} "{sc}":*)', f"Bash({py} {sc}:*)"]
        if platform == "win32":
            scb = sc.replace("/", "\\")
            allow += [f'Bash(python "{scb}":*)', f"Bash(python {scb}:*)"]
    return {"additionalDirectories": writable, "allow": allow}


def check_perms(home, root=None):
    st = jload(claude_settings_path(), {}) or {}
    perms = st.get("permissions") or {}
    have_allow = set(perms.get("allow") or [])
    have_dirs = set(fwd(x) for x in perms.get("additionalDirectories") or [])
    need = perm_rules(home, root=root)
    missing_allow = [r for r in need["allow"] if r not in have_allow]
    missing_dirs = [d for d in need["additionalDirectories"] if fwd(d) not in have_dirs]
    block = {"permissions": {"additionalDirectories": need["additionalDirectories"], "allow": need["allow"]}}
    return missing_allow, missing_dirs, block


def fix_perms(home, root=None):
    p = claude_settings_path()
    st = jload(p)
    if st is None and os.path.exists(p):
        raise CoachError(f"{p} 不是合法 JSON，请先手动修好", 2)
    st = st or {}
    perms = st.setdefault("permissions", {})
    need = perm_rules(home, root=root)
    allow = perms.setdefault("allow", [])
    for r in need["allow"]:
        if r not in allow:
            allow.append(r)
    dirs = perms.setdefault("additionalDirectories", [])
    for d in need["additionalDirectories"]:
        if fwd(d) not in [fwd(x) for x in dirs]:
            dirs.append(d)
    if os.path.exists(p):
        shutil.copy2(p, p + time.strftime(".bak-%Y%m%d-%H%M%S"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return p


def codex_snippet(home):
    return ("# 合并进 ~/.codex/config.toml（Codex 桌面版 → Settings → Config）\n"
            f"[projects.'{fwd(home)}']\ntrust_level = \"trusted\"\n")
