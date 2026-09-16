# 页面风格：所有页面照这个来

目标：一眼看懂要做什么、什么时候之前。删比加好。

## 用在哪
- 固定页面：STCanvas 周手帐（tools/render_week.py）和 Deadline 雷达（tools/cc_radar.py）由脚本生成，不手改 HTML。要改样子，改 tools/design.py 或渲染器，改完跑检查。
- 一次性页面：导读、讲义、对比、讲稿、排练表，任何给用户看的 HTML。按这次的内容自己设计结构，不必套 JSON 模板。Python 里 `sys.path.insert(0, "<skill>/tools"); from design import head, foot, status, tag`，正文只用下面的组件；不写 Python 就把 head() 生成的 `<style>` 整段复制过去。
- 旧的复习包页面（render_unit.py 的 unit / plan / vocab / mock）颜色和字体已经接到这里，组件还是旧的，暂不受检。

## 变量（只在 tools/design.py 定义一次，深浅两套自动切换）
- 颜色：--bg 底，--surface 卡片，--sunk 浅色块，--line 分隔线，--ink 正文，--muted 次要文字，--faint 只给线和占位。--accent 是唯一的强调色：链接、今天、最要紧的那张卡。--good / --warn / --bad 只表示状态：完成、待确认、快到期或已过期，各有一个 -soft 底色。--highlight 是荧光笔，只给时间点和考试。
- 字号只有四级：--fs-s 13 小字，--fs-m 15 正文和小标题，--fs-l 18 卡片标题和今天的必做，--fs-xl 26 页面标题。
- 间距 --s1 到 --s7：4、8、12、16、24、32、48。圆角 --r 12、--r-s 8。字体 --font（Inter 加系统中文字体，断网也好看），代码 --mono。
- 深浅：打开页面时看电脑的钟，19:00 到 6:00 深色，右上角按钮临时切换。只要用变量，深色自动就对。

## 组件（类名）
- 页头 `header.top`：h1，一行 `.meta`（时间范围、数据截至、时区），可选一句 `.lead`，可选 `.progress`。
- 状态条：`status(ev)`，按档位自动是 `.is-good` / `.is-warn` / `.is-bad`。
- 卡片 `.card`；最要紧的那张加 `.hero`；卡片上方的小标签 `.kicker`；课程代码 `.code`；卡里的补充行 `.sub`。
- 勾选清单 `ul.rows > li[data-row]`：勾选框 + `.t`（动词 `.v` + 标题链接）+ 右侧小字 `.m`。要记住勾选就给框加 `data-tick="编号"`；计入进度加 `data-item`；底部提示里显示的名字放 `data-label`；档案里已完成的加 `checked data-done`。
- deadline 行：`.rows` 里标题前放 `span.rel`（今天、还有 N 天），3 天内加 `.soon`。没有勾选框的清单用 `ul.rows.nobox`。
- 标签 `tag(文字, 种类)`：warn 待确认，bad 已过期，good 完成，hl 时间点。
- 提醒块 `.callout`：撞车之类，一页最多一两个。
- 折叠 `details.fold`：次要内容一律折起来，比如公告、没写日期的、资料来源。
- 其它：每天 `ol.days`，今天卡 `.card.today`，课程网格 `.courses`，贴边卡 `.card.flush`，表格外面包 `.scroll`，页面结尾由 `foot()` 生成；不要在页面里添加个人落款、二维码、社群、咨询或其他引流内容。

## 简洁
- 手机一屏之内要看到三样：状态、今天的必做、最急的 deadline。
- 每行字都回答「做什么」或「什么时候之前」，回答不了就删掉或折叠。同一件事全页只出现一次。
- 不写说明书式的提示，比如「做完就勾上」「灰字是有空再做的」，设计要自己说明白。
- 不用 emoji 当装饰，不用手写体或艺术字，不堆阴影、不套多层边框、不画虚线框。
- 时间和数字用 `.num` 对齐；链接只挂在标题上；中文和英文、数字之间留一个空格。
- 只改怎么显示：日期、数字、顺序和脚本算出来的内容一律不改。

## 交之前
1. 用当前已选定的 Python 跑 `tools/style_check.py 页面.html`，没有 FAIL。
2. 390 宽和 1280 宽各看一眼，深色也看一眼（浏览器控制台 `coachTheme.apply('dark')`）。390 宽不能左右滚动。
