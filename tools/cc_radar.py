"""deadline 雷达（markdown / html）与一屏状态。默认不联网，读上次快照 + 手动 deadline；末尾带一句状态评估。"""
import datetime as dt
import os
import re

import brand
import cc_state
from cc_collect import latest_digest, load_snapshot
from cc_courses import lms_label, lms_of
from cc_deadlines import deadline_rows, exam_today, plan_today, unresolved_pending
from cc_downloads import load_downloads
from cc_store import save_text
from cc_time import parse_ts
from htmlkit import esc, link, rich
from design import foot, head, status as status_html, tag

MARK_START, MARK_END = "<!-- coach:radar:start -->", "<!-- coach:radar:end -->"


def rows(ctx, today, days=14):
    return deadline_rows(ctx, load_snapshot(ctx) or {}, today, days)


def split(rs):
    normal = [r for r in rs if not r.get("overdue") and not r.get("undated")]
    return normal, [r for r in rs if r.get("undated")], [r for r in rs if r.get("overdue")]


def weight_sum(group):
    tot = 0
    for r in group:
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", r.get("weight") or "")
        if m:
            tot += float(m.group(1))
    return f"{tot:g}%" if tot else ""


def clashes(rs, hours=48):
    """任意 48 小时窗口内 ≥2 门课有 deadline → 一组。"""
    rs = sorted([r for r in rs if not r.get("overdue") and not r.get("undated")], key=lambda r: r["t"])
    out, used = [], set()
    for i, r in enumerate(rs):
        if i in used:
            continue
        grp = [j for j in range(i, len(rs)) if (rs[j]["t"] - r["t"]) <= dt.timedelta(hours=hours)]
        if len({rs[j]["course"] for j in grp}) >= 2:
            out.append([rs[j] for j in grp])
            used.update(grp)
    return out


def first_step_for(r, lms="Canvas"):
    st = r.get("submission_types") or []
    if r.get("origin") == "manual":
        return "打开作业页或课程公告，确认时间、地点和要交什么。"
    if r.get("kind") == "exam" or "online_quiz" in st:
        return "打开测验页，看时长、可试次数和开放时间。"
    if "online_upload" in st:
        return "打开作业页，看文件格式和命名要求。"
    if "discussion_topic" in st:
        return "打开讨论帖，看字数和回帖要求。"
    if "online_text_entry" in st:
        return "打开作业页，看字数和格式要求。"
    if "none" in st or "on_paper" in st:
        return "课上交或线下交，确认时间地点。"
    return "打开作业页，看一眼提交要求。" if r.get("url") else f"先去 {lms} 确认这条的具体要求。"


def next_per_course(ctx, rs):
    out = []
    normal, undated, _ = split(rs)
    for c in ctx.cfg.get("courses") or []:
        r = next((x for x in normal if x["course"] == c["code"]), None) or next((x for x in undated if x["course"] == c["code"]), None)
        out.append((c["code"], r))
    return out


def changes_since(ctx, limit=8):
    """最近一次采集的新变化（公告、作业改动、出分、新解锁），供雷达的「新变化」块。"""
    from cc_digest import auto_changes
    d = latest_digest(ctx)
    if not d:
        return [], None
    ch = auto_changes(d, ctx.clock, (ctx.cfg.get("user") or {}).get("name"))
    return ch[:limit], d.get("collected_at")


