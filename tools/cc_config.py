"""配置与状态：config.json / state.json 的默认值、版本适配（v1 → v3）和一次命令运行的上下文 Ctx。

config.json（v3）是唯一事实源：学校域名、时区、学期、课程、用户。没有任何学校的默认值。
state.json 只放机器状态：时间戳、待确认、决定、手动 deadline、心情信号、当前计划。
路径在 cc_paths.py，JSON 读写在 cc_store.py，课程查找在 cc_courses.py。
"""
import datetime as dt
import glob
import json
import os
import re
import sys

import brand
from cc_courses import course_by_code, lms_of
from cc_paths import coach_cmd, fwd, home_dir, rel_home, root_dir, safe_name
from cc_store import jload, jsave

SCHEMA_VERSION = 3
MIN_SCHEMA = 2
MACHINE_COURSE_KEYS = {"id", "name", "my_section", "last_fetch", "max_assignment_updated_at",
                       "latest_announcement_at", "counts", "api_notes", "pending_user_confirmation"}
V3_DEFAULTS = {
    "study": {"minutes": {"Page": 20, "File": 40, "Video": 45, "Quiz": 30, "Discussion": 30, "ExternalUrl": 20, "Assignment": 90},
              "max_should": 2, "lead_days": {"heavy": 2, "light": 1}},
    "root": None,
    "materials": {"auto_download": True, "max_mb": 50, "per_run": 30},
    "agent": {"kind": None},
    "tz_labels": {},
    "api_notes": {},
    "extra_sites": [],
    "notes": [],
}


class CoachError(Exception):
    """用户可读的错误；code 是进程退出码（2 = 阻塞，3 = 数据版本太老）。"""

    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def version_of(obj):
    try:
        return int((obj or {}).get("schema_version") or 1)
    except (TypeError, ValueError):
        return 1


def missing_config_message(home):
    return (f"还没有档案：{os.path.join(home, 'config.json')} 不存在。\n"
            f"先跑：{coach_cmd()} doctor --detect-site   （在浏览器记录里认学校的 Canvas 域名）\n"
            f"或：  {coach_cmd()} doctor --host <学校 Canvas 登录页网址>\n"
            f"档案在别的文件夹就先设环境变量 {brand.env_name('HOME')}。")


def minimal_state():
    return {"schema_version": SCHEMA_VERSION, "last_check": None, "last_fetch": None, "last_record": None,
            "last_seen": None, "last_done": None, "counters": {"pending": 0}, "courses": {},
            "pending_confirmations": [], "decisions": [], "mood": [], "manual_deadlines": [],
            "deadline_notes": {}, "locked_materials": [], "current_plan": None, "daily_report": {}}


def _deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def effective(cfg):
    """补上版本默认值（不落盘）。v2 档案沿用旧行为：课件自动下载。"""
    cfg = cfg or {}
    merged = _deep_merge(V3_DEFAULTS, cfg)
    if version_of(cfg) < 3 and "materials" not in cfg:
        merged["materials"] = {"auto_download": True, "max_mb": 50}
    if "courses" not in merged and "my_courses" in merged:
        merged["courses"] = merged["my_courses"]
    return merged


def parse_value(s):
    """config set 的值：JSON 能解析就当 JSON，否则当字符串。"""
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return s


def materials_ai(cfg, code):
    """这门课的课件要不要提取文字给 AI 读：默认不提取，按课打开。原件照下，不受这个开关影响。"""
    return bool((course_by_code(cfg or {}, code) or {}).get("materials_ai"))


def course_option(ctx, code, materials_ai_value=None):
    """config course <CODE> [--materials-ai on|off]：看 / 改这门课的开关。只管课件文字交不交给 AI。"""
    course = course_by_code(ctx.raw_cfg, code)
    if course is None:
        raise CoachError(f"config.json 里没有课程 {code}：先看 {coach_cmd()} config get courses", 2)
    if materials_ai_value is not None:
        course["materials_ai"] = materials_ai_value == "on"
        ctx.save_config()
    on = bool(course.get("materials_ai"))
    state = "交给 AI 读（提取到 text/）" if on else "不交给 AI（只下原件，不提取文字）"
    return {"course": course.get("code"), "materials_ai": on, "message": f"{course.get('code')}：课件文字{state}"}


def detect_exam_prep(home):
    for pj in sorted(glob.glob(os.path.join(home, "courses", "*", "exam_prep", "plan.json")) + glob.glob(os.path.join(root_dir(), "*", "产出", "exam_prep", "plan.json"))):
        code = os.path.basename(os.path.dirname(os.path.dirname(pj)))
        plan = jload(pj, {}) or {}
        days = [d.get("date") for d in plan.get("days") or [] if d.get("date")]
        until = (plan.get("exam") or {}).get("date") or (max(days) if days else None)
        return {"course": code, "dir": f"courses/{code}/exam_prep", "until": until}
    return None


