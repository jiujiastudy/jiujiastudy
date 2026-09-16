"""Render an exam-prep pack (units, plan, word list, mock test) as study pages; also the
shared page shell (head/foot/CSS) the other generated pages use.

Design: cool paper ground, blue-black ink, one highlighter yellow for the English exam words and an
exam-booklet navy for controls. Every Latin character is set in Atkinson Hyperlegible (a face built
for legibility, which suits an ESL reader); Chinese falls through to Noto Sans SC; ZCOOL XiaoWei is
used only for page titles. Works offline (system-font fallback) and in light or dark mode.

Usage:
  python render_unit.py unit <W1.json> <W1.html>
  python render_unit.py plan <plan.json> <复习计划.html>
  python render_unit.py vocab <exam_prep_dir> <单词总表.html>
  python render_unit.py mock <exam_prep_dir> <模拟小测.html> [n]
  python render_unit.py all <exam_prep_dir>          (every unit + plan + word list + mock test)
"""
import glob, io, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from htmlkit import esc, rich  # noqa: E402
from cc_time import WD, parse_date  # noqa: E402
from design import FONTS as _DFONTS, TOKENS as _TOKENS  # noqa: E402

LEVEL = {3: ("必会", "l3"), 2: ("常考", "l2"), 1: ("了解", "l1")}

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400'
         '&family=Noto+Sans+SC:wght@400;500;700&family=ZCOOL+XiaoWei&display=swap">')

DARK = """--ground:#0F1318;--surface:#161C23;--sunk:#1E252E;--ink:#E4E8EE;--muted:#9AA3B1;--faint:#747E8D;--line:#29313B;
--accent:#AEB9FF;--accent-soft:#222A47;--on-accent:#0F1318;--marker:rgba(255,214,64,.30);--marker-solid:#E9C23A;--on-marker:#0F1318;
--good:#4BC38A;--good-soft:#12302A;--bad:#F08377;--bad-soft:#3A1E1C;color-scheme:dark;"""

