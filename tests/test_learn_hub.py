"""周报接学习页：清单文件本身（格式检查、做页面那一刻 Canvas 上有什么），周报读清单的几种情况，排天用的小函数。

方案见施工说明「周报改成总入口」（Desktop\\qin\\救驾-周报改版）。
"""
import copy
import datetime as dt
import glob
import json
import os
import shutil
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")
sys.path.insert(0, TOOLS)
import cc_learn  # noqa: E402

GOOD = {
    "schema": 1, "course": "MFDI9313", "label": "MFDI9313", "week": "2026-W41", "week_no": 9,
    "page": "C:/x/产出/W9_本周学习页.html", "made_at": "2026-10-06T18:49:00+11:00",
    "data_as_of": "2026-10-06T07:01:11+00:00", "materials_read": True,
    "promise": "明天的 Zoom 课心里有数", "minutes_total": 130,
    "blocks": [
        {"id": "b1", "label": "第 1、6 节", "minutes": 60, "anchor": "#s1",
         "before": "2026-10-07T09:00:00+11:00", "before_label": "周三 09:00 Zoom 课前", "after": None},
        {"id": "b2", "label": "第 3 节", "minutes": 70, "anchor": "#s3", "before": "2026-10-12", "before_label": "下周一上课前", "after": None},
    ],
    "sessions": [{"start": "2026-10-07T09:00:00+11:00", "end": "2026-10-07T12:00:00+11:00", "title": "Zoom 课",
                  "where": "Zoom", "url": None, "inferred": False}],
    "todos": [{"text": "下载第 10 周课件", "due": "2026-10-12", "after": "2026-10-09", "anchor": "#todo"},
              {"text": "看 Studio 视频", "due": None, "after": None, "anchor": None}],
    "covered": {"module_items": [1, 2], "locked_items": [2], "announcements": [9]},
}
SYD = dt.timezone(dt.timedelta(hours=11))


class Validate(unittest.TestCase):
    def bad(self, change):
        m = copy.deepcopy(GOOD)
        change(m)
        return cc_learn.validate(m)

    def test_好的清单没有问题(self):
        self.assertEqual(cc_learn.validate(GOOD), [])

    def test_缺字段(self):
        self.assertIn("缺 promise", self.bad(lambda m: m.pop("promise")))
        self.assertIn("blocks 至少要有一块", self.bad(lambda m: m.update(blocks=[])))

    def test_周次和时间格式(self):
        self.assertTrue(self.bad(lambda m: m.update(week="2026-41")))
        self.assertTrue(self.bad(lambda m: m.update(made_at="2026-10-06")), "made_at 要写到分钟")
        self.assertTrue(self.bad(lambda m: m.update(data_as_of="2026-10-06T07:01:11")), "写到分钟就要带时区")
        self.assertTrue(self.bad(lambda m: m["blocks"][0].update(before="下周一")))
        self.assertTrue(self.bad(lambda m: m["todos"][0].update(due="10-12")))

    def test_分块要有正的分钟数和井号锚点(self):
        self.assertTrue(self.bad(lambda m: m["blocks"][0].update(minutes=0)))
        self.assertTrue(self.bad(lambda m: m["blocks"][0].update(anchor="s1")))

    def test_schema_不对就不认(self):
        self.assertTrue(self.bad(lambda m: m.update(schema=2)))

    def test_不是对象(self):
        self.assertEqual(cc_learn.validate([]), ["不是 JSON 对象"])


class Covered(unittest.TestCase):
    def test_只记这门课的公告和锁着的条目(self):
        mods = [{"items": [{"id": 1}, {"id": 2, "content_details": {"locked_for_user": True}}, {"title": "没 id 的小标题"}]},
                {"items": [{"id": 3}]}]
        anns = [{"id": 9, "context_code": "course_7"}, {"id": 8, "context_code": "course_5"}, {"id": 7}]
        self.assertEqual(cc_learn.covered_from_raw(mods, anns, 7),
                         {"module_items": [1, 2, 3], "locked_items": [2], "announcements": [9]})

    def test_空数据(self):
        self.assertEqual(cc_learn.covered_from_raw(None, None, 7), {"module_items": [], "locked_items": [], "announcements": []})


class Paths(unittest.TestCase):
    def test_清单放在档案的_learn_周次_下(self):
        p = cc_learn.manifest_path("H", "2026-W41", "MECO69362")
        self.assertEqual(os.path.normpath(p), os.path.normpath("H/learn/2026-W41/MECO69362.json"))

    def test_本机链接转义中文和空格(self):
        u = cc_learn.page_url("C:\\a b\\产出\\页.html", "#s1")
        self.assertTrue(u.startswith("file:///C:/a%20b/"))
        self.assertTrue(u.endswith(".html#s1"))
        self.assertNotIn(" ", u)


