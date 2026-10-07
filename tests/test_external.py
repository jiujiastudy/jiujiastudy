"""外部平台的保底清单、读的结果、给 AI 的「还差」和给学生的情况句（发起人 10-07：相关的都去找去读，不推给学生；
没读到只说情况）。browse 本身要真浏览器，这里只测它判断「读到了 / 要登录 / 人机验证」的那一步。
"""
import datetime as dt
import os
import shutil
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")
sys.path.insert(0, TOOLS)
import cc_external  # noqa: E402
import cc_gaps  # noqa: E402

NOW = dt.datetime(2026, 10, 7, 0, 0, tzinfo=dt.timezone.utc)
MODS = [
    {"name": "Padlets", "items": [
        {"type": "ExternalUrl", "title": "Listening and Reading Padlet", "external_url": "https://padlet.com/sydney/lr"},
        {"type": "ExternalUrl", "title": "Teacher Biographies Links to an external site.", "external_url": "https://padlet.com/sydney/people"}]},
    {"name": "Week 9 - Editing Audio", "items": [
        {"type": "ExternalTool", "title": "Ed Discussion", "html_url": "https://canvas.example.edu/courses/7/modules/items/1"},
        {"type": "Page", "title": "Week 9 Screenings", "html_url": "https://canvas.example.edu/courses/7/pages/x"}]},
    {"name": "Student Resources", "items": [
        {"type": "ExternalUrl", "title": "Archive.org", "external_url": "https://archive.org/index.php"},
        {"type": "ExternalUrl", "title": "W5 Studio", "external_url": "https://example.org/studio"}]},
]
ANNS = [
    {"id": 1, "context_code": "course_7", "title": "Week 9 Zoom", "posted_at": "2026-10-03T02:00:00Z",
     "message": '<p>Join <a href="https://uni.zoom.us/j/123">here</a>. Readings on '
                '<a href="https://docs.google.com/document/d/abcDEF/edit">this doc</a>, survey '
                '<a href="https://sydney.au1.qualtrics.com/jfe/form/SV_1">form</a>, '
                '<a href="https://canvas.example.edu/courses/7/pages/y">page</a>, '
                '<a href="mailto:a@b.c">mail</a>.</p>'},
    {"id": 2, "context_code": "course_7", "title": "Old", "posted_at": "2026-08-01T00:00:00Z",
     "message": '<a href="https://padlet.com/sydney/old">old</a>'},
    {"id": 3, "context_code": "course_8", "title": "Other course", "posted_at": "2026-10-03T00:00:00Z",
     "message": '<a href="https://edstem.org/au/courses/1">Ed</a>'},
]


def links():
    return cc_external.collect_links(MODS, ANNS, 7, "https://canvas.example.edu", NOW - dt.timedelta(days=14))


class Classify(unittest.TestCase):
    def test_按网址认平台(self):
        self.assertEqual(cc_external.classify("https://padlet.com/x"), ("Padlet", "内容"))
        self.assertEqual(cc_external.classify("https://edstem.org/au/courses/1"), ("Ed", "通知作业"))
        self.assertEqual(cc_external.classify("https://docs.google.com/forms/d/1"), ("Google 表单", "表单"))
        self.assertEqual(cc_external.classify("https://uni.zoom.us/j/1"), ("Zoom", "会议"))
        self.assertIsNone(cc_external.classify("mailto:a@b.c"))
        self.assertIsNone(cc_external.classify("https://url.au.m.mimecastprotect.com/s/x"))
        self.assertEqual(cc_external.classify("https://example.org/a")[0], "其他网站：example.org")

    def test_只有外部工具才按标题认(self):
        self.assertEqual(cc_external.classify("https://x/", "Ed Discussion", tool=True), ("Ed", "通知作业"))
        self.assertEqual(cc_external.classify("https://example.org/studio", "W5 Studio")[0], "其他网站：example.org")


class Collect(unittest.TestCase):
    def test_模块外链_外部工具_近期公告里的链接(self):
        got = {x["url"]: x for x in links()}
        self.assertIn("https://padlet.com/sydney/lr", got)
        self.assertEqual(got["https://padlet.com/sydney/people"]["title"], "Teacher Biographies", "去掉 Canvas 的读屏提示")
        self.assertEqual(got["https://canvas.example.edu/courses/7/modules/items/1"]["platform"], "Ed")
        self.assertEqual(got["https://canvas.example.edu/courses/7/modules/items/1"]["week"], 9)
        self.assertIn("https://docs.google.com/document/d/abcDEF/edit", got)
        self.assertNotIn("https://canvas.example.edu/courses/7/pages/y", got, "本校 Canvas 里的页面不算外部平台")
        self.assertNotIn("https://padlet.com/sydney/old", got, "超过 14 天的公告不算")
        self.assertNotIn("https://edstem.org/au/courses/1", got, "别的课的公告不算")


