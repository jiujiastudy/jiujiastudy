"""Run tools/coach.py against the mock Canvas in a throwaway fake home, and read or write golden output.

    python tests/harness.py capture [--code DIR] [--scenario NAME ...]    write tests/golden/ from DIR/tools
    python tests/harness.py run SCENARIO [--code DIR] [--keep] -- ARGS    one isolated command, masked output

Isolation: every run gets a fresh fake home (USERPROFILE, HOME, APPDATA, TEMP and
the archive all inside it), CANVAS_TOKEN=dummy, COURSECOACH_NO_DIALOG=1, no proxy,
pip without an index, and _coach_runner.py refuses every connection except the
mock's 127.0.0.1 port and every child process. The clock is pinned to the
scenario's "now" and every command gets --date.

Environment: STC_TEST_TMP (where fake homes go), STC_KEEP_HOMES=1 (keep them),
STC_CODE_DIR (test another checkout; default: this repo).
"""
import argparse
import datetime as dt
import glob
import html.parser
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS)
FIXTURES = os.path.join(TESTS, "fixtures")
GOLDEN = os.path.join(TESTS, "golden")
TZDATA = os.path.join(TESTS, "tzdata")
RUNNER = os.path.join(TESTS, "_coach_runner.py")
SCENARIOS = ("au_semester", "us_quarter", "uk_term", "cn_names")
TOKEN = "dummy"  # never a real token
UTC = dt.timezone.utc

sys.path.insert(0, TESTS)
import mockcanvas  # noqa: E402

# One archive, in order. Every command also gets --date <scenario date>.
MAIN_STEPS = [
    ("00_status_before_collect", ["status"]),
    ("01_collect_touch", ["collect", "--touch"]),
    ("02_status", ["status"]),
    ("03_status_json", ["status", "--json"]),
    ("04_radar", ["radar"]),
    ("05_radar_json", ["radar", "--json"]),
    ("06_study", ["study"]),
    ("07_study_json", ["study", "--json"]),
    ("08_radar_write_json", ["radar", "--write", "--json"]),
    ("09_study_write_json", ["study", "--write", "--json"]),
    ("10_status_after_write", ["status"]),
    ("11_status_after_write_json", ["status", "--json"]),
    ("12_collect_touch_again", ["collect", "--touch"]),
]
# A second, fresh archive (collect would otherwise reuse the first run for 10 minutes).
FRESH_STEPS = [("20_collect_touch_json", ["collect", "--touch", "--json"])]


def code_dir():
    return os.path.abspath(os.environ.get("STC_CODE_DIR") or REPO)


# ---------------------------------------------------------------- fake home
class FakeHome:
    def __init__(self, label):
        base = os.environ.get("STC_TEST_TMP")
        if base:
            os.makedirs(base, exist_ok=True)
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix=f"stc-{label}-", dir=base or None))
        self.user = os.path.join(self.dir, "user")
        self.root = os.path.join(self.user, "Desktop", "STCanvas")
        self.archive = os.path.join(self.root, ".coach")
        self.tmp = os.path.join(self.dir, "tmp")
        for d in (os.path.join(self.user, "Desktop"), self.tmp, os.path.join(self.user, "AppData", "Roaming"),
                  os.path.join(self.user, "AppData", "Local"), os.path.join(self.user, ".config")):
            os.makedirs(d, exist_ok=True)

    def seed(self, scenario, base_url):
        """config.json and state.json as doctor leaves them, pointing at the mock."""
        os.makedirs(self.archive, exist_ok=True)
        cfg = dict(scenario.meta["config"])
        cfg["canvas_host"] = base_url
        for name, obj in (("config.json", cfg), ("state.json", scenario.meta["state"])):
            with open(os.path.join(self.archive, name), "w", encoding="utf-8", newline="\n") as f:
                json.dump(obj, f, ensure_ascii=False, indent=1)
                f.write("\n")

    def env(self, tools, now=None, ports=()):
        keep = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE")
        env = {k: os.environ[k] for k in keep if k in os.environ}
        appdata = os.path.join(self.user, "AppData")
        env.update({
            "USERPROFILE": self.user, "HOME": self.user,
            "APPDATA": os.path.join(appdata, "Roaming"), "LOCALAPPDATA": os.path.join(appdata, "Local"),
            "XDG_CONFIG_HOME": os.path.join(self.user, ".config"),
            "XDG_DATA_HOME": os.path.join(self.user, ".local", "share"),
            "XDG_CACHE_HOME": os.path.join(self.user, ".cache"),
            "TEMP": self.tmp, "TMP": self.tmp, "TMPDIR": self.tmp,
            "COURSECOACH_HOME": self.archive, "COURSECOACH_ROOT": self.root, "COURSECOACH_NO_DIALOG": "1",
            "CANVAS_TOKEN": TOKEN,
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
            "PYTHONHASHSEED": os.environ.get("STC_HASHSEED", "0"),
            "PYTHONTZPATH": TZDATA,
            "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_CONFIG_FILE": os.devnull,
            "NO_PROXY": "*", "no_proxy": "*",
            "STC_TOOLS_DIR": tools, "STC_ALLOW_PORTS": ",".join(str(p) for p in ports),
        })
        if now:
            env["STC_NOW"] = now
        return env

    def cleanup(self):
        if os.environ.get("STC_KEEP_HOMES") != "1":
            shutil.rmtree(self.dir, ignore_errors=True)


