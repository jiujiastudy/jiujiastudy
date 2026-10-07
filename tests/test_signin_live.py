"""学生最多输一次（10-07 发起人：「让用户最多输入一次，后面就尽量不要再输入了」）。

对着本机假的学校统一登录（tests/mocksso.py）在真浏览器里（不开窗口）跑：
- 登一次以后，换一个新开的浏览器照样进得去：学校登录和网站登录都是会话 cookie，靠救驾自己存的那份；
- 一次管全校：走同一个学校登录的别的网站不用再输；
- 网站自己的登录过期、学校还记得：后台自己进；学校也忘了，才要学生再登；
- 登录窗口（browse --sign-in 起的）登好就存下全部登录记录、自己关；
- 浏览器登录方式的 Canvas 过期：先在后台走一遍学校登录，学校还记得就接着读，学生什么都不用做。
没有浏览器就跳过。存取登录记录的规矩（不盖掉浏览器自己记着的新记录、坏的一条不连累别的）不用浏览器，照常测。
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402
import mocksso  # noqa: E402

sys.path.insert(0, os.path.join(harness.code_dir(), "tools"))
import cc_external  # noqa: E402
import cc_session  # noqa: E402
from canvas_api import CanvasAuthError  # noqa: E402


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


def student_signs_in(home, start_url, keep=False):
    """代表学生在登录窗口里登一次（测试里替学生填假的 UniKey 和密码）：打开网址 → 学校登录页 → 填表 → 回到网站。
    窗口关之前存下全部登录记录（和真的登录窗口一样）。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = cc_session._launch(pw, home, headless=True)
        try:
            cc_session._restore_cookies(ctx, home)
            page = ctx.new_page()
            page.goto(start_url, wait_until="domcontentloaded")
            page.fill("input[name=username]", mocksso.USER)
            page.fill("input[name=password]", mocksso.PASSWORD)
            if keep:
                page.check("input[name=rememberMe]")
            page.click("button[type=submit]")
            page.wait_for_load_state("networkidle")
            cc_session._save_cookies(ctx, home)
        finally:
            ctx.close()


@unittest.skipUnless(HAVE, "这台电脑开不了浏览器")
class TypeOnce(unittest.TestCase):
    def setUp(self):
        self.sso = mocksso.MockSSO().start()
        self.home = tempfile.mkdtemp(prefix="stc-sso-")

    def tearDown(self):
        cc_session.close_all()
        self.sso.stop()
        shutil.rmtree(self.home, ignore_errors=True)

    def read(self, name, path="/timetable"):
        return cc_external.browse(self.home, self.sso.url(name, path), wait=20)

    def test_登一次_以后新开的浏览器也不用再登(self):
        self.assertEqual("login", self.read("site")["result"], "还没登过：被带去学校登录页")
        student_signs_in(self.home, self.sso.url("site", "/timetable"))
        r = self.read("site")
        self.assertEqual("ok", r["result"], r)
        with open(r["path"], encoding="utf-8") as f:
            self.assertIn("Tuesday 4 pm MECO6941", f.read())
        self.assertEqual(1, self.sso.form_logins)

    def test_对照_不存这份就要再登(self):
        student_signs_in(self.home, self.sso.url("site", "/timetable"))
        os.remove(os.path.join(cc_session.profile_dir(self.home), cc_session.COOKIES))
        self.assertEqual("login", self.read("site")["result"], "会话 cookie 浏览器一关就丢：靠的就是存下的这份")

    def test_一次管全校(self):
        student_signs_in(self.home, self.sso.url("site", "/timetable"))
        r = self.read("site2", "/recordings")
        self.assertEqual("ok", r["result"], r)
        self.assertEqual(1, self.sso.form_logins, "走同一个学校登录的别的网站，不用再输")
        self.assertGreaterEqual(self.sso.silent, 1)

    def test_网站过期_学校还记得_后台自己进(self):
        student_signs_in(self.home, self.sso.url("site", "/timetable"))
        self.sso.expire_site("site")
        self.assertEqual("ok", self.read("site")["result"])
        self.assertEqual(1, self.sso.form_logins)

    def test_学校也忘了_才要学生再登(self):
        student_signs_in(self.home, self.sso.url("site", "/timetable"))
        self.sso.expire_site("site")
        self.sso.expire_idp()
        self.assertEqual("login", self.read("site")["result"])

    def test_勾了保持登录的也照样存照样用(self):
        student_signs_in(self.home, self.sso.url("site", "/timetable"), keep=True)
        self.sso.expire_site("site")
        self.assertEqual("ok", self.read("site")["result"])
        self.assertEqual(1, self.sso.form_logins)

    def test_登录窗口_登好自己关_存下学校登录(self):
        self.sso.auto_accept = True  # 当学生在窗口里登好了
        rc = cc_session.signin_worker(self.home, self.sso.url("site", "/timetable"), timeout=60, headless=True)
        self.assertEqual(0, rc)
        with open(os.path.join(self.home, cc_session.SIGNIN), encoding="utf-8") as f:
            self.assertEqual("done", json.load(f)["state"])
        self.sso.auto_accept = False
        self.assertEqual("ok", self.read("site2", "/recordings")["result"], "窗口里那一次登录，别的网站也用得上")
        self.assertEqual(1, self.sso.form_logins)

    def test_登录窗口_等不到就超时(self):
        rc = cc_session.signin_worker(self.home, self.sso.url("site", "/timetable"), timeout=3, headless=True)
        self.assertEqual(1, rc)
        with open(os.path.join(self.home, cc_session.SIGNIN), encoding="utf-8") as f:
            self.assertEqual("timeout", json.load(f)["state"])
        self.assertEqual(0, self.sso.form_logins, "没人填表：不替学生登")


