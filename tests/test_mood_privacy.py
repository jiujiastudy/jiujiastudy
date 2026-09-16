"""学生说的原话不存进档案，也不在之后的输出里复读（G02）。

审计实测：说过一次之后，那句话出现在 7 个文件里（state.json、DDL雷达.md、plans/*.json 和 .md、
reports/周报_*.html、桌面的 Deadline雷达.html 和周手帐 HTML），而且连着 7 天每条状态行都引用一次。
别人瞄一眼屏幕就看见了。
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")
WORD = "我不想活了"  # 只在这条测试里出现；跑完必须在所有生成的文件里都找不到


class MoodPrivacy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sc = mockcanvas.Scenario("au_semester")
        cls.mock = mockcanvas.MockCanvas(cls.sc).start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def setUp(self):
        self.home = harness.FakeHome("mood")
        self.home.seed(self.sc, self.mock.base_url)
        self.date = self.sc.meta["date"]
        self.now = self.sc.meta["now"]

    def tearDown(self):
        self.home.cleanup()

    def coach(self, *args):
        return harness.run_coach(self.home, list(args) + ["--date", self.date], TOOLS,
                                 now=self.now, ports=(self.mock.port,))

    def written_files(self):
        out = []
        for base in (self.home.archive, self.home.root):
            for dirpath, _dirs, files in os.walk(base):
                for f in files:
                    out.append(os.path.join(dirpath, f))
        return out

    def test_原话不进档案也不进页面(self):
        self.assertEqual(0, self.coach("collect", "--touch").code)
        self.assertEqual(0, self.coach("record", "mood", WORD).code)
        self.assertEqual(0, self.coach("radar", "--write").code)
        self.assertEqual(0, self.coach("study", "--write").code)
        hits = []
        for p in self.written_files():
            try:
                with open(p, encoding="utf-8") as f:
                    if WORD in f.read():
                        hits.append(os.path.relpath(p, self.home.dir))
            except (OSError, UnicodeDecodeError):
                continue
        self.assertEqual([], hits, "这句原话不该出现在任何文件里")

    def test_状态行只说级别不复述(self):
        self.coach("collect", "--touch")
        self.coach("record", "mood", WORD)
        r = self.coach("status")
        self.assertNotIn(WORD, r.stdout)
        self.assertIn("状态不好", r.stdout, "状态行应该说「你 X 号说过状态不好」")

    def test_state_里不再留_word_字段(self):
        self.coach("collect", "--touch")
        self.coach("record", "mood", WORD)
        state = json.load(open(os.path.join(self.home.archive, "state.json"), encoding="utf-8"))
        moods = state.get("mood") or []
        self.assertTrue(moods, "应该记了一条")
        for m in moods:
            self.assertNotIn("word", m, "只存日期和级别")
            self.assertIn("level", m)


if __name__ == "__main__":
    unittest.main()