CSS = """
:root{--ground:var(--bg);--marker:rgba(255,214,64,.55);--marker-solid:var(--highlight);--on-marker:var(--on-highlight);--latin:var(--font);--body:var(--font);--display:var(--font)}
:root[data-theme="dark"]{--marker:rgba(255,214,64,.28)}
[hidden]{display:none!important}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--ground);color:var(--ink);font:16.5px/1.8 var(--body);-webkit-font-smoothing:antialiased}
.page{max-width:680px;margin:0 auto;padding:18px 20px 88px;overflow-wrap:break-word}
a{color:var(--accent);text-underline-offset:3px;overflow-wrap:anywhere}
.aside dd,.stem>*,.day>*,.ticket-main{min-width:0}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}
button{font:inherit}
.back{display:inline-block;font:500 14px/1 var(--body);color:var(--muted);text-decoration:none;padding:8px 0}
.eyebrow{font:700 12px/1.4 var(--latin);letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin:14px 0 6px}
h1{font:400 34px/1.25 var(--display);margin:0;text-wrap:balance}
.title-en{font:400 18px/1.4 var(--latin);color:var(--muted);margin:4px 0 12px}
.facts{display:flex;flex-wrap:wrap;gap:4px 16px;margin:0 0 16px;padding:0;list-style:none;font-size:14px;color:var(--muted);font-variant-numeric:tabular-nums}
.facts b{color:var(--ink)}
.steps{position:sticky;top:0;z-index:10;display:flex;gap:6px;margin:0 -20px;padding:10px 20px;background:var(--ground);border-bottom:1px solid var(--line);overflow-x:auto}
.steps a{flex:1 0 auto;display:flex;align-items:center;justify-content:center;gap:8px;padding:8px 12px;border-radius:999px;background:var(--surface);border:1px solid var(--line);color:var(--ink);text-decoration:none;font-size:14px;line-height:1;white-space:nowrap}
.n{display:inline-grid;place-items:center;flex:0 0 22px;width:22px;height:22px;border-radius:50%;background:var(--accent);color:var(--on-accent);font:700 12px/1 var(--latin)}
.steps [data-score]{color:var(--muted);font-variant-numeric:tabular-nums}
.lead{font-size:18px;line-height:1.75;margin:18px 0 12px}
.note{font-size:15px;color:var(--muted);margin:0}
.label{display:block;font-size:13px;font-weight:700;color:var(--ink);margin:0 0 2px}
section{scroll-margin-top:62px}
h2{display:flex;align-items:center;gap:10px;font:700 21px/1.35 var(--body);margin:40px 0 4px;text-wrap:balance}
h3{font:700 17px/1.4 var(--body);margin:30px 0 8px}
.hint{font-size:14.5px;color:var(--muted);margin:0 0 14px}
.stack{display:grid;gap:14px}
.concept,.q{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:18px 18px 16px}
.term-row{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 10px}
.term{font:700 22px/1.3 var(--latin);background:linear-gradient(transparent 58%,var(--marker) 58%);padding:0 .12em;margin-left:-.12em}
.term-zh{font-size:16px;color:var(--muted)}
.level{margin-left:auto;align-self:center;font-size:12px;font-weight:700;line-height:1;padding:5px 9px;border-radius:999px;white-space:nowrap}
.level.l3{background:var(--marker-solid);color:var(--on-marker)}
.level.l2{border:1px solid var(--line)}
.level.l1{color:var(--faint)}
.concept>p{margin:10px 0 0}
mark{background:linear-gradient(transparent 60%,var(--marker) 60%);color:inherit;padding:0 .08em}
.quote{margin:12px 0 0;padding:12px 14px;border-radius:10px;background:var(--sunk)}
.quote .en{font:400 16.5px/1.6 var(--latin);margin:0}
.quote .zh{margin:8px 0 0;color:var(--muted);font-size:15px}
.quote-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:8px}
.src{font:400 13px/1.4 var(--latin);color:var(--faint)}
.toggle{font-size:13px;line-height:1;color:var(--accent);background:var(--surface);border:1px solid var(--line);border-radius:999px;padding:7px 11px;cursor:pointer}
.aside{display:grid;grid-template-columns:auto 1fr;gap:6px 12px;margin:12px 0 0;font-size:15px;line-height:1.7}
.aside dt{font-weight:700;color:var(--muted);white-space:nowrap}
.aside dd{margin:0}
.readings{list-style:none;margin:0;padding:0}
.reading{padding:14px 0;border-top:1px solid var(--line)}
.reading:last-child{border-bottom:1px solid var(--line)}
.reading p{margin:6px 0 0}
.cite{font:400 13.5px/1.5 var(--latin);color:var(--muted);margin:0}
.badge{display:inline-block;font-size:12px;font-weight:700;line-height:1;padding:5px 8px;border-radius:999px;background:var(--sunk);color:var(--muted);margin:0 6px 4px 0}
.badge.full{background:var(--good-soft);color:var(--good)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 0;padding:0;list-style:none}
.chips li{font:400 13px/1.3 var(--latin);padding:5px 8px;border-radius:6px;background:var(--sunk)}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 12px}
.chip,.btn{font-size:14px;line-height:1;padding:9px 13px;border-radius:999px;border:1px solid var(--line);background:var(--surface);color:var(--ink);cursor:pointer}
.chip[aria-pressed="true"],.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
.btn{border-radius:10px;font-weight:700}
.btn:disabled{opacity:.5;cursor:default}
.deck{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.fc{position:relative;min-height:92px;text-align:left;padding:12px 26px 12px 14px;border-radius:12px;border:1px solid var(--line);background:var(--surface);color:var(--ink);cursor:pointer;display:flex;flex-direction:column;justify-content:center;gap:4px}
.fc-en{font:700 16.5px/1.3 var(--latin);overflow-wrap:anywhere}
.fc-back{display:none;flex-direction:column;gap:3px}
.fc.flipped{background:var(--accent-soft);border-color:transparent}
.fc.flipped .fc-en{font-size:13px;font-weight:400;color:var(--muted)}
.fc.flipped .fc-back{display:flex}
.fc-zh{font-size:17px;font-weight:700;line-height:1.4}
.fc-note{font-size:13px;line-height:1.55;color:var(--muted)}
.dot{position:absolute;top:11px;right:11px;width:9px;height:9px;border-radius:50%}
.dot.l3{background:var(--marker-solid)}
.dot.l2{background:var(--faint)}
.dot.l1{border:1.5px solid var(--faint)}
.q-no{font:700 12px/1.4 var(--latin);letter-spacing:.08em;text-transform:uppercase;color:var(--faint);margin:0 0 6px}
.q-stem{font:400 17px/1.6 var(--latin);margin:0 0 12px}
.opts{display:grid;gap:8px}
.opt{display:flex;align-items:flex-start;gap:12px;width:100%;text-align:left;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--surface);color:var(--ink);font:400 15.5px/1.5 var(--latin);cursor:pointer}
.opt:hover:not(:disabled){border-color:var(--accent)}
.opt:disabled{cursor:default}
.bub{flex:0 0 26px;height:26px;border-radius:50%;border:1.5px solid var(--faint);display:grid;place-items:center;font:700 13px/1 var(--latin);color:var(--muted)}
.opt.picked{border-color:var(--accent);background:var(--accent-soft)}
.opt.picked .bub{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
.opt.correct{border-color:var(--good);background:var(--good-soft)}
.opt.correct .bub{background:var(--good);border-color:var(--good);color:var(--surface)}
.opt.wrong{border-color:var(--bad);background:var(--bad-soft)}
.opt.wrong .bub{background:var(--bad);border-color:var(--bad);color:var(--surface)}
.opt.dim{opacity:.55}
.verdict{font-size:14px;font-weight:700;margin:12px 0 0}
.verdict:empty{display:none}
.verdict.is-right{color:var(--good)}
.verdict.is-wrong{color:var(--bad)}
.why{font-size:15px;margin:4px 0 0}
.why .src{display:block;margin-top:4px}
.recap{margin:0;padding-left:1.2em}
.recap li{margin:6px 0}
.next{margin:36px 0 0;padding:14px 16px;border-radius:12px;background:var(--sunk);font-size:15px}
.next a{font-weight:700}
details.more{margin:28px 0 0;font-size:14px;color:var(--muted)}
details.more summary{cursor:pointer;font-weight:700;color:var(--ink);padding:6px 0}
details.more ul{padding-left:1.2em;margin:6px 0 12px}
.infer{font-size:.86em;color:var(--faint);border-bottom:1px dotted var(--faint)}
.ticket{display:grid;grid-template-columns:1fr auto;border-radius:16px;overflow:hidden;background:var(--surface);border:1px solid var(--line);margin:14px 0 8px}
.ticket-main{padding:16px 18px}
.ticket-main p{margin:0}
.when{font:700 26px/1.25 var(--latin);font-variant-numeric:tabular-nums;margin:2px 0 4px!important}
.when small{font:500 16px/1 var(--body);margin-right:6px}
.ticket-sub{font-size:14.5px;color:var(--muted)}
.stub{display:grid;place-content:center;justify-items:center;gap:4px;min-width:110px;padding:16px 18px;border-left:2px dashed var(--line);background:var(--marker-solid);color:var(--on-marker);text-align:center}
.stub-big{font:700 40px/1 var(--latin);font-variant-numeric:tabular-nums}
.stub-label{font-size:13px;line-height:1.3}
.plainlist{margin:0;padding-left:1.2em}
.plainlist li{margin:6px 0}
.days{list-style:none;margin:0;padding:0;border-top:1px solid var(--line)}
.day{display:grid;grid-template-columns:28px 70px 1fr auto;gap:10px;align-items:center;padding:12px 8px;border-bottom:1px solid var(--line)}
.day .d{font:700 15px/1.25 var(--latin);font-variant-numeric:tabular-nums}
.day .d small{display:block;font:400 12px/1.3 var(--body);color:var(--muted)}
.day .m{font:400 13px/1 var(--latin);color:var(--muted);white-space:nowrap}
.day.is-today{background:var(--accent-soft);border-radius:10px}
.day.is-today .d small::after{content:" · 今天";color:var(--accent);font-weight:700}
.day.is-past{opacity:.55}
.day.is-done .t{text-decoration:line-through;color:var(--muted)}
input[type="checkbox"]{width:20px;height:20px;margin:0;accent-color:var(--accent)}
.stems{border-top:1px solid var(--line)}
.stem{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:2px 14px;padding:10px 0;border-bottom:1px solid var(--line)}
.stem .en{font:700 15.5px/1.5 var(--latin)}
.stem .nt{grid-column:1/-1;font-size:13.5px;color:var(--muted)}
.checklist{list-style:none;padding:0;margin:0}
.checklist li{display:grid;grid-template-columns:28px 1fr;gap:6px;align-items:start;padding:8px 0}
.checklist input{margin-top:4px}
.exambar{position:sticky;top:0;z-index:10;display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:0 -20px 12px;padding:10px 20px;background:var(--ground);border-bottom:1px solid var(--line)}
.timer{font:700 20px/1 var(--latin);font-variant-numeric:tabular-nums;min-width:64px}
.exambar .spacer{flex:1}
.picked-count{font-size:14px;color:var(--muted);font-variant-numeric:tabular-nums}
.result{padding:14px 16px;border-radius:12px;background:var(--marker-solid);color:var(--on-marker);margin:0 0 14px}
.submit-row{margin:20px 0 0;display:flex;justify-content:center}
@media (max-width:440px){h1{font-size:29px}.term{font-size:20px}.day{grid-template-columns:26px 60px 1fr}.day .m{grid-column:3}
.ticket{grid-template-columns:1fr}.stub{border-left:0;border-top:2px dashed var(--line);grid-auto-flow:column;justify-content:start;align-items:baseline;gap:8px}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
"""

