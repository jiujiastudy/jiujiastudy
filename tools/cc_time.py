"""时间与时区：全部经 zoneinfo。课程时区 = Canvas 显示的时区；用户时区 = 用户人在哪。相同只显示一个。

「现在」只有一个来源：Clock.now_utc()，--date 会把它钉在指定的那一刻。过没过期看这个时刻，
今天 / 明天 / 还有几天按显示的那个时区（用户那边）的日历天算，和显示的日期对得上。

没有任何城市的默认值：config 没写就用电脑时钟的时区，再没有才 UTC。
这台电脑的 Python 读不到任何时区数据（Windows 上没装 tzdata）时不装、不崩：按电脑时钟算并提示一句，装 tzdata 交给 doctor。
"""
import datetime as dt
import os
import re
import sys
import time
from zoneinfo import ZoneInfo

from deps import optional

UTC = dt.timezone.utc
WD = "周一 周二 周三 周四 周五 周六 周日".split()

TZ_LABELS_ZH = {
    "Australia/Sydney": "悉尼", "Australia/Melbourne": "墨尔本", "Australia/Brisbane": "布里斯班", "Australia/Perth": "珀斯",
    "Australia/Adelaide": "阿德莱德", "Australia/Hobart": "霍巴特", "Australia/Darwin": "达尔文", "Australia/Canberra": "堪培拉",
    "Pacific/Auckland": "奥克兰", "Asia/Shanghai": "北京", "Asia/Hong_Kong": "香港", "Asia/Taipei": "台北", "Asia/Singapore": "新加坡",
    "Asia/Kuala_Lumpur": "吉隆坡", "Asia/Tokyo": "东京", "Asia/Seoul": "首尔", "Asia/Kolkata": "印度", "Asia/Dubai": "迪拜",
    "Europe/London": "伦敦", "Europe/Dublin": "都柏林", "Europe/Paris": "巴黎", "Europe/Berlin": "柏林", "Europe/Amsterdam": "阿姆斯特丹",
    "Europe/Madrid": "马德里", "Europe/Rome": "罗马", "Europe/Zurich": "苏黎世", "Europe/Stockholm": "斯德哥尔摩",
    "America/New_York": "美东", "America/Chicago": "美中", "America/Denver": "美山区", "America/Los_Angeles": "美西",
    "America/Toronto": "多伦多", "America/Vancouver": "温哥华", "America/Edmonton": "埃德蒙顿", "America/Halifax": "哈利法克斯",
    "UTC": "UTC",
}

WIN_TO_IANA = {
    "AUS Eastern Standard Time": "Australia/Sydney", "E. Australia Standard Time": "Australia/Brisbane",
    "W. Australia Standard Time": "Australia/Perth", "Cen. Australia Standard Time": "Australia/Adelaide",
    "Tasmania Standard Time": "Australia/Hobart", "AUS Central Standard Time": "Australia/Darwin",
    "New Zealand Standard Time": "Pacific/Auckland", "China Standard Time": "Asia/Shanghai", "Taipei Standard Time": "Asia/Taipei",
    "Singapore Standard Time": "Asia/Singapore", "Tokyo Standard Time": "Asia/Tokyo", "Korea Standard Time": "Asia/Seoul",
    "India Standard Time": "Asia/Kolkata", "Arabian Standard Time": "Asia/Dubai", "GMT Standard Time": "Europe/London",
    "W. Europe Standard Time": "Europe/Berlin", "Romance Standard Time": "Europe/Paris", "Central Europe Standard Time": "Europe/Prague",
    "Central European Standard Time": "Europe/Warsaw", "E. Europe Standard Time": "Europe/Bucharest",
    "Eastern Standard Time": "America/New_York", "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver", "Pacific Standard Time": "America/Los_Angeles",
    "Atlantic Standard Time": "America/Halifax", "US Mountain Standard Time": "America/Phoenix", "Alaskan Standard Time": "America/Anchorage",
    "Hawaiian Standard Time": "Pacific/Honolulu", "UTC": "UTC",
}

