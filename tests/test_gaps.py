"""给 AI 看的「还差 N 件」：只在命令输出里，学生的周报页面上不出现；补上了就不再列，试过补不上的 7 天内不再列。

us_quarter：MATH3B、WRIT2 的模块按题目分，不按周分。
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")


class Gaps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sc = mockcanvas.Scenario("us_quarter")
        cls.mock = mockcanvas.MockCanvas(cls.sc).start()
        cls.home = harness.FakeHome("gaps")
        cls.home.seed(cls.sc, cls.mock.base_url)
        cls.day, cls.now = cls.sc.meta["date"], cls.sc.meta["now"]
        r = cls.coach(["collect", "--touch"])
        assert r.code in (0, 1), r.stdout + r.stderr
        w = cls.coach(["study", "--write"])
        assert w.code in (0, 1), w.stdout + w.stderr
        cls.plan_out = w.stdout

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()
        cls.home.cleanup()

    @classmethod
    def coach(cls, args):
        return harness.run_coach(cls.home, args + ["--date", cls.day], TOOLS, now=cls.now, ports=(cls.mock.port,))

    def gaps(self):
        r = self.coach(["status", "--json"])
        self.assertEqual(r.code, 0, r.stdout + r.stderr)
        return {g["key"] for g in r.json().get("todo_for_ai") or []}

    def busy_none_courses(self):
        r = self.coach(["study", "--json"])
        p = r.json()
        p = p.get("plan") or p
        return [c["code"] for c in p["study"]["courses"]
                if c["detect"] == "none" and (c["deadline_related"] or c["todo"] or c["notes"])]

    def test_1_模块不按周分的课在命令输出里_不在学生页面上(self):
        codes = self.busy_none_courses()
        self.assertTrue(codes, "us_quarter 应该有模块不按周分、这周又有事的课")
        self.assertIn("## 还差", self.plan_out)
        keys = self.gaps()
        for code in codes:
            self.assertIn(f"outline:{code}", keys)
        with open(os.path.join(self.home.root, "本周清单.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("还差", html)

    def test_2_读不到课程说明的_七天内不再列(self):
        code = self.busy_none_courses()[0]
        r = self.coach(["outline", code, "--url", "https://outline.example.invalid/unit"])  # 测试里不准联网：等于打不开
        self.assertEqual(r.code, 1, r.stdout + r.stderr)
        self.assertNotIn(f"outline:{code}", self.gaps())

    def test_3_有了每周安排表就不再列(self):
        codes = self.busy_none_courses()
        code = codes[-1]
        table = os.path.join(self.home.dir, f"{code}.json")
        with open(table, "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "course": code, "weeks": {"1": "a", "2": "b", "3": "c"}}, f)
        self.assertEqual(self.coach(["outline", code, "--file", table]).code, 0)
        self.assertNotIn(f"outline:{code}", self.gaps())


if __name__ == "__main__":
    unittest.main()
