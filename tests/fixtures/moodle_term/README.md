# moodle_term：假 Moodle 场景

`tests/mockmoodle.py` 读这个目录。全是编的：站点名 `Example Moodle (synthetic)`，课程代码 `MDL…`，没有任何真实学校。

## 时间

- now = `2026-09-23T03:00:00Z` = 悉尼 **09-23 周三 13:00**（AEST，UTC+10）。`--date 2026-09-23`。
- 课程时区 Australia/Sydney。**10-04 起夏令时**（AEDT，UTC+11），所以 10 月以后的 23:59 是 `12:59Z`，9 月以前是 `13:59Z`。
- 学期 2026-07-27（周一）到 2026-11-15。课程 startdate `2026-07-26T14:00:00Z`（= 07-27 00:00），enddate `2026-11-14T13:00:00Z`（= 11-15 00:00）。今天是第 9 周。
- 学生：id 1234，Test Student。访客 id 1，站点课程 id 1，站点上下文 2。

## 课程

| id | shortname | fullname | 格式 | 节名 | 备注 |
|---|---|---|---|---|---|
| 4101 | MDL1001_S2_2026 | Media & Research Methods | weeks | 全是默认日期名（`27 July - 2 August` …），rawtitle 为 null | fullname 在接口里是 `Media &amp; Research Methods` |
| 4102 | MDL2002_S2_2026 | Digital Media Production | topics | `Week 1`、`Week 5: Readings`、`Week 9: Pitching` … | 两个公告论坛 + 一个普通论坛；indent 是字符串 `"0"` |
| 4103 | MDL3003_S2_2026 | Screen Cultures | weeks | 日期名和 `Week 5 – Documentary`、`Week 8`、`Week 12: Essay writing` 混着 | LTI 考试、课程考试事件、锁住的课件 |
| 4104 | MDL4004_S2_2026 | Data Storytelling | topics | `Topic 2: Cleaning data`、`Week 9 (Topic 3)` | **日历里被过滤**；enddate 为 0；get_state 的 id 是 int |
| 4090 | MDL0900_S1_2026 | Introduction to Media Studies | topics | — | 上学期的课：只在 classification=all/past 里，不在 inprogress 里 |

cm 的上下文 id = 10000 + cmid，课程上下文 = 20000 + 课程 id（pluginfile 地址里用）。

## 覆盖点 → 在哪 → 期望

期望栏说的是按 `DESIGN_MOODLE.md` 该有的结果；「现状」是 2026-09-23 用开发副本跑 `collect --touch` + `radar` 实际看到的（UrllibTransport，seed 本目录的 config，cookie 用 `mock.playwright_cookies()`）。