EXTRA_CSS = """
.page.wide{max-width:900px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:14px 0}
.card.key{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
.card.fail{border-color:var(--bad);background:var(--bad-soft)}
.card>p{margin:6px 0 0}
.sect{font:700 12px/1.4 var(--latin);letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin:0 0 8px}
.pos{font:400 19px/1.6 var(--display);color:var(--accent);margin:0 0 12px}
.meta{font-size:13.5px;line-height:1.7;color:var(--muted);margin:0 0 6px}
.sub{font-size:14px;line-height:1.6;color:var(--muted);margin:6px 0 0}
.tag{display:inline-block;font-size:12px;line-height:1;padding:5px 9px;border:1px solid var(--line);border-radius:999px;color:var(--muted);white-space:nowrap;margin:0 4px 4px 0;vertical-align:middle}
.tag.hot{background:var(--accent);color:var(--on-accent);border-color:var(--accent)}
.tag.infer,.tag.pend{border-style:dashed}
table.grid{width:100%;border-collapse:collapse;margin:12px 0 4px;font-size:14.5px}
.grid th{text-align:left;font-size:12.5px;color:var(--muted);font-weight:700;padding:8px 10px 8px 0;border-bottom:1px solid var(--line);vertical-align:bottom}
.grid td{padding:10px 10px 10px 0;border-bottom:1px solid var(--line);vertical-align:top}
.grid td:first-child{white-space:nowrap;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}
blockquote{margin:12px 0;padding:10px 14px;border-left:3px solid var(--accent);background:var(--sunk);border-radius:0 10px 10px 0;font-size:15.5px;line-height:1.7}
blockquote .who{display:block;margin-top:6px;font-size:13px;color:var(--muted)}
.action{display:flex;gap:14px;background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin:12px 0}
.box{flex:0 0 20px;height:20px;border:1.5px solid var(--accent);border-radius:50%;margin-top:4px}
.abody{flex:1;min-width:0}
.atitle{font-weight:700;font-size:16.5px;margin-bottom:6px}
.first{margin:8px 0 0;padding:8px 12px;background:var(--sunk);border-radius:8px;font-size:14.5px}
.rd b,.action b{color:var(--accent);font-weight:700;margin-right:6px}
.rd p{margin:6px 0 0}
code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.86em;background:var(--sunk);padding:1px 5px;border-radius:4px;overflow-wrap:anywhere}
footer{margin-top:56px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}
footer ul{padding-left:1.2em;margin:6px 0}
footer li{margin:3px 0}
.urgent{background:var(--marker-solid);color:var(--on-marker);border-radius:14px;padding:16px 18px;margin:14px 0}
.urgent p{margin:4px 0 0}
.sig{margin:52px 0 0;padding-top:16px;border-top:1px solid var(--line);font:400 14px/1.7 var(--body);color:var(--muted);text-align:center}
.sig b{font-weight:600;color:var(--muted)}
.sig small{display:block;font-size:12.5px;margin-top:2px}
.theme{position:fixed;top:12px;right:12px;z-index:20;width:34px;height:34px;border-radius:50%;border:1px solid var(--line);background:var(--surface);color:var(--muted);font-size:16px;line-height:1;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.08)}
"""

