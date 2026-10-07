"""更新（/jj-update）：去 GitHub 看最新版，比装着的新就下下来换上。

- Claude Code、Codex 装着的几份（~/.claude、~/.codex、~/.agents 下的 skills/<SLUG>）一起换。
- 换之前把旧版打成压缩包，放在 skills 文件夹外面（「文档/<产品名>备份」）：放在 skills 里会被当成第二个技能加载。
- tools/、references/、skills/、agents/、assets/ 以新版为准，新版里没有的文件删掉；.git 和别的顶层文件不动。
- 换好以后用新版自己的代码装 /jj 入口（update --finish）：新功能装上，下架的删掉，版本号写新的。
- 哪一步出错就用备份换回旧版，旧版照常能用。学生的数据（档案、token、登录记录）不在技能文件夹里，不受影响。
"""
import datetime as dt
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

import brand
from cc_install import HOST_DIRS, _same, _version_of, install_entries, installed_entries, remove_entries, skill_location_ok

API = "https://api.github.com"
MANAGED = ("tools", "references", "skills", "agents", "assets")  # 以新版为准的文件夹
SKIP = ("__pycache__", ".git")


def api_base():
    return (brand.env("UPDATE_API") or API).rstrip("/")


def version_of_tag(tag):
    m = re.search(r"(\d+(?:\.\d+)+)", tag or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def show(v):
    return ".".join(map(str, v)) if v else "?"


def _get(url, timeout):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"{brand.SLUG}/{brand.VERSION} (update)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest(timeout=30):
    """GitHub 上最新的正式版：{tag, version, notes, zip}。"""
    d = json.loads(_get(f"{api_base()}/repos/{brand.REPO}/releases/latest", timeout).decode("utf-8"))
    return {"tag": d.get("tag_name"), "version": version_of_tag(d.get("tag_name")), "notes": (d.get("body") or "").strip(),
            "zip": d.get("zipball_url") or f"{api_base()}/repos/{brand.REPO}/zipball/{d.get('tag_name')}"}


def installed_copies(home=None, running=None):
    """装着的几份：~/.claude、~/.codex、~/.agents 下的 skills/<SLUG>，加上正在跑的这份（项目级、插件里的）。"""
    home = home or os.path.expanduser("~")
    out = [d for d in (os.path.join(home, h, "skills", brand.SLUG) for h in HOST_DIRS) if os.path.isfile(os.path.join(d, "SKILL.md"))]
    if running and skill_location_ok(running) and not any(_same(running, d) for d in out):
        out.append(os.path.normpath(running))
    return out


def _unpack(data, work):
    """下载的压缩包 → 新版的根目录（SKILL.md 所在的那层）。不认识的包、路径往外跳的包都不要。"""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in z.namelist():
            p = os.path.normpath(n)
            if os.path.isabs(n) or p.startswith(".."):
                raise ValueError(f"压缩包里有不安全的路径：{n}")
        z.extractall(work)
    for root, dirs, files in os.walk(work):
        if "SKILL.md" in files and os.path.isfile(os.path.join(root, "tools", "coach.py")):
            return root
        if root != work:
            dirs[:] = []
    raise ValueError(f"压缩包里没有{brand.NAME}（找不到 SKILL.md 和 tools/coach.py）")


def _check_tree(root, want):
    with open(os.path.join(root, "SKILL.md"), encoding="utf-8") as f:
        if not re.search(rf"^name:\s*{re.escape(brand.SLUG)}\s*$", f.read(), re.M):
            raise ValueError(f"压缩包里的 SKILL.md 不是{brand.NAME}")
    got = _version_of(root)
    if want and got != want:
        raise ValueError(f"压缩包里的版本是 {show(got)}，和发布的 {show(want)} 对不上")


def backup_dir(home):
    docs = os.path.join(home, "Documents")
    return os.path.join(docs if os.path.isdir(docs) else home, f"{brand.NAME}备份")


def backup(copy, home, stamp):
    """旧版打成压缩包放在 skills 外面，返回压缩包路径。"""
    host = os.path.basename(os.path.dirname(os.path.dirname(copy))).lstrip(".") or "skills"
    os.makedirs(backup_dir(home), exist_ok=True)
    path = os.path.join(backup_dir(home), f"{brand.SLUG}-{show(_version_of(copy))}-{host}-{stamp}.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(copy):
            dirs[:] = [d for d in dirs if d not in SKIP]
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, copy))
    return path


def _files(root):
    out = set()
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP]
        out.update(os.path.relpath(os.path.join(r, f), root) for f in files)
    return out


