"""基于 Python 标准库的本机 HTML 与 JSON 接口服务。"""

from __future__ import annotations

import json
import os
import ipaddress
import mimetypes
import re
import shutil
import subprocess
import threading
import time
import webbrowser
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from uuid import uuid4

from logging_config import get_logger
from local_pdf_toolkit.modules.pdf_info import (
    analyze_color_relationships,
    analyze_spatial_relationships,
    extract_pdf_elements,
    write_analysis_csv,
)
from local_pdf_toolkit.modules.pdf_ocr import ocr_pdf
from local_pdf_toolkit.modules.page_count_check import check_uploaded_page_counts
from local_pdf_toolkit.modules.pdf_location import capture_keyword_screenshots
from local_pdf_toolkit.modules.pdf_marker import prepare_keyword_markups
from local_pdf_toolkit.modules.copy_markups import prepare_transferred_markups
from local_pdf_toolkit.modules.pdf_stamp import prepare_pdf_stamps
from local_pdf_toolkit.modules.frame_to_pdf import images_to_pdf_with_revu
from local_pdf_toolkit.modules.page_replacement import replace_attached_front_pages
from local_pdf_toolkit.modules.pdf_backend import PdfBackend, detect_pdf_backend

logger = get_logger(__name__)


def _visible_window_handles() -> set[int]:
    """Return visible top-level window handles on Windows."""
    if os.name != "nt":
        return set()
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    enum_windows = user32.EnumWindows
    enum_windows.argtypes = [callback_type, wintypes.LPARAM]
    enum_windows.restype = wintypes.BOOL
    is_window_visible = user32.IsWindowVisible
    is_window_visible.argtypes = [wintypes.HWND]
    is_window_visible.restype = wintypes.BOOL
    handles: set[int] = set()

    @callback_type
    def collect(hwnd, _lparam):
        if is_window_visible(hwnd):
            handles.add(int(hwnd))
        return True

    enum_windows(collect, 0)
    return handles