JS = r"""
(function () {
  var body = document.body, KEY = (body.getAttribute('data-app') || 'coach') + ':' + (body.getAttribute('data-key') || 'page'), state = {};
  try { state = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { state = {}; }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }
  function all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  var L = 'ABCD';

  all('[data-zh-toggle]').forEach(function (b) {
    b.addEventListener('click', function () {
      var t = document.getElementById(b.getAttribute('aria-controls')), open = t.hidden;
      t.hidden = !open; b.setAttribute('aria-expanded', String(open)); b.textContent = open ? '收起中文' : '看中文';
    });
  });

  all('.fc').forEach(function (c) {
    c.addEventListener('click', function () { var on = c.classList.toggle('flipped'); c.setAttribute('aria-pressed', String(on)); });
  });
  all('[data-flip-all]').forEach(function (b) {
    b.addEventListener('click', function () {
      var cards = all('.fc').filter(function (c) { return !c.closest('[hidden]'); });
      var open = cards.some(function (c) { return !c.classList.contains('flipped'); });
      cards.forEach(function (c) { c.classList.toggle('flipped', open); c.setAttribute('aria-pressed', String(open)); });
      b.textContent = open ? '全部合上' : '全部翻开';
    });
  });
  all('[data-filter]').forEach(function (chip) {
    chip.addEventListener('click', function () {
      var group = chip.getAttribute('data-group'), val = chip.getAttribute('data-filter');
      all('[data-group="' + group + '"]').forEach(function (c) { c.setAttribute('aria-pressed', String(c === chip)); });
      all('[data-filterable="' + group + '"]').forEach(function (el) {
        el.hidden = !(val === 'all' || (' ' + el.getAttribute('data-tags') + ' ').indexOf(' ' + val + ' ') !== -1);
      });
    });
  });

  function reveal(q, idx) {
    var ans = q.getAttribute('data-answer');
    all('.opt', q).forEach(function (o, i) {
      o.disabled = true; o.classList.remove('picked');
      if (L[i] === ans) o.classList.add('correct'); else if (i === idx) o.classList.add('wrong'); else o.classList.add('dim');
    });
    var ok = idx >= 0 && L[idx] === ans, v = q.querySelector('.verdict');
    q.setAttribute('data-done', ok ? 'right' : 'wrong');
    v.textContent = ok ? '答对了' : (idx < 0 ? '没作答，正确答案是 ' : '答错了，正确答案是 ') + ans;
    v.className = 'verdict ' + (ok ? 'is-right' : 'is-wrong');
    q.querySelector('.why').hidden = false;
    return ok;
  }

  var instant = all('.q[data-mode="instant"]');
  function tally() {
    var right = instant.filter(function (q) { return q.getAttribute('data-done') === 'right'; }).length;
    var done = instant.filter(function (q) { return q.getAttribute('data-done'); }).length;
    all('[data-score]').forEach(function (el) { el.textContent = done ? right + ' / ' + instant.length : instant.length + ' 题'; });
  }
  state.q = state.q || {};
  instant.forEach(function (q) {
    all('.opt', q).forEach(function (o, i) {
      o.addEventListener('click', function () {
        if (q.getAttribute('data-done')) return;
        reveal(q, i); state.q[q.id] = i; save(); tally();
      });
    });
    if (state.q[q.id] != null) reveal(q, state.q[q.id]);
  });
  if (instant.length) tally();
  all('[data-reset-quiz]').forEach(function (b) { b.addEventListener('click', function () { state.q = {}; save(); location.reload(); }); });

  var exam = all('.q[data-mode="exam"]'), timerId = null;
  function stopTimer() { if (timerId) { clearInterval(timerId); timerId = null; } }
  exam.forEach(function (q) {
    all('.opt', q).forEach(function (o) {
      o.addEventListener('click', function () {
        if (body.classList.contains('submitted')) return;
        all('.opt', q).forEach(function (x) { x.classList.remove('picked'); x.setAttribute('aria-pressed', 'false'); });
        o.classList.add('picked'); o.setAttribute('aria-pressed', 'true');
        var n = exam.filter(function (x) { return x.querySelector('.picked'); }).length;
        all('[data-picked]').forEach(function (el) { el.textContent = '已答 ' + n + ' / ' + exam.length; });
      });
    });
  });
  all('[data-submit]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (body.classList.contains('submitted')) return;
      var right = 0;
      exam.forEach(function (q) {
        var idx = -1;
        all('.opt', q).forEach(function (o, i) { if (o.classList.contains('picked')) idx = i; });
        if (reveal(q, idx)) right++;
      });
      body.classList.add('submitted'); stopTimer();
      all('[data-submit]').forEach(function (x) { x.disabled = true; });
      all('[data-result]').forEach(function (el) {
        el.hidden = false;
        el.querySelector('b').textContent = right + ' / ' + exam.length + '（' + Math.round(right * 100 / exam.length) + '%）';
      });
      window.scrollTo(0, 0);
    });
  });
  var tEl = document.querySelector('[data-timer]');
  all('[data-start-timer]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (timerId || !tEl) return;
      var left = parseInt(tEl.getAttribute('data-seconds'), 10); b.disabled = true;
      timerId = setInterval(function () {
        left--; var m = Math.floor(left / 60), s = left % 60;
        tEl.textContent = (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
        if (left <= 0) { stopTimer(); tEl.textContent = '时间到'; }
      }, 1000);
    });
  });

  var now = new Date(), iso = now.getFullYear() + '-' + ('0' + (now.getMonth() + 1)).slice(-2) + '-' + ('0' + now.getDate()).slice(-2);
  all('[data-date]').forEach(function (row) {
    var d = row.getAttribute('data-date');
    if (d === iso) row.classList.add('is-today'); else if (d < iso) row.classList.add('is-past');
  });
  all('[data-countdown]').forEach(function (el) {
    var days = Math.round((new Date(el.getAttribute('data-countdown') + 'T00:00:00') - new Date(iso + 'T00:00:00')) / 86400000);
    el.textContent = days > 0 ? String(days) : (days === 0 ? '今天' : '已考完');
    var lab = el.parentNode.querySelector('.stub-label'); if (lab && days <= 0) lab.hidden = true;
  });
  state.tick = state.tick || {};
  all('input[data-tick]').forEach(function (box) {
    var id = box.getAttribute('data-tick'), row = box.closest('[data-row]');
    box.checked = !!state.tick[id] || box.hasAttribute('data-done'); if (row) row.classList.toggle('is-done', box.checked);
    box.addEventListener('change', function () { state.tick[id] = box.checked; save(); if (row) row.classList.toggle('is-done', box.checked); });
  });

  // 主题：打开页面时看钟，晚上 7 点到早上 6 点用深色；右上角小按钮临时切换，不记忆
  var root = document.documentElement;
  function autoTheme(h) { h = (h == null) ? new Date().getHours() : h; return (h >= 19 || h < 6) ? 'dark' : 'light'; }
  var tbtn = document.createElement('button'); tbtn.type = 'button'; tbtn.className = 'theme'; tbtn.title = '深色 / 浅色';
  function applyTheme(t) { root.setAttribute('data-theme', t); tbtn.textContent = t === 'dark' ? '☀' : '☾'; tbtn.setAttribute('aria-label', t === 'dark' ? '切到浅色' : '切到深色'); }
  tbtn.addEventListener('click', function () { applyTheme(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark'); });
  body.appendChild(tbtn);
  applyTheme(autoTheme());
  window.coachTheme = { auto: autoTheme, apply: applyTheme };
})();
"""

