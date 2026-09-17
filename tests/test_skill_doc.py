"""技能不许变厚：SKILL.md 和 references/ 的体量上限当测试跑。

发起人的红线：指令越多，弱一点的模型越不照做。上限超了就是测试失败，
付账办法是删规矩或把判断搬进脚本，不是把上限调大。
"""
import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

SKILL_DIR = harness.code_dir()


def load(name):
    spec = importlib.util.spec_from_file_location("_" + name, os.path.join(SKILL_DIR, "tools", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SkillDocTest(unittest.TestCase):
    def test_体量都在上限内(self):
        problems = load("skill_check").check(SKILL_DIR)
        self.assertEqual([], problems, "；".join(problems))

    def test_闸门本身认得出超标(self):
        sc = load("skill_check")
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("## 规矩\n" + "".join(f"{i}. 又一条规矩\n" for i in range(1, 9)) + "x" * 9000)
            problems = sc.check(d)
        self.assertTrue(any("字节" in p for p in problems), problems)
        self.assertTrue(any("规矩" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
