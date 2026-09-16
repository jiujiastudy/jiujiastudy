"""采集：只读拉各课的作业（含本人提交）、模块、公告、站内信和考试站点，与上次快照比对。

成功时写 raw/daily/<date>/digest.json、提升快照并更新采集状态；失败只写 last_failure.json，不进缓存。
"""
import datetime as dt
import difflib
import glob
import hashlib
import html as html_mod
import os
import re
import urllib.error

from cc_courses import course_of_context, course_pairs
from cc_downloads import DOC_EXT, queue_downloads
from cc_store import FileLock, jload, jsave
from cc_time import parse_ts

DESC_UNCHANGED = "（说明文字有改动，但去掉格式后内容相同）"


def strip_html(h, limit=None):
    t = re.sub(r"<br\s*/?>|</p>|</li>|</div>|</h\d>", "\n", h or "")
    t = re.sub(r"<[^>]+>", " ", t)
    t = html_mod.unescape(t)
    lines = [re.sub(r"[ \t　]+", " ", l).strip() for l in t.splitlines()]
    t = "\n".join(l for l in lines if l)
    return t[:limit] + ("…" if limit and len(t) > limit else "") if limit else t


def weight_of(a, group_w):
    m = re.search(r"(\d{1,3})\s*%", a.get("name") or "")
    if m:
        return m.group(1) + "%"
    w = group_w.get(a.get("assignment_group_id"))
    if w is not None and a.get("points_possible"):
        return f"{w:g}%"
    return "—"


def snapshot_from(courses, assignments, modules, group_ws, ann_ids, conv):
    snap = {"assignments": {}, "items": {}, "announcements": ann_ids, "conversations": conv}
    for cid, code in courses:
        for a in assignments.get(code) or []:
            s = a.get("submission") or {}
            snap["assignments"][str(a["id"])] = {
                "course": code, "name": a.get("name"), "html_url": a.get("html_url"),
                "due_at": a.get("due_at"), "lock_at": a.get("lock_at"), "unlock_at": a.get("unlock_at"),
                "points": a.get("points_possible"), "weight": weight_of(a, group_ws.get(code, {})),
                "desc_hash": hashlib.md5((a.get("description") or "").encode("utf-8")).hexdigest(),
                "updated_at": a.get("updated_at"),
                "sub_state": s.get("workflow_state"), "submitted_at": s.get("submitted_at"), "attempt": s.get("attempt"),
                "score": s.get("score"), "grade": s.get("grade"), "graded_at": s.get("graded_at"),
                "posted_at": s.get("posted_at"), "sub_type": s.get("submission_type"),
                "attachments": [x.get("display_name") for x in s.get("attachments") or []],
                "submission_types": a.get("submission_types") or [],
                "is_quiz": bool(a.get("is_quiz_assignment") or "online_quiz" in (a.get("submission_types") or [])),
            }
        for m in modules.get(code) or []:
            for it in m.get("items") or []:
                if it.get("type") == "SubHeader":
                    continue
                cd = it.get("content_details") or {}
                snap["items"][str(it["id"])] = {
                    "course": code, "module": m.get("name"), "title": (it.get("title") or "").strip(),
                    "type": it.get("type"), "locked": bool(cd.get("locked_for_user")),
                    "unlock_at": cd.get("unlock_at") or m.get("unlock_at"), "content_id": it.get("content_id"),
                    "url": it.get("html_url"), "page_url": it.get("page_url"),
                }
    return snap


def baseline_from_bundles(ctx, courses):
    """还没有快照：从首次全量采集的 raw/bundle_<id>.json 重建一份。"""
    assignments, modules, group_ws = {}, {}, {}
    for cid, code in courses:
        b = jload(ctx.P("raw", f"bundle_{cid}.json"), {}) or {}
        assignments[code] = b.get("assignments") or []
        modules[code] = b.get("modules") or []
        group_ws[code] = {g["id"]: g.get("group_weight") for g in b.get("groups") or []}
    snap = snapshot_from(courses, assignments, modules, group_ws, {}, {})
    snap["baseline"] = True
    return snap, assignments


def load_snapshot(ctx):
    return jload(ctx.P("raw", "daily", "snapshot.json"))


