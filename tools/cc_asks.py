"""可以让我做的：从周计划 JSON 里挑几句「学生能直接复制去跟 AI 说」的话。

为什么有这一块：学生拿到周报也常常不知道下一步能让 AI 干什么、不知道怎么开口。
所以按当下处境（作业类型和日程）挑好几句现成的话，点一下复制。

三条硬规矩：
1. 只建议这个技能真做得出来的产出（见 produces，对应 references/toolbox.md）。做不到的事一句都不许出现。
2. 不代写计分内容：起角度、列提纲、挑毛病、讲概念、做导读/复习包/排练表、拟不计分的消息，都可以；
   「帮我写这篇论文」不行。
3. 纯函数：只吃周计划 dict，不读时钟、不读 config、不碰文件。所以能单测，在 golden 里也不会随日期漂。
"""
import re

MAX_LINE = 72   # 整句上限：一行读得完，手机上也不至于折成三行
SHOW = 3        # 卡片上露几条
MAX_TOTAL = 6   # 连折叠的一起，最多留几条
URGENT = ("overdue", "exam", "quiz", "write", "discussion", "oral", "homework")  # deadline 驱动的那几类

# 这个技能真做得出来的产出；每条建议必须落在这里面（tests/test_asks.py 机器校验）
PRODUCES = ("消息草稿", "复习包", "模拟小测", "写东西", "排练表", "导读", "下课件", "重排清单", "讲概念")

ORAL_RE = re.compile(r"(?i)presentation|pitch|viva|oral|seminar|moot|debate|演讲|口试|答辩|汇报|展示")
ATTEND_RE = re.compile(r"(?i)participation|attendance|sona|打卡|出勤|考勤|签到")
BIG_RE = re.compile(r"(?i)mid-?semester|in-?semester|midterm|final|exam|期中|期末|大考")

# 文案。占位符：{course} 课程代码、{item} 作业名、{when} 时间、{file} 课件名
TEXTS = {
    "overdue": "{course} {item} 过期了，帮我拟一条给老师的消息，问能不能补交。",
    "exam": "{course} {item}{when}，帮我做个复习包，复习计划和模拟小测都要。",
    "quiz": "{course} {item}{when}，出一套 10 道的模拟小测，带中文解析。",
    "write": "{course} {item}{when}，先给我三个角度和一份提纲，正文我自己写。",
    "discussion": "{course} {item}{when}，给我两个能接住别人的角度，正文我自己写。",
    "oral": "{course} {item}{when}，帮我做张排练表，标好每段讲几分钟。",
    "homework": "{course} {item}{when}，讲讲它到底要我做什么，第一步从哪下手。",
    "guide": "{file} 我还没看，帮我做份导读，20 分钟读完，重点和例子留着。",
    "state_overload": "我这周排不开，帮我重排本周清单，只留必做的，按权重排。",
    "state_stuck": "{course} 我看卡住了，挑最难的那块做逐页精讲，要课件里的例子。",
    "state_sick": "我病了，帮我拟一条给老师的消息，问这周到期的能不能延期。",
    "state_behind": "我落下不少，帮我重排本周清单，只留上课前要看的。",
    "prefetch": "把这周要看的列出来，能下的课件先下下来，我按顺序看。",
}

PRODUCED_BY = {
    "overdue": "消息草稿", "exam": "复习包", "quiz": "模拟小测", "write": "写东西",
    "discussion": "写东西", "oral": "排练表", "homework": "重排清单", "guide": "导读",
    "state_overload": "重排清单", "state_stuck": "讲概念", "state_sick": "消息草稿",
    "state_behind": "重排清单", "prefetch": "下课件",
}

STATE_KIND = {"过载": "state_overload", "卡住": "state_stuck", "病了": "state_sick", "落后": "state_behind"}


