"""把采集结果给人和 AI 看：终端 digest、档案上下文、新变化列表、最近公告，以及旧版日报页面（render）。"""
import datetime as dt
import glob
import os

import brand
from cc_collect import DESC_UNCHANGED, load_snapshot, strip_html
from cc_courses import course_pairs
from cc_deadlines import deadline_rows, exam_today, plan_today, unresolved_pending
from cc_store import jload
from cc_time import parse_date, parse_ts
from htmlkit import canvas_text, esc, file_link, link, rich
from render_unit import foot, head


def recent_announcements(ctx, today, days=7):
    """最近 days 天的公告（来自最新一次采集的原始响应），按课程标注。"""
    files = sorted(glob.glob(ctx.P("raw", "daily", "*", "announcements.json")))
    anns = (jload(files[-1], []) if files else []) or []
    courses = course_pairs(ctx.cfg)
    since = ctx.clock.course_local_to_utc(today - dt.timedelta(days=days))
    out = []
    for a in anns:
        code = next((k for c, k in courses if a.get("context_code") == f"course_{c}"), None)
        posted = parse_ts(a.get("posted_at"))
        if not code or not posted or posted < since:
            continue
        out.append({"course": code, "when": ctx.clock.fmt(posted), "posted_at": a.get("posted_at"), "title": a.get("title"),
                    "url": a.get("html_url"), "gist": canvas_text(strip_html(a.get("message"), 300))})
    out.sort(key=lambda x: x["posted_at"] or "", reverse=True)
    return out


def print_context(ctx, date):
    """报告写手需要的全部档案上下文，一次打印，省掉额外的 Read。"""
    state, clock = ctx.state, ctx.clock
    today = parse_date(date)
    print(f"\n# 今日上下文 {clock.fmt_date(today)}（学期{clock.term_week(today)}）")
    ex = exam_today(ctx, today)
    if ex:
        print(f"## 今日 {ex.get('course')} 复习: {ex.get('task_zh')}（{ex.get('minutes')} 分钟）文件 {ex.get('path') or '无'}")
    plan = plan_today(ctx, today)
    if plan:
        print(f"## 周计划 {ctx.rel(plan['file'])}（{plan['rows']} 行，📦 {plan['boxes']}，✅ {plan['done']}）")
        print(f" - 必做: {plan.get('must') or '—'}")
        if plan.get("first_step"):
            print(f" - 第一步: {plan['first_step']}")
        if plan.get("if_then"):
            print(f" - 如果-那么: {plan['if_then']}")
        print(f" - 应做: {'；'.join(plan.get('should') or []) or '—'}")
        print(f" - 状态: {plan.get('status') or '📦'}")
    else:
        print("## 周计划: plans/ 里没有今天这一行（说「这周干什么」我来排）")
    pend = unresolved_pending(state)
    print(f"## 待你确认（未解决 {len(pend)} 条；卡 7 天内 deadline 的标 ⏳）")
    for p in pend:
        b = parse_date(p.get("blocks"))
        soon = " ⏳" if (b and (b - today).days <= 7) else ""
        print(f" - [{p.get('id')}] {p.get('course')}: {p.get('text')}（已问 {p.get('times_asked', 1)} 次，首次 {p.get('first_asked')}）{soon}")
    dec = state.get("decisions") or []
    if dec:
        print(f"## 已定的事（不再提起，{len(dec)} 条）")
        for d in dec:
            print(f" - {d.get('course') or ''} {d.get('text')}（{d.get('date')}）")
    md = state.get("manual_deadlines") or []
    print(f"## manual_deadlines: {len(md)} 条（渲染时自动进 14 天表）")
    for m in md:
        print(f" - {m.get('date')} {m.get('time') or m.get('time_text', '')} {m.get('course')} {m.get('item')}{'（待确认）' if m.get('pending') else ''}")