class Result:
    def __init__(self, args, code, stdout, stderr, elapsed):
        self.args, self.code, self.stdout, self.stderr, self.elapsed = args, code, stdout, stderr, elapsed

    def json(self):
        return json.loads(self.stdout)


def run_coach(home, args, tools, now=None, ports=(), timeout=180, extra_env=None, script=None):
    """Run tools/coach.py (or another tools/ script, e.g. script="canvas_api.py") in the fake home.
    An extra_env value of None removes that variable (e.g. {"CANVAS_TOKEN": None})."""
    t0 = time.monotonic()
    env = home.env(tools, now, ports)
    for k, v in (extra_env or {}).items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    if script:
        env["STC_SCRIPT"] = script
    p = subprocess.run([sys.executable, "-B", RUNNER] + list(args), env=env, cwd=home.dir,
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    dec = lambda b: b.decode("utf-8", "replace").replace("\r\n", "\n")  # noqa: E731
    return Result(list(args), p.returncode, dec(p.stdout), dec(p.stderr), time.monotonic() - t0)


# ---------------------------------------------------------------- masking
_PLACEHOLDER = re.compile(r"<(?:CODE|ARCHIVE|ROOT|USER|TMP|FAKE|PY|PYDIR)>")
_TIME = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?:([T ])(\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)(Z|[+-]\d{2}:?\d{2})?)?(?!\d)")


class Masker:
    """Local paths -> <ARCHIVE>/<ROOT>/<CODE>/..., mock URL -> <CANVAS>, the pinned now -> <NOW>,
    and any time within 3 days of the real clock -> <WALLCLOCK> (the tool read the real clock)."""

    def __init__(self, home, code, base_url, now_iso):
        pairs = []
        for path, tag in ((code, "<CODE>"), (home.archive, "<ARCHIVE>"), (home.root, "<ROOT>"), (home.user, "<USER>"),
                          (home.tmp, "<TMP>"), (home.dir, "<FAKE>"), (sys.executable, "<PY>"),
                          (os.path.dirname(sys.executable), "<PYDIR>")):
            for v in self._variants(path):
                pairs.append((v, tag))
        pairs.append((base_url, "<CANVAS>"))
        pairs = sorted(set(pairs), key=lambda p: -len(p[0]))
        self._tags = {f"g{i}": tag for i, (_, tag) in enumerate(pairs)}
        self._rx = re.compile("|".join(f"(?P<g{i}>{re.escape(v)})" for i, (v, _) in enumerate(pairs)),
                              re.IGNORECASE if os.name == "nt" else 0)
        self.now = mockcanvas._ts(now_iso)
        self.wall = dt.datetime.now(UTC)

    @staticmethod
    def _variants(p):
        p = os.path.abspath(p)
        out = set()
        for v in (p, os.path.normpath(p), os.path.realpath(p)):
            out |= {v, v.replace("\\", "/"), v.replace("\\", "\\\\")}
        return {v for v in out if len(v) > 3}

    def _time(self, m):
        date, sep, clock, off = m.groups()
        try:
            if clock:
                t = dt.datetime.fromisoformat(f"{date}T{clock}" + ("+00:00" if off == "Z" else off or ""))
                if t.tzinfo and self.now and t == self.now:
                    return "<NOW>"
                tt = t if t.tzinfo else t.replace(tzinfo=UTC)
                return "<WALLCLOCK>" if abs(tt - self.wall) < dt.timedelta(days=3) else m.group(0)
            d = dt.date.fromisoformat(date)
            return "<WALLDATE>" if abs((d - self.wall.date()).days) <= 2 else m.group(0)
        except ValueError:
            return m.group(0)

    def text(self, s):
        s = self._rx.sub(lambda m: self._tags[m.lastgroup], s.replace("\r\n", "\n"))
        s = "\n".join(l.replace("\\", "/") if _PLACEHOLDER.search(l) else l for l in s.split("\n"))
        return _TIME.sub(self._time, s)

    def obj(self, o):
        if isinstance(o, str):
            return self.text(o)
        if isinstance(o, list):
            return [self.obj(x) for x in o]
        if isinstance(o, dict):
            return {self.text(k): self.obj(v) for k, v in o.items()}
        return o


