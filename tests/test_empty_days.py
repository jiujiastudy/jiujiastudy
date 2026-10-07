"""空出来的日子不再塞「整理这周的笔记」（发起人 10-06：帮别人装时周报好多天都是这句）。

先把真有的事分到事最少的那天、提成必做；还空就给一天放「今天适合做 X 的学习页」（建议，不算必做）；
其余留空，不算必做、不打勾。复盘和「落后」只数真的必做，老版本计划里的填空句子也不算。
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
import cc_state  # noqa: E402

FILLER = "整理这周的笔记"


class RealMust(unittest.TestCase):
    def test_只有真的必做才算(self):
        self.assertTrue(cc_state.real_must({"must": "ACCT1101 交 Case study", "must_kind": "自己写"}))
        self.assertFalse(cc_state.real_must({"must": "", "must_kind": "空"}))
        self.assertFalse(cc_state.real_must({"must": "今天适合做 X 的学习页", "must_kind": "建议"}))
        self.assertFalse(cc_state.real_must({"must": "整理这周的笔记，把没看完的补上", "must_kind": "机械"}))
        self.assertFalse(cc_state.real_must({"must": "收工：回我「做完了」，我来排下周"}), "老计划里没写 kind 的收工也不算")
        self.assertFalse(cc_state.real_must(None))


class Study(unittest.TestCase):
    """au_semester 第 5 周的周三生成：周一、周二已经过去。"""

    @classmethod
    def setUpClass(cls):
        cls.sc = mockcanvas.Scenario("au_semester")
        cls.mock = mockcanvas.MockCanvas(cls.sc).start()
        cls.home = harness.FakeHome("empty")
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

    def plan(self):
        r = self.coach(["study", "--json"])
        self.assertIn(r.code, (0, 1), r.stdout + r.stderr)
        d = r.json()
        return d.get("plan") or d

    def test_哪天都不塞整理笔记_过去的日子不补(self):
        days = self.plan()["days"]
        self.assertFalse([d for d in days if FILLER in (d.get("must") or "") or d.get("must_kind") == "机械"])
        for d in days:
            if d["date"] < self.day and d.get("must_kind") == "空":
                self.assertEqual(d["must"], "")

    def test_有空日子时别的日子不会还挤着有空再做(self):
        future = [d for d in self.plan()["days"] if d["date"] >= self.day]
        if any(d.get("must_kind") == "空" for d in future):
            self.assertFalse([d for d in future if d["should"]], "条目应该先分到空日子上")

    def test_学习页建议最多一天(self):
        self.assertLessEqual(sum(1 for d in self.plan()["days"] if d.get("must_kind") == "建议"), 1)

    def test_复盘只数真的必做_老计划里的填空句子不算(self):
        prev = {"week": "2026-W12", "days": []}
        for i, date in enumerate(["2026-03-16", "2026-03-17", "2026-03-18", "2026-03-19", "2026-03-20", "2026-03-21", "2026-03-22"]):
            must = "PSYC2012 交 Lab Report 草稿" if i == 2 else ("收工：回我「做完了」，我来排下周" if i == 6 else "整理这周的笔记，把没看完的补上")
            prev["days"].append({"date": date, "weekday": "周一 周二 周三 周四 周五 周六 周日".split()[i], "must": must,
                                 "must_kind": "自己写" if i == 2 else ("机械" if i < 6 else None), "status": "📦", "should": [], "fixed": []})
        path = os.path.join(self.home.archive, "plans", "2026-W12.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(prev, f, ensure_ascii=False)
        try:
            review = self.plan()["review"]
            self.assertIn("上周 1 件必做完成 0 件", review)
            self.assertNotIn(FILLER, review)
        finally:
            os.remove(path)

    def test_页面上连着的空日子并成一行_没有勾选框(self):
        w = self.coach(["study", "--write"])
        self.assertIn(w.code, (0, 1), w.stdout + w.stderr)
        with open(os.path.join(self.home.root, "本周清单.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn(FILLER, html)
        days = self.plan()["days"]

        def blank(d):
            return not d.get("must") and not d.get("fixed") and not d.get("should") and not d.get("todos") and not d.get("revise")
        runs, prev = 0, False
        for d in days:
            cur = blank(d) and d["date"] >= self.day
            runs += 1 if cur and not prev else 0
            prev = cur
        self.assertEqual(html.count('<p class="t meta">没排事，留给自己</p>'), runs)
        for d in days:
            if d.get("must_kind") in ("空", "建议"):
                self.assertNotIn(f'data-tick="{d["date"]}"', html, "没排必做的日子不该有勾选框")


if __name__ == "__main__":
    unittest.main()