@unittest.skipUnless(HAVE, "这台电脑开不了浏览器")
class CanvasRelogin(unittest.TestCase):
    def test_浏览器登录方式_Canvas过期_后台自己重进(self):
        home = tempfile.mkdtemp(prefix="stc-ssocv-")
        try:
            with mocksso.MockSSO() as sso, mockcanvas.MockCanvas("au_semester", session=True, sso=sso) as mock:
                student_signs_in(home, mock.base_url + "/login")  # 学生在登录窗口里登 Canvas：走学校登录
                self.assertEqual((1, 1), (mock.logins, sso.form_logins))

                mock.expire_session()  # Canvas 的会话过期了，学校的还在
                api = cc_session.SessionCanvas(mock.base_url, home)
                self.assertEqual("Test Student", api.get("/api/v1/users/self")["name"])
                api.close()
                self.assertEqual((2, 1), (mock.logins, sso.form_logins), "后台自己重进了一次，学生没再输")

                api = cc_session.SessionCanvas(mock.base_url, home)  # 再开一次：用的是刚才存下的新会话
                self.assertEqual("Test Student", api.get("/api/v1/users/self")["name"])
                api.close()
                self.assertEqual(2, mock.logins)

                mock.expire_session()
                sso.expire_idp()  # 学校也要重新输密码了：这时才报「重新登录」
                api = cc_session.SessionCanvas(mock.base_url, home)
                t0 = time.time()
                with self.assertRaises(CanvasAuthError):
                    api.get("/api/v1/users/self")
                api.close()
                self.assertLess(time.time() - t0, 15, "碰到要输密码的页面就停，不干等")
                self.assertEqual(1, sso.form_logins)
        finally:
            cc_session.close_all()
            shutil.rmtree(home, ignore_errors=True)


def _browser_tests_on():
    if os.environ.get("JIUJIASTUDY_BROWSER_TESTS") != "1":
        return False
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


