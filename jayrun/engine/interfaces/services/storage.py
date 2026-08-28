from collections.abc import Hashable
from threading import Lock

from ..value_record import ValueRecord


class StoredValueRepository:
    def __init__(self) -> None:
        self._records: dict[Hashable, list[ValueRecord]] = {}
        self._lock = Lock()

    def store(self, record: ValueRecord) -> None:
        with self._lock:
            self._records.setdefault(record.key, []).append(record)

    def get_records(self, key: Hashable) -> tuple[ValueRecord, ...]:
        with self._lock:
            return tuple(self._records.get(key, ()))

    def remove_context(self, context_id: int) -> None:
        with self._lock:
            for key, records in tuple(self._records.items()):
                remaining = [
                    record for record in records if record.context_id != context_id
                ]
                if remaining:
                    self._records[key] = remaining
                else:
                    del self._records[key]
