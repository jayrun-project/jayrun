from __future__ import annotations


class ExecutionTracker:
    def __init__(self, total_steps: int) -> None:
        self._total_steps = total_steps
        self._finished_steps = 0
        self._skipped_steps = 0

    def restart(self) -> None:
        self._finished_steps = 0
        self._skipped_steps = 0

    @property
    def finished_steps(self) -> int:
        return self._finished_steps

    @property
    def skipped_steps(self) -> int:
        return self._skipped_steps

    @property
    def completed_steps(self) -> int:
        return self._finished_steps + self._skipped_steps

    @property
    def remaining_steps(self) -> int:
        return self._total_steps - self.completed_steps

    def finished(self, count: int = 1) -> None:
        self._finished_steps += count

    def skipped(self, count: int = 1) -> None:
        self._skipped_steps += count

    @property
    def is_done(self) -> bool:
        return self.completed_steps == self._total_steps