class Helpers(unittest.TestCase):
    clock = types.SimpleNamespace(same=True, course_tz=SYD, user_tz=SYD)

    def test_课前截止_早上的课前一天看_下午的课当天能看(self):
        c = self.clock
        self.assertEqual(cc_learn.latest_day("2026-10-07T09:00:00+11:00", c), dt.date(2026, 10, 6))
        self.assertEqual(cc_learn.latest_day("2026-10-08T18:00:00+11:00", c), dt.date(2026, 10, 8))
        self.assertEqual(cc_learn.latest_day("2026-10-12", c), dt.date(2026, 10, 11))
        self.assertIsNone(cc_learn.latest_day(None, c))
        self.assertEqual(cc_learn.earliest_day("2026-10-08T20:00:00+11:00", c), dt.date(2026, 10, 8))

    def test_带日期的事排在截止前一天_不早于今天和after(self):
        m = {"todos": [{"text": "A", "due": "2026-10-09"}, {"text": "B", "due": "2026-10-12", "after": "2026-10-11"},
                       {"text": "C", "due": "2026-10-06"}, {"text": "D", "due": "2026-10-20"}, {"text": "E"}]}
        dated, undated = cc_learn.todos_split(m, "X", dt.date(2026, 10, 6), dt.date(2026, 10, 5), self.clock)
        self.assertEqual(dated, [(dt.date(2026, 10, 8), "X A（10-09 前）"), (dt.date(2026, 10, 11), "X B（10-12 前）"),
                                 (dt.date(2026, 10, 6), "X C（10-06 前）")])
        self.assertEqual(undated, ["D（10-20 前）", "E"])

    def test_上课时间换成显示的时区_推断的标出来(self):
        m = {"sessions": [{"start": "2026-10-07T09:00:00+11:00", "end": "2026-10-07T12:00:00+11:00", "title": "Zoom 课", "where": "Zoom"},
                          {"start": "2026-10-06", "title": "consultation", "inferred": True}]}
        self.assertEqual(cc_learn.sessions_fixed(m, "X", self.clock),
                         [(dt.date(2026, 10, 7), "09:00–12:00 X Zoom 课"), (dt.date(2026, 10, 6), "X consultation「推断」")])

    def test_先做哪门_截止最近的那门_只剩一门没有就不推荐(self):
        cs = [{"code": "A", "learn": None, "before_class": [1]}, {"code": "B", "learn": None, "before_class": []},
              {"code": "C", "learn": {"x": 1}}]
        rows = [{"course": "B", "item": "Essay", "days_left": 2}, {"course": "A", "item": "Quiz", "days_left": 5}]
        self.assertEqual(cc_learn.suggest_first(cs, rows, None), {"course": "B", "why": "Essay 还有 2 天截止"})
        self.assertIsNone(cc_learn.suggest_first(cs[1:], rows, None))

    def test_先做哪门_没有七天内的截止就挑这周东西最多的_长标题截短(self):
        cs = [{"code": "MECO6941", "learn": None, "before_class": [], "todo": []},
              {"code": "MFDI9313", "learn": None, "before_class": [1, 2, 3, 4, 5], "todo": []},
              {"code": "MECO6902", "learn": None, "before_class": [1], "todo": []}]
        rows = [{"course": "MECO6941", "item": "Draft presentation to class 5% - due in Class 11 or 12 by arrangement", "days_left": 12}]
        self.assertEqual(cc_learn.suggest_first(cs, rows, None), {"course": "MFDI9313", "why": "这周有 5 样要看要做"})
        cs2 = [cs[0], {"code": "B", "learn": None, "before_class": [], "todo": []}]
        got = cc_learn.suggest_first(cs2, rows, None)
        self.assertEqual(got["course"], "MECO6941")
        self.assertEqual(got["why"], "Draft presentation to cl… 还有 12 天截止")

    def test_做好以后的新东西(self):
        m = {"data_as_of": "2026-10-06T07:00:00+00:00",
             "covered": {"module_items": [1, 2], "locked_items": [2], "announcements": [9]}}
        mods = [{"items": [{"id": 1, "title": "旧的"}, {"id": 2, "title": "第 10 周课件"}, {"id": 3, "title": "新页面"},
                           {"id": 4, "title": "锁着的新条目", "content_details": {"locked_for_user": True}},
                           {"id": 5, "type": "SubHeader", "title": "小标题"}]}]
        anns = [{"id": 9, "context_code": "course_7", "title": "旧公告", "posted_at": "2026-10-05T00:00:00Z"},
                {"id": 10, "context_code": "course_7", "title": "新公告", "posted_at": "2026-10-07T00:00:00Z"},
                {"id": 11, "context_code": "course_7", "title": "窗口挪了才看到的旧公告", "posted_at": "2026-09-01T00:00:00Z"}]
        got = cc_learn.what_changed(m, mods, anns, 7)
        self.assertEqual(got, [{"what": "新解锁", "title": "第 10 周课件"}, {"what": "新条目", "title": "新页面"},
                               {"what": "新公告", "title": "新公告"}])


