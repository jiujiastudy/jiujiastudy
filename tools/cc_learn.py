"""学习页清单：每份「本周学习页」旁边放一个给机器看的 JSON，周报只读它，不拆网页。

位置：<档案>/learn/<ISO周>/<课程代码>.json。课程代码用 config 里的（比如 MECO69362），页面上显示的写在 label。

格式（schema 1）：
{
  "schema": 1,
  "course": "MFDI9313",                 config 里的课程代码
  "label": "MFDI9313",                  页面上显示的代码，可省
  "week": "2026-W41",                   这份学习页是哪一周的（ISO 周）
  "week_no": 9,                         学期第几周，不知道写 null
  "page": "C:/…/产出/W9_本周学习页.html",
  "made_at": "2026-10-06T18:49:00+11:00",
  "data_as_of": "2026-10-06T07:01:11+00:00",   做这份学习页时用的快照时间
  "materials_read": true,               读没读课件文字
  "promise": "明天的 Zoom 课……",         页面上「看完你就」后面那一句
  "minutes_total": 190,
  "blocks": [{"id": "b1", "label": "第 1、6 节 + 术语", "minutes": 60, "anchor": "#s1",
              "before": "2026-10-07T09:00:00+11:00", "before_label": "周三 09:00 Zoom 课前", "after": null}],
  "sessions": [{"start": "2026-10-07T09:00:00+11:00", "end": "2026-10-07T12:00:00+11:00",
                "title": "Zoom 课（Tutorial/11）", "where": "Zoom", "url": null, "inferred": false}],
  "todos": [{"text": "下载第 10 周课件", "due": "2026-10-12", "after": "2026-10-09", "anchor": "#todo"}],
  "covered": {"module_items": [3272230], "locked_items": [3301234], "announcements": [123456]}
}

before / after / due / start / end 可以只写日期（2026-10-12），也可以写到分钟（带时区）。
blocks 是「分几块看」：每块要在 before 之前看完（after 是不能早于的时间，比如讲座后才看的那块）。
covered 记做页面时 Canvas 上已有的东西，周报拿它和新快照比，判断学习页过没过期。
"""
import datetime as dt
import os

SCHEMA = 1
REQUIRED = ("course", "week", "page", "made_at", "data_as_of", "promise", "minutes_total", "blocks")


def manifest_dir(home, week):
    return os.path.join(home, "learn", week)


def manifest_path(home, week, code):
    return os.path.join(manifest_dir(home, week), f"{code}.json")


def parse_when(s):
    """日期或带时区的时刻 → date / datetime；认不出返回 None。"""
    if not s or not isinstance(s, str):
        return None
    try:
        if len(s) == 10:
            return dt.date.fromisoformat(s)
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return t if t.tzinfo else None  # 写到分钟就必须带时区，不然周报不知道是哪里的时间
    except ValueError:
        return None


def validate(m):
    """清单有什么问题就列出来；空列表 = 能用。周报遇到有问题的清单就当这门课没有学习页。"""
    if not isinstance(m, dict):
        return ["不是 JSON 对象"]
    bad = [f"缺 {k}" for k in REQUIRED if m.get(k) in (None, "")]
    if m.get("schema") != SCHEMA:
        bad.append(f"schema 不是 {SCHEMA}")
    if m.get("week") and not (isinstance(m["week"], str) and len(m["week"]) == 8 and m["week"][4:6] == "-W"):
        bad.append("week 要写成 2026-W41 这样")
    for k in ("made_at", "data_as_of"):
        if m.get(k) and not isinstance(parse_when(m[k]), dt.datetime):
            bad.append(f"{k} 要写到分钟并带时区")
    if not isinstance(m.get("minutes_total"), int) or m.get("minutes_total", 0) <= 0:
        bad.append("minutes_total 要是正整数")
    blocks = m.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        bad.append("blocks 至少要有一块")
        blocks = []
    for i, b in enumerate(blocks):
        where = f"blocks[{i}]"
        if not isinstance(b, dict):
            bad.append(f"{where} 不是对象")
            continue
        if not b.get("label"):
            bad.append(f"{where} 缺 label")
        if not isinstance(b.get("minutes"), int) or b["minutes"] <= 0:
            bad.append(f"{where} minutes 要是正整数")
        if b.get("anchor") and not str(b["anchor"]).startswith("#"):
            bad.append(f"{where} anchor 要以 # 开头")
        for k in ("before", "after"):
            if b.get(k) and parse_when(b[k]) is None:
                bad.append(f"{where} {k} 认不出")
    for i, s in enumerate(m.get("sessions") or []):
        if not isinstance(s, dict) or parse_when(s.get("start")) is None or not s.get("title"):
            bad.append(f"sessions[{i}] 要有 start 和 title")
        elif s.get("end") and parse_when(s["end"]) is None:
            bad.append(f"sessions[{i}] end 认不出")
    for i, t in enumerate(m.get("todos") or []):
        if not isinstance(t, dict) or not t.get("text"):
            bad.append(f"todos[{i}] 缺 text")
            continue
        for k in ("due", "after"):
            if t.get(k) and parse_when(t[k]) is None:
                bad.append(f"todos[{i}] {k} 认不出")
    return bad