class GapsAndLines(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="stc-ext-")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def gaps(self, weekly=True, week=9):
        return {x["cmd"].split()[1] for x in cc_external.gap_items(self.home, "C7", links(), NOW, week=week, weekly=weekly)}

    def test_按周分的课只读这周模块和公告里的_不读整学期的资源站和会议表单(self):
        got = self.gaps(weekly=True, week=9)
        self.assertIn("https://canvas.example.edu/courses/7/modules/items/1", got, "这周模块里的 Ed")
        self.assertIn("https://docs.google.com/document/d/abcDEF/edit", got, "公告里的文档")
        self.assertNotIn("https://archive.org/index.php", got)
        self.assertNotIn("https://padlet.com/sydney/lr", got)
        self.assertNotIn("https://uni.zoom.us/j/123", got)
        self.assertNotIn("https://sydney.au1.qualtrics.com/jfe/form/SV_1", got)

    def test_不按周分的课模块里只算活的平台(self):
        got = self.gaps(weekly=False)
        self.assertIn("https://padlet.com/sydney/lr", got)
        self.assertNotIn("https://archive.org/index.php", got, "整学期挂着的普通网站不用每周读")

    def test_视频不进还差(self):
        self.assertEqual(cc_external.classify("https://www.youtube.com/watch?v=1"), ("YouTube", "视频"))

    def test_读过或者这周试过的不再列(self):
        cc_external.record(self.home, "C7", "https://padlet.com/sydney/lr", "ok", NOW - dt.timedelta(days=2))
        cc_external.record(self.home, "C7", "https://padlet.com/sydney/people", "login", NOW - dt.timedelta(days=1))
        got = self.gaps(weekly=False)
        self.assertNotIn("https://padlet.com/sydney/lr", got)
        self.assertNotIn("https://padlet.com/sydney/people", got)
        cc_external.record(self.home, "C7", "https://padlet.com/sydney/lr", "ok", NOW - dt.timedelta(days=9))
        self.assertIn("https://padlet.com/sydney/lr", self.gaps(weekly=False), "一周前读的，这周再读")

    def test_情况句_只给可能有作业的平台_只说情况(self):
        cc_external.record(self.home, "C7", "https://edstem.org/x", "login", NOW, platform="Ed", kind="通知作业")
        cc_external.record(self.home, "C7", "https://padlet.com/y", "bot", NOW, platform="Padlet", kind="内容")
        self.assertEqual(cc_external.situation_lines(self.home, "C7", NOW),
                         ["这次没读到 Ed，Ed 上这周有没有新作业还不确定，下次会再试。"])
        cc_external.record(self.home, "C7", "https://edstem.org/x", "ok", NOW, platform="Ed", kind="通知作业")
        self.assertEqual(cc_external.situation_lines(self.home, "C7", NOW), [])

    def test_还差里带上外部平台(self):
        ctx = types.SimpleNamespace(home=self.home, state={}, clock=types.SimpleNamespace(now_utc=lambda: NOW))
        plan = {"week_no": 9, "study": {"courses": [{"code": "C7", "detect": "module-name", "external": links()}]}}
        keys = {x["key"] for x in cc_gaps.for_ai(ctx, plan, NOW.date())}
        self.assertIn(cc_external.key_of("C7", "https://docs.google.com/document/d/abcDEF/edit"), keys)


class Judge(unittest.TestCase):
    def test_读到了_要登录_人机验证(self):
        j = cc_external.judge
        self.assertEqual(j("https://padlet.com/a", "https://padlet.com/a", "Padlet", "Week 9 readings", False), "ok")
        self.assertEqual(j("https://edstem.org/au", "https://login.microsoftonline.com/x/saml2", "Sign in", "", False), "login")
        self.assertEqual(j("https://edstem.org/au", "https://edstem.org/au/login", "Ed", "Log in", True), "login")
        self.assertEqual(j("https://x.org", "https://x.org", "Just a moment...", "Checking your browser", False), "bot")

    def test_谷歌文档走导出纯文本(self):
        self.assertEqual(cc_external.export_url("https://docs.google.com/document/d/ID_1/edit?usp=sharing"),
                         "https://docs.google.com/document/d/ID_1/export?format=txt")
        self.assertIsNone(cc_external.export_url("https://padlet.com/x"))

    def test_中文界面的Cloudflare等待页和同站登录页(self):
        j = cc_external.judge
        self.assertEqual(j("https://openai.com/a", "https://openai.com/a", "请稍候…", "正在执行安全验证", False), "bot",
                         "10-07：浏览器是中文界面，Cloudflare 的等待页被当成读到了")
        self.assertEqual(j("https://x.org/a", "https://x.org/a", "X", "some text", False, challenge=True), "bot")
        self.assertEqual(j("https://padlet.com/sydney/b", "https://padlet.com/auth/login?referrer=x", "Padlet", "Log in", False), "login")


