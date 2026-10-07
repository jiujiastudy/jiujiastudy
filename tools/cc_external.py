"""外部平台的保底清单：每门课用到的 Padlet、Ed、Google 文档……

两路来源：
- 已经采集下来的（不访问任何网站）：模块里的外部链接和外部工具、近 14 天公告里的链接（标题写到这周的旧公告也算，
  「Information for Weeks 7, 8 and 9」）、快到期作业说明里的链接；
- external 命令去 Canvas 查一遍（7 天一次，只 GET）：导航栏里的外部工具（Ed、Zoom、阅读清单常挂在这里）、
  学生在哪个班、课程首页和名字像入口的课程页面里的链接。存 <档案>/external/<课>.found.json。
一处列着每个班各一个的链接（Class 15、Class 27……的 Padlet），只留学生自己班的。
找外部平台的主力仍是 AI：「提到了但没给链接」的它也认得出；这张清单是保底，清单上有、还没读过的进「还差 N 件」。

读的结果记在 <档案>/external/<课>.json：{网址: {platform, kind, title, result: ok|login|bot|error, last_try, read_at, note}}。
读到的页面文字存 <档案>/external/pages/<编号>.txt，给 AI 读。Padlet 读的是它网页自己取下来的整板数据（按栏列出全部帖子），
网页上只画出左边几栏也不影响。
"""
import datetime as dt
import hashlib
import html as _html
import json
import os
import re
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

from cc_time import parse_ts

# (网址里出现的片段, 平台名, 类别)。类别：通知作业 = 可能有作业和截止；内容；录播；阅读；会议
PLATFORMS = [
    ("docs.google.com/forms", "Google 表单", "表单"), ("forms.gle", "Google 表单", "表单"), ("qualtrics.com", "Qualtrics 表单", "表单"),
    ("forms.office.com", "Microsoft 表单", "表单"), ("forms.microsoft.com", "Microsoft 表单", "表单"),
    ("edstem.org", "Ed", "通知作业"), ("gradescope.", "Gradescope", "通知作业"), ("piazza.com", "Piazza", "通知作业"),
    ("perusall.com", "Perusall", "通知作业"), ("teams.microsoft.com", "Teams", "通知作业"), ("moodle", "Moodle", "通知作业"),
    ("blackboard", "Blackboard", "通知作业"), ("feedbackfruits.com", "FeedbackFruits", "通知作业"), ("kritik.io", "Kritik", "通知作业"),
    ("webassign.net", "WebAssign", "通知作业"), ("mylab.pearson.com", "Pearson MyLab", "通知作业"), ("mlm.pearson.com", "Pearson MyLab", "通知作业"),
    ("mheducation.com", "McGraw Hill Connect", "通知作业"), ("wileyplus.com", "WileyPLUS", "通知作业"),
    ("padlet.com", "Padlet", "内容"), ("padlet.org", "Padlet", "内容"), ("docs.google.com", "Google 文档", "内容"),
    ("drive.google.com", "Google Drive", "内容"), ("sites.google.com", "Google Sites", "内容"), ("youtube.com", "YouTube", "视频"),
    ("youtu.be", "YouTube", "视频"), ("vimeo.com", "Vimeo", "视频"), ("soundcloud.com", "SoundCloud", "音频"),
    ("github.io", "课程网站", "内容"), ("github.com", "GitHub", "内容"), ("notion.site", "Notion", "内容"), ("miro.com", "Miro", "内容"),
    ("sharepoint.com", "SharePoint", "内容"), ("onedrive.live.com", "OneDrive", "内容"), ("1drv.ms", "OneDrive", "内容"),
    ("dropbox.com", "Dropbox", "内容"),
    ("echo360", "Echo360 录播", "录播"), ("instructuremedia.com", "Canvas Studio", "录播"), ("panopto", "Panopto 录播", "录播"),
    ("kaltura", "Kaltura 录播", "录播"), ("leganto", "Leganto 阅读清单", "阅读"), ("ereserve", "eReserve", "阅读"),
    ("library.", "图书馆", "阅读"), ("zoom.us", "Zoom", "会议"),
]
# LTI 工具在 Canvas 里只有一个跳转链接，平台靠标题认
TOOL_TITLES = [
    (r"\bed\b|ed discussion", "Ed", "通知作业"), (r"gradescope", "Gradescope", "通知作业"), (r"piazza", "Piazza", "通知作业"),
    (r"perusall", "Perusall", "通知作业"), (r"feedback ?fruits", "FeedbackFruits", "通知作业"), (r"kritik", "Kritik", "通知作业"),
    (r"mylab|mastering", "Pearson MyLab", "通知作业"), (r"webassign", "WebAssign", "通知作业"), (r"wiley", "WileyPLUS", "通知作业"),
    (r"m[oö]bius", "Möbius", "通知作业"), (r"webwork", "WebWork", "通知作业"), (r"\bteams\b", "Teams", "通知作业"),
    (r"echo ?360|lecture recording", "Echo360 录播", "录播"), (r"panopto", "Panopto 录播", "录播"), (r"kaltura|my media", "Kaltura 录播", "录播"),
    (r"canvas studio|studio", "Canvas Studio", "录播"), (r"reading list|leganto", "Leganto 阅读清单", "阅读"),
    (r"padlet", "Padlet", "内容"), (r"zoom", "Zoom", "会议"),
]
# 链接文字只有「here」时靠前后的字认：这几个在普通句子里太常见，换成更窄的说法（「Audio Studio」不是 Canvas Studio）
NEAR_ONLY = {"Ed": r"ed discussion|edstem", "Canvas Studio": r"canvas studio", "Teams": r"microsoft teams|\bms teams",
             "Kaltura 录播": r"kaltura", "Echo360 录播": r"echo ?360"}
