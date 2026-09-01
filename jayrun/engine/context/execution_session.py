from dataclasses import dataclass, field

from ...core.context.runtime_data import Data
from ..execution.execution_mode import ExecutionMode
from ..recorders.execution.recorder import ExecutionRecorder
from ..recorders.execution.records import ExecutionOutcome, ExecutionReport
from ..resource.placement_request import (
    PlacementImpossible,
    PlacementRequest,
    PlacementUnavailable,
)
from .execution_state import ExecutionState
from .execution_step import ExecutionOperator, ExecutionResource, ExecutionStep
from .resource_key import ResourceKey


@dataclass(slots=True)
class ExecutionSession:
    step: ExecutionStep
    execution_mode: ExecutionMode
    recorder: ExecutionRecorder
    supervising: bool = False
    state: ExecutionState = ExecutionState.IDLE
    result: tuple[object, ...] | None = None
    report: ExecutionReport | None = None
    failure: Exception | None = None
    placement_request: PlacementRequest | None = None
    placement_requests: tuple[PlacementRequest, ...] = ()
    attempt_count: int = 0
    repeat_count: int = 0
    _resource_keys: list[ResourceKey] = field(default_factory=list, repr=False)
    _resource_registration_key: ResourceKey | None = field(
        default=None,
        repr=False,
    )
    _report_recorded: bool = field(default=False, repr=False)
    _attempt_started: bool = field(default=False, repr=False)

    def collect(
        self,
        result: tuple[object, ...] | Exception,
    ) -> None:
        if self.state is not ExecutionState.DISPATCHED:
            raise RuntimeError("only a dispatched session can collect a result")

        self.recorder.stop_internal_timer("execution_latency")

        if isinstance(result, PlacementUnavailable):
            request = result.request
            result.__traceback__ = None
            result.__context__ = None
            result.__cause__ = None
            self._wait_for_placement(request)
            return

        elif isinstance(result, PlacementImpossible):
            self._fail(result)
            return
        elif isinstance(result, Exception):
            self._fail(result)
            return

        if isinstance(self.step, ExecutionResource):
            if len(result) != 1 or not isinstance(result[0], Data):
                failure = TypeError(
                    "resource setup must return exactly one Data instance"
                )
                self._fail(failure)
                return

            normalized_result = result

        elif isinstance(self.step, ExecutionOperator):
            normalized_result = tuple(
                output if isinstance(output, Data) else Data(value=output)
                for output in result
            )

        else:
            failure = TypeError("unsupported execution step")
            self._fail(failure)
            return

        self._finish(normalized_result)

    def dispatch(self) -> None:
        if self.state is not ExecutionState.IDLE:
            raise RuntimeError("only an idle session can be dispatched")
        self.recorder.start_internal_timer("execution_latency")
        if not self._attempt_started:
            self.attempt_count += 1
            self._attempt_started = True
        self.state = ExecutionState.DISPATCHED

    def resume_placement(self, request: PlacementRequest) -> None:
        if self.state is not ExecutionState.PLACEMENT_WAITING:
            raise RuntimeError("session is not waiting for placement")
        if self.placement_request != request:
            raise ValueError("placement request does not belong to this session")
        self.step.proxy.placement._restart(request)
        self.placement_request = None
        self.state = ExecutionState.IDLE

    def restart_placements(self, request: PlacementRequest) -> None:
        if self.state is not ExecutionState.PLACEMENT_WAITING:
            raise RuntimeError("session is not waiting for placement")
        if self.placement_request != request:
            raise ValueError("placement request does not belong to this session")
        self.step.proxy.placement._clear()
        self.placement_request = None
        self.placement_requests = ()
        self.state = ExecutionState.IDLE

    def retry(self) -> None:
        if self.state is not ExecutionState.FAILED:
            raise RuntimeError("only a failed session can be retried")
        self.step.proxy.placement._clear()
        self.state = ExecutionState.IDLE
        self.result = None
        self.failure = None
        self._attempt_started = False
        self.recorder.retry()

    def repeat(self) -> None:
        if self.state is not ExecutionState.FINISHED:
            raise RuntimeError("only a finished session can be repeated")
        self.step.proxy.placement._clear()
        self.state = ExecutionState.IDLE
        self.result = None
        self.failure = None
        self.attempt_count = 0
        self._attempt_started = False
        self.repeat_count += 1
        self.recorder.repeat()
        self.step.proxy.execution._requests.reset()

    def cancel(self) -> None:
        if self.state is ExecutionState.CANCELLED:
            return
        self.step.proxy.placement._clear()
        self.placement_request = None
        self.state = ExecutionState.CANCELLED

    def finalize(self) -> None:
        if self.report is not None:
            return
        outcomes = {
            ExecutionState.FINISHED: ExecutionOutcome.FINISHED,
            ExecutionState.FAILED: ExecutionOutcome.FAILED,
            ExecutionState.CANCELLED: ExecutionOutcome.CANCELLED,
        }
        try:
            outcome = outcomes[self.state]
        except KeyError as error:
            raise RuntimeError("session has no terminal outcome") from error
        self.step.proxy.placement._clear()
        self.recorder.stop(outcome)
        self.report = self.recorder.report

    def _wait_for_placement(self, request: PlacementRequest) -> None:
        self.result = None
        self.failure = None
        self.placement_request = request
        self.state = ExecutionState.PLACEMENT_WAITING

    def _fail(self, failure: Exception) -> None:
        self.recorder.record_failure(failure)
        self.state = ExecutionState.FAILED
        self.failure = failure

    def _finish(self, result: tuple[object, ...]) -> None:
        self.placement_request = None
        self.placement_requests = self.step.proxy.placement.placement_requests
        self.state = ExecutionState.FINISHED
        self.result = result

    @property
    def placement_waiting(self) -> bool:
        return self.state is ExecutionState.PLACEMENT_WAITING

    @property
    def failed(self) -> bool:
        return self.state is ExecutionState.FAILED

    @property
    def finished(self) -> bool:
        return self.state is ExecutionState.FINISHED

    @property
    def cancelled(self) -> bool:
        return self.state is ExecutionState.CANCELLED
