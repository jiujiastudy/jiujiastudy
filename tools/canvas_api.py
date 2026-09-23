"""Canvas API 客户端（只读）。

- 只有 GET 和下载。写请求（发帖、交作业）在 cc_write.py，只经预览和系统确认窗口发出；token 从哪读在 cc_token.py。
  token 不打印、不写盘、不进命令行参数；跳转到别的域名时去掉 Authorization。
- 域名来自 config.json 的 canvas_host（coach.py 传入）或环境变量 CANVAS_HOST。
- 出错抛异常（不 sys.exit），网络错误 / 429 / 5xx 有限重试，翻页有上限。

命令行（临时查询）：
  python canvas_api.py get "/api/v1/..." [out.json]     GET 并自动翻页，列表页合并
  python canvas_api.py download <file_id> <dest_dir>    按 id 下载课件（锁定的跳过并报 unlock_at）
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import brand


class CanvasError(Exception):
    pass


class CanvasAuthError(CanvasError):
    pass


class CanvasConfigError(CanvasError):
    pass


class CanvasPagingError(CanvasError):
    pass


RETRY_CODES = {429, 500, 502, 503, 504}


def utf8_stdout():
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")


class _StripAuthOffHost(urllib.request.HTTPRedirectHandler):
    def __init__(self, netloc):
        super().__init__()
        self.netloc = netloc

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlparse(newurl).netloc != self.netloc:
            new.remove_header("Authorization")
        return new


class Canvas:
    def __init__(self, host=None, tok=None, timeout=120, max_pages=50, retries=2):
        host = (host or os.environ.get("CANVAS_HOST") or "").strip().rstrip("/")
        if not host:
            raise CanvasConfigError("没有 canvas_host：写进 config.json，或设环境变量 CANVAS_HOST")
        if not host.startswith("http"):
            host = "https://" + host
        self.host = host
        self.netloc = urllib.parse.urlparse(host).netloc
        self.tok = tok
        self.timeout, self.max_pages, self.retries = timeout, max_pages, retries
        self.opener = urllib.request.build_opener(_StripAuthOffHost(self.netloc))

    def fetch(self, url, accept="application/json"):
        headers = {"Accept": accept, "User-Agent": f"{brand.SLUG}/2 (read-only)"}
        if self.tok and urllib.parse.urlparse(url).netloc == self.netloc:
            headers["Authorization"] = "Bearer " + self.tok
        delay = 2
        for attempt in range(self.retries + 1):
            try:
                with self.opener.open(urllib.request.Request(url, headers=headers), timeout=self.timeout) as r:
                    return r.headers, r.read()
            except urllib.error.HTTPError as e:
                if e.code not in RETRY_CODES or attempt == self.retries:
                    raise
                ra = e.headers.get("Retry-After") if e.headers else None
                wait = min(float(ra), 30) if ra and str(ra).replace(".", "", 1).isdigit() else delay
            except urllib.error.URLError:
                if attempt == self.retries:
                    raise
                wait = delay
            time.sleep(wait)
            delay *= 3
        raise CanvasError("unreachable")

    @staticmethod
    def _next_link(headers):
        for part in (headers.get("Link") or "").split(","):
            seg = part.split(";")
            if len(seg) >= 2 and 'rel="next"' in seg[1]:
                return seg[0].strip()[1:-1]
        return None

    def url_of(self, path):
        # Git Bash 会把开头的 "/api/..." 改写成 Windows 路径，这里恢复
        if not path.startswith("http") and "api/v1/" in path:
            path = "/" + path[path.index("api/v1/"):]
        url = path if path.startswith("http") else self.host + path
        if not url.startswith(self.host + "/api/v1/"):
            raise ValueError(f"refusing a non-API URL: {url.split('?')[0]}")
        return url

    def get(self, path, max_pages=None):
        url = self.url_of(path)
        items, obj, pages = [], None, 0
        limit = max_pages or self.max_pages
        while url:
            pages += 1
            if pages > limit:
                raise CanvasPagingError(f"分页超过 {limit} 页：{path.split('?')[0]}")
            headers, body = self.fetch(url)
            payload = json.loads(body.decode("utf-8") or "null")
            if isinstance(payload, list):
                items.extend(payload)
                url = self._next_link(headers)
            else:
                obj, url = payload, None
        return items if obj is None else obj

    def file_meta(self, file_id):
        meta = self.get(f"/api/v1/files/{file_id}")
        return meta[0] if isinstance(meta, list) and meta else meta

    def download(self, file_id, dest_dir, max_bytes=None):
        meta = self.file_meta(file_id)
        name = meta.get("display_name") or meta.get("filename") or str(file_id)
        if meta.get("locked_for_user") or not meta.get("url"):
            return {"locked": True, "name": name, "unlock_at": meta.get("unlock_at"),
                    "lock_explanation": meta.get("lock_explanation")}
        if max_bytes and (meta.get("size") or 0) > max_bytes:
            return {"skipped": f"{(meta.get('size') or 0) / 1e6:.0f}MB", "name": name}
        import cc_downloads  # 显示名只当文件名用，且必须落在 dest_dir 里
        _, body = self.fetch(meta["url"], accept="*/*")
        os.makedirs(dest_dir, exist_ok=True)
        dest = cc_downloads.safe_dest(dest_dir, name)
        with open(dest, "wb") as f:
            f.write(body)
        return {"saved": dest, "name": name, "bytes": len(body), "updated_at": meta.get("updated_at")}


def from_config():
    """优先用 config.json 里的域名；没有 config 时退回环境变量 CANVAS_HOST。"""
    host = home = None
    cfg = {}
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import cc_paths
        import cc_store
        home = cc_paths.home_dir()
        cfg = cc_store.jload(os.path.join(home, "config.json")) or {}
        host = cfg.get("canvas_host")
    except Exception:  # noqa: BLE001
        host = None
    import cc_session
    login = cc_session.read_login(home) if home else None
    if login and (login.get("lms") == "moodle" or cfg.get("lms") == "moodle"):  # Moodle 只能用登录
        import moodle_api
        return moodle_api.MoodleClient(host or login["host"], home)
    if login:  # 跑过 login：用浏览器里的登录，不用 token
        return cc_session.SessionCanvas(host or login["host"], home)
    import cc_token
    return Canvas(host, cc_token.token())


def main(argv=None):
    utf8_stdout()
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2 or argv[0] not in ("get", "download"):
        print(__doc__ + "\n写操作（post / upload）走 coach.py api，需用户逐次确认。")
        return 2
    try:
        api = from_config()
        if argv[0] == "get":
            data = api.get(argv[1])
            text = json.dumps(data, ensure_ascii=False, indent=1)
            if len(argv) > 2:
                with open(argv[2], "w", encoding="utf-8") as f:
                    f.write(text)
                n = len(data) if isinstance(data, list) else 1
                print(f"wrote {argv[2]} ({n} item(s), {len(text)} chars)")
            else:
                sys.stdout.buffer.write(text.encode("utf-8"))
        else:
            print(json.dumps(api.download(argv[1], argv[2]), ensure_ascii=False))
        return 0
    except urllib.error.HTTPError as e:
        print(json.dumps({"http_error": e.code, "path": argv[1].split("?")[0]}))
        return 1
    except urllib.error.URLError as e:
        print(json.dumps({"network_error": str(e.reason)}))
        return 1
    except (CanvasError, ValueError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    # 直接跑本文件时它叫 __main__；登记成 canvas_api，cc_token 里的 `from canvas_api import …` 就拿到同一份，
    # 抛出的 CanvasAuthError 才接得住（否则是另一份模块的类，main() 接不住，变成 traceback）
    sys.modules.setdefault("canvas_api", sys.modules[__name__])
    sys.exit(main())
