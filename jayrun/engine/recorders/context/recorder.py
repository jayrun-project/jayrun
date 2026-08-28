from __future__ import annotations

from collections import deque

from ..artifact.recorder import ArtifactRecorder
from ..execution.recorder import ExecutionRecorder
from ..execution.records import ExecutionOutcome, ExecutionReport
from .report import ContextReport
from .state import RecorderState


class ContextRecorder:
    def __init__(
        self,
        *,
        execution_recorder_type: type[ExecutionRecorder],
        artifact_recorder_type: type[ArtifactRecorder],
    ) -> None:
        self._execution_recorder_type = execution_recorder_type
        self._artifact_recorder_type = artifact_recorder_type
        self._records: deque[ExecutionReport] = deque()
        self._state = RecorderState.RUNNING
        self._report: ContextReport | None = None

    def record(self, record: ExecutionReport) -> None:
        self._require_running()
        self._records.append(record)

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
    ) -> None:
        self.record(
            ExecutionReport(
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
        )

    def create_execution_recorder(self) -> ExecutionRecorder:
        self._require_running()
        return self._execution_recorder_type()

    def create_artifact_recorder(self) -> ArtifactRecorder:
        self._require_running()
        return self._artifact_recorder_type()

    def stop(self) -> None:
        if self._state is RecorderState.STOPPED:
            return
        self._report = ContextReport(executions=tuple(self._records))
        self._records.clear()
        self._state = RecorderState.STOPPED

    @property
    def report(self) -> ContextReport:
        if self._state is not RecorderState.STOPPED or self._report is None:
            raise RuntimeError("recorder has not stopped")
        return self._report

    def _require_running(self) -> None:
        if self._state is not RecorderState.RUNNING:
            raise RuntimeError("recorder is not running")
