"""Convert ENTITY-SENSOR-MIB values to dBm."""

from __future__ import annotations

import math
import re
from typing import Any

from src.snmp_client import parse_snmp_int, parse_snmp_str, snmp_get

ENT_SENSOR_TYPE = "1.3.6.1.2.1.99.1.1.1.1"
ENT_SENSOR_SCALE = "1.3.6.1.2.1.99.1.1.1.2"
ENT_SENSOR_PRECISION = "1.3.6.1.2.1.99.1.1.1.3"
ENT_SENSOR_VALUE = "1.3.6.1.2.1.99.1.1.1.4"
ENT_SENSOR_UNITS = "1.3.6.1.2.1.99.1.1.1.6"

# entPhySensorType: other(1) often used for dB/dBm displays
SENSOR_TYPE_OTHER = 1
SENSOR_TYPE_DBM = 14  # vendor-specific; treat units string as authority


def read_rx_dbm(host: str, sensor_index: int, snmp) -> float | None:
    """Read Rx optical power in dBm from entPhySensorTable."""
    base = str(sensor_index)
    raw_value = snmp_get(host, f"{ENT_SENSOR_VALUE}.{base}", snmp)
    if raw_value is None:
        return None

    units = parse_snmp_str(snmp_get(host, f"{ENT_SENSOR_UNITS}.{base}", snmp) or "").lower()
    scale = parse_snmp_int(snmp_get(host, f"{ENT_SENSOR_SCALE}.{base}", snmp)) or 0
    precision = parse_snmp_int(snmp_get(host, f"{ENT_SENSOR_PRECISION}.{base}", snmp)) or 0

    numeric = _coerce_float(raw_value)
    if numeric is None:
        return None

    if "dbm" in units:
        return numeric

    # RFC 3433 scaled value
    if precision:
        numeric = numeric * (10 ** (-precision))
    if scale:
        numeric = numeric * (10**scale)

    if "db" in units and "dbm" not in units:
        return numeric

    # watts -> dBm
    if numeric > 0:
        return 10 * math.log10(numeric * 1000)  # W to mW to dBm
    return None


def _coerce_float(value: Any) -> float | None:
    text = str(value)
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group())