# ---------------------------------------------------------------- 第 8 块：Opus 和 Haiku 对比实验找到的漏洞（10-07）

class MoreSources(unittest.TestCase):
    def test_周次写法(self):
        w = cc_external.weeks_in
        self.assertEqual(w("Information for Weeks 7, 8 and 9"), {7, 8, 9})
        self.assertEqual(w("Week 11/12 drafts"), {11, 12})
        self.assertEqual(w("Weeks 7-9"), {7, 8, 9})
        self.assertEqual(w("Week 9 2026"), {9})
        self.assertEqual(w("Weekly Materials"), set())

    def test_公告里链接文字只有here的Canvas外部工具_靠前后的字认(self):
        anns = [{"id": 9, "context_code": "course_7", "title": "IMPORTANT: Online classes", "posted_at": "2026-09-29T00:00:00Z",
                 "message": '<p>Book the Audio Studio after hours.</p><p>You can find the Zoom links for each class in the Zoom tab '
                            'on Canvas <a href="https://canvas.example.edu/courses/7/external_tools/11159">here</a>.</p>'}]
        got = cc_external.collect_links([], anns, 7, "https://canvas.example.edu", NOW - dt.timedelta(days=14))
        self.assertEqual([(x["platform"], x["kind"]) for x in got], [("Zoom", "会议")])
        anns[0]["message"] = '<p>Book the Audio Studio <a href="https://canvas.example.edu/courses/7/external_tools/2">here</a>.</p>'
        self.assertEqual(cc_external.collect_links([], anns, 7, "https://canvas.example.edu", NOW - dt.timedelta(days=14)), [],
                         "「Audio Studio」不是 Canvas Studio")

    def test_标题写到这周的旧公告也算(self):
        anns = [{"id": 5, "context_code": "course_7", "title": "Information for Weeks 7, 8 and 9", "posted_at": "2026-09-14T00:00:00Z",
                 "message": '<a href="https://docs.google.com/document/d/SCHED/edit?usp=sharing">MECO6941 S2 2026 Production Schedule</a>'}]
        since = NOW - dt.timedelta(days=14)
        self.assertEqual(len(cc_external.collect_links([], anns, 7, None, since, week=9)), 1)
        self.assertEqual(cc_external.collect_links([], anns, 7, None, since, week=10), [])

    def test_快到期作业说明里认得出的平台(self):
        asg = [{"name": "Draft presentation", "due_at": "2026-10-20T06:00:00Z",
                "description": '<a href="https://padlet.com/sydney/class-27-x">schedule</a> <a href="https://apastyle.apa.org/">APA</a>'},
               {"name": "Final", "due_at": "2026-12-20T06:00:00Z", "description": '<a href="https://edstem.org/au/courses/9">Ed</a>'}]
        got = cc_external.collect_links([], [], 7, None, None, assignments=asg, now=NOW)
        self.assertEqual([x["url"] for x in got], ["https://padlet.com/sydney/class-27-x"], "其他网站和两个多月后的作业不算")
        self.assertIn("Draft presentation", got[0]["source"])

    def test_平台首页不算(self):
        got = cc_external.collect_links([], [{"context_code": "course_7", "title": "t", "posted_at": "2026-10-05T00:00:00Z",
                                              "message": '<a href="https://padlet.com?ref=embed">Made with Padlet</a>'}],
                                        7, None, NOW - dt.timedelta(days=14))
        self.assertEqual(got, [])


CLASS_PAGE = "".join(f'<p>Class {n}: <a href="https://padlet.com/sydney/meco6941-2026-class-{n}-with-x-y-tuesday-4-pm-224-ab12cd34ef56gh">here</a></p>'
                     for n in (15, 11, 12, 27, 24, 35))
