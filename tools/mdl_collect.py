"""Moodle 取数：课程清单、课程结构、日历、作业/测验页、成绩页、公告 → 和 Canvas 同形状的列表。

每个读取都经 cc_collect 的 run(...)：某门课某一步失败只记这一门这一项；登录过期原样抛出。
时间一律转成 ISO 8601 UTC 字符串（...Z），下游的 parse_ts 不认 unix 整数。
缓存（只存读到的真数据）：raw/moodle_files.json（课件真实文件名）、raw/moodle_cache.json
（哪个论坛是公告论坛、公告正文、作业/测验页读到的状态、成绩页）。
"""
import datetime as dt
import hashlib
import html as html_mod
import json
import re

import mdl_pages
from cc_courses import course_code_of, course_pairs, in_current_term, looks_like_non_course
from cc_store import jload, jsave
from cc_time import Clock, ensure_zone, machine_zone, monday_of, normalize_zone, parse_date, parse_ts

UTC = dt.timezone.utc
Z = "%Y-%m-%dT%H:%M:%SZ"
ENROLLED = "core_course_get_enrolled_courses_by_timeline_classification"
STATE = "core_courseformat_get_state"
MONTH = "core_calendar_get_calendar_monthly_view"
ACTIONS = "core_calendar_get_action_events_by_timesort"
POSTS = "mod_forum_get_discussion_posts"
SITEID = 1  # courseid=1 =「我所有的课」；不能传 null（PHP 8 会 TypeError）

TYPE_MAP = {"resource": "File", "page": "Page", "book": "Page", "url": "ExternalUrl", "lti": "ExternalTool",
            "assign": "Assignment", "quiz": "Quiz", "forum": "Discussion"}
SKIP_MODS = {"label", "subsection"}  # subsection 的内容在它自己的节里
GRADED = {"assign", "quiz", "turnitintooltwo", "workshop", "lti", "lesson", "h5pactivity", "scorm"}
SUB_TYPES = {"assign": ["online_upload"], "quiz": ["online_quiz"], "lti": ["external_tool"],
             "turnitintooltwo": ["external_tool"], "workshop": ["online_upload"]}
EXPECT = "expectcompletionon"  # 活动完成设置里的「预期完成日期」：不是硬性截止，没别的日期时才拿来用
NOT_DUE = {"open", "gradingdue", EXPECT}  # 开放时间、老师的批改截止、完成期望都不是学生的截止
DUE_RANK = {"extension": 0, "due": 1, "close": 2}       # 个人延期优先
SPLIT_MODS = {"turnitintooltwo", "workshop"}            # 一个活动几个截止：每个截止一行
PART_LABEL = {"closesubmission": "提交", "closeassessment": "互评"}  # workshop 的两个截止
EXAM_RE = re.compile(r"(?i)\b(exam|test|quiz|midterm|final)\b|考试|测验|小测")
OLD_DAYS = 21  # 截止过了这么久、已经读过页面的，不再每次去读
TERM_AFTER = 30  # 结课日后多少天仍算在读：Moodle 的 enddate 常设在最后一个教学周，考试周在后面


class CalendarMissing(Exception):
    """日历没读全：这门课的截止日期不可信，按「这门课没采到」处理。"""


def error_text(e, short, course=None):
    """Moodle 下一次读取失败 → 给人看的一句，带上中文原因（不只写英文类名）。
    返回 None = 不用再记：日历没读到那一条已经记过了，不按课重复。"""
    if isinstance(e, CalendarMissing):
        return None
    if course and (getattr(e, "errorcode", None) == "requireloginerror" or "选课页" in str(e)):
        return f"{course} 这门课打不开了（可能退课或课程已结束）"
    return f"{short}：{e}" if str(e).strip() else f"{type(e).__name__}: {short}"


# ---------------------------------------------------------------- 小工具
def _iso(v):
    """unix 秒 / 数字字符串 / ISO 字符串 → ISO UTC 字符串；0 和空是「没有」。"""
    if v in (None, "", 0, "0"):
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().isdigit()):
        try:
            return dt.datetime.fromtimestamp(int(v), UTC).strftime(Z)
        except (ValueError, OverflowError, OSError):
            return None
    t = parse_ts(v)
    return t.strftime(Z) if t else None


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _sid(v):
    """id（数字或数字字符串）→ 统一的字符串键。"""
    i = _int(v)
    return str(i) if i is not None else None


def _text(s):
    """format_string 过的文字：反转义实体、压空白。"""
    return re.sub(r"\s+", " ", html_mod.unescape(str(s or ""))).strip()


def _key(name):
    return _text(name).lower()


def _num(s):
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(s or ""))
    return float(m.group(0).replace(",", ".")) if m else None


def _abs(host, url):
    """cm.url 是 HTML 转义过的绝对地址；相对地址补上站点根。"""
    u = html_mod.unescape(str(url or "")).strip()
    if u and not u.startswith("http"):
        u = host + "/" + u.lstrip("/")
    return u or None


def _load_cache(ctx):
    c = jload(ctx.P("raw", "moodle_cache.json"), {}) or {}
    for k in ("forums", "anns", "status", "grades"):
        if not isinstance(c.get(k), dict):
            c[k] = {}
    return c


