---
name: stcanvas
description: STCanvas 是留学生的 Canvas 学习手帐：盯 deadline、排本周该学什么、按状态给建议。用户提到课程、作业、deadline、考试、Canvas、老师，或说「现在什么情况」「最近要交什么」「这周学什么」「做完了」「没状态 / 累 / 来不及」时使用；第一次用时自己完成设置，只向用户要 Canvas 网址和 token。
---

# STCanvas

脚本在本文件同目录的 `tools/coach.py`。宿主给了本文件路径就直接用；没给就依次找 `~/.claude/skills/stcanvas`、`~/.codex/skills/stcanvas`、`~/.agents/skills/stcanvas`。解释器优先用宿主已经提供的 Python；Codex 桌面版先调用 `load_workspace_dependencies` 取得 Python executable，再试 `python3` / `python` / Windows `py -3`。已有任何可用解释器就不安装；全部不可用才征得用户同意安装。下文只写命令名。用用户说话的语言回答，默认中文。

两个地方。**资料夹**给人看：默认桌面的「STCanvas」，`paths` 打印具体路径；根目录是「STCanvas.html」和「Deadline雷达.html」，每门课一个文件夹，里面只有两个子文件夹，「课件」放 Canvas 原件，「产出」放 AI 做的一切。**机器档案**给 AI 用：config.json（学校、时区、课程）、state.json（进度、待确认、心情、手动 deadline）、raw/、plans/、reports/、text/（课件文字稿，默认不提取），在资料夹里的 .coach（老版档案仍兼容 ~/CourseCoach），用户不用管。显示的时间跟着用户电脑的时钟走；deadline 的「今天 / 明天 / 还有 N 天」按课程所在时区数，过没过期按真实时刻算。

## 主次
第一优先永远是准确的 deadline 和这周的清单。课件只排队、后台补，任何时候都不让用户等下载。

## 规矩（AI 默认不会做的，才写在这）
1. 每句结论带出处（作业页、公告、模块、用户说过的话）；推断加 ⚠️。判断说「大概率」，不说「一定」。
2. 只在两种时候开口：用户来问；现在不说就来不及。答完最多续一句下一步。
3. 每次交付末尾一句状态评估加建议：直接用 `status` / `radar` / `study` / `record done` / `record mood` 打印的那句，可以换成用户的口吻，不加新判断（细则 references/state.md）。
4. 待确认的事只问一次，之后进停车场；用户定过的事（state.decisions）不再提。
5. 往 Canvas 发帖、发站内信、交作业：先不带 `--confirmed` 跑 `api post` / `api upload` 拿预览，原样给用户看；用户说「发」再加 `--confirmed`，脚本会弹系统确认窗口，用户本人点「确定」才真的发。窗口弹不出就不发，把链接给用户自己交。
6. 出 deadline 清单、周报、雷达之前一律 `collect --force` 重新核对 Canvas（不吃 10 分钟缓存），哪怕几分钟前刚采过。脚本打印了采集错误或「没采到」的课，就照它的原话点名说哪门课、数据是几点的，再给清单；不许默默拿旧快照当最新的。每份清单末尾写一句数据截至时间。给别人看的清单同样照这条做。

## 第一次（用户不用说任何口令）
`status` 报「还没有档案」→ 按 references/setup.md 走：确认有可用 Python（宿主内置优先，不重复安装）→ `doctor --detect-site --env-dialog`（浏览器记录里认 Canvas 域名；缺 token 才弹窗口）→ 看它的输出：打印了「config.json：已新建」就直接往下；否则一句话说清两样东西，用户粘完再搭话，再跑一次 `doctor` → `collect --touch`（只记元数据，十几秒；失败不进入缓存）→ `radar --write` → `study --write` → `collect --download --background`（课件后台补；同一档案最多一个 worker，命令立刻返回）→ 一条消息：连上了哪个站、最急的一条和第一步、本周最要紧的一件、资料夹在哪、状态一句。doctor 列的「你需要做的事」：自己能做的（`--fix-perms`）做掉，其余最多一句带给用户。网络和权限已就绪时通常一分钟内出首份雷达和清单；首次权限审批或装依赖的时间另算。

