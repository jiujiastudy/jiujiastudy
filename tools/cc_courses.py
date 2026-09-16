"""课程：Canvas 课程对象 → 短代码、哪些站点不是课、按代码找课、站内信归到哪门课。"""
import re


TERM_RE = re.compile(r"(?i)^(s|sem|semester|t|term|hs|ws|sp|su|fa|wi|aut|spr|sum|win)\d{1,4}$")


def has_course_code(cc):
    """看着像正规课程代码：字母 2–6 位接数字，且不是学期代码（AUT2026、SEM2 这种）。"""
    m = re.search(r"([A-Za-z]{2,6})[ -]?(\d{2,5}[A-Za-z]?)", (cc or "").strip())
    return bool(m) and not TERM_RE.match(m.group(1) + m.group(2))


def course_code_of(course):
    """从 Canvas 课程对象或 course_code 字符串得到短代码。宽容：任何学校的写法都不丢课。"""
    cc = course.get("course_code") if isinstance(course, dict) else course
    cc = (cc or "").strip()
    lead = re.match(r"^(\d{4,8})(?:[_\- ]|$)", cc)  # 31251_AUT2026 这种：取开头的数字，别把学期当代码（S38）
    if lead:
        return lead.group(1)
    m = re.search(r"([A-Za-z]{2,6})[ -]?(\d{2,5}[A-Za-z]?)", cc)
    if m and not TERM_RE.match((m.group(1) + m.group(2))):
        return (m.group(1) + m.group(2)).upper()
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
