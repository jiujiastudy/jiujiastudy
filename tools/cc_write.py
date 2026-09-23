"""往 Canvas 写：api 命令（get / download 只读；post / upload 先预览，用户说「发」后再弹系统确认窗口）和写请求本身。

canvas_api.py 只读；发帖、发站内信、交作业的请求只在这个文件里。
"""
import json
import os
import sys
import urllib.error
import urllib.request

import brand
import canvas_api
from canvas_api import CanvasError
from cc_config import CoachError, Ctx
from cc_store import load_json_arg


def run_api(args):
    """coach.py api get|download|post|upload。"""
    ctx = Ctx(args.home, quiet=True, allow_missing=True)
    api = ctx.api if ctx.cfg.get("canvas_host") else canvas_api.from_config()
    if args.op == "get":
        data = api.get(args.a)
        text = json.dumps(data, ensure_ascii=False, indent=1)
        if args.b:
            with open(args.b, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"wrote {args.b} ({len(data) if isinstance(data, list) else 1} item(s))")
        else:
            sys.stdout.write(text + "\n")
        return 0, {"path": args.a}
    if args.op == "download":
        r = api.download(args.a, args.b)
        print(json.dumps(r, ensure_ascii=False))
        return 0, r
    if args.op in ("post", "upload"):
        mode = getattr(api, "mode", "token")
        if mode in ("session", "moodle"):  # 登录模式和 Moodle 都只读
            import cc_session
            raise CoachError(cc_session.READ_ONLY.replace("Canvas", "Moodle") if mode == "moodle" else cc_session.READ_ONLY, 2)
        return _api_write(ctx, api, args)
    raise CoachError("api 子命令：get / download / post / upload", 2)


def _course_code_by_id(ctx, cid):
    return next((c.get("code") for c in ctx.cfg.get("courses") or [] if str(c.get("id")) == str(cid)), None) or f"课程 {cid}"


import re

AI_RULE_RE = re.compile(r"(?i)(artificial intelligence|generative ai|\bAI\b|ChatGPT|academic integrity|学术诚信|人工智能)")


def ai_rule_line(desc, limit=160):
    """作业说明里关于 AI 的那一句，原样截一段。没有就返回 None。

    只摆事实，不做判断：交不交、怎么交是学生自己的事（发起人 2026-09-16 决定）。
    """
    from htmlkit import strip_tags
    text = re.sub(r"\s+", " ", strip_tags(desc or "")).strip()
    if not text:
        return None
    for piece in re.split(r"(?<=[.!?。！？])\s*", text):  # 去掉标签后句子之间可能没有空格
        if AI_RULE_RE.search(piece):
            piece = piece.strip()
            return piece if len(piece) <= limit else piece[:limit].rstrip() + "……"
    return None


