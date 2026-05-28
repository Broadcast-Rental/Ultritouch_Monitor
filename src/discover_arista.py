"""
Discover Arista Ethernet port ifIndex values and Rx DOM sensor indices.

Usage:
  python -m src.discover_arista
  python -m src.discover_arista --host 172.21.100.2 --output arista_ports.yaml
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

from src.config import AristaPortConfig, load_config
from src.snmp_client import parse_snmp_str, snmp_walk

IF_NAME_OID = "1.3.6.1.2.1.31.1.1.1.1"
IF_DESCR_OID = "1.3.6.1.2.1.2.2.1.2"
ENT_PHYSICAL_DESCR_OID = "1.3.6.1.2.1.47.1.1.1.1.2"
ENT_PHYSICAL_NAME_OID = "1.3.6.1.2.1.47.1.1.1.1.7"
ENT_SENSOR_VALUE_OID = "1.3.6.1.2.1.99.1.1.1.4"
ENT_SENSOR_UNITS_OID = "1.3.6.1.2.1.99.1.1.1.6"


def _port_number_from_if_name(name: str) -> int | None:
    """Match Arista-style names: Ethernet3, Et3, Ethernet3/1."""
    patterns = [
        r"(?:Ethernet|Et)(\d+)(?:/\d+)?$",
        r"^(\d+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, name, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def discover_ports(host: str, port_start: int, port_end: int, snmp) -> dict[str, AristaPortConfig]:
    if_names = snmp_walk(host, IF_NAME_OID, snmp)
    if_descrs = snmp_walk(host, IF_DESCR_OID, snmp)

    by_port: dict[int, tuple[int, str]] = {}
    for suffix, val in if_names.items():
        name = parse_snmp_str(val)
        port_num = _port_number_from_if_name(name)
        if port_num is None or not (port_start <= port_num <= port_end):
            continue
        if_index = int(suffix)
        by_port[port_num] = (if_index, name)

    for suffix, val in if_descrs.items():
        if int(suffix) in {t[0] for t in by_port.values()}:
            continue
        name = parse_snmp_str(val)
        port_num = _port_number_from_if_name(name)
        if port_num is None or not (port_start <= port_num <= port_end):
            continue
        by_port.setdefault(port_num, (int(suffix), name))

    ent_descr = snmp_walk(host, ENT_PHYSICAL_DESCR_OID, snmp)
    ent_name = snmp_walk(host, ENT_PHYSICAL_NAME_OID, snmp)
    ent_units = snmp_walk(host, ENT_SENSOR_UNITS_OID, snmp)
    ent_values = snmp_walk(host, ENT_SENSOR_VALUE_OID, snmp)

    rx_by_entity_name: dict[str, int] = {}
    for suffix, val in ent_descr.items():
        descr = parse_snmp_str(val).lower()
        if "rx" not in descr or "power" not in descr:
            continue
        entity_name = parse_snmp_str(ent_name.get(suffix, ""))
        if entity_name and suffix in ent_values:
            rx_by_entity_name[entity_name.lower()] = int(suffix)

    ports: dict[str, AristaPortConfig] = {}
    for port_num in sorted(by_port):
        if_index, label = by_port[port_num]
        rx_sensor: int | None = None
        for key, sensor_idx in rx_by_entity_name.items():
            if str(port_num) in key or label.lower().replace("ethernet", "et") in key:
                rx_sensor = sensor_idx
                break
        if rx_sensor is None:
            for key, sensor_idx in rx_by_entity_name.items():
                if f"et{port_num}" in key or f"ethernet{port_num}" in key:
                    rx_sensor = sensor_idx
                    break

        ports[str(port_num)] = AristaPortConfig(
            if_index=if_index,
            rx_sensor_index=rx_sensor,
            label=label,
        )

    return ports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover Arista port and DOM sensor mapping")
    parser.add_argument("--host", help="Arista management IP")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--output", help="Write ports section to YAML file")
    parser.add_argument("--port-start", type=int, default=None)
    parser.add_argument("--port-end", type=int, default=None)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    host = args.host or cfg.arista.host
    port_start = args.port_start if args.port_start is not None else cfg.arista.port_start
    port_end = args.port_end if args.port_end is not None else cfg.arista.port_end

    print(f"Discovering Arista ports on {host} (ports {port_start}-{port_end})...")
    try:
        ports = discover_ports(host, port_start, port_end, cfg.snmp)
    except Exception as exc:
        print(f"SNMP discovery failed: {exc}", file=sys.stderr)
        return 1

    if not ports:
        print("No ports found. Check SNMP community and network reachability.", file=sys.stderr)
        return 1

    serializable = {
        p: {"if_index": c.if_index, "rx_sensor_index": c.rx_sensor_index, "label": c.label}
        for p, c in ports.items()
    }
    for port, entry in serializable.items():
        rx = entry["rx_sensor_index"]
        print(f"  Port {port}: ifIndex={entry['if_index']}, Rx sensor={rx or 'NOT FOUND'}, label={entry['label']}")

    if args.output:
        out_path = Path(args.output)
        payload = {"arista": {"ports": serializable}}
        out_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        print(f"Wrote {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
