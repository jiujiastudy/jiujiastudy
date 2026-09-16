"""Build the synthetic Canvas fixtures in tests/fixtures/<scenario>/.

Every school, course, person and message here is invented. Hosts are
"{{BASE}}", which the mock server replaces with its own 127.0.0.1 address.
Times are written as local wall-clock times of the school and stored as
UTC with a trailing "Z", the way Canvas returns them.

    python tests/fixtures/make_fixtures.py            # rebuild all scenarios
    python tests/fixtures/make_fixtures.py us_quarter # rebuild one

The JSON files are committed; the tests never run this script. Rebuilding
changes the golden output, so re-capture goldens afterwards (see harness.py).
"""
import datetime as dt
import json
import os
import shutil
import sys
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
UTC = dt.timezone.utc
BASE = "{{BASE}}"


def iso(t):
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def minimal_state():
    """What doctor writes next to a fresh config.json (schema v3)."""
    return {"schema_version": 3, "last_check": None, "last_fetch": None, "last_record": None,
            "last_seen": None, "last_done": None, "counters": {"pending": 0}, "courses": {},
            "pending_confirmations": [], "decisions": [], "mood": [], "manual_deadlines": [],
            "deadline_notes": {}, "locked_materials": [], "current_plan": None, "daily_report": {}}


