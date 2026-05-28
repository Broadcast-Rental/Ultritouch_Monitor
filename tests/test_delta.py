from src.poller.delta import DeltaTracker


def test_delta_detects_increasing_errors():
    t = DeltaTracker(window_size=3)
    t.record("k", 0, 0)
    t.record("k", 0, 0)
    assert not t.errors_increasing("k")
    t.record("k", 5, 0)
    assert t.errors_increasing("k")


def test_delta_first_sample_zero():
    t = DeltaTracker(window_size=3)
    d = t.record("x", 100, 50)
    assert d == 0