RAILS_TO_IANA = {
    "Sydney": "Australia/Sydney", "Melbourne": "Australia/Melbourne", "Canberra": "Australia/Sydney", "Brisbane": "Australia/Brisbane",
    "Perth": "Australia/Perth", "Adelaide": "Australia/Adelaide", "Hobart": "Australia/Hobart", "Darwin": "Australia/Darwin",
    "Auckland": "Pacific/Auckland", "Wellington": "Pacific/Auckland", "Beijing": "Asia/Shanghai", "Hong Kong": "Asia/Hong_Kong",
    "Taipei": "Asia/Taipei", "Singapore": "Asia/Singapore", "Kuala Lumpur": "Asia/Kuala_Lumpur", "Tokyo": "Asia/Tokyo",
    "Seoul": "Asia/Seoul", "Mumbai": "Asia/Kolkata", "New Delhi": "Asia/Kolkata", "Abu Dhabi": "Asia/Dubai",
    "London": "Europe/London", "Edinburgh": "Europe/London", "Dublin": "Europe/Dublin", "Paris": "Europe/Paris",
    "Berlin": "Europe/Berlin", "Amsterdam": "Europe/Amsterdam", "Madrid": "Europe/Madrid", "Rome": "Europe/Rome",
    "Bern": "Europe/Zurich", "Stockholm": "Europe/Stockholm", "Eastern Time (US & Canada)": "America/New_York",
    "Central Time (US & Canada)": "America/Chicago", "Mountain Time (US & Canada)": "America/Denver",
    "Pacific Time (US & Canada)": "America/Los_Angeles", "Atlantic Time (Canada)": "America/Halifax",
    "Arizona": "America/Phoenix", "Alaska": "America/Anchorage", "Hawaii": "Pacific/Honolulu", "UTC": "UTC",
}


IANA_NAME = re.compile(r"^[A-Za-z]+(?:/[A-Za-z0-9_+\-]+){1,2}$")
HAS_CLOCK = re.compile(r"\d[T ]\s*\d{1,2}:\d{2}")  # --date 里写没写到时分
FULLWIDTH = str.maketrans("０１２３４５６７８９：．／－　", "0123456789:./- ")
_zone_data = None  # None = 还没查过
_noted = False
_pinned = None  # --date 给的值；之后建的 Clock 把「现在」钉在它上面


def zone_data_available(refresh=False):
    """zoneinfo 能不能读到时区（系统时区库或 tzdata 包）。doctor 装完 tzdata 后用 refresh=True 重查。"""
    global _zone_data
    if _zone_data is None or refresh:
        try:
            ZoneInfo("UTC")
            _zone_data = True
        except Exception:  # noqa: BLE001
            _zone_data = False
    return _zone_data


class MachineClockZone(dt.tzinfo):
    """没有任何时区数据时的退路：按这台电脑的时钟算（本地夏令时由系统负责）。
    课程所在地和电脑时区不同时会差几个小时，所以用到它时 ensure_zone 会提示一句。"""
    LABEL = "电脑时钟"
    _EPOCH = dt.datetime(1970, 1, 1)

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"MachineClockZone({self.name!r})"

    @staticmethod
    def _offset(ts):
        try:
            return dt.timedelta(seconds=time.localtime(ts).tm_gmtoff)
        except (OverflowError, OSError, ValueError):
            return dt.timedelta(seconds=time.localtime().tm_gmtoff)

    def utcoffset(self, t):
        if t is None:
            return self._offset(time.time())
        try:
            ts = time.mktime(t.replace(tzinfo=None).timetuple())
        except (OverflowError, OSError, ValueError):
            ts = time.time()
        return self._offset(ts)

    def dst(self, t):
        return dt.timedelta(0)

    def tzname(self, t):
        return self.name

    def fromutc(self, t):
        return (t + self._offset((t.replace(tzinfo=None) - self._EPOCH).total_seconds())).replace(tzinfo=self)


def _note_no_zone_data(name):
    global _noted
    if _noted:
        return
    _noted = True
    off = int(time.localtime().tm_gmtoff) // 60
    sign, off = ("+" if off >= 0 else "-"), abs(off)
    print(f"[提示] 这台电脑的 Python 缺时区数据（tzdata），{name} 暂按电脑时钟（现在 UTC{sign}{off // 60:02d}:{off % 60:02d}）算，"
          "课程所在地和电脑时区不同时会差几个小时；跑一次 doctor 会装上 tzdata。", file=sys.stderr)


def ensure_zone(name):
    """IANA 名 → tzinfo。缺时区数据时不装、不崩：UTC 照常，其余按电脑时钟算并提示一句；装 tzdata 只由 doctor 做。"""
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001
        if name in ("UTC", "Etc/UTC"):
            return UTC
        _note_no_zone_data(name)
        return MachineClockZone(name)


