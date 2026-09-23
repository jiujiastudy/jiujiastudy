"""deadline 行和雷达要查的东西：未来 N 天的 deadline（Canvas + 手动 + 没写日期 + 已过期未交）、
今天的周计划行、复习计划的今天、待确认。纯数据，不联网。
"""
import datetime as dt
import glob
import html as html_mod
import os
import re

from cc_courses import lms_label
from cc_store import jload
from cc_time import norm_hhmm, parse_date, parse_ts, text_datetimes

EXAM_RE = re.compile(r"(?i)\b(exam|test|quiz|midterm|final)\b|考试|测验|小测")
SUBMITTED = ("submitted", "graded", "pending_review")  # Canvas 认这三种叫交了
def _ann_texts(ctx, days=120):
    """公告全文索引：{课程代码: [(发布时间, 标题, 链接, 正文), ...]}，新的在前。

    先读每天采集存下的 raw/daily/<日期>/announcements.json，再补 raw/bundle_<课程id>.json（老档案才有）。
    这里要的是全文：digest 里的 text 会被截断，日期常常正好在截断之后。
    """
    pairs = [(c.get("id"), c.get("code")) for c in (ctx.cfg.get("courses") or []) if c.get("code")]
    by_id = {str(cid): code for cid, code in pairs if cid}
    out, seen = {}, set()
    daily = ctx.P("raw", "daily")  # Moodle 另有课程页文字 moodle_texts.json（同公告形状）；Canvas 档案没有这个文件
    files = sorted(glob.glob(os.path.join(daily, "*", "announcements.json")) + glob.glob(os.path.join(daily, "*", "moodle_texts.json")),
                   reverse=True)
    files += sorted(glob.glob(os.path.join(ctx.P("raw"), "bundle_*.json")))
    for path in files:
        data = jload(path, None)
        anns = data if isinstance(data, list) else ((data or {}).get("announcements") or [])
        cid_from_name = os.path.basename(path)[7:-5] if os.path.basename(path).startswith("bundle_") else None
        for a in anns if isinstance(anns, list) else []:
            if not isinstance(a, dict) or a.get("id") in seen:
                continue
            seen.add(a.get("id"))
            ctxc = str(a.get("context_code") or "")
            code = by_id.get(ctxc[7:]) or by_id.get(cid_from_name or "")
            if not code:
                continue
            text = re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", " ", a.get("message") or "")))
            out.setdefault(code, []).append((a.get("posted_at") or "", a.get("title") or "", a.get("html_url"), text))
    for code in out:
        out[code].sort(reverse=True)
    return out


def _name_key(name):
    """作业名去掉括号里的权重等杂项，留下拿去和公告比对的那部分。"""
    return re.sub(r"\s+", " ", re.sub(r"[（(][^）)]*[）)]", " ", name or "")).strip().lower()


def announced_date(ctx, a, today, end, index, exam_only_one):
    """作业页没写日期时，看公告里有没有写明。找到返回 (date, "HH:MM" 或 None, 标题)，否则 None。

    保守：只认同一门课的公告；要么公告里出现作业名本身，要么双方都像考试且这门课只有这一件没写日期的考试。
    同一条公告里出现两个都落在窗口内的日期，算含糊，不用。
    """
    name = a.get("name") or ""
    key = _name_key(name)
    examish = bool(a.get("is_quiz")) or bool(EXAM_RE.search(name))
    for posted, title, url, text in index.get(a.get("course"), []):
        blob = (title + " " + text).lower()
        strong = len(key) >= 4 and key in blob
        if not strong and not (examish and EXAM_RE.search(title or "") and exam_only_one):
            continue
        hits = [(d, hhmm) for d, hhmm in text_datetimes(title + "。" + text, today) if today <= d <= end]
        if len(set(d for d, _ in hits)) != 1:
            continue  # 没有，或者不止一个，都不猜
        d, hhmm = hits[0]
        return d, hhmm, title
    return None


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


