"""风格检查：页面有没有跑出 references/style.md 的规范。

用法：python tools/style_check.py 页面.html [更多.html ...]
查五样：字号不在四级阶梯里、颜色没走变量、字体没走变量、正文里有 emoji、引了外部脚本。
design.py 里 /*tokens*/ 那一段是变量定义本身，不算违规。有问题退出码 1。
"""
import re
import sys

SIZES = {13.0, 15.0, 18.0, 26.0}
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿️]")
FAMILY_OK = re.compile(r"var\(--(font|mono)\)|inherit")


def check(path):
    try:
        with open(path, encoding="utf-8") as f:
            h = f.read()
    except OSError as e:
        return [f"读不了：{e}"]
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", h, re.S))
    css = re.sub(r"/\*tokens\*/.*?/\*end tokens\*/", "", css, flags=re.S)
    css += "\n" + "\n".join(re.findall(r'\sstyle="([^"]*)"', h))
    out = []
    for m in re.finditer(r"font(-size)?\s*:\s*([^;}]+)", css):
        val = m.group(2)
        size_part = val if m.group(1) else val.split("/")[0]
        for px in re.findall(r"(\d+(?:\.\d+)?)px", size_part):
            if float(px) not in SIZES:
                out.append(f"字号 {px}px 不在阶梯里，只能用 --fs-s / --fs-m / --fs-l / --fs-xl")
        if not m.group(1) and not FAMILY_OK.search(val):
            out.append(f"字体没走变量：font:{val.strip()[:40]}")
    for m in re.finditer(r"font-family\s*:\s*([^;}]+)", css):
        if not FAMILY_OK.search(m.group(1)):
            out.append(f"字体没走变量：font-family:{m.group(1).strip()[:40]}")
    for m in re.finditer(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)", css):
        out.append(f"颜色没走变量：{m.group(0)}")
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", h, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", re.sub(r'src="data:[^"]*"', "", body))
    emo = sorted(set(EMOJI.findall(text)))
    if emo:
        out.append("正文里有 emoji：" + " ".join(emo))
    if re.search(r"<script[^>]*\bsrc=", h):
        out.append("引了外部脚本")
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not argv:
        print(__doc__)
        return 2
    bad = 0
    for p in argv:
        probs = check(p)
        print(("OK   " if not probs else "FAIL ") + p)
        for x in probs[:30]:
            print("     - " + x)
        bad += bool(probs)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
