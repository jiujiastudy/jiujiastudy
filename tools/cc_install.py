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
            r = install_entries(target)
            extra = f"；/jj 入口 {len(r['installed'])} 个" if r["installed"] else ""
            return "ok", f"已装进 {target}{extra}，以后新开对话直接可用（本次对话继续用当前这份）", None
        return "warn", f"{sd} 不在宿主找得到的位置（要是 skills/<名字>/SKILL.md 这一层），换个对话就找不到它", f"我来装：{display_coach} doctor --install"
    if install:
        r = install_entries(sd)
        if r["installed"] or r["removed"]:
            return "ok", f"{sd}（/jj 入口：装好 {len(r['installed'])} 个，删掉旧的 {len(r['removed'])} 个）", None
    return "ok", f"{sd}", None


# /jj 菜单的入口（skills/jj-*）：源在主文件夹的 skills/ 下，装的时候复制到主文件夹旁边（同一个 skills 文件夹），
# 把「<产品名>主文件夹：」那一行换成真实路径、版本号换成主文件夹的版本。入口只有几个小文件，复制不用链接。
ENTRY_PREFIX = "jj-"
MAIN_LABEL = brand.NAME + "主文件夹："
MAIN_LINE = re.compile("^" + re.escape(MAIN_LABEL) + "(.*)$", re.M)
VERSION_TOKEN = "<和主文件夹一致>"


def entry_sources(sd=None):
    """主文件夹 skills/ 下带 SKILL.md 的 jj-* 文件夹（入口的源）。"""
    root = os.path.join(sd or skill_dir(), "skills")
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [os.path.join(root, n) for n in names if n.startswith(ENTRY_PREFIX) and os.path.isfile(os.path.join(root, n, "SKILL.md"))]


