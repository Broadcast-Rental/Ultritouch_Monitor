"""Load configuration from YAML and environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class SnmpConfig(BaseModel):
    community: str = "public"
    timeout: float = 0.5
    retries: int = 0


class AristaPortConfig(BaseModel):
    if_index: int
    rx_sensor_index: int | None = None
    label: str | None = None


class AristaConfig(BaseModel):
    host: str = "172.21.100.2"
    port_start: int = 3
    port_end: int = 26
    ports: dict[str, AristaPortConfig] = Field(default_factory=dict)


class ArubaConfig(BaseModel):
    subnet_base: str = "172.21.100"
    host_start: int = 3
    host_end: int = 50
    uplink_ifindex: int = 26


class EmberConfig(BaseModel):
    hosts: list[str] = Field(default_factory=lambda: ["172.21.50.21", "172.21.50.22"])
    port: int = 9000
    sr2_name_match: str = "SR2"
    fiber_root: str = "997"
    state_file: str = "data/ember_state.json"


class ThresholdConfig(BaseModel):
    orange_dbm: float = -18.0
    red_dbm: float = -25.0
    recent_error_seconds: int = 300


class PollingConfig(BaseModel):
    interval_seconds: int = 15
    error_window_polls: int = 3


class ApiConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class AppConfig(BaseModel):
    snmp: SnmpConfig = Field(default_factory=SnmpConfig)
    arista: AristaConfig = Field(default_factory=AristaConfig)
    aruba: ArubaConfig = Field(default_factory=ArubaConfig)
    ember: EmberConfig = Field(default_factory=EmberConfig)
    thresholds: ThresholdConfig = Field(default_factory=ThresholdConfig)
    polling: PollingConfig = Field(default_factory=PollingConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path or os.environ.get("CONFIG_PATH", "config.yaml"))
    data: dict[str, Any] = {}
    if config_path.is_file():
        with config_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    if community := os.environ.get("SNMP_COMMUNITY"):
        data.setdefault("snmp", {})["community"] = community
    if ember_host := os.environ.get("EMBER_HOST"):
        data.setdefault("ember", {})["hosts"] = [h.strip() for h in ember_host.split(",") if h.strip()]

    return AppConfig.model_validate(data)


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]
