"""本周清单：plans/<周>.json → reports/周报_<周>.html（资料夹根目录另存一份周手帐，文件名见 cc_paths.WEEK_PAGE）+ plans/<周>.md。

JSON 是唯一真源；用户回「做完了」时改 JSON 的 status 再重新生成。页面样式全部来自 design.py，规范见 references/style.md。
Usage: python render_week.py <plans/2026-W38.json> <reports/周报_2026-W38.html> [week_no]
"""
import datetime as dt
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brand  # noqa: E402
from cc_paths import WEEK_PAGE  # noqa: E402
from cc_store import save_text  # noqa: E402
from design import foot, head, status, tag  # noqa: E402
from htmlkit import esc, link, rich  # noqa: E402

MD_MARK = "<!-- coach:week -->"
CN_NUM = "零一二三四五六七八九十"
GENERIC_IF_THEN = "如果今天做不完，明天第一件事继续，不排别的。"
BUCKETS = (("上课前要看的", "before_class"), ("要做的练习或小测", "todo"), ("与 deadline 相关的事", "deadline_related"))
STUDY_BUCKETS = (("课前看", "before_class"), ("要做", "todo"))
WHEN_TAIL = re.compile(r"（(\d{2}-\d{2}) 周.(?:\s*(\d{1,2}:\d{2}))?）\s*$")

# 周报的手帐布局：沿用公共颜色和字号，只调整层次、留白与对齐。
JOURNAL_CSS = """
.page{max-width:calc(35em + 2 * var(--s4));line-height:1.7}
.top h1{font-size:var(--fs-l);font-weight:500}
.page>section{margin-top:var(--s7)}
.page>section.hero{margin-top:var(--s6)}
.card,.card.flush{padding:0;border:0;border-radius:0;background:transparent;box-shadow:none}
.hero h3{font-size:var(--fs-xl);font-weight:600;line-height:1.45;margin-top:var(--s3)}
.hero h3 .code{display:block;margin-bottom:var(--s2)}
.hero h3 a{color:var(--ink)}
.hero .kicker{color:var(--muted)}
.hero .meta,.hero .sub{margin-top:var(--s3)}
.status{padding:0;background:transparent;font-size:var(--fs-s)}
.status b{font-weight:500}
.today .must{font-size:var(--fs-m);font-weight:500}
.courses{grid-template-columns:1fr;gap:var(--s7)}
.course h3{font-weight:500}
.rows>li{padding:var(--s3) 0}
.days>li{padding:var(--s4) 0}
.days .must{font-weight:400}
.days>li.is-today{background:transparent}
.days>li.is-today+li{border-top-color:var(--line)}
.sub{margin-left:0}
.today details.fold{margin-left:0}
.scroll,.meta,.d,.rel,.m{font-variant-numeric:tabular-nums}
.toast,.theme{box-shadow:none}
"""


def cn(n):
    return CN_NUM[n] if 0 <= n <= 10 else str(n)


def iso_week_monday(week):
    """'2026-W38' → 该 ISO 周的周一。"""
    try:
        y, w = week.upper().split("-W")
        return dt.date.fromisocalendar(int(y), int(w), 1)
    except (ValueError, AttributeError):
        return None


def _norm(s):
    return re.sub(r"[\W_]+", "", str(s or "")).lower()


def _strip_when(text, date):
    """必做末尾的「（09-15 周二 16:00）」和这一行的日期重复：去掉，时间单独返回。"""
    text = text or ""
    m = WHEN_TAIL.search(text)
    if m and date and m.group(1) == date[5:10]:
        return text[:m.start()].rstrip(), m.group(2)
    return text, None


def _day_parts(d):
    """一天的必做：(正文, 时间点, 另外定死的时间点 [(时间, 文字)])。被必做覆盖的时间点只留时间标签。"""
    date = d.get("date") or ""
    must, t = _strip_when(d.get("must"), date)
    extra = []
    for f in d.get("fixed") or []:
        m = re.match(r"\s*(\d{1,2}:\d{2})\s+(.*)$", f or "")
        if not m:
            extra.append((None, f))
            continue
        rest = re.sub(r"\s*截止\s*$", "", m.group(2))
        if _norm(rest) and _norm(rest) in _norm(must):
            t = t or m.group(1)
        else:
            extra.append((m.group(1), m.group(2)))
    return must, t, extra


