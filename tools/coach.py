"""<NAME> 命令行入口。数据在 <HOME_ENV>（默认桌面 <NAME>/.coach），程序在本目录。

  doctor  [--detect-site] [--host URL] [--school NAME] [--tz ZONE] [--fix-perms] [--agent auto|claude|codex|other] [--dry-run]
          体检：装库、认学校（浏览器记录）、验 token、建档、按宿主写权限。缺什么就说什么，能修的自己修。
  token   set | forget                     用户发到对话里的 token：set 从标准输入读进来存好（有学校地址就先验一次）；forget 删掉
  login   [--host URL] [--wait 90] | --check | --forget
          学校不让生成 token 或用 Moodle 时用：弹出浏览器窗口，用户自己登录 Canvas / Moodle，之后读数据用这份登录（只读）；--check 看还有没有效；--forget 删掉
  status                                     一屏现状 + 状态评估；只记今天开场问了哪几句（没回就不再问），别的不写
  collect [--quick] [--touch] [--download] | --materials CODE WEEK
          只读采集（默认只元数据，不下载课件）
  radar   [--days 14] [--fetch] [--write]    deadline 雷达（每门课下一条 / 最急 / 撞车 / 已确认 / 待确认 / 已过期未交 / 新变化 / 状态）
  study   [--week N] [--write] [--zh FILE|-] [--out HTML] [--force]
          本周该学什么：脚本按模块和 deadline 排三桶和每天必做；--zh 传中文润色；--write 落盘并渲染
  record  done [目标] | mood 词 [--note] | product --file --status [--course --log] | pending 文本 --course [--blocks 日期 --ask-en --ask-zh]
          | asked ID | resolve ID --resolution 文本 | decision 文本 [--course] | note 作业id 文本
          | deadline 事项 [--course 课，课外的事不写] --due 日期 [--time 时刻 --weight --url --pending] | deadline --list | deadline --remove 序号或事项
  week <plans/X.json> [--out HTML] [--md] [--record]   渲染一份现成的周计划 JSON
  guide <导读.json> [--out] [--record] · unit {unit|plan|vocab|mock|all} <src> [dst] · lecture <精讲.json> [--out]   工具箱渲染器
  jj list | remove                           /jj 入口：列出装了哪些、各读哪份说明；remove 删掉（卸载时用）
  update [--check]                           /jj-update：GitHub 上有新版就换上（几份一起换），新的 /jj 入口装上、下架的删掉
  external CODE [--rescan] · browse 网址 [--course CODE] [--wait 20]
          外部平台：external 列这门课的外部链接（模块、公告、作业说明，加上导航栏、课程页面）读过没有；browse 用本工具自己那份浏览器只读打开一个网页
  learn prep CODE [--week N] | check CODE
          学习页：prep 列这周和前两周的课件（页数），没开读课件的直接打开；check 检查这周的学习页清单
  outline CODE [--url 网址 | --syllabus | --file 表.json | --remove]
          课程说明里的每周安排表（只给模块没按周分的课用）：读一遍认出每周题目存进档案，周报按周次写「这周讲什么」
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
from cc_courses import lms_label  # noqa: E402
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


def cmd_token(args):
    """用户在对话里发来 token → 从标准输入读进来，存进本机文件。token 不打印、不进命令参数、不进 JSON。
    知道学校地址（config / site.json / CANVAS_HOST）就先只对这一个地址验一次：401 不存，免得把复制不全的存下来。"""
    import cc_token
    from cc_store import jload
    if args.op == "forget":
        gone = cc_token.forget_token()
        msg = "本机存的 token 删掉了。" if gone else "本机没有存 token。"
        if not args.json:
            print(msg)
        return 0, {"forgotten": gone, "message": msg}
    tok = cc_token.pick_token(cc_token.read_stdin())
    if not tok:
        raise CoachError(f"没收到能用的 token：{cc_token.HOW_TO_PASS}；用户那段话里有好几串像 token 的，就只传他要用的那一串", 2)
    home = home_dir(args.home)
    cfg = jload(os.path.join(home, "config.json")) or {}
    site = jload(os.path.join(home, "site.json"), {}) or {}
    host = cfg.get("canvas_host") or os.environ.get("CANVAS_HOST") or site.get("host")
    who = None
    if host:
        try:
            who = (canvas_api.Canvas(host, tok, timeout=20, retries=0).get("/api/v1/users/self") or {}).get("name") or "你的账号"
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise CoachError(f"这个 token 在 {host} 上登不上，没有存：多半没复制全。让用户在 Canvas 重新生成一个，整段发过来", 2)
        except (urllib.error.URLError, OSError, canvas_api.CanvasError):
            pass  # 连不上就先存下，doctor 再验
    cc_token.save_token(tok)
    msg = f"token 存好了（{cc_token.TOKEN_FILE_SHOWN}，只有这台电脑的本人账户能读）" + (f"，在 {host} 上验过：{who}" if who else "") + "。下一步：doctor"
    if not args.json:
        print(msg)
    return 0, {"saved": True, "verified": bool(who), "host": host, "message": msg}


def cmd_login(args):
    """学校不让生成 token（或学校用 Moodle）时：弹出浏览器窗口，用户自己登录；之后读数据都用这份登录。"""
    import importlib
    import cc_host
    import cc_session
    import deps
    from cc_courses import lms_of
    from cc_store import jload
    home = home_dir(args.home)
    if args.worker:
        if args.site:
            return cc_session.signin_worker(home, args.site), {}
        if args.lms == "moodle":  # Moodle 的站点根可能带子目录，不能只留域名
            return cc_session.worker(home, (args.host or "").rstrip("/"), lms="moodle"), {}
        return cc_session.worker(home, cc_host.normalize_host(args.host)), {}
    if args.forget:
        info = cc_session.read_login(home)
        moodle = (cc_session.login_lms(info) if info else lms_of(jload(os.path.join(home, "config.json")))) == "moodle"
        gone = cc_session.forget(home)
        back = "Moodle 没有 token 方式，要再读数据就重新跑 login。" if moodle else "回到 token 方式。"
        msg = f"登录删掉了，{back}" if gone else "本来就没有登录。"
        if not args.json:
            print(msg)
        return 0, {"forgotten": gone, "message": msg}
    cfg = jload(os.path.join(home, "config.json")) or {}
    site = jload(os.path.join(home, "site.json"), {}) or {}
    host = (cc_host.normalize_host(args.host) or cfg.get("canvas_host") or cc_host.normalize_host(os.environ.get("CANVAS_HOST"))
            or site.get("host") or (cc_session.read_login(home) or {}).get("host"))
    if args.check:
        r = cc_session.check(home, host)
    else:
        if not host:
            raise CoachError("还不知道学校的 Canvas 地址：先问用户确认（doctor 会从浏览器记录里猜），再跑 login --host 网址", 2)
        lms, host = _login_target(home, cfg, args.host, host)
        if deps.optional("playwright") is None:
            from cc_install import pip_install
            if not args.json:
                print("第一次用登录模式，先装 playwright（只装一次）…")
            if not pip_install("playwright"):
                raise CoachError(f"playwright 没装上：{cc_session.NEED_PLAYWRIGHT}", 2)
            importlib.invalidate_caches()
        r = cc_session.start_login(home, host, wait=max(0, args.wait), lms=lms)
        if lms == "moodle":
            r["lms"] = "moodle"
        if r["state"] == "done":
            r["message"] += "。下一步：doctor" if not cfg or lms_of(cfg) != lms else "。下一步：collect"
    if not args.json:
        print(r["message"])
    return {"done": 0, "ok": 0, "waiting": 1}.get(r["state"], 2 if r["state"] in ("failed", "no_window") else 1), r


def _login_target(home, cfg, raw, host):
    """开登录窗口前先认平台（不带任何凭据）：Moodle 用站点自己报的根（可能带子目录）。
    认不出（连不上）就沿用档案或上次登录记的；都没有就按 Canvas。"""
    import cc_host
    import cc_session
    from cc_courses import lms_of
    kind, base = cc_host.detect_lms(raw or host)
    if kind:
        return kind, base
    known = cc_session.read_login(home) or {}
    for h, lms in ((cfg.get("canvas_host"), lms_of(cfg)), (known.get("host"), cc_session.login_lms(known))):
        if lms == "moodle" and h and cc_host.normalize_host(h) == cc_host.normalize_host(host):
            return "moodle", h.rstrip("/")
    return "canvas", host


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
        _auto_scan(ctx, args, res)
        return 0, res
    d = cc_collect.collect(ctx, date, quick=args.quick, touch=args.touch, download=(True if args.download else None))
    if not args.json:
        cc_digest.print_digest(d, lms_label(ctx.cfg))
        cc_digest.print_context(ctx, date)
    promoted = bool(d.get("promoted", not d.get("errors")))
    res = {"digest_path": ctx.P("raw", "daily", date, "digest.json") if promoted else None,
           "failure_path": d.get("failure_path"), "complete": bool(d.get("complete", promoted)),
           "promoted": promoted, "errors": d["errors"], "quick": args.quick,
           "counts": {k: len(d.get(k) or []) for k in ("new_announcements", "staff_messages", "changed_assignments", "submission_changes",
                                                       "new_items", "unlocked_items", "locked_items", "downloaded", "skipped_downloads")},
           "readiness": d.get("readiness"), "queued_downloads": d.get("queued_downloads", 0)}
    res["downloads"] = _downloads(ctx, args)
    _auto_scan(ctx, args, res)
    return (1 if d["errors"] else 0), res


def _auto_scan(ctx, args, res):
    """采集完顺手在后台去 Canvas 查外部平台（导航栏、课程页面、学生的分班；每门课 7 天一次），不等它（10-07：开场不该为它等）。"""
    import cc_external
    try:
        info = cc_external.spawn_scans(ctx, ctx.clock.now_utc())
    except Exception:  # noqa: BLE001  起不了就算了：「还差」里那条 external 照样会补
        return
    if info:
        res["external_scan"] = info
        if not args.json:
            print(f"外部平台：在后台去 {lms_label(ctx.cfg)} 查 {len(info['due'])} 门课的导航栏和课程页面，不用等")


def _auto_background(ctx, args):
    """采集完、队列里有课件、设置没关自动下载：顺手在后台开始下，不等它。
    以前全靠 AI 看到 status 那句「课件待下载」再去跑 --download --background；会话没读到这份档案时，就一直没人下。"""
    import cc_downloads
    if (ctx.cfg.get("materials") or {}).get("auto_download") is False:
        return None
    import datetime as _dt
    from cc_time import parse_ts as _pts
    last_err = _pts(cc_downloads.load_downloads(ctx).get("last_error_at"))
    if last_err and ctx.clock.now_utc() - last_err < _dt.timedelta(hours=cc_downloads.RETRY_AFTER_H):
        return None  # 上一批刚出过错：隔一段时间再自动试，免得每次刷新都白跑一遍
    try:
        info = cc_downloads.spawn_downloads(ctx)
    except Exception:  # noqa: BLE001  宿主不让开子进程（沙盒、测试）就算了，status 那句提示还在
        return None
    if info.get("disk_low") is not None:
        if not args.json:
            print(f"课件后台下载：硬盘只剩 {info['disk_low']} GB（不到 {cc_downloads.MIN_FREE_GB} GB），这次先不下")
        return info
    if not info.get("started"):
        return None
    if not args.json:
        print(f"课件后台下载：已自动开始，队列 {info['queued']} 个")
    return info


def _downloads(ctx, args):
    """collect 之后：--download 下队列（--background 另起进程，立刻返回）；没写 --download 也会在后台自动开始。"""
    import cc_downloads
    if not getattr(args, "download", False):
        return _auto_background(ctx, args)
    if getattr(args, "background", False):
        info = cc_downloads.spawn_downloads(ctx)
        if not args.json:
            if info.get("disk_low") is not None:
                msg = f"硬盘只剩 {info['disk_low']} GB（不到 {cc_downloads.MIN_FREE_GB} GB），这次先不下，队列 {info['queued']} 个留着"
            elif info.get("started"):
                msg = f"已启动，队列 {info['queued']} 个，日志 {info['log']}"
            elif info.get("running"):
                msg = f"已经在运行，队列 {info['queued']} 个，日志 {info['log']}"
            else:
                msg = "队列是空的"
            print(f"课件后台下载：{msg}")
        return info
    r = cc_downloads.run_downloads(ctx, cap=10)
    if not args.json:
        if r.get("disk_low") is not None:
            print(f"课件下载：硬盘只剩 {r['disk_low']} GB（不到 {cc_downloads.MIN_FREE_GB} GB），这次先不下，队列 {r['left']} 个留着")
        elif r.get("running"):
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
    opened = False
    if args.open and written:
        from cc_paths import open_page
        opened = open_page(next((w for w in written if w.endswith(".html")), None))
    if not args.json:
        print(md)
        for w in written:
            print("WRITTEN=" + w)
        if args.open:
            print("OPENED=" + ("yes" if opened else "no"))
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
    import cc_gaps
    res = {"plan": plan, "written": None, "todo_for_ai": cc_gaps.for_ai(ctx, plan, today)}
    if args.write:
        path = cc_study.write_plan(ctx, plan, force=args.force)
        r = render_week.write(path, args.out, week_no=plan.get("week_no"), generated=today.isoformat())
        r["copy"] = render_week.publish(ctx, r["html"]) if not args.out else None
        ctx.state["current_plan"] = ctx.rel(path)
        ctx.save_state()
        cc_record.record_product(ctx, ctx.rel(r["html"]), "📦 本周学习清单", course="全部课程",
                                 log=f"本周学习清单 `{ctx.rel(path)}`：{plan['study']['items_total']} 项，最要紧：{(plan['study'].get('top_one') or {}).get('title', '无')}")
        res.update({"written": r["html"], "json": path, "md": r.get("md"), "copy": r.get("copy")})
        if args.open:  # 交给用户时：直接打开，资料夹在桌面上就再放个快捷方式；定时任务不加 --open，早上不会自己弹网页
            import render_help
            from cc_paths import desktop_shortcut, open_page
            page = res.get("copy") or res["written"]
            res["help"] = render_help.ensure(ctx)
            res["opened"] = open_page(page)
            res["shortcut"] = desktop_shortcut(ctx.root, page)
    if not args.json:
        print(cc_study.to_text(plan))
        if res["todo_for_ai"]:
            print(cc_gaps.text_block(res["todo_for_ai"]))
        if res.get("written"):
            print("JSON=" + res["json"])
            print("WRITTEN=" + res["written"])
            if res.get("md"):
                print("MD=" + res["md"])
            if res.get("copy"):
                print("COPY=" + res["copy"])
            if args.open:
                print("OPENED=" + ("yes" if res.get("opened") else "no"))
                if res.get("shortcut"):
                    print("SHORTCUT=" + res["shortcut"])
    return 0, res


def cmd_update(args):
    """/jj-update：GitHub 上有新版就下下来换上（Claude Code、Codex 装着的几份一起换），旧版备份在 skills 外面；
    新版带来的 /jj 入口装上、下架的删掉。只跟学生说这次更新的新内容。"""
    import cc_update
    from cc_paths import skill_dir
    if args.finish:  # 换上新版以后，由新版自己的代码来装入口
        return 0, cc_update.finish(args.finish)
    r = cc_update.update(running=skill_dir(), check_only=args.check)
    if not args.json:
        print(r["message"])
        if r["state"] == "updated":
            if r.get("notes"):
                print("这次更新的新内容：")
                print(r["notes"])
            got = r.get("entries") or {}
            if got.get("installed"):
                print("新口令：" + "、".join("/" + n for n in got["installed"]))
            if got.get("removed"):
                print("下架的口令：" + "、".join("/" + n for n in got["removed"]))
            if r.get("failed"):
                print("这几份没换上，用的还是旧版：" + "；".join(r["failed"]))
            print("旧版备份在：" + cc_update.backup_dir(os.path.expanduser("~")) + "（给 AI 的：跟学生只说新内容和新口令，不用提备份）")
        elif r["state"] == "available" and r.get("notes"):
            print("新版的内容：")
            print(r["notes"])
    return {"latest": 0, "updated": 0, "available": 1}.get(r["state"], 2), r


def cmd_jj(args):
    """/jj 入口：主技能挑功能时用 list 看装了哪些、各读哪份 references（挑中后直接读那份说明，不去调用入口）。"""
    import cc_install
    if args.op == "remove":
        removed = cc_install.remove_entries()
        if not args.json:
            print(f"删掉了 {len(removed)} 个入口" + ("：" + "、".join(os.path.basename(d) for d in removed) if removed else ""))
        return 0, {"removed": removed}
    rows = cc_install.installed_entries()
    if not args.json:
        if not rows:
            print("没有 /jj 入口")
        for r in rows:
            refs = "、".join("references/" + x for x in r["refs"]) or "（没写）"
            state = f"已装（版本 {r['version'] or '?'}）" if r["installed"] else "没装（doctor --install 会装）"
            print(f"{r['name']}：{state} ｜ 读 {refs}")
    return 0, {"entries": rows}


def _course_of(ctx, code):
    want = (code or "").upper()
    return next((c for c in ctx.cfg.get("courses") or [] if c["code"].upper() == want), None)


def cmd_external(args):
    """一门课的外部平台保底清单，每条读过没有、上次结果。Canvas 的课先去查导航栏、课程页面和学生的分班（7 天一次，--rescan 马上再查），
    再合上已采集的模块、公告和作业说明。"""
    import cc_external
    import cc_study
    from cc_courses import lms_of
    from cc_time import parse_ts
    ctx = Ctx(args.home, quiet=args.json)
    now = ctx.clock.now_utc()
    if getattr(args, "scan_worker", False):  # collect 在后台起的那一路：把该查的课都查一遍
        res = cc_external.run_scans(ctx, now, cc_study.current_week(ctx, today_of(ctx, args), cc_study.load_modules(ctx))[0])
        if not args.json:
            print(f"{now.isoformat()} 外部平台：" + ("；".join(f"{k} {v}" for k, v in res.items()) or "没有要查的（或者另一个在查）"))
        return 0, {"scans": res, "worker": True}
    course = _course_of(ctx, args.code)
    if not course:
        raise CoachError(f"没有这门课：{args.code}（课程代码照 config 里的写）", 2)
    code = course["code"]
    mods = cc_study.load_modules(ctx)
    week = cc_study.current_week(ctx, today_of(ctx, args), mods)[0]
    scan = None
    busy = cc_external.scan_running(ctx)
    if busy and not args.json:
        print("后台正在去 Canvas 查外部平台：这次先列已有的，过一两分钟再跑一次能看到查完的")
    if not busy and lms_of(ctx.cfg) != "moodle" and (args.rescan or cc_external.scan_stale(ctx.home, code, now)):
        try:
            scan = cc_external.scan_canvas(ctx.api, ctx.cfg.get("canvas_host"), course.get("id"), mods.get(code), week, now)
            cc_external.save_found(ctx.home, code, scan)
        except Exception as e:  # noqa: BLE001  连不上 Canvas（没 token、登录过期）：照旧列已采集的
            scan = {"failed": f"{type(e).__name__}: {str(e).splitlines()[0][:160] if str(e) else ''}"}
    links, notes = cc_external.course_links(ctx, course, week, now, mods=mods)
    found = cc_external.load_found(ctx.home, code)
    recs = cc_external.load_records(ctx.home, code)
    for x in links:
        x["record"] = cc_external.record_of(recs, x["url"])
    if not args.json:
        if scan and scan.get("failed"):
            print(f"这次没能去 Canvas 查导航栏和课程页面（{scan['failed']}），下面只有已采集的")
        elif scan:
            pages = scan.get("pages") or []
            print(f"刚去 Canvas 查了导航栏、{len(pages)} 个课程页面" + (f"（{'、'.join(pages[:6])}{'……' if len(pages) > 6 else ''}）" if pages else ""))
            for e in scan.get("errors") or []:
                print(f"有一处没查到：{e}")
        elif found.get("scanned_at"):
            print(f"导航栏和课程页面 {ctx.clock.fmt(parse_ts(found['scanned_at']))} 查过（7 天内不再查，--rescan 马上再查）")
        if found.get("sections"):
            print(f"学生在 Canvas 上的分班：{'；'.join(found['sections'])}")
        for n in notes:
            print(f"说明：{n}")
        if not links:
            print(f"{code}：没找到外部平台的链接（「提到了但没给链接」的要 AI 读公告和课程页面认）")
        for x in links:
            r = x["record"] or {}
            read_at = parse_ts(r.get("read_at"))
            state = {"ok": f"读过（{ctx.clock.fmt(read_at) if read_at else ''}）", "login": "上次被带去登录页", "bot": "上次碰到人机验证",
                     "error": "上次没打开"}.get(r.get("result"), "还没读过")
            print(f" - {x['platform']}（{x['kind']}）「{x['title'] or '无标题'}」· {state} · 来自{x['source']}\n   {x['url']}")
    return 0, {"course": code, "week": week, "links": links, "notes": notes, "sections": found.get("sections") or [], "scan": scan}


def cmd_browse(args):
    """用本工具自己那份登录浏览器在后台只读打开一个网页，把文字存下来给 AI 读；结果记进这门课的外部平台记录。"""
    import cc_external
    import cc_study
    from cc_courses import lms_of
    from cc_session import LoginUnavailable
    ctx = Ctx(args.home, quiet=args.json)
    now = ctx.clock.now_utc()
    course = _course_of(ctx, args.course) if args.course else None
    known = None
    if course:  # 清单上有的用清单上的平台名（Canvas 里的 Zoom 跳转链接按网址认不出来）
        mods = cc_study.load_modules(ctx)
        week = cc_study.current_week(ctx, today_of(ctx, args), mods)[0]
        k = cc_external.norm(args.url)
        known = next((x for x in cc_external.course_links(ctx, course, week, now, mods=mods)[0] if cc_external.norm(x["url"]) == k), None)
    hit = (known["platform"], known["kind"]) if known else (cc_external.classify(args.url) or ("其他网站", "内容"))
    signed = None
    if args.sign_in:  # 学生同意了：开窗口让学生自己登一次，登好接着读；存下的学校登录以后对别的网站也管用
        import cc_session
        signed = cc_session.start_signin(ctx.home, args.url, wait=90)
        if signed["state"] not in ("done", "closed"):  # 关了窗口的可能已经登好：照样读一次看看
            if not args.json:
                print(signed["message"])
            return (1 if signed["state"] in ("waiting", "timeout") else 2), {"result": signed["state"], "note": signed["message"]}
    open_url, launch_note = None, None
    host = ctx.cfg.get("canvas_host")
    if lms_of(ctx.cfg) != "moodle" and cc_external.session_open_path(args.url, host):
        # 本校 Canvas 上的网址（嵌的工具、课程页面）：先换免登录的打开链接，token 和浏览器登录读到的一样
        try:
            open_url, launch_note = cc_external.open_link(ctx.api, args.url, host, lti=bool((known or {}).get("lti")))
        except Exception as e:  # noqa: BLE001  连接口都建不起来（没有 token 之类）：照原网址开
            launch_note = f"拿免登录打开链接没成（{type(e).__name__}）"
        finally:
            import cc_session
            cc_session.close_all()  # 浏览器登录模式下拿链接用的是同一份浏览器资料夹：先放开，下面才开得了
    try:
        r = cc_external.browse(ctx.home, args.url, wait=args.wait, open_url=open_url)
        if launch_note and r.get("result") != "ok":
            r["note"] = "；".join(x for x in (r.get("note"), launch_note) if x)
    except LoginUnavailable as e:
        r = {"result": "error", "note": str(e)}
    except Exception as e:  # noqa: BLE001  网址打不开、超时：记成没读到，下次再试（报错原话可能带着打开链接，先去掉凭证）
        first = cc_external.scrub(str(e), open_url).splitlines()[0][:160] if str(e) else ""
        r = {"result": "error", "note": f"{type(e).__name__}: {first}"}
    if course:
        cc_external.record(ctx.home, course["code"], args.url, r["result"], now, platform=hit[0], kind=hit[1],
                           title=r.get("title"), note=r.get("note"))
    if not args.json:
        if r["result"] == "ok":
            print(f"读到了：{r.get('title') or args.url}（{r['chars']} 字，链接 {len(r.get('links') or [])} 个）→ 文字存在 {r['path']}")
        elif r["result"] == "login" and signed:
            print("在窗口里登过了，还是被带去登录页：这个网站多半要别的账号。这次记成没读到；跟学生只说情况（learn.md「汇报」那段）")
        elif r["result"] == "login":
            from urllib.parse import urlparse
            print(f"被带去登录页（{urlparse(r.get('final_url') or '').netloc}）：这个网站要登录（多半是学校账号），{brand.NAME}的浏览器里还没有它的登录。"
                  "这次记成没读到。学生在对话里的话，先问一句：「这个网站要用学校账号登一次，我弹个窗口你登一下，以后就不用再登了，可以吗？」"
                  "同意就跑 browse 网址 --course 课 --sign-in；没人在对话里（定时任务）就不弹窗，跟学生只说情况（learn.md「汇报」那段）")
        elif r["result"] == "bot":
            print("这个网站要人机验证：停在这里，不绕过。这次记成没读到；跟学生只说情况")
        else:
            print(f"没打开：{r.get('note') or '原因不明'}。这次记成没读到，下次再试")
    return (0 if r["result"] == "ok" else 1), r


def cmd_learn(args):
    """学习页：prep 做之前看课件和读课件那一问；check 做完检查这周的清单文件。"""
    import cc_learn
    import cc_study
    from cc_config import materials_ai
    from cc_time import monday_of
    ctx = Ctx(args.home, quiet=args.json)
    code = (args.code or "").upper()
    course = next((c for c in ctx.cfg.get("courses") or [] if c["code"].upper() == code), None)
    if not course:
        raise CoachError(f"没有这门课：{args.code}（课程代码照 config 里的写）", 2)
    code, label = course["code"], cc_learn.display_code(course)
    today = today_of(ctx, args)
    monday = monday_of(today)
    week = f"{monday.isocalendar()[0]}-W{monday.isocalendar()[1]:02d}"
    if args.op == "check":
        info = cc_learn.load_week(ctx.home, week, None, [code])[code]
        if info["state"] == "ok":
            m = info["m"]
            msg = (f"{label} {week} 的学习页清单能用：{len(m['blocks'])} 块 {m['minutes_total']} 分钟，"
                   f"{len(m.get('sessions') or [])} 个上课时间，{len(m.get('todos') or [])} 件要学生做的")
        elif info["state"] is None:
            msg = f"{label} 还没有 {week} 的学习页清单：{cc_learn.manifest_path(ctx.home, week, code)}"
        else:
            msg = f"{label} {week} 的学习页清单有问题：{'；'.join(info['problems'])}"
        if not args.json:
            print(msg)
        return (0 if info["state"] == "ok" else 1), {"course": code, "week": week, "state": info["state"], "problems": info["problems"]}
    w = args.week or cc_study.current_week(ctx, today, cc_study.load_modules(ctx))[0]
    if not w:
        raise CoachError("认不出这是第几周：用 --week N 指定", 2)
    files = cc_learn.week_materials(ctx, code, w)
    raw_course = next((c for c in ctx.raw_cfg.get("courses") or [] if (c.get("code") or "").upper() == code.upper()), None) or {}
    declined = raw_course.get("materials_ai") is False  # 学生明说过这门课不读课件（config course 课 --materials-ai off）
    on, opened = materials_ai(ctx.cfg, code), False
    if not on and not declined:  # 学生要学习页，就是同意读这门课的课件：不再单独问（10-07 发起人：方便学生最重要）
        from cc_config import course_option
        course_option(ctx, code, "on")
        on, opened = True, True
    pages = sum(f["pages"] or 0 for f in files if f["local"] and not f["locked"])
    missing = [f for f in files if not f["local"] and not f["locked"]]
    tip = None
    if not (ctx.state.get("tips") or {}).get("learn_effort"):  # 第一次做学习页：提一次努力程度，只这一次
        tip = "第一次做学习页：跟学生提一句「想讲得更细，建议把努力程度调到 Extra high（xhigh）或更高，会慢一点、多用一些额度」，以后不再提"
        ctx.state.setdefault("tips", {})["learn_effort"] = today.isoformat()
        ctx.save_state()
    if not args.json:
        if tip:
            print(tip)
        print(f"{label} 第 {w} 周（连前两周）课件 {len(files)} 份：")
        for f in files:
            state = "锁着" if f["locked"] else ("还没下载" if not f["local"] else (f"{f['pages']} 页" if f["pages"] else "页数不明"))
            print(f"  第 {f['week']} 周 · {f['title']} · {state}")
        if missing:
            print(f"有 {len(missing)} 份还没下载：先跑 collect --materials {code} <周>")
        if declined:
            print("读课件：学生说过这门课不读课件。照样做，只用网页、公告和课程说明，学习页顶上写一句「这份没读课件」。")
        elif opened:
            print(f"读课件：学生要了这门课的学习页，已经替 {label} 打开读课件（不再单独问）。做完在结果里说一句读了几页课件。")
        else:
            print("读课件：已经打开，直接做。")
    return 0, {"course": code, "label": label, "week": w, "files": files, "materials_ai": on, "opened": opened, "declined": declined,
               "pages": pages, "missing": len(missing), "effort_tip": tip}


def cmd_outline(args):
    """课程说明里的每周安排：--url 公开页 / --syllabus Canvas 的 Syllabus / --file AI 整理的表 / 不带参数就看 / --remove 删。"""
    import cc_outline
    ctx = Ctx(args.home, quiet=args.json)
    code = (args.code or "").upper()
    course = next((c for c in ctx.cfg.get("courses") or [] if c["code"].upper() == code), None)
    if not course:
        raise CoachError(f"没有这门课：{args.code}（课程代码照 config 里的写）", 2)
    code = course["code"]
    if args.remove:
        try:
            os.remove(cc_outline.path(ctx.home, code))
            msg = f"{code}：每周安排表删了"
        except OSError:
            msg = f"{code}：本来就没有每周安排表"
        if not args.json:
            print(msg)
        return 0, {"course": code, "removed": True}
    if args.file:
        t = load_json_arg(args.file)
        bad = cc_outline.validate(t, code)
        if bad:
            raise CoachError(f"{code} 的表有问题：{'；'.join(bad)}", 2)
        p = cc_outline.save(ctx.home, code, t)
        import cc_gaps
        cc_gaps.clear_failed(ctx, f"outline:{code}")
        if not args.json:
            print(f"{code}：存好了 {len(t['weeks'])} 周 → {p}")
        return 0, {"course": code, "path": p, "weeks": t["weeks"]}
    if args.url or args.syllabus:
        import cc_gaps
        if args.url:
            try:
                html, title, url = cc_outline.fetch_public(args.url), f"{code} 课程说明", args.url
            except Exception as e:  # noqa: BLE001  打不开（网址错、网站挂了、要登录、断网）：记下，7 天内「还差」不再列
                cc_gaps.mark_failed(ctx, f"outline:{code}", today_of(ctx, args))
                msg = f"{code}：课程说明网页打不开（{type(e).__name__}）"
                if not args.json:
                    print(msg)
                return 1, {"course": code, "weeks": {}, "message": msg}
        else:
            from cc_courses import lms_of
            if lms_of(ctx.cfg) == "moodle":
                raise CoachError("Moodle 没有 Syllabus 页：用 --url 给课程说明的网址", 2)
            obj = ctx.api.get(f"/api/v1/courses/{course['id']}?include[]=syllabus_body")
            html, title = (obj or {}).get("syllabus_body") or "", f"{code} Syllabus"
            url = f"{ctx.cfg.get('canvas_host')}/courses/{course['id']}/assignments/syllabus"
        weeks = cc_outline.extract_weeks(cc_outline.text_lines(html))
        if not weeks:
            cc_gaps.mark_failed(ctx, f"outline:{code}", today_of(ctx, args))
            msg = f"{code}：页面里认不出每周安排（少于 {cc_outline.MIN_WEEKS} 周）。请照页面整理一张表，用 outline {code} --file 表.json 存"
            if not args.json:
                print(msg)
            return 1, {"course": code, "weeks": {}, "message": msg}
        old = cc_outline.load(ctx.home, code) or {}
        t = cc_outline.build(code, weeks, title, url, ctx.clock.now_utc())
        if old.get("weeks_zh"):
            t["weeks_zh"] = old["weeks_zh"]  # AI 之前补的中文留着
        p = cc_outline.save(ctx.home, code, t)
        if not args.json:
            print(f"{code}：认出 {len(weeks)} 周 → {p}\n" + "\n".join(f"  第 {k} 周：{v}" for k, v in weeks.items())
                  + "\n核对一遍：认错的地方照页面改好，用 --file 存回去；顺手补上 weeks_zh（每周一句中文）。")
        return 0, {"course": code, "path": p, "weeks": weeks}
    t = cc_outline.load(ctx.home, code)
    if not args.json:
        print(f"{code}：还没有每周安排表" if not t else "\n".join(
            f"第 {k} 周：{v}" + (f"（{t.get('weeks_zh', {}).get(k)}）" if (t.get("weeks_zh") or {}).get(k) else "") for k, v in t["weeks"].items()))
    return (0 if t else 1), {"course": code, "table": t}


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
    if op == "deadline" and not args.list and args.remove is None and not (args.item and args.due):
        raise CoachError('要写事项和 --due，例：record deadline "Essay" --course ACCT1101 --due 09-20 --time 23:59'
                         '（课外的事不写 --course，记成「课外」）', 2)
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
        r = cc_record.add_deadline(ctx, args.item, args.course or cc_record.EXTRA, args.due, time=args.time, time_text=args.time_text, weight=args.weight,
                                   url=args.url, note=args.note, source=args.source, status=args.status, pending=args.pending,
                                   assignment_id=args.assignment_id, force=args.force)
        if r["action"] == "same":
            msg = f"Canvas 上已经有这一项（「{r['canvas_item']}」，同一天），不用再记。"
        else:
            msg = (f"手动 deadline {'更新' if r['action'] == 'updated' else '+1'}：{r['course']} {r['item']} "
                   f"{cc_record.deadline_text(ctx.clock, r)}").rstrip() + ("（待确认）" if r["pending"] else "")
    elif op == "mood":
        r = cc_state.add_mood(ctx, args.word, note=args.note)
        today = today_of(ctx, args)
        ev = cc_state.evaluate(ctx, today, cc_deadlines.plan_today(ctx, today), cc_radar.rows(ctx, today))
        r = {"mood": r, "state_eval": ev}
        hint = "开不了头的话跟我说一句，我们把最急的那件拆成一小步。" if ev["label"] in ("落后", "卡住", "过载") else ""
        msg = "记下了。" + hint + cc_state.state_line(ev)
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
            cc_digest.print_digest(d, lms_label(ctx.cfg))
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
    p.add_argument("--host", help="学校 Canvas 网址（登录页网址也行）；Moodle 学校给 Moodle 网址")
    p.add_argument("--school", help="校名或域名（中英文都行），用来猜 Canvas 地址")
    p.add_argument("--tz", help="课程时区（IANA，如 Australia/Sydney）；不给就从 Canvas 推")
    p.add_argument("--detect-site", dest="detect_site", action="store_true", help="在浏览器记录里认 Canvas 域名（只取域名和访问次数）")
    p.add_argument("--no-detect", dest="no_detect", action="store_true", help="不读浏览器记录")
    p.add_argument("--dry-run", dest="dry_run", action="store_true", help="只列出会读哪些浏览器文件")
    p.add_argument("--env-dialog", dest="env_dialog", action="store_true", help=argparse.SUPPRESS)  # 旧参数：不再弹环境变量窗口，留着免得老说明报错
    p.add_argument("--fix-perms", dest="fix_perms", action="store_true", help="宿主是 Claude Code 时把权限规则写进全局 settings.json")
    p.add_argument("--agent", default="auto", choices=["auto", "claude", "codex", "other"])
    p.add_argument("--all-courses", dest="all_courses", action="store_true")
    p.add_argument("--install", action="store_true", help="skill 不在 skills 目录时复制进去（换对话也能用）")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("token", parents=[common], help="用户发到对话里的 token：set 从标准输入读进来存好；forget 删掉")
    p.add_argument("op", choices=["set", "forget"])
    p.set_defaults(fn=cmd_token)

    p = sub.add_parser("login", parents=[common], help="学校不让生成 token 或用 Moodle 时：弹出浏览器窗口让用户自己登录，之后用这份登录只读")
    p.add_argument("--host", help="学校 Canvas / Moodle 网址（不给就用 config / doctor 认出的）；先不带凭据认出是哪种")
    p.add_argument("--wait", type=int, default=90, help="最多等几秒就先返回（窗口留着继续等用户，最长 10 分钟）")
    p.add_argument("--check", action="store_true", help="不开窗口，只看登录还有没有效")
    p.add_argument("--forget", action="store_true", help="删掉这份登录，回到 token")
    p.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--lms", choices=["canvas", "moodle"], default="canvas", help=argparse.SUPPRESS)  # 窗口进程用：哪种平台
    p.add_argument("--site", help=argparse.SUPPRESS)  # 窗口进程用：给别的网站登学校账号（browse --sign-in 起的）
    p.set_defaults(fn=cmd_login)

    sub.add_parser("status", parents=[common]).set_defaults(fn=cmd_status)
    p = sub.add_parser("paths", parents=[common], help="资料夹和每门课的 课件 / 产出 目录"); p.add_argument("code", nargs="?"); p.set_defaults(fn=cmd_paths)
    p = sub.add_parser("external", parents=[common], help="一门课的外部平台保底清单：导航栏、课程页面、模块、公告里的外部链接，读过没有")
    p.add_argument("code", nargs="?"); p.add_argument("--rescan", action="store_true", help="马上再去 Canvas 查一遍导航栏和课程页面")
    p.add_argument("--scan-worker", dest="scan_worker", action="store_true", help=argparse.SUPPRESS)  # collect 在后台起的那一路
    p.set_defaults(fn=cmd_external)
    p = sub.add_parser("browse", parents=[common], help="用本工具自己那份登录浏览器在后台只读打开一个网页，文字存下来给 AI 读")
    p.add_argument("url"); p.add_argument("--course"); p.add_argument("--wait", type=int, default=20)
    p.add_argument("--sign-in", dest="sign_in", action="store_true", help="学生同意以后：弹出窗口让学生自己登一次（学校账号），登好接着读；以后不用再登")
    p.set_defaults(fn=cmd_browse)
    p = sub.add_parser("learn", parents=[common], help="学习页：prep 做之前看课件和读课件那一问；check 做完检查这周的清单文件")
    p.add_argument("op", choices=["prep", "check"]); p.add_argument("code"); p.add_argument("--week", type=int); p.set_defaults(fn=cmd_learn)
    p = sub.add_parser("outline", parents=[common], help="课程说明里的每周安排表：--url / --syllabus 读一遍，--file 存 AI 整理的表，--remove 删")
    p.add_argument("code"); p.add_argument("--url"); p.add_argument("--syllabus", action="store_true"); p.add_argument("--file")
    p.add_argument("--remove", action="store_true"); p.set_defaults(fn=cmd_outline)
    p = sub.add_parser("update", parents=[common], help="/jj-update：GitHub 上有新版就换上，新的 /jj 入口装上、下架的删掉")
    p.add_argument("--check", action="store_true", help="只看有没有新版，不换")
    p.add_argument("--finish", help=argparse.SUPPRESS)  # 换上新版以后由新版的代码装入口：给出这一份的路径
    p.set_defaults(fn=cmd_update)
    p = sub.add_parser("jj", parents=[common], help="/jj 菜单的入口：list 列出装了哪些、各自读哪份说明；remove 删掉（卸载时用）")
    js = p.add_subparsers(dest="op", required=True)
    js.add_parser("list", parents=[common])
    js.add_parser("remove", parents=[common])
    p.set_defaults(fn=cmd_jj)

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
    p.add_argument("--open", action="store_true", help="和 --write 一起用：写完用浏览器打开雷达（交给用户时用；定时任务别加）")
    p.set_defaults(fn=cmd_radar)

    p = sub.add_parser("study", parents=[common])
    p.add_argument("--week", type=int, default=None, help="强制周次")
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--write", action="store_true", help="写 plans/<周>.json 并渲染")
    p.add_argument("--zh", default=None, help="中文润色覆盖层 JSON 文件，或 - 表示 stdin")
    p.add_argument("--out", default=None)
    p.add_argument("--force", action="store_true", help="覆盖手写的同名计划")
    p.add_argument("--open", action="store_true",
                   help="和 --write 一起用：写完用浏览器打开本周清单，资料夹在桌面上时再放一个「本周清单」快捷方式（交给用户时用；定时任务别加）")
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
    q = rs.add_parser("deadline", parents=[common], help="手动 deadline（公告 / 大纲 / 老师说的；课外的事不写 --course）")
    q.add_argument("item", nargs="?"); q.add_argument("--course"); q.add_argument("--due", help="课程时区的日期：2026-09-20 或 09-20")
    q.add_argument("--time", help="HH:MM，也认 4pm / 11:59pm"); q.add_argument("--time-text", dest="time_text", help="写不出具体时刻时的文字，如「课上」")
    q.add_argument("--list", action="store_true", help="列出记过的手动 deadline（带序号）")
    q.add_argument("--remove", help="删掉一条：序号或事项名")
    q.add_argument("--weight"); q.add_argument("--url"); q.add_argument("--note"); q.add_argument("--source"); q.add_argument("--status")
    q.add_argument("--pending", action="store_true", help="还没确认：进区块二"); q.add_argument("--assignment-id", dest="assignment_id", help="替换 Canvas 上的这条作业")
    q.add_argument("--force", action="store_true", help="和 Canvas 上同一个作业的日期对不上也照记（确定 Canvas 写错了才用）")
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
        msg = f"Canvas 返回 HTTP {e.code}：{e.url.split('?')[0] if e.url else ''}" + ("（token 失效？让用户在 Canvas 重新生成一个发到对话里，token set 存好）" if e.code == 401 else "")
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
    finally:
        if "cc_session" in sys.modules:  # 登录模式在后台起过浏览器：关掉，存下续期后的登录
            sys.modules["cc_session"].close_all()


if __name__ == "__main__":
    sys.exit(main())