def cacheable_snapshot(ctx):
    """Only a complete, successfully promoted snapshot may satisfy the 10-minute cache."""
    snap = load_snapshot(ctx)
    if not snap or snap.get("complete") is False:
        return None
    # Legacy snapshots predate the complete flag. Reject one when its matching
    # digest records errors; this repairs caches poisoned by older versions.
    rd = raw_dir_abs(ctx, snap)
    digest = jload(os.path.join(rd, "digest.json")) if rd else latest_digest(ctx)
    if (digest and digest.get("collected_at") == snap.get("collected_at") and digest.get("errors")):
        return None
    return snap


def raw_dir_abs(ctx, snap):
    rd = (snap or {}).get("raw_dir")
    if not rd:
        return None
    return rd if os.path.isabs(rd) else ctx.P(rd)


def latest_digest(ctx):
    files = sorted(glob.glob(ctx.P("raw", "daily", "*", "digest.json")))
    return jload(files[-1]) if files else None


def _collect_lock_path(ctx):
    return ctx.P("raw", "collect.lock")


def collect(ctx, date, quick=False, touch=False, download=None):
    """Serialize canonical collection so two agent sessions cannot race."""
    lock = FileLock(_collect_lock_path(ctx))
    if not lock.acquire(blocking=False):
        now = ctx.clock.now_utc().isoformat()
        return {"date": date, "collected_at": now, "quick": quick, "complete": False, "promoted": False,
                "errors": ["已有一次 Canvas 采集正在运行；本次没有覆盖快照，请稍后重试"], "readiness": {},
                "new_announcements": [], "staff_messages": [], "changed_assignments": [], "submission_changes": [],
                "new_items": [], "unlocked_items": [], "locked_items": [], "downloaded": [],
                "skipped_downloads": [], "removed_items": []}
    try:
        return _collect_unlocked(ctx, date, quick=quick, touch=touch, download=download)
    finally:
        lock.release()