class School:
    """Collects one scenario's Canvas objects and writes them as JSON files."""

    def __init__(self, name, tz, now, user, description, created, mock=None):
        self.name, self.tzname, self.tz = name, tz, ZoneInfo(tz)
        self.now = now  # aware datetime, school-local
        self.user = user
        self.description = description
        self.created = created  # when the course shells were set up
        self.mock = mock or {}
        self.courses, self.data = [], {}
        self.announcements, self.conversations, self.events = [], [], []
        self.config, self.state = {}, minimal_state()
        self._n = {}

    # ---- helpers
    def at(self, m, d, hh=23, mm=59, y=None):
        return dt.datetime(y or self.now.year, m, d, hh, mm, tzinfo=self.tz)

    def _next(self, key, start):
        self._n[key] = self._n.get(key, start - 1) + 1
        return self._n[key]

    def _course(self, cid):
        return next(c for c in self.courses if c["id"] == cid)

    # ---- builders
    def course(self, cid, name, code, term, active=True, time_zone=None):
        self.courses.append({
            "id": cid, "name": name, "course_code": code, "workflow_state": "available", "account_id": 10,
            "start_at": None, "end_at": None, "enrollment_term_id": term["id"], "time_zone": time_zone or self.tzname,
            "default_view": "modules", "is_public": False, "apply_assignment_group_weights": True,
            "hide_final_grades": False, "term": term,
            "enrollments": [{"type": "student", "role": "StudentEnrollment", "role_id": 3,
                             "user_id": self.user["id"], "enrollment_state": "active"}],
            "_active": active})
        self.data[cid] = {"assignments": [], "assignment_groups": [], "modules": [], "files": [], "discussion_topics": []}
        return cid

    def group(self, cid, name, weight):
        gid = self._next(f"g{cid}", cid * 10 + 1)
        g = self.data[cid]["assignment_groups"]
        g.append({"id": gid, "name": name, "position": len(g) + 1, "group_weight": weight, "rules": {}})
        return gid

    def assignment(self, cid, name, due=None, lock=None, unlock=None, points=0, types=("online_upload",), group=None,
                   exts=(), attempts=-1, sub=None, desc="", quiz=False):
        """sub: None (unsubmitted) or dict(state, submitted, score, posted, late, attempt)."""
        aid = self._next(f"a{cid}", cid * 1000 + 1)
        sub = sub or {}
        state = sub.get("state", "unsubmitted")
        submitted = sub.get("submitted")
        posted = sub.get("posted", True) if state == "graded" else False
        attempt = sub.get("attempt", 1 if submitted else None)
        stype = None if state == "unsubmitted" else next((t for t in types if t not in ("none", "on_paper")), None)
        submission = {
            "id": aid * 10, "assignment_id": aid, "user_id": self.user["id"], "attempt": attempt,
            "workflow_state": state, "submitted_at": iso(submitted),
            "score": sub.get("score") if posted else None,
            "grade": (str(sub.get("score")) if posted and sub.get("score") is not None else None),
            "graded_at": iso(sub.get("graded", submitted)) if state == "graded" else None,
            "posted_at": iso(sub.get("graded", submitted)) if posted else None,
            "submission_type": stype, "late": bool(sub.get("late")), "missing": bool(sub.get("missing")),
            "excused": None, "seconds_late": 0}
        if stype == "online_upload" and submitted:
            submission["attachments"] = [{"id": aid * 10 + 1, "display_name": sub.get("file", "submission.pdf"),
                                          "filename": sub.get("file", "submission.pdf"), "size": 48213}]
        a = {"id": aid, "name": name, "description": desc, "created_at": iso(self.created),
             "updated_at": iso(sub.get("updated", self.created)), "due_at": iso(due), "lock_at": iso(lock),
             "unlock_at": iso(unlock), "points_possible": points, "grading_type": "points",
             "assignment_group_id": group, "submission_types": list(types), "allowed_extensions": list(exts),
             "allowed_attempts": attempts, "has_submitted_submissions": bool(submitted), "course_id": cid,
             "html_url": f"{BASE}/courses/{cid}/assignments/{aid}", "published": True,
             "position": len(self.data[cid]["assignments"]) + 1, "is_quiz_assignment": quiz,
             "locked_for_user": False, "omit_from_final_grade": False, "workflow_state": "published",
             "submission": submission}
        self.data[cid]["assignments"].append(a)
        if "discussion_topic" in types:
            tid = self._next(f"t{cid}", cid * 1000 + 701)
            a["discussion_topic"] = {"id": tid}
            self.data[cid]["discussion_topics"].append({
                "id": tid, "title": name, "message": desc, "assignment_id": aid, "posted_at": iso(self.created),
                "html_url": f"{BASE}/courses/{cid}/discussion_topics/{tid}", "discussion_type": "threaded",
                "locked_for_user": False, "is_announcement": False})
        return aid

    def file(self, cid, name, size=250_000, locked=False, unlock=None, ctype="application/pdf"):
        fid = self._next(f"f{cid}", cid * 1000 + 501)
        body = f"Synthetic course file {fid}: {name}\n"
        self.data[cid]["files"].append({
            "id": fid, "uuid": f"u{fid}", "folder_id": cid * 10, "display_name": name, "filename": name.replace(" ", "+"),
            "content-type": ctype, "size": size, "created_at": iso(self.created), "updated_at": iso(self.created),
            "unlock_at": iso(unlock), "locked": False, "hidden": False, "locked_for_user": locked,
            "lock_explanation": "This file is locked." if locked else None,
            "url": "" if locked else f"{BASE}/files/{fid}/download?download_frd=1&verifier=v{fid}",
            "_body": body})
        return fid

    def module(self, cid, name, items, unlock=None, locked=False):
        """items: list of (type, title, extra-dict). Locked modules lock every item until unlock."""
        mods = self.data[cid]["modules"]
        mid = self._next(f"m{cid}", cid * 1000 + 101)
        out = []
        for pos, (kind, title, extra) in enumerate(items, 1):
            iid = self._next(f"i{cid}", cid * 10000 + 1)
            it = {"id": iid, "module_id": mid, "position": pos, "title": title, "indent": 0, "type": kind,
                  "html_url": f"{BASE}/courses/{cid}/modules/items/{iid}"}
            cd = {"locked_for_user": locked}
            if locked:
                cd.update({"unlock_at": iso(unlock), "lock_explanation": f"This module is locked until {iso(unlock)}."})
            if kind == "File":
                fid = self.file(cid, title, size=extra.get("size", 250_000), locked=locked, unlock=unlock,
                                ctype=extra.get("ctype", "application/pdf"))
                it.update({"content_id": fid, "url": f"{BASE}/api/v1/courses/{cid}/files/{fid}"})
                cd["display_name"] = title
            elif kind == "Page":
                slug = extra.get("slug") or title.lower().replace(" ", "-")
                it.update({"page_url": slug, "url": f"{BASE}/api/v1/courses/{cid}/pages/{slug}"})
            elif kind in ("ExternalUrl", "ExternalTool"):
                it.update({"external_url": extra["url"]})
            elif kind in ("Assignment", "Quiz", "Discussion"):
                a = next(x for x in self.data[cid]["assignments"] if x["id"] == extra["assignment"])
                it["content_id"] = (a.get("discussion_topic") or {}).get("id", a["id"]) if kind == "Discussion" else a["id"]
                it["url"] = f"{BASE}/api/v1/courses/{cid}/assignments/{a['id']}"
                cd.update({"points_possible": a["points_possible"], "due_at": a["due_at"]})
            if kind != "SubHeader":
                it["content_details"] = cd
            else:
                it.pop("html_url")
            out.append(it)
        mods.append({"id": mid, "name": name, "position": len(mods) + 1, "unlock_at": iso(unlock),
                     "require_sequential_progress": False, "published": True,
                     "state": "locked" if locked else "unlocked", "items": out})
        return mid

    def announcement(self, cid, title, posted, message, author):
        aid = self._next("ann", 90001)
        self.announcements.append({
            "id": aid, "title": title, "message": message, "posted_at": iso(posted), "delayed_post_at": None,
            "html_url": f"{BASE}/courses/{cid}/discussion_topics/{aid}", "context_code": f"course_{cid}",
            "author": {"id": author[0], "display_name": author[1]}, "read_state": "unread",
            "is_announcement": True, "locked": True})

    def conversation(self, cid, subject, last, message, people, state="unread"):
        cv = self._next("conv", 80001)
        c = self._course(cid)
        parts = [{"id": pid, "name": name, "full_name": name} for pid, name in people]
        self.conversations.append({
            "id": cv, "subject": subject, "workflow_state": state, "last_message": message,
            "last_message_at": iso(last), "last_authored_message_at": None, "message_count": 2,
            "participants": parts, "audience": [p["id"] for p in parts if p["id"] != self.user["id"]],
            "context_name": c["name"], "context_code": f"course_{cid}", "starred": False, "private": True})

    def event(self, cid, title, start, end, location):
        eid = self._next("ev", 70001)
        self.events.append({
            "id": eid, "title": title, "start_at": iso(start), "end_at": iso(end), "all_day": False,
            "location_name": location, "context_code": f"course_{cid}", "workflow_state": "active",
            "html_url": f"{BASE}/calendar?event_id={eid}&include_contexts=course_{cid}", "type": "event"})

    # ---- derived views
    def _assignment_events(self):
        out = []
        for c in self.courses:
            for a in self.data[c["id"]]["assignments"]:
                if a["due_at"]:
                    out.append({"id": f"assignment_{a['id']}", "title": a["name"], "start_at": a["due_at"],
                                "end_at": a["due_at"], "all_day": False, "context_code": f"course_{c['id']}",
                                "workflow_state": "published", "html_url": a["html_url"], "type": "assignment",
                                "assignment": {"id": a["id"], "name": a["name"], "due_at": a["due_at"],
                                               "points_possible": a["points_possible"]}})
        return out

    def _planner(self):
        out = []
        for c in self.courses:
            for a in self.data[c["id"]]["assignments"]:
                if not a["due_at"]:
                    continue
                s = a["submission"]
                kind = ("quiz" if a["is_quiz_assignment"] else
                        "discussion_topic" if "discussion_topic" in a["submission_types"] else "assignment")
                out.append({"context_type": "Course", "course_id": c["id"], "context_name": c["name"],
                            "plannable_id": a["id"], "plannable_type": kind, "plannable_date": a["due_at"],
                            "plannable": {"id": a["id"], "title": a["name"], "due_at": a["due_at"],
                                          "points_possible": a["points_possible"]},
                            "html_url": a["html_url"], "new_activity": False, "planner_override": None,
                            "submissions": {"submitted": s["workflow_state"] != "unsubmitted",
                                            "graded": s["workflow_state"] == "graded", "late": s["late"],
                                            "missing": s["missing"], "excused": False, "needs_grading": False,
                                            "has_feedback": False}})
        for a in self.announcements:
            cid = int(a["context_code"].split("_")[1])
            out.append({"context_type": "Course", "course_id": cid, "context_name": self._course(cid)["name"],
                        "plannable_id": a["id"], "plannable_type": "announcement", "plannable_date": a["posted_at"],
                        "plannable": {"id": a["id"], "title": a["title"]}, "html_url": a["html_url"],
                        "new_activity": True, "planner_override": None, "submissions": False})
        return sorted(out, key=lambda x: (x["plannable_date"], str(x["plannable_id"])))

    # ---- output
    def dump(self):
        d = os.path.join(HERE, self.name)
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d)

        def w(rel, obj):
            p = os.path.join(d, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                json.dump(obj, f, ensure_ascii=False, indent=1)
                f.write("\n")

        user_tz = ZoneInfo(self.config.get("user_tz") or self.tzname)
        w("scenario.json", {"name": self.name, "description": self.description, "now": iso(self.now),
                            "date": self.now.astimezone(user_tz).date().isoformat(), "token": "dummy",
                            "mock": self.mock, "config": self.config, "state": self.state})
        w("users_self.json", self.user)
        w("courses.json", self.courses)
        for c in self.courses:
            for k, v in self.data[c["id"]].items():
                w(f"courses/{c['id']}/{k}.json", v)
        w("announcements.json", self.announcements)
        w("conversations.json", self.conversations)
        w("calendar_events.json", self.events + self._assignment_events())
        w("planner_items.json", self._planner())
        return d


def base_config(school, host_note, term, courses, course_tz, user_tz, user):
    """config.json as doctor writes it (canvas_host is filled in by the harness)."""
    return {"schema_version": 3, "canvas_host": None, "course_tz": course_tz, "user_tz": user_tz, "tz_labels": {},
            "term": term, "user": {"id": user["id"], "name": user["name"]}, "courses": courses,
            "extra_sites": [], "exam_prep": None, "api_notes": {}, "notes": [host_note] if host_note else [],
            "root": None, "materials": {"auto_download": True, "max_mb": 50, "per_run": 30}, "agent": {"kind": None}}


# ---- scenarios

SCENARIOS = {}


def scenario(fn):
    SCENARIOS[fn.__name__] = fn
    return fn


@scenario
def au_semester():
    """Australian semester: ABCD1234 codes, 13 weeks plus a break, weekly modules, student's clock in Shanghai."""
    tz = "Australia/Sydney"
    user = {"id": 5001, "name": "Test Student", "short_name": "Test", "sortable_name": "Student, Test",
            "locale": None, "effective_locale": "en-AU", "time_zone": "Beijing"}
    s = School("au_semester", tz, dt.datetime(2026, 3, 25, 10, 0, tzinfo=ZoneInfo(tz)), user,
               "13-week semester in Week 5; overdue quiz, 48-hour clash, lock_at-only and undated items, "
               "a placeholder date with a note, a manual deadline and one pending question; modules paged 10 per page.",
               created=dt.datetime(2026, 2, 2, 9, 0, tzinfo=ZoneInfo(tz)), mock={"max_per_page": 10})
    term = {"id": 301, "name": "Semester 1 2026", "start_at": "2026-02-22T13:00:00Z", "end_at": "2026-06-26T13:59:00Z"}
    week_monday = {1: (2, 23), 2: (3, 2), 3: (3, 9), 4: (3, 16), 5: (3, 23), 6: (3, 30), 7: (4, 13), 8: (4, 20),
                   9: (4, 27), 10: (5, 4), 11: (5, 11), 12: (5, 18), 13: (5, 25)}

    def fri(n):
        m, d = week_monday[n]
        return s.at(m, d) + dt.timedelta(days=4)

    # ACCT1101: weekly release, weekly quizzes
    a = s.course(1101, "ACCT1101 Accounting Foundations", "ACCT1101", term)
    g_quiz, g_case, g_exam = s.group(a, "Quizzes", 20), s.group(a, "Case study", 30), s.group(a, "Final exam", 50)
    quizzes = {}
    for n in range(1, 9):
        sub = {1: {"state": "graded", "submitted": fri(1) - dt.timedelta(hours=5), "score": 2},
               2: {"state": "graded", "submitted": fri(2) - dt.timedelta(hours=26), "score": 1.5},
               3: {"state": "graded", "submitted": fri(3) - dt.timedelta(hours=3), "score": 2}}.get(n)
        quizzes[n] = s.assignment(a, f"Weekly Quiz {n}", due=fri(n), points=2, types=("online_quiz",), group=g_quiz,
                                  quiz=True, attempts=1, sub=sub, desc=f"<p>Ten questions on Week {n}. 30 minutes.</p>")
    s.assignment(a, "Case Study Report (30%)", due=s.at(4, 2), points=30, exts=("pdf", "docx"), attempts=1, group=g_case,
                 desc="<p>Analyse the financial statements of <em>Harbour Bikes Pty Ltd</em> (1,500 words).</p>")
    s.assignment(a, "Final Exam (50%)", points=50, types=("on_paper",), group=g_exam,
                 desc="<p>Two-hour exam in the formal exam period. Date to be announced.</p>")
    topics = ["Introduction to Accounting", "The Accounting Equation", "Recording Transactions", "Adjusting Entries",
              "Financial Statements", "Inventory", "Receivables", "Non-current Assets", "Liabilities", "Equity",
              "Cash Flow", "Ratio Analysis", "Revision"]
    for n, topic in enumerate(topics, 1):
        m, d = week_monday[n]
        items = [("SubHeader", "Before the lecture", {}), ("File", f"ACCT1101 W{n} Lecture Slides.pdf", {}),
                 ("Page", f"Week {n} tutorial questions", {}),
                 ("ExternalUrl", "Lecture recording", {"url": f"https://video.example/echo360/acct1101-w{n}"})]
        if n in quizzes:
            items.append(("Quiz", f"Weekly Quiz {n}", {"assignment": quizzes[n]}))
        s.module(a, f"Week {n}: {topic}", items, unlock=s.at(m, d, 0, 0) if n > 5 else None, locked=n > 5)

    # PSYC2012: everything released at once (max unlocked week 13 is not a reliable signal)
    p = s.course(1102, "PSYC2012 Cognition and Memory", "PSYC2012_S1C_2026", term)
    s.assignment(p, "Lab Report draft", due=s.at(3, 20, 17, 0), points=0,
                 sub={"state": "submitted", "submitted": s.at(3, 19, 21, 40), "file": "draft.docx"})
    s.assignment(p, "Lab Report (25%)", due=s.at(3, 26, 17, 0), points=25, exts=("docx", "pdf"),
                 desc="<p>APA-style report on the working-memory experiment. 2,000 words.</p>")
    disc = s.assignment(p, "Week 5 discussion post", due=s.at(3, 27), points=1, types=("discussion_topic",),
                        desc="<p>Describe one way working memory limits you in daily life.</p>")
    s.assignment(p, "Mid-semester test (20%)", due=s.at(4, 1, 13, 0), points=20, types=("online_quiz",), quiz=True,
                 attempts=1)
    s.assignment(p, "Research Participation (5%)", points=5, types=("none",))
    ptopics = ["What is Cognition", "Perception", "Attention", "Short-term Memory", "Working Memory",
               "Long-term Memory", "Forgetting", "Language", "Reasoning", "Decision Making", "Expertise",
               "Cognitive Ageing", "Review"]
    for n, topic in enumerate(ptopics, 1):
        items = [("File", f"PSYC2012 Lecture {n} - {topic}.pptx",
                  {"ctype": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}),
                 ("Page", f"Week {n} tutorial prep", {}),
                 ("ExternalUrl", f"Week {n} lecture recording", {"url": f"https://youtube.example/watch?v=psyc{n:02d}"})]
        if n == 5:
            items.append(("Discussion", "Week 5 discussion post", {"assignment": disc}))
        s.module(p, f"Week {n}: {topic}", items)

    # DSGN3402: "W5 Studio" module names, lock_at-only portfolio, placeholder date
    d_ = s.course(1103, "DSGN3402 Interaction Design Studio", "DSGN3402", term)
    journal = s.assignment(d_, "Reflection journal", due=s.at(3, 18), points=10, types=("online_text_entry",))
    crit = s.assignment(d_, "Prototype critique (15%)", due=s.at(3, 30, 9, 0), points=15, types=("online_text_entry",))
    s.assignment(d_, "Design Portfolio (40%)", lock=s.at(4, 8), points=40, exts=("pdf",))
    s.assignment(d_, "Studio attendance", due=s.at(3, 24, 12, 0), points=0, types=("on_paper",))
    stopics = ["Kick-off", "Research", "Personas", "Ideation", "Prototyping", "Testing"]
    for n, topic in enumerate(stopics, 1):
        items = [("Page", f"W{n} studio notes", {}), ("File", f"W{n}_Studio_Toolkit.pdf", {})]
        if n == 1:
            items.insert(0, ("Page", "Course outline and policies", {}))
        if n == 5:
            items.append(("Assignment", "Prototype critique (15%)", {"assignment": crit}))
        m, d = week_monday[n]
        s.module(d_, f"W{n} Studio: {topic}", items, unlock=s.at(m, d, 0, 0) if n == 6 else None, locked=n == 6)

    s.course(1190, "Library Skills Hub", "2026_LIB_SKILLS", term)

    s.announcement(a, "Welcome to ACCT1101", s.at(2, 20, 9, 0), "<p>Welcome! Lectures start in Week 1.</p>", (7101, "Dr. Morgan Hale"))
    s.announcement(a, "Case study report: submission guide", s.at(3, 23, 9, 15),
                   "<p>The case study report is due <strong>Thursday 2 April, 11:59 pm</strong>. "
                   "Submit one PDF or Word file.</p><p>Use the template in Week 5.</p>", (7101, "Dr. Morgan Hale"))
    s.announcement(p, "Lab report extension policy", s.at(3, 24, 14, 0),
                   "<p>Extensions for the lab report need a Special Consideration application. "
                   "Late submissions lose 5% per day.</p>", (7201, "Prof. Lena Okafor"))
    s.announcement(d_, "Studio room change for Week 6", s.at(3, 20, 11, 30),
                   "<p>From Week 6 the studio moves to Room 2.14 in the Design Building.</p>", (7301, "Sam Taylor"))
    s.announcement(1190, "Library workshops this week", s.at(3, 24, 8, 0), "<p>Referencing workshop on Thursday.</p>",
                   (7901, "Library Team"))
    s.conversation(a, "Quiz 4 technical issue", s.at(3, 23, 13, 10),
                   "Hi, if Quiz 4 did not load for you, email me before Friday and I will reopen it.",
                   [(5001, "Test Student"), (7102, "Jamie Chen")])
    s.conversation(p, "Lab groups", s.at(3, 12, 10, 0), "Your lab group is Group 7. Please meet before Week 5.",
                   [(5001, "Test Student"), (7201, "Prof. Lena Okafor")], state="read")
    s.event(a, "Tutorial 05", s.at(3, 26, 14, 0), s.at(3, 26, 15, 0), "Room 410")
    s.event(p, "Mid-semester test", s.at(4, 1, 13, 0), s.at(4, 1, 14, 0), "Online")
    s.event(d_, "Studio crit", s.at(3, 30, 9, 0), s.at(3, 30, 12, 0), "Design Studio 2")

    s.config = base_config(s, "未当作课程的站点（要加就手动写进 courses）：2026_LIB_SKILLS（1190）",
                           {"name": "Semester 1 2026", "start": "2026-02-23", "end": "2026-06-26",
                            "week1_monday": "2026-02-23", "break": "2026-04-06..2026-04-10", "week_source": "config"},
                           [{"id": 1101, "code": "ACCT1101", "name": "ACCT1101 Accounting Foundations", "section": None, "weekday": None},
                            {"id": 1102, "code": "PSYC2012", "name": "PSYC2012 Cognition and Memory", "section": None, "weekday": 2},
                            {"id": 1103, "code": "DSGN3402", "name": "DSGN3402 Interaction Design Studio", "section": None, "weekday": None}],
                           tz, "Asia/Shanghai", user)
    s.state["manual_deadlines"] = [{"course": "DSGN3402", "item": "Studio pitch (in class)", "date": "2026-03-31", "time": None,
                                    "time_text": "课上", "weight": "10%", "status": "未交", "note": "", "source": "公告 03-20",
                                    "url": None, "pending": False, "assignment_id": None, "added": "2026-03-21"}]
    s.state["deadline_notes"] = {str(journal): "老师说 Canvas 日期只是占位，真正截止另行通知"}
    s.state["pending_confirmations"] = [{"id": "pc-0001", "course": "PSYC2012", "text": "Lab Report 是个人交还是小组交",
                                         "first_asked": "2026-03-20", "last_asked": "2026-03-20", "times_asked": 1,
                                         "blocks": "2026-03-26", "ask_en": "Is the lab report submitted individually or per group?",
                                         "ask_zh": "实验报告是个人交还是小组交？", "resolved": None, "resolution": None}]
    s.state["counters"] = {"pending": 1}
    return s


@scenario
def us_quarter():
    """US quarter: 'MATH 3B: Calculus' names, topic-named modules, America/Los_Angeles, fresh archive."""
    tz = "America/Los_Angeles"
    user = {"id": 6001, "name": "Test Student", "short_name": "Test", "sortable_name": "Student, Test",
            "locale": None, "effective_locale": "en", "time_zone": "Pacific Time (US & Canada)"}
    s = School("us_quarter", tz, dt.datetime(2026, 2, 25, 9, 0, tzinfo=ZoneInfo(tz)), user,
               "10-week quarter in Week 8, no week number in config (inferred from CHEM 1A's 'Week N' modules); "
               "topic-named and 'Unit N' modules; modules with more than 6 items are not inlined (items_url only); "
               "assignments paged 10 per page; due times that fall on the next UTC day.",
               created=dt.datetime(2025, 12, 15, 10, 0, tzinfo=ZoneInfo(tz)),
               mock={"max_per_page": 10, "inline_items_max": 6})
    term = {"id": 401, "name": "Winter 2026", "start_at": "2026-01-05T08:00:00Z", "end_at": "2026-03-21T07:59:00Z"}

    def monday(n):
        return dt.date(2026, 1, 5) + dt.timedelta(days=7 * (n - 1))

    def on(day, hh=23, mm=59):
        return s.at(day.month, day.day, hh, mm)

    m = s.course(2201, "MATH 3B: Calculus", "MATH 3B", term)
    g_hw, g_mid, g_fin, g_part = (s.group(m, "Homework", 20), s.group(m, "Midterms", 40),
                                  s.group(m, "Final", 30), s.group(m, "Participation", 10))
    scores = {1: 9, 2: 10, 3: 8, 4: 10, 5: 9}
    hw = {}
    for n in range(1, 9):
        due = on(monday(n + 1) + dt.timedelta(days=3))
        sub = ({"state": "graded", "submitted": due - dt.timedelta(hours=20), "score": scores[n]} if n in scores else
               {"state": "submitted", "submitted": due - dt.timedelta(hours=28)} if n == 6 else None)
        hw[n] = s.assignment(m, f"Homework {n}", due=due, points=10, types=("external_tool",), group=g_hw, sub=sub)
    s.assignment(m, "Midterm 1", due=s.at(1, 30, 14, 0), points=100, types=("on_paper",), group=g_mid,
                 sub={"state": "graded", "submitted": s.at(1, 30, 14, 0), "score": 84, "graded": s.at(2, 6, 12, 0)})
    s.assignment(m, "Midterm 2", due=s.at(3, 4, 14, 0), points=100, types=("on_paper",), group=g_mid)
    s.assignment(m, "Final Exam", due=s.at(3, 17, 12, 0), points=100, types=("on_paper",), group=g_fin)
    s.assignment(m, "Participation (10%)", points=10, types=("none",), group=g_part)
    topics = ["Integration by Substitution", "Integration by Parts", "Trigonometric Integrals", "Partial Fractions",
              "Improper Integrals", "Sequences", "Applications of Integration", "Series and Convergence", "Power Series"]
    for n, topic in enumerate(topics, 1):
        items = [("File", f"{topic} notes.pdf", {}), ("Page", f"{topic} practice problems", {}),
                 ("ExternalUrl", f"Lecture video: {topic}", {"url": f"https://video.example/math3b/{n}"})]
        if topic == "Series and Convergence":
            items += [("File", "Series worksheet.pdf", {}),
                      ("ExternalUrl", "Lecture video: Series, part 2", {"url": "https://video.example/math3b/8b"}),
                      ("Page", "Convergence tests summary", {}),
                      ("ExternalTool", "WebAssign: Homework 8", {"url": "https://webassign.example/hw8"}),
                      ("Assignment", "Homework 8", {"assignment": hw[8]})]
        mon = monday(n)
        s.module(m, topic, items, unlock=on(mon, 0, 0), locked=n == 9)

    c = s.course(2202, "CHEM 1A: General Chemistry", "CHEM 1A", term)
    s.assignment(c, "Lab 6 Report", due=s.at(2, 20, 17, 0), points=20, exts=("pdf",),
                 sub={"state": "submitted", "submitted": s.at(2, 21, 9, 30), "late": True, "file": "lab6.pdf"})
    s.assignment(c, "Lab 7 Report", due=s.at(2, 27, 17, 0), points=20, exts=("pdf",))
    prelab = s.assignment(c, "Pre-lab Quiz 8", due=s.at(3, 2, 8, 0), points=5, types=("online_quiz",), quiz=True)
    s.assignment(c, "Problem Set 5", due=s.at(2, 24), points=10,
                 sub={"state": "graded", "submitted": s.at(2, 24, 21, 0), "score": 7, "posted": False})
    s.assignment(c, "Midterm", due=s.at(2, 11, 18, 0), points=100, types=("on_paper",),
                 sub={"state": "graded", "submitted": s.at(2, 11, 18, 0), "score": 71, "graded": s.at(2, 18, 9, 0)})
    ctopics = ["Measurement", "Atoms and Molecules", "Stoichiometry", "Reactions in Solution", "Gases",
               "Midterm Week", "Energy", "Thermochemistry", "Quantum Theory", "Review"]
    for n, topic in enumerate(ctopics, 1):
        items = [("File", f"CHEM1A Week {n} slides.pdf", {}), ("Page", f"Week {n} reading guide", {})]
        if n == 8:
            items = [("SubHeader", "Lecture", {})] + items + [("SubHeader", "Lab", {}),
                                                              ("Quiz", "Pre-lab Quiz 8", {"assignment": prelab})]
        if n == 9:
            items += [("File", f"Quantum worksheet {k}.pdf", {}) for k in range(1, 6)]
        s.module(c, f"Week {n}: {topic}", items, unlock=on(monday(n), 0, 0), locked=n >= 9)

    w = s.course(2203, "WRIT 2: Academic Writing", "WRIT 2", term)
    s.assignment(w, "Essay 1: Rhetorical Analysis (20%)", due=s.at(1, 30), points=20,
                 sub={"state": "graded", "submitted": s.at(1, 30, 22, 5), "score": 17, "graded": s.at(2, 9, 10, 0)})
    peer = s.assignment(w, "Peer Review 2", due=s.at(2, 27), points=5, types=("discussion_topic",),
                        desc="<p>Reply to two classmates' drafts.</p>")
    s.assignment(w, "Essay 2: Argument (25%)", due=s.at(3, 6), points=25, exts=("docx", "pdf"))
    s.assignment(w, "Portfolio (40%)", due=s.at(3, 19), points=40)
    s.assignment(w, "Participation", points=0, types=("none",))
    s.module(w, "Unit 1: Rhetorical Situations", [("Page", "Unit 1 overview", {}), ("File", "Rhetorical triangle.pdf", {}),
                                                  ("Page", "Sample analysis", {}), ("File", "Essay 1 prompt.pdf", {}),
                                                  ("Page", "Essay 1 rubric", {})])
    s.module(w, "Unit 2: Research and Sources", [("Page", "Unit 2 overview", {}), ("File", "Library database guide.pdf", {}),
                                                 ("Page", "Evaluating sources", {}), ("Page", "Annotated bibliography", {})])
    s.module(w, "Unit 3: Argument", [("Page", "Unit 3 overview", {}), ("File", "Toulmin model.pdf", {}),
                                     ("Page", "Counterarguments", {}), ("File", "Essay 2 prompt.pdf", {}),
                                     ("Page", "Essay 2 rubric", {}), ("Discussion", "Peer Review 2", {"assignment": peer}),
                                     ("ExternalUrl", "Recorded workshop", {"url": "https://video.example/writ2/argument"}),
                                     ("Page", "Drafting checklist", {})])
    s.module(w, "Course Policies", [("Page", "Syllabus", {}), ("Page", "Late work policy", {})])

    s.announcement(m, "Welcome to MATH 3B", s.at(1, 4, 12, 0), "<p>See the syllabus for the homework schedule.</p>",
                   (8101, "Prof. Dana Whitfield"))
    s.announcement(m, "Midterm 2 room assignments", s.at(2, 23, 10, 0),
                   "<p>Midterm 2 is on <strong>Wednesday March 4</strong> in your usual lecture room. Bring a photo ID.</p>",
                   (8101, "Prof. Dana Whitfield"))
    s.announcement(c, "Lab safety reminder", s.at(2, 20, 16, 0), "<p>Goggles are required for Lab 8. No open-toed shoes.</p>",
                   (8201, "Dr. Rafael Soto"))
    s.announcement(w, "Office hours moved", s.at(2, 10, 10, 0), "<p>Office hours move to Tuesdays 2-3 pm.</p>",
                   (8301, "Kim Nguyen"))
    s.conversation(m, "HW7 question 4 typo", s.at(2, 24, 18, 30),
                   "Question 4 on HW7 has a typo: it should be n^2, not n^3.", [(6001, "Test Student"), (8102, "Chris Park")])
    s.conversation(c, "Lab section swap", s.at(2, 22, 11, 0), "Your swap to Section 3 is approved.",
                   [(6001, "Test Student"), (8201, "Dr. Rafael Soto")])
    s.event(m, "Midterm 2", s.at(3, 4, 14, 0), s.at(3, 4, 15, 15), "Lecture Hall 2")
    s.event(c, "Lab Section 3", s.at(2, 27, 13, 0), s.at(2, 27, 16, 0), "Chem Lab 1105")

    s.config = base_config(s, None, {"name": "Winter 2026", "start": "2026-01-05", "end": "2026-03-20",
                                     "week1_monday": None, "break": None, "week_source": None},
                           [{"id": 2201, "code": "MATH3B", "name": "MATH 3B: Calculus", "section": None, "weekday": None},
                            {"id": 2202, "code": "CHEM1A", "name": "CHEM 1A: General Chemistry", "section": None, "weekday": None},
                            {"id": 2203, "code": "WRIT2", "name": "WRIT 2: Academic Writing", "section": None, "weekday": None}],
                           tz, tz, user)
    return s


@scenario
def uk_term():
    """UK term: reading week, 'Lecture N' and 'Seminar N' modules, Europe/London near the clock change, student in Shanghai."""
    tz = "Europe/London"
    user = {"id": 7001, "name": "Test Student", "short_name": "Test", "sortable_name": "Student, Test",
            "locale": None, "effective_locale": "en-GB", "time_zone": "London"}
    s = School("uk_term", tz, dt.datetime(2026, 3, 18, 12, 0, tzinfo=ZoneInfo(tz)), user,
               "Spring term in teaching Week 9 after a reading week; weeks from 'Week N', 'Lecture N' and module "
               "unlock dates ('Seminar N'); London changes clock within 14 days; a mood word and a decision in state.",
               created=dt.datetime(2025, 12, 8, 10, 0, tzinfo=ZoneInfo(tz)))
    term = {"id": 501, "name": "Spring Term 2026", "start_at": "2026-01-12T00:00:00Z", "end_at": "2026-03-27T23:59:00Z"}

    def monday(n):  # teaching week n; reading week falls after week 5
        return dt.date(2026, 1, 12) + dt.timedelta(days=7 * (n - 1 if n <= 5 else n))

    def start(n):
        d = monday(n)
        return s.at(d.month, d.day, 0, 0)

    h = s.course(3301, "HIS2102 Modern Britain, 1800–1914", "HIS2102", term)
    s.assignment(h, "Formative essay plan", due=s.at(3, 2, 12, 0), points=0)
    s.assignment(h, "Source Analysis (40%)", due=s.at(3, 19, 12, 0), points=40, exts=("docx", "pdf"),
                 sub={"state": "submitted", "submitted": s.at(3, 17, 21, 14), "file": "source-analysis.docx"})
    s.assignment(h, "Summative Essay – 3,000 words (60%)", due=s.at(3, 26, 12, 0), points=60, exts=("docx", "pdf"))
    htopics = ["The Age of Reform", "Industrial Towns", "Chartism", "The Hungry Forties", "Victorian Religion",
               "Gladstone and Disraeli", "Empire and Trade", "Women and Work", "The Irish Question", "Edwardian Britain"]
    for n, topic in enumerate(htopics, 1):
        items = [("Page", f"Seminar {n} reading list", {}), ("File", f"HIS2102 Lecture {n}.pdf", {}),
                 ("ExternalUrl", f"Lecture {n} recording (Panopto)", {"url": f"https://video.example/panopto/his2102-{n}"})]
        if n == 9:
            items.append(("Page", "Seminar 9 prep questions", {}))
        s.module(h, f"Week {n}: {topic}", items, unlock=start(n) if n == 10 else None, locked=n == 10)
        if n == 5:
            s.module(h, "Reading Week (16–20 Feb)", [("Page", "Reading week tasks", {})])

    p = s.course(3302, "PSY2031 Research Methods II", "PSY2031", term)
    q7 = s.assignment(p, "Weekly practice quiz 7", due=s.at(3, 6, 17, 0), points=1, types=("online_quiz",), quiz=True,
                      sub={"state": "graded", "submitted": s.at(3, 6, 15, 0), "score": 1})
    q8 = s.assignment(p, "Weekly practice quiz 8", due=s.at(3, 13, 17, 0), points=1, types=("online_quiz",), quiz=True)
    s.assignment(p, "Lab report (50%)", due=s.at(3, 20, 16, 0), points=50, exts=("docx",),
                 desc="<p>Report the Lab 8 mixed ANOVA. 2,500 words.</p>")
    s.assignment(p, "SONA participation (5%)", points=5, types=("none",))
    s.assignment(p, "Exam (45%)", due=s.at(5, 12, 9, 30), points=45, types=("on_paper",))
    ptopics = ["Research Design", "Sampling", "Measurement", "t-tests", "One-way ANOVA", "Factorial ANOVA",
               "Repeated Measures", "Nonparametric Tests", "Mixed ANOVA", "Regression"]
    for n, topic in enumerate(ptopics, 1):
        items = [("File", f"PSY2031_Lecture{n:02d}_{topic.replace(' ', '')}.pptx",
                  {"ctype": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}),
                 ("Page", f"Lab {n}: R worksheet", {})]
        if n == 7:
            items.append(("Quiz", "Weekly practice quiz 7", {"assignment": q7}))
        if n == 8:
            items.append(("Quiz", "Weekly practice quiz 8", {"assignment": q8}))
        s.module(p, f"Lecture {n}: {topic}", items, unlock=start(n) if n == 10 else None, locked=n == 10)

    law = s.course(3303, "LAW1113 Contract Law", "LAW1113", term)
    s.assignment(law, "Problem question (30%)", due=s.at(3, 19), points=30, exts=("docx",))
    s.assignment(law, "Moot participation", due=s.at(3, 24, 10, 0), points=0, types=("on_paper",))
    s.assignment(law, "Exam (70%)", points=70, types=("on_paper",))
    ltopics = ["Offer and Acceptance", "Consideration", "Intention", "Terms", "Exclusion Clauses",
               "Misrepresentation", "Mistake", "Duress", "Frustration", "Remedies"]
    for n, topic in enumerate(ltopics, 1):
        s.module(law, f"Seminar {n}: {topic}", [("Page", f"Seminar {n} reading", {}),
                                                ("File", f"LAW1113 Seminar {n} handout.pdf", {})],
                 unlock=start(n), locked=n == 10)

    s.announcement(h, "Essay deadline reminder", s.at(3, 16, 9, 0),
                   "<p>The summative essay is due <strong>Thursday 26 March at 12:00 noon</strong>.</p>",
                   (9101, "Dr. Eleanor Grant"))
    s.announcement(p, "R drop-in sessions", s.at(3, 12, 14, 0),
                   "<p>Drop-in help with R every Thursday, 2-4 pm, Room B12.</p>", (9201, "Dr. Priya Nair"))
    s.announcement(law, "Seminar 9 room change", s.at(3, 17, 8, 30),
                   "<p>Seminar 9 moves to the Moot Court Room this week.</p>", (9301, "Prof. Tom Ashworth"))
    s.conversation(p, "Lab report word count", s.at(3, 17, 10, 0),
                   "The 2,500-word limit excludes references and tables.", [(7001, "Test Student"), (9201, "Dr. Priya Nair")])
    s.conversation(h, "Essay title approved", s.at(3, 11, 15, 20), "Your essay title is approved.",
                   [(7001, "Test Student"), (9101, "Dr. Eleanor Grant")], state="read")
    s.event(law, "Moot", s.at(3, 24, 10, 0), s.at(3, 24, 12, 0), "Moot Court Room")
    s.event(p, "Lab 9", s.at(3, 19, 11, 0), s.at(3, 19, 13, 0), "Room B12")

    s.config = base_config(s, None, {"name": "Spring Term 2026", "start": "2026-01-12", "end": "2026-03-27",
                                     "week1_monday": "2026-01-12", "break": "2026-02-16..2026-02-20", "week_source": "config"},
                           [{"id": 3301, "code": "HIS2102", "name": "HIS2102 Modern Britain, 1800–1914", "section": None, "weekday": None},
                            {"id": 3302, "code": "PSY2031", "name": "PSY2031 Research Methods II", "section": None, "weekday": 4},
                            {"id": 3303, "code": "LAW1113", "name": "LAW1113 Contract Law", "section": None, "weekday": None}],
                           tz, "Asia/Shanghai", user)
    s.state["mood"] = [{"date": "2026-03-17", "word": "来不及", "level": "过载", "note": None}]
    s.state["decisions"] = [{"text": "HIS2102 形成性作业不交，不再提起", "course": "HIS2102", "date": "2026-03-10",
                             "do_not_raise": True}]
    return s


@scenario
def cn_names():
    """Chinese course names and codes: 第N周 / 第N讲 modules, full-width punctuation, Asia/Shanghai."""
    tz = "Asia/Shanghai"
    user = {"id": 8001, "name": "测试同学", "short_name": "测试", "sortable_name": "测试同学",
            "locale": "zh-Hans", "effective_locale": "zh-Hans", "time_zone": "Beijing"}
    s = School("cn_names", tz, dt.datetime(2026, 3, 25, 20, 0, tzinfo=ZoneInfo(tz)), user,
               "Week 5 of a Chinese semester, week inferred from modules. Config codes are what the current doctor "
               "derives from these course_code values: MA1205, '3' (from 大学英语3) and C4403 (no letters or digits). "
               "Modules use 第5周, 第五周 Unit 4 and 第5讲; one weight uses a full-width ％.",
               created=dt.datetime(2026, 2, 10, 9, 0, tzinfo=ZoneInfo(tz)))
    term = {"id": 601, "name": "2025-2026学年第二学期", "start_at": "2026-02-22T16:00:00Z", "end_at": "2026-06-28T15:59:00Z"}

    def start(n):
        d = dt.date(2026, 2, 23) + dt.timedelta(days=7 * (n - 1))
        return s.at(d.month, d.day, 0, 0)

    ma = s.course(4401, "高等数学（二）", "（2025-2026-2）-MA1205-02", term)
    s.assignment(ma, "作业4（10%）", due=s.at(3, 20), points=10, types=("online_upload",),
                 sub={"state": "graded", "submitted": s.at(3, 20, 21, 5), "score": 9, "graded": s.at(3, 23, 10, 0),
                      "file": "作业4.pdf"})
    hw5 = s.assignment(ma, "作业5（10％）", due=s.at(3, 27), points=10, exts=("pdf",))
    quiz2 = s.assignment(ma, "小测2", due=s.at(3, 26, 19, 0), points=5, types=("online_quiz",), quiz=True, attempts=1)
    s.assignment(ma, "期中考试", points=100, types=("on_paper",))
    matopics = ["不定积分", "定积分", "微积分基本定理", "换元积分法", "定积分的应用", "反常积分", "微分方程"]
    for n, topic in enumerate(matopics, 1):
        items = [("File", f"第{n}周 {topic}.pdf", {}), ("Page", f"第{n}周 习题说明", {})]
        if n == 5:
            items += [("Assignment", "作业5（10％）", {"assignment": hw5}), ("Quiz", "小测2", {"assignment": quiz2})]
        s.module(ma, f"第{n}周 {topic}", items, unlock=start(n) if n >= 6 else None, locked=n >= 6)

    en = s.course(4402, "大学英语（三）", "大学英语3", term)
    s.assignment(en, "口语打卡 第4周", due=s.at(3, 22), points=2, types=("online_upload",))
    s.assignment(en, "Unit 4 写作任务", due=s.at(3, 29), points=20, types=("online_text_entry",))
    s.assignment(en, "期末口试（30%）", points=30, types=("on_paper",))
    weeks = ["第一周 课程介绍", "第二周 Unit 1 Campus Life", "第三周 Unit 2 Friendship", "第四周 Unit 3 Technology",
             "第五周 Unit 4 Food and Culture", "第六周 Unit 5 Travel"]
    for n, label in enumerate(weeks, 1):
        if n == 1:
            items = [("Page", "课程介绍与考核方式", {})]
        else:
            k = n - 1
            items = [("Page", f"{label.split()[0]} 学习任务", {}),
                     ("File", f"Unit {k} 课文讲解.pptx",
                      {"ctype": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}),
                     ("ExternalUrl", f"Unit {k} 听力音频", {"url": f"https://video.example/english/unit{k}"})]
        s.module(en, label, items, unlock=start(n) if n == 6 else None, locked=n == 6)

    jl = s.course(4403, "军事理论", "军事理论", term)
    q3 = s.assignment(jl, "第3讲 课后测验", due=s.at(3, 24), points=10, types=("online_quiz",), quiz=True,
                      sub={"state": "graded", "submitted": s.at(3, 24, 20, 30), "score": 10})
    q5 = s.assignment(jl, "第5讲 课后测验", due=s.at(3, 31), points=10, types=("online_quiz",), quiz=True)
    s.assignment(jl, "课程论文（50%）", due=s.at(4, 10), points=50, exts=("docx", "pdf"))
    jtopics = ["中国国防", "国家安全", "军事思想", "现代战争", "信息化装备"]
    for n, topic in enumerate(jtopics, 1):
        items = [("File", f"第{n}讲 课件.pdf", {}),
                 ("ExternalUrl", f"第{n}讲 教学视频", {"url": f"https://video.example/junli/{n}"})]
        if n == 3:
            items.append(("Quiz", "第3讲 课后测验", {"assignment": q3}))
        if n == 5:
            items.append(("Quiz", "第5讲 课后测验", {"assignment": q5}))
        s.module(jl, f"第{n}讲 {topic}", items)

    s.announcement(ma, "关于期中考试时间的通知", s.at(3, 24, 10, 0),
                   "<p>期中考试定于第 9 周周四（4 月 23 日）下午 2:00，地点另行通知。</p>", (9401, "李老师"))
    s.announcement(en, "第五周口语打卡提醒", s.at(3, 23, 8, 0), "<p>请在周日 23:59 前完成本周口语打卡。</p>", (9402, "王老师"))
    s.announcement(jl, "第5讲 教室调整", s.at(3, 19, 15, 0), "<p>第5讲改在东区 201 教室。</p>", (9403, "赵老师"))
    s.conversation(ma, "作业5第3题疑问", s.at(3, 25, 9, 30), "第3题的积分区间应为 [0, π]，已更正。",
                   [(8001, "测试同学"), (9401, "李老师")])
    s.event(ma, "习题课", s.at(3, 26, 14, 0), s.at(3, 26, 15, 40), "东区 305")
    s.event(en, "口语测试", s.at(4, 2, 10, 0), s.at(4, 2, 11, 0), "外语楼 210")

    s.config = base_config(s, None, {"name": "2025-2026学年第二学期", "start": "2026-02-23", "end": "2026-06-28",
                                     "week1_monday": None, "break": None, "week_source": None},
                           [{"id": 4401, "code": "MA1205", "name": "高等数学（二）", "section": None, "weekday": None},
                            {"id": 4402, "code": "3", "name": "大学英语（三）", "section": None, "weekday": None},
                            {"id": 4403, "code": "C4403", "name": "军事理论", "section": None, "weekday": None}],
                           tz, tz, user)
    s.state["mood"] = [{"date": "2026-03-24", "word": "累", "level": "落后", "note": None}]
    s.state["last_done"] = "2026-03-19T12:00:00Z"
    return s


def main(argv):
    names = argv or sorted(SCENARIOS)
    for n in names:
        print("wrote", SCENARIOS[n]().dump())


if __name__ == "__main__":
    main(sys.argv[1:])