class _VisibleText(html.parser.HTMLParser):
    BLOCK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "section", "header", "footer", "summary", "br", "table",
             "ul", "ol", "details", "main", "title", "td", "th"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.links = [], 0, []

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "a":
            self.links.append(dict(attrs).get("href"))

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self.skip -= 1
        if tag == "a" and self.links:
            href = self.links.pop()
            if href:
                self.out.append(f" [{href}]")
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def visible_text(markup):
    p = _VisibleText()
    p.feed(markup)
    lines = (re.sub(r"\s+", " ", l).strip() for l in "".join(p.out).split("\n"))
    return "\n".join(l for l in lines if l) + "\n"


# ---------------------------------------------------------------- scenario runs
def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def collect_artifacts(home, mask, date):
    A, R = home.archive, home.root
    out = {}

    def text(name, path, html=False):
        if os.path.isfile(path):
            s = _read(path)
            out[name] = mask.text(visible_text(s) if html else s)

    def js(name, path, drop=()):
        if os.path.isfile(path):
            o = json.loads(_read(path))
            for k in drop:
                o.pop(k, None)
            out[name] = mask.obj(o)

    text("ddl_radar.md", os.path.join(A, "DDL雷达.md"))
    plans = sorted(glob.glob(os.path.join(A, "plans", "*.json")))
    if plans:
        js("plan.json", plans[0])
    mds = sorted(glob.glob(os.path.join(A, "plans", "*.md")))
    if mds:
        text("plan.md", mds[0])
    text("radar_html.txt", os.path.join(R, "Deadline雷达.html"), html=True)
    text("week_html.txt", os.path.join(R, "STCanvas.html"), html=True)
    text("index.md", os.path.join(A, "INDEX.md"))
    text("log.md", os.path.join(A, "成果日志.md"))
    js("config.json", os.path.join(A, "config.json"))
    js("state.json", os.path.join(A, "state.json"))
    js("snapshot.json", os.path.join(A, "raw", "daily", "snapshot.json"))
    js("digest.json", os.path.join(A, "raw", "daily", date, "digest.json"), drop=("snapshot",))
    js("downloads.json", os.path.join(A, "raw", "downloads.json"))
    files = []
    for dirpath, _, names in os.walk(home.dir):
        for n in names:
            files.append(os.path.relpath(os.path.join(dirpath, n), home.dir).replace("\\", "/"))
    out["tree.txt"] = "\n".join(sorted(files)) + "\n"
    return out


def _step(sid, argv, r, mask, reqs):
    rec = {"id": sid, "args": argv, "exit": r.code, "stderr": mask.text(r.stderr), "elapsed": round(r.elapsed, 2)}
    if "--json" in argv:
        try:
            rec["stdout"] = mask.obj(json.loads(r.stdout))
        except ValueError:
            rec["stdout"], rec["stdout_not_json"] = mask.text(r.stdout), True
    else:
        rec["stdout"] = mask.text(r.stdout)
    rec["requests"] = [mask.text(f"{q['method']} {q['path']}" + ("?" + "&".join(f"{k}={v}" for k, v in q["query"]) if q["query"] else "")
                                 + f" -> {q['status']}") for q in reqs]
    rec["unmatched"] = [q["path"] for q in reqs if not q["matched"]]
    return rec


def run_scenario(name, code=None):
    """Run MAIN_STEPS in one archive and FRESH_STEPS in another; return masked records and artifacts."""
    code = os.path.abspath(code or code_dir())
    tools = os.path.join(code, "tools")
    sc = mockcanvas.Scenario(name)
    now, date = sc.meta["now"], sc.meta["date"]
    out = {"scenario": name, "steps": [], "artifacts": {}}
    with mockcanvas.MockCanvas(sc) as mock:
        for steps, label in ((MAIN_STEPS, name), (FRESH_STEPS, name + "-fresh")):
            home = FakeHome(label)
            try:
                home.seed(sc, mock.base_url)
                mask = Masker(home, code, mock.base_url, now)
                mock.requests(clear=True)
                for sid, args in steps:
                    argv = list(args) + ["--date", date]
                    r = run_coach(home, argv, tools, now=now, ports=(mock.port,))
                    out["steps"].append(_step(sid, argv, r, mask, mock.requests(clear=True)))
                if steps is MAIN_STEPS:
                    out["artifacts"] = collect_artifacts(home, mask, date)
            finally:
                home.cleanup()
    return out


