# 第三方组件

救驾本身按 MIT 发布（见 `LICENSE`），**不打包、不内嵌任何第三方库**。下面这些是可选依赖：
用到了才装，装的时候是从 PyPI 装到你自己的 Python 里，各自遵循各自的许可。

| 包 | 什么时候才需要 | 上游许可 |
|---|---|---|
| `pypdf` | 某门课打开了「课件文字给 AI 读」，且要读 PDF | BSD-3-Clause |
| `python-pptx` | 同上，要读 .pptx | MIT |
| `python-docx` | 同上，要读 .docx | MIT |
| `tzlocal` | 认电脑时区（认不出就退回按课程时区显示） | MIT |
| `tzdata` | 这个 Python 自带的时区库不全时 | Apache-2.0 |

不装任何一个，deadline 和本周清单照常工作——这是设计上的硬要求。

前三个（取字用的）`doctor` **不会**自动装：课件文字提取默认关着，
你给某门课打开（`config course <课程代码> --materials-ai on`）之后要读什么格式，再装什么。

## 为什么不用 PyMuPDF

PyMuPDF 取字更好，但它是 AGPL：一个按 MIT 发布的项目不该主动把用户引去装 AGPL 的库。
所以 PDF 取字用纯 Python 的 pypdf。

许可信息以各包在 PyPI 上的声明为准；上面这张表只是方便查阅。
