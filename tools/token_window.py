"""「连上 Canvas」小窗口：填学校、粘 token、点保存。由 doctor --token-window 另起进程打开。

token 从剪贴板进这个窗口，只存进本机文件（cc_token.TOKEN_FILE），不经过对话、不进命令行参数、不打印。
保存前先认学校（查表或用户给的网址）、不带 token 探一下是不是 Canvas，再只对这一个地址验一次 token：
复制不全、学校写错，当场在窗口里说，不用回对话来回问。
用法（AI 不直接跑它）：python token_window.py --home <机器档案> [--ready <文件>]
"""
import argparse
import os
import queue
import sys
import threading
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brand  # noqa: E402
import canvas_api  # noqa: E402
import cc_host  # noqa: E402
from cc_store import jsave  # noqa: E402
from cc_token import save_token, token_problem  # noqa: E402

IDLE_CLOSE_MS = 20 * 60 * 1000  # 20 分钟没人动就自己关
GEN_STEPS = ("① 在 Canvas 里：左边 Account → Settings → 往下找 Approved Integrations → + New Access Token\n"
             f"② Purpose 填「{brand.NAME}」，Expires 选学期结束那天，点生成\n"
             "③ 把出来的那一长串整段复制，粘到下面")


def check(home, school, tok):
    """认学校、验 token，存下来。返回 (ok, 给人看的一句话)。不碰界面，方便单测。"""
    problem = token_problem(tok)
    if not (school or "").strip():
        return False, "先填学校：校名，或者 Canvas 的网址"
    if problem:
        return False, problem
    got = cc_host.resolve_school(school)
    if got.get("ambiguous"):
        return False, f"「{school.strip()}」对得上不止一所：" + "、".join(n for _, n in got["ambiguous"]) + "。请写全名"
    host = got.get("host")
    if not host:
        return False, "没认出这所学校。请直接填 Canvas 的网址：登录 Canvas 后，浏览器地址栏里的那一串"
    site = host.split("://", 1)[-1]  # 给人看的地址不带 https://，窗口里折行好看
    looks = cc_host.is_canvas(host)
    if looks is False:
        return False, f"{site} 不像 Canvas。请填登录 Canvas 后浏览器地址栏里的网址"
    tok = tok.strip()
    if looks is None:
        save_token(tok)
        jsave(os.path.join(home, "site.json"), {"host": host, "school": school.strip()})
        return True, f"先存下了，但现在连不上 {site}（检查网络或 VPN）。回到对话说一句「好了」，会再试一次。"
    try:
        me = canvas_api.Canvas(host, tok, timeout=20, retries=0).get("/api/v1/users/self")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, f"token 在 {site} 上登不上：多半没复制全。回 Canvas 重新生成一个，整段复制再粘"
        return False, f"{site} 返回 HTTP {e.code}，等一会儿再点保存"
    except (urllib.error.URLError, OSError, canvas_api.CanvasError):
        save_token(tok)
        jsave(os.path.join(home, "site.json"), {"host": host, "school": school.strip()})
        return True, f"先存下了，但验证时连不上 {site}（检查网络或 VPN）。回到对话说一句「好了」，会再试一次。"
    save_token(tok)
    jsave(os.path.join(home, "site.json"), {"host": host, "school": school.strip()})
    who = (me or {}).get("name") or "你的账号"
    return True, f"连上了：{who} @ {site}。回到对话，说一句「好了」。"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", required=True)
    ap.add_argument("--ready")
    a = ap.parse_args()

    if sys.platform == "win32":
        try:  # 高分屏上字不糊
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(f"{brand.NAME} · 连上你的 Canvas")
    font = ("Microsoft YaHei UI", 10) if sys.platform == "win32" else (("PingFang SC", 13) if sys.platform == "darwin" else None)
    if font:
        root.option_add("*Font", font)
    frm = ttk.Frame(root, padding=18)
    frm.grid(sticky="nsew")
    frm.columnconfigure(0, weight=1)

    ttk.Label(frm, text="1. 你的学校").grid(row=0, column=0, sticky="w")
    school = tk.StringVar()
    e_school = ttk.Entry(frm, textvariable=school, width=46)
    e_school.grid(row=1, column=0, columnspan=2, sticky="we", pady=(4, 2))
    ttk.Label(frm, text="写校名（比如「悉尼大学」「UTS」），或者 Canvas 的网址", foreground="#666").grid(row=2, column=0, columnspan=2, sticky="w")

    ttk.Label(frm, text="2. Canvas token").grid(row=3, column=0, sticky="w", pady=(14, 0))
    steps = ttk.Label(frm, text=GEN_STEPS, foreground="#444", justify="left")
    steps.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 4))
    tokv = tk.StringVar()
    e_tok = ttk.Entry(frm, textvariable=tokv, show="•", width=46)
    e_tok.grid(row=5, column=0, sticky="we")
    shown = tk.BooleanVar(value=False)
    ttk.Checkbutton(frm, text="显示", variable=shown, command=lambda: e_tok.configure(show="" if shown.get() else "•")).grid(row=5, column=1, padx=(8, 0))
    ttk.Label(frm, text="token 只存在这台电脑上，不会进聊天记录。别发到对话里。", foreground="#666").grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))

    status = tk.StringVar()
    lab = tk.Label(frm, textvariable=status, justify="left", anchor="w")
    lab.grid(row=7, column=0, columnspan=2, sticky="we", pady=(12, 0))
    btns = ttk.Frame(frm)
    btns.grid(row=8, column=0, columnspan=2, sticky="e", pady=(14, 0))
    b_cancel = ttk.Button(btns, text="取消", command=root.destroy)
    b_cancel.grid(row=0, column=0, padx=(0, 8))
    b_save = ttk.Button(btns, text="保存")
    b_save.grid(row=0, column=1)

    results = queue.Queue()

    def poll():
        try:
            ok, msg = results.get_nowait()
        except queue.Empty:
            root.after(150, poll)
            return
        status.set(msg)
        lab.configure(fg="#1a7f37" if ok else "#b42318")
        if ok:
            b_save.configure(text="关闭", command=root.destroy, state="normal")
            b_cancel.grid_remove()
            root.after(15000, root.destroy)
        else:
            b_save.configure(state="normal")

    def on_save(*_):
        if str(b_save["state"]) == "disabled" or b_save["text"] == "关闭":
            return
        b_save.configure(state="disabled")
        status.set("正在连 Canvas……")
        lab.configure(fg="#444")
        s, t = school.get(), tokv.get()

        def work():
            try:
                results.put(check(a.home, s, t))
            except Exception as e:  # noqa: BLE001
                results.put((False, f"出错了：{type(e).__name__}。回到对话说一句，我换个办法"))

        threading.Thread(target=work, daemon=True).start()
        root.after(150, poll)

    b_save.configure(command=on_save)
    root.bind("<Return>", on_save)
    root.resizable(False, False)
    # 一直置顶：用户要在浏览器里生成 token 再切回来粘，窗口被浏览器盖住就找不到了（后台进程抢不到前台，不置顶会开在对话窗口后面）
    root.attributes("-topmost", True)
    root.after(IDLE_CLOSE_MS, root.destroy)
    root.update_idletasks()
    wrap = e_school.winfo_reqwidth()  # 按输入框自己要的宽度折行：写死像素在高分屏上折得很窄，不折又会把窗口撑得很宽
    steps.configure(wraplength=wrap)
    lab.configure(wraplength=wrap)
    root.update()
    root.lift()
    root.focus_force()
    e_school.focus_set()
    if a.ready:
        try:
            open(a.ready, "w").close()
        except OSError:
            pass
    root.mainloop()


if __name__ == "__main__":
    main()
