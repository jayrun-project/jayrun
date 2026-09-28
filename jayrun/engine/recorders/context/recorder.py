from __future__ import annotations

from ...history_budget import _HistoryBudget

from collections import deque
from collections.abc import Callable
from functools import partial

from ...settings._instrumentation import _InstrumentationPolicy

from ..artifact.recorder import ArtifactRecorder
from ..execution.recorder import ExecutionRecorder
from ..execution.records import ExecutionOutcome, ExecutionReport
from .state import RecorderState


class ContextRecorder:
    def __init__(
        self,
        *,
        execution_recorder_type: Callable[[], ExecutionRecorder],
        artifact_recorder_type: Callable[[], ArtifactRecorder],
    ) -> None:
        self._execution_recorder_type = execution_recorder_type
        self._artifact_recorder_type = artifact_recorder_type
        self._records: deque[ExecutionReport] = deque()
        self._iteration_records: list[ExecutionReport] = []
        self._state = RecorderState.RUNNING
        self._executions: tuple[ExecutionReport, ...] | None = None
        self._history_budget: _HistoryBudget | None = None

    @classmethod
    def _for_policy(cls, policy: _InstrumentationPolicy) -> ContextRecorder:
        return cls(
            execution_recorder_type=partial(
                ExecutionRecorder,
                record_logs=policy.record_logs,
                record_metrics=policy.record_metrics,
                record_timers=policy.record_timers,
                record_failures=policy.record_failure_details,
            ),
            artifact_recorder_type=partial(
                ArtifactRecorder, keep_history=policy.keep_artifact_history,
            ),
        )

    def record(self, record: ExecutionReport) -> None:
        self._require_running()
        if self._history_budget is not None:
            self._history_budget.account()
        self._records.append(record)
        self._iteration_records.append(record)

    def restore(self, reports: tuple[ExecutionReport, ...]) -> None:
        """Restore reports committed before this local execution generation."""
        self._require_running()
        if not isinstance(reports, tuple):
            raise TypeError("reports must be a tuple")
        if any(not isinstance(report, ExecutionReport) for report in reports):
            raise TypeError("reports must contain ExecutionReport instances")
        if self._records or self._iteration_records:
            raise RuntimeError("reports can only be restored into an empty recorder")
        self._records.extend(reports)

    def record_skipped(
        self,
        *,
        step_index: int,
        step_kind: str,
        step_name: str,
        layout_position: tuple[int, int],
        context_id: int,
        iteration: int,
        reason: str,
    ) -> ExecutionReport:
        report = ExecutionReport(
            step_index=step_index,
            step_kind=step_kind,
            step_name=step_name,
            layout_position=layout_position,
            context_id=context_id,
            iteration=iteration,
            attempts=(),
            execution_count=0,
            outcome=ExecutionOutcome.SKIPPED,
            skip_reason=reason,
        )
        self.record(report)
        return report

    def complete_iteration(self, iteration: int) -> tuple[ExecutionReport, ...]:
        self._require_running()
        if type(iteration) is not int or iteration < 1:
            raise ValueError("iteration must be a positive int")
        reports = tuple(self._iteration_records)
        if any(report.iteration != iteration for report in reports):
            raise RuntimeError("iteration execution reports are inconsistent")
        self._iteration_records.clear()
        return reports

    def create_execution_recorder(self) -> ExecutionRecorder:
        self._require_running()
        recorder = self._execution_recorder_type()
        recorder._history_budget = self._history_budget
        return recorder

    def create_artifact_recorder(self) -> ArtifactRecorder:
        self._require_running()
        recorder = self._artifact_recorder_type()
        recorder._history_budget = self._history_budget
        return recorder

    def stop(self) -> None:
        if self._state is RecorderState.STOPPED:
            return
        self._executions = tuple(self._records)
        self._records.clear()
        self._iteration_records.clear()
        self._state = RecorderState.STOPPED

    @property
    def executions(self) -> tuple[ExecutionReport, ...]:
        if self._state is not RecorderState.STOPPED or self._executions is None:
            raise RuntimeError("recorder has not stopped")
        return self._executions

    def _require_running(self) -> None:
        if self._state is not RecorderState.RUNNING:
            raise RuntimeError("recorder is not running")
