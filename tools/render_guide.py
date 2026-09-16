"""课件导读渲染：courses/<CODE>/导读_Wn.json → HTML（与复习包同一套样式）。

Usage: python render_guide.py <guide.json> <out.html> [generated-date]
"""
import datetime as dt
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brand  # noqa: E402
from htmlkit import INFER, esc, paras, ref_html, rich  # noqa: E402
from render_unit import foot, head  # noqa: E402


def render(g, generated=None, week_label=None):
    generated = generated or dt.date.today().isoformat()
    code = g.get("course_code") or ""
    wt = week_label or g.get("week_title") or ""
    o = [head(f"{code} {wt} 导读", f"guide-{wt}".lower(), app=code.lower() or "coach", wide=True),
         f'<p class="eyebrow">{esc(code)} · 课件导读</p>',
         f"<h1>{esc(wt)}</h1>",
         f'<p class="meta">{esc(g.get("course_name_zh"))} ｜ {esc(generated)} 生成 ｜ 依据：{rich(g.get("based_on_zh"))}</p>']
    if g.get("class_info_zh"):
        o.append(f'<p class="meta">{rich(g["class_info_zh"])}</p>')
    o += ['<div class="card key"><p class="sect">一句话定位</p>',
          f'<p class="pos">{rich(g.get("positioning_zh"))}</p>',
          '<p class="sect">这周对你意味着什么</p>', paras(g.get("this_week_for_you_zh")), "</div>"]

    if g.get("key_points"):
        o.append("<h2>本周重点</h2>")
    for i, k in enumerate(g.get("key_points") or [], 1):
        tags = "".join(INFER if t == "推断" else f'<span class="tag{" hot" if t in ("考点", "作业可用") else ""}">{esc(t)}</span>'
                       for t in k.get("tags") or [])
        o.append(f"<h3>{i} · {esc(k.get('title_zh'))} {tags}</h3>")
        if k.get("term_en"):
            o.append(f'<p class="cite">{esc(k["term_en"])}</p>')
        o.append(paras(k.get("explain_zh")))
        if k.get("quote_en"):
            o.append(f'<blockquote>“{esc(k["quote_en"])}”<span class="who">{rich(k.get("quote_src"))}</span></blockquote>')
        elif k.get("quote_src"):
            o.append(f'<p class="sub">出处：{rich(k["quote_src"])}</p>')
        if k.get("hook_zh"):
            o.append(f'<p class="sub"><strong>和考试 / 作业的关系：</strong>{rich(k["hook_zh"])}</p>')

    if g.get("readings"):
        o.append("<h2>阅读地图</h2>")
        for r in g["readings"]:
            mins = f'<span class="tag">约 {r["est_minutes"]} 分钟</span>' if r.get("est_minutes") else ""
            kind = '<span class="tag hot">必读</span>' if r.get("required") else '<span class="tag">选读</span>'
            where = rich(r.get("access_zh"))
            if r.get("url") and r["url"] not in (r.get("access_zh") or ""):
                where += " " + rich(r["url"])
            if r.get("local_path"):
                where += f' <code>{esc(r["local_path"])}</code>'
            o.append(f'<div class="card rd">{kind}{mins}<p class="cite">{esc(r.get("citation"))}</p>'
                     f'<p><b>重点看</b>{rich(r.get("focus_zh"))}</p>'
                     + (f'<p><b>可略过</b>{rich(r["skip_zh"])}</p>' if r.get("skip_zh") else "")
                     + f'<p class="sub"><b>在哪拿</b>{where}</p></div>')

    if g.get("in_class_zh"):
        o.append("<h2>课上会做什么</h2>" + paras(g["in_class_zh"]))

    if g.get("hooks"):
        o.append('<h2>和作业的关系</h2><div class="scroll"><table class="grid"><tr><th>作业</th><th>权重</th><th>时间</th><th>这周的内容怎么用上</th></tr>')
        for h in g["hooks"]:
            name = esc(h.get("assessment"))
            if h.get("url"):
                name = f'<a href="{esc(h["url"])}">{name}</a>'
            o.append(f"<tr><td>{name}</td><td>{esc(h.get('weight'))}</td><td>{rich(h.get('due_zh'))}</td><td>{rich(h.get('link_zh'))}</td></tr>")
        o.append("</table></div>")

    if g.get("actions"):
        total = sum(a.get("minutes") or 0 for a in g["actions"])
        o.append(f'<h2>本周行动清单</h2><p class="meta">一共约 {total} 分钟。做完一项，回我「✓ 课程代码 第几项」，我帮你记下。</p>')
        for a in g["actions"]:
            o.append('<div class="action"><span class="box"></span><div class="abody">'
                     f'<div class="atitle">{rich(a.get("action_zh"))}</div>'
                     f'<span class="tag">{a.get("minutes") or "?"} 分钟</span><span class="tag hot">{esc(a.get("due_zh"))}</span>'
                     f'<div class="first"><b>第一步</b>{rich(a.get("first_step_zh"))}</div>'
                     f'<p class="sub">{rich(a.get("why_zh"))}</p></div></div>')

    if g.get("glossary"):
        o.append('<h2>术语表</h2><div class="scroll"><table class="grid"><tr><th>English</th><th>中文</th></tr>')
        o += [f"<tr><td>{esc(t.get('en'))}</td><td>{rich(t.get('zh'))}</td></tr>" for t in g["glossary"]]
        o.append("</table></div>")

    if g.get("gaps_zh"):
        o.append("<h2>还不确定的地方</h2><ul>" + "".join(f"<li>{rich(x)}</li>" for x in g["gaps_zh"]) + "</ul>")

    o.append("<footer><p>依据与出处</p><ul>")
    o += [f"<li>{esc(s.get('label'))}：{ref_html(s.get('ref'))}</li>" for s in g.get("sources") or []]
    o.append(f"</ul><p>{brand.NAME} · 只整理课程材料；计分的文字由你自己写。标「推断」的地方请以 Canvas 和课表为准。</p></footer>")
    return "\n".join(o) + foot()


def write(src, dst, generated=None):
    g = json.load(io.open(src, encoding="utf-8"))
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    with io.open(dst, "w", encoding="utf-8") as f:
        f.write(render(g, generated))
    return dst


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    write(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    print("written", sys.argv[2])
