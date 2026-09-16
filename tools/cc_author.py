"""作者脚注：一句话 + 两个二维码，和「问题反馈」入口。

只出现在学生自己看的周报页底部，不进作业文件、不进交给老师的任何东西。
没有统计、没有跳转追踪；二维码是本地图片，页面不连外网。
二维码图放在技能目录的 assets/ 下，缺了就只留文字，绝不画假二维码。
"""
import base64
import os

from htmlkit import esc

LINE = "大家都离家这么远了，能帮上彼此一点，就帮一点。"
FEEDBACK = "使用问题或建议，可以通过小红书或抖音私信我。"

# url 留 None：作者只给了账号和二维码，没给主页链接，不猜。
ACCOUNTS = (
    {"key": "xhs", "platform": "小红书", "handle": "悉尼苏丹（控制canvas版）", "id": "42860459630",
     "file": "xiaohongshu.png", "mime": "image/png", "url": None},
    {"key": "dy", "platform": "抖音", "handle": "悉尼苏丹（控制canvas版）", "id": "64313418501",
     "file": "douyin.jpg", "mime": "image/jpeg", "url": None},
)


def assets_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def _data_uri(a):
    p = os.path.join(assets_dir(), a["file"])
    try:
        with open(p, "rb") as f:
            return f"data:{a['mime']};base64," + base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return None


def accounts():
    """带上二维码的账号列表；没有图的那个 uri 为 None（只出文字，不画假码）。"""
    return [dict(a, uri=_data_uri(a)) for a in ACCOUNTS]


def css(accs=None):
    """二维码用 background-image，这样同一张图在脚注和反馈里只存一份 base64。"""
    accs = accs if accs is not None else accounts()
    rules = [
        ".sig{text-align:left}",
        ".sig .word{color:var(--muted);font-size:var(--fs-s)}",
        ".qrs{display:flex;flex-wrap:wrap;gap:var(--s5);margin-top:var(--s4)}",
        ".qrs figure{margin:0}",
        ".qrs .qr{display:block;width:132px;height:132px;background-size:cover;border-radius:2px}",
        ".qrs figcaption{margin-top:var(--s2);color:var(--muted);font-size:var(--fs-s)}",
        ".qrs .num{display:block;color:var(--faint)}",
        ".sig .linkish{display:inline-block;margin-top:var(--s4);padding:0;border:0;background:none;"
        "color:var(--faint);font:400 var(--fs-s)/1.6 var(--font);text-decoration:underline;"
        "text-underline-offset:3px;cursor:pointer}",
    ]
    for a in accs:
        if a.get("uri"):
            rules.append(f'.qr-{a["key"]}{{background-image:url("{a["uri"]}")}}')
    return "\n".join(rules)


def _qr(a):
    label = f'{a["platform"]}二维码'
    if a.get("uri"):
        return f'<span class="qr qr-{a["key"]}" role="img" aria-label="{esc(label)}"></span>'
    return ""


def _figure(a, with_id=False):
    cap = f'{a["platform"]} · @{a["handle"]}'
    num = f'<span class="num">{esc(a["platform"])}号 {esc(a["id"])}</span>' if with_id else ""
    body = _qr(a) + f'<figcaption>{esc(cap)}{num}</figcaption>'
    if a.get("url"):
        return f'<figure><a href="{esc(a["url"])}" target="_blank" rel="noopener">{body}</a></figure>'
    return f"<figure>{body}</figure>"


def footer_html(accs=None):
    """周报最底下那一块。没有任何一张二维码时仍然出（文字就够找到人）。"""
    accs = accs if accs is not None else accounts()
    if not accs:
        return ""
    return ('<footer class="sig" data-author><p class="word">' + esc(LINE) + "</p>"
            + '<div class="qrs">' + "".join(_figure(a) for a in accs) + "</div>"
            + '<button type="button" class="linkish" data-hide-author>隐藏作者信息</button></footer>')


def feedback_html(accs=None):
    """「问题反馈」折叠块：作者脚注被隐藏了，这里照样找得到人。"""
    accs = accs if accs is not None else accounts()
    return ('<details class="fold"><summary>问题反馈</summary>'
            + f'<p class="meta">{esc(FEEDBACK)}</p>'
            + '<div class="qrs">' + "".join(_figure(a, with_id=True) for a in accs) + "</div>"
            + '<button type="button" class="linkish" data-show-author>恢复作者信息</button></details>')
