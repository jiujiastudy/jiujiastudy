"""今天到期的算不算进过载：72 小时条数和 7 天权重都算今天到期的；没日期的不算。"""
import datetime as dt
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

sys.path.insert(0, os.path.join(harness.code_dir(), "tools"))
import cc_state  # noqa: E402

TODAY = dt.date(2026, 9, 29)


def row(item, days, weight="20%", status="未交", origin="canvas"):
    return {"course": "ACCT1101", "item": item, "days_left": days, "weight": weight, "status": status, "origin": origin,
            "when": "", "rel": ""}


def evaluate(rows):
    ctx = types.SimpleNamespace(state={}, clock=None)
    return cc_state.evaluate(ctx, TODAY, None, rows)


class TodayCountsInOverload(unittest.TestCase):
    def test_今天到期的算进72小时条数(self):
        ev = evaluate([row("Quiz", 0), row("Essay", 1), row("Lab", 2)])
        self.assertEqual("过载", ev["label"], ev["signals"])
        self.assertTrue(any("72 小时内有 3 条" in s for s in ev["signals"]), ev["signals"])

    def test_今天到期的算进7天权重(self):
        ev = evaluate([row("Essay", 0, "25%"), row("Report", 3, "20%")])
        self.assertTrue(any("45%" in s for s in ev["signals"]), ev["signals"])

    def test_没日期的不算(self):
        self.assertEqual(99, cc_state.days_of({"days_left": None}))
        self.assertEqual(0, cc_state.days_of({"days_left": 0}))


if __name__ == "__main__":
    unittest.main()
