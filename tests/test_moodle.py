"""Moodle：对着本机假 Moodle（tests/mockmoodle.py，场景 fixtures/moodle_term）把整条链跑一遍。

离线、只用标准库：读数据走 UrllibTransport（JIUJIASTUDY_MOODLE_TRANSPORT=urllib），「已登录」= 测试自己写好
login.json（lms=moodle）和 browser/canvas-cookies.json。要守住的：
- doctor 建档 → collect → radar → study 一条链走通；fixtures/moodle_term/README.md 的每个覆盖点按期望出现；
- 时间字段全是 ISO 字符串（parse_ts 不认 unix 整数）；
- 登录过期时 collect 原样报「重新登录」；只读：白名单外的 ajax、api post / upload 都被拒，假 Moodle 一条写请求都没收到；
- 课件下到这门课的「课件」文件夹，文件名带扩展名（Moodle 的标题常不带）。
真浏览器那组要装 playwright 并设 JIUJIASTUDY_BROWSER_TESTS=1。
"""
import datetime
import glob
import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockmoodle  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")
sys.path.insert(0, TOOLS)
import cc_collect  # noqa: E402
import cc_deadlines  # noqa: E402
import cc_time  # noqa: E402
import mdl_collect  # noqa: E402
import mdl_pages  # noqa: E402
import moodle_api  # noqa: E402
from canvas_api import CanvasAuthError  # noqa: E402

SCENARIO = "moodle_term"
ENV = {"JIUJIASTUDY_MOODLE_TRANSPORT": "urllib", "CANVAS_TOKEN": None}  # 没有 token：Moodle 只用登录
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
GRADE_ONLY = "（成绩册里有，但没找到截止日期）"
NOW_DT = datetime.datetime(2026, 9, 23, 3, 0, tzinfo=datetime.timezone.utc)
CAL_NOTE = "MDL4004：课里有 2 个作业/测验，但 Moodle 日历里这门课一个事件都没有"


