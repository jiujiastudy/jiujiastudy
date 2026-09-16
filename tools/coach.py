"""<NAME> 命令行入口。数据在 <HOME_ENV>（默认桌面 <NAME>/.coach），程序在本目录。

  doctor  [--detect-site] [--env-dialog] [--host URL] [--school NAME] [--tz ZONE] [--fix-perms] [--agent auto|claude|codex|other] [--dry-run]
          体检：装库、认学校（浏览器记录）、收 token、建档、按宿主写权限。缺什么就说什么，能修的自己修。
  status                                     一屏现状 + 状态评估，零副作用
  collect [--quick] [--touch] [--download] | --materials CODE WEEK
          只读采集（默认只元数据，不下载课件）
  radar   [--days 14] [--fetch] [--write]    deadline 雷达（每门课下一条 / 最急 / 撞车 / 已确认 / 待确认 / 已过期未交 / 新变化 / 状态）
  study   [--week N] [--write] [--zh FILE|-] [--out HTML] [--force]
          本周该学什么：脚本按模块和 deadline 排三桶和每天必做；--zh 传中文润色；--write 落盘并渲染
  record  done [目标] | mood 词 [--note] | product --file --status [--course --log] | pending 文本 --course [--blocks 日期 --ask-en --ask-zh]
          | asked ID | resolve ID --resolution 文本 | decision 文本 [--course] | note 作业id 文本
          | deadline 事项 --course 课 --due 日期 [--time 时刻 --weight --url --pending] | deadline --list | deadline --remove 序号或事项
  week <plans/X.json> [--out HTML] [--md] [--record]   渲染一份现成的周计划 JSON
  guide <导读.json> [--out] [--record] · unit {unit|plan|vocab|mock|all} <src> [dst] · lecture <精讲.json> [--out]   工具箱渲染器
  config show | get KEY | set KEY VALUE | course CODE [--materials-ai on|off]
          看 / 改 config.json（KEY 用点号，如 term.week1_monday）；course 管这门课的课件文字交不交给 AI（默认 off，原件照下）
  migrate [--dry-run] · share [--out DIR] [--zip] · api get|download|post|upload …
每个命令都接受 --home DIR、--date（YYYY-MM-DD 或写到时分的时刻，把「现在」钉住）、--json（stdout 只有一个 JSON 对象，出错时是 {"error", "exit"}，命令写错也是）。--version 打印版本。
退出码：0 成功（status 有提醒、还没建档也是 0；doctor 连上了 Canvas、档案齐了也是 0，列出的事照做）；
1 有提醒或部分没完成（采集有错、doctor 还没连上 Canvas、发送被取消），不是失败；2 阻塞或出错（只打印一句中文）；3 档案版本太老。
"""
import argparse
import io
import json
import os
import re
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brand  # noqa: E402
import canvas_api  # noqa: E402
from cc_config import CoachError, Ctx, course_option, missing_config_message, parse_value  # noqa: E402
from cc_paths import WEEK_PAGE, coach_cmd, home_dir  # noqa: E402
from cc_store import get_key, load_json_arg, set_key  # noqa: E402


def out_json(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=1, default=str) + "\n")


def date_of(ctx, args):
    return today_of(ctx, args).isoformat()


def today_of(ctx, args):
    return ctx.clock.today_user()  # --date 已经把「现在」钉住了（check_date），今天从它算


def _record_product_if(ctx, args, html_path, status, course=None):
    if getattr(args, "record", False):
        import cc_record
        cc_record.record_product(ctx, ctx.rel(html_path), status, course=course)


# ---------------------------------------------------------------- commands
def cmd_doctor(args):
    import cc_doctor
    code, res = cc_doctor.doctor(args)
    if not args.json:
        print(res["text"])
    return code, res


def cmd_status(args):
    import cc_radar
    home = home_dir(args.home)
    if not os.path.exists(os.path.join(home, "config.json")):  # 还没建档不算错：告诉 AI 下一步是 doctor
        msg = missing_config_message(home)
        if not args.json:
            print(msg)
        return 0, {"needs_setup": True, "home": home, "message": msg}
    ctx = Ctx(args.home, quiet=args.json)
    d, text = cc_radar.status(ctx, today_of(ctx, args))
    if not args.json:
        print(text)
    return 0, d


