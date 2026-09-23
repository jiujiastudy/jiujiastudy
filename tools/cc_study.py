"""本周该学什么：只用元数据（模块条目、作业、公告、手动 deadline）排出每门课三桶和每天一件必做。

脚本先排，AI 只润色（--zh 覆盖层）。JSON 是唯一真源，render_week 负责渲染。
"""
import datetime as dt
import glob
import os
import re

import cc_collect
import cc_deadlines
import cc_digest
import cc_radar
import cc_state
from cc_courses import lms_label, lms_of
from cc_store import jload, jsave
from cc_time import monday_of, parse_date, parse_ts
from mantras import slogan_for

WEEK_RES = [
    re.compile(r"(?i)\b(?:week|wk|w)\s*0?(\d{1,2})\b"),
    re.compile(r"(?i)\b(?:module|unit|topic|session|lecture|lec|class)\s*0?(\d{1,2})\b"),
    re.compile(r"第\s*(\d{1,2}|[一二三四五六七八九十]{1,3})\s*[周講讲课節节]"),
]
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
          "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15}
ADMIN_RE = re.compile(r"(?i)policy|policies|contact|welcome|syllabus|staff|outline|how to|guide to|referencing|zoom link")
VIDEO_RE = re.compile(r"(?i)youtube|youtu\.be|vimeo|echo360|panopto|kaltura|/media|video|lecture recording|recording|screening")
DOC_EXT = (".pdf", ".pptx", ".ppt", ".docx", ".doc")
EXAM_RE = re.compile(r"(?i)\b(exam|test|quiz|midterm|final)\b|考试|测验|小测")


def week_of_name(s):
    for rx in WEEK_RES:
        m = rx.search(s or "")
        if m:
            g = m.group(1)
            n = CN_NUM.get(g) if not g.isdigit() else int(g)
            if n and 1 <= n <= 20:
                return n
    return None


def load_modules(ctx):
    """每门课最新的模块列表：raw/daily/<最新>/modules_<id>.json，没有就 raw/bundle_<id>.json。"""
    out = {}
    for cid, code in [(c["id"], c["code"]) for c in ctx.cfg.get("courses") or []]:
        files = sorted(glob.glob(ctx.P("raw", "daily", "*", f"modules_{cid}.json")))
        mods = jload(files[-1]) if files else None
        if mods is None:
            mods = (jload(ctx.P("raw", f"bundle_{cid}.json"), {}) or {}).get("modules")
        out[code] = mods or []
    return out


def max_unlocked_week(mods, now):
    best = None
    for m in mods:
        w = week_of_name(m.get("name"))
        if not w:
            continue
        items = m.get("items") or []
        unlocked = any(not (it.get("content_details") or {}).get("locked_for_user") for it in items) if items else True
        if unlocked and (best is None or w > best):
            best = w
    return best


def week_signal(mods, now):
    """(最大已解锁的 Week N, 可信吗)。整学期一次发完的课（最大周 ≥ 12）只能当下限，不可信。"""
    w = max_unlocked_week(mods, now)
    return w, bool(w and w < 12)


def current_week(ctx, today, mods_by_course, override=None):
    """(周次, 来源)。用户定的 / config 定的优先；否则每次都按模块重新推：按周发布的课最可信，一次发完的课只当下限。"""
    if override:
        return int(override), "user"
    term = ctx.cfg.get("term") or {}
    n = ctx.clock.week_no(today)
    # moodle：建档时按课程开课日定的第 1 周，比按模块名猜可靠（Moodle 的节名常是日期）
    if n and term.get("week1_monday") and term.get("week_source") in ("config", "user", "moodle"):
        return n, term.get("week_source")
    now = ctx.clock.now_utc()
    sig = [week_signal(m, now) for m in mods_by_course.values() if m]
    rel = [w for w, ok in sig if ok]
    allw = [w for w, ok in sig if w]
    if rel:
        return max(sorted(set(rel)), key=rel.count), "modules"
    if allw:
        return min(allw), "modules"
    if n and term.get("week1_monday"):
        return n, term.get("week_source") or "config"
    return None, None


def item_kind(it):
    t = it.get("type") or ""
    title = (it.get("title") or "").lower()
    url = (it.get("external_url") or it.get("url") or "").lower()
    if t == "Quiz" or "quiz" in title:
        return "Quiz"
    if t == "Discussion":
        return "Discussion"
    if t == "Assignment":
        return "Assignment"
    if t == "File":
        return "File" if (it.get("filename") or title).lower().endswith(DOC_EXT) else "Other"
    if t in ("ExternalUrl", "ExternalTool"):
        return "Video" if VIDEO_RE.search(title + " " + url) else "ExternalUrl"
    if t == "Page":
        return "Video" if VIDEO_RE.search(title) else "Page"
    return "Other"


