"""/jj 菜单里每个入口（skills/jj-*）的格式：薄入口，只能手动叫，指向主文件夹里真实存在的说明。

写法见 docs/DBS改编手册.md 第四节。入口不写流程，只写说明开头、主文件夹路径、几行指路、出处和版本号。
"""
import io
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

SKILL_DIR = harness.code_dir()
ENTRY_ROOT = os.path.join(SKILL_DIR, "skills")


def entries():
    if not os.path.isdir(ENTRY_ROOT):
        return []
    return sorted(n for n in os.listdir(ENTRY_ROOT) if n.startswith("jj-") and os.path.isdir(os.path.join(ENTRY_ROOT, n)))


def read(*parts):
    with io.open(os.path.join(ENTRY_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def yaml_value(text, key):
    m = re.search(r"^\s*" + re.escape(key) + r":\s*(.+?)\s*$", text, re.M)
    return m.group(1).strip().strip('"') if m else ""


class JjEntryTest(unittest.TestCase):
    def test_至少有几个入口(self):
        self.assertGreaterEqual(len(entries()), 1)

    def test_每个入口的格式(self):
        for name in entries():
            with self.subTest(entry=name):
                skill = read(name, "SKILL.md")
                fm = frontmatter(skill)
                self.assertEqual(fm.get("name"), name, "name 要和文件夹名一样")
                desc = fm.get("description", "")
                self.assertTrue(desc, "要有 description")
                label = desc.split("：", 1)[0]
                self.assertTrue(0 < len(label) <= 8 and "：" in desc, "description 开头几个字写它帮学生做什么，再接「：」")
                self.assertEqual(fm.get("disable-model-invocation"), "true", "只能手动叫")
                self.assertIn("救驾主文件夹：", skill, "要写主文件夹路径那一行（安装脚本写入）")
                refs = re.findall(r"references/([\w-]+\.md)", skill)
                self.assertTrue(refs, "要指向主文件夹里的 references/<功能>.md")
                for ref in refs:
                    self.assertTrue(os.path.isfile(os.path.join(SKILL_DIR, "references", ref)), f"references/{ref} 不存在")
                self.assertRegex(skill, r"想法来自 dontbesilent 的 dbskill（dbs-[\w、 -]+）|不来自 dontbesilent 的 dbskill", "要写出处")
                for word in ("提醒你", "到点回来问", "到点提醒"):
                    self.assertNotIn(word, skill, "不写会让人以为有提醒的话")
                body = skill.split("---", 2)[-1]
                self.assertLessEqual(len([l for l in body.splitlines() if re.match(r"^\d+\.\s", l)]), 3, "入口不写流程，只写几行指路")

                yml = read(name, "agents", "openai.yaml")
                self.assertRegex(yml, r"allow_implicit_invocation:\s*false", "Codex 里也只能手动叫")
                self.assertTrue(yaml_value(yml, "display_name").startswith(name), "display_name 以入口名开头")
                short = yaml_value(yml, "short_description")
                self.assertTrue(short.startswith(label + "："), "short_description 开头和 description 一样，关键词放最前")
                self.assertIn("$" + name, yaml_value(yml, "default_prompt"), "default_prompt 里写出 $入口名")


if __name__ == "__main__":
    unittest.main()
