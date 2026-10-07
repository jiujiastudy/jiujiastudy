# Moodle 上要读什么（给 AI）

各学校的 Moodle 主题、版本、插件都不一样，长相差很多。脚本只做各家都一样的那部分：课程、作业测验、日历、成绩项、课件，走 Moodle 自带的数据接口。认不出来的页面不猜，交给你：用 `browse 网址 --course 课` 读整页文字，自己找。下面的网址格式各家都一样，只是页面长得不同。

## 在哪读

- 课程首页 `/course/view.php?id=<课程id>`：每一节的标题，像「Week 3」或「9 March – 15 March」这种日期段；节里的说明和 Label 文字；每个活动的链接。折叠着的节 browse 也会读进来。新版 Moodle 的节可能单独成页（`/course/section.php?id=`），要一节一节读。
- 作业 `/mod/assign/view.php?id=<活动id>`，要读这几样：
  - 页头的日期：Opened、Due、Cut-off，是本地化文字；
  - 提交状态表：Submission status、Time remaining；
  - 说明全文和附件；
  - 评分标准（Rubric / Marking guide）：每一级的完整描述都要，不能只抄标题。
- 测验 `/mod/quiz/view.php?id=`：Opens、Closes、Time limit、Attempts allowed、Grading method，以及已经做过的次数。
- 互评 `/mod/workshop/view.php?id=`：各阶段的截止，提交一个、互评一个。
- 公告论坛（Announcements / News forum）和课程论坛 `/mod/forum/view.php?id=`、`/mod/forum/discuss.php?d=`：老师贴的日期、改期、考试安排。计分论坛自己也有 Due。
- 成绩页 `/grade/report/user/index.php?id=<课程id>`：每项的 Weight、Calculated weight、Range、分数和 Feedback。成绩页没对学生开放就跳过，这不是退课。
- Page / Book / Folder / URL：
  - 课程说明、每周阅读、评估要求常写在这里；
  - Book 要每一章都读；
  - URL 跳到外部平台的，跟着读过去（Padlet、Google 文档……，见 learn.md）；
  - 课件文件走 `collect --materials`。
- 外部工具 `/mod/lti/view.php?id=`：用登录过的浏览器打开就会自己启动，像 Zoom、录播（Echo360 / Panopto / Kaltura）、Turnitin、阅读清单、Ed、Gradescope。
- 日历 `/calendar/view.php?view=upcoming`：日期对不上的时候拿来对一下。
- 课程说明：Moodle 没有 Canvas 那种 Syllabus 页。找课程首页顶上的 Course outline / Unit guide / Course profile / Assessment guide 链接，或学校公开的课程手册页，用 `outline 课 --url 网址` 读。

## 照 Canvas 上的经验

- 列表要全。每个作业的要求要从这些地方都找一遍：作业页说明和附件、评分标准全文、课程首页和节说明里提到它的、公告、课程说明的评估表、论坛 FAQ。说法打架时以 Moodle 作业页为准：页头日期优先，其次说明里写的，再次公告，最后课程说明。打架的地方写出来。
- 读到的截止日期，记之前先核对星期几和年份。老公告常是往年模板，比如「Sunday 3 November」在 2026 年是周二。核对完再 `record deadline "事项" --course 课 --due 日期 --source "Moodle 作业页（AI 读到的）"`，脚本会和 Moodle 上同一个作业再对一遍。
- 每个班各一个的东西（论坛、Padlet、Zoom），只读学生自己班或组的。
- 页面认不出来（学校的主题不一样），别猜，读整页文字自己找。读不到就记成这次没读到，跟学生只说情况。
- 被带去学校登录页：先后台重进；重进没成，再按 setup.md 跑 `login`，让学生自己登。碰到人机验证就停，不绕。
- 不叫学生去改设置，比如打开日历里的「课程事件」，也不叫学生自己去查。日期没读到，就是 AI 去读作业页。
