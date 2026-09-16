"""真课程不许被当成非课程站点跳过（S38）。

审计实测：h7 的 EDUC6010（Literacy and Numeracy）、MKTG6020（Customer Engagement）、
NURS5001（Clinical Training）、INFS5001（Library and Information Studies）全被跳过，
学生只在 doctor 输出里看到一行「跳过非课程站点 4 个」。
另外 course_code_of('31251_AUT2026') 返回 'AUT2026'，把学期当成了课程代码。
"""
import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

TOOLS = os.path.join(harness.code_dir(), "tools")


def load_tool(name):
    spec = importlib.util.spec_from_file_location("_under_test_" + name, os.path.join(TOOLS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cc = load_tool("cc_courses")


def skipped(name, code):
    return cc.looks_like_non_course(name, code) or cc.looks_like_non_course(code, code)


class RealCoursesKept(unittest.TestCase):
    def test_名字里有那几个词的真课程不许跳过(self):
        for name, code in (("Literacy and Numeracy in Schools", "EDUC6010"),
                           ("Customer Engagement", "MKTG6020"),
                           ("Clinical Training", "NURS5001"),
                           ("Library and Information Studies", "INFS5001"),
                           ("学术写作与文献素养", "CHIN5002")):
            self.assertFalse(skipped(name, code), f"{code} 是真课程，不该被跳过")

    def test_没有课程代码的站点照样跳过(self):
        for name, code in (("Library Skills Hub", "2026_LIB_SKILLS"),
                           ("BYOD test support site", "2026_BYOD"),
                           ("Sandbox for staff", "2026_SANDBOX")):
            self.assertTrue(skipped(name, code), f"{code} 不是课，应该跳过")


class CourseCode(unittest.TestCase):
    def test_全数字开头的代码取开头那串数字(self):
        self.assertEqual("31251", cc.course_code_of({"course_code": "31251_AUT2026", "id": 1}))
        self.assertEqual("31251", cc.course_code_of({"course_code": "31251_AUT2026", "id": 2}), "两门课不该互相污染")

    def test_正常代码照旧(self):
        self.assertEqual("PSYC2012", cc.course_code_of({"course_code": "PSYC2012", "id": 3}))
        self.assertEqual("EDUC6010", cc.course_code_of({"course_code": "EDUC 6010", "id": 4}))


if __name__ == "__main__":
    unittest.main()