SKIP_HOSTS = ("mimecast", "safelinks.protection.outlook", "googletagmanager", "cookielaw", "w3.org", "fonts.")
LISTED_KINDS = ("通知作业", "内容", "阅读")   # 进「还差」的类别；会议、表单、录播、视频、音频不进（做学习页时 AI 读字幕）
# 模块不按周分的课：模块里只有「活的」平台进「还差」（会发作业、会一直更新）；整学期挂着的普通网站不用每周读
LIVING = {"Padlet", "Google 文档", "Google Drive", "Google Sites", "课程网站", "GitHub", "Notion", "Miro", "SharePoint", "OneDrive",
          "Dropbox"}
EXTERNAL_TAIL = re.compile(r"\s*Links to an external site\.?\s*$", re.I)   # Canvas 给外链文字自动加的读屏提示
WEEK_RE = re.compile(r"(?:week|wk)\s*0?(\d{1,2})\b", re.I)
WEEKS_RE = re.compile(r"\b(?:weeks?|wks?)\.?\s*((?:\d{1,2}\s*(?:[-–—/,&+]|to|and)\s*)*\d{1,2})(?!\d)", re.I)
CANVAS_TOOL = re.compile(r"/courses/\d+/external_tools/\d+")
GENERIC = re.compile(r"^(?:(?:click )?(?:here|link|this link|this|see here|open|visit|点这里|这里|链接)?\s*[.!:：]?"
                     r"|(?:youtube|vimeo) video player|embedded content|video)$", re.I)
FRESH_DAYS = 7


def _week(*texts):
    for t in texts:
        m = WEEK_RE.search(t or "")
        if m:
            return int(m.group(1))
    return None


def weeks_in(text):
    """「Week 9」「Weeks 7, 8 and 9」「Weeks 7–9」「Week 11/12」→ 写到的周次。"""
    out = set()
    for m in WEEKS_RE.finditer(text or ""):
        part = m.group(1)
        for a, b in re.findall(r"(\d{1,2})\s*(?:[-–—]|to)\s*(\d{1,2})", part):
            a, b = int(a), int(b)
            if 0 < a < b <= a + 13:
                out.update(range(a, b + 1))
        out.update(int(n) for n in re.findall(r"\d{1,2}", part) if 0 < int(n) <= 20)
    return out


def _tool_by_title(title):
    for pat, name, kind in TOOL_TITLES:
        if title and re.search(pat, title, re.I):
            return name, kind
    return None


def _tool_by_near(before, after):
    """链接前后的字里离链接最近的那个平台名。"""
    best = None
    for pat, name, kind in TOOL_TITLES:
        pat = NEAR_ONLY.get(name, pat)
        for m in re.finditer(pat, before or "", re.I):
            d = len(before) - m.end()
            if best is None or d < best[0]:
                best = (d, name, kind)
        m = re.search(pat, after or "", re.I)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), name, kind)
    return (best[1], best[2]) if best else None


def classify(url, title="", tool=False, near=("", "")):
    """(平台, 类别)；不是外部平台（mailto、追踪链接）返回 None。按网址认；只有 Canvas 里嵌的外部工具（tool=True）才按标题认，
    普通链接按标题认会认错（「W5 Studio」不是 Canvas Studio）；外部工具的标题认不出（「here」）再看链接前后的字。"""
    u = (url or "").strip()
    if not re.match(r"^https?://", u):
        return None
    host = urlparse(u).netloc.lower()
    if any(s in host for s in SKIP_HOSTS):
        return None
    for frag, name, kind in PLATFORMS:
        if frag in u.lower():
            return name, kind
    if tool:
        return _tool_by_title(title) or _tool_by_near(*(near or ("", "")))
    return ("其他网站：" + host, "内容") if host else None


A_RE = re.compile(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
IFRAME_RE = re.compile(r'<iframe\s[^>]*src="([^"]+)"[^>]*>', re.I)


def _plain(s):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _links(message):
    """(网址, 链接文字, 前面的字, 后面的字)。页面里嵌的 iframe（Padlet、Google 文档、视频）也算。"""
    msg = message or ""
    for m in A_RE.finditer(msg):
        yield (_html.unescape(m.group(1)), _plain(m.group(2)), _plain(msg[max(0, m.start() - 600):m.start()])[-300:],
               _plain(msg[m.end():m.end() + 300])[:120])
    for m in IFRAME_RE.finditer(msg):
        t = re.search(r'title="([^"]*)"', m.group(0), re.I)
        yield _html.unescape(m.group(1)), (_html.unescape(t.group(1)) if t else ""), "", ""


def _title_of(url, text, fallback=""):
    """链接文字像样就用它；只有「here」之类的，用网址里的名字（Padlet 的网址就是板名）或者所在公告、页面的标题。"""
    t = EXTERNAL_TAIL.sub("", text or "").strip()
    if t and not GENERIC.match(t) and t != url:
        return t[:120]
    seg = unquote(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])
    words = [w for w in re.split(r"[-_+]", seg) if w]
    if words and len(words[-1]) >= 10 and re.search(r"\d", words[-1]) and re.search(r"[a-z]", words[-1], re.I):
        words = words[:-1]  # Padlet 网址最后那串随机码
    wordlike = [w for w in words if re.fullmatch(r"[a-z]{1,15}|\d{1,4}", w, re.I)]
    if len(words) >= 3 and len(wordlike) >= 0.7 * len(words):  # Zoom 录像那种乱码 ID 不当名字
        return " ".join(words)[:120]
    return (fallback or t or "")[:120]


