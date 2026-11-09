"""本机 PDF 工具工作台

用途：
  启动 LocalPdfToolkit 的本机 HTML 页面和后台工作流接口，作为所有 PDF
  处理功能的唯一启动入口。PDF 修改与输出由本机 Bluebeam Revu eXtreme 执行；
  Python 模块负责网页服务、任务编排，以及允许的读取、搜索、渲染和坐标分析。

配置文件：
  根目录 config.yaml 提供服务地址、端口和日志级别；common.env 用于本机路径，
  不入库。Bluebeam 程序路径可通过配置或环境变量提供。

参数：
  --host / --port 可覆盖本机网页服务绑定地址和端口。

示例：
  python local-pdf-toolkit.py
  python local-pdf-toolkit.py --host 127.0.0.1 --port 8765

输出：
  在浏览器提供统一工具首页；运行日志写入 logs/local-pdf-toolkit.log。
  处理结果写入用户在网页中选择的目标目录。
"""

from __future__ import annotations

import argparse
import ipaddress
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from local_pdf_toolkit.config_loader import load_context
from local_pdf_toolkit.web.server import run_server
from logging_config import configure_utf8_stdio, get_logger, setup_logger


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", help="网页服务监听地址，默认仅本机回环地址")
    parser.add_argument("--port", type=int, help="网页服务端口")
    args = parser.parse_args()

    configure_utf8_stdio()
    context = load_context(PROJECT_ROOT)
    setup_logger(context.log_level)
    logger = get_logger(__name__)
    host = args.host or context.host
    port = args.port or context.port
    if not ipaddress.ip_address(host).is_loopback:
        parser.error("本机工作台仅允许绑定 127.0.0.1 或 ::1")
    logger.info("启动本机 PDF 工具工作台: http://%s:%s", host, port)
    try:
        run_server(host=host, port=port, project_root=PROJECT_ROOT)
    except KeyboardInterrupt:
        logger.info("收到关闭请求，工作台已停止")
    except OSError:
        logger.exception("网页服务启动失败")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
