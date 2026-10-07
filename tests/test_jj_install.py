"""/jj 入口的安装：装到主文件夹旁边、写进路径和版本、删旧入口、不碰别人的技能、doctor 四查、jj list / remove。

全部在临时文件夹和假家目录里跑，不碰真实的 ~/.claude、~/.codex、~/.agents。
"""
import io
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

CODE = harness.code_dir()
sys.path.insert(0, os.path.join(CODE, "tools"))
import brand  # noqa: E402
import cc_install  # noqa: E402

SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "tests", "golden")
PLACEHOLDER = "救驾主文件夹：C:\\Users\\<用户名>\\.claude\\skills\\jiujiastudy   ← 安装脚本写入，不手改"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def entry_text(name, ref, main_line=PLACEHOLDER, version="<和主文件夹一致>"):
    return (f"---\nname: {name}\ndescription: 测试：{name}\ndisable-model-invocation: true\n---\n\n{main_line}\n\n"
            f"1. 读主文件夹里的 references/{ref}，照着做。\n\n想法来自 dontbesilent 的 dbskill（dbs-x）。版本 {version}\n")


class JjInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jjinst-")
        self.home = os.path.join(self.tmp, "home")
        self.skills = os.path.join(self.home, ".claude", "skills")
        self.main = os.path.join(self.skills, "jiujiastudy")
        write(os.path.join(self.main, "SKILL.md"), "---\nname: jiujiastudy\n---\n")
        for name, ref in (("jj-a", "a.md"), ("jj-b", "b.md")):
            write(os.path.join(self.main, "skills", name, "SKILL.md"), entry_text(name, ref))
            write(os.path.join(self.main, "skills", name, "agents", "openai.yaml"),
                  f'interface:\n  display_name: "{name} 测试"\npolicy:\n  allow_implicit_invocation: false\n')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read(self, *parts):
        with io.open(os.path.join(self.skills, *parts), encoding="utf-8") as f:
            return f.read()

    def test_装到主文件夹旁边_写进路径和版本(self):
        r = cc_install.install_entries(self.main)
        self.assertEqual(2, len(r["installed"]), r)
        text = self.read("jj-a", "SKILL.md")
        self.assertIn("救驾主文件夹：" + os.path.normpath(self.main), text)
        self.assertNotIn("<用户名>", text)
        self.assertNotIn("安装脚本写入", text)
        self.assertIn("版本 " + brand.VERSION, text)
        self.assertTrue(os.path.isfile(os.path.join(self.skills, "jj-b", "agents", "openai.yaml")))

    def test_主文件夹不在skills里就不装(self):
        loose = os.path.join(self.tmp, "Downloads", "jiujiastudy")
        shutil.copytree(self.main, loose)
        r = cc_install.install_entries(loose)
        self.assertEqual([], r["installed"])
        self.assertTrue(r["skipped"])

    def test_同名的别人的技能不覆盖(self):
        write(os.path.join(self.skills, "jj-a", "SKILL.md"), "---\nname: jj-a\n---\n别人的技能\n")
        r = cc_install.install_entries(self.main)
        self.assertEqual([os.path.join(self.skills, "jj-a")], r["conflicts"])
        self.assertIn("别人的技能", self.read("jj-a", "SKILL.md"))

    def test_源里没有的旧入口删掉_别人的和别的主文件夹的不碰(self):
        write(os.path.join(self.skills, "jj-old", "SKILL.md"), entry_text("jj-old", "old.md", "救驾主文件夹：" + self.main, "0.1.0"))
        other = os.path.join(self.tmp, "other", "jiujiastudy")
        os.makedirs(other)
        write(os.path.join(self.skills, "jj-theirs", "SKILL.md"), entry_text("jj-theirs", "t.md", "救驾主文件夹：" + other, "0.1.0"))
        write(os.path.join(self.skills, "jj-foreign", "SKILL.md"), "---\nname: jj-foreign\n---\n不是救驾的\n")
        r = cc_install.install_entries(self.main)
        self.assertEqual([os.path.join(self.skills, "jj-old")], r["removed"])
        self.assertTrue(os.path.isdir(os.path.join(self.skills, "jj-theirs")))
        self.assertTrue(os.path.isdir(os.path.join(self.skills, "jj-foreign")))

    def test_搬家以后重写路径(self):
        cc_install.install_entries(self.main)
        stale = entry_text("jj-a", "a.md", "救驾主文件夹：" + os.path.join(self.tmp, "gone", "jiujiastudy"), brand.VERSION)
        write(os.path.join(self.skills, "jj-a", "SKILL.md"), stale)
        problems = cc_install.entry_problems(self.main, home=self.home)
        self.assertTrue(any(lvl == "warn" and "已经不在" in d for lvl, d, _ in problems), problems)
        cc_install.install_entries(self.main)
        self.assertIn("救驾主文件夹：" + os.path.normpath(self.main), self.read("jj-a", "SKILL.md"))
        self.assertEqual([], cc_install.entry_problems(self.main, home=self.home))

    def test_doctor四查(self):
        problems = cc_install.entry_problems(self.main, home=self.home)
        self.assertEqual({"info"}, {lvl for lvl, _, _ in problems}, "没装的只提一句")
        cc_install.install_entries(self.main)
        write(os.path.join(self.skills, "jj-b", "SKILL.md"), entry_text("jj-b", "b.md", "救驾主文件夹：" + self.main, "0.0.9"))
        for h in (".codex", ".agents"):
            write(os.path.join(self.home, h, "skills", "jj-a", "SKILL.md"), entry_text("jj-a", "a.md", "救驾主文件夹：" + self.main, brand.VERSION))
        details = [d for lvl, d, _ in cc_install.entry_problems(self.main, home=self.home) if lvl == "warn"]
        self.assertTrue(any("0.0.9" in d for d in details), details)
        self.assertTrue(any("出现两遍" in d for d in details), details)

    def test_列出和删除_只删自己的(self):
        cc_install.install_entries(self.main)
        write(os.path.join(self.skills, "jj-foreign", "SKILL.md"), "---\nname: jj-foreign\n---\n")
        rows = {r["name"]: r for r in cc_install.installed_entries(self.main)}
        self.assertTrue(rows["jj-a"]["installed"])
        self.assertEqual(["a.md"], rows["jj-a"]["refs"])
        self.assertNotIn("jj-foreign", rows)
        removed = cc_install.remove_entries(self.main)
        self.assertEqual(2, len(removed))
        self.assertTrue(os.path.isdir(os.path.join(self.skills, "jj-foreign")))