def _write_preview(ctx, api, args, body):
    """写操作预览；拒绝空文件、错 id、不收上传、扩展名不符和次数用完。"""
    import re as _re
    from cc_time import parse_ts
    from htmlkit import strip_tags
    p = {"lines": [], "url": None, "refuse": None}
    if args.op == "upload":
        cid, aid, f = args.a, args.b, args.file
        if not aid or not f:
            p["refuse"] = "交作业要三样：课程 id、作业 id、--file 文件"
            return p
        if not os.path.isfile(f):
            p["refuse"] = f"找不到文件：{f}"
            return p
        size = os.path.getsize(f)
        if size == 0:
            p["refuse"] = f"文件是空的：{os.path.basename(f)}（0 字节）"
            return p
        try:
            a = api.get(f"/api/v1/courses/{cid}/assignments/{aid}?include[]=submission")
        except Exception as e:  # noqa: BLE001
            p["refuse"] = f"Canvas 上找不到这个作业（{getattr(e, 'code', type(e).__name__)}）：课程 {cid} 作业 {aid}，多半是 id 写错了"
            return p
        name = os.path.basename(f)
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        types = a.get("submission_types") or []
        allowed = [x.lower().lstrip(".") for x in a.get("allowed_extensions") or []]
        sub = a.get("submission") or {}
        att, used = a.get("allowed_attempts"), int(sub.get("attempt") or 0)
        p["url"] = a.get("html_url")
        if "online_upload" not in types:
            p["refuse"] = f"「{a.get('name')}」不收文件上传（提交方式：{'、'.join(types) or '未设'}），按作业页的要求交：{p['url']}"
        elif allowed and ext not in allowed:
            p["refuse"] = f"「{a.get('name')}」只收 {'/'.join(allowed)}，这个文件是 .{ext or '（无扩展名）'}"
        elif att not in (None, -1) and used >= int(att):
            p["refuse"] = f"「{a.get('name')}」最多交 {att} 次，已经交了 {used} 次"
        due = parse_ts(a.get("due_at"))
        if size >= 1048576:
            size_text = f"{size / 1048576:.1f} MB"
        elif size >= 1024:
            size_text = f"{size / 1024:.1f} KB"
        else:
            size_text = f"{size} 字节"
        p["lines"] = [f"交作业：{_course_code_by_id(ctx, cid)}「{a.get('name')}」",
                      f"文件：{name}（{size_text}）",
                      f"截止：{ctx.clock.fmt(due) if due else 'Canvas 没写'}"]
        if args.comment:
            p["lines"].append(f"留言：{args.comment}")
        if sub.get("submitted_at"):
            p["lines"].append(f"注意：{ctx.clock.fmt(parse_ts(sub['submitted_at']))} 已经交过一次，这次会成为第 {used + 1} 次提交")
        rule = ai_rule_line(a.get("description"))
        if rule:  # 这门课自己写的 AI 规定，原样摆一句；不做判断、不拦截（G03）
            p["lines"].append(f"这门课的作业页写着：「{rule}」")
            if p["url"]:
                p["lines"].append(f"作业页：{p['url']}")
        return p
    path = (args.a or "").split("?")[0].rstrip("/")
    text = strip_tags(body.get("message") or body.get("body") or "").strip()
    short = text if len(text) <= 300 else text[:300] + "……"
    m = _re.search(r"/courses/(\d+)/discussion_topics/(\d+)/entries(?:/(\d+)/replies)?$", path)
    if path.endswith("/conversations"):
        rec = body.get("recipients") or []
        p["lines"] = [f"发站内信给：{'、'.join(str(x) for x in rec) or '（没写收件人）'}", f"主题：{body.get('subject') or '（无）'}"]
        if not rec:
            p["refuse"] = "站内信没写收件人"
    elif m:
        cid, tid, eid = m.groups()
        try:
            t = api.get(f"/api/v1/courses/{cid}/discussion_topics/{tid}")
        except Exception as e:  # noqa: BLE001
            p["refuse"] = f"Canvas 上找不到这个讨论（{getattr(e, 'code', type(e).__name__)}），多半是 id 写错了"
            return p
        p["url"] = t.get("html_url")
        p["lines"] = [f"{'回复讨论里的一条' if eid else '在讨论里发帖'}：{_course_code_by_id(ctx, cid)}「{t.get('title')}」"]
    else:
        p["lines"] = [f"发到 Canvas：POST {args.a}"]
    p["lines"].append(f"内容：{short or '（空）'}")
    if not text and not p["refuse"]:
        p["refuse"] = "内容是空的"
    return p