def normalize_zone(name):
    """IANA 名原样；Canvas 的 Rails 时区名（如 Sydney）、Windows 时区名转成 IANA；认不出返回 None。"""
    if not name:
        return None
    s = str(name).strip()
    if s in RAILS_TO_IANA:
        return RAILS_TO_IANA[s]
    if s in WIN_TO_IANA:
        return WIN_TO_IANA[s]
    try:
        ZoneInfo(s)
        return s
    except Exception:  # noqa: BLE001
        # 读不到任何时区数据时，形状像 IANA 的名字照收，交给 ensure_zone 按电脑时钟算
        return s if not zone_data_available() and IANA_NAME.match(s) else None


def machine_zone():
    """电脑时钟的 IANA 时区：tzlocal → Windows 注册表 → /etc/localtime → TZ 环境变量 → None。"""
    try:
        tzlocal = optional("tzlocal")
        z = tzlocal.get_localzone_name() if tzlocal else None
        if normalize_zone(z):
            return z
    except Exception:  # noqa: BLE001
        pass
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation") as k:
                name = winreg.QueryValueEx(k, "TimeZoneKeyName")[0]
            return WIN_TO_IANA.get(name)
        except OSError:
            return None
    try:
        target = os.readlink("/etc/localtime")
        if "zoneinfo/" in target:
            z = target.split("zoneinfo/", 1)[1]
            return z if normalize_zone(z) else None
    except OSError:
        pass
    return normalize_zone(os.environ.get("TZ"))


def zone_label(name, labels=None):
    if not name:
        return "本地"
    return (labels or {}).get(name) or TZ_LABELS_ZH.get(name) or name.split("/")[-1].replace("_", " ")


def parse_ts(s):
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(UTC)


def parse_date(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def monday_of(d):
    return d - dt.timedelta(days=d.weekday())


# ---- 用户手写的日期和时刻（--date、record deadline 的 --due / --time）----
def moment_ok(s):
    """--date 的值写得对不对：YYYY-MM-DD，或写到时分的时刻（2026-09-25T23:59+10:00）。"""
    return bool(parse_date(s)) and (parse_ts(s) is not None if HAS_CLOCK.search(str(s)) else True)


def pin_now(s):
    """把「现在」钉在 --date 给的那一刻：之后建的每个 Clock 都用它，日期、剩余天数、过没过期全从它算。"""
    global _pinned
    _pinned = str(s).strip() if s else None


def norm_hhmm(s):
    """时刻 → "HH:MM"：认 23:59、16.00、16：00、4pm、11:59pm、24:00（= 当天最后一刻）；认不出返回 None。"""
    s = str(s or "").translate(FULLWIDTH).strip().lower().replace(" ", "")
    m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{1,2}))?(a\.?m\.?|p\.?m\.?)?", s)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "")[:1]
    if ap:
        if not 1 <= h <= 12 or mi > 59:
            return None
        h = h % 12 + (12 if ap == "p" else 0)
    elif (h, mi) == (24, 0):
        h, mi = 23, 59
    elif h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


def norm_date(s, today):
    """日期 → date：认 2026-09-20、2026/9/20、09-20、9.20；不写年份就补今年，补出来太久以前的算明年。认不出返回 None。"""
    m = re.fullmatch(r"(?:(\d{4})[-/.])?(\d{1,2})[-/.](\d{1,2})", str(s or "").translate(FULLWIDTH).strip())
    if not m:
        return None
    year, mo, day = m.group(1), int(m.group(2)), int(m.group(3))
    for y in ([int(year)] if year else [today.year, today.year + 1]):
        try:
            d = dt.date(y, mo, day)
        except ValueError:
            return None
        if year or (d - today).days >= -30:
            return d
    return None


