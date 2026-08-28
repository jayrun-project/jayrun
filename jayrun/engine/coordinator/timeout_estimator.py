from __future__ import annotations

import time


class TimeoutEstimator:
    def __init__(
        self,
        alpha: float = 0.2,
        factor: float = 0.5,
        minimum: float = 1e-9,
        maximum: float = 50e-3,
    ) -> None:
        self._alpha = alpha
        self._factor = factor
        self._minimum = minimum
        self._maximum = maximum

        self._arrival_interval = 0.0
        self._last_arrival: float | None = None

    def update(self) -> None:
        now = time.monotonic()

        if self._last_arrival is None:
            self._last_arrival = now
            return

        interval = now - self._last_arrival
        self._last_arrival = now

        if self._arrival_interval == 0.0:
            self._arrival_interval = interval
        else:
            self._arrival_interval = (
                self._alpha * interval + (1 - self._alpha) * self._arrival_interval
            )

    def estimate(
        self,
        batch_size: int,
        queue_size: int,
    ) -> float:
        if queue_size >= batch_size:
            return self._minimum

        timeout = self._arrival_interval * batch_size * self._factor

        return max(
            self._minimum,
            min(timeout, self._maximum),
        )
