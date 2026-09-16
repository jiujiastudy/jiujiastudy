"""安装：pip 装可选依赖、skill 是否装在宿主找得到的地方（--install 复制进去）、分享版打包。"""
import glob
import os
import re
import shutil
import subprocess
import sys

import brand
from cc_paths import agent_kind, skill_dir
from cc_store import jload


def pip_install(pkg):
    base = [sys.executable, "-m", "pip", "install", "--no-cache-dir", "--quiet"]
    for extra in ([], ["--user"], ["--break-system-packages"]):
        try:
            r = subprocess.run(base + extra + [pkg], capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.SubprocessError):
            return False
        if r.returncode == 0:
            return True
    return False


HOST_DIRS = (".claude", ".codex", ".agents")  # 这些文件夹里的 skills/ 宿主会读：在 ~ 下（用户级）或在项目里（项目级）都算


def skill_location_ok(sd):
    """宿主找得到这个 skill 吗：SKILL.md 要直接在某个 skills 文件夹下一层（skills/<名字>/SKILL.md），多套一层就找不到。
    认的 skills 文件夹：.claude/skills、.codex/skills、.agents/skills（在 ~ 下或在项目里都行）、$CODEX_HOME/skills，
    以及插件的 skills/（插件根目录有 .claude-plugin/plugin.json）。"""
    sd = os.path.normpath(os.path.abspath(sd))
    if not os.path.isfile(os.path.join(sd, "SKILL.md")):
        return False
    skills = os.path.dirname(sd)
    if os.path.normcase(os.path.basename(skills)) != "skills":
        return False
    owner = os.path.dirname(skills)
    if os.path.normcase(os.path.basename(owner)) in HOST_DIRS:
        return True
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home and os.path.normcase(os.path.normpath(os.path.abspath(os.path.expanduser(codex_home)))) == os.path.normcase(owner):
        return True
    return os.path.isfile(os.path.join(owner, ".claude-plugin", "plugin.json"))


def check_skill_location(install=False, agent="auto", display_coach=""):
    """skill 位置：宿主只在 skills/<名字>/SKILL.md 这一层找（见 skill_location_ok）。不在（比如把文件拖进了聊天，
    或解压时多套了一层文件夹），换个对话就找不到；install=True 时复制进去。返回 (级别 "ok" / "warn", 详情, 要做的事或 None)。"""
    sd = skill_dir()
    if not skill_location_ok(sd):
        ag = agent_kind() if agent in (None, "auto") else agent
        target = os.path.join(os.path.expanduser("~"), ".codex" if ag == "codex" else ".claude", "skills", brand.SLUG)
        if os.path.isdir(target):
            return "warn", f"现在跑的是 {sd}，但 {target} 已经装过一份", "新对话用装好的那份即可；这份是临时的"
        if install:
            shutil.copytree(sd, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
            return "ok", f"已装进 {target}，以后新开对话直接可用（本次对话继续用当前这份）", None
        return "warn", f"{sd} 不在宿主找得到的位置（要是 skills/<名字>/SKILL.md 这一层），换个对话就找不到它", f"我来装：{display_coach} doctor --install"
    return "ok", f"{sd}", None


FLAG_PATTERNS = [r"\d{3,6}~[A-Za-z0-9]{40,}", r"CANVAS_TOKEN\s*=\s*[\"']?\d{3,6}~"]


def load_flags(cfg, home):
    """个人标识从 config 生成（姓名、学号、用户名、课程 id / 代码、域名），再加 HOME/share_flags.json 里的。"""
    flag, warn = list(FLAG_PATTERNS), []
    user = (cfg or {}).get("user") or {}
    if user.get("name"):
        flag.append(re.escape(user["name"]))
        for part in re.split(r"\s+", user["name"]):
            if len(part) >= 4:
                flag.append(re.escape(part))
    if user.get("id"):
        flag.append(rf"\b{user['id']}\b")
    osuser = os.path.basename(os.path.expanduser("~"))
    if osuser:
        flag.append(r"Users[/\\]" + re.escape(osuser) + r"\b")
    ids = [str(c.get("id")) for c in (cfg or {}).get("courses") or [] if c.get("id")]
    if ids:
        warn.append(r"\b(" + "|".join(ids) + r")\b")
    codes = [re.escape(c.get("code")) for c in (cfg or {}).get("courses") or [] if c.get("code")]
    if codes:
        warn.append(r"\b(" + "|".join(codes) + r")\b")
    host = (cfg or {}).get("canvas_host")
    if host:
        warn.append(re.escape(host.split("//")[-1]))
    extra = jload(os.path.join(home, "share_flags.json"), {}) or {}
    return flag + list(extra.get("flag") or []), warn + list(extra.get("warn") or [])


def share(home, out=None, zip_it=False):
    src = skill_dir()
    cfg = jload(os.path.join(home, "config.json"), {}) or {}
    out = out or os.path.join(os.path.expanduser("~"), "Documents", f"{brand.NAME}-分享版")
    dst = os.path.join(out, brand.SLUG)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    os.makedirs(dst, exist_ok=True)
    copied = []

    def cp(rel):
        s = os.path.join(src, rel)
        if not os.path.exists(s):
            return
        d = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)
        copied.append(rel)

    for name in ("SKILL.md", "AGENTS.md", "使用说明.md"):
        cp(name)
    for f in sorted(glob.glob(os.path.join(src, "references", "*.md"))):
        cp(os.path.join("references", os.path.basename(f)))
    for f in sorted(glob.glob(os.path.join(src, "tools", "*.py")) + glob.glob(os.path.join(src, "tools", "*.png"))):
        if ".private." in os.path.basename(f):
            continue
        cp(os.path.join("tools", os.path.basename(f)))
    guide = os.path.join(src, "使用说明.md")
    if os.path.exists(guide):
        shutil.copy2(guide, os.path.join(out, "使用说明.md"))
        txt = md_to_txt(open(guide, encoding="utf-8").read())
        with open(os.path.join(out, "使用说明.txt"), "w", encoding="utf-8-sig", newline="") as f:
            f.write(txt)
        copied += ["使用说明.md", "使用说明.txt"]
    flag_pats, warn_pats = load_flags(cfg, home)
    flagged, warned = [], []
    for root, _, files in os.walk(out):
        for fn in files:
            p = os.path.join(root, fn)
            if fn.endswith(".pyc"):
                continue
            try:
                txt = open(p, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            rel = os.path.relpath(p, out)
            for pat in flag_pats:
                if re.search(pat, txt):
                    flagged.append(f"{rel}: {pat}")
            for pat in warn_pats:
                if re.search(pat, txt):
                    warned.append(f"{rel}: {pat}")
    zip_path = None
    if zip_it and not flagged:
        zip_path = shutil.make_archive(out, "zip", out)
    return (2 if flagged else 0), {"out": out, "copied": copied, "flagged": flagged, "warned": warned, "zip": zip_path}


def md_to_txt(md):
    out = []
    for line in md.splitlines():
        t = line.rstrip()
        if t.startswith("# "):
            h = t[2:].strip()
            out += [h, "=" * (len(h) * 2), ""]
            continue
        if t.startswith("## "):
            out += ["", "【" + t[3:].strip() + "】", ""]
            continue
        t = re.sub(r"\*\*(.+?)\*\*", r"\1", t.replace("`", ""))
        if t.lstrip().startswith("- "):
            t = t.replace("- ", "· ", 1)
        out.append(t)
    return "\r\n".join(out).strip() + "\r\n"