def norm(url):
    """比较用：去掉协议、结尾的斜杠、分享参数（usp=sharing）和 Canvas 的 display=borderless。"""
    p = urlparse((url or "").strip())
    q = "&".join(x for x in p.query.split("&") if x and x.split("=")[0] not in ("display", "usp", "utm_source", "utm_medium", "utm_campaign"))
    return p.netloc.lower() + p.path.rstrip("/") + ("?" + q if q else "")


def _entry(url, hit, title, source, week=None, from_module=False, lti=False):
    e = {"url": url, "platform": hit[0], "kind": hit[1], "title": (title or "")[:120], "source": source,
         "week": week, "from_module": from_module}
    if lti:  # 本校 Canvas 里嵌的外部工具：browse 先拿免登录的打开链接再开（lti_launch_path）
        e["lti"] = True
    return e


class _Links:
    """攒链接：同一个网址只留一条；本校 Canvas 里的页面不算外部平台，外部工具的跳转链接（/external_tools/）算。"""

    def __init__(self, canvas_host=None):
        self.own = urlparse(canvas_host or "").netloc.lower()
        self.out, self.seen = [], set()

    def add(self, url, text, source, tool=False, week=None, from_module=False, fallback="", near=("", ""), known_only=False):
        url = (url or "").strip()
        if not url:
            return
        p = urlparse(url)
        lti = False
        if self.own and p.netloc.lower() == self.own:
            if not (tool or CANVAS_TOOL.search(p.path)):
                return
            tool = lti = True
        k = norm(url)
        if k in self.seen:
            return
        hit = classify(url, EXTERNAL_TAIL.sub("", text or ""), tool=tool, near=near)
        if not hit or (known_only and hit[0].startswith("其他网站")):
            return
        if not tool and not hit[0].startswith("其他网站") and not p.path.strip("/"):
            return  # 平台的首页（嵌入框角上的「Made with Padlet」→ padlet.com?ref=embed）不是课程的东西
        self.seen.add(k)
        self.out.append(_entry(url, hit, _title_of(url, text, fallback), source, week=week, from_module=from_module, lti=lti))

    def from_html(self, html, source, fallback="", known_only=False):
        for url, text, before, after in _links(html):
            self.add(url, text, source, fallback=fallback, near=(before, after), known_only=known_only)


def collect_links(modules, announcements, course_id, canvas_host=None, since=None, week=None, assignments=None, now=None):
    """[{url, platform, kind, title, source, week, from_module}]：模块里的外部链接和外部工具、近期公告正文里的链接
    （since 以前的公告只看标题写到这周的）、快到期作业（3 天前到 4 周后）说明里认得出的平台。同一个网址只留一条。"""
    acc = _Links(canvas_host)
    for mod in modules or []:
        for it in mod.get("items") or []:
            wk = _week(mod.get("name"), it.get("title"))
            if it.get("type") == "ExternalUrl":
                acc.add(it.get("external_url"), it.get("title"), f"模块「{mod.get('name')}」", week=wk, from_module=True)
            elif it.get("type") == "ExternalTool":
                acc.add(it.get("html_url") or it.get("url"), it.get("title"), f"模块「{mod.get('name')}」里的外部工具", tool=True,
                        week=wk, from_module=True)
    for a in announcements or []:
        if a.get("context_code") != f"course_{course_id}":
            continue
        t = parse_ts(a.get("posted_at"))
        if since and t and t < since and not (week and week in weeks_in(a.get("title"))):
            continue
        acc.from_html(a.get("message"), f"公告「{(a.get('title') or '')[:40]}」", fallback=a.get("title") or "")
    for a in assignments or []:
        due = parse_ts(a.get("due_at"))
        if not (due and now and now - dt.timedelta(days=3) <= due <= now + dt.timedelta(days=28)):
            continue
        acc.from_html(a.get("description"), f"作业「{(a.get('name') or '')[:40]}」的说明", fallback=a.get("name") or "", known_only=True)
    return acc.out


# ---------------------------------------------------------------- 每个班各一个的链接：只留学生自己班的

CLASS_NO = re.compile(r"(?:class|tut(?:orial)?|seminar|workshop|lab|group|section|stream|cohort)[\s_\-#.]*0*(\d{1,3})(?!\d)", re.I)


def section_numbers(names):
    """学生在 Canvas 上的分班名里的班号：「…/LecTut/27」→ 27，「Tutorial 03 (Mon 10am)」→ 3，「T05」→ 5。
    只认名字最后那个数、跟在 class/tutorial 这类词后面的、T05 这种写法——「Semester 2 2026」里的 2 不算。"""
    out = set()
    for n in names or []:
        n = n or ""
        m = re.search(r"(?<![A-Za-z0-9])0*(\d{1,3})\s*\)?\s*$", n)
        if m:
            out.add(int(m.group(1)))
        out.update(int(x.group(1)) for x in CLASS_NO.finditer(n))
        out.update(int(x.group(1)) for x in re.finditer(r"\b(?:T|TUT|L|LAB|SEM|WS|CL)0*(\d{1,3})\b", n))
    return out


