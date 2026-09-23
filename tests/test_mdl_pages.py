"""Moodle 页面解析（tools/mdl_pages.py）：纯函数，输入是规格里的样例页面和复查勘误后的变体。

钉住三件事：
1. 只认与语言无关的标记——把标签文字换成中文，结果不变。
2. 规格和勘误列出的每种变体都认得：限时作业的链接式编辑入口、弹窗测验的表单式回顾入口、
   成绩页的隐藏项空行 / 关掉的权重列 / 5.1 的表格 class、公告论坛的 forumtype-news 和
   time-created-<id>、没有公告时的 forumnodiscuss。
3. 认不出页面结构（登录页、错误页、成绩页重算中、课程被隐藏、别的页面）返回 None，
   不是空列表——调用方要分得清「没读懂」和「确实没有」。
课程页文字和 folder 页没有经过核实的规格，样例按 Moodle 4.x / 3.x 的常见标记写，解析器认不出就返回 None。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")
if TOOLS not in sys.path:
    sys.path.append(TOOLS)
import mdl_pages as mp  # noqa: E402

MCFG = ('<script>\n//<![CDATA[\nvar M = {}; M.yui = {};\nM.pageloadstarttime = new Date();\n'
        'M.cfg = {"wwwroot":"https:\\/\\/moodle.example.edu","apibase":"https:\\/\\/moodle.example.edu\\/r.php\\/api",'
        '"homeurl":{},"sesskey":"AbCdEf1234","sessiontimeout":"28800","usertimezone":"Australia\\/Sydney",'
        '"language":"en","courseId":42,"contextid":1234,"contextInstanceId":567,"siteId":1,"userId":501};'
        '\n//]]>\n</script>')

LOGIN_PAGE = ('<html><body id="page-login-index" class="pagelayout-login notloggedin">'
              '<form class="login-form" action="https://moodle.example.edu/login/index.php" method="post" id="login">'
              '<input type="hidden" name="logintoken" value="x"><input type="text" name="username" id="username">'
              '</form></body></html>')
FATAL_PAGE = ('<html><body id="page-grade-report-user-index" class="path-grade">'
              '<div class="box py-3 errorbox alert alert-danger" data-rel="fatalerror"><p class="errormessage">'
              'Cannot view grades.</p><p class="errorcode"><a href="https://docs.moodle.org/405/en/error/moodle/'
              'nopermissiontoviewgrades">More information about this error</a></p></div></body></html>')
OTHER_PAGE = '<html><body id="page-site-index" class="pagelayout-frontpage"><p>Welcome</p></body></html>'

# ---------------------------------------------------------------- 作业页（规格 A，M.cfg 按勘误转义斜杠）
ASSIGN_HEAD = """<html><head>%s</head>
<body id="page-mod-assign-view" class="format-topics path-mod path-mod-assign">
<span id="maincontent" tabindex="-1"></span>
<h2>Essay 1</h2>
<div class="activity-header" data-for="page-activity-header">
  <div data-region="activity-information" data-activityname="Essay 1" class="activity-information">
    <div data-region="activity-dates" class="activity-dates">
      <div><strong>Opened:</strong> Monday, 1 September 2025, 9:00 AM</div>
      <div><strong>Due:</strong> Friday, 3 October 2025, 11:59 PM</div>
    </div>
  </div>
