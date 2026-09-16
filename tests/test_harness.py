"""Checks on the test tools themselves: the mock behaves like Canvas where it matters, fixtures stay
synthetic, and the runner really isolates the tool (fake home, no network but the mock, no child processes)."""
import glob
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class MockCanvasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = mockcanvas.MockCanvas("us_quarter").start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def get(self, path, token="dummy"):
        url = path if path.startswith("http") else self.mock.base_url + path
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
        with NO_PROXY.open(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8")), r.headers

    def get_all(self, path):
        items, url = [], path
        while url:
            page, headers = self.get(url)
            items += page
            url = next((p.split(";")[0].strip()[1:-1] for p in (headers.get("Link") or "").split(",")
                        if 'rel="next"' in p), None)
        return items

    def test_requires_bearer_token(self):
        for token in (None, "wrong"):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.get("/api/v1/users/self", token=token)
            self.assertEqual(401, cm.exception.code)

    def test_link_header_paging_caps_per_page(self):
        first, headers = self.get("/api/v1/courses/2201/assignments?per_page=100&include[]=submission")
        self.assertEqual(10, len(first))
        self.assertIn('rel="next"', headers["Link"])
        every = self.get_all("/api/v1/courses/2201/assignments?per_page=100&include[]=submission")
        self.assertEqual(12, len(every))
        self.assertTrue(all("submission" in a for a in every))
        self.assertTrue(all(a["due_at"] is None or a["due_at"].endswith("Z") for a in every))

    def test_large_modules_come_without_inline_items(self):
        mods = self.get_all("/api/v1/courses/2201/modules?per_page=50&include[]=items&include[]=content_details")
        big = next(m for m in mods if m["name"] == "Series and Convergence")
        self.assertNotIn("items", big)
        self.assertEqual(8, big["items_count"])
        items = self.get_all(big["items_url"] + "?include[]=content_details")
        self.assertEqual(8, len(items))
        self.assertTrue(all("content_details" in it for it in items if it["type"] != "SubHeader"))

    def test_announcements_follow_start_date(self):
        q = "/api/v1/announcements?context_codes[]=course_2203&per_page=50&start_date="
        self.assertEqual(["Office hours moved"], [a["title"] for a in self.get_all(q + "2026-02-10")])
        self.assertEqual([], self.get_all(q + "2026-02-11"))

    def test_download_url_points_at_the_mock(self):
        files, _ = self.get("/api/v1/courses/2201/files?per_page=100")
        meta, _ = self.get(f"/api/v1/files/{files[0]['id']}")
        self.assertTrue(meta["url"].startswith(self.mock.base_url + "/files/"))
        with NO_PROXY.open(meta["url"], timeout=10) as r:
            self.assertIn(b"Synthetic course file", r.read())

    def test_writes_are_refused(self):
        req = urllib.request.Request(self.mock.base_url + "/api/v1/conversations", data=b"{}", method="POST",
                                     headers={"Authorization": "Bearer dummy", "Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            NO_PROXY.open(req, timeout=10)
        self.assertEqual(405, cm.exception.code)

    def test_binds_loopback_only(self):
        with self.assertRaises(ValueError):
            mockcanvas.MockCanvas("us_quarter", host="0.0.0.0")


class FixtureHygieneTest(unittest.TestCase):
    ISO = re.compile(r'"(\d{4}-\d{2}-\d{2}T[^"]*)"')
    URL = re.compile(r'https?://[^"\s<>]+')

    def test_timestamps_are_utc_z_and_hosts_are_fake(self):
        for path in glob.glob(os.path.join(harness.FIXTURES, "*", "**", "*.json"), recursive=True):
            with open(path, encoding="utf-8") as f:
                raw = f.read()
            with self.subTest(file=os.path.relpath(path, harness.FIXTURES)):
                self.assertEqual([], [t for t in self.ISO.findall(raw) if not t.endswith("Z")])
                hosts = {re.split(r"[/:?]", u.split("://", 1)[1])[0] for u in self.URL.findall(raw)}
                self.assertEqual(set(), {h for h in hosts if not h.endswith(".example")})

    def test_every_scenario_has_its_files(self):
        for name in harness.SCENARIOS:
            sc = mockcanvas.Scenario(name)
            with self.subTest(scenario=name):
                self.assertEqual(3, sc.meta["state"]["schema_version"])
                self.assertGreaterEqual(len(sc.meta["config"]["courses"]), 3)
                ids = {c["id"] for c in sc.courses}
                self.assertTrue({c["id"] for c in sc.meta["config"]["courses"]} <= ids)


PROBE = r'''
import os, socket, subprocess, sys, zoneinfo
allowed, other = int(os.environ["PROBE_ALLOWED"]), int(os.environ["PROBE_OTHER"])
out = []


def attempt(label, fn):
    try:
        fn()
        out.append(label + ":open")
    except OSError as e:
        out.append(label + ":" + ("blocked" if "harness" in str(e) else "other"))


def connect(host, port, ex=False):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        if ex:
            if s.connect_ex((host, port)):
                raise OSError("connect_ex failed")
        else:
            s.connect((host, port))
    finally:
        s.close()


# Every target is on this computer: nothing could leave it even if the runner's guard were broken.
attempt("mock", lambda: connect("127.0.0.1", allowed))              # the allowed port goes through
attempt("port", lambda: connect("127.0.0.1", other))                # a listening port the runner did not allow
attempt("port_ex", lambda: connect("127.0.0.1", other, ex=True))
attempt("host", lambda: connect("127.0.0.2", allowed))              # the allowed port on another address
# A numeric host with AI_NUMERICHOST never asks a DNS server, guard or not; the runner must refuse it anyway.
attempt("dns", lambda: socket.getaddrinfo("192.0.2.1", 443, flags=socket.AI_NUMERICHOST))
out.append("dnshook:" + ("installed" if socket.getaddrinfo.__module__ != "socket" else "missing"))
attempt("proc", lambda: subprocess.run([sys.executable, "-c", "pass"]))
print(" ".join(out))
if sys.platform == "win32":
    import winreg
    try:  # a value name nobody has: a real registry answers "not found" without the harness's words
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            winreg.QueryValueEx(k, "STC_PROBE_NO_SUCH_VALUE")
        print("registry=open")
    except OSError as e:
        print("registry=" + ("hidden" if "harness" in str(e) else "real"))
else:
    print("registry=n/a")
print("home=" + os.path.expanduser("~"))
print("token=" + os.environ.get("CANVAS_TOKEN", ""))
print("tzpath=" + os.pathsep.join(zoneinfo.TZPATH))
print("zone=" + str(zoneinfo.ZoneInfo("Australia/Sydney")))
'''


class RunnerIsolationTest(unittest.TestCase):
    def run_probe(self, **extra_env):
        """Run PROBE as coach.py. Two local listening ports: one allowed (like the mock), one not."""
        tools = tempfile.mkdtemp(prefix="stc-probe-", dir=os.environ.get("STC_TEST_TMP") or None)
        home = harness.FakeHome("probe")
        listeners = [socket.create_server(("127.0.0.1", 0)) for _ in range(2)]
        try:
            allowed, other = (s.getsockname()[1] for s in listeners)
            with open(os.path.join(tools, "coach.py"), "w", encoding="utf-8") as f:
                f.write(PROBE)
            env = dict(extra_env, PROBE_ALLOWED=str(allowed), PROBE_OTHER=str(other))
            r = harness.run_coach(home, [], tools, ports=(allowed,), extra_env=env)
            self.assertEqual(0, r.code, r.stderr)
            return home, dict(l.split("=", 1) if "=" in l else ("checks", l) for l in r.stdout.splitlines())
        finally:
            for s in listeners:
                s.close()
            home.cleanup()
            shutil.rmtree(tools, ignore_errors=True)

    def test_runner_blocks_network_dns_and_processes(self):
        home, lines = self.run_probe()
        self.assertEqual("mock:open port:blocked port_ex:blocked host:blocked dns:blocked dnshook:installed proc:blocked",
                         lines["checks"])
        self.assertEqual(os.path.normcase(home.user), os.path.normcase(lines["home"]))
        self.assertEqual("dummy", lines["token"])
        self.assertEqual(os.path.normcase(harness.TZDATA), os.path.normcase(lines["tzpath"]))
        self.assertEqual("Australia/Sydney", lines["zone"])

    def test_no_token_means_no_registry(self):
        # With CANVAS_TOKEN unset the tool looks for a saved token; on Windows it must not find this computer's.
        _, lines = self.run_probe(CANVAS_TOKEN=None)
        self.assertEqual("", lines["token"])
        self.assertEqual("hidden" if sys.platform == "win32" else "n/a", lines["registry"])

    def test_masker(self):
        home = harness.FakeHome("mask")
        try:
            m = harness.Masker(home, harness.REPO, "http://127.0.0.1:5555", "2026-03-24T23:00:00Z")
            s = m.text(os.path.join(home.archive, "plans", "x.json") + " 2026-03-24T23:00:00+00:00 "
                       "http://127.0.0.1:5555/courses/1 2026-03-20T12:59:00Z")
            self.assertEqual("<ARCHIVE>/plans/x.json <NOW> <CANVAS>/courses/1 2026-03-20T12:59:00Z", s)
        finally:
            home.cleanup()


if __name__ == "__main__":
    unittest.main()