def covered_from_raw(modules, announcements, course_id):
    """做学习页那一刻 Canvas 上有什么：模块条目、其中锁着的、这门课的公告。用 collect 存下的原始 JSON 算。"""
    items, locked = set(), set()
    for mod in modules or []:
        for it in mod.get("items") or []:
            if it.get("id") is None:
                continue
            items.add(it["id"])
            if (it.get("content_details") or {}).get("locked_for_user"):
                locked.add(it["id"])
    ctxcode = f"course_{course_id}"
    anns = {a["id"] for a in announcements or [] if a.get("id") is not None and a.get("context_code") == ctxcode}
    return {"module_items": sorted(items), "locked_items": sorted(locked), "announcements": sorted(anns)}


# ---------------------------------------------------------------- 周报读清单

SKIP_TYPES = {"SubHeader"}
HINT = "还没有这周的学习页。要的话跟我说「做 {code} 这周的学习页」，在后台做，大约 40 分钟，不用等。"


def page_url(path, anchor=None):
    """本机文件的链接（中文、空格都转义），可带 #锚点。"""
    import urllib.parse
    p = str(path).replace("\\", "/").lstrip("/")
    return "file:///" + urllib.parse.quote(p, safe="/:") + (anchor or "")


def _load(path):
    import json
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_week(home, week, prev_week, codes):
    """每门课这周的清单：{代码: {"m": 能用的清单或 None, "state": "ok" / "bad" / None, "problems": [...], "prev": 上周能用的清单}}。
    清单坏了、周次或课程对不上、学习页文件不在了，都当这门课没有学习页（state="bad"，原因在 problems），不报错。"""
    out = {}
    for code in codes:
        r = {"m": None, "state": None, "problems": [], "prev": None}
        path = manifest_path(home, week, code)
        if os.path.exists(path):
            try:
                m = _load(path)
            except (OSError, ValueError) as e:
                m, r["problems"] = None, [f"读不了：{type(e).__name__}"]
            if m is not None:
                r["problems"] = validate(m)
                if not r["problems"] and m.get("week") != week:
                    r["problems"] = ["清单里的周次和文件夹对不上"]
                if not r["problems"] and m.get("course") != code:
                    r["problems"] = ["清单里的课程和文件名对不上"]
                if not r["problems"] and not os.path.exists(m["page"]):
                    r["problems"] = ["学习页文件不在了"]
            r["state"] = "bad" if r["problems"] else "ok"
            r["m"] = m if r["state"] == "ok" else None
        if prev_week:
            try:
                pm = _load(manifest_path(home, prev_week, code))
                if not validate(pm) and os.path.exists(pm["page"]):
                    r["prev"] = pm
            except (OSError, ValueError, KeyError, TypeError):
                pass
        out[code] = r
    return out


def latest_raw(home, name):
    """最近一次采集存下的原始 JSON（raw/daily/<日期>/<name>），没有就 None。"""
    import glob
    files = sorted(glob.glob(os.path.join(home, "raw", "daily", "*", name)))
    for f in reversed(files):
        try:
            return _load(f)
        except (OSError, ValueError):
            continue
    return None