</div>
""" % MCFG

BTN = ('<div class="singlebutton"><form method="get" action="https://moodle.example.edu/mod/assign/view.php">'
       '<input type="hidden" name="id" value="567"><input type="hidden" name="action" value="%s">'
       '<button type="submit" class="btn btn-secondary" id="single_button65f1c2a3b4d5e1">%s</button></form></div>')


def actions(*btns, v50=False):
    inner = "".join(f'<div class="col-xs-6">{b}</div>' if not v50 else f"<div>{b}</div>" for b in btns)
    row = '<div class="d-flex flex-wrap gap-2">' if v50 else '<div class="row">'
    return f'<div class="container-fluid mb-4">{row}{inner}</div></div>'


def status_table(rows, cls="generaltable table-bordered"):
    body = "".join(f'<tr class=""><th class="cell c0" style="" scope="row">{th}</th>'
                   f'<td class="{k + " " if k else ""}cell c1 lastcol" style="">{td}</td></tr>' for th, k, td in rows)
    return ('<div class="submissionstatustable"><h3>Submission status</h3><div class="box py-3 boxaligncenter '
            f'submissionsummarytable"><div class="table-responsive"><table class="{cls}">'
            f'<caption class="accesshide">Submission status</caption><tbody>{body}</tbody></table></div></div></div>')


SUBMITTED_ROWS = [("Submission status", "submissionstatussubmitted", "Submitted for grading"),
                  ("Grading status", "submissionnotgraded", "Not graded"),
                  ("Extension due date", "", "Friday, 10 October 2025, 11:59 PM"),
                  ("Time remaining", "earlysubmission", "Assignment was submitted 8 days 3 hours early"),
                  ("Last modified", "", "Thursday, 2 October 2025, 8:15 PM")]
NEW_ROWS = [("Submission status", "", "No submissions have been made yet"),
            ("Grading status", "submissionnotgraded", "Not graded"),
            ("Time remaining", "timeremaining", "10 days 4 hours remaining")]

ASSIGN_SUBMITTED = (ASSIGN_HEAD + actions(BTN % ("editsubmission", "Edit submission"),
                                          BTN % ("removesubmissionconfirm", "Remove submission"))
                    + status_table(SUBMITTED_ROWS) + "</body></html>")
ASSIGN_NEW = ASSIGN_HEAD + actions(BTN % ("editsubmission", "Add submission")) + status_table(NEW_ROWS) + "</body></html>"
# 勘误：限时作业、计时没开始时，编辑入口是链接，没有 input[name=action]
TIMELIMIT_LINK = ('<a class="btn btn-primary" href="https://moodle.example.edu/mod/assign/view.php?id=567&amp;'
                  'action=editsubmission&amp;begin=1">Begin assignment</a>')
ASSIGN_TIMELIMIT = (ASSIGN_HEAD + f'<div class="container-fluid mb-4"><div class="row"><div class="col-xs-6 me-3">'
                    f'{TIMELIMIT_LINK}</div></div></div>' + status_table(NEW_ROWS) + "</body></html>")
# 勘误：线下作业过了截止也是 overdue 类，而且没有编辑入口
ASSIGN_OFFLINE = (ASSIGN_HEAD + status_table([
    ("Submission status", "", "This assignment does not require you to submit anything online"),
    ("Grading status", "submissionnotgraded", "Not graded"),
    ("Time remaining", "overdue", "Due date has passed")]) + "</body></html>")
ASSIGN_DRAFT = (ASSIGN_HEAD + actions(BTN % ("editsubmission", "Edit submission"),
                                      BTN % ("removesubmissionconfirm", "Remove submission"),
                                      BTN % ("submit", "Submit assignment")) + status_table([
    ("Submission status", "submissionstatusdraft", "Draft (not submitted)"),
    ("Grading status", "submissionnotgraded", "Not graded"),
    ("Time remaining", "overdue", "Assignment is overdue by: 1 day"),
    ("Last modified", "", "Thursday, 2 October 2025, 8:15 PM")]) + "</body></html>")
ASSIGN_REOPENED = (ASSIGN_HEAD + actions(BTN % ("editsubmission", "Add a new attempt"),
                                         BTN % ("editprevioussubmission", "Add a new attempt based on previous submission"))
                   + status_table([("Attempt number", "", "This is attempt 2."),
                                   ("Submission status", "submissionstatusreopened", "Reopened"),
                                   ("Grading status", "submissionnotgraded", "Not graded")]) + "</body></html>")
ASSIGN_GRADED_500 = (ASSIGN_HEAD + actions(BTN % ("removesubmissionconfirm", "Remove submission"), v50=True)
                     + status_table([("Submission status", "submissionstatussubmitted", "Submitted for grading"),
                                     ("", "submissionlocked", "This assignment is not accepting submissions"),
                                     ("Grading status", "submissiongraded", "Graded"),
                                     ("Time remaining", "latesubmission", "Assignment was submitted 2 hours late")],
                                    cls="generaltable table table-striped table-bordered table-hover")
                     + "</body></html>")
# 访客自动登录后课程允许访客：200，但没有状态表
ASSIGN_NO_TABLE = ASSIGN_HEAD + '<div class="activity-description">Write 1500 words.</div></body></html>'


def to_chinese(page):
    """把本地化文字换成中文：解析结果必须不变。"""
    for en, zh in [("Submission status", "提交状态"), ("Grading status", "评分状态"), ("Not graded", "未评分"),
                   ("Submitted for grading", "已提交以待评分"), ("Time remaining", "剩余时间"),
                   ("Extension due date", "延期截止日期"), ("Last modified", "最后修改"), ("Edit submission", "编辑提交"),
                   ("Add submission", "添加提交"), ("No submissions have been made yet", "还没有提交"),
                   ("Status", "状态"), ("Started", "开始于"), ("Completed", "完成于"), ("Duration", "耗时"),
                   ("Grade", "成绩"), ("Review", "回顾"), ("Re-attempt quiz", "再次尝试"), ("Finished", "已完成"),
                   (" out of ", " 满分 ")]:
        page = page.replace(en, zh)
    return page


class AssignStatus(unittest.TestCase):
    def test_已提交未评分有延期(self):
        r = mp.assign_status(ASSIGN_SUBMITTED)
        self.assertIs(True, r["submitted"])
        self.assertIs(False, r["graded"])
        self.assertEqual("submitted", r["state"])
        self.assertIs(True, r["has_extension"], "评分行和剩余时间行之间那条无类行就是延期")
        self.assertEqual("earlysubmission", r["time_class"])
        self.assertTrue(r["can_edit"])

    def test_页面上的日期是本地化文字不取(self):
        r = mp.assign_status(ASSIGN_SUBMITTED)
        for k in ("due_at", "cutoff_at", "extension_at"):
            self.assertIsNone(r[k], k + " 只能来自日历时间戳")

    def test_换成中文结果不变(self):
        for page in (ASSIGN_SUBMITTED, ASSIGN_NEW):
            self.assertEqual(mp.assign_status(page), mp.assign_status(to_chinese(page)))

    def test_没交且有编辑按钮(self):
        r = mp.assign_status(ASSIGN_NEW)
        self.assertIs(False, r["submitted"])
        self.assertEqual("new", r["state"])
        self.assertIs(False, r["has_extension"])
        self.assertEqual("timeremaining", r["time_class"])

    def test_限时作业的编辑入口是链接(self):
        r = mp.assign_status(ASSIGN_TIMELIMIT)
        self.assertTrue(r["can_edit"], "a[href*=action=editsubmission] 也算编辑入口")
        self.assertIs(False, r["submitted"], "有编辑入口、没有状态类 → 没交，不能当成线下作业")

    def test_线下作业overdue不判没交(self):
        r = mp.assign_status(ASSIGN_OFFLINE)
        self.assertFalse(r["can_edit"])
        self.assertEqual("overdue", r["time_class"])
        self.assertIsNone(r["submitted"], "overdue 也出现在线下作业上，没编辑入口时看不出交没交")

    def test_草稿和重新打开都算没交(self):
        d = mp.assign_status(ASSIGN_DRAFT)
        self.assertEqual(("draft", False), (d["state"], d["submitted"]))
        self.assertIs(False, d["has_extension"], "最后修改那条无类行在剩余时间行后面，不是延期")
        r = mp.assign_status(ASSIGN_REOPENED)
        self.assertEqual(("reopened", False), (r["state"], r["submitted"]))
        self.assertIs(False, r["has_extension"], "延期行要有截止日，有截止日就一定有剩余时间行；没有它就没有延期")
        self.assertTrue(r["can_edit"])

    def test_已评分和5点0的表格class(self):
        r = mp.assign_status(ASSIGN_GRADED_500)
        self.assertEqual((True, True), (r["submitted"], r["graded"]))
        self.assertIs(False, r["has_extension"])
        self.assertFalse(r["can_edit"])

    def test_没有状态表是看不出不是没交(self):
        r = mp.assign_status(ASSIGN_NO_TABLE)
        self.assertIsNotNone(r, "认得是作业页")
        self.assertIsNone(r["submitted"])
        self.assertIsNone(r["graded"])

    def test_认不出的页面返回None(self):
        for page in (LOGIN_PAGE, FATAL_PAGE, OTHER_PAGE, "", b"", None):
            self.assertIsNone(mp.assign_status(page), repr(page)[:40])

    def test_字节输入也能读(self):
        self.assertIs(True, mp.assign_status(ASSIGN_SUBMITTED.encode("utf-8"))["submitted"])


# ---------------------------------------------------------------- 测验页（规格 B）
QUIZ_HEAD = """<html><head>%s</head>
<body id="page-mod-quiz-view" class="format-topics path-mod path-mod-quiz limitedwidth">
<h2>Week 5 Quiz</h2>
<div class="activity-header" data-for="page-activity-header">
  <div data-region="activity-information" data-activityname="Week 5 Quiz" class="activity-information">
    <div data-region="activity-dates" class="activity-dates">
      <div><strong>Opened:</strong> Monday, 22 September 2025, 9:00 AM</div>
      <div><strong>Closes:</strong> Sunday, 28 September 2025, 11:59 PM</div>
    </div>
  </div>