def _box(tick, label, done, item=False, id_=None):
    a = [f'data-tick="{esc(tick)}"', f'data-label="{esc(label)}"']
    if id_:
        a.insert(0, f'id="{esc(id_)}"')
    if item:
        a.append("data-item")
    if done:
        a.append("checked data-done")
    return f'<input type="checkbox" {" ".join(a)}>'


def _pill(t):
    return tag(t, "hl") + " " if t else ""


def _item_meta(it):
    if it.get("locked"):
        ua = (it.get("unlock_at") or "")[:10]
        return f"未解锁 · {ua[5:]} 开" if ua else "未解锁"
    return f"{it['minutes']} 分钟" if it.get("minutes") else ""


def _item_row(it):
    iid = it["id"]
    return (f'<li data-row>{_box(iid, iid, it.get("status") == "✅", item=True, id_="k" + iid)}'
            f'<span class="t"><label class="v" for="k{esc(iid)}">{esc(it.get("verb"))}</label>{link(it.get("url"), it.get("title"))}</span>'
            f'<span class="m num">{esc(_item_meta(it))}</span></li>')


def _dl_row(x):
    dl = x.get("days_left")
    soon = dl is not None and dl <= 3
    w = x.get("weight") if x.get("weight") not in (None, "", "—") else ""
    meta = " · ".join(v for v in (x.get("when"), w) if v)
    tags = (tag("待确认", "warn") if x.get("pending") and dl is not None else "") + (tag("已过期", "bad") if dl is not None and dl < 0 else "")
    iid = x.get("id")
    box = _box(iid, iid, x.get("status") == "✅", item=True, id_="k" + iid) if iid else "<span></span>"
    rel = f'<span class="rel{" soon" if soon else ""}">{esc(x.get("rel"))}</span>' if x.get("rel") else ""
    return (f'<li data-row>{box}<span class="t">{rel}<span class="code">{esc(x.get("course"))}</span> {link(x.get("url"), x.get("title"))}{tags}</span>'
            f'<span class="m num">{esc(meta)}</span></li>')


