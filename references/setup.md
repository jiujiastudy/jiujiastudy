# 入门：两样东西，其余自己来

## 顺序
1. Python：先用宿主已经提供的解释器。Codex 桌面版调用 `load_workspace_dependencies`，直接使用返回的 Python executable；否则依次试 `python3 --version`、`python --version`、Windows `py -3 --version`，再查已安装路径。任何一个能运行就不安装；全部不可用才征得用户同意安装。不要用 `xcode-select --install` 代替 Python 安装。
2. `doctor --detect-site`：不需要 token 就能在浏览器记录里认 Canvas 域名。它会打印认出的域名和要用户做的事。
3. 看输出决定：
   - 打印了「config.json：已新建」（token 早就在，站点也认出来了）→ 不用问任何事，直接第 5 步。
   - 否则只发一条消息，四种情况选一种（原文）：
     - 认出一个：「你学校的 Canvas 是不是 canvas.xxx.edu？是就回我一句（探测只是线索，token 只发给你确认过的那一个地址）。现在只差 token：Canvas → Account → Settings → Approved Integrations → New Access Token，Purpose 填 救驾，Expires 设学期最后一天，把生成的一长串整段复制，直接发给我，我来存好。」
     - 有几个：「浏览器记录里有两个像 Canvas 的站点：A（常去）和 B，你学校用的是哪个？回一个就行。」+ token 那段。
     - 已读到记录但没找到：「把你平时登录 Canvas 的网址整个发我（地址栏 https:// 开头那一串）。」+ token 那段。
     - 记录读不了或可能被沙盒隐藏：先按宿主机制申请一次只读浏览器记录权限并重跑；仍不行才要网址。
     - 已找到候选但网络 / 沙盒无法验证：先批准访问候选 Canvas（需要时检查校园网 / VPN）并重跑；候选不对才要网址。
     - token 已经在、只差站点：只说站点那句。
4. 用户发来 token → `token set` 存好（见下面「token 放哪」），再 `doctor`（有网址就 `doctor --host 网址`）：验证 token、建档（课程、时区、学期）。401 → 「token 多半复制不全，重新生成一个发给我」，不重新问学校。
5. `collect --touch`（只记元数据；失败尝试不进入十分钟缓存）→ `radar --write` → `study --write` → `collect --download --background`（只消费已有队列；同一档案最多一个后台 worker，命令立刻返回），然后一条消息（状态一句放最后）：「连上了：域名（浏览器记录里认出来的，不对就告诉我），N 门课。最急的一条：…（还有 N 天），第一步：…。这周最要紧的一件：…。本周清单做好了：桌面「救驾」文件夹里的「本周清单.html」，双击打开，做完一项就在上面打勾；Deadline 雷达在同一个文件夹。课件和我做的东西也都在这个文件夹里，一门课一个文件夹，课件正在后台下。接下来你可以直接说：「这周学什么」（细看这周每天做什么）、「最近要交什么」、「做完了」、「帮我导读这周的课件」。状态：…。建议：…。」
   从装好到这条消息之间的每一步（认出学校、存好 token 或登好、建档、采集）做完，都用一句话说这一步好了、下一步是什么；要用户动手的（确认学校、给 token、在窗口里登录）只说那一件。
   主次：deadline 和本周清单先出来，其它一切（下载、导读）都排在后面。
6. doctor 打印的「你需要做的事」：`--fix-perms` 这类自己能做的做掉；电脑时区和课程时区不同这类，只在用户人就在学校城市时提一句「把电脑时区改成 X」，否则不提。

## 站点探测（doctor --detect-site）
读 Chrome / Edge / Brave / Firefox / Safari 的历史和书签：先复制到临时目录再只读打开，SQL 只取网址和访问次数；匹配 `*.instructure.com`、域名含 canvas 整词、路径 /login/canvas、/courses/数字；候选按访问次数排序，全程不带 token（Canvas 对 /api/v1/users/self 回 401，用这个判断像不像）；**token 只发给用户确认过的那一个地址**，确认后跑 `doctor --host 网址` 才写 HOME/site.json，临时副本删除。**不读网页标题，不保留任何网址。** Safari 的记录要系统的「完全磁盘访问」，读不了就直接要网址，不去申请权限。`--dry-run` 只列会读哪些文件。