</div>
""" % MCFG
START_BTN = ('<div class="singlebutton quizstartbuttondiv"><form method="post" action="https://moodle.example.edu/mod/'
             'quiz/startattempt.php"><input type="hidden" name="cmid" value="890"><input type="hidden" name="sesskey" '
             'value="AbCdEf1234"><button type="submit" class="btn btn-primary" id="single_button65f1c2a3b4d5e3">'
             'Re-attempt quiz</button></form></div>')
START_405 = f'<div class="container-fluid tertiary-navigation"><div class="row">{START_BTN}</div></div>'
START_500 = (f'<div class="container-fluid tertiary-navigation"><div class="d-flex"><div class="navitem">{START_BTN}'
             '</div></div></div>')
INFO = ('<div class="box py-3 quizinfo"><p class="text-start">Attempts allowed: 3</p>'
        '<p class="text-start">Grading method: Highest grade</p></div>')
REVIEW_LINK = ('<a title="Review your responses to this attempt" href="https://moodle.example.edu/mod/quiz/review.php?'
               'attempt=%d&amp;cmid=890">Review</a>')
# 勘误：弹窗测验的回顾入口是 POST 表单，没有 a[href*=review.php?attempt=]
REVIEW_FORM = ('<div class="singlebutton"><form method="post" action="https://moodle.example.edu/mod/quiz/review.php">'
               '<input type="hidden" name="attempt" value="%d"><input type="hidden" name="cmid" value="890">'
               '<input type="hidden" name="sesskey" value="AbCdEf1234"><button type="submit" class="btn btn-secondary" '
               'id="single_button65f1c2a3b4d5e9">Review</button></form></div>')
GRADE_ROW = '<tr><th class="cell" scope="row">Grade</th><td class="cell"><b>8.00</b> out of 10.00 (<b>80</b>%)</td></tr>'
PENDING_ROW = '<tr><th class="cell" scope="row">Grade</th><td class="cell">Not yet graded</td></tr>'


def card(n, rows, review=""):
    trs = "".join(f'<tr><th class="cell" scope="row">{a}</th><td class="cell">{b}</td></tr>' for a, b in rows)
    return (f'<li class="col ps-0 pe-2 mb-2"><div class="card h-100"><div class="card-header py-2 border-bottom-0">'
            f'<h4 class="card-title my-0">Attempt {n}</h4></div><table class="generaltable generalbox quizreviewsummary '
            f'mb-0"><caption class="sr-only">Attempt {n} summary</caption><tbody>{trs}</tbody></table>'
            f'<div class="card-body py-2"><div>{review}</div></div></div></li>')


FIN = [("Status", "Finished"), ("Started", "Tuesday, 23 September 2025, 10:02 AM"),
       ("Completed", "Tuesday, 23 September 2025, 10:21 AM"), ("Duration", "19 mins 4 secs")]
RUNNING = [("Status", "In progress"), ("Started", "Wednesday, 24 September 2025, 9:00 AM")]


def finished_card(n, review, grade_row=GRADE_ROW):
    c = card(n, FIN, review)
    return c.replace("</tbody>", grade_row + "</tbody>")


def quiz(start, cards, feedback='<div id="feedback" class="box py-3 generalbox"><h3>Highest grade: 8.00 / 10.00.</h3></div>'):
    lst = f'<h3>Your attempts</h3><ul class="list-unstyled row row-cols-1 row-cols-md-2 g-0">{"".join(cards)}</ul>' \
        if cards else ""
    return QUIZ_HEAD + start + INFO + feedback + lst + '<div class="box py-3 quizattempt"></div></body></html>'


QUIZ_ONE_DONE = quiz(START_405, [finished_card(1, REVIEW_LINK % 77)])
QUIZ_POPUP = quiz(START_405, [finished_card(1, REVIEW_FORM % 77)])
QUIZ_RUNNING = quiz(START_405, [card(2, RUNNING), finished_card(1, REVIEW_LINK % 77)])
QUIZ_CLOSED = quiz("", [finished_card(1, '<span class="noreviewmessage">Not permitted</span>')])
QUIZ_PENDING = quiz(START_500, [finished_card(1, REVIEW_LINK % 77, PENDING_ROW)], feedback="")
QUIZ_FRESH = quiz(START_405, [], feedback="")


class QuizStatus(unittest.TestCase):
    def test_做完一次还能再做(self):
        r = mp.quiz_status(QUIZ_ONE_DONE)
        self.assertEqual(1, r["attempts_finished"])
        self.assertIs(True, r["can_attempt_again"])
        self.assertIs(False, r["in_progress"])
        self.assertIs(True, r["graded"])
        self.assertIsNone(r["open_at"])
        self.assertIsNone(r["close_at"])

    def test_换成中文结果不变(self):
        self.assertEqual(mp.quiz_status(QUIZ_ONE_DONE), mp.quiz_status(to_chinese(QUIZ_ONE_DONE)))

    def test_弹窗测验的回顾入口是表单(self):
        r = mp.quiz_status(QUIZ_POPUP)
        self.assertEqual(1, r["attempts_finished"])
        self.assertIs(False, r["in_progress"], "表单式回顾入口也算回顾入口")

    def test_弹窗表单的回顾入口不算进行中(self):
        two_rows = quiz(START_405, [card(1, RUNNING, REVIEW_FORM % 78)])
        self.assertIs(False, mp.quiz_status(two_rows)["in_progress"])
        self.assertTrue(mp._has_review(mp._parse(REVIEW_FORM % 78)))
        self.assertFalse(mp._has_review(mp._parse(REVIEW_FORM.replace('name="attempt"', 'name="x"') % 78)))

    def test_有一次进行中(self):
        r = mp.quiz_status(QUIZ_RUNNING)
        self.assertEqual((2, 1), (r["attempts"], r["attempts_finished"]))
        self.assertIs(True, r["in_progress"])

    def test_关了就不能再做(self):
        r = mp.quiz_status(QUIZ_CLOSED)
        self.assertIs(False, r["can_attempt_again"])
        self.assertEqual(1, r["attempts_finished"])

    def test_成绩行没有粗体是待评分(self):
        r = mp.quiz_status(QUIZ_PENDING)
        self.assertEqual(1, r["attempts_finished"])
        self.assertIsNone(r["graded"], "没 <b> 不算有分")
        self.assertIs(True, r["can_attempt_again"], "5.0 的按钮外层是 d-flex > navitem，也要认")

    def test_还没做过(self):
        r = mp.quiz_status(QUIZ_FRESH)
        self.assertEqual((0, 0, True, False), (r["attempts"], r["attempts_finished"], r["can_attempt_again"],
                                               r["in_progress"]))

    def test_认不出的页面返回None(self):
        for page in (LOGIN_PAGE, FATAL_PAGE, OTHER_PAGE, ASSIGN_SUBMITTED, ""):
            self.assertIsNone(mp.quiz_status(page))


# ---------------------------------------------------------------- 成绩页（规格 sample + 勘误）
GRADE_THEAD = """<thead><tr>
<th class="header column-itemname header c0" id="itemname5" style="" colspan="2" scope="col">Grade item</th>
<th class="header column-weight header c1" id="weight5" style="" scope="col">Calculated weight</th>
<th class="header column-grade header c2" id="grade5" style="" scope="col">Grade</th>
<th class="header column-range header c3" id="range5" style="" scope="col">Range</th>
<th class="header column-percentage header c4" id="percentage5" style="" scope="col">Percentage</th>
<th class="header column-feedback header c5" id="feedback5" style="" scope="col">Feedback</th>
<th class="header column-contributiontocoursetotal header c6 lastcol" id="contributiontocoursetotal5" style="" scope="col">Contribution to course total</th>
</tr></thead>"""
CAT_ROWS = """<tr class="" data-hidden="false">
<th class="level1 d1 b1b b1t category column-itemname cell c0 lastcol" style="" colspan="8" id="cat_3_5" scope="row"><div class="d-flex category-content">
    <a aria-expanded="true" role="button" data-categoryid=3 data-target=".cat_3[data-hidden='false']" class="btn btn-icon me-1 toggle-category" href="#">
        <span class="collapsed text-nowrap" title="Collapse"><i class="icon fa fa-chevron-down fa-fw" title="Collapse" role="img" aria-label="Collapse"></i></span>
    </a>
    <span>MDL9901 Media Industries</span>
