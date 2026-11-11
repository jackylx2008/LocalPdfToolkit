"""PDF 页面 OCR 与正则内容核对，整合 GetPdfText/PDFPageReplacer 的可本地流程。"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import fitz
from rapidocr_onnxruntime import RapidOCR


_ENGINE: RapidOCR | None = None


def ocr_pdf(
    pdf_path: Path,
    output_dir: Path,
    *,
    pattern: str = "",
    start_page: int = 1,
    dpi: int = 220,
) -> dict[str, Any]:
    """逐页渲染并 OCR；如提供正则，则返回 OCR 匹配与文件名核对结果。"""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = RapidOCR()
    output_dir.mkdir(parents=True, exist_ok=True)
    document = fitz.open(pdf_path)
    pages: list[dict[str, Any]] = []
    regex = re.compile(pattern) if pattern else None
    try:
        for page_index in range(max(0, start_page - 1), document.page_count):
            page = document[page_index]
            scale = dpi / 72
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image = pix.samples
            import numpy as np
            array = np.frombuffer(image, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            if pix.n == 4:
                array = array[:, :, :3]
            result, _ = _ENGINE(array)
            lines = [str(item[1]).strip() for item in (result or []) if len(item) > 1 and str(item[1]).strip()]
            text = "\n".join(lines)
            matches = list(dict.fromkeys(match.group(0) for match in regex.finditer(text))) if regex else []
            pages.append({"page": page_index + 1, "text": text, "matches": matches})
    finally:
        document.close()

    stem = pdf_path.stem
    text_path = output_dir / f"{stem}_ocr.txt"
    text_path.write_text("\n\n".join(f"--- 第 {row['page']} 页 ---\n{row['text']}" for row in pages), encoding="utf-8")
    json_path = output_dir / f"{stem}_ocr.json"
    json_path.write_text(json.dumps({"pdf": pdf_path.name, "pages": pages}, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = output_dir / f"{stem}_ocr_matches.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["page", "match"])
        for row in pages:
            writer.writerows((row["page"], match) for match in row["matches"])
    filename_match = re.search(pattern, pdf_path.name) if pattern else None
    found = list(dict.fromkeys(match for row in pages for match in row["matches"]))
    return {
        "page_count": len(pages),
        "matched_values": found,
        "filename_value": filename_match.group(0) if filename_match else None,
        "filename_matches_content": bool(filename_match and filename_match.group(0) in found),
        "downloads": {"text": text_path.name, "json": json_path.name, "matches": csv_path.name},
    }