def marker(terms, cap=2):
    """Highlight the first few priority-3 English terms in a paragraph (not every repeat)."""
    terms = sorted({t.strip() for t in terms if t and len(t.strip()) > 2 and "…" not in t}, key=len, reverse=True)
    if not terms:
        return lambda s: s
    pat = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(esc(t)) for t in terms) + r")(?![A-Za-z])", re.I)

    def apply(text):
        seen, out = set(), []
        for part in re.split(r"(<[^>]+>)", text):
            if part.startswith("<"):
                out.append(part)
                continue

            def sub(m):
                key = m.group(1).lower()
                if key in seen or len(seen) >= cap:
                    return m.group(1)
                seen.add(key)
                return f"<mark>{m.group(1)}</mark>"
            out.append(pat.sub(sub, part))
        return "".join(out)
    return apply


def head(title, key, app="coach", wide=False, extra=""):
    cls = "page wide" if wide else "page"
    return ('<!doctype html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{esc(title)}</title>{_DFONTS}<style>{_TOKENS}{CSS}{EXTRA_CSS}</style>{extra}</head>'
            f'<body data-key="{esc(key)}" data-app="{esc(app or "coach")}"><div class="{cls}">')


def course_meta(u=None, plan=None):
    """课程代码、四位短码、考试名：来自单元或计划 JSON，不写死。"""
    ex = (plan or {}).get("exam") or {}
    code = (u or {}).get("course_code") or (plan or {}).get("course_code") or ex.get("course_code") or ""
    return code, (code[-4:] if code else "课程"), (ex.get("name") or "考试")


def load_plan(d):
    pj = os.path.join(d, "plan.json")
    return json.load(io.open(pj, encoding="utf-8")) if os.path.exists(pj) else None


def foot(extra="", script=""):
    """页面结尾。extra 是一句纯文字说明（会转义，不能放 HTML、图片或链接）。"""
    footer = f'<p class="sig">{esc(extra)}</p>' if extra else ""
    return f'{footer}</div><script>{JS}</script>{script}</body></html>'


def level_pill(p):
    name, cls = LEVEL.get(p or 1, LEVEL[1])
    return f'<span class="level {cls}">{name}</span>'


def sources_block(sources, gaps):
    o = ['<details class="more"><summary>资料来源与说明</summary>']
    if sources:
        o.append("<ul>" + "".join(f"<li>{esc(s['label'])}：{rich(s['ref'])}</li>" for s in sources) + "</ul>")
    if gaps:
        o.append("<p><b>还不确定的地方</b></p><ul>" + "".join(f"<li>{rich(g)}</li>" for g in gaps) + "</ul>")
    o.append("<p>个人复习资料，只整理课程材料；自测题是按题型自己出的，不是真题。</p></details>")
    return "".join(o)


