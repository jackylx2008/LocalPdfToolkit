"""基于 GetPdfInfo 原项目行为的矢量元素提取能力。"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

import pdfplumber


FIELDNAMES = [
    "page", "type", "text", "x0", "y0", "x1", "y1", "width", "height",
    "fontname", "size", "stroking_color", "non_stroking_color",
]


def extract_pdf_elements(
    pdf_path: Path,
    output_csv: Path,
    *,
    extract_text: bool = True,
    extract_lines: bool = True,
    extract_rects: bool = True,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """提取字符、线条和矩形，与 GetPdfInfo 字段结构兼容并写出 CSV。"""
    log = logger or logging.getLogger(__name__)
    rows: list[dict[str, Any]] = []
    page_count = 0
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages, start=1):
            if extract_text:
                for char in page.chars:
                    rows.append(_element(page_number, "text", char.get("text", ""), char))
            if extract_lines:
                for index, line in enumerate(page.lines):
                    rows.append(_element(page_number, "line", f"line_{index}", line))
            if extract_rects:
                for index, rect in enumerate(page.rects):
                    rows.append(_element(page_number, "rect", f"rect_{index}", rect))

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    log.info("PDF 元素提取完成：%s 页，%s 条记录，输出 %s", page_count, len(rows), output_csv)
    counts: dict[str, int] = {"text": 0, "line": 0, "rect": 0}
    for row in rows:
        counts[row["type"]] = counts.get(row["type"], 0) + 1
    return {"page_count": page_count, "element_count": len(rows), "counts": counts, "elements": rows}


def analyze_spatial_relationships(
    elements: list[dict[str, Any]], *, max_distance: float = 100.0
) -> list[dict[str, Any]]:
    """复用 GetPdfInfo 的中心距离、重叠和对齐分析规则。"""
    import math

    relationships: list[dict[str, Any]] = []
    for index, first in enumerate(elements):
        for second in elements[index + 1:]:
            if first["page"] != second["page"]:
                continue
            cx1, cy1 = (first["x0"] + first["x1"]) / 2, (first["y0"] + first["y1"]) / 2
            cx2, cy2 = (second["x0"] + second["x1"]) / 2, (second["y0"] + second["y1"]) / 2
            distance = round(math.hypot(cx2 - cx1, cy2 - cy1), 2)
            if distance > max_distance:
                continue
            tolerance = 5.0
            relationships.append({
                "element1_page": first["page"], "element1_type": first["type"],
                "element1_text": first["text"][:20], "element1_x0": first["x0"],
                "element1_y0": first["y0"], "element2_page": second["page"],
                "element2_type": second["type"], "element2_text": second["text"][:20],
                "element2_x0": second["x0"], "element2_y0": second["y0"],
                "distance": distance,
                "is_overlapping": not (first["x1"] < second["x0"] or second["x1"] < first["x0"] or first["y1"] < second["y0"] or second["y1"] < first["y0"]),
                "left_aligned": abs(first["x0"] - second["x0"]) < tolerance,
                "right_aligned": abs(first["x1"] - second["x1"]) < tolerance,
                "top_aligned": abs(first["y0"] - second["y0"]) < tolerance,
                "bottom_aligned": abs(first["y1"] - second["y1"]) < tolerance,
                "h_center_aligned": abs(cx1 - cx2) < tolerance,
                "v_center_aligned": abs(cy1 - cy2) < tolerance,
            })
    return relationships


def analyze_color_relationships(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按描边色和填充色统计跨页元素，与 GetPdfInfo 分组一致。"""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for element in elements:
        key = (element.get("stroking_color", ""), element.get("non_stroking_color", ""))
        groups.setdefault(key, []).append(element)
    return [
        {
            "stroking_color": key[0], "non_stroking_color": key[1],
            "element_count": len(group),
            "pages": ",".join(map(str, sorted({item["page"] for item in group}))),
            "types": ",".join(sorted({item["type"] for item in group})),
        }
        for key, group in groups.items() if len(group) > 1
    ]


def write_analysis_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    if rows:
        fields = list(rows[0])
    else:
        fields = []
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as stream:
        if fields:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


def _element(page_number: int, kind: str, label: str, source: dict[str, Any]) -> dict[str, Any]:
    def number(key: str) -> float:
        try:
            return round(float(source.get(key) or 0), 2)
        except (TypeError, ValueError):
            return 0.0

    def color(key: str) -> str:
        value = source.get(key)
        if value is None:
            return ""
        if isinstance(value, (tuple, list)):
            return ",".join(str(part) for part in value)
        return str(value)

    return {
        "page": page_number,
        "type": kind,
        "text": label,
        "x0": number("x0"),
        "y0": number("y0"),
        "x1": number("x1"),
        "y1": number("y1"),
        "width": number("width"),
        "height": number("height"),
        "fontname": source.get("fontname", "") if kind == "text" else "",
        "size": number("size") if kind == "text" else 0,
        "stroking_color": color("stroking_color"),
        "non_stroking_color": color("non_stroking_color"),
    }