class JjInstallThroughDoctor(unittest.TestCase):
    """学生那条路：仓库整个在 ~/.claude/skills/jiujiastudy，跑 doctor --install，入口出现在它旁边；jj list 看得到。"""

    @classmethod
    def setUpClass(cls):
        cls.sc = mockcanvas.Scenario("au_semester")
        cls.mock = mockcanvas.MockCanvas(cls.sc).start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def setUp(self):
        self.home = harness.FakeHome("jjinstall")
        self.skills = os.path.join(self.home.user, ".claude", "skills")
        self.skill = os.path.join(self.skills, "jiujiastudy")
        shutil.copytree(CODE, self.skill, ignore=SKIP)
        self.tools = os.path.join(self.skill, "tools")

    def tearDown(self):
        self.home.cleanup()

    def run_it(self, *args):
        return harness.run_coach(self.home, list(args), self.tools, now=self.sc.meta["now"], ports=(self.mock.port,))

    def test_doctor_install装上入口_jj_list看得到(self):
        r = self.run_it("doctor", "--no-detect", "--host", self.mock.base_url, "--tz", "Australia/Sydney",
                        "--agent", "claude", "--all-courses", "--install", "--json")
        self.assertEqual(0, r.code, r.stdout[-600:] + r.stderr[-600:])
        sources = sorted(n for n in os.listdir(os.path.join(self.skill, "skills")) if n.startswith("jj-"))
        self.assertTrue(sources)
        for name in sources:
            with self.subTest(entry=name):
                with io.open(os.path.join(self.skills, name, "SKILL.md"), encoding="utf-8") as f:
                    text = f.read()
                self.assertIn("救驾主文件夹：" + os.path.normpath(self.skill), text)
                self.assertIn("版本 " + brand.VERSION, text)
        lst = self.run_it("jj", "list", "--json")
        self.assertEqual(0, lst.code, lst.stderr[-400:])
        rows = {e["name"]: e for e in lst.json()["entries"]}
        self.assertTrue(all(rows[n]["installed"] for n in sources), rows)


if __name__ == "__main__":
    unittest.main()
