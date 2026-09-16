"""第一次建档：从 Canvas 课程列表生成 config.json（课程、学期、时区），按模块名反推第 1 周。"""
import datetime as dt

from cc_config import SCHEMA_VERSION
from cc_courses import course_code_of, in_current_term, looks_like_non_course
from cc_time import machine_zone, normalize_zone, parse_date


def resolve_tz(cfg, me, api, course_objs):
    """课程 time_zone → 用户设置 → 电脑时钟 → UTC。返回 (IANA, 来源)。"""
    z = normalize_zone((cfg or {}).get("course_tz"))
    if z:
        return z, "config"
    tzs = [normalize_zone(c.get("time_zone")) for c in course_objs or [] if c.get("time_zone")]
    tzs = [t for t in tzs if t]
    if tzs:
        return max(set(tzs), key=tzs.count), "课程"
    z = normalize_zone((me or {}).get("time_zone"))
    if z:
        return z, "Canvas 用户设置"
    z = machine_zone()
    if z:
        return z, "电脑时钟"
    return "UTC", "默认"


def bootstrap_config(home, host, api, me, all_courses=False, tz_override=None):
    raw = api.get("/api/v1/courses?enrollment_state=active&include[]=term&per_page=100")
    today = dt.date.today()
    courses, terms, skipped, objs = [], {}, [], []
    for c in raw or []:
        term = c.get("term") or {}
        s, e = parse_date(term.get("start_at")), parse_date(term.get("end_at"))
        if not (all_courses or in_current_term(c, today)):
            continue
        if looks_like_non_course(c.get("name"), c.get("course_code")) or looks_like_non_course(c.get("course_code"), c.get("course_code")):
            skipped.append(f"{c.get('course_code') or c.get('name')}（{c.get('id')}）")
            continue
        objs.append(c)
        courses.append({"id": c.get("id"), "code": course_code_of(c), "name": c.get("name"), "section": None, "weekday": None})
        if term.get("name"):
            terms.setdefault(term["name"], {"n": 0, "start": s, "end": e})["n"] += 1
    seen, uniq = {}, []
    for c in courses:  # 同名短码去重
        base = c["code"]
        k = 2
        while c["code"] in seen:
            c["code"] = f"{base}{k}"
            k += 1
        seen[c["code"]] = True
        uniq.append(c)
    term_name, tinfo = (max(terms.items(), key=lambda kv: kv[1]["n"]) if terms else (None, {}))
    start = tinfo.get("start")
    tz, tz_src = (normalize_zone(tz_override), "参数") if normalize_zone(tz_override) else resolve_tz(None, me, api, objs)
    utz = "auto"  # 显示时区跟着电脑时钟走；用户要固定就 config set user_tz <IANA>
    notes = []
    if skipped:
        notes.append("未当作课程的站点（要加就手动写进 courses）：" + "；".join(skipped))
    cfg = {"schema_version": SCHEMA_VERSION, "canvas_host": host, "course_tz": tz, "user_tz": utz, "tz_labels": {},
           "term": {"name": term_name, "start": start.isoformat() if start else None,
                    "end": tinfo.get("end").isoformat() if tinfo.get("end") else None,
                    "week1_monday": None, "break": None, "week_source": None},
           "user": {"id": me.get("id"), "name": me.get("name")},
           "courses": uniq, "extra_sites": [], "exam_prep": None, "api_notes": {}, "notes": notes, "root": None,
           "materials": {"auto_download": True, "max_mb": 50, "per_run": 30}, "agent": {"kind": None}}
    return cfg, {"tz_src": tz_src, "skipped": skipped}


def align_week1(ctx):
    """按模块里最大已解锁的 Week N 反推第 1 周周一；写进 config，标 week_source=modules。"""
    import cc_study
    mods = cc_study.load_modules(ctx)
    today = ctx.clock.today_user()
    W, src = cc_study.current_week(ctx, today, mods)
    if src != "modules" or not W:
        return None
    from cc_time import monday_of
    w1 = monday_of(today) - dt.timedelta(days=7 * (W - 1))
    ctx.raw_cfg.setdefault("term", {})
    ctx.raw_cfg["term"]["week1_monday"] = w1.isoformat()
    ctx.raw_cfg["term"]["week_source"] = "modules"
    ctx.save_config()
    return W, w1
