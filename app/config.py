"""配置与设置：data/config.json 校验 + 环境变量。"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger("reaper_monitor.config")


class MonitorConfig(BaseModel):
    """监听轨道由 REAPER 实际轨道名动态发现：名称以 monitor_prefix 开头的轨道 = 一条监听母线。"""

    monitor_prefix: str = Field(default="MON ", min_length=1)


def load_config(path: str | Path) -> MonitorConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    try:
        return MonitorConfig.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"配置文件 {path} 无效: {exc}") from exc


def _load_dotenv(project_root: Path) -> None:
    """极简 .env 加载（无第三方依赖）：只填缺失的变量，不覆盖已有环境变量。"""
    dotenv = project_root / ".env"
    if not dotenv.exists():
        return
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    http_host: str
    http_port: int
    osc_reaper_host: str
    osc_reaper_port: int
    osc_listen_host: str
    osc_listen_port: int
    reastream_host: str
    reastream_port: int
    config_path: Path
    static_dir: Path

    @classmethod
    def from_env(cls, project_root: Path) -> "Settings":
        _load_dotenv(project_root)

        def env(name: str, default: str) -> str:
            return os.environ.get(name, default)

        return cls(
            http_host=env("RMP_HTTP_HOST", "0.0.0.0"),
            http_port=int(env("RMP_HTTP_PORT", "61390")),
            osc_reaper_host=env("RMP_OSC_REAPER_HOST", "127.0.0.1"),
            osc_reaper_port=int(env("RMP_OSC_REAPER_PORT", "9212")),
            osc_listen_host=env("RMP_OSC_LISTEN_HOST", "0.0.0.0"),
            osc_listen_port=int(env("RMP_OSC_LISTEN_PORT", "9213")),
            reastream_host=env("RMP_REASTREAM_HOST", "0.0.0.0"),
            reastream_port=int(env("RMP_REASTREAM_PORT", "58710")),
            config_path=(project_root / env("RMP_CONFIG_PATH", "data/config.json")).resolve(),
            static_dir=(project_root / "app" / "static").resolve(),
        )
