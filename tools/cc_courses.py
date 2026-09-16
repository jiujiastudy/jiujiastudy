"""课程：Canvas 课程对象 → 短代码、哪些站点不是课、按代码找课、站内信归到哪门课。"""
import re


def course_code_of(course):
    """从 Canvas 课程对象或 course_code 字符串得到短代码。宽容：任何学校的写法都不丢课。"""
    cc = course.get("course_code") if isinstance(course, dict) else course
    cc = (cc or "").strip()
    m = re.search(r"([A-Za-z]{2,6})[ -]?(\d{2,5}[A-Za-z]?)", cc)
    if m:
        return (m.group(1) + m.group(2)).upper()
    slug = re.sub(r"[^A-Za-z0-9]", "", cc).upper()
    if slug:
        return slug[:12]
    cid = course.get("id") if isinstance(course, dict) else None
    return f"C{cid}" if cid else "COURSE"


def looks_like_non_course(name):
    """图书馆、迎新、BYOD 测试站、学院公告站这类不是课；course_code 以四位年份加下划线开头的多半是通用站点。"""
    s = name or ""
    return bool(re.search(r"(?i)library|literacy|orientation|sandbox|template|training|student hub|byod|test support|engagement|support site", s)
                or re.match(r"^\d{4}_", s))


def course_pairs(cfg):
    return [(c["id"], c["code"]) for c in cfg.get("courses") or []]


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