</div></th>
</tr>
<tr class="cat_3 spacer" data-hidden="false">
<td class="level1 d1 b1t b2b b1l cell c0 lastcol" style="" rowspan="5"></td>
</tr>"""


def item_row(itemid, mod, cmid, name, weight, grade, rng, pct="-", contrib="0.00 %", grade_cls="", last=""):
    icon = f'<img class="icon itemicon" src="https://moodle.example.edu/theme/image.php/boost/{mod}/1727000000/monologo" alt="{mod}" />'
    title = (f'<a title="{mod} activity {name}" class="gradeitemheader " href="https://moodle.example.edu/mod/{mod}/'
             f'view.php?id={cmid}">{name}</a>') if cmid else \
        f'<span class="gradeitemheader " title="{name}" tabindex="0">{name}</span>'
    h = f"cat_3_5 row_{itemid}_5"
    return (f'<tr class="cat_3{last}" data-hidden="false">\n'
            f'<th class="level2 item b1b column-itemname cell c0" style="" colspan="1" id="row_{itemid}_5" scope="row">'
            f'<div class="item d-flex align-items-center"><div class="me-1">{icon}</div><div><span class="d-block '
            f'text-uppercase small " title="{mod}">{mod}</span><div class="rowtitle">{title}</div></div></div></th>\n'
            f'<td class="level2 item b1b itemcenter  column-weight cell c1" headers="{h} weight5" style="">{weight}</td>\n'
            f'<td class="level2 item b1b itemcenter {grade_cls}  column-grade cell c2" headers="{h} grade5" style="">{grade}</td>\n'
            f'<td class="level2 item b1b itemcenter  column-range cell c3" headers="{h} range5" style="">{rng}</td>\n'
            f'<td class="level2 item b1b itemcenter  column-percentage cell c4" headers="{h} percentage5" style="">{pct}</td>\n'
            f'<td class="level2 item b1b feedbacktext column-feedback cell c5" headers="{h} feedback5" style="">&nbsp;</td>\n'
            f'<td class="level2 item b1b itemcenter  column-contributiontocoursetotal cell c6 lastcol" headers="{h} '
            f'contributiontocoursetotal5" style="">{contrib}</td>\n</tr>\n')


COURSE_TOTAL = """<tr class="cat_3%s" data-hidden="false">
<th class="level1 d1 baggt b2b column-itemname cell c0" style="" colspan="1" id="row_20_5" scope="row"><div class="courseitem d-flex align-items-center"><div class="me-1"><i class="icon fa fa-calculator fa-fw icon itemicon" title="Natural" role="img" aria-label="Natural"></i></div><div><span class="d-block text-uppercase small " title="Aggregation">Aggregation</span><div class="rowtitle"><span class="gradeitemheader " title="Course total" tabindex="0">Course total</span></div></div></div></th>
<td class="level1 d1 baggt b2b itemcenter  column-weight cell c1" headers="cat_3_5 row_20_5 weight5" style="">-</td>
<td class="level1 d1 baggt b2b itemcenter   column-grade cell c2" headers="cat_3_5 row_20_5 grade5" style="">152.50</td>
<td class="level1 d1 baggt b2b itemcenter  column-range cell c3" headers="cat_3_5 row_20_5 range5" style="">0&ndash;200</td>
<td class="level1 d1 baggt b2b itemcenter  column-percentage cell c4" headers="cat_3_5 row_20_5 percentage5" style="">76.25 %%</td>
<td class="level1 d1 baggt b2b feedbacktext column-feedback cell c5" headers="cat_3_5 row_20_5 feedback5" style="">&nbsp;</td>
<td class="level1 d1 baggt b2b itemcenter  column-contributiontocoursetotal cell c6 lastcol" headers="cat_3_5 row_20_5 contributiontocoursetotal5" style="">-</td>
</tr>
"""
A1 = item_row(21, "assign", 101, "A1 Essay", "50.00 %", "72.50", "0&ndash;100", "72.50 %", "36.25 %")
A2 = item_row(22, "assign", 102, "A2 Report", "50.00 %", "80.00", "0&ndash;100", "80.00 %", "40.00 %")
Q1 = item_row(23, "quiz", 103, "Weekly Quiz 1", "0.00 %<br>( Empty )", "-", "0&ndash;50")


def grade_page(rows, table_cls="generaltable boxaligncenter user-grade", thead=GRADE_THEAD):
    return (f'<html><body id="page-grade-report-user-index" class="path-grade path-grade-report">'
            f'<div class="user-report-container" id="user-report-5"><div class="table-responsive">'
            f'<table class="{table_cls}">{thead}<tbody>{CAT_ROWS}{rows}</tbody></table></div></div></body></html>')


GRADES = grade_page(A1 + A2 + Q1 + COURSE_TOTAL % " lastrow")


def drop_weight(page):
    """课程关掉权重列：表头和每行的 column-weight 都没有。"""
    import re
    page = re.sub(r'<th class="header column-weight[^>]*>[^<]*</th>', "", page)
    return re.sub(r'<td class="[^"]*column-weight[^"]*"[^>]*>.*?</td>', "", page)


class GradeItems(unittest.TestCase):
    def test_规格样例(self):
        items = mp.grade_items(GRADES)
        self.assertEqual(["A1 Essay", "A2 Report", "Weekly Quiz 1", "Course total"], [i["name"] for i in items])
        a1 = items[0]
        self.assertEqual((101, "assign", 50.0, 100.0, "72.50", False),
                         (a1["cmid"], a1["module"], a1["weight_pct"], a1["range_max"], a1["grade"], a1["is_category"]))
        self.assertEqual(21, a1["item_id"])
        q = items[2]
        self.assertEqual(("quiz", 103, 50.0, None), (q["module"], q["cmid"], q["range_max"], q["grade"]))
        self.assertIsNone(q["weight_pct"], "0.00 % 带 ( Empty ) 是没算进去，不能报成 0%")
        total = items[3]
        self.assertTrue(total["is_category"])
        self.assertEqual((None, None, None, 200.0), (total["cmid"], total["module"], total["weight_pct"], total["range_max"]))

    def test_换成中文结果不变(self):
        zh = GRADES.replace("Calculated weight", "计算后的权重").replace("( Empty )", "（空）") \
            .replace("Course total", "课程总分").replace("Assignment", "作业")
        items = mp.grade_items(zh)
        self.assertEqual([50.0, 50.0, None, None], [i["weight_pct"] for i in items])
        self.assertEqual([101, 102, 103, None], [i["cmid"] for i in items])

    def test_隐藏项输出空行而且可能带lastrow(self):
        page = grade_page(A1 + '<tr class="cat_3" data-hidden="false"></tr>\n' + A2 + COURSE_TOTAL % ""
                          + '<tr class="cat_3 lastrow" data-hidden="false"></tr>\n')
        items = mp.grade_items(page)
        self.assertEqual(["A1 Essay", "A2 Report", "Course total"], [i["name"] for i in items])
        self.assertTrue(items[-1]["is_category"], "最后一行是空行，课程总分照样认出来")

    def test_权重列被关掉(self):
        items = mp.grade_items(drop_weight(GRADES))
        self.assertEqual(4, len(items))
        self.assertEqual([None] * 4, [i["weight_pct"] for i in items])
        self.assertEqual([100.0, 100.0, 50.0, 200.0], [i["range_max"] for i in items], "按 class 取列，不按列序号")

    def test_5点1的表格class(self):
        items = mp.grade_items(grade_page(A1 + COURSE_TOTAL % " lastrow", table_cls="table generaltable user-grade"))
        self.assertEqual(["A1 Essay", "Course total"], [i["name"] for i in items])

    def test_没出分权重是横杠(self):
        row = item_row(24, "assign", 104, "A3 Final", "-", "-", "0&ndash;100")
        it = mp.grade_items(grade_page(row + COURSE_TOTAL % " lastrow"))[0]
        self.assertEqual((None, None, 100.0), (it["weight_pct"], it["grade"], it["range_max"]))

    def test_量表文本型和逗号小数(self):
        rows = (item_row(31, "forum", 201, "Participation", "10,00 %", "Pass", "Fail&ndash;Pass")
                + item_row(32, "assign", 202, "Reflection", "-", "", "&ndash;")
                + item_row(33, "assign", 203, "Lab", "25,50 %", "7,5", "0&ndash;12,5"))
        items = mp.grade_items(grade_page(rows))
        self.assertEqual((10.0, None, "Pass"), (items[0]["weight_pct"], items[0]["range_max"], items[0]["grade"]))
        self.assertIsNone(items[1]["range_max"], "文本型成绩项的 range 两边都是空的")
        self.assertEqual((25.5, 12.5, "7,5"), (items[2]["weight_pct"], items[2]["range_max"], items[2]["grade"]))

    def test_成绩格出错或只给提交时间(self):
        rows = (item_row(41, "assign", 301, "Err", "-", "Error", "0&ndash;100", grade_cls="gradingerror")
                + item_row(42, "assign", 302, "Hidden", "-", "Submitted on Friday, 3 October 2025",
                           "0&ndash;100", grade_cls="datesubmitted"))
        e, h = mp.grade_items(grade_page(rows))
        self.assertEqual((None, "error"), (e["grade"], e["grade_flag"]))
        self.assertEqual((None, "submitted"), (h["grade"], h["grade_flag"]))
        self.assertIsNone(mp.grade_items(GRADES)[0]["grade_flag"])

    def test_手工项没有cmid(self):
        row = item_row(51, "manual", None, "Participation mark", "5.00 %", "4.00", "0&ndash;5")
        it = mp.grade_items(grade_page(row))[0]
        self.assertEqual(("Participation mark", None, None, 5.0), (it["name"], it["cmid"], it["module"], it["weight_pct"]))
        self.assertFalse(it["is_category"])

    def test_课程里没有成绩项只剩课程总分(self):
        items = mp.grade_items(grade_page(COURSE_TOTAL % " lastrow"))
        self.assertEqual(1, len(items))
        self.assertTrue(items[0]["is_category"])

    def test_重算中和课程被隐藏返回None(self):
        recalc = ('<html><body id="page-grade-report-user-index" class="path-grade"><h2>Recalculating grades</h2>'
                  '<div class="singlebutton"><form method="get" action="https://moodle.example.edu/grade/report/user/'
                  'index.php"><button type="submit">Continue</button></form></div></body></html>')
        task = ('<html><body id="page-grade-report-user-index" class="path-grade"><div data-region="task-indicator">'
                '<div class="progress"></div></div></body></html>')
        hidden = ('<html><body id="page-grade-report-user-index" class="path-grade"><div class="box generalbox">'
                  '<p>This course is currently unavailable to students</p></div></body></html>')
        for page in (recalc, task, hidden, FATAL_PAGE, LOGIN_PAGE, OTHER_PAGE, ""):
            self.assertIsNone(mp.grade_items(page), "没有 table.user-grade 是没读到，不是没有计分项")


# ---------------------------------------------------------------- 公告论坛（规格 sample，time id 按勘误去掉 uniqid）
def disc_row(did, title, ts, text=None, extra=""):
    return f"""<tr class="discussion subscribed{extra}" data-region="discussion-list-item" data-discussionid="{did}" data-forumid="">
  <td class="p-0 text-center align-middle icon-no-margin" style="width: 1px;"></td>
  <th scope="row" class="topic p-0 align-middle"><div class="p-3 ps-0"><div class="d-flex">
    <a class="w-100 h-100 d-block" href="https://moodle.example.edu/mod/forum/discuss.php?d={did}" title="{title}" aria-label="{title}">
      {text or title}
    </a></div>
    <div><span class="badge bg-danger text-white rounded" data-region="locked-label" hidden>Locked</span></div></div></th>
  <td class="author align-middle fit-content limit-width px-3"><div class="d-flex">
    <div class="align-middle p-0"><img class="rounded-circle userpicture" src="https://moodle.example.edu/pluginfile.php/2345/user/icon/boost/f1?rev=12345" alt="Picture of Dr Jane Smith"></div>
    <div class="author-info align-middle">
      <div class="mb-1 line-height-3 text-truncate">Dr Jane Smith</div>
      <div class="line-height-3"><time id="time-created-{did}" class="" datetime="" data-timestamp="{ts}" data-datetimeformat="%Y-%m-%dT%H:%M%z">23 Sep 2026</time></div>
    </div></div></td>
  <td class="text-start align-middle fit-content limit-width px-3"><div class="d-flex"><div class="author-info align-middle">
    <div class="mb-1 line-height-3 text-truncate">Tutor Bob</div>
    <div class="line-height-3"><a href="https://moodle.example.edu/mod/forum/discuss.php?d={did}&parent=9004" title="Wed, 23 Sep 2026, 5:40 PM">
      <time id="time-modified-{did}" class="" datetime="" data-timestamp="1790156400" data-datetimeformat="%Y-%m-%dT%H:%M%z">23 Sep 2026</time></a></div>
  </div></div></td>
  <td class="p-0 text-center align-middle fit-content px-2"><span>1</span></td>