## token 放哪（都不用重启）
用户把 token 直接发到对话里，这是正常做法，不让用户去弄环境变量、终端或别的窗口。收到就存：
- Bash：`python "…/tools/coach.py" token set <<'EOF'`，下一行是 token，再下一行 `EOF`。
- PowerShell：`'token' | python "…/tools/coach.py" token set`。
- token 只从标准输入传，不放进命令参数，不写进别的文件；回复里不重复 token，只说「存好了」接着往下。知道学校地址时 `token set` 会先验一次，登不上就不存，照它那句请用户重新生成。
- 存在 ~/.config/jiujiastudy/token（Mac / Linux 权限 600）。以后每条命令直接读，用户不用再给。换 token：用户再发一个新的，`token set` 覆盖；不用了：`token forget`。
- 读取顺序：这个文件 → 环境变量 CANVAS_TOKEN → Windows 用户级注册表 → Mac 钥匙串（后三个是老版本存的，照样认）。
- 不讲安全课；用户问了再说「token 存在你电脑上，只有你本人的账户能读；聊天记录里也有一份，介意就用完去 Canvas 撤销重新生成」。

## 学校不让生成 token，或学校用 Moodle
Moodle 学校不要 token：拿到网址就 `login --host 网址`（先不带凭据认出是 Moodle）。其余同下：确认学校地址后 `login`，照它打印的话请用户在弹出的窗口里自己登录（AI 不代输密码），用户说登好了 → `login --check` → `doctor`。之后自动用这份登录，只读；报「登录过期」就再 `login`。

## 建档时自动推的（用户不用回答）
- 课程：本学期 active 的课，代码从 course_code 里取（`CS101-F26` → CS101，`2026FA-BIO-101-01` → BIO101），图书馆、迎新、BYOD 测试站跳过并写进 config.notes。
- 时区：课程时区来自 Canvas（课程的 time_zone → 用户设置 → 电脑时钟 → UTC），deadline 按它算。显示的时间和「今天」跟着用户电脑的时钟走（config 里 `user_tz: auto`）：人在哪里，看到的就是哪里的时间；两地此刻时间不同时，deadline 并列写两个（先课程时区，再电脑时区）。用户要固定：「时间按上海显示」→ `config set user_tz Asia/Shanghai`；`config set user_tz auto` 恢复跟着电脑。
- 学期周：config 有 week1_monday 就用；没有就在排本周清单时按模块名里最大已解锁的 Week N 反推，写进 config 并标「推断」；算不出就显示「周次待定」。用户说「这周是第 N 周」→ `config set term.week1_monday <那周周一>`，再 `config set term.week_source user`。
- 上课日：不问。用户提到「这门课周二上」→ `config set courses` 里该课的 weekday（1–7），本周清单会把课件排在上课前一天。
- 资料夹：默认桌面的「救驾」（Windows 从系统读真正的桌面路径，可能在 OneDrive 里），每门课一个文件夹，「课件」放 Canvas 原件，「产出」放 AI 做的一切；机器档案在里面的 .coach（隐藏），老版档案仍兼容 ~/CourseCoach。用户要换：`config set root <路径>` 再 `doctor`，旧文件会搬过去。`paths` 随时打印路径。
- skill 位置：doctor 发现自己不在 skills 目录（用户把文件拖进了聊天）会提示，`doctor --install` 复制进 ~/.claude/skills（Codex 就 ~/.codex/skills），以后新对话直接可用。

## 宿主差异（详见 agents.md）
- Claude Code：`doctor --fix-perms` 把权限规则写进 ~/.claude/settings.json（备份 .bak）；被拦就把打印的块给用户。
- Codex 桌面版：先用 `load_workspace_dependencies` 返回的 Python。第一次读取浏览器记录或联网访问 Canvas 时可能要批准；只批准准确的 `coach.py` 命令前缀，合适时选「始终允许」。`doctor` 仍会打印可合并进 config.toml 的项目片段。
- 其它读 AGENTS.md 的代理：按它自己的方式批准 python 命令。

## 数据坏了
config.json 或 state.json 解析失败：复制成 .bak-日期，`doctor` 重建（config 从 Canvas 拉，state 建空的），告诉用户重建了什么、待确认和手动 deadline 可能少了。
