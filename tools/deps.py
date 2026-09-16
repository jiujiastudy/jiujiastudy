"""可选依赖：import 名 → pip 包名，和唯一的可选导入入口。缺了哪个都不挡 deadline 和本周清单。"""
import importlib
import importlib.util

# 取字用的三个（pypdf / python-pptx / python-docx）都是可选的，只有用户给某门课打开了
# 「课件文字给 AI 读」才需要；doctor 不预装它们，缺了也不挡 deadline 和本周清单。
DEP_NAMES = {"pypdf": "pypdf", "pptx": "python-pptx", "docx": "python-docx", "tzlocal": "tzlocal", "tzdata": "tzdata"}
EXTRACT_DEPS = ("pypdf", "pptx", "docx")  # 按课打开后才用得上，不进 doctor 的自动安装


def optional(name):
    """可选模块：装了就返回模块，没装返回 None。导入时的其它错误照常抛出，由调用处处理。"""
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def missing():
    """DEP_NAMES 里还没装的 import 名；只有 doctor 用它决定要不要 pip。
    tzdata 不在这里算：系统自带时区库时根本不需要，doctor 的时区检查单独处理它。"""
    skip = ("tzdata",) + EXTRACT_DEPS
    return [m for m in DEP_NAMES if m not in skip and importlib.util.find_spec(m) is None]
