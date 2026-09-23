"""课件：下载队列（排队、后台 worker、崩溃回收）、单个文件的下载和文字提取、按课按周补下。

课件永远不挡 deadline 和周报：采集只把新课件排进队列，由这里下。
Canvas 给的显示名只当文件名用（safe_dest）：不当路径、不越出这门课的「课件」文件夹。
课件文字要不要提取给 AI 读，按课开关（config.courses[].materials_ai，默认关）。
"""
import json
import os
import re
import sys
import time
import urllib.error
import uuid
import zipfile

from canvas_api import CanvasAuthError
from cc_config import materials_ai
from cc_courses import lms_of
from cc_paths import coach_cmd, safe_name
from cc_store import FileLock, jload, jsave
from deps import optional

DOC_EXT = (".pdf", ".pptx", ".docx", ".doc")


def doc_name(it):
    """判断是不是课件用的名字：有真实文件名（Moodle）就用它，否则用标题（Canvas 的标题就是文件名）。"""
    return it.get("filename") or it.get("title") or ""

NAME_LIMIT = 80  # 文件名上限：Windows 整条路径只有 260
RESERVED_NAMES = ({"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)})
AI_WORDS = re.compile(r"(?i)\bAI\b|artificial intelligence|generative|生成式|人工智能")
POLICY_WORDS = re.compile(r"(?i)polic|guideline|integrity|declaration|规定|政策|规范|诚信|声明")


def safe_filename(name, limit=NAME_LIMIT):
    """Canvas 的显示名 → 一个文件名：去掉目录、非法字符和结尾的点，避开设备名，留住扩展名，长名截短。"""
    base = os.path.basename(str(name or "").replace("\\", "/").rstrip("/"))
    stem, ext = os.path.splitext(base)
    ext = safe_name(ext, 16) if ext.strip(". ") else ""
    if ext and not ext.startswith("."):
        ext = "." + ext
    stem = safe_name(stem, max(1, limit - len(ext))).rstrip(". ") or "未命名"  # 截短之后可能又落在点上
    if stem.split(".")[0].upper() in RESERVED_NAMES:  # CON.pdf 在 Windows 上仍是设备名
        stem = "_" + stem
    return stem + ext


def safe_dest(dirpath, name, unique=True):
    """dirpath 里的落盘路径：名字只当名字用，重名加「 (2)」，越出 dirpath 就不写。"""
    d = os.path.realpath(dirpath)
    fn = safe_filename(name)
    if unique:
        stem, ext = os.path.splitext(fn)
        n = 2
        while os.path.exists(os.path.join(d, fn)):
            fn = f"{stem} ({n}){ext}"
            n += 1
    dest = os.path.realpath(os.path.join(d, fn))
    if os.path.dirname(dest) != d:
        raise ValueError(f"文件名越出了目标文件夹：{fn}")
    return dest


def downloads_path(ctx):
    return ctx.P("raw", "downloads.json")


def _download_lock_path(ctx):
    return ctx.P("logs", "download-worker.lock")


def _queue_lock_path(ctx):
    return ctx.P("raw", "downloads.lock")


def _launch_path(ctx):
    return ctx.P("logs", "download-launch.json")


def _load_downloads_unlocked(ctx):
    d = jload(downloads_path(ctx), {}) or {}
    d.setdefault("queue", [])
    d.setdefault("done", [])
    d.setdefault("in_progress", [])
    return d


def load_downloads(ctx):
    return _load_downloads_unlocked(ctx)


def queue_downloads(ctx, items):
    """把新出的课件排进队列（按 id 去重），不下载。返回 (新加, 队列总数)。

    `config set materials.auto_download false` 是真的关：文档一直这么写，之前代码没读它。
    关了就一个都不排，用户要哪一周自己 `collect --materials 课 周`。
    """
    if (ctx.cfg.get("materials") or {}).get("auto_download") is False:
        return 0, len(_load_downloads_unlocked(ctx)["queue"])
    with FileLock(_queue_lock_path(ctx)):
        d = _load_downloads_unlocked(ctx)
        seen = ({q.get("id") for q in d["queue"]} | {x.get("id") for x in d["done"]} |
                {x.get("id") for x in d["in_progress"]})
        added, fresh = 0, []
        for it in items:
            if it.get("id") not in seen:
                d["queue"].append({k: it.get(k) for k in ("id", "course", "module", "title", "url", "content_id", "type")})
                seen.add(it.get("id"))
                fresh.append(it)
                added += 1
        note = None if d.get("ai_note") or not added else _materials_ai_note(ctx, fresh)
        if note:
            d["ai_note"] = True
        if added or not os.path.exists(downloads_path(ctx)):
            jsave(downloads_path(ctx), d)
        total = len(d["queue"])
    if note:  # 第一次排课件时说一句；stdout 留给 --json
        print(note, file=sys.stderr)
    return added, total


def _materials_ai_note(ctx, queued):
    """第一次排课件时的一句话：原件照下，课件文字默认不交给 AI，某门课要开怎么开。"""
    codes = [c for c in dict.fromkeys(it.get("course") for it in queued if it.get("course"))
             if not materials_ai(ctx.cfg, c)]
    if not codes:
        return None
    note = (f"课件照常下到「课件」文件夹；课件文字默认不交给 AI 读，"
            f"要给某门课打开：{coach_cmd()} config course {codes[0]} --materials-ai on")
    page = _ai_policy_page(ctx, codes)
    return note + (f"。{page}" if page else "")


def _ai_policy_page(ctx, codes):
    """课程自己的模块里有没有一页在讲 AI 规定：有就点名，没有就不多说。"""
    import cc_study
    try:
        mods = cc_study.load_modules(ctx)
    except Exception:  # noqa: BLE001  提示而已，读不到就不提
        return None
    for code in codes:
        for m in mods.get(code) or []:
            for it in m.get("items") or []:
                title = " ".join(str(it.get("title") or "").split())[:60]
                if it.get("type") == "Page" and AI_WORDS.search(title) and POLICY_WORDS.search(title):
                    return f"{code} 的模块里有「{title}」一页"
    return None


def run_downloads(ctx, cap=10, lock_token=None):
    """下队列里的课件：本周的先，一次最多 cap 个；失败 3 次的丢掉。"""
    worker_lock = FileLock(_download_lock_path(ctx))
    if not worker_lock.acquire(blocking=False):
        _clear_launch(ctx, lock_token)
        d = load_downloads(ctx)
        return {"downloaded": [], "left": len(d["queue"]) + len(d["in_progress"]), "errors": [], "running": True}
    token = lock_token or uuid.uuid4().hex
    try:
        _clear_launch(ctx, lock_token)
        # A crashed foreground or background worker may have left reserved
        # items behind. We hold the sole worker lock, so reclaiming is safe.
        _recover_orphaned_downloads(ctx)
        import cc_study
        now = ctx.clock.now_utc()
        wk = {code: cc_study.max_unlocked_week(m, now) for code, m in cc_study.load_modules(ctx).items() if m}

        def key(it):
            w = cc_study.week_of_name(it.get("module") or "") or 0
            return (0 if wk.get(it.get("course")) and w == wk[it["course"]] else 1, -w)

        with FileLock(_queue_lock_path(ctx)):
            d = _load_downloads_unlocked(ctx)
            d["queue"].sort(key=key)
            batch, d["queue"] = d["queue"][:cap], d["queue"][cap:]
            reserved_at = now.isoformat()
            d["in_progress"].extend([{**it, "_worker": token, "_reserved_at": reserved_at} for it in batch])
            jsave(downloads_path(ctx), d)
        if not batch:
            return {"downloaded": [], "left": len(d["queue"]) + len(d["in_progress"]), "errors": []}

        errors, out, retry, completed = [], [], [], []
        moodle = lms_of(ctx.cfg) == "moodle"
        for n, it in enumerate(batch):
            try:
                r = download_new(ctx, it, it["course"], errors)
            except Exception as e:  # noqa: BLE001
                if moodle and isinstance(e, CanvasAuthError):  # 登录过期：这一批原样放回队列，不算失败次数
                    errors.append(str(e))
                    retry.extend(batch[n:])
                    break
                errors.append(f"下载失败 {it.get('title')}: {type(e).__name__}")
                r = None
            if r:
                out.append({"course": it["course"], "module": it.get("module"), **r})
                completed.append((it, r))
            else:
                it["attempts"] = int(it.get("attempts") or 0) + 1
                if it["attempts"] < 3:
                    retry.append(it)

        with FileLock(_queue_lock_path(ctx)):
            cur = _load_downloads_unlocked(ctx)
            cur["in_progress"] = [x for x in cur["in_progress"] if x.get("_worker") != token]
            queued_ids = {x.get("id") for x in cur["queue"]}
            for it in retry:
                if it.get("id") not in queued_ids:
                    cur["queue"].append(it)
                    queued_ids.add(it.get("id"))
            done_ids = {x.get("id") for x in cur["done"]}
            for it, result in completed:
                if it.get("id") not in done_ids:
                    cur["done"].append({"id": it.get("id"), "title": it.get("title"),
                                        "saved": result.get("saved"), "skipped": result.get("skipped")})
                    done_ids.add(it.get("id"))
            cur["last_run"] = now.isoformat()
            jsave(downloads_path(ctx), cur)
            left = len(cur["queue"]) + len(cur["in_progress"])
        return {"downloaded": out, "left": left, "errors": errors}
    finally:
        _clear_launch(ctx, lock_token)
        worker_lock.release()


def spawn_downloads(ctx):
    """另起一个进程下队列，立刻返回：用户看周报，课件在后台到。"""
    import subprocess
    import sys as _sys
    logdir = ctx.P("logs")
    os.makedirs(logdir, exist_ok=True)
    log = os.path.join(logdir, "download.log")
    if _worker_running(ctx):
        d = load_downloads(ctx)
        return {"queued": len(d["queue"]) + len(d["in_progress"]), "started": False, "running": True, "log": log}
    d = load_downloads(ctx)
    pending = len(d["queue"]) + len(d["in_progress"])
    if not pending:
        return {"queued": 0, "started": False, "running": False, "log": log}
    token = uuid.uuid4().hex
    if not _claim_launch(ctx, token):
        return {"queued": pending, "started": False, "running": True, "log": log}
    # Close the gap between the first worker probe and claiming the launch
    # marker. A worker that acquired the lock in that gap already owns the job.
    if _worker_running(ctx):
        _clear_launch(ctx, token)
        d = load_downloads(ctx)
        return {"queued": len(d["queue"]) + len(d["in_progress"]), "started": False, "running": True, "log": log}
    cmd = [_sys.executable, "-u", os.path.join(os.path.dirname(os.path.abspath(__file__)), "coach.py"), "collect", "--download",
           "--download-worker", "--download-token", token, "--home", ctx.home]
    log_handle = open(log, "a", encoding="utf-8")
    kw = {"stdin": subprocess.DEVNULL, "stdout": log_handle, "stderr": subprocess.STDOUT, "close_fds": True}
    if _sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    else:
        kw["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, **kw)
    except Exception:
        _clear_launch(ctx, token)
        raise
    finally:
        log_handle.close()
    return {"queued": pending, "started": True, "running": False, "log": log, "pid": proc.pid}


def _worker_running(ctx):
    lock = FileLock(_download_lock_path(ctx))
    acquired = lock.acquire(blocking=False)
    if acquired:
        lock.release()
    return not acquired


def _claim_launch(ctx, token):
    path = _launch_path(ctx)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"token": token, "created": time.time()}, f)
            return True
        except FileExistsError:
            cur = jload(path, {}) or {}
            try:
                created = float(cur["created"])
            except (KeyError, TypeError, ValueError):
                # Another process may be between O_EXCL creation and its JSON
                # write. Treat a fresh/invalid marker as active, never stale.
                try:
                    created = os.path.getmtime(path)
                except OSError:
                    return False
            if time.time() - created < 60:
                return False
            try:
                os.remove(path)
            except OSError:
                return False
    return False


def _clear_launch(ctx, token):
    if not token:
        return
    path = _launch_path(ctx)
    cur = jload(path, {}) or {}
    if cur.get("token") == token:
        try:
            os.remove(path)
        except OSError:
            pass


def _recover_orphaned_downloads(ctx):
    """Return crash reservations; caller must already hold the sole worker lock."""
    with FileLock(_queue_lock_path(ctx)):
        d = _load_downloads_unlocked(ctx)
        if not d["in_progress"]:
            return
        seen = {x.get("id") for x in d["queue"]}
        done = {x.get("id") for x in d["done"]}
        for item in d["in_progress"]:
            clean = {k: v for k, v in item.items() if not k.startswith("_")}
            if clean.get("id") not in seen and clean.get("id") not in done:
                d["queue"].append(clean)
                seen.add(clean.get("id"))
        d["in_progress"] = []
        jsave(downloads_path(ctx), d)


def extract_text(path):
    """返回 (文本, 错误说明)。提取失败文本为空，错误另给，不再把错误当正文写进 .txt。"""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".pdf":
            pypdf = optional("pypdf")
            if pypdf is None:
                return "", "ModuleNotFoundError: No module named 'pypdf'"
            reader = pypdf.PdfReader(path)
            out = []
            for i, page in enumerate(reader.pages, 1):
                try:
                    out.append(page.extract_text() or "")
                except Exception as e:  # noqa: BLE001  个别页取不出字不该毁掉整份
                    out.append(f"[第 {i} 页取字失败：{type(e).__name__}]")
            return "\n".join(out), None
        pptx = optional("pptx") if ext == ".pptx" else None
        if pptx is not None:
            try:
                out = []
                for i, slide in enumerate(pptx.Presentation(path).slides, 1):
                    out.append(f"\n===== Slide {i} =====")
                    for sh in slide.shapes:
                        if sh.has_text_frame:
                            out.append(sh.text_frame.text)
                    if slide.has_notes_slide:
                        out.append("[notes] " + slide.notes_slide.notes_text_frame.text)
                return "\n".join(out), None
            except ImportError:
                pass
        if ext in (".pptx", ".docx"):
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist() if n.endswith(".xml") and ("slides/slide" in n or n == "word/document.xml")]
                txt = []
                for n in sorted(names):
                    xml = z.read(n).decode("utf-8", "ignore")
                    txt.append(" ".join(re.findall(r"<(?:a|w):t[^>]*>([^<]*)</(?:a|w):t>", xml)))
                return "\n".join(txt), None
        if ext == ".doc":
            with open(path, "rb") as f:
                raw = f.read()
            best = ""
            for enc in ("utf-16le", "cp1252"):
                s = raw.decode(enc, "ignore")
                runs = [r for r in re.findall(r"[\x20-\x7e -ɏ一-鿿]{4,}", s) if re.search(r"[A-Za-z]{3}|[一-鿿]{2}", r)]
                cand = "\n".join(runs)
                if len(cand) > len(best):
                    best = cand
            return best, ("crude" if best else "no text")
    except Exception as e:  # noqa: BLE001
        return "", f"{type(e).__name__}: {e}"[:200]
    return "", "unsupported"