def per_class(links, numbers):
    """同一处来的 4 个以上按班编号的同一平台链接（Class 15、Class 27……各一个 Padlet）只留学生自己班的。返回 (留下的, 给 AI 的说明)。"""
    groups = {}
    for x in links:
        m = CLASS_NO.search(urlparse(x["url"]).path) or CLASS_NO.search(x.get("title") or "")
        if m:
            groups.setdefault((x["source"], x["platform"]), []).append((x, int(m.group(1))))
    drop, notes = set(), []
    for (src, plat), xs in groups.items():
        if len({n for _, n in xs}) < 4:
            continue
        mine = [x for x, n in xs if n in numbers]
        drop.update(norm(x["url"]) for x, n in xs if n not in numbers)
        if mine:
            notes.append(f"{src}里有 {len(xs)} 个按班分开的 {plat}，按学生在 Canvas 上的分班只留了「{mine[0]['title']}」")
        elif numbers:
            notes.append(f"{src}里有 {len(xs)} 个按班分开的 {plat}，学生的分班在里面没对上，一个都没列；打开那一处，按学生的上课时间认")
        else:
            notes.append(f"{src}里有 {len(xs)} 个按班分开的 {plat}，还不知道学生在哪个班，一个都没列（external 会去 Canvas 查分班）")
    return [x for x in links if norm(x["url"]) not in drop], notes


# ---------------------------------------------------------------- external 去 Canvas 查的那一份

SCAN_DAYS = 7
MAX_PAGES = 15
PAGE_HINT = re.compile(r"padlet|\bed\b|discussion|zoom|teams|\blinks?\b|platform|class|tutorial|seminar|workshop|roster|sign[- ]?(?:on|up)|"
                       r"schedule|timetable|calendar|welcome|start here|getting started|how to use|resources?\b|guide|overview", re.I)


def found_path(home, code):
    return os.path.join(home, "external", f"{code}.found.json")


