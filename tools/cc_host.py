"""认学校：域名规范化、按校名猜地址、不带 token 探测是 Canvas 还是 Moodle、用 token 找能登上的那个。

没有默认学校。HOST_HINTS 只是校名 → 地址的提示表，用户说了校名才查。
"""
import re
import urllib.error
import urllib.parse

import canvas_api

HOST_HINTS = [
    (("sydney", "usyd", "悉尼大学", "悉大"), "https://canvas.sydney.edu.au"),
    (("unimelb", "melbourne", "墨尔本大学", "墨大"), "https://canvas.lms.unimelb.edu.au"),
    (("uts", "悉尼科技"), "https://canvas.uts.edu.au"),
    (("adelaide", "阿德莱德"), "https://myuni.adelaide.edu.au"),
    (("rmit", "皇家墨尔本"), "https://rmit.instructure.com"),
    (("qut", "昆士兰科技"), "https://canvas.qut.edu.au"),
    (("newcastle", "纽卡斯尔"), "https://canvas.newcastle.edu.au"),
    (("flinders", "弗林德斯"), "https://canvas.flinders.edu.au"),
    (("swinburne", "斯威本"), "https://swinburne.instructure.com"),
    (("auckland", "奥克兰大学"), "https://canvas.auckland.ac.nz"),
    (("vuw", "wgtn", "惠灵顿维多利亚"), "https://nuku.wgtn.ac.nz"),
]


def normalize_host(url):
    """登录页 / 课程页网址 → scheme://域名。"""
    u = (url or "").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u):
        u = "https://" + u
    p = urllib.parse.urlparse(u)
    return f"{p.scheme}://{p.netloc}" if p.netloc else ""


def candidate_hosts(school):
    """校名 / 域名 → 可能的 Canvas 地址。只猜学校自己域名下的写法和提示表，token 不往无关网站发。"""
    key = (school or "").strip().lower()
    out = []
    for aliases, host in HOST_HINTS:
        if any(a in key for a in aliases):
            out.append(host)
    m = re.search(r"([a-z0-9-]+(?:\.[a-z0-9-]+)+)", key)
    if m:
        dom = re.sub(r"^(www|canvas|lms|learn|myuni|elearning)\.", "", m.group(1))
        out += [f"https://canvas.{dom}", f"https://lms.{dom}", f"https://learn.{dom}", f"https://myuni.{dom}", f"https://canvas.lms.{dom}"]
        first = dom.split(".")[0]
        if first and first not in ("edu", "ac"):
            out.append(f"https://{first}.instructure.com")
    elif re.fullmatch(r"[a-z0-9-]{2,30}", key):
        out.append(f"https://{key}.instructure.com")
    seen, uniq = set(), []
    for h in out:
        if h not in seen:
            seen.add(h)
            uniq.append(h)
    return uniq


def is_canvas(host):
    """不带 token 探一下：标准 Canvas 对 /api/v1/users/self 回 401；200 是普通网页；404 / HTML 不是。连不上返回 None。"""
    try:
        canvas_api.Canvas(host, None, timeout=15, retries=0).fetch(host + "/api/v1/users/self")
        return False
    except urllib.error.HTTPError as e:
        return e.code == 401
    except (urllib.error.URLError, OSError, ValueError):
        return None


# 站点根后面常见的路径：网址里出现它们，前面那段就是站点根（Moodle 可能带子目录，如 /moodle）；/courses、/api/ 是 Canvas 的
MOODLE_PATHS = ("/login/", "/my/", "/course/", "/mod/", "/user/", "/grade/", "/calendar/", "/auth/", "/admin/",
                "/lib/", "/blocks/", "/enrol/", "/message/", "/pluginfile.php", "/index.php", "/courses", "/api/")


def moodle_bases(url):
    """网址 → 可能的 Moodle 站点根：先带子目录的，再只有域名的。"""
    u = (url or "").strip()
    if not u:
        return []
    if not re.match(r"^https?://", u):
        u = "https://" + u
    p = urllib.parse.urlparse(u)
    if not p.netloc:
        return []
    origin = f"{p.scheme}://{p.netloc}"
    path = p.path or ""
    cuts = [i for i in (path.find(m) for m in MOODLE_PATHS) if i >= 0]
    prefix = (path[:min(cuts)] if cuts else path).rstrip("/")
    return ([origin + prefix] if prefix else []) + [origin]


def detect_lms(url):
    """不带任何凭据认平台：先问 Moodle 的公开配置，再看 Canvas 的 401。
    返回 ("moodle", wwwroot) | ("canvas", 域名) | (None, None)。"""
    try:
        import moodle_api
    except ImportError:
        moodle_api = None
    if moodle_api is not None:
        for base in moodle_bases(url):
            try:
                conf = moodle_api.public_config(base)
            except Exception:  # noqa: BLE001  连不上、不是 JSON：都当「不是 Moodle」
                conf = None
            if isinstance(conf, dict):
                root = str(conf.get("wwwroot") or "").rstrip("/")
                # 以站点自己报的 wwwroot 为准（可能带子目录）；报的是别的域名就不跟，只用用户给的这个
                same = urllib.parse.urlparse(root).netloc.lower() == urllib.parse.urlparse(base).netloc.lower()
                return "moodle", (root if root and same else base)
    origin = normalize_host(url)
    if origin and is_canvas(origin):
        return "canvas", origin
    return None, None


def find_host(tok, candidates):
    """在候选里找 token 能登上的那个。返回 (host, me, tried)。"""
    tried = []
    for h in candidates:
        ok = is_canvas(h)
        tried.append((h, "不是 Canvas" if ok is False else ("连不上" if ok is None else "是 Canvas")))
        if not ok:
            continue
        try:
            me = canvas_api.Canvas(h, tok, timeout=20, retries=0).get("/api/v1/users/self")
            return h, me, tried
        except urllib.error.HTTPError as e:
            tried[-1] = (h, f"token 无效（{e.code}）")
        except (urllib.error.URLError, OSError, canvas_api.CanvasError):
            tried[-1] = (h, "连不上")
    return None, None, tried