def question(i, q, mode, week=None):
    tag = f" · W{week}" if week else ""
    opts = "".join(f'<button class="opt" type="button" aria-pressed="false"><span class="bub">{"ABCD"[k]}</span>'
                   f'<span>{esc(x)}</span></button>' for k, x in enumerate(q["options"]))
    return (f'<article class="q" id="q{i}" data-answer="{esc(q["answer"])}" data-mode="{mode}">'
            f'<p class="q-no">第 {i} 题{tag}</p><p class="q-stem">{esc(q["q_en"])}</p><div class="opts">{opts}</div>'
            f'<p class="verdict" aria-live="polite"></p>'
            f'<div class="why" hidden>{rich(q.get("why_zh"))}<span class="src">出处：{esc(q.get("src"))}</span></div></article>')


def flashcard(en, zh, note, p, tags=""):
    name, cls = LEVEL.get(p or 1, LEVEL[1])
    return (f'<button class="fc" type="button" aria-pressed="false" data-tags="{esc(tags)}" data-filterable="deck">'
            f'<span class="dot {cls}" title="{name}"></span><span class="fc-en">{esc(en)}</span>'
            f'<span class="fc-back"><span class="fc-zh">{esc(zh)}</span>'
            + (f'<span class="fc-note">{rich(note)}</span>' if note else "") + "</span></button>")


def render_unit(u, plan=None):
    concepts = sorted(u.get("concepts", []), key=lambda c: -c.get("priority", 1))
    vocab = sorted(u.get("vocab", []), key=lambda v: -v.get("priority", 1))
    practice = u.get("practice", [])
    p3 = [c["term_en"] for c in concepts if c.get("priority") == 3] + [v["en"] for v in vocab if v.get("priority") == 3]
    mk = marker(p3)
    w = u["week"]
    code, short, exam_name = course_meta(u, plan)
    o = [head(f"W{w} {u['title_zh'].split('：')[0]} · {short} 复习", f"unit-w{w}", app=code.lower() or "coach"),
         '<a class="back" href="复习计划.html">← 复习计划</a>',
         f'<p class="eyebrow">{esc(code)} · {esc(exam_name)} · Week {w}</p>',
         f'<h1>{esc(u["title_zh"])}</h1><p class="title-en">{esc(u["title_en"])}</p>',
         f'<ul class="facts"><li><b>{u.get("minutes", 40)}</b> 分钟</li><li><b>{len(concepts)}</b> 个概念</li>'
         f'<li><b>{len(vocab)}</b> 个词</li><li><b>{len(practice)}</b> 道自测题</li></ul>',
         '<nav class="steps" aria-label="今天分三步">'
         '<a href="#read"><span class="n">1</span>读懂概念</a><a href="#words"><span class="n">2</span>记单词</a>'
         f'<a href="#quiz"><span class="n">3</span>自测 <span data-score>{len(practice)} 题</span></a></nav>',
         f'<p class="lead">{mk(rich(u["one_line_zh"]))}</p>',
         f'<p class="note"><span class="label">考试大概考什么</span>{rich(u["why_exam_zh"])}</p>',
         '<section id="read"><h2><span class="n">1</span>读懂概念</h2>'
         '<p class="hint">先读中文解释，再看课件原句。黄色是考试会用的英文词；标「必会」的先弄懂。</p><div class="stack">']
    for i, c in enumerate(concepts, 1):
        o.append(f'<article class="concept"><div class="term-row"><span class="term">{esc(c["term_en"])}</span>'
                 f'<span class="term-zh">{esc(c.get("term_zh"))}</span>{level_pill(c.get("priority"))}</div>'
                 f'<p>{mk(rich(c["explain_zh"]))}</p>')
        if c.get("key_sentence_en"):
            o.append(f'<div class="quote"><p class="en">“{esc(c["key_sentence_en"])}”</p>'
                     f'<p class="zh" id="zh{i}" hidden>{esc(c.get("key_sentence_zh"))}</p>'
                     f'<div class="quote-foot"><span class="src">{esc(c.get("src"))}</span>'
                     f'<button class="toggle" type="button" data-zh-toggle aria-controls="zh{i}" aria-expanded="false">看中文</button></div></div>')
        rows = [("例子", c.get("example_zh")), ("别混淆", c.get("confuse_zh"))]
        rows = [(k, v) for k, v in rows if v]
        if rows:
            o.append('<dl class="aside">' + "".join(f"<dt>{k}</dt><dd>{rich(v)}</dd>" for k, v in rows) + "</dl>")
        o.append("</article>")
    o.append("</div>")
    if u.get("readings"):
        o.append('<h3>本周阅读</h3><p class="hint">阅读也会出题。标「摘要」的只拿到了简介，细节以原文为准。</p><ul class="readings">')
        for r in u["readings"]:
            acc = r.get("accessed", "")
            kt = "".join(f"<li>{esc(k)}</li>" for k in r.get("key_terms", []))
            o.append(f'<li class="reading"><span class="badge{" full" if "全文" in acc else ""}">{esc(acc)}</span>'
                     f'<p class="cite">{esc(r["citation"])}</p><p>{rich(r.get("gist_zh"))}</p>'
                     + (f'<ul class="chips">{kt}</ul>' if kt else "")
                     + f'<p class="note"><span class="label">可能怎么考</span>{rich(r.get("exam_angle_zh"))}</p></li>')
        o.append("</ul>")
    o.append("</section>")

    n3 = sum(1 for v in vocab if v.get("priority") == 3)
    o.append('<section id="words"><h2><span class="n">2</span>记单词</h2>'
             '<p class="hint">先看英文，心里说出中文意思，再点卡片翻过来对答案。</p>'
             f'<div class="toolbar"><button class="chip" type="button" data-group="deck" data-filter="all" aria-pressed="true">全部 {len(vocab)}</button>'
             f'<button class="chip" type="button" data-group="deck" data-filter="l3" aria-pressed="false">只看必会 {n3}</button>'
             '<button class="chip" type="button" data-flip-all>全部翻开</button></div><div class="deck">')
    for v in vocab:
        o.append(flashcard(v["en"], v["zh"], v.get("note_zh"), v.get("priority"), LEVEL.get(v.get("priority", 1), LEVEL[1])[1]))
    o.append("</div></section>")

    o.append('<section id="quiz"><h2><span class="n">3</span>自测</h2>'
             '<p class="hint">按考试题型自己出的练习题，不是真题。点一个选项，马上看对错和中文解析；做过的会记住。</p><div class="stack">')
    o += [question(i, q, "instant") for i, q in enumerate(practice, 1)]
    o.append('</div><div class="submit-row"><button class="btn" type="button" data-reset-quiz>清空重做</button></div></section>')

    if u.get("recap_zh"):
        o.append("<h2>三句话记住这一周</h2><ul class=\"recap\">" + "".join(f"<li>{mk(rich(x))}</li>" for x in u["recap_zh"]) + "</ul>")
    if plan:
        days = plan.get("days", [])
        k = next((j for j, d in enumerate(days) if d.get("unit") == f"W{w}"), None)
        nxt = next((d for d in days[k + 1:] if d.get("file")), None) if k is not None else None
        if nxt:
            o.append(f'<p class="next">今天就到这里。下一份：{esc(nxt["date"][5:])} {esc(nxt["weekday"])} · '
                     f'<a href="{esc(nxt["file"])}">{esc(nxt["task_zh"])}</a></p>')
    o.append(sources_block(u.get("sources"), u.get("gaps_zh")))
    return "\n".join(o) + foot()