def render(r, week_no=None, n_courses=None):
    st = r.get("study") or {}
    courses = st.get("courses") or []
    week_no = week_no or r.get("week_no")
    inferred = (r.get("week_source") or st.get("week_source")) == "modules"
    days = r.get("days") or []
    gen = r.get("generated") or ""
    name = f"第 {week_no} 周" if week_no else (r.get("title") or "本周")
    o = [head(f"{brand.NAME} · {name}", r.get("week", "week"), app=brand.SLUG, extra_css=JOURNAL_CSS)]

    # ---- 页头：周次、时间范围、数据截至、口号、进度
    rng = re.sub(r"\s*周[一二三四五六日]", "", re.sub(r"\s*·\s*\d+\s*门课\s*$", "", r.get("range") or ""))
    meta = [x for x in (rng, r.get("canvas_check"), r.get("tz_note"), "周次是推断的" if inferred else "") if x]
    o.append(f'<header class="top"><h1>{esc(name)}</h1><p class="meta num">{esc(" · ".join(meta))}</p>'
             + (f'<p class="lead">{esc(r["mantra"])}</p>' if r.get("mantra") else "")
             + ('<div class="progress" data-progress><div class="bar"><div class="fill"></div></div><span class="ptxt"></span></div>' if courses else "")
             + "</header>")
    o.append(status(r.get("state")))

    # ---- 今天 + 本周最要紧（是同一件事就只出现一次）
    tops = r.get("top") or []
    hero = st.get("top_one") or (tops[0] if tops else None)
    today = next((d for d in days if d.get("date") == gen), None)
    same = bool(hero and today and ((hero.get("id") and hero.get("id") == today.get("must_item_id"))
                                    or (_norm(hero.get("title")) and _norm(hero.get("title")) in _norm(today.get("must")))))
    if today and today.get("must"):
        must, t, extra = _day_parts(today)
        kick = f"今天 · {gen[5:]} {today.get('weekday') or ''}".rstrip() + (" · 也是本周最要紧的一件" if same else "")
        o.append(f'<section class="card today" data-today="{esc(gen)}"><p class="kicker">{esc(kick)}</p>'
                 f'<label class="must" data-row>{_box(today["date"], today["date"][5:], today.get("status") == "✅")}'
                 f'<span class="t">{_pill(t)}{rich(must)}</span></label>'
                 + "".join(f'<p class="sub meta">{_pill(tm)}{rich(x)}</p>' for tm, x in extra)
                 + (f'<p class="sub meta">第一步：{rich(today["must_first_step"])}</p>' if today.get("must_first_step") else "")
                 + (f'<details class="fold"><summary>有空再做 {len(today["should"])} 件</summary><ul class="plain">'
                    + "".join(f"<li>{rich(x)}</li>" for x in today["should"]) + "</ul></details>" if today.get("should") else "")
                 + (f'<p class="sub meta">{rich(today["revise"])}</p>' if today.get("revise") else "")
                 + "</section>")
    if hero and not same:
        bits = [x for x in (hero.get("when"), hero.get("why")) if x]
        o.insert(2, '<section class="card hero"><p class="kicker">本周最要紧</p>'
                 f'<h3><span class="code">{esc(hero.get("course"))}</span> {link(hero.get("url"), hero.get("title"))}</h3>'
                 + (f'<p class="meta num">{esc(" · ".join(bits))}</p>' if bits else "")
                 + (f'<p class="sub">第一步：{rich(hero["first_step"])}</p>' if hero.get("first_step") else "")
                 + "</section>")

    # ---- deadline：两周内按时间排；Canvas 没写日期的折起来
    dls = [dict(it, course=c.get("code")) for c in courses for it in (c.get("deadline_related") or [])]
    if not dls:
        dls = [{"course": x.get("course"), "title": x.get("item"), "when": x.get("when"), "rel": x.get("rel"), "days_left": x.get("days_left"),
                "weight": x.get("weight"), "pending": x.get("pending"), "url": x.get("url")} for x in r.get("deadlines") or []]
    dated = sorted([x for x in dls if x.get("days_left") is not None], key=lambda x: x["days_left"])
    undated = [x for x in dls if x.get("days_left") is None]
    if dls:
        o.append('<section><h2>Deadline · 两周内</h2>'
                 + ('<div class="card flush"><ul class="rows">' + "".join(_dl_row(x) for x in dated) + "</ul></div>"
                    if dated else '<p class="meta">两周内没有写了日期的 deadline。</p>')
                 + (f'<p class="callout end-gap">{rich(r["clash"])}</p>' if r.get("clash") else "")
                 + (f'<details class="fold"><summary>Canvas 没写日期的 {len(undated)} 条，以 Canvas 和老师为准</summary>'
                    '<div class="card flush"><ul class="rows">' + "".join(_dl_row(x) for x in undated) + "</ul></div></details>" if undated else "")
                 + "</section>")

    # ---- 每天
    if days:
        o.append('<section><h2>每天</h2><div class="card flush"><ol class="days">')
        for d in days:
            date = d.get("date") or ""
            must, t, extra = _day_parts(d)
            try:
                dom = str(int(date[8:10]))
            except ValueError:
                dom = date[5:]
            subs = "".join(f'<p class="sub meta">{_pill(tm)}{rich(x)}</p>' for tm, x in extra)
            if d.get("should"):
                subs += f'<p class="sub meta">有空再做：{"；".join(rich(x) for x in d["should"])}</p>'
            if d.get("revise"):
                subs += f'<p class="sub meta">{rich(d["revise"])}</p>'
            o.append(f'<li data-date="{esc(date)}" data-row><div class="d">{esc(dom)}<span>{esc(d.get("weekday"))}</span></div><div>'
                     f'<label class="must">{_box(date, date[5:], d.get("status") == "✅")}<span class="t">{_pill(t)}{rich(must)}</span></label>'
                     f"{subs}</div></li>")
        o.append("</ol></div></section>")

    # ---- 每门课这周要学的（deadline 已经在上面，这里不重复）
    if courses:
        o.append('<section><h2>这周要学的</h2><div class="courses">')
        for c in courses:
            ex = c.get("exam") or {}
            exam = tag(f"考试 {str(ex.get('when'))[:5]} · 还有 {ex['days_left']} 天", "hl") if ex.get("when") and ex.get("days_left") is not None else ""
            body = []
            for lab, key in STUDY_BUCKETS:
                items = c.get(key) or []
                if items:
                    body.append(f'<p class="blabel">{lab}</p><ul class="rows">' + "".join(_item_row(it) for it in items) + "</ul>")
            if not body and not c.get("gap"):
                body.append('<p class="sub meta">这周模块里没有要看的课件。</p>')
            notes = c.get("notes") or []
            if notes:
                body.append(f'<details class="fold"><summary>公告 {len(notes)} 条</summary><ul class="plain">'
                            + "".join(f'<li><span class="num">{esc(x.get("when"))}</span> {link(x.get("url"), x.get("title"))}</li>' for x in notes[:5])
                            + "</ul></details>")
            if c.get("gap"):
                body.append(f'<p class="sub meta">{rich(c["gap"])}</p>')
            o.append(f'<article class="card course" data-group><p class="code">{esc(c.get("code"))}{tag("本周完成", "good done-mark")}{exam}</p>'
                     f'<h3>{esc(c.get("name"))}</h3>' + (f'<p class="meta">{esc(c.get("topic"))}</p>' if c.get("topic") else "")
                     + (f'<p class="meta">课：{rich(c["class"])}</p>' if c.get("class") else "") + "".join(body) + "</article>")
        o.append("</div></section>")

    # ---- 很少出现的几块
    if r.get("parking"):
        o.append('<section><h2>停车场</h2><ul class="plain">'
                 + "".join(f"<li>{esc(p.get('date') or '') if isinstance(p, dict) else ''} {rich(p.get('text') if isinstance(p, dict) else str(p))}</li>"
                           for p in r["parking"]) + "</ul></section>")
    if r.get("courses"):  # 旧版手写周报的每门课
        o.append('<section><h2>每门课</h2><div class="courses">')
        for c in r["courses"]:
            o.append(f'<article class="card"><p class="code">{esc(c.get("code"))}</p><h3>{esc(c.get("name"))}</h3>'
                     + (f'<p class="meta">{esc(c.get("topic"))}</p>' if c.get("topic") else "")
                     + '<ul class="plain">' + "".join(f"<li>{rich(x)}</li>" for x in (c.get("items") or []) + (c.get("notes") or [])) + "</ul>"
                     + "".join(f'<p class="sub meta">{tag("待确认", "warn")}{esc(x)}</p>' for x in c.get("confirm") or []) + "</article>")
        o.append("</div></section>")
    if r.get("review"):
        o.append(f'<section><h2>回我一句</h2><p>{rich(r["review"])}</p></section>')
    o.append('<section class="end"><details class="fold"><summary>资料来源</summary><ul class="plain">'
             + "".join(f"<li>{esc(s.get('label'))}：{rich(s.get('ref'))}</li>" for s in r.get("sources") or [])
             + "<li>标了待确认的，以 Canvas、课表和老师的答复为准。</li></ul></details></section>")
    o.append('<div class="toast" data-toast hidden><span></span><button type="button">复制</button></div>')
    return "\n".join(o) + foot()


