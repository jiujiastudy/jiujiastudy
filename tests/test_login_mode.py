"""登录模式：学校不让学生生成 token 时，用户在弹出的浏览器窗口里自己登录，之后用这份登录只读 Canvas。

要守住的：和 token 版读到的东西一样（翻页、while(1); 前缀、下载）；登录过期要说「重新登录」而不是「token 坏了」；
有登录就不带 token 发请求；登录模式不代发帖、不代交作业。

平时跑的部分不开浏览器（假的请求对象）。真浏览器那组要装了 playwright，并设 JIUJIASTUDY_BROWSER_TESTS=1：
会弹出一个浏览器窗口几秒，登录页是本机假 Canvas，自己关。
"""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")
sys.path.insert(0, TOOLS)
import cc_session  # noqa: E402
from canvas_api import CanvasAuthError  # noqa: E402

HOST = "https://canvas.example.edu"
NOW = "2026-03-24T23:00:00Z"


class FakeResponse:
    def __init__(self, status, body=b"", headers=None, url=None, status_text=""):
        self.status, self._body, self.url, self.status_text = status, body, url, status_text
        self.headers_array = [{"name": k, "value": v} for k, v in (headers or {}).items()]

    def body(self):
        return self._body


class FakeRequest:
    def __init__(self, routes):
        self.routes, self.seen = routes, []

    def get(self, url, headers=None, timeout=None, fail_on_status_code=True, max_redirects=None):
        self.seen.append((url, dict(headers or {})))
        r = self.routes[url]
        if r.url is None:
            r.url = url
        return r


class FakeContext:
    def __init__(self, routes):
        self.request = FakeRequest(routes)

    def cookies(self, urls=None):
        return []

    def close(self):
        pass


def session_api(routes):
    api = cc_session.SessionCanvas(HOST, tempfile.gettempdir(), retries=0)
    api._ctx = FakeContext(routes)  # 不起浏览器
    return api


class ReadsLikeTokenVersion(unittest.TestCase):
    def test_翻页和_while1_前缀(self):
        p1, p2 = HOST + "/api/v1/courses?per_page=1", HOST + "/api/v1/courses?page=2&per_page=1"
        api = session_api({
            p1: FakeResponse(200, b'while(1);[{"id": 1}]', {"link": f'<{p2}>; rel="next"'}),  # 名字是小写的
            p2: FakeResponse(200, b'[{"id": 2}]'),
        })
        self.assertEqual([{"id": 1}, {"id": 2}], api.get("/api/v1/courses?per_page=1"))
        headers = api._ctx.request.seen[0][1]
        self.assertEqual("application/json", headers["Accept"])
        self.assertNotIn("Authorization", headers, "登录模式不带 token")

    def test_没登录是重新登录_没权限照旧是_401(self):
        me, grades = HOST + "/api/v1/users/self", HOST + "/api/v1/courses/1/users"
        api = session_api({
            me: FakeResponse(401, b'{"status":"unauthenticated","errors":[{"message":"user authorization required"}]}'),
            grades: FakeResponse(401, b'{"status":"unauthorized","errors":[{"message":"user not authorized to perform that action"}]}'),
        })
        with self.assertRaises(CanvasAuthError) as cm:
            api.get("/api/v1/users/self")
        self.assertIn("login", str(cm.exception))
        with self.assertRaises(urllib.error.HTTPError) as cm:
            api.get("/api/v1/courses/1/users")
        self.assertEqual(401, cm.exception.code)

    def test_下载被转到登录页_不把登录页当课件存下(self):
        meta, dl = HOST + "/api/v1/files/7", HOST + "/files/7/download?verifier=x"
        api = session_api({
            meta: FakeResponse(200, json.dumps({"id": 7, "display_name": "W1.pdf", "url": dl, "size": 3}).encode()),
            dl: FakeResponse(200, b"<html>login</html>", url=HOST + "/login/saml"),
        })
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(CanvasAuthError):
                api.download(7, d)
            self.assertEqual([], os.listdir(d))