def manual_row(clock, m, now, start, end):
    """一条手动 deadline → 雷达行（不在窗口里返回 None）。日期或时刻是自己记的，可能写错：
    写错的那行不丢也不崩，标「时间写错了」进待确认，等 record deadline --list / --remove 收拾。"""
    d = parse_date(m.get("date"))
    hhmm = norm_hhmm(m.get("time")) if m.get("time") else None
    bad = bool(m.get("time")) and not hhmm
    row = {"id": None, "course": m.get("course", ""), "item": m.get("item", ""), "url": m.get("url"),
           "weight": m.get("weight", "—"), "status": m.get("status", ""), "note": m.get("note", ""),
           "src": m.get("source", ""), "pending": bool(m.get("pending")), "origin": "manual",
           "kind": "exam" if EXAM_RE.search(m.get("item") or "") else "assignment", "submission_types": [],
           "overdue": False, "undated": False}
    if not d:
        row.update({"t": clock.course_local_to_utc(end, "23:59"), "date": None, "when": "时间写错了",
                    "rel": "", "days_left": None, "pending": True, "undated": True})
        return row
    if not start <= d <= end:
        return None
    t = clock.course_local_to_utc(d, hhmm or "00:00")     # 排序用：没写时刻的排在那天最前
    due = clock.course_local_to_utc(d, hhmm or "23:59")   # 比较用：没写时刻的算到那天结束
    when = f"{clock.fmt_date(d)} 时间写错了" if bad else (
        clock.fmt(t) if hhmm else f"{clock.fmt_date(d)} {m.get('time_text', '')}".strip())
    row.update({"t": t, "date": d, "when": when, "rel": clock.rel(due, now), "days_left": (d - start).days,
                "pending": row["pending"] or bad})
    return row


