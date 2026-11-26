from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..._snapshot_compat import restore_fields
from ...context.step_reference import StepReference
from ...registry.context_state import ContextState
from ...registry.context_status import ContextHistoryEntry
from ..execution.records import ExecutionOutcome, ExecutionReport


@dataclass(frozen=True, slots=True)
class ExecutionStatistics:
    """Cumulative session outcomes and work, including evicted step reports."""

    finished: int = 0
    skipped: int = 0
    failed: int = 0
    cancelled: int = 0
    executions: int = 0
    attempts: int = 0

    @property
    def report_count(self) -> int:
        return self.finished + self.skipped + self.failed + self.cancelled

    def _covers(self, other: ExecutionStatistics) -> bool:
        return (self.finished >= other.finished and self.skipped >= other.skipped
                and self.failed >= other.failed and self.cancelled >= other.cancelled
                and self.executions >= other.executions and self.attempts >= other.attempts)

    def _including(self, reports: tuple[ExecutionReport, ...]) -> ExecutionStatistics:
        finished, skipped = self.finished, self.skipped
        failed, cancelled = self.failed, self.cancelled
        executions, attempts = self.executions, self.attempts
        for report in reports:
            match report.outcome:
                case ExecutionOutcome.FINISHED:
                    finished += 1
                case ExecutionOutcome.SKIPPED:
                    skipped += 1
                case ExecutionOutcome.FAILED:
                    failed += 1
                case ExecutionOutcome.CANCELLED:
                    cancelled += 1
            executions += report.execution_count
            attempts += len(report.attempts)
        return ExecutionStatistics(finished, skipped, failed, cancelled, executions, attempts)


@dataclass(frozen=True, slots=True)
class ContextReport:
    """Immutable terminal report for one submitted context.

    Attributes:
        context_id: Probabilistically unique 62-bit logical context identifier.
        state: Terminal context state.
        revision: Final monotonic context revision.
        iteration_count: Number of graph iterations that started.
        stop_requested: Whether the owner accepted graceful iteration stopping.
            Independent of the final state: normal drain is FINISHED, and failure
            or abort retains its actual outcome. Zero iterations means no work
            began, even for FINISHED.
        created_at: Submission timestamp.
        updated_at: Timestamp of the final context update.
        validated_at: Validation-completion timestamp, if reached.
        started_at: Execution-start timestamp, if reached.
        finished_at: Terminal-state timestamp.
        history: Ordered lifecycle and iteration history.
        executions: Retained step reports in runtime recording order.
        execution_statistics: Lifetime totals when bounded native history is enabled.
        history_omitted: Number of lifecycle entries preceding the retained history.
        failure: Context failure, if any.
        failed_step: Graph step associated with the failure, if any.
    """

    __setstate__ = restore_fields

    context_id: int
    state: ContextState
    revision: int
    iteration_count: int
    stop_requested: bool
    created_at: datetime
    updated_at: datetime
    validated_at: datetime | None
    started_at: datetime | None
    finished_at: datetime
    history: tuple[ContextHistoryEntry, ...]
    executions: tuple[ExecutionReport, ...]
    failure: Exception | None
    failed_step: StepReference | None
    execution_statistics: ExecutionStatistics | None = None
    history_omitted: int = 0

    @property
    def executions_omitted(self) -> int:
        """Step reports evicted before the retained detail window."""
        if self.execution_statistics is None:
            return 0
        return self.execution_statistics.report_count - len(self.executions)