def to_markdown(r, week_no=None, generated=None):
    L = [MD_MARK, f"# {r.get('title', '周计划')}（{r.get('range', '')}）", "",
         f"> 生成 {generated or dt.date.today().isoformat()}{' · 学期第 ' + str(week_no) + ' 周' if week_no else ''} · {r.get('tz_note', '')}",
         "> 📦 = 已交付；✅ = 你确认做了。做完回「做完了」「做完了 编号」或「✓ 09-16」。", ""]
    if r.get("mantra"):
        L += [f"**今日心法** ——「{r['mantra']}」", ""]
    if r.get("canvas_check"):
        L += [r["canvas_check"], ""]
    st = r.get("study") or {}
    if st.get("courses"):
        L.append("## 这周该学什么")
        if st.get("top_one"):
            t = st["top_one"]
            L.append(f"本周最要紧的一件：**{t.get('course')} {t.get('title')}**（{t.get('why')}）。第一步：{t.get('first_step')}")
        for c in st["courses"]:
            L.append(f"\n### {c.get('code')} {c.get('name') or ''}" + (f"（{c['topic']}）" if c.get("topic") else ""))
            for label, key in BUCKETS:
                items = c.get(key) or []
                if items:
                    L.append(f"- {label}：")
                    for it in items:
                        extra = f"，{it['when']}{'，' + it['rel'] if it.get('rel') else ''}" if it.get("when") else (f"，{it['minutes']} 分钟" if it.get("minutes") else "")
                        L.append(f"  - [{'x' if it.get('status') == '✅' else ' '}] {it['id']} {it.get('verb')}：{it.get('title')}{extra}" + (f"（{it['url']}）" if it.get("url") else ""))
            for n in (c.get("notes") or [])[:3]:
                L.append(f"- 公告 {n.get('when')}：{n.get('title')}")
            if c.get("gap"):
                L.append(f"- ⚠️ {c['gap']}")
        L.append("")
    if r.get("top"):
        L.append("## 这周最要紧的三件事")
        for i, t in enumerate(r["top"], 1):
            L.append(f"{i}. **[{t.get('course')}] {t.get('title')}** — {t.get('when')}。{t.get('why', '')}"
                     + (f" 第一步：{t['first_step']}" if t.get("first_step") else ""))
        L.append("")
    L += ["## 每天", "", "| 日期 | 必做 | 应做 | 状态 |", "|---|---|---|---|"]
    for d in r.get("days") or []:
        must = d.get("must") or ""
        bits = []
        if d.get("must_first_step"):
            bits.append(f"第一步：{d['must_first_step']}")
        if d.get("must_if_then"):
            bits.append(d["must_if_then"])
        if d.get("must_minutes"):
            bits.append(f"{d['must_minutes']} 分钟")
        if d.get("must_who"):
            bits.append(d["must_who"])
        if bits:
            must += "（" + "；".join(bits) + "）"
        fixed = " ".join(f"⏰ {x}" for x in d.get("fixed") or [])
        if fixed:
            must = fixed + " " + must
        should = "；".join(d.get("should") or [])
        if d.get("revise"):
            should = (should + "；" if should else "") + d["revise"]
        L.append(f"| {(d.get('date') or '')[5:]} {d.get('weekday', '')} | {must} | {should} | {d.get('status') or '📦'} |")
    L.append("")
    if r.get("parking"):
        L += ["## 停车场（有日期）"] + [f"- {p.get('date') or ''} {p.get('text') if isinstance(p, dict) else p}" for p in r["parking"]] + [""]
    if r.get("deadlines"):
        L += ["## 未来两周的 deadline", "", "| 时间 | 课 | 事项 | 权重 | 状态 |", "|---|---|---|---|---|"]
        L += [f"| {x.get('when')}{'，' + x['rel'] if x.get('rel') else ''} | {x.get('course')} | {x.get('item')}{'（待确认）' if x.get('pending') else ''} | {x.get('weight')} | {x.get('status')} |" for x in r["deadlines"]]
        L.append("")
        if r.get("clash"):
            L += [f"⚠️ {r['clash']}", ""]
    if r.get("review"):
        L += ["## 回我一句", "", r["review"], ""]
    if r.get("state"):
        ev = r["state"]
        L += [f"状态：{ev.get('label')}（{'；'.join(ev.get('signals') or []) or '没有异常信号'}）。建议：{ev.get('advice')}", ""]
    L += ["收工模板：「今天做完了 ___，没做完 ___」。", ""]
    return "\n".join(L)


