# LocalPdfToolkit

LocalPdfToolkit 是运行在本机的统一 PDF 工作台。唯一根目录入口
`local-pdf-toolkit.py` 启动本机 HTML 页面和后台接口；服务只绑定回环地址，不对局域网开放。

PDF 的修改和输出由本机 Bluebeam Revu 20 eXtreme 执行；Python 可用于读取、搜索、
渲染、OCR 前后处理和坐标分析。Bluebeam Script Engine 的具体操作会由适配模块封装。
AI 服务由外部项目管理，本项目只调用已运行的本地服务，不负责安装、启动或配置 AI 运行时。

## 当前进度

当前版本已建立本机网页服务、统一首页、健康状态接口、配置加载、日志入口和工具分组展示。
各 PDF 工作流仍在从来源项目中分析和迁移；首页会标记尚未接入的功能。当前 `/api/jobs`
尚未执行 PDF 任务，不应将此版本视为功能迁移完成。

计划纳入：

- `PdfTextMarker`、`CopyPdfPline`、`PDFPageReplacer`
- `GetPdfText`、`GetPdfInfo`、`GetLocInPdf`
- `PdfStamp`、`Frame2Pdf` 及盘点后确认的其他 PDF 工作流

`GetPdfInfo` 和 `GetLocInPdf` 暂时各自保留，完成代码分析后再决定是否共享底层能力。

## 启动

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item common.env.example common.env
.\.venv\Scripts\python.exe local-pdf-toolkit.py
```

默认打开 `http://127.0.0.1:8765`。可在 `common.env` 设置 Bluebeam Revu 和 Script Engine
的本机路径；机器相关路径不应写入版本库。复制配置模板后无需填写 AI 配置。

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
