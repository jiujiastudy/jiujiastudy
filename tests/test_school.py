"""第一次设置：按校名认学校、「填学校 + 粘 token」小窗口、缺 token 时一条消息说完。

红线（S09 以来一直是这条）：token 只发给查表查准的，或用户自己给的那一个地址，而且发之前先不带 token
探一下是不是 Canvas。认不准就问，不猜：「西悉尼大学」不是悉尼大学，「纽卡斯尔大学」澳洲英国各有一所。
不读浏览器记录，不改任何宿主的权限设置。
"""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")
sys.path.insert(0, TOOLS)
import canvas_api  # noqa: E402
import cc_host  # noqa: E402
import cc_token  # noqa: E402
import token_window  # noqa: E402

SYD = "https://canvas.sydney.edu.au"
SHARED_ON_PURPOSE = {"纽卡斯尔大学", "纽卡斯尔", "纽卡", "newcastle", "uva"}


class SchoolTable(unittest.TestCase):
    def test_常见说法都认得(self):
        for said in ("悉尼大学", "悉大", "USYD", "usyd", "University of Sydney", "The University of Sydney",
                     "  university  of sydney ", "我是悉尼大学的", "ＵＳＹＤ"):
            with self.subTest(said=said):
                self.assertEqual({"host": SYD, "name": "悉尼大学（University of Sydney）"}, cc_host.resolve_school(said))
        self.assertEqual("https://canvas.uts.edu.au", cc_host.resolve_school("UTS")["host"])
        self.assertEqual("https://canvas.uts.edu.au", cc_host.resolve_school("悉尼科技大学")["host"])

    def test_名字里带着别的学校也不认错(self):
        for said in ("西悉尼大学", "Western Sydney University", "伊利诺伊大学芝加哥分校", "Oxford Brookes", "悉尼", "大学"):
            with self.subTest(said=said):
                self.assertEqual({}, cc_host.resolve_school(said))

    def test_对得上两所就问(self):
        got = cc_host.resolve_school("纽卡斯尔大学")
        self.assertEqual({"https://canvas.newcastle.edu.au", "https://ncl.instructure.com"}, {h for h, _ in got["ambiguous"]})
        self.assertIn("澳洲", "".join(n for _, n in got["ambiguous"]))
        self.assertEqual(2, len(cc_host.resolve_school("UVA")["ambiguous"]))
        self.assertEqual("https://ncl.instructure.com", cc_host.resolve_school("Newcastle University")["host"])

    def test_网址直接用(self):
        self.assertEqual(SYD, cc_host.resolve_school("https://canvas.sydney.edu.au/courses/123")["host"])
        self.assertEqual("https://canvas.xyz.edu", cc_host.resolve_school("canvas.xyz.edu")["host"])

    def test_表本身干净(self):
        hosts = [h for h, _, _ in cc_host.SCHOOLS]
        self.assertEqual(len(hosts), len(set(hosts)), "同一个地址写了两遍")
        owners = {}
        for host, name, aliases in cc_host.SCHOOLS:
            self.assertTrue(host.startswith("https://") and host == cc_host.normalize_host(host), host)
            self.assertTrue(name and aliases, host)
            for a in aliases:
                key = cc_host._norm(a)
                self.assertTrue(key, (host, a))
                owners.setdefault(key, set()).add(host)
        shared = {k for k, v in owners.items() if len(v) > 1}
        self.assertEqual({cc_host._norm(a) for a in SHARED_ON_PURPOSE}, shared, "别名撞车了：要么删掉，要么确认是故意让用户说全名")


