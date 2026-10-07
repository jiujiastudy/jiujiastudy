"""课程说明的每周安排表：认出每周题目、存表读表，模块没按周分的课在周报上写「这周讲什么」。

起因：发起人的 MECO6941 Canvas 上没有按周分的模块，周报只会写「去课程主页确认」；USYD 的 unit outline 是公开页，
第 9 周那一行写着 "Beginnings, structure, production workshop"。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")
sys.path.insert(0, TOOLS)
import cc_outline  # noqa: E402

# USYD unit outline 的样子：前面一张作业表（周次和截止日期混在一起），后面才是每周安排表（周次一行、题目下一行）
USYD_LIKE = [
    "Assessment summary",
    "Podcast mini-review", "Week 01", "Due date : 09 Aug 2026 at 23:59",
    "Class pitch", "Week 07", "2 minutes presentation + 3 minutes q&a",
    "Final podcast", "Week 13", "Due date : 08 Nov 2026 at 23:59",
] + ["filler"] * 40 + [
    "Weekly schedule",
    "Week 01", "Introduction - phone recording, story ideas", "Lecture (1.5 hr)", "LO1",
    "Week 02", "Interviewing, writing for audio", "Lecture (1.5 hr)",
    "Week 08", "Consultations", "Lecture (1.5 hr)",
    "Week 09", "Beginnings, structure, production workshop", "Lecture (1.5 hr)", "LO4",
    "Week 09", "Beginnings, structure, production workshop", "Tutorial (2 hr)",
    "Week 10", "Sensitive subjects, copyright, audio effects", "Lecture (1.5 hr)",
]


class Extract(unittest.TestCase):
    def test_挑每周安排那一段_不要作业表里的截止日期(self):
        w = cc_outline.extract_weeks(USYD_LIKE)
        self.assertEqual(w["1"], "Introduction - phone recording, story ideas")
        self.assertEqual(w["9"], "Beginnings, structure, production workshop", "同一周两行一样的只留一个")
        self.assertNotIn("7", w, "作业表里的周次不算")
        self.assertFalse(any("Due date" in v for v in w.values()))

    def test_同一行写着题目的格式(self):
        lines = ["Week 1: Course overview", "Week 2 – Markets and prices", "Wk 3 | Elasticity | Reading: ch 3", "Week 4. Costs"]
        self.assertEqual(cc_outline.extract_weeks(lines),
                         {"1": "Course overview", "2": "Markets and prices", "3": "Elasticity", "4": "Costs"})

    def test_认出的周太少就交给_AI(self):
        self.assertEqual(cc_outline.extract_weeks(["Week 1: Intro", "Week 2: More"]), {})

    def test_网页变成一行一段(self):
        lines = cc_outline.text_lines("<table><tr><td>Week 09</td><td>Beginnings</td></tr></table><script>x=1</script>")
        self.assertEqual(lines, ["Week 09", "Beginnings"])


class Table(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="stc-outline-")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_存了能读_查得到这周_中文可选(self):
        t = cc_outline.build("MECO6941", {"9": "Beginnings, structure"}, "Unit outline", "https://x")
        t["weeks_zh"] = {"9": "开头、结构"}
        cc_outline.save(self.home, "MECO6941", t)
        got = cc_outline.load(self.home, "MECO6941")
        self.assertEqual(cc_outline.topic_for(got, 9), ("Beginnings, structure", "开头、结构"))
        self.assertIsNone(cc_outline.topic_for(got, 10))

    def test_格式不对或课程对不上就当没有(self):
        cc_outline.save(self.home, "A", {"schema": 1, "course": "B", "weeks": {"1": "x"}})
        self.assertIsNone(cc_outline.load(self.home, "A"))
        self.assertTrue(cc_outline.validate({"schema": 1, "course": "A", "weeks": {"one": "x"}}, "A"))
        self.assertIsNone(cc_outline.load(self.home, "没有这门"))


class Command(unittest.TestCase):
    """us_quarter：MATH3B 的模块按题目分，不按周分（第 3 周）。"""

    @classmethod
    def setUpClass(cls):
        cls.sc = mockcanvas.Scenario("us_quarter")
        cls.mock = mockcanvas.MockCanvas(cls.sc).start()
        cls.home = harness.FakeHome("outline")
        cls.home.seed(cls.sc, cls.mock.base_url)
        cls.day, cls.now = cls.sc.meta["date"], cls.sc.meta["now"]
        r = cls.coach(["collect", "--touch"])
        assert r.code in (0, 1), r.stdout + r.stderr

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()
        cls.home.cleanup()

    @classmethod
    def coach(cls, args):
        return harness.run_coach(cls.home, args + ["--date", cls.day], TOOLS, now=cls.now, ports=(cls.mock.port,))

    def math(self):
        r = self.coach(["study", "--json"])
        self.assertIn(r.code, (0, 1), r.stdout + r.stderr)
        p = r.json()
        return next(c for c in (p.get("plan") or p)["study"]["courses"] if c["code"] == "MATH3B")

    def test_有表就写这周讲什么_删了就退回原来那句(self):
        self.assertTrue(self.math()["gap"], "没表时照旧让学生去主页看")
        table = os.path.join(self.home.dir, "math.json")
        with open(table, "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "course": "MATH3B", "source": {"title": "Syllabus", "url": "https://x", "fetched_at": "2026-02-20T00:00:00+00:00"},
                       "weeks": {"2": "Limits", "3": "Derivatives and the chain rule"}, "weeks_zh": {"3": "导数和链式法则"}}, f)
        r = self.coach(["outline", "math3b", "--file", table])
        self.assertEqual(r.code, 0, r.stdout + r.stderr)
        c = self.math()
        self.assertIsNone(c["gap"])
        self.assertEqual(c["outline"], {"week": 3, "topic": "Derivatives and the chain rule", "topic_zh": "导数和链式法则"})
        shown = self.coach(["outline", "MATH3B"])
        self.assertIn("第 3 周：Derivatives and the chain rule（导数和链式法则）", shown.stdout)
        w = self.coach(["study", "--write"])
        self.assertIn(w.code, (0, 1), w.stdout + w.stderr)
        with open(os.path.join(self.home.root, "本周清单.html"), encoding="utf-8") as f:
            self.assertIn("这周讲：", f.read())
        self.assertEqual(self.coach(["outline", "MATH3B", "--remove"]).code, 0)
        self.assertTrue(self.math()["gap"])

    def test_没有这门课_表不对_都直接说(self):
        self.assertEqual(self.coach(["outline", "NOPE101"]).code, 2)
        bad = os.path.join(self.home.dir, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "course": "CHEM1A", "weeks": {"1": "x"}}, f)
        r = self.coach(["outline", "MATH3B", "--file", bad])
        self.assertEqual(r.code, 2)
        self.assertIn("course 和课程代码对不上", r.stdout + r.stderr)

    def test_没表时看一眼是提醒不是错(self):
        r = self.coach(["outline", "WRIT2"])
        self.assertEqual(r.code, 1)
        self.assertIn("还没有每周安排表", r.stdout)


if __name__ == "__main__":
    unittest.main()
