"""作业页没写日期、公告里写明了的，日期要进雷达（S20 / G06）。

审计里真出过事的那条：一个 20% 的测验 9 天后截止，日期白纸黑字写在公告里，
作业页没有 due_at，于是那行没有日期，撞车检测、最急一条、每门课下一条全都看不见它。

这里钉三件事：
1. 公告里写明日期的，那一行拿到日期，并且仍然留在「待确认」区（出处写公告标题）。
2. 一条公告里出现多个都落在窗口内的日期，算含糊，那一行必须仍然「没写日期」。
3. 日期解析只认写明月份名或 ISO 的写法；9/25 这种纯数字的、Week 8 这种相对说法，都不认。
"""
import datetime as dt
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

sys.path.insert(0, os.path.join(harness.code_dir(), "tools"))
import cc_time  # noqa: E402


def radar_rows(scenario="au_semester"):
    """跑一次 radar --json，拿回 deadline 行。"""
    data = harness.run_scenario(scenario)
    for step in data["steps"]:
        if str(step.get("id") or step.get("step") or "").startswith("05_radar_json"):
            out = step.get("stdout")
            return json.loads(out) if isinstance(out, str) else out
    raise AssertionError("没找到 05_radar_json 这一步：" + str([s.get("id") for s in data["steps"]][:6]))


class AnnouncementDate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = radar_rows()["rows"]

    def row(self, needle):
        hits = [r for r in self.rows if needle in (r.get("item") or "")]
        self.assertEqual(1, len(hits), f"{needle} 应该只有一行，实际 {len(hits)} 行")
        return hits[0]

    def test_公告里写明日期的进了雷达(self):
        r = self.row("Final Exam")
        self.assertIn("04-03", r["when"], "公告写了 3 April 2026 9:15 am")
        self.assertIn("09:15", r["when"])
        self.assertEqual(9, r["days_left"])
        self.assertFalse(r["undated"], "有了日期就不再算「没写日期」，否则撞车和最急都看不见它")
        self.assertTrue(r["pending"], "日期是从公告推的，必须留在待确认区")
        self.assertIn("公告", r["src"])

    def test_一条公告里多个日期算含糊(self):
        r = self.row("Research Participation")
        self.assertIsNone(r["days_left"], "公告里 1 April 和 8 April 都在窗口内，不许猜")
        self.assertIn("没写日期", r["when"])
        self.assertTrue(r["undated"])

    def test_原本就有日期的不受影响(self):
        r = self.row("Case Study Report")
        self.assertIn("04-02", r["when"])
        self.assertIn("Canvas due_at", r["src"], "Canvas 自己有日期时不看公告")


class ParseText(unittest.TestCase):
    ref = dt.date(2026, 9, 16)

    def parse(self, s):
        return cc_time.text_datetimes(s, self.ref)

    def test_认得出写明的写法(self):
        self.assertEqual([(dt.date(2026, 9, 25), "18:30")],
                         self.parse("our IST will take place at 6:30pm on 25 September (Friday) 2026"))
        self.assertEqual([(dt.date(2026, 9, 25), "23:59")],
                         self.parse("Due Week 8, Friday Evening (25 September @11.59pm)"))
        self.assertEqual([(dt.date(2026, 10, 4), "23:59")], self.parse("submit by 2026-10-04 23:59"))
        self.assertEqual([(dt.date(2026, 9, 25), "18:30")], self.parse("The exam is on September 25, 2026 at 18:30"))

    def test_含糊的一律不认(self):
        self.assertEqual([], self.parse("test on 9/25 at 6:30pm"), "纯数字日期各国月日顺序不同")
        self.assertEqual([], self.parse("scheduled to take place during Week 8"), "相对说法不是日期")
        self.assertEqual([], self.parse("this format has been used since semester 2 2024"), "不是日期")
        self.assertEqual([], self.parse("no dates here"))

    def test_没写年份时取最近的一年(self):
        self.assertEqual([(dt.date(2026, 10, 4), None)], self.parse("due 4 October"))
        self.assertEqual([(dt.date(2027, 1, 5), None)], self.parse("due 5 January"), "跨年取最近的那一个")


if __name__ == "__main__":
    unittest.main()
