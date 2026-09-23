"""课程：Canvas 课程对象 → 短代码、哪些站点不是课、按代码找课、站内信归到哪门课。"""
import re


TERM_RE = re.compile(r"(?i)^(s|sem|semester|t|term|hs|ws|sp|su|fa|wi|aut|spr|sum|win)\d{1,4}$")
LMS_LABELS = {"canvas": "Canvas", "moodle": "Moodle"}


def lms_of(cfg):
    """这个档案连的是哪种学习平台。老档案没有这个键，就是 Canvas。"""
    v = str((cfg or {}).get("lms") or "canvas").lower()
    return v if v in LMS_LABELS else "canvas"


def lms_label(cfg):
    return LMS_LABELS[lms_of(cfg)]


def has_course_code(cc):
    """看着像正规课程代码：字母 2–6 位接数字，且不是学期代码（AUT2026、SEM2 这种）。"""
    m = re.search(r"([A-Za-z]{2,6})[ -]?(\d{2,5}[A-Za-z]?)", (cc or "").strip())
    return bool(m) and not TERM_RE.match(m.group(1) + m.group(2))


def course_code_of(course):
    """从 Canvas 课程对象或 course_code 字符串得到短代码。宽容：任何学校的写法都不丢课。"""
    cc = course.get("course_code") if isinstance(course, dict) else course
    cc = (cc or "").strip()
    m = re.search(r"([A-Za-z]{2,6})[ -]?(\d{2,5}[A-Za-z]?)", cc)
    if m and not TERM_RE.match(m.group(1) + m.group(2)):
        return (m.group(1) + m.group(2)).upper()
    # 「2023_ARIN1001_S1C」里的正规代码在课名里；「31251_AUT2026」这种才真的只有数字（S38）
    name = course.get("name") if isinstance(course, dict) else None
    m2 = re.search(r"([A-Za-z]{2,6})[ -]?(\d{2,5}[A-Za-z]?)", name or "")
    if m2 and not TERM_RE.match(m2.group(1) + m2.group(2)):
        return (m2.group(1) + m2.group(2)).upper()
    lead = re.match(r"^(\d{4,8})(?:[_\- ]|$)", cc)
    if lead:
        return lead.group(1)
    if m:
        return (m.group(1) + m.group(2)).upper()
    slug = re.sub(r"[^A-Za-z0-9]", "", cc).upper()
    if slug:
        return slug[:12]
    cid = course.get("id") if isinstance(course, dict) else None
    return f"C{cid}" if cid else "COURSE"


NON_COURSE_RE = re.compile(r"(?i)orientation|sandbox|template|student hub|byod|test support|support site|help ?desk|资源中心|迎新")
SOFT_NON_COURSE_RE = re.compile(r"(?i)library|literacy|training|engagement|writing centre|writing center")


def looks_like_non_course(name, code=None):
    """图书馆、迎新、BYOD 测试站这类不是课。

    S38：有正规课程代码的一律当课。名字里带 Literacy / Engagement / Training / Library 的真课程
    （EDUC6010、MKTG6020、NURS5001、INFS5001）以前会被这张词表误杀。
    代价是「Orientation 2026 / ORI2026」这种带课程码的站点会被留下：多一张空课程卡，
    比漏掉一门真课强得多。
    """
    s = name or ""
    if has_course_code(code if code is not None else s):
        return False
    if NON_COURSE_RE.search(s):
        return True
    if SOFT_NON_COURSE_RE.search(s) and not has_course_code(s):
        return True
    return bool(re.match(r"^\d{4}_", s))


def in_current_term(course, today, before=14, after=7):
    """这门课的学期是不是当前的：开学前 14 天到结课后 7 天算在读。

    Canvas 的 enrollment_state=active 并不代表「这学期在上」——悉大的旧选课记录一直是 active，
    两三年前的课照样回来（真机实测：ARIN1001 2023、ECON1001 2022）。只能靠学期日期筛。
    """
    import datetime as _dt

    from cc_time import parse_date
    term = (course.get("term") or {}) if isinstance(course, dict) else {}
    s, e = parse_date(term.get("start_at")), parse_date(term.get("end_at"))
    if s is None and e is None:  # 「Default Term」没有日期：退回课程自己的起止（真机实测：LIBR1000 挂在 Default Term）
        s, e = parse_date(course.get("start_at")), parse_date(course.get("end_at"))
        if s is None and e is None:
            return True  # 一个日期都查不到：判断不了，就当在读（宁可多一门，不漏报）
        if e is None:
            return s is not None and today - _dt.timedelta(days=300) <= s <= today + _dt.timedelta(days=before)
    return (s is None or s <= today + _dt.timedelta(days=before)) and (e is None or e >= today - _dt.timedelta(days=after))


def course_pairs(cfg, include_inactive=True):
    """(课程 id, 代码) 列表。include_inactive=False 时跳过已结课/已退课的（S02）：数据留着，不再去拉。"""
    return [(c["id"], c["code"]) for c in cfg.get("courses") or [] if include_inactive or not c.get("inactive")]


def course_codes(cfg):
    return [c["code"] for c in cfg.get("courses") or []]


def course_by_code(cfg, code):
    code = (code or "").upper()
    for c in cfg.get("courses") or []:
        if c["code"].upper() == code or c["code"].upper().endswith(code):
            return c
    return None


def course_of_context(name, courses):
    for cid, code in courses:
        if (name or "").startswith(code):
            return code
    return None
