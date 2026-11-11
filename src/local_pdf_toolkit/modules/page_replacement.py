"""Replace the leading pages of an attached PDF using Bluebeam Revu."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf import PdfWriter

from local_pdf_toolkit.modules.bluebeam import run_commands, script_string
from local_pdf_toolkit.modules.pdf_backend import PdfBackend, detect_pdf_backend


def replace_attached_front_pages(
    content_pdf: Path,
    attached_pdf: Path,
    output_pdf: Path,
    *,
    script_engine_path: str | Path | None = None,
    backend: PdfBackend | None = None,
) -> dict[str, Any]:
    """Replace the first min(content pages, attached pages) with Revu Script."""
    content_count = len(PdfReader(str(content_pdf)).pages)
    attached_count = len(PdfReader(str(attached_pdf)).pages)
    if not content_count or not attached_count:
        raise ValueError("两个 PDF 都必须至少有一页")
    replace_count = min(content_count, attached_count)
    output_pdf = output_pdf.resolve()
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    selected_backend = backend or detect_pdf_backend(output_pdf.parent)
    if selected_backend.mode == "bluebeam":
        commands = [
            f"Open({script_string(attached_pdf.resolve())})",
            f"ReplacePages({script_string(content_pdf.resolve())}, \"1-{replace_count}\", \"1-{replace_count}\")",
            f"Save({script_string(output_pdf)}, 1)",
            "Close()",
        ]
        run_commands(
            commands,
            output_pdf.parent,
            script_engine_path=script_engine_path or selected_backend.script_engine_path,
        )
    else:
        writer = PdfWriter()
        content_reader = PdfReader(str(content_pdf))
        attached_reader = PdfReader(str(attached_pdf))
        for index in range(attached_count):
            page = content_reader.pages[index] if index < replace_count else attached_reader.pages[index]
            writer.add_page(page)
        with output_pdf.open("wb") as stream:
            writer.write(stream)
    output_count = len(PdfReader(str(output_pdf)).pages)
    expected_count = attached_count
    if output_count != expected_count:
        raise RuntimeError(f"PDF 后端输出页数异常：期望 {expected_count}，实际 {output_count}")
    return {
        "output_file": output_pdf.name,
        "content_page_count": content_count,
        "attached_page_count": attached_count,
        "replaced_page_count": replace_count,
        "output_page_count": output_count,
        "expected_output_page_count": expected_count,
        "backend": selected_backend.mode,
    }