def log_in(home, mock):
    """代表「用户已在登录窗口里登好」：login.json（lms=moodle）+ 浏览器存下的会话 cookie。"""
    os.makedirs(os.path.join(home.archive, "browser"), exist_ok=True)
    with open(os.path.join(home.archive, "browser", "canvas-cookies.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(mock.playwright_cookies(), f)
    with open(os.path.join(home.archive, "login.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"host": mock.base_url, "lms": "moodle", "name": "Test Student", "user_id": 1234,
                   "at": mock.scenario.meta["now"]}, f)


def coach(home, mock, *args, now=None, date=None):
    sc = mock.scenario.meta
    argv = list(args) + ["--date", date or sc["date"]]
    return harness.run_coach(home, argv, TOOLS, now=now or sc["now"], ports=(mock.port,), extra_env=ENV)


def as_json(tc, r):
    try:
        return r.json()
    except ValueError:
        tc.fail(f"{r.args} 没打印 JSON（exit {r.code}）：\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")


def jread(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class MoodleChainTest(unittest.TestCase):
    """doctor 建档 → collect → radar → study → 下载课件，一个档案从头走到尾。"""

    @classmethod
    def setUpClass(cls):
        cls.mock = mockmoodle.MockMoodle(SCENARIO).start()
        cls.home = harness.FakeHome("moodle")
        log_in(cls.home, cls.mock)
        run = lambda *a, **k: coach(cls.home, cls.mock, *a, **k)  # noqa: E731
        cls.doctor = run("doctor", "--no-detect", "--agent", "other", "--json")
        cfg = os.path.join(cls.home.archive, "config.json")
        cls.cfg = jread(cfg) if os.path.isfile(cfg) else {}  # study 之后会按模块改 week_source，先留一份
        cls.collect = run("collect", "--touch")  # 终端版：要看原文圈的标签
        cls.radar = run("radar", "--json")
        cls.radar_wide = run("radar", "--days", "50", "--json")  # 窗口放到 11-12：延期、限时作业、LTI 考试都进得来
        cls.radar_text = run("radar")
        cls.study = run("study", "--json")
        cls.status = run("status")
        A = cls.home.archive
        cls.raw = os.path.join(A, "raw", "daily", cls.mock.scenario.meta["date"])
        snap, digest = os.path.join(A, "raw", "daily", "snapshot.json"), os.path.join(cls.raw, "digest.json")
        cls.snap = jread(snap) if os.path.isfile(snap) else {}
        cls.digest = jread(digest) if os.path.isfile(digest) else {}
        cls.download = run("collect", "--download", "--json")
        cls.materials = run("collect", "--materials", "MDL2002", "5")

    @classmethod
    def tearDownClass(cls):
        cls.home.cleanup()
        cls.mock.stop()

    # ---- 小工具
    def rows(self, r=None):
        return as_json(self, r or self.radar)["rows"]

    def row(self, item, r=None):
        got = [x for x in self.rows(r) if x["item"] == item]
        self.assertEqual(1, len(got), f"雷达里「{item}」应恰好一行：{[x['item'] for x in self.rows(r)]}")
        return got[0]

    def assignment(self, aid):
        a = (self.snap.get("assignments") or {}).get(str(aid))
        self.assertIsNotNone(a, f"快照里没有作业 {aid}")
        return a

    def mats(self, code):
        got = glob.glob(os.path.join(self.home.root, f"{code}*", "课件"))
        self.assertEqual(1, len(got), f"{code} 的课件文件夹：{os.listdir(self.home.root)}")
        return got[0]

    def raw_assignment(self, cid, aid):
        a = next((x for x in jread(os.path.join(self.raw, f"assignments_{cid}.json")) if x["id"] == str(aid)), None)
        self.assertIsNotNone(a, f"assignments_{cid}.json 里没有 {aid}")
        return a

    # ---- 链条本身
    def test_doctor_用登录建档(self):
        res = as_json(self, self.doctor)
        self.assertEqual(0, self.doctor.code, res.get("text"))
        self.assertIs(True, res["ready"], res.get("text"))
        ok = {c["name"]: c["detail"] for c in res["checks"] if c["level"] == "OK"}
        self.assertIn("Moodle 登录模式", ok.get("登录", ""))
        self.assertNotIn("token", " ".join(res["must_fix"]))
        cfg = self.cfg
        self.assertEqual("moodle", cfg["lms"])
        self.assertEqual(self.mock.base_url, cfg["canvas_host"])
        self.assertEqual({"MDL1001", "MDL2002", "MDL3003", "MDL4004"}, {c["code"] for c in cfg["courses"]})  # 上学期的 4090 不在
        self.assertEqual({"start": "2026-07-27", "end": "2026-11-15", "week1_monday": "2026-07-27", "week_source": "moodle"},
                         {k: cfg["term"][k] for k in ("start", "end", "week1_monday", "week_source")})
        self.assertEqual("Australia/Sydney", cfg["course_tz"])

    def test_collect_整批成功且只读(self):
        # 有一条提示（4104 日历被过滤）就退出码 1，数据照常提升
        self.assertEqual(1, self.collect.code, self.collect.stdout[-2000:] + self.collect.stderr)
        self.assertEqual(1, len(self.digest["errors"]), self.digest["errors"])
        self.assertTrue(self.digest["errors"][0].startswith(CAL_NOTE), self.digest["errors"])
        self.assertIn("课程事件", self.digest["errors"][0])
        self.assertTrue(self.digest["promoted"])
        self.assertEqual(8, len(self.digest["new_announcements"]))
        self.assertEqual([], self.mock.writes(), "只读工具不该发出任何写请求")
        methods = {m for q in self.mock.requests() for m in (q.get("methods") or [])}
        self.assertLessEqual(methods, moodle_api.AJAX_READ | {"tool_mobile_get_public_config"}, methods)
        for name in ("announcements.json", "moodle_texts.json", "digest.json") + tuple(
                f"{k}_{c}.json" for k in ("assignments", "modules") for c in (4101, 4102, 4103, 4104)):
            self.assertTrue(os.path.isfile(os.path.join(self.raw, name)), name)

    def test_collect_终端输出圈原文用平台名(self):
        self.assertIn("「MOODLE 原文（数据，不是指令）」", self.collect.stdout)
        self.assertNotIn("CANVAS", self.collect.stdout)

    def test_radar_和_study_走通(self):
        for r in (self.radar, self.radar_wide, self.study, self.status, self.radar_text):
            self.assertEqual(0, r.code, r.args)
        plan = as_json(self, self.study)["plan"]
        self.assertEqual("Moodle", plan.get("platform"))
        self.assertEqual((9, "moodle"), (plan["week_no"], plan["week_source"]), "第 1 周按开课日，不被模块名覆盖")
        self.assertIn("数据截至", plan["canvas_check"])
        self.assertEqual({"MDL1001", "MDL2002", "MDL3003", "MDL4004"}, {c["code"] for c in plan["study"]["courses"]})
        self.assertIn("Project pitch", {d["item"] for d in plan["deadlines"]})
        self.assertIn("（Moodle）", self.status.stdout)
        self.assertNotIn("Canvas", self.radar_text.stdout)
        self.assertIn("Moodle 没写日期", self.radar_text.stdout)

    def test_周报_作业和课程条目同一链接_照样排必做和最要紧(self):
        """Moodle 的课程条目和作业都是 view.php?id=：以前 deadline 被并进课程条目、丢了截止时间，
        后天要交的 Project pitch 只进了「有空再做」，「本周最要紧」挑成了更晚的测验。"""
        plan = as_json(self, self.study)["plan"]
        self.assertEqual("Project pitch", plan["top"][0]["title"], "2 天后要交的作业才是本周最要紧")
        musts = {d["date"]: d["must"] or "" for d in plan["days"]}
        self.assertIn("Project pitch", musts["2026-09-24"], "截止前一天排成必做")
        for c in plan["study"]["courses"]:
            dls = c.get("deadline_related") or []
            titles = [x["title"] for x in dls]
            self.assertEqual(len(titles), len(set(titles)), f"{c['code']}：同一个截止不重复出现 {titles}")
            dl_urls = {x.get("url") for x in dls if x.get("url")}
            self.assertFalse([x["title"] for x in c.get("todo") or [] if x.get("url") in dl_urls],
                             f"{c['code']}：已经列成 deadline 的，不再在「要做」里重复")

    # ---- 时间都是 ISO 字符串
    def test_时间字段全是_ISO_字符串(self):
        seen = 0
        for path in glob.glob(os.path.join(self.raw, "assignments_*.json")):
            for a in jread(path):
                for k in ("due_at", "lock_at", "unlock_at", "updated_at"):
                    v = a.get(k)
                    self.assertTrue(v is None or (isinstance(v, str) and ISO_Z.match(v)), f"{a['id']} {k}={v!r}")
                    seen += v is not None
        for a in jread(os.path.join(self.raw, "announcements.json")) + jread(os.path.join(self.raw, "moodle_texts.json")):
            self.assertRegex(a["posted_at"], ISO_Z)
        for aid, a in self.snap["assignments"].items():
            for k in ("due_at", "lock_at", "unlock_at"):
                self.assertFalse(isinstance(a.get(k), (int, float)), f"{aid} {k}")
        self.assertGreater(seen, 5)

    # ---- README 覆盖点
    def test_已交已评分的作业不进待办(self):
        a = self.assignment(7003)
        self.assertEqual("graded", a["sub_state"])
        self.assertEqual("—", a["weight"], "成绩页的 Calculated weight 是按已出分项算的，不是大纲权重，不拿来显示")
        self.assertEqual(90.91, self.raw_assignment(4101, 7003)["moodle"]["calc_weight_pct"])
        self.assertNotIn("Assignment 1: Research proposal", {x["item"] for x in self.rows(self.radar_wide)})

    def test_草稿没正式提交是最急的一条(self):
        r = self.row("Project pitch")
        self.assertEqual(("未交", 2, False), (r["status"], r["days_left"], r["pending"]))
        self.assertEqual("Moodle due_at", r["src"])
        self.assertIn("**MDL2002 · Project pitch**", as_json(self, self.radar)["markdown"])

    def test_已过期没交(self):
        r = self.row("Production log")
        self.assertTrue(r["overdue"])
        self.assertEqual(-5, r["days_left"])

    def test_个人延期用延期后的时间(self):
        self.assertEqual("2026-10-16T12:59:00Z", self.assignment(7005)["due_at"])
        r = self.row("Assignment 2: Literature review", self.radar_wide)
        self.assertTrue(r["when"].startswith("10-16"), r["when"])
        self.assertEqual("未交", r["status"])
        self.assertNotIn("Assignment 2: Literature review", {x["item"] for x in self.rows()}, "10-16 在 14 天窗口外")

    def test_线下作业不按作业页判没交(self):
        a = self.raw_assignment(4102, 7104)
        self.assertEqual("2026-10-14T07:00:00Z", a["due_at"])
        self.assertNotEqual("page", a["moodle"]["status_confidence"], "没有编辑入口的 new 状态不能当作业页说了「没交」")
        self.assertNotIn(a["submission"]["workflow_state"], ("submitted", "graded"))
        self.assertIn("In-class presentation", {x["item"] for x in self.rows(self.radar_wide)})

    def test_限时作业的编辑入口是链接(self):
        a = self.raw_assignment(4103, 7203)
        self.assertEqual(("2026-10-30T12:59:00Z", "unsubmitted", "page"),
                         (a["due_at"], a["submission"]["workflow_state"], a["moodle"]["status_confidence"]))
        self.assertTrue(self.row("Essay", self.radar_wide)["when"].startswith("10-30"))

    def test_做过一次还能再做的测验算未交(self):
        r = self.row("Week 8 reading quiz")
        self.assertEqual("未交", r["status"])
        self.assertTrue(r["when"].startswith("09-27"), r["when"])
        self.assertEqual("—", r["weight"], "9.09 % 是被放大的实算权重，不是配置权重")

    def test_没做过的测验(self):
        r = self.row("Weekly quiz 9")
        self.assertEqual("未交", r["status"])
        self.assertTrue(r["when"].startswith("09-28"), r["when"])

    def test_做完且关了的测验算已交(self):
        self.assertIn(self.assignment(7204)["sub_state"], ("submitted", "graded"))
        self.assertNotIn("Practice quiz", {x["item"] for x in self.rows(self.radar_wide)})

    def test_只在成绩页出现的计分项(self):
        undated = [x for x in self.rows() if x["undated"]]
        r = self.row("Tutorial participation" + GRADE_ONLY)
        self.assertIn(r, undated)
        self.assertEqual(("MDL2002", "Moodle 没写日期"), (r["course"], r["when"]))
        peer = [a for a in self.snap["assignments"].values() if a["name"].startswith("Peer feedback")]
        self.assertEqual(1, len(peer))
        self.assertEqual("graded", peer[0]["sub_state"])  # 已有分：不进待办
        self.assertNotIn(peer[0]["name"], {x["item"] for x in self.rows()})

    def test_成绩页隐藏项和改过名的分类不产生条目(self):
        names = [a["name"] for a in self.snap["assignments"].values() if a["course"] == "MDL2002"]
        self.assertEqual(2, sum(GRADE_ONLY in n for n in names), names)  # 只有 625、627，隐藏项 626 不算
        self.assertFalse([n for n in names if "production marks" in n.lower() or "course total" in n.lower()], names)

    def test_成绩页没有权重列(self):
        for aid in ("7302", "7303"):
            a = self.raw_assignment(4104, aid)
            self.assertIsNone(a["moodle"]["calc_weight_pct"])
            self.assertEqual("—", self.snap["assignments"][aid]["weight"])

    def test_只在日历里的课程考试(self):
        a = self.assignment("ev8301")
        self.assertEqual(("MDL3003", "2026-10-12T23:00:00Z"), (a["course"], a["due_at"]))  # 10-13 10:00 悉尼
        self.assertTrue(self.row("Mid-semester exam (in class)", self.radar_wide)["when"].startswith("10-13 周二 10:00"))

    def test_站点考试事件跨月也不重复(self):
        names = [a["name"] for a in self.snap["assignments"].values()]
        self.assertLessEqual(names.count("Formal examination period"), 1, "跨两个月视图的站点事件要按 id 去重")
        self.assertNotIn("Study group", names, "个人日历事件不是 deadline")

    def test_LTI_外部考试(self):
        r = self.row("Final exam (external tool)")
        self.assertTrue(r["undated"])
        self.assertEqual("Moodle 没写日期", r["when"])
        w = self.row("Final exam (external tool)", self.radar_wide)  # 11-09 进窗口：公告里写的日期配上来
        self.assertTrue(w["pending"])
        self.assertTrue(w["when"].startswith("11-09"), w)
        self.assertIn("Final exam arrangements", w["src"])

    def test_日历过滤掉的课靠课程结构兜底(self):
        for item in ("Data report", "Module quiz"):
            r = self.row(item)
            self.assertEqual(("MDL4004", True, "日历里没看到日期（可能被过滤）"), (r["course"], r["undated"], r["when"]),
                             "不能说成「Moodle 没写日期」：学生会以为老师真的没写")

    def test_课件真实文件名(self):
        items = self.snap["items"]
        want = {"7002": "MDL1001_Unit_Outline.pdf", "7006": "W2_Lecture_Slides.pptx", "7007": "Reading list (2026).pdf",
                "7106": "Lecture 1 slides.pdf", "7205": "第三周阅读材料.pdf", "7304": "Course guide.docx"}
        self.assertEqual(want, {k: items[k].get("filename") for k in want})
        self.assertEqual("Unit outline", items["7002"]["title"])

    def test_folder_每个文件一条(self):
        files = {k: v for k, v in self.snap["items"].items() if k.startswith("f7107:")}
        self.assertEqual({"Smith 2019 - Media production.pdf", "第五周阅读笔记.docx", "shot-list-template.xlsx"},
                         {v["title"] for v in files.values()})
        for v in files.values():
            self.assertIn("/pluginfile.php/17107/mod_folder/content/", v["content_id"])
            self.assertEqual("File", v["type"])

    def test_锁住的课件和页面(self):
        for iid in ("7206", "7011"):
            self.assertTrue(self.snap["items"][iid]["locked"], iid)
        self.assertNotIn("filename", self.snap["items"]["7206"], "锁住的课件不去问文件名")

    def test_公告(self):
        anns = jread(os.path.join(self.raw, "announcements.json"))
        by = {}
        for a in anns:
            by.setdefault(a["context_code"], set()).add(a["id"])
        self.assertEqual({"course_4101": {"mdl501", "mdl502", "mdl503"}, "course_4102": {"mdl511", "mdl512", "mdl513"},
                          "course_4103": {"mdl521", "mdl522"}}, by)  # 两个公告论坛合并；Q&A 论坛（514）和空论坛不收
        a503 = next(a for a in anns if a["id"] == "mdl503")
        self.assertIn("Thursday 24 September", a503["message"])
        self.assertNotIn("Room 1.10", a503["message"], "正文取首帖，不取回复")

    def test_课程页文字交给找日期(self):
        texts = jread(os.path.join(self.raw, "moodle_texts.json"))
        blob = " ".join(t["message"] for t in texts if t["context_code"] == "course_4101")
        self.assertIn("20 October 2026", blob)
        self.assertTrue(all(t.get("id") for t in texts))

    def test_周名和日期名混着(self):
        names = [m["name"] for m in jread(os.path.join(self.raw, "modules_4103.json"))]
        self.assertIn("Week 12: Essay writing", names)
        self.assertIn("21 September - 27 September", names)

    # ---- 课件下载
    def test_课件下进课件文件夹且带扩展名(self):
        res = as_json(self, self.download)
        got = (res.get("downloads") or {}).get("downloaded") or []
        self.assertTrue(got, res)
        mats = self.mats("MDL1001")
        names = set(os.listdir(mats))
        self.assertLessEqual({"MDL1001_Unit_Outline.pdf", "W2_Lecture_Slides.pptx", "Reading list (2026).pdf"}, names)
        for d in got:
            self.assertEqual("课件", os.path.basename(os.path.dirname(d["saved"])))
            self.assertRegex(d["saved"], r"\.(pdf|pptx|docx|doc)$")
        self.assertEqual([], self.mock.writes())

    def test_按周补下_folder_里的课件(self):
        self.assertEqual(0, self.materials.code, self.materials.stdout + self.materials.stderr)
        self.assertIn("Smith 2019 - Media production.pdf", self.materials.stdout)  # 前面 --download 已下过：认得出是同一个
        self.assertIn("already", self.materials.stdout)
        names = set(os.listdir(self.mats("MDL2002")))
        self.assertLessEqual({"Smith 2019 - Media production.pdf", "第五周阅读笔记.docx"}, names)


class MoodleReadOnlyTest(unittest.TestCase):
    """登录过期、白名单、写操作：每个用例一个干净的档案（config 从场景 seed）。"""

    def setUp(self):
        self.mock = mockmoodle.MockMoodle(SCENARIO).start()
        self.home = harness.FakeHome("moodle-ro")
        self.home.seed(self.mock.scenario, self.mock.base_url)
        log_in(self.home, self.mock)

    def tearDown(self):
        self.home.cleanup()
        self.mock.stop()

    def client(self, cookies=None):
        jar = moodle_api.UrllibTransport(cookies=cookies if cookies is not None else self.mock.playwright_cookies())
        return moodle_api.MoodleClient(self.mock.base_url, self.home.archive, retries=0, transport=jar)

    def test_登录过期_collect_报重新登录(self):
        self.mock.expire_session()
        r = coach(self.home, self.mock, "collect", "--json")
        res = as_json(self, r)
        self.assertEqual(2, r.code, res)
        self.assertIn("重新登录", res["error"])
        self.assertIn("login", res["error"])
        self.assertFalse(os.path.exists(os.path.join(self.home.archive, "raw", "daily", "snapshot.json")))
        self.assertEqual("expired", as_json(self, coach(self.home, self.mock, "login", "--check", "--json"))["state"])
        self.assertEqual([], self.mock.writes())

    def test_转去学校登录页或访客也是重新登录(self):
        for mode in ("sso", "guest"):
            with self.subTest(mode=mode):
                old = self.mock.playwright_cookies()  # 过期前存下的那份
                self.mock.logged_out = mode
                self.mock.expire_session()
                with self.assertRaises(CanvasAuthError):
                    self.client(old).ajax("core_courseformat_get_state", {"courseid": 4101})
                with self.assertRaises(CanvasAuthError):
                    self.client(old).page("/grade/report/user/index.php?id=4101")
                with self.assertRaises(CanvasAuthError):
                    self.client(old).whoami()

    def test_sesskey_换了重取一次(self):
        api = self.client()
        self.assertEqual(1234, api.whoami()["id"])
        self.mock.new_sesskey()
        self.assertIsInstance(api.ajax("core_courseformat_get_state", {"courseid": 4101}), str)

    def test_白名单外的_ajax_不发请求(self):
        api = self.client()
        api.sesskey()
        self.mock.requests(clear=True)
        for name in ("core_user_update_user_preferences", "mod_forum_add_discussion", "mod_assign_save_submission",
                     "core_message_send_instant_messages"):
            with self.assertRaises(moodle_api.MoodleError):
                api.ajax(name, {})
        with self.assertRaises(moodle_api.MoodleError):
            api.get("/api/v1/users/self")
        with self.assertRaises(moodle_api.MoodleError):
            api.page("https://elsewhere.example.edu/login")
        self.assertEqual([], self.mock.requests())

    def test_api_post_和_upload_被拒(self):
        for args in (["api", "post", "/mod/forum/post.php", '{"subject": "hi"}', "--json"],
                     ["api", "upload", "4101", "7005", "--json"]):
            with self.subTest(op=args[1]):
                r = coach(self.home, self.mock, *args)
                self.assertEqual(2, r.code, r.stdout + r.stderr)
                self.assertIn("只能读", r.stdout + r.stderr)
                self.assertIn("Moodle", r.stdout + r.stderr)
        self.assertEqual([], [q for q in self.mock.requests() if q["method"] != "GET"])
        self.assertEqual([], self.mock.writes())

    def test_api_get_在_Moodle_下说清楚(self):
        r = coach(self.home, self.mock, "api", "get", "/api/v1/users/self")
        self.assertEqual(2, r.code)
        self.assertIn("Moodle", r.stdout + r.stderr)

    def test_api_download_单个课件(self):
        with tempfile.TemporaryDirectory() as d:
            r = coach(self.home, self.mock, "api", "download", "7006", d)
            self.assertEqual(0, r.code, r.stderr)
            got = json.loads(r.stdout)
            self.assertEqual("W2_Lecture_Slides.pptx", os.path.basename(got["saved"]))
            r = coach(self.home, self.mock, "api", "download", "7206", d)  # 锁住的
            self.assertTrue(json.loads(r.stdout).get("locked"))

    def test_quick_用上次读到的状态(self):
        self.assertTrue(as_json(self, coach(self.home, self.mock, "collect", "--json"))["promoted"])
        self.mock.requests(clear=True)
        r = coach(self.home, self.mock, "collect", "--quick", "--force", "--json")
        self.assertIn(r.code, (0, 1), r.stdout)
        self.assertTrue(as_json(self, r)["promoted"])
        paths = {q["path"] for q in self.mock.requests()}
        self.assertFalse({p for p in paths if p.startswith(("/mod/assign/", "/mod/quiz/", "/grade/"))}, paths)
        snap = jread(os.path.join(self.home.archive, "raw", "daily", "snapshot.json"))
        self.assertEqual("graded", snap["assignments"]["7003"]["sub_state"])


class DoctorWithoutLoginTest(unittest.TestCase):
    def test_没登录的_Moodle_待办是_login_不是_token(self):
        with mockmoodle.MockMoodle(SCENARIO) as mock:
            home = harness.FakeHome("moodle-doctor")
            try:
                r = harness.run_coach(home, ["doctor", "--no-detect", "--host", mock.base_url + "/login/index.php", "--agent", "other",
                                             "--json"], TOOLS, now=mock.scenario.meta["now"], ports=(mock.port,), extra_env=ENV)
                res = as_json(self, r)
                todo = " ".join(res["must_fix"])
                self.assertIn("login", todo)
                self.assertNotIn("token", todo.lower())
                self.assertFalse(os.path.exists(os.path.join(home.archive, "config.json")))
                self.assertEqual(0, mock.logins)
            finally:
                home.cleanup()


def _ts(iso):
    return int(datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _ev(eid, cmid, kind, when, mod="assign"):
    return {"id": eid, "instance": cmid, "modulename": mod, "eventtype": kind, "timestart": _ts(when), "name": f"ev {eid}"}


class _FixedClock:
    """_window 只用 now_utc / course_date。"""

    def __init__(self, now):
        self.now = datetime.datetime.fromisoformat(now.replace("Z", "+00:00"))

    def now_utc(self):
        return self.now

    def course_date(self, t):
        return t.date()


class _FakeCtx:
    def __init__(self, cfg, now=None, home=None):
        self.cfg, self.state, self.home = cfg, {}, home
        self.clock = _FixedClock(now) if now else cc_time.Clock(cfg)

    def P(self, *a):
        return os.path.join(self.home or tempfile.gettempdir(), *a)


HOST = "https://moodle.example.edu"


class MoodleBuildUnit(unittest.TestCase):
    """mdl_collect 的纯函数：不联网，直接喂数据。"""

    def snap(self, rows, code="MDL5005"):
        return cc_collect.snapshot_from([(4105, code)], {code: rows}, {code: None}, {}, {}, {})["assignments"]

    def test_互评两个成绩项两个截止_经快照后各留一条有日期的(self):
        cms = [{"id": 50, "module": "workshop", "name": "Peer review", "url": f"{HOST}/mod/workshop/view.php?id=50"}]
        by_cm = {"50": [_ev(1, 50, "closesubmission", "2026-09-21T13:59:00Z", "workshop"),
                        _ev(2, 50, "closeassessment", "2026-10-03T13:59:00Z", "workshop")]}
        grades = [{"name": "Peer review (submission)", "cmid": 50, "module": "workshop", "item_id": 801, "range_max": 80.0},
                  {"name": "Peer review (assessment)", "cmid": 50, "module": "workshop", "item_id": 802, "range_max": 20.0}]
        rows = mdl_collect._build(4105, cms, by_cm, [], grades, {}, set(), HOST, NOW_DT)
        ids = [r["id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)), ids)
        snap = self.snap(rows)
        self.assertEqual(2, len(snap), snap)
        got = sorted((a["due_at"], a["name"], a["points"]) for a in snap.values())
        self.assertEqual([("2026-09-21T13:59:00Z", "Peer review（提交）", 80.0), ("2026-10-03T13:59:00Z", "Peer review（互评）", 20.0)], got)

    def test_同一活动两个成绩项_截止日期不被成绩册那行盖掉(self):
        cms = [{"id": 60, "module": "forum", "name": "Graded discussion", "url": f"{HOST}/mod/forum/view.php?id=60"}]
        by_cm = {"60": [_ev(3, 60, "due", "2026-10-01T13:59:00Z", "forum")]}
        grades = [{"name": "Graded discussion whole forum", "cmid": 60, "module": "forum", "item_id": 901, "range_max": 10.0},
                  {"name": "Graded discussion rating", "cmid": 60, "module": "forum", "item_id": 902, "range_max": 5.0}]
        rows = mdl_collect._build(4105, cms, by_cm, [], grades, {}, None, HOST, NOW_DT)
        ids = [r["id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)), ids)
        snap = self.snap(rows)
        self.assertEqual(["2026-10-01T13:59:00Z"], [a["due_at"] for a in snap.values()])
        self.assertNotIn(GRADE_ONLY, " ".join(a["name"] for a in snap.values()))

    def test_成绩册里同一_cmid_的两项另起不同的_id(self):
        grades = [{"name": "Lab (part A)", "cmid": 70, "module": "workshop", "item_id": 1},
                  {"name": "Lab (part B)", "cmid": 70, "module": "workshop", "item_id": 2}]
        rows = mdl_collect._build(4105, [], {}, [], grades, {}, None, HOST, NOW_DT)
        self.assertEqual(["70", "70:g2"], [r["id"] for r in rows])

    def test_推断出的可能已交不算已交(self):
        past = (NOW_DT - datetime.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cms = [{"id": 77, "module": "assign", "name": "Essay draft"}, {"id": 78, "module": "quiz", "name": "Closed quiz"}]
        by_cm = {"77": [_ev(5, 77, "due", past)], "78": [_ev(6, 78, "close", past, "quiz")]}
        rows = mdl_collect._build(4105, cms, by_cm, [], [], {}, set(), HOST, NOW_DT)  # 时间线读到了，但两条都不在里面
        st = {r["id"]: (r["submission"]["workflow_state"], r["moodle"]["status_confidence"]) for r in rows}
        self.assertEqual({"77": ("unsubmitted", "maybe"), "78": ("unsubmitted", "unknown")}, st)
        for s, _ in st.values():
            self.assertNotIn(s, cc_deadlines.SUBMITTED)
        cfg = {"lms": "moodle", "course_tz": "UTC", "user_tz": "UTC", "courses": [{"id": 4105, "code": "MDL5005"}]}
        ctx = _FakeCtx(cfg)
        ctx.clock.now_utc = lambda: NOW_DT
        rs = {r["item"]: r for r in cc_deadlines.deadline_rows(ctx, {"assignments": self.snap(rows)}, NOW_DT.date())}
        self.assertEqual({"Essay draft", "Closed quiz"}, set(rs), "过期没交的要进「已过期未交」")
        self.assertTrue(all(r["overdue"] and not r["submitted"] for r in rs.values()))
        self.assertEqual(("可能已交，待确认", True), (rs["Essay draft"]["status"], rs["Essay draft"]["pending"]))
        self.assertEqual("未交", rs["Closed quiz"]["status"])

    def test_测验只有两行能回顾_不能再做_不当没交也不当已交(self):
        card = ('<li><div class="card"><table class="generaltable generalbox quizreviewsummary"><tbody>'
                '<tr><th>Status</th><td>Submitted</td></tr><tr><th>Started</th><td>x</td></tr></tbody></table>'
                '<div class="card-body"><a href="https://m.example/mod/quiz/review.php?attempt=9&amp;cmid=80">Review</a></div></div></li>')
        page = (f'<html><body id="page-mod-quiz-view" class="path-mod path-mod-quiz"><ul class="list-unstyled">{card}</ul>'
                '<div class="box py-3 quizattempt"><p>No more attempts are allowed</p></div></body></html>')
        r = mdl_pages.quiz_status(page)
        self.assertEqual((0, 1, False), (r["attempts_finished"], r["reviewable"], r["can_attempt_again"]))
        s = mdl_collect._page_status("quiz", page)
        self.assertIsNone(s["state"])
        self.assertEqual(("unsubmitted", "maybe"), mdl_collect._status("quiz", "80", s, set(), True, None))

    def test_只有预期完成日期的计分活动不丢日期(self):
        evs = [_ev(7, 90, "expectcompletionon", "2026-10-15T13:59:00Z", "lti"),
               _ev(8, 91, "expectcompletionon", "2026-10-20T13:59:00Z", "quiz"), _ev(9, 91, "close", "2026-10-10T13:59:00Z", "quiz")]
        by_cm, extra, expect = mdl_collect._split_events(evs)
        self.assertEqual(([], ["90", "91"]), (extra, sorted(expect)))
        cms = [{"id": 90, "module": "lti", "name": "Online exam"}, {"id": 91, "module": "quiz", "name": "Quiz 3"}]
        rows = {r["id"]: r for r in mdl_collect._build(4105, cms, by_cm, extra, [], {}, None, HOST, NOW_DT, expect)}
        self.assertEqual(("2026-10-15T13:59:00Z", "expected"), (rows["90"]["due_at"], rows["90"]["moodle"]["date_from"]))
        self.assertEqual(("2026-10-10T13:59:00Z", "calendar"), (rows["91"]["due_at"], rows["91"]["moodle"]["date_from"]),
                         "预期完成日期不能盖过真正的截止")
        self.assertEqual({"status_confidence": "unknown", "date_from": "expected"}, self.snap(list(rows.values()))["90"]["moodle"])

    def test_学期早结束时日历往后读半年(self):
        ctx = _FakeCtx({"term": {"start": "2026-02-23", "end": "2026-06-30"}}, now="2026-09-23T03:00:00Z")
        start, end = mdl_collect._window(ctx)
        self.assertEqual(datetime.date(2026, 8, 24), start)
        self.assertGreaterEqual(end, datetime.date(2026, 11, 30), "11 月的截止要拉得到")

    def test_读取失败的话带中文原因(self):
        e = moodle_api.MoodleError("core_courseformat_get_state: requireloginerror", errorcode="requireloginerror")
        self.assertEqual("MDL1001 这门课打不开了（可能退课或课程已结束）", mdl_collect.error_text(e, "MDL1001 课程结构", "MDL1001"))
        self.assertIsNone(mdl_collect.error_text(mdl_collect.CalendarMissing("日历没读到"), "MDL1001 的截止日期", "MDL1001"))
        self.assertEqual("MDL1001 课程结构：课程结构读不懂",
                         mdl_collect.error_text(ValueError("课程结构读不懂"), "MDL1001 课程结构", "MDL1001"))


class MoodleFixesChain(unittest.TestCase):
    """复查确认的问题：每个用例一个干净的档案，对着假 Moodle 跑 coach。"""

    def setUp(self):
        self.mock = mockmoodle.MockMoodle(SCENARIO).start()
        self.home = harness.FakeHome("moodle-fix")
        self.home.seed(self.mock.scenario, self.mock.base_url)
        log_in(self.home, self.mock)

    def tearDown(self):
        self.home.cleanup()
        self.mock.stop()

    def run_json(self, *args):
        r = coach(self.home, self.mock, *args)
        return r, as_json(self, r)

    def collected(self, *extra):
        """collect 提升了快照（fixture 里 4104 的日历被过滤，总有那一条提示，退出码是 1）。"""
        r, res = self.run_json("collect", "--json", *extra)
        self.assertTrue(res.get("promoted"), res)
        self.assertIn(r.code, (0, 1), res)
        return res

    def snapshot(self):
        return jread(os.path.join(self.home.archive, "raw", "daily", "snapshot.json"))

    def client(self, cookies=None):
        jar = moodle_api.UrllibTransport(cookies=cookies if cookies is not None else self.mock.playwright_cookies())
        return moodle_api.MoodleClient(self.mock.base_url, self.home.archive, retries=0, transport=jar)

    def test_仪表盘上隐藏的课不算退课(self):
        self.mock.dashboard_hidden.add(4103)
        self.collected()
        cfg = jread(os.path.join(self.home.archive, "config.json"))
        self.assertFalse([c["code"] for c in cfg["courses"] if c.get("inactive")])
        self.assertTrue(any(a["course"] == "MDL3003" and a["name"] == "Essay" for a in self.snapshot()["assignments"].values()))

    def test_建档_隐藏的课和刚结课的课都要(self):
        home = harness.FakeHome("moodle-boot")
        try:
            log_in(home, self.mock)
            self.mock.dashboard_hidden.add(4102)
            meta = next(c for c in self.mock.scenario.courses if c["id"] == 4103)
            meta["enddate"] = "2026-09-13T13:00:00Z"  # 结课 10 天了：考试周第一次建档
            r = coach(home, self.mock, "doctor", "--no-detect", "--agent", "other", "--json")
            self.assertEqual(0, r.code, r.stdout[-1500:])
            cfg = jread(os.path.join(home.archive, "config.json"))
            self.assertEqual({"MDL1001", "MDL2002", "MDL3003", "MDL4004"}, {c["code"] for c in cfg["courses"]})
            self.assertTrue(any("仪表盘上隐藏了 MDL2002" in n for n in cfg["notes"]), cfg["notes"])
            r = coach(home, self.mock, "collect", "--json")
            cfg = jread(os.path.join(home.archive, "config.json"))
            self.assertFalse([c["code"] for c in cfg["courses"] if c.get("inactive")], r.stdout[-800:])
        finally:
            home.cleanup()

    def test_评过分又被重开的作业要重交(self):
        a = self.mock.scenario.cms[7102]["assign"]
        a.update(status="submitted", graded=True, grade="80.00", submitted_at="2026-09-22T11:40:00Z")
        self.collected()
        self.assertEqual("graded", self.snapshot()["assignments"]["7102"]["sub_state"])
        a.update(status="reopened", graded=False)
        self.collected("--force")
        self.assertEqual("unsubmitted", self.snapshot()["assignments"]["7102"]["sub_state"])

    def test_登录过期时补下课件说重新登录(self):
        self.collected()
        self.mock.expire_session()
        r = coach(self.home, self.mock, "collect", "--materials", "MDL2002", "5")
        out = r.stdout + r.stderr
        self.assertEqual(2, r.code, out)
        self.assertIn("重新登录", out)
        self.assertNotIn("没有可下载的课件", out)
        self.assertNotIn("/api/v1/files", out)

    def test_关了_slasharguments_课件照样拿到(self):
        self.mock.slasharguments = 0
        api = self.client()
        meta = api.file_meta("7006")
        self.assertEqual((False, "W2_Lecture_Slides.pptx"), (meta["locked_for_user"], meta["filename"]))
        self.assertIn("/pluginfile.php?file=", meta["url"])
        files = mdl_pages.folder_files(api.page("/mod/folder/view.php?id=7107"))
        url = next(f["url"] for f in files if f["name"] == "Smith 2019 - Media production.pdf")
        self.assertEqual("Smith 2019 - Media production.pdf", api.file_meta(url)["display_name"])
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual("W2_Lecture_Slides.pptx", os.path.basename(api.download(7006, d)["saved"]))
            self.assertEqual("Smith 2019 - Media production.pdf", os.path.basename(api.download(url, d)["saved"]))

    def test_4_4_没有_userId_的访客页也是重新登录(self):
        self.mock.release = "4.4"
        self.assertEqual({"id": None, "name": "Test Student"}, self.client().whoami(), "登录着的 4.4 页面不能误判")
        old = self.mock.playwright_cookies()
        self.mock.logged_out = "guest"
        self.mock.expire_session()
        with self.assertRaises(CanvasAuthError):
            self.client(old).whoami()
        with self.assertRaises(CanvasAuthError):
            self.client(old).page("/mod/forum/view.php?id=7101")

    def test_读取失败写中文原因_不写英文类名(self):
        self.mock.force_ajax_error("core_courseformat_get_state", "requireloginerror")
        _, res = self.run_json("collect", "--json")
        self.assertIn("MDL1001 这门课打不开了（可能退课或课程已结束）", res["errors"])
        self.assertFalse([e for e in res["errors"] if "MoodleError" in e], res["errors"])

    def test_网关挡住日历_原因不丢_也不按课重复(self):
        self.mock.force_status(r"info=core_calendar_get_calendar_monthly_view", 200)
        _, res = self.run_json("collect", "--json")
        self.assertTrue([e for e in res["errors"] if "不是 JSON" in e], res["errors"])
        self.assertFalse([e for e in res["errors"] if "MoodleError" in e or "CalendarMissing" in e], res["errors"])

    def test_公告论坛页认不出要点名(self):
        self.mock.force_status(r"/mod/forum/view\.php\?id=7201$", 200)  # 200 的提示页，不带 forumtype-*
        self.collected()
        digest = jread(os.path.join(self.home.archive, "raw", "daily", self.mock.scenario.meta["date"], "digest.json"))
        self.assertTrue([e for e in digest["errors"] if e.startswith("MDL3003 公告没读到")], digest["errors"])

    def test_第一次没问到文件名的课件_下次补排队(self):
        self.mock.force_status(r"/mod/resource/view\.php\?id=7006&redirect=1$", 404)
        self.collected()
        self.assertNotIn("filename", self.snapshot()["items"]["7006"])
        self.mock._force.clear()
        self.collected("--force")
        d = jread(os.path.join(self.home.archive, "raw", "downloads.json"))
        self.assertIn("7006", {q["id"] for q in d["queue"] + d["done"] + d["in_progress"]})

    def test_login_forget_不叫人回到_token(self):
        r, res = self.run_json("login", "--forget", "--json")
        self.assertEqual(0, r.code, res)
        self.assertTrue(res["forgotten"])
        self.assertNotIn("回到 token 方式", res["message"])
        self.assertIn("login", res["message"])


def _browser_tests_on():
    if os.environ.get("JIUJIASTUDY_BROWSER_TESTS") != "1":
        return False
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


@unittest.skipUnless(_browser_tests_on(), "真浏览器测试：装 playwright 并设 JIUJIASTUDY_BROWSER_TESTS=1")
class RealBrowserMoodle(unittest.TestCase):
    def test_登录_读_下载_过期(self):
        import cc_session
        with mockmoodle.MockMoodle(SCENARIO) as mock, tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as home:
            r = cc_session.start_login(home, mock.base_url, wait=60, lms="moodle")
            self.assertEqual("done", r["state"], r)
            self.assertEqual(1, mock.logins)
            self.assertEqual("moodle", cc_session.read_login(home).get("lms"))

            api = moodle_api.MoodleClient(mock.base_url, home, transport=moodle_api.PlaywrightTransport(home=home))
            self.assertEqual(1234, api.whoami()["id"])
            self.assertIn("courses", api.ajax("core_course_get_enrolled_courses_by_timeline_classification",
                                              {"classification": "inprogress", "limit": 0, "offset": 0}))
            with tempfile.TemporaryDirectory() as d:
                got = api.download(7002, d)
                self.assertEqual("MDL1001_Unit_Outline.pdf", os.path.basename(got["saved"]))
            api.close()
            self.assertEqual("ok", cc_session.check(home)["state"])
            self.assertEqual(1, mock.logins, "没过期就不该再登录")
            self.assertEqual([], mock.writes())

            mock.expire_session()
            api = moodle_api.MoodleClient(mock.base_url, home, transport=moodle_api.PlaywrightTransport(home=home))
            with self.assertRaises(CanvasAuthError):
                api.whoami()
            api.close()
            self.assertEqual("expired", cc_session.check(home)["state"])


if __name__ == "__main__":
    unittest.main()