VERBS = {"Page": "读", "File": "看课件", "Video": "看视频", "ExternalUrl": "看", "Quiz": "做", "Discussion": "发帖", "Assignment": "交", "Other": "打开"}
FIRST = {"Page": "打开页面，读完这一页", "File": "打开课件，先翻目录和前三页", "Video": "打开链接，看完为止；先看前 5 分钟",
         "ExternalUrl": "打开链接，看一遍", "Quiz": "打开测验页，先看题数和时限", "Discussion": "打开讨论页，读题干和字数要求",
         "Assignment": "打开作业页，看一眼提交要求和文件名规则", "Other": "打开看一眼是什么"}
KIND_ZH = {"Page": "页面", "File": "课件", "Video": "视频", "ExternalUrl": "链接", "Quiz": "小测", "Discussion": "讨论", "Assignment": "作业", "Other": "其它"}


def minutes_for(ctx, kind, it):
    table = (ctx.cfg.get("study") or {}).get("minutes") or {}
    base = table.get(kind, 20)
    if kind == "File" and (it.get("filename") or it.get("title") or "").lower().endswith((".pptx", ".ppt")):
        base = table.get("File", 40)
    return base


def week_items(ctx, code, mods, W, monday):
    """本周条目 + 识别方法。四级回退：模块名 → 条目标题 → 本周解锁 → 无。"""
    def flat(m):
        return [it for it in (m.get("items") or []) if it.get("type") != "SubHeader"]
    picked, method = [], None
    for m in mods:
        if W and week_of_name(m.get("name")) == W:
            picked += [(m, it) for it in flat(m)]
    if picked:
        method = "module-name"
    else:
        for m in mods:
            for it in flat(m):
                if W and week_of_name(it.get("title")) == W:
                    picked.append((m, it))
        if picked:
            method = "item-title"
    if not picked:
        lo, hi = monday - dt.timedelta(days=1), monday + dt.timedelta(days=6)
        for m in mods:
            for it in flat(m):
                cd = it.get("content_details") or {}
                ua = parse_ts(cd.get("unlock_at") or m.get("unlock_at"))
                if ua and lo <= ctx.clock.course_date(ua) <= hi:
                    picked.append((m, it))
        if picked:
            method = "unlock-window"
    return picked, (method or "none")