def sync(new_root, copy):
    """把新版铺到这一份上：新版的文件全部覆盖；以新版为准的文件夹里，新版没有的文件删掉。"""
    new = _files(new_root)
    for rel in sorted(new):
        dst = os.path.join(copy, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(new_root, rel), dst)
    for rel in sorted(_files(copy) - new):
        if rel.split(os.sep)[0] in MANAGED:
            os.remove(os.path.join(copy, rel))
    for top in MANAGED:
        for r, dirs, files in os.walk(os.path.join(copy, top), topdown=False):
            if os.path.basename(r) == "__pycache__":
                shutil.rmtree(r, ignore_errors=True)
            elif not os.listdir(r):
                os.rmdir(r)


def restore(copy, zip_path):
    """出错时用备份换回旧版。"""
    for top in MANAGED:
        shutil.rmtree(os.path.join(copy, top), ignore_errors=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(copy)


def finish(copy):
    """用新版自己的代码装 /jj 入口（新的装上、下架的删掉、版本写新的）→ {installed, removed}（入口名）。
    Codex 两处都读（~/.codex/skills 和 ~/.agents/skills）：两处都有主文件夹时口令只装在 .agents 那份旁边，不然菜单里出现两遍。"""
    names = lambda ps: sorted(os.path.basename(p) for p in ps)  # noqa: E731
    host = os.path.dirname(os.path.dirname(os.path.normpath(copy)))
    twin = os.path.join(os.path.dirname(host), ".agents", "skills", brand.SLUG)
    if os.path.basename(host).lower() == ".codex" and os.path.isfile(os.path.join(twin, "SKILL.md")):
        return {"installed": [], "removed": names(remove_entries(copy)), "skipped": "Codex 的口令装在 ~/.agents/skills 那份旁边"}
    r = install_entries(copy)
    return {"installed": names(r["installed"]), "removed": names(r["removed"]), "skipped": r.get("skipped")}


def _finish_with_new_code(copy, timeout=120):
    """新版换上以后，这个进程里加载的还是旧代码：起一个新版的 coach.py 来装入口。"""
    cmd = [sys.executable, "-B", os.path.join(copy, "tools", "coach.py"), "update", "--finish", copy, "--json"]
    p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or ["装入口没成"])
    return json.loads(p.stdout.decode("utf-8"))


def update(home=None, running=None, check_only=False, timeout=60, finisher=None):
    """{state: latest / available / updated / error, from, to, notes, copies, backups, entries, message}。"""
    home = home or os.path.expanduser("~")
    copies = installed_copies(home, running)
    if not copies:
        return {"state": "error", "message": f"{brand.NAME}还没装在 skills 文件夹里，先说「帮我装{brand.NAME}」"}
    have = {c: _version_of(c) for c in copies}
    try:
        rel = latest(timeout)
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"state": "error", "message": f"这次连不上 GitHub（{type(e).__name__}），没更新；现在的 {show(max(v for v in have.values() if v) if any(have.values()) else None)} 版照常能用"}
    want = rel["version"]
    old = [c for c, v in have.items() if not v or (want and v < want)]
    base = {"from": show(max((v for v in have.values() if v), default=None)), "to": show(want), "notes": rel["notes"], "copies": copies}
    if not want or not old:
        return dict(base, state="latest", message=f"已经是最新版（{base['from']}）")
    if check_only:
        return dict(base, state="available", message=f"有新版 {show(want)}（现在是 {show(min(have[c] or (0,) for c in old))}）")
    work = tempfile.mkdtemp(prefix=f"{brand.SLUG}-update-")
    try:
        try:
            root = _unpack(_get(rel["zip"], timeout), work)
            _check_tree(root, want)
        except (urllib.error.URLError, OSError, ValueError, zipfile.BadZipFile) as e:
            return dict(base, state="error", message=f"新版没下好（{e}），没更新；旧版照常能用")
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
        backups, entries, failed = [], {"installed": [], "removed": []}, []
        for c in old:
            zp = backup(c, home, stamp)
            backups.append(zp)
            try:
                before = {r["name"] for r in installed_entries(c) if r["installed"]}
                sync(root, c)
                got = (finisher or _finish_with_new_code)(c)
                entries["installed"] += [n for n in got.get("installed", []) if n not in before]
                entries["removed"] += got.get("removed", [])
            except Exception as e:  # noqa: BLE001  换到一半出错：用备份换回旧版
                restore(c, zp)
                failed.append(f"{c}：{type(e).__name__} {e}")
        if failed and len(failed) == len(old):
            return dict(base, state="error", backups=backups, message="新版没换上，已经换回旧版：" + "；".join(failed))
        entries = {k: sorted(set(v)) for k, v in entries.items()}
        msg = f"从 {base['from']} 更新到 {show(want)}"
        return dict(base, state="updated", backups=backups, entries=entries, failed=failed, message=msg)
    finally:
        shutil.rmtree(work, ignore_errors=True)
