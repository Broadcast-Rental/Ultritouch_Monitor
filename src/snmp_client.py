"""Shared SNMP v2c helpers (pysnmp 6 asyncio API)."""

from __future__ import annotations

import asyncio
import re
import threading
from typing import Any

from pysnmp.hlapi.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    getCmd,
    nextCmd,
)

from src.config import SnmpConfig

_ENGINE = SnmpEngine()
_snmp_lock = threading.Lock()
_thread_local = threading.local()


def _loop() -> asyncio.AbstractEventLoop:
    """One event loop per thread — avoids asyncio.run() overhead/deadlocks in the poller."""
    loop = getattr(_thread_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _thread_local.loop = loop
    return loop


def _run(coro):
    return _loop().run_until_complete(coro)


def _target(host: str, snmp: SnmpConfig) -> UdpTransportTarget:
    return UdpTransportTarget(
        (host, 161),
        timeout=snmp.timeout,
        retries=snmp.retries,
    )


def _community(snmp: SnmpConfig) -> CommunityData:
    return CommunityData(snmp.community, mpModel=1)


async def _async_get(host: str, oid: str, snmp: SnmpConfig) -> Any | None:
    error_indication, error_status, _error_index, var_binds = await getCmd(
        _ENGINE,
        _community(snmp),
        _target(host, snmp),
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
    )
    if error_indication or error_status:
        return None
    return var_binds[0][1]


async def _async_walk(host: str, oid: str, snmp: SnmpConfig) -> dict[str, Any]:
    base = oid.rstrip(".")
    results: dict[str, Any] = {}
    async for error_indication, error_status, _error_index, var_binds in nextCmd(
        _ENGINE,
        _community(snmp),
        _target(host, snmp),
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
        lexicographicMode=False,
    ):
        if error_indication or error_status:
            break
        for name, val in var_binds:
            oid_str = str(name)
            if not oid_str.startswith(base):
                return results
            suffix = oid_str[len(base) :].lstrip(".")
            if suffix:
                results[suffix] = val
    return results


def snmp_get(host: str, oid: str, snmp: SnmpConfig) -> Any | None:
    with _snmp_lock:
        return _run(_async_get(host, oid, snmp))


def snmp_walk(host: str, oid: str, snmp: SnmpConfig) -> dict[str, Any]:
    with _snmp_lock:
        return _run(_async_walk(host, oid, snmp))


def parse_snmp_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value)
    match = re.search(r"-?\d+", text)
    return int(match.group()) if match else None


def parse_snmp_str(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "asOctets"):
        return bytes(value.asOctets()).decode("utf-8", errors="replace")
    return str(value)