def _pct(weight):
    """权重字符串 → 数字。"—"、空、认不出都算 0。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*[%％]", str(weight or ""))
    return float(m.group(1)) if m else 0.0


def _clean(s, limit=40):
    """压平空白、摘掉末尾那段括号补充说明、太长的截断。

    这句话要被原样复制，不能带换行；末尾括号里多半是「（BYOD + LockDown Browser，60 分钟，50 题）」
    这种补充，截断时最容易切在括号中间，不如整块去掉。
    """
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    s = re.sub(r"(?i)^(assignment|assessment task|quiz|task|homework|作业|任务)\s*[:：]\s*", "", s)
    while len(s) > limit:
        cut = re.sub(r"\s*[（(][^（()）]*[）)]\s*$", "", s)
        if cut == s or not cut:
            break
        s = cut
    return s if len(s) <= limit else s[:limit].rstrip() + "…"


def _when(rel):
    """「今天」「明天」补一个「截止」，其余（还有 N 天）原样。空的就不写。"""
    rel = (rel or "").strip()
    if rel in ("今天", "明天"):
        return "，" + rel + "截止"
    return "，" + rel if rel else ""


def _submitted(x):
    """交没交。新字段优先；老档案/手写周计划退回看中文状态串。"""
    if x.get("submitted"):
        return True
    return str(x.get("status") or "").startswith(("已交", "已批改"))


def _items(plan):
    """把 deadline 拉平成统一形状。优先用 study.courses[]（字段全），没有就退回顶层 deadlines[]。"""
    out = []
    courses = ((plan.get("study") or {}).get("courses")) or []
    for c in courses:
        for x in c.get("deadline_related") or []:
            out.append({"course": x.get("course") or c.get("code"), "title": x.get("title"),
                        "weight": _pct(x.get("weight")), "days_left": x.get("days_left"),
                        "rel": x.get("rel"), "overdue": x.get("kind") == "Overdue",
                        "exam": bool(x.get("exam")), "submitted": _submitted(x),
                        "stypes": [str(s).lower() for s in x.get("submission_types") or []]})
    if not courses:  # 手写周计划：只有顶层那份，字段少，够触发考试一类
        for x in plan.get("deadlines") or []:
            out.append({"course": x.get("course"), "title": x.get("item"),
                        "weight": _pct(x.get("weight")), "days_left": x.get("days_left"),
                        "rel": x.get("rel"), "overdue": bool(x.get("overdue")),
                        "exam": x.get("kind") == "exam", "submitted": _submitted(x), "stypes": []})
    return [x for x in out if x.get("title")]


def _files(plan):
    """这周排了、还没打勾的课件文件。每门课取第一份。

    只认 File：Page 没有正文、视频没有转写，对着它们说「做成导读」是承诺做不到的事。
    """
    out = []
    for c in ((plan.get("study") or {}).get("courses")) or []:
        for x in c.get("before_class") or []:
            if x.get("kind") == "File" and x.get("status") != "✅" and not x.get("locked"):
                out.append({"course": x.get("course") or c.get("code"), "title": x.get("title")})
                break
    return out


def _file_label(course, title, limit=40):
    """课件名自带课号就不再加前缀。用 startswith 不用 in：有的课程代码就是「3」，用 in 会被标题里的数字误伤。"""
    course = (course or "").strip()
    head = "" if not course or str(title or "").strip().startswith(course) else f"{course} 的 "
    return head + _clean(title, max(8, limit - len(head)))


def _line(kind, **kw):
    """填好一句话。留给作业名/课件名的位置由整句上限反推，免得一刀切得太狠或太松。"""
    tmpl = TEXTS[kind]
    if "{item}" in tmpl:
        room = MAX_LINE - len(tmpl.format(item="", **{k: v for k, v in kw.items() if k != "item"}))
        kw["item"] = _clean(kw.get("item"), max(8, room))
    if "{file}" in tmpl:
        room = MAX_LINE - len(tmpl.format(file="", **{k: v for k, v in kw.items() if k != "file"}))
        kw["file"] = _file_label(kw.pop("course", ""), kw.get("file"), max(8, room))
    return {"kind": kind, "text": tmpl.format(**kw), "produces": PRODUCED_BY[kind]}


def _urgency(x, kind):
    """排前后看的是「还有几天」，不是类别——类别只当同一天里的先后。

    过期的那条要分轻重：两分的 practice quiz 不该压过明天就截止的 30%。
    """
    d = x["days_left"]
    if kind == "overdue":
        return 0 if (x["weight"] >= 10 or (d is not None and d >= -3)) else 6
    if d is None:
        return 9
    return d - (3 if kind == "exam" else 1 if kind == "quiz" else 0)  # 考试要提前动手


def _kind_of(x):
    """一条 deadline 归到哪个桶。顺序就是优先级，命中即止。"""
    if x["overdue"] and not x["submitted"]:
        return "overdue"
    if x["submitted"]:
        return None  # 交都交了，不提
    d, st, title = x["days_left"], x["stypes"], x["title"] or ""
    if d is None or d < 0:
        return None
    if ATTEND_RE.search(title):
        return None  # 参与分、打卡、出勤：只有「问老师能不能补」那条成立，其余都替不了学生去上课
    if x["exam"] and d <= 14 and (x["weight"] >= 10 or BIG_RE.search(title)):
        return "exam"
    if x["exam"] and d <= 7:
        return "quiz"  # 分量轻的小测：给自测题，不给整套复习包
    if ORAL_RE.search(title) and d <= 10:
        return "oral"
    if ("discussion_topic" in st) and d <= 7:
        return "discussion"
    if ({"online_upload", "online_text_entry"} & set(st)) and d <= (14 if x["weight"] >= 25 else 7):
        return "write"  # 大论文要提前动手，窗口放宽
    if "on_paper" in st and d <= 10:
        return "oral"
    if d <= 7:
        return "homework"  # 类型认不出来的（外部工具、手动记的）：只要快到了就给一条通用的
    return None


def _spread(lines, n):
    """露出来的这几条：每类最多一条、每门课最多一条。不然三行里两行都是复习包，或者都是同一门课。"""
    out, kinds, courses = [], set(), set()
    for x in lines:
        if len(out) >= n:
            break
        if x["kind"] in kinds or (x.get("course") and x["course"] in courses):
            continue
        kinds.add(x["kind"])
        if x.get("course"):
            courses.add(x["course"])
        out.append(x)
    return out


def suggest(plan, show=SHOW, total=MAX_TOTAL):
    """周计划 dict → 已排序、已去重、已限量的建议。前 show 条给卡片露出，其余折叠。"""
    plan = plan or {}
    cands, seen = [], set()

    def add(bucket, sort_key, key, line, course=""):
        if key in seen:
            return
        seen.add(key)
        line["course"] = course
        cands.append((bucket, sort_key, line))

    order = {k: i for i, k in enumerate(URGENT)}
    for x in _items(plan):
        kind = _kind_of(x)
        if not kind:
            continue
        course, title = (x["course"] or "").strip(), _clean(x["title"])
        add(_urgency(x, kind), (order[kind], -x["weight"], course, title),
            (course, title), _line(kind, course=course, item=x["title"], when=_when(x["rel"])),
            course=course)

    state = plan.get("state") or {}
    kind = STATE_KIND.get(state.get("label"))
    if kind:
        top = (plan.get("study") or {}).get("top_one") or {}
        course = top.get("course") or next((c.get("code") for c in ((plan.get("study") or {}).get("courses")) or []), "")
        if kind != "state_stuck" or course:
            add(90, (0, 0, "", ""), ("state",), _line(kind, course=course))

    for f in _files(plan)[:2]:
        add(91, (0, 0, f["course"] or "", f["title"] or ""), ("file", f["course"], f["title"]),
            _line("guide", course=f["course"], file=f["title"]), course=f["course"])

    if ((plan.get("study") or {}).get("courses")) or plan.get("deadlines"):
        add(92, (0, 0, "", ""), ("prefetch",), _line("prefetch"))

    ordered = [line for _, _, line in sorted(cands, key=lambda c: (c[0], c[1]))]
    # 露出的三条 = 最急的两条 + 一条不是 deadline 的：不然忙的那周三行全是 deadline，
    # 和正下方的「今天」「本周最要紧」「Deadline 两周内」重复第四遍，卡片就成了噪音。
    urgent = _spread([x for x in ordered if x["kind"] in URGENT], show - 1)
    other = [x for x in ordered if x["kind"] not in URGENT]
    shown = (urgent + other[:1])[:show] or ordered[:show]
    if len(shown) < show:
        shown += [x for x in ordered if x not in shown][:show - len(shown)]
    rest = [x for x in ordered if x not in shown][:max(0, total - len(shown))]
    return shown + rest
