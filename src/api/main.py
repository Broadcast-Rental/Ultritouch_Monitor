"""FastAPI application: status API and kiosk static files."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.config import load_config, project_root
from src.connectivity import log_connectivity_report, run_connectivity_checks
from src.logging_setup import configure_logging
from src.poller.orchestrator import PollerOrchestrator
from src.status import build_status

logger = logging.getLogger(__name__)

_orchestrator: PollerOrchestrator | None = None
_cfg = load_config()


def _web_dir() -> Path:
    return project_root() / "web"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _orchestrator
    configure_logging()

    logger.info("Ultritouch Fiber Monitor starting")
    logger.info(
        "Config: arista=%s ports %s-%s | aruba %s.%s-%s | ember hosts=%s | poll every %ss",
        _cfg.arista.host,
        _cfg.arista.port_start,
        _cfg.arista.port_end,
        _cfg.aruba.subnet_base,
        _cfg.aruba.host_start,
        _cfg.aruba.host_end,
        ",".join(_cfg.ember.hosts),
        _cfg.polling.interval_seconds,
    )
    if not _cfg.arista.ports:
        logger.warning(
            "arista.ports is empty — run: python -m src.discover_arista --output arista_ports.yaml "
            "and merge into config.yaml for Rx dBm readings"
        )

    _orchestrator = PollerOrchestrator(_cfg)
    logger.info("Running startup connectivity check (ping / SNMP / TCP)...")
    report = await asyncio.get_event_loop().run_in_executor(None, run_connectivity_checks, _cfg)
    log_connectivity_report(report, _cfg.snmp.community)
    _orchestrator.start()
    logger.info("Kiosk UI: http://0.0.0.0:%s/  |  API: /api/status  |  Logs: docker compose logs -f", _cfg.api.port)

    yield

    logger.info("Shutting down")
    if _orchestrator:
        _orchestrator.stop()


app = FastAPI(title="Ultritouch Fiber Monitor", lifespan=lifespan)

web_dir = _web_dir()
if web_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")


@app.get("/")
async def index():
    index_path = web_dir / "index.html"
    if index_path.is_file():
        return FileResponse(index_path)
    return {"message": "Ultritouch Fiber Monitor API"}


@app.get("/health")
async def health():
    poll = _orchestrator.get_state() if _orchestrator else None
    ok = poll is not None and poll.updated_at is not None and not getattr(poll, "polling", False)
    age: float | None = None
    if poll and poll.updated_at:
        age = (datetime.now(timezone.utc) - poll.updated_at).total_seconds()
        ok = ok and age < _cfg.polling.interval_seconds * 3
    ember_path = Path(_cfg.ember.state_file)
    if not ember_path.is_absolute():
        ember_path = project_root() / ember_path
    ember_ok = ember_path.is_file()
    if not ok:
        logger.debug(
            "Health not OK: polling=%s age=%ss switches=%d ember_file=%s",
            getattr(poll, "polling", None) if poll else None,
            age,
            len(poll.switches) if poll else 0,
            ember_ok,
        )
    return {
        "ok": ok,
        "snmpPoller": ok,
        "emberStateFile": ember_ok,
        "pollAgeSeconds": age,
        "switchCount": len(poll.switches) if poll else 0,
    }


@app.get("/api/status")
async def api_status():
    if not _orchestrator:
        return build_status(type("S", (), {"switches": [], "updated_at": None, "last_error": "Poller not started"})())
    return build_status(_orchestrator.get_state(), _cfg)


def main():
    import uvicorn

    configure_logging()
    cfg = load_config()
    uvicorn.run(
        "src.api.main:app",
        host=cfg.api.host,
        port=cfg.api.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
