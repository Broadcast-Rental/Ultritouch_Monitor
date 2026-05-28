"""Merge poll results into API-facing status with severity colors."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from src.config import AppConfig, load_config
from src.poller.arista import AristaPortStatus
from src.poller.aruba import ArubaPortStatus
from src.poller.models import PollState, SwitchPathStatus

logger = logging.getLogger(__name__)

StatusColor = Literal["green", "orange", "red", "gray"]


def _severity_arista(port: AristaPortStatus, cfg: AppConfig) -> StatusColor:
    if not port.reachable:
        return "red"
    if port.oper_up is False:
        return "red"
    if port.errors_increasing:
        return "orange"
    if port.rx_dbm is not None:
        if port.rx_dbm < cfg.thresholds.red_dbm:
            return "red"
        if port.rx_dbm < cfg.thresholds.orange_dbm:
            return "orange"
    return "green"


def _severity_aruba(port: ArubaPortStatus) -> StatusColor:
    if not port.reachable:
        return "red"
    if port.oper_up is False:
        return "red"
    if port.errors_increasing:
        return "orange"
    return "green"


def _worst(*colors: StatusColor) -> StatusColor:
    order = {"red": 3, "orange": 2, "green": 1, "gray": 0}
    return max(colors, key=lambda c: order.get(c, 0))


def _serialize_arista(p: AristaPortStatus, cfg: AppConfig) -> dict[str, Any]:
    color = _severity_arista(p, cfg)
    return {
        "port": p.port,
        "ifIndex": p.if_index,
        "label": p.label,
        "operUp": p.oper_up,
        "rxDbm": p.rx_dbm,
        "inErrors": p.in_errors,
        "outErrors": p.out_errors,
        "errorsIncreasing": p.errors_increasing,
        "message": p.message,
        "status": color,
    }


def _serialize_aruba(p: ArubaPortStatus) -> dict[str, Any]:
    return {
        "host": p.host,
        "operUp": p.oper_up,
        "uplinkIfIndex": p.uplink_ifindex,
        "inErrors": p.in_errors,
        "outErrors": p.out_errors,
        "errorsIncreasing": p.errors_increasing,
        "message": p.message,
        "status": _severity_aruba(p),
    }


def _serialize_switch(path: SwitchPathStatus, cfg: AppConfig) -> dict[str, Any]:
    arista_color = _severity_arista(path.arista, cfg)
    aruba_color = _severity_aruba(path.aruba) if path.aruba else "gray"
    combined = _worst(arista_color, aruba_color)

    return {
        "ip": path.ip,
        "octet": path.octet,
        "label": path.label,
        "status": combined,
        "summary": _assistant_summary(combined, path),
        "arista": _serialize_arista(path.arista, cfg),
        "aruba": _serialize_aruba(path.aruba) if path.aruba else None,
    }


def _assistant_summary(color: StatusColor, path: SwitchPathStatus) -> str:
    if color == "green":
        return "OK"
    if path.arista.oper_up is False or (path.aruba and path.aruba.oper_up is False):
        return "No link"
    if path.arista.errors_increasing or (path.aruba and path.aruba.errors_increasing):
        return "Unstable"
    if path.arista.rx_dbm is not None and path.arista.message == "Weak signal":
        return "Weak signal"
    if path.aruba and not path.aruba.reachable:
        return "Switch offline"
    return "Check fiber"


def load_ember_state(cfg: AppConfig) -> dict[str, Any]:
    from src.config import project_root

    path = Path(cfg.ember.state_file)
    if not path.is_absolute():
        path = project_root() / path
    if not path.is_file():
        return {"online": False, "message": "Ember+ poller not ready", "trunks": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read Ember state from %s: %s", path, exc)
        return {"online": False, "message": "Ember+ state unreadable", "trunks": []}


def build_status(poll: PollState, cfg: AppConfig | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    switches = [_serialize_switch(s, cfg) for s in poll.switches]
    ember = load_ember_state(cfg)

    colors: list[StatusColor] = [s["status"] for s in switches]
    for trunk in ember.get("trunks") or []:
        colors.append(trunk.get("status", "gray"))
    if not ember.get("online"):
        colors.append("red")

    overall = _worst(*(colors or ["gray"]))

    updated = poll.updated_at.isoformat() if poll.updated_at else None

    return {
        "updatedAt": updated,
        "overallStatus": overall,
        "pollError": poll.last_error,
        "connectivity": poll.connectivity,
        "stageracer": ember,
        "switches": switches,
    }


def log_status_summary(poll: PollState, cfg: AppConfig) -> None:
    """Write a human-readable status summary to the log after each poll."""
    status = build_status(poll, cfg)
    overall = status["overallStatus"]
    switches = status["switches"]
    sr = status["stageracer"]

    logger.info(
        "=== Status summary: overall=%s | switches=%d | stageracer online=%s ===",
        overall.upper(),
        len(switches),
        sr.get("online"),
    )

    if poll.last_error:
        logger.error("Last poll error: %s", poll.last_error)

    if sr.get("online"):
        logger.info(
            "Stageracer: name=%s host=%s trunks=%d",
            sr.get("name"),
            sr.get("host"),
            len(sr.get("trunks") or []),
        )
        for trunk in sr.get("trunks") or []:
            logger.info(
                "  Trunk %s: %s | sync=%s | power=%s dBm | lastError=%ss",
                trunk.get("id"),
                trunk.get("summary"),
                trunk.get("sync"),
                trunk.get("powerDbm"),
                trunk.get("lastErrorSeconds"),
            )
    else:
        logger.warning("Stageracer: OFFLINE — %s", sr.get("message", "unknown"))

    if not switches:
        logger.warning(
            "No switches in dashboard. Typical causes: "
            "cannot reach 172.21.100.x from this host (try Docker host network), "
            "wrong SNMP community, or no links up on Arista ports %s-%s",
            cfg.arista.port_start,
            cfg.arista.port_end,
        )
    else:
        for sw in switches:
            ar = sw["arista"]
            ab = sw.get("aruba")
            aruba_part = "no aruba poll"
            if ab:
                aruba_part = f"aruba={ab['status']} ({ab['message']})"
            logger.info(
                "  Switch .%s %s [%s]: %s | arista=%s oper=%s rx=%s | %s",
                sw["octet"],
                sw["ip"],
                sw["status"],
                sw["summary"],
                ar["status"],
                ar.get("operUp"),
                f"{ar['rxDbm']:.1f}dBm" if ar.get("rxDbm") is not None else "n/a",
                aruba_part,
            )

    if overall == "red" and not switches and not sr.get("online"):
        logger.warning(
            "UI shows PROBLEM because nothing is reachable. "
            "Is this machine on the flypack network (172.21.x)?"
        )
