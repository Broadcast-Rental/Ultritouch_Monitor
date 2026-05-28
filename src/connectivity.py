"""ICMP ping and TCP probes to separate network vs service issues."""

from __future__ import annotations

import logging
import platform
import socket
import subprocess
from dataclasses import dataclass, field
from typing import Any

from src.config import AppConfig
from src.poller.aruba import aruba_ip
from src.snmp_client import snmp_get

logger = logging.getLogger(__name__)

_SYS_UP_TIME = "1.3.6.1.2.1.1.3.0"


@dataclass
class HostCheck:
    name: str
    host: str
    ping: bool | None
    snmp: bool | None = None
    tcp_port: int | None = None
    tcp_open: bool | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "host": self.host,
            "ping": self.ping,
            "snmp": self.snmp,
            "tcpPort": self.tcp_port,
            "tcpOpen": self.tcp_open,
            "note": self.note,
        }


@dataclass
class ConnectivityReport:
    checked_at: str | None = None
    hosts: list[HostCheck] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkedAt": self.checked_at,
            "hosts": [h.to_dict() for h in self.hosts],
        }


def ping_host(host: str, timeout_sec: float = 1.0) -> bool | None:
    """
    Return True/False for reachability, or None if ping is not available.
    """
    timeout_sec = max(0.2, timeout_sec)
    wait = max(1, int(timeout_sec))
    system = platform.system().lower()

    try:
        if "windows" in system:
            cmd = ["ping", "-n", "1", "-w", str(int(timeout_sec * 1000)), host]
        else:
            cmd = ["ping", "-c", "1", "-W", str(wait), host]
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout_sec + 3,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return False
    except OSError as exc:
        logger.debug("ping %s failed: %s", host, exc)
        return False


def tcp_port_open(host: str, port: int, timeout_sec: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError:
        return False


def run_connectivity_checks(cfg: AppConfig) -> ConnectivityReport:
    from datetime import datetime, timezone

    ping_timeout = 1.0
    hosts: list[HostCheck] = []

    arista_ping = ping_host(cfg.arista.host, ping_timeout)
    arista_snmp = snmp_get(cfg.arista.host, _SYS_UP_TIME, cfg.snmp) is not None
    arista_note = _diagnose(arista_ping, arista_snmp, None)
    hosts.append(
        HostCheck(
            name="arista",
            host=cfg.arista.host,
            ping=arista_ping,
            snmp=arista_snmp,
            note=arista_note,
        )
    )

    sample_aruba = aruba_ip(cfg, cfg.aruba.host_start)
    aruba_ping = ping_host(sample_aruba, ping_timeout)
    aruba_snmp = snmp_get(sample_aruba, _SYS_UP_TIME, cfg.snmp) is not None
    hosts.append(
        HostCheck(
            name=f"aruba_sample (.{cfg.aruba.host_start})",
            host=sample_aruba,
            ping=aruba_ping,
            snmp=aruba_snmp,
            note=_diagnose(aruba_ping, aruba_snmp, None),
        )
    )

    for i, host in enumerate(cfg.ember.hosts):
        label = "stageracer_primary" if i == 0 else f"stageracer_fallback_{i}"
        eping = ping_host(host, ping_timeout)
        tcp_ok = tcp_port_open(host, cfg.ember.port, timeout_sec=3.0)
        hosts.append(
            HostCheck(
                name=label,
                host=host,
                ping=eping,
                tcp_port=cfg.ember.port,
                tcp_open=tcp_ok,
                note=_diagnose(eping, None, tcp_ok, service="Ember+ TCP"),
            )
        )

    return ConnectivityReport(
        checked_at=datetime.now(timezone.utc).isoformat(),
        hosts=hosts,
    )


def _diagnose(
    ping: bool | None,
    snmp: bool | None,
    tcp_open: bool | None,
    service: str = "SNMP",
) -> str:
    if ping is None:
        return "ping not available in container"
    if not ping:
        return "no ICMP (routing/firewall or host down)"
    if snmp is False:
        return f"ping OK but {service} failed (community/firewall/service)"
    if tcp_open is False:
        return f"ping OK but {service} port closed or filtered"
    if snmp is True or tcp_open is True:
        return "OK"
    return "ping OK"


def log_connectivity_report(report: ConnectivityReport, snmp_community: str = "public") -> None:
    logger.info("=== Network connectivity (ping / SNMP / TCP) ===")
    for h in report.hosts:
        ping_s = "n/a" if h.ping is None else ("OK" if h.ping else "FAIL")
        parts = [f"ping={ping_s}"]
        if h.snmp is not None:
            parts.append(f"snmp={'OK' if h.snmp else 'FAIL'}")
        if h.tcp_port is not None:
            parts.append(f"tcp:{h.tcp_port}={'OK' if h.tcp_open else 'FAIL'}")
        logger.info("  %-22s %-17s %s | %s", h.name, h.host, " ".join(parts), h.note)

    arista = next((x for x in report.hosts if x.name == "arista"), None)
    if arista and arista.ping is False:
        logger.warning(
            "Ping to Arista failed — this is a L3/network problem from inside the container, "
            "not SNMP config."
        )
    elif arista and arista.ping and arista.snmp is False:
        logger.warning(
            "Ping to Arista OK but SNMP failed — check community '%s' and SNMP enabled on switch.",
            snmp_community,
        )

    sr = next((x for x in report.hosts if x.name == "stageracer_primary"), None)
    if sr and sr.ping is False:
        logger.warning("Ping to Stageracer failed — check 172.21.50.x routing from container.")
    elif sr and sr.ping and sr.tcp_open is False:
        logger.warning(
            "Ping to Stageracer OK but TCP %s closed — wrong Ember+ port or service not running.",
            sr.tcp_port,
        )