def deadline_rows(ctx, snap, today, days=14, include_overdue=True, include_undated=True):
    """未来 days 天的 deadline：Canvas due_at（没有就用 lock_at）+ 手动 deadline + 没写日期的计分作业 / 考试（待确认）+ 已过期未交。纯数据。
    state.deadline_notes[作业id] 说明过的（如「Canvas 日期只是占位」）：不算过期，进区块二带着说明；
    手动 deadline 的 url 或 assignment_id 指向同一作业时，Canvas 那行不再出现（以手动的为准）。

    比较只用两样东西：真实时刻（now，--date 可以钉住）决定过没过期，课程时区的日历天决定今天 / 明天 / 还有几天和 14 天窗口。
    手动 deadline 也先按课程时区换算成时刻再比；参数 today 是用户时区的今天，只留给调用方对齐报告日期。"""
    clock, state = ctx.clock, ctx.state
    lbl = lms_label(getattr(ctx, "cfg", None))  # 给人看的平台名：Canvas 档案下逐字不变
    now = clock.now_utc()
    start = clock.show_date(now)
    end = start + dt.timedelta(days=days)
    oldest = now - dt.timedelta(days=21)  # 已过期未交只回看 21 天
    notes = {str(k): v for k, v in (state.get("deadline_notes") or {}).items() if v}
    manual = state.get("manual_deadlines") or []
    _idx = {}

    def ann_index():  # 只有真的有没写日期的计分项时才去读公告
        if not _idx:
            _idx.update(_ann_texts(ctx) or {"": []})
        return _idx

    only_exam = {}  # 每门课有几件「没写日期的考试」：只有一件时才敢按公告配对
    for _a in (snap.get("assignments") or {}).values():
        if not _a.get("due_at") and not _a.get("lock_at") and (_a.get("is_quiz") or EXAM_RE.search(_a.get("name") or "")):
            only_exam[_a.get("course")] = only_exam.get(_a.get("course"), 0) + 1
    manual_aids = set()
    for m in manual:
        mm = re.search(r"/assignments/(\d+)|/mod/\w+/view\.php\?(?:[^#]*&)?id=(\d+)", m.get("url") or "")  # Canvas / Moodle 的作业链接
        if mm:
            manual_aids.add(mm.group(1) or mm.group(2))
        if m.get("assignment_id"):
            manual_aids.add(str(m["assignment_id"]))
    rows = []

    def base(a, aid):  # noqa: C901
        name = a.get("name") or ""
        w = a.get("weight")
        if not w or w == "—":
            pm = re.search(r"\d+(?:\.\d+)?\s*%", name)
            w = pm.group(0).replace(" ", "") if pm else "—"
        return {"id": aid, "course": a["course"], "item": name, "url": a.get("html_url"), "weight": w,
                "status": status_text(a, clock), "note": notes.get(str(aid), ""), "origin": "canvas",
                "kind": "exam" if (a.get("is_quiz") or EXAM_RE.search(name)) else "assignment",
                "submission_types": a.get("submission_types") or [], "overdue": False, "undated": False,
                "submitted": a.get("sub_state") in SUBMITTED}

    for aid, a in ((snap or {}).get("assignments") or {}).items():
        if str(aid) in manual_aids:
            continue
        name = a.get("name") or ""
        via_lock = not a.get("due_at") and bool(a.get("lock_at"))
        due = parse_ts(a.get("due_at")) or (parse_ts(a.get("lock_at")) if via_lock else None)
        graded = (a.get("points") or 0) > 0
        counts = graded or bool(a.get("is_quiz")) or bool(EXAM_RE.search(name)) or bool(re.search(r"\d+\s*%", name))
        unsub = a.get("sub_state") not in SUBMITTED
        noted = notes.get(str(aid))
        if due:
            d = clock.show_date(due)
            if noted and unsub and due <= now:
                if include_undated:
                    r = base(a, aid)
                    r.update({"t": clock.course_local_to_utc(end, "23:59"), "date": None, "when": f"{clock.fmt(due)}（{lbl} 日期只是占位）",
                              "rel": "", "days_left": None, "pending": True, "undated": True, "src": f"你说明过：{noted}"})
                    rows.append(r)
            elif now < due and d <= end:
                r = base(a, aid)
                r.update({"t": due, "date": d, "when": clock.fmt(due) + ("（锁定时间当截止）" if via_lock else ""), "rel": clock.rel(due, now),
                          "days_left": (d - start).days, "pending": via_lock, "src": f"{lbl} lock_at" if via_lock else f"{lbl} due_at"})
                rows.append(r)
            elif include_overdue and counts and unsub and not noted and oldest <= due <= now:
                r = base(a, aid)
                r.update({"t": due, "date": d, "when": clock.fmt(due), "rel": clock.rel(due, now), "days_left": (d - start).days,
                          "pending": False, "overdue": True, "src": f"{lbl} due_at"})
                rows.append(r)
        elif include_undated and counts and unsub:
            ua = parse_ts(a.get("unlock_at"))
            r = base(a, aid)
            hit = announced_date(ctx, a, start, end, ann_index(), only_exam.get(a.get("course"), 0) == 1)
            if hit:  # 作业页没写，但公告里写明了：填上日期，仍然留在「待确认」区
                d, hhmm, title = hit
                t = clock.course_local_to_utc(d, hhmm or "23:59")
                r.update({"t": t, "date": d, "when": clock.fmt(t) + ("" if hhmm else "（公告只写了日期）"),
                          "rel": clock.rel(t, now), "days_left": (d - start).days,
                          "pending": True, "undated": False, "src": f"公告《{title}》"})
            else:
                when = (f"{clock.fmt_date(clock.show_date(ua))} 解锁，截止未写" if ua and clock.show_date(ua) > start else f"{lbl} 没写日期")
                r.update({"t": clock.course_local_to_utc(end, "23:59"), "date": None, "when": when, "rel": "", "days_left": None,
                          "pending": True, "undated": True, "src": "作业页没有 due_at"})
            rows.append(r)
    _moodle_hints(rows, (snap or {}).get("assignments") or {}, lbl)
    for m in manual:
        rows.append(manual_row(clock, m, now, start, end))
    rows = [r for r in rows if r]
    rows.sort(key=lambda r: r["t"])
    return rows


def _moodle_hints(rows, assignments, lbl):
    """Moodle 的行：推断出的「可能已交」、只有「预期完成日期」、日历被过滤的，都标待确认并说清楚。
    只看快照里 Moodle 作业才有的 moodle 键，Canvas 的行不动。"""
    for r in rows:
        m = (assignments.get(str(r.get("id"))) or {}).get("moodle")
        if not m:
            continue
        if m.get("status_confidence") == "maybe" and not r.get("submitted"):
            r.update(status="可能已交，待确认", pending=True)
        if m.get("date_from") == "expected" and r.get("date"):
            r.update(pending=True, src=f"{lbl} 预期完成日期（不是硬性截止）")
        if m.get("calendar_empty") and r.get("undated") and r.get("when") == f"{lbl} 没写日期":
            r["when"] = "日历里没看到日期（可能被过滤）"
