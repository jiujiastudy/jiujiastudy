"""版面检查：在手机宽（390）和电脑宽（1280）各打开一遍页面，看两样——整页会不会左右滚动、有没有字被挤成竖排。

用法：python tools/layout_check.py 页面.html [更多.html ...]
中文每个字之间都能断行，一列被挤窄时不会溢出，而是变成一字一行（10-07：范例说明、周报的学习页那几行、一张表格都这样过，
只看手机宽度、只看会不会左右滚动的检查发现不了）。折叠起来的内容会先展开再量。有问题退出码 1；开不了浏览器退出码 2。
"""
import os
import sys
import urllib.parse

WIDTHS = ((390, 844), (1280, 900))
CHANNELS = ("msedge", "chrome", None)  # None = Playwright 自带的 Chromium（装过才有）
# 自己带的字有 6 个以上，宽度却不到 4 个字、高度超过 5 行：就是被挤成竖排了
SQUEEZED = """() => {
  document.querySelectorAll('details').forEach(d => { d.open = true; });
  const out = [];
  for (const e of document.querySelectorAll('body *')) {
    const own = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
    if (own.length < 6) continue;
    const r = e.getBoundingClientRect();
    const fs = parseFloat(getComputedStyle(e).fontSize) || 16;
    if (r.height > fs * 5 && r.width < fs * 4) out.push(`「${own.slice(0, 16)}」被挤成 ${Math.round(r.width)}px 宽`);
  }
  return out;
}"""


def file_url(path):
    return "file:///" + urllib.parse.quote(os.path.abspath(path).replace("\\", "/").lstrip("/"), safe="/:")


def _browser(pw):
    last = None
    for ch in CHANNELS:
        try:
            return pw.chromium.launch(channel=ch, headless=True) if ch else pw.chromium.launch(headless=True)
        except Exception as e:  # noqa: BLE001  这台电脑没有这个浏览器，换下一个
            last = e
    raise RuntimeError(f"这台电脑上没找到能用的浏览器（Edge、Chrome 或 Playwright 自带的）：{str(last).splitlines()[0][:120] if last else ''}")


def check_pages(paths):
    """{路径: [问题, ...]}。"""
    from playwright.sync_api import sync_playwright
    out = {p: [] for p in paths}
    with sync_playwright() as pw:
        b = _browser(pw)
        try:
            for w, h in WIDTHS:
                page = b.new_page(viewport={"width": w, "height": h})
                for p in paths:
                    if not os.path.exists(p):
                        out[p].append("文件不存在")
                        continue
                    page.goto(file_url(p))
                    page.wait_for_timeout(150)
                    sw, iw = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
                    label = "手机宽" if w < 600 else "电脑宽"
                    if sw > iw:
                        out[p].append(f"{label}（{w}）整页会左右滚动：内容宽 {sw}px")
                    for x in page.evaluate(SQUEEZED)[:5]:
                        out[p].append(f"{label}（{w}）{x}")
                page.close()
        finally:
            b.close()
    return out


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not argv:
        print(__doc__)
        return 2
    try:
        res = check_pages(argv)
    except ImportError:
        print("没装 Playwright，版面检查跳过：pip install playwright")
        return 2
    except RuntimeError as e:
        print(f"版面检查跳过：{e}")
        return 2
    bad = 0
    for p, probs in res.items():
        probs = list(dict.fromkeys(probs))
        print(("OK   " if not probs else "FAIL ") + p)
        for x in probs[:20]:
            print("     - " + x)
        bad += bool(probs)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
