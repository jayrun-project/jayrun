from collections.abc import Hashable
from dataclasses import dataclass

from ..recorders.execution.recorder import ExecutionRecorder
from .base import ScopeInterface
from .value_record import ValueRecord


@dataclass(slots=True)
class ExecutionRequests:
    repeat_requested: bool = False

    def request_repeat(self) -> None:
        self.repeat_requested = True

    def reset(self) -> None:
        self.repeat_requested = False


class ExecutionInterface(ScopeInterface):
    """Observe and store data for the current step execution session."""

    def __init__(self, recorder: ExecutionRecorder) -> None:
        super().__init__(recorder=recorder)
        self._records: dict[Hashable, list[ValueRecord]] = {}
        self._requests = ExecutionRequests()

    def get_records(self, key: Hashable) -> tuple[ValueRecord, ...]:
        """Return execution-scoped records for ``key`` in recording order."""
        return tuple(self._records.get(key, ()))

    def _store(self, record: ValueRecord) -> None:
        self._records.setdefault(record.key, []).append(record)

    def log(self, message: str) -> None:
        """Record a text log message for the current execution."""
        self._recorder.log(message)

    def metric(self, name: str, value: float) -> None:
        """Record a numeric metric for the current execution."""
        self._recorder.metric(name, value)

    def start_timer(self, name: str) -> None:
        """Start a named wall-clock timer for the current execution."""
        self._recorder.start_timer(name)

    def stop_timer(self, name: str) -> None:
        """Stop a named timer and record its elapsed duration."""
        self._recorder.stop_timer(name)


class OperatorExecutionInterface(ExecutionInterface):
    """Execution interface extended with operator repetition controls."""

    def repeat(self) -> None:
        """Request another execution after the current invocation returns.

        The context's ``max_repeats`` setting remains authoritative.
        """
        self._requests.request_repeat()

    @property
    def number(self) -> int:
        """Zero-based execution number within the current operator session."""
        return self._recorder.execution


class ResourceExecutionInterface(ExecutionInterface):
    pass
