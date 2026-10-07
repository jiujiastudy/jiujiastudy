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
import cc_external
import cc_learn
import cc_outline
import cc_radar
import cc_state
from cc_courses import lms_label, lms_of, looks_like_exam_site
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
    br = ctx.clock.break_range()
    if br and term.get("week1_monday") and br[0] <= today <= br[1]:
        # 期中假：排假后第一周的东西（提前准备），不按模块重推，免得把第 1 周改错
        return ctx.clock.week_no(br[1] + dt.timedelta(days=1)), "break"
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
                if ua and lo <= ctx.clock.show_date(ua) <= hi:
                    picked.append((m, it))
        if picked:
            method = "unlock-window"
    return picked, (method or "none")


def build(ctx, today, week=None, days=14):
    cfg, clock, state = ctx.cfg, ctx.clock, ctx.state
    moodle = lms_of(cfg) == "moodle"
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
                if url_key in seen_urls and r.get("url") and moodle:
                    # Moodle 的课程条目和作业用同一个链接（view.php?id=）：留 deadline 这条（有截止时间，排必做和「最要紧」都靠它），
                    # 去掉课程条目那条；同一个活动的两个截止（互评的提交 / 互评）也共用链接，两条都要留
                    before[:] = [x for x in before if x.get("url") != r["url"]]
                    todo[:] = [x for x in todo if x.get("url") != r["url"]]
                    all_items[:] = [x for x in all_items if x.get("url") != r["url"] or x["kind"] in ("Deadline", "Overdue")]
                elif url_key in seen_urls and r.get("url"):
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
        outline = None
        exam_site = looks_like_exam_site(c.get("name"))
        if method == "none" and not exam_site:
            hit = cc_outline.topic_for(cc_outline.load(ctx.home, code), W)
            if hit:  # 课程说明里有这周的题目：写出来，不再让学生自己去主页找
                outline = {"week": W, "topic": hit[0], "topic_zh": hit[1]}
            else:  # 只说情况，不叫学生去主页看（10-07）；「还差」里有给 AI 的那条去补
                gap = f"{code} 在 {lms_label(cfg)} 上没按周排，这周讲什么还没对上。"
                gaps.append(gap)
        exam = (next((x for x in dl if x.get("exam") and x.get("days_left") is not None), None)
                or next((x for x in dl if x.get("exam")), None))  # 有日期的考试优先
        courses_out.append({"code": code, "name": c.get("name"), "topic": "、".join(sorted({m.get('name') for m, _ in picked if m.get('name')}))[:80] or None,
                            "detect": method, "class": c.get("class"), "weekday": c.get("weekday"),
                            "before_class": before, "todo": todo, "deadline_related": dl, "notes": notes, "gap": gap,
                            "exam": ({"title": exam["title"], "when": exam["when"], "days_left": exam.get("days_left")} if exam else None)})
        if outline:
            courses_out[-1]["outline"] = outline
        if exam_site:  # 只放考试的站：考试时间照样排进每天和雷达，但没有「这周要学的」卡片
            courses_out[-1]["exam_site"] = True

    suggestion = attach_learn(ctx, today, monday, iso, courses_out, mods, rows)
    attach_external(ctx, courses_out, mods, W)
    all_items = [it for c in courses_out for k in ("before_class", "todo", "deadline_related") for it in c[k]]
    top_one = pick_top(courses_out)
    days_out = schedule_days(ctx, today, monday, courses_out, rows, suggestion)
    ev = cc_state.evaluate(ctx, today, None, rows)
    clash = cc_radar.clashes(rows)
    clash_txt = ""
    if clash:
        g = clash[0]
        clash_txt = f"撞车：{clock.fmt_date(g[0]['date'])} 至 {clock.fmt_date(g[-1]['date'])}，" + "、".join(f"{x['course']} {x['item']}（{x['weight']}）" for x in g) + "。"
    review = last_week_review(ctx, monday)
    plan = {
        "week": iso, "week_no": W, "week_source": wsrc, "title": (f"期中假（假后是第 {W} 周）" if wsrc == "break" else f"第 {W} 周" if W else "本周"),
        "range": f"{clock.fmt_date(monday)} 至 {clock.fmt_date(sunday)} · {len([c for c in courses_out if not c.get('exam_site')])} 门课",
        "tz_note": clock.tz_note(today), "generated": today.isoformat(), "generated_by": "study",
        "canvas_check": (f"数据截至 {clock.fmt(parse_ts(snap.get('collected_at')))}" if snap.get("collected_at") else f"还没采集过 {lms_label(cfg)}"),
        "mantra": slogan_for(iso),
        "top": ([{"course": top_one["course"], "title": top_one["title"], "when": top_one.get("when") or "", "why": top_one.get("why") or "",
                  "first_step": top_one.get("first_step") or ""}] if top_one else []) + [
            {"course": r["course"], "title": r["item"], "when": f"{r['when']}{'，' + r['rel'] if r['rel'] else ''}",
             "why": f"权重 {r['weight']}，{r['status']}", "first_step": cc_radar.first_step_for(r, lms_label(cfg))}
            for r in rows if not r.get("overdue") and cc_state.days_of(r) <= 7 and not (top_one and r["item"] == top_one["title"])][:2],
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
    with_l = [c for c in courses_out if c.get("learn")]
    ls = getattr(schedule_days, "learn", None) or {}
    plan["learn"] = {"courses": [c["code"] for c in with_l], "without": [c["code"] for c in courses_out if not c.get("learn")],
                     "minutes_total": sum(c["learn"]["minutes_total"] for c in with_l),
                     "scheduled_minutes": ls.get("scheduled", 0), "parked_minutes": sum(x["minutes"] for x in ls.get("parked") or []),
                     "daily_cap": ls.get("cap"), "suggest": suggestion,
                     "order": cc_learn.learn_order(courses_out, rows)}  # /jj-learn 不说哪门就照这个顺序全做
    if lms_of(cfg) == "moodle":  # 周报页面上的平台名；Canvas 档案不加这个键，输出不变
        plan["platform"] = lms_label(cfg)
    return plan


def attach_external(ctx, courses_out, mods, week=None):
    """每门课的外部平台保底清单（已采集的模块、公告、作业说明，加上 external 查过的导航栏和课程页面）和课程卡上的情况句
    （试过没读到的作业通知类平台）。"""
    now = ctx.clock.now_utc()
    anns = cc_learn.latest_raw(ctx.home, "announcements.json") or []
    by_code = {c["code"]: c for c in ctx.cfg.get("courses") or []}
    for c in courses_out:
        if c.get("exam_site"):
            continue
        links = cc_external.course_links(ctx, by_code.get(c["code"]) or {"code": c["code"]}, week, now, mods=mods, anns=anns)[0]
        if links:
            c["external"] = links
        notes = cc_external.situation_lines(ctx.home, c["code"], now)
        if notes:
            c["external_notes"] = notes


def attach_learn(ctx, today, monday, iso, courses_out, mods, rows):
    """有这周学习页清单的课：学习页的阅读块代替模块里的「课前看」，带上上课时间、要学生做的事、做好后 Canvas 又多了什么。
    没有清单（或清单坏了、学习页文件不在了）的课照旧，只多一句怎么要学习页。返回「先做哪门」的推荐（两门以上没有时才有）。"""
    prev = monday - dt.timedelta(days=7)
    prev_iso = f"{prev.isocalendar()[0]}-W{prev.isocalendar()[1]:02d}"
    info = cc_learn.load_week(ctx.home, iso, prev_iso, [c["code"] for c in courses_out])
    ids = {c["code"]: c.get("id") for c in ctx.cfg.get("courses") or []}
    anns = None
    for c in courses_out:
        got = info.get(c["code"]) or {}
        m = got.get("m")
        c["learn"] = None
        c["learn_prev"] = cc_learn.page_url(got["prev"]["page"]) if got.get("prev") else None
        if got.get("problems"):
            c["learn_problems"] = got["problems"]
        if not m:
            if not c.get("exam_site") and any(c.get(k) for k in ("before_class", "todo", "deadline_related")):  # 这周什么都没有的课、考试站不提
                c["learn_hint"] = cc_learn.HINT.format(code=c["code"])
            continue
        if anns is None:
            anns = cc_learn.latest_raw(ctx.home, "announcements.json") or []
        n = max([int(it["id"].rsplit("-", 1)[1]) for k in ("before_class", "todo", "deadline_related") for it in c[k]] or [0])
        blocks = []
        for b in m["blocks"]:
            n += 1
            blocks.append({"id": f"{c['code'][-4:]}-{n}", "course": c["code"], "title": f"学习页：{b['label']}", "kind": "Learn",
                           "kind_zh": "学习页", "verb": "看", "url": cc_learn.page_url(m["page"], b.get("anchor")), "module": None,
                           "minutes": b["minutes"], "minutes_src": "学习页", "first_step": "打开学习页，点这一块的标题直接跳到那一节",
                           "source": "学习页", "locked": False, "unlock_at": None, "status": "📦",
                           "before": b.get("before"), "after": b.get("after"), "before_label": b.get("before_label")})
        dated, undated = cc_learn.todos_split(m, c["code"], today, monday, ctx.clock)
        c["before_class"] = blocks  # 这周模块里要看的东西，学习页已经逐份讲过了
        c["learn"] = {"page": cc_learn.page_url(m["page"]), "promise": m["promise"], "minutes_total": m["minutes_total"],
                      "materials_read": m.get("materials_read", True), "made_at": m.get("made_at"),
                      "changed": cc_learn.what_changed(m, mods.get(c["code"]), anns, ids.get(c["code"])),
                      "sessions": [[d.isoformat(), t] for d, t in cc_learn.sessions_fixed(m, c["code"], ctx.clock)],
                      "todos": [[d.isoformat(), t] for d, t in dated], "todos_undated": undated}
    return cc_learn.suggest_first(courses_out, rows, today)


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
        for c in sorted(courses_out, key=lambda x: min([cc_state.days_of(i) for i in x["deadline_related"]] or [99])):
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


def _hhmm(f):
    """「09:00–12:00 …」「23:59 … 截止」开头的钟点，用来给一天里的固定时间排序；没写钟点的排最后。"""
    m = re.match(r"\s*(\d{1,2}):(\d{2})", f or "")
    return (int(m.group(1)), int(m.group(2))) if m else (99, 99)


def schedule_days(ctx, today, monday, courses_out, rows, suggestion=None):
    """排天：deadline 前 1–2 天必做；核心课件排上课日前一天（不知道就周一到周四轮流）；其余应做 ≤2。
    空出来的日子先把真有的事提上来，再给一天放「今天适合做 X 的学习页」，其余留空（没排事，不算必做）。"""
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
    should_items = {}  # 应做那一行的文字 → 条目：空日子把它提成必做时，第一步、时长、链接都带上
    movable = []       # 先搁着里没有截止约束的（模块条目、小测）：空日子可以挪过去

    def put_must(d, text, item, kind, who, if_then=None):
        if item.get("id") in placed:
            return False
        if d["must"]:
            if len(d["should"]) < max_should:
                d["should"].append(text)
                should_items[text] = item
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
            due = parse_date(ctx.clock.show_date(parse_ts(it["due_at"])).isoformat())
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
        due = ctx.clock.show_date(parse_ts(ex["due_at"]))
        for k in range(1, 4):
            d = due - dt.timedelta(days=k)
            if d.isoformat() in by_date and d >= today:
                w = c.get("exam") and c["exam"].get("days_left")
                put_must(by_date[d.isoformat()], f"复习 {c['code']}：过一周的课件（{ex['title']} {ex.get('rel') or ''}）",
                         {"first_step": "打开这门课的模块列表，从最早的一周开始，只看标题和小结页", "minutes": 60, "course": c["code"], "id": ex["id"], "url": ex.get("url")},
                         "思考", "👤", "如果一天看不完一周，就只看每周的第一份课件。")
    # 3a. 学习页：上课时间进 fixed，带日期的事挂在那天；阅读块照「在哪节课之前」排进某天，每天最多 daily_minutes 分钟
    sunday = monday + dt.timedelta(days=6)
    cap = int((cfg.get("study") or {}).get("daily_minutes") or 120)
    used = {d["date"]: 0 for d in days}
    learn_parked, scheduled = [], 0
    timed = set()
    for c in courses_out:
        for ds, text in (c.get("learn") or {}).get("sessions") or []:
            if ds in by_date:
                by_date[ds]["fixed"].append(text)
                timed.add(ds)
        for ds, text in (c.get("learn") or {}).get("todos") or []:
            if ds in by_date:
                by_date[ds].setdefault("todos", []).append(text)
    for ds in timed:  # 加了上课时间的那几天按钟点排一下；别的天保持原样
        by_date[ds]["fixed"].sort(key=_hhmm)
    blocks = [(it, c) for c in courses_out if c.get("learn") for it in c["before_class"] if it.get("kind") == "Learn"]

    def last_ok(it):
        return cc_learn.latest_day(it.get("before"), ctx.clock) or sunday

    for it, c in sorted(blocks, key=lambda x: (last_ok(x[0]), x[0]["id"])):
        lo = max(today, monday, cc_learn.earliest_day(it.get("after"), ctx.clock) or monday)
        hi = min(last_ok(it), sunday)
        late = hi < lo
        if late:
            hi = lo  # 建议的时间已经过了：排最早能看的那天，写明是补的
        text = (f"{c['code']} {it['title']}（{it['minutes']} 分钟" + (f"，{it['before_label']}" if it.get("before_label") else "")
                + ("，原定时间已过，能补就补" if late else "") + "）")
        cands = [d for d in days if lo <= parse_date(d["date"]) <= hi]
        fits = [d for d in cands if used[d["date"]] + it["minutes"] <= cap and (not d["must"] or len(d["should"]) < max_should)]
        placed.add(it["id"])
        if not fits:
            real = cc_learn.latest_day(it.get("before"), ctx.clock)
            if real and real > sunday:
                why = f"这周每天都排满了；它{it.get('before_label') or '在截止前'}看完就行，下周初再看"
            elif cands:
                why = f"到 {hi.month:02d}-{hi.day:02d} 前每天的学习页已经排满 {cap} 分钟，或者那几天的事已经排满"
            else:
                why = "这周已经没有能排的日子"
            learn_parked.append({"date": (hi if cands else sunday).isoformat(), "text": f"{text}——{why}", "minutes": it["minutes"], "course": c["code"]})
            continue
        d = min(fits, key=lambda x: (used[x["date"]], x["date"]))
        used[d["date"]] += it["minutes"]
        scheduled += it["minutes"]
        placed.discard(it["id"])
        put_must(d, text, it, "思考", "👤", "如果看不完，先看这一块的第一节，剩下的挪到明天。")
        if it["id"] not in placed:  # 必做已经有了、应做也满了（理论上 fits 已经排除）：照放进应做
            d["should"].append(text)
            should_items[text] = it
            placed.add(it["id"])
    schedule_days.learn = {"cap": cap, "scheduled": scheduled, "parked": learn_parked}
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
            # 放到事最少的那天（必做算一件），一样少就放早的：一周里每天都有一件真事，不让后几天空着、前几天挤着
            open_days = [d for d in days if parse_date(d["date"]) >= today and len(d["should"]) < max_should]
            if open_days:
                d = min(open_days, key=lambda x: ((1 if x["must"] else 0) + len(x["should"]), x["date"]))
                d["should"].append(text)
                should_items[text] = it
                found_slot = True
            if not found_slot:
                parking.append({"date": (monday + dt.timedelta(days=6)).isoformat(), "text": text})
                movable.append((text, it))
    parking += [{"date": p["date"], "text": p["text"]} for p in learn_parked]
    # 5. 空出来的日子（今天及以后）：先把这天「有空再做」的第一件提成必做，再从先搁着里挪一件；还空，就给第一个空日子
    #    放「今天适合做 X 的学习页」（建议，不算必做）；其余留空：没排事，留给自己（不算必做、不打勾）。今天以前的日子不补。
    suggested = False
    for d in days:
        if d["must"]:
            continue
        future = parse_date(d["date"]) >= today
        text, it = None, {}
        if future and d["should"]:
            text = d["should"].pop(0)
            it = should_items.get(text) or {}
        elif future and movable:
            text, it = movable.pop(0)
            parking[:] = [p for p in parking if p.get("text") != text]
        if text:
            d.update({"must": text, "must_first_step": it.get("first_step"), "must_minutes": it.get("minutes"), "must_kind": "思考",
                      "must_who": "👤", "must_course": it.get("course"), "must_item_id": it.get("id"), "must_url": it.get("url")})
        elif future and suggestion and not suggested:
            suggested = True
            code = suggestion["course"]
            d.update({"must": f"今天适合做 {code} 的学习页：跟我说「做 {code} 这周的学习页」", "must_kind": "建议", "must_who": "👤",
                      "must_course": code, "must_first_step": "跟 AI 说这一句，它在后台做，大约 40 分钟"})
        else:
            d.update({"must": "", "must_kind": "空"})
    days[-1]["revise"] = "周日：回我「做完了」，我记进度、排下周。"
    schedule_days.parking = parking
    return days


def last_week_review(ctx, monday):
    prev = monday - dt.timedelta(days=7)
    f, data = cc_deadlines.find_plan_json(ctx, prev + dt.timedelta(days=3))
    if not data:
        return ""
    days = data.get("days") or []
    musts = [d for d in days if cc_state.real_must(d)]  # 没排事的日子、建议、老版本的填空句子都不算必做
    done = sum(1 for d in musts if d.get("status") == "✅")
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
        if c.get("exam_site"):  # 只放考试的站：考试时间在每天和雷达里
            continue
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
        L.append(f"- {d['date'][5:]} {d['weekday']}：必做 {d['must'] or '（没排事）'}" + (f"（第一步：{d['must_first_step']}）" if d.get("must_first_step") else "")
                 + (f"；应做 {'；'.join(d['should'])}" if d.get("should") else "") + f" [{d['status']}]")
    if plan.get("review"):
        L.append("\n" + plan["review"])
    L.append("\n" + cc_state.state_line(plan["state"]))
    return "\n".join(L)
