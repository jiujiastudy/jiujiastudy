"""防臃肿闸：SKILL.md 和 references/ 的体量上限。

技能越厚，弱一点的模型越不照做；这几条上限是发起人定的红线，不是建议。
用法：python tools/skill_check.py [技能目录]（默认脚本所在目录的上一级）。
退出码：0 都在上限内，1 有超的，2 参数不对。
"""
import io
import os
import re
import sys

MAX_SKILL_BYTES = 8192      # SKILL.md 全文
MAX_RULES = 6               # 「规矩」里的编号条
MAX_TABLE_ROWS = 28         # 「用户说什么，做什么」表的行数（不含表头和分隔行）
MAX_REFS_BYTES = 26624      # references/ 合计 26KB


def _read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def check(skill_dir):
    """返回中文问题列表；空列表表示都在上限内。"""
    out = []
    p = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(p):
        return [f"找不到 {p}"]
    text = _read(p)
    size = len(text.encode("utf-8"))
    if size > MAX_SKILL_BYTES:
        out.append(f"SKILL.md {size} 字节，超过上限 {MAX_SKILL_BYTES}（多了 {size - MAX_SKILL_BYTES}）")

    rules = re.findall(r"^\d+\.\s", _section(text, "规矩"), re.M)
    if len(rules) > MAX_RULES:
        out.append(f"规矩 {len(rules)} 条，超过上限 {MAX_RULES}：能让脚本自己打印或自己拒绝的，不要写成规矩")

    rows = [l for l in _section(text, "用户说什么，做什么").splitlines()
            if l.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", l)]
    rows = [l for l in rows if not re.match(r"^\|\s*(用户说|说什么|情况)", l)]
    if len(rows) > MAX_TABLE_ROWS:
        out.append(f"「用户说什么，做什么」{len(rows)} 行，超过上限 {MAX_TABLE_ROWS}")

    refs = os.path.join(skill_dir, "references")
    total = 0
    if os.path.isdir(refs):
        for name in sorted(os.listdir(refs)):
            f = os.path.join(refs, name)
            if os.path.isfile(f):
                total += os.path.getsize(f)
    if total > MAX_REFS_BYTES:
        out.append(f"references/ 合计 {total} 字节，超过上限 {MAX_REFS_BYTES}")
    return out


def _section(text, title):
    """取 ## <title> 到下一个 ## 之间的正文；没有这一节就返回空串。"""
    m = re.search(r"^##\s*" + re.escape(title) + r".*$", text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    n = re.search(r"^##\s", rest, re.M)
    return rest[:n.start()] if n else rest


def main(argv):
    d = argv[1] if len(argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isdir(d):
        print(f"用法：{os.path.basename(__file__)} [技能目录]", file=sys.stderr)
        return 2
    problems = check(d)
    for p in problems:
        print(" -", p)
    print("FAIL" if problems else "OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
