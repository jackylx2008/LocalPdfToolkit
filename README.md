# LocalPdfToolkit

LocalPdfToolkit 是运行在本机的统一 PDF 工作台。唯一根目录入口
`local-pdf-toolkit.py` 启动本机 HTML 页面和后台接口；服务只绑定回环地址，不对局域网开放。

启动时自动检测本机 Bluebeam Revu 20 eXtreme Script Engine：检测到时，适用的 PDF 修改
工作流选择 Bluebeam；未检测到时，自动使用 PyMuPDF、pypdf、Pillow 等 Python 包完成相应操作。
Python 包也为 Revu 环境提供可切换的替代后端；读取、搜索、渲染、OCR 和坐标分析仍由 Python 模块完成。
AI 服务由外部项目管理，本项目只调用已运行的本地服务，不负责安装、启动或配置 AI 运行时。

## 当前进度

当前首页已接入 `GetPdfInfo` 元素和关联分析、单文件 OCR 与编号核对、批量页数校核、
`GetLocInPdf` 关键词截图、`PdfTextMarker` 关键词标注、`CopyPdfPline` 单页配准、
`PDFPageReplacer` 首页替换、`PdfStamp` 编号变更盖章和 `Frame2Pdf` 图片合并。
标注类工作流在 Bluebeam 模式生成 FDF；Python 模式生成已应用标注的 PDF。图片转 PDF、页面替换
均支持两个后端。AI 图框拆分、OCR 改名/拆页和批量楼层迁移仍需后续接入。

所有指定项目已完成源码盘点；详细映射、重叠分析和其他项目候选见
[PDF 工作流盘点](docs/PDF_WORKFLOW_INVENTORY.md)。`GetPdfInfo` 与 `GetLocInPdf` 保持为
不同工作流：前者提取和分析页面元素，后者定位关键词并生成截图。
可复用的浏览器主显示器启动要求见 [HTML 交互原则](docs/HTML_INTERACTION_PRINCIPLES.md)。

## 启动

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item common.env.example common.env
.\.venv\Scripts\python.exe local-pdf-toolkit.py
```

默认打开 `http://127.0.0.1:8765`。`PDF_BACKEND=auto` 会自动检测 Bluebeam 并选择后端；
可设置为 `bluebeam` 或 `python` 强制指定。需要 Bluebeam 时，可在 `common.env` 设置 Revu 和
Script Engine 的本机路径；机器相关路径不应写入版本库。复制配置模板后无需填写 AI 配置。
Bluebeam 检测可用时，也可在首页右上角开关即时启用或停用；未检测到时开关会禁用并使用 Python。
Windows 上启动时会请求 Chrome 新建窗口打开工作台，并将其移动到主显示器后最大化；未安装 Chrome 时改用系统默认浏览器新建窗口。

如果 `common.env` 不存在，服务使用 `config.yaml` 中的默认回环地址、端口和日志级别。
也可通过 `WEB_HOST`、`WEB_PORT`、`LOG_LEVEL` 覆盖；监听地址必须是 `127.0.0.1` 或 `::1`。

## 结构

```text
local-pdf-toolkit.py             # 唯一网页服务入口
logging_config.py                # 统一日志
config.yaml                      # 通用默认配置
common.env.example               # 本机配置模板
src/local_pdf_toolkit/modules/   # PDF/Bluebeam/解析等可复用能力
src/local_pdf_toolkit/flows/     # 按工作流组织处理步骤
src/local_pdf_toolkit/web/       # 本地 HTML 与 API
tests/                           # 自动化测试
docs/                            # 架构、功能映射和使用文档
logs/                            # 本机滚动日志
```

统一日志同时写入控制台和 `logs/local-pdf-toolkit.log`，单文件达到 10 MB 后轮转并保留
5 份备份。日志文件和本机配置不会提交到 Git。

整合工作流会逐项迁入，原项目入口和接口不作为新项目的用户入口。项目 Git 同步与敏感文件
检查约定见 [docs/GitHub.md](docs/GitHub.md)，本次初始骨架更新见
[2026-11-09 更新记录](docs/UPDATE_2026-11-09.md)。

原项目测试样本可放入本机 `test_data/`，该目录已加入 `.gitignore`，不会提交到仓库。
