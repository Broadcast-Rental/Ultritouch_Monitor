"""Background SNMP polling loop."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from src.config import AppConfig, AristaPortConfig, load_config
from src.connectivity import log_connectivity_report, run_connectivity_checks
from src.poller.arista import poll_arista_port
from src.poller.aruba import aruba_ip, is_present, poll_aruba
from src.poller.delta import DeltaTracker
from src.poller.models import PollState, SwitchPathStatus
from src.snmp_client import snmp_get
from src.status import log_status_summary

logger = logging.getLogger(__name__)

_SYS_UP_TIME = "1.3.6.1.2.1.1.3.0"


class PollerOrchestrator:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self.state = PollState(updated_at=datetime.now(timezone.utc))
        self._deltas = DeltaTracker(window_size=self.config.polling.error_window_polls)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="snmp-poller", daemon=True)
        self._thread.start()
        logger.info("SNMP poller thread started (interval=%ss)", self.config.polling.interval_seconds)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        interval = self.config.polling.interval_seconds
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:
                logger.exception("Poll cycle failed: %s", exc)
                with self._lock:
                    self.state.last_error = str(exc)
                    self.state.polling = False
            self._stop.wait(interval)

    def _poll_octet(self, octet: int) -> SwitchPathStatus | None:
        cfg = self.config
        port_key = str(octet)
        port_cfg: AristaPortConfig | None = cfg.arista.ports.get(port_key)
        host = aruba_ip(cfg, octet)

        arista = poll_arista_port(cfg, octet, port_cfg, self._deltas)
        aruba_present = is_present(host, cfg.snmp)
        aruba = poll_aruba(host, octet, cfg, self._deltas) if aruba_present else None

        if not aruba_present and not arista.oper_up and port_cfg is None:
            logger.debug(
                "Skip .%s: aruba absent, arista link down, no port map in config",
                octet,
            )
            return None

        if not aruba_present and arista.oper_up:
            logger.debug("Switch .%s: arista link up, aruba %s did not answer SNMP", octet, host)
        if not arista.reachable:
            logger.debug("Switch .%s: Arista SNMP failed for port %s (ifIndex %s)", octet, octet, arista.if_index)

        label = (aruba.sys_name if aruba else None) or f"Switch {octet}"
        return SwitchPathStatus(octet=octet, ip=host, label=label, arista=arista, aruba=aruba)

    def poll_once(self) -> None:
        cfg = self.config
        port_start = cfg.arista.port_start
        port_end = cfg.arista.port_end
        octets = list(range(port_start, port_end + 1))
        t0 = time.monotonic()

        connectivity = run_connectivity_checks(cfg)
        log_connectivity_report(connectivity, cfg.snmp.community)

        arista_reachable = snmp_get(cfg.arista.host, _SYS_UP_TIME, cfg.snmp) is not None
        logger.info(
            "SNMP poll starting: arista=%s reachable=%s | ports %s-%s | community=%s | timeout=%ss",
            cfg.arista.host,
            arista_reachable,
            port_start,
            port_end,
            cfg.snmp.community,
            cfg.snmp.timeout,
        )
        if not arista_reachable:
            logger.warning(
                "Cannot reach Arista at %s — check network/VLAN and SNMP community '%s'",
                cfg.arista.host,
                cfg.snmp.community,
            )

        with self._lock:
            self.state.polling = True

        paths: list[SwitchPathStatus] = []
        failures = 0
        try:
            for i, octet in enumerate(octets, start=1):
                if i == 1 or i % 5 == 0 or i == len(octets):
                    logger.info("SNMP progress: port %s (%d/%d)", octet, i, len(octets))
                try:
                    result = self._poll_octet(octet)
                    if result is not None:
                        paths.append(result)
                except Exception as exc:
                    failures += 1
                    logger.warning("Poll failed for octet %s: %s", octet, exc)
            paths.sort(key=lambda p: p.octet)
        finally:
            elapsed = time.monotonic() - t0
            with self._lock:
                self.state.switches = paths
                self.state.updated_at = datetime.now(timezone.utc)
                self.state.last_error = None
                self.state.polling = False
                self.state.connectivity = connectivity.to_dict()
                snapshot = PollState(
                    updated_at=self.state.updated_at,
                    switches=list(self.state.switches),
                    last_error=self.state.last_error,
                    polling=False,
                    connectivity=self.state.connectivity,
                )

            logger.info(
                "SNMP poll finished in %.1fs: %d switches shown, %d octets scanned, %d errors",
                elapsed,
                len(paths),
                len(octets),
                failures,
            )
            log_status_summary(snapshot, cfg)

    def get_state(self) -> PollState:
        with self._lock:
            return PollState(
                updated_at=self.state.updated_at,
                switches=list(self.state.switches),
                last_error=self.state.last_error,
                polling=self.state.polling,
                connectivity=self.state.connectivity,
            )
