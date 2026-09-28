from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import replace
from threading import RLock
from typing import TYPE_CHECKING

from ..context_record import ContextRecord, _freeze_value, _validate_key

if TYPE_CHECKING:
    from ...settings.combined_context import CombinedContextSettings
    from ...settings.context import ContextSettings


class ContextRecordRepository:
    """One context's committed records and bounded, unpublished reservations."""

    def __init__(
        self, settings: CombinedContextSettings | ContextSettings, context_id: int,
    ) -> None:
        self._settings = settings
        self._context_id = context_id
        self._records: dict[str, deque[ContextRecord]] = {}
        self._record_snapshots: dict[str, tuple[ContextRecord, ...]] = {}
        self._sizes: dict[int, int] = {}
        self._pending: dict[int, tuple[ContextRecord, int]] = {}
        self._pending_bytes = 0
        self._pending_keys: dict[str, int] = {}
        self._total_bytes = 0
        self._sequence = 0
        self._snapshot: tuple[ContextRecord, ...] | None = ()
        self._lock = RLock()
        self._closed = False

    def enqueue(self, record: ContextRecord, submit: Callable[[], None]) -> None:
        _, size = _freeze_value(record.value, max_bytes=self._settings.record_max_value_bytes)
        with self._lock:
            if self._closed:
                raise RuntimeError("context record repository is closed")
            if record.sequence != 0 or record.context_id != self._context_id:
                raise ValueError("record request identity is invalid")
            keys = self._records.keys() | self._pending_keys.keys() | {record.key}
            if len(keys) > self._settings.record_max_keys:
                raise ValueError("record key limit exceeded")
            # Conservatively reserve in-flight values; no accepted request relies
            # on a future prune to fit the declared total budget.
            if self._total_bytes + self._pending_bytes + size > self._settings.record_max_total_bytes:
                raise ValueError("record total byte limit exceeded")
            self._release_pending(record)
            self._pending[id(record)] = (record, size)
            self._pending_bytes += size
            self._pending_keys[record.key] = self._pending_keys.get(record.key, 0) + 1
            try:
                submit()
            except BaseException:
                self._release_pending(record)
                raise

    def discard(self, record: ContextRecord) -> None:
        with self._lock:
            self._release_pending(record)

    def _release_pending(self, record: ContextRecord) -> None:
        # Called only while holding _lock, including reentrant submit callbacks.
        pending = self._pending.pop(id(record), None)
        if pending is not None:
            reserved, size = pending
            self._pending_bytes -= size
            count = self._pending_keys[reserved.key] - 1
            if count:
                self._pending_keys[reserved.key] = count
            else:
                del self._pending_keys[reserved.key]

    def commit(self, record: ContextRecord) -> ContextRecord:
        with self._lock:
            pending, size = self._pending[id(record)]
            if pending is not record:
                raise ValueError("record request is not owned by this context")
            committed = replace(record, sequence=self._sequence + 1)
            records = self._records.get(record.key)
            if records is None:
                records = self._records[record.key] = deque()
            records.append(committed)
            limit = self._settings.record_history_limit
            while limit is not None and len(records) > limit:
                old = records.popleft()
                self._total_bytes -= self._sizes.pop(old.sequence)
            self._record_snapshots.pop(record.key, None)
            self._sizes[committed.sequence] = size
            self._total_bytes += size
            self._sequence = committed.sequence
            self._snapshot = None
            self._release_pending(record)
            return committed

    def records(self, key: str) -> tuple[ContextRecord, ...]:
        _validate_key(key)
        with self._lock:
            records = self._records.get(key)
            if records is None:
                return ()
            snapshot = self._record_snapshots.get(key)
            if snapshot is None:
                snapshot = self._record_snapshots[key] = tuple(records)
            return snapshot

    @property
    def sequence(self) -> int:
        with self._lock:
            return self._sequence

    @property
    def snapshot(self) -> tuple[ContextRecord, ...]:
        with self._lock:
            if self._snapshot is None:
                self._snapshot = tuple(sorted(
                    (r for values in self._records.values() for r in values),
                    key=lambda r: r.sequence,
                ))
            return self._snapshot

    def _history_snapshot(self, *, max_items: int, max_bytes: int) -> tuple[tuple[ContextRecord, ...], int]:
        """Bound a durable handoff before materializing the retained reference tuple."""
        with self._lock:
            if len(self._sizes) > max_items or self._total_bytes > max_bytes:
                raise ValueError("retained records exceed the durable capture allowance")
            return self.snapshot, self._sequence

    def replace(self, records: tuple[ContextRecord, ...], sequence: int) -> None:
        grouped, sizes = self.validate_snapshot(records, sequence)
        with self._lock:
            self._records = grouped
            self._record_snapshots.clear()
            self._sizes = sizes
            self._total_bytes = sum(sizes.values())
            self._sequence = sequence
            self._snapshot = records
            self._pending.clear()
            self._pending_bytes = 0
            self._pending_keys.clear()

    def validate_snapshot(
        self, records: tuple[ContextRecord, ...], sequence: int,
    ) -> tuple[dict[str, deque[ContextRecord]], dict[int, int]]:
        if type(sequence) is not int or sequence < 0 or not isinstance(records, tuple):
            raise ValueError("invalid record sequence or collection")
        grouped: dict[str, deque[ContextRecord]] = {}
        sizes: dict[int, int] = {}
        previous = 0
        for record in records:
            if not isinstance(record, ContextRecord) or record.context_id != self._context_id:
                raise ValueError("snapshot record identity is invalid")
            if not previous < record.sequence <= sequence:
                raise ValueError("snapshot record sequences must be ordered and unique")
            previous = record.sequence
            _, size = _freeze_value(record.value, max_bytes=self._settings.record_max_value_bytes)
            values = grouped.get(record.key)
            if values is None:
                values = grouped[record.key] = deque()
            values.append(record)
            sizes[record.sequence] = size
        if (sequence > 0 and previous != sequence) or (sequence == 0 and records):
            raise ValueError("snapshot must retain its latest record")
        limit = self._settings.record_history_limit
        required = sequence if limit is None else min(sequence, limit)
        if len(records) < required or any(
            record.sequence != sequence - required + index + 1
            for index, record in enumerate(records[len(records) - required:])
        ):
            raise ValueError("snapshot is missing records required by retention")
        if len(grouped) > self._settings.record_max_keys:
            raise ValueError("snapshot record key limit exceeded")
        if self._settings.record_history_limit is not None and any(
            len(values) > self._settings.record_history_limit for values in grouped.values()
        ):
            raise ValueError("snapshot record retention limit exceeded")
        if sum(sizes.values()) > self._settings.record_max_total_bytes:
            raise ValueError("snapshot record total byte limit exceeded")
        return grouped, sizes

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._pending.clear()
            self._pending_bytes = 0
            self._pending_keys.clear()
