# 第三方组件

救驾本身按 PolyForm Noncommercial 1.0.0 发布（见 `LICENSE`；v0.2.x 及更早是 MIT）。**内嵌的第三方组件只有一个**：原样收进来的 humanizer（见最后一节）。除此之外不打包、不内嵌任何第三方库，下面这些是可选依赖：
用到了才装，装的时候是从 PyPI 装到你自己的 Python 里，各自遵循各自的许可。

| 包 | 什么时候才需要 | 上游许可 |
|---|---|---|
| `pypdf` | 某门课打开了「课件文字给 AI 读」，且要读 PDF | BSD-3-Clause |
| `python-pptx` | 同上，要读 .pptx | MIT |
| `python-docx` | 同上，要读 .docx | MIT |
| `tzlocal` | 认电脑时区（认不出就退回按课程时区显示） | MIT |
| `tzdata` | 这个 Python 自带的时区库不全时 | Apache-2.0 |
| `playwright` | 学校不让生成 token、改用登录模式（`login`）时，以及学校用 Moodle 时（Moodle 只走登录模式）；浏览器用电脑上已有的 Edge / Chrome | Apache-2.0 |

不装任何一个，deadline 和本周清单照常工作——这是设计上的硬要求。

前三个（取字用的）`doctor` **不会**自动装：课件文字提取默认关着，
你给某门课打开（`config course <课程代码> --materials-ai on`）之后要读什么格式，再装什么。

## 为什么不用 PyMuPDF

PyMuPDF 取字更好，但它是 AGPL：一个不按 AGPL 发布的项目不该主动把用户引去装 AGPL 的库。
所以 PDF 取字用纯 Python 的 pypdf。

许可信息以各包在 PyPI 上的声明为准；上面这张表只是方便查阅。

## 内嵌的组件

| 组件 | 放在哪 | 版本 | 上游许可 |
|---|---|---|---|
| humanizer（blader/humanizer，https://github.com/blader/humanizer） | `skills/humanizer/` | 3.1.0，commit 8c307f3（2026-10-16） | MIT，全文在 `skills/humanizer/LICENSE`：Copyright (c) 2025 Siqi Chen |

`/humanizer`（去 AI 味）就是 blader/humanizer 本身：SKILL.md、LICENSE、agents/openai.yaml 原样放在 `skills/humanizer/`，一个字没改，SKILL.md 连文件名都没改（它要作为单独的技能装出去，口令就用原名）。安装时只在它旁边多写一个记号文件 `installed-by.json`（记主文件夹和版本），不改它的文件。每次发新版前对一遍原作者的更新，读过、测好再合进来。