# ---------------------------------------------------------------- golden files
def _dump_json(o):
    return json.dumps(o, ensure_ascii=False, indent=1) + "\n"


def write_golden(data, root=GOLDEN):
    d = os.path.join(root, data["scenario"])
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(os.path.join(d, "artifacts"))

    def w(rel, s):
        with open(os.path.join(d, rel), "w", encoding="utf-8", newline="\n") as f:
            f.write(s)

    manifest = {"scenario": data["scenario"], "python": sys.version.split()[0], "steps": [], "artifacts": sorted(data["artifacts"])}
    reqs = []
    for st in data["steps"]:
        is_json = not isinstance(st["stdout"], str)
        fname = st["id"] + (".json" if is_json else ".txt")
        w(fname, _dump_json(st["stdout"]) if is_json else st["stdout"])
        manifest["steps"].append({"id": st["id"], "args": st["args"], "exit": st["exit"], "stdout": fname,
                                  "stderr": st["stderr"]})
        reqs += [f"{st['id']} {q}" for q in st["requests"]]
    for name, val in data["artifacts"].items():
        w(os.path.join("artifacts", name), val if isinstance(val, str) else _dump_json(val))
    w("requests.txt", "\n".join(reqs) + "\n")
    w("manifest.json", _dump_json(manifest))
    return d


def load_golden(name, root=GOLDEN):
    d = os.path.join(root, name)
    manifest = json.loads(_read(os.path.join(d, "manifest.json")))
    steps = []
    for st in manifest["steps"]:
        raw = _read(os.path.join(d, st["stdout"]))
        steps.append(dict(st, stdout_file=st["stdout"], stdout=json.loads(raw) if st["stdout"].endswith(".json") else raw))
    arts = {}
    for name_ in manifest["artifacts"]:
        raw = _read(os.path.join(d, "artifacts", name_))
        arts[name_] = json.loads(raw) if name_.endswith(".json") else raw
    reqs = [l for l in _read(os.path.join(d, "requests.txt")).split("\n") if l]
    return {"manifest": manifest, "steps": steps, "artifacts": arts, "requests": reqs}


def as_text(v):
    return v if isinstance(v, str) else _dump_json(v)


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture", help="write golden output from a code tree")
    c.add_argument("--code", default=None, help="checkout whose tools/ to run (default: this repo)")
    c.add_argument("--scenario", action="append", choices=SCENARIOS)
    c.add_argument("--out", default=GOLDEN)
    r = sub.add_parser("run", help="run one command in a fresh fake home and print masked output")
    r.add_argument("scenario", choices=SCENARIOS)
    r.add_argument("--code", default=None)
    r.add_argument("--keep", action="store_true", help="keep the fake home and print its path")
    argv = list(sys.argv[1:] if argv is None else argv)
    tail = argv[argv.index("--") + 1:] if "--" in argv else []
    a = ap.parse_args(argv[:argv.index("--")] if "--" in argv else argv)
    a.args = tail
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    if a.cmd == "capture":
        for name in a.scenario or SCENARIOS:
            t0 = time.monotonic()
            data = run_scenario(name, a.code)
            d = write_golden(data, a.out)
            bad = [st["id"] for st in data["steps"] if st["unmatched"] or st.get("stdout_not_json")]
            print(f"{name}: {len(data['steps'])} steps, {len(data['artifacts'])} artifacts, "
                  f"{time.monotonic() - t0:.1f}s -> {os.path.relpath(d, REPO)}" + (f"  CHECK {bad}" if bad else ""))
        return 0
    args = [x for x in a.args if x != "--"]
    code = os.path.abspath(a.code or code_dir())
    sc = mockcanvas.Scenario(a.scenario)
    with mockcanvas.MockCanvas(sc) as mock:
        home = FakeHome(a.scenario)
        try:
            home.seed(sc, mock.base_url)
            res = run_coach(home, args + ["--date", sc.meta["date"]], os.path.join(code, "tools"), now=sc.meta["now"],
                            ports=(mock.port,))
            mask = Masker(home, code, mock.base_url, sc.meta["now"])
            sys.stdout.write(mask.text(res.stdout))
            if res.stderr:
                sys.stderr.write(mask.text(res.stderr))
            print(f"[exit {res.code}]" + (f" [home {home.dir}]" if a.keep else ""))
            for q in mock.requests():
                print("  " + q["method"], q["path"], q["status"])
        finally:
            if not a.keep:
                home.cleanup()
    return res.code


if __name__ == "__main__":
    sys.exit(main())