def _collect_unlocked(ctx, date, quick=False, touch=False, download=None):
    cfg, state, clock = ctx.cfg, ctx.state, ctx.clock
    courses = course_pairs(cfg)
    rawdir = ctx.P("raw", "daily", date)
    os.makedirs(rawdir, exist_ok=True)
    api = ctx.api
    errors = []
    pending_raw = {}
    collected_at = clock.now_utc().isoformat()

    def get(path, name=None):
        try:
            data = api.get(path)
        except urllib.error.HTTPError as e:
            errors.append(f"HTTP {e.code}: {path.split('?')[0]}")
            return None
        except urllib.error.URLError as e:
            errors.append(f"网络错误 {path.split('?')[0]}: {e.reason}")
            return None
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {path.split('?')[0]}")
            return None
        if name:
            pending_raw[name] = data
        return data

    prev = load_snapshot(ctx)
    assignments, modules, group_ws = {}, {}, {}
    for cid, code in courses:
        assignments[code] = get(f"/api/v1/courses/{cid}/assignments?per_page=100&include[]=submission", f"assignments_{cid}.json")
        modules[code] = None if quick else get(f"/api/v1/courses/{cid}/modules?per_page=50&include[]=items&include[]=content_details", f"modules_{cid}.json")
        b = jload(ctx.P("raw", f"bundle_{cid}.json"), {}) or {}
        group_ws[code] = {g["id"]: g.get("group_weight") for g in b.get("groups") or []}
    last_check = parse_ts(state.get("last_check")) or (clock.now_utc() - dt.timedelta(days=14))
    start = (last_check - dt.timedelta(days=1)).date().isoformat()
    ctxq = "&".join(f"context_codes[]=course_{cid}" for cid, _ in courses)
    anns = get(f"/api/v1/announcements?{ctxq}&start_date={start}&per_page=50", "announcements.json") or []
    convs = [] if quick else (get("/api/v1/conversations?scope=inbox&per_page=30", "conversations.json") or [])

    readiness = {}
    if not quick:
        for site in cfg.get("extra_sites") or []:
            if site.get("until") and date > str(site["until"]):
                continue
            label = site.get("label") or f"{site.get('kind')} {site.get('course_id')}"
            n0 = len(errors)
            if site.get("kind") == "exam_site":
                r = get(f"/api/v1/courses/{site['course_id']}", f"site_{site['course_id']}.json")
                if r is None:
                    e = errors[n0] if len(errors) > n0 else "未知"
                    del errors[n0:]  # readiness probes are optional; never freeze core deadlines
                    if e.startswith("HTTP 403") or e.startswith("HTTP 401"):
                        readiness[label] = "403 未开放"
                    else:
                        readiness[label] = e
                else:
                    readiness[label] = f"已开放：{r.get('name')}（{r.get('workflow_state')}）"
            elif site.get("kind") == "byod_quiz" and site.get("assignment_id"):
                r = get(f"/api/v1/courses/{site['course_id']}/assignments/{site['assignment_id']}/submissions/self",
                        f"quiz_{site['assignment_id']}.json")
                if isinstance(r, dict):
                    readiness[label] = f"{r.get('workflow_state')}" + (f"，提交于 {clock.fmt(parse_ts(r.get('submitted_at')))}" if r.get("submitted_at") else "")
                elif r is None and len(errors) > n0:
                    readiness[label] = errors[n0]
                    del errors[n0:]  # optional readiness failure is reported, not promoted as core failure

    if errors:
        # Never turn partial/empty responses into the canonical truth. In
        # particular, do not advance last_fetch/last_check: the next collect
        # must retry instead of reusing this failed attempt for ten minutes.
        failure_path = os.path.join(rawdir, "last_failure.json")
        failure = {"date": date, "collected_at": collected_at, "quick": quick, "complete": False,
                   "promoted": False, "errors": errors, "readiness": readiness,
                   "new_announcements": [], "staff_messages": [], "changed_assignments": [],
                   "submission_changes": [], "new_items": [], "unlocked_items": [],
                   "locked_items": [], "downloaded": [], "skipped_downloads": [], "removed_items": []}
        failure["failure_path"] = failure_path
        jsave(failure_path, failure)
        return failure

    old_assign = {}
    if prev is None:
        prev, old_assign = baseline_from_bundles(ctx, courses)
    else:
        rd = raw_dir_abs(ctx, prev)
        if rd:
            for cid, code in courses:
                old_assign[code] = jload(os.path.join(rd, f"assignments_{cid}.json"), []) or []
    old_desc = {str(a["id"]): a.get("description") or "" for lst in old_assign.values() for a in lst}
    # Promote raw endpoint responses only after every required request has
    # succeeded and after the previous same-day snapshot has been read.
    for name, data in pending_raw.items():
        jsave(os.path.join(rawdir, name), data)

    ann_ids = {str(a["id"]): a.get("posted_at") for a in anns}
    conv_ids = {str(c["id"]): c.get("last_message_at") for c in convs}
    snap = snapshot_from(courses, assignments, modules, group_ws, ann_ids, conv_ids)
    if quick:  # 模块和站内信没重新拉，沿用上次的
        snap["items"] = dict(prev.get("items") or {})
        snap["conversations"] = dict(prev.get("conversations") or {})
    snap["raw_dir"] = ctx.rel(rawdir)
    snap["collected_at"] = collected_at
    snap["complete"] = True
    for k in ("announcements", "conversations"):
        for i, v in (prev.get(k) or {}).items():
            snap[k].setdefault(i, v)

    digest = {"date": date, "collected_at": collected_at, "quick": quick, "complete": True, "promoted": True,
              "errors": errors, "readiness": readiness,
              "new_announcements": [], "staff_messages": [], "changed_assignments": [], "submission_changes": [],
              "new_items": [], "unlocked_items": [], "locked_items": [], "downloaded": [], "skipped_downloads": [], "removed_items": []}
    baseline = bool(prev.get("baseline"))
    cstate = state.get("courses") or {}

    for a in anns:
        code = next((k for c, k in courses if a.get("context_code") == f"course_{c}"), None)
        posted = parse_ts(a.get("posted_at"))
        seen_at = parse_ts((cstate.get(code) or {}).get("latest_announcement_at")) if code else None
        is_new = str(a["id"]) not in (prev.get("announcements") or {}) if not baseline else (seen_at is None or (posted and posted > seen_at))
        if is_new:
            digest["new_announcements"].append({
                "id": a["id"], "course": code, "posted_at": a.get("posted_at"), "when": clock.fmt(posted),
                "title": a.get("title"), "author": (a.get("author") or {}).get("display_name"),
                "url": a.get("html_url"), "text": strip_html(a.get("message"), 2500)})

    for c in convs:
        code = course_of_context(c.get("context_name"), courses)
        if not code:
            continue
        lm = parse_ts(c.get("last_message_at"))
        if baseline:
            cutoff = parse_ts((cstate.get(code) or {}).get("last_fetch")) or last_check
            is_new = bool(lm and lm > cutoff)
        else:
            is_new = (prev.get("conversations") or {}).get(str(c["id"])) != c.get("last_message_at")
        if is_new:
            digest["staff_messages"].append({
                "id": c["id"], "course": code, "subject": c.get("subject"), "when": clock.fmt(lm),
                "last_message_at": c.get("last_message_at"), "state": c.get("workflow_state"),
                "from": [p.get("name") for p in c.get("participants") or []],
                "text": strip_html(c.get("last_message"), 1500)})

    pa = prev.get("assignments") or {}
    for aid, cur in snap["assignments"].items():
        old = pa.get(aid)
        if not old:
            digest["changed_assignments"].append({"id": aid, **cur, "change": "新作业"})
            continue
        fields = [(k, old.get(k), cur.get(k)) for k in ("name", "due_at", "lock_at", "unlock_at", "points") if old.get(k) != cur.get(k)]
        desc_changed = old.get("desc_hash") != cur.get("desc_hash")
        if fields or desc_changed:
            entry = {"id": aid, "course": cur["course"], "name": cur["name"], "url": cur["html_url"],
                     "fields": [{"field": k, "old": o, "new": n} for k, o, n in fields], "updated_at": cur.get("updated_at")}
            if desc_changed:
                new_desc = next((x.get("description") or "" for x in assignments.get(cur["course"]) or [] if str(x["id"]) == aid), "")
                od, nd = strip_html(old_desc.get(aid, "")).splitlines(), strip_html(new_desc).splitlines()
                diff = [l for l in difflib.unified_diff(od, nd, lineterm="", n=0) if l[:1] in "+-" and not l.startswith(("+++", "---"))]
                entry["description_diff"] = [l[:600] for l in diff[:30]] or [DESC_UNCHANGED]
            digest["changed_assignments"].append(entry)
        sch = [(k, old.get(k), cur.get(k)) for k in ("sub_state", "submitted_at", "attempt", "score", "grade", "graded_at", "posted_at") if old.get(k) != cur.get(k)]
        if sch:
            digest["submission_changes"].append({"id": aid, "course": cur["course"], "name": cur["name"], "url": cur["html_url"],
                                                 "changes": [{"field": k, "old": o, "new": n} for k, o, n in sch],
                                                 "attachments": cur.get("attachments"), "posted": bool(cur.get("posted_at"))})

    if not quick:
        pi = prev.get("items") or {}
        for iid, it in snap["items"].items():
            old = pi.get(iid)
            if not old:
                digest["new_items"].append({"id": iid, **it})
            elif old.get("locked") and not it["locked"]:
                digest["unlocked_items"].append({"id": iid, **it})
            if it["locked"]:
                digest["locked_items"].append({"course": it["course"], "module": it["module"], "title": it["title"], "unlock_at": it["unlock_at"]})
        for iid, it in pi.items():
            if iid not in snap["items"]:
                digest["removed_items"].append({"id": iid, **it})
        want = [it for it in digest["new_items"] + digest["unlocked_items"]
                if it["type"] == "File" and it["title"].lower().endswith(DOC_EXT) and not it["locked"]]
        added, total = queue_downloads(ctx, want)  # 采集不下载：课件排队，后台或用到时再下，周报和 deadline 永远先出
        digest["queued_downloads"] = total
        digest["skipped_downloads"] = [{"course": it["course"], "module": it["module"], "title": it["title"], "url": it.get("url"), "reason": "已排队"} for it in want]
    else:
        digest["locked_items"] = list(state.get("locked_materials") or [])

    digest["snapshot"] = snap
    jsave(os.path.join(rawdir, "digest.json"), digest)
    # 采集完就把快照提升为「上次」：雷达和本周清单读它；新变化 = 自上次采集以来
    jsave(ctx.P("raw", "daily", "snapshot.json"), snap)
    if not ctx.is_v1:
        now_iso = clock.now_utc().isoformat()
        state["last_fetch"] = collected_at
        cs = state.setdefault("courses", {})
        for cid, code in courses:
            c = cs.setdefault(code, {})
            c["last_fetch"] = collected_at
            latest = parse_ts(c.get("latest_announcement_at"))
            for a in digest["new_announcements"]:
                t = parse_ts(a.get("posted_at"))
                if a.get("course") == code and t and (latest is None or t > latest):
                    latest = t
            if latest:
                c["latest_announcement_at"] = latest.strftime("%Y-%m-%dT%H:%M:%SZ")
            c.setdefault("counts", {})["assignments"] = sum(1 for a in snap["assignments"].values() if a.get("course") == code)
        state["locked_materials"] = digest["locked_items"]
        if touch:
            state["last_check"] = now_iso
        ctx.save_state()
    return digest
