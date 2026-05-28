"""Shared poller data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.poller.arista import AristaPortStatus
from src.poller.aruba import ArubaPortStatus


@dataclass
class SwitchPathStatus:
    octet: int
    ip: str
    label: str
    arista: AristaPortStatus
    aruba: ArubaPortStatus | None


@dataclass
class PollState:
    updated_at: datetime | None = None
    switches: list[SwitchPathStatus] = field(default_factory=list)
    last_error: str | None = None
    polling: bool = False
    connectivity: dict[str, Any] | None = None
