"""只放考试的站、认不出这周内容的课（10-07 两份范例周报都出过「这周看什么请打开课程主页确认」，那张卡还是个考试站）。

考试站（「In-semester Test for: MECO6936」）：考试时间照样进每天和雷达；没有「这周要学的」卡片，不推荐做学习页，
「还差」里也不给它列事。认不出这周内容的课：卡片上只说情况，不叫学生去主页看。
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")
sys.path.insert(0, TOOLS)
from cc_courses import looks_like_exam_site  # noqa: E402


class Names(unittest.TestCase):
    def test_考试站的名字(self):
        for n in ("In-semester Test for: MECO6936", "Final Exam for: ECON1001", "MATH1001 Exam Site", "Online quiz site"):
            self.assertTrue(looks_like_exam_site(n), n)
        for n in ("MECO6936 Social Media Communication", "Assessment for Learning (EDUC6010)", "Exam Preparation Workshop", "", None):
            self.assertFalse(looks_like_exam_site(n), n)


class Scenario(unittest.TestCase):
    """au_semester：挑一门这周有截止的课，把它在 config 里的名字改成考试站的样子，看周报怎么处理它。"""
    SC = "au_semester"

    @classmethod
    def setUpClass(cls):
        cls.sc = mockcanvas.Scenario(cls.SC)
        cls.mock = mockcanvas.MockCanvas(cls.sc).start()
        cls.home = harness.FakeHome("exam-site")
        cls.home.seed(cls.sc, cls.mock.base_url)
        cls.day, cls.now = cls.sc.meta["date"], cls.sc.meta["now"]
        r = cls.coach(["collect", "--touch"])
        assert r.code in (0, 1), r.stdout + r.stderr
        before = cls.coach(["study", "--json"]).json()
        before = before.get("plan") or before
        cls.CODE = next(x["course"] for x in before["deadlines"] if not x.get("overdue"))
        cls.DUE = next(x["item"] for x in before["deadlines"] if x["course"] == cls.CODE and not x.get("overdue"))
        cfgp = os.path.join(cls.home.archive, "config.json")
        with open(cfgp, encoding="utf-8") as f:
            cfg = json.load(f)
        for c in cfg["courses"]:
            if c["code"] == cls.CODE:
                c["name"] = f"In-semester Test for: {cls.CODE}"
        with open(cfgp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
        w = cls.coach(["study", "--write"])
        assert w.code in (0, 1), w.stdout + w.stderr
        cls.out = w.stdout
        with open(os.path.join(cls.home.root, "本周清单.html"), encoding="utf-8") as f:
            cls.html = f.read()
        cls.plan = cls.coach(["study", "--json"]).json()
        cls.plan = cls.plan.get("plan") or cls.plan
        cls.status = cls.coach(["status", "--json"]).json()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()
        cls.home.cleanup()

    @classmethod
    def coach(cls, args):
        return harness.run_coach(cls.home, args + ["--date", cls.day], TOOLS, now=cls.now, ports=(cls.mock.port,))

    def test_考试站没有卡片_也不推荐做学习页(self):
        c = next(x for x in self.plan["study"]["courses"] if x["code"] == self.CODE)
        self.assertTrue(c.get("exam_site"))
        self.assertNotIn("learn_hint", c)
        self.assertNotEqual((self.plan["learn"].get("suggest") or {}).get("course"), self.CODE)
        self.assertNotIn(f'<p class="code">{self.CODE}', self.html, "这周要学的里没有它的卡片")
        self.assertIn(f"· {len(self.plan['study']['courses']) - 1} 门课", self.plan["range"], "门数不算考试站")

    def test_考试站的截止照样在(self):
        self.assertIn(self.DUE, [x["item"] for x in self.plan["deadlines"] if x["course"] == self.CODE])
        self.assertIn(self.DUE, self.html, "考试时间照样出现在每天或雷达里")

    def test_还差里不给考试站列事(self):
        keys = {g["key"] for g in self.status.get("todo_for_ai") or []}
        self.assertFalse([k for k in keys if k.endswith(f":{self.CODE}") or f":{self.CODE}:" in k], keys)


class NotWeekly(unittest.TestCase):
    """us_quarter：MATH3B、WRIT2 的模块按题目分、没有课程说明表，卡片上只说情况。"""

    @classmethod
    def setUpClass(cls):
        cls.sc = mockcanvas.Scenario("us_quarter")
        cls.mock = mockcanvas.MockCanvas(cls.sc).start()
        cls.home = harness.FakeHome("not-weekly")
        cls.home.seed(cls.sc, cls.mock.base_url)
        cls.day, cls.now = cls.sc.meta["date"], cls.sc.meta["now"]
        r = harness.run_coach(cls.home, ["collect", "--touch", "--date", cls.day], TOOLS, now=cls.now, ports=(cls.mock.port,))
        assert r.code in (0, 1), r.stdout + r.stderr
        w = harness.run_coach(cls.home, ["study", "--write", "--date", cls.day], TOOLS, now=cls.now, ports=(cls.mock.port,))
        assert w.code in (0, 1), w.stdout + w.stderr
        with open(os.path.join(cls.home.root, "本周清单.html"), encoding="utf-8") as f:
            cls.html = f.read()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()
        cls.home.cleanup()

    def test_只说情况不叫学生去主页看(self):
        self.assertIn("上没按周排，这周讲什么还没对上。", self.html)
        for bad in ("请打开课程主页", "主页确认", "/modules\""):
            self.assertNotIn(bad, self.html)


if __name__ == "__main__":
    unittest.main()
