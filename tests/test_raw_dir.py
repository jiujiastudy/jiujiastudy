"""快照里的 raw_dir 要找得回上一次的原始数据。

原来的行为：raw_dir 按资料夹记（".coach/raw/daily/<日期>"），读的时候却拼在档案（资料夹/.coach）上，
成了 ".coach/.coach/raw/daily/<日期>"，永远找不到。新用户的档案都在资料夹里，于是：
改了说明的作业拿空字符串去比，整段说明都算「改动」；旧版坏缓存的检查也读不到 digest，形同虚设。
老用户的档案（~/CourseCoach）不在资料夹里，按档案记，不受影响。
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")
sys.path.insert(0, TOOLS)
import cc_collect  # noqa: E402

AID = 1101001
OLD = "<p>Ten questions on Week 1.</p><p>30 minutes.</p><p>Open book.</p>"
NEW = "<p>Ten questions on Week 1.</p><p>45 minutes.</p><p>Open book.</p>"
DAY1, NOW1 = "2026-03-24", "2026-03-24T23:00:00Z"
DAY2, NOW2 = "2026-03-25", "2026-03-25T23:00:00Z"


class _Ctx:
    """cc_collect 读快照只用到 home / P。"""

    def __init__(self, home):
        self.home = home.archive

    def P(self, *a):
        return os.path.join(self.home, *a)


class RawDir(unittest.TestCase):
    def setUp(self):
        self.sc = mockcanvas.Scenario("au_semester")
        self.mock = mockcanvas.MockCanvas(self.sc).start()
        self.home = harness.FakeHome("rawdir")
        self.home.seed(self.sc, self.mock.base_url)
        self.ctx = _Ctx(self.home)
        self.set_desc(OLD)

    def tearDown(self):
        self.home.cleanup()
        self.mock.stop()

    def set_desc(self, html):
        a = next(x for x in self.sc.course[1101]["assignments"] if x["id"] == AID)
        a["description"] = html

    def collect(self, date, now):
        r = harness.run_coach(self.home, ["collect", "--touch", "--json", "--force", "--date", date],
                              TOOLS, now=now, ports=(self.mock.port,))
        try:
            res = r.json()
        except ValueError:
            self.fail(f"collect --json 没输出 JSON（exit {r.code}）：\n{r.stdout[-800:]}\n{r.stderr[-800:]}")
        self.assertTrue(res.get("promoted"), res)

    def path(self, *a):
        return os.path.join(self.home.archive, "raw", "daily", *a)

    def load(self, *a):
        with open(self.path(*a), encoding="utf-8") as f:
            return json.load(f)

    def save(self, obj, *a):
        with open(self.path(*a), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

    def desc_diff(self):
        d = self.load(DAY2, "digest.json")
        e = next((x for x in d["changed_assignments"] if str(x["id"]) == str(AID)), None)
        self.assertIsNotNone(e, "改了说明的作业要列进 changed_assignments")
        return e.get("description_diff")

    def test_快照记的原始数据目录找得到(self):
        self.collect(DAY1, NOW1)
        snap = self.load("snapshot.json")
        self.assertEqual("raw/daily/" + DAY1, snap["raw_dir"], "raw_dir 按档案记，别带资料夹那一层 .coach")
        rd = cc_collect.raw_dir_abs(self.ctx, snap)
        self.assertTrue(os.path.isfile(os.path.join(rd, "assignments_1101.json")), rd)

    def test_说明改了一句_只列这一句(self):
        self.collect(DAY1, NOW1)
        self.set_desc(NEW)
        self.collect(DAY2, NOW2)
        self.assertEqual(["-30 minutes.", "+45 minutes."], self.desc_diff())

    def test_旧版按资料夹记的快照照样读得到(self):
        """已经在用的新用户，手上的快照是旧写法；升级后第一次采集也不能把整段说明当成改动。"""
        self.collect(DAY1, NOW1)
        snap = self.load("snapshot.json")
        snap["raw_dir"] = ".coach/raw/daily/" + DAY1
        self.save(snap, "snapshot.json")
        self.assertTrue(os.path.isdir(cc_collect.raw_dir_abs(self.ctx, snap)))
        self.set_desc(NEW)
        self.collect(DAY2, NOW2)
        self.assertEqual(["-30 minutes.", "+45 minutes."], self.desc_diff())
        self.assertEqual("raw/daily/" + DAY2, self.load("snapshot.json")["raw_dir"], "采一次就换成新写法")

    def test_档案挪过地方_旧路径按日期也找得到(self):
        """真机：资料夹整个挪进别的文件夹后，config 里的 root 和旧快照记的绝对路径都还指着老地方。"""
        self.collect(DAY1, NOW1)
        gone = os.path.join(self.home.dir, "搬走之前", "救驾", ".coach", "raw", "daily", DAY1)
        rd = cc_collect.raw_dir_abs(self.ctx, {"raw_dir": gone})
        self.assertEqual(os.path.normcase(self.path(DAY1)), os.path.normcase(rd))

    def test_旧版坏缓存_不许拿来用(self):
        """没有 complete 标记的旧快照，对应的 digest 里记着错误：说明那次没采全，要重拉。"""
        self.collect(DAY1, NOW1)
        self.assertIsNotNone(cc_collect.cacheable_snapshot(self.ctx), "干净的一次采集可以进缓存")
        snap = self.load("snapshot.json")
        snap.pop("complete")
        self.save(snap, "snapshot.json")
        digest = self.load(DAY1, "digest.json")
        digest["errors"] = ["HTTP 500: /api/v1/courses/1101/assignments"]
        self.save(digest, DAY1, "digest.json")
        self.assertIsNone(cc_collect.cacheable_snapshot(self.ctx))

    def test_完整快照只是可选接口报错_照样进缓存(self):
        """complete 标记在的快照以它为准：考试站点 403、公告挂了这类可选接口的错误不影响作业，不该每次都重拉。"""
        self.collect(DAY1, NOW1)
        digest = self.load(DAY1, "digest.json")
        digest["errors"] = ["HTTP 503: /api/v1/announcements"]
        self.save(digest, DAY1, "digest.json")
        self.assertIsNotNone(cc_collect.cacheable_snapshot(self.ctx))


if __name__ == "__main__":
    unittest.main()
