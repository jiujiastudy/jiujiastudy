"""时间与时区：全部经 zoneinfo。课程时区 = Canvas 显示的时区；用户时区 = 用户人在哪。相同只显示一个。

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
_zone_data = None  # None = 还没查过
_noted = False


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

    # ---- now
    def now_utc(self):
        return dt.datetime.now(UTC).replace(microsecond=0)

    def now_user(self):
        return self.now_utc().astimezone(self.user_tz)

    def today_user(self):
        return self.now_user().date()

    # ---- formatting
    def fmt(self, t, date=True):
        if t is None:
            return "—"
        c, u = t.astimezone(self.course_tz), t.astimezone(self.user_tz)
        base = f"{c:%m-%d} {WD[c.weekday()]} " if date else ""
        if self.same:
            return f"{base}{c:%H:%M}"
        if c.utcoffset() == u.utcoffset():
            return f"{base}{c:%H:%M}"  # 两地此刻时间相同：不加标签，tz_note 里说明一次
        return f"{base}{c:%H:%M}（{self.course_label}）= {u:%H:%M}（{self.user_label}）"

    @staticmethod
    def fmt_date(d):
        return f"{d:%m-%d} {WD[d.weekday()]}"

    def stamp(self, t=None):
        t = (t or self.now_utc()).astimezone(self.user_tz)
        return f"{t:%Y-%m-%d %H:%M}（{self.user_label}）"

    @staticmethod
    def rel(d, today, cap=60):
        if d is None:
            return ""
        n = (d - today).days
        if n == 0:
            return "今天"
        if n == 1:
            return "明天"
        if n < 0:
            return f"已过 {-n} 天"
        return f"还有 {n} 天" if n <= cap else ""

    def when_rel(self, t, today):
        s = self.fmt(t)
        r = self.rel(self.course_date(t), today) if t else ""
        return f"{s}，{r}" if r else s

    # ---- conversions
    def course_date(self, t):
        return t.astimezone(self.course_tz).date() if t else None

    def user_date(self, t):
        return t.astimezone(self.user_tz).date() if t else None

    def course_local_to_utc(self, d, hhmm="00:00"):
        h, m = (int(x) for x in (hhmm or "00:00").split(":")[:2])
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
        """报告页眉的一句：时间按哪个时区；两地此刻不同才说先后；14 天内有夏令时切换才提。"""
        noon = dt.datetime.combine(today, dt.time(12), tzinfo=self.course_tz)
        diff = 0 if self.same else (noon.utcoffset() - noon.astimezone(self.user_tz).utcoffset()).total_seconds() / 3600
        s = f"时间为{self.course_label}时间" if diff == 0 else f"时间先{self.course_label}后{self.user_label}"
        zones = ((self.course_label, self.course_tz),) if self.same else ((self.course_label, self.course_tz), (self.user_label, self.user_tz))
        for label, zone in zones:
            tr = self.next_transition(today, days=14, tz=zone)
            if tr:
                d, h = tr
                base = dt.datetime.combine(today, dt.time(12), tzinfo=zone).utcoffset().total_seconds() / 3600
                s += f"，{d:%m-%d} 起{label}{'进入' if h > base else '结束'}夏令时"
        return s
