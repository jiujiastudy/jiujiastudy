"""手动记 deadline 时先和 Canvas 对一遍（10-07 实验：弱一点的模型从往年的模板里读到「11 月 3 日周日」就记进了雷达，
Canvas 上写的是 11 月 8 日，2026 年的 11 月 3 日是周二）。同一个作业日期对不上 → 不记，退出码 1，说清哪里对不上；
同一天 → 不重复记；确定 Canvas 写错了才 --force。
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")
sys.path.insert(0, TOOLS)
import cc_record  # noqa: E402


class SameItem(unittest.TestCase):
    def test_像不像同一个作业(self):
        self.assertTrue(cc_record.same_item("Mixed podcast and documentation due (final assignment)",
                                            "Final Assignment mixed podcast + supporting documentation (45%) due at the end of Week 13"))
        self.assertTrue(cc_record.same_item("Essay", "4. Essay"))
        self.assertFalse(cc_record.same_item("Quiz 5", "Quiz 6"), "编号对不上")
        self.assertFalse(cc_record.same_item("Week 5 quiz", "Interview (audio recording) + transcript + reflection 20% due end of Week 5"))
        self.assertFalse(cc_record.same_item("Studio pitch", "Lab Report (25%)"))


class PickTheRightOne(unittest.TestCase):
    """像的作业不止一条：日期对得上的优先，再挑最像的（10-07：closing date 被拿去和 Pitch 比了）。"""

    def setUp(self):
        import datetime as dt
        import types
        import cc_collect
        self.dt, self.cc_collect, self.saved = dt, cc_collect, cc_collect.load_snapshot
        tz = dt.timezone(dt.timedelta(hours=11))
        self.ctx = types.SimpleNamespace(clock=types.SimpleNamespace(course_date=lambda t: t.astimezone(tz).date()))
        snap = {"assignments": {
            "1": {"course": "MECO69362", "name": "Assignment: Social Media Campaign Pitch (10%)", "due_at": "2026-09-24T13:59:59Z"},
            "2": {"course": "MECO69362", "name": "Assignment: Social Media Campaign (40%)", "due_at": "2026-11-08T12:59:59Z"}}}
        cc_collect.load_snapshot = lambda ctx: snap

    def tearDown(self):
        self.cc_collect.load_snapshot = self.saved

    def test_挑最像的那条(self):
        hit = cc_record.canvas_conflict(self.ctx, "MECO69362", "Social Media Campaign closing date", self.dt.date(2026, 11, 18))
        self.assertEqual(hit[0], "Assignment: Social Media Campaign (40%)")

    def test_日期对得上的优先(self):
        hit = cc_record.canvas_conflict(self.ctx, "MECO69362", "Social Media Campaign Pitch slides", self.dt.date(2026, 11, 8))
        self.assertEqual(hit, ("Assignment: Social Media Campaign (40%)", self.dt.date(2026, 11, 8)))


class Command(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sc = mockcanvas.Scenario("au_semester")
        cls.mock = mockcanvas.MockCanvas(cls.sc).start()
        cls.home = harness.FakeHome("guard")
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

    def listed(self):
        return self.coach(["record", "deadline", "--list"]).stdout

    def test_日期对不上不记_同一天不重复记_force才记(self):
        r = self.coach(["record", "deadline", "Lab report", "--course", "PSYC2012", "--due", "2026-04-20", "--source", "Ed（AI 读到的）"])
        self.assertEqual(r.code, 1, r.stdout + r.stderr)
        out = r.stdout + r.stderr
        self.assertIn("对不上", out)
        canvas_day = re.search(r"截止 (\d{4}-\d{2}-\d{2})", out).group(1)
        self.assertNotIn("Lab report", self.listed())

        same = self.coach(["record", "deadline", "Lab report", "--course", "PSYC2012", "--due", canvas_day])
        self.assertEqual(same.code, 0, same.stdout + same.stderr)
        self.assertIn("不用再记", same.stdout)
        self.assertNotIn("Lab report", self.listed())

        forced = self.coach(["record", "deadline", "Lab report", "--course", "PSYC2012", "--due", "2026-04-20", "--force"])
        self.assertEqual(forced.code, 0, forced.stdout + forced.stderr)
        self.assertIn("Lab report", self.listed())
        self.coach(["record", "deadline", "--remove", "Lab report"])

    def test_不相干的事照记(self):
        r = self.coach(["record", "deadline", "Field trip consent form", "--course", "PSYC2012", "--due", "2026-03-30"])
        self.assertEqual(r.code, 0, r.stdout + r.stderr)
        self.assertIn("Field trip consent form", self.listed())
        self.coach(["record", "deadline", "--remove", "Field trip consent form"])


if __name__ == "__main__":
    unittest.main()
