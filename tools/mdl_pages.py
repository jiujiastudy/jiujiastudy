"""Moodle 页面解析：纯函数，不联网，只用标准库。

只认与语言无关的标记（class、id 前缀、data- 属性、链接格式），本地化文字不拿来判断。
约定：认不出页面结构（登录页、错误页、别的页面、成绩页正在重算等）一律返回 None，
表示「这一页没读懂」；读懂了但确实没有内容，返回空列表。调用方据此记「这一页读不懂」。
页面上的日期只有按用户语言和时区写成的文字，这里不从文字里取日期（日期以日历时间戳为准），
所以 due_at / cutoff_at / extension_at / open_at / close_at 恒为 None，键留着给调用方统一形状。
"""
import datetime as dt
import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlsplit

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_SKIP = {"script", "style", "template", "noscript"}
_HIDDEN = {"sr-only", "visually-hidden", "accesshide"}
_BLOCK = {"p", "div", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6",
          "blockquote", "pre", "section", "article", "dd", "dt", "hr"}
_TIME_CLS = {"earlysubmission", "latesubmission", "overdue", "timeremaining"}
_TEXT_CLS = {"summarytext", "activity-altcontent", "activity-description", "contentwithoutlink", "contentafterlink"}
_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")
_MCFG = re.compile(r"\bM\.cfg\s*=\s*(?=\{)")
_ROW_ID = re.compile(r"^row_(\d+)_(\d+)$")
_MOD_LINK = re.compile(r"/mod/([a-z][a-z0-9_]*)/view\.php\?(?:.*&)?id=(\d+)")


# ---------------------------------------------------------------- 小 DOM
class _Node:
    __slots__ = ("tag", "attrs", "kids", "up")

    def __init__(self, tag, attrs, up):
        self.tag, self.up, self.kids = tag, up, []
        self.attrs = {k: ("" if v is None else v) for k, v in attrs}

    def get(self, key):
        return self.attrs.get(key, "")