| 覆盖点 | 课 · cmid / 事件 id | 数据里的样子 | 期望在雷达里 |
|---|---|---|---|
| 已交且已评分的作业 | 4101 · 7003 Assignment 1: Research proposal · 事件 9001（08-28 23:59） | 作业页 `submissionstatussubmitted` + `submissiongraded` + `earlysubmission`；日历 due 事件没有 `action`；成绩页 72.50 / 0–100，权重 `90.91 %`（Calculated weight：按已出分项算的实际权重，不是大纲权重，只留在原始数据的 `calc_weight_pct`，雷达显示「—」） | 已交，不进待办 |
| 草稿没正式提交 | 4102 · 7102 Project pitch · 9102（09-25 周五 17:00） | `submissionstatusdraft`，有 editsubmission / submit 按钮；日历有 action | 区块一，未交，最急的一条（还有 2 天） |
| 没交、已过期 | 4102 · 7103 Production log · 9101（09-18 23:59） | 状态格没有 submissionstatus* 类，剩余时间行 `overdue`；日历 `overdue:true` 且有 action | 「已过期未交」 |
| 没交、还没到期 + 个人延期 | 4101 · 7005 Assignment 2: Literature review · 9004 due（10-09 23:59）+ 9005 **extension**（10-16 23:59，userid=1234） | 作业页多一行无 class 的延期行，`timeremaining` 按延期算；日历两条事件都有 action | 有效截止 10-16 23:59（原 10-09）；未交。距今天 16/23 天，14 天窗口外 |
| 线下作业（不用在线交） | 4102 · 7104 In-class presentation · 9105（10-14 18:00） | 没有 editsubmission 入口；日历 action 的 `actionable:false`；状态格文字是「不需要在线提交」 | 不能判成「没交」；以后进窗口时按未交/待确认处理 |
| 限时作业（Begin 是链接不是表单） | 4103 · 7203 Essay · 9203（10-30 23:59） | 编辑入口是 `a[href*="action=editsubmission"]`（带 begin=1），页面上没有 `input[name=action]` | 未交，10-30 |
| 做过一次还能再做的测验 | 4101 · 7004 Week 8 reading quiz · 9002 open / 9003 close（09-27 23:59） | 1 次 finished（8.00/10.00），允许 3 次，有 `quizstartbuttondiv`（Re-attempt）和 review 链接；日历 close 事件**没有** action（有 finished 尝试） | 区块一 09-27；设计说「还能再做就不算已交」→ 未交 |
| 没做过的测验 | 4102 · 7105 Weekly quiz 9 · 9103 / 9104（09-28 23:59） | 0 次尝试，有开始按钮；close 事件有 action（actionable） | 区块一，未交 |
| 做完且关了的测验（弹窗回顾） | 4103 · 7204 Practice quiz · 9201 / 9202（09-20，已过） | 回顾入口是 `form[action$="/mod/quiz/review.php"]` + `input[name=attempt]`，没有 review 链接；没有开始按钮 | 已交，不进待办 |
| 只在成绩页出现的计分项 | 4102 · 成绩项 625 Tutorial participation（没分）、627 Peer feedback（8.00/10） | 成绩页里是 `span.gradeitemheader`（没有活动链接）；日历、课程结构里都没有 | 625 进区块二，名字后标「成绩册里有，但没找到截止日期」；627 已有分，不进待办。现状：符合 |
| 成绩页隐藏项 | 4102 · 成绩项 626 | 输出一个没有单元格的空 `<tr class="cat_61">` | 不产生任何条目，也不能让解析错位 |
| 顶层分类名被老师改过 | 4102 | 分类名 `MDL2002 production marks`（不等于课程全名） | 不拿它匹配课程 |
| 成绩页没有权重列 | 4104 | thead 里没有 `column-weight` | weight_pct 为 None，不报错 |
| 只在日历里的课程考试事件 | 4103 · 事件 **8301** Mid-semester exam (in class)（10-13 10:00–12:00，timeduration 7200） | eventtype `course`，没有 modulename / instance | id `ev8301`，按 10-13 10:00 列出。现状：collect 收到了 |
| 只在日历里的站点考试事件 | 事件 **8001** Formal examination period（10-31 08:00 起 15 天） | eventtype `site`，**没有 course 键**；跨 16 个日格、跨 10 月和 11 月两次月视图 → 必须按 id 去重 | 设计要求收（站点事件也要）；不属于任何课。现状：collect 没收，待定 |
| 个人日历事件 | 事件 8401 Study group（09-24 18:00–19:00） | eventtype `user`，没有 course 键 | 不是 deadline |
| LTI 外部考试（没日期，公告里写了） | 4103 · 7202 Final exam (external tool)；公告讨论 521 | 日历里没有任何事件；成绩页有（`/mod/lti/view.php?id=7202`，0–100）；公告正文写「Monday 9 November 2026, 9:00 am」 | 区块二「Moodle 没写日期」；公告找日期的逻辑能给出 11-09 09:00 的待确认条目 |
| 日历把一门课过滤掉（兜底） | 4104 · 7302 Data report（本应 10-02 23:59）、7303 Module quiz（本应 10-05 23:59）· 事件 9301–9303 | 月视图和 timesort 都不返回 4104 的事件（`scenario.json` 的 `calendar.hidden_courses`）；日期只在作业/测验页头的本地化文字里 | 两条都照样列出，区块二「日历里没看到日期（可能被过滤）」；collect 的 errors 里点名一条「MDL4004：课里有 2 个作业/测验，但 Moodle 日历里这门课一个事件都没有…」（所以这个场景的 collect 退出码是 1，数据照常提升） |
| 带扩展名的课件名 | 4101 · 7007 `Reading list (2026).pdf`；4102 · 7106 `Lecture 1 slides.pdf`；4104 · 7304 `Course guide.docx` | cm 名字本身带扩展名；7007 的 pluginfile 地址是 `Reading%20list%20%282026%29.pdf` | 文件名 = 地址最后一段反转义 |
| 不带扩展名的课件名 | 4101 · 7002 Unit outline → `MDL1001_Unit_Outline.pdf`；7006 Week 2 lecture slides → `W2_Lecture_Slides.pptx`；4103 · 7205 第三周阅读材料 → `第三周阅读材料.pdf` | 真实文件名只能从 `/mod/resource/view.php?id=&redirect=1` 的 303 Location 拿 | filename 取 Location，判断「是不是课件」看 filename 的扩展名 |
| folder | 4102 · 7107 Week 5 readings | 3 个文件：`Smith 2019 - Media production.pdf`、`第五周阅读笔记.docx`、`shot-list-template.xlsx`；链接是 `/pluginfile.php/17107/mod_folder/content/0/<名>?forcedownload=1` | 每个文件一个 File 条目，content_id 用 pluginfile 地址 |
| 锁住的课件 / 页面 | 4103 · 7206 Week 9 screening notes（resource）；4101 · 7011 Week 3 extra reading（page） | get_state 里 `uservisible:false`、`hascmrestrictions:true`；打开 view.php 被 303 回课程页 | locked_for_user = True（「仍锁定」） |
| 公告论坛 2 条以上 | 4101 · 7001（501 置顶、502、503 带一条回复 9504）；4103 · 7201（521、522） | 页面 body class `forumtype-news`；`time[id^="time-created-"]` 是 `time-created-<讨论id>`（没有 uniqid 后缀） | 公告各 3 条 / 2 条；503 的正文取首帖 9503，不是回复 |
| 一门课两个公告论坛 | 4102 · 7101（511、512）+ 7108 Tutor announcements（513） | 两个都是 `forumtype-news` | 合并成 3 条 |
| 普通论坛不是公告 | 4102 · 7109 Q&A forum（514） | `forumtype-general`；名字接口里是 `Q&amp;A forum` | 不能当公告收 |
| 还没有公告 | 4104 · 7301 | 没有 table，只有 `div.forumnodiscuss` | 0 条，不算错误 |
| 课程页文字里的日期 | 4101 · label 7010：「mid-semester test is on Tuesday 20 October 2026」；各节 summary | `/course/view.php?id=` 的 `.summarytext`、`.activity-altcontent` | 交给公告找日期的逻辑（moodle_texts.json） |
| 周名 Week N 和日期型混合 | 4103 节 1–4、7、9、16 是日期名，5、6、8、12 是 Week 名 | get_state `rawtitle` 为 null 的节 `title` 是本地化日期区间 | 模块名照 title 显示；不从日期名里解析日期 |