class Study(unittest.TestCase):
    """周报读学习页清单的几种情况：跑真的 study（假档案 + 模拟 Canvas，au_semester 第 5 周的周三）。"""

    @classmethod
    def setUpClass(cls):
        cls.sc = mockcanvas.Scenario("au_semester")
        cls.mock = mockcanvas.MockCanvas(cls.sc).start()
        cls.home = harness.FakeHome("learn")
        cls.home.seed(cls.sc, cls.mock.base_url)
        cls.day, cls.now = cls.sc.meta["date"], cls.sc.meta["now"]
        r = cls.coach(["collect", "--touch"])
        assert r.code in (0, 1), r.stdout + r.stderr
        cls.week, cls.prev = "2026-W13", "2026-W12"
        with open(os.path.join(cls.home.archive, "config.json"), encoding="utf-8") as f:
            cls.ids = {c["code"]: c["id"] for c in json.load(f)["courses"]}

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()
        cls.home.cleanup()

    @classmethod
    def coach(cls, args):
        return harness.run_coach(cls.home, args + ["--date", cls.day], TOOLS, now=cls.now, ports=(cls.mock.port,))

    def setUp(self):
        shutil.rmtree(os.path.join(self.home.archive, "learn"), ignore_errors=True)

    def raw(self, name):
        files = sorted(glob.glob(os.path.join(self.home.archive, "raw", "daily", "*", name)))
        if not files:
            return None
        with open(files[-1], encoding="utf-8") as f:
            return json.load(f)

    def anns_of(self, code):
        return [a for a in self.raw("announcements.json") or [] if a.get("context_code") == f"course_{self.ids[code]}"]

    def write(self, code, week=None, page=True, **over):
        week = week or self.week
        pdir = os.path.join(self.home.root, code, "产出")
        os.makedirs(pdir, exist_ok=True)
        path = os.path.join(pdir, f"{week}_本周学习页.html")
        if page:
            with open(path, "w", encoding="utf-8") as f:
                f.write("<p>学习页</p>")
        elif os.path.exists(path):
            os.remove(path)
        m = {"schema": 1, "course": code, "label": code, "week": week, "week_no": 5, "page": path,
             "made_at": "2026-03-25T07:00:00+08:00", "data_as_of": "2026-03-24T23:00:00+00:00", "materials_read": True,
             "promise": f"{code} 这周的东西讲清楚", "minutes_total": 90,
             "blocks": [{"id": "b1", "label": "第 1–3 节", "minutes": 50, "anchor": "#s1", "before": "2026-03-27T09:00:00+11:00",
                         "before_label": "周五 09:00 课前", "after": None},
                        {"id": "b2", "label": "第 4–6 节", "minutes": 40, "anchor": "#s4", "before": "2026-03-30",
                         "before_label": "下周一上课前", "after": None}],
             "sessions": [{"start": "2026-03-27T09:00:00+11:00", "end": "2026-03-27T11:00:00+11:00", "title": f"{code} Tutorial",
                           "where": "Zoom", "url": None, "inferred": False}],
             "todos": [{"text": "给 tutor 发邮件", "due": "2026-03-27", "after": None, "anchor": "#todo"},
                       {"text": "看录播", "due": None, "after": None, "anchor": None}],
             "covered": cc_learn.covered_from_raw(self.raw(f"modules_{self.ids[code]}.json"), self.raw("announcements.json"), self.ids[code])}
        m.update(over)
        os.makedirs(cc_learn.manifest_dir(self.home.archive, week), exist_ok=True)
        with open(cc_learn.manifest_path(self.home.archive, week, code), "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False)
        return m

    def plan(self):
        r = self.coach(["study", "--json"])
        self.assertIn(r.code, (0, 1), r.stdout + r.stderr)
        d = r.json()
        return d.get("plan") or d

    @staticmethod
    def course(plan, code):
        return next(c for c in plan["study"]["courses"] if c["code"] == code)

    @staticmethod
    def on_day(plan, date):
        return next(d for d in plan["days"] if d["date"] == date)

    def test_一份都没有_周报照旧只多一句怎么要(self):
        p = self.plan()
        self.assertEqual(p["learn"]["courses"], [])
        for c in p["study"]["courses"]:
            self.assertIsNone(c["learn"])
            self.assertFalse([x for x in c["before_class"] if x["kind"] == "Learn"])
            if c["before_class"] or c["todo"] or c["deadline_related"]:
                self.assertIn(f"做 {c['code']} 这周的学习页", c["learn_hint"])
        self.assertIn(p["learn"]["suggest"]["course"], self.ids)

    def test_一门有_入口代替课前看_上课时间和要做的事排进每天(self):
        self.write("ACCT1101")
        p = self.plan()
        c = self.course(p, "ACCT1101")
        self.assertEqual([x["kind"] for x in c["before_class"]], ["Learn", "Learn"])
        ids = [x["id"] for k in ("before_class", "todo", "deadline_related") for x in c[k]]
        self.assertEqual(len(ids), len(set(ids)), "编号不能重")
        self.assertNotIn("learn_hint", c)
        self.assertEqual(c["learn"]["todos_undated"], ["看录播"])
        self.assertTrue(any("ACCT1101 Tutorial" in f for f in self.on_day(p, "2026-03-27")["fixed"]))
        self.assertIn("ACCT1101 给 tutor 发邮件（03-27 前）", self.on_day(p, "2026-03-26").get("todos") or [])
        first = [d for d in p["days"] if "第 1–3 节" in (d["must"] or "") + "".join(d["should"])]
        self.assertTrue(first and first[0]["date"] <= "2026-03-26", "周五早上的课前那块最晚排到周四")
        for code in ("PSYC2012", "DSGN3402"):
            self.assertIn("这周的学习页", self.course(p, code).get("learn_hint") or "")
        self.assertNotEqual(p["learn"]["suggest"]["course"], "ACCT1101")

    def test_全有_不再提示_排进和先搁着加起来等于总量(self):
        for code in self.ids:
            self.write(code)
        p = self.plan()
        self.assertIsNone(p["learn"]["suggest"])
        self.assertEqual(p["learn"]["minutes_total"], 90 * len(self.ids))
        self.assertEqual(p["learn"]["scheduled_minutes"] + p["learn"]["parked_minutes"], p["learn"]["minutes_total"])
        for c in p["study"]["courses"]:
            self.assertNotIn("learn_hint", c)

    def test_过期_新条目_新解锁_新公告都会提一句(self):
        code = max(self.ids, key=lambda k: len(self.anns_of(k)))
        cov = cc_learn.covered_from_raw(self.raw(f"modules_{self.ids[code]}.json"), self.raw("announcements.json"), self.ids[code])
        items = list(cov["module_items"])
        self.assertGreaterEqual(len(items), 2)
        self.write(code, data_as_of="2026-01-01T00:00:00+00:00",
                   covered={"module_items": items[1:], "locked_items": [items[1]], "announcements": []})
        whats = {x["what"] for x in self.course(self.plan(), code)["learn"]["changed"]}
        self.assertIn("新解锁", whats)
        if self.anns_of(code):
            self.assertIn("新公告", whats)

    def test_只有上周的_当没有_折叠里给上周那份(self):
        self.write("ACCT1101", week=self.prev)
        c = self.course(self.plan(), "ACCT1101")
        self.assertIsNone(c["learn"])
        self.assertTrue(c["learn_prev"].startswith("file:///"))

    def test_学习页文件被删_当没有_不报错(self):
        self.write("ACCT1101", page=False)
        c = self.course(self.plan(), "ACCT1101")
        self.assertIsNone(c["learn"])
        self.assertIn("学习页文件不在了", c["learn_problems"])

    def test_清单坏了_当没有_不报错(self):
        os.makedirs(cc_learn.manifest_dir(self.home.archive, self.week), exist_ok=True)
        with open(cc_learn.manifest_path(self.home.archive, self.week, "ACCT1101"), "w", encoding="utf-8") as f:
            f.write("{坏了")
        c = self.course(self.plan(), "ACCT1101")
        self.assertIsNone(c["learn"])
        self.assertTrue(c["learn_problems"][0].startswith("读不了"))

    def test_每天上限太小就进先搁着_页面上有提醒(self):
        self.write("ACCT1101")
        r = self.coach(["config", "set", "study.daily_minutes", "30"])
        self.assertEqual(r.code, 0, r.stdout + r.stderr)
        try:
            p = self.plan()
            self.assertEqual(p["learn"]["parked_minutes"], 90)
            self.assertEqual(p["learn"]["daily_cap"], 30)
            w = self.coach(["study", "--write"])
            self.assertIn(w.code, (0, 1), w.stdout + w.stderr)
            with open(os.path.join(self.home.root, "本周清单.html"), encoding="utf-8") as f:
                html = f.read()
            self.assertIn("看完你就", html)
            self.assertIn("打开学习页", html)
            self.assertIn("排不下", html)
            with open(os.path.join(self.home.archive, "plans", f"{self.week}.json"), encoding="utf-8") as f:
                parking = json.load(f)["parking"]
            self.assertTrue(any("学习页" in x["text"] and "排满" in x["text"] for x in parking))
        finally:
            self.coach(["config", "set", "study.daily_minutes", "120"])


if __name__ == "__main__":
    unittest.main()
