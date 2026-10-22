# 更新（/jj-update）

学生打 /jj-update，或者说「更新救驾」：

1. 跑 `update`。它去 GitHub 看最新的正式版，比装着的新就换上。
   - Claude Code、Codex 装着的几份一起换。
   - 旧版打成压缩包，放在 skills 外面的「文档/救驾备份」。
   - 新版带来的 /jj 口令装上，下架的删掉。
   - 学生的档案、token、登录记录不在技能文件夹里，换版本不受影响。
2. 跟学生只说它打印的「这次更新的新内容」和「新口令」，用学生听得懂的话，不加别的；不提备份。打印「已经是最新版」就说一句。
3. 连不上 GitHub、新版没下好、没换上：照它打印的那句说，旧版照常能用；不叫学生自己去下。
4. 换完以后这个对话里加载的还是旧说明：学生接着要用新口令，就照新口令的入口去读主文件夹里的新说明；档案格式变了的话，下一条命令会报退出码 3，照 SKILL.md 跑 `migrate`。

## 给维护者：加一个新功能

`/jj-update` 会把新版里的口令自动装上。新功能要做的就是两样：

- `skills/jj-<名字>/SKILL.md`：入口，只写几行指路。格式照 jj-learn，`tests/test_jj_entries.py` 会查；
- `references/<名字>.md`：这个功能的完整说明。

**整份收一个外部的 skill（发起人 10-22 定的，/humanizer 就是这样收的）**：要它用起来跟原版一模一样、口令用原作者起的名字时这么收。

- 收之前查三样：许可（读它仓库的 LICENSE）、安全（读完它的说明和要跑的每个脚本）、在自己电脑上真跑一次。
- 原样放进 `skills/<原名>/`（用 `git -c core.autocrlf=false archive` 导出，保持原作者的 LF），SKILL.md 不改名、不加「主文件夹」那一行。它装出去就是一个独立的技能，不读主文件夹，产品改名、搬家都不影响它。
- 名字加进 `tools/cc_install.py` 的 `BUNDLED`。装的时候整份复制到主文件夹旁边，旁边写记号 `installed-by.json`；学生自己装过同名的不覆盖。
- `tests/fixtures/upstream/<原名>.json` 存每个文件的 sha256（照 `tests/test_humanizer.py`），`THIRD_PARTY_NOTICES.md` 写上来源和许可。
- 每次发版前对一遍原作者的更新：有新 commit 就读改了什么，重新导出，更新清单，测好再跟着这一版发。

发版时，在 GitHub Release 的说明里写「这次更新的新内容」，一句一条，学生听得懂的话。/jj-update 会原样转述给学生。版本号改 `tools/brand.py` 的 VERSION，打 tag `v<版本>`。
