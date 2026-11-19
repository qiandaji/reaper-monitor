"""配置加载与校验测试。"""
from __future__ import annotations

import json

import pytest

from app.config import load_config


def write_config(tmp_path, data) -> str:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_load_valid_config(tmp_path):
    path = write_config(tmp_path, {"monitor_prefix": "MON "})
    cfg = load_config(path)
    assert cfg.monitor_prefix == "MON "


def test_default_prefix_when_missing(tmp_path):
    path = write_config(tmp_path, {})
    cfg = load_config(path)
    assert cfg.monitor_prefix == "MON "


def test_reject_empty_prefix(tmp_path):
    path = write_config(tmp_path, {"monitor_prefix": ""})
    with pytest.raises(ValueError):
        load_config(path)
