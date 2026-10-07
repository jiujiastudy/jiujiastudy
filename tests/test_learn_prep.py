"""做学习页之前：数课件页数；学生要学习页就是同意读这门课的课件，learn prep 直接打开、不再单独问
（10-07 发起人：方便学生最重要；学生明说过不读的照旧不读）；learn prep / check 两个命令。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")
sys.path.insert(0, TOOLS)
import cc_learn  # noqa: E402


class Display(unittest.TestCase):
    def test_显示用课程名里的代码(self):
        self.assertEqual(cc_learn.display_code({"code": "MECO69362", "name": "MECO6936 Social Media Communication"}), "MECO6936")
        self.assertEqual(cc_learn.display_code({"code": "ACCT1101", "name": "ACCT1101 Accounting"}), "ACCT1101")
        self.assertEqual(cc_learn.display_code({"code": "MATH3B", "name": "Calculus"}), "MATH3B")


class Pages(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="stc-pages-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_pptx_数幻灯片(self):
        p = os.path.join(self.dir, "a.pptx")
        with zipfile.ZipFile(p, "w") as z:
            for i in (1, 2, 3):
                z.writestr(f"ppt/slides/slide{i}.xml", "<p/>")
            z.writestr("ppt/slides/_rels/slide1.xml.rels", "<r/>")
        self.assertEqual(cc_learn.count_pages(p), 3)

    def test_pdf_没有_pypdf_也能数页对象(self):
        p = os.path.join(self.dir, "a.pdf")
        with open(p, "wb") as f:
            f.write(b"%PDF-1.4\n1 0 obj<</Type /Pages /Kids [2 0 R 3 0 R]>>\n2 0 obj<</Type /Page>>\n3 0 obj<</Type/Page>>\n%%EOF")
        with mock.patch.dict(sys.modules, {"pypdf": None}):
            self.assertEqual(cc_learn.count_pages(p), 2)

    def test_数不出来就不写页数(self):
        p = os.path.join(self.dir, "a.docx")
        open(p, "wb").close()
        self.assertIsNone(cc_learn.count_pages(p))
        self.assertIsNone(cc_learn.count_pages(os.path.join(self.dir, "没有.pdf")))


class Command(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sc = mockcanvas.Scenario("au_semester")
        cls.mock = mockcanvas.MockCanvas(cls.sc).start()
        cls.home = harness.FakeHome("prep")
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

    def test_prep_要学习页就直接打开读课件_不再问(self):
        r = self.coach(["learn", "prep", "DSGN3402"])
        self.assertEqual(r.code, 0, r.stdout + r.stderr)
        self.assertIn("已经替 DSGN3402 打开读课件（不再单独问）", r.stdout)
        self.assertNotIn("要读吗", r.stdout)
        d = self.coach(["learn", "prep", "DSGN3402", "--json"]).json()
        self.assertEqual(d["week"], 5)
        self.assertTrue(d["materials_ai"])
        self.assertFalse(d["opened"], "已经打开过，第二次不再说")
        self.assertNotIn("ask", d)
        self.assertIn("交给 AI 读", self.coach(["config", "course", "DSGN3402"]).stdout)

    def test_prep_学生明说过不读就不读(self):
        self.assertEqual(self.coach(["config", "course", "PSYC2012", "--materials-ai", "off"]).code, 0)
        r = self.coach(["learn", "prep", "PSYC2012", "--json"])
        self.assertEqual(r.code, 0, r.stdout + r.stderr)
        d = r.json()
        self.assertTrue(d["declined"])
        self.assertFalse(d["materials_ai"])
        self.assertFalse(d["opened"])

    def test_check_没有清单是提醒_有了就说能用(self):
        r = self.coach(["learn", "check", "ACCT1101"])
        self.assertEqual(r.code, 1)
        self.assertIn("还没有", r.stdout)
        page = os.path.join(self.home.root, "ACCT1101", "产出", "W5.html")
        os.makedirs(os.path.dirname(page), exist_ok=True)
        open(page, "w", encoding="utf-8").close()
        m = {"schema": 1, "course": "ACCT1101", "week": "2026-W13", "page": page, "made_at": "2026-03-25T07:00:00+08:00",
             "data_as_of": "2026-03-24T23:00:00+00:00", "promise": "x", "minutes_total": 30,
             "blocks": [{"id": "b1", "label": "第 1 节", "minutes": 30, "anchor": "#s1"}]}
        os.makedirs(cc_learn.manifest_dir(self.home.archive, "2026-W13"), exist_ok=True)
        with open(cc_learn.manifest_path(self.home.archive, "2026-W13", "ACCT1101"), "w", encoding="utf-8") as f:
            json.dump(m, f)
        r = self.coach(["learn", "check", "ACCT1101"])
        self.assertEqual(r.code, 0, r.stdout + r.stderr)
        self.assertIn("能用：1 块 30 分钟", r.stdout)

    def test_没有这门课(self):
        self.assertEqual(self.coach(["learn", "prep", "NOPE"]).code, 2)

    def test_努力程度只在第一次做学习页时提一次(self):
        home = harness.FakeHome("prep-tip")
        try:
            home.seed(self.sc, self.mock.base_url)
            run = lambda a: harness.run_coach(home, a + ["--date", self.day], TOOLS, now=self.now, ports=(self.mock.port,))  # noqa: E731
            self.assertIn(run(["collect", "--touch"]).code, (0, 1))
            first = run(["learn", "prep", "DSGN3402", "--json"]).json()
            self.assertIn("Extra high", first["effort_tip"] or "")
            again = run(["learn", "prep", "ACCT1101", "--json"]).json()
            self.assertIsNone(again["effort_tip"], "只提一次，换一门课也不再提")
        finally:
            home.cleanup()


class Order(unittest.TestCase):
    """/jj-learn 不说哪门就全做：最急的在前，考试站不做，学习页做完以后课程又多了东西的排在后面重做。"""

    def test_顺序(self):
        courses = [
            {"code": "FAR", "before_class": [], "todo": []},
            {"code": "BUSY", "before_class": [1, 2], "todo": [3]},
            {"code": "SOON", "before_class": [], "todo": []},
            {"code": "EXAM", "exam_site": True},
            {"code": "DONE", "learn": {"changed": []}},
            {"code": "STALE", "learn": {"changed": [{"title": "Week 9 slides"}]}},
        ]
        rows = [{"course": "SOON", "item": "Essay", "days_left": 2}, {"course": "FAR", "item": "Report", "days_left": 20}]
        got = [x["course"] for x in cc_learn.learn_order(courses, rows)]
        self.assertEqual(["SOON", "BUSY", "FAR", "STALE"], got)
        self.assertEqual("SOON", cc_learn.suggest_first(courses, rows, None)["course"], "推荐的那门就是全做时的第一门")


if __name__ == "__main__":
    unittest.main()