class Clock:
    def __init__(self, cfg):
        cfg = cfg or {}
        ctz = normalize_zone(cfg.get("course_tz")) or normalize_zone(machine_zone() or "") or "UTC"
        raw_utz = cfg.get("user_tz")
        self.user_auto = raw_utz in (None, "", "auto")  # 显示时区跟着电脑时钟走；config set user_tz <IANA> 可固定
        utz = (normalize_zone(machine_zone() or "") if self.user_auto else normalize_zone(raw_utz)) or ctz
        self.course_name, self.user_name = ctz, utz
        self.course_tz, self.user_tz = ensure_zone(ctz), ensure_zone(utz)
        labels = cfg.get("tz_labels") or {}
        self.course_label = zone_label(ctz, labels)
        self.user_label = zone_label(utz, labels)
        if isinstance(self.course_tz, MachineClockZone):
            self.course_label = MachineClockZone.LABEL
        if isinstance(self.user_tz, MachineClockZone):
            self.user_label = MachineClockZone.LABEL
        self.same = ctz == utz or self.course_label == self.user_label == MachineClockZone.LABEL
        term = cfg.get("term")
        if not isinstance(term, dict):
            term = {"start": cfg.get("term_start"), "end": cfg.get("term_end"), "week1_monday": cfg.get("term_start"), "break": None}
        self.term = term
        if _pinned:
            t = self._moment(_pinned)
            if t:
                self.now_utc = lambda: t  # 钉在这个 Clock 上（不改类）：之后「现在」只有这一个来源

    # ---- now
    def now_utc(self):
        return dt.datetime.now(UTC).replace(microsecond=0)

    def _moment(self, s):
        """--date 的值 → UTC 时刻：写到时分就按写的算（没写时区按用户时区），只写日期就是那天的此时此刻。"""
        if HAS_CLOCK.search(s):
            try:
                t = dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
            except ValueError:
                return None
            t = t.replace(tzinfo=self.user_tz) if t.tzinfo is None else t
            return t.astimezone(UTC).replace(microsecond=0)
        d = parse_date(s)
        return dt.datetime.combine(d, self.now_utc().astimezone(self.user_tz).timetz()).astimezone(UTC) if d else None

    def now_user(self):
        return self.now_utc().astimezone(self.user_tz)

    def today_user(self):
        return self.now_user().date()

    # ---- formatting
    def fmt(self, t, date=True):
        """显示用户那边的日期和时刻（人在哪，看到的就是哪里的时间）；不再解释两地差几个小时。
        两地时间相同时和原来一样。"""
        if t is None:
            return "—"
        u = t.astimezone(self.course_tz if self.same else self.user_tz)
        return (f"{u:%m-%d} {WD[u.weekday()]} " if date else "") + f"{u:%H:%M}"

    @staticmethod
    def fmt_date(d):
        return f"{d:%m-%d} {WD[d.weekday()]}"

    def stamp(self, t=None):
        t = (t or self.now_utc()).astimezone(self.user_tz)
        return f"{t:%Y-%m-%d %H:%M}（{self.user_label}）"

    def days_ahead(self, t, now=None):
        """显示的时区里，t 落在此刻之后的第几个日历天（0 = 今天，负数 = 已经过去的天数）。和 fmt 显示的日期用同一个时区，两边才对得上。"""
        return (self.show_date(t) - self.show_date(now or self.now_utc())).days

    def rel(self, t, now=None, cap=60):
        """剩余：过没过看真实时刻（差一小时也算过了），今天 / 明天 / 还有几天按课程时区的日历天数。"""
        if t is None:
            return ""
        now = now or self.now_utc()
        n = self.days_ahead(t, now)
        if t <= now:
            return f"已过 {-n} 天" if n < 0 else "已过期"
        return "今天" if n == 0 else "明天" if n == 1 else (f"还有 {n} 天" if n <= cap else "")

    def when_rel(self, t, now=None):
        s = self.fmt(t)
        r = self.rel(t, now) if t else ""
        return f"{s}，{r}" if r else s

    # ---- conversions
    def course_date(self, t):
        return t.astimezone(self.course_tz).date() if t else None

    def show_date(self, t):
        """给人看的日期：和 fmt 同一个时区（两地相同时就是课程时区）。deadline 分天、排哪天做都用它。"""
        return t.astimezone(self.course_tz if self.same else self.user_tz).date() if t else None

    def user_date(self, t):
        return t.astimezone(self.user_tz).date() if t else None

    def course_local_to_utc(self, d, hhmm="00:00"):
        """课程时区的某天某时刻 → UTC。时刻写错了当 00:00，绝不抛异常（写错的那行由调用方标出来）。"""
        h, m = (int(x) for x in (norm_hhmm(hhmm) or "00:00").split(":"))
        return dt.datetime.combine(d, dt.time(h, m), tzinfo=self.course_tz).astimezone(UTC)

    # ---- term
    def week1(self):
        return parse_date(self.term.get("week1_monday"))

    def break_range(self):
        brk = self.term.get("break") or ""
        if ".." in brk:
            a, b = (parse_date(x) for x in brk.split(".."))
            if a and b:
                return a, b
        return None

    def week_no(self, d):
        w1 = self.week1()
        if not w1:
            return None
        n = (d - w1).days // 7 + 1
        br = self.break_range()
        if br:
            b0, b1 = br
            if b0 <= d <= b1:
                return None
            if d > b1:
                n -= 1
        return n

    def term_week(self, d):
        if not self.week1():
            return "周次待定"
        br = self.break_range()
        if br and br[0] <= d <= br[1]:
            return "期中假"
        n = self.week_no(d)
        end = parse_date(self.term.get("end"))
        if n is None or n < 1 or (end and d > end + dt.timedelta(days=14)):
            return "学期外"
        tag = "" if self.term.get("week_source") in ("config", "user") else "（推断）"
        return f"第 {n} 周{tag}"

    # ---- DST notes
    def next_transition(self, today, days=120, tz=None):
        zone = tz or self.user_tz

        def off(d):
            return dt.datetime.combine(d, dt.time(12), tzinfo=zone).utcoffset()
        base = off(today)
        for i in range(1, days + 1):
            d = today + dt.timedelta(days=i)
            o = off(d)
            if o != base:
                return d, o.total_seconds() / 3600
        return None

    def tz_note(self, today):
        """页眉里关于时区的说明。发起人 2026-09-23：时间没那么重要，只要让人知道是什么时候出的；
        不解释时区、不提夏令时（每行时间已是用户那边的）。留着这个方法，调用处不用改。"""
        return ""


