"""照搬安装：学生跟 AI 说一句「帮我安装 jiujiastudy」，AI 把仓库放进 skills 文件夹之后，能不能直接用。

这条路以前只在文档里写着，没跑过。这里整份仓库复制进假的 ~/.claude/skills/jiujiastudy，
再从那个位置一路走到第一份雷达和本周清单——中间只有「粘 token」是人做的，其余都不该要人动手。
"""
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

CODE = harness.code_dir()
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "tests", "golden")


class InstallRehearsal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sc = mockcanvas.Scenario("au_semester")
        cls.mock = mockcanvas.MockCanvas(cls.sc).start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def setUp(self):
        self.home = harness.FakeHome("install")
        # AI 会做的那一步：把仓库整个放进宿主找得到的位置
        self.skill = os.path.join(self.home.user, ".claude", "skills", "jiujiastudy")
        shutil.copytree(CODE, self.skill, ignore=SKIP)
        self.tools = os.path.join(self.skill, "tools")

    def tearDown(self):
        self.home.cleanup()

    def run_it(self, *args, **kw):
        return harness.run_coach(self.home, list(args), self.tools, now=self.sc.meta["now"],
                                 ports=(self.mock.port,), **kw)

    def test_装完就是能跑的那几样(self):
        for rel in ("SKILL.md", "README.md", os.path.join("tools", "coach.py"),
                    os.path.join("references", "setup.md"), os.path.join("assets", "xiaohongshu.png")):
            self.assertTrue(os.path.isfile(os.path.join(self.skill, rel)), rel)

    def test_第一句话就知道该干嘛(self):
        """还没建档时 status 要说清楚下一步，而不是报错了事。"""
        r = self.run_it("status", "--date", self.sc.meta["date"])
        out = r.stdout + r.stderr
        self.assertIn("还没", out)
        self.assertIn("doctor", out, "要告诉 AI 下一步跑什么")

    def test_一路走到第一份清单(self):
        date = self.sc.meta["date"]
        r, res = self.doctor()
        self.assertEqual(0, r.code, res.get("text"))
        self.assertIs(True, res["ready"])
        self.assertIn(("OK", "skill 位置"), {(c["level"], c["name"]) for c in res["checks"]},
                      "装在 ~/.claude/skills/jiujiastudy 就该判定位置正确")

        for args in (("collect", "--touch", "--json"), ("radar", "--write", "--json"), ("study", "--write", "--json")):
            with self.subTest(cmd=args[0]):
                rr = self.run_it(*args, "--date", date)
                self.assertEqual(0, rr.code, rr.stdout[-500:] + rr.stderr[-500:])

        for name in ("本周清单.html", "Deadline雷达.html"):
            self.assertTrue(os.path.isfile(os.path.join(self.home.root, name)), name)
        for name in ("config.json", "state.json"):
            self.assertTrue(os.path.isfile(os.path.join(self.home.archive, name)), name)

    def test_没有网也不至于报个堆栈(self):
        r = self.run_it("status", "--date", self.sc.meta["date"], extra_env={"CANVAS_TOKEN": None})
        self.assertNotIn("Traceback", r.stderr)

    def doctor(self):
        r = self.run_it("doctor", "--no-detect", "--host", self.mock.base_url, "--tz", "Australia/Sydney",
                        "--agent", "claude", "--all-courses", "--json")
        try:
            return r, r.json()
        except ValueError:
            self.fail(f"doctor --json 没输出 JSON（exit {r.code}）：\n{r.stdout[-600:]}\n{r.stderr[-600:]}")


if __name__ == "__main__":
    unittest.main()
