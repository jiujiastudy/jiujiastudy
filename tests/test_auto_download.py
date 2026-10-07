"""采集完自动在后台开始下课件：不再靠 AI 看到 status 那句「课件待下载」才去跑。

10-06 发现：发起人的 USYD 档案排队 26 个课件一个没下，档案里没有 download.log——后台下载从没启动过。
原因是电脑默认档案指向别处，开场的 status 从没读到这份档案，那句提示也就没人看到。
"""
import io
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")
sys.path.insert(0, TOOLS)
import cc_downloads  # noqa: E402
import coach  # noqa: E402


class _Clock:
    def now_utc(self):
        import datetime as dt
        return dt.datetime(2026, 10, 7, 0, 0, tzinfo=dt.timezone.utc)


def ctx_with(materials):
    return types.SimpleNamespace(cfg={"materials": materials}, clock=_Clock())


def args(json=False, download=False):
    return types.SimpleNamespace(json=json, download=download, background=False)


class AutoBackground(unittest.TestCase):
    def run_it(self, ctx, a, spawn, downloads=None):
        out = io.StringIO()
        with mock.patch.object(cc_downloads, "spawn_downloads", spawn), \
                mock.patch.object(cc_downloads, "load_downloads", lambda _ctx: downloads or {}), redirect_stdout(out):
            r = coach._downloads(ctx, a)
        return r, out.getvalue()

    def test_队列有课件就在后台开始并说一句(self):
        spawn = mock.Mock(return_value={"queued": 26, "started": True, "running": False, "log": "x"})
        r, out = self.run_it(ctx_with({"auto_download": True}), args(), spawn)
        spawn.assert_called_once()
        self.assertTrue(r["started"])
        self.assertIn("课件后台下载：已自动开始，队列 26 个", out)

    def test_设置关了自动下载就不碰(self):
        spawn = mock.Mock()
        r, out = self.run_it(ctx_with({"auto_download": False}), args(), spawn)
        spawn.assert_not_called()
        self.assertIsNone(r)
        self.assertEqual(out, "")

    def test_没写设置也算开着(self):
        spawn = mock.Mock(return_value={"queued": 3, "started": True, "running": False, "log": "x"})
        r, _ = self.run_it(types.SimpleNamespace(cfg={}, clock=_Clock()), args(json=True), spawn)
        self.assertTrue(r["started"])

    def test_上一批刚出过错就隔六小时再自动试(self):
        spawn = mock.Mock(return_value={"queued": 3, "started": True, "running": False, "log": "x"})
        r, out = self.run_it(ctx_with({"auto_download": True}), args(), spawn, downloads={"last_error_at": "2026-10-06T21:00:00+00:00"})
        spawn.assert_not_called()
        self.assertIsNone(r)
        self.assertEqual(out, "")
        r, _ = self.run_it(ctx_with({"auto_download": True}), args(), spawn, downloads={"last_error_at": "2026-10-06T10:00:00+00:00"})
        self.assertTrue(r["started"], "过了六小时照常开始")

    def test_硬盘快满了就不下并说一句(self):
        spawn = mock.Mock(return_value={"queued": 26, "started": False, "running": False, "log": "x", "disk_low": 1.2})
        r, out = self.run_it(ctx_with({"auto_download": True}), args(), spawn)
        self.assertEqual(r["disk_low"], 1.2)
        self.assertIn("硬盘只剩 1.2 GB（不到 2 GB），这次先不下", out)

    def test_已经在下或队列是空的就什么都不说(self):
        for info in ({"queued": 5, "started": False, "running": True, "log": "x"},
                     {"queued": 0, "started": False, "running": False, "log": "x"}):
            r, out = self.run_it(ctx_with({"auto_download": True}), args(), mock.Mock(return_value=info))
            self.assertIsNone(r)
            self.assertEqual(out, "")

    def test_宿主不让开子进程也不报错(self):
        r, out = self.run_it(ctx_with({"auto_download": True}), args(), mock.Mock(side_effect=PermissionError("blocked")))
        self.assertIsNone(r)
        self.assertEqual(out, "")

    def test_json_模式不打印(self):
        spawn = mock.Mock(return_value={"queued": 2, "started": True, "running": False, "log": "x"})
        r, out = self.run_it(ctx_with({"auto_download": True}), args(json=True), spawn)
        self.assertTrue(r["started"])
        self.assertEqual(out, "")


class DiskOk(unittest.TestCase):
    def ctx(self, materials=None):
        return types.SimpleNamespace(cfg={"materials": materials or {}}, root=tempfile.gettempdir(), home=tempfile.gettempdir())

    def test_剩余空间够不够(self):
        usage = types.SimpleNamespace(total=0, used=0, free=1.5e9)
        with mock.patch("shutil.disk_usage", return_value=usage):
            self.assertEqual(cc_downloads.disk_ok(self.ctx()), (False, 1.5))
            self.assertEqual(cc_downloads.disk_ok(self.ctx({"min_free_gb": 1})), (True, 1.5))

    def test_查不到就当够(self):
        with mock.patch("shutil.disk_usage", side_effect=OSError("no")):
            self.assertEqual(cc_downloads.disk_ok(self.ctx()), (True, None))


if __name__ == "__main__":
    unittest.main()
