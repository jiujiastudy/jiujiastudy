"""生成页面的风格：颜色、字号、间距、组件和页面脚本，全在这一个文件里。

规范写在 references/style.md。这里一改，所有用 head() / foot() 的页面一起变；别的文件里不要另写颜色和字号。
检查一个页面：用当前已选定的 Python 运行 tools/style_check.py 页面.html
"""
import html as _html

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">')

_LIGHT = ("--bg:#F6F6F3;--surface:#FFFFFF;--sunk:#EFEEEA;--line:#E4E2DC;"
          "--ink:#1C1F23;--muted:#5F646B;--faint:#9A9FA6;"
          "--accent:#2F5BD8;--accent-soft:#EAF0FD;--on-accent:#FFFFFF;"
          "--good:#1E7F4F;--good-soft:#E7F3EC;--warn:#945800;--warn-soft:#FBF1DF;--bad:#C0392B;--bad-soft:#FCEBE9;"
          "--highlight:#FFE58A;--on-highlight:#1C1F23;--shadow:0 6px 24px rgba(20,22,26,.14);color-scheme:light;")
_DARK = ("--bg:#121417;--surface:#1A1D21;--sunk:#23272C;--line:#2E3238;"
         "--ink:#E7E9EC;--muted:#A3A9B1;--faint:#6F7680;"
         "--accent:#8AA8FF;--accent-soft:#1F2A45;--on-accent:#0E1116;"
         "--good:#5FC48D;--good-soft:#16281E;--warn:#E8B04E;--warn-soft:#2E2412;--bad:#F08A7E;--bad-soft:#35201D;"
         "--highlight:#5C4D12;--on-highlight:#F5EFD6;--shadow:0 6px 24px rgba(0,0,0,.5);color-scheme:dark;")

TOKENS = ("/*tokens*/:root{" + _LIGHT
          + '--font:"Inter","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC","Noto Sans SC",system-ui,sans-serif;'
          + '--mono:ui-monospace,"SF Mono",Consolas,monospace;'
          + "--fs-s:13px;--fs-m:15px;--fs-l:18px;--fs-xl:26px;"
          + "--s1:4px;--s2:8px;--s3:12px;--s4:16px;--s5:24px;--s6:32px;--s7:48px;--r:12px;--r-s:8px}"
          + '@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){' + _DARK + "}}"
          + ':root[data-theme="dark"]{' + _DARK + "}/*end tokens*/")

