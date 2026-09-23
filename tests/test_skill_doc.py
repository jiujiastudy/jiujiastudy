"""规矩不许变多：SKILL.md 的规矩条数和「用户说什么，做什么」表的行数当测试跑。

指令越多，弱一点的模型越不照做。条数、行数超了就是测试失败，付账办法是删规矩或把判断搬进脚本。
字节数不设上限（发起人 2026-09-23 取消）：为了凑字节删掉有用的话，得不偿失。
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
    def test_条数和行数都在上限内(self):
        problems = load("skill_check").check(SKILL_DIR)
        self.assertEqual([], problems, "；".join(problems))

    def test_闸门认得出规矩太多_但不管字节(self):
        sc = load("skill_check")
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("## 规矩\n" + "".join(f"{i}. 又一条规矩\n" for i in range(1, 9)) + "x" * 20000)
            problems = sc.check(d)
        self.assertTrue(any("规矩" in p for p in problems), problems)
        self.assertFalse(any("字节" in p for p in problems), "字节数不设上限")


if __name__ == "__main__":
    unittest.main()