公告合计 8 条（4101 三、4102 三、4103 二）。

### 日历 action 事件（timesort，从 0 起全拿）

`9101, 9102, 9104, 9004, 9105, 9005, 9203`（按 timesort）。没有 9001（已交）、9003（有 finished 尝试）、open 事件（设了关闭时间的测验 open 是 STANDARD）、4104 的事件（被过滤）。

## 文件格式（改场景看这里）

- `scenario.json`：now、时区、站点、学生、`calendar.hidden_courses`；`config` / `state` 是给 `harness.FakeHome.seed` 直接用的（`lms: "moodle"`），形状照 au_semester。
- `courses.json`：课程元数据，时间是 ISO Z。
- `courses/<id>/structure.json`：`sections`（`name` 为 null = 没命名，用默认名）和 `cms`。cm 的 `assign` / `quiz` / `resource` / `folder` / `forum` / `text` 字段给页面用；截止和开放时间一律从 `calendar_events.json` 取（作业页头的 Due、测验页头的 Opens/Closes 也是）。`ids_as`（string|int）、`indent_as`（int|string）控制 get_state 里的类型。
- `courses/<id>/grades.json`：成绩页的行，字段是页面上显示的文字（`range` 用 U+2013 的 –，渲染时写成 `&ndash;`）。
- `courses/<id>/forums.json`：cmid → 讨论列表，第一条帖是首帖，`parent` 标回复。正文里用 `{{BASE}}` 代站点根。
- `calendar_events.json`：全部日历事件。活动事件只写 `cmid` 和 `eventtype`，名字按 `{活动名} is due / opens / closes / extended due date` 生成；`user: true` = 本人的事件（userid=1234）。

