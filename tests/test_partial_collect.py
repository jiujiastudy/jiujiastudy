"""一门课出问题不许把全部数据冻住（S03），课程清单每次都要对一遍（S02）。

S03 原来的行为：任何一个接口报错就整批不提升，三门课的 deadline 一起停在上一次；
课程级的 401/403/404 还会被写成「token 有问题」，学生照着提示去换 token，白折腾。
S02 原来的行为：课程清单只在第一次建档时拉一次，之后加的课、下学期的课永远不出现，也没有任何提示。
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")
NOW = "2026-03-24T23:00:00Z"
DATE = "2026-03-24"
ASSIGN_1101 = r"/courses/1101/assignments"


def blank_course():
    return {k: [] for k in ("assignments", "assignment_groups", "modules", "files", "discussion_topics")}


class PartialCollect(unittest.TestCase):
    def setUp(self):
        self.sc = mockcanvas.Scenario("au_semester")
        self.mock = mockcanvas.MockCanvas(self.sc).start()
        self.home = harness.FakeHome("partial")
        self.home.seed(self.sc, self.mock.base_url)

    def tearDown(self):
        self.home.cleanup()
        self.mock.stop()

    def collect(self, *extra):
        r = harness.run_coach(self.home, ["collect", "--touch", "--json", "--date", DATE] + list(extra),
                              TOOLS, now=NOW, ports=(self.mock.port,))
        try:
            res = r.json()
        except ValueError:
            self.fail(f"collect --json 没输出 JSON（exit {r.code}）：\n{r.stdout[-800:]}\n{r.stderr[-800:]}")
        return r, dict(res, **self.digest())

    def digest(self):
        """采集详情写在 digest.json 里；CLI 的 --json 只给摘要。"""
        p = os.path.join(self.home.archive, "raw", "daily", DATE, "digest.json")
        if not os.path.isfile(p):
            return {"stale": {}, "course_changes": []}
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return {"stale": d.get("stale") or {}, "course_changes": d.get("course_changes") or []}

    def snapshot(self):
        with open(os.path.join(self.home.archive, "raw", "daily", "snapshot.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_一门课挂了_别的课照常更新(self):
        _, first = self.collect()
        self.assertTrue(first["promoted"], first.get("errors"))
        before = self.snapshot()
        n_1101 = sum(1 for a in before["assignments"].values() if a["course"] == "ACCT1101")
        self.assertTrue(n_1101, "第一次采集就该有 ACCT1101 的作业")

        self.mock.force_status(ASSIGN_1101, 500)
        r, d = self.collect("--force")

        self.assertTrue(d["promoted"], "一门课挂了不该整批不提升")
        self.assertEqual(["ACCT1101"], list(d["stale"]), d.get("errors"))
        self.assertFalse(d["complete"], "有课没采到就不算完整")
        after = self.snapshot()
        self.assertEqual(n_1101, sum(1 for a in after["assignments"].values() if a["course"] == "ACCT1101"),
                         "挂掉那门课的作业要沿用上次的，不能凭空消失")
        for code in ("PSYC2012", "DSGN3402"):
            self.assertTrue(any(a["course"] == code for a in after["assignments"].values()), f"{code} 该照常更新")
        self.assertTrue(any("ACCT1101" in e and "上次" not in e[:4] for e in d["errors"]),
                        f"要点名说哪门课没采到：{d['errors']}")

    def test_课程级的401说的是这门课打不开_不是token有问题(self):
        self.collect()
        self.mock.force_status(ASSIGN_1101, 401)
        _, d = self.collect("--force")
        msg = "\n".join(d["errors"])
        self.assertIn("ACCT1101", msg)
        self.assertIn("这门课打不开", msg)
        self.assertNotIn("token", msg.lower(), f"课程级 401 不该赖 token：{msg}")

    def test_所有课都挂了_不提升(self):
        self.collect()
        self.mock.force_status(r"/courses/\d+/assignments", 500)
        r, d = self.collect("--force")
        self.assertFalse(d["promoted"], "一门都没采到还提升，等于拿旧数据冒充新的")
        self.assertFalse(d["complete"])

    def test_只有模块挂了_deadline照样更新(self):
        self.collect()
        self.mock.force_status(r"/courses/1101/modules", 503)
        _, d = self.collect("--force")
        self.assertTrue(d["promoted"])
        self.assertFalse(d["stale"], "模块拉不到不影响 deadline，不该整门课作废")
        self.assertTrue(any(it["course"] == "ACCT1101" for it in self.snapshot()["items"].values()),
                        "模块这次没拉到，要沿用上次的条目")


class CourseListRefresh(unittest.TestCase):
    def setUp(self):
        self.sc = mockcanvas.Scenario("au_semester")
        self.mock = mockcanvas.MockCanvas(self.sc).start()
        self.home = harness.FakeHome("courses")
        self.home.seed(self.sc, self.mock.base_url)

    def tearDown(self):
        self.home.cleanup()
        self.mock.stop()

    collect = PartialCollect.collect
    digest = PartialCollect.digest

    def config(self):
        with open(os.path.join(self.home.archive, "config.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_新选的课自动进清单并点名告诉用户(self):
        self.collect()
        self.sc.courses.append({"id": 1104, "name": "STAT2011 Probability", "course_code": "STAT2011", "_active": True})
        self.sc.course[1104] = blank_course()

        _, d = self.collect("--force")

        codes = [c["code"] for c in self.config()["courses"]]
        self.assertIn("STAT2011", codes, "新选的课要自己出现在清单里")
        self.assertTrue(any("STAT2011" in c for c in d["course_changes"]), d.get("course_changes"))

    def test_退掉的课标成看不到_数据留着_不再去拉(self):
        self.collect()
        before = sum(1 for a in self.snapshot()["assignments"].values() if a["course"] == "ACCT1101")
        self.sc.courses[0]["_active"] = False  # 1101 退课了

        _, d = self.collect("--force")

        gone = next(c for c in self.config()["courses"] if c["code"] == "ACCT1101")
        self.assertTrue(gone.get("inactive"), "看不到的课要标出来")
        self.assertTrue(any("ACCT1101" in c for c in d["course_changes"]), d.get("course_changes"))
        self.assertEqual(before, sum(1 for a in self.snapshot()["assignments"].values() if a["course"] == "ACCT1101"),
                         "退课了旧数据也要留着")
        paths = [q["path"] for q in self.mock.requests()]
        self.assertFalse(any(p.endswith("/courses/1101/assignments") for p in paths[-6:]),
                         "已经看不到的课不该继续去拉")

    def test_图书馆之类的站点不进课程清单(self):
        self.sc.courses.append({"id": 1901, "name": "Library Skills Hub", "course_code": "2026_LIB", "_active": True})
        self.sc.course[1901] = blank_course()
        self.collect()
        self.assertNotIn(1901, [c["id"] for c in self.config()["courses"]])

    def snapshot(self):
        with open(os.path.join(self.home.archive, "raw", "daily", "snapshot.json"), encoding="utf-8") as f:
            return json.load(f)


if __name__ == "__main__":
    unittest.main()