脚本退出码：0 成功；退出码 1 = 有提醒，不是失败，照输出里列的事做；2 = 卡住了，输出只有一句原因；3 = 档案版本太老，先跑 `migrate`。

## 用户说什么，做什么
| 用户说 | 做 | 读 |
|---|---|---|
| 任何话（会话开始） | `status`；要看 Canvas 数据先 `collect --touch`（10 分钟内采过它会直接用上次的）；status 说有课件待下载就 `collect --download --background`，不等它 | — |
| 「现在什么情况」 | `status` 一屏：今天必做、每门课下一条、状态一句 | — |
| 「最近要交什么」 | `collect --touch` → `radar --write`；复述每门课下一条、最急一条和第一步、撞车、待确认里今天要定的；不整表贴 | radar.md |
| 「这周学什么」「这周干什么」「周报」 | `collect --force --touch` → `study --write --zh plans/<周>.zh.json`（覆盖层在就必须带上，不带等于把上课时间、tutor、最要紧那几件、停车场、复盘全丢掉）；覆盖层没有就先写一个再跑：脚本查不到的东西（上课时间和教室、tutor、为什么这件最要紧、要定的事、复盘）写进覆盖层，条目和日期交给脚本 | study.md |
| 「做完了」「做完了 2001-2」「✓ 09-16」「2001 看完了」 | `record done <目标>`，回它打印的「✅ …，明天：…」和状态一句 | study.md |
| 「没状态」「累」「来不及」「病了」 | `record mood <词>`，按它返回的建议说，别追问 | state.md |
| 「这个日期只是占位」「老师说 X 号交」「公告说考试在 X」 | `record note <作业id> "…"`（Canvas 日期不算数，不再算过期）/ `record deadline "事项" --course 课 --due 日期 --time 时刻 --weight 权重 --url 作业链接`（进雷达；`--due` 认 2026-09-20 / 09-20，`--time` 认 23:59 / 4pm，认不出当场退回；`--list` 看、`--remove 序号` 删） | radar.md |
| 「这周是第 N 周」「X 不是课」「这门课周二上」「时间按 X 显示」 | `config set term.week1_monday …` / 改 courses / `config set user_tz Asia/Shanghai`（`auto` = 跟着电脑） | setup.md |
| 「资料放哪」「换个文件夹」 | `paths` 报路径；换地方：`config set root <路径>` 再 `doctor`，它会把旧文件搬过去 | setup.md |
| 导读课件、复习包、逐页精讲、做图、问老师、写东西、发帖、交作业、任何想法 | 直接做：先 `paths 课` 拿路径；课件原件在「课件」；课件文字默认不提取给 AI，要读某门课的文字稿先经用户同意开：`config course <课程代码> --materials-ai on`，开了才有 text/<课>/；某周课件还没下就 `collect --materials 课 周`；产物一律写进「产出」；做页面先读 references/style.md；发帖交作业按规矩 5 | toolbox.md |

## 自愈（先修，修不了才说一句）
脚本出错时会连「该怎么办」一起打印：照它那句做，做得了就做掉，别复述。下面几种它给不出办法：
| 情况 | 做 |
|---|---|
| 没有可调用的 Python | 先用宿主公开的 Python（Codex：`load_workspace_dependencies`）并查 `python3` / `python` / Windows `py -3`；确认全不可用，再征得用户同意按平台安装。不要把 `xcode-select --install` 当 Python 安装器 |
| token 贴进了对话 | 不写进任何命令或文件；`doctor --env-dialog` 弹窗口让用户粘，只说「粘进刚弹出的窗口就行」 |
| 认不出学校 / 有几个候选 | 让用户发登录页网址或选一个，`doctor --host 网址`。探测不发 token |
| 浏览器记录读不了 / 被沙盒隐藏 | 按宿主机制申请一次只读权限；仍读不了就直接要网址 |
| 连不上 / 5xx | 脚本已重试；用上次快照回答，并写明「数据截至 X」，哪门课没采到点名说 |