def cmd_collect(args):
    import cc_collect
    import cc_digest
    import cc_downloads
    ctx = Ctx(args.home, quiet=args.json)
    date = date_of(ctx, args)
    if args.materials:
        code, week = args.materials
        r = cc_downloads.collect_materials(ctx, code.upper(), week)
        return (1 if r.get("errors") or r.get("error") else 0), r
    if getattr(args, "download_worker", False):
        cap = max(1, int((ctx.cfg.get("materials") or {}).get("per_run") or 30))
        r = cc_downloads.run_downloads(ctx, cap=cap, lock_token=getattr(args, "download_token", None))
        if not args.json:
            print(f"课件下载 {len(r['downloaded'])} 个，队列还剩 {r['left']}" +
                  (f"，出错 {len(r['errors'])}" if r["errors"] else ""))
        return (1 if r.get("errors") else 0), {"downloads": r, "worker": True}
    # A background request consumes the queue produced by the preceding
    # metadata collection. Do not synchronously collect Canvas again here.
    if args.download and args.background:
        info = _downloads(ctx, args)
        return 0, {"downloads": info, "background": True}
    import datetime as _dt
    from cc_time import parse_ts as _pts
    last = _pts(ctx.state.get("last_fetch"))
    age = (ctx.clock.now_utc() - last) if last else None
    if age is not None and age < _dt.timedelta(minutes=10) and not args.force and not args.download and cc_collect.cacheable_snapshot(ctx):
        mins = max(1, int(age.total_seconds() // 60))  # 刚采过：不重拉，免得每问一句就等十几秒
        if args.touch:
            ctx.state["last_check"] = ctx.clock.now_utc().isoformat()
            ctx.save_state()
        if not args.json:
            print(f"（{mins} 分钟前刚采过，直接用上次的快照；要重拉加 --force）")
            cc_digest.print_context(ctx, date)
        res = {"skipped": True, "age_minutes": mins, "errors": [], "quick": args.quick}
        res["downloads"] = _downloads(ctx, args)
        return 0, res
    d = cc_collect.collect(ctx, date, quick=args.quick, touch=args.touch, download=(True if args.download else None))
    if not args.json:
        cc_digest.print_digest(d)
        cc_digest.print_context(ctx, date)
    promoted = bool(d.get("promoted", not d.get("errors")))
    res = {"digest_path": ctx.P("raw", "daily", date, "digest.json") if promoted else None,
           "failure_path": d.get("failure_path"), "complete": bool(d.get("complete", promoted)),
           "promoted": promoted, "errors": d["errors"], "quick": args.quick,
           "counts": {k: len(d.get(k) or []) for k in ("new_announcements", "staff_messages", "changed_assignments", "submission_changes",
                                                       "new_items", "unlocked_items", "locked_items", "downloaded", "skipped_downloads")},
           "readiness": d.get("readiness"), "queued_downloads": d.get("queued_downloads", 0)}
    res["downloads"] = _downloads(ctx, args)
    return (1 if d["errors"] else 0), res


def _downloads(ctx, args):
    """collect 之后：--download 下队列（--background 另起进程，立刻返回）。"""
    import cc_downloads
    if not getattr(args, "download", False):
        return None
    if getattr(args, "background", False):
        info = cc_downloads.spawn_downloads(ctx)
        if not args.json:
            if info.get("started"):
                msg = f"已启动，队列 {info['queued']} 个，日志 {info['log']}"
            elif info.get("running"):
                msg = f"已经在运行，队列 {info['queued']} 个，日志 {info['log']}"
            else:
                msg = "队列是空的"
            print(f"课件后台下载：{msg}")
        return info
    r = cc_downloads.run_downloads(ctx, cap=10)
    if not args.json:
        if r.get("running"):
            print(f"课件后台下载已经在运行，队列 {r['left']} 个；这次没有重复启动")
        else:
            print(f"课件下载 {len(r['downloaded'])} 个，队列还剩 {r['left']}" + (f"，出错 {len(r['errors'])}" if r["errors"] else ""))
    return r


def cmd_radar(args):
    import cc_collect
    import cc_deadlines
    import cc_radar
    import cc_state
    ctx = Ctx(args.home, quiet=args.json)
    today = today_of(ctx, args)
    if args.fetch:
        cc_collect.collect(ctx, today.isoformat(), quick=True, touch=not ctx.is_v1)
    rows = cc_radar.rows(ctx, today, args.days)
    ev = cc_state.evaluate(ctx, today, cc_deadlines.plan_today(ctx, today), rows)
    md = cc_radar.to_markdown(ctx, rows, today, ev)
    written = cc_radar.write(ctx, rows, today, ev) if args.write else []
    if not args.json:
        print(md)
        for w in written:
            print("WRITTEN=" + w)
    return 0, {"rows": [{k: r.get(k) for k in ("rel", "when", "course", "item", "weight", "status", "pending", "url", "src", "note",
                                                "days_left", "kind", "overdue", "undated")} for r in rows],
               "state_eval": ev, "markdown": md, "written": written}


def cmd_study(args):
    import cc_record
    import cc_study
    import render_week
    ctx = Ctx(args.home, quiet=args.json)
    today = today_of(ctx, args)
    plan = cc_study.build(ctx, today, week=args.week, days=args.days)
    plan = cc_study.apply_overlay(plan, load_json_arg(args.zh))
    res = {"plan": plan, "written": None}
    if args.write:
        path = cc_study.write_plan(ctx, plan, force=args.force)
        r = render_week.write(path, args.out, week_no=plan.get("week_no"), generated=today.isoformat())
        r["copy"] = render_week.publish(ctx, r["html"]) if not args.out else None
        ctx.state["current_plan"] = ctx.rel(path)
        ctx.save_state()
        cc_record.record_product(ctx, ctx.rel(r["html"]), "📦 本周学习清单", course="全部课程",
                                 log=f"本周学习清单 `{ctx.rel(path)}`：{plan['study']['items_total']} 项，最要紧：{(plan['study'].get('top_one') or {}).get('title', '无')}")
        res.update({"written": r["html"], "json": path, "md": r.get("md"), "copy": r.get("copy")})
    if not args.json:
        print(cc_study.to_text(plan))
        if res.get("written"):
            print("JSON=" + res["json"])
            print("WRITTEN=" + res["written"])
            if res.get("md"):
                print("MD=" + res["md"])
            if res.get("copy"):
                print("COPY=" + res["copy"])
    return 0, res


def cmd_paths(args):
    """资料夹在哪：根目录、每门课的 课件 / 产出，以及机器档案。AI 写产物前先问这个。"""
    ctx = Ctx(args.home, quiet=args.json)
    ctx.ensure_dirs()
    codes = [args.code.upper()] if args.code else [c["code"] for c in ctx.cfg.get("courses") or []]
    r = {"root": ctx.root, "home": ctx.home, "week_html": os.path.join(ctx.root, WEEK_PAGE), "radar_html": os.path.join(ctx.root, "Deadline雷达.html"),
         "courses": {c: {"folder": ctx.course_dir(c), "materials": ctx.materials_dir(c), "output": ctx.output_dir(c)} for c in codes}}
    if not args.json:
        print(f"资料夹：{r['root']}\n机器档案：{r['home']}\n{brand.NAME} 周手帐：{r['week_html']}\ndeadline 雷达：{r['radar_html']}")
        for c, d in r["courses"].items():
            print(f"{c}：课件 {d['materials']} ｜ 产出 {d['output']}")
    return 0, r


def cmd_record(args):
    import cc_deadlines
    import cc_radar
    import cc_record
    import cc_state
    op = args.op
    if op == "deadline" and not args.list and args.remove is None and not (args.item and args.course and args.due):
        raise CoachError('要写事项、--course 和 --due，例：record deadline "Essay" --course ACCT1101 --due 09-20 --time 23:59', 2)
    ctx = Ctx(args.home, quiet=args.json)
    if op == "product":
        r = cc_record.record_product(ctx, args.file, args.status, course=args.course, log=args.log, date=date_of(ctx, args))
        msg = f"INDEX={r['index']} LOG=appended"
    elif op == "done":
        r = cc_record.mark_done(ctx, args.target, today_of(ctx, args))
        nxt = r.get("next")
        today = today_of(ctx, args)
        ev = cc_state.evaluate(ctx, today, cc_deadlines.plan_today(ctx, today), cc_radar.rows(ctx, today))
        r["state_eval"] = ev
        msg = ("✅ " + "；".join(r["marked"]) + (f"\n明天：{nxt['must']}" + (f"（第一步：{nxt['first_step']}）" if nxt.get("first_step") else "") if nxt else "")
               + "\n" + cc_state.state_line(ev))
    elif op == "note":
        r = cc_record.add_note(ctx, args.assignment_id, args.text)
        msg = f"记下了 [{r['assignment_id']}]：{r['note'] or '（已清除）'}。雷达里这条不再算过期。"
    elif op == "deadline" and args.list:
        r = {"deadlines": cc_record.list_deadlines(ctx)}
        msg = "\n".join(f"{x['n']}. {x['course']} {x['item']} · {x['when']}" + ("（待确认）" if x["pending"] else "")
                        for x in r["deadlines"]) or "还没记过手动 deadline。"
    elif op == "deadline" and args.remove is not None:
        r = cc_record.remove_deadline(ctx, args.remove)
        msg = f"删掉了：{r.get('course')} {r.get('item')} {cc_record.deadline_text(ctx.clock, r)}"
    elif op == "deadline":
        r = cc_record.add_deadline(ctx, args.item, args.course, args.due, time=args.time, time_text=args.time_text, weight=args.weight,
                                   url=args.url, note=args.note, source=args.source, status=args.status, pending=args.pending,
                                   assignment_id=args.assignment_id)
        msg = (f"手动 deadline {'更新' if r['action'] == 'updated' else '+1'}：{r['course']} {r['item']} "
               f"{cc_record.deadline_text(ctx.clock, r)}").rstrip() + ("（待确认）" if r["pending"] else "")
    elif op == "mood":
        r = cc_state.add_mood(ctx, args.word, note=args.note)
        today = today_of(ctx, args)
        ev = cc_state.evaluate(ctx, today, cc_deadlines.plan_today(ctx, today), cc_radar.rows(ctx, today))
        r = {"mood": r, "state_eval": ev}
        msg = "记下了。" + cc_state.state_line(ev)
    elif op == "pending":
        r = cc_record.add_pending(ctx, args.text, args.course, blocks=args.blocks, ask_en=args.ask_en, ask_zh=args.ask_zh)
        msg = f"待确认 +1 {r['id']}"
    elif op == "asked":
        r = cc_record.mark_asked(ctx, args.id)
        msg = f"{r['id']} 已问 {r['times_asked']} 次"
    elif op == "resolve":
        r = cc_record.resolve_pending(ctx, args.id, args.resolution)
        msg = f"{r['id']} 已解决：{r['resolution']}"
    elif op == "decision":
        r = cc_record.add_decision(ctx, args.text, course=args.course)
        msg = f"已记决定（不再提起）：{r['text']}"
    else:
        raise CoachError(f"未知 record 子命令：{op}", 2)
    if not args.json:
        print(msg)
    return 0, r


def cmd_week(args):
    import cc_record
    import render_week
    ctx = Ctx(args.home, quiet=args.json)
    src = args.src if os.path.exists(args.src) else ctx.P(args.src)
    data = json.load(open(src, encoding="utf-8"))
    week_no = data.get("week_no") or cc_record.week_no_of(ctx, data)
    res = render_week.write(src, args.out, week_no=week_no, generated=date_of(ctx, args), force_md=args.md)
    if not ctx.is_v1:
        ctx.state["current_plan"] = ctx.rel(src)
        ctx.save_state()
    _record_product_if(ctx, args, res["html"], "📦 周计划（源 " + ctx.rel(src) + "）", course="全部课程")
    if not args.json:
        print("WRITTEN=" + res["html"])
        print("MD=" + (res["md"] or f"未覆盖（{res['md_skipped']} 是手写的，加 --md 强制）"))
    return 0, {"written": res["html"], "md": res["md"], "week_no": week_no}


def cmd_guide(args):
    import render_guide
    ctx = Ctx(args.home, quiet=args.json)
    src = args.src if os.path.exists(args.src) else ctx.P(args.src)
    out = args.out or os.path.splitext(src)[0] + ".html"
    render_guide.write(src, out, generated=date_of(ctx, args))
    _record_product_if(ctx, args, out, "📦 课件导读")
    if not args.json:
        print("WRITTEN=" + out)
    return 0, {"written": out}


def cmd_lecture(args):
    import render_lecture
    ctx = Ctx(args.home, quiet=args.json)
    src = args.src if os.path.exists(args.src) else ctx.P(args.src)
    out = args.out or os.path.splitext(src)[0] + ".html"
    d = json.load(io.open(src, encoding="utf-8"))
    io.open(out, "w", encoding="utf-8").write(render_lecture.render(d))
    _record_product_if(ctx, args, out, "📦 逐页精讲")
    if not args.json:
        print("WRITTEN=" + out)
    return 0, {"written": out}


def cmd_unit(args):
    import render_unit
    ctx = Ctx(args.home, quiet=args.json)
    src = args.src if os.path.exists(args.src) else ctx.P(args.src)
    written = []
    if args.mode == "all":
        render_unit.render_all(src)
        written = sorted(p for p in os.listdir(src) if p.endswith(".html"))
    else:
        dst = args.dst or (os.path.splitext(src)[0] + ".html" if args.mode in ("unit", "plan")
                           else os.path.join(src, {"vocab": "单词总表.html", "mock": "模拟小测.html"}[args.mode]))
        if args.mode == "unit":
            html = render_unit.render_unit(json.load(io.open(src, encoding="utf-8")), render_unit.load_plan(os.path.dirname(os.path.abspath(src))))
        elif args.mode == "plan":
            html = render_unit.render_plan(json.load(io.open(src, encoding="utf-8")))
        elif args.mode == "vocab":
            html = render_unit.render_vocab(src)
        else:
            html = render_unit.render_mock(src, args.n)
        io.open(dst, "w", encoding="utf-8").write(html)
        written = [dst]
        _record_product_if(ctx, args, dst, "📦 复习包")
    if not args.json:
        for w in written:
            print("WRITTEN=" + str(w))
    return 0, {"written": written}


def cmd_config(args):
    ctx = Ctx(args.home, quiet=True)
    if args.op == "show":
        res = ctx.cfg
        if not args.json:
            out_json(res)
        return 0, res
    if args.op == "get":
        v = get_key(ctx.cfg, args.key)
        if not args.json:
            print(json.dumps(v, ensure_ascii=False))
        return 0, {"key": args.key, "value": v}
    if args.op == "course":
        res = course_option(ctx, args.code, args.materials_ai)
        if not args.json:
            print(res["message"])
        return 0, res
    set_key(ctx.raw_cfg, args.key, parse_value(args.value))
    ctx.save_config()
    if not args.json:
        print(f"{args.key} = {json.dumps(get_key(ctx.cfg, args.key), ensure_ascii=False)}")
    return 0, {"key": args.key, "value": get_key(ctx.cfg, args.key)}


def cmd_migrate(args):
    import cc_doctor
    code, res = cc_doctor.migrate(home_dir(args.home), args.dry_run)
    if not args.json and not res.get("already_current"):
        print(("【预演】" if args.dry_run else "") + f"v{res.get('from')} → v{res.get('to')}")
        if res.get("moved_keys"):
            print("迁出的叙事键：" + ", ".join(res["moved_keys"]))
        if res.get("fixed"):
            print("修复：" + "；".join(res["fixed"]))
        if res.get("backup_dir"):
            print("backup_dir=" + res["backup_dir"])
    return code, res


def cmd_share(args):
    import cc_install
    code, res = cc_install.share(home_dir(args.home), args.out, args.zip)
    if not args.json:
        print(f"分享版：{res['out']}（{len(res['copied'])} 个文件）" + (f"，zip：{res['zip']}" if res.get("zip") else ""))
        for f in res["flagged"]:
            print("个人信息！" + f)
        for w in res["warned"]:
            print("提醒（课程 ID/代码/域名）：" + w)
    return code, res


def cmd_api(args):
    import cc_write
    return cc_write.run_api(args)


def cmd_render(args):
    import cc_digest
    ctx = Ctx(args.home, quiet=args.json)
    date = date_of(ctx, args)
    r = cc_digest.render(ctx, date, load_json_arg(args.zh), out=args.out, record=not args.no_record)
    if not args.json:
        print("REPORT=" + r["report"])
        print("REVISION=" + (r["revision"] or "none"))
        print(f"CHANGES={r['changes']} DEADLINES_14D={r['deadlines_14d']} OFFLINE={r['offline']}")
        print("ONE_THING=" + (r["one_thing"] or ""))
    return (1 if r["offline"] else 0), r


def cmd_run(args):
    import cc_collect
    import cc_digest
    ctx = Ctx(args.home, quiet=args.json)
    date = date_of(ctx, args)
    try:
        d = cc_collect.collect(ctx, date, quick=args.quick, touch=False)
        if not args.json:
            cc_digest.print_digest(d)
    except (canvas_api.CanvasError, urllib.error.URLError) as e:
        print(f"采集失败：{e}", file=sys.stderr)
    return cmd_render(args)


# ---------------------------------------------------------------- main
_ARG_NAMES = {"cmd": "子命令", "op": "子命令"}  # argparse 的 dest → 报错里给人看的名字
_ZH_PUNCT = "：，。、（）"


def _join_zh(*parts):
    """拼成一句：中文和英文 / 数字之间加一个空格，中文标点两边不加。"""
    out = ""
    for p in parts:
        if (out and p and out[-1].isascii() != p[0].isascii() and not out[-1].isspace() and not p[0].isspace()
                and out[-1] not in _ZH_PUNCT and p[0] not in _ZH_PUNCT):
            out += " "
        out += p
    return out


def usage_error_zh(message):
    """argparse 的英文报错 → 一句中文；认不出的原样附在后面。"""
    message = " ".join(str(message).split())
    name = lambda s: _ARG_NAMES.get(s, s)  # noqa: E731
    m = re.match(r"unrecognized arguments: (.+)$", message)
    if m:
        return _join_zh("不认识的参数：", m.group(1))
    m = re.match(r"the following arguments are required: (.+)$", message)
    if m:
        return _join_zh("少了", "、".join(name(a.strip()) for a in m.group(1).split(",")))
    m = re.match(r"argument (\S+?): invalid choice: '?(.*?)'? \(choose from (.+)\)$", message)
    if m:
        return _join_zh(name(m.group(1)), "不能是", m.group(2), "，可选：", m.group(3).replace("'", ""))
    m = re.match(r"argument (\S+?): invalid (?:int|float) value: '?(.*?)'?$", message)
    if m:
        return _join_zh(name(m.group(1)), "要填数字，现在是", m.group(2))
    m = re.match(r"argument (\S+?): expected one argument$", message)
    if m:
        return _join_zh(name(m.group(1)), "后面要跟一个值")
    m = re.match(r"argument (\S+?): expected (\d+) arguments$", message)
    if m:
        return _join_zh(name(m.group(1)), "后面要跟", m.group(2), "个值")
    m = re.match(r"argument (\S+?): expected at least one argument$", message)
    if m:
        return _join_zh(name(m.group(1)), "后面至少要跟一个值")
    return _join_zh("命令行参数不对：", message)


class ArgParser(argparse.ArgumentParser):
    """命令写错了也守约定：一句中文（带 --json 时 stdout 是 {"error", "exit": 2}），退出码 2，不打印英文用法。"""
    json_errors = False  # main() 按命令行里有没有 --json 设置

    def error(self, message):
        msg = _join_zh(usage_error_zh(message), "。看用法：", f"{self.prog} -h")
        if ArgParser.json_errors:
            out_json({"error": msg, "exit": 2})
        else:
            print(msg, file=sys.stderr)
        sys.exit(2)


def build_parser():
    common = ArgParser(add_help=False)
    common.add_argument("--home", default=None, help=f"档案目录（默认 {brand.env_name('HOME')} 或桌面 {brand.NAME}/.coach）")
    common.add_argument("--date", default=None, help="把「现在」钉在某一刻：YYYY-MM-DD（那天此刻）或 2026-09-25T23:59+10:00，默认真实时钟")
    common.add_argument("--json", action="store_true", help="stdout 只输出一个 JSON 对象")
    desc = __doc__.replace("<NAME>", brand.NAME).replace("<HOME_ENV>", brand.env_name("HOME"))
    ap = ArgParser(prog="coach.py", description=desc, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"{brand.NAME} {brand.VERSION}", help="打印版本")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor", parents=[common])
    p.add_argument("--host", help="学校 Canvas 网址（登录页网址也行）")
    p.add_argument("--school", help="校名或域名（中英文都行），用来猜 Canvas 地址")
    p.add_argument("--tz", help="课程时区（IANA，如 Australia/Sydney）；不给就从 Canvas 推")
    p.add_argument("--detect-site", dest="detect_site", action="store_true", help="在浏览器记录里认 Canvas 域名（只取域名和访问次数）")
    p.add_argument("--no-detect", dest="no_detect", action="store_true", help="不读浏览器记录")
    p.add_argument("--dry-run", dest="dry_run", action="store_true", help="只列出会读哪些浏览器文件")
    p.add_argument("--env-dialog", dest="env_dialog", action="store_true", help="缺 token 时弹出让用户粘 token 的窗口")
    p.add_argument("--fix-perms", dest="fix_perms", action="store_true", help="宿主是 Claude Code 时把权限规则写进全局 settings.json")
    p.add_argument("--agent", default="auto", choices=["auto", "claude", "codex", "other"])
    p.add_argument("--all-courses", dest="all_courses", action="store_true")
    p.add_argument("--install", action="store_true", help="skill 不在 skills 目录时复制进去（换对话也能用）")
    p.set_defaults(fn=cmd_doctor)

    sub.add_parser("status", parents=[common]).set_defaults(fn=cmd_status)
    p = sub.add_parser("paths", parents=[common], help="资料夹和每门课的 课件 / 产出 目录"); p.add_argument("code", nargs="?"); p.set_defaults(fn=cmd_paths)

    p = sub.add_parser("collect", parents=[common])
    p.add_argument("--quick", action="store_true", help="只拉作业和公告")
    p.add_argument("--touch", action="store_true", help="更新 state.last_check")
    p.add_argument("--download", action="store_true", help="采集后下排队的课件（本周的先，一次最多 10 个）")
    p.add_argument("--background", action="store_true", help="和 --download 一起用：另起进程下，立刻返回")
    p.add_argument("--download-worker", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--download-token", help=argparse.SUPPRESS)
    p.add_argument("--materials", nargs=2, metavar=("CODE", "WEEK"), help="只下载某课某周的课件")
    p.add_argument("--force", action="store_true", help="10 分钟内采过也重拉")
    p.set_defaults(fn=cmd_collect)

    p = sub.add_parser("radar", parents=[common])
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--fetch", action="store_true")
    p.add_argument("--write", action="store_true")
    p.set_defaults(fn=cmd_radar)

    p = sub.add_parser("study", parents=[common])
    p.add_argument("--week", type=int, default=None, help="强制周次")
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--write", action="store_true", help="写 plans/<周>.json 并渲染")
    p.add_argument("--zh", default=None, help="中文润色覆盖层 JSON 文件，或 - 表示 stdin")
    p.add_argument("--out", default=None)
    p.add_argument("--force", action="store_true", help="覆盖手写的同名计划")
    p.set_defaults(fn=cmd_study)

    p = sub.add_parser("record", parents=[common])
    rs = p.add_subparsers(dest="op", required=True)
    q = rs.add_parser("done", parents=[common]); q.add_argument("target", nargs="?", default="today")
    q = rs.add_parser("mood", parents=[common]); q.add_argument("word"); q.add_argument("--note")
    q = rs.add_parser("product", parents=[common]); q.add_argument("--file", required=True); q.add_argument("--status", required=True); q.add_argument("--course"); q.add_argument("--log")
    q = rs.add_parser("pending", parents=[common]); q.add_argument("text"); q.add_argument("--course", required=True); q.add_argument("--blocks"); q.add_argument("--ask-en", dest="ask_en"); q.add_argument("--ask-zh", dest="ask_zh")
    q = rs.add_parser("asked", parents=[common]); q.add_argument("id")
    q = rs.add_parser("resolve", parents=[common]); q.add_argument("id"); q.add_argument("--resolution", required=True)
    q = rs.add_parser("decision", parents=[common]); q.add_argument("text"); q.add_argument("--course")
    q = rs.add_parser("note", parents=[common], help="作业说明：Canvas 日期只是占位等"); q.add_argument("assignment_id"); q.add_argument("text")
    q = rs.add_parser("deadline", parents=[common], help="手动 deadline（公告 / 大纲 / 老师说的）")
    q.add_argument("item", nargs="?"); q.add_argument("--course"); q.add_argument("--due", help="课程时区的日期：2026-09-20 或 09-20")
    q.add_argument("--time", help="HH:MM，也认 4pm / 11:59pm"); q.add_argument("--time-text", dest="time_text", help="写不出具体时刻时的文字，如「课上」")
    q.add_argument("--list", action="store_true", help="列出记过的手动 deadline（带序号）")
    q.add_argument("--remove", help="删掉一条：序号或事项名")
    q.add_argument("--weight"); q.add_argument("--url"); q.add_argument("--note"); q.add_argument("--source"); q.add_argument("--status")
    q.add_argument("--pending", action="store_true", help="还没确认：进区块二"); q.add_argument("--assignment-id", dest="assignment_id", help="替换 Canvas 上的这条作业")
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("week", parents=[common])
    p.add_argument("src")
    p.add_argument("--out", default=None)
    p.add_argument("--md", action="store_true")
    p.add_argument("--record", action="store_true")
    p.set_defaults(fn=cmd_week)

    p = sub.add_parser("guide", parents=[common]); p.add_argument("src"); p.add_argument("--out"); p.add_argument("--record", action="store_true"); p.set_defaults(fn=cmd_guide)
    p = sub.add_parser("lecture", parents=[common]); p.add_argument("src"); p.add_argument("--out"); p.add_argument("--record", action="store_true"); p.set_defaults(fn=cmd_lecture)
    p = sub.add_parser("unit", parents=[common])
    p.add_argument("mode", choices=["unit", "plan", "vocab", "mock", "all"]); p.add_argument("src"); p.add_argument("dst", nargs="?")
    p.add_argument("--n", type=int, default=25); p.add_argument("--record", action="store_true"); p.set_defaults(fn=cmd_unit)

    p = sub.add_parser("config", parents=[common])
    cs = p.add_subparsers(dest="op", required=True)
    cs.add_parser("show", parents=[common])
    q = cs.add_parser("get", parents=[common]); q.add_argument("key")
    q = cs.add_parser("set", parents=[common]); q.add_argument("key"); q.add_argument("value")
    q = cs.add_parser("course", parents=[common]); q.add_argument("code")
    q.add_argument("--materials-ai", dest="materials_ai", choices=["on", "off"], help="这门课的课件要不要提取文字给 AI 读（默认 off）")
    p.set_defaults(fn=cmd_config)

    p = sub.add_parser("migrate", parents=[common]); p.add_argument("--dry-run", dest="dry_run", action="store_true"); p.set_defaults(fn=cmd_migrate)
    p = sub.add_parser("share", parents=[common]); p.add_argument("--out"); p.add_argument("--zip", action="store_true"); p.set_defaults(fn=cmd_share)

    p = sub.add_parser("api", parents=[common])
    p.add_argument("op", choices=["get", "download", "post", "upload"])
    p.add_argument("a", help="get: 路径 · download: 文件 id · post: 路径 · upload: 课程 id")
    p.add_argument("b", nargs="?", help="get: 输出文件 · download: 目录 · upload: 作业 id")
    p.add_argument("--body", help="post 的 JSON 文件，或 - 表示 stdin")
    p.add_argument("--file", help="upload 的本地文件")
    p.add_argument("--comment", help="upload 时附的提交留言")
    p.add_argument("--confirmed", action="store_true", help="post / upload：用户看过预览并说了「发」；会弹系统确认窗口，本人点确定才发")
    p.set_defaults(fn=cmd_api)

    p = sub.add_parser("render", parents=[common]); p.add_argument("--zh"); p.add_argument("--out"); p.add_argument("--no-record", dest="no_record", action="store_true"); p.set_defaults(fn=cmd_render)
    p = sub.add_parser("run", parents=[common]); p.add_argument("--zh"); p.add_argument("--out"); p.add_argument("--quick", action="store_true"); p.set_defaults(fn=cmd_run, no_record=False)
    return ap


GLOBAL_FLAGS = ("--home", "--date")


def _reorder_globals(argv):
    """允许把 --home/--date/--json 写在子命令前面：挪到末尾再交给 argparse。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    head, i = [], 0
    while i < len(argv) and argv[i].startswith("-"):
        a = argv[i]
        if a == "--json" or a.split("=", 1)[0] in GLOBAL_FLAGS and "=" in a:
            head.append(a); i += 1
        elif a in GLOBAL_FLAGS and i + 1 < len(argv):
            head += argv[i:i + 2]; i += 2
        else:
            break
    return argv[i:] + head


def check_date(args):
    """--date 进命令之前先查，再把「现在」钉在它上面：写错了只报一句。"""
    import cc_time
    if not getattr(args, "date", None):
        return
    if not cc_time.moment_ok(args.date):
        raise CoachError(f"日期要写成 YYYY-MM-DD，或写到时分的时刻 2026-09-25T23:59+10:00：{args.date}", 2)
    cc_time.pin_now(args.date)


def describe_error(e):
    """没接住的异常 → 一句中文，不带 traceback。"""
    if isinstance(e, FileNotFoundError):
        return f"找不到文件：{e.filename or e}"
    if isinstance(e, json.JSONDecodeError):
        return f"JSON 格式不对：{e.msg}（第 {e.lineno} 行第 {e.colno} 列）"
    detail = " ".join(str(e).split())
    detail = detail if len(detail) <= 300 else detail[:300] + "…"
    return (f"出错了（{type(e).__name__}）" + (f"：{detail}" if detail else "")
            + f"。设环境变量 {brand.env_name('DEBUG')}=1 再跑一次可看完整报错")


def main(argv=None):
    canvas_api.utf8_stdout()
    argv = _reorder_globals(argv)
    ArgParser.json_errors = "--json" in argv  # 子命令的解析器也用这个类，出错时照样守 --json 约定
    args = build_parser().parse_args(argv)
    try:
        check_date(args)
        code, res = args.fn(args)
        if args.json and args.cmd != "api":
            out_json(res)
        return code
    except CoachError as e:
        out_json({"error": str(e), "exit": e.code}) if args.json else print(str(e), file=sys.stderr)
        return e.code
    except canvas_api.CanvasError as e:
        out_json({"error": str(e), "exit": 2}) if args.json else print(str(e), file=sys.stderr)
        return 2
    except urllib.error.HTTPError as e:
        msg = f"Canvas 返回 HTTP {e.code}：{e.url.split('?')[0] if e.url else ''}" + ("（token 失效？重新生成后粘进窗口）" if e.code == 401 else "")
        out_json({"error": msg, "exit": 2}) if args.json else print(msg, file=sys.stderr)
        return 2
    except urllib.error.URLError as e:
        msg = f"Canvas 连不上：{e.reason}。离线也能用：status / radar / study。"
        out_json({"error": msg, "exit": 2}) if args.json else print(msg, file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001  其余任何异常：一句中文，退出码 2
        if brand.env("DEBUG"):
            import traceback
            traceback.print_exc()
        msg = describe_error(e)
        out_json({"error": msg, "exit": 2}) if args.json else print(msg, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
