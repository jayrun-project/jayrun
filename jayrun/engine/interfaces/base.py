from abc import ABC, abstractmethod
from datetime import UTC, datetime

from ..recorders.execution.recorder import ExecutionRecorder
from .context_record import ContextRecord


class ScopeInterface(ABC):
    """Publish portable context values and read retained immutable records."""

    def __init__(self, recorder: ExecutionRecorder) -> None:
        self._recorder = recorder

    def record(self, key: str, value: object) -> None:
        """Validate and detach a value before queueing it for context commitment.

        Return means queued acceptance, not committed visibility. An immediate
        records() call may still see the preceding snapshot. Capacity violations
        raise before queueing; shutdown or ownership transfer may discard pending
        requests. Recording does not acknowledge an application action.
        """
        record = ContextRecord(
            step_name=self._recorder.step_name,
            execution=self._recorder.execution,
            context_id=self._recorder.context_id,
            iteration=self._recorder.iteration,
            key=key,
            value=value,
            recorded_at=datetime.now(UTC),
            step_index=self._recorder.step_reference.step_index,
            attempt=self._recorder._attempt,
        )
        self._record(record)

    @abstractmethod
    def records(self, key: str) -> tuple[ContextRecord, ...]:
        """Return retained records in commit order; an unknown key returns ()."""
        raise NotImplementedError

    @abstractmethod
    def _record(self, record: ContextRecord) -> None:
        raise NotImplementedError