def _read(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def entry_info(d):
    """装出去的入口：写着的主文件夹、版本、指向的 references 文件。不是本技能的入口（没有「<产品名>主文件夹：」那一行）返回 None。"""
    text = _read(os.path.join(d, "SKILL.md"))
    m = MAIN_LINE.search(text or "")
    if not m:
        return None
    ver = re.search(r"版本\s*([\d.]+)", text)
    return {"name": os.path.basename(os.path.normpath(d)), "path": d, "main": m.group(1).split("←")[0].strip(),
            "version": ver.group(1) if ver else None, "refs": re.findall(r"references/([\w-]+\.md)", text)}


def _same(a, b):
    return os.path.normcase(os.path.normpath(os.path.abspath(a))) == os.path.normcase(os.path.normpath(os.path.abspath(b)))


def install_entries(sd=None):
    """把入口装到主文件夹旁边，写进主文件夹路径和版本；删掉源里已经没有、又指向这个主文件夹的旧入口。
    主文件夹不在宿主找得到的位置时不装（入口放进去也叫不出来）；同名的别人的技能不覆盖。"""
    sd = os.path.normpath(os.path.abspath(sd or skill_dir()))
    out = {"installed": [], "removed": [], "conflicts": [], "skipped": None}
    if not skill_location_ok(sd):
        out["skipped"] = "主文件夹不在宿主找得到的 skills 文件夹里，入口装了也叫不出来"
        return out
    skills = os.path.dirname(sd)
    names = set()
    for src in entry_sources(sd):
        name = os.path.basename(src)
        names.add(name)
        dst = os.path.join(skills, name)
        if os.path.isdir(dst) and entry_info(dst) is None:
            out["conflicts"].append(dst)
            continue
        text = _read(os.path.join(src, "SKILL.md")) or ""
        text = MAIN_LINE.sub(lambda m: MAIN_LABEL + sd, text, count=1).replace(VERSION_TOKEN, brand.VERSION)
        os.makedirs(os.path.join(dst, "agents"), exist_ok=True)
        with open(os.path.join(dst, "SKILL.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        yml = os.path.join(src, "agents", "openai.yaml")
        if os.path.isfile(yml):
            shutil.copyfile(yml, os.path.join(dst, "agents", "openai.yaml"))
        out["installed"].append(dst)
    for name in sorted(os.listdir(skills)):
        d = os.path.join(skills, name)
        info = entry_info(d) if name.startswith(ENTRY_PREFIX) and name not in names else None
        if info and _same(info["main"], sd):
            shutil.rmtree(d)
            out["removed"].append(d)
    return out


def installed_entries(sd=None):
    """主文件夹旁边装着的本技能入口，加上源里有、还没装的：[{name, installed, main, version, refs}]。"""
    sd = os.path.normpath(os.path.abspath(sd or skill_dir()))
    skills = os.path.dirname(sd)
    rows = {}
    for src in entry_sources(sd):
        info = entry_info(src) or {}
        rows[os.path.basename(src)] = {"name": os.path.basename(src), "installed": False, "main": None, "version": None, "refs": info.get("refs", [])}
    if skill_location_ok(sd):
        for name in sorted(os.listdir(skills)):
            info = entry_info(os.path.join(skills, name)) if name.startswith(ENTRY_PREFIX) else None
            if info:
                rows[name] = dict(info, installed=True)
                rows[name].pop("path", None)
    return [rows[k] for k in sorted(rows)]


def remove_entries(sd=None):
    """删掉主文件夹旁边、指向这个主文件夹的本技能入口（卸载时用）；别人的技能不碰。"""
    sd = os.path.normpath(os.path.abspath(sd or skill_dir()))
    skills, removed = os.path.dirname(sd), []
    for name in sorted(os.listdir(skills)) if skill_location_ok(sd) else []:
        d = os.path.join(skills, name)
        info = entry_info(d) if name.startswith(ENTRY_PREFIX) else None
        if info and _same(info["main"], sd):
            shutil.rmtree(d)
            removed.append(d)
    return removed


def entry_problems(sd=None, home=None, display_coach=""):
    """doctor 查入口：路径还在不在、是不是这个主文件夹、版本对不对得上、有没有没装的、同一个入口在 .codex 和 .agents 各一份。
    返回 [(级别 "warn" / "info", 详情, 要做的事)]。"""
    sd = os.path.normpath(os.path.abspath(sd or skill_dir()))
    home = home or os.path.expanduser("~")
    fix = f"{display_coach} doctor --install".strip()
    out = []
    if not skill_location_ok(sd):
        return out
    rows = installed_entries(sd)
    for r in rows:
        if not r["installed"]:
            out.append(("info", f"/jj 入口 {r['name']} 还没装", f"装：{fix}"))
        elif not os.path.isdir(r["main"] or ""):
            out.append(("warn", f"入口 {r['name']} 写着的主文件夹 {r['main']} 已经不在了", f"重写路径：{fix}"))
        elif not _same(r["main"], sd):
            out.append(("warn", f"入口 {r['name']} 指向另一份主文件夹 {r['main']}", f"改成指向这份：{fix}"))
        elif r["version"] != brand.VERSION:
            out.append(("warn", f"入口 {r['name']} 是 {r['version'] or '没写版本'}，主文件夹是 {brand.VERSION}", f"更新入口：{fix}"))
    names = {r["name"] for r in rows}
    places = {n: [h for h in (".codex", ".agents") if entry_info(os.path.join(home, h, "skills", n))] for n in names}
    for n, hs in sorted(places.items()):
        if len(hs) > 1:
            out.append(("warn", f"入口 {n} 在 ~/.codex/skills 和 ~/.agents/skills 各有一份，Codex 菜单里可能出现两遍",
                        "跟用户说一句，留一份就够，另一份挪出 skills 文件夹"))
    return out


HOST_TOOLS = {".claude": "Claude Code", ".codex": "Codex", ".agents": "Codex 等其它 AI 工具"}


def _version_of(d):
    try:
        with open(os.path.join(d, "tools", "brand.py"), encoding="utf-8") as f:
            m = re.search(r'^VERSION\s*=\s*"([\d.]+)"', f.read(), re.M)
        return tuple(int(x) for x in m.group(1).split(".")) if m else None
    except (OSError, ValueError):
        return None


def duplicate_skills(sd=None, home=None):
    """skills 文件夹里有没有多出来的一份本技能。返回 [(级别 "warn" / "info", 详情, 要做的事或 None)]。
    - 同一个 skills 里的备份（<SLUG>.backup-… 这类，更新时常被放在这里）或旧名字的一份：宿主会当成第二个技能加载 → warn；
    - 别的 AI 工具的 skills 里同名的一份：是给那个工具用的，正常；只在它比这份旧时提醒一句 → info。"""
    sd = os.path.normpath(os.path.abspath(sd or skill_dir()))
    home = home or os.path.expanduser("~")
    key = os.path.normcase  # 比较时不分大小写（Windows），显示时保留原样
    parent = os.path.dirname(sd)  # 从实验文件夹（比如「文档」里）跑时，旁边的备份不在 skills 里，宿主不会加载，不算
    here = [parent] if os.path.normcase(os.path.basename(parent)) == "skills" else []
    dirs = {key(d): d for d in here + [os.path.join(home, h, "skills") for h in HOST_DIRS]}
    mine, out = _version_of(sd), []
    for _, skills in sorted(dirs.items()):
        try:
            names = os.listdir(skills)
        except OSError:
            continue
        for name in sorted(names):
            p = os.path.join(skills, name)
            if key(p) == key(sd) or not os.path.isfile(os.path.join(p, "SKILL.md")):
                continue
            low = name.lower()
            if (low.startswith(brand.SLUG) and low != brand.SLUG) or low in brand.LEGACY_SKILL_DIRS:
                out.append(("warn", f"{p} 也是一份{brand.NAME}（备份或旧名字），AI 工具会把它当成第二个技能加载，可能用到旧版",
                            f"跟用户说一句，把 {p} 挪出 skills 文件夹（比如挪到「文档」里），别删"))
            elif low == brand.SLUG:
                theirs = _version_of(p)
                if mine and theirs and theirs < mine:
                    tool = HOST_TOOLS.get(os.path.basename(os.path.dirname(skills)).lower(), "另一个 AI 工具")
                    out.append(("info", f"给 {tool} 用的那份（{p}）还是 {'.'.join(map(str, theirs))} 版，比这份旧",
                                f"用户说「更新{brand.NAME}」时一起更新它"))
    return out


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