def _api_write(ctx, api, args):
    """写操作三步：预览（不带 --confirmed，不发）→ 用户说「发」→ 带 --confirmed 弹系统确认窗口，用户本人点「确定」才发。"""
    import cc_confirm
    body = (load_json_arg(args.body) or {}) if args.op == "post" else {}
    pv = _write_preview(ctx, api, args, body)
    head = "\n".join(pv["lines"])
    res = {"sent": False, "preview": pv["lines"], "url": pv["url"]}

    def say(text, code, extra=None):
        res.update(extra or {})
        print(json.dumps(res, ensure_ascii=False) if args.json else text)
        return code, res

    if pv["refuse"]:
        return say(f"没有发送：{pv['refuse']}", 2, {"refused": pv["refuse"]})
    if not args.confirmed:
        return say(head + "\n\n这是预览，没有发送。把上面几行原样给用户看；用户说「发」再加 --confirmed 跑一次，"
                   "会弹出系统确认窗口，要用户本人点「确定」。", 0)
    ans = cc_confirm.ask(head + "\n\n点「确定」才会真的发出去；点「取消」什么都不发。")
    if ans != "ok":
        why = {"cancel": "用户在确认窗口点了取消", "timeout": "确认窗口没人点，已自动关闭",
               "unavailable": "这台电脑弹不出确认窗口"}.get(ans, ans)
        tail = f" 请用户自己在 Canvas 上操作：{pv['url']}" if ans == "unavailable" and pv.get("url") else ""
        return say(f"没有发送：{why}。{tail}".rstrip(), 2 if ans == "unavailable" else 1, {"confirm": ans})
    if args.op == "upload":
        r = upload_submission(api, args.a, args.b, args.file, comment=args.comment)
        out = {k: (r or {}).get(k) for k in ("id", "workflow_state", "submitted_at", "attempt", "preview_url")}
    else:
        r = post(api, args.a, body)
        out = r if isinstance(r, dict) else {"result": r}
    try:
        import cc_record
        cc_record.append_log(ctx, "已发到 Canvas（用户在确认窗口点了确定）：" + "；".join(pv["lines"][:2]))
    except Exception:  # noqa: BLE001
        pass
    return say("已发送。\n" + json.dumps(out, ensure_ascii=False)[:2000], 0, {"sent": True, "confirm": "ok", "result": out})


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post(api, path, data=None, method="POST"):
    """写操作（发帖、提交）。只在用户明确确认后由 coach.py api post/upload 调用。"""
    url = api.url_of(path)
    body = json.dumps(data or {}).encode("utf-8")
    headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": f"{brand.SLUG}/2"}
    if api.tok:
        headers["Authorization"] = "Bearer " + api.tok
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with api.opener.open(req, timeout=api.timeout) as r:
        raw = r.read().decode("utf-8")
    return json.loads(raw or "null")


def upload_submission(api, course_id, assignment_id, path, comment=None):
    """Canvas 三步上传：申请上传 → 把文件 POST 到返回的地址 → 用 file_id 提交作业。"""
    import uuid
    name, size = os.path.basename(path), os.path.getsize(path)
    if size == 0:
        raise CanvasError(f"拒绝上传空文件：{name}（0 字节）")
    info = post(api, f"/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/self/files", {"name": name, "size": size})
    upload_url, params = info["upload_url"], info.get("upload_params") or {}
    boundary = f"----{brand.SLUG}-" + uuid.uuid4().hex
    parts = []
    for k, v in params.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8"))
    with open(path, "rb") as f:
        blob = f.read()
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                  'Content-Type: application/octet-stream\r\n\r\n').encode("utf-8") + blob + b"\r\n")
    body = b"".join(parts) + f"--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(upload_url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    no_redirect = urllib.request.build_opener(_NoRedirect())
    file_id = None
    try:
        with no_redirect.open(req, timeout=600) as r:
            raw = r.read().decode("utf-8", "ignore")
            file_id = (json.loads(raw) if raw.strip().startswith("{") else {}).get("id")
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307) and e.headers.get("Location"):
            _, raw = api.fetch(e.headers["Location"])
            file_id = json.loads(raw.decode("utf-8") or "{}").get("id")
        else:
            raise
    if not file_id:
        raise CanvasError("上传后没有拿到 file id，提交没完成")
    payload = {"submission": {"submission_type": "online_upload", "file_ids": [file_id]}}
    if comment:
        payload["comment"] = {"text_comment": comment}
    return post(api, f"/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions", payload)