class TokenWindowCheck(unittest.TestCase):
    """窗口点保存时做的事（不开界面）：认学校 → 不带 token 探 → 只对这一个地址验 token → 存。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "archive")
        self._saved = (cc_token.TOKEN_FILE, cc_host.is_canvas, canvas_api.Canvas)
        cc_token.TOKEN_FILE = os.path.join(self.tmp.name, "cfg", "token")
        self.calls = []

    def tearDown(self):
        cc_token.TOKEN_FILE, cc_host.is_canvas, canvas_api.Canvas = self._saved
        self.tmp.cleanup()

    def fake_canvas(self, answer):
        calls = self.calls

        class FakeCanvas:
            def __init__(self, host, tok, **kw):
                calls.append(("token-client", host, tok))

            def get(self, path):
                if isinstance(answer, Exception):
                    raise answer
                return answer

        return FakeCanvas

    def probe(self, result):
        def is_canvas(host):
            self.calls.append(("probe", host))
            return result
        return is_canvas

    def saved(self):
        tok = site = None
        if os.path.exists(cc_token.TOKEN_FILE):
            with io.open(cc_token.TOKEN_FILE, encoding="utf-8") as f:
                tok = f.read().strip()
        site_path = os.path.join(self.home, "site.json")
        if os.path.exists(site_path):
            with io.open(site_path, encoding="utf-8") as f:
                site = json.load(f)
        return tok, site

    GOOD = "7071~" + "a" * 64

    def test_连上了就存下_token_只发给这一个地址(self):
        cc_host.is_canvas = self.probe(True)
        canvas_api.Canvas = self.fake_canvas({"id": 1, "name": "Test Student"})
        ok, msg = token_window.check(self.home, "悉尼大学", "  " + self.GOOD + "\n")
        self.assertTrue(ok, msg)
        self.assertIn("连上了", msg)
        self.assertIn("Test Student", msg)
        self.assertEqual([("probe", SYD), ("token-client", SYD, self.GOOD)], self.calls, "先探再发 token，且只发这一个地址")
        self.assertEqual((self.GOOD, {"host": SYD, "school": "悉尼大学"}), self.saved())

    def test_写错了当场说_什么都不存也不发(self):
        cc_host.is_canvas = self.probe(True)
        canvas_api.Canvas = self.fake_canvas({"id": 1})
        cases = {("", self.GOOD): "学校", ("悉尼大学", ""): "token", ("悉尼大学", "abc def"): "不像 token",
                 ("纽卡斯尔大学", self.GOOD): "不止一所", ("西悉尼大学", self.GOOD): "网址"}
        for (school, tok), hint in cases.items():
            with self.subTest(school=school, tok=tok):
                ok, msg = token_window.check(self.home, school, tok)
                self.assertFalse(ok)
                self.assertIn(hint, msg)
        self.assertEqual([], self.calls, "没认准学校、token 不像样之前，一个请求都不该发")
        self.assertEqual((None, None), self.saved())

    def test_不是_Canvas_就不发_token(self):
        cc_host.is_canvas = self.probe(False)
        canvas_api.Canvas = self.fake_canvas({"id": 1})
        ok, msg = token_window.check(self.home, "https://example.edu", self.GOOD)
        self.assertFalse(ok)
        self.assertEqual([("probe", "https://example.edu")], self.calls)
        self.assertEqual((None, None), self.saved())

    def test_token_不对就不存(self):
        cc_host.is_canvas = self.probe(True)
        canvas_api.Canvas = self.fake_canvas(urllib.error.HTTPError(SYD, 401, "Unauthorized", {}, None))
        ok, msg = token_window.check(self.home, "USYD", self.GOOD)
        self.assertFalse(ok)
        self.assertIn("没复制全", msg)
        self.assertEqual((None, None), self.saved())

    def test_断网先存下_回对话再试(self):
        cc_host.is_canvas = self.probe(True)
        canvas_api.Canvas = self.fake_canvas(urllib.error.URLError("offline"))
        ok, msg = token_window.check(self.home, "USYD", self.GOOD)
        self.assertTrue(ok)
        self.assertIn("先存下了", msg)
        self.assertEqual(self.GOOD, self.saved()[0])

    def test_小窗口存的_token_排在注册表和钥匙串前面(self):
        old = os.environ.pop("CANVAS_TOKEN", None)
        try:
            cc_token.save_token(self.GOOD)
            self.assertEqual(self.GOOD, cc_token.token())
        finally:
            if old is not None:
                os.environ["CANVAS_TOKEN"] = old


class DoctorFirstRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = mockcanvas.MockCanvas("au_semester").start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def setUp(self):
        self.home = harness.FakeHome("school")

    def tearDown(self):
        self.home.cleanup()

    def doctor(self, *extra, **env):
        args = ["doctor", "--tz", "Australia/Sydney", "--agent", "claude", "--all-courses", "--json", *extra]
        r = harness.run_coach(self.home, args, TOOLS, ports=(self.mock.port,), extra_env=env)
        try:
            return r, r.json()
        except ValueError:
            self.fail(f"doctor --json printed no JSON (exit {r.code}):\n{r.stdout[-800:]}\n{r.stderr[-800:]}")

    @staticmethod
    def todo(res):
        """「你需要做的事」里和学校、token 有关的那几条（「skill 位置」、缺可选依赖这些和环境有关的提醒不算）。"""
        return [a for a in res["must_fix"] if "token" in a or "学校" in a]

    def test_缺_token_时一条消息问完学校和_token(self):
        r, res = self.doctor("--token-window", CANVAS_TOKEN=None)  # 测试里不弹窗（NO_DIALOG），走「弹不出」那段话
        self.assertEqual(2, r.code, res["text"])
        self.assertEqual(1, len(self.todo(res)), res["must_fix"])
        msg = self.todo(res)[0]
        for word in ("学校", "Approved Integrations", "别发到聊天里", "doctor --school"):
            self.assertIn(word, msg)

    def test_没让弹窗时_下一步就是弹窗(self):
        r, res = self.doctor(CANVAS_TOKEN=None)
        self.assertEqual(["跑 doctor --token-window：弹出填学校和 token 的小窗口"], self.todo(res))

    def test_校名给的是网址_照样建档(self):
        r, res = self.doctor("--school", self.mock.base_url)
        self.assertEqual(0, r.code, res["text"])
        self.assertTrue(os.path.isfile(os.path.join(self.home.archive, "config.json")))

    def test_认不准就问_不建档(self):
        for school, hint in (("西悉尼大学", "网址"), ("纽卡斯尔大学", "哪一所")):
            with self.subTest(school=school):
                r, res = self.doctor("--school", school)
                self.assertNotEqual(0, r.code)
                self.assertTrue(any(hint in a for a in res["must_fix"]), res["must_fix"])
                self.assertFalse(os.path.exists(os.path.join(self.home.archive, "config.json")))

    def test_token_只给一次_以后每次都读存下的(self):
        """小窗口存进 ~/.config/jiujiastudy/token 之后：环境变量里没有 token，建档、采集、再体检都不再要。"""
        path = os.path.join(self.home.user, ".config", "jiujiastudy", "token")
        os.makedirs(os.path.dirname(path))
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(harness.TOKEN + "\n")
        r, res = self.doctor("--host", self.mock.base_url, CANVAS_TOKEN=None)
        self.assertEqual(0, r.code, res["text"])
        for args in (["collect", "--touch", "--json"], ["status", "--json"]):
            with self.subTest(args=args):
                r2 = harness.run_coach(self.home, args, TOOLS, ports=(self.mock.port,), extra_env={"CANVAS_TOKEN": None})
                self.assertEqual(0, r2.code, r2.stderr[-600:] + r2.stdout[-600:])
        r, res = self.doctor(CANVAS_TOKEN=None)  # 第二次体检：不带 --host、不带 token，照样连得上
        self.assertEqual(0, r.code, res["text"])
        self.assertIn(("OK", "token"), {(c["level"], c["name"]) for c in res["checks"]})

    def test_不改宿主权限_不读浏览器记录(self):
        r, res = self.doctor("--host", self.mock.base_url)
        self.assertEqual(0, r.code, res["text"])
        self.assertFalse(os.path.exists(os.path.join(self.home.user, ".claude", "settings.json")))
        self.assertNotIn("浏览器", res["text"])
        self.assertNotIn("permissions", res["text"])


if __name__ == "__main__":
    unittest.main()
