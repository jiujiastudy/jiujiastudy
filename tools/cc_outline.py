"""课程说明（unit outline / syllabus）里的每周安排：整理成一张表存进档案，周报按周次查「这周讲什么」。

只给模块没按周分的课用（模块按周分的课，以模块为准）。

位置：<档案>/outline/<课程代码>.json
格式（schema 1）：
{"schema": 1, "course": "MECO6941",
 "source": {"title": "Unit outline MECO6941 Semester 2 2026", "url": "https://…", "fetched_at": "2026-10-06T08:00:00+00:00"},
 "weeks": {"1": "Introduction to podcasting", "9": "Beginnings, structure, production workshop"},
 "weeks_zh": {"9": "开头、结构、制作工作坊"}}           weeks_zh 可省：AI 核对时给英语一般的学生补一句中文

怎么来：coach.py outline <课> --url <公开的课程说明页>（只 GET，不带任何登录信息），或 --syllabus（Canvas 课程的
Syllabus 页，走已经连好的接口）。脚本按「Week 9 …」这种行认出每周的题目；认不出、认错，AI 照页面整理一张表用 --file 存。
"""
import datetime as dt
import html as _html
import json
import os
import re

SCHEMA = 1
WEEK_LINE = re.compile(r"^(?:week|wk)\s*0?(\d{1,2})\b[\s:：.,\-–—|]*(.*)$", re.I)
NOISE = re.compile(r"^(lecture|tutorial|seminar|workshop|lab|class)\s*\(|^lo\d|^\(?\d+(\.\d+)?\s*(hr|hrs|hour|hours)\)?$|^due\s*date", re.I)
MIN_WEEKS = 3  # 认出的周少于这个数，多半认错了：交给 AI


def path(home, code):
    return os.path.join(home, "outline", f"{code}.json")


def validate(t, code=None):
    if not isinstance(t, dict):
        return ["不是 JSON 对象"]
    bad = []
    if t.get("schema") != SCHEMA:
        bad.append(f"schema 不是 {SCHEMA}")
    if code and t.get("course") != code:
        bad.append("course 和课程代码对不上")
    weeks = t.get("weeks")
    if not isinstance(weeks, dict) or not weeks:
        bad.append("weeks 至少要有一周")
    else:
        for k, v in weeks.items():
            if not str(k).isdigit() or not isinstance(v, str) or not v.strip():
                bad.append(f"weeks[{k}] 要是「周次: 题目」")
                break
    if t.get("weeks_zh") is not None and not isinstance(t.get("weeks_zh"), dict):
        bad.append("weeks_zh 要是「周次: 中文」")
    return bad


def load(home, code):
    """能用的表，或者 None（没有、读不了、格式不对都当没有）。"""
    try:
        with open(path(home, code), encoding="utf-8") as f:
            t = json.load(f)
    except (OSError, ValueError):
        return None
    return None if validate(t, code) else t


def save(home, code, table):
    os.makedirs(os.path.dirname(path(home, code)), exist_ok=True)
    with open(path(home, code), "w", encoding="utf-8", newline="\n") as f:
        json.dump(table, f, ensure_ascii=False, indent=1)
    return path(home, code)


def topic_for(table, week_no):
    """(英文题目, 中文) 或 None。"""
    if not table or not week_no:
        return None
    en = (table.get("weeks") or {}).get(str(week_no))
    if not en:
        return None
    return en.strip(), ((table.get("weeks_zh") or {}).get(str(week_no)) or "").strip() or None


def text_lines(html):
    """网页 → 一行一段的纯文字（去掉脚本和样式）。"""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "", flags=re.S | re.I)
    t = re.sub(r"<(br|/p|/div|/li|/tr|/td|/th|/h\d)[^>]*>", "\n", t, flags=re.I)
    t = _html.unescape(re.sub(r"<[^>]+>", " ", t))
    return [re.sub(r"\s+", " ", x).strip() for x in t.split("\n") if x.strip()]


def extract_weeks(lines):
    """按「Week 9 题目」或「Week 09」下一行是题目，认出每周的题目。
    课程说明里周次常出现在好几张表里（作业截止表、每周安排表）：按位置分成几段，挑认出周数最多的那一段。
    同一周在那一段里出现两次（讲座、辅导各一行）就合在一起。"""
    hits = []
    for i, line in enumerate(lines):
        m = WEEK_LINE.match(line)
        if not m:
            continue
        n = int(m.group(1))
        if not 1 <= n <= 20:
            continue
        rest = m.group(2).strip(" |:：-–—")
        if not rest:
            nxt = next((x for x in lines[i + 1:i + 4] if x.strip() and not WEEK_LINE.match(x) and not NOISE.search(x)), "")
            rest = nxt.strip(" |:：-–—")
        rest = re.split(r"\s*\|\s*", rest)[0].strip()[:120]
        if rest and not NOISE.search(rest):
            hits.append((i, n, rest))
    runs, cur = [], []
    for h in hits:
        if cur and h[0] - cur[-1][0] > 30:
            runs.append(cur)
            cur = []
        cur.append(h)
    if cur:
        runs.append(cur)
    if not runs:
        return {}
    best = max(runs, key=lambda r: len({n for _, n, _ in r}))
    weeks = {}
    for _, n, rest in best:
        have = weeks.setdefault(str(n), [])
        if rest not in have and len(have) < 2:
            have.append(rest)
    out = {k: "；".join(v) for k, v in sorted(weeks.items(), key=lambda kv: int(kv[0]))}
    return out if len(out) >= MIN_WEEKS else {}


def fetch_public(url, timeout=20):
    """公开网页：只 GET，不带 cookie 和 token。"""
    import urllib.request
    if not re.match(r"^https?://", url or ""):
        raise ValueError("只认 http(s) 网址")
    import brand
    req = urllib.request.Request(url, headers={"User-Agent": f"{brand.SLUG}/2 (read-only; outline)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 网址由用户或 AI 给，只读
        return r.read().decode("utf-8", errors="replace")


def build(code, weeks, title, url, now=None):
    return {"schema": SCHEMA, "course": code,
            "source": {"title": title, "url": url, "fetched_at": (now or dt.datetime.now(dt.timezone.utc)).replace(microsecond=0).isoformat()},
            "weeks": weeks}