def adapt_v1(cfg1, state1, home, today):
    """把 v1 的 config/state 转成新结构（内存里），叙事笔记单独交出去。幂等。"""
    from cc_time import machine_zone
    cfg1 = cfg1 or {}
    state1 = state1 or {}
    if version_of(cfg1) >= 2 and version_of(state1) >= 2:
        return cfg1, state1, {}
    term1 = state1.get("term") or {}
    courses1 = state1.get("courses") or {}
    courses = []
    for c in cfg1.get("courses") or cfg1.get("my_courses") or []:
        code = c["code"]
        s = courses1.get(code) or {}
        courses.append({"id": c["id"], "code": code, "name": c.get("name"),
                        "section": c.get("section") or s.get("my_section"), "weekday": c.get("weekday")})
    api_notes = cfg1.get("api_notes") or next((s.get("api_notes") for s in courses1.values() if s.get("api_notes")), {}) or {}
    exam_prep = cfg1.get("exam_prep") or detect_exam_prep(home)
    extra = list(cfg1.get("extra_sites") or [])
    watch = state1.get("watch") or {}
    if not extra and watch:
        for_course = (exam_prep or {}).get("course")
        if watch.get("exam_site_course"):
            extra.append({"kind": "exam_site", "course_id": watch["exam_site_course"],
                          "label": f"考试站点 {watch['exam_site_course']}", "for_course": for_course, "until": watch.get("until")})
        b = watch.get("byod") or {}
        if b.get("course") and b.get("assignment"):
            extra.append({"kind": "byod_quiz", "course_id": b["course"], "assignment_id": b["assignment"],
                          "label": f"练习测验 {b['assignment']}", "for_course": for_course, "until": watch.get("until")})
    term = cfg1.get("term") if isinstance(cfg1.get("term"), dict) else {
        "name": term1.get("name"), "start": cfg1.get("term_start"), "end": cfg1.get("term_end"),
        "week1_monday": term1.get("week1_monday") or cfg1.get("term_start"), "break": term1.get("break"),
        "week_source": "config"}
    tz = cfg1.get("course_tz") or machine_zone() or "UTC"
    notes = [x for x in [cfg1.get("user_tz_note")] if x] + list(cfg1.get("notes") or [])
    cfg2 = {"schema_version": SCHEMA_VERSION, "canvas_host": cfg1.get("canvas_host"),
            "course_tz": tz, "user_tz": cfg1.get("user_tz") or "auto", "tz_labels": cfg1.get("tz_labels") or {},
            "term": term, "user": cfg1.get("user") or state1.get("user") or {},
            "courses": courses, "extra_sites": extra, "exam_prep": exam_prep, "api_notes": api_notes, "notes": notes,
            "materials": {"auto_download": True, "max_mb": 50}, "agent": {"kind": None}}

    counter = 0
    pending = list(state1.get("pending_confirmations") or [])
    decisions = list(state1.get("decisions") or [])
    narratives = {}
    courses2 = {}
    for code, s in courses1.items():
        courses2[code] = {k: s.get(k) for k in ("last_fetch", "max_assignment_updated_at", "latest_announcement_at", "counts")
                          if s.get(k) is not None}
        for p in s.get("pending_user_confirmation") or []:
            counter += 1
            done = ("✅" in p) or p.startswith("已确认") or ("已确认" in p[:8])
            pending.append({"id": f"pc-{counter:04d}", "course": code, "text": p.replace("✅", "").strip(" ：:"),
                            "first_asked": today, "last_asked": today, "times_asked": 1, "blocks": None,
                            "ask_en": None, "ask_zh": None, "resolved": today if done else None,
                            "resolution": p if done else None})
        nar = {k: v for k, v in s.items() if k not in MACHINE_COURSE_KEYS}
        if nar:
            narratives[code] = nar
    for h in state1.get("first_step_hints") or []:
        m = h.get("match") or ""
        code = next((c["code"] for c in courses if m.startswith(c["code"])), "_misc")
        narratives.setdefault(code, {}).setdefault("first_step_hints", []).append(h)

    def walk(v, code):
        if isinstance(v, str):
            if "不再提起" in v and not any(d.get("text") == v for d in decisions):
                m = re.search(r"\d{4}-\d{2}-\d{2}", v)
                decisions.append({"text": v, "course": None if code == "_misc" else code,
                                  "date": m.group(0) if m else today, "do_not_raise": True})
        elif isinstance(v, dict):
            for x in v.values():
                walk(x, code)
        elif isinstance(v, list):
            for x in v:
                walk(x, code)
    for code, nar in narratives.items():
        walk(nar, code)

    dn = {k: (v[:120] if isinstance(v, str) else v) for k, v in (state1.get("deadline_notes") or {}).items()}
    dr = dict(state1.get("daily_report") or {})
    if dr.get("last_report") and os.path.isabs(str(dr["last_report"])):
        dr["last_report"] = rel_home(home, dr["last_report"])
    state2 = minimal_state()
    state2.update({"last_check": state1.get("last_check"), "last_fetch": state1.get("last_fetch"),
                   "last_record": state1.get("last_record"), "counters": {"pending": max(counter, len(pending))},
                   "courses": courses2, "pending_confirmations": pending, "decisions": decisions,
                   "manual_deadlines": state1.get("manual_deadlines") or [], "deadline_notes": dn,
                   "locked_materials": state1.get("locked_materials") or [], "current_plan": state1.get("current_plan"),
                   "daily_report": dr})
    return cfg2, state2, narratives