fixture 里不写网址主机名、时间一律带 Z（`test_harness` 会查）。

## 假 Moodle 怎么用

```python
with mockmoodle.MockMoodle("moodle_term") as mock:      # 只绑 127.0.0.1
    mock.base_url                     # 站点根（也是 public config 的 wwwroot）
    mock.playwright_cookies()         # 直接写进 browser/canvas-cookies.json
    mock.cookie_header(); mock.sesskey; mock.logins
    mock.expire_session()             # cookie 和 sesskey 都作废
    mock.new_sesskey()                # 会话还在，sesskey 换了（测 invalidsesskey 重取）
    mock.force_status(r"grade/report/user/index\.php\?id=4102", 503)   # 按「路径?查询串」匹配
    mock.force_ajax_error("monthly_view", "nopermissions")             # 单个函数回 error:true
    mock.regrading.add(4101)          # 成绩页 200 但没有 table.user-grade（正在重算）
    mock.logged_out = "sso"           # 没登录时：login（默认，303 /login/index.php）/ sso（303 外部 IdP）/ guest（访客自动登录）
    mock.dashboard_hidden.add(4103)   # 学生在仪表盘上「从视图中移除」：all/inprogress/past/future 不列，allincludinghidden 带 hidden=true
    mock.slasharguments = 0           # pluginfile 地址写成 /pluginfile.php?file=%2F<ctx>%2F…（resource 的 303、folder 页的链接都是）
    mock.release = "4.4"              # M.cfg 没有 userId / apibase：访客只能从用户菜单的 span.login 认出来
    mock.requests(); mock.writes()    # writes()：被拒的写请求，只读工具应为空
```

- 登录：`GET /login/index.php` 直接发 `MoodleSession` cookie（无密码），303 到 `/my/`，`logins += 1`。`cookie_suffix=` 可以测 cookie 名带后缀的站点。
- 没登录打开 `/` 是 200 的站点首页，`M.cfg.userId` 为 0、sesskey 是假的；`/my/`、课程和活动页 303 到登录页。
- ajax：未登录 → `servicerequireslogin`；URL 没 sesskey → `missingparam`；sesskey 错 → `invalidsesskey`；存在但不在白名单 → `servicenotavailable`；函数名不存在 → 单个对象 `{"error":"…","errorcode":"invalidrecord",…}`；courseid 显式传 null → `generalexceptionmessage`；一批里第一个出错就停。index 不是 0..n-1 时按 PHP 输出成对象。
- 写：除两个 ajax 端点外的 POST、PUT/DELETE/PATCH、写类 ajax 函数（第三段是 add/update/delete/save/submit/view… 的），以及会改东西的 GET（登出、开始测验、论坛 `o=`、成绩页 `userview=`、作业页带 `action=`）都回 405。

## 没核实的标记（规格里没有，照 4.5 的样子写的）

课程页 `/course/view.php` 的节和活动标记、folder 页、resource 不带 redirect 的说明页、作业页的反馈表、讨论页 `discuss.php`、`core_calendar_get_action_events_by_timesort` 的返回（按源码 `events_exporter`：`{events, firstid, lastid}`，事件字段同月视图去掉 islastday / popupname / draggable）、延期事件的名字文案。解析这些时要按「取不到就降级」写。