def what_changed(m, modules, announcements, course_id):
    """学习页做好以后 Canvas 上多了什么：新条目、新解锁的、新公告。锁着的新条目等解锁了再算。"""
    cov = m.get("covered") or {}
    items0, locked0, anns0 = (set(cov.get(k) or []) for k in ("module_items", "locked_items", "announcements"))
    since = parse_when(m.get("data_as_of"))
    out = []
    for mod in modules or []:
        for it in mod.get("items") or []:
            iid = it.get("id")
            if iid is None or it.get("type") in SKIP_TYPES:
                continue
            locked = bool((it.get("content_details") or {}).get("locked_for_user"))
            title = (it.get("title") or "").strip()
            if iid not in items0 and not locked:
                out.append({"what": "新条目", "title": title})
            elif iid in locked0 and not locked:
                out.append({"what": "新解锁", "title": title})
    for a in announcements or []:
        if a.get("context_code") != f"course_{course_id}" or a.get("id") in anns0:
            continue
        t = parse_when(a.get("posted_at"))
        if isinstance(since, dt.datetime) and isinstance(t, dt.datetime) and t <= since:
            continue  # 采集窗口挪了才第一次看到的旧公告，不算新的
        out.append({"what": "新公告", "title": (a.get("title") or "").strip()})
    return out


def _local(clock, t):
    return t.astimezone(clock.course_tz if clock.same else clock.user_tz)


def latest_day(when, clock):
    """「要在 when 之前看完」→ 最晚排到哪天。只写日期 = 那天之前；写到时刻：中午以后的可以当天看，早上的要前一天看。"""
    t = parse_when(when)
    if isinstance(t, dt.datetime):
        lt = _local(clock, t)
        return lt.date() if lt.hour >= 12 else lt.date() - dt.timedelta(days=1)
    return t - dt.timedelta(days=1) if t else None


def earliest_day(when, clock):
    """「after 之后才能看」→ 最早排到哪天。"""
    t = parse_when(when)
    if isinstance(t, dt.datetime):
        return _local(clock, t).date()
    return t


def sessions_fixed(m, code, clock):
    """学习页查到的上课时间 → [(日期, "09:00–12:00 课 标题（地点）")]；推断的末尾标「推断」。"""
    out = []
    for s in m.get("sessions") or []:
        st, en = parse_when(s.get("start")), parse_when(s.get("end"))
        where = s.get("where")
        tail = f"（{where}）" if where and where not in (s.get("title") or "") else ""
        if isinstance(st, dt.datetime):
            ls = _local(clock, st)
            hm = ls.strftime("%H:%M") + (("–" + _local(clock, en).strftime("%H:%M")) if isinstance(en, dt.datetime) else "")
            out.append((ls.date(), f"{hm} {code} {s['title']}{tail}" + ("「推断」" if s.get("inferred") else "")))
        elif st:
            out.append((st, f"{code} {s['title']}{tail}" + ("「推断」" if s.get("inferred") else "")))
    return out


def todos_split(m, code, today, monday, clock):
    """要学生自己做的事：带截止日期的排进某一天（截止前一天，不早于 after、不早于今天），其余留在课程卡上。"""
    dated, undated = [], []
    sunday = monday + dt.timedelta(days=6)
    for t in m.get("todos") or []:
        due = parse_when(t.get("due"))
        if not due:
            undated.append(t["text"])
            continue
        due_d = _local(clock, due).date() if isinstance(due, dt.datetime) else due
        day = due_d - dt.timedelta(days=1)
        if t.get("after"):
            day = max(day, earliest_day(t["after"], clock) or day)
        day = max(day, today)
        if day > sunday:
            undated.append(f"{t['text']}（{due_d.month:02d}-{due_d.day:02d} 前）")
            continue
        dated.append((day, f"{code} {t['text']}（{due_d.month:02d}-{due_d.day:02d} 前）"))
    return dated, undated


def _short(s, n=24):
    s = str(s or "").strip()
    return s if len(s) <= n else s[:n].rstrip() + "…"