def build(ctx, today, week=None, days=14):
    cfg, clock, state = ctx.cfg, ctx.clock, ctx.state
    monday = monday_of(today)
    sunday = monday + dt.timedelta(days=6)
    mods = load_modules(ctx)
    W, wsrc = current_week(ctx, today, mods, week)
    if W and wsrc == "modules" and not ctx.is_v1:
        # 推断出的周次每次都对一遍 config（用户说「这周是第 N 周」后 week_source=user，就不再动）
        w1 = monday - dt.timedelta(days=7 * (W - 1))
        term_cfg = ctx.raw_cfg.setdefault("term", {})
        if term_cfg.get("week1_monday") != w1.isoformat() or term_cfg.get("week_source") != "modules":
            term_cfg.update({"week1_monday": w1.isoformat(), "week_source": "modules"})
            ctx.save_config()
            ctx.clock.term = ctx.cfg.get("term") or {}
    snap = cc_collect.load_snapshot(ctx) or {}
    rows = cc_deadlines.deadline_rows(ctx, snap, today, days)
    anns = cc_digest.recent_announcements(ctx, today, 7)
    iso = f"{monday.isocalendar()[0]}-W{monday.isocalendar()[1]:02d}"
    courses_out, gaps, all_items = [], [], []
    for c in cfg.get("courses") or []:
        code = c["code"]
        picked, method = week_items(ctx, code, mods.get(code) or [], W, monday)
        before, todo, dl = [], [], []
        seen_urls = set()
        n = 0
        for m, it in picked:
            kind = item_kind(it)
            title = (it.get("title") or "").strip()
            if kind in ("Page", "File", "Video", "ExternalUrl", "Other") and ADMIN_RE.search(title):
                continue
            url = it.get("html_url") or it.get("url") or it.get("external_url")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            n += 1
            cd = it.get("content_details") or {}
            locked = bool(cd.get("locked_for_user"))
            item = {"id": f"{code[-4:]}-{n}", "course": code, "title": title, "kind": kind, "kind_zh": KIND_ZH[kind], "verb": VERBS[kind],
                    "url": url, "module": m.get("name"), "minutes": minutes_for(ctx, kind, it), "minutes_src": "估",
                    "first_step": FIRST[kind], "source": f"模块「{m.get('name')}」", "locked": locked,
                    "unlock_at": cd.get("unlock_at") or m.get("unlock_at"), "status": "📦"}
            (todo if kind in ("Quiz", "Discussion", "Assignment") else before).append(item)
            all_items.append(item)
        for r in rows:
            if r["course"] != code:
                continue
            n += 1
            item = {"id": f"{code[-4:]}-{n}", "course": code, "title": r["item"], "kind": "Deadline" if not r.get("overdue") else "Overdue",
                    "kind_zh": "已过期未交" if r.get("overdue") else "deadline", "verb": "交", "url": r.get("url"), "module": None,
                    "minutes": None, "minutes_src": None, "first_step": cc_radar.first_step_for(r, lms_label(cfg)), "source": r.get("src"),
                    "when": r["when"], "rel": r["rel"], "due_at": r["t"].isoformat() if r.get("t") else None,
                    "weight": r.get("weight"), "days_left": r.get("days_left"), "pending": r.get("pending"), "status": "📦",
                    "exam": r.get("kind") == "exam",
                    "submission_types": r.get("submission_types") or [], "submitted": bool(r.get("submitted"))}
            if url_key := (r.get("url") or r["item"]):
                if url_key in seen_urls and r.get("url"):
                    for x in todo:
                        if x.get("url") == r.get("url"):
                            x.update({"when": r["when"], "rel": r["rel"], "weight": r.get("weight"), "days_left": r.get("days_left")})
                    n -= 1
                    continue
                seen_urls.add(url_key)
            dl.append(item)
            all_items.append(item)
        notes = [{"when": a["when"], "title": a["title"], "url": a["url"], "gist": a["gist"]} for a in anns if a["course"] == code]
        gap = None
        if method == "none":
            mod_url = (f"{cfg.get('canvas_host')}/course/view.php?id={c['id']}" if lms_of(cfg) == "moodle"
                       else f"{cfg.get('canvas_host')}/courses/{c['id']}/modules")
            gap = f"{code} 的模块没按周命名，这周看什么请打开课程主页确认：{mod_url}"
            gaps.append(gap)
        exam = (next((x for x in dl if x.get("exam") and x.get("days_left") is not None), None)
                or next((x for x in dl if x.get("exam")), None))  # 有日期的考试优先
        courses_out.append({"code": code, "name": c.get("name"), "topic": "、".join(sorted({m.get('name') for m, _ in picked if m.get('name')}))[:80] or None,
                            "detect": method, "class": c.get("class"), "weekday": c.get("weekday"),
                            "before_class": before, "todo": todo, "deadline_related": dl, "notes": notes, "gap": gap,
                            "exam": ({"title": exam["title"], "when": exam["when"], "days_left": exam.get("days_left")} if exam else None)})

    top_one = pick_top(courses_out)
    days_out = schedule_days(ctx, today, monday, courses_out, rows)
    ev = cc_state.evaluate(ctx, today, None, rows)
    clash = cc_radar.clashes(rows)
    clash_txt = ""
    if clash:
        g = clash[0]
        clash_txt = f"撞车：{clock.fmt_date(g[0]['date'])} 至 {clock.fmt_date(g[-1]['date'])}，" + "、".join(f"{x['course']} {x['item']}（{x['weight']}）" for x in g) + "。"
    review = last_week_review(ctx, monday)
    plan = {
        "week": iso, "week_no": W, "week_source": wsrc, "title": f"第 {W} 周" if W else "本周",
        "range": f"{clock.fmt_date(monday)} 至 {clock.fmt_date(sunday)} · {len(courses_out)} 门课",
        "tz_note": clock.tz_note(today), "generated": today.isoformat(), "generated_by": "study",
        "canvas_check": (f"数据截至 {clock.fmt(parse_ts(snap.get('collected_at')))}" if snap.get("collected_at") else f"还没采集过 {lms_label(cfg)}"),
        "mantra": slogan_for(iso),
        "top": ([{"course": top_one["course"], "title": top_one["title"], "when": top_one.get("when") or "", "why": top_one.get("why") or "",
                  "first_step": top_one.get("first_step") or ""}] if top_one else []) + [
            {"course": r["course"], "title": r["item"], "when": f"{r['when']}{'，' + r['rel'] if r['rel'] else ''}",
             "why": f"权重 {r['weight']}，{r['status']}", "first_step": cc_radar.first_step_for(r, lms_label(cfg))}
            for r in rows if not r.get("overdue") and (r.get("days_left") or 99) <= 7 and not (top_one and r["item"] == top_one["title"])][:2],
        "days": days_out,
        "study": {"week": iso, "week_no": W, "week_source": wsrc, "top_one": top_one, "courses": courses_out, "gaps": gaps,
                  "items_total": len(all_items), "minutes_total": sum(i.get("minutes") or 0 for i in all_items)},
        "deadlines": [{"when": r["when"], "course": r["course"], "item": r["item"], "weight": r["weight"], "status": r["status"], "pending": r["pending"],
                       "days_left": r.get("days_left"), "rel": r.get("rel"), "url": r.get("url"), "kind": r.get("kind"), "overdue": bool(r.get("overdue"))} for r in rows],
        "clash": clash_txt, "parking": [], "review": review,
        "state": ev,
        "sources": [{"label": f"{lms_label(cfg)} 快照", "ref": "raw/daily/snapshot.json"}, {"label": "模块列表", "ref": "raw/daily/<日期>/modules_<课程id>.json"},
                    {"label": "手动 deadline 与待确认", "ref": "state.json"}],
    }
    if lms_of(cfg) == "moodle":  # 周报页面上的平台名；Canvas 档案不加这个键，输出不变
        plan["platform"] = lms_label(cfg)
    return plan


