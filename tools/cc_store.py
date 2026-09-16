"""档案读写：读 JSON、原子写 JSON、点号键、命令行的 JSON 参数、跨进程文件锁。不含业务逻辑。"""
import json
import os
import sys
import tempfile
import time


def jload(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def jsave(p, obj):
    """原子写：先写临时文件再替换。"""
    d = os.path.dirname(p)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.write("\n")
        # Windows can briefly deny os.replace while another process or an
        # antivirus scanner still has the destination open. Keep the atomic
        # write, but tolerate that short sharing window.
        for attempt in range(5):
            try:
                os.replace(tmp, p)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (2 ** attempt))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get_key(obj, dotted, default=None):
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def set_key(obj, dotted, value):
    parts = dotted.split(".")
    cur = obj
    for part in parts[:-1]:
        if not isinstance(cur.get(part), dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value
    return obj


def load_json_arg(spec):
    if not spec:
        return None
    raw = sys.stdin.buffer.read().decode("utf-8") if spec == "-" else open(spec, encoding="utf-8").read()
    return json.loads(raw) if raw.strip() else {}


class FileLock:
    """Small cross-platform advisory lock held by an open file handle."""

    def __init__(self, path):
        self.path = path
        self.handle = None
        self.held = False

    def acquire(self, blocking=True):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.handle = open(self.path, "a+b")
        if os.path.getsize(self.path) == 0:
            self.handle.write(b"0")
            self.handle.flush()
        while True:
            try:
                self.handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.held = True
                return True
            except OSError:
                if not blocking:
                    self.release()
                    return False
                time.sleep(0.05)

    def release(self):
        if self.handle is None:
            return
        if self.held:
            try:
                self.handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        self.held = False
        self.handle.close()
        self.handle = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()
