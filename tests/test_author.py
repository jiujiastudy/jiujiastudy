"""作者脚注：一句话 + 账号名 + 隐藏按钮；二维码只在「问题反馈」里。

红线：不连外网（二维码是内嵌的本地图）、没有统计、没给链接就不编链接、
同一张图在一页里只存一份、脚注藏起来之后反馈入口照样能用。
"""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

CODE = harness.code_dir()
sys.path.insert(0, os.path.join(CODE, "tools"))
import cc_author  # noqa: E402
import design  # noqa: E402
import render_week  # noqa: E402
import style_check  # noqa: E402


def page():
    return render_week.render({"week": "2026-W13", "title": "第 7 周", "range": "x",
                               "generated": "2026-03-25", "sources": [{"label": "快照", "ref": "raw/x.json"}]})


class Assets(unittest.TestCase):
    def test_两张二维码都在(self):
        missing = [a["file"] for a in cc_author.ACCOUNTS
                   if not os.path.isfile(os.path.join(cc_author.assets_dir(), a["file"]))]
        self.assertEqual([], missing, "assets/ 里缺二维码原图")

    def test_缺图就只出文字_不画假码(self):
        real = cc_author.assets_dir
        cc_author.assets_dir = lambda: os.path.join(CODE, "assets", "并不存在")
        try:
            accs = cc_author.accounts()
            self.assertTrue(all(a["uri"] is None for a in accs))
            html = cc_author.feedback_html(accs)
            self.assertIn("小红书 · @", html)
            self.assertNotIn("data:image", html)
            self.assertNotIn("<span class=\"qr", html)
        finally:
            cc_author.assets_dir = real


class Footer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = page()

    def test_排在资料来源之后(self):
        self.assertLess(self.html.index("资料来源"), self.html.index("data-author"))

    def test_那句话一字不差(self):
        self.assertIn("大家都离家这么远了，能帮上彼此一点，就帮一点。", self.html)

    def test_两个平台标注都在(self):
        for a in cc_author.ACCOUNTS:
            self.assertIn(f'{a["platform"]} · @{a["handle"]}', self.html)

    def test_底部不再摆二维码_只留账号名(self):
        seg = self.html[self.html.index("data-author"):]
        self.assertNotIn('class="qr', seg, "二维码已经在「问题反馈」里，底部不该再摆一遍")
        for a in cc_author.ACCOUNTS:
            self.assertIn(a["platform"], seg)
            self.assertIn("@" + a["handle"], seg)

    def test_没给链接就不编链接(self):
        seg = self.html[self.html.index("data-author"):]
        self.assertNotIn("<a ", seg, "作者没给主页链接，不许自己编一个")

    def test_不连外网_不做统计(self):
        seg = self.html[self.html.index("data-author"):]
        for bad in ("http://", "https://", "utm_", "track", "pixel"):
            self.assertNotIn(bad, seg)

    def test_同一张图只存一份(self):
        for a in cc_author.accounts():
            if a["uri"]:
                self.assertEqual(1, self.html.count(a["uri"]), f'{a["platform"]} 的二维码存了不止一份')

    def test_隐藏按钮和恢复入口都在(self):
        self.assertIn("data-hide-author", self.html)
        self.assertIn("data-show-author", self.html)
        self.assertIn("隐藏作者信息", self.html)
        for k in ("[data-author]", "hideAuthor"):
            self.assertIn(k, design.CORE_JS)

    def test_反馈入口独立于脚注(self):
        fb = self.html[self.html.index("问题反馈"):self.html.index("data-author")]
        self.assertIn("使用问题或建议，可以通过小红书或抖音私信我。", fb)
        for a in cc_author.accounts():  # 藏了脚注也要能找到人，所以这里带上号和二维码
            self.assertIn(a["id"], fb)
            if a["uri"]:
                self.assertIn(f'class="qr qr-{a["key"]}"', fb)

    def test_二维码尺寸够大(self):
        self.assertIn("width:132px;height:132px", cc_author.css())

    def test_还是过风格检查(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "week.html")
            io.open(p, "w", encoding="utf-8", newline="\n").write(self.html)
            self.assertEqual([], style_check.check(p))


if __name__ == "__main__":
    unittest.main()
