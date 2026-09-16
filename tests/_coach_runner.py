"""Run tools/coach.py for the tests: pinned clock, loopback-only network, no child processes.

harness.py starts this with:
  STC_TOOLS_DIR    the tools/ folder under test
  STC_SCRIPT       the tools/ script to run (default coach.py), e.g. canvas_api.py for its own command line
  STC_NOW          pinned "now" (ISO, UTC); cc_time.Clock.now_utc returns it
  STC_ALLOW_PORTS  comma-separated 127.0.0.1 ports the tool may connect to (the mock Canvas)
  STC_NO_TZDATA    1 = no time zone data at all (empty zoneinfo path, tzdata package hidden),
                   like a Windows Python without tzdata
  STC_NO_REGISTRY  1 = on Windows the registry reads as empty. Always on when CANVAS_TOKEN is not set,
                   so a token saved on this computer is never picked up.
Any other connection, DNS lookup or child process raises instead of running.
Not part of the skill; the tool has no clock hook of its own yet.
"""
import datetime as dt
import os
import runpy
import socket
import subprocess
import sys
import types

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _guard_network(ports):
    orig_connect, orig_connect_ex, orig_gai = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def check(sock, addr):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            host, port = addr[0], addr[1]
            if host not in LOOPBACK or port not in ports:
                raise ConnectionRefusedError(f"test harness blocked a connection to {host}:{port}")

    def connect(self, addr):
        check(self, addr)
        return orig_connect(self, addr)

    def connect_ex(self, addr):
        check(self, addr)
        return orig_connect_ex(self, addr)

    def getaddrinfo(host, *a, **k):
        name = host.decode() if isinstance(host, bytes) else host
        if name is not None and name not in LOOPBACK:
            raise socket.gaierror(socket.EAI_NONAME, f"test harness blocked a DNS lookup of {name}")
        return orig_gai(host, *a, **k)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo


def _guard_processes():
    def blocked(*a, **k):
        what = a[0] if a else k.get("args")
        raise PermissionError(f"test harness blocked a child process: {what!r}")

    subprocess.Popen = blocked
    os.system = blocked
    for name in ("startfile", "execv", "execve", "execvp", "spawnv", "spawnve"):
        if hasattr(os, name):
            setattr(os, name, blocked)


def _hide_tzdata():
    import zoneinfo
    zoneinfo.reset_tzpath(to=[])
    sys.modules["tzdata"] = None  # `import tzdata` now fails, as when the package is not installed


def _pin_clock(now):
    import cc_time
    fixed = dt.datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(dt.timezone.utc).replace(microsecond=0)
    cc_time.Clock.now_utc = lambda self: fixed


class _EmptyKey:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def Close(self):  # noqa: N802  (winreg's name)
        pass


def _hide_registry():
    """Replace winreg with one whose keys open but hold nothing: every value read fails like a missing value."""
    def open_key(*a, **k):
        return _EmptyKey()

    def missing(*a, **k):
        raise FileNotFoundError(2, "test harness hid the registry")

    def attr(name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name == "error":
            return OSError
        if name in ("OpenKey", "OpenKeyEx", "ConnectRegistry"):
            return open_key
        if name == "CloseKey":
            return lambda *a, **k: None
        return 0 if name.isupper() else missing  # HKEY_*/KEY_*/REG_* constants; any other function fails

    stub = types.ModuleType("winreg")
    stub.__getattr__ = attr
    sys.modules["winreg"] = stub


def main():
    sys.dont_write_bytecode = True
    tools = os.path.abspath(os.environ["STC_TOOLS_DIR"])
    script = os.environ.get("STC_SCRIPT") or "coach.py"
    if os.path.basename(script) != script or not script.endswith(".py"):
        raise SystemExit(f"STC_SCRIPT must be a file name in tools/: {script!r}")
    ports = {int(p) for p in (os.environ.get("STC_ALLOW_PORTS") or "").split(",") if p.strip()}
    _guard_network(ports)
    if os.environ.get("STC_ALLOW_SUBPROCESS") != "1":
        _guard_processes()
    if os.environ.get("STC_NO_TZDATA") == "1":
        _hide_tzdata()
    if sys.platform == "win32" and (os.environ.get("STC_NO_REGISTRY") == "1" or not os.environ.get("CANVAS_TOKEN")):
        _hide_registry()
    sys.path.insert(0, tools)
    if os.environ.get("STC_NOW"):
        _pin_clock(os.environ["STC_NOW"])
    path = os.path.join(tools, script)
    sys.argv = [path] + sys.argv[1:]
    runpy.run_path(path, run_name="__main__")


if __name__ == "__main__":
    main()
