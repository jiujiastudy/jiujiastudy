"""探测学校时绝不发 token（S09）。

原来的做法：把真 token 依次发给浏览器记录里每个返回 401 的站点，直到有一个能登上。
审计实测：悉大的 token 先被发到了 oc.sjtu.edu.cn；一个只会回 401 的假站点也拿到了 Bearer token。
现在：探测只判断「像不像 Canvas」，token 只发给用户确认过的那一个地址。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

sys.path.insert(0, os.path.join(harness.code_dir(), "tools"))
import canvas_api  # noqa: E402
import cc_detect  # noqa: E402
import cc_host  # noqa: E402


def hosts(*rows):
    return {h: {"score": s, "visits": s // 10, "bookmarks": 0, "browsers": ["Chrome"]} for h, s in rows}


class DetectNeverSendsToken(unittest.TestCase):
    def setUp(self):
        self._scan, self._is_canvas, self._canvas = cc_detect.scan, cc_host.is_canvas, canvas_api.Canvas
        cc_host.is_canvas = lambda url: True

    def tearDown(self):
        cc_detect.scan, cc_host.is_canvas, canvas_api.Canvas = self._scan, self._is_canvas, self._canvas

    def test_探测不构造带_token_的客户端(self):
        """浏览器记录里三个候选都像 Canvas；探测过程中一次也不许带 token 发请求。"""
        built = []

        class Boom:
            def __init__(self, *a, **k):
                built.append(a)
                raise AssertionError("探测阶段不许构造 Canvas 客户端：token 会被发出去")

        canvas_api.Canvas = Boom
        cc_detect.scan = lambda dry_run=False: {
            "hosts": hosts(("canvas.sydney.edu.au", 400), ("oc.sjtu.edu.cn", 90), ("canvas.lookalike.test", 30)),
            "files": ["history.sqlite"], "skipped": [], "scanned": ["history.sqlite"]}

        res = cc_detect.detect("REAL-TOKEN-DO-NOT-SEND")

        self.assertEqual([], built, "探测阶段构造了带 token 的客户端")
        self.assertTrue(all(c.get("token_ok") is None for c in res["candidates"]), "探测不该给出 token 能不能登的结论")
        self.assertEqual(3, len(res["candidates"]))

    def test_候选按访问次数排序_最多的排第一(self):
        cc_detect.scan = lambda dry_run=False: {
            "hosts": hosts(("canvas.a.edu", 30), ("canvas.b.edu", 300)), "files": [], "skipped": [], "scanned": []}
        res = cc_detect.detect()
        self.assertEqual("canvas.b.edu", res["candidates"][0]["host"])


if __name__ == "__main__":
    unittest.main()