def print_digest(d):
    print(f"# digest {d['date']}（采集 {d['collected_at']}{'，快速模式：只看作业和公告' if d.get('quick') else ''}）")
    if d.get("course_changes"):
        print("## 课程清单有变")
        for c in d["course_changes"]:
            print(" -", c)
    if d.get("stale"):
        print("## 这几门课这次没采到（用的是上次的数据）")
        for code, when in d["stale"].items():
            print(f" - {code}：{when or '上次'}")
    if d["errors"]:
        print("## 采集错误")
        for e in d["errors"]:
            print(" -", e)
    if d.get("readiness"):
        print("## 考试准备")
        for k, v in d["readiness"].items():
            print(f" - {k}: {v}")
    print(f"## 新公告 {len(d['new_announcements'])}")
    for a in d["new_announcements"]:
        print(f" - [{a['course']}] {a['when']} 《{a['title']}》 {a['author']} {a['url']}")
        print(canvas_text(a["text"][:1200], indent="   "))
    print(f"## 站内信（有变化）{len(d['staff_messages'])}")
    for m in d["staff_messages"]:
        print(f" - [{m['course']}] {m['when']} 《{m['subject']}》 from {m['from']}")
        print(canvas_text(m["text"][:600], indent="   "))
    print(f"## 作业改动 {len(d['changed_assignments'])}")
    for a in d["changed_assignments"]:
        print(f" - [{a['course']}] {a['name']} {a.get('url')} {a.get('change', '')} {a.get('fields', '')}")
        diff = [l[:300] for l in a.get("description_diff") or []]
        if diff == [DESC_UNCHANGED]:  # 这句是本工具写的，不是 Canvas 原文
            print("      " + diff[0])
        elif diff:
            print(canvas_text("\n".join(diff), indent="      "))
    print(f"## 提交/成绩变化 {len(d['submission_changes'])}")
    for s in d["submission_changes"]:
        print(f" - [{s['course']}] {s['name']} {s['changes']} 附件={s.get('attachments')} 已发布分数={s['posted']}")
    print(f"## 新模块条目 {len(d['new_items'])}")
    for it in d["new_items"][:40]:
        print(f" - [{it['course']}] {it['module']} / {it['title']} ({it['type']}) {'🔒' + str(it['unlock_at']) if it['locked'] else ''} {it.get('url')}")
    if len(d["new_items"]) > 40:
        print(f"   … 还有 {len(d['new_items']) - 40} 条")
    print(f"## 新解锁 {len(d['unlocked_items'])}")
    for it in d["unlocked_items"]:
        print(f" - [{it['course']}] {it['module']} / {it['title']}")
    print(f"## 仍锁定 {len(d['locked_items'])}")
    for it in d["locked_items"]:
        print(f" - [{it['course']}] {it['title']} 解锁 {it['unlock_at']}")
    print(f"## 已下载 {len(d['downloaded'])}")
    for x in d["downloaded"]:
        print(f" - {x}")
    if d.get("skipped_downloads"):
        print(f"## 课件排队待下 {d.get('queued_downloads', len(d['skipped_downloads']))}（周报先出；后台补：collect --download --background）")
        for x in d["skipped_downloads"][:20]:
            print(f" - [{x['course']}] {x['module']} / {x['title']}")
    if d["removed_items"]:
        print(f"## 已移除条目 {len(d['removed_items'])}")
        for it in d["removed_items"][:20]:
            print(f" - [{it['course']}] {it['module']} / {it['title']}")


