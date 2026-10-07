"""版面检查（layout_check）和设计组件的兜底：中文被挤成一字一行、整页左右滚动。

10-07：范例说明（一行里塞了一段说明）、周报的学习页那几行（右边的长小字不换行）、学习页的一张表（手机上一列被挤窄）
都出现过一字一行；只看手机宽度、只看会不会左右滚动的检查发现不了。这里要真浏览器，没有就跳过。
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
import cc_learn  # noqa: E402
import layout_check  # noqa: E402
from design import foot, head  # noqa: E402

LONG = "网页只画出最左边约 5 栏，后面的栏只有标题。现在直接读 Padlet 网页自己取下来的整板数据，第 9 周五栏都读到了。" * 2


def browser_ok():
    d = tempfile.mkdtemp(prefix="stc-lay-")
    p = os.path.join(d, "a.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write("<p>ok</p>")
    try:
        layout_check.check_pages([p])
        return True
    except Exception:  # noqa: BLE001  没装 Playwright 或者没有浏览器
        return False
    finally:
        shutil.rmtree(d, ignore_errors=True)


HAVE = browser_ok()


@unittest.skipUnless(HAVE, "这台电脑开不了浏览器")
class Check(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="stc-lay-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def page(self, name, body, css=""):
        p = os.path.join(self.dir, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(head("测试", key="t", extra_css=css) + body + foot())
        return p

    def test_挤成竖排和左右滚动都报出来(self):
        squeezed = self.page("a.html", f'<div style="display:grid;grid-template-columns:8px 1fr"><div>这一列被挤得只剩一个字宽</div><div>{LONG}</div></div>')
        wide = self.page("b.html", '<div style="width:2000px">很宽的一块</div>')
        res = layout_check.check_pages([squeezed, wide])
        self.assertTrue(any("被挤成" in x for x in res[squeezed]), res[squeezed])
        self.assertTrue(any("左右滚动" in x for x in res[wide]), res[wide])

    def test_组件兜底_一行里另放一段说明也不会挤成竖排(self):
        p = self.page("c.html", f'<section class="card"><ul class="rows nobox"><li><div class="t">Padlet 以前只读到左边几栏</div>'
                                f'<div class="sub">{LONG}</div></li></ul></section>')
        self.assertEqual(layout_check.check_pages([p])[p], [])

    def test_组件兜底_右边的长小字会换行(self):
        p = self.page("d.html", '<div class="courses">' + "".join(
            f'<article class="card course"><ul class="rows"><li data-row><input type="checkbox"><span class="t">学习页：第 2–4 节 + 第 5 节第 1–5 份 + 第 7 节挑一个问题</span>'
            f'<span class="m num">80 分钟 · 讲座后，下周一 14:00 第 10 周课前</span></li></ul></article>' for _ in range(2)) + "</div>")
        self.assertEqual(layout_check.check_pages([p])[p], [])

    def test_组件兜底_表格在手机上每列有最小宽度(self):
        rows = "".join(f"<tr><td>Padlet</td><td>https://padlet.com/sydney/very-long-board-name-{i}</td><td>这次没读到：被带去登录页</td>"
                       f"<td>10 月 7 日 01:56</td></tr>" for i in range(3))
        p = self.page("e.html", f'<div class="scroll"><table><tr><th>平台</th><th>网址</th><th>结果</th><th>时间（悉尼）</th></tr>{rows}</table></div>')
        self.assertEqual(layout_check.check_pages([p])[p], [])


@unittest.skipUnless(HAVE, "这台电脑开不了浏览器")
class WeeklyPage(unittest.TestCase):
    """四门课都有学习页、分块写着很长的「在哪节课之前」：周报在手机宽和电脑宽都不能挤成竖排。"""

    @classmethod
    def setUpClass(cls):
        cls.sc = mockcanvas.Scenario("au_semester")
        cls.mock = mockcanvas.MockCanvas(cls.sc).start()
        cls.home = harness.FakeHome("layout")
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

    def test_周报不挤成竖排(self):
        with open(os.path.join(self.home.archive, "config.json"), encoding="utf-8") as f:
            codes = [c["code"] for c in json.load(f)["courses"]]
        week = "2026-W13"
        for code in codes:
            pdir = os.path.join(self.home.root, code, "产出")
            os.makedirs(pdir, exist_ok=True)
            page = os.path.join(pdir, f"{week}_本周学习页.html")
            with open(page, "w", encoding="utf-8") as f:
                f.write("<p>学习页</p>")
            m = {"schema": 1, "course": code, "label": code, "week": week, "week_no": 5, "page": page,
                 "made_at": "2026-03-25T07:00:00+08:00", "data_as_of": "2026-03-24T23:00:00+00:00", "materials_read": True,
                 "promise": "周四晚上的客座讲座讲什么、带哪个问题去，你都清楚；下周一课前，essay 推进到选好题、找到一个例子。",
                 "minutes_total": 115,
                 "blocks": [{"id": "b1", "label": "学习页：第 2–4 节 + 第 5 节第 1–5 份 + 第 7 节挑一个问题", "minutes": 80, "anchor": "#s2",
                             "before": "2026-03-27T09:00:00+11:00", "before_label": "周五 09:00 客座讲座前（Zoom，要提前十分钟进）", "after": None},
                            {"id": "b2", "label": "学习页：第 5 节第 6–9 份", "minutes": 35, "anchor": "#s5", "before": "2026-03-30",
                             "before_label": "讲座后，下周一 14:00 第 10 周课前", "after": None}],
                 "sessions": [], "todos": [{"text": "读 comment piece 的总评和正文批注；Essay 选题：划掉 Q5，在 Q6、Q7 里挑一个", "due": None,
                                            "after": None, "anchor": None}],
                 "covered": {"module_items": [], "locked_items": [], "announcements": []}}
            os.makedirs(cc_learn.manifest_dir(self.home.archive, week), exist_ok=True)
            with open(cc_learn.manifest_path(self.home.archive, week, code), "w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False)
        w = self.coach(["study", "--write"])
        self.assertIn(w.code, (0, 1), w.stdout + w.stderr)
        p = os.path.join(self.home.root, "本周清单.html")
        self.assertEqual(layout_check.check_pages([p])[p], [])


if __name__ == "__main__":
    unittest.main()
