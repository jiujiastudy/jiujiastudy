"""deadline 行和雷达要查的东西：未来 N 天的 deadline（Canvas + 手动 + 没写日期 + 已过期未交）、
今天的周计划行、复习计划的今天、待确认。纯数据，不联网。
"""
import datetime as dt
import glob
import os
import re

from cc_store import jload
from cc_time import parse_date, parse_ts

EXAM_RE = re.compile(r"(?i)\b(exam|test|quiz|midterm|final)\b|考试|测验|小测")


def unresolved_pending(state, today=None, soon_days=None):
    out = []
    for p in state.get("pending_confirmations") or []:
        if p.get("resolved"):
            continue
        if soon_days is not None and today is not None:
            b = parse_date(p.get("blocks"))
            if b and (b - today).days > soon_days:
                continue
        out.append(p)
    return out


def find_plan_json(ctx, date):
    """当前周计划 JSON：state.current_plan 优先，否则 plans/ 里含今天日期行的、最新的那个。"""
    cands = []
    cp = (ctx.state or {}).get("current_plan")
    if cp and os.path.exists(ctx.P(cp)):
        cands.append(ctx.P(cp))
    cands += sorted(glob.glob(ctx.P("plans", "*.json")), key=os.path.getmtime, reverse=True)
    iso = date.isoformat()
    seen = set()
    for f in cands:
        if f in seen:
            continue
        seen.add(f)
        data = jload(f)
        if not isinstance(data, dict) or not isinstance(data.get("days"), list):
            continue
        if any(d.get("date") == iso for d in data["days"]):
            return f, data
    return None, None


def plan_today(ctx, date):
    f, data = find_plan_json(ctx, date)
    if data:
        days = data["days"]
        d = next(x for x in days if x.get("date") == date.isoformat())
        return {"file": f, "kind": "json", "data": data, "must": d.get("must"), "should": d.get("should") or [],
                "status": d.get("status") or "📦", "first_step": d.get("must_first_step"), "if_then": d.get("must_if_then"),
                "minutes": d.get("must_minutes"), "who": d.get("must_who"), "kind_of": d.get("must_kind"),
                "rows": len(days), "boxes": sum(1 for x in days if (x.get("status") or "📦") != "✅"),
                "done": sum(1 for x in days if x.get("status") == "✅"), "fixed": d.get("fixed") or [], "revise": d.get("revise")}
    mmdd = date.strftime("%m-%d")
    files = sorted(glob.glob(ctx.P("plans", "*.md")), key=lambda f: (not re.search(r"\d{4}-W\d{2}\.md$", f), f))
    for f in files:
        try:
            lines = open(f, encoding="utf-8").read().splitlines()
        except OSError:
            continue
        for line in lines:
            if re.match(rf"^\|\s*{re.escape(mmdd)}\b", line):
                cells = [c.strip() for c in line.strip().strip("|").split("|")] + ["", "", "", ""]
                rows = [l for l in lines if re.match(r"^\|\s*\d{2}-\d{2}\b", l)]
                return {"file": f, "kind": "md", "must": cells[1], "should": [cells[2]] if cells[2] else [], "status": cells[3] or "📦",
                        "first_step": None, "if_then": None, "rows": len(rows),
                        "boxes": sum("📦" in l for l in rows), "done": sum("✅" in l for l in rows), "fixed": [], "revise": None}
    return None


def exam_today(ctx, date):
    ep = ctx.cfg.get("exam_prep") or {}
    if not ep.get("dir"):
        return None
    if ep.get("until") and date.isoformat() > str(ep["until"]):
        return None
    plan = jload(ctx.P(ep["dir"], "plan.json"), {}) or {}
    for d in plan.get("days") or []:
        if d.get("date") == date.isoformat():
            f = d.get("file")
            path = os.path.normpath(ctx.P(ep["dir"], f)) if f else None
            return {**d, "course": ep.get("course"), "path": path if path and os.path.exists(path) else None}
    return None


def status_text(a, clock):
    st = a.get("sub_state")
    if st == "graded":
        s = "已批改"
        if a.get("posted_at") and a.get("score") is not None:
            s += f"，{a['score']:g}/{a.get('points') or 0:g}"
        elif not a.get("posted_at"):
            s += "（分数未发布）"
        return s
    if st == "submitted":
        return f"已交 {clock.fmt(parse_ts(a.get('submitted_at')))}" + (f"，第 {a['attempt']} 次" if (a.get("attempt") or 0) > 1 else "")
    return "未交"