def auto_changes(digest, clock, user_name=None):
    out = []
    for a in digest.get("new_announcements") or []:
        out.append({"course": a["course"], "kind": "公告", "when": a["when"], "title": a["title"],
                    "gist": "原文英文，摘录：" + (a["text"][:400] or ""), "source": a["url"]})
    for m in digest.get("staff_messages") or []:
        senders = "、".join(x for x in m["from"] if x and x != user_name)
        out.append({"course": m["course"], "kind": "站内信", "when": m["when"], "title": m["subject"] or "（无标题）",
                    "gist": f"来自 {senders}。原文英文，摘录：" + m["text"][:300], "source": "GET /api/v1/conversations?scope=inbox"})
    for a in digest.get("changed_assignments") or []:
        f = "；".join(f"{x['field']}：{x['old']} → {x['new']}" for x in a.get("fields") or [])
        dd = "\n".join(a.get("description_diff") or [])
        out.append({"course": a["course"], "kind": "作业改动", "when": clock.fmt(parse_ts(a.get("updated_at"))), "title": a["name"],
                    "gist": (a.get("change", "") + " " + f + ("\n说明文字改动：\n" + dd if dd else "")).strip(), "source": a.get("url")})
    for s in digest.get("submission_changes") or []:
        f = "；".join(f"{x['field']}：{x['old']} → {x['new']}" for x in s["changes"])
        out.append({"course": s["course"], "kind": "提交/成绩", "when": "", "title": s["name"], "gist": f + (f"；附件 {s['attachments']}" if s.get("attachments") else ""), "source": s.get("url")})
    by_mod = {}
    for it in digest.get("new_items") or []:
        by_mod.setdefault((it["course"], it["module"]), []).append(it)
    for (course, mod), its in by_mod.items():
        names = "、".join(i["title"] for i in its[:6]) + (f" 等 {len(its)} 项" if len(its) > 6 else "")
        out.append({"course": course, "kind": "新材料", "when": "", "title": mod, "gist": names, "source": its[0].get("url")})
    for it in digest.get("unlocked_items") or []:
        out.append({"course": it["course"], "kind": "新解锁", "when": "", "title": it["title"], "gist": it["module"], "source": it.get("url")})
    for x in digest.get("downloaded") or []:
        if x.get("saved"):
            out.append({"course": x["course"], "kind": "已下载", "when": "", "title": x["name"],
                        "gist": x["saved"] + ("（已提取文字）" if x.get("text") else ""), "source": ""})
    return out


def one_thing_of(ctx, today, plan, rows, zh=None):
    one = (zh or {}).get("one_thing") or {}
    if one:
        return one
    if plan and plan.get("must"):
        return {"title": plan["must"],
                "first_step": plan.get("first_step") or f"打开 {ctx.rel(plan['file'])}，找到今天这一行，只做「必做」那一格。",
                "if_then": plan.get("if_then"), "why": "这是本周计划里今天唯一的必做。", "link": None}
    r = rows[0] if rows else None
    if r:
        return {"title": f"{r['course']} {r['item']}（{r['when']}{'，' + r['rel'] if r['rel'] else ''}）",
                "first_step": "打开作业页，看一眼提交要求。", "why": "最近的一条 deadline。", "link": r.get("url")}
    return {"title": "今天没有必做事项", "first_step": "", "why": "", "link": None}


