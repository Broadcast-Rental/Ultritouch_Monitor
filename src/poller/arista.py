"""Poll Arista core switch ports."""

from __future__ import annotations

from dataclasses import dataclass

from src.config import AppConfig, AristaPortConfig
from src.poller.delta import DeltaTracker
from src.poller.sensor import read_rx_dbm
from src.snmp_client import parse_snmp_int, snmp_get

IF_OPER_STATUS = "1.3.6.1.2.1.2.2.1.8"
IF_IN_ERRORS = "1.3.6.1.2.1.2.2.1.14"
IF_OUT_ERRORS = "1.3.6.1.2.1.2.2.1.16"

IF_OPER_UP = 1


@dataclass
class AristaPortStatus:
    port: int
    if_index: int
    label: str | None
    reachable: bool
    oper_up: bool | None
    rx_dbm: float | None
    in_errors: int | None
    out_errors: int | None
    error_delta: int
    errors_increasing: bool
    message: str


def _guess_if_index(port: int) -> int:
    """Fallback when discovery has not been run (Arista often uses 1000 + port)."""
    return 1000 + port


def poll_arista_port(
    cfg: AppConfig,
    port: int,
    port_cfg: AristaPortConfig | None,
    deltas: DeltaTracker,
) -> AristaPortStatus:
    host = cfg.arista.host
    snmp = cfg.snmp
    if_index = port_cfg.if_index if port_cfg else _guess_if_index(port)
    label = port_cfg.label if port_cfg else f"Ethernet{port}"
    key = f"arista:{host}:{if_index}"

    oper = parse_snmp_int(snmp_get(host, f"{IF_OPER_STATUS}.{if_index}", snmp))
    in_err = parse_snmp_int(snmp_get(host, f"{IF_IN_ERRORS}.{if_index}", snmp))
    out_err = parse_snmp_int(snmp_get(host, f"{IF_OUT_ERRORS}.{if_index}", snmp))

    reachable = oper is not None
    oper_up = oper == IF_OPER_UP if oper is not None else None
    error_delta = deltas.record(key, in_err, out_err) if reachable else 0
    increasing = deltas.errors_increasing(key) if reachable else False

    rx_dbm: float | None = None
    if port_cfg and port_cfg.rx_sensor_index:
        rx_dbm = read_rx_dbm(host, port_cfg.rx_sensor_index, snmp)

    message = "OK"
    if not reachable:
        message = "Arista unreachable"
    elif not oper_up:
        message = "No link"
    elif increasing:
        message = "Errors increasing"
    elif rx_dbm is not None and rx_dbm < cfg.thresholds.orange_dbm:
        message = "Weak signal"

    return AristaPortStatus(
        port=port,
        if_index=if_index,
        label=label,
        reachable=reachable,
        oper_up=oper_up,
        rx_dbm=rx_dbm,
        in_errors=in_err,
        out_errors=out_err,
        error_delta=error_delta,
        errors_increasing=increasing,
        message=message,
    )