def pick_top(courses_out):
    """本周最要紧的一件：未交且 7 天内权重最高 → 已过期 → 本周小测/讨论 → 最近 deadline 课程的第一份课件。"""
    cands = []
    for c in courses_out:
        for it in c["deadline_related"]:
            dl = it.get("days_left")
            if it["kind"] == "Deadline" and dl is not None and dl <= 7:
                cands.append((0, -cc_state.weight_pct(it.get("weight")), dl, it))
            elif it["kind"] == "Overdue":
                cands.append((1, 0, dl or 0, it))
        for it in c["todo"]:
            if it["kind"] in ("Quiz", "Discussion"):
                cands.append((2, 0, 0, it))
    if not cands:
        for c in sorted(courses_out, key=lambda x: min([i.get("days_left") or 99 for i in x["deadline_related"]] or [99])):
            if c["before_class"]:
                it = c["before_class"][0]
                cands.append((3, 0, 0, it))
                break
    if not cands:
        return None
    cands.sort(key=lambda x: (x[0], x[1], x[2]))
    it = cands[0][3]
    why = {"Deadline": f"权重 {it.get('weight')}，{it.get('rel') or ''}", "Overdue": "已过期未交，先确认能不能补交", "Quiz": "本周小测", "Discussion": "本周讨论要发帖"}.get(it["kind"], "这门课离 deadline 最近")
    return {"id": it["id"], "course": it["course"], "title": it["title"], "why": why, "when": it.get("when") or "",
            "first_step": it.get("first_step"), "url": it.get("url"), "kind": it["kind"]}


