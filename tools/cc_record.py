"""记账：INDEX.md 行、成果日志一行、state.json 的列表与时间戳。所有落盘经这里，格式只有一种。"""
import glob
import os
import re

from cc_config import CoachError
from cc_store import jload, jsave
from cc_time import norm_date, norm_hhmm, parse_date

INDEX_HEADER = ["# 产物索引", "", "| 文件 | 日期 | 课程 | 状态 |", "|---|---|---|---|"]
INDEX_LEGEND = "> 📦 = 已交付；✅ = 你确认读过/做过。只有你说了才改成 ✅。"


def _read(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def append_log(ctx, text):
    p = ctx.P("成果日志.md")
    text = re.sub(r"\s*\n\s*", "；", (text or "").strip())
    existing = _read(p)
    prefix = "# 成果日志\n\n" if not existing else ("" if existing.endswith("\n") else "\n")
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{prefix}- **{ctx.clock.stamp()}** — {text}\n")
    return p


def upsert_index_row(ctx, file_rel, date, course, status):
    p = ctx.P("INDEX.md")
    lines = _read(p).splitlines() or list(INDEX_HEADER)
    file_rel = file_rel.replace("\\", "/")
    label = f"[{file_rel}]({file_rel})" if "*" not in file_rel else file_rel
    row = f"| {label} | {date} | {course} | {status} |"
    hit = next((i for i, l in enumerate(lines) if l.startswith("|") and file_rel in l and not l.startswith("|---")), None)
    if hit is not None:
        lines[hit] = row
        action = "updated"
    else:
        pos = max((i for i, l in enumerate(lines) if l.startswith("> 📦")), default=None)
        if pos is None:
            if not any(l.startswith("|---") for l in lines):
                lines += INDEX_HEADER[2:]
            lines.append(row)
            lines += ["", INDEX_LEGEND]
        else:
            while pos > 0 and not lines[pos - 1].strip():
                pos -= 1
            lines.insert(pos, row)
        action = "added"
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")
    return action


def infer_course(ctx, file_rel):
    m = re.search(r"courses/([A-Za-z0-9]+)/", file_rel.replace("\\", "/"))
    if m:
        return m.group(1)
    return "全部课程"


def touch(ctx):
    ctx.state["last_record"] = ctx.clock.now_utc().isoformat()
    ctx.save_state()


def record_product(ctx, file_rel, status, course=None, log=None, date=None):
    file_rel = file_rel.replace("\\", "/")
    date = date or ctx.clock.today_user().isoformat()
    course = course or infer_course(ctx, file_rel)
    action = upsert_index_row(ctx, file_rel, date, course, status)
    append_log(ctx, log or f"{status} `{file_rel}`")
    touch(ctx)
    return {"index": action, "log": "appended", "file": file_rel, "course": course}


def next_pending_id(ctx):
    c = ctx.state.setdefault("counters", {})
    c["pending"] = int(c.get("pending") or 0) + 1
    return f"pc-{c['pending']:04d}"


def add_pending(ctx, text, course, blocks=None, ask_en=None, ask_zh=None):
    today = ctx.clock.today_user().isoformat()
    item = {"id": next_pending_id(ctx), "course": course, "text": text.strip(), "first_asked": today, "last_asked": today,
            "times_asked": 1, "blocks": blocks, "ask_en": ask_en, "ask_zh": ask_zh, "resolved": None, "resolution": None}
    ctx.state.setdefault("pending_confirmations", []).append(item)
    append_log(ctx, f"待确认 +1 [{item['id']}] {course}：{item['text']}")
    touch(ctx)
    return item


def find_pending(ctx, pid):
    for p in ctx.state.get("pending_confirmations") or []:
        if p.get("id") == pid:
            return p
    raise CoachError(f"没有这条待确认：{pid}（用 status 看编号）", 2)


def mark_asked(ctx, pid):
    p = find_pending(ctx, pid)
    p["times_asked"] = int(p.get("times_asked") or 0) + 1
    p["last_asked"] = ctx.clock.today_user().isoformat()
    touch(ctx)
    return p


def resolve_pending(ctx, pid, resolution):
    p = find_pending(ctx, pid)
    p["resolved"] = ctx.clock.today_user().isoformat()
    p["resolution"] = resolution
    append_log(ctx, f"待确认已解决 [{pid}] {p.get('course')}：{p.get('text')} → {resolution}")
    touch(ctx)
    return p


def add_decision(ctx, text, course=None):
    item = {"text": text.strip(), "course": course, "date": ctx.clock.today_user().isoformat(), "do_not_raise": True}
    ctx.state.setdefault("decisions", []).append(item)
    append_log(ctx, f"已定（不再提起）{course or ''}：{item['text']}")
    touch(ctx)
    return item


def add_note(ctx, assignment_id, text):
    """作业的说明（如「Canvas 日期只是占位，实际课上讲」）：state.deadline_notes[作业id]。雷达带着它显示，不再算过期。"""
    text = (text or "").strip()
    notes = ctx.state.setdefault("deadline_notes", {})
    if text:
        notes[str(assignment_id)] = text
    else:
        notes.pop(str(assignment_id), None)
    append_log(ctx, f"deadline 说明 [{assignment_id}]：{text or '（清除）'}")
    touch(ctx)
    return {"assignment_id": str(assignment_id), "note": text}


def deadline_text(clock, row):
    """一条手动 deadline 的时间，给人看：09-20 周日 23:59 / 09-20 周日 课上 / 时间写错了。"""
    d = parse_date(row.get("date"))
    t = row.get("time")
    if not d or (t and not norm_hhmm(t)):
        return "时间写错了"
    return " ".join(x for x in (clock.fmt_date(d), norm_hhmm(t) if t else (row.get("time_text") or "")) if x)


def list_deadlines(ctx):
    """记过的手动 deadline，序号从 1 起（--remove 用得上）。"""
    return [{"n": i, "course": m.get("course"), "item": m.get("item"), "date": m.get("date"), "time": m.get("time"),
             "time_text": m.get("time_text"), "when": deadline_text(ctx.clock, m), "pending": bool(m.get("pending")),
             "weight": m.get("weight"), "source": m.get("source")}
            for i, m in enumerate(ctx.state.get("manual_deadlines") or [], 1)]


def remove_deadline(ctx, which):
    """删掉一条手动 deadline：--list 里的序号，或事项名（写全了，或只对上一条的一段）。"""
    rows = ctx.state.get("manual_deadlines") or []
    key = str(which or "").strip()
    if key.isdigit() and 1 <= int(key) <= len(rows):
        hit = int(key) - 1
    else:
        same = [i for i, m in enumerate(rows) if (m.get("item") or "").strip().lower() == key.lower()]
        part = same or ([i for i, m in enumerate(rows) if key and key.lower() in (m.get("item") or "").lower()])
        if len(part) > 1:
            raise CoachError(f"「{key}」对上了 {len(part)} 条，用 record deadline --list 看序号再删", 2)
        if not part:
            raise CoachError(f"没有这条手动 deadline：{key}（用 record deadline --list 看序号）", 2)
        hit = part[0]
    row = rows.pop(hit)
    append_log(ctx, f"手动 deadline 删掉 {row.get('course')} {row.get('item')} {deadline_text(ctx.clock, row)}")
    touch(ctx)
    return row


def add_deadline(ctx, item, course, date, time=None, time_text=None, weight=None, url=None, note=None, source=None,
                 status=None, pending=False, assignment_id=None):
    """手动 deadline（公告 / 大纲 / 老师说的）：进雷达区块一；pending=True 进区块二。url 或 assignment_id 指向某个 Canvas 作业时替换那一行。

    日期和时刻当场规整：09-20、9/20、4pm、11:59pm、16：00 都认，认不出来就退回（退出码 2），不留到雷达那边才出事。
    同一门课同一件事再记一次是更新，不是多一条。"""
    clock = ctx.clock
    d = norm_date(date, clock.course_date(clock.now_utc()))
    if not d:
        raise CoachError(f"--due 写成 2026-09-20 或 09-20，「{date}」认不出来", 2)
    hhmm = norm_hhmm(time) if time else None
    if time and not hhmm:
        raise CoachError(f"--time 写成 23:59 或 11:59pm，「{time}」认不出来", 2)
    row = {"course": course, "item": (item or "").strip(), "date": d.isoformat(), "time": hhmm, "time_text": time_text,
           "weight": weight or "—", "status": status or "未交", "note": note or "", "source": source or "用户 / 公告", "url": url,
           "pending": bool(pending), "assignment_id": str(assignment_id) if assignment_id else None,
           "added": ctx.clock.today_user().isoformat()}
    rows = ctx.state.setdefault("manual_deadlines", [])
    old = next((x for x in rows if (x.get("item") or "").strip().lower() == row["item"].lower()
                and (x.get("course") or "").upper() == (course or "").upper()), None)
    if old:
        row["added"] = old.get("added") or row["added"]
        rows[rows.index(old)] = row
    else:
        rows.append(row)
    append_log(ctx, f"手动 deadline {'更新' if old else '+1'} {course} {row['item']} {deadline_text(clock, row)}".rstrip())
    touch(ctx)
    return dict(row, action="updated" if old else "added")


# ---------------------------------------------------------------- weekly plan ticks
def current_plan_path(ctx, today):
    from cc_deadlines import find_plan_json
    f, data = find_plan_json(ctx, today)
    if not f:
        cands = sorted(glob.glob(ctx.P("plans", "*.json")), key=os.path.getmtime, reverse=True)
        for c in cands:
            d = jload(c)
            if isinstance(d, dict) and isinstance(d.get("days"), list):
                return c, d
        raise CoachError("plans/ 里没有周计划。说「这周学什么」先排。", 2)
    return f, data


def _all_items(data):
    for c in (data.get("study") or {}).get("courses") or []:
        for k in ("before_class", "todo", "deadline_related"):
            for it in c.get(k) or []:
                yield c, it


def mark_done(ctx, target, today=None):
    """📦→✅。target：today / 今天 / YYYY-MM-DD / MM-DD / 项目 id（6936-2）/ 课程代码或后四位（该课本周条目全部）/ all。"""
    import render_week
    today = today or ctx.clock.today_user()
    path, data = current_plan_path(ctx, today)
    days = data.get("days") or []
    t = (target or "today").strip()
    tl = t.lower()
    stamp = today.isoformat()
    marked = []

    def tick_day(d):
        d["status"] = "✅"
        d["done_at"] = stamp
        marked.append(f"{d['date'][5:]} {d.get('must')}")
        if d.get("must_item_id"):
            for _, it in _all_items(data):
                if it["id"] == d["must_item_id"]:
                    it["status"] = "✅"

    def tick_item(it):
        it["status"] = "✅"
        it["done_at"] = stamp
        marked.append(f"{it['id']} {it['title']}")
        for d in days:
            if d.get("must_item_id") == it["id"]:
                d["status"] = "✅"
                d["done_at"] = stamp

    if tl in ("today", "今天", ""):
        for d in days:
            if d.get("date") == today.isoformat():
                tick_day(d)
    elif tl in ("all", "全部"):
        for d in days:
            if (d.get("date") or "") <= today.isoformat():
                tick_day(d)
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", tl):
        for d in days:
            if d.get("date") == tl:
                tick_day(d)
    elif re.fullmatch(r"\d{2}-\d{2}", tl):
        for d in days:
            if (d.get("date") or "").endswith(tl):
                tick_day(d)
    elif re.fullmatch(r"[a-z0-9]{2,6}-\d{1,3}", tl):
        for _, it in _all_items(data):
            if it["id"].lower() == tl:
                tick_item(it)
    else:
        code = t.upper()
        hit = False
        for c, it in _all_items(data):
            if c["code"].upper().endswith(code) and it["kind"] in ("Page", "File", "Video", "ExternalUrl", "Other") and it["status"] != "✅":
                tick_item(it)
                hit = True
        if not hit:
            cands = [d for d in days if code in (d.get("must") or "").upper() or code in (d.get("must_course") or "").upper()]
            past = [d for d in cands if (d.get("date") or "") <= today.isoformat()]
            if past or cands:
                tick_day((past or cands)[-1])
    if not marked:
        raise CoachError(f"周计划里没找到「{target}」对应的项（用 status 看今天那行，或 study 看项目编号）", 2)
    jsave(path, data)
    res = render_week.write(path, week_no=data.get("week_no") or week_no_of(ctx, data))
    render_week.publish(ctx, res.get("html"))
    ctx.state["current_plan"] = ctx.rel(path)
    ctx.state["last_done"] = ctx.clock.now_utc().isoformat()
    append_log(ctx, "✅ " + "；".join(marked))
    touch(ctx)
    nxt = next((d for d in days if (d.get("date") or "") > today.isoformat() and d.get("status") != "✅"), None)
    return {"marked": marked, "plan": path, "html": res.get("html"), "md": res.get("md"),
            "next": ({"date": nxt.get("date"), "must": nxt.get("must"), "first_step": nxt.get("must_first_step")} if nxt else None)}


def week_no_of(ctx, data):
    import render_week
    mon = render_week.iso_week_monday(data.get("week") or "")
    return ctx.clock.week_no(mon) if mon else None


# ---------------------------------------------------------------- legacy daily report bookkeeping
def after_render(ctx, date, out_abs, digest, offline, n_changes, n_rows, one_title, errors, shown_pending_ids):
    from cc_time import parse_ts
    state, clock = ctx.state, ctx.clock
    now = clock.now_utc()
    state["last_check"] = now.isoformat()
    if not offline:
        state["last_fetch"] = digest.get("collected_at")
        snap = digest.get("snapshot") or {}
        cs = state.setdefault("courses", {})
        for code in [c["code"] for c in ctx.cfg.get("courses") or []]:
            c = cs.setdefault(code, {})
            c["last_fetch"] = digest.get("collected_at")
            latest = parse_ts(c.get("latest_announcement_at"))
            for a in digest.get("new_announcements") or []:
                t = parse_ts(a.get("posted_at"))
                if a.get("course") == code and t and (latest is None or t > latest):
                    latest = t
            if latest:
                c["latest_announcement_at"] = latest.strftime("%Y-%m-%dT%H:%M:%SZ")
        state["locked_materials"] = digest.get("locked_items") or []
        jsave(ctx.P("raw", "daily", "snapshot.json"), snap)
    for p in state.get("pending_confirmations") or []:
        if p.get("id") in shown_pending_ids:
            p["times_asked"] = int(p.get("times_asked") or 0) + 1
            p["last_asked"] = date
    rel = ctx.rel(out_abs)
    state["daily_report"] = {"last_date": date, "last_report": rel, "offline": offline}
    upsert_index_row(ctx, rel, date, "全部课程", f"📦 已生成 · 新变化 {n_changes} 条 · 14 天内 deadline {n_rows} 条{'（离线，采集失败）' if offline else ''}")
    append_log(ctx, f"日报 `{rel}`{'（离线模式）' if offline else ''}：新变化 {n_changes} 条，14 天内 deadline {n_rows} 条，"
                    f"今天最该做：{re.sub(r'[*`]', '', one_title or '')[:80]}。" + (f" 采集问题：{'；'.join(errors)}。" if errors else ""))
    touch(ctx)
