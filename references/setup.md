# 入门：两样东西，其余自己来

## 顺序
1. Python：先用宿主已经提供的解释器。Codex 桌面版调用 `load_workspace_dependencies`，直接使用返回的 Python executable；否则依次试 `python3 --version`、`python --version`、Windows `py -3 --version`，再查已安装路径。任何一个能运行就不安装；全部不可用才征得用户同意安装。不要用 `xcode-select --install` 代替 Python 安装。
2. `doctor --detect-site --env-dialog`：不需要 token 就能在浏览器记录里认 Canvas 域名；缺 token 时才弹出粘 token 的窗口（Windows 环境变量窗口 / Mac 终端存钥匙串）。它会打印认出的域名和要用户做的事。
3. 看输出决定：
   - 打印了「config.json：已新建」（token 早就在，站点也认出来了）→ 不用问任何事，直接第 5 步。
   - 否则只发一条消息，四种情况选一种（原文）：
     - 认出一个：「在你浏览器记录里找到 Canvas 站点 canvas.xxx.edu，先按这个来，不对就告诉我。现在只差 token：Canvas → Account → Settings → Approved Integrations → New Access Token，Purpose 填 STCanvas，Expires 设学期最后一天，整段复制，粘进刚弹出的窗口（Windows：用户变量 → 新建，变量名 CANVAS_TOKEN，值粘 token，确定两次；Mac：终端里粘贴回车两次）。粘完随便回我一句。」
     - 有几个：「浏览器记录里有两个像 Canvas 的站点：A（常去）和 B，你学校用的是哪个？回一个就行。」+ token 那段。
     - 已读到记录但没找到：「把你平时登录 Canvas 的网址整个发我（地址栏 https:// 开头那一串）。」+ token 那段。
     - 记录读不了或可能被沙盒隐藏：先按宿主机制申请一次只读浏览器记录权限并重跑；仍不行才要网址。
     - 已找到候选但网络 / 沙盒无法验证：先批准访问候选 Canvas（需要时检查校园网 / VPN）并重跑；候选不对才要网址。
     - token 已经在、只差站点：只说站点那句。
4. 用户回来 → `doctor`（有网址就 `doctor --host 网址`）：验证 token、建档（课程、时区、学期）。401 → 「token 多半复制不全，重新生成再粘一次」，不重新问学校。
5. `collect --touch`（只记元数据；失败尝试不进入十分钟缓存）→ `radar --write` → `study --write` → `collect --download --background`（只消费已有队列；同一档案最多一个后台 worker，命令立刻返回），然后一条消息（状态一句放最后）：「连上了：域名（浏览器记录里认出来的，不对就告诉我），N 门课。最急的一条：…（还有 N 天），第一步：…。这周最要紧的一件：…。课件和我做的东西都在桌面的「STCanvas」文件夹里，一门课一个文件夹，课件正在后台下。以后随时说「最近要交什么」「这周学什么」。状态：…。建议：…。」
   主次：deadline 和本周清单先出来，其它一切（下载、导读）都排在后面。
6. doctor 打印的「你需要做的事」：`--fix-perms` 这类自己能做的做掉；电脑时区和课程时区不同这类，只在用户人就在学校城市时提一句「把电脑时区改成 X」，否则不提。

## 站点探测（doctor --detect-site）
读 Chrome / Edge / Brave / Firefox / Safari 的历史和书签：先复制到临时目录再只读打开，SQL 只取网址和访问次数；匹配 `*.instructure.com`、域名含 canvas 整词、路径 /login/canvas、/courses/数字；候选按访问次数排序，不带 token 探一下（Canvas 对 /api/v1/users/self 回 401）；只把认定的域名写进 HOME/site.json，临时副本删除。**不读网页标题，不保留任何网址。** Safari 的记录要系统的「完全磁盘访问」，读不了就直接要网址，不去申请权限。`--dry-run` 只列会读哪些文件。

## token 放哪（都不用重启）
读取顺序：环境变量 CANVAS_TOKEN → Windows 用户级注册表 → Mac 钥匙串（stcanvas-canvas）→ ~/.config/stcanvas/token。
- Windows：`doctor --env-dialog` 弹「环境变量」窗口，用户变量 → 新建 → CANVAS_TOKEN → 值粘 token → 确定两次。
- Mac：`doctor --env-dialog` 打开终端，已在等输入（security add-generic-password），粘贴回车两次。
- 别在 Claude 的终端里 setx：写进的是隔离副本，用户电脑读不到，还留在历史里。
- 用户把 token 贴进对话：不写进任何命令或文件，立刻弹窗口，只说「收到，粘进刚弹出的窗口就行」。不讲安全课；用户问了再说「聊天记录会存在本机，介意就之后重新生成一个」。

## 建档时自动推的（用户不用回答）
- 课程：本学期 active 的课，代码从 course_code 里取（`CS101-F26` → CS101，`2026FA-BIO-101-01` → BIO101），图书馆、迎新、BYOD 测试站跳过并写进 config.notes。
- 时区：课程时区来自 Canvas（课程的 time_zone → 用户设置 → 电脑时钟 → UTC），deadline 按它算。显示的时间和「今天」跟着用户电脑的时钟走（config 里 `user_tz: auto`）：人在哪里，看到的就是哪里的时间；两地此刻时间不同时，deadline 并列写两个（先课程时区，再电脑时区）。用户要固定：「时间按上海显示」→ `config set user_tz Asia/Shanghai`；`config set user_tz auto` 恢复跟着电脑。
- 学期周：config 有 week1_monday 就用；没有就在排本周清单时按模块名里最大已解锁的 Week N 反推，写进 config 并标「推断」；算不出就显示「周次待定」。用户说「这周是第 N 周」→ `config set term.week1_monday <那周周一>`，再 `config set term.week_source user`。
- 上课日：不问。用户提到「这门课周二上」→ `config set courses` 里该课的 weekday（1–7），本周清单会把课件排在上课前一天。
- 资料夹：默认桌面的「STCanvas」（Windows 从系统读真正的桌面路径，可能在 OneDrive 里），每门课一个文件夹，「课件」放 Canvas 原件，「产出」放 AI 做的一切；机器档案在里面的 .coach（隐藏），老版档案仍兼容 ~/CourseCoach。用户要换：`config set root <路径>` 再 `doctor`，旧文件会搬过去。`paths` 随时打印路径。
- skill 位置：doctor 发现自己不在 skills 目录（用户把文件拖进了聊天）会提示，`doctor --install` 复制进 ~/.claude/skills（Codex 就 ~/.codex/skills），以后新对话直接可用。

## 宿主差异（详见 agents.md）
- Claude Code：`doctor --fix-perms` 把权限规则写进 ~/.claude/settings.json（备份 .bak）；被拦就把打印的块给用户。
- Codex 桌面版：先用 `load_workspace_dependencies` 返回的 Python。第一次读取浏览器记录或联网访问 Canvas 时可能要批准；只批准准确的 `coach.py` 命令前缀，合适时选「始终允许」。`doctor` 仍会打印可合并进 config.toml 的项目片段。
- 其它读 AGENTS.md 的代理：按它自己的方式批准 python 命令。

## 数据坏了
config.json 或 state.json 解析失败：复制成 .bak-日期，`doctor` 重建（config 从 Canvas 拉，state 建空的），告诉用户重建了什么、待确认和手动 deadline 可能少了。
