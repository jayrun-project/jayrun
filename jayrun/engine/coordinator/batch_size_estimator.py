from __future__ import annotations


class BatchSizeEstimator:
    def __init__(
        self,
        alpha: float = 0.2,
        utilization: float = 0.9,
        minimum: int = 1,
        maximum: int = 1024,
    ) -> None:
        self._alpha = alpha
        self._utilization = utilization
        self._minimum = minimum
        self._maximum = maximum
        self._estimate = minimum

    def update(
        self,
        active_sessions: int,
    ) -> int:
        target = int(active_sessions * self._utilization)
        target = max(
            self._minimum,
            min(target, self._maximum),
        )

        self._estimate = int(self._alpha * target + (1 - self._alpha) * self._estimate)

        self._estimate = max(
            self._minimum,
            min(self._estimate, self._maximum),
        )

        return self._estimate

    @property
    def value(self) -> int:
        return self._estimate
