# 工具箱：用户有想法时直接做

原则：先 `paths 课程代码` 拿到这门课的两个目录。材料用档案里的事实（课件文字稿、雷达、公告、产出里已有的东西）；产物一律写进「产出」，文件名带日期或周次；做完 `record product --file <路径> --status "📦 …"`；最后续一句下一步。用户要什么就做什么，不预设不做的事。

## 两个目录，别混
- 「课件」：Canvas 上的原件（pdf / pptx / docx），只由脚本写入，AI 不往里放东西。
- 「产出」：AI 做的一切：导读、精讲、复习包、草稿、给老师的消息、进行中.md（这门课的进行中笔记）。
- 文字稿：脚本从课件提取的 .txt 在机器档案 `text/<课程代码>/`，读课件内容先读它，没有再打开原件。

## 拿课件
- 采集只排队不下载；后台补：`collect --download --background`（只消费已有队列；同一档案最多一个 worker，立刻返回）。要某门课某一周现在就下：`collect --materials 课程代码 周`（前台，下完再继续）。锁定的会标「未解锁」和解锁时间。
- 一次前台下载：`collect --download`（本周的先，最多 10 个）。想关掉自动排队：`config set materials.auto_download false`（关了就一个都不排，要哪周自己 `collect --materials 课 周`）。

## 页面（先读 references/style.md）
- 一次性页面（导读、讲义、对比图、讲稿、排练表）：按这次的内容自己设计，`from design import head, foot`，只用 style.md 里的组件，存进「产出」；交之前用当前已选定的 Python 跑 `tools/style_check.py 文件`，再在 390 宽和 1280 宽各看一眼。
- 下面几个 JSON 渲染器留给已有的复习包用，新页面不必套：
- 课件导读：写 `产出/导读_W<n>.json` → `guide <json> --record`。字段：course_code, course_name_zh, week_title, class_info_zh, based_on_zh, positioning_zh, this_week_for_you_zh, key_points[{title_zh, term_en, explain_zh, quote_en, quote_src, tags[], hook_zh}], readings[{citation, required, access_zh, local_path, url, focus_zh, skip_zh, est_minutes}], in_class_zh, hooks[{assessment, weight, due_zh, link_zh, url}], actions[{action_zh, first_step_zh, minutes, due_zh, why_zh}], glossary[{en, zh}], gaps_zh[], sources[{label, ref}]。
- 逐页精讲：`产出/精讲_W<n>.json` → `lecture <json> --record`。
- 复习包：`产出/exam_prep/` 下写 `plan.json`（title, subtitle, course_code, exam{course_code, name, weight, date, time, tz_note, duration_min, n_questions, scope, facts[]}, goal[], days[{date, weekday, unit, file, task_zh, minutes}], stem_words[], tips[], exam_day[], sources[]）和 `W<n>.json`（week, course_code, title_en, title_zh, minutes, one_line_zh, why_exam_zh, concepts[{term_en, term_zh, priority, explain_zh, key_sentence_en, key_sentence_zh, src, example_zh, confuse_zh}], readings[], vocab[{en, zh, priority, note_zh}], practice[{q_en, options[4], answer, why_zh, src}], recap_zh[], sources[], gaps_zh[]）→ `unit all <产出>/exam_prep --record`。
- 周计划：手写的计划 JSON 也能渲染：`week <文件>.json --record`。

## 发到 Canvas（规矩 5：预览 → 用户说「发」→ 系统确认窗口）
- 回帖：`api post "/api/v1/courses/<课程id>/discussion_topics/<帖子id>/entries" --body 内容.json`（`{"message": "<p>…</p>"}`）。
- 站内信：`api post /api/v1/conversations --body 信.json`（`{"recipients": ["<用户id>"], "subject": "…", "body": "…"}`）。
- 交作业：`api upload <课程id> <作业id> --file "路径" [--comment "留言"]`。
- 三个都一样。先不带 `--confirmed` 跑：脚本打印预览（哪门课哪个作业、文件名和真实大小、截止、是不是第二次交；或发给谁、发什么），不发送。文件不存在或为空、id 写错、作业不收上传、扩展名不符合、次数用完，它直接拒绝并说原因。把预览原样给用户，用户说「发」再加 `--confirmed`：弹出系统确认窗口，用户点「确定」才发；点取消、110 秒没人点、窗口弹不出，都不发。发完复述返回的状态一句，交完雷达里会显示「已交」。

## 写东西、问老师
用户要草稿、讲稿、引用、给老师的消息：直接写，存进「产出」，登记产物。给老师的消息四行：我看到 A、公告说 B、我目前按 A 做、请确认是否 B；附中文意思和发送路径（Canvas → Inbox → Compose 选课程和 tutor），用户说「发」按上面的流程发站内信。
