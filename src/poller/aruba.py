"""Poll Aruba distribution switch uplinks."""

from __future__ import annotations

from dataclasses import dataclass

from src.config import AppConfig
from src.poller.delta import DeltaTracker
from src.snmp_client import parse_snmp_int, parse_snmp_str, snmp_get

SYS_UP_TIME = "1.3.6.1.2.1.1.3.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
IF_OPER_STATUS = "1.3.6.1.2.1.2.2.1.8"
IF_IN_ERRORS = "1.3.6.1.2.1.2.2.1.14"
IF_OUT_ERRORS = "1.3.6.1.2.1.2.2.1.16"

IF_OPER_UP = 1


@dataclass
class ArubaPortStatus:
    host: str
    octet: int
    sys_name: str | None
    reachable: bool
    uplink_ifindex: int
    oper_up: bool | None
    in_errors: int | None
    out_errors: int | None
    error_delta: int
    errors_increasing: bool
    message: str


def aruba_ip(cfg: AppConfig, octet: int) -> str:
    return f"{cfg.aruba.subnet_base}.{octet}"


def is_present(host: str, snmp) -> bool:
    return snmp_get(host, SYS_UP_TIME, snmp) is not None


def poll_aruba(host: str, octet: int, cfg: AppConfig, deltas: DeltaTracker) -> ArubaPortStatus:
    snmp = cfg.snmp
    ifindex = cfg.aruba.uplink_ifindex
    key = f"aruba:{host}:{ifindex}"

    if not is_present(host, snmp):
        return ArubaPortStatus(
            host=host,
            octet=octet,
            sys_name=None,
            reachable=False,
            uplink_ifindex=ifindex,
            oper_up=None,
            in_errors=None,
            out_errors=None,
            error_delta=0,
            errors_increasing=False,
            message="Switch offline",
        )

    sys_name = parse_snmp_str(snmp_get(host, SYS_NAME, snmp) or "")
    oper = parse_snmp_int(snmp_get(host, f"{IF_OPER_STATUS}.{ifindex}", snmp))
    in_err = parse_snmp_int(snmp_get(host, f"{IF_IN_ERRORS}.{ifindex}", snmp))
    out_err = parse_snmp_int(snmp_get(host, f"{IF_OUT_ERRORS}.{ifindex}", snmp))

    oper_up = oper == IF_OPER_UP if oper is not None else None
    error_delta = deltas.record(key, in_err, out_err)
    increasing = deltas.errors_increasing(key)

    message = "OK"
    if not oper_up:
        message = "No link"
    elif increasing:
        message = "Errors increasing"

    return ArubaPortStatus(
        host=host,
        octet=octet,
        sys_name=sys_name or None,
        reachable=True,
        uplink_ifindex=ifindex,
        oper_up=oper_up,
        in_errors=in_err,
        out_errors=out_err,
        error_delta=error_delta,
        errors_increasing=increasing,
        message=message,
    )
