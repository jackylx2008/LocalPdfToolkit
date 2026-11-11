"""Register a source drawing and prepare transferred markups for Bluebeam."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz

from local_pdf_toolkit.modules.pdf_marker import _fdf_document, _fdf_text
from local_pdf_toolkit.modules.registration import (
    RegistrationSettings,
    estimate_page_registration,
    map_page_point,
)
from local_pdf_toolkit.modules.pdf_backend import PdfBackend, detect_pdf_backend


def _pdf_color(color: tuple[float, ...] | None, default: str) -> str:
    if not color:
        return default
    return "[" + " ".join(f"{max(0.0, min(1.0, float(value))):.4f}" for value in color[:3]) + "]"


def prepare_transferred_markups(
    source_path: Path,
    target_path: Path,
    output_dir: Path,
    settings: RegistrationSettings | None = None,
    *,
    backend: PdfBackend | None = None,
) -> dict[str, Any]:
    """Map Polygon, PolyLine and MM/RC FreeText markups into a target FDF.

    The output is an annotation interchange file. Revu imports and saves it into
    the target document so the toolkit never edits the PDF directly.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_backend = backend or detect_pdf_backend(output_dir)
    with fitz.open(source_path) as source, fitz.open(target_path) as target:
        if source.page_count != 1 or target.page_count != 1:
            raise ValueError("批注迁移首版要求源图与目标图各为一个 PDF 页面")
        source_page, target_page = source[0], target[0]
        result = estimate_page_registration(
            source_page, target_page, settings or RegistrationSettings()
        )
        target_height = float(target_page.mediabox.height)
        annots: list[str] = []
        counts = {"Polygon": 0, "PolyLine": 0, "FreeText": 0}
        annot = source_page.first_annot
        while annot:
            kind = annot.type[1]
            content = annot.info.get("content", "") or ""
            if kind in {"Polygon", "PolyLine"}:
                points = [
                    map_page_point(fitz.Point(point), source_page, target_page, result.transform)
                    for point in (annot.vertices or [])
                ]
                if len(points) >= (3 if kind == "Polygon" else 2):
                    if selected_backend.mode == "python":
                        colors = annot.colors or {}
                        stroke_color = tuple(colors["stroke"]) if colors.get("stroke") else (1, 0, 0)
                        if kind == "Polygon":
                            copied = target_page.add_polygon_annot(points)
                            fill_color = tuple(colors["fill"]) if colors.get("fill") else None
                            copied.set_colors(stroke=stroke_color, fill=fill_color)
                        else:
                            copied = target_page.add_polyline_annot(points)
                            copied.set_colors(stroke=stroke_color)
                        copied.set_border(width=max(0.25, float(annot.border.get("width", 1.0)) * result.transform.linear_scale))
                        copied.set_info({"content": content, "title": annot.info.get("title", "")})
                        copied.update()
                    pdf_points = [(point.x, target_height - point.y) for point in points]
                    x0, y0 = min(p[0] for p in pdf_points), min(p[1] for p in pdf_points)
                    x1, y1 = max(p[0] for p in pdf_points), max(p[1] for p in pdf_points)
                    subtype = "Polygon" if kind == "Polygon" else "PolyLine"
                    coordinates = " ".join(f"{x:.3f} {y:.3f}" for x, y in pdf_points)
                    colors = annot.colors or {}
                    stroke = _pdf_color(colors.get("stroke"), "[1 0 0]")
                    fill = _pdf_color(colors.get("fill"), "[1 1 1]")
                    width = max(0.25, float(annot.border.get("width", 1.0)) * result.transform.linear_scale)
                    extra = f"/IC {fill}" if subtype == "Polygon" and colors.get("fill") else ""
                    annots.append(
                        f"<< /Type /Annot /Subtype /{subtype} /Page 0 "
                        f"/Rect [{x0:.3f} {y0:.3f} {x1:.3f} {y1:.3f}] "
                        f"/Vertices [{coordinates}] /C {stroke} {extra} "
                        f"/BS << /W {width:.3f} /S /S >> /Contents {_fdf_text(content)} >>"
                    )
                    counts[subtype] += 1
            elif kind == "FreeText" and content.strip().upper() in {"MM", "RC"}:
                corners = [
                    map_page_point(point, source_page, target_page, result.transform)
                    for point in (annot.rect.tl, annot.rect.tr, annot.rect.bl, annot.rect.br)
                ]
                x0 = min(point.x for point in corners)
                x1 = max(point.x for point in corners)
                y0 = target_height - max(point.y for point in corners)
                y1 = target_height - min(point.y for point in corners)
                if selected_backend.mode == "python":
                    rect = fitz.Rect(x0, target_height - y1, x1, target_height - y0)
                    copied = target_page.add_freetext_annot(
                        rect,
                        content.strip().upper(),
                        fontsize=14,
                        fontname="helv",
                        text_color=(1, 0, 0),
                        rotate=target_page.rotation,
                    )
                    copied.set_info({"content": content.strip().upper(), "title": annot.info.get("title", "")})
                    copied.update()
                annots.append(
                    f"<< /Type /Annot /Subtype /FreeText /Page 0 "
                    f"/Rect [{x0:.3f} {y0:.3f} {x1:.3f} {y1:.3f}] "
                    f"/C [1 1 1] /Contents {_fdf_text(content.strip().upper())} >>"
                )
                counts["FreeText"] += 1
            annot = annot.next
        if not annots:
            raise ValueError("源 PDF 中没有可迁移的 Polygon、PolyLine 或 MM/RC 文字批注")
        fdf_path = output_dir / f"{target_path.stem}_transferred_markups.fdf"
        fdf_path.write_bytes(_fdf_document(annots))
        summary = {
            "annotation_file": fdf_path.name,
            "counts": counts,
            "registration": result.to_dict(),
            "source_file": source_path.name,
            "target_file": target_path.name,
            "backend": selected_backend.mode,
        }
        if selected_backend.mode == "python":
            output_pdf = output_dir / f"{target_path.stem}_markups.pdf"
            target.save(output_pdf, garbage=4, deflate=True)
            summary["output_pdf"] = output_pdf.name
        return summary
