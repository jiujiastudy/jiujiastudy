"""「我能帮你做什么」页：资料夹根目录的一张静态页，告诉用户能跟 AI 说什么、本周清单怎么用、卡住了怎么办。

点一句话就复制（design.CORE_JS 认 [data-copy]），粘到 AI 对话里发出去就行。
内容不看课程数据；交周报时（study --write --open）没有这页或版本号变了才写。
"""
import os

import brand
from cc_store import save_text
from design import esc, foot, head

PAGE = "我能帮你做什么.html"
SAY = [  # （你可以说，它会做什么）
    ("现在什么情况", "一屏看今天必做、每门课下一件事、你现在的状态"),
    ("最近要交什么", "重新核对学校平台，列出每门课下一条 deadline、最急的一件和第一步"),
    ("这周学什么", "排出这周每天做什么，打开本周清单"),
    ("做完了", "记下你做完的事，告诉你明天做什么"),
    ("好累，今天没状态", "按你的状态把今天的任务缩小，不追问"),
    ("帮我导读这周的课件", "把这周的课件讲成一份 20 分钟能读完的导读"),
    ("帮我做个复习包", "复习计划和模拟小测，考前用"),
    ("帮我起草一封给老师的邮件，问能不能延期", "写好先给你看，发不发你自己决定"),
]
HOWTO = [
    "本周清单：桌面上的「本周清单」，或这个文件夹里的「本周清单.html」，双击就能打开。",
    "做完一项就在本周清单上打勾。打完勾回到 AI 对话里说「做完了」（点页面底部的「复制，发给 AI」再粘过去最快）——不说的话 AI 不知道你做完了。",
    "Deadline雷达.html：两周内所有要交的，最急的在最上面。",
    "每门课一个文件夹：「课件」是学校平台上的原件，「产出」是 AI 帮你做的东西。",
]
STUCK = [
    "登录过期了：跟 AI 说「重新登录」，会弹出一个浏览器窗口，你自己在里面登录；登好它会自己关，这是正常的。",
    "弹出的窗口找不到：先看任务栏；还是没有，就跟 AI 说「没看到窗口」。",
    "AI 说要点「允许」：那是你用的 AI 工具在问权限。嫌麻烦的话，把输入框左下角的权限设置改一下：Claude Code 选「Auto」，Codex 选「帮我批准」。",
]
CSS = ".card p+p{margin-top:var(--s2)}.asks .meta{display:block}"  # 布局上的小调整：段落间距、说明另起一行


def render():
    o = [head(f"{brand.NAME} · 我能帮你做什么", "help", extra_css=CSS),
         f'<p class="kicker" data-version="{esc(brand.VERSION)}">{esc(brand.NAME)}</p>',
         "<h1>我能帮你做什么</h1>",
         '<p class="meta">点一句话就复制，粘到 AI 对话里发出去。用你自己的话说也行。</p>',
         "<h2>你可以直接说</h2>",
         '<div class="card asks"><ul>']
    for say, does in SAY:
        o.append(f'<li><button type="button" data-copy="{esc(say)}">{esc(say)}'
                 f'<span class="meta">{esc(does)}</span></button></li>')
    o += ["</ul></div>", "<h2>本周清单怎么用</h2>", '<div class="card">']
    o += [f"<p>{esc(x)}</p>" for x in HOWTO]
    o += ["</div>", "<h2>遇到这些情况</h2>", '<div class="card">']
    o += [f"<p>{esc(x)}</p>" for x in STUCK]
    o += ["</div>", '<p class="end"><strong>不知道怎么办，直接问 AI。</strong>用你自己的话说就行。</p>', foot()]
    return "\n".join(o)


def ensure(ctx):
    """资料夹根目录没有这页、或是旧版本写的，就写一份。返回路径；写不了返回 None。"""
    path = os.path.join(ctx.root, PAGE)
    try:
        with open(path, encoding="utf-8") as f:
            if f'data-version="{brand.VERSION}"' in f.read():
                return path
    except OSError:
        pass
    try:
        os.makedirs(ctx.root, exist_ok=True)
        save_text(path, render(), keep_backup=False)
        return path
    except OSError:
        return None
