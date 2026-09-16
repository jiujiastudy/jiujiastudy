r"""S04 显示名不是路径 · S05 课件文字默认不交给 AI。

S04：Canvas 的 display_name 以前直接当路径用。`..\..\evil.txt` 会写到「课件」外面，
`C:\Windows\Temp\x.txt` 真的落在那里，`Week 1: Intro.pdf` 在 NTFS 上留下 0 字节的「Week 1」、
正文藏进副数据流，带 `?` `"` 的名字写不出来又被当成失败丢掉，两个同名课件互相覆盖，长名超过 MAX_PATH。
现在一律走 cc_downloads.safe_dest()：清理名字、留住扩展名、重名加「 (2)」、落点必须在这门课的「课件」里。
canvas_api 的 `api download` 也走同一条。

S05：课件照常下到本机，课件文字默认不提取给 AI；按课打开：config course <CODE> --materials-ai on。
HTTP 层在 S04 这几个用例里是替身，S05 走 mockcanvas，两处都不出门。
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
if TOOLS not in sys.path:
    sys.path.append(TOOLS)  # 直接调 tools/ 里的下载函数；HTTP 层用替身
import canvas_api  # noqa: E402
import cc_downloads  # noqa: E402

CODE = "ABCD1234"
HAN = r"[一-鿿]"
# (Canvas 给的显示名, 落盘后必须留住的扩展名)
NAMES = [
    (r"..\..\..\evil.txt", ".txt"),
    ("/etc/passwd", ""),
    (r"C:\Windows\Temp\abs.txt", ".txt"),
    ("Week 1: Intro.pdf", ".pdf"),
    ('a?b".pdf', ".pdf"),
    ("CON.pdf", ".pdf"),
    ("name.", ""),
    ("x" * 296 + ".pdf", ".pdf"),
    ("Lecture slides.pdf", ".pdf"),
    ("Lecture slides.pdf", ".pdf"),
]
DOC_BODY = "Unit guide for {code}. Week 5 reading list, assessment notes and the marking rubric."


def tmpdir(prefix):
    return os.path.realpath(tempfile.mkdtemp(prefix=prefix, dir=os.environ.get("STC_TEST_TMP") or None))


def files_under(root):
    out = []
    for dirpath, _, names in os.walk(root):
        out += [os.path.join(dirpath, n) for n in names]
    return out


class StubApi:
    """ctx.api 的替身：file_meta 和 fetch 都不出门。"""

    def __init__(self):
        self.files = {}

    def add(self, name, body):
        fid = str(900 + len(self.files) + 1)
        self.files[fid] = {"id": int(fid), "display_name": name, "size": len(body),
                           "url": f"stub://files/{fid}", "_body": body}
        return int(fid)

    def file_meta(self, file_id):
        return {k: v for k, v in self.files[str(file_id)].items() if k != "_body"}

    def fetch(self, url, accept="application/json"):
        return {}, self.files[url.rsplit("/", 1)[1]]["_body"]


class FakeCtx:
    """download_new 要的最小上下文：机器档案、资料夹、config、api。"""

    def __init__(self, base, api, courses):
        self.home = os.path.join(base, ".coach")
        self.root = os.path.join(base, "救驾")
        self.cfg = {"courses": courses, "materials": {"max_mb": 50}}
        self.api = api

    def P(self, *a):
        return os.path.join(self.home, *a)

    def materials_dir(self, code):
        return os.path.join(self.root, code, "课件")


class DisplayNameIsNotAPathTest(unittest.TestCase):
    """S04：这 10 个显示名全部下下来，全部落在这门课的「课件」里，一个都不能丢。"""

    def setUp(self):
        self.base = tmpdir("stc-s04-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.ctx = FakeCtx(self.base, StubApi(), [{"id": 1, "code": CODE}])
        self.mats = os.path.realpath(self.ctx.materials_dir(CODE))
        self.errors, self.saved = [], []
        for i, (name, _) in enumerate(NAMES):
            body = f"file {i} ".encode("utf-8") + b"ABCDEFGH" * 8
            fid = self.ctx.api.add(name, body)
            r = cc_downloads.download_new(self.ctx, {"content_id": fid}, CODE, self.errors)
            self.saved.append((name, body, r))

    def test_nothing_is_silently_dropped(self):
        self.assertEqual([], self.errors)
        for name, _, r in self.saved:
            with self.subTest(name=name[:40]):
                self.assertIsNotNone(r, "下载返回 None = 这个名字被丢掉了")
                self.assertTrue(r.get("saved"), r)
        self.assertEqual(len(NAMES), len(set(r["saved"] for _, _, r in self.saved)))

    def test_every_file_stays_inside_the_course_materials_folder(self):
        for name, _, r in self.saved:
            with self.subTest(name=name[:40]):
                p = os.path.realpath(r["saved"])
                self.assertEqual(self.mats, os.path.dirname(p), "落到了「课件」外面")
                self.assertTrue(os.path.isfile(p))
        # 整个临时目录里除了「课件」下的这 10 个文件，没有别的东西
        self.assertEqual(sorted(os.path.realpath(r["saved"]) for _, _, r in self.saved),
                         sorted(os.path.realpath(p) for p in files_under(self.base)))

    def test_the_whole_file_lands_on_disk_not_in_an_alternate_stream(self):
        for name, body, r in self.saved:
            with self.subTest(name=name[:40]):
                base = os.path.basename(r["saved"])
                self.assertNotIn(":", base, "冒号会在 NTFS 上变成副数据流")
                self.assertEqual(len(body), os.path.getsize(r["saved"]), "盘上的字节数不对（内容进了副数据流？）")
                with open(r["saved"], "rb") as f:
                    self.assertEqual(body, f.read())
        names = os.listdir(self.mats)
        self.assertNotIn("Week 1", names, "「Week 1: Intro.pdf」不能只留下一个「Week 1」")
        self.assertEqual(len(NAMES), len(names))

    def test_names_windows_cannot_take_are_repaired_not_refused(self):
        for (name, ext), (_, _, r) in zip(NAMES, self.saved):
            with self.subTest(name=name[:40]):
                base = os.path.basename(r["saved"])
                self.assertEqual(ext, os.path.splitext(base)[1].lower(), "扩展名没留住")
                self.assertFalse(base.endswith((".", " ")), base)
                self.assertNotIn(os.path.splitext(base)[0].upper(), cc_downloads.RESERVED_NAMES, "设备名")
                self.assertLessEqual(len(base), cc_downloads.NAME_LIMIT + 4, "长名没截短（MAX_PATH）")
                self.assertLess(len(r["saved"]), 260, "整条路径超过了 MAX_PATH")
        self.assertEqual("Week 1 Intro.pdf", os.path.basename(self.saved[3][2]["saved"]))
        self.assertEqual("a b.pdf", os.path.basename(self.saved[4][2]["saved"]))

    def test_two_files_with_one_name_do_not_overwrite_each_other(self):
        first, second = self.saved[-2][2]["saved"], self.saved[-1][2]["saved"]
        self.assertEqual("Lecture slides.pdf", os.path.basename(first))
        self.assertEqual("Lecture slides (2).pdf", os.path.basename(second))
        with open(first, "rb") as f:
            self.assertEqual(self.saved[-2][1], f.read())
        with open(second, "rb") as f:
            self.assertEqual(self.saved[-1][1], f.read())

    def test_text_extraction_is_off_by_default(self):
        self.assertEqual([], files_under(self.ctx.P("text")))


class CanvasApiDownloadTest(unittest.TestCase):
    """S04：`api download <id> <目录>` 是另一条下载路径，同样不许名字当路径。"""

    def test_display_name_cannot_escape_the_destination(self):
        base = tmpdir("stc-s04-api-")
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        dest_dir = os.path.join(base, "课件")
        api = canvas_api.Canvas("https://canvas.example.invalid", None)
        api.file_meta = lambda file_id: {"display_name": r"..\..\evil: slides.pdf", "size": 3,
                                         "url": "https://canvas.example.invalid/files/7/download"}
        api.fetch = lambda url, accept="application/json": ({}, b"abc")  # 不出门
        r = api.download(7, dest_dir)
        self.assertEqual(os.path.realpath(dest_dir), os.path.dirname(os.path.realpath(r["saved"])))
        self.assertEqual("evil slides.pdf", os.path.basename(r["saved"]))
        self.assertEqual([os.path.realpath(r["saved"])], [os.path.realpath(p) for p in files_under(base)])


class MaterialsAiUnitTest(unittest.TestCase):
    """S05：提取开关按课走；第一次排课件时的那一句话。"""

    def setUp(self):
        self.base = tmpdir("stc-s05u-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.ctx = FakeCtx(self.base, StubApi(),
                           [{"id": 1, "code": "AAAA1111", "materials_ai": True}, {"id": 2, "code": "BBBB2222"}])

    def _download(self, code):
        body = DOC_BODY.format(code=code).encode("utf-8")
        fid = self.ctx.api.add(f"{code} Unit Guide.doc", body)
        return cc_downloads.download_new(self.ctx, {"content_id": fid}, code, [])

    def test_only_the_course_that_was_turned_on_gets_a_text_extract(self):
        on, off = self._download("AAAA1111"), self._download("BBBB2222")
        self.assertTrue(os.path.isfile(on["saved"]) and os.path.isfile(off["saved"]), "两门课的原件都要下下来")
        texts = files_under(self.ctx.P("text"))
        self.assertEqual([os.path.realpath(self.ctx.P("text", "AAAA1111", "AAAA1111 Unit Guide.txt"))],
                         [os.path.realpath(p) for p in texts])
        with open(texts[0], encoding="utf-8") as f:
            self.assertIn("Unit guide for AAAA1111", f.read())

    def _note(self, code, items):
        d = os.path.join(self.ctx.P("raw", "daily", "2026-03-25"))
        os.makedirs(d, exist_ok=True)
        cid = next(c["id"] for c in self.ctx.cfg["courses"] if c["code"] == code)
        with open(os.path.join(d, f"modules_{cid}.json"), "w", encoding="utf-8") as f:
            json.dump([{"id": 1, "name": "Week 1", "items": items}], f, ensure_ascii=False)
        return cc_downloads._materials_ai_note(self.ctx, [{"course": code}])

    def test_the_note_says_how_to_turn_it_on_and_names_the_course_ai_page(self):
        note = self._note("BBBB2222", [{"id": 1, "type": "Page", "title": "Academic integrity and AI policy"},
                                       {"id": 2, "type": "File", "title": "Week 1 slides.pdf"}])
        self.assertEqual(1, len(note.splitlines()))
        self.assertIn("config course BBBB2222 --materials-ai on", note)
        self.assertIn("Academic integrity and AI policy", note)
        # 课程自己没有这一页就不多说
        plain = self._note("BBBB2222", [{"id": 1, "type": "Page", "title": "Week 1 tutorial questions"}])
        self.assertIn("config course BBBB2222 --materials-ai on", plain)
        self.assertNotIn("模块里有", plain)
        # 这门课已经开了 AI，就没什么可提醒的
        self.assertIsNone(cc_downloads._materials_ai_note(self.ctx, [{"course": "AAAA1111"}]))


def _scenario_two_courses():
    """au_semester：给两门课的第 5 周各加一个 .doc（fixture 里的 pdf/pptx 是假的，提不出文字）。"""
    sc = mockcanvas.Scenario("au_semester")
    for cid, code, module_prefix in ((1101, "ACCT1101", "Week 5"), (1103, "DSGN3402", "W5 Studio")):
        fid = cid * 1000 + 901
        body = DOC_BODY.format(code=code)
        name = f"{code} Unit Guide.doc"
        sc.course[cid]["files"].append({
            "id": fid, "display_name": name, "filename": name.replace(" ", "+"), "content-type": "application/msword",
            "size": len(body), "created_at": "2026-03-20T00:00:00Z", "updated_at": "2026-03-20T00:00:00Z",
            "unlock_at": None, "locked": False, "hidden": False, "locked_for_user": False, "lock_explanation": None,
            "url": f"{mockcanvas.BASE_MARK}/files/{fid}/download?download_frd=1", "_body": body})
        m = next(x for x in sc.course[cid]["modules"] if x["name"].startswith(module_prefix))
        m["items"].append({
            "id": fid, "module_id": m["id"], "position": len(m["items"]) + 1, "title": name, "indent": 0,
            "type": "File", "html_url": f"{mockcanvas.BASE_MARK}/courses/{cid}/modules/items/{fid}",
            "content_id": fid, "url": f"{mockcanvas.BASE_MARK}/api/v1/courses/{cid}/files/{fid}",
            "content_details": {"locked_for_user": False, "display_name": name}})
    return sc


class AutoDownloadSwitchTest(unittest.TestCase):
    """文档一直把 config set materials.auto_download false 当开关卖，代码以前没读它。"""

    def setUp(self):
        self.base = tmpdir("stc-auto-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.ctx = FakeCtx(self.base, StubApi(), [{"id": 1, "code": "AAAA1111"}])
        os.makedirs(self.ctx.P("raw"), exist_ok=True)
        self.items = [{"id": 11, "course": "AAAA1111", "title": "Week 1.pdf", "content_id": 1, "type": "File"}]

    def test_关掉之后一个都不排(self):
        self.ctx.cfg["materials"] = {"max_mb": 50, "auto_download": False}
        self.assertEqual((0, 0), cc_downloads.queue_downloads(self.ctx, self.items))

    def test_没关就照常排(self):
        self.assertEqual((1, 1), cc_downloads.queue_downloads(self.ctx, self.items))


class MaterialsAiCommandTest(unittest.TestCase):
    """S05：真的跑一遍 collect --download。默认只下原件；开了才有文字稿，且只开那一门。"""

    CODES = ("ACCT1101", "DSGN3402")

    @classmethod
    def setUpClass(cls):
        cls.sc = _scenario_two_courses()
        cls.mock = mockcanvas.MockCanvas(cls.sc).start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def home(self, label):
        h = harness.FakeHome(label)
        self.addCleanup(h.cleanup)
        h.seed(self.sc, self.mock.base_url)
        return h

    def run_coach(self, home, *args):
        return harness.run_coach(home, list(args) + ["--date", self.sc.meta["date"]], TOOLS,
                                 now=self.sc.meta["now"], ports=(self.mock.port,))

    def download_all(self, home):
        """后台 worker 走的就是这条（cap = materials.per_run），一次把队列下完，省得分批。"""
        r = self.run_coach(home, "collect", "--download", "--download-worker")
        self.assertEqual(0, r.code, r.stderr)
        return r

    def materials(self, home):
        return sorted(os.path.basename(p) for p in files_under(home.root)
                      if os.path.basename(os.path.dirname(p)) == "课件")

    def texts(self, home):
        return sorted(os.path.relpath(p, os.path.join(home.archive, "text")).replace("\\", "/")
                      for p in files_under(os.path.join(home.archive, "text")))

    def test_off_by_default_still_downloads_but_writes_nothing_into_text(self):
        home = self.home("s05-off")
        r = self.run_coach(home, "collect", "--touch")
        self.assertEqual(0, r.code, r.stderr)
        self.assertIn("--materials-ai on", r.stderr, "第一次排课件要说一句")
        self.assertEqual(1, len([x for x in r.stderr.splitlines() if "--materials-ai on" in x]))
        self.download_all(home)
        got = self.materials(home)
        for code in self.CODES:
            self.assertIn(f"{code} Unit Guide.doc", got)
        self.assertEqual([], self.texts(home), "默认不提取：text/ 一个字都不该写")
        # 第二次采集不再重复那一句
        r = self.run_coach(home, "collect", "--touch", "--force")
        self.assertNotIn("--materials-ai on", r.stderr)

    def test_turning_it_on_extracts_for_that_course_only(self):
        home = self.home("s05-on")
        r = self.run_coach(home, "config", "course", "acct1101", "--materials-ai", "on")  # 大小写不计
        self.assertEqual(0, r.code, r.stderr)
        self.assertIn("ACCT1101", r.stdout)
        self.assertRegex(r.stdout, HAN)
        r = self.run_coach(home, "config", "course", "ACCT1101", "--json")
        self.assertIs(True, r.json()["materials_ai"])
        self.assertEqual(0, self.run_coach(home, "collect", "--touch").code)
        self.download_all(home)
        got = self.materials(home)
        for code in self.CODES:
            self.assertIn(f"{code} Unit Guide.doc", got, "开关只管文字，原件照下")
        self.assertEqual(["ACCT1101/ACCT1101 Unit Guide.txt"], self.texts(home))
        with open(os.path.join(home.archive, "text", "ACCT1101", "ACCT1101 Unit Guide.txt"), encoding="utf-8") as f:
            self.assertIn("Unit guide for ACCT1101", f.read())
        r = self.run_coach(home, "config", "course", "ACCT1101", "--materials-ai", "off", "--json")
        self.assertIs(False, r.json()["materials_ai"])

    def test_a_bad_value_or_an_unknown_course_is_one_chinese_line_and_exit_2(self):
        home = self.home("s05-bad")
        for args in (("config", "course", "ACCT1101", "--materials-ai", "bogus"),
                     ("config", "course", "NOPE9999", "--materials-ai", "on")):
            with self.subTest(args=args):
                r = self.run_coach(home, *args)
                self.assertEqual(2, r.code, r.stderr)
                self.assertEqual("", r.stdout)
                lines = [x for x in r.stderr.splitlines() if x.strip()]
                self.assertEqual(1, len(lines), r.stderr)
                self.assertRegex(lines[0], HAN)
                self.assertNotIn("Traceback", r.stderr)
                self.assertNotIn("usage:", r.stderr)


if __name__ == "__main__":
    unittest.main()
