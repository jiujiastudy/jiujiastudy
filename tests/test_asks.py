"""「可以让我做的」这张卡：挑出来的话必须对得上学生当下的处境，而且必须是真做得出来的事。

这块最容易出的丑是「建议一件人家已经做完的事」——uk_term 的场景里就有真实案例：
HIS2102 Source Analysis (40%) 明天截止，但三天前已经交了。所以 submitted 那条是硬测。
"""
import importlib.util
import io
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

CODE = harness.code_dir()
GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")


def load(name):
    spec = importlib.util.spec_from_file_location("_asks_" + name, os.path.join(CODE, "tools", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


asks = load("cc_asks")


def dl(course="ACCT1101", title="Essay 1 (30%)", days=3, weight="30%", stypes=("online_upload",),
       exam=False, overdue=False, submitted=False, rel=None):
    return {"course": course, "title": title, "kind": "Overdue" if overdue else "Deadline",
            "weight": weight, "days_left": days, "rel": rel if rel is not None else f"还有 {days} 天",
            "exam": exam, "submitted": submitted, "submission_types": list(stypes), "status": "📦"}


def plan(deadlines=(), files=(), label=None, code="ACCT1101"):
    course = {"code": code, "deadline_related": list(deadlines),
              "before_class": [{"id": f"{code[-4:]}-{i}", "course": code, "kind": "File", "kind_zh": "课件",
                                "verb": "看课件", "title": f, "minutes": 40, "status": "📦"}
                               for i, f in enumerate(files, 1)]}
    p = {"study": {"courses": [course], "top_one": {"course": code}}}
    if label:
        p["state"] = {"label": label, "advice": "", "signals": []}
    return p


def kinds(p):
    return [a["kind"] for a in asks.suggest(p)]


class Pick(unittest.TestCase):
    def test_没数据就一条都不给(self):
        self.assertEqual([], asks.suggest({}))
        self.assertEqual([], asks.suggest({"study": {"courses": []}}))

    def test_已过期排在最前(self):
        p = plan([dl(title="Midterm (20%)", days=5, exam=True), dl(title="Quiz 4", days=-2, overdue=True, weight="—")])
        self.assertEqual("overdue", kinds(p)[0])

    def test_大考给复习包_小测给自测题(self):
        big = asks.suggest(plan([dl(title="Mid-semester test (20%)", days=6, weight="20%", exam=True)]))[0]
        small = asks.suggest(plan([dl(title="Weekly Quiz 5", days=2, weight="—", exam=True)]))[0]
        self.assertEqual(("exam", "quiz"), (big["kind"], small["kind"]))
        self.assertIn("复习包", big["text"])
        self.assertIn("模拟小测", small["text"])

    def test_已经交了的不提(self):
        p = plan([dl(title="Source Analysis (40%)", days=1, submitted=True)])
        self.assertNotIn("write", kinds(p))
        self.assertFalse(any("Source Analysis" in a["text"] for a in asks.suggest(p)))

    def test_老档案没有submitted就看中文状态串(self):
        row = dl(title="Essay 2", days=2)
        row["submitted"], row["status"] = False, "已交 03-17 周二 21:14"
        self.assertNotIn("write", kinds(plan([row])))

    def test_打过勾的课件不提(self):
        p = plan([], files=["W5 Slides.pdf"])
        p["study"]["courses"][0]["before_class"][0]["status"] = "✅"
        self.assertNotIn("guide", kinds(p))

    def test_只有File才提导读(self):
        p = plan([], files=[])
        p["study"]["courses"][0]["before_class"] = [
            {"course": "ACCT1101", "kind": "Video", "title": "Week 5 录像", "status": "📦"},
            {"course": "ACCT1101", "kind": "Page", "title": "Week 5 阅读", "status": "📦"}]
        self.assertNotIn("guide", kinds(p), "视频没有转写、Page 没有正文，说「做成导读」是承诺做不到的事")

    def test_提交方式决定文案(self):
        got = {}
        for name, st in (("write", ("online_upload",)), ("discussion", ("discussion_topic",)), ("oral", ("on_paper",))):
            got[name] = asks.suggest(plan([dl(title="Task", days=2, stypes=st)]))[0]["kind"]
        self.assertEqual({"write": "write", "discussion": "discussion", "oral": "oral"}, got)

    def test_标题里的演讲词也算演讲(self):
        self.assertEqual("oral", asks.suggest(plan([dl(title="Class Pitch (15%)", days=4, stypes=())]))[0]["kind"])

    def test_认不出提交方式的快到期了才兜底(self):
        self.assertEqual("homework", asks.suggest(plan([dl(title="Homework 7", days=1, stypes=("external_tool",))]))[0]["kind"])
        self.assertNotIn("homework", kinds(plan([dl(title="Homework 9", days=9, stypes=("external_tool",))])))

    def test_只认作业类型不认学科(self):
        a = plan([dl(course="FILM1001", title="Short film edit (30%)", days=2)], files=["Week 5 剪辑.pdf"])
        b = plan([dl(course="LAWS1001", title="Case note (30%)", days=2)], files=["Week 5 案例.pdf"], code="ACCT1101")
        self.assertEqual(kinds(a), kinds(b), "换个学科，挑法不该变")

    def test_课件名自带课号就不重复(self):
        one = asks.suggest(plan([], files=["ACCT1101 W5 Lecture Slides.pdf"]))[0]["text"]
        self.assertEqual(1, one.count("ACCT1101"))
        self.assertIn("ACCT1101 的 第5周", asks.suggest(plan([], files=["第5周 定积分.pdf"]))[0]["text"])

    def test_课程代码是单个数字也不会误伤(self):
        text = asks.suggest(plan([], files=["Unit 5 课文讲解.pptx"], code="3"))[0]["text"]
        self.assertIn("3 的 Unit 5", text)

    def test_前三条最多两条是deadline(self):
        p = plan([dl(title=f"Task {i}", days=i) for i in range(1, 6)], files=["W5.pdf"])
        head = asks.suggest(p)[:3]
        self.assertLessEqual(len([x for x in head if x["kind"] in asks.URGENT]), 2)
        self.assertEqual(3, len(head))

    def test_顺序只由数据决定(self):
        rows = [dl(course="BBB2222", title="B", days=2), dl(course="AAA1111", title="A", days=2)]
        p1, p2 = plan(rows), plan(list(reversed(rows)))
        self.assertEqual([a["text"] for a in asks.suggest(p1)], [a["text"] for a in asks.suggest(p2)])

    def test_不读时钟(self):
        src = io.open(os.path.join(CODE, "tools", "cc_asks.py"), encoding="utf-8").read()
        self.assertNotIn("import datetime", src)
        self.assertNotIn("time.time", src)
        p = plan([dl()])
        self.assertEqual(asks.suggest(p), asks.suggest(p))

    def test_状态正常不出状态句_其余四种各有一句(self):
        self.assertNotIn("state_overload", kinds(plan([], label="正常")))
        for label, kind in (("过载", "state_overload"), ("卡住", "state_stuck"), ("病了", "state_sick"), ("落后", "state_behind")):
            self.assertIn(kind, kinds(plan([], files=["W5.pdf"], label=label)), label)

    def test_手写周计划不炸(self):
        p = {"deadlines": [{"course": "X1", "item": "期末考试", "kind": "exam", "weight": "40%",
                            "days_left": 5, "rel": "还有 5 天", "status": "未交"}]}
        self.assertEqual("exam", asks.suggest(p)[0]["kind"])

    def test_全做完的那周退化成一句真话(self):
        p = plan([dl(days=2, submitted=True)])
        out = asks.suggest(p)
        self.assertEqual(["prefetch"], [a["kind"] for a in out])

    def test_标题超长和空白都收拾干净(self):
        long_title = "Assessment 2 " + "很长的题目 " * 20
        text = asks.suggest(plan([dl(title=long_title + "\n第二行", days=2)]))[0]["text"]
        self.assertNotIn("\n", text)
        self.assertIn("…", text)

    def test_每句话都是一行人话(self):
        seen = []
        for sc in os.listdir(GOLDEN):
            f = os.path.join(GOLDEN, sc, "artifacts", "plan.json")
            if os.path.isfile(f):
                import json
                seen += asks.suggest(json.load(io.open(f, encoding="utf-8")))
        seen += asks.suggest(plan([dl()], files=["W5.pdf"], label="病了"))
        self.assertTrue(seen)
        for a in seen:
            with self.subTest(text=a["text"]):
                self.assertNotIn("\n", a["text"])
                self.assertLessEqual(len(a["text"]), asks.MAX_LINE, "整句上限是 cc_asks.MAX_LINE，别偷偷放宽")
                self.assertTrue(a["text"].endswith("。"))
                self.assertFalse(re.search(r"请|您|为您|亲|一键|神器|小助手", a["text"]))
                self.assertFalse(re.search(r"[\U0001F300-\U0001FAFF☀-➿]", a["text"]))

    def test_每条建议都对得上一个真产出(self):
        self.assertEqual(set(asks.PRODUCED_BY), set(asks.TEXTS))
        for kind, produces in asks.PRODUCED_BY.items():
            self.assertIn(produces, asks.PRODUCES, kind)

    def test_不代写计分内容(self):
        for kind, text in asks.TEXTS.items():
            with self.subTest(kind=kind):
                self.assertFalse(re.search(r"帮我写(这|那)?(篇|份)?(论文|作业|essay|报告)", text), text)


class Card(unittest.TestCase):
    """卡片在页面上的位置、复制交互、以及「先搁着」那一栏。"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(CODE, "tools"))
        import design
        import render_week
        cls.design, cls.rw = design, render_week

    def week(self, **extra):
        r = {"week": "2026-W13", "title": "第 7 周", "range": "x", "generated": "2026-03-25",
             "state": {"label": "正常", "advice": "", "signals": []}, "sources": []}
        r.update(extra)
        return self.rw.render(r)

    def test_卡片在状态下面今天上面(self):
        html = self.week(**plan([dl(days=2)], files=["W5.pdf"]),
                         days=[{"date": "2026-03-25", "weekday": "周三", "must": "读 Week 5", "status": "📦"}])
        i_status, i_asks, i_today = html.index('class="status'), html.index("可以让我做的"), html.index('card today')
        self.assertLess(i_status, i_asks)
        self.assertLess(i_asks, i_today)

    def test_没建议就没有这块(self):
        self.assertNotIn("可以让我做的", self.week())

    def test_每条都能点着复制(self):
        p = plan([dl(days=2)], files=["W5.pdf"])
        html = self.week(**p)
        self.assertEqual(len(asks.suggest(p)), html.count('data-copy="'))
        self.assertIn("[data-copy]", self.design.CORE_JS)

    def test_复制失败的退路只有一份(self):
        self.assertEqual(1, self.design.CORE_JS.count("window.prompt"))

    def test_复盘搬进了先搁着(self):
        html = self.week(review="上周三件只做了一件。", parking=[{"date": "03-24", "text": "问 tutor"}])
        self.assertNotIn("回我一句", html)
        seg = html[html.index("先搁着"):]
        self.assertIn("上周三件只做了一件。", seg)
        self.assertIn("2026-03-25", seg)
        md = self.rw.to_markdown({"review": "复盘一句。", "parking": [], "generated": "2026-03-25"}, 7)
        self.assertIn("## 先搁着", md)
        self.assertNotIn("回我一句", md)

    def test_旧名字全仓消失(self):
        for rel in ("SKILL.md", os.path.join("references", "study.md"),
                    os.path.join("tools", "cc_digest.py"), os.path.join("tools", "cc_study.py"),
                    os.path.join("tools", "render_week.py")):
            with self.subTest(rel=rel):
                self.assertNotIn("停车场", io.open(os.path.join(CODE, rel), encoding="utf-8").read())

    def test_周报还是过风格检查(self):
        import tempfile

        import style_check
        html = self.week(**plan([dl(days=2)], files=["W5.pdf"]))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "week.html")
            io.open(p, "w", encoding="utf-8", newline="\n").write(html)
            self.assertEqual([], style_check.check(p))


if __name__ == "__main__":
    unittest.main()
