"""Prepare the legacy number-change stamp as Bluebeam-importable annotations."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import fitz

from local_pdf_toolkit.modules.pdf_marker import _fdf_document, _fdf_text
from local_pdf_toolkit.modules.pdf_backend import PdfBackend, detect_pdf_backend


def _read_mapping(data: bytes, filename: str) -> dict[str, str]:
    if filename.lower().endswith(".csv"):
        text = data.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
    elif filename.lower().endswith(".xlsx"):
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise ValueError("读取 XLSX 需要安装 openpyxl") from exc
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheet = workbook.active
        values = sheet.iter_rows(values_only=True)
        headers = [str(value or "").strip() for value in next(values, ())]
        rows = [dict(zip(headers, row)) for row in values]
    else:
        raise ValueError("编号映射表须为 CSV 或 XLSX")
    mappings: dict[str, str] = {}
    for row in rows:
        old = str(row.get("旧编号", "") or "").strip()
        new = str(row.get("新编号", "") or "").strip()
        if old and new:
            mappings[old] = new
    if not mappings:
        raise ValueError("映射表中未找到“旧编号”和“新编号”列或有效数据")
    return mappings


def prepare_pdf_stamps(
    pdf_files: list[tuple[str, bytes]],
    mapping_name: str,
    mapping_bytes: bytes,
    output_dir: Path,
    *,
    backend: PdfBackend | None = None,
) -> dict[str, Any]:
    """Create Bluebeam FDFs or Python-marked PDF copies from an old/new map."""
    mappings = _read_mapping(mapping_bytes, mapping_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_backend = backend or detect_pdf_backend(output_dir)
    report: list[dict[str, Any]] = []
    fdf_payloads: list[tuple[str, bytes]] = []
    pdf_payloads: list[Path] = []
    for filename, payload in pdf_files:
        old = Path(filename).stem.strip()
        new = mappings.get(old)
        if not new:
            report.append({"file": filename, "status": "unmatched", "old": old, "new": ""})
            continue
        if old == new:
            report.append({"file": filename, "status": "unchanged", "old": old, "new": new})
            continue
        with fitz.open(stream=payload, filetype="pdf") as document:
            if not len(document) or document.needs_pass:
                raise ValueError(f"无法读取 PDF 或 PDF 需要密码：{filename}")
            page = document[0]
            width, height = float(page.rect.width), float(page.rect.height)
            font_size = height / 50
            strings = [f"旧编号：{old}", f"新编号：{new}"]
            annotations = []
            for index, value in enumerate(strings):
                y_top = height * 0.05 - (index + 1) * (font_size + 5)
                rect = fitz.Rect(width * 2 / 3, y_top, width - 8, y_top + font_size * 1.2)
                rect = rect * page.derotation_matrix if page.rotation else rect
                if selected_backend.mode == "python":
                    markup = page.add_freetext_annot(
                        rect,
                        value,
                        fontsize=font_size,
                        fontname="china-s",
                        text_color=(1, 0, 0),
                    )
                    markup.set_border(width=0)
                    markup.update()
                else:
                    media_height = float(page.mediabox.height)
                    coordinates = [rect.x0, media_height - rect.y1, rect.x1, media_height - rect.y0]
                    annotations.append(
                        "<< /Type /Annot /Subtype /FreeText /Page 0 "
                        f"/Rect [{coordinates[0]:.3f} {coordinates[1]:.3f} {coordinates[2]:.3f} {coordinates[3]:.3f}] "
                        f"/Contents {_fdf_text(value)} /DA (/Helv {font_size:.3f} Tf 1 0 0 rg) "
                        "/C [1 0 0] /F 4 /Q 0 /Border [0 0 0] >>"
                    )
            if selected_backend.mode == "python":
                pdf_output = output_dir / f"{Path(filename).stem}_stamped.pdf"
                document.save(pdf_output, garbage=4, deflate=True)
                pdf_payloads.append(pdf_output)
            else:
                fdf_payloads.append((f"{Path(filename).stem}_stamp.fdf", _fdf_document(annotations)))
            report.append({"file": filename, "status": f"ready_{selected_backend.mode}", "old": old, "new": new,
                           "page": 1, "position": "x=2/3 page width, y=95% page height"})
    report_path = output_dir / "pdf_stamp_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    zip_path = output_dir / ("pdf_stamp_bluebeam_import.zip" if selected_backend.mode == "bluebeam" else "pdf_stamp_python_pdfs.zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in fdf_payloads:
            archive.writestr(name, payload)
        for pdf_path in pdf_payloads:
            archive.write(pdf_path, pdf_path.name)
        archive.write(report_path, report_path.name)
    return {"pdf_count": len(pdf_files), "fdf_count": len(fdf_payloads), "output_pdf_count": len(pdf_payloads),
            "unmatched_count": sum(row["status"] == "unmatched" for row in report),
            "unchanged_count": sum(row["status"] == "unchanged" for row in report),
            "zip_file": zip_path.name, "report_file": report_path.name, "backend": selected_backend.mode}
