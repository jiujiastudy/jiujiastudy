"""各学校的 Moodle 不一样：脚本只做各家都一样的部分，认不出的交给 AI（10-07 发起人：「moodle 我们做我们能做的，剩下的让 ai 自己处理」）。

10-07 在 Moodle 官方演示站（Mount Orange，Moodle 5.3）上把整条链跑了一遍，找到的几处在这里守住：
- 几门常设课 2009 年开课、2028 年结课，学期被推成十九年，周报写「第 917 周」→ 只拿日期合理的课推学期，周数超过一年就当不知道；
- 作业本来没设日期，却说「日历里关掉了课程事件」、叫学生去改设置 → 只说情况，日期标待确认，AI 去读作业页；
- 一门课的成绩页 404，被报成「这门课打不开了（可能退课）」→ 成绩页没开放就跳过；
- 状态那句「去公告或课程页确认时间」是叫学生自己去查 → 改成 AI 去找。
"""
import datetime as dt
import io
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

sys.path.insert(0, os.path.join(harness.code_dir(), "tools"))
import cc_external  # noqa: E402
import cc_gaps  # noqa: E402
import cc_state  # noqa: E402
import mdl_collect  # noqa: E402
from cc_time import Clock, monday_of  # noqa: E402

UTC = dt.timezone.utc


def ts(d):
    return int(dt.datetime.combine(d, dt.time(9, 0), tzinfo=UTC).timestamp())


class Term(unittest.TestCase):
    def test_拿来推学期的课(self):
        today = dt.date(2026, 10, 7)
        p = mdl_collect._plausible_term
        self.assertTrue(p(dt.date(2026, 7, 27), dt.date(2026, 11, 20), today), "这学期的课")
        self.assertTrue(p(dt.date(2026, 2, 23), dt.date(2026, 12, 4), today), "全年课也算")
        self.assertTrue(p(dt.date(2026, 8, 3), None, today), "没写结课日的新课")
        self.assertFalse(p(dt.date(2009, 3, 21), dt.date(2028, 6, 19), today), "常设课：开了十九年")
        self.assertFalse(p(dt.date(2015, 1, 5), None, today), "很早开、没写结课日")
        self.assertFalse(p(None, None, today))

    def test_建档时常设课照样跟踪_但不拿来推学期(self):
        today = Clock({"course_tz": "UTC", "user_tz": "UTC"}).now_utc().date()
        this_term = today - dt.timedelta(days=70)

        class Api:
            host = "https://moodle.example.edu"

            def ajax(self, method, args):
                return {"courses": [
                    {"id": 62, "fullname": "Psychology in Cinema", "shortname": "PSYCHCINE", "visible": True,
                     "startdate": ts(dt.date(2009, 3, 21)), "enddate": ts(today + dt.timedelta(days=600))},
                    {"id": 80, "fullname": "Dementia care", "shortname": "DEMENTIACARE", "visible": True,
                     "startdate": ts(this_term), "enddate": ts(today + dt.timedelta(days=40))},
                    {"id": 6, "fullname": "Class and Conflict in World Cinema", "shortname": "CINE", "visible": True,
                     "startdate": ts(this_term + dt.timedelta(days=6)), "enddate": 0},
                ]}

        cfg, _ = mdl_collect.bootstrap(tempfile.gettempdir(), Api.host, Api(), {"id": 1}, tz="UTC")
        self.assertEqual({"PSYCHCINE", "DEMENTIACARE", "CINE"}, {c["code"] for c in cfg["courses"]})
        self.assertEqual(this_term.isoformat(), cfg["term"]["start"])
        self.assertEqual(monday_of(this_term).isoformat(), cfg["term"]["week1_monday"])
        self.assertLess(Clock(cfg).week_no(today), 20)

    def test_周数超过一年就当不知道(self):
        c = Clock({"course_tz": "UTC", "user_tz": "UTC",
                   "term": {"start": "2009-03-21", "end": "2028-06-19", "week1_monday": "2009-03-16", "week_source": "moodle"}})
        self.assertIsNone(c.week_no(dt.date(2026, 10, 7)), "不报「第 917 周」")
        self.assertEqual("周次待定", c.term_week(dt.date(2026, 10, 7)))
        ok = Clock({"course_tz": "UTC", "user_tz": "UTC", "term": {"week1_monday": "2026-07-27", "week_source": "moodle"}})
        self.assertEqual(11, ok.week_no(dt.date(2026, 10, 7)))


