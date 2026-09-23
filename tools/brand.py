"""产品名、版本和由名字派生的标识。改名只改这一个文件；其余代码里的产品名都从这里取。

旧版的名字（LEGACY_*）只用来读老用户的环境变量和档案，不再写出。
"""
import os

NAME = "救驾"                  # 给人看的名字：桌面资料夹、页面标题、确认窗口
SLUG = "jiujiastudy"          # 小写：skills 下的文件夹名、~/.config 子目录、User-Agent、页面存储键
ENV_PREFIX = "JIUJIASTUDY"    # 环境变量前缀：JIUJIASTUDY_HOME、JIUJIASTUDY_ROOT、JIUJIASTUDY_NO_DIALOG …
KEYCHAIN_SERVICE = SLUG + "-canvas"  # macOS 钥匙串里存 token 的服务名
VERSION = "0.2.1"

LEGACY_ENV_PREFIXES = ("JIUJIA", "STCANVAS", "COURSECOACH")  # 旧版环境变量前缀：仍然读
LEGACY_HOME_DIRNAME = "CourseCoach"     # 旧版机器档案 ~/CourseCoach：仍然认


def env_name(key):
    """当前的环境变量名，如 env_name("HOME") → JIUJIASTUDY_HOME。给提示文字用。"""
    return f"{ENV_PREFIX}_{key}"


def env(key, default=None):
    """读环境变量：先读当前名字，再读旧版名字（COURSECOACH_*）；都没有或是空的就返回 default。"""
    for prefix in (ENV_PREFIX,) + LEGACY_ENV_PREFIXES:
        value = os.environ.get(f"{prefix}_{key}")
        if value:
            return value
    return default