# ---------------------------------------------------------------- 课程清单
def _enrolled(api, classification):
    data = api.ajax(ENROLLED, {"classification": classification, "limit": 0, "offset": 0, "sort": "fullname"})
    return (data or {}).get("courses") or [] if isinstance(data, dict) else []


def _enrolled_all(api):
    """全部已选的课，连学生在仪表盘上「从视图中移除」的也要：all / inprogress 在 SQL 层就把它们排除了。
    老站点不认 allincludinghidden 时退回 all → (课程列表, 是否退回了)。"""
    try:
        return _enrolled(api, "allincludinghidden"), False
    except Exception as e:  # noqa: BLE001
        if getattr(e, "errorcode", None) != "invalidparameter":
            raise
    return _enrolled(api, "all"), True


def _course_obj(c):
    """Moodle 课程 → cc_courses 认的形状（shortname 当 course_code，起止日期当学期）。"""
    return {"id": c.get("id"), "course_code": _text(c.get("shortname")), "name": _text(c.get("fullname")),
            "term": {"start_at": _iso(c.get("startdate")), "end_at": _iso(c.get("enddate"))}}


def _non_course(o):
    return looks_like_non_course(o["name"], o["course_code"]) or looks_like_non_course(o["course_code"], o["course_code"])


def refresh_courses(ctx, api, run, errors):
    """同 cc_collect.refresh_courses：新课加进 config，整个清单里都没有了才标 inactive。
    拿 allincludinghidden 判断「看得到」：inprogress 在结课日后就不列了，all 不列学生在仪表盘上隐藏的课，
    两种都会把还在上的课误标成结课。仪表盘隐藏只是视图偏好，照样采。"""
    got = run("课程清单", lambda: _enrolled_all(api), kind="modules")
    live, fell_back = got if got else ([], False)
    if not live:
        return []
    raw = ctx.raw_cfg
    if "courses" not in raw:
        raw["courses"] = list(ctx.cfg.get("courses") or [])
    known = {str(c.get("id")): c for c in raw["courses"]}
    codes = {c.get("code") for c in raw["courses"]}
    changes, seen = [], set()
    today = ctx.clock.today_user()
    for c in live:
        cid = _sid(c.get("id"))
        if not cid:
            continue
        seen.add(cid)
        if cid in known:
            if known[cid].pop("inactive", None):
                changes.append(f"{known[cid].get('code')} 又能看到了")
            continue
        o = _course_obj(c)
        if c.get("visible") is False or _non_course(o) or not in_current_term(o, today, after=TERM_AFTER):
            continue  # 老师没开放的、不是课的、旧学期的，不往清单里加
        code = _unique(course_code_of(o), codes)
        raw["courses"].append({"id": c.get("id"), "code": code, "name": o["name"]})
        changes.append(f"新课程：{code} {o['name']}")
    why = "结课、退课，或你在仪表盘上隐藏了它" if fell_back else "结课或退课"
    for cid, c in known.items():
        if cid not in seen and not c.get("inactive"):
            c["inactive"] = True
            changes.append(f"{c.get('code')} 在 Moodle 上看不到了（{why}），数据保留")
    if changes:
        ctx.save_config()
    return changes


def _unique(code, codes):
    base, k = code, 2
    while code in codes:
        code, k = f"{base}{k}", k + 1
    codes.add(code)
    return code


# ---------------------------------------------------------------- 日历
def _window(ctx):
    """日历读哪几个月：学期开始（或今天往前 30 天，取较早）到学期结束后一个月（没有就往后 6 个月）。
    term 只在建档时定；学期已经结束（上学期建的档接着用）就不信它，按「没有学期」算。"""
    today = ctx.clock.course_date(ctx.clock.now_utc())
    term = ctx.cfg.get("term") or {}
    s, e = parse_date(term.get("start")), parse_date(term.get("end"))
    if e and e < today:
        s = e = None
    start = min(s, today - dt.timedelta(days=30)) if s else today - dt.timedelta(days=30)
    end = max(e + dt.timedelta(days=31), today + dt.timedelta(days=30)) if e else today + dt.timedelta(days=183)
    return max(start, today - dt.timedelta(days=366)), min(end, today + dt.timedelta(days=400))


