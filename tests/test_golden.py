"""Golden tests: status, radar, study and collect --touch on four synthetic schools must match tests/golden/.

The goldens were captured from the untouched package with
    python tests/harness.py capture --code <reference checkout>
and since then re-captured only where a fix changes output on purpose (B0: the Canvas text fence in the
collect digest and the study notes). If a change is meant to alter output, re-capture from the new code and
review the diff in git.
"""
import difflib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402


def _diff(expected, actual, label):
    a, b = harness.as_text(expected), harness.as_text(actual)
    lines = list(difflib.unified_diff(a.splitlines(), b.splitlines(), "golden/" + label, "actual/" + label,
                                      lineterm="", n=2))
    return "\n".join(lines[:80]) + ("\n..." if len(lines) > 80 else "")


class _Golden:
    scenario = None

    @classmethod
    def setUpClass(cls):
        cls.golden = harness.load_golden(cls.scenario)
        cls.actual = harness.run_scenario(cls.scenario)

    def test_steps(self):
        got = {s["id"]: s for s in self.actual["steps"]}
        for exp in self.golden["steps"]:
            with self.subTest(step=exp["id"]):
                act = got.get(exp["id"])
                self.assertIsNotNone(act, "step did not run")
                self.assertEqual(exp["exit"], act["exit"], "exit code; stderr:\n" + act["stderr"][-1500:])
                if exp["stdout"] != act["stdout"]:
                    self.fail("stdout differs\n" + _diff(exp["stdout"], act["stdout"], exp["stdout_file"]))
                if exp["stderr"] != act["stderr"]:
                    self.fail("stderr differs\n" + _diff(exp["stderr"], act["stderr"], exp["id"] + ".stderr"))
        self.assertEqual([s["id"] for s in self.golden["steps"]], [s["id"] for s in self.actual["steps"]])

    def test_artifacts(self):
        act = self.actual["artifacts"]
        self.assertEqual(sorted(self.golden["artifacts"]), sorted(act), "set of written files changed")
        for name, exp in self.golden["artifacts"].items():
            with self.subTest(artifact=name):
                if exp != act.get(name):
                    self.fail(_diff(exp, act.get(name, ""), "artifacts/" + name))

    def test_requests(self):
        act = [f"{s['id']} {q}" for s in self.actual["steps"] for q in s["requests"]]
        if act != self.golden["requests"]:
            self.fail("Canvas requests changed\n" + _diff("\n".join(self.golden["requests"]), "\n".join(act), "requests.txt"))

    def test_only_known_endpoints(self):
        self.assertEqual([], [(s["id"], p) for s in self.actual["steps"] for p in s["unmatched"]])


for _name in harness.SCENARIOS:
    _cls = type(f"Golden_{_name}", (_Golden, unittest.TestCase), {"scenario": _name})
    globals()[_cls.__name__] = _cls
del _cls, _name

if __name__ == "__main__":
    unittest.main()