def to_markdown(ctx, rs, today, ev=None):
    clock = ctx.clock
    lbl = lms_label(ctx.cfg)
    normal, undated, overdue = split(rs)
    L = [MARK_START, f"_更新 {clock.fmt(clock.now_utc())}_", ""]
    L.append("## 每门课下一条")
    for code, r in next_per_course(ctx, rs):
        L.append(f"- {code}：" + (f"{r['item']} · {r['when']}{'，' + r['rel'] if r.get('rel') else ''}（{r['weight']}）{'（待确认）' if r.get('pending') else ''}" if r else "14 天内没有"))
    L.append("")
    if normal or undated:
        r0 = (normal or undated)[0]
        L += ["## 🔴 最急的一条", "",
              f"**{r0['course']} · {r0['item']}** — {r0['when']}{'，' + r0['rel'] if r0.get('rel') else ''}（{r0['weight']}）{'（待确认）' if r0.get('pending') else ''}",
              f"第一步：{first_step_for(r0, lbl)}", ""]
    cl = clashes(rs)
    if cl:
        L += ["## ⚠️ 撞车预警", ""]
        for g in cl:
            span = f"{clock.fmt_date(g[0]['date'])} 至 {clock.fmt_date(g[-1]['date'])}" if g[0]["date"] != g[-1]["date"] else clock.fmt_date(g[0]["date"])
            items = "、".join(f"{x['course']} {x['item']}（{x['weight']}）" for x in g)
            ws = weight_sum(g)
            L.append(f"- {span}：{items}{'，合计 ' + ws if ws else ''}")
        L.append("")
    a = [r for r in normal if not r["pending"]]
    b = [r for r in normal if r["pending"]] + undated
    L += ["## 区块一 · 已确认 deadline", ""]
    if a:
        L += ["| 剩余 | 时间 | 课 | 事项 | 权重 | 状态 | 说明 · 出处 |", "|---|---|---|---|---|---|---|"]
        for r in a:
            item = f"[{r['item']}]({r['url']})" if r.get("url") else r["item"]
            note = " · ".join(x for x in (r.get("note"), r.get("src")) if x)
            L.append(f"| {r['rel']} | {r['when']} | {r['course']} | {item} | {r['weight']} | {r['status']} | {note} |")
    else:
        L.append("（无）")
    L += ["", f"## 区块二 · 待确认（{lbl} 没给正式截止时间、从公告或说明里推的、或你还没确认的，以 {lbl} 和老师为准）", ""]
    if b:
        L += ["| 剩余 | 时间 | 课 | 事项 | 权重 | 状态 | 出处 |", "|---|---|---|---|---|---|---|"]
        for r in b:
            item = f"[{r['item']}]({r['url']})" if r.get("url") else r["item"]
            L.append(f"| {r['rel'] or '—'} | ⚠️ {r['when']} | {r['course']} | {item} | {r['weight']} | {r['status']} | {r.get('src', '')} |")
    else:
        L.append("（无）")
    if overdue:
        L += ["", f"## 已过期未交（可能是课堂活动或已线下交，以 {lbl} 为准）", ""]
        L += ["| 过了 | 时间 | 课 | 事项 | 权重 |", "|---|---|---|---|---|"]
        for r in overdue[:5]:
            item = f"[{r['item']}]({r['url']})" if r.get("url") else r["item"]
            L.append(f"| {r['rel']} | {r['when']} | {r['course']} | {item} | {r['weight']} |")
    ch, at = changes_since(ctx)
    L += ["", f"## 新变化（最近一次采集 {clock.fmt(parse_ts(at)) if at else '无'}）", ""]
    L += [f"- {c['course']} · {c['kind']}{' · ' + c['when'] if c.get('when') else ''}：{c['title']}" for c in ch] or ["（没有新公告、作业改动或新解锁）"]
    if ev:
        L += ["", cc_state.state_line(ev)]
    L += ["", MARK_END]
    return "\n".join(L)


GENERIC_SRC = ("作业页没有 due_at", "Canvas due_at", "Canvas lock_at", "Moodle due_at", "Moodle lock_at")


def _radar_row(r):
    dl = r.get("days_left")
    soon = dl is not None and dl <= 3
    w = r.get("weight") if r.get("weight") not in (None, "", "—") else ""
    stt = r.get("status") if r.get("status") not in (None, "", "未交") else ""
    meta = " · ".join(x for x in (r.get("when"), w, stt) if x)
    note = " · ".join(x for x in (r.get("note"), r.get("src")) if x and x not in GENERIC_SRC)
    tags = (tag("待确认", "warn") if r.get("pending") else "") + (tag("已过期", "bad") if r.get("overdue") else "")
    return (f'<li><span class="t"><span class="rel{" soon" if soon else ""}">{esc(r.get("rel") or "—")}</span>'
            f'<span class="code">{esc(r["course"])}</span> {link(r.get("url"), r["item"])}{tags}'
            + (f'<span class="src">{rich(note)}</span>' if note else "") + f'</span><span class="m num">{esc(meta)}</span></li>')