def _months(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _calendar(api, run, start, end):
    """逐月拉月视图（courseid=1），摊平各日格的事件，按事件 id 去重。任何一个月失败返回 None。"""
    seen = {}
    for y, m in _months(start, end):
        data = run(f"日历 {y}-{m:02d}", lambda y=y, m=m: api.ajax(MONTH, {
            "year": y, "month": m, "courseid": SITEID, "day": 1, "view": "month",
            "includenavigation": False, "mini": False}), kind="assignments")
        if not isinstance(data, dict):
            return None
        for w in data.get("weeks") or []:
            for d in w.get("days") or []:
                for ev in d.get("events") or []:
                    if isinstance(ev, dict) and ev.get("id") is not None:
                        seen.setdefault(ev["id"], ev)
    return list(seen.values())


def _timeline(api, frm, to):
    """待办时间线（已交的作业、做完的测验不在里面）→ 还挂着的 cmid 集合。"""
    out, after = set(), 0
    for _ in range(20):
        data = api.ajax(ACTIONS, {"timesortfrom": frm, "timesortto": to, "aftereventid": after,
                                  "limitnum": 50, "limittononsuspendedevents": True}) or {}
        evs = data.get("events") or [] if isinstance(data, dict) else []
        out |= {_sid(e.get("instance")) for e in evs if _sid(e.get("instance"))}
        if len(evs) < 50 or not data.get("lastid"):
            break
        after = data["lastid"]
    return out


def _pending(api, run, errors, frm, to, events):
    """还没交的 cmid：时间线 + 月视图里带 action 的事件。两边都给不出信息时返回 None（不推断）。"""
    month = {_sid(e.get("instance")) for e in events or [] if "action" in e and _sid(e.get("instance"))}
    has_info = any("action" in e for e in events or [])
    n0 = len(errors)
    tl = run("待办时间线", lambda: _timeline(api, frm, to), kind="modules")
    if tl is None:
        del errors[n0:]  # 可选来源：读不到就只用月视图，不算错误
        return month if has_info else None
    return tl | month


def _mentions(e, code):
    blob = _text(e.get("name")) + " " + _text(re.sub(r"<[^>]+>", " ", e.get("description") or ""))
    return bool(re.search(rf"(?i)(?<![A-Za-z]){re.escape(code)}(?!\d)", blob))


def _course_events(events, cid, code, cmids):
    """本课的事件：course.id 对得上的；没有 course 键但 cmid 在本课的；站点/个人/分类事件里写了课程代码的。"""
    out = []
    for e in events:
        ec = _int((e.get("course") or {}).get("id")) if isinstance(e.get("course"), dict) else None
        if ec is not None:
            if ec == _int(cid):
                out.append(e)
        elif _sid(e.get("instance")) and _sid(e.get("instance")) in cmids:
            out.append(e)
        elif not e.get("modulename") and _mentions(e, code):
            out.append(e)
    return out


def _is_due(et):
    et = str(et or "")
    if et in NOT_DUE or et.endswith("start"):
        return False
    return et in DUE_RANK or et.endswith("end") or "due" in et or "close" in et


def _split_events(evs):
    """→ ({cmid: [截止类事件]}, [非模块事件], {cmid: [预期完成日期事件]})。open / gradingdue 不算截止；
    预期完成日期单独放：LTI、H5P 这类常常只有它，没别的日期时拿来用。"""
    by_cm, extra, expect = {}, [], {}
    for e in evs:
        cm, et = _sid(e.get("instance")), e.get("eventtype")
        if e.get("modulename") and cm:
            if _is_due(et):
                by_cm.setdefault(cm, []).append(e)
            elif et == EXPECT:
                expect.setdefault(cm, []).append(e)
        elif et not in NOT_DUE:
            extra.append(e)
    return by_cm, extra, expect


def _pick(evs):
    evs = sorted(evs or [], key=lambda e: (DUE_RANK.get(e.get("eventtype"), 3), _int(e.get("timestart")) or 0))
    return evs[0] if evs else None


def _parts(mod, evs):
    """这个活动出几行：Turnitin 每个 part、workshop 的提交和互评各一行；其它一行（取最该算的那个截止）。"""
    if mod in SPLIT_MODS and len(evs) > 1:
        return [[e] for e in sorted(evs, key=lambda e: (_int(e.get("timestart")) or 0, _int(e.get("id")) or 0))]
    return [evs]


def _part_name(mod, name, ev):
    label = PART_LABEL.get(ev.get("eventtype")) if mod == "workshop" else None
    return f"{name}（{label or _text(ev.get('name'))}）"


# ---------------------------------------------------------------- 课程结构 → 模块
def _state(api, cid):
    data = api.ajax(STATE, {"courseid": int(cid)})
    if isinstance(data, str):  # data 本身是 JSON 字符串，要再解一次
        data = json.loads(data)
    if not isinstance(data, dict) or not isinstance(data.get("cm"), list):
        raise ValueError("课程结构读不懂")
    return data


def _filename(api, run, code, cmid, files):
    """resource 的真实文件名：只读 Location，不下文件；按 cmid 缓存，只问新出现的。"""
    if cmid in files:
        return files[cmid]
    meta = run(f"{code} 课件 {cmid}", lambda: api.file_meta(int(cmid)), course=code, kind="modules")
    name = (meta or {}).get("filename") or (meta or {}).get("display_name")
    if name and not (meta or {}).get("locked_for_user"):
        files[cmid] = name
    return name


def _folder(api, run, errors, code, cmid, host, cd):
    """folder 页 → 每个文件一个 File 条目（content_id 是 pluginfile 地址）；读不懂返回 None。"""
    html = run(f"{code} 文件夹 {cmid}", lambda: api.page(f"/mod/folder/view.php?id={cmid}"), course=code, kind="modules")
    files = mdl_pages.folder_files(html) if html is not None else None
    if files is None:
        if html is not None:
            errors.append(f"{code} 文件夹 {cmid} 的页面读不懂，只列了文件夹本身")
        return None
    out = []
    for n, f in enumerate(files, 1):
        url = _abs(host, f.get("url"))
        out.append({"id": f"f{cmid}:{n}", "type": "File", "title": _text(f.get("name")), "html_url": url, "url": url,
                    "content_id": url, "filename": _text(f.get("name")), "content_details": dict(cd)})
    return out


def _items(api, run, errors, code, cm, host, files):
    mod, cmid = cm.get("module"), _sid(cm.get("id"))
    if mod in SKIP_MODS or not cmid:
        return []
    url = _abs(host, cm.get("url")) or f"{host}/mod/{mod}/view.php?id={cmid}"
    cd = {"locked_for_user": "uservisible" in cm and not cm.get("uservisible"), "unlock_at": None}
    it = {"id": int(cmid), "type": TYPE_MAP.get(mod, "ExternalUrl"), "title": _text(cm.get("name")),
          "html_url": url, "url": url, "content_details": cd}
    if mod == "folder" and not cd["locked_for_user"]:
        sub = _folder(api, run, errors, code, cmid, host, cd)
        if sub is not None:
            return sub
    if mod == "resource":
        it["content_id"] = int(cmid)
        name = None if cd["locked_for_user"] else _filename(api, run, code, cmid, files)
        if name:
            it["filename"] = name
    return [it]


def _modules(api, run, errors, code, st, host, files):
    """get_state → Canvas 模块形状：每节一个模块，每个活动一个条目。"""
    cmap = {_sid(c.get("id")): c for c in st.get("cm") or [] if isinstance(c, dict)}
    mods = []
    for s in st.get("section") or []:
        items = []
        for x in s.get("cmlist") or []:
            cm = cmap.get(_sid(x))
            if cm:
                items += _items(api, run, errors, code, cm, host, files)
        num = s.get("number") if s.get("number") is not None else s.get("section")
        mods.append({"id": _int(s.get("id")), "name": _text(s.get("rawtitle")) or _text(s.get("title")),
                     "position": _int(num), "unlock_at": None, "items": items})
    return mods


# ---------------------------------------------------------------- 页面：成绩、作业、测验、课程页
def _grades(api, run, errors, code, cid, cache, quick):
    """成绩页 → 成绩项；读不到或读不懂时沿用上次读到的（并点名），quick 直接用上次的。"""
    key, old = str(cid), cache["grades"].get(str(cid))
    if quick:
        return old
    html = run(f"{code} 成绩页", lambda: api.page(f"/grade/report/user/index.php?id={cid}"), course=code, kind="modules")
    items = mdl_pages.grade_items(html) if html is not None else None
    if items is None:
        if html is not None:  # 200 但没有成绩表：重算中、课程被隐藏或没权限，不是「没有计分项」
            errors.append(f"{code} 成绩页读不懂（可能正在重算或没开放）" + ("，满分和权重沿用上次读到的" if old else ""))
        elif old:
            errors.append(f"{code} 成绩页没读到，满分和权重沿用上次读到的")
        return old
    cache["grades"][key] = items
    return items


def _page_status(mod, html):
    """作业/测验页 → {"state", "due_at", "cutoff_at"}；页面认不出返回 None。state 为 None 表示看不出来，
    再带 "maybe": True 表示「可能交了，但页面分不开」（下游算没交、标待确认）。"""
    if mod == "assign":
        r = mdl_pages.assign_status(html)
        if r is None:
            return None
        sub = r.get("submitted")
        state = ("graded" if r.get("graded") else "submitted") if sub is True else ("unsubmitted" if sub is False else None)
        return {"state": state, "due_at": _iso(r.get("extension_at") or r.get("due_at")), "cutoff_at": _iso(r.get("cutoff_at"))}
    r = mdl_pages.quiz_status(html)
    if r is None:
        return None
    fin, again, tried = r.get("attempts_finished"), r.get("can_attempt_again"), r.get("attempts") or 0
    out = {"state": None, "due_at": _iso(r.get("close_at")), "cutoff_at": None}
    if fin is None:
        pass
    elif fin and not again:
        out["state"] = "graded" if r.get("graded") else "submitted"
    elif again or not tried or r.get("in_progress"):
        out["state"] = "unsubmitted"  # 还能再做就不算已交
    elif r.get("reviewable"):
        out["maybe"] = True  # 做过、不能再做、只有 2 行但能回顾：5.0 的「已交待处理」或放弃的尝试，页面分不开
    return out


def _pages(api, run, errors, code, cms, by_cm, cache, quick, now):
    """读作业页、测验页的交没交。quick、截止过了很久且读过的，用上次读到的。
    评过分的也要再读：老师可以在评分后重开一次尝试（reopened），要重交。"""
    st, out, bad = cache["status"], {}, 0
    for cm in cms:
        mod, cmid = cm.get("module"), _sid(cm.get("id"))
        old = st.get(cmid)
        if mod not in ("assign", "quiz") or not cmid:
            continue
        ev = _pick(by_cm.get(cmid))
        due = parse_ts(_iso(ev.get("timestart"))) if ev else None
        stale_ok = old and due and due < now - dt.timedelta(days=OLD_DAYS)
        if quick or stale_ok or cm.get("uservisible") is False:
            if old:
                out[cmid] = old
            continue
        html = run(f"{code} {mod} {cmid}", lambda m=mod, c=cmid: api.page(f"/mod/{m}/view.php?id={c}"),
                   course=code, kind="modules")
        s = _page_status(mod, html) if html is not None else None
        if s is None:
            bad += html is not None
            if old:
                out[cmid] = old
            continue
        st[cmid] = out[cmid] = s
    if bad:
        errors.append(f"{code}：{bad} 个作业/测验页读不懂，交没交按日历推断")
    return out


def _course_texts(api, run, errors, code, cid, host, now):
    """课程页的分节说明、标签文字 → 公告形状，交给「从公告找日期」。"""
    html = run(f"{code} 课程页", lambda: api.page(f"/course/view.php?id={cid}"), course=code, kind="announcements")
    texts = mdl_pages.course_texts(html) if html is not None else None
    if html is not None and texts is None:
        errors.append(f"{code} 课程页读不懂，没从里面找日期")
    return [{"id": f"txt{cid}:{n}", "context_code": f"course_{cid}", "title": f"{code} 课程页", "message": t,
             "posted_at": now.strftime(Z), "html_url": f"{host}/course/view.php?id={cid}"}
            for n, t in enumerate(texts or [], 1) if t]


# ---------------------------------------------------------------- 作业（Canvas 形状）
def _status(mod, cmid, page, pending, has_event, g):
    """交没交 → (workflow_state, 置信度)。作业/测验页 > 成绩页 > 日历推断 > 不知道。
    推断只往「没交」那边推：时间线里还挂着 = 没交（inferred）。作业不在时间线里只说明「可能交了」
    （手动标完成也会让它消失），照样算没交，置信度 maybe，下游标「待确认」；测验不做这种推断
    （关了、做过一次、标了完成都会没有 action，还能再做的也算没交）。"""
    page = page or {}
    if page.get("state"):
        return page["state"], "page"
    if g and (g.get("grade") or g.get("grade_flag") == "submitted"):
        return ("graded" if g.get("grade") else "submitted"), "page"
    if page.get("maybe"):
        return "unsubmitted", "maybe"
    if pending is not None and has_event:
        if cmid in pending:
            return "unsubmitted", "inferred"
        if mod == "assign":
            return "unsubmitted", "maybe"
    return "unsubmitted", "unknown"


def _row(iid, name, mod, url, due, lock, state, conf, g, sources, points=None, **extra):
    """一条 Canvas 形状的作业。calc_weight_pct 是成绩页的「Calculated weight」（按已出分项算的实际权重，
    不是大纲权重，只留在原始数据里备查，不拿来显示）。"""
    g = g or {}
    rng = g.get("range_max")
    pts = points if points is not None else (rng if rng and rng > 0 else 1)
    return {"id": str(iid), "name": name, "html_url": url, "due_at": due, "lock_at": lock, "unlock_at": None,
            "points_possible": pts, "assignment_group_id": None,
            "submission_types": SUB_TYPES.get(mod, ["none"]), "is_quiz_assignment": mod == "quiz",
            "description": "", "updated_at": None,
            "submission": {"workflow_state": state, "submitted_at": None, "attempt": None,
                           "score": _num(g.get("grade")) if g.get("grade") else None, "grade": g.get("grade")},
            "moodle": {"module": mod, "sources": sources, "calc_weight_pct": g.get("weight_pct"),
                       "status_confidence": conf, **{k: v for k, v in extra.items() if v}}}


def _gid(g):
    return _sid(g.get("cmid")) or "g" + hashlib.md5(_key(g.get("name")).encode("utf-8")).hexdigest()[:10]


def _grades_by_cm(gl):
    """{cmid: [成绩项]}：互评（提交/评审）、计分论坛（整坛/rating）一个活动有几项，链接都是同一个 cmid。"""
    out = {}
    for g in gl:
        if _sid(g.get("cmid")):
            out.setdefault(_sid(g.get("cmid")), []).append(g)
    for gs in out.values():
        gs.sort(key=lambda g: _int(g.get("item_id")) or 0)
    return out


def _pair(gs, parts, name):
    """每一行配哪个成绩项：行数和成绩项数一样就按顺序一一配（workshop 的提交、评审），
    否则都配名字对得上的那项（没有就第一项）。"""
    if len(parts) > 1 and len(gs) == len(parts):
        return list(gs)
    main = next((g for g in gs if _key(g.get("name")) == _key(name)), gs[0] if gs else None)
    return [main] * len(parts)


def _build(cid, cms, by_cm, extra, grades, pages, pending, host, now, expect=None, cal_empty=False):
    """合并日历、课程结构、作业/测验页、成绩页 → 这门课的作业列表。id 是 cmid 字符串；
    一个活动出几行时是 cmid:ev<事件id>，成绩册里同一 cmid 的其余项是 cmid:g<成绩项id>，保证不重。"""
    if by_cm is None:
        raise CalendarMissing("日历没读到")
    expect = expect or {}
    cmap = {_sid(c.get("id")): c for c in cms}
    gl = [g for g in grades or [] if not g.get("is_category") and _text(g.get("name"))]
    g_cm = _grades_by_cm(gl)
    g_name = {}
    for g in gl:
        g_name.setdefault(_key(g.get("name")), g)
    used, ids = set(), set()
    order = [c for c, cm in cmap.items() if cm.get("module") in GRADED or c in g_cm or c in by_cm]
    order += [c for c in by_cm if c not in cmap]
    out = []
    for cmid in order:
        cm, evs = cmap.get(cmid) or {}, by_cm.get(cmid) or []
        e0 = evs[0] if evs else {}
        mod = cm.get("module") or e0.get("modulename")
        name = _text(cm.get("name")) or _text(e0.get("activityname")) or _text(e0.get("name"))
        url = _abs(host, cm.get("url")) or e0.get("url") or f"{host}/mod/{mod}/view.php?id={cmid}"
        gs = g_cm.get(cmid) or [x for x in [g_name.get(_key(name))] if x is not None]
        used.update(id(g) for g in gs)  # 同一活动的其余成绩项算进这一行，不再单列
        page = pages.get(cmid)
        parts = _parts(mod, evs)
        for grp, g in zip(parts, _pair(gs, parts, name)):
            ev = _pick(grp)
            iid, nm = (cmid, name) if len(parts) == 1 else (f"{cmid}:ev{ev['id']}", _part_name(mod, name, ev))
            srcs = [s for s, ok in (("calendar", ev), ("structure", cm), ("page", page), ("grades", g)) if ok]
            due, date_from = (_iso(ev.get("timestart")), "calendar") if ev else ((page or {}).get("due_at"), None)
            x = None if due else _pick(expect.get(cmid))
            if x:  # 没有截止，只有「预期完成日期」：拿来用，下游标待确认
                due, date_from = _iso(x.get("timestart")), "expected"
                srcs.append("expected")
            state, conf = _status(mod, cmid, page, pending, bool(ev), g)
            ids.add(str(iid))
            out.append(_row(iid, nm, mod, url, due, (page or {}).get("cutoff_at"), state, conf, g, srcs,
                            date_from=date_from, calendar_empty=cal_empty and not due))
    for g in gl:  # 成绩册里有、别处都没有的计分项：照样列出，名字后标明
        if id(g) in used:
            continue
        used.add(id(g))
        iid, mod = _gid(g), g.get("module")
        url = (f"{host}/mod/{mod}/view.php?id={iid}" if mod and _sid(g.get("cmid"))
               else f"{host}/grade/report/user/index.php?id={cid}")
        state, conf = _status(mod, iid, pages.get(iid), pending, False, g)
        if iid in ids:  # 同一 cmid 已经有一行：这一项另起 id，免得快照按 id 存时互相覆盖
            iid = f"{iid}:g{g.get('item_id')}"
        ids.add(iid)
        out.append(_row(iid, f"{_text(g.get('name'))}（成绩册里有，但没找到截止日期）", mod, url, None, None,
                        state, conf, g, ["grades"]))
    for e in extra:  # 只在日历里的课程/小组/个人/站点事件
        due = _iso(e.get("timestart"))
        t = parse_ts(due)
        name = _text(e.get("name"))
        conf = "maybe" if t is not None and t <= now else "unknown"  # 没东西可交：过了不知道算不算完成，标待确认
        out.append(_row(f"ev{e.get('id')}", name, None, e.get("url") or f"{host}/course/view.php?id={cid}", due, None,
                        "unsubmitted", conf, None, ["calendar"], points=1 if EXAM_RE.search(name) else 0,
                        date_from="calendar"))
    return out


# ---------------------------------------------------------------- 公告
def _post(api, run, code, cid, d, host):
    """一条讨论的首帖 → Canvas 公告形状；首帖看不到或已删除返回 None。"""
    did = _int(d.get("id"))
    data = run(f"{code} 公告 {did}", lambda: api.ajax(POSTS, {"discussionid": did, "sortby": "created", "sortdirection": "ASC"}),
               course=code, kind="announcements")
    posts = (data or {}).get("posts") if isinstance(data, dict) else None
    first = next((p for p in posts or [] if not p.get("hasparent") and not p.get("parentid")), None)
    if not first or first.get("isdeleted") or (first.get("capabilities") or {}).get("view") is False \
            or not first.get("timecreated"):
        return None
    return {"id": f"mdl{did}", "context_code": f"course_{cid}", "posted_at": _iso(first.get("timecreated")),
            "title": _text(first.get("subject")) or d.get("subject"), "html_url": f"{host}/mod/forum/discuss.php?d={did}",
            "message": first.get("message") or "", "author": {"display_name": (first.get("author") or {}).get("fullname") or d.get("author")}}


def _announcements(ctx, api, run, errors, courses, forums, cache, host):
    """每门课的公告论坛（body class 含 forumtype-news；多个就合并）→ 讨论列表 → 只对新讨论取首帖正文。
    论坛页读到了却认不出类型（被转到别的页、200 的提示页）：不缓存，下次再试；这门课一个公告论坛都
    没认出来时点名说一句，免得「公告里写的日期」静默丢掉。"""
    now = ctx.clock.now_utc()
    last = parse_ts((ctx.state or {}).get("last_check")) or now - dt.timedelta(days=14)
    cutoff = min(last - dt.timedelta(days=1), now - dt.timedelta(days=60))  # 同 Canvas：往前多看一点
    kinds, old, keep, out = cache["forums"], cache["anns"], {}, []
    for cid, code in courses:
        cms = sorted(forums.get(str(cid)) or [], key=lambda c: (c.get("sectionnumber") != 0, _int(c.get("id")) or 0))
        news = unknown = 0
        for cm in cms:
            cmid = _sid(cm.get("id"))
            if kinds.get(cmid) == "other":
                continue
            html = run(f"{code} 论坛 {cmid}", lambda c=cmid: api.page(f"/mod/forum/view.php?id={c}"),
                       course=code, kind="announcements")
            ftype = mdl_pages.forum_type(html) if html is not None else None
            if ftype is None:
                unknown += html is not None
                continue
            kinds[cmid] = "news" if ftype == "news" else "other"
            if ftype != "news":
                continue
            news += 1
            ds = mdl_pages.forum_discussions(html)
            if ds is None:
                errors.append(f"{code} 公告列表读不懂")
                continue
            for d in ds:
                t = parse_ts(d.get("time"))
                if t and t < cutoff:
                    continue
                k = str(d.get("id"))
                a = old.get(k) or _post(api, run, code, cid, d, host)
                if a and (parse_ts(a.get("posted_at")) or now) >= cutoff:
                    keep[k] = a
                    out.append(a)
        if unknown and not news:
            errors.append(f"{code} 公告没读到（论坛页认不出是不是公告论坛），公告里写的日期这次没看")
    cache["anns"] = keep
    run("公告", lambda: out, name="announcements.json", kind="announcements")
    return out


# ---------------------------------------------------------------- 入口
def _n_work(cms):
    """学生看得到的作业、测验有几个。"""
    return sum(1 for c in cms if c.get("module") in ("assign", "quiz") and c.get("uservisible") is not False)


def _empty_calendar_notes(empty, checked):
    """课里有作业测验、日历里这门课却一个事件都没有：多半是学生在日历里关掉了「课程事件」，
    日历接口会静默少给。点名说，别让学生以为老师没写日期。所有课都这样时合成一条。"""
    fix = "这些日期先标待确认；到 Moodle 日历把「课程事件」打开就能读到"
    if len(empty) > 1 and len(empty) == checked:
        return [f"每门课的 Moodle 日历都是空的，但课里有作业/测验：可能在日历里关掉了「课程事件」。{fix}"]
    return [f"{code}：课里有 {n} 个作业/测验，但 Moodle 日历里这门课一个事件都没有（可能在日历里关掉了「课程事件」）。{fix}"
            for code, n in empty]


def fetch(ctx, api, courses, date, quick, run, errors):
    """Moodle 取数，返回同 cc_collect._fetch_canvas 的 dict。quick：不刷课程清单、不重建模块、不读页面（用上次读到的）。"""
    host, now = api.host, ctx.clock.now_utc()
    cache = _load_cache(ctx)
    files = jload(ctx.P("raw", "moodle_files.json"), {}) or {}
    n_files = len(files)
    course_changes = [] if quick else refresh_courses(ctx, api, run, errors)
    if course_changes:
        courses = course_pairs(ctx.cfg, include_inactive=False)
    d0, d1 = _window(ctx)
    frm = int(ctx.clock.course_local_to_utc(d0, "00:00").timestamp())
    to = int(ctx.clock.course_local_to_utc(d1, "23:59").timestamp())
    events = _calendar(api, run, d0, d1)
    pending = _pending(api, run, errors, frm, to, events) if events is not None else None
    assignments, modules, forums, texts = {}, {}, {}, []
    checked, empty = 0, []  # 日历读到了的课 / 其中有作业测验、日历却一个事件都没有的课
    for cid, code in courses:
        st = run(f"{code} 课程结构", lambda c=cid: _state(api, c), course=code, kind="assignments")
        if st is None:
            assignments[code] = modules[code] = None
            continue
        cms = [c for c in st.get("cm") or [] if isinstance(c, dict)]
        forums[str(cid)] = [c for c in cms if c.get("module") == "forum" and c.get("uservisible") is not False]
        modules[code] = None
        if not quick:
            modules[code] = _modules(api, run, errors, code, st, host, files)
            run(f"{code} 模块", lambda m=modules[code]: m, name=f"modules_{cid}.json", course=code, kind="modules")
            texts += _course_texts(api, run, errors, code, cid, host, now)
        by_cm, extra, expect, cal_empty = None, None, None, False
        if events is not None:
            mine = _course_events(events, cid, code, {_sid(c.get("id")) for c in cms})
            by_cm, extra, expect = _split_events(mine)
            n_work = _n_work(cms)
            checked += 1
            if n_work and not mine:
                cal_empty = True
                empty.append((code, n_work))
        grades = _grades(api, run, errors, code, cid, cache, quick)
        pages = _pages(api, run, errors, code, cms, by_cm or {}, cache, quick, now)
        assignments[code] = run(f"{code} 的截止日期", lambda a=(cid, cms, by_cm, extra, grades, pages, pending, host, now, expect,
                                                              cal_empty): _build(*a),
                                name=f"assignments_{cid}.json", course=code, kind="assignments")
    errors += _empty_calendar_notes(empty, checked)
    anns = _announcements(ctx, api, run, errors, courses, forums, cache, host)
    if not quick:
        run("课程页文字", lambda: texts, name="moodle_texts.json", kind="announcements")
    jsave(ctx.P("raw", "moodle_cache.json"), cache)
    if len(files) != n_files:
        jsave(ctx.P("raw", "moodle_files.json"), files)
    return {"courses": courses, "course_changes": course_changes, "assignments": assignments, "modules": modules,
            "group_ws": {code: {} for _, code in courses}, "anns": anns, "convs": [], "readiness": {}}


# ---------------------------------------------------------------- 建档（doctor 用）
def _zone(tz, api):
    """参数 → Moodle 用户时区（M.cfg.usertimezone 恰好是 IANA 名时）→ 电脑时钟 → UTC。"""
    z = normalize_zone(tz)
    if z:
        return z, "参数"
    ut = str((getattr(api, "site", None) or {}).get("usertimezone") or "")
    if ut and normalize_zone(ut) == ut and "/" in ut:
        return ut, "Moodle 用户设置"
    z = machine_zone()
    if z:
        return z, "电脑时钟（Moodle 没给能用的用户时区）"
    return "UTC", "默认"


def bootstrap(home, host, api, me, all_courses=False, tz=None):
    """在读课程 → 和 Canvas 版同形状的 config（lms=moodle）。学期取在读课程起止日期的最早/最晚。
    课程拿全部（连仪表盘上隐藏的），在读与否自己按日期筛：inprogress 在结课日一过就不列了，
    考试周第一次建档会把有期末考的课漏掉。"""
    from cc_config import SCHEMA_VERSION
    raw, fell_back = _enrolled_all(api)
    zone_name, tz_src = _zone(tz, api)
    zone = ensure_zone(zone_name)
    today = Clock({"course_tz": zone_name, "user_tz": zone_name}).now_utc().astimezone(zone).date()
    courses, skipped, old, hidden, starts, ends, codes = [], [], [], [], [], [], set()
    for c in raw:
        o = _course_obj(c)
        label = o['course_code'] or o['name']
        if c.get("visible") is False and not all_courses:
            skipped.append(f"{label}（{c.get('id')}，老师还没开放）")
            continue
        if _non_course(o):
            skipped.append(f"{label}（{c.get('id')}）")
            continue
        if not all_courses and not in_current_term(o, today, after=TERM_AFTER):
            old.append(label)
            continue
        if c.get("hidden"):
            hidden.append(label)
        courses.append({"id": c.get("id"), "code": _unique(course_code_of(o), codes), "name": o["name"],
                        "section": None, "weekday": None})
        for v, acc in ((c.get("startdate"), starts), (c.get("enddate"), ends)):
            if _int(v):
                acc.append(dt.datetime.fromtimestamp(_int(v), UTC).astimezone(zone).date())
    start, end = (min(starts) if starts else None), (max(ends) if ends else None)
    notes = []
    if skipped:
        notes.append("未当作课程的站点（要加就手动写进 courses）：" + "；".join(skipped))
    if tz_src.startswith("电脑时钟"):
        notes.append("Moodle 没给能用的用户时区，课程时区先按电脑时钟；不对就 config set course_tz <IANA>")
    said = []
    if hidden:
        said.append("你在 Moodle 仪表盘上隐藏了 " + "、".join(hidden) + "，仍在跟踪")
    if old:
        said.append(f"不在本学期（结课超过 {TERM_AFTER} 天或还没开学）、没加进来的课：" + "、".join(old[:8])
                    + ("等" if len(old) > 8 else "") + "（要加就 doctor --all-courses）")
    if fell_back:
        said.append("这个 Moodle 不认 allincludinghidden，仪表盘上隐藏的课可能没拿到")
    notes += said
    me = me or {}
    cfg = {"schema_version": SCHEMA_VERSION, "lms": "moodle", "canvas_host": getattr(api, "host", None) or host,
           "course_tz": zone_name, "user_tz": "auto", "tz_labels": {},
           "term": {"name": None, "start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
                    "week1_monday": monday_of(start).isoformat() if start else None, "break": None,
                    "week_source": "moodle"},
           "user": {"id": me.get("id"), "name": me.get("name")},
           "courses": courses, "extra_sites": [], "exam_prep": None, "api_notes": {}, "notes": notes, "root": None,
           "materials": {"auto_download": True, "max_mb": 50, "per_run": 30}, "agent": {"kind": None}}
    return cfg, {"tz_src": tz_src, "skipped": skipped, "note": "；".join(said) or None}