BASE = """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:400 var(--fs-m)/1.65 var(--font);-webkit-font-smoothing:antialiased}
[hidden]{display:none!important}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline;text-underline-offset:3px}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:var(--r-s)}
.page{max-width:760px;margin:0 auto;padding:var(--s6) var(--s4) var(--s7);overflow-wrap:break-word}
h1{margin:0;font-size:var(--fs-xl);font-weight:700;line-height:1.25;letter-spacing:-.01em}
h2{margin:var(--s6) 0 var(--s3);font-size:var(--fs-m);font-weight:600;color:var(--muted)}
h3{margin:0;font-size:var(--fs-l);font-weight:600;line-height:1.4}
p,ul,ol{margin:0}
ul,ol{padding:0;list-style:none}
.meta{font-size:var(--fs-s);color:var(--muted)}
.num{font-variant-numeric:tabular-nums}
.infer{font-size:var(--fs-s);color:var(--muted)}
.code{font-size:var(--fs-s);font-weight:600;letter-spacing:.02em;color:var(--muted)}
.kicker{font-size:var(--fs-s);font-weight:600;color:var(--muted)}
.end{margin-top:var(--s6)}

.top .meta{margin-top:var(--s2)}
.lead{margin-top:var(--s3);color:var(--muted)}
.progress{display:flex;align-items:center;gap:var(--s3);margin-top:var(--s4);font-size:var(--fs-s);color:var(--muted)}
.progress .bar{flex:1 1 auto;max-width:240px;height:6px;border-radius:999px;background:var(--sunk);overflow:hidden}
.progress .fill{width:0;height:100%;border-radius:999px;background:var(--good);transition:width .3s ease}
.progress .ptxt{white-space:nowrap}
.progress.all-done{color:var(--good);font-weight:600}

.status{margin-top:var(--s5);padding:var(--s3) var(--s4);border-radius:var(--r);background:var(--sunk)}
.status b{margin-right:var(--s2);font-weight:600}
.status .why{margin-top:2px;font-size:var(--fs-s);color:var(--muted)}
.status.is-good{background:var(--good-soft)}.status.is-good b{color:var(--good)}
.status.is-warn{background:var(--warn-soft)}.status.is-warn b{color:var(--warn)}
.status.is-bad{background:var(--bad-soft)}.status.is-bad b{color:var(--bad)}

.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:var(--s4) var(--s5)}
.card.today,.card.hero{margin-top:var(--s3)}
.card.flush{padding:var(--s1) var(--s4)}
.hero{border-color:var(--accent)}
.hero .kicker{color:var(--accent)}
.hero h3{margin-top:var(--s1)}
.hero .meta{margin-top:var(--s1)}
.sub{margin:var(--s2) 0 0 32px}
.hero .sub{margin:var(--s3) 0 0}

.tag{display:inline-block;margin-left:var(--s1);padding:0 var(--s2);border-radius:999px;background:var(--sunk);color:var(--muted);font-size:var(--fs-s);font-weight:500;line-height:1.6;white-space:nowrap;vertical-align:1px}
.t>.tag:first-child,.sub>.tag:first-child{margin:0 var(--s1) 0 0}
.tag.warn{background:var(--warn-soft);color:var(--warn)}
.tag.bad{background:var(--bad-soft);color:var(--bad)}
.tag.good{background:var(--good-soft);color:var(--good)}
.tag.hl{background:var(--highlight);color:var(--on-highlight)}
.callout{margin:0 0 var(--s3);padding:var(--s3) var(--s4);border-radius:var(--r);background:var(--warn-soft);font-size:var(--fs-s)}
.callout.end-gap{margin:var(--s3) 0 0}

input[type=checkbox]{width:18px;height:18px;margin:0;accent-color:var(--good);cursor:pointer}
.must{display:grid;grid-template-columns:20px minmax(0,1fr);gap:var(--s3);align-items:start;cursor:pointer}
.must input{margin-top:3px}
.today .must{margin-top:var(--s2);font-size:var(--fs-l);font-weight:600;line-height:1.45}
.today .must input{margin-top:5px}
.days .must{font-weight:500}
.is-done .t{color:var(--muted);text-decoration:line-through}
.pop{animation:pop .6s ease}
@keyframes pop{from{background:var(--good-soft)}to{background:transparent}}

.rows>li{display:grid;grid-template-columns:20px minmax(0,1fr) auto;column-gap:var(--s3);row-gap:2px;align-items:start;padding:var(--s2) 0;border-top:1px solid var(--line)}
.rows>li:first-child{border-top:0}
.rows>li>input{margin-top:3px}
.rows .t{min-width:0}
.rows .v{margin-right:var(--s2);color:var(--muted);cursor:pointer}
.rows .code{margin-right:var(--s1)}
.rows .m{padding-top:2px;font-size:var(--fs-s);color:var(--muted);white-space:nowrap;text-align:right}
.rows .rel{display:inline-block;min-width:5.4em;margin-right:var(--s2);font-size:var(--fs-s);font-weight:600;color:var(--muted)}
.rows .rel.soon{color:var(--bad)}
.rows .src{display:block;font-size:var(--fs-s);color:var(--muted)}
.rows.nobox>li{grid-template-columns:minmax(0,1fr) auto}

.days>li{display:grid;grid-template-columns:44px minmax(0,1fr);gap:var(--s3);padding:var(--s3) var(--s2);border-top:1px solid var(--line)}
.days>li:first-child{border-top:0}
.days .d{font-size:var(--fs-l);font-weight:600;line-height:1.1;font-variant-numeric:tabular-nums}
.days .d span{display:block;margin-top:2px;font-size:var(--fs-s);font-weight:400;color:var(--muted)}
.days>li.is-today{border-radius:var(--r-s);border-top-color:transparent;background:var(--accent-soft)}
.days>li.is-today+li{border-top-color:transparent}
.days>li.is-today .d{color:var(--accent)}
.days>li.is-past{opacity:.5}

.courses{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--s3);align-items:start}
.course h3{margin-top:2px}
.course>.meta{margin-top:2px}
.blabel{margin-top:var(--s4);font-size:var(--fs-s);font-weight:600;color:var(--muted)}
.course .rows{margin-top:var(--s1)}
.course .sub{margin-left:0}
.done-mark{display:none}
.course.is-complete{border-color:var(--good)}
.course.is-complete .done-mark{display:inline-block}
.code>.tag{margin-left:var(--s2)}

details.fold{margin-top:var(--s3)}
.today details.fold{margin:var(--s2) 0 0 32px}
details.fold>summary,.changes summary{cursor:pointer;list-style:none}
details.fold>summary{font-size:var(--fs-s);color:var(--muted)}
details.fold>summary::-webkit-details-marker,.changes summary::-webkit-details-marker{display:none}
details.fold>summary::before{content:"\\25B8";display:inline-block;width:1.1em;transition:transform .15s}
details.fold[open]>summary::before{transform:rotate(90deg)}
details.fold>.rows,details.fold>.plain{margin-top:var(--s2)}
.plain>li{padding:2px 0;font-size:var(--fs-s)}
.plain .num{color:var(--muted)}
.changes>li{padding:var(--s2) 0;border-top:1px solid var(--line)}
.changes>li:first-child{border-top:0}
.changes .meta{margin-left:var(--s2)}
.changes .gist{margin-top:var(--s2);white-space:pre-line}

.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:var(--fs-s)}
th{padding:var(--s2) var(--s3) var(--s2) 0;border-bottom:1px solid var(--line);color:var(--muted);font-weight:600;text-align:left}
td{padding:var(--s2) var(--s3) var(--s2) 0;border-bottom:1px solid var(--line);vertical-align:top}
blockquote{margin:var(--s3) 0;padding:var(--s2) var(--s4);border-left:3px solid var(--line);color:var(--muted)}
code{padding:1px var(--s1);border-radius:var(--r-s);background:var(--sunk);font-family:var(--mono);font-size:var(--fs-s)}
mark{padding:0 2px;border-radius:3px;background:var(--highlight);color:var(--on-highlight)}

.sig{margin-top:var(--s7);padding-top:var(--s4);border-top:1px solid var(--line);color:var(--muted);font-size:var(--fs-s);text-align:center}
.sig b{font-weight:600}
.sig img{display:block;width:120px;height:120px;margin:var(--s3) auto var(--s2);border-radius:var(--r-s)}
.sig small{display:block;font-size:var(--fs-s)}
.toast{position:fixed;left:50%;bottom:var(--s4);z-index:30;display:flex;align-items:center;gap:var(--s3);max-width:calc(100% - 32px);padding:var(--s2) var(--s2) var(--s2) var(--s4);border-radius:999px;background:var(--ink);color:var(--bg);font-size:var(--fs-s);box-shadow:var(--shadow);transform:translateX(-50%)}
.toast span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.toast button{flex:0 0 auto;padding:var(--s1) var(--s3);border:0;border-radius:999px;background:var(--accent);color:var(--on-accent);font:600 var(--fs-s)/1.6 var(--font);cursor:pointer}
.theme{position:fixed;top:var(--s3);right:var(--s3);z-index:20;padding:var(--s1) var(--s3);border:1px solid var(--line);border-radius:999px;background:var(--surface);color:var(--muted);font:500 var(--fs-s)/1.6 var(--font);cursor:pointer}

@media (max-width:640px){
.page{padding:var(--s5) var(--s4) var(--s7)}
.card{padding:var(--s4)}
.card.flush{padding:var(--s1) var(--s3)}
.courses{grid-template-columns:1fr}
.rows>li{grid-template-columns:20px minmax(0,1fr)}
.rows .m{grid-column:2;padding-top:0;text-align:left;white-space:normal}
.rows.nobox>li{grid-template-columns:minmax(0,1fr)}
.rows.nobox .m{grid-column:1}
.days>li{grid-template-columns:36px minmax(0,1fr);padding:var(--s3) var(--s1)}
.theme{top:var(--s2);right:var(--s2)}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""

CORE_JS = r"""
(function () {
  var d = document, root = d.documentElement, body = d.body;
  var KEY = (body.getAttribute('data-app') || 'coach') + ':' + (body.getAttribute('data-key') || 'page'), st = {};
  try { st = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { st = {}; }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) {} }
  function all(s, r) { return Array.prototype.slice.call((r || d).querySelectorAll(s)); }

  // 今天高亮、过去变淡；生成日不是今天的「今天」卡片藏起来
  var n = new Date(), iso = n.getFullYear() + '-' + ('0' + (n.getMonth() + 1)).slice(-2) + '-' + ('0' + n.getDate()).slice(-2);
  all('[data-date]').forEach(function (el) { var x = el.getAttribute('data-date'); if (x === iso) el.classList.add('is-today'); else if (x < iso) el.classList.add('is-past'); });
  all('[data-today]').forEach(function (el) { if (el.getAttribute('data-today') !== iso) el.hidden = true; });

  // 勾选：记在这台电脑上；同一编号的框一起变；新勾的在底部提示「做完了 …」，复制回对话就记进档案
  st.tick = st.tick || {};
  var boxes = all('input[data-tick]'), bar = d.querySelector('[data-progress]'), toast = d.querySelector('[data-toast]');
  function mark(b, anim) {
    var r = b.closest('[data-row]'); if (!r) return;
    r.classList.toggle('is-done', b.checked);
    if (anim && b.checked) { r.classList.remove('pop'); void r.offsetWidth; r.classList.add('pop'); }
  }
  function uniq(list) { var seen = {}; return list.filter(function (b) { var k = b.getAttribute('data-tick'); if (seen[k]) return false; seen[k] = 1; return true; }); }
  function update() {
    var items = uniq(boxes.filter(function (b) { return b.hasAttribute('data-item'); }));
    var days = uniq(boxes.filter(function (b) { return !b.hasAttribute('data-item'); }));
    if (bar) {
      var k = items.filter(function (b) { return b.checked; }).length, m = items.length, dn = days.filter(function (b) { return b.checked; }).length;
      bar.querySelector('.fill').style.width = (m ? Math.round(k * 100 / m) : 0) + '%';
      bar.querySelector('.ptxt').textContent = (m && k === m) ? '本周 ' + m + ' 项全部完成' : '本周 ' + k + ' / ' + m + ' 项' + (days.length ? ' · ' + dn + ' / ' + days.length + ' 天' : '');
      bar.classList.toggle('all-done', m > 0 && k === m);
    }
    all('[data-group]').forEach(function (g) {
      var bs = all('input[data-item]', g);
      g.classList.toggle('is-complete', bs.length > 0 && bs.every(function (b) { return b.checked; }));
    });
    if (toast) {
      var p = uniq(boxes.filter(function (b) { return b.checked && !b.hasAttribute('data-done'); })).map(function (b) { return b.getAttribute('data-label') || b.getAttribute('data-tick'); });
      toast.hidden = !p.length;
      if (p.length) { toast.querySelector('span').textContent = '做完了 ' + p.join('、'); toast.querySelector('button').textContent = '复制'; }
    }
  }
  boxes.forEach(function (b) {
    var id = b.getAttribute('data-tick');
    b.checked = !!st.tick[id] || b.hasAttribute('data-done'); mark(b);
    b.addEventListener('change', function () {
      st.tick[id] = b.checked; save();
      boxes.forEach(function (x) { if (x !== b && x.getAttribute('data-tick') === id) { x.checked = b.checked; mark(x); } });
      mark(b, true); update();
    });
  });
  if (toast) {
    toast.querySelector('button').addEventListener('click', function () {
      var t = toast.querySelector('span').textContent, btn = this;
      var pr = navigator.clipboard && navigator.clipboard.writeText ? navigator.clipboard.writeText(t) : Promise.reject();
      pr.then(function () { btn.textContent = '已复制，粘到对话里'; }, function () { window.prompt('复制这句回我：', t); });
    });
  }
  update();

  // 深浅：打开页面时看电脑的钟，19:00 到 6:00 深色；右上角按钮临时切换，不记忆
  function auto(h) { h = (h == null) ? new Date().getHours() : h; return (h >= 19 || h < 6) ? 'dark' : 'light'; }
  var tb = d.createElement('button'); tb.type = 'button'; tb.className = 'theme';
  function apply(t) { root.setAttribute('data-theme', t); tb.textContent = t === 'dark' ? '浅色' : '深色'; tb.setAttribute('aria-label', t === 'dark' ? '切到浅色' : '切到深色'); }
  tb.addEventListener('click', function () { apply(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark'); });
  body.appendChild(tb); apply(auto());
  window.coachTheme = { auto: auto, apply: apply };
})();
"""

STATUS_CLASS = {"正常": "is-good", "落后": "is-warn", "病了": "is-warn", "卡住": "is-bad", "过载": "is-bad"}


def esc(s):
    return _html.escape(str(s if s is not None else ""), quote=True)


def head(title, key="page", app="coach", extra_css=""):
    """页面开头。extra_css 只放布局上的小调整，颜色和字号一律用变量。"""
    return ('<!doctype html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{esc(title)}</title>{FONTS}<style>{TOKENS}{BASE}{extra_css}</style></head>'
            f'<body data-key="{esc(key)}" data-app="{esc(app or "coach")}"><main class="page">')


def foot(extra="", script=""):
    """页面结尾及页面脚本。extra 是一句纯文字说明（会转义，不能放 HTML、图片或链接）。"""
    footer = f'<footer class="sig">{esc(extra)}</footer>' if extra else ""
    return f'{footer}</main><script>{CORE_JS}</script>{script}</body></html>'


def status(ev):
    """状态条：一句结论 + 建议，信号放小字。ev = cc_state.evaluate() 的结果。"""
    if not ev:
        return ""
    sig = "；".join(ev.get("signals") or [])
    return (f'<div class="status {STATUS_CLASS.get(ev.get("label"), "")}"><b>状态：{esc(ev.get("label"))}</b>{esc(ev.get("advice"))}'
            + (f'<p class="why">{esc(sig)}</p>' if sig else "") + "</div>")


def tag(text, kind=""):
    """小标签：kind = warn（待确认）/ bad（已过期）/ good（完成）/ hl（时间点、考试）。"""
    return f'<span class="tag {esc(kind)}">{esc(text)}</span>' if text else ""
