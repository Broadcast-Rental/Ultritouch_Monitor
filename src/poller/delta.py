"""Counter delta tracking and error-trend detection."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class CounterSample:
    in_errors: int | None
    out_errors: int | None


@dataclass
class DeltaTracker:
    """Track interface error counter deltas over a sliding window of polls."""

    window_size: int = 3
    _history: dict[str, deque[CounterSample]] = field(default_factory=dict)

    def record(self, key: str, in_errors: int | None, out_errors: int | None) -> int:
        """
        Record a sample and return total error delta since previous poll
        (0 if first sample or counters unavailable).
        """
        sample = CounterSample(in_errors=in_errors, out_errors=out_errors)
        history = self._history.setdefault(key, deque(maxlen=self.window_size))
        delta = 0
        if history:
            prev = history[-1]
            if in_errors is not None and prev.in_errors is not None:
                d = in_errors - prev.in_errors
                if d > 0:
                    delta += d
            if out_errors is not None and prev.out_errors is not None:
                d = out_errors - prev.out_errors
                if d > 0:
                    delta += d
        history.append(sample)
        return delta

    def errors_increasing(self, key: str) -> bool:
        """True if any poll in the window had a positive error delta."""
        history = self._history.get(key)
        if not history or len(history) < 2:
            return False
        for i in range(1, len(history)):
            prev, curr = history[i - 1], history[i]
            if prev.in_errors is not None and curr.in_errors is not None:
                if curr.in_errors > prev.in_errors:
                    return True
            if prev.out_errors is not None and curr.out_errors is not None:
                if curr.out_errors > prev.out_errors:
                    return True
        return False

    def clear(self, key: str) -> None:
        self._history.pop(key, None)