@unittest.skipUnless(_browser_tests_on(), "真窗口测试：装 playwright 并设 JIUJIASTUDY_BROWSER_TESTS=1（会弹出几秒浏览器窗口）")
class RealWindow(unittest.TestCase):
    def test_browse_sign_in_弹窗_登好_接着读(self):
        import argparse
        import coach
        home = harness.FakeHome("signin")
        try:
            with mocksso.MockSSO() as sso, mockcanvas.MockCanvas("au_semester") as mock:
                home.seed(mock.scenario, mock.base_url)
                sso.auto_accept = True  # 当学生在弹出的窗口里登好了
                args = argparse.Namespace(home=home.archive, url=sso.url("site", "/timetable"), course=None, wait=20,
                                          sign_in=True, json=True, date=None)
                code, r = coach.cmd_browse(args)
                self.assertEqual((0, "ok"), (code, r["result"]), r)
                self.assertEqual(1, sso.form_logins)
                sso.auto_accept = False
                args.url, args.sign_in = sso.url("site2", "/recordings"), False
                self.assertEqual("ok", coach.cmd_browse(args)[1]["result"], "以后别的网站不用再登")
                self.assertEqual(1, sso.form_logins)
        finally:
            cc_session.close_all()
            home.cleanup()


class FakeCtx:
    def __init__(self, have=()):
        self.jar = list(have)

    def cookies(self, urls=None):
        return list(self.jar)

    def add_cookies(self, cs):
        if any(c["name"] == "bad" for c in cs):
            raise ValueError("Invalid cookie fields")
        self.jar += cs


def ck(name, value, domain, expires=-1):
    return {"name": name, "value": value, "domain": domain, "path": "/", "expires": expires,
            "httpOnly": True, "secure": False, "sameSite": "Lax"}


class Store(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="stc-ck-")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def saved(self):
        with open(os.path.join(cc_session.profile_dir(self.home), cc_session.COOKIES), encoding="utf-8") as f:
            return json.load(f)

    def test_存全部网站_过期的不存(self):
        os.makedirs(cc_session.profile_dir(self.home), exist_ok=True)
        cc_session._save_cookies(FakeCtx([ck("canvas_session", "a", "canvas.example.edu"), ck("idp_sid", "b", "sso.example.edu"),
                                          ck("old", "c", "x.example", expires=time.time() - 60)]), self.home)
        self.assertEqual({"canvas_session", "idp_sid"}, {c["name"] for c in self.saved()})

    def test_放回时不盖掉浏览器自己记着的新记录(self):
        os.makedirs(cc_session.profile_dir(self.home), exist_ok=True)
        cc_session._save_cookies(FakeCtx([ck("idp_keep", "old", "sso.example.edu", expires=time.time() + 3600),
                                          ck("idp_sid", "s", "sso.example.edu")]), self.home)
        ctx = FakeCtx([ck("idp_keep", "new", "sso.example.edu", expires=time.time() + 7200)])
        cc_session._restore_cookies(ctx, self.home)
        got = {c["name"]: c["value"] for c in ctx.jar}
        self.assertEqual({"idp_keep": "new", "idp_sid": "s"}, got)

    def test_坏的一条不连累别的(self):
        os.makedirs(cc_session.profile_dir(self.home), exist_ok=True)
        cc_session._save_cookies(FakeCtx([ck("bad", "x", "a.example"), ck("idp_sid", "s", "sso.example.edu")]), self.home)
        ctx = FakeCtx()
        cc_session._restore_cookies(ctx, self.home)
        self.assertEqual(["idp_sid"], [c["name"] for c in ctx.jar])


class SignedIn(unittest.TestCase):
    class P:
        def __init__(self, url, inputs=()):
            self.url, self.inputs = url, inputs

        def query_selector_all(self, sel):
            return [type("El", (), {"is_visible": lambda self: True})() for _ in self.inputs]

    def test_在网站上没有登录框才算登好(self):
        t = cc_session._site_host("https://www.timetable.example.edu/even/student")
        self.assertTrue(cc_session._signed_in_on(self.P("https://timetable.example.edu/even/student"), t))
        self.assertFalse(cc_session._signed_in_on(self.P("https://sso.example.edu/app/x/sso/saml"), t), "还在学校登录页")
        self.assertFalse(cc_session._signed_in_on(self.P("https://timetable.example.edu/login"), t))
        self.assertFalse(cc_session._signed_in_on(self.P("https://timetable.example.edu/even/student", inputs=[1]), t), "页面上还有登录框")


if __name__ == "__main__":
    unittest.main()
