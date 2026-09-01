from abc import ABC, abstractmethod
from collections.abc import Hashable
from datetime import UTC, datetime

from ..recorders.execution.recorder import ExecutionRecorder
from .value_record import ValueRecord


class ScopeInterface(ABC):
    """Store and retrieve values within the current context.

    Keys must be hashable. Each store operation creates an immutable
    :class:`ValueRecord`; convenience getters expose either the latest value or the
    complete ordered history for a key.
    """

    def __init__(self, recorder: ExecutionRecorder) -> None:
        self._recorder = recorder

    def store(self, key: Hashable, value: object) -> None:
        """Append a value record under ``key`` in this scope."""
        hash(key)
        record = ValueRecord(
            step_name=self._recorder.step_name,
            execution=self._recorder.execution,
            context_id=self._recorder.context_id,
            iteration=self._recorder.iteration,
            key=key,
            value=value,
            recorded_at=datetime.now(UTC),
        )
        self._store(record)

    def has_value(self, key: Hashable) -> bool:
        """Return whether this scope contains at least one record for ``key``."""
        return self.get_value_record(key) is not None

    def get_value(self, key: Hashable) -> object | None:
        """Return the most recently stored value for ``key``, or ``None``."""
        record = self.get_value_record(key)
        return None if record is None else record.value

    def get_values(self, key: Hashable) -> tuple[object, ...]:
        """Return all values stored for ``key`` in recording order."""
        return tuple(record.value for record in self.get_value_records(key))

    def get_value_record(self, key: Hashable) -> ValueRecord | None:
        """Return the most recent full record for ``key``, or ``None``."""
        records = self.get_value_records(key)
        return None if not records else records[-1]

    @abstractmethod
    def get_value_records(self, key: Hashable) -> tuple[ValueRecord, ...]:
        """Return all full records for ``key`` in recording order."""
        raise NotImplementedError

    @abstractmethod
    def _store(self, record: ValueRecord) -> None:
        raise NotImplementedError