</tr>"""


def forum_page(inner, ftype="news", v50=False):
    wrap = ('<div class="table-responsive">%s</div>' if v50 else
            '<div class="position-relative"><div class="no-overflow">%s</div></div>')
    cap = "visually-hidden" if v50 else "sr-only"
    table = (f'<table class="table discussion-list generaltable"><caption class="{cap}">Showing 2 of 2 discussions'
             f'</caption><thead><tr><th scope="col">Discussion</th></tr></thead><tbody>{inner}</tbody></table>')
    body = wrap % table if inner is not None else \
        '<div class="forumnodiscuss alert alert-info">(No announcements have been posted yet.)</div>'
    return (f'<html><body id="page-mod-forum-view" class="format-topics path-mod path-mod-forum course-42 cmid-77 '
            f'forumtype-{ftype}"><div id="discussion-list-68f1a2b3c4d5e1" data-contextid="305" data-cmid="77" '
            f'data-name="Announcements" data-group=""><div class="py-3"></div>{body}</div></body></html>')


LONG = "Week 8 lecture moved to Thursday &amp; room change " + "x" * 80
NEWS = forum_page(disc_row(501, LONG, 1790154000, text="Week 8 lecture moved to Thursday &amp; room ch...",
                           extra=" hasunread") + disc_row(498, "Assignment 2 brief released", 1789549200))


class ForumDiscussions(unittest.TestCase):
    def test_讨论列表(self):
        ds = mp.forum_discussions(NEWS)
        self.assertEqual([501, 498], [d["id"] for d in ds])
        self.assertEqual("Week 8 lecture moved to Thursday & room change " + "x" * 80, ds[0]["subject"],
                         "标题取 title 属性（完整、反转义），不取截断的链接文字")
        self.assertEqual("2026-09-23T09:00:00Z", ds[0]["time"], "time-created-<id> 的 data-timestamp，转 ISO UTC")
        self.assertEqual("2026-09-16T09:00:00Z", ds[1]["time"])
        self.assertEqual("Dr Jane Smith", ds[0]["author"], "首帖作者，不是最后回复的人")

    def test_旧样例带uniqid的time也认(self):
        page = NEWS.replace('id="time-created-501"', 'id="time-created-50168f1a2b3c4d5e2"')
        self.assertEqual("2026-09-23T09:00:00Z", mp.forum_discussions(page)[0]["time"])

    def test_没有时间标记就是None(self):
        page = NEWS.replace('id="time-created-498"', 'id="something-else"')
        self.assertIsNone(mp.forum_discussions(page)[1]["time"])

    def test_5点0的外层和caption(self):
        page = forum_page(disc_row(498, "Assignment 2 brief released", 1789549200), v50=True)
        self.assertEqual([498], [d["id"] for d in mp.forum_discussions(page)])

    def test_还没有公告是空列表(self):
        self.assertEqual([], mp.forum_discussions(forum_page(None)))
        zh = forum_page(None).replace("(No announcements have been posted yet.)", "（还没有公告）")
        self.assertEqual([], mp.forum_discussions(zh), "只认 div.forumnodiscuss，不认文字")

    def test_公告论坛看body的forumtype(self):
        self.assertEqual("news", mp.forum_type(NEWS))
        self.assertEqual("general", mp.forum_type(forum_page(None, ftype="general")))
        self.assertIsNone(mp.forum_type(OTHER_PAGE))
        self.assertIsNone(mp.forum_type(""))

    def test_认不出的页面返回None(self):
        for page in (LOGIN_PAGE, FATAL_PAGE, OTHER_PAGE, ASSIGN_SUBMITTED, ""):
            self.assertIsNone(mp.forum_discussions(page))


# ---------------------------------------------------------------- 课程页文字（无核实规格：按 4.x / 3.x 常见标记）
COURSE_4X = """<html><body id="page-course-view-topics" class="format-topics path-course path-course-view">
<ul class="topics">
<li id="section-0" class="section course-section main clearfix" data-sectionid="0" data-for="section" data-id="900" data-number="0">
  <div class="course-section-header d-flex" data-for="section_title"><h3 class="sectionname"><a href="#">General</a></h3></div>
  <div class="content course-content-item-content">
    <div class="my-3" data-for="sectioninfo"><div class="summarytext"><div class="no-overflow">
      <p>Welcome to MDL9901.</p><p>The final exam is on <strong>3 November 2026, 9:00 am</strong>.</p>
    </div></div></div>
    <ul class="section m-0 p-0 img-text d-block" data-for="cmlist">
      <li class="activity activity-wrapper label modtype_label" id="module-55" data-for="cmitem" data-id="55">
        <div class="activity-item"><div class="activity-altcontent d-flex text-break">
          <div class="no-overflow"><p>Week 4 quiz opens 22 September.</p><span class="sr-only">Mark as done</span></div>
        </div></div>
      </li>
      <li class="activity activity-wrapper assign modtype_assign" id="module-101" data-for="cmitem" data-id="101">
        <div class="activity-item"><div class="activity-name-area"><a href="https://moodle.example.edu/mod/assign/view.php?id=101">A1 Essay</a></div>
        <div class="activity-altcontent activity-description"><div class="no-overflow"><p>Submit via Turnitin.</p></div></div></div>
      </li>
    </ul>
  </div>