SECTIONS = ["MECO6941 Podcasting", "(activity) 2026-MECO6941-S2C-ND-CC/LecTut/27"]


class PerClass(unittest.TestCase):
    def links(self):
        acc = cc_external._Links("https://canvas.example.edu")
        acc.from_html(CLASS_PAGE, "课程页面「Class Padlets」", fallback="Class Padlets", known_only=True)
        return acc.out

    def test_分班号(self):
        n = cc_external.section_numbers
        self.assertEqual(n(SECTIONS), {27})
        self.assertEqual(n(["Tutorial 03 (Mon 10am)"]), {3})
        self.assertEqual(n(["T05"]), {5})
        self.assertEqual(n(["Semester 2 2026"]), set())

    def test_每个班各一个的只留学生的班(self):
        kept, notes = cc_external.per_class(self.links(), cc_external.section_numbers(SECTIONS))
        self.assertEqual(len(kept), 1)
        self.assertIn("class-27", kept[0]["url"])
        self.assertIn("class 27", kept[0]["title"], "链接文字只有 here：用网址里的板名")
        self.assertTrue(any("6 个按班分开的 Padlet" in x for x in notes), notes)

    def test_不知道分班就一个都不列(self):
        kept, notes = cc_external.per_class(self.links(), set())
        self.assertEqual(kept, [])
        self.assertTrue(any("还不知道学生在哪个班" in x for x in notes), notes)


class FakeApi:
    """只认 GET 的假 Canvas：路径 → 返回值；没有的给 404。"""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, path):
        path = path.replace("https://canvas.example.edu", "")
        self.calls.append(path)
        if path in self.routes:
            return self.routes[path]
        err = Exception("HTTP 404")
        err.code = 404
        raise err


MODS9 = [
    {"name": "Padlets", "items": [{"type": "Page", "title": "Class Padlets", "url": "https://canvas.example.edu/api/v1/courses/7/pages/class-padlets"},
                                  {"type": "Page", "title": "Acknowledgement of Country", "url": "https://canvas.example.edu/api/v1/courses/7/pages/ack"}]},
    {"name": "Week 4 - Montage", "items": [{"type": "Page", "title": "Week 4 - Links to Adobe Resources",
                                            "url": "https://canvas.example.edu/api/v1/courses/7/pages/w4-links"}]},
    {"name": "Week 9 - Editing Audio", "items": [{"type": "Page", "title": "Week 9 Sound Exercise",
                                                  "url": "https://canvas.example.edu/api/v1/courses/7/pages/w9-ex"}]},
]
ROUTES = {
    "/api/v1/courses/7?include[]=sections": {"id": 7, "sections": [{"name": s} for s in SECTIONS]},
    "/api/v1/courses/7/tabs": [
        {"id": "home", "type": "internal", "label": "Home", "html_url": "/courses/7"},
        {"id": "context_external_tool_11159", "type": "external", "label": "Zoom", "html_url": "/courses/7/external_tools/11159",
         "full_url": "https://canvas.example.edu/courses/7/external_tools/11159"},
        {"id": "context_external_tool_5", "type": "external", "label": "Ed Discussion", "html_url": "/courses/7/external_tools/5",
         "full_url": "https://canvas.example.edu/courses/7/external_tools/5"},
        {"id": "context_external_tool_6", "type": "external", "label": "Unit Outline", "hidden": True, "html_url": "/courses/7/external_tools/6"}],
    "/api/v1/courses/7/pages/class-padlets": {"title": "Class Padlets", "body": CLASS_PAGE},
    "/api/v1/courses/7/pages/w9-ex": {"title": "Week 9 Sound Exercise",
                                      "body": '<a href="https://drive.google.com/drive/folders/EXMEDIA">exercise media</a>'
                                              '<iframe src="https://sydney.padlet.org/embed/uu5yddbj0p3gau1i" title="Resources padlet"></iframe>'
                                              '<a href="https://padlet.com?ref=embed">Made with Padlet</a>'},
}


