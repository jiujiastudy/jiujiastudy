"""体检（doctor）和迁移（migrate）。没有任何学校或用户的默认值。

建档在 cc_bootstrap.py，token 在 cc_token.py，宿主权限在 cc_perms.py，装依赖、装 skill 和分享版在 cc_install.py。
"""
import datetime as dt
import glob
import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error

import brand
import canvas_api
import cc_host
import deps
from cc_bootstrap import align_week1, bootstrap_config
from cc_config import SCHEMA_VERSION, CoachError, Ctx, adapt_v1, minimal_state, upgrade_v2, version_of
from cc_install import check_skill_location, pip_install
from cc_paths import WEEK_PAGE, agent_kind, coach_cmd, fwd, home_dir, python_cmd, root_dir
from cc_perms import check_perms, claude_settings_path, codex_snippet, fix_perms
from cc_store import jload, jsave
from cc_time import Clock, ensure_zone, machine_zone, normalize_zone, parse_date, zone_data_available, zone_label
from cc_token import TOKEN_FILE_SHOWN, open_token_prompt, token

NARRATIVE_LABELS = {"confirmed_by_user": "用户已确认", "first_step_hints": "下一步提示", "class_meeting": "上课信息", "deck_location": "文件位置"}


def doctor(args):
    home = home_dir(getattr(args, "home", None))
    checks, must_fix = [], []
    blocking = False
    extra_blocks = []
    ask_host_action = "让用户把 Canvas 登录页网址整个发过来（地址栏 https:// 开头那一串），然后跑 doctor --host 网址"
    retry_browser_action = ("按宿主机制批准一次只读浏览器记录权限后重跑 doctor --detect-site；"
                            "仍读不了，再让用户发 Canvas 登录页网址并跑 doctor --host 网址")
    retry_canvas_action = ("按宿主机制批准访问候选 Canvas（需要时检查校园网 / VPN）后重跑 doctor --detect-site；"
                           "候选不对，再让用户发登录页网址并跑 doctor --host 网址")

    def ok(name, detail=""):
        checks.append(("OK", name, detail))

    def warn(name, detail="", action=None):
        checks.append(("注意", name, detail))
        if action and action not in must_fix:
            must_fix.append(action)

    def err(name, detail="", action=None):
        nonlocal blocking
        checks.append(("错误", name, detail))
        if action and action not in must_fix:
            must_fix.append(action)

    cfg = jload(os.path.join(home, "config.json"))
    agent = agent_kind(cfg, getattr(args, "agent", None))
    display_shell = "powershell" if sys.platform == "win32" and agent == "codex" else "portable"
    display_python = python_cmd(display_shell)
    display_coach = coach_cmd(display_shell)

    # 1 python + tz data
    tz_probe = normalize_zone(getattr(args, "tz", None)) or normalize_zone((cfg or {}).get("course_tz")) or machine_zone() or "UTC"
    if not zone_data_available() and pip_install(deps.DEP_NAMES["tzdata"]):  # 只有 doctor 装 tzdata，别的命令不 pip
        importlib.invalidate_caches()
        zone_data_available(refresh=True)
    if zone_data_available():
        ensure_zone(tz_probe)
        ok("Python", f"{sys.version.split()[0]}，时区数据可用")
    elif importlib.util.find_spec("pip") is None:
        err("Python 时区数据", f"没有时区数据（tzdata），{tz_probe} 暂按电脑时钟算；这个 Python 也没有 pip",
            f"运行 {display_python} -m ensurepip --upgrade 再重跑体检；用 uv 的话运行 uv pip install --python \"{fwd(sys.executable)}\" tzdata")
    else:
        err("Python 时区数据", f"没有时区数据（tzdata），{tz_probe} 暂按电脑时钟算；自动安装没成功",
            f"运行 {display_python} -m pip install --no-cache-dir tzdata，然后重跑体检")

    # 2 home
    try:
        os.makedirs(home, exist_ok=True)
        test = os.path.join(home, ".write-test")
        open(test, "w").close()
        os.remove(test)
        ok("档案目录", home)
    except OSError as e:
        err("档案目录", f"{home} 不可写：{e}", f"检查 {brand.env_name('HOME')} 指向的文件夹是否存在且可写：{home}")
        blocking = True

    # 3 site detection (no token needed) when asked or when no host is known
    site = jload(os.path.join(home, "site.json"), {}) or {}
    host = cc_host.normalize_host(getattr(args, "host", None)) or (cfg or {}).get("canvas_host") or cc_host.normalize_host(os.environ.get("CANVAS_HOST")) or site.get("host")
    detect_res = None
    if getattr(args, "detect_site", False) or (not host and not getattr(args, "school", None) and not getattr(args, "no_detect", False)):
        import cc_detect
        detect_res = cc_detect.detect(dry_run=getattr(args, "dry_run", False))  # 探测不带 token（S09）
        if detect_res.get("dry_run"):
            checks.append(("信息", "站点探测（预演）", "；".join(detect_res["files"]) or "当前没有枚举到浏览器记录文件；预演未读取内容"))
        elif detect_res.get("found"):
            found_host = cc_host.normalize_host(detect_res["found"])
            if not host:
                found_candidate = next((c for c in detect_res["candidates"]
                                        if cc_host.normalize_host(c.get("url")) == found_host), None)
                browsers = ", ".join((found_candidate or {}).get("browsers") or [])
                # 浏览器记录只是线索，不是答案：token 只发给用户确认过的地址，所以这里不自动采用（S09）
                warn("学校", f"浏览器记录里最像的是 {found_host}" + (f"（{browsers}）" if browsers else ""),
                     f"问用户一句「你学校的 Canvas 是不是 {found_host}？」；是就跑 doctor --host {found_host}，不是就让他发登录页网址")
            elif cc_host.normalize_host(host) == found_host:
                ok("学校", f"浏览器记录与已指定地址一致：{host}")
            else:
                checks.append(("信息", "学校", f"浏览器候选 {found_host} 与已指定地址 {host} 不同；继续验证已指定地址"))
        elif detect_res.get("ambiguous"):
            hs = "、".join(c["host"] for c in detect_res["candidates"] if c.get("is_canvas"))
            warn("学校", f"浏览器记录里有不止一个像 Canvas 的站点：{hs}", f"问用户「你学校用的是哪个：{hs}？」然后跑 doctor --host 那个")
        elif detect_res.get("validation_unavailable"):
            hs = "、".join(c["host"] for c in detect_res["candidates"])
            warn("学校", f"浏览器记录里找到候选 {hs}，但当前网络或沙盒无法验证", retry_canvas_action)
        else:
            status = detect_res.get("read_status")
            why = ("浏览器记录存在但读不了（可能被系统权限或宿主沙盒拦住）" if status == "unreadable" else
                   "没有发现可读取的浏览器记录（可能没有记录，也可能被宿主沙盒隐藏）" if status == "unavailable_or_absent" else
                   "已读取浏览器记录，但没找到 Canvas")
            warn("学校", why, retry_browser_action if status in ("unreadable", "unavailable_or_absent") else ask_host_action)

    # 4 token + host verification
    detected_found = cc_host.normalize_host((detect_res or {}).get("found"))
    me = ((detect_res or {}).get("me") if detected_found and detected_found == cc_host.normalize_host(host) else None)
    api = None
    tok, token_available, verified = None, False, False
    school = getattr(args, "school", None)
    try:
        tok = token()
        token_available = True
        if not host and school:
            found, me, tried = cc_host.find_host(tok, cc_host.candidate_hosts(school))
            if found:
                host = found
                ok("学校", f"按「{school}」认出 {host}")
            else:
                warn("学校", "按「" + school + "」猜的地址都不对：" + "；".join(f"{h} {r}" for h, r in tried),
                     "让用户把 Canvas 登录页的网址整个发过来，跑 doctor --host 网址")
        if host:
            candidate_api = canvas_api.Canvas(host, tok)
            if me is None:
                me = candidate_api.get("/api/v1/users/self")
            api, verified = candidate_api, True
            ok("token", f"已设置；/users/self 200 {me.get('name')}（{me.get('id')}）@ {host}")
        else:
            ok("token", "已设置；有学校地址后再验证")
            if not any(name == "学校" for _, name, _ in checks):
                warn("学校", "还不知道学校的 Canvas 地址", ask_host_action)
    except canvas_api.CanvasAuthError:
        opened = open_token_prompt() if getattr(args, "env_dialog", False) else None
        gen = f"去 Canvas → Account → Settings → Approved Integrations → New Access Token（Purpose 填 {brand.NAME}，Expires 设学期最后一天）整段复制；"
        if sys.platform == "win32":
            warn("token", "CANVAS_TOKEN 未设置" + ("；已弹出「环境变量」窗口" if opened else ""),
                 gen + ("在刚弹出的窗口里" if opened else "让我弹出窗口（doctor --env-dialog），在窗口里")
                 + "上半部分「用户变量」点「新建」，变量名 CANVAS_TOKEN，变量值粘贴 token，确定两次。不用重启，粘完再说一次「体检」")
        elif sys.platform == "darwin":
            warn("token", "CANVAS_TOKEN 未设置" + ("；已打开「终端」等你粘 token" if opened else ""),
                 gen + ("在刚打开的终端里" if opened else "让我打开终端（doctor --env-dialog），在终端里")
                 + "粘贴 token 回车（输入时不显示字符，会要你粘两次），它存进钥匙串。不用重启，存完再说一次「体检」")
        else:
            warn("token", "CANVAS_TOKEN 未设置", gen + "在 shell 配置里加 export CANVAS_TOKEN=\"…\" 后重开对话，或把 token 写进 " + TOKEN_FILE_SHOWN + "（chmod 600）")
    except urllib.error.HTTPError as e:
        api = None
        if e.code == 401:
            warn("token", f"token 在 {host} 上登不上（401）：多半是复制不全",
                 "在同一个 Canvas 站点重新生成一个 token，再完整粘进 token 窗口；不要重问学校")
        else:
            warn("Canvas", f"{host} 返回 HTTP {e.code}", "让用户把学校 Canvas 登录页的网址发过来，跑 doctor --host 网址")
    except urllib.error.URLError as e:
        api = None
        warn("Canvas", f"连不上 {host}：{e.reason}", "检查网络（校园网 / VPN）后重跑体检")
    except canvas_api.CanvasError as e:
        api = None
        warn("Canvas", str(e))

    if not host and not any(name == "学校" for _, name, _ in checks):
        warn("学校", "还不知道学校的 Canvas 地址", ask_host_action)

    # 5 config
    if cfg is None:
        if not verified:
            if token_available and not host:
                missing = "只差学校地址"
            elif host and not token_available:
                missing = "只差 token"
            elif not host and not token_available:
                missing = "还缺 token 和学校地址"
            else:
                missing = "Canvas 身份或网络验证未通过"
            err("config.json", f"还没建档：{missing}")
            blocking = True
        else:
            try:
                cfg, info = bootstrap_config(home, host, api, me, getattr(args, "all_courses", False), getattr(args, "tz", None))
                jsave(os.path.join(home, "config.json"), cfg)
                ok("config.json", f"已新建：{len(cfg['courses'])} 门课（{', '.join(c['code'] for c in cfg['courses'])}），学期 {cfg['term'].get('name') or '未知'}，"
                   f"时区 {cfg['course_tz']}（来自{info['tz_src']}）" + (f"；跳过非课程站点 {len(info['skipped'])} 个" if info["skipped"] else ""))
                try:
                    os.remove(os.path.join(home, "site.json"))
                except OSError:
                    pass
            except Exception as e:  # noqa: BLE001
                err("config.json", f"自动建档失败：{type(e).__name__}: {e}")
                blocking = True
    elif version_of(cfg) < 2:
        warn("config.json", "还是 v1", f"我来跑：{display_coach} migrate")
    else:
        if version_of(cfg) < SCHEMA_VERSION:
            cfg = upgrade_v2(cfg)
            jsave(os.path.join(home, "config.json"), cfg)
            checks.append(("信息", "config.json", f"已升到 v{SCHEMA_VERSION}（只补键，值不变）"))
        if not cfg.get("canvas_host") and host:
            cfg["canvas_host"] = host
            jsave(os.path.join(home, "config.json"), cfg)
        ok("config.json", f"v{version_of(cfg)}，{len(cfg.get('courses') or [])} 门课，课程时区 {cfg.get('course_tz')}，显示时区{'跟着电脑' if cfg.get('user_tz') in (None, '', 'auto') else '固定为 ' + str(cfg.get('user_tz'))}")
        if me and (cfg.get("user") or {}).get("id") and cfg["user"]["id"] != me.get("id"):
            warn("用户", f"config.user.id={cfg['user']['id']} 与 token 的 {me.get('id')} 不一致", "确认 token 是不是你自己的账号")
        if me and not (cfg.get("user") or {}).get("id"):
            cfg["user"] = {"id": me.get("id"), "name": me.get("name")}
            jsave(os.path.join(home, "config.json"), cfg)

    # 一门课都没有就什么都做不了：这是错误，不是提示（S02）
    if cfg is not None:
        live = [c for c in (cfg.get("courses") or []) if not c.get("inactive")]
        if not live:
            had = len(cfg.get("courses") or [])
            err("课程", "config.json 里一门在读的课都没有" + (f"（{had} 门都已结课或退课）" if had else ""),
                f"新学期开学后跑：{display_coach} collect --force；还是空的就是这个账号在 Canvas 上没有在读课程")
            blocking = True

    # 6 state
    sp = os.path.join(home, "state.json")
    st = jload(sp)
    if st is None:
        if cfg is not None and version_of(cfg) >= 2:
            jsave(sp, minimal_state())
            ok("state.json", "已新建（空）")
        else:
            warn("state.json", "不存在")
    elif version_of(st) < 2:
        warn("state.json", "还是 v1", f"我来跑：{display_coach} migrate")
    else:
        ok("state.json", f"待确认 {sum(1 for p in st.get('pending_confirmations') or [] if not p.get('resolved'))} 条未解决")

    # 7 dirs: 机器档案 + 给人看的资料夹（每门课 课件 / 产出），旧的 courses/ 搬过去
    for d in ("plans", "reports", os.path.join("raw", "daily")):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    root = root_dir(cfg or {})
    moved = []
    try:
        os.makedirs(root, exist_ok=True)
        if sys.platform == "win32" and fwd(home).lower().startswith(fwd(root).lower() + "/"):
            try:  # 机器档案在资料夹里就藏起来；藏不了（没有 attrib、子进程被拦）不影响使用，不报
                subprocess.run(["attrib", "+h", home], capture_output=True, timeout=20)
            except (OSError, subprocess.SubprocessError):
                pass
        if cfg and version_of(cfg) >= 2:
            ctx_tmp = Ctx(home, quiet=True)
            ctx_tmp.ensure_dirs()
            old_courses = os.path.join(home, "courses")
            for c in cfg.get("courses") or []:
                src = os.path.join(old_courses, c["code"])
                if not os.path.isdir(src):
                    continue
                for name in os.listdir(src):
                    sp = os.path.join(src, name)
                    if name == "materials" and os.path.isdir(sp):
                        for f in os.listdir(sp):
                            shutil.move(os.path.join(sp, f), os.path.join(ctx_tmp.materials_dir(c["code"]), f))
                        os.rmdir(sp)
                    else:
                        dst = os.path.join(ctx_tmp.output_dir(c["code"]), name)
                        if os.path.exists(dst):
                            dst = os.path.join(ctx_tmp.output_dir(c["code"]), f"旧_{name}")
                        shutil.move(sp, dst)
                    moved.append(f"{c['code']}/{name}")
                if not os.listdir(src):
                    os.rmdir(src)
            if os.path.isdir(old_courses) and not os.listdir(old_courses):
                os.rmdir(old_courses)
            sp, dp = os.path.join(home, "DDL雷达.html"), os.path.join(root, "Deadline雷达.html")
            if os.path.exists(sp) and not os.path.exists(dp):
                shutil.copy2(sp, dp)
            reports = sorted(glob.glob(os.path.join(home, "reports", "周报_*.html")))
            wk = os.path.join(root, WEEK_PAGE)
            if reports and not os.path.exists(wk):
                shutil.copy2(reports[-1], wk)
        ok("资料夹", f"{root}（每门课：课件 / 产出）" + (f"；已把旧的 courses/ 搬过去：{len(moved)} 项" if moved else ""))
    except Exception as e:  # noqa: BLE001
        warn("资料夹", f"{root} 建不了或搬不动：{type(e).__name__}: {e}", "换个位置：config set root <路径>，再跑 doctor")

    # 8 week alignment (when config has no week1_monday)
    if cfg and version_of(cfg) >= 2 and not (cfg.get("term") or {}).get("week1_monday"):
        try:
            r = align_week1(Ctx(home, quiet=True))
            if r:
                checks.append(("信息", "学期周", f"按模块名推断现在是第 {r[0]} 周，第 1 周周一 {r[1]}（不对就说「这周是第 N 周」）"))
            else:
                checks.append(("信息", "学期周", "还没采集或模块没按周命名；采集后排本周清单时会自动算，算不出就说「这周是第 N 周」"))
        except Exception as e:  # noqa: BLE001
            checks.append(("信息", "学期周", f"暂时算不出（{type(e).__name__}）"))

    # 9 clock vs display tz
    if cfg:
        try:
            raw = cfg.get("user_tz")
            auto = raw in (None, "", "auto")
            ctz_name = normalize_zone(cfg.get("course_tz")) or tz_probe
            mz = normalize_zone(machine_zone() or "")
            if auto:
                if not mz:
                    warn("电脑时钟", "认不出电脑的时区，先按课程时区显示", "说「我人在 X」我把显示时区固定成 X（config set user_tz）")
                elif mz != ctz_name:
                    checks.append(("信息", "电脑时钟", f"显示时间跟着电脑走（{zone_label(mz)}）；课程时区是 {zone_label(ctz_name)}，deadline 会并列写两个时间。人其实在 {zone_label(ctz_name)} 的话，把电脑时区改过去就只剩一个时间"))
                else:
                    ok("电脑时钟", f"显示时间跟着电脑走（{zone_label(mz)}），和课程时区一致")
            else:
                utz_name = normalize_zone(raw) or ctz_name
                utz = ensure_zone(utz_name)
                now = dt.datetime.now(dt.timezone.utc)
                end = parse_date((cfg.get("term") or {}).get("end")) or (now.date() + dt.timedelta(days=90))
                probe_at = dt.datetime.combine(end, dt.time(12), tzinfo=dt.timezone.utc)
                mismatch = []
                for label, t in (("现在", now), (f"学期末 {end}", probe_at)):
                    machine = dt.timedelta(seconds=time.localtime(t.timestamp()).tm_gmtoff)
                    want = t.astimezone(utz).utcoffset()
                    if machine != want:
                        mismatch.append(f"{label}：电脑 UTC{machine.total_seconds() / 3600:+g}，{utz_name} UTC{want.total_seconds() / 3600:+g}")
                if mismatch:
                    warn("电脑时钟", "；".join(mismatch), f"显示时区固定为 {zone_label(utz_name)}，和电脑不一致：系统设置里把电脑时区改过去，或 config set user_tz auto 让显示跟着电脑走")
                else:
                    ok("电脑时钟", f"显示时区固定为 {zone_label(utz_name)}，与电脑一致（含学期末）")
        except Exception as e:  # noqa: BLE001
            warn("电脑时钟", f"检查失败：{type(e).__name__}")

    # 9b skill 位置：不在 skills 目录（比如把文件拖进了聊天），换个对话就找不到；--install 复制进去
    try:
        lvl, detail, action = check_skill_location(getattr(args, "install", False), getattr(args, "agent", "auto"), display_coach)
        if lvl == "ok":
            ok("skill 位置", detail)
        else:
            warn("skill 位置", detail, action)
    except Exception as e:  # noqa: BLE001
        warn("skill 位置", f"检查失败：{type(e).__name__}")

    # 10 deps：缺就自动装
    missing = deps.missing()
    if missing:
        installed, failed = [], []
        for m in missing:
            (installed if pip_install(deps.DEP_NAMES[m]) else failed).append(deps.DEP_NAMES[m])
        if installed:
            ok("依赖", "已自动安装 " + "、".join(installed))
        if failed:
            warn("依赖", "自动安装失败：" + "、".join(failed) + "（课件提取文字会降级为只记文件名）",
                 f"运行 {display_python} -m pip install --no-cache-dir " + " ".join(failed))
    else:
        ok("依赖", " / ".join(deps.DEP_NAMES[m] for m in deps.DEP_NAMES if m != "tzdata") + " 已装")

    # 11 permissions per host agent
    if agent == "claude":
        missing_allow, missing_dirs, block = check_perms(home, root_dir(cfg or {}))
        if (missing_allow or missing_dirs) and getattr(args, "fix_perms", False):
            try:
                p = fix_perms(home, root_dir(cfg or {}))
                ok("权限", f"已写入 {p}（原文件已备份 .bak）")
                missing_allow, missing_dirs = [], []
            except Exception as e:  # noqa: BLE001
                warn("权限", f"自动写入失败：{type(e).__name__}: {e}")
        if missing_allow or missing_dirs:
            warn("权限", f"Claude Code 的 {claude_settings_path()} 缺 {len(missing_allow)} 条 allow" + ("，缺 additionalDirectories" if missing_dirs else ""),
                 "跑 doctor --fix-perms 自动合并；被拦就把下面的 permissions 块粘进那个文件，保存后重开对话")
            extra_blocks.append(("要合并进 settings.json 的 permissions 块：", json.dumps(block, ensure_ascii=False, indent=2)))
        else:
            ok("权限", "Claude Code 全局 settings.json 已含全部规则")
    elif agent == "codex":
        checks.append(("信息", "权限", "Codex 第一次读取浏览器记录或访问 Canvas 时可能要求批准；只放行准确的 coach.py 命令前缀，合适时选「始终允许」。下面的项目片段可合并进 config.toml"))
        extra_blocks.append(("Codex config.toml 片段：", codex_snippet(home)))
    else:
        checks.append(("信息", "权限", f"宿主 {agent}：按它自己的方式批准 python 命令即可"))

    # 12 old tools
    old = os.path.join(home, "tools")
    if os.path.isdir(old) and os.path.exists(os.path.join(old, "daily_report.py")):
        checks.append(("信息", "旧脚本", f"{old} 仍在；可移到 _backup/"))

    lines = [f"{lvl:<3} {name}：{detail}" if detail else f"{lvl:<3} {name}" for lvl, name, detail in checks]
    if detect_res and not detect_res.get("dry_run"):
        import cc_detect
        lines += ["", cc_detect.to_text(detect_res)]
    if must_fix:
        lines += ["", "你需要做的事："] + [f"{i}. {a}" for i, a in enumerate(must_fix, 1)]
    for title, block in extra_blocks:
        lines += ["", title, block]
    # 退出码（S56）：token 这次在 Canvas 上验证通过、config 和 state 都在，就是 0，「你需要做的事」只是提醒；
    # 已经建档但还没连上 Canvas 是 1；什么都建不了（缺 token / 学校地址、档案目录不可写）是 2。
    ready = bool(verified and version_of(jload(os.path.join(home, "config.json"))) >= 2
                 and version_of(jload(os.path.join(home, "state.json"))) >= 2)
    code = 2 if blocking else (0 if ready or not must_fix else 1)
    return code, {"checks": [{"level": l, "name": n, "detail": d} for l, n, d in checks], "must_fix": must_fix, "agent": agent,
                  "host": host, "home": home, "detect": detect_res, "ready": ready, "exit": code, "text": "\n".join(lines)}


