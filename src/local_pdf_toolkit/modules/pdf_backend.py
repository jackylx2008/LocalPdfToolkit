"""Detect the local PDF engine once and expose one portable runtime choice."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PdfBackend:
    """Selected PDF implementation and optional local Bluebeam paths."""

    mode: str
    reason: str
    script_engine_path: Path | None = None
    revu_path: Path | None = None

    @property
    def label(self) -> str:
        return "Bluebeam Revu 20 eXtreme" if self.mode == "bluebeam" else "Python PDF packages"

    def public_info(self) -> dict[str, str | None]:
        return {
            "mode": self.mode,
            "label": self.label,
            "reason": self.reason,
        }


def detect_pdf_backend(
    project_root: Path,
    *,
    requested_mode: str = "auto",
    script_engine_path: str | Path | None = None,
    revu_path: str | Path | None = None,
) -> PdfBackend:
    """Choose Bluebeam only when its eXtreme Script Engine is available."""
    mode = requested_mode.strip().lower()
    if mode not in {"auto", "bluebeam", "python"}:
        raise ValueError("pdf_backend 须为 auto、bluebeam 或 python")

    candidates = _bluebeam_candidates(project_root, script_engine_path, revu_path)
    detected_engine = next((candidate for candidate in candidates if candidate.is_file()), None)
    detected_revu = _resolve_revu(detected_engine, revu_path) if detected_engine else None

    if mode == "python":
        return PdfBackend("python", "由配置指定 Python 后端", detected_engine, detected_revu)
    if mode == "bluebeam":
        if detected_engine is None:
            raise FileNotFoundError(
                "配置指定 Bluebeam 后端，但找不到 Bluebeam Revu eXtreme Script Engine。"
                "请检查 BLUEBEAM_SCRIPT_ENGINE_PATH。"
            )
        return PdfBackend("bluebeam", "由配置指定，且检测到 Script Engine", detected_engine, detected_revu)
    if detected_engine:
        return PdfBackend("bluebeam", "自动检测到 Bluebeam Revu eXtreme Script Engine", detected_engine, detected_revu)
    return PdfBackend("python", "未检测到 Bluebeam Script Engine，自动使用 Python 后端")


def _bluebeam_candidates(
    project_root: Path,
    script_engine_path: str | Path | None,
    revu_path: str | Path | None,
) -> list[Path]:
    candidates: list[Path] = []
    for value in (
        script_engine_path,
        os.environ.get("BLUEBEAM_SCRIPT_ENGINE_PATH"),
    ):
        if value and str(value).strip():
            candidates.append(Path(value).expanduser())

    configured_revu = revu_path or os.environ.get("BLUEBEAM_REVU_PATH")
    if configured_revu and str(configured_revu).strip():
        revu = Path(configured_revu).expanduser()
        candidates.append(revu.with_name("ScriptEngine.exe"))
        candidates.append(revu.parent / "ScriptEngine.exe")

    if os.name == "nt":
        program_roots = [
            Path(os.environ[key])
            for key in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)")
            if os.environ.get(key)
        ]
        for root in dict.fromkeys(program_roots):
            candidates.append(
                root / "Bluebeam Software" / "Bluebeam Revu" / "20" / "Revu" / "ScriptEngine.exe"
            )
    located = shutil.which("ScriptEngine.exe") or shutil.which("ScriptEngine")
    if located:
        candidates.append(Path(located))

    normalized: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key not in seen:
            seen.add(key)
            normalized.append(candidate)
    return normalized


def _resolve_revu(engine: Path | None, configured: str | Path | None) -> Path | None:
    if configured and str(configured).strip():
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return candidate
    if engine is None:
        return None
    for candidate in (engine.with_name("Revu.exe"), engine.parent / "Revu.exe"):
        if candidate.is_file():
            return candidate
    return None