class Grades(unittest.TestCase):
    def test_成绩页没开放_不说退课(self):
        class Api:
            def page(self, path):
                raise urllib.error.HTTPError(path, 404, "Not Found", {}, io.BytesIO(b""))

        errors, old = [], [{"name": "Course Finale Big Quiz", "range": "0–100"}]
        cache = {"grades": {"80": old}}
        got = mdl_collect._grades(Api(), lambda label, fn, **kw: fn(), errors, "DEMENTIACARE", 80, cache, False)
        self.assertEqual(old, got, "满分和权重用上次读到的")
        self.assertEqual([], errors)

    def test_别的错照常报(self):
        class Api:
            def page(self, path):
                raise urllib.error.HTTPError(path, 500, "Server Error", {}, io.BytesIO(b""))

        with self.assertRaises(urllib.error.HTTPError):
            mdl_collect._grade_page(Api(), 80)


class CalendarEmpty(unittest.TestCase):
    def test_只说情况_不叫学生改设置(self):
        one = mdl_collect._empty_calendar_notes([("CHEMISTRY", 8)], 3)[0]
        self.assertTrue(one.startswith("CHEMISTRY：课里有 8 个作业/测验，但 Moodle 日历里这门课一个事件都没有"))
        self.assertIn("AI 去读作业页", one)
        self.assertNotIn("打开就能读到", one)
        allc = mdl_collect._empty_calendar_notes([("A", 2), ("B", 3)], 2)[0]
        self.assertIn("不叫学生去改设置", allc)


class Undated(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="stc-undated-")
        self.now = dt.datetime(2026, 10, 7, 3, 0, tzinfo=UTC)
        u = "https://school.moodle.example/mod/quiz/view.php?id={}"
        self.plan = {"deadlines": [
            {"when": "日期待确认", "course": "CHEMISTRY", "item": f"Quiz {i}", "status": "未交", "url": u.format(700 + i)}
            for i in range(1, 6)] + [
            {"when": "日期待确认", "course": "CHEMISTRY", "item": "Done quiz", "status": "已交 10-01 09:00", "url": u.format(799)},
            {"when": "10-12 周一 23:59", "course": "CHEMISTRY", "item": "Dated", "status": "未交", "url": u.format(798)},
            {"when": "Moodle 没写日期", "course": "PSYCHCINE", "item": "Reflective journal", "status": "未交",
             "url": "https://school.moodle.example/mod/assign/view.php?id=901"}]}

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_没日期还没交的_列出要读的作业页(self):
        got = {x["course"]: x for x in cc_gaps.undated_items(self.home, self.plan, self.now)}
        self.assertEqual({"CHEMISTRY", "PSYCHCINE"}, set(got))
        chem = got["CHEMISTRY"]
        self.assertIn("5 件", chem["text"])
        self.assertIn("view.php?id=701", chem["cmd"])
        self.assertIn("还有 2 件", chem["cmd"], "一门课最多点三页的网址")
        self.assertNotIn("id=799", chem["cmd"], "交了的不用补日期")
        self.assertNotIn("id=798", chem["cmd"])
        self.assertIn("record deadline", chem["cmd"])
        self.assertIn("moodle.md", chem["cmd"])

    def test_读过的页_7天内不再列(self):
        cc_external.record(self.home, "PSYCHCINE", "https://school.moodle.example/mod/assign/view.php?id=901", "ok", self.now)
        got = {x["course"] for x in cc_gaps.undated_items(self.home, self.plan, self.now)}
        self.assertNotIn("PSYCHCINE", got, "真没写日期的，读过一遍就不天天提")


class Advice(unittest.TestCase):
    def test_没写日期的考试_AI去找_不叫学生查(self):
        line = cc_state.advise("正常", None, {"course": "CHEMISTRY", "item": "Final exam", "days_left": None}, None, None, None)
        self.assertIn("我去公告和课程页找", line)
        self.assertNotIn("确认时间", line)


if __name__ == "__main__":
    unittest.main()