def _find_chrome_executable() -> Path | None:
    """Locate the installed Chrome executable without relying on the default browser."""
    if os.name != "nt":
        return None
    located = shutil.which("chrome.exe") or shutil.which("chrome")
    if located:
        return Path(located)
    candidates = [
        Path(os.environ[root]) / "Google" / "Chrome" / "Application" / "chrome.exe"
        for root in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)")
        if os.environ.get(root)
    ]
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(
            Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "Application" / "chrome.exe"
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    try:
        import winreg

        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, r"Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:
                    candidate = Path(winreg.QueryValue(key, None))
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
    except ImportError:
        pass
    return None


def _move_toolkit_window_to_primary_monitor(
    page_title: str,
    existing_windows: set[int] | None = None,
    timeout: float = 12.0,
) -> None:
    """Move the browser window showing this page onto the primary Windows monitor."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    class Rect(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    get_title_length = user32.GetWindowTextLengthW
    get_title_length.argtypes = [wintypes.HWND]
    get_title_length.restype = ctypes.c_int
    get_title = user32.GetWindowTextW
    get_title.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    get_title.restype = ctypes.c_int
    is_window_visible = user32.IsWindowVisible
    is_window_visible.argtypes = [wintypes.HWND]
    is_window_visible.restype = wintypes.BOOL
    enum_windows = user32.EnumWindows
    enum_windows.argtypes = [callback_type, wintypes.LPARAM]
    enum_windows.restype = wintypes.BOOL
    system_parameters_info = user32.SystemParametersInfoW
    system_parameters_info.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT]
    system_parameters_info.restype = wintypes.BOOL
    get_window_rect = user32.GetWindowRect
    get_window_rect.argtypes = [wintypes.HWND, ctypes.POINTER(Rect)]
    get_window_rect.restype = wintypes.BOOL
    is_zoomed = user32.IsZoomed
    is_zoomed.argtypes = [wintypes.HWND]
    is_zoomed.restype = wintypes.BOOL
    is_iconic = user32.IsIconic
    is_iconic.argtypes = [wintypes.HWND]
    is_iconic.restype = wintypes.BOOL
    show_window = user32.ShowWindow
    show_window.argtypes = [wintypes.HWND, ctypes.c_int]
    show_window.restype = wintypes.BOOL
    set_window_pos = user32.SetWindowPos
    set_window_pos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    set_window_pos.restype = wintypes.BOOL

    existing_windows = existing_windows or set()
    deadline = time.monotonic() + timeout
    browser_window = None
    while time.monotonic() < deadline and browser_window is None:
        matches: list[wintypes.HWND] = []

        @callback_type
        def enum_window(hwnd, _lparam):
            if not is_window_visible(hwnd):
                return True
            length = get_title_length(hwnd)
            if length <= 0:
                return True
            title = ctypes.create_unicode_buffer(length + 1)
            get_title(hwnd, title, len(title))
            if int(hwnd) not in existing_windows and page_title.casefold() in title.value.casefold():
                matches.append(hwnd)
                return False
            return True

        enum_windows(enum_window, 0)
        if matches:
            browser_window = matches[0]
            break
        time.sleep(0.25)

    if browser_window is None:
        logger.warning("未找到显示工作台页面的浏览器窗口，无法调整到主显示器")
        return

    work_area = Rect()
    if not system_parameters_info(0x0030, 0, ctypes.byref(work_area), 0):
        logger.warning("无法读取主显示器工作区，浏览器窗口未移动")
        return
    current = Rect()
    if not get_window_rect(browser_window, ctypes.byref(current)):
        logger.warning("无法读取浏览器窗口位置，窗口未移动")
        return

    was_maximized = bool(is_zoomed(browser_window))
    was_minimized = bool(is_iconic(browser_window))
    if was_maximized or was_minimized:
        show_window(browser_window, 9)  # SW_RESTORE
        if not get_window_rect(browser_window, ctypes.byref(current)):
            logger.warning("无法读取浏览器还原后的位置，窗口未移动")
            return

    available_width = max(1, work_area.right - work_area.left)
    available_height = max(1, work_area.bottom - work_area.top)
    width = min(max(1, current.right - current.left), available_width)
    height = min(max(1, current.bottom - current.top), available_height)
    left = work_area.left + (available_width - width) // 2
    top = work_area.top + (available_height - height) // 2
    if not set_window_pos(browser_window, 0, left, top, width, height, 0x0040):  # SWP_SHOWWINDOW
        logger.warning("将浏览器窗口移动到主显示器失败")
        return
    show_window(browser_window, 3)  # SW_MAXIMIZE
    logger.info("已将新建的工作台浏览器窗口移到主显示器并最大化")


def run_server(
    host: str,
    port: int,
    project_root: Path,
    pdf_backend: PdfBackend | None = None,
) -> None:
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError("本机工作台仅允许绑定回环地址")
    web_root = project_root / "src" / "local_pdf_toolkit" / "web" / "static"
    selected_backend = pdf_backend or detect_pdf_backend(project_root)
    handler = _make_handler(web_root, selected_backend)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"
    try:
        if os.name == "nt":
            existing_windows = _visible_window_handles()
            chrome = _find_chrome_executable()
            if chrome:
                subprocess.Popen(
                    [str(chrome), "--new-window", "--start-maximized", "--window-position=0,0", url],
                    close_fds=True,
                )
                logger.info("已请求 Chrome 新建最大化窗口打开工作台: %s", url)
            else:
                logger.warning("未找到 Chrome，改用系统默认浏览器新建窗口")
                opened = webbrowser.open(url, new=1, autoraise=True)
                if not opened:
                    logger.warning("未能自动打开浏览器，请手动访问: %s", url)
            threading.Thread(
                target=_move_toolkit_window_to_primary_monitor,
                args=("本机 PDF 工具工作台", existing_windows),
                name="move-browser-to-primary-monitor",
                daemon=True,
            ).start()
        else:
            opened = webbrowser.open(url, new=2, autoraise=True)
            if opened:
                logger.info("已请求默认浏览器打开工作台: %s", url)
            else:
                logger.warning("未能自动打开浏览器，请手动访问: %s", url)
    except Exception:
        logger.exception("自动打开浏览器失败，请手动访问: %s", url)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _make_handler(web_root: Path, pdf_backend: PdfBackend | None = None):
    selected_backend = pdf_backend or detect_pdf_backend(web_root.parents[3])
    backend_state = {
        "selected": selected_backend,
        "bluebeam_available": selected_backend.script_engine_path is not None,
    }
    backend_lock = threading.Lock()

    class LocalToolkitHandler(BaseHTTPRequestHandler):
        server_version = "LocalPdfToolkit/0.1"
        project_root = web_root.parents[3]
        runtime_backend_state = backend_state
        runtime_backend_lock = backend_lock

        def _selected_backend(self) -> PdfBackend:
            with self.runtime_backend_lock:
                return self.runtime_backend_state["selected"]

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/status":
                backend = self._selected_backend()
                backend_info = backend.public_info()
                backend_info["bluebeam_available"] = self.runtime_backend_state["bluebeam_available"]
                self._json(200, {
                    "status": "ready",
                    "host_scope": "localhost",
                    "pdf_backend": backend_info,
                })
                return
            if path == "/api/tools":
                self._json(200, {"tools": [
                    {"id": "pdf-info", "source": "GetPdfInfo", "status": "ready"},
                    {"id": "pdf-ocr", "source": "GetPdfText / PDFPageReplacer", "status": "partial"},
                    {"id": "page-counts", "source": "PDFPageReplacer", "status": "ready"},
                    {"id": "pdf-marker", "source": "PdfTextMarker", "status": "ready"},
                    {"id": "copy-markups", "source": "CopyPdfPline", "status": "ready"},
                    {"id": "ocr-verify", "source": "PDFPageReplacer / GetPdfText", "status": "planned"},
                    {"id": "pdf-location", "source": "GetLocInPdf", "status": "ready"},
                    {"id": "more-pdf", "source": "PDF workflow inventory", "status": "reviewed"},
                    {"id": "pdf-stamp", "source": "PdfStamp", "status": "ready"},
                    {"id": "frame-to-pdf", "source": "Frame2Pdf", "status": "ready"},
                ]})
                return
            if path.startswith("/api/files/"):
                self._send_output_file(path)
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
            path = urlparse(self.path).path
            if path == "/api/backend":
                self._set_pdf_backend()
                return
            if path not in ("/api/jobs/pdf-info", "/api/jobs/pdf-ocr", "/api/jobs/page-counts", "/api/jobs/pdf-location", "/api/jobs/pdf-marker", "/api/jobs/copy-markups", "/api/jobs/pdf-stamp", "/api/jobs/frame-to-pdf", "/api/jobs/replace-front-pages"):
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 150 * 1024 * 1024:
                    self._json(413, {"error": "上传文件为空或超过 150 MB 限制"})
                    return
                message = BytesParser(policy=policy.default).parsebytes(
                    b"Content-Type: " + self.headers.get("Content-Type", "").encode("ascii")
                    + b"\r\nMIME-Version: 1.0\r\n\r\n" + self.rfile.read(length)
                )
                fields: dict[str, str] = {}
                pdf_name = ""
                pdf_bytes = b""
                uploaded: dict[str, list[tuple[str, bytes]]] = {}
                for part in message.iter_parts():
                    name = part.get_param("name", header="content-disposition")
                    filename = part.get_filename()
                    payload = part.get_payload(decode=True) or b""
                    if filename:
                        uploaded.setdefault(name or "", []).append((Path(filename).name, payload))
                        if name == "pdf":
                            pdf_name, pdf_bytes = Path(filename).name, payload
                    elif name:
                        fields[name] = payload.decode("utf-8", errors="replace")
                if path == "/api/jobs/page-counts":
                    sources = uploaded.get("sources", [])
                    targets = uploaded.get("targets", [])
                    if not sources or not targets or any(not name.lower().endswith(".pdf") for name, _ in sources + targets):
                        self._json(400, {"error": "请分别选择源 PDF 和目标 PDF（至少各一个）"})
                        return
                    job_id = uuid4().hex
                    output_dir = self.project_root / "output" / "pdf_counts" / job_id
                    summary = check_uploaded_page_counts(sources, targets, output_dir)
                    downloads = {key: f"/api/files/pdf_counts/{job_id}/{name}" for key, name in summary.pop("downloads").items()}
                    self._json(200, {"status":"completed","job_id":job_id,"summary":summary,"downloads":downloads})
                    return
                if path == "/api/jobs/pdf-location":
                    if not pdf_name or not pdf_bytes or not pdf_name.lower().endswith(".pdf"):
                        self._json(400, {"error": "请选择一个有效的 PDF 文件"})
                        return
                    job_id = uuid4().hex
                    output_dir = self.project_root / "output" / "pdf_location" / job_id
                    input_pdf = output_dir / Path(pdf_name).name
                    input_pdf.parent.mkdir(parents=True, exist_ok=True)
                    input_pdf.write_bytes(pdf_bytes)
                    keywords = fields.get("keywords", "").replace("\r", "\n").split("\n")
                    mode = fields.get("mode", "full_page")
                    region = None
                    if mode == "region":
                        region = tuple(float(fields[key]) for key in ("x0", "y0", "x1", "y1"))
                    summary = capture_keyword_screenshots(
                        input_pdf,
                        output_dir,
                        keywords,
                        mode=mode,
                        dpi=max(72, min(400, int(fields.get("dpi", "220")))),
                        region=region,
                    )
                    input_pdf.unlink(missing_ok=True)
                    summary["screenshots"] = [
                        {
                            **item,
                            "url": f"/api/files/pdf_location/{job_id}/{item['file_name']}?inline=1",
                        }
                        for item in summary["screenshots"]
                    ]
                    summary["manifest_url"] = f"/api/files/pdf_location/{job_id}/screenshots.json"
                    self._json(200, {"status": "completed", "job_id": job_id, "summary": summary})
                    return
                if path == "/api/jobs/pdf-marker":
                    if not pdf_name or not pdf_bytes or not pdf_name.lower().endswith(".pdf"):
                        self._json(400, {"error": "请选择一个有效的 PDF 文件"})
                        return
                    keywords = fields.get("keywords", "").replace("\r", "\n").split("\n")
                    job_id = uuid4().hex
                    output_dir = self.project_root / "output" / "pdf_marker" / job_id
                    input_pdf = output_dir / Path(pdf_name).name
                    input_pdf.parent.mkdir(parents=True, exist_ok=True)
                    input_pdf.write_bytes(pdf_bytes)
                    summary = prepare_keyword_markups(
                        input_pdf, keywords, output_dir, backend=self._selected_backend()
                    )
                    input_pdf.unlink(missing_ok=True)
                    summary["downloads"] = {
                        "fdf": f"/api/files/pdf_marker/{job_id}/{summary.pop('annotation_file')}",
                        "csv": f"/api/files/pdf_marker/{job_id}/{summary.pop('report_file')}",
                    }
                    if summary.get("output_pdf"):
                        summary["downloads"]["pdf"] = f"/api/files/pdf_marker/{job_id}/{summary['output_pdf']}"
                    self._json(200, {"status": "completed", "job_id": job_id, "summary": summary})
                    return
                if path == "/api/jobs/copy-markups":
                    source_files, target_files = uploaded.get("source", []), uploaded.get("target", [])
                    if len(source_files) != 1 or len(target_files) != 1:
                        self._json(400, {"error": "请选择一个单页源 PDF 和一个单页目标 PDF"})
                        return
                    source_name, source_bytes = source_files[0]
                    target_name, target_bytes = target_files[0]
                    if not source_name.lower().endswith(".pdf") or not target_name.lower().endswith(".pdf"):
                        self._json(400, {"error": "源文件与目标文件都必须是 PDF"})
                        return
                    job_id = uuid4().hex
                    output_dir = self.project_root / "output" / "copy_markups" / job_id
                    output_dir.mkdir(parents=True, exist_ok=True)
                    source_pdf = output_dir / ("source_" + Path(source_name).name)
                    target_pdf = output_dir / ("target_" + Path(target_name).name)
                    source_pdf.write_bytes(source_bytes)
                    target_pdf.write_bytes(target_bytes)
                    summary = prepare_transferred_markups(
                        source_pdf, target_pdf, output_dir, backend=self._selected_backend()
                    )
                    source_pdf.unlink(missing_ok=True)
                    target_pdf.unlink(missing_ok=True)
                    summary["download_url"] = f"/api/files/copy_markups/{job_id}/{summary.pop('annotation_file')}"
                    if summary.get("output_pdf"):
                        summary["pdf_url"] = f"/api/files/copy_markups/{job_id}/{summary['output_pdf']}"
                    self._json(200, {"status": "completed", "job_id": job_id, "summary": summary})
                    return
                if path == "/api/jobs/pdf-stamp":
                    pdf_files = uploaded.get("pdfs", [])
                    mapping_files = uploaded.get("mapping", [])
                    if not pdf_files or any(not name.lower().endswith(".pdf") for name, _ in pdf_files):
                        self._json(400, {"error": "请选择至少一个 PDF 文件"})
                        return
                    if len(mapping_files) != 1:
                        self._json(400, {"error": "请选择一个 CSV 或 XLSX 编号映射表"})
                        return
                    mapping_name, mapping_bytes = mapping_files[0]
                    job_id = uuid4().hex
                    output_dir = self.project_root / "output" / "pdf_stamp" / job_id
                    summary = prepare_pdf_stamps(
                        pdf_files, mapping_name, mapping_bytes, output_dir,
                        backend=self._selected_backend(),
                    )
                    summary["downloads"] = {
                        "zip": f"/api/files/pdf_stamp/{job_id}/{summary.pop('zip_file')}",
                        "report": f"/api/files/pdf_stamp/{job_id}/{summary.pop('report_file')}",
                    }
                    self._json(200, {"status": "completed", "job_id": job_id, "summary": summary})
                    return
                if path == "/api/jobs/frame-to-pdf":
                    images = uploaded.get("images", [])
                    if not images or any(Path(name).suffix.lower() not in {".jpg", ".jpeg"} for name, _ in images):
                        self._json(400, {"error": "请选择至少一张 JPEG 图片目录"})
                        return
                    job_id = uuid4().hex
                    output_dir = self.project_root / "output" / "frame_to_pdf" / job_id
                    summary = images_to_pdf_with_revu(
                        images,
                        output_dir,
                        fields.get("output_name", "images"),
                        backend=self._selected_backend(),
                    )
                    summary["download_url"] = f"/api/files/frame_to_pdf/{job_id}/{summary.pop('pdf_file')}"
                    self._json(200, {"status": "completed", "job_id": job_id, "summary": summary})
                    return
                if path == "/api/jobs/replace-front-pages":
                    content_files, attached_files = uploaded.get("content", []), uploaded.get("attached", [])
                    if len(content_files) != 1 or len(attached_files) != 1:
                        self._json(400, {"error": "请选择一份内容 PDF 和一份带附图的 PDF"})
                        return
                    content_name, content_bytes = content_files[0]
                    attached_name, attached_bytes = attached_files[0]
                    if not content_name.lower().endswith(".pdf") or not attached_name.lower().endswith(".pdf"):
                        self._json(400, {"error": "两个文件都必须是 PDF"})
                        return
                    job_id = uuid4().hex
                    output_dir = self.project_root / "output" / "page_replacement" / job_id
                    output_dir.mkdir(parents=True, exist_ok=True)
                    content_pdf, attached_pdf = output_dir / "content.pdf", output_dir / "attached.pdf"
                    content_pdf.write_bytes(content_bytes)
                    attached_pdf.write_bytes(attached_bytes)
                    summary = replace_attached_front_pages(
                        content_pdf, attached_pdf, output_dir / "replaced.pdf",
                        backend=self._selected_backend(),
                    )
                    content_pdf.unlink(missing_ok=True)
                    attached_pdf.unlink(missing_ok=True)
                    summary["source_content_name"] = content_name
                    summary["source_attached_name"] = attached_name
                    summary["download_url"] = f"/api/files/page_replacement/{job_id}/{summary['output_file']}"
                    self._json(200, {"status": "completed", "job_id": job_id, "summary": summary})
                    return
                if not pdf_name or not pdf_bytes or not pdf_name.lower().endswith(".pdf"):
                    self._json(400, {"error": "请选择一个有效的 PDF 文件"})
                    return
                job_id = uuid4().hex
                is_ocr = path.endswith("pdf-ocr")
                category = "pdf_ocr" if is_ocr else "pdf_info"
                output_dir = self.project_root / "output" / category / job_id
                output_csv = output_dir / f"{Path(pdf_name).stem}_elements.csv"
                input_pdf = output_dir / f"{Path(pdf_name).stem}.pdf"
                input_pdf.parent.mkdir(parents=True, exist_ok=True)
                input_pdf.write_bytes(pdf_bytes)
                if is_ocr:
                    summary = ocr_pdf(
                        input_pdf,
                        output_dir,
                        pattern=fields.get("pattern", "").strip(),
                        start_page=max(1, int(fields.get("start_page", "1"))),
                        dpi=max(72, min(400, int(fields.get("dpi", "220")))),
                    )
                    downloads = {key: f"/api/files/{category}/{job_id}/{name}" for key, name in summary.pop("downloads").items()}
                else:
                    summary = extract_pdf_elements(
                        input_pdf,
                        output_csv,
                        extract_text=fields.get("text") == "1",
                        extract_lines=fields.get("lines") == "1",
                        extract_rects=fields.get("rects") == "1",
                        logger=logger,
                    )
                    elements = summary.pop("elements")
                    downloads = {"elements": f"/api/files/{category}/{job_id}/{output_csv.name}"}
                    if fields.get("spatial") == "1":
                        spatial = analyze_spatial_relationships(
                            elements, max_distance=float(fields.get("max_distance", "100"))
                        )
                        spatial_path = output_dir / f"{Path(pdf_name).stem}_spatial.csv"
                        write_analysis_csv(spatial, spatial_path)
                        downloads["spatial"] = f"/api/files/{category}/{job_id}/{spatial_path.name}"
                        summary["spatial_relationships"] = len(spatial)
                    if fields.get("color") == "1":
                        colors = analyze_color_relationships(elements)
                        color_path = output_dir / f"{Path(pdf_name).stem}_color.csv"
                        write_analysis_csv(colors, color_path)
                        downloads["color"] = f"/api/files/{category}/{job_id}/{color_path.name}"
                        summary["color_groups"] = len(colors)
                input_pdf.unlink(missing_ok=True)
                self._json(200, {
                    "status": "completed",
                    "job_id": job_id,
                    "summary": summary,
                    "downloads": downloads,
                })
            except Exception as exc:
                logger.exception("PDF 工作流执行失败")
                self._json(400, {"error": f"PDF 工作流执行失败：{exc}"})

        def _set_pdf_backend(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 1024:
                    self._json(400, {"error": "缺少有效的后端切换设置"})
                    return
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    self._json(400, {"error": "后端设置必须为 JSON 对象"})
                    return
                enabled = payload.get("bluebeam_enabled")
                if not isinstance(enabled, bool):
                    self._json(400, {"error": "bluebeam_enabled 必须为布尔值"})
                    return
                with self.runtime_backend_lock:
                    state = self.runtime_backend_state
                    if enabled and not state["bluebeam_available"]:
                        self._json(409, {"error": "未检测到 Bluebeam Script Engine，无法启用"})
                        return
                    current = state["selected"]
                    if enabled:
                        state["selected"] = PdfBackend(
                            "bluebeam", "由网页开关启用 Bluebeam",
                            current.script_engine_path, current.revu_path,
                        )
                    else:
                        state["selected"] = PdfBackend(
                            "python", "由网页开关停用 Bluebeam，使用 Python PDF 包",
                            current.script_engine_path, current.revu_path,
                        )
                    backend_info = state["selected"].public_info()
                    backend_info["bluebeam_available"] = state["bluebeam_available"]
                self._json(200, {"status": "ready", "pdf_backend": backend_info})
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                self._json(400, {"error": f"后端设置格式错误：{exc}"})

        def _json(self, status: int, value: dict) -> None:
            data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _send_output_file(self, url_path: str) -> None:
            parsed = urlparse(url_path)
            pieces = parsed.path.strip("/").split("/")
            if len(pieces) != 5 or pieces[2] not in {"pdf_info", "pdf_ocr", "pdf_counts", "pdf_location", "pdf_marker", "copy_markups", "pdf_stamp", "frame_to_pdf", "page_replacement"} or not re.fullmatch(r"[0-9a-f]{32}", pieces[3]):
                self.send_error(404)
                return
            output_root = (self.project_root / "output" / pieces[2]).resolve()
            target = (output_root / pieces[3] / unquote(pieces[4])).resolve()
            allowed_extensions = {".csv", ".json", ".txt"} | ({".png", ".jpg", ".jpeg"} if pieces[2] == "pdf_location" else set()) | ({".fdf", ".pdf"} if pieces[2] in {"pdf_marker", "copy_markups"} else set()) | ({".zip"} if pieces[2] == "pdf_stamp" else set()) | ({".pdf"} if pieces[2] in {"frame_to_pdf", "page_replacement"} else set())
            if not target.is_relative_to(output_root) or not target.is_file() or target.suffix.lower() not in allowed_extensions:
                self.send_error(404)
                return
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            inline = pieces[2] == "pdf_location" and "inline=1" in parsed.query
            disposition = "inline" if inline else "attachment"
            self.send_header(
                "Content-Disposition",
                f"{disposition}; filename=\"download{target.suffix.lower()}\"; filename*=UTF-8''{quote(target.name)}",
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args) -> None:
            logger.info("%s - %s", self.address_string(), format % args)

    return LocalToolkitHandler
