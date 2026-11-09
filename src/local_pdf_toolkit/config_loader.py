"""加载本机工作台配置与运行上下文。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppContext:
    project_root: Path
    host: str
    port: int
    log_level: str


def load_context(project_root: Path) -> AppContext:
    """从 common.env、进程环境和 config.yaml 读取服务启动配置。"""
    root = project_root.resolve()
    _load_common_env(root / "common.env")
    config = _load_yaml(root / "config.yaml")
    app = config.get("app", {}) if isinstance(config, dict) else {}
    host = os.environ.get("WEB_HOST", str(app.get("host", "127.0.0.1")))
    port = int(os.environ.get("WEB_PORT", app.get("port", 8765)))
    log_level = os.environ.get("LOG_LEVEL", str(app.get("log_level", "INFO")))
    return AppContext(root, host, port, log_level)


def _load_common_env(env_file: Path) -> None:
    """加载简单 dotenv 文件，已有进程环境变量优先。"""
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def _load_yaml(config_file: Path) -> dict:
    if not config_file.is_file():
        return {}
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("读取 config.yaml 需要安装 PyYAML") from exc
    with config_file.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    return config if isinstance(config, dict) else {}