def schedule_days(ctx, today, monday, courses_out, rows):
    """排天：deadline 前 1–2 天必做；核心课件排上课日前一天（不知道就周一到周四轮流）；其余应做 ≤2；周日收工。"""
    cfg = ctx.cfg
    lead = (cfg.get("study") or {}).get("lead_days") or {"heavy": 2, "light": 1}
    max_should = (cfg.get("study") or {}).get("max_should", 2)
    days = []
    for i in range(7):
        d = monday + dt.timedelta(days=i)
        days.append({"date": d.isoformat(), "weekday": "周一 周二 周三 周四 周五 周六 周日".split()[i], "fixed": [], "must": None,
                     "must_first_step": None, "must_if_then": None, "must_minutes": None, "must_kind": None, "must_who": None,
                     "must_course": None, "must_item_id": None, "must_url": None, "should": [], "revise": None, "status": "📦"})
    by_date = {d["date"]: d for d in days}
    placed = set()

    def put_must(d, text, item, kind, who, if_then=None):
        if item.get("id") in placed:
            return False
        if d["must"]:
            if len(d["should"]) < max_should:
                d["should"].append(text)
                placed.add(item.get("id"))
            return False
        placed.add(item.get("id"))
        d.update({"must": text, "must_first_step": item.get("first_step"), "must_minutes": item.get("minutes"), "must_kind": kind,
                  "must_who": who, "must_course": item.get("course"), "must_item_id": item.get("id"), "must_url": item.get("url"),
                  "must_if_then": if_then})
        return True

    # 1. deadline：到期前 lead 天当必做；固定时间点写进 fixed
    for c in courses_out:
        for it in c["deadline_related"]:
            if it["kind"] != "Deadline" or it.get("due_at") is None:
                continue
            due = parse_date(ctx.clock.course_date(parse_ts(it["due_at"])).isoformat())
            if due and due.isoformat() in by_date:
                by_date[due.isoformat()]["fixed"].append(f"{it['when'].split(' ', 2)[-1] if it.get('when') else ''} {it['course']} {it['title']} 截止" .strip())
            heavy = cc_state.weight_pct(it.get("weight")) >= 10
            target = due - dt.timedelta(days=lead["heavy"] if heavy else lead["light"]) if due else None
            if target and target < today:
                target = today
            if target and target.isoformat() in by_date:
                put_must(by_date[target.isoformat()], f"{it['course']} {it['title']}（{it['when']}）", it, "自己写", "👤",
                         "如果今天做不完，明天第一件事继续，不排别的。")
    # 2. 考试：考前 3 天每天复习
    for c in courses_out:
        ex = next((it for it in c["deadline_related"] if it.get("exam") and it.get("due_at")), None)
        if not ex:
            continue
        due = ctx.clock.course_date(parse_ts(ex["due_at"]))
        for k in range(1, 4):
            d = due - dt.timedelta(days=k)
            if d.isoformat() in by_date and d >= today:
                w = c.get("exam") and c["exam"].get("days_left")
                put_must(by_date[d.isoformat()], f"复习 {c['code']}：过一周的课件（{ex['title']} {ex.get('rel') or ''}）",
                         {"first_step": "打开这门课的模块列表，从最早的一周开始，只看标题和小结页", "minutes": 60, "course": c["code"], "id": ex["id"], "url": ex.get("url")},
                         "思考", "👤", "如果一天看不完一周，就只看每周的第一份课件。")
    # 3. 核心课件：上课日前一天，或周一到周四轮流
    slot = 0
    for c in courses_out:
        core = next((it for it in c["before_class"] if it["kind"] in ("File", "Page", "Video")), None)
        if not core:
            continue
        if c.get("weekday"):
            d = monday + dt.timedelta(days=(int(c["weekday"]) - 1) - 1)
            if d < monday:
                d = monday
        else:
            d = monday + dt.timedelta(days=slot % 4)
            slot += 1
        if d < today:
            d = today if today <= monday + dt.timedelta(days=6) else d
        if d.isoformat() in by_date:
            put_must(by_date[d.isoformat()], f"{c['code']} {core['verb']}：{core['title']}（{core['minutes']} 分钟）", core, "思考", "👤",
                     "如果看不进去，只看每页标题和最后一页小结。")
    # 4. 其余进应做；装不下进先搁着
    parking = []
    for c in courses_out:
        rest = [it for it in c["before_class"] + c["todo"] if it["id"] not in placed]
        for it in rest:
            placed.add(it["id"])
            text = f"{c['code']} {it['verb']}：{it['title']}（{it['minutes']} 分钟）" if it.get("minutes") else f"{c['code']} {it['verb']}：{it['title']}"
            found_slot = False
            for d in days:
                if parse_date(d["date"]) < today:
                    continue
                if len(d["should"]) < max_should:
                    d["should"].append(text)
                    found_slot = True
                    break
            if not found_slot:
                parking.append({"date": (monday + dt.timedelta(days=6)).isoformat(), "text": text})
    for d in days:
        if not d["must"]:
            d["must"] = "整理这周的笔记，把没看完的补上" if d["weekday"] != "周日" else "收工：回我「做完了」，我来排下周"
            d["must_kind"] = "机械"
            d["must_who"] = "👤"
            d["must_first_step"] = "打开本周清单，从第一条没勾的开始"
    days[-1]["revise"] = "周日：回我「做完了」，我记进度、排下周。"
    schedule_days.parking = parking
    return days