def publish(ctx, html_path):
    """把本周的 HTML 复制到资料夹根目录的周手帐 WEEK_PAGE（人看这份；历史留在 reports/）。"""
    import shutil
    try:
        os.makedirs(ctx.root, exist_ok=True)
        dst = os.path.join(ctx.root, WEEK_PAGE)
        if os.path.exists(dst):  # 人看的那份被覆盖前留一份
            try:
                shutil.copy2(dst, dst + ".bak")
            except OSError:
                pass
        shutil.copy2(html_path, dst)
        return dst
    except OSError:
        return None


def md_writable(md_path):
    """只覆盖自己生成过的 md（带标记）或不存在的；手写的不动。"""
    if not os.path.exists(md_path):
        return True
    try:
        with io.open(md_path, encoding="utf-8") as f:
            return f.readline().strip() == MD_MARK
    except OSError:
        return False


def write(src, html_out=None, md_out=None, week_no=None, generated=None, force_md=False):
    r = json.load(io.open(src, encoding="utf-8"))
    week_no = week_no or r.get("week_no")
    base = os.path.splitext(os.path.basename(src))[0].replace("_report", "")
    plans_dir = os.path.dirname(os.path.abspath(src))
    html_out = html_out or os.path.join(os.path.dirname(plans_dir), "reports", f"周报_{base}.html")
    md_out = md_out or os.path.join(plans_dir, f"{base}.md")
    os.makedirs(os.path.dirname(html_out), exist_ok=True)
    save_text(html_out, render(r, week_no))
    wrote_md = None
    if force_md or md_writable(md_out):
        save_text(md_out, to_markdown(r, week_no, generated))
        wrote_md = md_out
    return {"html": html_out, "md": wrote_md, "md_skipped": None if wrote_md else md_out, "week_no": week_no}


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    res = write(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None,
                week_no=int(sys.argv[3]) if len(sys.argv) > 3 else None)
    print("written", res["html"], res["md"] or f"(md 未覆盖：{res['md_skipped']} 是手写的)")