def load_found(home, code):
    try:
        with open(found_path(home, code), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_found(home, code, found):
    os.makedirs(os.path.dirname(found_path(home, code)), exist_ok=True)
    with open(found_path(home, code), "w", encoding="utf-8", newline="\n") as f:
        json.dump(found, f, ensure_ascii=False, indent=1)


def scan_stale(home, code, now, days=SCAN_DAYS):
    return not _fresh(load_found(home, code).get("scanned_at"), now, days)


def scan_canvas(api, canvas_host, course_id, modules, week, now):
    """Canvas 上模块和公告之外的外部平台，只 GET：学生的分班、导航栏里的外部工具、课程首页、这周的课程页面和名字像入口的课程页面
    （Padlets、Zoom、Class……，最多 15 页）。一处查不到不挡别处；没有首页（404）不算错。返回要存进 <课>.found.json 的内容。"""
    found = {"scanned_at": now.isoformat(), "week": week, "sections": [], "links": [], "pages": [], "errors": []}

    def get(path):
        try:
            return api.get(path)
        except Exception as e:  # noqa: BLE001
            if getattr(e, "code", None) != 404:
                found["errors"].append(f"{path.split('?')[0].split('/api/v1/')[-1]}：{type(e).__name__} {getattr(e, 'code', '') or ''}".strip())
            return None

    course = get(f"/api/v1/courses/{course_id}?include[]=sections")
    found["sections"] = [s.get("name") for s in (course or {}).get("sections") or [] if isinstance(s, dict) and s.get("name")]
    acc = _Links(canvas_host)
    for t in get(f"/api/v1/courses/{course_id}/tabs") or []:
        if isinstance(t, dict) and t.get("type") == "external" and not t.get("hidden"):
            url = t.get("full_url") or ((canvas_host or "").rstrip("/") + (t.get("html_url") or ""))
            acc.add(url, t.get("label"), "课程导航栏", tool=True)
    pages = []
    front = get(f"/api/v1/courses/{course_id}/front_page")
    if isinstance(front, dict) and front.get("body"):
        pages.append(("课程首页", front))
    want = []
    for m in modules or []:
        mw = _week(m.get("name"))
        for it in m.get("items") or []:
            if it.get("type") != "Page" or not it.get("url"):
                continue
            w = mw or _week(it.get("title"))
            this = week is not None and w == week
            if this or (w is None and PAGE_HINT.search(it.get("title") or "")):
                want.append((0 if this else 1, it.get("title") or "", it["url"]))
    seen = set()
    for _, title, url in sorted(want, key=lambda x: x[0]):
        if url in seen or len(seen) >= MAX_PAGES:
            continue
        seen.add(url)
        p = get(url)
        if isinstance(p, dict):
            pages.append((title, p))
    for title, p in pages:
        found["pages"].append(title)
        acc.from_html(p.get("body"), "课程首页" if title == "课程首页" else f"课程页面「{title[:40]}」", fallback=title, known_only=True)
    found["links"], found["notes"] = per_class(acc.out, section_numbers(found["sections"]))
    return found


def scan_due(ctx, now):
    """这 7 天还没去 Canvas 查过的课（Moodle 不查；只放考试的站不查）。"""
    from cc_courses import lms_of, looks_like_exam_site
    if lms_of(ctx.cfg) == "moodle":
        return []
    return [c for c in ctx.cfg.get("courses") or []
            if not c.get("inactive") and not looks_like_exam_site(c.get("name")) and scan_stale(ctx.home, c["code"], now)]


def _scan_lock(ctx):
    from cc_store import FileLock
    return FileLock(ctx.P("logs", "external-scan.lock"))


def scan_running(ctx):
    if not os.path.exists(ctx.P("logs", "external-scan.lock")):  # 从没查过：别为了看一眼就生出一个锁文件
        return False
    lock = _scan_lock(ctx)
    if lock.acquire(blocking=False):
        lock.release()
        return False
    return True


def run_scans(ctx, now, week):
    """后台那一路：把该查的课挨个去 Canvas 查一遍（拿不到锁说明另一个在查，直接走）。返回 {课: 结果}。"""
    lock = _scan_lock(ctx)
    if not lock.acquire(blocking=False):
        return {}
    out = {}
    try:
        import cc_study
        mods = cc_study.load_modules(ctx)
        for c in scan_due(ctx, now):
            try:
                found = scan_canvas(ctx.api, ctx.cfg.get("canvas_host"), c.get("id"), mods.get(c["code"]), week, now)
                save_found(ctx.home, c["code"], found)
                out[c["code"]] = f"{len(found['pages'])} 个页面、{len(found['links'])} 个链接" + (f"，{len(found['errors'])} 处没查到" if found["errors"] else "")
            except Exception as e:  # noqa: BLE001  连不上 Canvas、登录过期：这门这次不查，下次开场再试
                out[c["code"]] = f"没查成：{type(e).__name__}"
    finally:
        lock.release()
    return out


def spawn_scans(ctx, now):
    """采集完顺手在后台去 Canvas 查外部平台，不等它（10-07：开场不该为它等）。返回 {started, due} 或 None（不用查、在查、开不了进程）。"""
    import subprocess
    import sys as _sys
    due = scan_due(ctx, now)
    if not due or scan_running(ctx):
        return None
    logdir = ctx.P("logs")
    os.makedirs(logdir, exist_ok=True)
    log = os.path.join(logdir, "external-scan.log")
    cmd = [_sys.executable, "-u", os.path.join(os.path.dirname(os.path.abspath(__file__)), "coach.py"), "external",
           "--scan-worker", "--home", ctx.home]
    log_handle = open(log, "a", encoding="utf-8")
    kw = {"stdin": subprocess.DEVNULL, "stdout": log_handle, "stderr": subprocess.STDOUT, "close_fds": True}
    if _sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    else:
        kw["start_new_session"] = True
    try:
        subprocess.Popen(cmd, **kw)
    except Exception:  # noqa: BLE001  宿主不让开子进程（沙盒、测试）：「还差」里那条 external 照样会补
        log_handle.close()
        try:
            if os.path.getsize(log) == 0:
                os.remove(log)
        except OSError:
            pass
        return None
    log_handle.close()
    return {"started": True, "due": [c["code"] for c in due]}


def all_links(home, code, raw_links):
    """导航栏和课程页面查到的在前，再接已采集的；同一个网址只留一条；按班分开的只留学生自己班的。返回 (清单, 给 AI 的说明)。"""
    found = load_found(home, code)
    out, seen = [], set()
    for x in (found.get("links") or []) + list(raw_links or []):
        k = norm(x.get("url"))
        if k and k not in seen:
            seen.add(k)
            out.append(x)
    kept, notes = per_class(out, section_numbers(found.get("sections")))
    return kept, list(dict.fromkeys((found.get("notes") or []) + notes))


def course_links(ctx, course, week, now, mods=None, anns=None):
    """一门课的保底清单（已采集的 + external 查到的）。返回 (清单, 给 AI 的说明)。"""
    import cc_learn
    if mods is None:
        import cc_study
        mods = cc_study.load_modules(ctx)
    if anns is None:
        anns = cc_learn.latest_raw(ctx.home, "announcements.json") or []
    cid = course.get("id")
    raw = collect_links(mods.get(course["code"]), anns, cid, ctx.cfg.get("canvas_host"), now - dt.timedelta(days=14), week=week,
                        assignments=cc_learn.latest_raw(ctx.home, f"assignments_{cid}.json") or [], now=now)
    return all_links(ctx.home, course["code"], raw)


# ---------------------------------------------------------------- 读过没有

def _path(home, code):
    return os.path.join(home, "external", f"{code}.json")


def load_records(home, code):
    try:
        with open(_path(home, code), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record(home, code, url, result, now, platform=None, kind=None, title=None, note=None):
    data = load_records(home, code)
    r = data.get(url) or {}
    r.update({"result": result, "last_try": now.isoformat()})
    if result == "ok":
        r["read_at"] = now.isoformat()
    for k, v in (("platform", platform), ("kind", kind), ("title", title), ("note", note)):
        if v:
            r[k] = v
    data[url] = r
    os.makedirs(os.path.dirname(_path(home, code)), exist_ok=True)
    with open(_path(home, code), "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return r


def record_of(recs, url):
    """同一个网址换了写法（带不带 ?usp=sharing）也认得出。"""
    if url in recs:
        return recs[url]
    k = norm(url)
    return next((r for u, r in recs.items() if norm(u) == k), None)


def key_of(code, url):
    return f"external:{code}:{hashlib.sha1(url.encode('utf-8')).hexdigest()[:10]}"


def _fresh(ts, now, days=FRESH_DAYS):
    t = parse_ts(ts)
    return bool(t) and now - t < dt.timedelta(days=days)


def gap_items(home, code, links, now, limit=5, week=None, weekly=True):
    """保底清单上该读还没读的（7 天内没读到过、也没试过）→ 给「还差 N 件」的条目。
    公告、作业说明、导航栏、课程页面里的都算；按周分模块的课，模块里的只算这周的（整学期都在的资源站不用每周读）；
    不按周分的课，模块里的只算「活的」平台（Ed、Padlet、Google 文档……）。"""
    recs = load_records(home, code)
    todo = []
    for x in links:
        if x["kind"] not in LISTED_KINDS:
            continue
        if x.get("from_module") and weekly and (week is None or x.get("week") != week):
            continue
        if x.get("from_module") and not weekly and not (x["kind"] == "通知作业" or x["platform"] in LIVING):
            continue
        r = record_of(recs, x["url"]) or {}
        if _fresh(r.get("read_at"), now) or _fresh(r.get("last_try"), now):
            continue
        todo.append({"key": key_of(code, x["url"]), "course": code,
                     "text": f"{code}：{x['platform']}「{x['title'] or x['url']}」还没读过（{x['source']}）",
                     "cmd": f"browse {x['url']} --course {code}"})
    if len(todo) > limit:
        rest = len(todo) - limit
        todo = todo[:limit]
        todo[-1] = dict(todo[-1], text=todo[-1]["text"] + f"；这门课另外还有 {rest} 个，external {code} 看全部")
    return todo


def situation_lines(home, code, now):
    """周报课程卡上的情况句（学生看的）：可能有作业和截止的平台，这周试过但没读到。只说情况，不派活。"""
    lines, done = [], set()
    for url, r in load_records(home, code).items():
        name = r.get("platform") or ""
        if r.get("kind") != "通知作业" or name in done:
            continue
        if r.get("result") != "ok" and _fresh(r.get("last_try"), now) and not _fresh(r.get("read_at"), now):
            done.add(name)
            lines.append(f"这次没读到 {name}，{name} 上这周有没有新作业还不确定，下次会再试。")
    return lines


# ---------------------------------------------------------------- browse：用本工具自己那份登录浏览器只读打开一个网页

BOT_WORDS = ("verify you are human", "verifying you are human", "are you a robot", "captcha", "unusual traffic", "checking your browser",
             "checking if the site connection is secure", "just a moment", "请完成安全验证", "人机验证", "确认您是真人", "验证您是否是真人")
BOT_TITLES = ("请稍候", "请稍等", "attention required")   # Cloudflare 等待页的标题（浏览器是中文界面时是「请稍候…」）
LOGIN_HOST = re.compile(r"(^|\.)(login|signin|sso|idp|auth|okta|accounts)\.|microsoftonline\.com|shibboleth|/cas/login|/saml", re.I)
LOGIN_PATH = re.compile(r"/(?:auth/)?(?:log[-_]?in|sign[-_]?in)\b", re.I)
# Cloudflare 的验证页。不用 reCAPTCHA 的框、/cdn-cgi/challenge-platform/ 脚本来认：很多正常页面也挂着
CHALLENGE_SEL = "#challenge-form, #challenge-running, #cf-challenge-running"
TURNSTILE_SEL = "iframe[src*='challenges.cloudflare.com']"   # 只有页面上几乎没别的字时才算验证页


def judge(start_url, final_url, title, text, has_password, challenge=False):
    """这次打开算什么：ok / login（被带去登录）/ bot（人机验证、Cloudflare 等待页：停）。"""
    low = f"{title or ''}\n{(text or '')[:4000]}".lower()
    if challenge or any(w in low for w in BOT_WORDS) or any(w in (title or "").lower() for w in BOT_TITLES):
        return "bot"
    s, f = urlparse(start_url or ""), urlparse(final_url or "")
    moved = f.netloc.lower() != s.netloc.lower()
    if has_password or (moved and LOGIN_HOST.search(final_url or "")) or LOGIN_HOST.search(f.netloc or ""):
        return "login"
    if LOGIN_PATH.search(f.path or "") and not LOGIN_PATH.search(s.path or ""):
        return "login"  # 同一个网站的登录页（padlet.com/auth/login）
    return "ok"


GDOC = re.compile(r"https://docs\.google\.com/(document|presentation|spreadsheets)/d/([\w-]+)")


def export_url(url):
    """Google 文档、幻灯片、表格的正文画在页面上，网页里取不到文字：改走它们自带的「导出成纯文本」。"""
    m = GDOC.match(url or "")
    if not m:
        return None
    kind, did = m.groups()
    return {"document": f"https://docs.google.com/document/d/{did}/export?format=txt",
            "presentation": f"https://docs.google.com/presentation/d/{did}/export/txt",
            "spreadsheets": f"https://docs.google.com/spreadsheets/d/{did}/export?format=csv"}[kind]


PADLET_HOST = re.compile(r"(^|\.)padlet\.(com|org)$", re.I)
PADLET_DATA = re.compile(r"/api/\d+/(wishes|wall_sections|padlet_starting_state)\b")
UPLOAD_HOST = "padletusercontent.com"


def _html_text(s):
    """帖子正文（HTML）→ 纯文字：链接写成「文字（网址）」，换行和列表留着。"""
    def a(m):
        href, t = _html.unescape(m.group(1)).strip(), _plain(m.group(2))
        if not href or (t and href in t):
            return t
        return f"{t}（{href}）" if t and t != href else href
    s = A_RE.sub(a, s or "")
    s = re.sub(r"<li[^>]*>", "\n- ", s, flags=re.I)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</h\d>|</tr>", "\n", s, flags=re.I)
    s = _html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    out = []
    for x in (re.sub(r"[ \t]+", " ", x).strip() for x in s.split("\n")):
        if x or (out and out[-1]):
            out.append(x)
    return "\n".join(out).strip()


def _post_lines(a):
    subj = (a.get("subject") or "").strip()   # 不用 headline：没标题时它是界面语言的占位字（「无内容」）
    body = _html_text(a.get("body"))
    day = str(a.get("published_at") or a.get("created_at") or "")[:10]   # AI 靠它分清哪些是这周新贴的
    out = [("· " + subj if subj else "·") + (f"（{day} 贴）" if day else "")]
    out += [f"  {x}" if x else "" for x in body.split("\n")] if body else []
    att = (a.get("attachment") or "").strip()
    link = a.get("attachment_link") or {}
    name = unquote(urlparse(att).path.rsplit("/", 1)[-1]) if att else ""
    if att and (link.get("content_category") == "image" or re.search(r"\.(png|jpe?g|gif|webp|svg|heic)$", name, re.I)):
        out.append(f"  （图片{'：' + name if UPLOAD_HOST in att else ''}）")
    elif att and UPLOAD_HOST in att:
        out.append(f"  附件：{name} {att}")
    elif att and att not in body:
        t = (link.get("title") or "").strip()
        out.append(f"  链接：{t + ' ' if t and t != subj else ''}{att}")
        desc = (link.get("description") or "").strip()
        if desc and desc not in body:
            out.append(f"  （{desc[:200]}）")
    return out


def padlet_text(store):
    """Padlet 网页取下来的整板数据 [(网址, JSON)] → 按栏列出全部帖子；一条帖子都没取到返回 None。
    栏按 Padlet 上从左到右；栏里的帖子按板子的排序设置（手动排的，sort_index 大的在上面——对过网页）。"""
    secs, posts, wall = {}, {}, {}
    for u, d in store:
        if not isinstance(d, dict):
            continue
        path = urlparse(u).path
        if "padlet_starting_state" in path:
            wall = d.get("wall") or wall
            continue
        for x in d.get("data") if isinstance(d.get("data"), list) else []:
            a = (x or {}).get("attributes") or {}
            if a.get("id") is None:
                continue
            if "/wall_sections" in path:
                secs[a["id"]] = a
            elif "/wishes" in path and a.get("published") is not False and not a.get("is_content_hidden"):
                posts[a["id"]] = a
    if not posts:
        return None
    sort_by = str(((wall or {}).get("wish_arrangement") or {}).get("sort_by") or "manual")
    if "newest" in sort_by or "oldest" in sort_by:
        key, rev = (lambda a: a.get("published_at") or a.get("created_at") or ""), "newest" in sort_by
    elif "subject" in sort_by or "alpha" in sort_by:
        key, rev = (lambda a: (a.get("subject") or "").lower()), False
    else:
        key, rev = (lambda a: a.get("sort_index") or 0), True
    by = {}
    for a in posts.values():
        by.setdefault(a.get("wall_section_id"), []).append(a)
    groups = [((s.get("title") or "（没有栏名）").strip(), by.pop(s.get("id"), []))
              for s in sorted(secs.values(), key=lambda s: s.get("sort_index") or 0)]
    if by:
        groups.append(("（不在任何栏里的帖子）" if secs else "", [a for v in by.values() for a in v]))
    lines = [f"（Padlet 整板：{len(secs)} 栏、{len(posts)} 条帖子；按 Padlet 上的顺序，一栏一栏从左到右）"]
    for title, ps in groups:
        lines.append("")
        if title:
            lines.append(f"## {title}")
        if not ps:
            lines.append("（这一栏没有帖子）")
        for a in sorted(ps, key=key, reverse=rev):
            lines += _post_lines(a)
    return "\n".join(lines)


def _padlet_rest(page, store, limit=30):
    """帖子是分页取的：网页没自己取完的，在同一个网页里接着取（只 GET）。取全了返回 True。"""
    for _ in range(limit):
        wishes = [(u, d) for u, d in store if "/wishes" in urlparse(u).path and isinstance(d, dict)]
        have = {parse_qs(urlparse(u).query).get("page_start", [""])[0] for u, _ in wishes}
        todo = [(u, (d.get("meta") or {}).get("next")) for u, d in wishes]
        todo = [(u, n) for u, n in todo if n and n not in have]
        if not todo:
            return True
        u, n = todo[0]
        p = urlparse(u)
        q = {k: v[0] for k, v in parse_qs(p.query, keep_blank_values=True).items()}
        q["page_start"] = n
        nu = urlunparse(p._replace(query=urlencode(q)))
        try:
            body = page.evaluate("async u => { const r = await fetch(u, {credentials: 'include'}); return r.ok ? await r.text() : ''; }", nu)
            store.append((nu, json.loads(body)))
        except Exception:  # noqa: BLE001  取不到就停，文字里注明没取全
            return False
    return False


def lti_launch_path(url, canvas_host, lti=False):
    """本校 Canvas 里嵌的外部工具（Zoom、阅读清单、录播、Ed……）：给出 sessionless_launch 的 API 路径。
    凭 token 或浏览器登录都拿得到一次性的打开链接，不用浏览器另外登学校账号（10-07 实测：Zoom 会议列表、Leganto 阅读清单都读到了）。
    模块里的外部工具条目（/modules/items/<id>）要 lti=True 才算。不是这类链接、不是本校 Canvas，返回 None。"""
    p = urlparse(url or "")
    if not canvas_host or p.netloc.lower() != urlparse(canvas_host).netloc.lower():
        return None
    m = re.search(r"/courses/(\d+)/external_tools/(\d+)", p.path)
    if m:
        return f"/api/v1/courses/{m.group(1)}/external_tools/sessionless_launch?id={m.group(2)}"
    m = re.search(r"/courses/(\d+)/modules/items/(\d+)", p.path)
    if m and lti:
        return f"/api/v1/courses/{m.group(1)}/external_tools/sessionless_launch?launch_type=module_item&module_item_id={m.group(2)}"
    return None


def session_open_path(url, canvas_host):
    """本校 Canvas 自己的页面（课程页面、作业、讨论……）：token 方式用 /login/session_token 换一次浏览器会话再开，
    和浏览器登录方式读到的一样（10-07 实测：MECO6941 的课程页面和页面里嵌的 AI 助手都读到了）。不是本校 Canvas 返回 None。"""
    p = urlparse(url or "")
    if not canvas_host or p.netloc.lower() != urlparse(canvas_host).netloc.lower():
        return None
    return "/login/session_token?" + urlencode({"return_to": url})


SECRET_PARAMS = ("verifier", "session_token")  # 打开链接里的一次性凭证


def scrub(text, open_url):
    """把打开链接里的凭证从文字里去掉（页面文字、报错原话都可能带着整条链接）。"""
    q = parse_qs(urlparse(open_url or "").query)
    for v in (v for k in SECRET_PARAMS for v in q.get(k, []) if v):
        text = (text or "").replace(v, "…")
    return text


def open_link(api, url, canvas_host, lti=False):
    """读本校 Canvas 上的网址之前，先换一个不用另外登录的打开链接，返回 (open_url, note)：
    嵌的外部工具走 sessionless_launch（两种方式都一样）；Canvas 自己的页面，token 方式走 session_token，
    浏览器登录方式本来就带着会话，不用换。打开链接是一次性的登录凭证：只交给 browse，不打印、不落盘。"""
    try:
        launch = lti_launch_path(url, canvas_host, lti=lti)
        if launch:
            return (api.get(launch) or {}).get("url"), None
        path = session_open_path(url, canvas_host)
        if path and getattr(api, "mode", None) != "session":
            _, body = api.fetch(api.host + path)
            body = body[9:] if body[:9] == b"while(1);" else body
            return (json.loads(body.decode("utf-8") or "null") or {}).get("session_url"), None
    except Exception as e:  # noqa: BLE001  拿不到就照原网址开（多半会被带去登录页）
        return None, f"拿免登录打开链接没成（{type(e).__name__}）"
    return None, None


def page_path(home, url):
    return os.path.join(home, "external", "pages", hashlib.sha1(url.encode("utf-8")).hexdigest()[:12] + ".txt")


def browse(home, url, wait=20, open_url=None):
    """{result, final_url, title, chars, path, links}。只 GET、只读：不填表、不点按钮。
    页面里嵌的框（Canvas 里的外部工具就是这样嵌的）的文字一起存；Padlet 换成它自己取下来的整板数据；
    页面上折叠着的内容（课程说明的评估表这类）也一起读。
    open_url：Canvas 给的一次性打开链接（open_link 拿的）。它就是一次登录凭证：只用来打开，不打印、不落盘，
    记录和页面文字都按原来的 url 存，最后到达的地址去掉参数。"""
    import cc_outline
    import cc_session
    sync_playwright = cc_session._sync_playwright()
    padlet = bool(PADLET_HOST.search(urlparse(url).netloc or ""))
    store = []
    with sync_playwright() as pw:
        ctx = cc_session._launch(pw, home, headless=True)
        try:
            cc_session._restore_cookies(ctx, home)
            page = ctx.new_page()
            if padlet:
                def keep(resp):
                    if PADLET_DATA.search(urlparse(resp.url).path):
                        try:
                            store.append((resp.url, resp.json()))
                        except Exception:  # noqa: BLE001  不是 JSON（出错页）就算了
                            pass
                page.on("response", keep)
            page.goto(open_url or url, wait_until="domcontentloaded", timeout=wait * 1000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000 if open_url else 6000)
            except Exception:  # noqa: BLE001  一直有请求的页面等不到安静，读当前内容就行
                pass
            title = page.title()
            text = page.inner_text("body") if page.query_selector("body") else ""
            full = "\n".join(cc_outline.text_lines(page.content()))
            if len(full) > len(text) * 1.3 + 200:  # 折叠着的（details、手风琴）看不见但在网页里：10-07 课程说明的评估表就是这样漏的
                text = full
            has_pw = bool(page.query_selector("input[type=password]"))
            challenge = bool(page.query_selector(CHALLENGE_SEL)) or (bool(page.query_selector(TURNSTILE_SEL)) and len(text.strip()) < 600)
            links = page.eval_on_selector_all("a[href]", "els => els.slice(0, 400).map(e => [e.href, (e.innerText || '').trim().slice(0, 120)])")
            final = page.url
            for fr in page.frames[1:6]:
                try:
                    t = fr.inner_text("body", timeout=3000).strip()
                except Exception:  # noqa: BLE001  框还没加载好、跨站拿不到：跳过
                    continue
                if len(t) > 40:
                    text += f"\n\n（页面里嵌的「{urlparse(fr.url).netloc or fr.name}」）\n{t[:20000]}"
            if padlet and store:
                whole = _padlet_rest(page, store)
                board = padlet_text(store)
                if board:
                    text = board + ("" if whole else "\n\n（帖子是分页取的，后面还有没取到的）")
            exp = export_url(url)
            if exp and not has_pw:
                try:
                    resp = ctx.request.get(exp, timeout=wait * 1000)
                    body = resp.text() if resp.ok else ""
                    if len(body.strip()) > len((text or "").strip()):
                        text = body
                except Exception:  # noqa: BLE001  导出不了（不公开、被关了导出）就用网页上能取到的
                    pass
        finally:
            cc_session._save_cookies(ctx, home)  # 学校登录、网站登录在用的时候会续期：存下最新的，学生就不用再登
            ctx.close()
    if open_url:  # 经一次性链接打开的：到达地址里可能还带着凭证，只留域名和路径；页面里回显凭证的链接不要
        f = urlparse(final or "")
        final = f"{f.scheme}://{f.netloc}{f.path}" if f.netloc else ""
        links = [x for x in links if scrub(x[0], open_url) == x[0]]
        text, title = scrub(text, open_url), scrub(title, open_url)
    result = judge(url, final, title, text, has_pw, challenge)
    note = None
    if result == "ok" and len((text or "").strip()) < 40:  # 10-07：APA 网站打开是空白页，记成了「读到了，0 字」
        result, note = "error", "打开是空白页（几乎没有文字）：可能内容要等脚本加载，或者这个网站不让程序打开"
    path = None
    if result == "ok":
        path = page_path(home, url)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"网址：{url}\n最后到达：{final}\n标题：{title}\n\n{text}")
    return {"result": result, "final_url": final, "title": title, "chars": len(text or ""), "path": path, "links": links[:200], "note": note}
