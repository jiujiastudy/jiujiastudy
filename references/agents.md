# 宿主差异

| | Claude Code | Codex 桌面版 | 读 AGENTS.md 的代理（Cursor、Cline、Gemini CLI…） |
|---|---|---|---|
| 放哪 | `~/.claude/skills/jiujiastudy/` | `~/.codex/skills/jiujiastudy/`（有的版本也读 `~/.agents/skills/`） | `~/.agents/skills/jiujiastudy/`，项目 AGENTS.md 里加一行指过去 |
| 脚本路径 | `${CLAUDE_SKILL_DIR}` 会被换成技能目录 | 不一定告诉；按 SKILL.md 开头的顺序找 | 同左 |
| 命令 | `python "${CLAUDE_SKILL_DIR}/tools/coach.py" …`（Mac / Linux 用 `python3`） | 先 `load_workspace_dependencies`，用返回的 Python executable | 优先宿主已有 Python，再用 `python3` / `python` / Windows `py -3` |
| 权限 | SKILL.md 的 `allowed-tools` 只放行上面那种写法；还是被拦就请用户切到每次询问、点允许，不改设置 | 第一次访问 Canvas 可能要批准；只放行准确的 `coach.py` 前缀，合适时选「始终允许」 | 按宿主自己的方式批准 |
| 发文件给用户 | 有发文件工具就发 HTML；没有就给路径 | 给路径（用户想看就让系统默认程序打开） | 给路径 |
| token 窗口 | `doctor --token-window`（三个宿主都一样；弹不出时它给另一段话） | 同左 | 同左 |

`doctor --agent auto` 自己认宿主（环境变量 CLAUDECODE / CODEX_HOME，或 skill 目录在 .claude / .codex 下）。
