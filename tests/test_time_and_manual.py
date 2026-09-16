"""过没过期、今天 / 明天 / 还有几天，和手动 deadline 的日期时刻（S01 / S10）。

S01：审计里两地日期直接相减，跨时区就错——课程在美东、人在上海、还有 3 小时才截止的那条被写成
「已过 1 天」放进已过期未交；悉尼的课配美西的人，过了半小时反而写「明天」；今天早些时候已经过了的，
一整天还挂着「今天」。这里钉住新算法：过没过期看真实时刻，今天 / 明天 / 还有几天按课程时区的日历天
（显示的日期也是课程时区的，两边才对得上），--date 指的是一个时刻。

S10：`record deadline --time 4pm` 当场说成功，之后每个命令都崩在 int() 上；`--due 09-20` 说成功
但那行根本不出现，而且没有办法删掉一条。这里钉住：写得对的当场规整并回显，写不对的当场退回（退出码 2），
档案里已经写坏的那行只显示「时间写错了」，不许崩；--list / --remove 能看能删。
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

sys.path.insert(0, os.path.join(harness.code_dir(), "tools"))
import cc_deadlines  # noqa: E402
import cc_time  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")
DEAD_HOST = "http://127.0.0.1:9"  # 只写进 config；这些测试全程离线
HAN = r"[一-鿿]"


class FakeCtx:
    """deadline_rows 要的全部：时钟、state、cfg、P()。没有「没写日期的计分项」时不会去读公告。"""

    def __init__(self, clock, state=None, home="."):
        self.clock, self.state, self.cfg, self.home = clock, state or {}, {"courses": []}, home

    def P(self, *a):
        return os.path.join(self.home, *a)


def seeded_home(label, manual):
    """au_semester 的档案，手动 deadline 换成给定的这几条（fixture 自带一条，先清掉）。"""
    home = harness.FakeHome(label)
    home.seed(mockcanvas.Scenario("au_semester"), DEAD_HOST)
    path = os.path.join(home.archive, "state.json")
    with open(path, encoding="utf-8") as f:
        state = json.load(f)
    state["manual_deadlines"] = manual
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    return home


def one_assignment(due_iso, course="ACCT1101", name="Essay (20%)"):
    return {"assignments": {"1101001": {"course": course, "name": name, "due_at": due_iso, "points": 20,
                                        "sub_state": None, "html_url": None, "submission_types": ["online_upload"]}}}


# 课程时区, 用户时区, 此刻, 截止, 剩余, days_left, 是否已过期；注释里是旧算法的答案
CASES = [
    ("上海的课 · 人在伦敦 · 明天", "Asia/Shanghai", "Europe/London",
     "2026-09-20T02:00:00Z", "2026-09-21T15:59:00Z", "明天", 1, False),
    ("上海的课 · 人在伦敦 · 今天", "Asia/Shanghai", "Europe/London",
     "2026-09-20T02:00:00Z", "2026-09-20T15:59:00Z", "今天", 0, False),
    ("上海的课 · 人在伦敦 · 今天早些时候已经过了", "Asia/Shanghai", "Europe/London",
     "2026-09-20T02:00:00Z", "2026-09-19T23:00:00Z", "已过期", 0, True),  # 旧算法：今天，还留在区块一
    ("上海的课 · 人在伦敦 · 课程那边已经是第二天", "Asia/Shanghai", "Europe/London",
     "2026-09-20T17:00:00Z", "2026-09-25T15:59:00Z", "还有 4 天", 4, False),  # 旧算法：还有 5 天
    ("美东的课 · 人在上海 · 还有 3 小时", "America/New_York", "Asia/Shanghai",
     "2026-09-25T00:59:00Z", "2026-09-25T03:59:00Z", "今天", 0, False),  # 旧算法：已过 1 天，进已过期未交
    ("美东的课 · 人在上海 · 过了半小时", "America/New_York", "Asia/Shanghai",
     "2026-09-25T04:30:00Z", "2026-09-25T03:59:00Z", "已过 1 天", -1, True),
    ("悉尼的课 · 人在美西 · 过了半小时", "Australia/Sydney", "America/Los_Angeles",
     "2026-10-04T14:00:00Z", "2026-10-04T13:30:00Z", "已过期", 0, True),  # 旧算法：明天
    ("悉尼的课 · 人在美西 · 明天", "Australia/Sydney", "America/Los_Angeles",
     "2026-10-04T14:00:00Z", "2026-10-06T12:59:00Z", "明天", 1, False),  # 旧算法：还有 2 天
    ("悉尼换夏令时那天 · 今天", "Australia/Sydney", "Asia/Shanghai",
     "2026-10-03T15:30:00Z", "2026-10-04T12:59:00Z", "今天", 0, False),  # 此刻 +10，截止 +11；旧算法：明天
    ("悉尼换夏令时那天 · 明天", "Australia/Sydney", "Asia/Shanghai",
     "2026-10-03T15:30:00Z", "2026-10-05T12:59:00Z", "明天", 1, False),
    ("悉尼换夏令时那天 · 昨天已经过了", "Australia/Sydney", "Asia/Shanghai",
     "2026-10-04T00:00:00Z", "2026-10-03T12:59:00Z", "已过 1 天", -1, True),
]


class RelAcrossZones(unittest.TestCase):
    """同一个时刻，两个时区，一行 deadline 该写什么。"""

    def tearDown(self):
        cc_time.pin_now(None)

    def rows(self, course_tz, user_tz, now, due):
        cc_time.pin_now(now)  # --date 走的就是这条路：「现在」钉在一个时刻上
        clock = cc_time.Clock({"course_tz": course_tz, "user_tz": user_tz})
        self.assertEqual(cc_time.parse_ts(now), clock.now_utc(), "--date 没把「现在」钉住")
        ctx = FakeCtx(clock)
        return clock, cc_deadlines.deadline_rows(ctx, one_assignment(due), clock.today_user())

    def test_两地日期不一致时每一行怎么算(self):
        for label, course_tz, user_tz, now, due, rel, days_left, overdue in CASES:
            with self.subTest(case=label):
                clock, rows = self.rows(course_tz, user_tz, now, due)
                self.assertEqual(1, len(rows), f"{label}：这条应该正好出现一次")
                r = rows[0]
                self.assertEqual(rel, r["rel"], label)
                self.assertEqual(days_left, r["days_left"], label)
                self.assertEqual(overdue, r["overdue"], label)
                self.assertEqual(clock.course_date(cc_time.parse_ts(due)), r["date"], "显示的日期是课程时区的")

    def test_两地时间都还照旧显示(self):
        # 只改比较，显示的规矩不动：日期是课程时区的，两地时间不同就都写出来。
        clock, rows = self.rows("America/New_York", "Asia/Shanghai", "2026-09-25T00:59:00Z", "2026-09-25T03:59:00Z")
        when = rows[0]["when"]
        self.assertIn("09-24", when)
        self.assertIn("23:59（美东）", when)
        self.assertIn("11:59（北京）", when)

    def test_没写时刻的手动_deadline_算到那天结束(self):
        # 「课上」这种写不出时刻的：排序排在那天最前，过没过期算到那天结束。
        cc_time.pin_now("2026-03-31T09:00:00+11:00")  # 悉尼 03-31 上午
        clock = cc_time.Clock({"course_tz": "Australia/Sydney", "user_tz": "Asia/Shanghai"})
        state = {"manual_deadlines": [{"course": "DSGN3402", "item": "Studio pitch", "date": "2026-03-31",
                                       "time": None, "time_text": "课上"}]}
        rows = cc_deadlines.deadline_rows(FakeCtx(clock, state), {}, clock.today_user())
        self.assertEqual(["今天"], [r["rel"] for r in rows])
        self.assertEqual("03-31 周二 课上", rows[0]["when"])


class NormalizeDueAndTime(unittest.TestCase):
    """record deadline 的 --due / --time：认得出的规整后回显，认不出的当场退回。"""

    def setUp(self):
        self.home = seeded_home("manual", [])

    def tearDown(self):
        self.home.cleanup()

    def coach(self, *args):
        return harness.run_coach(self.home, list(args) + ["--date", "2026-03-25T10:00:00+11:00"], TOOLS)

    def stored(self):
        with open(os.path.join(self.home.archive, "state.json"), encoding="utf-8") as f:
            return json.load(f).get("manual_deadlines") or []

    def add(self, item, *extra):
        return self.coach("record", "deadline", item, "--course", "ACCT1101", *extra)

    def test_认得出的写法都收下并回显规整后的样子(self):
        cases = [("2026-09-20", "23:59", "09-20 周日 23:59"), ("09-20", "11:59pm", "09-20 周日 23:59"),
                 ("9/20", "4pm", "09-20 周日 16:00"), ("2026/09/20", "16：00", "09-20 周日 16:00"),
                 ("2026-9-20", "16.00", "09-20 周日 16:00"), ("09-20", "24:00", "09-20 周日 23:59"),
                 ("09-20", None, "09-20 周日")]
        for i, (due, time, echo) in enumerate(cases):
            with self.subTest(due=due, time=time):
                r = self.add(f"Essay {i}", "--due", due, *(["--time", time] if time else []))
                self.assertEqual(0, r.code, r.stderr)
                self.assertIn(echo, r.stdout)
                row = self.stored()[-1]
                self.assertEqual("2026-09-20", row["date"])
                self.assertEqual(echo.split(" ")[-1] if time else None, row["time"])

    def test_认不出的当场退回而且不落盘(self):
        for extra in (["--due", "next friday"], ["--due", "abc"], ["--due", "09-20", "--time", "25:00"],
                      ["--due", "09-20", "--time", "abc"]):
            with self.subTest(extra=" ".join(extra)):
                r = self.add("Essay X", *extra)
                self.assertEqual(2, r.code, r.stderr)
                self.assertEqual("", r.stdout)
                lines = [x for x in r.stderr.splitlines() if x.strip()]
                self.assertEqual(1, len(lines), r.stderr)
                self.assertRegex(lines[0], HAN)
                self.assertNotIn("Traceback", r.stderr)
                self.assertEqual([], self.stored(), "退回的那条不许留在档案里")

    def test_少写了事项或课程也只报一句(self):
        r = self.coach("record", "deadline", "Essay")
        self.assertEqual(2, r.code, r.stderr)
        self.assertEqual("", r.stdout)
        self.assertEqual(1, len([x for x in r.stderr.splitlines() if x.strip()]), r.stderr)
        self.assertNotIn("usage:", r.stderr)

    def test_列出_删掉_再记一次是更新(self):
        self.assertEqual(0, self.add("Essay", "--due", "09-20", "--time", "23:59").code)
        self.assertEqual(0, self.add("Final exam", "--due", "10-02", "--time", "9am").code)
        r = self.coach("record", "deadline", "--list")
        self.assertEqual(0, r.code, r.stderr)
        self.assertIn("1. ACCT1101 Essay · 09-20 周日 23:59", r.stdout)
        self.assertIn("2. ACCT1101 Final exam · 10-02 周五 09:00", r.stdout)

        r = self.add("Essay", "--due", "09-21", "--time", "16:00")  # 同一件事再记一次
        self.assertEqual(0, r.code, r.stderr)
        self.assertIn("更新", r.stdout)
        self.assertEqual(2, len(self.stored()), "再记一次是更新，不是多一条")
        self.assertEqual("2026-09-21", self.stored()[0]["date"])

        self.assertEqual(0, self.coach("record", "deadline", "--remove", "Final exam").code)
        r = self.coach("record", "deadline", "--remove", "2")
        self.assertEqual(2, r.code, "只剩一条了，序号 2 该报错")
        self.assertEqual(0, self.coach("record", "deadline", "--remove", "1").code)
        self.assertEqual([], self.stored())
        r = self.coach("record", "deadline", "--list")
        self.assertEqual(0, r.code, r.stderr)
        self.assertIn("还没记过", r.stdout)


class BrokenRowStillRenders(unittest.TestCase):
    """档案里已经写坏的手动 deadline：只显示「时间写错了」，radar 和 status 照常出。"""

    def setUp(self):
        self.home = seeded_home("broken", [
            {"course": "ACCT1101", "item": "Essay", "date": "2026-03-26", "time": "23:99"},
            {"course": "ACCT1101", "item": "Presentation", "date": "next friday", "time": None},
        ])

    def tearDown(self):
        self.home.cleanup()

    def coach(self, *args):
        return harness.run_coach(self.home, list(args) + ["--date", "2026-03-25T10:00:00+11:00"], TOOLS)

    def test_radar_和_status_都不崩(self):
        for args in (["radar"], ["status"]):
            with self.subTest(args=args):
                r = self.coach(*args)
                self.assertEqual(0, r.code, r.stderr)
                self.assertNotIn("Traceback", r.stderr)
                self.assertIn("时间写错了", r.stdout)
        rows = self.coach("radar", "--json").json()["rows"]
        self.assertEqual(["03-26 周四 时间写错了", "时间写错了"], [r["when"] for r in rows], "两条都要看得见")
        self.assertTrue(all(r["pending"] for r in rows), "写坏的行进待确认，不当成已确认的 deadline")
        self.assertIn("时间写错了", self.coach("record", "deadline", "--list").stdout)


class DateFlagIsAMoment(unittest.TestCase):
    """--date 指的是一个时刻：同一条 deadline，时刻往前挪一点，剩余就该变。"""

    def setUp(self):
        self.home = seeded_home("moment", [{"course": "ACCT1101", "item": "Essay", "date": "2026-03-26",
                                            "time": "09:00", "weight": "20%"}])

    def tearDown(self):
        self.home.cleanup()

    def test_同一条_deadline_在三个时刻的三种写法(self):
        # 课程在悉尼、人在上海：三次都用悉尼时间说「现在」。
        for date, rel in (("2026-03-25T23:00:00+11:00", "明天"), ("2026-03-26T08:00:00+11:00", "今天"),
                          ("2026-03-26T10:00:00+11:00", "已过期")):
            with self.subTest(date=date):
                r = harness.run_coach(self.home, ["radar", "--json", "--date", date], TOOLS)
                self.assertEqual(0, r.code, r.stderr)
                row = next(x for x in r.json()["rows"] if x["item"] == "Essay")
                self.assertEqual(rel, row["rel"])

    def test_日期写错了还是只报一句(self):
        for bad in ("2026-02-30", "2026-03-25T25:00:00Z", "下周五"):
            with self.subTest(date=bad):
                r = harness.run_coach(self.home, ["status", "--date", bad], TOOLS)
                self.assertEqual(2, r.code, r.stderr)
                self.assertEqual(1, len([x for x in r.stderr.splitlines() if x.strip()]), r.stderr)


if __name__ == "__main__":
    unittest.main()
