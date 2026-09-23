# 救驾（留学生的 Canvas / Moodle 学习手帐）

给 Codex、Cursor、Cline 这类读 AGENTS.md 的代理看的入口。完整规范在同目录的 `SKILL.md`，先读它。

- 做什么：连上用户自己的 Canvas 或 Moodle，盯 deadline、排本周该学什么、按状态给一句建议。只读采集；发帖、发信、交作业要先预览给用户看，用户同意后脚本还会弹系统确认窗口，由用户本人点确定。
- 命令：优先使用宿主提供的 Python；Codex 先用 `load_workspace_dependencies` 返回的 Python executable，否则再试 `python3` / `python` / Windows `py -3`。已有可用解释器绝不重复安装。常用：`status`、`doctor --detect-site`、`token set`（token 从标准输入传）、`collect --touch`、`radar --write`、`study --write`、`record done <目标>`、`record mood <词>`。
- 第一次：`status` 说还没有档案 → 走 `references/setup.md`，只向用户要 Canvas 网址（先自己在浏览器记录里找）和 token（用户直接发到对话里，`token set` 存好，以后不用再给）；学校不让生成 token，或学校用的是 Moodle（不要 token），就 `login`，用户在弹出的窗口里自己登录。
- 刚装好：用户让你从 GitHub 安装时，装好不要停，按 `SKILL.md`「第一次」在同一个对话里接着做，直到把「本周清单.html」交到用户手上；周报只交脚本生成的这个网页，不自己另写。动手前提醒用户把左下角权限设置改成「帮我批准」（Codex）/「Auto」（Claude Code），能省很多次点「允许」；登录窗口没出来就申请在沙盒外重跑 `login`，不要改用你自带的浏览器（救驾读不到那里的登录）。更新时旧版备份放到 skills 文件夹外面。
- 规矩：每句结论带出处；只在用户来问或来不及时开口；每一步做完告诉用户做成了什么、接下来能直接说哪两三句话；每次交付末尾一句状态和建议；待确认只问一次。
- 两个地方：资料夹（默认桌面的「救驾」，`paths` 打印路径；每门课一个文件夹，「课件」放原件，「产出」放 AI 做的一切；根目录是 本周清单.html 和 Deadline雷达.html）和机器档案（config.json、state.json、raw/、plans/，在资料夹的 .coach 或老版档案 ~/CourseCoach）。config.json 是唯一事实源，没有任何学校的默认值。
- 主次：先出准确的 deadline 和本周清单；课件排队后台补（`collect --download --background`），从不让用户等。