def render_plan(p):
    e = p["exam"]
    code, short, exam_name = course_meta(None, p)
    ed = e.get("date") or ""
    d0 = parse_date(ed)
    dlabel = f"{d0:%m-%d} {WD[d0.weekday()]}" if d0 else ed
    subbits = [x for x in (e.get("tz_note"), f"{e['duration_min']} 分钟" if e.get("duration_min") else None,
                           f"{e['n_questions']} 道选择题" if e.get("n_questions") else None,
                           f"考 {e['scope']}" if e.get("scope") else None) if x]
    facts = e.get("facts") or []
    facts = facts[1:] if (ed and facts) else facts
    weight = f" · {esc(e['weight'])}" if e.get("weight") else ""
    o = [head(f"{short} 考前复习计划", "plan", app=code.lower() or "coach"),
         f'<p class="eyebrow">{esc(code)} · {esc(exam_name)}{weight}</p><h1>考前复习计划</h1>',
         f'<p class="title-en">{esc(p.get("subtitle"))}</p>',
         '<section class="ticket" aria-label="考试信息"><div class="ticket-main">'
         f'<p class="eyebrow" style="margin:0">考试时间</p><p class="when"><small>{esc(dlabel)}</small>{esc(e.get("time") or "")}</p>'
         f'<p class="ticket-sub">{esc(" · ".join(subbits))}</p></div>'
         f'<div class="stub"><span class="stub-big" data-countdown="{esc(ed)}">—</span><span class="stub-label">天后开考</span></div></section>',
         '<ul class="plainlist">' + "".join(f"<li>{rich(x)}</li>" for x in facts) + "</ul>",
         "<h2>目标</h2>" + "".join(f"<p>{rich(x)}</p>" for x in p["goal"]),
         '<section><h2>每天一份</h2><p class="hint">每天只打开当天那一份。做完就勾上，勾选只存在这台设备的浏览器里。</p><ol class="days">']
    for d in p["days"]:
        task = f'<a href="{esc(d["file"])}">{esc(d["task_zh"])}</a>' if d.get("file") else rich(d["task_zh"])
        o.append(f'<li class="day" data-row data-date="{esc(d["date"])}">'
                 f'<input type="checkbox" data-tick="{esc(d["date"])}" aria-label="{esc(d["date"])} 做完了">'
                 f'<span class="d">{esc(d["date"][5:])}<small>{esc(d["weekday"])}</small></span>'
                 f'<span class="t">{task}</span><span class="m">{d["minutes"]} 分钟</span></li>')
    o.append("</ol></section>")
    o.append('<section><h2>题干常用词</h2><p class="hint">选择题的题干和选项里经常出现的英文（通用考试英语）。</p><div class="stems">')
    o += [f'<div class="stem"><span class="en">{esc(w["en"])}</span><span>{esc(w["zh"])}</span>'
          + (f'<span class="nt">{rich(w["note_zh"])}</span>' if w.get("note_zh") else "") + "</div>" for w in p["stem_words"]]
    o.append("</div></section>")
    o.append('<section><h2>做选择题的小办法</h2><ul class="plainlist">' + "".join(f"<li>{rich(x)}</li>" for x in p["tips"]) + "</ul></section>")
    o.append('<section><h2>考试当天</h2><ul class="checklist">')
    o += [f'<li data-row><input type="checkbox" data-tick="examday-{i}" aria-label="已准备"><span class="t">{rich(x)}</span></li>'
          for i, x in enumerate(p["exam_day"])]
    o.append("</ul></section>")
    o.append(sources_block(p.get("sources"), None))
    return "\n".join(o) + foot()