def _rank(c, rows):
    """(排序键, 理由)：7 天内有截止的先；没有就看这周要看要做的东西多少；再没有才看更远的截止。"""
    mine = sorted((r for r in rows if r.get("course") == c["code"] and not r.get("overdue") and r.get("days_left") is not None),
                  key=lambda x: x["days_left"])
    n = len(c.get("before_class") or []) + len(c.get("todo") or [])
    if mine and mine[0]["days_left"] <= 7:
        d = mine[0]["days_left"]
        return (0, d, c["code"]), f"{_short(mine[0]['item'])} {'今天' if d == 0 else '明天' if d == 1 else f'还有 {d} 天'}截止"
    if n:
        return (1, -n, c["code"]), f"这周有 {n} 样要看要做"
    if mine:
        return (2, mine[0]["days_left"], c["code"]), f"{_short(mine[0]['item'])} 还有 {mine[0]['days_left']} 天截止"
    return (3, 0, c["code"]), "这周的东西最少，可以放后面"


def suggest_first(courses_out, rows, today):
    """没有学习页的课里先做哪一门（所有宿主挑的都一样）。只剩一门没有就不推荐。"""
    without = [c for c in courses_out if not c.get("learn") and not c.get("exam_site")]  # 考试站不是要学的课
    if len(without) < 2:
        return None
    best = min(without, key=lambda c: _rank(c, rows)[0])
    return {"course": best["code"], "why": _rank(best, rows)[1]}


def learn_order(courses_out, rows):
    """/jj-learn 不说哪门就全做（10-07 发起人）：这周还没有学习页的课，最急的在前；
    学习页做完以后课程又多了东西的，排在后面重做。考试站不做。"""
    todo = sorted((c for c in courses_out if not c.get("exam_site") and not c.get("learn")), key=lambda c: _rank(c, rows)[0])
    redo = sorted((c for c in courses_out if not c.get("exam_site") and (c.get("learn") or {}).get("changed")),
                  key=lambda c: _rank(c, rows)[0])
    return ([{"course": c["code"], "why": _rank(c, rows)[1]} for c in todo]
            + [{"course": c["code"], "why": "学习页做完以后课程又多了东西，重做一遍"} for c in redo])


# ---------------------------------------------------------------- 做学习页之前：读课件那一问

def count_pages(path):
    """课件有几页：pptx 数幻灯片，pdf 数页（有 pypdf 用它，没有就数页对象）；数不出来返回 None。"""
    import re
    low = (path or "").lower()
    try:
        if low.endswith(".pptx"):
            import zipfile
            with zipfile.ZipFile(path) as z:
                return sum(1 for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)) or None
        if low.endswith(".pdf"):
            try:
                import pypdf
                return len(pypdf.PdfReader(path).pages) or None
            except ImportError:
                with open(path, "rb") as f:
                    return len(re.findall(rb"/Type\s*/Page(?![a-z])", f.read())) or None
    except Exception:  # noqa: BLE001  坏文件、加密文件：页数不知道就不写页数
        return None
    return None


def week_materials(ctx, code, week, back=2):
    """这周和前 back 周模块里的课件文件：[{week, title, local, locked, pages}]。按模块名或文件名里的周次认。"""
    import cc_downloads
    import cc_study
    mods = cc_study.load_modules(ctx).get(code) or []
    mats = ctx.materials_dir(code)
    out, seen = [], set()
    for w in range(max(1, week - back), week + 1):
        for m in mods:
            in_week = cc_downloads.week_matches(m.get("name"), w)
            for it in m.get("items") or []:
                if it.get("type") != "File":
                    continue
                name = cc_downloads.doc_name(it)
                if not name.lower().endswith(cc_downloads.DOC_EXT) or name in seen:
                    continue
                if not (in_week or cc_downloads.week_matches(it.get("title"), w)):
                    continue
                seen.add(name)
                local = os.path.join(mats, cc_downloads.safe_filename(name))
                have = os.path.exists(local)
                out.append({"week": w, "title": it.get("title") or name, "local": local if have else None,
                            "locked": bool((it.get("content_details") or {}).get("locked_for_user")),
                            "pages": count_pages(local) if have else None})
    return out


def display_code(course):
    """页面和问话里显示的课程代码：档案里为了不重名可能是 MECO69362，课程名里写的才是 MECO6936。"""
    import re
    m = re.search(r"\b[A-Z]{3,5}\d{3,5}[A-Z]?\b", course.get("name") or "")
    code = course.get("code") or ""
    return m.group(0) if m and code.startswith(m.group(0)) else code