class _Builder(HTMLParser):
    """容错的树：没闭合的 td/tr/li/p 按 HTML 规则隐式闭合，多余的结束标签忽略。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", [], None)
        self.stack = [self.root]

    def _close(self, tags, stops):
        for i in range(len(self.stack) - 1, 0, -1):
            tag = self.stack[i].tag
            if tag in tags:
                del self.stack[i:]
                return
            if tag in stops:
                return

    def handle_starttag(self, tag, attrs):
        if tag in ("td", "th"):
            self._close({"td", "th"}, {"tr", "table"})
        elif tag == "tr":
            self._close({"tr"}, {"table", "tbody", "thead", "tfoot"})
        elif tag == "li":
            self._close({"li"}, {"ul", "ol"})
        elif tag == "p":
            self._close({"p"}, {"div", "td", "th", "li", "table", "body"})
        node = _Node(tag, attrs, self.stack[-1])
        self.stack[-1].kids.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].kids.append(_Node(tag, attrs, self.stack[-1]))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].kids.append(data)


def _as_text(html):
    if isinstance(html, (bytes, bytearray)):
        return bytes(html).decode("utf-8", "replace")
    return html if isinstance(html, str) else ""


def _parse(html):
    b = _Builder()
    b.feed(_as_text(html))
    b.close()
    return b.root


def _walk(node):
    """深度优先、文档顺序列出所有元素（不递归，防深层嵌套）。"""
    todo = [k for k in reversed(node.kids) if isinstance(k, _Node)]
    while todo:
        n = todo.pop()
        yield n
        todo.extend(k for k in reversed(n.kids) if isinstance(k, _Node))


def _cls(n):
    return set(n.get("class").split())


def _first(node, pred):
    return next((n for n in _walk(node) if pred(n)), None)


def _closest(n, pred):
    n = n.up
    while n is not None and n.tag != "#root":
        if pred(n):
            return n
        n = n.up
    return None


def _own_rows(table):
    """表格自己的行，不含嵌套表格里的行。"""
    return [tr for tr in _walk(table) if tr.tag == "tr" and _closest(tr, lambda x: x.tag == "table") is table]


def _cells(tr):
    return [k for k in tr.kids if isinstance(k, _Node) and k.tag in ("td", "th")]


def _text(node):
    """可见文字：跳过脚本和读屏专用文字，块元素换行；每行压空白、去空行。"""
    parts, todo = [], [node]
    while todo:
        n = todo.pop()
        if isinstance(n, str):
            parts.append(n)
            continue
        if n.tag in _SKIP or (n is not node and _cls(n) & _HIDDEN):
            continue
        brk = n.tag in _BLOCK or n.tag == "br"
        if brk:
            parts.append("\n")
            todo.append("\n")
        todo.extend(reversed(n.kids))
    lines = (" ".join(ln.split()) for ln in "".join(parts).split("\n"))
    return "\n".join(ln for ln in lines if ln)


def _line(node):
    return " ".join(_text(node).split())


def _num(s):
    """「72.50」「50,00 %」→ 浮点；小数点可能是逗号（Moodle 不输出千分位）。"""
    m = _NUM.search((s or "").replace("\xa0", " "))
    return float(m.group(0).replace(",", ".")) if m else None


def _iso(ts):
    try:
        return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _path(url):
    try:
        return urlsplit(url or "").path
    except ValueError:
        return ""


# ---------------------------------------------------------------- 页面类型
def _body(root):
    return _first(root, lambda n: n.tag == "body")


def _unreadable(root):
    """登录页、错误页：哪个解析函数都不该从里面读东西。"""
    body = _body(root)
    if body is not None and (body.get("id") == "page-login-index" or "notloggedin" in _cls(body)):
        return True
    return _first(root, lambda n: n.get("data-rel") == "fatalerror") is not None


def _is_page(root, pagetype):
    """body 的 id 是 page-<pagetype>，或 class 里有 path-<pagetype 前两段>。"""
    body = _body(root)
    if body is None:
        return False
    path = "path-" + "-".join(pagetype.split("-")[:2])
    return body.get("id") == "page-" + pagetype or path in _cls(body)


def m_cfg(html):
    """页面里的 M.cfg（json_encode 出来的，斜杠转义成 \\/）→ dict；没有或坏了返回 None。"""
    s = _as_text(html)
    dec = json.JSONDecoder()
    for m in _MCFG.finditer(s):
        try:
            val, _ = dec.raw_decode(s, m.end())
        except ValueError:
            continue
        if isinstance(val, dict):
            return val
    return None


# ---------------------------------------------------------------- 作业页
def _assign_can_edit(root):
    """有没有编辑入口：表单按钮 input[name=action][value=editsubmission]，或限时作业的链接。"""
    for n in _walk(root):
        if n.tag == "input" and n.get("name") == "action" and n.get("value") == "editsubmission":
            return True
        href = n.get("href") if n.tag == "a" else ""
        if href and "/mod/assign/view.php" in href and re.search(r"[?&]action=editsubmission(?:[&#]|$)", href):
            return True
    return False


def _row_keys(tr):
    """状态表一行里 td 的键名 class（去掉 html_writer 加的 cell/cN/lastcol）。"""
    tds = [c for c in _cells(tr) if c.tag == "td"]
    if not tds:
        return None
    return {c for c in _cls(tds[0]) if c not in ("cell", "lastcol") and not re.fullmatch(r"c\d+", c)}


def _assign_rows(table):
    """逐行归类 → (state, graded, 延期行在不在, 剩余时间行的 class)。"""
    keys = [k for k in (_row_keys(tr) for tr in _own_rows(table)) if k is not None]
    state = graded = timecls = None
    gi = ti = None
    for i, k in enumerate(keys):
        st = next((c[len("submissionstatus"):] for c in sorted(k) if c.startswith("submissionstatus")), None)
        if st and state is None:
            state = st
        if k & {"submissiongraded", "submissionnotgraded"} and gi is None:
            gi, graded = i, "submissiongraded" in k
        if k & _TIME_CLS and ti is None:
            ti, timecls = i, next(iter(k & _TIME_CLS))
    has_ext = None
    if gi is not None:
        # 延期行 = 评分行和剩余时间行之间那行无类的；没有剩余时间行就不可能有延期
        has_ext = ti is not None and any(not keys[j] for j in range(gi + 1, ti))
    return state or "new", graded, has_ext, timecls


def assign_status(html):
    """作业页 → 交没交、评没评。

    返回 {"submitted", "graded", "due_at", "cutoff_at", "extension_at",
          "state", "can_edit", "has_extension", "time_class"}；日期键恒为 None。
    submitted：True 已正式提交；False 没交（新建 / 草稿 / 被重新打开要再交）；
    None 看不出来（没有状态表，或状态是 new 又没有编辑入口——线下作业和已关闭的作业分不开）。
    overdue 只说明「过了截止还没正式提交」，线下作业也有，不拿它判没交。
    """
    root = _parse(html)
    if _unreadable(root):
        return None
    box = _first(root, lambda n: "submissionstatustable" in _cls(n))
    if box is None and not _is_page(root, "mod-assign-view"):
        return None
    out = {"submitted": None, "graded": None, "due_at": None, "cutoff_at": None, "extension_at": None,
           "state": None, "can_edit": _assign_can_edit(root), "has_extension": None, "time_class": None}
    table = _first(box, lambda n: n.tag == "table") if box is not None else None
    if table is None:
        return out  # 没有状态表：没权限或访客，不能当没交
    state, graded, has_ext, timecls = _assign_rows(table)
    out.update(state=state, graded=graded, has_extension=has_ext, time_class=timecls)
    if state == "submitted" or timecls in ("earlysubmission", "latesubmission"):
        out["submitted"] = True
    elif state in ("draft", "reopened") or (state == "new" and out["can_edit"]):
        out["submitted"] = False
    return out


# ---------------------------------------------------------------- 测验页
def _is_form_to(n, path_end):
    return n.tag == "form" and _path(n.get("action")).endswith(path_end)


def _has_review(card):
    """回顾入口：链接 review.php?attempt=，或弹窗测验的表单（action 是 review.php，里面有 attempt）。"""
    for n in _walk(card):
        if n.tag == "a" and "/mod/quiz/review.php?attempt=" in n.get("href"):
            return True
        if _is_form_to(n, "/mod/quiz/review.php"):
            if _first(n, lambda x: x.tag == "input" and x.get("name") == "attempt") is not None:
                return True
    return False


def _row_has_score(tr):
    """成绩格以 <b>数字</b> 开头才算有分；没 <b>（如「待评分」）不算。"""
    td = next((c for c in _cells(tr) if c.tag == "td"), None)
    if td is None:
        return False
    first = next((k for k in td.kids if isinstance(k, _Node) or k.strip()), None)
    return isinstance(first, _Node) and first.tag == "b" and _num(_line(first)) is not None


def quiz_status(html):
    """测验页 → 做了几次、还能不能做。

    返回 {"attempts_finished", "can_attempt_again", "open_at", "close_at",
          "attempts", "in_progress", "graded", "reviewable"}；日期键恒为 None。
    已完成 = 尝试摘要表有 ≥4 行（有完成时间和用时，只有 FINISHED 才有）。
    reviewable：不到 4 行、但有回顾入口的尝试数。5.0 的 SUBMITTED（已交、待处理）和放弃的尝试都是这样，
    所以 attempts_finished 为 0 不等于「没交」。
    graded：已完成的尝试里有一格以 <b>分数</b> 开头为 True，否则 None（待评分或不给看分，分不开）。
    """
    root = _parse(html)
    if _unreadable(root):
        return None
    tables = [n for n in _walk(root) if n.tag == "table" and "quizreviewsummary" in _cls(n)]
    start = _first(root, lambda n: _is_form_to(n, "/mod/quiz/startattempt.php")) is not None
    marks = _first(root, lambda n: _cls(n) & {"quizinfo", "quizattempt", "quizstartbuttondiv"}) is not None
    if not (tables or start or marks or _is_page(root, "mod-quiz-view")):
        return None
    finished = graded = reviewable = 0
    open_card = False
    for t in tables:
        rows = _own_rows(t)
        card = _closest(t, lambda n: "card" in _cls(n)) or t.up
        if len(rows) >= 4:
            finished += 1
            graded += any(_row_has_score(tr) for tr in rows[4:])
        elif _has_review(card):
            reviewable += 1
        else:
            open_card = True
    return {"attempts_finished": finished, "can_attempt_again": start, "open_at": None, "close_at": None,
            "attempts": len(tables), "in_progress": start and open_card, "graded": True if graded else None,
            "reviewable": reviewable}


# ---------------------------------------------------------------- 成绩页
def _weight(td):
    """权重格：第一个 <br> 前的「40.00 %」；后面带状态（Empty / Dropped…）说明没算进去，当作没有。"""
    if td is None:
        return None
    head, tail = [], []
    for k in td.kids:
        if isinstance(k, _Node) and k.tag == "br" and not tail:
            tail.append("")
            continue
        (tail if tail else head).append(k if isinstance(k, str) else _line(k))
    if "".join(tail).strip():
        return None
    return _num("".join(head))


def _range_max(td):
    """满分格「0–100」取后半；量表文字、文本型成绩项（两边空）都给 None。"""
    if td is None:
        return None
    parts = _line(td).split("–")
    if len(parts) < 2:
        return None
    hi = parts[-1].strip()
    return _num(hi) if re.fullmatch(r"-?\d+(?:[.,]\d+)?", hi) else None


def _grade(td):
    """已得分：保留原文（显示方式可能是分数、百分比或等级）；「-」、出错、隐藏只给提交时间都给 None。"""
    if td is None:
        return None, None
    k = _cls(td)
    if "gradingerror" in k:
        return None, "error"
    if "datesubmitted" in k:
        return None, "submitted"
    s = _line(td)
    return (None if s in ("", "-") else s), None


def _grade_row(th):
    tr = th.up
    tds = {c: n for n in _cells(tr) if n.tag == "td" for c in _cls(n) if c.startswith("column-")}
    kind = _first(th, lambda n: n.tag == "div" and _cls(n) & {"item", "categoryitem", "courseitem"})
    kind = next(iter(_cls(kind) & {"item", "categoryitem", "courseitem"}), None) if kind else None
    head = _first(th, lambda n: "gradeitemheader" in _cls(n)) or _first(th, lambda n: "rowtitle" in _cls(n)) or th
    m = _MOD_LINK.search(head.get("href")) if head.tag == "a" else None
    grade, flag = _grade(tds.get("column-grade"))
    return {"name": _line(head), "cmid": int(m.group(2)) if m else None, "module": m.group(1) if m else None,
            "weight_pct": _weight(tds.get("column-weight")), "range_max": _range_max(tds.get("column-range")),
            "grade": grade, "grade_flag": flag, "is_category": kind in ("categoryitem", "courseitem"),
            "item_id": int(_ROW_ID.match(th.get("id")).group(1))}


def grade_items(html):
    """学生成绩页（user report）→ 每个成绩项一条。

    返回 [{"name", "cmid", "module", "weight_pct", "range_max", "grade", "is_category", "grade_flag", "item_id"}]。
    按 th[id^=row_] 遍历（隐藏项会输出空行，不按 tr 计数）；列按 td 的 column-* class 取，
    权重列被关掉就是 None。is_category：分类总分和课程总分。
    没有 table.user-grade（重算中、课程被隐藏、没权限）返回 None，不能当作「没有计分项」。
    """
    root = _parse(html)
    if _unreadable(root):
        return None
    table = _first(root, lambda n: n.tag == "table" and "user-grade" in _cls(n))
    if table is None:
        return None
    return [_grade_row(th) for th in _walk(table)
            if th.tag == "th" and _ROW_ID.match(th.get("id")) and th.up.tag == "tr"]


# ---------------------------------------------------------------- 论坛
def forum_type(html):
    """论坛页 body class 里的 forumtype-<type>（news = 公告论坛）；不是论坛页返回 None。"""
    body = _body(_parse(html))
    if body is None:
        return None
    return next((c[len("forumtype-"):] for c in sorted(_cls(body)) if c.startswith("forumtype-")), None) or None


def _discussion(tr):
    try:
        did = int(tr.get("data-discussionid"))
    except ValueError:
        return None
    link = _first(tr, lambda n: n.tag == "a" and "/mod/forum/discuss.php?d=" in n.get("href") and n.get("title")) \
        or _first(tr, lambda n: n.tag == "a" and "/mod/forum/discuss.php?d=" in n.get("href"))
    subject = (link.get("title") or _line(link)) if link is not None else ""
    t = _first(tr, lambda n: n.tag == "time" and n.get("id").startswith("time-created-"))
    who = _first(tr, lambda n: "author-info" in _cls(n))
    who = _first(who, lambda n: "text-truncate" in _cls(n)) if who is not None else None
    return {"id": did, "subject": " ".join(subject.split()), "time": _iso(t.get("data-timestamp")) if t else None,
            "author": _line(who) if who is not None else None}


def forum_discussions(html):
    """论坛讨论列表页 → [{"id", "subject", "time", "author"}]，time 是首帖时间（ISO UTC）。

    标题取链接的 title（链接文字会截到 100 字）；div.forumnodiscuss 表示确实还没有讨论 → []。
    认不出讨论列表返回 None。是不是公告论坛用 forum_type() 判断。
    """
    root = _parse(html)
    if _unreadable(root):
        return None
    rows = [n for n in _walk(root) if n.tag == "tr" and n.get("data-region") == "discussion-list-item"]
    known = rows or _first(root, lambda n: n.get("id").startswith("discussion-list-")
                           or (_cls(n) & {"discussion-list", "forumnodiscuss"})) is not None
    if not known:
        return None
    return [d for d in (_discussion(tr) for tr in rows) if d is not None]


# ---------------------------------------------------------------- 课程页、folder
def _is_course_page(root):
    """body 带 path-course-view（page-course-view-<格式>），或页面上有课程分节标记。"""
    if _is_page(root, "course-view"):
        return True
    return _first(root, lambda n: n.get("data-for") == "section"
                  or (n.tag == "li" and "section" in _cls(n) and n.get("id").startswith("section-"))) is not None


def course_texts(html):
    """课程页 → 分节说明、标签、活动说明里的文字（用来从文字里找日期）；按页面顺序，每段一条。

    认的 class：summarytext、activity-altcontent、activity-description、contentwithoutlink、contentafterlink，
    以及旧版 li.section 里的 div.summary。嵌套的只取最外层。不是课程页返回 None。
    """
    root = _parse(html)
    if _unreadable(root) or not _is_course_page(root):
        return None
    out, todo = [], [k for k in reversed(root.kids) if isinstance(k, _Node)]
    while todo:
        n = todo.pop()
        if n.tag in _SKIP:
            continue
        k = _cls(n)
        old = n.tag == "div" and "summary" in k and _closest(n, lambda x: x.tag == "li" and "section" in _cls(x))
        if k & _TEXT_CLS or old:
            s = _text(n)
            if s and s not in out:
                out.append(s)
            continue
        todo.extend(x for x in reversed(n.kids) if isinstance(x, _Node))
    return out


def _folder_url(href):
    """folder 里的文件地址：pluginfile.php/<ctx>/mod_folder/content/…；slasharguments 关掉时在 file= 里。"""
    try:
        parts = urlsplit(href)
    except ValueError:
        return None
    if not parts.path.endswith("/pluginfile.php") and "/pluginfile.php/" not in parts.path:
        return None
    inner = parts.path if "/pluginfile.php/" in parts.path else (parse_qs(parts.query).get("file") or [""])[0]
    inner = unquote(inner)
    return inner if "/mod_folder/content/" in inner else None


def folder_files(html):
    """folder 页（或课程页上内嵌的 folder）→ [{"name", "url"}]，按页面顺序、按地址去重。

    name 取 span.fp-filename，没有就取地址最后一段（URL 解码）。认不出 folder 页返回 None。
    """
    root = _parse(html)
    if _unreadable(root):
        return None
    out, seen = [], set()
    for a in _walk(root):
        href = a.get("href") if a.tag == "a" else ""
        inner = _folder_url(href) if href else None
        if not inner or href in seen:
            continue
        seen.add(href)
        span = _first(a, lambda n: "fp-filename" in _cls(n))
        name = _line(span) if span is not None else ""
        out.append({"name": name or inner.rstrip("/").rsplit("/", 1)[-1], "url": href})
    if out:
        return out
    tree = _first(root, lambda n: _cls(n) & {"foldertree", "filemanager"} or n.get("id").startswith("folder_tree"))
    return [] if tree is not None or _is_page(root, "mod-folder-view") else None
