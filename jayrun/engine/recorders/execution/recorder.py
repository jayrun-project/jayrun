from __future__ import annotations

from time import perf_counter

from ...context.step_reference import StepReference
from .records import (
    AttemptRecord,
    ExecutionRecord,
    ExecutionOutcome,
    ExecutionReport,
    FailureRecord,
    LogRecord,
    MetricRecord,
    RecordOrigin,
    TimerRecord,
)
from .state import RecorderState


class ExecutionRecorder:
    def __init__(
        self,
        *,
        record_logs: bool,
        record_metrics: bool,
        record_timers: bool,
        record_failures: bool,
    ) -> None:
        self._record_logs = record_logs
        self._record_metrics = record_metrics
        self._record_timers = record_timers
        self._record_failures = record_failures
        self._state = RecorderState.PENDING
        self._custom_timer_starts: dict[str, float] = {}
        self._internal_timer_starts: dict[str, float] = {}

    def initialize(
        self,
        step_name: str,
        step_kind: str,
        step_index: int,
        layout_position: tuple[int, int],
        context_id: int,
        iteration: int,
    ) -> None:
        if self._state is RecorderState.RUNNING:
            raise RuntimeError("recorder is already running")
        self._step_name = step_name
        self._step_kind = step_kind
        self._step_index = step_index
        self._layout_position = layout_position
        self._context_id = context_id
        self._iteration = iteration
        self._state = RecorderState.RUNNING
        self._execution = 1
        self._attempt = 1
        self._failure: Exception | None = None
        self._attempts: list[AttemptRecord] = []
        self._current_records: list[ExecutionRecord] = []
        self._report: ExecutionReport | None = None

    def log(self, message: str) -> None:
        self._require_running()
        if not self._record_logs:
            return
        self._current_records.append(
            LogRecord(
                message=message,
                origin=RecordOrigin.USER,
                execution=self._execution,
            )
        )

    def metric(self, name: str, value: int | float) -> None:
        self._require_running()
        if not self._record_metrics:
            return
        self._current_records.append(
            MetricRecord(
                name=name,
                value=value,
                origin=RecordOrigin.USER,
                execution=self._execution,
            )
        )

    def record_failure(
        self,
        failure: Exception,
        *,
        origin: RecordOrigin = RecordOrigin.INTERNAL,
    ) -> None:
        self._require_running()
        if self._record_failures:
            self._current_records.append(
                FailureRecord(
                    exception=failure,
                    origin=origin,
                    execution=self._execution,
                )
            )
        self._failure = failure

    def start_timer(self, name: str) -> None:
        self._require_running()
        if self._record_timers:
            self._custom_timer_starts[name] = perf_counter()

    def stop_timer(self, name: str) -> None:
        self._require_running()
        if self._record_timers:
            self._stop_timer(
                name=name,
                origin=RecordOrigin.USER,
                starts=self._custom_timer_starts,
            )

    def start_internal_timer(self, name: str) -> None:
        self._require_running()
        if self._record_timers:
            self._internal_timer_starts[name] = perf_counter()

    def stop_internal_timer(self, name: str) -> None:
        self._require_running()
        if self._record_timers:
            self._stop_timer(
                name=name,
                origin=RecordOrigin.INTERNAL,
                starts=self._internal_timer_starts,
            )

    def retry(self) -> None:
        self._require_running()
        self._finish_attempt()
        self._current_records = []
        self._failure = None
        self._attempt += 1

    def repeat(self) -> None:
        self._require_running()
        self._finish_attempt()
        self._current_records = []
        self._failure = None
        self._execution += 1
        self._attempt = 1

    def stop(self, outcome: ExecutionOutcome) -> None:
        if self._state is RecorderState.STOPPED:
            return
        self._require_running()
        self._finish_attempt()
        self._report = ExecutionReport(
            step_index=self._step_index,
            step_kind=self._step_kind,
            step_name=self._step_name,
            layout_position=self._layout_position,
            context_id=self._context_id,
            iteration=self._iteration,
            attempts=tuple(self._attempts),
            execution_count=self._execution,
            outcome=outcome,
        )
        self._current_records = []
        self._attempts = []
        self._custom_timer_starts.clear()
        self._internal_timer_starts.clear()
        self._state = RecorderState.STOPPED

    @property
    def report(self) -> ExecutionReport:
        if self._state is not RecorderState.STOPPED or self._report is None:
            raise RuntimeError("recorder has not stopped")
        return self._report

    @property
    def step_reference(self) -> StepReference:
        return StepReference(
            step_name=self._step_name,
            step_kind=self._step_kind,
            step_index=self._step_index,
            layout_position=self._layout_position,
        )

    @property
    def context_id(self) -> int:
        return self._context_id

    @property
    def execution(self) -> int:
        return self._execution

    @property
    def iteration(self) -> int:
        return self._iteration

    @property
    def step_name(self) -> str:
        return self._step_name

    @property
    def step_kind(self) -> str:
        return self._step_kind

    @property
    def layout_position(self) -> tuple[int, int]:
        return self._layout_position

    @property
    def failure(self) -> Exception | None:
        return self._failure

    def _finish_attempt(self) -> None:
        self._attempts.append(
            AttemptRecord(
                execution=self._execution,
                attempt=self._attempt,
                records=tuple(self._current_records),
            )
        )

    def _stop_timer(
        self,
        *,
        name: str,
        origin: RecordOrigin,
        starts: dict[str, float],
    ) -> None:
        start_time = starts.pop(name, None)
        if start_time is None:
            return
        self._current_records.append(
            TimerRecord(
                name=name,
                elapsed_time=perf_counter() - start_time,
                origin=origin,
                execution=self._execution,
            )
        )

    def _require_running(self) -> None:
        if self._state is not RecorderState.RUNNING:
            raise RuntimeError("recorder is not running")
