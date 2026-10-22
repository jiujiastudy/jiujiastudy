"""整份收进来的技能 humanizer（blader/humanizer）：口令就叫 /humanizer，用起来跟原版一模一样。

10-22 发起人定的：打 /humanizer 任何情况下都跟原版功能一样；产品以后可能改名，这个口令不能跟着名字走。所以查：
原作者的文件一个字没改；装出去是整份、不读主文件夹；同名的别人的技能（比如学生自己装的原版）不碰，链接过来的也不往里写；
模拟改名、搬家以后口令照样在，改名后的新版照样认得它；卸载、下架只删自己装的。

全部在临时文件夹和假家目录里跑，不碰真实的 ~/.claude、~/.codex、~/.agents。
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

CODE = harness.code_dir()
sys.path.insert(0, os.path.join(CODE, "tools"))
import brand  # noqa: E402
import cc_install  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
SRC = os.path.join(CODE, "skills", "humanizer")
MARK = cc_install.BUNDLED_MARK


def manifest():
    with io.open(os.path.join(FIXTURES, "upstream", "humanizer.json"), encoding="utf-8") as f:
        return json.load(f)


def hashes(root):
    """root 下每个文件的 sha256（记号文件不算）。"""
    out = {}
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for f in files:
            if f == MARK:
                continue
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root).replace(os.sep, "/")] = hashlib.sha256(fh.read()).hexdigest()
    return out


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def make_link(link, target):
    """建一个目录链接（Windows 用目录联接，不要管理员权限）；建不了返回 False。"""
    os.makedirs(os.path.dirname(link), exist_ok=True)
    if os.name == "nt":
        return subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True).returncode == 0
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        return False


class Upstream(unittest.TestCase):
    def test_原作者的文件一个字没改(self):
        m = manifest()
        self.assertEqual("skills/humanizer", m["path"])
        self.assertEqual("blader/humanizer", m["repo"])  # 清单里只写 owner/仓库：fixtures 不放真网址
        self.assertEqual(m["files"], hashes(SRC), "skills/humanizer 跟收进来时不一样：合了原作者的更新就重新生成清单")

    def test_口令就是原名_自带全文_不读主文件夹(self):
        self.assertIn("humanizer", cc_install.BUNDLED)
        self.assertTrue(cc_install.is_entry_name("humanizer"))
        self.assertFalse(cc_install.is_entry_name("humanizer-zh"), "只收这一个，别的同名开头的不算")
        text = read(os.path.join(SRC, "SKILL.md"))
        self.assertRegex(text, r"(?m)^name: humanizer$")
        for word in ("主文件夹", brand.NAME, brand.SLUG, "references/"):
            self.assertNotIn(word, text, "原版全文自己就够用，不指向主文件夹，也不带产品名")
        self.assertNotIn("disable-model-invocation", text, "跟原版一样：不打口令、说一句「改得像人写的」也会用上")
        self.assertTrue(os.path.isfile(os.path.join(SRC, "LICENSE")))

    def test_第三方声明和说明都写着它_不许诺过检测(self):
        notes = read(os.path.join(CODE, "THIRD_PARTY_NOTICES.md"))
        for word in ("blader/humanizer", manifest()["commit"][:7], "skills/humanizer/LICENSE"):
            self.assertIn(word, notes)
        self.assertIn("/humanizer", read(os.path.join(CODE, "SKILL.md")))
        readme = read(os.path.join(CODE, "README.md"))
        self.assertIn("/humanizer", readme)
        self.assertNotIn("降低 AI 痕迹」之类的事", readme, "收了 humanizer，这句话就不对了")
        for word in ("降 AI 率", "降AI率", "过检测"):
            self.assertNotIn(word, readme, "原作者写明躲检测器不是它的目标：对学生不许诺")


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="humanizer-")
        self.home = os.path.join(self.tmp, "home")
        self.skills = os.path.join(self.home, ".claude", "skills")
        self.main = self.make_main(os.path.join(self.skills, brand.SLUG))
        self.dst = os.path.join(self.skills, "humanizer")
        self.links = []

    def tearDown(self):
        for link in self.links:  # 先拆链接，再删临时文件夹：删的时候不顺着链接进去
            try:
                os.rmdir(link) if os.name == "nt" else os.unlink(link)
            except OSError:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_main(self, path):
        write(os.path.join(path, "SKILL.md"), f"---\nname: {os.path.basename(path)}\n---\n")
        shutil.copytree(SRC, os.path.join(path, "skills", "humanizer"))
        return path

    def rows(self, main=None):
        return {r["name"]: r for r in cc_install.installed_entries(main or self.main)}

    def test_新电脑装上就有_humanizer_和原版逐字节一样(self):
        r = cc_install.install_entries(self.main)
        self.assertIn(self.dst, r["installed"])
        self.assertEqual(manifest()["files"], hashes(self.dst))
        info = cc_install.entry_info(self.dst)
        self.assertTrue(cc_install._same(self.main, info["main"]))
        self.assertEqual(brand.VERSION, info["version"])
        self.assertTrue(self.rows()["humanizer"]["installed"])
        self.assertEqual([], cc_install.entry_problems(self.main, home=self.home))

    def test_源文件是Windows换行_装出去还是原版的LF(self):
        for rel in manifest()["files"]:
            p = os.path.join(self.main, "skills", "humanizer", *rel.split("/"))
            with open(p, "rb") as f:
                data = f.read()
            with open(p, "wb") as f:
                f.write(data.replace(b"\n", b"\r\n"))
        cc_install.install_entries(self.main)
        self.assertEqual(manifest()["files"], hashes(self.dst))

    def test_学生自己装过同名的_不覆盖不删_doctor不提(self):
        write(os.path.join(self.dst, "SKILL.md"), "---\nname: humanizer\n---\n学生自己装的\n")
        r = cc_install.install_entries(self.main)
        self.assertIn(self.dst, r["conflicts"])
        self.assertEqual([], r["installed"])
        self.assertIn("学生自己装的", read(os.path.join(self.dst, "SKILL.md")))
        self.assertFalse(os.path.exists(os.path.join(self.dst, MARK)))
        row = self.rows()["humanizer"]
        self.assertFalse(row["installed"])
        self.assertTrue(row["taken"])
        self.assertEqual([], cc_install.entry_problems(self.main, home=self.home))
        cc_install.remove_entries(self.main)
        self.assertIn("学生自己装的", read(os.path.join(self.dst, "SKILL.md")))

    def test_链接过来的同名技能_不往里写_卸载也不删(self):
        # skills 命令行的装法：~/.claude/skills/humanizer 链到 ~/.agents/skills/humanizer。就算那边带着这里的记号，也不顺着链接写、删
        target = os.path.join(self.home, ".agents", "skills", "humanizer")
        write(os.path.join(target, "SKILL.md"), "---\nname: humanizer\n---\n链过去的那份\n")
        write(os.path.join(target, MARK), json.dumps({"main": self.main, "version": "0.0.1"}))
        if not make_link(self.dst, target):
            self.skipTest("这台机器建不了目录链接")
        self.links.append(self.dst)
        r = cc_install.install_entries(self.main)
        self.assertIn(self.dst, r["conflicts"])
        self.assertIn("链过去的那份", read(os.path.join(target, "SKILL.md")))
        self.assertEqual([], cc_install.remove_entries(self.main))
        self.assertIn("链过去的那份", read(os.path.join(target, "SKILL.md")))

    def test_改名搬家以后_口令照样在_改名后的新版照样认得(self):
        cc_install.install_entries(self.main)
        # 产品改名：主文件夹换了名字，旧的没了
        new_main = os.path.join(self.skills, "newname")
        shutil.move(self.main, new_main)
        # 还没重新装：/humanizer 那份不靠主文件夹，原样还在
        self.assertEqual(manifest()["files"], hashes(self.dst))
        problems = cc_install.entry_problems(new_main, home=self.home)
        self.assertTrue(any(lvl == "warn" and "已经不在" in d for lvl, d, _ in problems), problems)
        # 改名后的新版来装：产品名、文件夹名、版本都换了，照样认得旧记号，换成新的，不当成别人的
        with mock.patch.object(brand, "NAME", "新名字"), mock.patch.object(brand, "SLUG", "newname"), \
                mock.patch.object(brand, "VERSION", "9.9.9"):
            r = cc_install.install_entries(new_main)
            self.assertIn(self.dst, r["installed"])
            self.assertEqual([], r["conflicts"])
            info = cc_install.entry_info(self.dst)
            self.assertTrue(cc_install._same(new_main, info["main"]))
            self.assertEqual("9.9.9", info["version"])
            self.assertEqual([], cc_install.entry_problems(new_main, home=self.home))
        self.assertEqual(manifest()["files"], hashes(self.dst))

    def test_卸载和下架_只删自己装的(self):
        cc_install.install_entries(self.main)
        self.assertEqual([self.dst], cc_install.remove_entries(self.main))
        self.assertFalse(os.path.exists(self.dst))
        # 以后哪一版不收它了：源里没有，又是这个主文件夹装的，就删掉
        cc_install.install_entries(self.main)
        shutil.rmtree(os.path.join(self.main, "skills", "humanizer"))
        r = cc_install.install_entries(self.main)
        self.assertEqual([self.dst], r["removed"])
        self.assertFalse(os.path.exists(self.dst))

    def test_Codex_两处都装了_doctor提醒菜单里两遍(self):
        cc_install.install_entries(self.main)
        for h in (".codex", ".agents"):
            d = os.path.join(self.home, h, "skills", "humanizer")
            write(os.path.join(d, "SKILL.md"), read(os.path.join(SRC, "SKILL.md")))
            write(os.path.join(d, MARK), json.dumps({"main": self.main, "version": brand.VERSION}))
        details = [d for lvl, d, _ in cc_install.entry_problems(self.main, home=self.home) if lvl == "warn"]
        self.assertTrue(any("humanizer" in d and "出现两遍" in d for d in details), details)


if __name__ == "__main__":
    unittest.main()