def download_new(ctx, item, code, errors):
    """下载课件类文件（≤50MB）到 资料夹/<课程>/课件/ 并提取文字。"""
    fid = item.get("content_id")
    if not fid:
        return None
    moodle = lms_of(ctx.cfg) == "moodle"  # Moodle：登录过期往外抛（别说成「没有课件」），错误写中文原因
    try:
        meta = ctx.api.file_meta(fid)
    except urllib.error.HTTPError as e:
        errors.append(f"HTTP {e.code}: " + (f"课件 {fid}" if moodle else f"/api/v1/files/{fid}"))
        return None
    except Exception as e:  # noqa: BLE001
        if moodle and isinstance(e, CanvasAuthError):
            raise
        errors.append(f"课件 {fid} 没读到：{str(e) or type(e).__name__}" if moodle else f"{type(e).__name__}: /api/v1/files/{fid}")
        return None
    name = meta.get("display_name") or meta.get("filename") or str(fid)
    if meta.get("locked_for_user") or not meta.get("url"):
        return {"name": name, "skipped": "locked", "unlock_at": meta.get("unlock_at")}
    max_mb = (ctx.cfg.get("materials") or {}).get("max_mb", 50)
    if (meta.get("size") or 0) > max_mb * 1024 * 1024:
        return {"name": name, "skipped": f"{(meta.get('size') or 0) / 1e6:.0f}MB > {max_mb}MB"}
    dest_dir = ctx.materials_dir(code)
    os.makedirs(dest_dir, exist_ok=True)
    dest = safe_dest(dest_dir, name)  # Canvas 的显示名只当名字用，且必须落在这门课的「课件」里
    try:
        _, body = ctx.api.fetch(meta["url"], accept="*/*")
    except Exception as e:  # noqa: BLE001
        if moodle and isinstance(e, CanvasAuthError):
            raise
        errors.append(f"下载失败 {name}: {(str(e) or type(e).__name__) if moodle else type(e).__name__}")
        return None
    with open(dest, "wb") as f:
        f.write(body)
    txt, err = ("", None)
    if materials_ai(ctx.cfg, code):  # 默认不提取：原件下到本机，文字不交给 AI
        txt, err = extract_text(dest)
    if txt.strip():  # 文字稿放机器档案里，课件文件夹只留原件
        tdir = ctx.P("text", code)
        os.makedirs(tdir, exist_ok=True)
        with open(safe_dest(tdir, os.path.splitext(os.path.basename(dest))[0] + ".txt", unique=False), "w", encoding="utf-8") as f:
            f.write(txt)
    r = {"name": name, "saved": dest, "bytes": len(body), "text": ("crude" if err == "crude" else bool(txt.strip()))}
    if err and err != "crude":
        r["extract_error"] = err
    return r