class LoginModeInCoach(unittest.TestCase):
    def setUp(self):
        self.sc = mockcanvas.Scenario("au_semester")
        self.mock = mockcanvas.MockCanvas(self.sc).start()
        self.home = harness.FakeHome("login")
        self.home.seed(self.sc, self.mock.base_url)

    def tearDown(self):
        self.home.cleanup()
        self.mock.stop()

    def coach(self, *args):
        return harness.run_coach(self.home, list(args), TOOLS, now=NOW, ports=(self.mock.port,))

    def mark_logged_in(self):
        with open(os.path.join(self.home.archive, cc_session.MARKER), "w", encoding="utf-8") as f:
            json.dump({"host": self.mock.base_url, "name": "Test Student", "user_id": 5001}, f)

    def test_有登录就不用_token(self):
        """CANVAS_TOKEN 设着，但用户跑过 login：一个带 token 的请求都不许发（这里起不了浏览器，所以一个请求都没有）。"""
        self.mark_logged_in()
        r = self.coach("collect", "--json", "--date", "2026-03-24")
        self.assertNotEqual(0, r.code)
        self.assertEqual([], self.mock.requests())

    def test_登录模式不代发(self):
        self.mark_logged_in()
        r = self.coach("api", "post", "/api/v1/conversations", '{"body": "hi"}', "--json")
        self.assertEqual(2, r.code, r.stdout + r.stderr)
        self.assertIn("只能读", r.stdout + r.stderr)
        self.assertEqual([], self.mock.requests())

    def test_check_和_forget(self):
        r = self.coach("login", "--check", "--json")
        self.assertEqual("none", r.json()["state"])
        self.mark_logged_in()
        os.makedirs(os.path.join(self.home.archive, cc_session.PROFILE), exist_ok=True)
        r = self.coach("login", "--forget", "--json")
        self.assertTrue(r.json()["forgotten"])
        self.assertFalse(os.path.exists(os.path.join(self.home.archive, cc_session.MARKER)))
        self.assertFalse(os.path.exists(os.path.join(self.home.archive, cc_session.PROFILE)))
        self.assertEqual(0, self.coach("collect", "--json", "--date", "2026-03-24").code, "删掉登录就回到 token")


class ExpiredSessionCollect(unittest.TestCase):
    """Canvas 登录模式下会话过期时 collect 不往外抛（radar --fetch 还要用上次的快照把 deadline 列出来），
    只写 last_failure.json，并把「重新登录」那句原话记进 errors。只有 Moodle 才把它抛出去。"""

    class Expired:
        def get(self, path, max_pages=None):
            raise CanvasAuthError(cc_session.RELOGIN)

    def test_会话过期_collect_记错误不抛(self):
        import cc_collect
        import cc_config
        sc = mockcanvas.Scenario("au_semester")
        home = harness.FakeHome("login-expired")
        try:
            home.seed(sc, HOST)
            ctx = cc_config.Ctx(home.archive, quiet=True)
            ctx._api = self.Expired()
            d = cc_collect.collect(ctx, "2026-03-24", quick=True)
            self.assertFalse(d["promoted"])
            self.assertEqual(1, d["errors"].count(cc_session.RELOGIN), "「重新登录」的原话要原样记下来，而且只记一次")
            self.assertTrue(os.path.isfile(d["failure_path"]))
        finally:
            home.cleanup()


def _browser_tests_on():
    if os.environ.get("JIUJIASTUDY_BROWSER_TESTS") != "1":
        return False
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


@unittest.skipUnless(_browser_tests_on(), "真浏览器测试：装 playwright 并设 JIUJIASTUDY_BROWSER_TESTS=1")
class RealBrowser(unittest.TestCase):
    def test_登录_读_下载_换进程_过期_重登(self):
        with mockcanvas.MockCanvas("au_semester", session=True) as mock, \
                tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as home:
            base = mock.base_url
            r = cc_session.start_login(home, base, wait=60)
            self.assertEqual("done", r["state"], r)
            self.assertEqual(1, mock.logins)

            api = cc_session.SessionCanvas(base, home)
            self.assertEqual("Test Student", api.get("/api/v1/users/self")["name"])
            self.assertEqual(len(mock.scenario.courses), len(api.get("/api/v1/courses?per_page=1")))  # 一页一门，靠翻页拿齐
            f = next(f for c in mock.scenario.course.values() for f in c["files"] if not f.get("locked_for_user"))
            with tempfile.TemporaryDirectory() as d:
                got = api.download(f["id"], d)
                with open(got["saved"], encoding="utf-8") as fh:
                    self.assertEqual(f.get("_body") or "", fh.read())
            api.close()

            api = cc_session.SessionCanvas(base, home)  # 新进程、新浏览器：会话 cookie 要靠我们自己存的那份
            self.assertEqual("Test Student", api.get("/api/v1/users/self")["name"])
            api.close()
            self.assertEqual(1, mock.logins, "没过期就不该再登录")

            mock.expire_session()
            api = cc_session.SessionCanvas(base, home)
            with self.assertRaises(CanvasAuthError):
                api.get("/api/v1/users/self")
            api.close()

            self.assertEqual("done", cc_session.start_login(home, base, wait=60)["state"])
            self.assertEqual(2, mock.logins)
            self.assertEqual("ok", cc_session.check(home)["state"])
            self.assertTrue(cc_session.forget(home))
            self.assertFalse(cc_session.has_login(home))


if __name__ == "__main__":
    unittest.main()
