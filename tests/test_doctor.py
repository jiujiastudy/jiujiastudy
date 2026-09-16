"""doctor's verdicts that later batches build on.

- S56: after a successful first-time setup (token verified on Canvas, config.json and state.json written) doctor
  exits 0, and again on the next run; what it still lists under 「你需要做的事」 is advice. It exits 1 once set up
  but not connected (the token stopped working), and 2 when nothing can be set up.
- S22: the 「skill 位置」 check passes only where a host looks for skills: SKILL.md directly in a folder under
  .claude/skills, .codex/skills, .agents/skills (user or project), $CODEX_HOME/skills, or a plugin's skills/.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import mockcanvas  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")


class DoctorExitCodeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = mockcanvas.MockCanvas("au_semester").start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def setUp(self):
        self.home = harness.FakeHome("doctor")

    def tearDown(self):
        self.home.cleanup()

    def doctor(self, **env):
        # --all-courses: every fixture course counts, whatever today's real date is.
        args = ["doctor", "--no-detect", "--host", self.mock.base_url, "--tz", "Australia/Sydney", "--agent", "other",
                "--all-courses", "--json"]
        r = harness.run_coach(self.home, args, TOOLS, ports=(self.mock.port,), extra_env=env)
        try:
            return r, r.json()
        except ValueError:
            self.fail(f"doctor --json printed no JSON (exit {r.code}):\n{r.stdout[-800:]}\n{r.stderr[-800:]}")

    def test_first_setup_exits_0_and_stays_0(self):
        for run in ("first", "second"):
            with self.subTest(run=run):
                r, res = self.doctor()
                self.assertEqual(0, r.code, res.get("text"))
                self.assertIs(True, res["ready"])
                self.assertIn(("OK", "token"), {(c["level"], c["name"]) for c in res["checks"]})
                self.assertNotIn("错误", {c["level"] for c in res["checks"]}, res.get("text"))
                for name in ("config.json", "state.json"):
                    self.assertTrue(os.path.isfile(os.path.join(self.home.archive, name)), name)

    def test_not_connected_is_1_and_nothing_set_up_is_2(self):
        r, res = self.doctor(CANVAS_TOKEN="wrong")  # the mock answers 401, so no archive can be made
        self.assertEqual(2, r.code, res.get("text"))
        self.assertFalse(os.path.exists(os.path.join(self.home.archive, "config.json")))
        self.assertEqual(0, self.doctor()[0].code)
        r, res = self.doctor(CANVAS_TOKEN="wrong")  # set up, but the token no longer works
        self.assertEqual(1, r.code, res.get("text"))
        self.assertIs(False, res["ready"])
        self.assertTrue(res["must_fix"])


class SkillLocationTest(unittest.TestCase):
    CASES = {  # folder holding SKILL.md, relative to a fake home -> a host finds it
        ".claude/skills/jiujiastudy": True,
        ".agents/skills/jiujiastudy": True,
        ".codex/skills/jiujiastudy": True,
        "repo/.claude/skills/jiujiastudy": True,        # project skill (Claude Code)
        "repo/.agents/skills/jiujiastudy": True,        # project skill (Codex)
        "codexhome/skills/jiujiastudy": True,           # $CODEX_HOME/skills
        "plugin/skills/jiujiastudy": True,              # plugin skill; plugin/.claude-plugin/plugin.json exists
        ".claude/skills/jiujiastudy-main/jiujiastudy": False,  # unzipped one folder too deep
        "Downloads/jiujiastudy": False,
        "notes/skills/jiujiastudy": False,              # a folder called skills that no host reads
        ".claude/skills/empty": False,               # no SKILL.md
    }

    def test_only_where_a_host_looks(self):
        base = os.path.realpath(tempfile.mkdtemp(prefix="stc-skills-", dir=os.environ.get("STC_TEST_TMP") or None))
        try:
            for rel in self.CASES:
                d = os.path.join(base, *rel.split("/"))
                os.makedirs(d)
                if not rel.endswith("empty"):
                    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
                        f.write("---\nname: jiujiastudy\n---\n")
            os.makedirs(os.path.join(base, "plugin", ".claude-plugin"))
            with open(os.path.join(base, "plugin", ".claude-plugin", "plugin.json"), "w", encoding="utf-8") as f:
                f.write('{"name": "p"}\n')
            keep = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE")
            env = {k: os.environ[k] for k in keep if k in os.environ}
            env.update(HOME=base, USERPROFILE=base, CODEX_HOME=os.path.join(base, "codexhome"),
                       PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
            code = ("import json, os, sys, cc_install\n"
                    "base, rels = sys.argv[1], json.loads(sys.argv[2])\n"
                    "print(json.dumps({r: cc_install.skill_location_ok(os.path.join(base, *r.split('/'))) for r in rels}))\n")
            r = subprocess.run([sys.executable, "-B", "-c", code, base, json.dumps(list(self.CASES))], cwd=TOOLS, env=env,
                               capture_output=True, timeout=60)
            self.assertEqual(0, r.returncode, r.stderr.decode("utf-8", "replace"))
            self.assertEqual(self.CASES, json.loads(r.stdout.decode("utf-8")))
        finally:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
