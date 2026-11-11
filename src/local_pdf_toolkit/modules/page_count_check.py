"""按源文件名匹配目标 PDF 并核对页数，复刻 PDFPageReplacer 工作流规则。"""

from __future__ import annotations

import csv
import json
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader


def check_uploaded_page_counts(
    source_files: list[tuple[str, bytes]], target_files: list[tuple[str, bytes]], output_dir: Path
) -> dict[str, Any]:
    """源 PDF 的 stem 必须是唯一目标 PDF stem 的前缀；输出一致项与异常项。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    targets = [(name, payload, Path(name).stem) for name, payload in target_files]
    matches: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    used: set[str] = set()
    for source_name, source_bytes in source_files:
        source_stem = Path(source_name).stem
        candidates = [(name, payload) for name, payload, stem in targets if stem.startswith(source_stem)]
        if not candidates:
            issues.append({"status":"unmatched","source_file_name":source_name,"source_page_count":None,"matched_file_name":"","matched_page_count":None,"candidates":[],"reason":"no_target_pdf_stem_startswith_source_stem"})
            continue
        if len(candidates) > 1:
            issues.append({"status":"ambiguous","source_file_name":source_name,"source_page_count":None,"matched_file_name":"","matched_page_count":None,"candidates":[name for name,_ in candidates],"reason":"multiple_target_pdf_stem_prefix_matches"})
            continue
        target_name, target_bytes = candidates[0]
        if target_name in used:
            issues.append({"status":"ambiguous","source_file_name":source_name,"source_page_count":None,"matched_file_name":target_name,"matched_page_count":None,"candidates":[target_name],"reason":"target_pdf_already_matched"})
            continue
        try:
            source_count = len(PdfReader(BytesIO(source_bytes)).pages)
            target_count = len(PdfReader(BytesIO(target_bytes)).pages)
        except Exception as exc:
            issues.append({"status":"error","source_file_name":source_name,"source_page_count":None,"matched_file_name":target_name,"matched_page_count":None,"candidates":[target_name],"reason":str(exc)})
            used.add(target_name)
            continue
        used.add(target_name)
        row = {"source_file_name":source_name,"source_page_count":source_count,"matched_file_name":target_name,"matched_page_count":target_count}
        if source_count == target_count:
            matches.append(row)
        else:
            issues.append({"status":"page_count_mismatch",**row,"candidates":[target_name],"reason":"page_count_differs"})
    report = {"source_count":len(source_files),"target_count":len(target_files),"matched_count":len(matches)+sum(issue["status"]=="page_count_mismatch" for issue in issues),"consistent_count":len(matches),"issue_count":len(issues),"matches":matches,"issues":issues}
    json_path=output_dir/"page_count_report.json"
    json_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    csv_path=output_dir/"page_count_report.csv"
    fields=["status","source_file_name","source_page_count","matched_file_name","matched_page_count","candidates","reason"]
    with csv_path.open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        writer.writerows({"status":"consistent",**row,"candidates":row["matched_file_name"],"reason":""} for row in matches)
        writer.writerows({**row,"candidates":"; ".join(row.get("candidates",[]))} for row in issues)
    return {**{k:v for k,v in report.items() if k not in {"matches","issues"}},"downloads":{"json":json_path.name,"csv":csv_path.name}}
