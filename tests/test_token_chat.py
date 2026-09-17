"""token：用户直接发到对话里，AI 用 `token set` 从标准输入存好，只要给一次。

发起人 09-17：不要让用户去弄环境变量、终端或别的窗口，token 发在对话里，由工具保管好。
红线：token 不打印（输出和 JSON 里都没有）、不进命令参数；知道学校地址就先只对那一个地址验，
登不上就不存；存下的文件只有本人能读；以后每条命令直接读它，不用再给。
"""
import io
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")
sys.path.insert(0, TOOLS)
import cc_token  # noqa: E402

REAL_LOOKING = "7071~" + "Ab3" * 22


class PickToken(unittest.TestCase):
    def test_整段只有_token_就原样用(self):
        self.assertEqual(REAL_LOOKING, cc_token.pick_token("  " + REAL_LOOKING + "\n"))
        self.assertEqual(REAL_LOOKING, cc_token.pick_token("`" + REAL_LOOKING + "`"))

    def test_夹着别的字就挑出那一串(self):
        self.assertEqual(REAL_LOOKING, cc_token.pick_token(f"这是我的 token：{REAL_LOOKING} 帮我存一下"))

    def test_认不出就不猜(self):
        self.assertIsNone(cc_token.pick_token(""))
        self.assertIsNone(cc_token.pick_token("帮我存一下 token"))
        self.assertIsNone(cc_token.pick_token(f"{REAL_LOOKING} 还有 {REAL_LOOKING[:-1]}X"))

    def test_本机文件排在老地方前面(self):
        with tempfile.TemporaryDirectory() as d:
            saved, old_env = cc_token.TOKEN_FILE, os.environ.get("CANVAS_TOKEN")
            cc_token.TOKEN_FILE = os.path.join(d, "cfg", "token")
            os.environ["CANVAS_TOKEN"] = "old-token-from-env"
            try:
                cc_token.save_token(REAL_LOOKING)
                self.assertEqual(REAL_LOOKING, cc_token.token(), "新发来的 token 要换掉以前存在环境变量里的旧的")
                self.assertTrue(cc_token.forget_token())
                self.assertEqual("old-token-from-env", cc_token.token())
            finally:
                cc_token.TOKEN_FILE = saved
                if old_env is None:
                    os.environ.pop("CANVAS_TOKEN", None)
                else:
                    os.environ["CANVAS_TOKEN"] = old_env


class TokenSetCommand(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = mockcanvas.MockCanvas("au_semester").start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def setUp(self):
        self.home = harness.FakeHome("token")
        self.path = os.path.join(self.home.user, ".config", "jiujiastudy", "token")

    def tearDown(self):
        self.home.cleanup()

    def run_it(self, *args, stdin_text=None, **env):
        env.setdefault("CANVAS_TOKEN", None)  # 真实情况：用户电脑上没有环境变量，token 只从对话里来
        return harness.run_coach(self.home, list(args), TOOLS, ports=(self.mock.port,), extra_env=env, stdin_text=stdin_text)

    def saved(self):
        if not os.path.exists(self.path):
            return None
        with io.open(self.path, encoding="utf-8") as f:
            return f.read().strip()

    def test_发一次_以后每条命令都不用再给(self):
        r = self.run_it("token", "set", stdin_text=harness.TOKEN + "\n")  # 还没建档：不知道学校，先存下
        self.assertEqual(0, r.code, r.stderr)
        self.assertEqual(harness.TOKEN, self.saved())
        if os.name != "nt":
            self.assertEqual(0o600, stat.S_IMODE(os.stat(self.path).st_mode))
        r = self.run_it("doctor", "--no-detect", "--host", self.mock.base_url, "--tz", "Australia/Sydney",
                        "--agent", "other", "--all-courses", "--json")
        self.assertEqual(0, r.code, r.stdout[-800:])
        for args in (["collect", "--touch", "--json"], ["status", "--json"], ["doctor", "--json", "--agent", "other"]):
            with self.subTest(args=args):
                r = self.run_it(*args)
                self.assertEqual(0, r.code, r.stderr[-600:] + r.stdout[-600:])

    def test_token_不出现在任何输出里(self):
        secret = "4242~" + "Zz9" * 22
        r = self.run_it("token", "set", "--json", stdin_text=f"我的 token 是 {secret} 谢谢")
        self.assertEqual(0, r.code, r.stderr)
        self.assertEqual(secret, self.saved())
        self.assertNotIn(secret, r.stdout + r.stderr)
        self.assertNotIn(secret[5:20], r.stdout + r.stderr)
        self.assertIs(True, r.json()["saved"])

    def test_知道学校就先验_登不上不存(self):
        self.assertEqual(0, self.run_it("token", "set", stdin_text=harness.TOKEN).code)
        self.assertEqual(0, self.run_it("doctor", "--no-detect", "--host", self.mock.base_url, "--tz", "Australia/Sydney",
                                        "--agent", "other", "--all-courses", "--json").code)
        wrong = "1111~" + "wrong" * 5
        r = self.run_it("token", "set", stdin_text=wrong)
        self.assertEqual(2, r.code)
        self.assertIn("没复制全", r.stderr)
        self.assertNotIn(wrong, r.stdout + r.stderr)
        self.assertEqual(harness.TOKEN, self.saved(), "登不上的 token 不许把能用的那个换掉")
        r = self.run_it("token", "set", "--json", stdin_text=harness.TOKEN)
        self.assertEqual(0, r.code, r.stdout)
        self.assertIs(True, r.json()["verified"])

    def test_没传进来就说清怎么传(self):
        r = self.run_it("token", "set")
        self.assertEqual(2, r.code)
        self.assertIn("标准输入", r.stderr)
        self.assertIsNone(self.saved())

    def test_缺_token_时_doctor_让用户发到对话里(self):
        r = self.run_it("doctor", "--no-detect", "--host", self.mock.base_url, "--agent", "other", "--json")
        todo = [a for a in r.json()["must_fix"] if "token" in a]
        self.assertEqual(1, len(todo), r.json()["must_fix"])
        for word in ("发到对话里", "token set", "标准输入"):
            self.assertIn(word, todo[0])
        for gone in ("环境变量", "终端", "窗口"):
            self.assertNotIn(gone, todo[0])

    def test_forget_删掉(self):
        self.run_it("token", "set", stdin_text=harness.TOKEN)
        r = self.run_it("token", "forget")
        self.assertEqual(0, r.code)
        self.assertIsNone(self.saved())


if __name__ == "__main__":
    unittest.main()