class Scan(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="stc-scan-")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def scan(self):
        api = FakeApi(ROUTES)
        found = cc_external.scan_canvas(api, "https://canvas.example.edu", 7, MODS9, 9, NOW)
        return api, found

    def test_查分班_导航栏_首页_这周和像入口的页面(self):
        api, found = self.scan()
        self.assertEqual(found["sections"], SECTIONS)
        self.assertEqual(found["errors"], [], "没有首页（404）不算错")
        self.assertIn("/api/v1/courses/7/pages/class-padlets", api.calls)
        self.assertIn("/api/v1/courses/7/pages/w9-ex", api.calls)
        self.assertNotIn("/api/v1/courses/7/pages/w4-links", api.calls, "别的周的页面不读")
        self.assertNotIn("/api/v1/courses/7/pages/ack", api.calls, "名字不像入口的不读")
        self.assertLess(api.calls.index("/api/v1/courses/7/pages/w9-ex"), api.calls.index("/api/v1/courses/7/pages/class-padlets"),
                        "这周的页面先读")
        got = {x["url"]: x for x in found["links"]}
        self.assertEqual(got["https://canvas.example.edu/courses/7/external_tools/11159"]["platform"], "Zoom")
        self.assertEqual(got["https://canvas.example.edu/courses/7/external_tools/5"]["platform"], "Ed")
        self.assertIn("https://drive.google.com/drive/folders/EXMEDIA", got)
        self.assertIn("https://sydney.padlet.org/embed/uu5yddbj0p3gau1i", got, "页面里嵌的 Padlet")
        self.assertNotIn("https://padlet.com?ref=embed", got)
        self.assertEqual([u for u in got if "class-" in u], [u for u in got if "class-27" in u])
        self.assertTrue(found["notes"])

    def test_合并时导航栏的在前_同一个网址只留一条_说明带出来(self):
        _, found = self.scan()
        cc_external.save_found(self.home, "C7", found)
        anns = [{"context_code": "course_7", "title": "Zoom", "posted_at": "2026-10-05T00:00:00Z",
                 "message": 'Zoom tab <a href="https://canvas.example.edu/courses/7/external_tools/11159">here</a>'}]
        raw = cc_external.collect_links([], anns, 7, "https://canvas.example.edu", NOW - dt.timedelta(days=14))
        links, notes = cc_external.all_links(self.home, "C7", raw)
        zoom = [x for x in links if x["url"].endswith("/11159")]
        self.assertEqual(len(zoom), 1)
        self.assertEqual(zoom[0]["source"], "课程导航栏")
        self.assertTrue(any("按班分开" in n for n in notes))

    def test_还差里先去查一遍_查过7天内不再列_Moodle不列(self):
        plan = {"week_no": 9, "study": {"courses": [{"code": "C7", "detect": "module-name", "external": []}]}}

        def keys(cfg):
            ctx = types.SimpleNamespace(home=self.home, state={}, cfg=cfg, clock=types.SimpleNamespace(now_utc=lambda: NOW))
            return {x["key"] for x in cc_gaps.for_ai(ctx, plan, NOW.date())}
        self.assertIn("external-scan:C7", keys({}))
        self.assertNotIn("external-scan:C7", keys({"lms": "moodle"}))
        _, found = self.scan()
        cc_external.save_found(self.home, "C7", found)
        self.assertNotIn("external-scan:C7", keys({}))

    def test_读过的网址换了写法也认得出(self):
        cc_external.record(self.home, "C7", "https://docs.google.com/document/d/D/edit", "ok", NOW)
        recs = cc_external.load_records(self.home, "C7")
        self.assertIsNotNone(cc_external.record_of(recs, "https://docs.google.com/document/d/D/edit?usp=sharing"))


class Background(unittest.TestCase):
    """采集完在后台去 Canvas 查（10-07：开场不该为它等）：只查这 7 天没查过的课，考试站和 Moodle 不查；另一个在查就直接走。"""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="stc-bg-")
        cfg = {"canvas_host": "https://canvas.example.edu",
               "courses": [{"id": 7, "code": "C7", "name": "C7 Podcasting"}, {"id": 8, "code": "C8", "name": "Final Exam for: C7"}]}
        self.ctx = types.SimpleNamespace(home=self.home, cfg=cfg, api=FakeApi(ROUTES), P=lambda *a: os.path.join(self.home, *a))

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_只查该查的_查过就不再查(self):
        self.assertEqual([c["code"] for c in cc_external.scan_due(self.ctx, NOW)], ["C7"], "考试站不查")
        res = cc_external.run_scans(self.ctx, NOW, 9)
        self.assertEqual(list(res), ["C7"])
        self.assertTrue(cc_external.load_found(self.home, "C7").get("links"))
        self.assertEqual(cc_external.scan_due(self.ctx, NOW + dt.timedelta(days=2)), [])
        self.assertEqual([c["code"] for c in cc_external.scan_due(self.ctx, NOW + dt.timedelta(days=8))], ["C7"], "7 天后再查")

    def test_另一个在查就直接走(self):
        self.assertFalse(cc_external.scan_running(self.ctx))
        self.assertFalse(os.path.exists(os.path.join(self.home, "logs", "external-scan.lock")), "看一眼不该生出锁文件")
        lock = cc_external._scan_lock(self.ctx)
        self.assertTrue(lock.acquire(blocking=False))
        try:
            self.assertTrue(cc_external.scan_running(self.ctx))
            self.assertEqual(cc_external.run_scans(self.ctx, NOW, 9), {})
        finally:
            lock.release()

    def test_Moodle不查(self):
        self.ctx.cfg["lms"] = "moodle"
        self.assertEqual(cc_external.scan_due(self.ctx, NOW), [])


