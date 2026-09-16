"""状态感知：从客观信号（打勾、提交、deadline）和主观信号（用户说的话）推断学生状态，给一句建议。

四档：正常 / 落后 / 卡住 / 过载。规则可解释，每个信号都能指出来源。
"""
import datetime as dt
import re

from cc_time import parse_date, parse_ts

LEVELS = ["正常", "落后", "卡住", "过载"]
MOOD_WORDS = {
    "没状态": "落后", "不想学": "落后", "累": "落后", "疲": "落后", "困": "落后",
    "来不及": "过载", "太多": "过载", "忙不过来": "过载", "焦虑": "过载", "慌": "过载",
    "卡住": "卡住", "不会": "卡住", "看不懂": "卡住", "写不出": "卡住",
    "病": "病了", "生病": "病了", "发烧": "病了", "住院": "病了",
}


def classify_mood(word):
    w = (word or "").strip()
    for k, v in MOOD_WORDS.items():
        if k in w:
            return v
    return "落后"


def weight_pct(s):
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", s or "")
    return float(m.group(1)) if m else 0.0


def evaluate(ctx, today, plan=None, rows=None):
    """plan = cc_deadlines.plan_today 的结果（可 None）；rows = 14 天 deadline 行（可 None）。"""
    state, clock = ctx.state, ctx.clock
    signals, level = [], 0

    def bump(to, why):
        nonlocal level
        signals.append(why)
        level = max(level, LEVELS.index(to))

    rows = rows or []
    unsub = [r for r in rows if r.get("origin") == "canvas" and r.get("status") == "未交"]
    overdue = [r for r in rows if r.get("overdue")]
    soon48 = [r for r in unsub if 0 <= (r.get("days_left") if r.get("days_left") is not None else 99) <= 2]
    w7 = sum(weight_pct(r.get("weight")) for r in unsub if 0 <= (r.get("days_left") or 99) <= 7)
    n72 = sum(1 for r in rows if 0 <= (r.get("days_left") or 99) <= 3)
    if w7 >= 40:
        bump("过载", f"7 天内到期的作业合计 {w7:g}% 还没交")
    if n72 >= 3:
        bump("过载", f"72 小时内有 {n72} 条 deadline")
    if overdue:
        bump("卡住", f"有 {len(overdue)} 项已过期未交（{overdue[0].get('course')} {overdue[0].get('item')}）")

    data = (plan or {}).get("data") if plan else None
    days = (data or {}).get("days") or []
    if days:
        past = [d for d in days if parse_date(d.get("date")) and parse_date(d["date"]) <= today]
        ticked = sum(1 for d in past if d.get("status") == "✅")
        musts = sum(1 for d in past if d.get("must"))
        if musts >= 2 and today.weekday() >= 3 and ticked / max(musts, 1) < 0.4:
            bump("落后", f"本周到今天 {musts} 件必做只勾了 {ticked} 件")
        streak = 0
        for d in reversed(past):
            if d.get("must") and d.get("status") != "✅":
                streak += 1
            else:
                break
        if streak >= 3:
            bump("卡住", f"连续 {streak} 天有必做没打勾")
    last_done = parse_ts(state.get("last_done"))
    if last_done and days:
        gap = (today - clock.user_date(last_done)).days
        if gap > 4 and any(d.get("must") for d in days):
            bump("落后", f"上次打勾是 {gap} 天前")
    if soon48 and level < 1:
        bump("落后", f"48 小时内有 {len(soon48)} 项还没交（{soon48[0].get('course')} {soon48[0].get('item')}）")

    sick = False
    for m in state.get("mood") or []:
        d = parse_date(m.get("date"))
        if not d or (today - d).days > 7:
            continue
        lvl = m.get("level") or classify_mood(m.get("word"))
        if lvl == "病了":
            sick = True
            signals.append(f"你 {m.get('date')} 说过{m.get('word')}")
            continue
        signals.append(f"你 {m.get('date')} 说过「{m.get('word')}」")
        level = max(level, min(LEVELS.index(lvl), level + 1) if level else LEVELS.index(lvl))

    label = "病了" if sick else LEVELS[level]
    exam = (next((r for r in rows if r.get("kind") == "exam" and r.get("days_left") is not None), None)
            or next((r for r in rows if r.get("kind") == "exam"), None))  # 有日期的考试优先
    top = next((r for r in rows if r.get("status") == "未交" or r.get("origin") == "manual"), rows[0] if rows else None)
    advice = advise(label, top, exam, plan, today, clock)
    return {"label": label, "signals": signals, "advice": advice, "exam": ({"course": exam["course"], "item": exam["item"], "when": exam["when"]} if exam else None)}


def advise(label, top, exam, plan, today, clock):
    done_today = bool(plan) and plan.get("status") == "✅"
    first = plan.get("first_step") if plan and not done_today else None
    must = plan.get("must") if plan and not done_today else None
    top_txt = f"{top['course']} {top['item']}（{top['when']}{'，' + top['rel'] if top.get('rel') else ''}）" if top else None
    if label == "病了":
        return "先休息。要交的东西去 Canvas 课程页找「Special Consideration」或「Extension」申请，附医生证明；两句话我可以替你起草给老师的消息。"
    if label == "过载":
        return (f"只留必做，按权重排。今天只做最急的一条的第一步：{top_txt or must or '打开作业页看要求'}，15 分钟就停。" +
                ("交不完的先发消息问能不能延期，我可以起草两句。" if top else ""))
    if label == "卡住":
        step = first or "打开作业页，把要求抄成三行"
        lead = "今天的必做已经勾了，先歇；明天" if done_today else "现在"
        return f"{lead}把任务缩到一个动作：{step}。是不会做就告诉我卡在哪一页课件，我指给你看；是没开始就用五分钟规则。"
    if label == "落后":
        tail = "今天的必做已经勾了，今天就到这。" if done_today else f"今天先做：{must or top_txt or '打开本周清单看第一项'}。"
        return f"本周清单砍到「上课前要看的」最小集，周末补一件。{tail}"
    if exam and exam.get("days_left") is None:
        return f"节奏正常。{exam['course']} 有个 {exam['item']} 还没写日期，去公告或课程页确认时间，我记进雷达。"
    if exam:
        return f"节奏正常。{exam['course']} 的 {exam['item']}（{exam['when']}）快到了，从今天起每天过一周的课件。"
    if done_today:
        return "节奏正常。今天的必做已经勾了，剩下的明天再说。"
    return f"节奏正常。下一步：{first or must or top_txt or '看一眼本周清单'}。"


def state_line(ev):
    why = "；".join(ev.get("signals") or []) or "没有异常信号"
    return f"状态：{ev['label']}（{why}）。建议：{ev['advice']}"


def add_mood(ctx, word, note=None):
    from cc_record import touch
    item = {"date": ctx.clock.today_user().isoformat(), "word": word.strip(), "level": classify_mood(word), "note": note}
    moods = ctx.state.setdefault("mood", [])
    moods.append(item)
    cutoff = (ctx.clock.today_user() - dt.timedelta(days=30)).isoformat()
    ctx.state["mood"] = [m for m in moods if (m.get("date") or "") >= cutoff]
    touch(ctx)
    return item