def to_html(ctx, rs, today, ev=None):
    """Deadline 雷达页面。样式全部来自 design.py，规范见 references/style.md。"""
    clock = ctx.clock
    lbl = lms_label(ctx.cfg)
    normal, undated, overdue = split(rs)
    confirmed = [r for r in normal if not r["pending"]]
    pending = [r for r in normal if r["pending"]] + undated
    meta = " · ".join(x for x in ("未来 14 天", f"更新 {clock.fmt(clock.now_utc())}", clock.tz_note(today), f"学期{clock.term_week(today)}") if x)
    o = [head(f"Deadline 雷达 · {today.isoformat()}", "radar", app="coach"),
         f'<header class="top"><h1>Deadline 雷达</h1><p class="meta num">{esc(meta)}</p></header>', status_html(ev)]
    first = (normal or undated or [None])[0]
    if first:
        w = first.get("weight") if first.get("weight") not in (None, "", "—") else ""
        bits = " · ".join(x for x in (first.get("when"), first.get("rel"), w) if x)
        o.append('<section class="card hero"><p class="kicker">最急的一条</p>'
                 f'<h3><span class="code">{esc(first["course"])}</span> {link(first.get("url"), first["item"])}{tag("待确认", "warn") if first.get("pending") else ""}</h3>'
                 f'<p class="meta num">{esc(bits)}</p><p class="sub">第一步：{rich(first_step_for(first, lbl))}</p></section>')
    cl = clashes(rs)
    o.append('<section><h2>已确认</h2>')
    for g in cl:
        span = f"{clock.fmt_date(g[0]['date'])} 至 {clock.fmt_date(g[-1]['date'])}" if g[0]["date"] != g[-1]["date"] else clock.fmt_date(g[0]["date"])
        items = "、".join(f"{x['course']} {x['item']}（{x['weight']}）" for x in g)
        ws = weight_sum(g)
        o.append(f'<p class="callout">撞车：{esc(span)}，{esc(items)}{"，合计 " + ws if ws else ""}</p>')
    o.append('<div class="card flush"><ul class="rows nobox">' + "".join(_radar_row(r) for r in confirmed) + "</ul></div>"
             if confirmed else '<p class="meta">两周内没有已确认的 deadline。</p>')
    o.append("</section>")
    if pending:
        o.append(f'<section><h2>待确认 · 以 {lbl} 和老师为准</h2><div class="card flush"><ul class="rows nobox">'
                 + "".join(_radar_row(r) for r in pending) + "</ul></div></section>")
    if overdue:
        o.append('<section><h2>已过期未交 · 可能是课堂活动或已线下交</h2><div class="card flush"><ul class="rows nobox">'
                 + "".join(_radar_row(r) for r in overdue[:5]) + "</ul></div></section>")
    ch, at = changes_since(ctx)
    o.append(f'<section><h2>新变化 · {esc("最近一次采集 " + clock.fmt(parse_ts(at)) if at else "还没采集过")}</h2>')
    if ch:
        o.append('<div class="card flush"><ul class="changes">')
        for c in ch:
            gist = "\n".join(x for x in (c.get("gist") or "").split("\n")[:4] if x.strip())
            sub = " · ".join(x for x in (c.get("kind"), c.get("when")) if x)
            o.append(f'<li><details><summary><span class="code">{esc(c.get("course"))}</span> {rich(c.get("title", ""))}'
                     f'<span class="meta num">{esc(sub)}</span></summary>' + (f'<p class="gist meta">{rich(gist)}</p>' if gist else "") + "</details></li>")
        o.append("</ul></div>")
    else:
        o.append('<p class="meta">没有新公告、作业改动或新解锁。</p>')
    o.append("</section>")
    return "\n".join(o) + foot()

def write(ctx, rs, today, ev=None):
    import cc_record
    os.makedirs(ctx.root, exist_ok=True)
    md_path, html_path = ctx.P("DDL雷达.md"), os.path.join(ctx.root, "Deadline雷达.html")  # md 给 AI，html 给人
    block = to_markdown(ctx, rs, today, ev)
    try:
        with open(md_path, encoding="utf-8") as f:
            old = f.read()
    except OSError:
        old = ""
    if MARK_START in old and MARK_END in old:
        new = old[:old.index(MARK_START)] + block + old[old.index(MARK_END) + len(MARK_END):]
    elif old.strip():
        lines = old.splitlines()
        k = 1 if lines and lines[0].startswith("#") else 0
        new = "\n".join(lines[:k] + ["", block, ""] + lines[k:]) + "\n"
    else:
        new = f"# DDL雷达\n\n{block}\n"
    save_text(md_path, new)
    save_text(html_path, to_html(ctx, rs, today, ev))
    normal, undated, overdue = split(rs)
    cc_record.record_product(ctx, "DDL雷达.md", f"📦 已更新 · 14 天内 {len(normal)} 条", log=f"DDL雷达更新：14 天内 {len(normal)} 条，待确认 {len(undated)} 条，已过期未交 {len(overdue)} 条")
    return [md_path, html_path]


