"""逐页精讲渲染：courses/<CODE>/精讲_Wn.json → HTML（与复习包同一套样式）。

一张幻灯片（或一组分节页）一张卡：课件原句 + 中文翻译 + 中文精讲 + 联系前几周 / 考试 / 作业。

Usage: python render_lecture.py <精讲_W7.json> <精讲_W7.html>
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from htmlkit import esc, rich  # noqa: E402
from render_unit import foot, head, marker  # noqa: E402

EXTRA = """<style>
.map{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;margin:12px 0 0;padding:0;list-style:none}
.map a{display:block;height:100%;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--surface);color:var(--ink);text-decoration:none;font-size:14.5px;line-height:1.45}
.map small{display:block;font:400 12.5px/1.3 var(--latin);color:var(--faint);margin-top:2px}
.sec-intro{font-size:15px;color:var(--muted);margin:0 0 14px}
.slide-no{font:700 12px/1 var(--latin);letter-spacing:.06em;padding:6px 8px;border-radius:6px;background:var(--sunk);color:var(--muted);align-self:center;white-space:nowrap}
.slide .term{font-size:20px}
.slide .quote .en{white-space:pre-line}
.slide .quote .zh{display:block;white-space:pre-line}
.tbl{width:100%;border-collapse:collapse;font-size:14.5px;margin:12px 0 0}
.tbl th{text-align:left;font-size:12.5px;color:var(--muted);padding:6px 10px 6px 0;border-bottom:1px solid var(--line)}
.tbl td{padding:8px 10px 8px 0;border-bottom:1px solid var(--line);vertical-align:top}
.tbl td:first-child{font:700 14.5px/1.5 var(--latin)}
.take{margin:0;padding-left:1.2em}
.take li{margin:8px 0}
.links{display:flex;flex-wrap:wrap;gap:12px;font-size:14.5px;font-weight:700;margin:10px 0 0}
</style>"""


def render(d):
    terms = d.get("terms", [])
    mk = marker(terms, cap=2)
    t = lambda s: mk(rich(s))  # noqa: E731
    code, w = d["course_code"], d["week"]
    o = [head(f"{code} W{w} 逐页精讲", f"lecture-{code.lower()}-w{w}", app=code.lower(), wide=False, extra=EXTRA),
         f'<p class="eyebrow">{esc(code)} · Week {w} · 逐页精讲</p>',
         f'<h1>{esc(d["title_zh"])}</h1><p class="title-en">{esc(d["title_en"])}</p>',
         f'<ul class="facts"><li>{esc(d["deck"])}</li><li>约 <b>{d.get("minutes", 45)}</b> 分钟</li></ul>',
         f'<p class="lead">{t(d["lead_zh"])}</p>',
         f'<p class="note">{rich(d["how_to_read_zh"])}</p>',
         '<h2>这一讲的顺序</h2><ol class="map">']
    o += [f'<li><a href="#{esc(s["id"])}">{esc(s["title_zh"])}<small>{esc(s["slides_label"])}</small></a></li>' for s in d["sections"]]
    o.append("</ol>")

    for n, s in enumerate(d["sections"], 1):
        o.append(f'<section id="{esc(s["id"])}"><h2><span class="n">{n}</span>{esc(s["title_zh"])}</h2>')
        if s.get("intro_zh"):
            o.append(f'<p class="sec-intro">{t(s["intro_zh"])}</p>')
        o.append('<div class="stack">')
        for sl in s["slides"]:
            tag = f'<span class="level l3">{esc(sl["tag"])}</span>' if sl.get("tag") else ""
            o.append(f'<article class="concept slide"><div class="term-row"><span class="slide-no">SLIDE {esc(sl["no"])}</span>'
                     f'<span class="term">{esc(sl["title_en"])}</span>{tag}</div>')
            if sl.get("en"):
                o.append(f'<div class="quote"><p class="en">{esc(sl["en"])}</p>'
                         + (f'<p class="zh">{esc(sl["zh"])}</p>' if sl.get("zh") else "")
                         + f'<div class="quote-foot"><span class="src">W{w} slide {esc(sl["no"])}{("　" + esc(sl["src_note"])) if sl.get("src_note") else ""}</span></div></div>')
            for para in sl.get("explain_zh", []):
                o.append(f"<p>{t(para)}</p>")
            if sl.get("table"):
                tb = sl["table"]
                o.append('<div class="scroll"><table class="tbl"><tr>' + "".join(f"<th>{esc(h)}</th>" for h in tb["head"]) + "</tr>"
                         + "".join("<tr>" + "".join(f"<td>{rich(c)}</td>" for c in row) + "</tr>" for row in tb["rows"]) + "</table></div>")
            rows = [(k, v) for k, v in sl.get("aside", []) if v]
            if rows:
                o.append('<dl class="aside">' + "".join(f"<dt>{esc(k)}</dt><dd>{t(v)}</dd>" for k, v in rows) + "</dl>")
            o.append("</article>")
        o.append("</div></section>")

    o.append("<h2>这一讲要带走的</h2><ul class=\"take\">" + "".join(f"<li>{t(x)}</li>" for x in d["takeaways"]) + "</ul>")
    if d.get("authors"):
        o.append('<h3>作者和概念对上号</h3><div class="scroll"><table class="tbl"><tr><th>作者</th><th>这一讲用到的</th><th>在哪一页</th></tr>'
                 + "".join(f"<tr><td>{esc(a)}</td><td>{rich(b)}</td><td>{esc(c)}</td></tr>" for a, b, c in d["authors"]) + "</table></div>")
    if d.get("links"):
        o.append('<div class="links">' + "".join(f'<a href="{esc(l["href"])}">{esc(l["label"])}</a>' for l in d["links"]) + "</div>")
    o.append('<details class="more"><summary>资料来源与说明</summary><ul>'
             + "".join(f"<li>{esc(x['label'])}：{rich(x['ref'])}</li>" for x in d.get("sources", [])) + "</ul>"
             + ("<p><b>还不确定的地方</b></p><ul>" + "".join(f"<li>{rich(g)}</li>" for g in d.get("gaps_zh", [])) + "</ul>" if d.get("gaps_zh") else "")
             + "<p>个人复习资料。课件原句照录（包括课件自己的错字），中文是翻译和讲解；标「推断」的是课件没写、按上下文推的。</p></details>")
    return "\n".join(o) + foot()


if __name__ == "__main__":
    data = json.load(io.open(sys.argv[1], encoding="utf-8"))
    io.open(sys.argv[2], "w", encoding="utf-8").write(render(data))
    print("written", sys.argv[2])
