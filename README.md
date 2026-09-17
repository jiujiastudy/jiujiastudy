# 救驾

给用第二语言上课的留学生的 Canvas 学习手帐：盯 deadline、排本周该学什么、按完成情况给下一步。它是一个 Agent Skill，装在你自己的电脑上，数据存在你自己的文件夹里。

[![tests](https://github.com/jiujiastudy/jiujiastudy/actions/workflows/ci.yml/badge.svg)](https://github.com/jiujiastudy/jiujiastudy/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](#要求)

## 它做什么

- **Deadline 雷达**：每门课下一件要交什么、最急的一件、几件撞在一起的、Canvas 上没写日期的，一页看完。
- **本周清单**：按模块和 deadline 排出每门课这周要看的、要做的，每天一件必做。
- **状态和建议**：按打勾情况和你说的话判断正常、落后、过载，给一句具体建议。
- **课件在后台下**：Canvas 原件自动下到每门课的文件夹，从不让你等。
- **发到 Canvas 之前先过你的手**：发帖、发站内信、交作业都先给预览，再弹系统窗口由你本人点确定。

## 要求

- Python 3.10 或更新（CI 在 3.10–3.14 上测过）。没有的话 AI 会先问你要不要装。
- 一个能读 Agent Skills、能跑命令的 AI 助手：Claude Code、Codex 都行。
- Windows、macOS、Linux 都行。

## 安装

跟你的 AI 说一句（两种说法都行）：

> 帮我安装 救驾：https://github.com/jiujiastudy/jiujiastudy

> 帮我安装 GitHub 上的 jiujiastudy/jiujiastudy

两句都带了仓库地址（`jiujiastudy/jiujiastudy` 就是地址）。光说「救驾」或「jiujia」不行：模型不认识新仓库，可能装到别人的同名仓库，而这个技能会拿到你的 Canvas token。请只从上面这个地址安装。

安装和第一次运行时 AI 会请你点「允许」。用 Claude Code 自动模式（Auto）被拦下「刚下载的代码」的话，把输入框旁的权限模式换成每次询问，再说「继续」。救驾不改任何权限设置。

**装好不用重启**，直接跟 AI 说「最近要交什么」。

### 手动安装

`SKILL.md` 要直接在 `skills/jiujiastudy/` 下面，不要多套一层。

Claude Code（macOS / Linux / Git Bash）：

```bash
git clone https://github.com/jiujiastudy/jiujiastudy ~/.claude/skills/jiujiastudy
```

Claude Code（Windows PowerShell）：

```powershell
git clone https://github.com/jiujiastudy/jiujiastudy "$HOME\.claude\skills\jiujiastudy"
```

Codex 及其它读 Agent Skills 的工具：把上面的 `.claude` 换成 `.agents`。

没有 git：下载 [main.zip](https://github.com/jiujiastudy/jiujiastudy/archive/refs/heads/main.zip)，解压出来的文件夹叫 `jiujiastudy-main`，改名成 `jiujiastudy` 再放到上面的位置。Windows「全部解压」会多套一层，确认 `SKILL.md` 直接在 `jiujiastudy` 文件夹里，多套了一层就把里面那层拿出来。

更新：在 `skills/jiujiastudy` 里执行

```bash
git pull
```

## 第一次使用

跟 AI 说「最近要交什么」，它会：

1. 用你电脑上已有的 Python。
2. 从浏览器记录里认出你学校的 Canvas 网址（**不会带 token 去试**），让你确认是哪个学校。
3. 你去 Canvas → Account → Settings → Approved Integrations → New Access Token 生成一个 token，直接发给 AI，它替你存好。
4. 采集，生成桌面文件夹、本周清单和 Deadline 雷达。

token 只要给一次：它存在你电脑上的 `~/.config/jiujiastudy/token`（Windows 是 `C:\Users\你的用户名\.config\jiujiastudy\token`，只有你本人的账户能读），以后每次直接用，只发给你确认过的那一个学校地址。要换就再发一个新的给 AI。token 也会留在你和 AI 的聊天记录里；介意的话，用完去 Canvas 撤销、重新生成。

平时这样说：「现在什么情况」「最近要交什么」「这周学什么」「做完了」「没状态」，或者直接说你想做的事：导读课件、做复习包、写东西、发帖、交作业。

## 配置

都是跟 AI 说一句它就改；想自己改，命令在下面。

| 想改什么 | 默认 | 命令 |
|---|---|---|
| 课件原件自动下载到你的文件夹 | 开 | `config set materials.auto_download false` |
| **把课件文字交给 AI 读**（导读、逐页精讲、复习包要用） | **关** | 按课打开：`config course <课程代码> --materials-ai on` |
| 显示时间跟着哪个时区 | 跟着电脑 | `config set user_tz Asia/Shanghai`，`auto` 恢复跟着电脑 |
| 这周是学期第几周 | 按模块名推断 | 跟 AI 说「这周是第 N 周」 |
| 资料放在哪个文件夹 | 桌面的「救驾」 | `config set root <路径>`，再让 AI 跑一次体检 |

作业、截止时间、模块、公告、站内信（收件箱）总是读，这是它的本职；只读，不改 Canvas 上的任何东西。

课件文字默认不交给 AI，是因为不少学校（悉尼大学也在内）把「把课程材料放进生成式 AI」列为误用。要不要打开，由你按你那门课的规定决定。

## 隐私与数据

- 给人看的：桌面「救驾」文件夹——本周清单、Deadline 雷达，每门课一个文件夹（课件放 Canvas 原件，产出放 AI 做的东西）。
- 给程序用的：同一个文件夹里的隐藏目录 `.coach`（配置、进度、采集到的原始数据）。
- token：`~/.config/jiujiastudy/token`，只有你本人的账户能读。以前存在环境变量或钥匙串里的也认。
- 一切都在你自己的电脑上。这个项目没有服务器，不上传任何东西。你让 AI 读的内容会经过你使用的那家 AI 服务。
- 发帖、发站内信、交作业：先给你看预览，你说「发」，再弹一个系统确认窗口，**你本人点确定**才真的发送。窗口弹不出来就不发，把链接给你自己交。

## 写作业这件事

这个工具会帮你写草稿、讲稿、提纲、给老师的消息，也会按你的要求上传文件。**交什么、交不交，由你决定**：请自己遵守你所在学校和那门课对 AI 使用的规定，需要声明的地方自己声明。工具不会替你判断，也不会替你点提交。它不做任何「降低 AI 痕迹」之类的事。

## 卸载

1. 删掉技能文件夹（`~/.claude/skills/jiujiastudy` 或 `~/.agents/skills/jiujiastudy`）。
2. 删掉桌面的「救驾」文件夹和 `~/.config/jiujiastudy`（Windows：`C:\Users\你的用户名\.config\jiujiastudy`）。
3. 去 Canvas → Account → Settings → Approved Integrations 撤销那个 token。

## 反馈

问题和建议发到 [Issues](https://github.com/jiujiastudy/jiujiastudy/issues)，或在小红书、抖音私信 @悉尼苏丹（控制canvas版）。

## 依赖

只用 Python 标准库就能跑。少数功能会用到可选的第三方包（都不打包在仓库里，用到了才从 PyPI 装），清单和各自的许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 许可

MIT，见 [LICENSE](LICENSE)，不提供任何担保。与 Instructure 无关，未获其背书；Canvas 是 Instructure, Inc. 的商标。使用前请自行确认它符合你所在学校的规定。
