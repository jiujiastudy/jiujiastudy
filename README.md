# STCanvas

STCanvas 是一个连接个人 Canvas 的学习手帐 Skill：整理 deadline、生成每周学习安排，并按完成进度给出下一步。

## 直接安装

把 `STCanvas.zip` 交给 Codex 或 Claude Code，然后说：

> 安装 STCanvas skill。安装完成后新开一个对话。

也可以手动解压，并确认 `SKILL.md` 位于以下目录：

- Codex：`~/.codex/skills/stcanvas/SKILL.md`
- Claude Code：`~/.claude/skills/stcanvas/SKILL.md`
- 其他读取 Agent Skills 的工具：`~/.agents/skills/stcanvas/SKILL.md`

## 第一次使用

新开一个对话，说：

> 最近要交什么

STCanvas 会优先使用宿主已有的 Python，尝试从浏览器记录中识别学校的 Canvas 域名，然后用系统窗口接收 `CANVAS_TOKEN`。网络与权限就绪后，它会生成桌面 `STCanvas` 文件夹、`STCanvas.html` 周手帐和 `Deadline雷达.html`。

发帖、发信和交作业会先显示预览，只有用户再次同意并在系统确认窗口点确定后才会发送。
