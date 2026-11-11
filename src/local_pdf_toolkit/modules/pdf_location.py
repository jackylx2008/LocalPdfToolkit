"""Keyword search and screenshot workflow migrated from GetLocInPdf."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from local_pdf_toolkit.modules.screenshot_engine import (
    ArrowStyle,
    BorderStyle,
    LineBoxDetectionConfig,
    capture_full_page_screenshots,
    capture_region_screenshots,
)


def capture_keyword_screenshots(
    pdf_path: Path,
    output_dir: Path,
    keywords: list[str],
    *,
    mode: str = "full_page",
    dpi: int = 220,
    region: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    """Render full-page or configured-region screenshots around PDF keywords."""
    normalized = list(dict.fromkeys(item.strip() for item in keywords if item.strip()))
    if not normalized:
        raise ValueError("请至少输入一个搜索关键词")
    if mode not in {"full_page", "region"}:
        raise ValueError("截图模式无效")
    output_dir.mkdir(parents=True, exist_ok=True)
    detection = LineBoxDetectionConfig(cache_enabled=True)
    border = BorderStyle(width=1.5, color=(230, 55, 45), opacity=0.95, fill=False)
    arrow = ArrowStyle(color=(230, 55, 45), size=16, tail_length=30)
    base = pdf_path.stem
    if mode == "region":
        if region is None:
            raise ValueError("区域模式需要提供 x0,y0,x1,y1 页面坐标")
        x0, y0, x1, y1 = region
        if x1 <= x0 or y1 <= y0:
            raise ValueError("区域坐标必须满足 x1 > x0 且 y1 > y0")
        results = capture_region_screenshots(
            str(pdf_path), normalized, str(output_dir), base,
            region_rect={"x0": x0, "y0": y0, "x1": x1, "y1": y1},
            line_box_detection=detection, border_style=border,
            arrow_style=arrow, dpi=dpi,
        )
    else:
        results = capture_full_page_screenshots(
            str(pdf_path), normalized, str(output_dir), base,
            line_box_detection=detection, border_style=border,
            arrow_style=arrow, dpi=dpi,
        )
    entries = [
        {
            "keyword": result.keyword,
            "page_number": result.page_number,
            "match_index": result.match_index,
            "file_name": Path(result.output_path).name,
        }
        for result in results
    ]
    (output_dir / "screenshots.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"count": len(entries), "screenshots": entries}
