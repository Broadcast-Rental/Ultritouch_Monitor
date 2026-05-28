from datetime import datetime, timezone

from src.config import AppConfig, ThresholdConfig
from src.poller.arista import AristaPortStatus
from src.poller.aruba import ArubaPortStatus
from src.poller.models import PollState
from src.status import build_status, _severity_arista, _worst


def test_worst_color():
    assert _worst("green", "orange") == "orange"
    assert _worst("green", "red") == "red"


def test_arista_weak_signal_orange():
    cfg = AppConfig(thresholds=ThresholdConfig(orange_dbm=-18, red_dbm=-25))
    port = AristaPortStatus(
        port=3,
        if_index=1003,
        label="Et3",
        reachable=True,
        oper_up=True,
        rx_dbm=-20,
        in_errors=0,
        out_errors=0,
        error_delta=0,
        errors_increasing=False,
        message="Weak signal",
    )
    assert _severity_arista(port, cfg) == "orange"


def test_build_status_empty():
    poll = PollState(updated_at=datetime.now(timezone.utc), switches=[])
    out = build_status(poll)
    assert "switches" in out
    assert "stageracer" in out