def upgrade_v2(cfg2):
    """v2 → v3：只补键，不改值。"""
    cfg = dict(cfg2)
    cfg["schema_version"] = SCHEMA_VERSION
    if "courses" not in cfg and "my_courses" in cfg:
        cfg["courses"] = cfg.pop("my_courses")
    cfg.setdefault("materials", {"auto_download": True, "max_mb": 50})
    cfg.setdefault("agent", {"kind": None})
    cfg.setdefault("study", dict(V3_DEFAULTS["study"]))
    term = cfg.get("term") if isinstance(cfg.get("term"), dict) else {}
    term.setdefault("week_source", "config" if term.get("week1_monday") else None)
    cfg["term"] = term
    for c in cfg.get("courses") or []:
        c.setdefault("weekday", None)
    return cfg


class Ctx:
    """一次命令运行的上下文：HOME、config（补了默认值）、state、时钟。缺 config 时报中文错误（doctor 除外）。"""

    def __init__(self, home=None, allow_missing=False, quiet=False):
        from cc_time import Clock
        self.home = home_dir(home)
        cfg1 = jload(self.P("config.json"))
        if cfg1 is None and not allow_missing:
            raise CoachError(missing_config_message(self.home), 2)
        state1 = jload(self.P("state.json")) or {}
        cfg1 = cfg1 or {}
        self.config_missing = not cfg1
        self.is_v1 = bool(cfg1 or state1) and (version_of(cfg1) < 2 or version_of(state1) < 2)
        pre_clock = Clock(cfg1)
        today = pre_clock.today_user().isoformat()
        if self.is_v1:
            raw_cfg, self.state, self.narratives = adapt_v1(cfg1, state1, self.home, today)
            if not quiet:
                print(f"[提示] 档案还是 v1，请运行 {coach_cmd()} migrate", file=sys.stderr)
        else:
            raw_cfg, self.state, self.narratives = cfg1, (state1 or minimal_state()), {}
            for k, v in minimal_state().items():
                self.state.setdefault(k, v)
        self.raw_cfg = raw_cfg
        self.cfg = effective(raw_cfg)
        self.clock = Clock(self.cfg)
        self._api = None

    def P(self, *a):
        return os.path.join(self.home, *a)

    # ---- 给人看的资料夹
    @property
    def root(self):
        return root_dir(self.cfg if isinstance(self.cfg, dict) else None)

    def course_name(self, code):
        return next((c.get("name") for c in (self.cfg.get("courses") or []) if c.get("code") == code), None)

    def course_folder(self, code):
        name = (self.course_name(code) or "").strip()
        if not name or name.upper() == code.upper():
            return safe_name(code)
        return safe_name(name if code.upper() in name.upper() else f"{code} {name}")  # Canvas 课名常自带代码

    def course_dir(self, code):
        return os.path.join(self.root, self.course_folder(code))

    def materials_dir(self, code):
        return os.path.join(self.course_dir(code), "课件")

    def output_dir(self, code):
        return os.path.join(self.course_dir(code), "产出")

    def ensure_dirs(self):
        os.makedirs(self.root, exist_ok=True)
        for c in self.cfg.get("courses") or []:
            for d in (self.materials_dir(c["code"]), self.output_dir(c["code"])):
                os.makedirs(d, exist_ok=True)

    def rel(self, path):
        try:
            r = os.path.relpath(path, self.root)
            if not r.startswith(".."):
                return fwd(r)
        except ValueError:
            pass
        return rel_home(self.home, path)

    @property
    def api(self):
        if self._api is None:
            import canvas_api
            import cc_session
            import cc_token
            host = self.cfg.get("canvas_host")
            if not host:
                raise CoachError("config.json 里还没有 canvas_host：跑 doctor --detect-site 或 doctor --host 网址", 2)
            if lms_of(self.cfg) == "moodle":  # Moodle 只有登录这一种方式，没有 token
                import moodle_api
                if not cc_session.has_login(self.home):
                    raise canvas_api.CanvasAuthError(cc_session.RELOGIN)
                self._api = moodle_api.MoodleClient(host, self.home)
            elif cc_session.has_login(self.home):  # 用户跑过 login：用他在浏览器里的登录，不用 token
                self._api = cc_session.SessionCanvas(host, self.home)
            else:
                self._api = canvas_api.Canvas(host, cc_token.token())
        return self._api

    def save_state(self):
        if self.is_v1:
            raise CoachError(f"档案还是 v1，写入前请先运行：{coach_cmd()} migrate", 3)
        self.state["last_seen"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        jsave(self.P("state.json"), self.state)

    def save_config(self):
        jsave(self.P("config.json"), self.raw_cfg)
        self.cfg = effective(self.raw_cfg)