def md_of(v, depth=0):
    ind = "  " * depth
    out = []
    if isinstance(v, dict):
        for k, x in v.items():
            if isinstance(x, (dict, list)):
                out.append(f"{ind}- {k}:")
                out += md_of(x, depth + 1)
            else:
                out.append(f"{ind}- {k}: {x}")
    elif isinstance(v, list):
        for x in v:
            if isinstance(x, dict):
                out.append(f"{ind}- ")
                out += md_of(x, depth + 1)
            elif isinstance(x, list):
                out += md_of(x, depth + 1)
            else:
                out.append(f"{ind}- {x}")
    else:
        out.append(f"{ind}- {v}")
    return out


def narrative_markdown(code, nar, today):
    L = [f"# {code} · 进行中", f"> 从 state.json v1 迁出（{today}）。放正在进行的事；做完就删掉这一段，或搬进 档案.md。", ""]
    for k, v in nar.items():
        label = NARRATIVE_LABELS.get(k)
        if not label:
            m = re.match(r"^(check|\w+?)_(\d{4}-\d{2}-\d{2})$", k)
            label = f"{m.group(2)} {'核查' if m.group(1) == 'check' else m.group(1).replace('_', ' ')}" if m else k
        L.append(f"## {label}（{k}）")
        L += md_of(v)
        L.append("")
    return "\n".join(L)