</li>
<li id="section-1" class="section course-section main clearfix" data-for="section" data-id="901" data-number="1">
  <div class="course-section-header d-flex" data-for="section_title"><h3 class="sectionname">Week 1 (22 July - 28 July)</h3></div>
  <div class="content"><ul class="section" data-for="cmlist"></ul></div>
</li>
</ul>
<script>var x = "summarytext";</script>
</body></html>"""
COURSE_3X = """<html><body id="page-course-view-weeks" class="format-weeks path-course path-course-view">
<ul class="weeks"><li id="section-0" class="section main clearfix" role="region">
<div class="content"><h3 class="sectionname">General</h3>
<div class="summary"><div class="no-overflow"><p>Exam: 3 November 2026</p></div></div>
<ul class="section img-text"><li class="activity label modtype_label" id="module-55"><div><div class="mod-indent-outer">
<div class="contentwithoutlink "><div class="no-overflow"><p>Lab moved to Friday 9 October.</p></div></div>
</div></div></li></ul></div></li></ul>
<div class="summary">Not a section summary</div>
</body></html>"""


class CourseTexts(unittest.TestCase):
    def test_4点x分节说明和标签(self):
        texts = mp.course_texts(COURSE_4X)
        self.assertEqual(["Welcome to MDL9901.\nThe final exam is on 3 November 2026, 9:00 am.",
                          "Week 4 quiz opens 22 September.", "Submit via Turnitin."], texts,
                         "分节标题不收（周次日期不是 deadline）；读屏文字、脚本里的字不收；嵌套的不重复")

    def test_3点x的summary和contentwithoutlink(self):
        self.assertEqual(["Exam: 3 November 2026", "Lab moved to Friday 9 October."], mp.course_texts(COURSE_3X),
                         "分节外面的 div.summary 不算")

    def test_课程页没有文字是空列表(self):
        page = COURSE_4X.split("<ul class=\"topics\">")[0] + '<ul class="topics"><li id="section-0" class="section" ' \
            'data-for="section"><div class="content"></div></li></ul></body></html>'
        self.assertEqual([], mp.course_texts(page))

    def test_认不出的页面返回None(self):
        for page in (LOGIN_PAGE, FATAL_PAGE, OTHER_PAGE, ASSIGN_SUBMITTED, ""):
            self.assertIsNone(mp.course_texts(page))


# ---------------------------------------------------------------- folder（无核实规格：按 4.x 常见标记）
def fp(href, name=None):
    span = f'<span class="fp-filename">{name}</span>' if name is not None else ""
    return (f'<li><span class="fp-filename-icon"><a href="{href}"><span class="fp-icon"><img class="icon" alt="" '
            f'src="https://moodle.example.edu/theme/image.php/boost/core/1/f/pdf"></span>{span}</a></span></li>')


BASE = "https://moodle.example.edu/pluginfile.php/310/mod_folder/content/0/"
FOLDER = f"""<html><body id="page-mod-folder-view" class="format-topics path-mod path-mod-folder">
<div class="box generalbox foldertree py-3"><div id="folder_tree0" class="filemanager"><ul><li>
<div class="fp-filename-icon"><span class="fp-icon"></span><span class="fp-filename"></span></div><ul>
{fp(BASE + "Week%201%20slides.pdf?forcedownload=1", "Week 1 slides.pdf")}
<li><span class="fp-filename-icon"><span class="fp-icon"></span><span class="fp-filename">Readings</span></span><ul>
{fp(BASE + "Readings/Chapter%202.docx?forcedownload=1")}
</ul></li>
{fp(BASE + "Week%201%20slides.pdf?forcedownload=1", "Week 1 slides.pdf")}
</ul></li></ul></div></div>
<div class="singlebutton"><form method="post" action="https://moodle.example.edu/mod/folder/download_folder.php">
<button type="submit">Download folder</button></form></div>
<a href="https://moodle.example.edu/pluginfile.php/305/mod_forum/post/9001/room-map.png">not a folder file</a>
</body></html>"""


class FolderFiles(unittest.TestCase):
    def test_文件名和地址(self):
        files = mp.folder_files(FOLDER)
        self.assertEqual([{"name": "Week 1 slides.pdf", "url": BASE + "Week%201%20slides.pdf?forcedownload=1"},
                          {"name": "Chapter 2.docx", "url": BASE + "Readings/Chapter%202.docx?forcedownload=1"}], files,
                         "没有 fp-filename 时取地址最后一段并解码；同一地址只列一次；别的 pluginfile 不算")

    def test_slasharguments关掉的地址(self):
        href = ("https://moodle.example.edu/pluginfile.php?file=%2F310%2Fmod_folder%2Fcontent%2F0%2Fnotes.pdf"
                "&amp;forcedownload=1")
        files = mp.folder_files(FOLDER.replace(fp(BASE + "Readings/Chapter%202.docx?forcedownload=1"), fp(href)))
        self.assertEqual("notes.pdf", files[1]["name"])
        self.assertTrue(files[1]["url"].endswith("&forcedownload=1"), "实体反转义")

    def test_空folder是空列表(self):
        empty = ('<html><body id="page-mod-folder-view" class="path-mod-folder"><div class="box generalbox foldertree">'
                 '<div id="folder_tree0" class="filemanager"></div></div></body></html>')
        self.assertEqual([], mp.folder_files(empty))

    def test_认不出的页面返回None(self):
        for page in (LOGIN_PAGE, FATAL_PAGE, OTHER_PAGE, ASSIGN_SUBMITTED, ""):
            self.assertIsNone(mp.folder_files(page))


# ---------------------------------------------------------------- M.cfg
class MCfg(unittest.TestCase):
    def test_按JSON解析斜杠转义(self):
        cfg = mp.m_cfg(ASSIGN_SUBMITTED)
        self.assertEqual("https://moodle.example.edu", cfg["wwwroot"])
        self.assertEqual("AbCdEf1234", cfg["sesskey"])
        self.assertEqual(501, cfg["userId"])
        self.assertEqual("Australia/Sydney", cfg["usertimezone"])
        self.assertEqual({}, cfg["homeurl"])

    def test_字符串里有分号和花括号(self):
        page = '<script>M.cfg = {"wwwroot":"https:\\/\\/m.example.edu\\/x;y","theme":"a}b","sesskey":"k","userId":7};</script>'
        self.assertEqual(("https://m.example.edu/x;y", "a}b", 7), (lambda c: (c["wwwroot"], c["theme"], c["userId"]))(
            mp.m_cfg(page)))

    def test_没有或坏了返回None(self):
        for page in (OTHER_PAGE, "", None, b"", '<script>M.cfg = {"sesskey": </script>', "M.cfg = [1,2];"):
            self.assertIsNone(mp.m_cfg(page), repr(page)[:40])

    def test_坏的一段后面还有好的(self):
        page = '<script>M.cfg = {broken};</script><script>M.cfg = {"sesskey":"ok"};</script>'
        self.assertEqual({"sesskey": "ok"}, mp.m_cfg(page))


class Robustness(unittest.TestCase):
    def test_残缺HTML不抛异常(self):
        junk = ['<table class="user-grade"><tr><th id="row_1_2"><div class="item"><div class="rowtitle">X',
                "<body class='path-mod-assign' id='page-mod-assign-view'><div class='submissionstatustable'><table><tr><td",
                "<" * 50 + "div" * 1000, "<div>" * 3000 + "deep"]
        for page in junk:
            for fn in (mp.assign_status, mp.quiz_status, mp.grade_items, mp.forum_discussions, mp.course_texts,
                       mp.folder_files, mp.m_cfg, mp.forum_type):
                fn(page)  # 不抛就行
        self.assertEqual("X", mp.grade_items(junk[0])[0]["name"])


if __name__ == "__main__":
    unittest.main()
