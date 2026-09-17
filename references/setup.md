# 入门：一个小窗口，其余自己来

## 顺序
1. Python：先用宿主已经提供的解释器。Codex 桌面版调用 `load_workspace_dependencies`，直接使用返回的 Python executable；否则依次试 `python3 --version`、`python --version`、Windows `py -3 --version`，再查已安装路径。任何一个能运行就不安装；全部不可用才征得用户同意安装。不要用 `xcode-select --install` 代替 Python 安装。
2. `doctor --token-window`：缺 token 就弹出「填学校 + 粘 token」的小窗口，命令立刻返回。窗口里写着去 Canvas 生成 token 的步骤；用户点保存时，窗口先认学校（查表或网址）、不带 token 探一下是不是 Canvas，再只对这一个地址验 token，复制不全、学校写错当场在窗口里说。验过的 token 存进 `~/.config/jiujiastudy/token`，学校地址存进机器档案的 site.json。
3. 看输出决定：
   - 打印了「config.json：已新建」（token 和学校早就有）→ 不用问任何事，直接第 5 步。
   - 否则把「你需要做的事」里那段话原样发给用户，一条消息说完，别拆成两条。弹出了小窗口时它是：「弹出了一个「救驾」小窗口：填上你的学校，再按窗口里写的步骤去 Canvas 生成 token，粘进去点保存。窗口里显示「连上了」以后，回我一句「好了」。token 别发到聊天里。」
   - 窗口弹不出来（没有桌面、沙盒拦了），它会给另一段话：一条消息里同时问学校、教怎么生成和存 token，照发。
   - token 早就有、只差学校：只问「你是哪个学校的？说校名就行，或者发 Canvas 网址」。
4. 用户回来 → `doctor`；用户是在对话里说的学校，用 `doctor --school 他说的校名`（发的是网址就 `--host 网址`）：验证 token、建档（课程、时区、学期）。「对得上不止一所」「表里没有」就照 doctor 那句问一次，不猜。401 → 跑 `doctor --token-window` 让用户重新粘一个新生成的 token，不重新问学校。
5. `collect --touch`（只记元数据；失败尝试不进入十分钟缓存）→ `radar --write` → `study --write` → `collect --download --background`（只消费已有队列；同一档案最多一个后台 worker，命令立刻返回），然后一条消息（状态一句放最后）：「连上了：学校（域名），N 门课。最急的一条：…（还有 N 天），第一步：…。这周最要紧的一件：…。课件和我做的东西都在桌面的「救驾」文件夹里，一门课一个文件夹，课件正在后台下。以后随时说「最近要交什么」「这周学什么」。状态：…。建议：…。」
   主次：deadline 和本周清单先出来，其它一切（下载、导读）都排在后面。
6. doctor 打印的其余「你需要做的事」：自己能做的做掉；电脑时区和课程时区不同这类，只在用户人就在学校城市时提一句「把电脑时区改成 X」，否则不提。

## 认学校（doctor --school / 小窗口）
`tools/cc_host.py` 里有一张校名 → Canvas 地址的表（澳洲、新西兰、英国、美国、加拿大、香港、新加坡、欧洲的常见学校，中英文名和常用简称），每个地址都不带 token 探过是 Canvas。只按整个校名或简称对，不做「包含」：「西悉尼大学」不会被认成悉尼大学。对得上两所（比如「纽卡斯尔大学」澳洲和英国各一所）就问是哪一所；表里没有就要 Canvas 网址（登录 Canvas 后浏览器地址栏那一串）。**token 只发给查表查准的或用户给的那一个地址**，发之前先不带 token 探一下是不是 Canvas。不读浏览器记录。

## token 放哪（都不用重启）
读取顺序：环境变量 CANVAS_TOKEN → `~/.config/jiujiastudy/token`（小窗口存的；Mac / Linux 权限 600）→ Windows 用户级注册表 → Mac 钥匙串（jiujiastudy-canvas）。文件排在注册表和钥匙串前面，所以在小窗口里重新粘一次就能换掉旧的。
- 小窗口弹不出时的老办法：Windows 弹「环境变量」窗口（用户变量 → 新建 → CANVAS_TOKEN → 值粘 token → 确定两次）；Mac 打开终端存钥匙串（粘贴回车两次）；Linux 让用户把 token 一行写进 `~/.config/jiujiastudy/token`。
- 别在 Claude 的终端里 setx：写进的是隔离副本，用户电脑读不到，还留在历史里。
- 用户把 token 贴进对话：不写进任何命令或文件，跑 `doctor --token-window`，只说「收到，粘进刚弹出的小窗口就行」。不讲安全课；用户问了再说「聊天记录会存在本机，介意就之后重新生成一个」。

## 建档时自动推的（用户不用回答）
- 课程：本学期 active 的课，代码从 course_code 里取（`CS101-F26` → CS101，`2026FA-BIO-101-01` → BIO101），图书馆、迎新、BYOD 测试站跳过并写进 config.notes。
- 时区：课程时区来自 Canvas（课程的 time_zone → 用户设置 → 电脑时钟 → UTC），deadline 按它算。显示的时间和「今天」跟着用户电脑的时钟走（config 里 `user_tz: auto`）：人在哪里，看到的就是哪里的时间；两地此刻时间不同时，deadline 并列写两个（先课程时区，再电脑时区）。用户要固定：「时间按上海显示」→ `config set user_tz Asia/Shanghai`；`config set user_tz auto` 恢复跟着电脑。
- 学期周：config 有 week1_monday 就用；没有就在排本周清单时按模块名里最大已解锁的 Week N 反推，写进 config 并标「推断」；算不出就显示「周次待定」。用户说「这周是第 N 周」→ `config set term.week1_monday <那周周一>`，再 `config set term.week_source user`。
- 上课日：不问。用户提到「这门课周二上」→ `config set courses` 里该课的 weekday（1–7），本周清单会把课件排在上课前一天。
- 资料夹：默认桌面的「救驾」（Windows 从系统读真正的桌面路径，可能在 OneDrive 里），每门课一个文件夹，「课件」放 Canvas 原件，「产出」放 AI 做的一切；机器档案在里面的 .coach（隐藏），老版档案仍兼容 ~/CourseCoach。用户要换：`config set root <路径>` 再 `doctor`，旧文件会搬过去。`paths` 随时打印路径。
- skill 位置：doctor 发现自己不在 skills 目录（用户把文件拖进了聊天）会提示，`doctor --install` 复制进 ~/.claude/skills（Codex 就 ~/.codex/skills），以后新对话直接可用。

## 权限（详见 agents.md）
- 不改任何宿主的权限设置。Claude Code：SKILL.md 开头的 `allowed-tools` 只放行 `python "${CLAUDE_SKILL_DIR}/tools/coach.py" …` 这一种写法，所以调用写法要和 SKILL.md 一字不差。
- 宿主还是拦（比如自动模式说「从网上下载的代码」）：不绕开。告诉用户把权限模式换成每次询问，弹框时点允许（有「总是允许」就选），再说「继续」。
- Codex 桌面版：先用 `load_workspace_dependencies` 返回的 Python。第一次联网访问 Canvas 时可能要批准；只批准准确的 `coach.py` 命令前缀，合适时选「始终允许」。`doctor` 会打印可合并进 config.toml 的项目片段。
- 其它读 AGENTS.md 的代理：按它自己的方式批准 python 命令。

## 数据坏了
config.json 或 state.json 解析失败：复制成 .bak-日期，`doctor` 重建（config 从 Canvas 拉，state 建空的），告诉用户重建了什么、待确认和手动 deadline 可能少了。