def load_units(d):
    return sorted((json.load(io.open(f, encoding="utf-8")) for f in glob.glob(os.path.join(d, "W*.json"))), key=lambda u: u["week"])


def render_vocab(d):
    units = load_units(d)
    code, short, exam_name = course_meta(units[0] if units else None, load_plan(d))
    wr = f"W{units[0]['week']}–W{units[-1]['week']}" if units else ""
    o = [head(f"{short} 必会单词", "vocab", app=code.lower() or "coach"), '<a class="back" href="复习计划.html">← 复习计划</a>',
         f'<p class="eyebrow">{esc(code)} · {esc(exam_name)} · {wr}</p><h1>必会单词</h1>',
         f'<p class="title-en">{len(units)} 周里标「必会」的概念和单词。遮住中文，看英文能不能说出意思，再点卡片对答案。</p>',
         '<div class="toolbar"><button class="chip" type="button" data-group="weeks" data-filter="all" aria-pressed="true">全部</button>']
    o += [f'<button class="chip" type="button" data-group="weeks" data-filter="w{u["week"]}" aria-pressed="false">W{u["week"]}</button>' for u in units]
    o.append('<button class="chip" type="button" data-flip-all>全部翻开</button></div>')
    for u in units:
        cards, seen = [], set()
        for c in u.get("concepts", []):
            if c.get("priority") == 3 and "…" not in c["term_en"] and c["term_en"].lower() not in seen:
                seen.add(c["term_en"].lower())
                cards.append(flashcard(c["term_en"], c.get("term_zh", ""), "", 3))
        for v in u.get("vocab", []):
            if v.get("priority") == 3 and v["en"].lower() not in seen:
                seen.add(v["en"].lower())
                cards.append(flashcard(v["en"], v["zh"], v.get("note_zh"), 3))
        o.append(f'<section data-filterable="weeks" data-tags="w{u["week"]}"><h2>W{u["week"]} · {esc(u["title_zh"].split("：")[0])}'
                 f'<span class="src">{len(cards)} 个</span></h2><div class="deck">' + "".join(cards) + "</div></section>")
    return "\n".join(o) + foot()


def render_mock(d, n=25):
    units = load_units(d)
    pools = [[(u["week"], q) for q in reversed(u.get("practice", []))] for u in units]
    picked = []
    while len(picked) < n and any(pools):  # round-robin so every week is covered evenly
        for pool in pools:
            if pool and len(picked) < n:
                picked.append(pool.pop(0))
    qs = sorted(picked, key=lambda x: x[0])
    minutes = round(len(qs) * 1.2)
    code, short, exam_name = course_meta(units[0] if units else None, load_plan(d))
    o = [head(f"{short} 模拟小测", "mock", app=code.lower() or "coach"), '<a class="back" href="复习计划.html">← 复习计划</a>',
         f'<p class="eyebrow">{esc(code)} · {esc(exam_name)} · 模拟</p><h1>模拟小测</h1>',
         f'<p class="title-en">{len(qs)} 题，建议 {minutes} 分钟：和真考试一样，一题一分钟多一点。先全部做完，再交卷看对错。</p>',
         f'<div class="exambar"><span class="timer" data-timer data-seconds="{minutes * 60}">{minutes:02d}:00</span>'
         '<button class="btn" type="button" data-start-timer>开始计时</button><span class="spacer"></span>'
         f'<span class="picked-count" data-picked>已答 0 / {len(qs)}</span><button class="btn primary" type="button" data-submit>交卷</button></div>',
         '<p class="result" data-result hidden>得分 <b></b>。错的题下面有中文解析，回到那一周的单元再看一遍。</p><div class="stack">']
    o += [question(i, q, "exam", w) for i, (w, q) in enumerate(qs, 1)]
    o.append('</div><div class="submit-row"><button class="btn primary" type="button" data-submit>交卷</button></div>')
    return "\n".join(o) + foot()


def render_all(d):
    plan_path = os.path.join(d, "plan.json")
    plan = json.load(io.open(plan_path, encoding="utf-8")) if os.path.exists(plan_path) else None
    for u in load_units(d):
        io.open(os.path.join(d, f"W{u['week']}.html"), "w", encoding="utf-8").write(render_unit(u, plan))
    if plan:
        io.open(os.path.join(d, "复习计划.html"), "w", encoding="utf-8").write(render_plan(plan))
    io.open(os.path.join(d, "单词总表.html"), "w", encoding="utf-8").write(render_vocab(d))
    io.open(os.path.join(d, "模拟小测.html"), "w", encoding="utf-8").write(render_mock(d))
    print("rendered", d)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    mode = sys.argv[1]
    if mode == "all":
        render_all(sys.argv[2])
        sys.exit()
    src, dst = sys.argv[2], sys.argv[3]
    if mode == "unit":
        pj = os.path.join(os.path.dirname(os.path.abspath(src)), "plan.json")
        out = render_unit(json.load(io.open(src, encoding="utf-8")),
                          json.load(io.open(pj, encoding="utf-8")) if os.path.exists(pj) else None)
    elif mode == "plan":
        out = render_plan(json.load(io.open(src, encoding="utf-8")))
    elif mode == "vocab":
        out = render_vocab(src)
    else:
        out = render_mock(src, int(sys.argv[4]) if len(sys.argv) > 4 else 25)
    io.open(dst, "w", encoding="utf-8").write(out)
    print("written", dst)