# ---- 公告正文里写明的日期（作业页没写 due_at 时才用）----
_MONTHS = {m: i for i, ms in enumerate(
    [("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",), ("june", "jun"),
     ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"), ("october", "oct"),
     ("november", "nov"), ("december", "dec")], start=1) for m in ms}
_MON_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DMY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + _MON_RE + r")\.?(?:\s*,?\s*(\d{4}))?\b", re.I)
_MDY = re.compile(r"\b(" + _MON_RE + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{4}))?\b", re.I)
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_TIME = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?m\.?\b|\b(\d{1,2}):(\d{2})\b", re.I)
_PAREN = re.compile(r"\(([^)]{0,24})\)")


def _near_time(text, lo, hi):
    """日期前后各 40 个字符里找时间；找不到返回 None。"""
    m = _TIME.search(text[max(0, lo - 40):hi + 40])
    if not m:
        return None
    if m.group(3):
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
        h = 0 if (ap == "a" and h == 12) else (h + 12 if ap == "p" and h != 12 else h)
    else:
        h, mi = int(m.group(4)), int(m.group(5))
    return "%02d:%02d" % (h, mi) if 0 <= h <= 23 and 0 <= mi <= 59 else None


def _with_year(month, day, year, ref):
    """没写年份时取离参考日期最近的那一年；写了年份就照写。"""
    best = None
    for y in ([year] if year else [ref.year - 1, ref.year, ref.year + 1]):
        try:
            d = dt.date(int(y), month, day)
        except ValueError:
            continue
        if best is None or abs((d - ref).days) < abs((best - ref).days):
            best = d
    return best


def text_datetimes(text, ref_date):
    """从一段文字里找出写明的日期，返回 [(date, "HH:MM" 或 None), ...]，按出现先后去重。

    只认写出月份名或 ISO 的写法（25 September 2026 / Sep 25, 2026 / 2026-09-25）。
    9/25 这类纯数字日期各国月日顺序不同，含糊，一律不认。
    """
    if not text:
        return []
    # 「25 September (Friday) 2026」里的星期去掉，年份才接得上；
    # 「(25 September @11.59pm)」这种把日期写在括号里的，内容留下。
    s = _PAREN.sub(lambda m: " " + m.group(1) + " " if re.search(r"\d", m.group(1)) else " ", str(text))
    found, seen = [], set()
    for rx, kind in ((_DMY, "dmy"), (_MDY, "mdy"), (_ISO, "iso")):
        for m in rx.finditer(s):
            if kind == "iso":
                try:
                    d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError:
                    continue
            else:
                day, mon, year = (m.group(1), m.group(2), m.group(3)) if kind == "dmy" else (m.group(2), m.group(1), m.group(3))
                mon = _MONTHS.get(mon.lower())
                d = _with_year(mon, int(day), year, ref_date) if mon else None
            if not d or d in seen:
                continue
            seen.add(d)
            found.append((m.start(), d, _near_time(s, m.start(), m.end())))
    found.sort()
    return [(d, t) for _, d, t in found]
