"""/jj-update：GitHub 上有新版就换上，几份一起换；新的 /jj 口令装上、下架的删掉；出错就保持旧版（10-07 发起人：「我后面会总更新一些新的 skill 进入救驾，所以用户需要这么一个」）。

对着本机假的 GitHub（releases/latest + 压缩包）和一个假的家目录跑：
- 有新版：.claude 和 .agents 两份都换上，旧版打成压缩包放在「文档/救驾备份」（不在 skills 里）；
  新版里没有的旧模块删掉，.git 和别的顶层文件不动；新口令装上、下架的口令删掉，口令里写的版本是新的；
- 已经是最新、线上更旧：不动；只看（--check）：不动；
- 压缩包不对（不是救驾、版本对不上、路径往外跳）、连不上：不动，旧版照常；换到一半出错：用备份换回旧版。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

CODE = harness.code_dir()
sys.path.insert(0, os.path.join(CODE, "tools"))
import cc_install  # noqa: E402
import cc_update  # noqa: E402

TREE = ("SKILL.md", "tools", "references", "skills", "agents", "assets")
NOTES = "- 新口令 /jj-newthing：测试用的新功能\n- 周报每次都重新核对"


def make_tree(dst, version, extra=None):
    """一份救驾（只要宿主要的那些文件），版本改成 version。"""
    os.makedirs(dst, exist_ok=True)
    for name in TREE:
        src = os.path.join(CODE, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name), ignore=shutil.ignore_patterns("__pycache__"))
        elif os.path.isfile(src):
            shutil.copyfile(src, os.path.join(dst, name))
    brand = os.path.join(dst, "tools", "brand.py")
    with open(brand, encoding="utf-8") as f:
        text = f.read()
    import re
    text = re.sub(r'^VERSION = "[\d.]+"', f'VERSION = "{version}"', text, flags=re.M)
    with open(brand, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    for rel, body in (extra or {}).items():
        p = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
    return dst


def zip_of(root, prefix="jiujiastudy-jiujiastudy-abc1234", extra=None):
    path = root + ".zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for r, dirs, files in os.walk(root):
            for f in files:
                full = os.path.join(r, f)
                z.write(full, prefix + "/" + os.path.relpath(full, root).replace(os.sep, "/"))
        for name, body in (extra or {}).items():
            z.writestr(name, body)
    with open(path, "rb") as f:
        return f.read()


class FakeGitHub:
    def __init__(self):
        self.release, self.blob = None, b""
        mock = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path == "/repos/jiujiastudy/jiujiastudy/releases/latest" and mock.release:
                    body, ctype = json.dumps(mock.release).encode("utf-8"), "application/json"
                elif self.path == "/zip":
                    body, ctype = mock.blob, "application/zip"
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def publish(self, tag, blob):
        self.release = {"tag_name": tag, "name": tag, "body": NOTES, "zipball_url": f"{self.base}/zip"}
        self.blob = blob

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Update(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gh = FakeGitHub()
        cls.store = tempfile.mkdtemp(prefix="stc-upd-src-")
        newthing = "---\nname: jj-newthing\ndescription: 测试用的新功能\ndisable-model-invocation: true\n---\n\n救驾主文件夹：x   ← 安装脚本写入，不手改\n\n版本 <和主文件夹一致>\n"
        cls.good = zip_of(make_tree(os.path.join(cls.store, "v999"), "9.9.9", {"skills/jj-newthing/SKILL.md": newthing}))
        cls.mismatch = zip_of(make_tree(os.path.join(cls.store, "v998"), "9.9.8"))
        os.makedirs(os.path.join(cls.store, "junk"))
        cls.junk = zip_of(os.path.join(cls.store, "junk"), extra={"x/readme.txt": "not a skill"})
        cls.evil = zip_of(make_tree(os.path.join(cls.store, "evil"), "9.9.9"), extra={"../evil.txt": "x"})

    @classmethod
    def tearDownClass(cls):
        cls.gh.stop()
        shutil.rmtree(cls.store, ignore_errors=True)

    def setUp(self):
        self.old_env = os.environ.get("JIUJIASTUDY_UPDATE_API")
        os.environ["JIUJIASTUDY_UPDATE_API"] = self.gh.base
        self.home = tempfile.mkdtemp(prefix="stc-upd-home-")
        os.makedirs(os.path.join(self.home, "Documents"))
        self.claude = make_tree(os.path.join(self.home, ".claude", "skills", "jiujiastudy"), "0.3.0",
                                {"tools/cc_old.py": "# 老版本才有的模块\n", ".git/HEAD": "ref: refs/heads/main\n", "我的笔记.txt": "别删\n"})
        self.agents = make_tree(os.path.join(self.home, ".agents", "skills", "jiujiastudy"), "0.1.0")
        stale = os.path.join(self.home, ".claude", "skills", "jj-check")
        os.makedirs(stale)
        with open(os.path.join(stale, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(f"---\nname: jj-check\n---\n\n救驾主文件夹：{self.claude}   ← 安装脚本写入，不手改\n\n版本 0.2.2\n")

    def tearDown(self):
        if self.old_env is None:
            os.environ.pop("JIUJIASTUDY_UPDATE_API", None)
        else:
            os.environ["JIUJIASTUDY_UPDATE_API"] = self.old_env
        shutil.rmtree(self.home, ignore_errors=True)

    def ver(self, d):
        return cc_install._version_of(d)

    def backups(self):
        d = cc_update.backup_dir(self.home)
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def test_有新版_几份一起换上_口令跟着新版(self):
        self.gh.publish("v9.9.9", self.good)
        r = cc_update.update(home=self.home)
        self.assertEqual("updated", r["state"], r)
        self.assertEqual(("0.3.0", "9.9.9"), (r["from"], r["to"]))
        self.assertEqual(NOTES, r["notes"])
        self.assertEqual(((9, 9, 9), (9, 9, 9)), (self.ver(self.claude), self.ver(self.agents)))
        self.assertFalse(os.path.exists(os.path.join(self.claude, "tools", "cc_old.py")), "新版里没有的旧模块删掉")
        self.assertTrue(os.path.isfile(os.path.join(self.claude, ".git", "HEAD")), ".git 不动")
        self.assertTrue(os.path.isfile(os.path.join(self.claude, "我的笔记.txt")), "别的顶层文件不动")
        self.assertEqual(2, len(self.backups()))
        self.assertTrue(self.backups()[0].endswith(".zip"))
        skills = os.path.join(self.home, ".claude", "skills")
        for name in ("jj-learn", "jj-update", "jj-newthing"):
            info = cc_install.entry_info(os.path.join(skills, name))
            self.assertIsNotNone(info, name)
            self.assertEqual("9.9.9", info["version"], "口令里写的版本是新版的")
            self.assertTrue(cc_install._same(info["main"], self.claude))
        self.assertFalse(os.path.exists(os.path.join(skills, "jj-check")), "下架的口令删掉")
        self.assertIn("jj-newthing", r["entries"]["installed"])
        self.assertIn("jj-check", r["entries"]["removed"])
        self.assertTrue(os.path.isfile(os.path.join(self.home, ".agents", "skills", "jj-update", "SKILL.md")), "Codex 那份也装上")

    def test_已经是最新_或线上更旧_不动(self):
        os.remove(os.path.join(self.agents, "SKILL.md"))  # 只剩 .claude 那份 0.3.0
        self.gh.publish("v0.3.0", self.good)
        r = cc_update.update(home=self.home)
        self.assertEqual("latest", r["state"], r)
        self.gh.publish("v0.2.2", self.good)
        self.assertEqual("latest", cc_update.update(home=self.home)["state"], "不会「更新」回旧版")
        self.assertEqual((0, 3, 0), self.ver(self.claude))
        self.assertEqual([], self.backups())

    def test_只看不换(self):
        self.gh.publish("v9.9.9", self.good)
        r = cc_update.update(home=self.home, check_only=True)
        self.assertEqual("available", r["state"])
        self.assertEqual((0, 3, 0), self.ver(self.claude))
        self.assertEqual([], self.backups())

    def test_Codex两处都有时_口令只装在agents旁边(self):
        codex = make_tree(os.path.join(self.home, ".codex", "skills", "jiujiastudy"), "0.3.0")
        self.gh.publish("v9.9.9", self.good)
        r = cc_update.update(home=self.home)
        self.assertEqual("updated", r["state"], r)
        self.assertEqual((9, 9, 9), self.ver(codex), "主文件夹照样换上新版")
        self.assertTrue(os.path.isfile(os.path.join(self.home, ".agents", "skills", "jj-update", "SKILL.md")))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".codex", "skills", "jj-update")), "Codex 菜单里不出现两遍")

    def test_压缩包不对就不动(self):
        for blob, tag in ((self.junk, "v9.9.9"), (self.mismatch, "v9.9.9"), (self.evil, "v9.9.9")):
            self.gh.publish(tag, blob)
            r = cc_update.update(home=self.home)
            self.assertEqual("error", r["state"], r)
            self.assertIn("没更新", r["message"])
            self.assertEqual((0, 3, 0), self.ver(self.claude))
            self.assertTrue(os.path.isfile(os.path.join(self.claude, "tools", "cc_old.py")))
        self.assertEqual([], self.backups())

    def test_连不上就说一句(self):
        os.environ["JIUJIASTUDY_UPDATE_API"] = "http://127.0.0.1:9"
        r = cc_update.update(home=self.home, timeout=3)
        self.assertEqual("error", r["state"])
        self.assertIn("连不上 GitHub", r["message"])
        self.assertIn("照常能用", r["message"])

    def test_换到一半出错_换回旧版(self):
        self.gh.publish("v9.9.9", self.good)

        def boom(copy):
            raise RuntimeError("装口令时出错")
        r = cc_update.update(home=self.home, finisher=boom)
        self.assertEqual("error", r["state"], r)
        self.assertIn("换回旧版", r["message"])
        self.assertEqual(((0, 3, 0), (0, 1, 0)), (self.ver(self.claude), self.ver(self.agents)))
        self.assertTrue(os.path.isfile(os.path.join(self.claude, "tools", "cc_old.py")), "备份换回来了")

    def test_没装好就说一句(self):
        r = cc_update.update(home=tempfile.gettempdir() + os.sep + "stc-no-such-home")
        self.assertEqual("error", r["state"])
        self.assertIn("还没装", r["message"])


class Duplicates(unittest.TestCase):
    def test_实验文件夹旁边的备份不算第二个技能(self):
        d = tempfile.mkdtemp(prefix="stc-dup-")
        try:
            lab = make_tree(os.path.join(d, "Documents", "jiujiastudy-lab"), "0.3.0")
            make_tree(os.path.join(d, "Documents", "jiujiastudy.bak-20260923-moodle"), "0.2.0")
            self.assertEqual([], [x for x in cc_install.duplicate_skills(lab, home=os.path.join(d, "home")) if x[0] == "warn"])
            inside = make_tree(os.path.join(d, "home", ".claude", "skills", "jiujiastudy"), "0.3.0")
            make_tree(os.path.join(d, "home", ".claude", "skills", "jiujiastudy.backup-1"), "0.2.0")
            self.assertTrue([x for x in cc_install.duplicate_skills(inside, home=os.path.join(d, "home")) if x[0] == "warn"],
                            "放在 skills 里的备份照样提醒")
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
