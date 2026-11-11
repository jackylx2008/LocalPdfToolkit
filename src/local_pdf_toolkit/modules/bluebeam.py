"""Local Bluebeam Revu 20 eXtreme Script Engine adapter."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


DEFAULT_SCRIPT_ENGINE = Path(
    r"C:\Program Files\Bluebeam Software\Bluebeam Revu\20\Revu\ScriptEngine.exe"
)


def script_string(value: str | Path) -> str:
    """Quote a Revu Script string, using its documented vertical-bar escape."""
    text = str(value)
    if "\r" in text or "\n" in text:
        raise ValueError("Bluebeam 脚本参数不能包含换行")
    return '"' + text.replace("|", "||").replace('"', '|"') + '"'


def run_commands(
    commands: list[str],
    work_dir: Path,
    *,
    script_engine_path: str | Path | None = None,
    timeout: int = 900,
) -> str:
    """Run commands through ScriptEngine with an explicit document context."""
    configured = script_engine_path or os.environ.get("BLUEBEAM_SCRIPT_ENGINE_PATH")
    executable = Path(configured).expanduser() if configured else DEFAULT_SCRIPT_ENGINE
    if not executable.is_file():
        raise FileNotFoundError(f"找不到 Bluebeam Script Engine：{executable}")
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    script_path = work_dir / "bluebeam_job.bci"
    script_path.write_text("\n".join(commands) + "\n", encoding="utf-8-sig")
    command = f"Script({script_string(script_path)})"
    try:
        result = subprocess.run(
            [str(executable), "-d", command],
            cwd=work_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Bluebeam 处理超过 {timeout} 秒，脚本：{script_path}") from exc
    output = (result.stdout or "") + (result.stderr or "")
    (work_dir / "bluebeam_script.log").write_text(output, encoding="utf-8")
    if result.returncode != 0 or "Run.SUCCESS" not in output:
        raise RuntimeError(f"Bluebeam 脚本执行失败（退出码 {result.returncode}）：{output[-2500:]}")
    return output