def hours_ago(ts, clock):
    t = parse_ts(ts)
    if not t:
        return None
    return round((clock.now_utc() - t).total_seconds() / 3600, 1)


def status(ctx, today):
    """一屏现状，零副作用。返回 (dict, 文本)。"""
    clock, state = ctx.clock, ctx.state
    rs = rows(ctx, today)
    normal, undated, overdue = split(rs)
    plan = plan_today(ctx, today)
    ex = exam_today(ctx, today)
    pend = unresolved_pending(state)
    snap = load_snapshot(ctx) or {}
    ev = cc_state.evaluate(ctx, today, plan, rs)
    warnings = []
    if ctx.is_v1:
        warnings.append("档案还是 v1：跑一次 migrate")
    h_fetch = hours_ago(snap.get("collected_at") or state.get("last_fetch"), clock)
    if h_fetch is None or h_fetch > 36:
        warnings.append(f"{lms_label(ctx.cfg)} 快照超过 36 小时（或没有）：先 collect --touch")
    if not plan:
        warnings.append("本周没有计划：说「这周学什么」")
    h_check = hours_ago(state.get("last_check"), clock)
    d = {"home": ctx.home, "script": __file__.replace("cc_radar.py", "coach.py"), "today": today.isoformat(), "term_week": clock.term_week(today),
         "host": ctx.cfg.get("canvas_host"), "last_check": state.get("last_check"), "last_check_hours_ago": h_check,
         "last_fetch": snap.get("collected_at") or state.get("last_fetch"), "last_fetch_hours_ago": h_fetch,
         "plan": ({k: plan.get(k) for k in ("file", "must", "first_step", "if_then", "status", "should", "rows", "done")} if plan else None),
         "revision": ({k: ex.get(k) for k in ("course", "task_zh", "minutes", "path")} if ex else None),
         "next_per_course": [{"course": c, "item": r["item"] if r else None, "when": r["when"] if r else None, "rel": r["rel"] if r else None} for c, r in next_per_course(ctx, rs)],
         "deadlines": [{k: r.get(k) for k in ("rel", "when", "course", "item", "weight", "status", "pending", "url", "days_left", "kind", "overdue", "undated")} for r in rs],
         "pending": [{k: p.get(k) for k in ("id", "course", "text", "times_asked", "first_asked", "blocks", "ask_en")} for p in pend],
         "decisions": len(state.get("decisions") or []), "state_eval": ev, "warnings": warnings}
    site = (d["host"] or "未设") + ("（Moodle）" if lms_of(ctx.cfg) == "moodle" else "")  # Canvas 档案下这一行不变
    T = [f"{brand.NAME} · {clock.fmt_date(today)} · 学期{d['term_week']}", f"资料夹：{ctx.root} ｜ 站点：{site}",
         f"上次检查：{'无' if h_check is None else f'{h_check:g} 小时前'} ｜ 上次采集：{'无' if h_fetch is None else f'{h_fetch:g} 小时前'}"]
    dq = len(load_downloads(ctx).get("queue") or [])
    if dq:
        T.append(f"课件待下载 {dq} 个（后台补：collect --download --background）")
    if plan:
        T.append(f"今日必做：{plan.get('must')}  [{plan.get('status')}]" + (f"\n  第一步：{plan['first_step']}" if plan.get("first_step") else "")
                 + (f"\n  {plan['if_then']}" if plan.get("if_then") else "")
                 + (f"\n  应做：{'；'.join(plan['should'])}" if plan.get("should") else ""))
    else:
        T.append("今日必做：本周还没排（说「这周学什么」）")
    if ex:
        T.append(f"今日复习：{ex.get('course')} {ex.get('task_zh')}（{ex.get('minutes')} 分钟）")
    T.append("每门课下一条：")
    T += [f" - {c}：" + (f"{r['item']} · {r['when']}{'，' + r['rel'] if r.get('rel') else ''}（{r['weight']}）" if r else "14 天内没有") for c, r in next_per_course(ctx, rs)]
    if overdue:
        T.append(f"已过期未交 {len(overdue)} 项：" + "；".join(f"{r['course']} {r['item']}（{r['rel']}）" for r in overdue[:3]))
    T.append(f"待你确认（{len(pend)} 条）：" + ("；".join(f"[{p.get('id')}] {p.get('course')} {p.get('text')}" for p in pend[:4]) if pend else "无") + (" …" if len(pend) > 4 else ""))
    T.append(cc_state.state_line(ev))
    if warnings:
        T.append("提醒：" + "；".join(warnings))
    return d, "\n".join(T)
