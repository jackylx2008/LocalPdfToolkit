"""基于 Python 标准库的本机 HTML 与 JSON 接口服务。"""

from __future__ import annotations

import json
import ipaddress
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from logging_config import get_logger

logger = get_logger(__name__)


def run_server(host: str, port: int, project_root: Path) -> None:
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError("本机工作台仅允许绑定回环地址")
    web_root = project_root / "src" / "local_pdf_toolkit" / "web" / "static"
    handler = _make_handler(web_root)
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _make_handler(web_root: Path):
    class LocalToolkitHandler(BaseHTTPRequestHandler):
        server_version = "LocalPdfToolkit/0.1"

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/status":
                self._json(200, {"status": "ready", "host_scope": "localhost"})
                return
            if path == "/api/tools":
                self._json(200, {"tools": []})
                return
            relative = "index.html" if path in ("/", "") else path.lstrip("/")
            target = (web_root / relative).resolve()
            if not target.is_relative_to(web_root.resolve()) or not target.is_file():
                self.send_error(404)
                return
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/jobs":
                self.send_error(404)
                return
            self._json(501, {"error": "工作流尚未接入"})

        def _json(self, status: int, value: dict) -> None:
            data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args) -> None:
            logger.info("%s - %s", self.address_string(), format % args)

    return LocalToolkitHandler
