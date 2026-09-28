"""Opt-in, non-destructive safety admission for full context evidence.

The budget counts history-producing admissions and retained detail, not RSS.
Mandatory completion/cleanup is retained for already admitted sessions and the
graph boundary; the limit is an admission ceiling, not an exact final entry count. Explicit ContextRecords have separate limits.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from .limits import ContextHistoryLimitError

if TYPE_CHECKING:
    from .snapshot import ContextSnapshot


class _HistoryBudget:
    def __init__(self, limit: int | None) -> None:
        self.limit = limit
        self._used = 0
        self._lock = threading.Lock()

    @property
    def exhausted(self) -> bool:
        if self.limit is None:
            return False
        with self._lock:
            return self._used >= self.limit

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    def error(self) -> ContextHistoryLimitError:
        return ContextHistoryLimitError(
            f"context history admission budget {self.limit} exhausted; "
            "accepted evidence is retained and admitted work is drained"
        )

    def admit(self) -> bool:
        if self.limit is None:
            return True
        with self._lock:
            if self._used >= self.limit:
                return False
            self._used += 1
            return True

    def consume(self) -> None:
        if not self.admit():
            raise self.error()

    def account(self, count: int = 1) -> None:
        # Never stop cleanup or lose factual evidence for already admitted work.
        if self.limit is not None:
            with self._lock:
                self._used += count

    def restore(self, snapshot: ContextSnapshot) -> None:
        if self.limit is not None:
            with self._lock:
                self._used = max(self._used, self.cost(snapshot))

    @staticmethod
    def terminal_allowance(step_count: int, artifact_count: int) -> int:
        """Receive-only tail for accepted graph cleanup; not reusable admission."""
        return 64 + 16 * step_count + 4 * artifact_count

    @staticmethod
    def cost(snapshot: ContextSnapshot) -> int:
        return (len(snapshot.history) + len(snapshot.reports)
                + sum(len(report.attempts) + sum(len(a.records) for a in report.attempts)
                      for report in snapshot.reports)
                + sum(len(result.history) for _, result in snapshot.artifacts))
