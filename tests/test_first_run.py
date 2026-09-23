"""第一次用就顺利拿到周报（2026-09-23 一位同学用 Codex 装 v0.2.0 的记录暴露的问题）。

- 交周报时（study --write --open）直接打开，并写好「我能帮你做什么」页；测试环境（NO_DIALOG）不许真的打开浏览器、
  不许往真实桌面放快捷方式。
- 本周清单上写明：打完勾要回 AI 对话说「做完了」；不知道怎么办直接问 AI。
- 登录窗口：这个进程在用户看不见的桌面上（沙盒）就不开窗口，也不许让 AI 以为窗口在等人；
  给 AI 的话里写明别改用宿主自带的浏览器（救驾读不到那里的登录）。
- skills 里多出来的一份（更新时的备份、旧名字）要提醒挪走；别的 AI 工具用的同名一份只在版本旧时提一句。
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
sys.path.insert(0, TOOLS)
import brand  # noqa: E402
import cc_install  # noqa: E402
import cc_session  # noqa: E402
import render_help  # noqa: E402

NOW = "2026-03-24T23:00:00Z"
DATE = "2026-03-24"


class StudyOpen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sc = mockcanvas.Scenario("au_semester")
        cls.mock = mockcanvas.MockCanvas(cls.sc).start()
        cls.home = harness.FakeHome("first-run")
        cls.home.seed(cls.sc, cls.mock.base_url)
        run = lambda *a: harness.run_coach(cls.home, list(a) + ["--date", DATE], TOOLS, now=NOW, ports=(cls.mock.port,))  # noqa: E731
        run("collect", "--touch")
        cls.study = run("study", "--write", "--open", "--json")

    @classmethod
    def tearDownClass(cls):
        cls.home.cleanup()
        cls.mock.stop()

    def test_交周报时写好帮助页_测试里不开浏览器不放快捷方式(self):
        self.assertEqual(0, self.study.code, self.study.stderr)
        res = self.study.json()
        self.assertFalse(res.get("opened"), "NO_DIALOG 下不许真的打开浏览器")
        self.assertIsNone(res.get("shortcut"), "测试里的资料夹不在真实桌面上，不放快捷方式")
        self.assertTrue(res.get("help") and os.path.isfile(res["help"]), res)
        self.assertEqual(self.home.root, os.path.dirname(res["help"]))
        with open(res["help"], encoding="utf-8") as f:
            page = f.read()
        self.assertIn("不知道怎么办，直接问 AI", page)
        self.assertIn('data-copy="这周学什么"', page, "点一句话就能复制")
        self.assertIn(f'data-version="{brand.VERSION}"', page)

    def test_本周清单上写明打完勾要回来说做完了(self):
        with open(os.path.join(self.home.root, "本周清单.html"), encoding="utf-8") as f:
            text = harness.visible_text(f.read())
        self.assertIn("做完了", text)
        self.assertIn("不知道怎么办，直接问 AI", text)

    def test_不加_open_就不写帮助页(self):
        home = harness.FakeHome("first-run-quiet")
        try:
            home.seed(self.sc, self.mock.base_url)
            r = harness.run_coach(home, ["study", "--write", "--json", "--date", DATE], TOOLS, now=NOW, ports=(self.mock.port,))
            self.assertEqual(0, r.code, r.stderr)
            self.assertFalse(os.path.exists(os.path.join(home.root, render_help.PAGE)), "每天的定时任务不加 --open，不动资料夹")
        finally:
            home.cleanup()


class DesktopShortcut(unittest.TestCase):
    """资料夹在桌面上时放一个「本周清单」快捷方式；桌面换成临时文件夹来测，不碰真实桌面。"""

    def setUp(self):
        import cc_paths
        self.cc_paths = cc_paths
        self.desk = os.path.realpath(tempfile.mkdtemp(prefix="stc-desk-", dir=os.environ.get("STC_TEST_TMP") or None))
        self._desktop, self._env = cc_paths.desktop_dir, dict(os.environ)
        cc_paths.desktop_dir = lambda: self.desk
        for k in list(os.environ):
            if k.endswith("_NO_DIALOG"):
                del os.environ[k]
        self.root = os.path.join(self.desk, brand.NAME)
        os.makedirs(self.root)
        self.page = os.path.join(self.root, "本周清单.html")
        with open(self.page, "w", encoding="utf-8") as f:
            f.write("<p>week</p>")

    def tearDown(self):
        self.cc_paths.desktop_dir = self._desktop
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.desk, ignore_errors=True)

    def test_放一个_重复跑不出错_资料夹不在桌面就不放(self):
        first = self.cc_paths.desktop_shortcut(self.root, self.page)
        self.assertTrue(first and os.path.lexists(first), "资料夹在桌面上：放快捷方式")
        self.assertEqual(first, self.cc_paths.desktop_shortcut(self.root, self.page), "已经有了就不动")
        if sys.platform == "win32":
            with open(first, encoding="utf-8") as f:
                self.assertIn("URL=file:///", f.read())
        else:
            self.assertEqual(os.path.realpath(self.page), os.path.realpath(first))
        elsewhere = os.path.join(self.desk, "sub", brand.NAME)
        os.makedirs(elsewhere)
        self.assertIsNone(self.cc_paths.desktop_shortcut(elsewhere, self.page), "资料夹不在桌面上：不放")


class LoginWindowHidden(unittest.TestCase):
    def setUp(self):
        self._visible, self._spawn = cc_session.visible_desktop, cc_session._spawn
        self.spawned = []
        cc_session.visible_desktop = lambda: False
        cc_session._spawn = lambda *a, **k: self.spawned.append(a)
        self.home = tempfile.mkdtemp(prefix="stc-nowin-", dir=os.environ.get("STC_TEST_TMP") or None)

    def tearDown(self):
        cc_session.visible_desktop, cc_session._spawn = self._visible, self._spawn
        shutil.rmtree(self.home, ignore_errors=True)

    def test_沙盒里不开窗口_也不说窗口在等(self):
        r = cc_session.start_login(self.home, "https://canvas.example.edu", wait=0)
        self.assertEqual("no_window", r["state"])
        self.assertEqual([], self.spawned, "看不见的窗口不许开")
        self.assertIn("沙盒外", r["message"])
        self.assertIn("白登一次", r["message"], "要写明为什么不能换宿主自带的浏览器")
        self.assertNotIn("已经打开", r["message"])

    def test_窗口开着时给用户的话里有任务栏和会自己关(self):
        self.assertIn("任务栏", cc_session.WAITING_MSG)
        self.assertIn("会自己关", cc_session.WAITING_MSG)
        self.assertIn("白登一次", cc_session.WAITING_MSG)


class DuplicateSkills(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="stc-dups-", dir=os.environ.get("STC_TEST_TMP") or None))
        self.me = self.skill(".claude", brand.SLUG, brand.VERSION)

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def skill(self, host, name, version):
        d = os.path.join(self.base, host, "skills", name)
        os.makedirs(os.path.join(d, "tools"))
        with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(f"---\nname: {brand.SLUG}\n---\n")
        with open(os.path.join(d, "tools", "brand.py"), "w", encoding="utf-8") as f:
            f.write(f'VERSION = "{version}"\n')
        return d

    def test_都没有就不说话(self):
        self.assertEqual([], cc_install.duplicate_skills(self.me, home=self.base))

    def test_skills_里的备份要挪走(self):
        bak = self.skill(".codex", brand.SLUG + ".backup-20260923-193053", "0.2.0")
        self.skill(".claude", "course-coach", "0.1.0")
        found = cc_install.duplicate_skills(self.me, home=self.base)
        self.assertEqual(["warn", "warn"], [lvl for lvl, _, _ in found])
        self.assertTrue(any(bak in detail for _, detail, _ in found))
        self.assertTrue(all("挪" in action and "别删" in action for _, _, action in found))

    def test_别的工具用的同名一份_只在旧的时候提一句(self):
        self.skill(".agents", brand.SLUG, brand.VERSION)
        self.assertEqual([], cc_install.duplicate_skills(self.me, home=self.base), "一样新：是给别的工具用的，正常")
        shutil.rmtree(os.path.join(self.base, ".agents"))
        self.skill(".agents", brand.SLUG, "0.1.0")
        found = cc_install.duplicate_skills(self.me, home=self.base)
        self.assertEqual(["info"], [lvl for lvl, _, _ in found])
        self.assertIn("0.1.0", found[0][1])


if __name__ == "__main__":
    unittest.main()
