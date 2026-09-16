# 救驾

给用第二语言上课的留学生的 Canvas 助手：盯 deadline、排本周该学什么、按完成情况给下一步。它是一个 Agent Skill，装在你自己的电脑上，数据存在你自己的文件夹里。

## 安装

跟你的 AI 说一句（把网址换成本仓库的地址）：

> 帮我安装 救驾：https://github.com/&lt;账号&gt;/jiujia

只说名字不带网址不可靠：模型不认识新仓库，同名仓库也可能是别人的，而这个技能会拿到你的 Canvas token。请只从上面这个地址安装。

也可以自己放好文件，确认 `SKILL.md` 在这些位置之一：

- Claude Code：`~/.claude/skills/jiujia/SKILL.md`
- Codex：`~/.agents/skills/jiujia/SKILL.md`（`~/.codex/skills/jiujia/` 也认）
- 其它读 Agent Skills 的工具：`~/.agents/skills/jiujia/SKILL.md`

**装好不用重启**：让 AI 直接读 `SKILL.md`，按里面的「第一次」往下走就行。

## 第一次使用

跟 AI 说「最近要交什么」。它会：用你电脑上已有的 Python → 从浏览器记录里认出你学校的 Canvas 网址（**不会带 token 去试**）→ 你确认是哪个学校 → 弹一个系统窗口让你粘贴 `CANVAS_TOKEN` → 采集 → 生成桌面文件夹、本周清单和 Deadline 雷达。

Token 只发给你确认过的那一个学校地址。它不会出现在对话里，也不会写进任何文件；要换的时候再弹一次窗口。

## 它会读什么

| 读 | 默认 | 怎么改 |
|---|---|---|
| 作业、截止时间、模块、公告 | 开 | 这是它的本职 |
| 站内信（收件箱） | 开 | `config set inbox off` |
| 课件原件下载到你的文件夹 | 开 | `config set materials.auto_download false` |
| **把课件文字交给 AI 读**（导读、逐页精讲、复习包要用） | **关** | 按课打开：`config course <课程代码> --materials-ai on` |

最后一条默认关，是因为不少学校（悉尼大学也在内）把「把课程材料放进生成式 AI」列为误用。要不要打开，由你按你那门课的规定决定。

## 发到 Canvas 的东西

发帖、发站内信、交作业：先给你看预览，你说「发」，再弹一个系统确认窗口，**你本人点确定**才真的发送。窗口弹不出来就不发，把链接给你自己交。

## 写作业这件事

这个工具会帮你写草稿、讲稿、提纲、给老师的消息，也会按你的要求上传文件。**交什么、交不交，由你决定**：请自己遵守你所在学校和那门课对 AI 使用的规定，需要声明的地方自己声明。工具不会替你判断，也不会替你点提交。它不做任何「降低 AI 痕迹」之类的事。

## 你的数据在哪

- 给人看的：桌面「救驾」文件夹——本周清单、Deadline 雷达，每门课一个文件夹（课件放 Canvas 原件，产出放 AI 做的东西）。
- 给程序用的：同一个文件夹里的隐藏目录 `.coach`（配置、进度、采集到的原始数据）。
- token：Windows 存在凭据管理器 / 环境变量，macOS 存在钥匙串，Linux 存在 `~/.config/jiujia/token`。
- 一切都在你自己的电脑上。这个项目没有服务器，不上传任何东西。你让 AI 读的内容会经过你使用的那家 AI 服务。

## 卸载

删掉技能文件夹和桌面的 救驾 文件夹，再去 Canvas → Account → Settings → Approved Integrations 撤销那个 token。

## 依赖

只用 Python 标准库就能跑。少数功能会用到可选的第三方包（都不打包在仓库里，用到了才从 PyPI 装），清单和各自的许可见 `THIRD_PARTY_NOTICES.md`。

## 声明

与 Instructure 无关，未获其背书；Canvas 是 Instructure, Inc. 的商标。本项目按 MIT 许可发布（见 `LICENSE`），不提供任何担保。使用前请自行确认它符合你所在学校的规定。