def week_matches(module_name, week):
    """模块名是否属于第 week 周：Week 7 / Week 07 / W7 / 第 7 周。"""
    w = str(week).lstrip("Ww")
    return bool(re.search(rf"(?i)(?:week|wk|w)\s*0?{w}\b|第\s*{w}\s*周", module_name or ""))


def collect_materials(ctx, code, week):
    """只下载某门课某一周模块里的课件（导读分支缺课件时用）。"""
    course = next((c for c in ctx.cfg.get("courses") or [] if c["code"] == code), None)
    if not course:
        return {"error": f"config.json 里没有课程 {code}", "downloaded": []}
    errors, out = [], []
    if lms_of(ctx.cfg) == "moodle":  # Moodle 没有模块接口：用上次采集整理好的模块（同 Canvas 形状）
        import cc_study
        modules = cc_study.load_modules(ctx).get(code)
    else:
        modules = ctx.api.get(f"/api/v1/courses/{course['id']}/modules?per_page=50&include[]=items&include[]=content_details")
    mats = ctx.materials_dir(code)
    have = set(os.listdir(mats)) if os.path.isdir(mats) else set()
    for m in modules or []:
        if not week_matches(m.get("name"), week):
            continue
        for it in m.get("items") or []:
            if it.get("type") != "File" or not doc_name(it).lower().endswith(DOC_EXT):
                continue
            cd = it.get("content_details") or {}
            if cd.get("locked_for_user"):
                out.append({"name": it.get("title"), "skipped": "locked", "unlock_at": cd.get("unlock_at") or m.get("unlock_at")})
                continue
            if safe_filename(doc_name(it)) in have:  # 盘上是清理过的名字，比对也用它
                out.append({"name": it.get("title"), "skipped": "already"})
                continue
            r = download_new(ctx, {"content_id": it.get("content_id")}, code, errors)
            if r:
                out.append({"module": m.get("name"), **r})
    for r in out:
        tag = "已下载" if r.get("saved") else f"跳过（{r.get('skipped')}{'，解锁 ' + str(r.get('unlock_at')) if r.get('unlock_at') else ''}）"
        print(f" - {r.get('name')}：{tag}")
    if not out:
        print(f"（{code} 第 {week} 周的模块里没有可下载的课件；模块名要含 Week {week} / W{week}）")
    for e in errors:
        print(" ! " + e)
    return {"course": code, "week": week, "downloaded": out, "errors": errors}
