"""课外的 deadline（品牌交稿、比赛截止）：record deadline 不写 --course 记成「课外」；照样算进 72 小时条数和撞车；
它当最急的一条时，第一步和过载建议不按课说。

见 docs/DBS逐个改法.md「还没定」第 17 条和「要写程序的全部」第 12 条。
"""
import datetime as dt
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")
sys.path.insert(0, TOOLS)
import cc_radar  # noqa: E402
import cc_state  # noqa: E402

ITEM = "品牌合作视频交稿"


class Wording(unittest.TestCase):
    def test_第一步不按课说(self):
        self.assertIn("对方给的要求", cc_radar.first_step_for({"origin": "manual", "extra": True}))
        self.assertIn("作业页或课程公告", cc_radar.first_step_for({"origin": "manual"}), "课上的手动 deadline 照旧")

    def test_过载时问对方能不能晚几天(self):
        top = {"course": "课外", "item": ITEM, "when": "10-12 周日 18:00", "rel": "明天", "extra": True}
        self.assertIn("问对方能不能晚几天", cc_state.advise("过载", top, None, None, None, None))
        top.pop("extra")
        self.assertIn("问能不能延期", cc_state.advise("过载", top, None, None, None, None))


class Command(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sc = mockcanvas.Scenario("au_semester")
        cls.mock = mockcanvas.MockCanvas(cls.sc).start()
        cls.home = harness.FakeHome("extra")
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

    def count72(self):
        ev = self.coach(["status", "--json"]).json()["state_eval"]
        m = next((re.search(r"72 小时内有 (\d+) 条", s) for s in ev["signals"] if "72 小时内" in s), None)
        return int(m.group(1)) if m else 0

    def test_不写课也能记_照样算进72小时(self):
        before = self.count72()
        due = (dt.date.fromisoformat(self.day) + dt.timedelta(days=1)).isoformat()
        r = self.coach(["record", "deadline", ITEM, "--due", due, "--time", "09:00"])  # 比明天下午的 Lab Report 早，当最急的一条
        self.assertEqual(0, r.code, r.stdout + r.stderr)
        self.assertIn("课外", r.stdout)
        with open(os.path.join(self.home.archive, "state.json"), encoding="utf-8") as f:
            row = next(m for m in json.load(f)["manual_deadlines"] if m["item"] == ITEM)
        self.assertEqual("课外", row["course"])
        self.assertEqual(before + 1, self.count72())
        md = self.coach(["radar", "--json"]).json()["markdown"]
        urgent = md.split("## 🔴 最急的一条", 1)[1].split("## ", 1)[0]
        self.assertIn(ITEM, urgent)
        self.assertIn("对方给的要求", urgent, "课外那条的第一步不按课说")


if __name__ == "__main__":
    unittest.main()