def fix_index(text):
    out, n = [], 0
    for l in text.splitlines():
        if l.startswith("|") and not l.startswith("|---") and not l.rstrip().endswith("|"):
            l = l.rstrip() + " |"
            n += 1
        out.append(l)
    return "\n".join(out).rstrip("\n") + "\n", n


def fix_log(text):
    new, n = re.subn(r"(?<!\n)(- \*\*\d{4}-\d{2}-\d{2})", r"\n\1", text)
    if new and not new.endswith("\n"):
        new += "\n"
    return new, n


def migrate(home, dry_run=False):
    cp, sp = os.path.join(home, "config.json"), os.path.join(home, "state.json")
    cfg1, state1 = jload(cp), jload(sp) or {}
    if cfg1 is None:
        raise CoachError(f"找不到 {cp}；先跑 doctor", 2)
    if version_of(cfg1) >= SCHEMA_VERSION and version_of(state1) >= 2:
        print(f"已是 v{SCHEMA_VERSION}，无需迁移")
        return 0, {"already_current": True}
    today = Clock(cfg1).today_user().isoformat()
    if version_of(cfg1) >= 2 and version_of(state1) >= 2:
        cfg3 = upgrade_v2(cfg1)
        summary = {"already_current": False, "from": version_of(cfg1), "to": SCHEMA_VERSION, "dry_run": dry_run, "moved_keys": [], "fixed": []}
        if not dry_run:
            ts = time.strftime("%Y%m%d-%H%M%S")
            bdir = os.path.join(home, "_backup", ts)
            os.makedirs(bdir, exist_ok=True)
            shutil.copy2(cp, os.path.join(bdir, "config.json"))
            jsave(cp, cfg3)
            summary["backup_dir"] = bdir
        return 0, summary
    cfg2, state2, narratives = adapt_v1(cfg1, state1, home, today)
    moved = [f"{code}.{k}" for code, nar in narratives.items() for k in nar]
    idx_p, log_p, snap_p = os.path.join(home, "INDEX.md"), os.path.join(home, "成果日志.md"), os.path.join(home, "raw", "daily", "snapshot.json")
    idx_txt = open(idx_p, encoding="utf-8").read() if os.path.exists(idx_p) else ""
    log_txt = open(log_p, encoding="utf-8").read() if os.path.exists(log_p) else ""
    idx_new, idx_n = fix_index(idx_txt) if idx_txt else ("", 0)
    log_new, log_n = fix_log(log_txt) if log_txt else ("", 0)
    snap = jload(snap_p)
    snap_fix = bool(snap and snap.get("raw_dir") and os.path.isabs(str(snap["raw_dir"])))
    fixed = []
    if idx_n:
        fixed.append(f"INDEX.md {idx_n} 行补竖线")
    if log_n:
        fixed.append(f"成果日志.md {log_n} 处拆行")
    if snap_fix:
        fixed.append("snapshot.json raw_dir 改相对路径")
    summary = {"already_current": False, "from": 1, "to": SCHEMA_VERSION, "moved_keys": moved, "fixed": fixed,
               "pending": len(state2["pending_confirmations"]), "decisions": len(state2["decisions"]), "dry_run": dry_run}
    if dry_run:
        return 0, summary
    ts = time.strftime("%Y%m%d-%H%M%S")
    bdir = os.path.join(home, "_backup", ts)
    os.makedirs(bdir, exist_ok=True)
    for p in (cp, sp, idx_p, log_p, snap_p):
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(bdir, os.path.basename(p)))
    jsave(cp, cfg2)
    jsave(sp, state2)
    for code, nar in narratives.items():
        p = os.path.join(home, "进行中_杂项.md") if code == "_misc" else os.path.join(home, "courses", code, "进行中.md")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        text = narrative_markdown(code, nar, today)
        with open(p, "a" if os.path.exists(p) else "w", encoding="utf-8") as f:
            f.write(("\n" + text.split("\n", 2)[2]) if os.path.exists(p) and text.count("\n") >= 2 else text)
    if idx_n:
        with open(idx_p, "w", encoding="utf-8") as f:
            f.write(idx_new)
    if log_txt and (log_n or not log_txt.endswith("\n")):
        with open(log_p, "w", encoding="utf-8") as f:
            f.write(log_new)
    if snap_fix:
        try:
            snap["raw_dir"] = fwd(os.path.relpath(snap["raw_dir"], home))
            jsave(snap_p, snap)
        except ValueError:
            pass
    summary["backup_dir"] = bdir
    return 0, summary
