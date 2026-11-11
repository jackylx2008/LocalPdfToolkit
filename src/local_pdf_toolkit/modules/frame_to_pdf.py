"""Prepare photographed pages and create a multipage PDF with the selected backend."""

from __future__ import annotations

import io
import re
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps
from pypdf import PdfReader
import fitz

from local_pdf_toolkit.modules.bluebeam import run_commands, script_string
from local_pdf_toolkit.modules.pdf_backend import PdfBackend, detect_pdf_backend


DPI = 600
A4 = (4960, 7016)
A3 = (7016, 9922)


def _prepare_page(image_bytes: bytes) -> tuple[Image.Image, str]:
    with Image.open(io.BytesIO(image_bytes)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    width, height = image.size
    if width > height:
        a4, a3 = (A4[1], A4[0]), (A3[1], A3[0])
    else:
        a4, a3 = A4, A3
    target_size = a3 if max(width, height) > max(a4) * 1.5 else a4
    paper = "A3" if target_size == a3 else "A4"
    image.thumbnail(target_size, Image.Resampling.LANCZOS)
    page = Image.new("RGB", target_size, (255, 255, 255))
    page.paste(image, ((target_size[0] - image.width) // 2, (target_size[1] - image.height) // 2))
    image.close()
    return page, paper


def images_to_pdf_with_revu(
    image_files: list[tuple[str, bytes]],
    output_dir: Path,
    output_stem: str,
    *,
    script_engine_path: str | Path | None = None,
    backend: PdfBackend | None = None,
) -> dict[str, Any]:
    """Apply Frame2Pdf A3/A4 layout and use Bluebeam or Python to build the PDF."""
    if not image_files:
        raise ValueError("请选择至少一张 JPEG 图片")
    if any(Path(name).suffix.lower() not in {".jpg", ".jpeg"} for name, _ in image_files):
        raise ValueError("Frame2Pdf 只接收 JPEG 图片")
    safe_stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", output_stem).strip(" .") or "images"
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_backend = backend or detect_pdf_backend(output_dir)
    ordered = sorted(image_files, key=lambda item: item[0].casefold())
    output_pdf = output_dir / f"{safe_stem}.pdf"
    paper_sizes: list[str] = []
    with tempfile.TemporaryDirectory(prefix="frame_pages_", dir=output_dir) as temporary:
        page_paths: list[Path] = []
        for index, (name, payload) in enumerate(ordered, start=1):
            page, paper = _prepare_page(payload)
            page_path = Path(temporary) / f"page_{index:04d}.jpg"
            page.save(page_path, "JPEG", quality=100, subsampling=0, dpi=(DPI, DPI))
            page.close()
            page_paths.append(page_path)
            paper_sizes.append(paper)
        if selected_backend.mode == "bluebeam":
            args = ", ".join(script_string(path) for path in page_paths)
            run_commands(
                [
                    f"OpenImage({args})",
                    f"Save({script_string(output_pdf)}, 1)",
                    "Close()",
                ],
                output_dir,
                script_engine_path=script_engine_path or selected_backend.script_engine_path,
                timeout=max(900, len(page_paths) * 45),
            )
        else:
            document = fitz.open()
            try:
                for page_path in page_paths:
                    with Image.open(page_path) as prepared:
                        pixel_width, pixel_height = prepared.size
                    page = document.new_page(
                        width=pixel_width * 72 / DPI,
                        height=pixel_height * 72 / DPI,
                    )
                    page.insert_image(page.rect, filename=str(page_path))
                document.save(output_pdf, garbage=4, deflate=True)
            finally:
                document.close()
    if not output_pdf.is_file():
        raise RuntimeError(f"{selected_backend.label} 处理已结束，但没有生成 PDF")
    page_count = len(PdfReader(str(output_pdf)).pages)
    if page_count != len(ordered):
        raise RuntimeError(f"PDF 后端输出页数 {page_count} 与图片数量 {len(ordered)} 不一致")
    return {
        "pdf_file": output_pdf.name,
        "page_count": page_count,
        "source_image_count": len(ordered),
        "a3_pages": paper_sizes.count("A3"),
        "a4_pages": paper_sizes.count("A4"),
        "dpi": DPI,
        "backend": selected_backend.mode,
    }