def deadline_rows(ctx, snap, today, days=14, include_overdue=True, include_undated=True):
    """未来 days 天的 deadline：Canvas due_at（没有就用 lock_at）+ 手动 deadline + 没写日期的计分作业 / 考试（待确认）+ 已过期未交。纯数据。
    state.deadline_notes[作业id] 说明过的（如「Canvas 日期只是占位」）：不算过期，进区块二带着说明；
    手动 deadline 的 url 或 assignment_id 指向同一作业时，Canvas 那行不再出现（以手动的为准）。"""
    clock, state = ctx.clock, ctx.state
    end = today + dt.timedelta(days=days)
    notes = {str(k): v for k, v in (state.get("deadline_notes") or {}).items() if v}
    manual = state.get("manual_deadlines") or []
    manual_aids = set()
    for m in manual:
        mm = re.search(r"/assignments/(\d+)", m.get("url") or "")
        if mm:
            manual_aids.add(mm.group(1))
        if m.get("assignment_id"):
            manual_aids.add(str(m["assignment_id"]))
    rows = []

    def base(a, aid):
        name = a.get("name") or ""
        w = a.get("weight")
        if not w or w == "—":
            pm = re.search(r"\d+(?:\.\d+)?\s*%", name)
            w = pm.group(0).replace(" ", "") if pm else "—"
        return {"id": aid, "course": a["course"], "item": name, "url": a.get("html_url"), "weight": w,
                "status": status_text(a, clock), "note": notes.get(str(aid), ""), "origin": "canvas",
                "kind": "exam" if (a.get("is_quiz") or EXAM_RE.search(name)) else "assignment",
                "submission_types": a.get("submission_types") or [], "overdue": False, "undated": False}

    for aid, a in ((snap or {}).get("assignments") or {}).items():
        if str(aid) in manual_aids:
            continue
        name = a.get("name") or ""
        via_lock = not a.get("due_at") and bool(a.get("lock_at"))
        due = parse_ts(a.get("due_at")) or (parse_ts(a.get("lock_at")) if via_lock else None)
        graded = (a.get("points") or 0) > 0
        counts = graded or bool(a.get("is_quiz")) or bool(EXAM_RE.search(name)) or bool(re.search(r"\d+\s*%", name))
        unsub = a.get("sub_state") not in ("submitted", "graded", "pending_review")
        noted = notes.get(str(aid))
        if due:
            d = clock.course_date(due)
            if noted and unsub and d < today:
                if include_undated:
                    r = base(a, aid)
                    r.update({"t": clock.course_local_to_utc(end, "23:59"), "date": None, "when": f"{clock.fmt(due)}（Canvas 日期只是占位）",
                              "rel": "", "days_left": None, "pending": True, "undated": True, "src": f"你说明过：{noted}"})
                    rows.append(r)
            elif today <= d <= end:
                r = base(a, aid)
                r.update({"t": due, "date": d, "when": clock.fmt(due) + ("（锁定时间当截止）" if via_lock else ""), "rel": clock.rel(d, today),
                          "days_left": (d - today).days, "pending": via_lock, "src": "Canvas lock_at" if via_lock else "Canvas due_at"})
                rows.append(r)
            elif include_overdue and counts and unsub and not noted and today - dt.timedelta(days=21) <= d < today:
                r = base(a, aid)
                r.update({"t": due, "date": d, "when": clock.fmt(due), "rel": clock.rel(d, today), "days_left": (d - today).days,
                          "pending": False, "overdue": True, "src": "Canvas due_at"})
                rows.append(r)
        elif include_undated and counts and unsub:
            ua = parse_ts(a.get("unlock_at"))
            r = base(a, aid)
            when = (f"{clock.fmt_date(clock.course_date(ua))} 解锁，截止未写" if ua and clock.course_date(ua) > today else "Canvas 没写日期")
            r.update({"t": clock.course_local_to_utc(end, "23:59"), "date": None, "when": when, "rel": "", "days_left": None,
                      "pending": True, "undated": True, "src": "作业页没有 due_at"})
            rows.append(r)
    for m in manual:
        d = parse_date(m.get("date"))
        if not d or not (today <= d <= end):
            continue
        if m.get("time"):
            t = clock.course_local_to_utc(d, m["time"])
            when = clock.fmt(t)
        else:
            t = clock.course_local_to_utc(d, "00:00")
            when = f"{clock.fmt_date(d)} {m.get('time_text', '')}".strip()
        rows.append({"id": None, "t": t, "date": d, "when": when, "rel": clock.rel(d, today), "days_left": (d - today).days,
                     "course": m.get("course", ""), "item": m.get("item", ""), "url": m.get("url"),
                     "weight": m.get("weight", "—"), "status": m.get("status", ""), "note": m.get("note", ""),
                     "src": m.get("source", ""), "pending": bool(m.get("pending")), "origin": "manual",
                     "kind": "exam" if EXAM_RE.search(m.get("item") or "") else "assignment", "submission_types": [],
                     "overdue": False, "undated": False})
    rows.sort(key=lambda r: r["t"])
    return rows
