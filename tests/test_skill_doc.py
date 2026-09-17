"""技能不许变厚：SKILL.md 和 references/ 的体量上限当测试跑。

发起人的红线：指令越多，弱一点的模型越不照做。上限超了就是测试失败，
付账办法是删规矩或把判断搬进脚本，不是把上限调大。（09-17 发起人亲自把 SKILL.md 放宽到 10KB 一次，
给 allowed-tools 和统一的调用写法；别的上限没动。）
"""
import importlib.util
import io
import os
import re
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
                f.write("## 规矩\n" + "".join(f"{i}. 又一条规矩\n" for i in range(1, 9)) + "x" * 11000)
            problems = sc.check(d)
        self.assertTrue(any("字节" in p for p in problems), problems)
        self.assertTrue(any("规矩" in p for p in problems), problems)


class PermissionTest(unittest.TestCase):
    """用户点「允许」的次数取决于这里：allowed-tools 按原样匹配命令，SKILL.md 教的写法必须被它覆盖。"""

    @classmethod
    def setUpClass(cls):
        with io.open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as f:
            cls.text = f.read()
        front = cls.text.split("---", 2)[1]
        m = re.search(r"^allowed-tools:\s*(.+)$", front, re.M)
        cls.allowed = m.group(1) if m else ""

    def test_教的写法被_allowed_tools_覆盖(self):
        form = 'python "${CLAUDE_SKILL_DIR}/tools/coach.py"'
        self.assertIn(f"`{form} 命令 参数`", self.text, "SKILL.md 要把调用写法写死")
        for tool in ("Bash", "PowerShell"):
            for py in ("python", "python3", "py -3"):
                self.assertIn(f'{tool}({py} "${{CLAUDE_SKILL_DIR}}/tools/coach.py" *)', self.allowed)

    def test_只放行自己的脚本(self):
        rules = re.findall(r"(\w+)\(([^)]*)\)", self.allowed)
        self.assertTrue(rules)
        for tool, pattern in rules:
            self.assertIn(tool, ("Bash", "PowerShell"))
            self.assertRegex(pattern, r'^(python|python3|py -3) "\$\{CLAUDE_SKILL_DIR\}/tools/coach\.py" \*$')

    def test_不再教读浏览器记录和改权限(self):
        for gone in ("--detect-site", "--fix-perms", "--env-dialog", "settings.json"):
            self.assertNotIn(gone, self.text)


if __name__ == "__main__":
    unittest.main()
