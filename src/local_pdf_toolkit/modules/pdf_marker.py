"""Prepare keyword markups for import into Bluebeam Revu."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import fitz
from local_pdf_toolkit.modules.pdf_backend import PdfBackend, detect_pdf_backend


def _fdf_text(value: str) -> str:
    if all(ord(character) < 128 for character in value):
        escaped = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\r", " ").replace("\n", " ")
        return f"({escaped})"
    return "<FEFF" + value.encode("utf-16-be").hex().upper() + ">"


def _fdf_document(annotations: list[str]) -> bytes:
    """Serialize a minimal FDF 1.2 file with a valid cross-reference table."""
    prefix = b"%FDF-1.2\n%\xe2\xe3\xcf\xd3\n"
    obj = ("1 0 obj\n<< /FDF << /Annots [" + " ".join(annotations)
           + "] >> >>\nendobj\n").encode("ascii")
    xref_offset = len(prefix) + len(obj)
    xref = b"xref\n0 2\n0000000000 65535 f \n" + f"{len(prefix):010d} 00000 n \n".encode("ascii")
    trailer = b"trailer\n<< /Root 1 0 R /Size 2 >>\nstartxref\n" + str(xref_offset).encode("ascii") + b"\n%%EOF\n"
    return prefix + obj + xref + trailer


def prepare_keyword_markups(
    pdf_path: Path,
    keywords: list[str],
    output_dir: Path,
    *,
    backend: PdfBackend | None = None,
) -> dict[str, Any]:
    """Find selectable text and emit a standard FDF annotation interchange file.

    Revu imports the FDF and performs the actual PDF modification when the user
    imports it through Markups List > Markups > Import.
    """
    unique = list(dict.fromkeys(word.strip() for word in keywords if word.strip()))
    if not unique:
        raise ValueError("请至少提供一个关键词")
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_backend = backend or detect_pdf_backend(output_dir)
    document = fitz.open(pdf_path)
    try:
        if document.needs_pass:
            raise ValueError("PDF 已加密，当前流程无法读取")
        annotations: list[str] = []
        rows: list[dict[str, Any]] = []
        for page_index, page in enumerate(document):
            height = float(page.mediabox.height)
            for keyword in unique:
                rects = page.search_for(keyword)
                for match_index, rect in enumerate(rects, start=1):
                    # PyMuPDF text-search rectangles use unrotated page coordinates.
                    left, top = float(rect.x0), height - float(rect.y1)
                    right, bottom = float(rect.x1), height - float(rect.y0)
                    annotations.append(
                        "<< /Type /Annot /Subtype /Highlight "
                        f"/Rect [{left:.3f} {top:.3f} {right:.3f} {bottom:.3f}] "
                        f"/QuadPoints [{left:.3f} {bottom:.3f} {right:.3f} {bottom:.3f} "
                        f"{left:.3f} {top:.3f} {right:.3f} {top:.3f}] "
                        f"/F 4 /C [1 1 0] /CA 0.35 /Page {page_index} "
                        f"/Contents {_fdf_text(keyword)} >>"
                    )
                    rows.append({"page": page_index + 1, "keyword": keyword, "match": match_index,
                                 "x0": round(rect.x0, 3), "y0": round(rect.y0, 3),
                                 "x1": round(rect.x1, 3), "y1": round(rect.y1, 3)})
                    if selected_backend.mode == "python":
                        highlight = page.add_highlight_annot(rect)
                        highlight.set_colors(stroke=(1, 1, 0))
                        highlight.set_opacity(0.35)
                        highlight.update()
        fdf_path = output_dir / f"{pdf_path.stem}_keyword_markups.fdf"
        fdf_path.write_bytes(_fdf_document(annotations))
        report_path = output_dir / f"{pdf_path.stem}_keyword_matches.csv"
        with report_path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=["page", "keyword", "match", "x0", "y0", "x1", "y1"])
            writer.writeheader()
            writer.writerows(rows)
        result = {
            "match_count": len(rows),
            "page_count": document.page_count,
            "annotation_file": fdf_path.name,
            "report_file": report_path.name,
            "backend": selected_backend.mode,
        }
        if selected_backend.mode == "python":
            output_pdf = output_dir / f"{pdf_path.stem}_marked.pdf"
            if rows:
                document.save(output_pdf, garbage=4, deflate=True)
                result["output_pdf"] = output_pdf.name
            else:
                result["output_pdf"] = None
        return result
    finally:
        document.close()