def post(pid, sec, idx, subject="", body="", attachment="", link=None, **kw):
    a = {"id": pid, "wall_section_id": sec, "sort_index": idx, "subject": subject, "body": body, "attachment": attachment,
         "attachment_link": link, "published": True, "created_at": f"2026-08-0{pid % 9 + 1}T00:00:00Z"}
    a.update(kw)
    return {"id": str(pid), "type": "wish", "attributes": a}


def board(posts, sections, sort_by="manual_new_posts_last", nxt=None):
    return [("https://padlet.com/api/11/padlet_starting_state?token=t", {"wall": {"wish_arrangement": {"sort_by": sort_by}}}),
            ("https://padlet.com/api/5/wall_sections?wall_id=1", {"data": [{"id": str(s), "attributes": {"id": s, "title": t, "sort_index": i}}
                                                                           for s, t, i in sections]}),
            ("https://padlet.com/api/10/wishes?wall_hashid=b&page_start=", {"data": posts, "meta": {"next": nxt}})]


class Padlet(unittest.TestCase):
    SECS = [(1, "Class 9: Story Structure", 2048), (2, "How to use this padlet", 0)]

    def test_按栏列全部帖子_栏从左到右_手动排的大的在上面(self):
        txt = cc_external.padlet_text(board([
            post(11, 1, -100, "READ: Story Structure", '<div>Chapter PDF - <a href="https://drive.google.com/file/d/F/view">CLICK HERE</a><br>'
                                                       '<ol><li><strong>Begin</strong> by asking why.</li></ol></div>'),
            post(12, 1, -10, "LISTEN: Kulas", attachment="https://omny.fm/x", link={"title": "Kulas on structure", "description": "A masterclass"}),
            post(13, 1, -5, "Read: S-Town paper",
                 attachment="https://u1.padletusercontent.com/uploads/a/b/S_Town.pdf?expiry_token=zz", link={"content_category": "document"}),
            post(14, 1, -1, "", attachment="https://u1.padletusercontent.com/uploads/a/b/pic.png?expiry_token=zz"),
            post(15, 1, -2, "hidden", is_content_hidden=True),
            post(21, 2, 5, "Please bookmark this Padlet"),
        ], self.SECS))
        self.assertIn("2 栏、5 条帖子", txt)
        self.assertLess(txt.index("## How to use this padlet"), txt.index("## Class 9: Story Structure"))
        order = [txt.index(s) for s in ("（图片：pic.png）", "Read: S-Town paper", "LISTEN: Kulas", "READ: Story Structure")]
        self.assertEqual(order, sorted(order), "手动排序：sort_index 大的在上面（对过网页）")
        self.assertIn("CLICK HERE（https://drive.google.com/file/d/F/view）", txt)
        self.assertIn("- Begin by asking why.", txt)
        self.assertIn("链接：Kulas on structure https://omny.fm/x", txt)
        self.assertIn("（A masterclass）", txt)
        self.assertIn("附件：S_Town.pdf https://u1.padletusercontent.com/", txt)
        self.assertNotIn("hidden", txt)
        self.assertIn("· Please bookmark this Padlet（2026-08-04 贴）", txt, "带发帖日期：分得清哪些是这周新贴的")

    def test_按时间排的板子_没帖子返回None(self):
        txt = cc_external.padlet_text(board([post(1, 2, 0, "old one", created_at="2026-08-01T00:00:00Z", published_at="2026-08-01T00:00:00Z"),
                                             post(2, 2, 0, "new one", created_at="2026-09-01T00:00:00Z", published_at="2026-09-01T00:00:00Z")],
                                            self.SECS, sort_by="date_newest_first"))
        self.assertLess(txt.index("new one"), txt.index("old one"))
        self.assertIsNone(cc_external.padlet_text(board([], self.SECS)))


if __name__ == "__main__":
    unittest.main()
