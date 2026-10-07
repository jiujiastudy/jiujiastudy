"""给 AI 看的「还差 N 件」：周报和开场现状的命令输出末尾一块，列出 AI 补得上的事和现成的命令。学生的页面上不出现。

只列补得上的：模块没按周分、还没有每周安排表的课（outline）；学习页清单有问题的（learn check）；
保底清单上还没读过的外部平台（cc_external 接上）。一件事试过补不上（outline 认不出每周安排、网页打不开），
记在 state.gap_failed，7 天内不再列——说一次就够，不天天催。
"""
from cc_time import parse_date

RETRY_DAYS = 7


def failed_recently(state, key, today, days=RETRY_DAYS):
    t = parse_date(((state or {}).get("gap_failed") or {}).get(key) or "")
    return bool(t) and (today - t).days < days


def mark_failed(ctx, key, today):
    ctx.state.setdefault("gap_failed", {})[key] = today.isoformat()
    ctx.save_state()


def clear_failed(ctx, key):
    if (ctx.state.get("gap_failed") or {}).pop(key, None) is not None:
        ctx.save_state()


def for_ai(ctx, plan, today, extra=None):
    """[{key, course, text, cmd}]。plan 是周计划（study 刚算的，或 status 读到的那份）。"""
    import cc_outline
    out = []
    for c in ((plan or {}).get("study") or {}).get("courses") or []:
        code = c.get("code")
        if c.get("exam_site"):  # 只放考试的站：没有每周安排、没有外部平台要补
            continue
        busy = c.get("deadline_related") or c.get("todo") or c.get("notes")
        if c.get("detect") == "none" and busy and not c.get("outline") and not c.get("learn"):
            key = f"outline:{code}"
            if not failed_recently(ctx.state, key, today) and not cc_outline.load(ctx.home, code):
                out.append({"key": key, "course": code, "text": f"{code}：模块没按周分，还没有每周安排表",
                            "cmd": f"outline {code} --syllabus；Syllabus 里没有每周安排，就在课程里找 unit outline / course outline 的链接，"
                                   f"outline {code} --url <网址>；认出来以后核对、补 weeks_zh，outline {code} --file 存回"})
        if c.get("learn_problems"):
            out.append({"key": f"learn:{code}", "course": code, "text": f"{code} 的学习页清单有问题：{'；'.join(c['learn_problems'])}",
                        "cmd": f"照 learn.md 修好清单，再 learn check {code}"})
    import cc_external
    from cc_courses import lms_of
    now = ctx.clock.now_utc() if getattr(ctx, "clock", None) else None
    canvas = lms_of(getattr(ctx, "cfg", None) or {}) != "moodle"
    if now:
        for c in ((plan or {}).get("study") or {}).get("courses") or []:
            code = c.get("code")
            if c.get("exam_site"):
                continue
            if canvas and cc_external.scan_stale(ctx.home, code, now):  # 导航栏、课程页面、分班：保底清单只翻已采集的，这几处要去 Canvas 查
                extra = list(extra or []) + [{"key": f"external-scan:{code}", "course": code,
                                              "text": f"{code}：导航栏、课程页面和学生的分班这 7 天还没查过外部平台",
                                              "cmd": f"external {code}（会先去 Canvas 查一遍），列出来「还没读过」的逐个 browse"}]
            extra = list(extra or []) + cc_external.gap_items(ctx.home, code, c.get("external") or [], now,
                                                              week=(plan or {}).get("week_no"), weekly=c.get("detect") != "none")
    if now and not canvas:
        extra = list(extra or []) + undated_items(ctx.home, plan, now)
    for x in extra or []:
        if not failed_recently(ctx.state, x["key"], today):
            out.append(x)
    return out


UNDATED = ("日期待确认", "Moodle 没写日期")


def undated_items(home, plan, now, per_course=3):
    """Moodle：日历里没日期、还没交的作业/测验 → AI 去读作业页、测验页把日期补上（不叫学生去查）。
    读过的页（browse 记下的，7 天内）不再列：真没写日期的，读过一遍就不天天提。"""
    import cc_external
    todo = {}
    for d in (plan or {}).get("deadlines") or []:
        if d.get("when") not in UNDATED or not d.get("url") or not str(d.get("status") or "").startswith("未交"):
            continue
        r = cc_external.record_of(cc_external.load_records(home, d.get("course")), d["url"]) or {}
        if cc_external._fresh(r.get("read_at"), now) or cc_external._fresh(r.get("last_try"), now):
            continue
        todo.setdefault(d.get("course"), []).append(d)
    out = []
    for code, rows in todo.items():
        pages = "；".join(f"{r['item']} {r['url']}" for r in rows[:per_course]) + (f"；还有 {len(rows) - per_course} 件" if len(rows) > per_course else "")
        out.append({"key": f"dates:{code}", "course": code, "text": f"{code}：{len(rows)} 件作业/测验在 Moodle 上没读到日期",
                    "cmd": f"照 moodle.md 逐个 browse 作业页 --course {code}（{pages}）：看页头的 Due / Closes / Cut-off，说明里写的日期，"
                           f"公告和课程首页提到它的也对一下；找到就 record deadline \"事项\" --course {code} --due 日期 "
                           f"--source \"Moodle 作业页（AI 读到的）\"；真没写就不记，跟学生只说情况"})
    return out


def text_block(items):
    if not items:
        return ""
    return "\n".join([f"## 还差 {len(items)} 件（给 AI 的：先回答学生，回答完再照着补；补到新作业、新截止或周报要改的，再跟学生说一句；"
                      "这一块不给学生看，也不跟学生说「还差」）"]
                     + [f" - {x['text']} → {x['cmd']}" for x in items])