def last_week_review(ctx, monday):
    prev = monday - dt.timedelta(days=7)
    f, data = cc_deadlines.find_plan_json(ctx, prev + dt.timedelta(days=3))
    if not data:
        return ""
    days = data.get("days") or []
    done = sum(1 for d in days if d.get("status") == "✅")
    musts = [d for d in days if d.get("must")]
    left = [d for d in musts if d.get("status") != "✅"]
    if not musts:
        return ""
    txt = f"上周 {len(musts)} 件必做完成 {done} 件。"
    if left:
        txt += "没完成的：" + "；".join((d.get("must") or "")[:30] for d in left[:3]) + "。挪到本周还是先搁着？说一句就行，不说就先搁着。"
    return txt


def apply_overlay(plan, zh):
    """AI 的中文润色：days 按日期、courses 按代码合并；top / review / mantra / parking 整体替换。"""
    if not zh:
        return plan
    for date, patch in (zh.get("days") or {}).items():
        for d in plan["days"]:
            if d["date"] == date:
                d.update({k: v for k, v in patch.items() if v is not None})
    for code, patch in (zh.get("courses") or {}).items():
        for c in plan["study"]["courses"]:
            if c["code"] == code:
                for k, v in patch.items():
                    if k in ("before_class", "todo", "deadline_related") and isinstance(v, dict):
                        for it in c[k]:
                            if it["id"] in v:
                                it.update(v[it["id"]])
                    elif v is not None:
                        c[k] = v
    for k in ("top", "review", "mantra", "parking", "clash", "title"):
        if zh.get(k) is not None:
            plan[k] = zh[k]
    top = zh.get("top")
    if isinstance(top, list) and top and isinstance(top[0], dict) and (plan.get("study") or {}).get("top_one"):
        t1 = plan["study"]["top_one"]  # 覆盖层改了第一件，控制台 / md 的「本周最要紧的一件」跟着变
        for k in ("course", "title", "when", "why", "first_step", "url"):
            if top[0].get(k) is not None:
                t1[k] = top[0][k]
    return plan


def write_plan(ctx, plan, force=False):
    path = ctx.P("plans", f"{plan['week']}.json")
    old = jload(path)
    if old and not old.get("generated_by") and not force:
        path = ctx.P("plans", f"{plan['week']}.auto.json")
    if old and old.get("generated_by") and not force:
        keep = {d["date"]: d.get("status") for d in old.get("days") or []}
        for d in plan["days"]:
            if keep.get(d["date"]) == "✅":
                d["status"] = "✅"
        done_ids = {it["id"] for c in old.get("study", {}).get("courses", []) for k in ("before_class", "todo", "deadline_related") for it in c.get(k, []) if it.get("status") == "✅"}
        for c in plan["study"]["courses"]:
            for k in ("before_class", "todo", "deadline_related"):
                for it in c[k]:
                    if it["id"] in done_ids:
                        it["status"] = "✅"
    plan["parking"] = plan.get("parking") or getattr(schedule_days, "parking", [])
    jsave(path, plan)
    return path


def to_text(plan):
    s = plan["study"]
    L = [f"# {plan['title']} {plan['range']}（周次来源：{plan.get('week_source') or '未知'}）"]
    if s.get("top_one"):
        t = s["top_one"]
        L.append(f"本周最要紧的一件：{t['course']} {t['title']}（{t.get('why')}）。第一步：{t.get('first_step')}")
    for c in s["courses"]:
        L.append(f"\n## {c['code']} {c.get('name') or ''}（识别：{c['detect']}）")
        for label, key in (("上课前要看的", "before_class"), ("要做的练习或小测", "todo"), ("与 deadline 相关的事", "deadline_related")):
            items = c[key]
            if not items:
                continue
            L.append(f"- {label}：")
            for it in items:
                extra = f"，{it['when']}{'，' + it['rel'] if it.get('rel') else ''}" if it.get("when") else (f"，{it['minutes']} 分钟" if it.get("minutes") else "")
                L.append(f"  - [{it['id']}] {it['verb']}：{it['title']}{extra}{'（锁定）' if it.get('locked') else ''}")
        for n in c["notes"][:3]:
            L.append(f"- 公告 {n['when']}：{n['title']}")
        if c.get("gap"):
            L.append(f"- ⚠️ {c['gap']}")
    L.append("\n## 每天")
    for d in plan["days"]:
        L.append(f"- {d['date'][5:]} {d['weekday']}：必做 {d['must']}" + (f"（第一步：{d['must_first_step']}）" if d.get("must_first_step") else "")
                 + (f"；应做 {'；'.join(d['should'])}" if d.get("should") else "") + f" [{d['status']}]")
    if plan.get("review"):
        L.append("\n" + plan["review"])
    L.append("\n" + cc_state.state_line(plan["state"]))
    return "\n".join(L)
