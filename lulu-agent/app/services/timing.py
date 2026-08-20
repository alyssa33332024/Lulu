from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("lulu.timing")


class StepWatch:
    """Collect named step durations and emit one summary line."""

    def __init__(self, name: str, **meta: Any) -> None:
        self.name = name
        self.meta = meta
        self._t0 = time.perf_counter()
        self._last = self._t0
        self.steps: list[tuple[str, float]] = []

    def mark(self, label: str) -> float:
        now = time.perf_counter()
        ms = (now - self._last) * 1000
        self.steps.append((label, ms))
        self._last = now
        return ms

    def lap(self, label: str, started: float) -> float:
        ms = (time.perf_counter() - started) * 1000
        self.steps.append((label, ms))
        return ms

    @property
    def total_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000

    def log(self, **extra: Any) -> None:
        parts = [f"{label}={ms:.0f}ms" for label, ms in self.steps]
        meta = {**self.meta, **extra, "total_ms": f"{self.total_ms:.0f}"}
        meta_s = " ".join(f"{k}={v}" for k, v in meta.items() if v not in (None, ""))
        logger.warning("[timing] %s %s | %s", self.name, meta_s, " ".join(parts))