def render(ctx, date, zh=None, out=None, record=True):
    import cc_record
    zh = zh or {}
    cfg, state, clock = ctx.cfg, ctx.state, ctx.clock
    courses = course_pairs(cfg)
    today = parse_date(date)
    digest = jload(ctx.P("raw", "daily", date, "digest.json"))
    offline = digest is None
    errors = list((digest or {}).get("errors") or [])
    if offline:
        errors.insert(0, "本次没有采集到 Canvas 数据（digest.json 不存在），下面的内容来自档案和上次快照")
        digest = {"snapshot": load_snapshot(ctx) or {}, "errors": errors}
    last_check = parse_ts(state.get("last_check"))
    snap = digest.get("snapshot") or {}
    rows = [r for r in deadline_rows(ctx, snap, today) if not r.get("overdue") and not r.get("undated")]
    plan = plan_today(ctx, today)
    ex = exam_today(ctx, today)
    one = one_thing_of(ctx, today, plan, rows, zh)
    changes = zh.get("changes") if zh.get("changes") is not None else auto_changes(digest, clock, (cfg.get("user") or {}).get("name"))
    pend = unresolved_pending(state)
    # 只问一次：没问过的、或卡 7 天内 deadline 的才算「问」；其余进停车场，只列不催
    def _soon(p):
        b = parse_date(p.get("blocks"))
        return int(p.get("times_asked") or 0) == 0 or (b is not None and (b - today).days <= 7)
    ask_now = [p for p in pend if _soon(p)]
    parked = [p for p in pend if not _soon(p)]
    n = len(courses)

    o = [head(f"日报 {date}", f"daily-{date}", app="coach", wide=True),
         f'<p class="eyebrow">{brand.NAME} · 日报</p>',
         f"<h1>{clock.fmt_date(today)} 日报</h1>",
         f'<p class="meta">{clock.stamp()} 生成 ｜ 学期{clock.term_week(today)} ｜ 上次检查 {clock.fmt(last_check) if last_check else "无记录"} ｜ 数据：Canvas API（只读）+ 本地档案</p>']
    if zh.get("top_note"):
        o.append(f'<div class="card key"><p>{rich(zh["top_note"])}</p></div>')
    if errors:
        o.append('<div class="card fail"><p class="sect">采集有问题</p><ul>' + "".join(f"<li>{esc(e)}</li>" for e in errors) + "</ul></div>")

    if ex:
        o.append(f'<div class="card key"><p class="sect">今日 {esc(ex.get("course"))} 复习</p>')
        o.append(f'<p class="pos">{esc(ex.get("task_zh", ""))}<span class="tag" style="margin-left:10px">{ex.get("minutes", "")} 分钟</span></p>')
        if ex.get("path"):
            o.append(f'<p class="sub">材料：{file_link(ex["path"])}</p>')
        o.append("</div>")

    o.append("<h2>今天最该做的一件事</h2>")
    o.append('<div class="action"><span class="box"></span><div class="abody">'
             f'<div class="atitle">{rich(one.get("title", ""))}</div>'
             + (f'<div class="first"><b>第一步（2 分钟内）</b>{rich(one.get("first_step", ""))}</div>' if one.get("first_step") else "")
             + (f'<p class="sub">{rich(one["if_then"])}</p>' if one.get("if_then") else "")
             + (f'<p class="sub">{rich(one.get("why", ""))}</p>' if one.get("why") else "")
             + (f'<p class="sub">{rich(one["link"])}</p>' if one.get("link") else "") + "</div></div>")

    o.append(f'<h2>新变化<span class="tag" style="margin-left:10px">自 {clock.fmt(last_check) if last_check else "上次检查"} 以来</span></h2>')
    if not changes:
        o.append("<p>没有新公告、新作业改动、新解锁材料或新站内信。</p>")
    for c in changes:
        hd = " · ".join(x for x in (c.get("course"), c.get("kind"), c.get("when")) if x)
        src = c.get("source") or ""
        src_html = rich(src) if src.startswith("http") else esc(src)
        o.append(f'<div class="card"><p class="sect">{esc(hd)}</p><p class="atitle">{rich(c.get("title", ""))}</p>'
                 + "".join(f"<p>{rich(p)}</p>" for p in (c.get("gist") or "").split("\n") if p.strip())
                 + (f'<p class="sub">出处：{src_html}</p>' if src else "") + "</div>")
    readiness = zh.get("readiness") or ""
    rd = (digest or {}).get("readiness") or {}
    if not readiness and rd:
        readiness = "考试准备：" + "；".join(f"{k} {v}" for k, v in rd.items()) + "。"
    if readiness:
        o.append(f'<p class="sub">{rich(readiness)}</p>')

    o.append(f'<h2>未来 14 天 deadline<span class="tag" style="margin-left:10px">{clock.fmt_date(today)} 至 {clock.fmt_date(today + dt.timedelta(days=14))}</span></h2>')
    o.append(f'<p class="meta">{esc(clock.tz_note(today))}标「待确认」的日期来自公告、作业说明或公开大纲，不是 Canvas 的 due_at。</p>')
    if rows:
        o.append('<div class="scroll"><table class="grid"><tr><th>剩余</th><th>时间</th><th>课</th><th>事项</th><th>权重</th><th>状态</th><th>说明 / 出处</th></tr>')
        for r in rows:
            note = " · ".join(x for x in (r.get("note"), r.get("src")) if x)
            tag = '<span class="tag pend">待确认</span> ' if r.get("pending") else ""
            o.append(f"<tr><td>{esc(r['rel'])}</td><td>{esc(r['when'])}</td><td>{esc(r['course'])}</td><td>{tag}{link(r.get('url'), r['item'])}</td>"
                     f"<td>{esc(r['weight'])}</td><td>{esc(r['status'])}</td><td class=\"sub\">{rich(note)}</td></tr>")
        o.append("</table></div>")
    else:
        o.append("<p>14 天内没有 deadline。</p>")

    o.append("<h2>本周计划进度</h2>")
    if plan:
        o.append(f'<p class="meta">{esc(ctx.rel(plan["file"]))} ｜ 本周 {plan["rows"]} 行，✅ {plan["done"]} 行，📦 {plan["boxes"]} 行</p>')
        o.append('<div class="scroll"><table class="grid"><tr><th>今天</th><th>必做</th><th>应做</th><th>状态</th></tr>'
                 f"<tr><td>{esc(clock.fmt_date(today))}</td><td>{rich(plan.get('must'))}"
                 + (f'<div class="sub">第一步：{rich(plan["first_step"])}</div>' if plan.get("first_step") else "")
                 + f"</td><td>{rich('；'.join(plan.get('should') or []))}</td><td>{esc(plan.get('status'))}</td></tr></table></div>")
        o.append('<p class="sub">📦 = 我交付了；✅ = 你确认做了。做完回我「做完了」或「✓ 日期」，我在计划里改。</p>')
    else:
        o.append("<p>本周还没有计划。说「这周干什么」，我来排。</p>")

    o.append("<h2>待你确认</h2>")

    def _pend_li(p):
        asked = f'<span class="tag">已问 {p.get("times_asked", 1)} 次 · {esc(p.get("first_asked") or "")}</span>'
        ask = (f'<div class="sub">问老师：{rich(p["ask_en"])}' + (f'（{rich(p["ask_zh"])}）' if p.get("ask_zh") else "") + "</div>") if p.get("ask_en") else ""
        return f"<li><b>{esc(p.get('course'))}</b> {rich(p.get('text'))} {asked}{ask}</li>"

    if ask_now or zh.get("confirm_new"):
        o.append("<ul>" + "".join(_pend_li(p) for p in ask_now) + "".join(f"<li>{rich(p)}</li>" for p in zh.get("confirm_new") or []) + "</ul>")
    else:
        o.append("<p>今天没有新的要你确认的事。</p>")
    if parked:
        o.append(f'<details class="more"><summary>停车场（已问过，不催，{len(parked)} 条）</summary><ul>' + "".join(_pend_li(p) for p in parked) + "</ul></details>")

    ep = cfg.get("exam_prep") or {}
    o.append("<footer><p>依据与出处</p><ul>")
    o.append(f"<li>Canvas API（只读）：/courses/{{id}}/assignments?include[]=submission、/courses/{{id}}/modules?include[]=items、/announcements、/conversations?scope=inbox；原始响应存 <code>raw/daily/{date}/</code></li>")
    o.append("<li>本地档案：state.json、DDL雷达.md、courses/&lt;课程&gt;/档案.md、plans/" + (f"、{esc(ep['dir'])}/plan.json" if ep.get("dir") else "") + "</li>")
    o.append(f"</ul><p>{brand.NAME} · 只整理课程材料；计分的文字由你自己写。标「待确认」「推断」的地方请以 Canvas 和课表为准。</p></footer>")
    html = "\n".join(o) + foot()

    out = out or ctx.P("reports", f"日报_{date}.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    result = {"report": out, "revision": (ex["path"] if ex and ex.get("path") else None), "changes": len(changes),
              "deadlines_14d": len(rows), "offline": offline, "one_thing": one.get("title", ""), "recorded": False}
    if record:
        cc_record.after_render(ctx, date, out, digest, offline, len(changes), len(rows), one.get("title", ""), errors,
                               [p.get("id") for p in ask_now])
        result["recorded"] = True
    return result
