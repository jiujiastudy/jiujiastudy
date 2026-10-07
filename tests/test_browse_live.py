"""browse 在真浏览器里（不开窗口）：本校 Canvas 上的网址先换免登录的打开链接再开，token 和浏览器登录读到的一样——
嵌的外部工具走 sessionless_launch；Canvas 自己的页面，token 方式走 session_token，浏览器登录方式本来就带着会话。
打开链接是一次性的登录凭证：不落盘、不交出去。页面上折叠着的内容也读进来。没有浏览器就跳过。

10-07：用 token 的档案读不到 Canvas 里的 Zoom、阅读清单和 Canvas 自己的课程页面（都被带去登录页）；
换成这两种打开链接，实测 Zoom 会议列表、Leganto 阅读清单、MECO6941 的课程页面都读到了。
课程说明的评估表折叠着，以前只读看得见的字，整段漏掉。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

sys.path.insert(0, os.path.join(harness.code_dir(), "tools"))
import canvas_api  # noqa: E402
import cc_external  # noqa: E402
import cc_session  # noqa: E402


def browser_ok():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            for ch in cc_session.CHANNELS:
                try:
                    b = pw.chromium.launch(channel=ch, headless=True) if ch else pw.chromium.launch(headless=True)
                    b.close()
                    return True
                except Exception:  # noqa: BLE001
                    continue
    except Exception:  # noqa: BLE001
        return False
    return False


HAVE = browser_ok()


def logged_in(home, mock):
    """代表「学生在登录窗口里登好了」：浏览器资料夹里存着会话 cookie。"""
    prof = cc_session.profile_dir(home)
    os.makedirs(prof, exist_ok=True)
    host = urllib.parse.urlparse(mock.base_url).hostname
    with open(os.path.join(prof, cc_session.COOKIES), "w", encoding="utf-8") as f:
        json.dump([{"name": "canvas_session", "value": mock.session_cookie, "domain": host, "path": "/",
                    "expires": -1, "httpOnly": True, "secure": False, "sameSite": "Lax"}], f)
    return cc_session.SessionCanvas(mock.base_url, home)


@unittest.skipUnless(HAVE, "这台电脑开不了浏览器")
class BothWays(unittest.TestCase):
    """同一个网址，token 和浏览器登录两种方式都要读到同样的内容。"""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="stc-open-")

    def tearDown(self):
        cc_session.close_all()
        shutil.rmtree(self.home, ignore_errors=True)

    def read(self, api, url, base, secret, want):
        open_url, note = cc_external.open_link(api, url, base)
        self.assertIsNone(note)
        cc_session.close_all()  # 浏览器登录方式拿链接用的是同一份资料夹：先放开
        r = cc_external.browse(self.home, url, wait=20, open_url=open_url)
        self.assertEqual("ok", r["result"], r)
        with open(r["path"], encoding="utf-8") as f:
            saved = f.read()
        self.assertIn(want, saved)
        self.assertTrue(saved.startswith(f"网址：{url}\n"), "记录按原来的网址存")
        self.assertNotIn(secret, saved, "一次性链接是登录凭证，不能落盘")
        self.assertNotIn(secret, r["final_url"])
        self.assertFalse([h for h, _ in r["links"] if secret in h], "页面回显凭证的链接不交出去")
        return r

    def tool(self, mock, api):
        url = f"{mock.base_url}/courses/{mock.scenario.courses[0]['id']}/external_tools/11159"
        r = self.read(api, url, mock.base_url, "mock-verifier", "Upcoming Meetings")
        self.assertIn("https://zoom.example/recordings/week9", [h for h, _ in r["links"]])

    def page(self, mock, api):
        url = f"{mock.base_url}/courses/{mock.scenario.courses[0]['id']}/pages/week-9-audio-effects"
        self.read(api, url, mock.base_url, "mock-session-token", "set up the audio effects")

    def test_token方式_嵌的工具(self):
        with mockcanvas.MockCanvas("au_semester") as mock:
            self.tool(mock, canvas_api.Canvas(mock.base_url, mock.scenario.token))

    def test_token方式_Canvas自己的页面(self):
        with mockcanvas.MockCanvas("au_semester") as mock:
            self.page(mock, canvas_api.Canvas(mock.base_url, mock.scenario.token))

    def test_token方式_不换会话会被带去登录页(self):
        with mockcanvas.MockCanvas("au_semester") as mock:
            url = f"{mock.base_url}/courses/{mock.scenario.courses[0]['id']}/pages/week-9-audio-effects"
            self.assertEqual("login", cc_external.browse(self.home, url, wait=20)["result"], "对照：以前就是这样读不到")

    def test_浏览器登录方式_嵌的工具(self):
        with mockcanvas.MockCanvas("au_semester", session=True) as mock:
            self.tool(mock, logged_in(self.home, mock))

    def test_浏览器登录方式_Canvas自己的页面(self):
        with mockcanvas.MockCanvas("au_semester", session=True) as mock:
            api = logged_in(self.home, mock)
            self.assertEqual((None, None), cc_external.open_link(api, f"{mock.base_url}/courses/1/pages/x", mock.base_url),
                             "浏览器登录方式本来就带着会话，不用换")
            self.page(mock, api)


@unittest.skipUnless(HAVE, "这台电脑开不了浏览器")
class Collapsed(unittest.TestCase):
    def test_折叠着的内容也读进来(self):
        d = tempfile.mkdtemp(prefix="stc-fold-")
        try:
            page = os.path.join(d, "outline.html")
            rows = "".join(f"<tr><td>Assessment {i}</td><td>Due week {i + 8}</td><td>Hurdle task: yes</td></tr>" for i in range(1, 9))
            with open(page, "w", encoding="utf-8") as f:
                f.write("<!doctype html><title>Unit outline</title><h1>MECO6941</h1><p>Overview of the unit.</p>"
                        f"<details><summary>Assessment summary</summary><table>{rows}</table></details>")
            url = "file:///" + urllib.parse.quote(page.replace("\\", "/"), safe="/:")
            r = cc_external.browse(d, url, wait=20)
            self.assertEqual("ok", r["result"], r)
            with open(r["path"], encoding="utf-8") as f:
                self.assertIn("Hurdle task: yes", f.read())
        finally:
            cc_session.close_all()
            shutil.rmtree(d, ignore_errors=True)


class FakeApi:
    def __init__(self, mode=None, fail=False):
        self.host, self.mode, self.fail, self.calls = "https://canvas.example.edu", mode, fail, []

    def get(self, path):
        self.calls.append(("get", path))
        if self.fail:
            raise RuntimeError("boom")
        return {"url": "https://canvas.example.edu/lti?verifier=v"}

    def fetch(self, url):
        self.calls.append(("fetch", url))
        return {}, b'{"session_url": "https://canvas.example.edu/courses/7/pages/a?session_token=s"}'


class OpenLink(unittest.TestCase):
    HOST = "https://canvas.example.edu"

    def test_嵌的工具两种方式都走sessionless_launch(self):
        for mode in (None, "session"):
            api = FakeApi(mode)
            got, note = cc_external.open_link(api, self.HOST + "/courses/7/external_tools/11159?display=borderless", self.HOST)
            self.assertEqual("https://canvas.example.edu/lti?verifier=v", got)
            self.assertEqual([("get", "/api/v1/courses/7/external_tools/sessionless_launch?id=11159")], api.calls)

    def test_Canvas自己的页面_token方式换会话(self):
        api = FakeApi()
        got, _ = cc_external.open_link(api, self.HOST + "/courses/7/pages/a", self.HOST)
        self.assertTrue(got.endswith("session_token=s"))
        self.assertEqual("fetch", api.calls[0][0])
        q = urllib.parse.parse_qs(urllib.parse.urlparse(api.calls[0][1]).query)
        self.assertEqual([self.HOST + "/courses/7/pages/a"], q["return_to"])

    def test_Canvas自己的页面_浏览器登录方式不用换(self):
        api = FakeApi("session")
        self.assertEqual((None, None), cc_external.open_link(api, self.HOST + "/courses/7/pages/a", self.HOST))
        self.assertEqual([], api.calls)

    def test_别的网站不换(self):
        api = FakeApi()
        self.assertEqual((None, None), cc_external.open_link(api, "https://padlet.com/sydney/board", self.HOST))
        self.assertIsNone(cc_external.lti_launch_path("https://other.example/courses/1/external_tools/2", self.HOST))
        self.assertEqual([], api.calls)

    def test_模块条目要知道是外部工具才走sessionless_launch(self):
        url = self.HOST + "/courses/1/modules/items/9"
        self.assertIsNone(cc_external.lti_launch_path(url, self.HOST))
        self.assertIn("launch_type=module_item&module_item_id=9", cc_external.lti_launch_path(url, self.HOST, lti=True))

    def test_报错原话里的凭证也去掉(self):
        open_url = self.HOST + "/courses/7/pages/a?session_token=s3cr3t-token"
        msg = f"Page.goto: net::ERR_CONNECTION_RESET at {open_url}"
        self.assertNotIn("s3cr3t-token", cc_external.scrub(msg, open_url))
        self.assertEqual("没有打开链接就原样", cc_external.scrub("没有打开链接就原样", None))

    def test_换不到就照原网址开_说一句原因(self):
        got, note = cc_external.open_link(FakeApi(fail=True), self.HOST + "/courses/7/external_tools/1", self.HOST)
        self.assertIsNone(got)
        self.assertIn("RuntimeError", note)
        self.assertNotIn("verifier", note)


class Entries(unittest.TestCase):
    def test_本校Canvas里的外部工具链接带上lti(self):
        acc = cc_external._Links("https://canvas.example.edu")
        acc.add("https://canvas.example.edu/courses/7/external_tools/11159", "here", "公告「Zoom」", near=("the Zoom tab on Canvas", ""))
        acc.add("https://padlet.com/sydney/board-abc", "Padlet board", "模块「Padlets」")
        got = {x["url"]: x for x in acc.out}
        self.assertTrue(got["https://canvas.example.edu/courses/7/external_tools/11159"].get("lti"))
        self.assertNotIn("lti", got["https://padlet.com/sydney/board-abc"])


if __name__ == "__main__":
    unittest.main()
